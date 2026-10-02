from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen
from typing import Any


def explain_with_ollama(
    candidate: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    timeout: float = 12,
) -> dict[str, str]:
    """Request an evidence-only explanation; a failure never changes its score."""
    settings = settings or {}
    endpoint = str(settings.get("endpoint", "http://localhost:11434"))
    model = str(settings.get("model", "qwen3:8b"))
    evidence = {
        "ticker": candidate.get("ticker"),
        "signal": candidate.get("signal"),
        "score": candidate.get("score"),
        "factors": candidate.get("factors", {}),
        "missing_factors": candidate.get("missing_factors", []),
        "indicators": {
            key: candidate.get(key)
            for key in (
                "return_20",
                "return_60",
                "relative_20",
                "relative_60",
                "rvol_20",
                "rsi_14",
                "atr_14",
                "obv",
                "cmf_20",
                "sma_50",
                "sma_200",
            )
        },
    }
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Explain only the supplied calculated evidence in concise strengths, risks, "
                    "and missing-data bullets. Do not add news, ETF flows, institutional activity, "
                    "or other facts. State that technical price/volume indicators are proxies."
                ),
            },
            {"role": "user", "content": json.dumps(evidence, allow_nan=False)},
        ],
    }
    request = Request(
        endpoint.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
            raise ValueError("Ollama returned an unexpected response.")
        content = result["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned no explanation.")
        return {"status": "available", "model": model, "text": content.strip()}
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "model": model, "text": f"Ollama unavailable: {exc}"}
