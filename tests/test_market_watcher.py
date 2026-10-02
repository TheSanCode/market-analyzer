from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_watcher.backtest import evaluate_signals
from market_watcher.config import AppConfig, _SP500TableParser
from market_watcher.extensions import OPTIONAL_EVIDENCE_PROVIDERS
from market_watcher.indicators import calculate_indicators
from market_watcher.ollama import explain_with_ollama
from market_watcher.providers import DemoProvider
from market_watcher.scanner import scan_market
from market_watcher.scoring import score_candidate
from market_watcher.storage import list_scans, load_scan, save_scan


def price_history(length: int = 240, *, start: datetime | None = None) -> pd.DataFrame:
    dates = pd.bdate_range(end=start or datetime(2026, 10, 1), periods=length)
    close = pd.Series([100 + index * 0.25 for index in range(length)], index=dates)
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": [100.0] * length,
        },
        index=dates,
    )


def test_indicator_windows_compare_recent_volume_to_prior_twenty_sessions() -> None:
    history = price_history()
    history.iloc[200:220, history.columns.get_loc("Volume")] = 100
    history.iloc[220:240, history.columns.get_loc("Volume")] = 200
    result = calculate_indicators(history, history)

    assert result["rvol_20"] == 2
    assert result["return_20"] == history["Close"].iloc[-1] / history["Close"].iloc[-21] - 1
    assert result["relative_20"] == 0
    assert result["sma_200"] is not None
    assert result["rsi_14"] == 100
    assert result["atr_14"] is not None
    assert result["obv"] is not None
    assert result["cmf_20"] is not None
    scored = score_candidate(result)
    assert abs(
        sum(
            factor["contribution"] or 0
            for factor in scored["factors"].values()
        )
        - scored["score"]
    ) < 0.02


def test_missing_history_produces_missing_indicators_and_avoid_signal() -> None:
    short_history = price_history(35)
    result = calculate_indicators(short_history)
    score = score_candidate(result)

    assert result["rvol_20"] is None
    assert result["sma_200"] is None
    assert score["signal"] == "SELL/AVOID"
    assert "sma_200" in score["missing_factors"]


def test_scan_marks_stale_quote_unavailable() -> None:
    history = price_history(220, start=datetime(2026, 9, 1))
    config = AppConfig(
        values={
            "universe": {"stocks": ["TEST"], "sector_etfs": {}, "benchmark": "SPY"},
            "data": {"period": "2y", "stale_after_days": 7},
            "scoring": {},
        },
        path=Path("config.yaml"),
    )

    class Provider:
        errors = {}

        def fetch_history(self, tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
            del period
            return {ticker: history for ticker in tickers}

    result = scan_market(
        config,
        Provider(),
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    stale_candidate = next(row for row in result["candidates"] if row["ticker"] == "TEST")
    assert stale_candidate["status"] == "unavailable"
    assert "stale" in stale_candidate["error"]


def test_demo_data_and_optional_providers_are_explicit() -> None:
    histories = DemoProvider().fetch_history(["AAPL", "UNKNOWN"])
    assert "AAPL" in histories
    assert histories["AAPL"].shape[0] >= 200
    assert "UNKNOWN" not in histories
    assert all(provider.fetch("SPY")["status"] == "unavailable" for provider in OPTIONAL_EVIDENCE_PROVIDERS.values())


def test_sp500_table_parser_extracts_constituent_sector() -> None:
    parser = _SP500TableParser()
    parser.feed(
        '<table class="wikitable sortable"><tr><th>Symbol</th><th>Name</th>'
        '<th>GICS Sector</th></tr><tr><td>BRK.B[1]</td><td>Example</td>'
        '<td>Financials</td></tr></table>'
    )

    assert parser.constituents() == {"BRK-B": "Financials"}


def test_ollama_unavailability_does_not_raise(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        raise ConnectionError("not running")

    monkeypatch.setattr("market_watcher.ollama.urlopen", unavailable)
    result = explain_with_ollama({"ticker": "AAPL", "score": 70}, timeout=0.01)

    assert result["status"] == "unavailable"
    assert "not running" in result["text"]


def test_backtest_enters_next_session_and_applies_costs() -> None:
    history = price_history(260)
    histories = {"TEST": history, "SPY": history}
    result = evaluate_signals(
        histories,
        "SPY",
        {"minimum_factor_coverage": 0, "buy_threshold": 0},
        holding_sessions=20,
        fee_bps=5,
        slippage_bps=10,
    )

    trade = result["trades"][0]
    signal_index = history.index.get_loc(pd.Timestamp(trade["signal_date"]))
    assert pd.Timestamp(trade["entry_date"]) == history.index[signal_index + 1]
    assert trade["entry_price"] == history["Open"].iloc[signal_index + 1]
    assert trade["estimated_cost"] == 0.003
    assert trade["net_return"] < trade["gross_return"]
    assert "only" in result["assumptions"]["lookahead_safeguard"]


def test_scans_round_trip_through_sqlite(tmp_path) -> None:
    scan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "demo",
        "candidates": [{"ticker": "AAPL", "score": 77}],
    }
    database = tmp_path / "test.sqlite"
    scan_id = save_scan(database, scan)

    assert list_scans(database)[0]["scan_id"] == scan_id
    assert load_scan(database, scan_id)["candidates"][0]["ticker"] == "AAPL"
