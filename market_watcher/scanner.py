"""Scan orchestration: fetch -> validate -> indicators -> score -> rank -> explain.

Failures are isolated per ticker: any exception while fetching or analysing a
symbol is recorded on that symbol's result and the scan continues.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import pandas as pd

from . import indicators as ind
from .config import AppConfig, IndicatorConfig
from .data import DataQualityError, PriceData, Provider, is_stale
from .llm import OllamaUnavailable
from .scoring import INSUFFICIENT, LABEL_ORDER, score_metrics

log = logging.getLogger(__name__)

SIGNAL_DISCLAIMER = (
    "Signals are price/volume proxies for buying or selling pressure. They are "
    "not verified institutional money flows, not news, and not investment advice. "
    "Labels are research candidates only and ignore any holdings."
)


class Explainer(Protocol):
    def explain(self, result: dict[str, Any]) -> str: ...


@dataclass
class TickerResult:
    ticker: str
    status: str  # "ok" | "error"
    label: str = INSUFFICIENT
    score: float | None = None
    rank: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    last_bar: str | None = None
    fetched_at: str | None = None
    stale: bool = False
    source: str | None = None
    simulated: bool = False
    explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    started_at: str
    finished_at: str
    provider: str
    simulated: bool
    benchmark: str
    benchmark_last_bar: str | None
    universe: list[str]
    results: list[TickerResult]
    notes: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    scan_id: int | None = None

    @property
    def ok(self) -> list[TickerResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def failed(self) -> list[TickerResult]:
        return [r for r in self.results if r.status == "error"]


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _last(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    return _num(series.iloc[-1])


def compute_metrics(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame | None,
    cfg: IndicatorConfig,
) -> dict[str, Any]:
    """Latest-session indicator values. Unavailable values are None."""
    c, h, lo, v = frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    close = _last(c)
    atr_v = _last(ind.atr(h, lo, c, cfg.atr_window))
    m: dict[str, Any] = {
        "close": close,
        "change_1d": _last(ind.period_return(c, 1)),
        "volume": _last(v),
        "rvol": _last(ind.relative_volume(v, cfg.rvol_window)),
        "sma50": _last(ind.sma(c, cfg.sma_fast)),
        "sma200": _last(ind.sma(c, cfg.sma_slow)),
        "rsi": _last(ind.rsi(c, cfg.rsi_window)),
        "atr": atr_v,
        "atr_pct": (100.0 * atr_v / close) if (atr_v is not None and close) else None,
        "obv": _last(ind.obv(c, v)),
        "obv_trend": _last(ind.obv_trend(c, v, cfg.obv_window)),
        "cmf": _last(ind.chaikin_money_flow(h, lo, c, v, cfg.cmf_window)),
        "return_20d": _last(ind.period_return(c, cfg.return_short)),
        "return_63d": _last(ind.period_return(c, cfg.return_long)),
        "rel_return_20d": None,
        "rel_return_63d": None,
        "sessions": int(len(frame)),
    }
    if benchmark is not None and not benchmark.empty:
        bc = benchmark["Close"]
        m["rel_return_20d"] = _last(ind.relative_return(c, bc, cfg.return_short))
        m["rel_return_63d"] = _last(ind.relative_return(c, bc, cfg.return_long))
    return m


def indicator_frame(frame: pd.DataFrame, cfg: IndicatorConfig) -> pd.DataFrame:
    """Full indicator time series for charting."""
    c, h, lo, v = frame["Close"], frame["High"], frame["Low"], frame["Volume"]
    return pd.DataFrame(
        {
            "Close": c,
            f"SMA{cfg.sma_fast}": ind.sma(c, cfg.sma_fast),
            f"SMA{cfg.sma_slow}": ind.sma(c, cfg.sma_slow),
            "Volume": v,
            "RelVolume": ind.relative_volume(v, cfg.rvol_window),
            "RSI": ind.rsi(c, cfg.rsi_window),
            "ATR": ind.atr(h, lo, c, cfg.atr_window),
            "OBV": ind.obv(c, v),
            "CMF": ind.chaikin_money_flow(h, lo, c, v, cfg.cmf_window),
        },
        index=frame.index,
    )


def _fetch_with_retry(provider: Provider, ticker: str, cfg: AppConfig) -> PriceData:
    attempts = max(1, cfg.data.retries + 1)
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return provider.fetch(ticker, cfg.data.history_days)
        except DataQualityError:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate any provider failure
            last_exc = exc
            log.warning("fetch %s failed (attempt %d/%d): %s", ticker, i + 1, attempts, exc)
            if i + 1 < attempts and not provider.simulated:
                time.sleep(1.0)
    assert last_exc is not None
    raise last_exc


def analyse_ticker(
    ticker: str,
    pdata: PriceData,
    bench: PriceData | None,
    cfg: AppConfig,
    reference: datetime,
) -> TickerResult:
    res = TickerResult(
        ticker=ticker,
        status="ok",
        last_bar=pdata.last_bar.isoformat(),
        fetched_at=pdata.fetched_at.isoformat(timespec="seconds"),
        source=pdata.source,
        simulated=pdata.simulated,
        warnings=list(pdata.warnings),
    )
    res.stale = is_stale(pdata.last_bar, reference, cfg.data.max_stale_days)
    if len(pdata.frame) < cfg.data.min_sessions:
        res.label = INSUFFICIENT
        res.missing.append(
            f"only {len(pdata.frame)} sessions of history (needs {cfg.data.min_sessions})"
        )
        return res

    bench_frame = None
    if bench is not None:
        # Never compare against benchmark sessions after the asset's last bar.
        bench_frame = bench.frame[bench.frame.index <= pdata.frame.index[-1]]
        if bench_frame.empty or bench_frame.index[-1] != pdata.frame.index[-1]:
            res.missing.append("benchmark has no bar for the ticker's latest session")
    metrics = compute_metrics(pdata.frame, bench_frame, cfg.indicators)
    if metrics["sma200"] is None:
        res.missing.append(
            f"SMA{cfg.indicators.sma_slow} needs {cfg.indicators.sma_slow} sessions "
            f"(have {metrics['sessions']})"
        )
    scored = score_metrics(metrics, cfg.scoring, stale=res.stale)
    res.metrics = metrics
    res.score = scored.score
    res.label = scored.label
    res.evidence = scored.evidence()
    res.risks = scored.risks
    res.missing.extend(m for m in scored.missing if m not in res.missing)
    return res


def rank_results(results: list[TickerResult]) -> None:
    ok = [r for r in results if r.status == "ok" and r.score is not None]
    ok.sort(key=lambda r: (LABEL_ORDER.get(r.label, 9), -(r.score or 0.0), r.ticker))
    for i, r in enumerate(ok, start=1):
        r.rank = i


def sorted_results(results: list[TickerResult]) -> list[TickerResult]:
    return sorted(
        results,
        key=lambda r: (
            r.rank is None,
            r.rank or 0,
            r.status != "ok",
            r.ticker,
        ),
    )


def run_scan(
    cfg: AppConfig,
    provider: Provider,
    explainer: Explainer | None = None,
    *,
    reference_time: datetime | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScanResult:
    started = datetime.now(UTC)
    if reference_time is None:
        reference_time = getattr(provider, "reference_time", None) or started
    notes: list[str] = []
    say = progress or (lambda _msg: None)

    bench: PriceData | None = None
    try:
        say(f"fetching benchmark {cfg.benchmark}")
        bench = _fetch_with_retry(provider, cfg.benchmark, cfg)
        if is_stale(bench.last_bar, reference_time, cfg.data.max_stale_days):
            notes.append(f"benchmark {cfg.benchmark} data is stale (last bar {bench.last_bar})")
    except Exception as exc:  # noqa: BLE001
        notes.append(
            f"benchmark {cfg.benchmark} unavailable ({exc}); relative-strength "
            "component skipped for all tickers"
        )
        bench = None

    results: list[TickerResult] = []
    for ticker in cfg.universe:
        say(f"scanning {ticker}")
        try:
            pdata = _fetch_with_retry(provider, ticker, cfg)
            results.append(analyse_ticker(ticker, pdata, bench, cfg, reference_time))
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the scan
            log.warning("ticker %s failed: %s", ticker, exc)
            results.append(
                TickerResult(
                    ticker=ticker,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    source=provider.name,
                    simulated=provider.simulated,
                )
            )

    rank_results(results)
    results = sorted_results(results)

    if explainer is not None and cfg.ollama.enabled and cfg.ollama.explain_top_n > 0:
        ranked = [r for r in results if r.rank is not None][: cfg.ollama.explain_top_n]
        for r in ranked:
            say(f"explaining {r.ticker} with local LLM")
            try:
                r.explanation = explainer.explain(r.to_dict())
            except Exception as exc:  # noqa: BLE001 - LLM is optional
                notes.append(f"LLM explanation skipped for {r.ticker}: {exc}")
                if isinstance(exc, OllamaUnavailable):
                    break

    if provider.simulated:
        notes.insert(0, "SIMULATED DEMO DATA - not real market prices.")

    return ScanResult(
        started_at=started.isoformat(timespec="seconds"),
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        provider=provider.name,
        simulated=provider.simulated,
        benchmark=cfg.benchmark,
        benchmark_last_bar=bench.last_bar.isoformat() if bench else None,
        universe=list(cfg.universe),
        results=results,
        notes=notes,
        config={
            "scoring": cfg.scoring.to_dict(),
            "indicators": asdict(cfg.indicators),
            "data": asdict(cfg.data),
        },
    )
