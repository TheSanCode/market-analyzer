from __future__ import annotations

import math
from typing import Any

import pandas as pd


def calculate_indicators(
    history: pd.DataFrame, benchmark: pd.DataFrame | None = None
) -> dict[str, Any]:
    """Calculate daily technical measures using the supplied history only."""
    if history.empty or "Close" not in history or "Volume" not in history:
        return {}
    prices = history.sort_index().copy()
    close = pd.to_numeric(prices["Close"], errors="coerce")
    volume = pd.to_numeric(prices["Volume"], errors="coerce")
    recent_volume = _last(volume.rolling(20, min_periods=20).mean())
    prior_volume = _last(volume.shift(20).rolling(20, min_periods=20).mean())
    result: dict[str, Any] = {
        "as_of": prices.index[-1],
        "close": _last(close),
        "volume": _last(volume),
        "return_20": _return(close, 20),
        "return_60": _return(close, 60),
        "rvol_20": recent_volume / prior_volume if recent_volume is not None and prior_volume else None,
        "sma_50": _last(close.rolling(50, min_periods=50).mean()),
        "sma_200": _last(close.rolling(200, min_periods=200).mean()),
        "rsi_14": _rsi(close),
        "atr_14": _atr(prices),
        "obv": _obv(close, volume),
        "cmf_20": _cmf(prices, volume),
        "benchmark_return_20": None,
        "benchmark_return_60": None,
        "relative_20": None,
        "relative_60": None,
    }
    if benchmark is not None and not benchmark.empty and "Close" in benchmark:
        benchmark_close = pd.to_numeric(benchmark["Close"], errors="coerce").sort_index()
        result["benchmark_return_20"] = _return(benchmark_close, 20)
        result["benchmark_return_60"] = _return(benchmark_close, 60)
        if result["return_20"] is not None and result["benchmark_return_20"] is not None:
            result["relative_20"] = result["return_20"] - result["benchmark_return_20"]
        if result["return_60"] is not None and result["benchmark_return_60"] is not None:
            result["relative_60"] = result["return_60"] - result["benchmark_return_60"]
    return {key: _clean(value) for key, value in result.items()}


def _last(series: pd.Series) -> float | None:
    if series.empty or pd.isna(series.iloc[-1]):
        return None
    return float(series.iloc[-1])


def _return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions or pd.isna(close.iloc[-1]) or pd.isna(close.iloc[-sessions - 1]):
        return None
    previous = float(close.iloc[-sessions - 1])
    return float(close.iloc[-1] / previous - 1) if previous else None


def _rsi(close: pd.Series) -> float | None:
    delta = close.diff()
    average_gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    average_loss = -delta.clip(upper=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    loss = _last(average_loss)
    gain = _last(average_gain)
    if loss is None or gain is None:
        return None
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def _atr(prices: pd.DataFrame) -> float | None:
    if not {"High", "Low", "Close"}.issubset(prices.columns):
        return None
    high = pd.to_numeric(prices["High"], errors="coerce")
    low = pd.to_numeric(prices["Low"], errors="coerce")
    close = pd.to_numeric(prices["Close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    return _last(true_range.rolling(14, min_periods=14).mean())


def _obv(close: pd.Series, volume: pd.Series) -> float | None:
    direction = close.diff().apply(lambda change: 1 if change > 0 else -1 if change < 0 else 0)
    return _last((direction * volume).fillna(0).cumsum())


def _cmf(prices: pd.DataFrame, volume: pd.Series) -> float | None:
    if not {"High", "Low", "Close"}.issubset(prices.columns):
        return None
    high = pd.to_numeric(prices["High"], errors="coerce")
    low = pd.to_numeric(prices["Low"], errors="coerce")
    close = pd.to_numeric(prices["Close"], errors="coerce")
    spread = high - low
    multiplier = ((close - low) - (high - close)) / spread.where(spread != 0)
    flow = multiplier * volume
    denominator = volume.rolling(20, min_periods=20).sum()
    return _last(flow.rolling(20, min_periods=20).sum() / denominator)


def _clean(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
