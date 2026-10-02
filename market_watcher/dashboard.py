"""Streamlit dashboard. Run with:  streamlit run app.py"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from market_watcher import storage
from market_watcher.cli import apply_demo
from market_watcher.config import AppConfig, ConfigError, load_config
from market_watcher.data import DemoProvider, YFinanceProvider, make_provider
from market_watcher.export import results_frame, to_markdown
from market_watcher.llm import OllamaClient, OllamaError
from market_watcher.scanner import SIGNAL_DISCLAIMER, indicator_frame, run_scan

DEFAULT_CONFIG = os.environ.get("MARKET_WATCHER_CONFIG", "config.toml")

TABLE_COLUMNS = [
    "rank",
    "ticker",
    "label",
    "score",
    "rvol",
    "change_1d",
    "rel_return_20d",
    "rel_return_63d",
    "rsi",
    "cmf",
    "obv_trend",
    "atr_pct",
    "last_bar",
    "stale",
    "fetched_at_utc",
    "status",
    "missing",
    "risks",
    "error",
]


def _load_config(path: str) -> AppConfig:
    if path and Path(path).exists():
        return load_config(path)
    return AppConfig()


@st.cache_data(ttl=900, show_spinner=False)
def _chart_data(ticker: str, simulated: bool, history_days: int, demo_path: str):
    provider = DemoProvider(demo_path or None) if simulated else YFinanceProvider()
    pdata = provider.fetch(ticker, history_days)
    return pdata.frame, pdata.fetched_at.isoformat(timespec="seconds")


def _sidebar(cfg_path: str) -> tuple[AppConfig, int | None]:
    st.sidebar.header("Scan")
    try:
        cfg = _load_config(cfg_path)
    except ConfigError as exc:
        st.sidebar.error(f"Config error: {exc}")
        cfg = AppConfig()
    mode = st.sidebar.radio("Data", ["Live (yfinance)", "Demo (SIMULATED)"], index=0)
    use_llm = st.sidebar.checkbox(
        f"Explain top {cfg.ollama.explain_top_n} with Ollama ({cfg.ollama.model})",
        value=False,
    )
    if st.sidebar.button("Run scan now", type="primary"):
        run_cfg = _load_config(cfg_path)
        if mode.startswith("Demo"):
            apply_demo(run_cfg)
        else:
            run_cfg.data.provider = "yfinance"
        run_cfg.ollama.enabled = use_llm
        explainer = None
        if use_llm:
            client = OllamaClient(run_cfg.ollama)
            ok, msg = client.check()
            if ok:
                explainer = client
            else:
                st.sidebar.warning(f"Ollama unavailable, scanning without it: {msg}")
        with st.spinner("Scanning..."):
            provider = make_provider(run_cfg.data.provider, run_cfg.data.demo_path)
            scan = run_scan(run_cfg, provider, explainer)
            storage.save_scan(cfg.database_path, scan)
        st.session_state["scan_id"] = scan.scan_id
        st.sidebar.success(f"Saved scan {scan.scan_id}")

    st.sidebar.header("History")
    scans = storage.list_scans(cfg.database_path, limit=100)
    if not scans:
        return cfg, None
    options = {
        f"#{s['id']}  {s['started_at']}  {'SIMULATED' if s['simulated'] else s['provider']}"
        f"  ok={s['n_ok']} failed={s['n_failed']}": s["id"]
        for s in scans
    }
    ids = list(options.values())
    wanted = st.session_state.get("scan_id", ids[0])
    idx = ids.index(wanted) if wanted in ids else 0
    choice = st.sidebar.selectbox("Saved scans", list(options.keys()), index=idx)
    return cfg, options[choice]


def _ticker_detail(cfg: AppConfig, scan, ticker: str) -> None:
    r = next(x for x in scan.results if x.ticker == ticker)
    st.subheader(
        f"{ticker}: {r.label}" + (f" (score {r.score:.1f})" if r.score is not None else "")
    )
    st.caption(
        f"Last bar at scan: {r.last_bar or 'n/a'} | fetched {r.fetched_at or 'n/a'} UTC | "
        f"source {r.source}{' | STALE' if r.stale else ''}"
    )
    if r.status != "ok":
        st.error(r.error)
        return

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Evidence (score components)**")
        st.dataframe(pd.DataFrame(r.evidence), hide_index=True, width="stretch")
    with c2:
        st.markdown("**Risks**")
        for x in r.risks or ["none flagged"]:
            st.write(f"- {x}")
        st.markdown("**Missing information**")
        for x in r.missing or ["none"]:
            st.write(f"- {x}")
        if r.warnings:
            st.markdown("**Data warnings**")
            for x in r.warnings:
                st.write(f"- {x}")

    st.markdown("**Local LLM explanation** (explains calculated evidence only)")
    if r.explanation:
        st.info(r.explanation)
    if st.button(f"Explain {ticker} with Ollama ({cfg.ollama.model})"):
        try:
            text = OllamaClient(cfg.ollama).explain(r.to_dict())
            storage.update_explanation(cfg.database_path, scan.scan_id, ticker, text)
            st.info(text)
        except (OllamaError, ValueError) as exc:
            st.warning(f"Explanation unavailable: {exc}. Rankings are unaffected.")

    try:
        frame, fetched = _chart_data(
            ticker, scan.simulated, cfg.data.history_days, cfg.data.demo_path
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Chart data unavailable: {exc}")
        return
    ind = indicator_frame(frame, cfg.indicators)
    st.caption(
        f"Charts use data fetched {fetched} UTC (last bar {frame.index[-1].date()}); "
        "this may be newer than the data used in the selected scan."
        + (" SIMULATED DATA." if scan.simulated else "")
    )
    fast, slow = f"SMA{cfg.indicators.sma_fast}", f"SMA{cfg.indicators.sma_slow}"
    st.markdown("Price with moving averages")
    st.line_chart(ind[["Close", fast, slow]])
    a, b = st.columns(2)
    with a:
        st.markdown("Volume")
        st.bar_chart(ind[["Volume"]].tail(120))
        st.markdown("RSI")
        st.line_chart(ind[["RSI"]].tail(250))
    with b:
        st.markdown("Relative volume vs preceding sessions")
        st.line_chart(ind[["RelVolume"]].tail(120))
        st.markdown("Chaikin Money Flow")
        st.line_chart(ind[["CMF"]].tail(250))
    st.markdown("On-Balance Volume")
    st.line_chart(ind[["OBV"]])

    hist = storage.ticker_history(cfg.database_path, ticker, limit=200)
    if len(hist) > 1:
        st.markdown("Score history across saved scans")
        h = pd.DataFrame(hist)
        h["started_at"] = pd.to_datetime(h["started_at"])
        st.line_chart(h.set_index("started_at")[["score"]])


def main() -> None:
    st.set_page_config(page_title="Market Watcher", layout="wide")
    st.title("Market Watcher")
    st.caption(SIGNAL_DISCLAIMER + " No broker connection; no orders are placed.")
    cfg_path = st.sidebar.text_input("Config file", DEFAULT_CONFIG)
    cfg, scan_id = _sidebar(cfg_path)
    if scan_id is None:
        st.info(
            "No saved scans yet. Use 'Run scan now' (try Demo first) or run "
            "`python -m market_watcher scan`."
        )
        return
    scan = storage.load_scan(cfg.database_path, scan_id)
    if scan is None:
        st.error("Scan not found.")
        return

    if scan.simulated:
        st.error("SIMULATED DEMO DATA - these are not real market prices or securities.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Scan started (UTC)", scan.started_at.replace("+00:00", ""))
    m2.metric("Benchmark last bar", f"{scan.benchmark} {scan.benchmark_last_bar or 'n/a'}")
    m3.metric("Analysed", len(scan.ok))
    m4.metric("Failed", len(scan.failed))
    for n in scan.notes:
        st.warning(n)

    df = results_frame(scan)
    labels = st.multiselect(
        "Labels",
        ["BUY", "WATCH", "SELL/AVOID", "INSUFFICIENT DATA"],
        default=["BUY", "WATCH", "SELL/AVOID", "INSUFFICIENT DATA"],
    )
    view = df[df["label"].isin(labels) | (df["status"] != "ok")]
    st.dataframe(
        view[[c for c in TABLE_COLUMNS if c in view.columns]],
        hide_index=True,
        width="stretch",
        column_config={
            "score": st.column_config.NumberColumn(format="%.1f"),
            "rvol": st.column_config.NumberColumn("rel. volume", format="%.2fx"),
            "change_1d": st.column_config.NumberColumn(format="percent"),
            "rel_return_20d": st.column_config.NumberColumn("vs bench 20d", format="percent"),
            "rel_return_63d": st.column_config.NumberColumn("vs bench 63d", format="percent"),
            "rsi": st.column_config.NumberColumn(format="%.1f"),
            "cmf": st.column_config.NumberColumn(format="%.3f"),
            "obv_trend": st.column_config.NumberColumn(format="%.2f"),
            "atr_pct": st.column_config.NumberColumn("ATR %", format="%.1f"),
        },
    )
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download CSV", df.to_csv(index=False), f"scan_{scan.scan_id}.csv", "text/csv"
    )
    d2.download_button(
        "Download Markdown", to_markdown(scan), f"scan_{scan.scan_id}.md", "text/markdown"
    )

    tickers = [r.ticker for r in scan.results]
    if tickers:
        _ticker_detail(cfg, scan, st.selectbox("Ticker detail", tickers))
