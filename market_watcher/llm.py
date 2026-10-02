"""Optional local LLM explanations via Ollama's /api/chat endpoint.

The LLM never produces signals or scores. It only rewrites already-calculated
evidence, risks and missing information into plain language. Any failure here
is non-fatal for the scanner.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from .config import OllamaConfig

SYSTEM_PROMPT = """You are a cautious equity research assistant.
Explain ONLY the JSON evidence you are given. Rules:
- Use only the numbers and facts in the JSON. Do not invent news, earnings,
  fundamentals, analyst opinions, price targets or fund/institutional flow data.
- Price/volume indicators (relative volume, OBV, Chaikin Money Flow) are PROXIES
  for buying or selling pressure, not verified institutional money flows. Say so.
- The label (BUY / WATCH / SELL/AVOID) is a research-candidate label from a
  rules-based score, not a trade instruction. Do not tell the user to trade.
- If data is stale, missing or simulated, state this clearly.
Respond in plain text with four short sections:
Summary, Evidence, Risks, Missing information. Maximum 180 words."""

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaError(RuntimeError):
    """Ollama returned an error or an unusable response."""


class OllamaUnavailable(OllamaError):
    """Ollama could not be reached at all (stop trying for this scan)."""


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_round(x) for x in v]
    return v


def build_evidence_payload(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "ticker",
        "label",
        "score",
        "rank",
        "metrics",
        "evidence",
        "risks",
        "missing",
        "warnings",
        "last_bar",
        "stale",
        "simulated",
        "source",
    )
    payload = {k: result.get(k) for k in keys}
    payload["signal_type"] = "price/volume proxy for buying pressure (not verified flows)"
    return _round(payload)


def build_messages(result: dict[str, Any]) -> list[dict[str, str]]:
    evidence = json.dumps(build_evidence_payload(result), indent=1, default=str)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Explain this calculated evidence:\n{evidence}"},
    ]


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


class OllamaClient:
    def __init__(self, cfg: OllamaConfig, session: requests.Session | None = None):
        if not cfg.base_url.startswith(("http://", "https://")):
            raise ValueError("ollama.base_url must start with http:// or https://")
        self.cfg = cfg
        self.base_url = cfg.base_url.rstrip("/")
        self.session = session or requests.Session()

    def chat(self, messages: list[dict[str, str]]) -> str:
        body = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": self.cfg.temperature},
        }
        url = f"{self.base_url}/api/chat"
        try:
            resp = self.session.post(url, json=body, timeout=self.cfg.timeout_seconds)
        except requests.ConnectionError as exc:
            raise OllamaUnavailable(f"Ollama unreachable at {self.base_url}: {exc}") from exc
        except requests.Timeout as exc:
            raise OllamaError(f"Ollama timed out after {self.cfg.timeout_seconds}s") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc
        if resp.status_code != 200:
            detail = resp.text[:300]
            raise OllamaError(f"Ollama HTTP {resp.status_code}: {detail}")
        try:
            data = resp.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaError("Ollama returned an unexpected response shape") from exc
        if not isinstance(content, str):
            raise OllamaError("Ollama returned non-text content")
        text = strip_thinking(content)
        if not text:
            raise OllamaError("Ollama returned an empty answer")
        return text

    def explain(self, result: dict[str, Any]) -> str:
        return self.chat(build_messages(result))

    def check(self) -> tuple[bool, str]:
        """Check the server is reachable and the model is pulled."""
        try:
            resp = self.session.get(f"{self.base_url}/api/tags", timeout=5)
        except requests.RequestException as exc:
            return False, f"cannot reach Ollama at {self.base_url}: {exc}"
        if resp.status_code != 200:
            return False, f"Ollama HTTP {resp.status_code} on /api/tags"
        try:
            names = [m.get("name", "") for m in resp.json().get("models", [])]
        except (ValueError, AttributeError):
            return False, "unexpected /api/tags response"
        want = self.cfg.model
        if not any(n == want or n == f"{want}:latest" for n in names):
            return False, (
                f"Ollama is running but model '{want}' is not pulled "
                f"(run: ollama pull {want}). Available: {', '.join(names) or 'none'}"
            )
        return True, f"Ollama reachable at {self.base_url}; model '{want}' available"
