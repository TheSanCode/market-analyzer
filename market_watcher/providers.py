from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    def fetch_history(self, tickers: list[str], period: str) -> dict[str, pd.DataFrame]: ...


class DemoProvider:
    def __init__(self, data_path: str | Path | None = None) -> None:
        self.data_path = Path(data_path) if data_path else Path(__file__).parent / "data" / "demo_prices.csv"
        self.errors: dict[str, str] = {}

    def fetch_history(self, tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
        del period
        if not self.data_path.exists():
            raise FileNotFoundError(f"Demo data not found: {self.data_path}")
        data = pd.read_csv(self.data_path, parse_dates=["Date"])
        data["Ticker"] = data["Ticker"].str.upper()
        found: dict[str, pd.DataFrame] = {}
        self.errors = {}
        for ticker in tickers:
            rows = data.loc[data["Ticker"] == ticker].drop(columns="Ticker").set_index("Date")
            if rows.empty:
                self.errors[ticker] = "Ticker is not included in the bundled demo dataset."
            else:
                found[ticker] = rows.sort_index()
        return found


class YFinanceProvider:
    def __init__(
        self,
        attempts: int = 3,
        retry_delay: float = 1.0,
        fallback_ticker_limit: int = 20,
    ) -> None:
        self.attempts = max(1, attempts)
        self.retry_delay = max(0.0, retry_delay)
        self.fallback_ticker_limit = max(0, fallback_ticker_limit)
        self.errors: dict[str, str] = {}

    def fetch_history(self, tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
        import yfinance as yf

        self.errors = {}
        results: dict[str, pd.DataFrame] = {}
        batch = None
        batch_error = "Yahoo Finance returned no data."
        for attempt in range(self.attempts):
            try:
                downloaded = self._download(yf, tickers, period)
                if downloaded.empty:
                    raise ValueError("Yahoo Finance returned an empty batch.")
                batch = downloaded
                break
            except Exception as exc:
                batch_error = f"Batch download failed: {exc}"
                if attempt + 1 < self.attempts:
                    time.sleep(self.retry_delay * (2**attempt))
        if batch is None:
            self.errors["*"] = batch_error
            self.errors.update({ticker: batch_error for ticker in tickers})
            return results
        for ticker in tickers:
            frame = _extract_ticker(batch, ticker)
            if not frame.empty:
                results[ticker] = frame

        missing = [ticker for ticker in tickers if ticker not in results]
        retryable = missing[: self.fallback_ticker_limit]
        for ticker in missing[self.fallback_ticker_limit :]:
            self.errors[ticker] = "No batch history; individual retry limit reached."
        for ticker in retryable:
            for attempt in range(self.attempts):
                try:
                    single = self._download(yf, [ticker], period)
                    frame = _extract_ticker(single, ticker)
                    if not frame.empty:
                        results[ticker] = frame
                        self.errors.pop(ticker, None)
                        break
                    self.errors[ticker] = "No daily price history was returned."
                except Exception as exc:
                    self.errors[ticker] = str(exc)
                if attempt + 1 < self.attempts:
                    time.sleep(self.retry_delay * (2**attempt))
        return results

    @staticmethod
    def _download(yf: object, tickers: list[str], period: str) -> pd.DataFrame:
        return yf.download(
            tickers=tickers,
            period=period,
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )


def _extract_ticker(download: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if download is None or download.empty:
        return pd.DataFrame()
    if isinstance(download.columns, pd.MultiIndex):
        if ticker not in download.columns.get_level_values(0):
            if ticker in download.columns.get_level_values(-1):
                frame = download.xs(ticker, axis=1, level=-1, drop_level=True)
            else:
                return pd.DataFrame()
        else:
            frame = download[ticker]
    else:
        frame = download
    required = {"Close", "Volume"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    selected = [column for column in ("Open", "High", "Low", "Close", "Volume") if column in frame.columns]
    frame = frame[selected].copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.dropna(subset=["Close", "Volume"])
    return frame[~frame.index.duplicated(keep="last")].sort_index()
