import numpy as np
import pandas as pd
import pytest

from market_watcher import indicators as ind


def _idx(n):
    return pd.bdate_range("2024-01-01", periods=n)


def test_sma_requires_full_window():
    s = pd.Series([1.0, 2.0, 3.0, 4.0], index=_idx(4))
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(3.0)


def test_relative_volume_excludes_current_session():
    vol = pd.Series([100.0] * 5 + [300.0], index=_idx(6))
    rv = ind.relative_volume(vol, window=5)
    assert rv.iloc[-1] == pytest.approx(3.0)
    assert rv.iloc[:5].isna().all()


def test_relative_volume_zero_baseline_is_nan():
    vol = pd.Series([0.0] * 5 + [10.0], index=_idx(6))
    assert np.isnan(ind.relative_volume(vol, 5).iloc[-1])


def test_relative_return_aligns_on_common_dates():
    idx = _idx(5)
    asset = pd.Series([100, 101, 102, 103, 110.0], index=idx)
    bench = pd.Series([100, 100, 100, 100, 105.0], index=idx)
    rel = ind.relative_return(asset, bench, 4)
    assert rel.iloc[-1] == pytest.approx(0.10 - 0.05)

    # Benchmark missing the last session -> no comparison for that session.
    rel2 = ind.relative_return(asset, bench.iloc[:-1], 3)
    assert np.isnan(rel2.iloc[-1])


def test_rsi_extremes_and_known_value():
    up = pd.Series(np.arange(1, 31, dtype=float), index=_idx(30))
    assert ind.rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.arange(30, 0, -1, dtype=float), index=_idx(30))
    assert ind.rsi(down, 14).iloc[-1] == pytest.approx(0.0)
    flat = pd.Series([5.0] * 30, index=_idx(30))
    assert ind.rsi(flat, 14).iloc[-1] == pytest.approx(50.0)


def test_rsi_matches_reference_wilder_loop():
    rng = np.random.default_rng(3)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 80)), index=_idx(80))
    n = 14
    d = np.diff(close.to_numpy())
    gains, losses = np.clip(d, 0, None), np.clip(-d, 0, None)
    # Seed with the pandas ewm convention (first diff), then Wilder recursion.
    ag, al = gains[0], losses[0]
    for g, lo in zip(gains[1:], losses[1:], strict=True):
        ag = (ag * (n - 1) + g) / n
        al = (al * (n - 1) + lo) / n
    expected = 100 - 100 / (1 + ag / al)
    assert ind.rsi(close, n).iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_rsi_warmup_is_nan():
    s = pd.Series(np.arange(1, 11, dtype=float), index=_idx(10))
    assert ind.rsi(s, 14).isna().all()


def test_atr_constant_range():
    n = 30
    close = pd.Series([100.0] * n, index=_idx(n))
    high = close + 1
    low = close - 1
    out = ind.atr(high, low, close, 14)
    assert out.iloc[-1] == pytest.approx(2.0)
    assert np.isnan(out.iloc[12])


def test_true_range_uses_gap_from_previous_close():
    idx = _idx(2)
    close = pd.Series([100.0, 110.0], index=idx)
    high = pd.Series([101.0, 111.0], index=idx)
    low = pd.Series([99.0, 108.0], index=idx)
    assert ind.true_range(high, low, close).iloc[-1] == pytest.approx(11.0)


def test_obv():
    idx = _idx(5)
    close = pd.Series([10, 11, 10, 10, 12.0], index=idx)
    vol = pd.Series([100, 200, 300, 400, 500.0], index=idx)
    assert ind.obv(close, vol).tolist() == [0, 200, -100, -100, 400]


def test_obv_trend_bounds():
    idx = _idx(25)
    close = pd.Series(np.arange(25, dtype=float) + 1, index=idx)
    vol = pd.Series([1000.0] * 25, index=idx)
    assert ind.obv_trend(close, vol, 20).iloc[-1] == pytest.approx(1.0)
    assert ind.obv_trend(close[::-1].set_axis(idx), vol, 20).iloc[-1] == pytest.approx(-1.0)


def test_cmf_close_at_high_and_low_and_zero_range():
    n = 20
    idx = _idx(n)
    high = pd.Series([11.0] * n, index=idx)
    low = pd.Series([9.0] * n, index=idx)
    vol = pd.Series([1000.0] * n, index=idx)
    assert ind.chaikin_money_flow(high, low, high, vol, 20).iloc[-1] == pytest.approx(1.0)
    assert ind.chaikin_money_flow(high, low, low, vol, 20).iloc[-1] == pytest.approx(-1.0)
    flat = pd.Series([10.0] * n, index=idx)
    assert ind.chaikin_money_flow(flat, flat, flat, vol, 20).iloc[-1] == pytest.approx(0.0)
    zero_vol = pd.Series([0.0] * n, index=idx)
    assert np.isnan(ind.chaikin_money_flow(high, low, high, zero_vol, 20).iloc[-1])
