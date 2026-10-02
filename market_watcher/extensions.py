from __future__ import annotations

from typing import Any, Protocol


class EvidenceProvider(Protocol):
    """Extension point for evidence that cannot be inferred from prices and volume."""

    name: str

    def fetch(self, ticker: str) -> dict[str, Any]: ...


class UnavailableEvidenceProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def fetch(self, ticker: str) -> dict[str, Any]:
        del ticker
        return {"status": "unavailable", "provider": self.name, "evidence": None}


OPTIONAL_EVIDENCE_PROVIDERS = {
    "etf_net_flows": UnavailableEvidenceProvider("ETF net flows"),
    "sec_disclosures": UnavailableEvidenceProvider("SEC disclosures"),
    "options_flow": UnavailableEvidenceProvider("Options flow"),
    "news": UnavailableEvidenceProvider("News"),
}
