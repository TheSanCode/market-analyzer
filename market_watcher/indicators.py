"""Technical indicators used as *proxies* for buying/selling pressure.

All functions are pure pandas operations on daily OHLCV data. None of them
measure institutional money flows directly; they only describe price and
volume behaviour.

Conventions:
- Inputs are pandas Series indexed by date (ascending).
- Outputs are aligned to the input index; warm-up periods are NaN.
- Moving averages and windows require a full window (no partial values).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average requiring a full window."""
    return series.rolling(window=window, min_periods=window).mean()


def relative_volume(volume: pd.Series, window: int = 20) -> pd.Series:
    """Volume divided by the mean volume of the *preceding* ``window`` sessions.

    The current session is excluded from its own baseline so a volume spike
    does not dilute itself. Baselines of zero yield NaN.
    """
    baseline = volume.shift(1).rolling(window=window, min_periods=window).mean()
    baseline = baseline.where(baseline > 0)
    return volume / baseline


def period_return(close: pd.Series, periods: int) -> pd.Series:
    """Simple return over ``periods`` sessions."""
    return close / close.shift(periods) - 1.0


def relative_return(close: pd.Series, benchmark_close: pd.Series, periods: int) -> pd.Series:
    """Asset return minus benchmark return over ``periods`` common sessions.

    Both series are aligned on their common dates first so that a missing
    session in either series does not shift the comparison window.
    """
    joined = pd.concat([close, benchmark_close], axis=1, join="inner").dropna()
    joined.columns = ["asset", "bench"]
    rel = period_return(joined["asset"], periods) - period_return(joined["bench"], periods)
    return rel.reindex(close.index)


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Returns 100 when there are no losses in the smoothing window and 50 when
    there is no movement at all.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    alpha = 1.0 / window
    avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return out


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    return ranges.max(axis=1, skipna=True)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume, starting at 0 on the first session."""
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume.fillna(0.0)).cumsum()


def chaikin_money_flow(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Chaikin Money Flow.

    Sessions with zero range (high == low) contribute a multiplier of 0.
    Windows with zero total volume yield NaN.
    """
    span = high - low
    multiplier = ((close - low) - (high - close)) / span.replace(0.0, np.nan)
    multiplier = multiplier.fillna(0.0)
    mf_volume = multiplier * volume
    vol_sum = volume.rolling(window=window, min_periods=window).sum()
    mfv_sum = mf_volume.rolling(window=window, min_periods=window).sum()
    return mfv_sum / vol_sum.replace(0.0, np.nan)


def obv_trend(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Net OBV change over ``window`` sessions divided by total volume traded.

    The result lies in [-1, 1]: +1 means every session in the window closed up,
    -1 means every session closed down. Being normalised by volume makes it
    comparable across tickers, unlike the raw (cumulative) OBV level.
    """
    obv_series = obv(close, volume)
    change = obv_series - obv_series.shift(window)
    total = volume.rolling(window=window, min_periods=window).sum()
    return change / total.replace(0.0, np.nan)
