"""Transparent, configurable scoring of price/volume evidence.

Every component maps one calculated metric to a sub-score in [-1, 1]. The total
score is the weighted sum of sub-scores, scaled to [-100, 100] by the total
weight of components that had data. Each component also records a short,
human-readable reason so rankings can be audited.

Signals are *proxies* for buying or selling pressure derived from public
price and volume data. They are not verified institutional money flows and are
not investment advice.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

BUY = "BUY"
WATCH = "WATCH"
SELL_AVOID = "SELL/AVOID"
INSUFFICIENT = "INSUFFICIENT DATA"

LABEL_ORDER = {BUY: 0, WATCH: 1, SELL_AVOID: 2, INSUFFICIENT: 3}


@dataclass
class ScoringConfig:
    """Weights and thresholds. Edit here or override in the TOML config."""

    # Component weights (relative; they do not need to sum to anything).
    weight_volume_pressure: float = 25.0
    weight_relative_strength: float = 20.0
    weight_trend: float = 20.0
    weight_cmf: float = 15.0
    weight_obv: float = 10.0
    weight_rsi: float = 10.0

    # Relative volume: below `rvol_min` gives no signal, at/above `rvol_full`
    # gives full signal. Direction comes from the session's close change.
    rvol_min: float = 1.2
    rvol_full: float = 2.5

    # Benchmark-relative return (fraction) that earns a full +/-1 sub-score.
    rel_return_full: float = 0.10

    # CMF value that earns a full +/-1 sub-score; |CMF| below `cmf_dead_zone`
    # is treated as neutral.
    cmf_full: float = 0.25
    cmf_dead_zone: float = 0.05

    # OBV trend (net signed volume fraction, -1..1) that earns full sub-score.
    obv_full: float = 0.5

    # RSI zones.
    rsi_overbought: float = 75.0
    rsi_oversold: float = 30.0
    rsi_bull_low: float = 50.0
    rsi_bull_high: float = 70.0

    # ATR as % of price above which a volatility risk penalty is applied.
    atr_pct_high: float = 6.0
    atr_penalty_points: float = 10.0

    # Label thresholds on the final score (-100..100).
    buy_threshold: float = 40.0
    avoid_threshold: float = -20.0

    # A BUY needs at least this share of total weight to have data, and fresh
    # data; otherwise it is capped at WATCH.
    min_weight_coverage: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Component:
    name: str
    weight: float
    sub_score: float | None  # None means "missing data"
    reason: str

    @property
    def points(self) -> float:
        return 0.0 if self.sub_score is None else self.weight * self.sub_score


@dataclass
class ScoreResult:
    score: float
    label: str
    components: list[Component] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    weight_coverage: float = 0.0

    def evidence(self) -> list[dict[str, Any]]:
        return [
            {
                "component": c.name,
                "weight": c.weight,
                "sub_score": None if c.sub_score is None else round(c.sub_score, 3),
                "points": round(c.points, 2),
                "reason": c.reason,
            }
            for c in self.components
        ]


def _ok(value: Any) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _volume_pressure(m: dict, cfg: ScoringConfig) -> Component:
    rvol, chg = m.get("rvol"), m.get("change_1d")
    w = cfg.weight_volume_pressure
    if not (_ok(rvol) and _ok(chg)):
        return Component("volume_pressure", w, None, "relative volume or 1-day change unavailable")
    if rvol < cfg.rvol_min or chg == 0:
        return Component(
            "volume_pressure",
            w,
            0.0,
            f"relative volume {rvol:.2f}x (below {cfg.rvol_min}x or flat close): no signal",
        )
    span = max(cfg.rvol_full - cfg.rvol_min, 1e-9)
    magnitude = min(1.0, (rvol - cfg.rvol_min) / span)
    direction = 1.0 if chg > 0 else -1.0
    side = "up" if direction > 0 else "down"
    return Component(
        "volume_pressure",
        w,
        direction * magnitude,
        f"relative volume {rvol:.2f}x on an {side} session ({chg:+.2%})",
    )


def _relative_strength(m: dict, cfg: ScoringConfig) -> Component:
    w = cfg.weight_relative_strength
    vals = [m.get(k) for k in ("rel_return_20d", "rel_return_63d")]
    vals = [v for v in vals if _ok(v)]
    if not vals:
        return Component("relative_strength", w, None, "benchmark-relative return unavailable")
    avg = sum(vals) / len(vals)
    parts = []
    for key, label in (("rel_return_20d", "20d"), ("rel_return_63d", "63d")):
        if _ok(m.get(key)):
            parts.append(f"{label} {m[key]:+.2%}")
    return Component(
        "relative_strength",
        w,
        _clip(avg / cfg.rel_return_full),
        "vs benchmark: " + ", ".join(parts),
    )


def _trend(m: dict, cfg: ScoringConfig) -> Component:
    w = cfg.weight_trend
    close, fast, slow = m.get("close"), m.get("sma50"), m.get("sma200")
    if not (_ok(close) and _ok(fast)):
        return Component("trend", w, None, "50-day moving average unavailable")
    if not _ok(slow):
        sub = 0.5 if close > fast else -0.5
        return Component(
            "trend",
            w,
            sub,
            f"close {'above' if close > fast else 'below'} SMA50; SMA200 unavailable",
        )
    score = 0.0
    score += 0.4 if close > fast else -0.4
    score += 0.3 if close > slow else -0.3
    score += 0.3 if fast > slow else -0.3
    desc = (
        f"close {'>' if close > fast else '<'} SMA50, "
        f"close {'>' if close > slow else '<'} SMA200, "
        f"SMA50 {'>' if fast > slow else '<'} SMA200"
    )
    return Component("trend", w, _clip(score), desc)


def _cmf(m: dict, cfg: ScoringConfig) -> Component:
    w = cfg.weight_cmf
    cmf = m.get("cmf")
    if not _ok(cmf):
        return Component("chaikin_money_flow", w, None, "CMF unavailable")
    if abs(cmf) < cfg.cmf_dead_zone:
        return Component("chaikin_money_flow", w, 0.0, f"CMF {cmf:+.3f} (neutral zone)")
    return Component("chaikin_money_flow", w, _clip(cmf / cfg.cmf_full), f"CMF {cmf:+.3f}")


def _obv(m: dict, cfg: ScoringConfig) -> Component:
    w = cfg.weight_obv
    trend = m.get("obv_trend")
    if not _ok(trend):
        return Component("obv_trend", w, None, "OBV trend unavailable")
    return Component(
        "obv_trend",
        w,
        _clip(trend / cfg.obv_full),
        f"OBV net volume fraction {trend:+.2f} over window",
    )


def _rsi(m: dict, cfg: ScoringConfig) -> Component:
    w = cfg.weight_rsi
    r = m.get("rsi")
    if not _ok(r):
        return Component("rsi", w, None, "RSI unavailable")
    if r >= cfg.rsi_overbought:
        return Component("rsi", w, -0.5, f"RSI {r:.1f}: overbought, chase risk")
    if r <= cfg.rsi_oversold:
        return Component("rsi", w, -0.5, f"RSI {r:.1f}: oversold, weak momentum")
    if cfg.rsi_bull_low <= r <= cfg.rsi_bull_high:
        return Component("rsi", w, 1.0, f"RSI {r:.1f}: constructive momentum")
    if r > cfg.rsi_bull_high:
        return Component("rsi", w, 0.3, f"RSI {r:.1f}: strong but extended")
    return Component("rsi", w, -0.3, f"RSI {r:.1f}: below 50, soft momentum")


COMPONENTS = (_volume_pressure, _relative_strength, _trend, _cmf, _obv, _rsi)


def score_metrics(
    metrics: dict[str, Any], cfg: ScoringConfig | None = None, *, stale: bool = False
) -> ScoreResult:
    """Score a ticker's latest metrics. Pure function; no I/O."""
    cfg = cfg or ScoringConfig()
    components = [fn(metrics, cfg) for fn in COMPONENTS]
    total_weight = sum(c.weight for c in components if c.weight > 0)
    covered = sum(c.weight for c in components if c.sub_score is not None and c.weight > 0)
    coverage = covered / total_weight if total_weight else 0.0

    missing = [c.reason for c in components if c.sub_score is None]
    risks: list[str] = []

    if covered == 0:
        return ScoreResult(0.0, INSUFFICIENT, components, risks, missing, coverage)

    score = 100.0 * sum(c.points for c in components) / covered

    atr_pct = metrics.get("atr_pct")
    if _ok(atr_pct) and atr_pct > cfg.atr_pct_high:
        score -= cfg.atr_penalty_points
        risks.append(
            f"high volatility: ATR {atr_pct:.1f}% of price "
            f"(> {cfg.atr_pct_high}%), -{cfg.atr_penalty_points:g} points"
        )
    elif not _ok(atr_pct):
        missing.append("ATR unavailable (volatility risk not assessed)")

    rsi_v = metrics.get("rsi")
    if _ok(rsi_v) and rsi_v >= cfg.rsi_overbought:
        risks.append(f"RSI {rsi_v:.1f} is overbought")
    close, slow = metrics.get("close"), metrics.get("sma200")
    if _ok(close) and _ok(slow) and close < slow:
        risks.append("price below 200-day moving average (long-term downtrend)")

    score = max(-100.0, min(100.0, score))

    if score >= cfg.buy_threshold:
        label = BUY
    elif score <= cfg.avoid_threshold:
        label = SELL_AVOID
    else:
        label = WATCH

    if label == BUY and coverage < cfg.min_weight_coverage:
        label = WATCH
        risks.append(
            f"capped at WATCH: only {coverage:.0%} of scoring weight had data "
            f"(needs {cfg.min_weight_coverage:.0%})"
        )
    if label == BUY and stale:
        label = WATCH
        risks.append("capped at WATCH: price data is stale")
    if stale:
        missing.append("latest session missing (data stale)")

    return ScoreResult(round(score, 2), label, components, risks, missing, coverage)
