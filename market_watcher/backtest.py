from __future__ import annotations

from typing import Any

import pandas as pd

from market_watcher.indicators import calculate_indicators
from market_watcher.scoring import score_candidate


def evaluate_signals(
    histories: dict[str, pd.DataFrame],
    benchmark_ticker: str,
    scoring: dict[str, Any] | None = None,
    *,
    holding_sessions: int = 20,
    fee_bps: float = 5,
    slippage_bps: float = 5,
    rebalance_every: int = 5,
) -> dict[str, Any]:
    """Evaluate BUY signals at close; enter next open and exit at a later close."""
    benchmark = histories.get(benchmark_ticker)
    if benchmark is None or benchmark.empty:
        return {"trades": [], "message": "Benchmark history is unavailable."}
    cost = 2 * (fee_bps + slippage_bps) / 10_000
    trades: list[dict[str, Any]] = []
    for ticker, history in histories.items():
        if ticker == benchmark_ticker or not {"Open", "Close"}.issubset(history.columns):
            continue
        prices = history.sort_index()
        shared_dates = prices.index.intersection(benchmark.index)
        last_exit_index = -1
        for signal_index in range(200, len(shared_dates) - holding_sessions, max(1, rebalance_every)):
            if signal_index <= last_exit_index:
                continue
            signal_date = shared_dates[signal_index]
            known_prices = prices.loc[:signal_date]
            known_benchmark = benchmark.loc[:signal_date]
            if known_prices.empty or known_benchmark.empty:
                continue
            indicators = calculate_indicators(known_prices, known_benchmark)
            scored = score_candidate(indicators, scoring)
            if scored["signal"] != "BUY":
                continue
            entry_index = signal_index + 1
            exit_index = entry_index + holding_sessions - 1
            entry_date = shared_dates[entry_index]
            exit_date = shared_dates[exit_index]
            entry_price = float(prices.loc[entry_date, "Open"])
            exit_price = float(prices.loc[exit_date, "Close"])
            if pd.isna(entry_price) or pd.isna(exit_price) or entry_price <= 0:
                continue
            gross_return = exit_price / entry_price - 1 if entry_price else 0.0
            trades.append(
                {
                    "ticker": ticker,
                    "signal_date": pd.Timestamp(signal_date).isoformat(),
                    "entry_date": pd.Timestamp(entry_date).isoformat(),
                    "exit_date": pd.Timestamp(exit_date).isoformat(),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "score": scored["score"],
                    "gross_return": gross_return,
                    "estimated_cost": cost,
                    "net_return": gross_return - cost,
                }
            )
            last_exit_index = exit_index
    return {
        "trades": trades,
        "assumptions": {
            "signal": "Computed at session close from data available through that close only.",
            "entry": "Next session open.",
            "exit": f"Close after {holding_sessions} holding sessions.",
            "fees_bps_per_side": fee_bps,
            "slippage_bps_per_side": slippage_bps,
            "lookahead_safeguard": "Indicator inputs are sliced at each signal date; future prices are used only for trade outcomes.",
            "survivorship_bias": "A universe based on today's S&P 500 constituents has survivorship bias in historical evaluation.",
        },
    }
