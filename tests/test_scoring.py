import pytest

from market_watcher.config import ConfigError, config_from_dict
from market_watcher.scoring import (
    BUY,
    INSUFFICIENT,
    SELL_AVOID,
    WATCH,
    ScoringConfig,
    score_metrics,
)

BULLISH = {
    "close": 120.0,
    "change_1d": 0.03,
    "rvol": 3.0,
    "sma50": 110.0,
    "sma200": 100.0,
    "rsi": 60.0,
    "atr_pct": 2.0,
    "obv_trend": 0.5,
    "cmf": 0.3,
    "rel_return_20d": 0.08,
    "rel_return_63d": 0.15,
}
BEARISH = {
    "close": 80.0,
    "change_1d": -0.03,
    "rvol": 3.0,
    "sma50": 90.0,
    "sma200": 100.0,
    "rsi": 40.0,
    "atr_pct": 2.0,
    "obv_trend": -0.5,
    "cmf": -0.3,
    "rel_return_20d": -0.08,
    "rel_return_63d": -0.15,
}


def test_bullish_is_buy_and_bearish_is_avoid():
    b = score_metrics(BULLISH)
    assert b.label == BUY
    assert b.score > 80
    s = score_metrics(BEARISH)
    assert s.label == SELL_AVOID
    assert s.score < -60


def test_score_is_transparent_sum_of_components():
    r = score_metrics(BULLISH)
    covered = sum(c.weight for c in r.components if c.sub_score is not None)
    assert r.score == pytest.approx(100 * sum(c.points for c in r.components) / covered, abs=0.01)
    names = [e["component"] for e in r.evidence()]
    assert names == [
        "volume_pressure",
        "relative_strength",
        "trend",
        "chaikin_money_flow",
        "obv_trend",
        "rsi",
    ]
    assert all(e["reason"] for e in r.evidence())


def test_high_volume_down_day_is_negative_pressure():
    m = dict(BULLISH, change_1d=-0.02)
    comp = score_metrics(m).components[0]
    assert comp.name == "volume_pressure"
    assert comp.sub_score < 0


def test_low_relative_volume_gives_no_volume_signal():
    m = dict(BULLISH, rvol=1.0)
    assert score_metrics(m).components[0].sub_score == 0.0


def test_neutral_is_watch():
    m = {
        "close": 100.0,
        "change_1d": 0.001,
        "rvol": 1.0,
        "sma50": 100.5,
        "sma200": 99.0,
        "rsi": 50.0,
        "atr_pct": 2.0,
        "obv_trend": 0.0,
        "cmf": 0.0,
        "rel_return_20d": 0.0,
        "rel_return_63d": 0.0,
    }
    assert score_metrics(m).label == WATCH


def test_weights_and_thresholds_are_configurable():
    cfg = ScoringConfig(buy_threshold=101)
    assert score_metrics(BULLISH, cfg).label == WATCH
    # Zeroing all weights except RSI makes RSI the only driver.
    cfg2 = ScoringConfig(
        weight_volume_pressure=0,
        weight_relative_strength=0,
        weight_trend=0,
        weight_cmf=0,
        weight_obv=0,
        weight_rsi=10,
    )
    assert score_metrics(BULLISH, cfg2).score == pytest.approx(100.0)


def test_missing_data_reduces_coverage_and_caps_buy():
    m = {k: v for k, v in BULLISH.items() if k not in ("rvol", "rel_return_20d", "rel_return_63d")}
    r = score_metrics(m)
    assert r.weight_coverage < 0.7
    assert r.label == WATCH
    assert any("capped at WATCH" in x for x in r.risks)
    assert any("relative volume" in x for x in r.missing)
    assert any("benchmark" in x for x in r.missing)


def test_nan_values_are_treated_as_missing():
    m = dict(BULLISH, cmf=float("nan"))
    comp = [c for c in score_metrics(m).components if c.name == "chaikin_money_flow"][0]
    assert comp.sub_score is None


def test_stale_data_caps_buy():
    r = score_metrics(BULLISH, stale=True)
    assert r.label == WATCH
    assert any("stale" in x for x in r.risks)


def test_no_data_is_insufficient():
    assert score_metrics({}).label == INSUFFICIENT


def test_high_atr_penalty_and_overbought_risk():
    base = score_metrics(BULLISH).score
    r = score_metrics(dict(BULLISH, atr_pct=9.0, rsi=80.0))
    assert r.score < base
    assert any("volatility" in x for x in r.risks)
    assert any("overbought" in x for x in r.risks)


def test_score_clamped():
    cfg = ScoringConfig(atr_penalty_points=500)
    assert score_metrics(dict(BEARISH, atr_pct=50), cfg).score == -100.0


def test_config_overrides_scoring_and_rejects_unknown_keys():
    cfg = config_from_dict({"scoring": {"buy_threshold": 55}, "universe": [" aapl ", "AAPL"]})
    assert cfg.scoring.buy_threshold == 55.0
    assert cfg.universe == ["AAPL"]
    with pytest.raises(ConfigError):
        config_from_dict({"scoring": {"nope": 1}})
    with pytest.raises(ConfigError):
        config_from_dict({"scoring": {"buy_threshold": "high"}})
    with pytest.raises(ConfigError):
        config_from_dict({"data": {"provider": "broker"}})
