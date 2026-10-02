from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from market_watcher.config import AppConfig
from market_watcher.indicators import calculate_indicators
from market_watcher.scoring import score_candidate


def scan_market(
    config: AppConfig,
    provider: Any,
    *,
    demo: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    universe, sectors = _universe(config, demo=demo)
    benchmark = str(config.universe.get("benchmark", "SPY")).upper()
    tickers = list(dict.fromkeys([*universe, benchmark]))
    period = str(config.data.get("period", "2y"))
    histories = provider.fetch_history(tickers, period)
    current = now or datetime.now(timezone.utc)
    benchmark_data = histories.get(benchmark)
    stale_after = int(config.data.get("stale_after_days", 7))
    rows = []
    errors = dict(getattr(provider, "errors", {}))

    for ticker in universe:
        history = histories.get(ticker)
        if history is None or history.empty:
            rows.append(
                _unavailable(
                    ticker,
                    sectors.get(ticker, "Unclassified"),
                    errors.get(ticker, errors.get("*", "No data returned.")),
                )
            )
            continue
        history = history.sort_index()
        if not {"Close", "Volume"}.issubset(history.columns):
            rows.append(
                _unavailable(
                    ticker,
                    sectors.get(ticker, "Unclassified"),
                    "Price history is missing required Close or Volume columns.",
                )
            )
            continue
        observed = pd.Timestamp(history.index[-1])
        observed_date = observed.date()
        age_days = max(0, (current.date() - observed_date).days)
        if age_days > stale_after:
            rows.append(
                _unavailable(
                    ticker,
                    sectors.get(ticker, "Unclassified"),
                    f"Last quote is stale ({observed_date.isoformat()}, {age_days} calendar days old).",
                    as_of=observed_date.isoformat(),
                )
            )
            continue
        indicators = calculate_indicators(history, benchmark_data)
        scored = score_candidate(indicators, config.scoring)
        rows.append(
            {
                "ticker": ticker,
                "sector": sectors.get(ticker, "Unclassified"),
                "status": "ok",
                **indicators,
                **scored,
                "data_timestamp": observed.isoformat(),
                "data_source": "demo" if demo else "live",
                "pressure_label": "Buying-pressure proxy; not confirmed institutional inflows.",
            }
        )
    rows.sort(key=lambda row: (row["status"] == "ok", row.get("score", -1)), reverse=True)
    return {
        "scan_id": None,
        "created_at": current.isoformat(),
        "data_source": "demo" if demo else "live",
        "benchmark": benchmark,
        "universe_size": len(universe),
        "candidates": rows,
        "provider_errors": errors,
        "optional_evidence": {
            name: "unavailable until a provider is connected"
            for name in ("ETF net flows", "SEC disclosures", "options flow", "news")
        },
        "limitations": [
            "Price and volume indicators are buying-pressure proxies, not verified institutional flows.",
            "ETF flows, SEC disclosures, options flow, and news are unavailable without connected providers.",
            "Scores are heuristic research rankings, not probabilities of profit.",
        ],
    }


def _universe(config: AppConfig, *, demo: bool) -> tuple[list[str], dict[str, str]]:
    from market_watcher.config import resolve_universe

    return resolve_universe(config, demo=demo)


def _unavailable(ticker: str, sector: str, message: str, as_of: str | None = None) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "sector": sector,
        "status": "unavailable",
        "error": message,
        "as_of": as_of,
        "score": None,
        "signal": "SELL/AVOID",
        "coverage": 0,
        "factors": {},
        "missing_factors": ["price_history"],
        "data_source": None,
    }
