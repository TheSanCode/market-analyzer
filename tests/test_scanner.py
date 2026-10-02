from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from market_watcher import storage
from market_watcher.cli import apply_demo, main
from market_watcher.config import AppConfig
from market_watcher.data import (
    DataQualityError,
    DemoProvider,
    PriceData,
    ProviderError,
    YFinanceProvider,
    clean_ohlcv,
    is_stale,
)
from market_watcher.export import export_scan, results_frame, to_markdown
from market_watcher.scanner import run_scan
from market_watcher.scoring import INSUFFICIENT

REF = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)


def make_frame(n=260, end="2024-12-31", drift=0.001, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=end, periods=n)
    close = 100 * np.cumprod(1 + rng.normal(drift, 0.01, n))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": rng.integers(1_000_000, 2_000_000, n).astype(float),
        },
        index=idx,
    )


class FakeProvider:
    name = "fake"
    simulated = False

    def __init__(self, frames, errors=None):
        self.frames = frames
        self.errors = errors or {}
        self.calls = {}

    def fetch(self, ticker, history_days):
        self.calls[ticker] = self.calls.get(ticker, 0) + 1
        if ticker in self.errors:
            raise self.errors[ticker]
        if ticker not in self.frames:
            raise ProviderError(f"{ticker}: unknown")
        frame, warnings = clean_ohlcv(self.frames[ticker], ticker)
        return PriceData(ticker, frame, self.name, False, REF, warnings)


def _cfg(universe, **data):
    cfg = AppConfig(universe=universe, benchmark="BENCH")
    cfg.ollama.enabled = False
    for k, v in data.items():
        setattr(cfg.data, k, v)
    return cfg


def test_one_failing_ticker_does_not_stop_scan():
    frames = {"BENCH": make_frame(seed=0), "GOOD": make_frame(seed=2)}
    errors = {"BOOM": RuntimeError("network down"), "TIMEOUT": TimeoutError("slow")}
    prov = FakeProvider(frames, errors)
    scan = run_scan(_cfg(["GOOD", "BOOM", "TIMEOUT", "NOPE"]), prov, reference_time=REF)
    by = {r.ticker: r for r in scan.results}
    assert by["GOOD"].status == "ok" and by["GOOD"].rank == 1
    assert by["BOOM"].status == "error" and "network down" in by["BOOM"].error
    assert by["TIMEOUT"].status == "error"
    assert by["NOPE"].status == "error"
    assert len(scan.ok) == 1 and len(scan.failed) == 3
    # retries=1 -> two attempts for provider errors
    assert prov.calls["BOOM"] == 2


def test_benchmark_failure_skips_relative_strength_only():
    prov = FakeProvider({"GOOD": make_frame(seed=2)}, {"BENCH": RuntimeError("down")})
    scan = run_scan(_cfg(["GOOD"]), prov, reference_time=REF)
    r = scan.results[0]
    assert r.status == "ok"
    assert scan.benchmark_last_bar is None
    assert any("benchmark BENCH unavailable" in n for n in scan.notes)
    rs = [e for e in r.evidence if e["component"] == "relative_strength"][0]
    assert rs["sub_score"] is None


def test_stale_ticker_flagged_and_not_buy():
    frames = {"BENCH": make_frame(), "OLD": make_frame(end="2024-12-10", drift=0.004)}
    scan = run_scan(_cfg(["OLD"]), FakeProvider(frames), reference_time=REF)
    r = scan.results[0]
    assert r.stale is True
    assert r.label != "BUY"
    assert any("stale" in m for m in r.missing)


def test_short_history_is_insufficient():
    frames = {"BENCH": make_frame(), "NEW": make_frame(n=30)}
    scan = run_scan(_cfg(["NEW"]), FakeProvider(frames), reference_time=REF)
    r = scan.results[0]
    assert r.label == INSUFFICIENT and r.rank is None
    assert any("sessions of history" in m for m in r.missing)


def test_missing_sma200_reported():
    frames = {"BENCH": make_frame(), "MID": make_frame(n=120)}
    scan = run_scan(_cfg(["MID"]), FakeProvider(frames), reference_time=REF)
    assert any("SMA200" in m for m in scan.results[0].missing)


def test_empty_and_malformed_data_are_isolated():
    bad_cols = make_frame().drop(columns=["Volume"])
    frames = {
        "BENCH": make_frame(),
        "EMPTY": pd.DataFrame(),
        "BADCOLS": bad_cols,
        "OK": make_frame(seed=5),
    }
    prov = FakeProvider(frames)
    scan = run_scan(_cfg(["EMPTY", "BADCOLS", "OK"]), prov, reference_time=REF)
    by = {r.ticker: r for r in scan.results}
    assert by["EMPTY"].status == "error" and "DataQualityError" in by["EMPTY"].error
    assert "missing columns" in by["BADCOLS"].error
    assert by["OK"].status == "ok"
    assert prov.calls["EMPTY"] == 1  # data-quality errors are not retried


def test_clean_ohlcv_handles_gaps_and_timezones():
    f = make_frame(n=40)
    f.index = f.index.tz_localize("America/New_York")
    f.iloc[5, f.columns.get_loc("Close")] = np.nan
    f.iloc[6, f.columns.get_loc("Volume")] = np.nan
    f.iloc[7, f.columns.get_loc("High")] = np.nan
    f = pd.concat([f, f.iloc[[-1]]])  # duplicate last row
    out, warnings = clean_ohlcv(f, "X")
    assert out.index.tz is None
    assert len(out) == 39
    assert out["Volume"].isna().sum() == 0
    assert (out["High"] >= out["Low"]).all()
    assert any("missing/invalid close" in w for w in warnings)
    assert any("missing volume" in w for w in warnings)
    with pytest.raises(DataQualityError):
        clean_ohlcv(pd.DataFrame({"Close": [np.nan]}), "Y")


def test_is_stale():
    assert not is_stale(datetime(2024, 12, 27).date(), REF, 4)
    assert is_stale(datetime(2024, 12, 20).date(), REF, 4)


def test_yfinance_provider_wraps_errors(monkeypatch):
    import sys
    import types

    class Boom:
        def __init__(self, t):
            pass

        def history(self, **kw):
            raise ConnectionError("rate limited")

    class Empty(Boom):
        def history(self, **kw):
            return pd.DataFrame()

    fake = types.SimpleNamespace(Ticker=Boom)
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    with pytest.raises(ProviderError, match="rate limited"):
        YFinanceProvider().fetch("AAPL", 100)
    fake.Ticker = Empty
    with pytest.raises(ProviderError, match="no data"):
        YFinanceProvider().fetch("AAPL", 100)


def test_explainer_failure_does_not_break_scan():
    class BadExplainer:
        def explain(self, result):
            raise RuntimeError("model crashed")

    cfg = _cfg(["GOOD"])
    cfg.ollama.enabled = True
    prov = FakeProvider({"BENCH": make_frame(), "GOOD": make_frame(seed=2)})
    scan = run_scan(cfg, prov, BadExplainer(), reference_time=REF)
    assert scan.results[0].status == "ok"
    assert scan.results[0].explanation is None
    assert any("LLM explanation skipped" in n for n in scan.notes)


def test_demo_scan_storage_and_export(tmp_path):
    cfg = apply_demo(AppConfig())
    cfg.ollama.enabled = False
    scan = run_scan(cfg, DemoProvider())
    assert scan.simulated
    assert "SIMULATED" in scan.notes[0]
    by = {r.ticker: r for r in scan.results}
    assert by["DEMO-ACCUM"].label == "BUY"
    assert by["DEMO-DISTRIB"].label == "SELL/AVOID"
    assert by["DEMO-STALE"].stale
    assert by["DEMO-MISSING"].status == "error"
    assert by["DEMO-GAPPY"].warnings

    db = tmp_path / "h.db"
    sid = storage.save_scan(db, scan)
    loaded = storage.load_scan(db, sid)
    assert loaded is not None and loaded.simulated
    assert [r.ticker for r in loaded.results] == [r.ticker for r in scan.results]
    assert loaded.results[0].evidence == scan.results[0].evidence
    assert storage.list_scans(db)[0]["id"] == sid
    assert storage.ticker_history(db, "DEMO-ACCUM")[0]["label"] == "BUY"
    storage.update_explanation(db, sid, "DEMO-ACCUM", "text")
    assert storage.load_scan(db).results[0].explanation == "text"

    csv_path, md_path = export_scan(loaded, tmp_path / "out")
    assert "SIMULATED" in csv_path.name
    df = pd.read_csv(csv_path)
    assert df["simulated"].all()
    md = md_path.read_text(encoding="utf-8")
    assert "SIMULATED DEMO DATA" in md
    assert "not verified institutional money flows" in md
    assert "DEMO-MISSING" in md
    assert len(results_frame(loaded)) == len(loaded.results)
    assert to_markdown(loaded).startswith("# Market Watcher scan")


def test_cli_demo_scan_without_ollama(tmp_path, capsys):
    db = tmp_path / "cli.db"
    # Ollama enabled by default but unreachable port -> scan still succeeds.
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text('[ollama]\nbase_url = "http://127.0.0.1:9"\n', encoding="utf-8")
    rc = main(
        [
            "-c",
            str(cfg_file),
            "--db",
            str(db),
            "scan",
            "--demo",
            "--export-dir",
            str(tmp_path / "exp"),
        ]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert "SIMULATED" in out.out
    assert "LLM explanations disabled" in out.err
    assert main(["--db", str(db), "history"]) == 0
    assert main(["--db", str(db), "export", "--out", str(tmp_path / "exp2")]) == 0
    assert list((tmp_path / "exp2").glob("*.md"))
