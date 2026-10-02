from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS = {
    "rvol_20": 15,
    "return_20": 10,
    "return_60": 15,
    "relative_20": 10,
    "relative_60": 10,
    "sma_50": 15,
    "sma_200": 15,
    "rsi_14": 5,
    "cmf_20": 5,
}


def score_candidate(
    indicators: dict[str, Any], settings: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Score calculated evidence; this heuristic is not a return probability."""
    settings = settings or {}
    weights = {**DEFAULT_WEIGHTS, **settings.get("weights", {})}
    factors: dict[str, dict[str, Any]] = {}
    valid_weight = 0.0
    weighted_points = 0.0
    total_weight = sum(max(0.0, float(weight)) for weight in weights.values())

    for name, raw_weight in weights.items():
        weight = float(raw_weight)
        if weight <= 0:
            continue
        value = indicators.get(name)
        if value is None:
            factors[name] = {"value": None, "points": None, "weight": weight, "contribution": None}
            continue
        points = _factor_points(name, value, indicators)
        valid_weight += weight
        weighted_points += points * weight
        factors[name] = {
            "value": value,
            "points": round(points, 2),
            "weight": weight,
            "contribution": None,
        }

    coverage = valid_weight / total_weight if total_weight else 0.0
    score = weighted_points / valid_weight if valid_weight else 0.0
    for factor in factors.values():
        if factor["value"] is not None:
            factor["contribution"] = (
                round(factor["points"] * factor["weight"] / valid_weight, 2)
                if valid_weight
                else 0.0
            )
    minimum_coverage = float(settings.get("minimum_factor_coverage", 0.5))
    buy_threshold = float(settings.get("buy_threshold", 70))
    watch_threshold = float(settings.get("watch_threshold", 45))
    if coverage < minimum_coverage:
        signal = "SELL/AVOID"
    elif score >= buy_threshold:
        signal = "BUY"
    elif score >= watch_threshold:
        signal = "WATCH"
    else:
        signal = "SELL/AVOID"
    return {
        "score": round(score, 2),
        "signal": signal,
        "coverage": round(coverage, 3),
        "factors": factors,
        "missing_factors": [name for name, item in factors.items() if item["value"] is None],
        "score_disclaimer": "Heuristic ranking, not a probability of profit or investment advice.",
    }


def _factor_points(name: str, value: float, indicators: dict[str, Any]) -> float:
    if name == "rvol_20":
        return _linear(value, 0.5, 2.0)
    if name in {"return_20", "relative_20"}:
        return _linear(value, -0.1, 0.1)
    if name in {"return_60", "relative_60"}:
        return _linear(value, -0.2, 0.2)
    if name == "sma_50":
        return 100.0 if indicators.get("close") is not None and indicators["close"] > value else 0.0
    if name == "sma_200":
        return 100.0 if indicators.get("close") is not None and indicators["close"] > value else 0.0
    if name == "rsi_14":
        if value <= 30 or value >= 85:
            return 0.0
        if 50 <= value <= 65:
            return 70 + (value - 50) * 2
        if value < 50:
            return max(0.0, (value - 30) * 3.5)
        return max(0.0, 100 - (value - 65) * 4)
    if name == "cmf_20":
        return _linear(value, -0.2, 0.2)
    return 0.0


def _linear(value: float, low: float, high: float) -> float:
    return round(max(0.0, min(100.0, (float(value) - low) / (high - low) * 100)), 2)
