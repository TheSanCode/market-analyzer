"""Market data providers, validation and staleness checks.

Each provider fetches one ticker at a time so that a failure for one symbol
never aborts the whole scan (see ``scanner.run_scan``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")

DEMO_CSV = Path(__file__).parent / "demo_data" / "simulated_ohlcv.csv"


class ProviderError(RuntimeError):
    """Provider could not return data for a ticker."""


class DataQualityError(ValueError):
    """Data was returned but is unusable."""


@dataclass
class PriceData:
    ticker: str
    frame: pd.DataFrame  # index: tz-naive dates; columns: REQUIRED_COLUMNS
    source: str
    simulated: bool
    fetched_at: datetime  # UTC
    warnings: list[str] = field(default_factory=list)

    @property
    def last_bar(self) -> date:
        return self.frame.index[-1].date()


class Provider(Protocol):
    name: str
    simulated: bool

    def fetch(self, ticker: str, history_days: int) -> PriceData: ...


def clean_ohlcv(raw: pd.DataFrame, ticker: str) -> tuple[pd.DataFrame, list[str]]:
    """Normalise columns/index, drop unusable rows and report what was dropped."""
    if raw is None or raw.empty:
        raise DataQualityError(f"{ticker}: provider returned no rows")
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    rename = {c: str(c).strip().title() for c in df.columns}
    df = df.rename(columns=rename)
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise DataQualityError(f"{ticker}: missing columns {missing_cols}")
    df = df[list(REQUIRED_COLUMNS)].apply(pd.to_numeric, errors="coerce")

    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()

    warnings: list[str] = []
    bad_close = df["Close"].isna() | (df["Close"] <= 0)
    if bad_close.any():
        warnings.append(f"dropped {int(bad_close.sum())} session(s) with missing/invalid close")
        df = df[~bad_close]
    if df.empty:
        raise DataQualityError(f"{ticker}: no valid closing prices")

    # Fill missing high/low from close so range-based indicators stay defined.
    for col in ("High", "Low", "Open"):
        n = int(df[col].isna().sum())
        if n:
            warnings.append(f"{n} session(s) missing {col}; filled from Close")
            df[col] = df[col].fillna(df["Close"])
    df["High"] = df[["High", "Close", "Open"]].max(axis=1)
    df["Low"] = df[["Low", "Close", "Open"]].min(axis=1)

    vol_missing = int(df["Volume"].isna().sum())
    if vol_missing:
        warnings.append(f"{vol_missing} session(s) missing volume; treated as 0")
        df["Volume"] = df["Volume"].fillna(0.0)
    if (df["Volume"] < 0).any():
        warnings.append("negative volume values set to 0")
        df["Volume"] = df["Volume"].clip(lower=0.0)
    if float(df["Volume"].tail(20).sum()) == 0.0:
        warnings.append("no volume reported in the last 20 sessions")
    return df, warnings


def is_stale(last_bar: date, reference: datetime, max_stale_days: int) -> bool:
    """True if the last bar is more than ``max_stale_days`` calendar days old."""
    return (reference.date() - last_bar) > timedelta(days=max_stale_days)


class YFinanceProvider:
    """Daily OHLCV from Yahoo Finance via ``yfinance`` (unofficial, may be delayed)."""

    name = "yfinance"
    simulated = False

    def fetch(self, ticker: str, history_days: int) -> PriceData:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise ProviderError("yfinance is not installed") from exc
        start = (datetime.now(UTC) - timedelta(days=history_days)).date()
        try:
            raw = yf.Ticker(ticker).history(
                start=start.isoformat(),
                interval="1d",
                auto_adjust=True,
                actions=False,
                timeout=20,
                raise_errors=True,
            )
        except Exception as exc:  # network, parsing, rate limits...
            raise ProviderError(f"{ticker}: yfinance error: {exc}") from exc
        if raw is None or raw.empty:
            raise ProviderError(f"{ticker}: yfinance returned no data (delisted or invalid?)")
        frame, warnings = clean_ohlcv(raw, ticker)
        return PriceData(ticker, frame, self.name, False, datetime.now(UTC), warnings)


class DemoProvider:
    """Offline SIMULATED data. Not real market data."""

    name = "demo (SIMULATED)"
    simulated = True

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEMO_CSV
        self._data: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._data is None:
            if not self.path.exists():
                raise ProviderError(f"demo dataset not found: {self.path}")
            self._data = pd.read_csv(self.path, parse_dates=["Date"])
        return self._data

    @property
    def tickers(self) -> list[str]:
        return sorted(self._load()["Ticker"].unique().tolist())

    @property
    def reference_time(self) -> datetime:
        """'Now' for staleness checks: the latest date in the simulated set."""
        last = self._load()["Date"].max()
        return datetime(last.year, last.month, last.day, 23, 0, tzinfo=UTC)

    def fetch(self, ticker: str, history_days: int) -> PriceData:
        data = self._load()
        rows = data[data["Ticker"] == ticker]
        if rows.empty:
            raise ProviderError(f"{ticker}: not in simulated demo dataset")
        frame = rows.drop(columns=["Ticker"]).set_index("Date")
        frame, warnings = clean_ohlcv(frame, ticker)
        cutoff = frame.index[-1] - pd.Timedelta(days=history_days)
        frame = frame[frame.index >= cutoff]
        return PriceData(ticker, frame, self.name, True, datetime.now(UTC), warnings)


def make_provider(name: str, demo_path: str | None = None) -> Provider:
    if name == "demo":
        return DemoProvider(demo_path or None)
    if name == "yfinance":
        return YFinanceProvider()
    raise ValueError(f"unknown provider {name!r}")
