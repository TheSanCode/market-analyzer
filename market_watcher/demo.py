"""Generator for the small offline demo dataset.

THE DATA PRODUCED HERE IS SIMULATED. It is a deterministic random walk with
hand-picked scenarios (accumulation, distribution, range, spike, short history,
stale feed, gappy feed) used to demonstrate and test the scanner offline. It
does not describe any real security.

Regenerate with:  python -m market_watcher.demo
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import DEMO_CSV

DEMO_BENCHMARK = "DEMO-BENCH"
DEMO_START = "2025-01-02"
DEMO_SESSIONS = 300


@dataclass
class Scenario:
    ticker: str
    drift: float  # mean daily return
    vol: float  # daily return std
    close_loc: float  # mean close location within the day's range (0=low, 1=high)
    up_volume_boost: float  # volume multiplier on up days
    base_volume: float
    last_day_return: float | None = None
    last_day_rvol: float | None = None
    sessions: int = DEMO_SESSIONS
    drop_last: int = 0  # simulate a feed that stopped updating
    gaps: bool = False  # simulate missing values


SCENARIOS = [
    Scenario(DEMO_BENCHMARK, 0.0004, 0.009, 0.5, 1.0, 80e6),
    Scenario("DEMO-ACCUM", 0.0018, 0.013, 0.68, 1.35, 4e6, 0.031, 3.2),
    Scenario("DEMO-DISTRIB", -0.0015, 0.015, 0.32, 0.75, 6e6, -0.034, 2.8),
    Scenario("DEMO-RANGE", 0.0, 0.010, 0.5, 1.0, 2e6),
    Scenario("DEMO-SPIKE", 0.0030, 0.040, 0.6, 1.2, 9e6, 0.085, 4.0),
    Scenario("DEMO-YOUNG", 0.0012, 0.020, 0.6, 1.2, 1.5e6, sessions=120),
    Scenario("DEMO-STALE", 0.0010, 0.012, 0.6, 1.1, 3e6, drop_last=8),
    Scenario("DEMO-GAPPY", 0.0008, 0.014, 0.55, 1.1, 2.5e6, gaps=True),
]


def _simulate(s: Scenario, dates: pd.DatetimeIndex, rng: np.random.Generator) -> pd.DataFrame:
    n = len(dates)
    rets = rng.normal(s.drift, s.vol, n)
    if s.last_day_return is not None:
        rets[-1] = s.last_day_return
    close = 100.0 * np.cumprod(1.0 + rets)
    rng_pct = np.abs(rng.normal(s.vol * 1.6, s.vol * 0.4, n)).clip(0.002)
    span = close * rng_pct
    loc = np.clip(rng.normal(s.close_loc, 0.15, n), 0.0, 1.0)
    low = close - loc * span
    high = low + span
    open_ = low + rng.uniform(0.2, 0.8, n) * span
    volume = s.base_volume * rng.lognormal(0.0, 0.25, n)
    volume = np.where(rets > 0, volume * s.up_volume_boost, volume)
    if s.last_day_rvol is not None:
        volume[-1] = volume[-21:-1].mean() * s.last_day_rvol
    df = pd.DataFrame(
        {
            "Date": dates,
            "Ticker": s.ticker,
            "Open": open_.round(2),
            "High": high.round(2),
            "Low": low.round(2),
            "Close": close.round(2),
            "Volume": volume.round(0),
        }
    )
    if s.gaps:
        idx = rng.choice(np.arange(10, n - 5), size=6, replace=False)
        df.loc[idx[:3], "Volume"] = np.nan
        df.loc[idx[3:], "Close"] = np.nan
    if s.drop_last:
        df = df.iloc[: -s.drop_last]
    return df


def generate_demo_frame(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    all_dates = pd.bdate_range(DEMO_START, periods=DEMO_SESSIONS)
    frames = [_simulate(s, all_dates[-s.sessions :], rng) for s in SCENARIOS]
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    DEMO_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = generate_demo_frame()
    df.to_csv(DEMO_CSV, index=False, date_format="%Y-%m-%d")
    print(f"wrote {len(df)} SIMULATED rows to {DEMO_CSV}")


if __name__ == "__main__":
    main()
