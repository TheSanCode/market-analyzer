"""Ollama integration tests. All HTTP traffic is mocked; no server is needed."""

import json

import pytest
import requests

from market_watcher.config import OllamaConfig
from market_watcher.llm import (
    OllamaClient,
    OllamaError,
    OllamaUnavailable,
    build_messages,
    strip_thinking,
)


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, post=None, get=None):
        self._post = post
        self._get = get
        self.posted = []

    def post(self, url, json=None, timeout=None):
        self.posted.append((url, json, timeout))
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    def get(self, url, timeout=None):
        if isinstance(self._get, Exception):
            raise self._get
        return self._get


RESULT = {
    "ticker": "DEMO-ACCUM",
    "label": "BUY",
    "score": 97.4,
    "rank": 1,
    "metrics": {"rvol": 3.2, "cmf": 0.405123456},
    "evidence": [],
    "risks": [],
    "missing": ["SMA200 unavailable"],
    "warnings": [],
    "last_bar": "2026-02-25",
    "stale": False,
    "simulated": True,
    "source": "demo (SIMULATED)",
}


def test_chat_request_shape_and_think_stripping():
    sess = FakeSession(
        post=FakeResponse(
            payload={
                "message": {"role": "assistant", "content": "<think>internal</think>\nSummary: ok"}
            }
        )
    )
    client = OllamaClient(OllamaConfig(), session=sess)
    assert client.explain(RESULT) == "Summary: ok"
    url, body, timeout = sess.posted[0]
    assert url == "http://localhost:11434/api/chat"
    assert body["model"] == "qwen3:8b"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert "DEMO-ACCUM" in body["messages"][1]["content"]
    assert timeout == OllamaConfig().timeout_seconds


def test_prompt_forbids_fabrication_and_marks_proxies():
    msgs = build_messages(RESULT)
    system = msgs[0]["content"]
    assert "Do not invent news" in system
    assert "PROXIES" in system
    user = msgs[1]["content"]
    assert "0.4051" in user  # floats rounded
    assert "not verified flows" in user
    assert '"simulated": true' in user


def test_connection_error_is_unavailable():
    sess = FakeSession(post=requests.ConnectionError("refused"))
    with pytest.raises(OllamaUnavailable):
        OllamaClient(OllamaConfig(), session=sess).explain(RESULT)


def test_timeout_http_error_and_bad_payloads():
    cfg = OllamaConfig()
    with pytest.raises(OllamaError, match="timed out"):
        OllamaClient(cfg, FakeSession(post=requests.Timeout())).explain(RESULT)
    with pytest.raises(OllamaError, match="HTTP 404"):
        OllamaClient(cfg, FakeSession(post=FakeResponse(404, text="model not found"))).explain(
            RESULT
        )
    with pytest.raises(OllamaError, match="unexpected response"):
        OllamaClient(cfg, FakeSession(post=FakeResponse(200, payload={"x": 1}))).explain(RESULT)
    with pytest.raises(OllamaError, match="unexpected response"):
        OllamaClient(cfg, FakeSession(post=FakeResponse(200, None, "garbage"))).explain(RESULT)
    empty = FakeResponse(payload={"message": {"content": "<think>x</think>"}})
    with pytest.raises(OllamaError, match="empty"):
        OllamaClient(cfg, FakeSession(post=empty)).explain(RESULT)


def test_check_reports_model_presence():
    ok = FakeSession(get=FakeResponse(payload={"models": [{"name": "qwen3:8b"}]}))
    assert OllamaClient(OllamaConfig(), ok).check()[0] is True
    missing = FakeSession(get=FakeResponse(payload={"models": [{"name": "llama3:8b"}]}))
    good, msg = OllamaClient(OllamaConfig(), missing).check()
    assert not good and "ollama pull qwen3:8b" in msg
    down = FakeSession(get=requests.ConnectionError("refused"))
    assert OllamaClient(OllamaConfig(), down).check()[0] is False


def test_invalid_base_url_rejected():
    with pytest.raises(ValueError):
        OllamaClient(OllamaConfig(base_url="file:///etc/passwd"))


def test_strip_thinking():
    assert strip_thinking("<THINK>a\nb</THINK> hi ") == "hi"


def test_scan_stops_calling_unreachable_ollama():
    from market_watcher.cli import apply_demo
    from market_watcher.config import AppConfig
    from market_watcher.data import DemoProvider
    from market_watcher.scanner import run_scan

    sess = FakeSession(post=requests.ConnectionError("refused"))
    client = OllamaClient(OllamaConfig(), session=sess)
    cfg = apply_demo(AppConfig())
    scan = run_scan(cfg, DemoProvider(), client)
    assert len(sess.posted) == 1  # gave up after first unreachable error
    assert len(scan.ok) >= 5
    assert all(r.explanation is None for r in scan.results)


def test_scan_with_mocked_ollama_attaches_explanations():
    from market_watcher.cli import apply_demo
    from market_watcher.config import AppConfig
    from market_watcher.data import DemoProvider
    from market_watcher.scanner import run_scan

    reply = FakeResponse(payload={"message": {"content": "Summary: calculated evidence only."}})
    sess = FakeSession(post=reply)
    cfg = apply_demo(AppConfig())
    cfg.ollama.explain_top_n = 2
    scan = run_scan(cfg, DemoProvider(), OllamaClient(cfg.ollama, sess))
    explained = [r for r in scan.results if r.explanation]
    assert len(explained) == 2
    assert explained[0].rank == 1
