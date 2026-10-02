from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_watcher.config import load_config
from market_watcher.ollama import explain_with_ollama
from market_watcher.providers import DemoProvider, YFinanceProvider
from market_watcher.reports import candidates_csv, markdown_report
from market_watcher.scanner import scan_market
from market_watcher.storage import list_scans, load_scan, save_scan


st.set_page_config(page_title="Market Watcher", layout="wide")
st.title("Market Watcher")
st.caption(
    "Local research rankings only. Price/volume signals are buying-pressure proxies, "
    "not confirmed institutional inflows or probabilities of profit."
)
config = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
database_setting = Path(config.storage.get("database", "market_watcher.sqlite"))
database = database_setting if database_setting.is_absolute() else config.path.parent / database_setting

with st.sidebar:
    st.header("Scan controls")
    demo_mode = st.toggle("Use bundled demo data", value=True)
    if st.button("Run market scan", type="primary"):
        with st.spinner("Scanning configured universe..."):
            provider = DemoProvider() if demo_mode else YFinanceProvider(
                attempts=int(config.data.get("retries", 3)),
                retry_delay=float(config.data.get("retry_delay_seconds", 1)),
                fallback_ticker_limit=int(config.data.get("fallback_ticker_limit", 20)),
            )
            result = scan_market(config, provider, demo=demo_mode)
            save_scan(database, result)
            st.session_state["active_scan"] = result

    scans = list_scans(database)
    if scans:
        scan_ids = [scan["scan_id"] for scan in scans]
        selected_id = st.selectbox("Saved scan", scan_ids, format_func=lambda value: f"Scan {value}")
        if st.button("Load selected scan"):
            st.session_state["active_scan"] = load_scan(database, selected_id)

scan = st.session_state.get("active_scan")
if scan is None:
    scans = list_scans(database)
    if scans:
        scan = load_scan(database, scans[0]["scan_id"])
        st.session_state["active_scan"] = scan
if not scan:
    st.info("Run a demo scan to explore the dashboard, or use the CLI for a live scan.")
    st.stop()

st.caption(
    f"Scan {scan.get('scan_id') or ''} · {scan.get('data_source', 'unknown').upper()} data · "
    f"as of {scan.get('created_at')} · Benchmark {scan.get('benchmark')}"
)
if scan.get("data_source") == "demo":
    st.info("DEMO RESULTS: deterministic synthetic sample data; these are not live market observations.")
else:
    st.warning("LIVE DATA: Yahoo Finance availability, coverage, and timestamps can be delayed or incomplete.")

candidates = scan.get("candidates", [])
okay = [row for row in candidates if row.get("status") == "ok"]
frame = pd.DataFrame(okay)
if frame.empty:
    st.error("No usable candidate price histories were returned.")
else:
    left, middle, right = st.columns(3)
    left.metric("Candidates with data", len(okay))
    middle.metric("BUY", sum(row.get("signal") == "BUY" for row in okay))
    right.metric("WATCH", sum(row.get("signal") == "WATCH" for row in okay))

    st.subheader("Sector rankings")
    if {"sector", "score"}.issubset(frame.columns):
        sectors = frame.groupby("sector", as_index=False).agg(
            average_score=("score", "mean"), candidates=("ticker", "count"), buy_candidates=("signal", lambda values: int((values == "BUY").sum()))
        )
        st.dataframe(sectors.sort_values("average_score", ascending=False), use_container_width=True, hide_index=True)

    st.subheader("Top research candidates")
    display_columns = [
        name for name in ("ticker", "sector", "signal", "score", "coverage", "return_20", "relative_20", "rvol_20", "rsi_14", "cmf_20", "data_timestamp")
        if name in frame
    ]
    ranked = frame.sort_values("score", ascending=False)
    st.dataframe(ranked[display_columns].head(20), use_container_width=True, hide_index=True)

    st.subheader("Signal breakdown")
    selected_ticker = st.selectbox("Candidate", ranked["ticker"].tolist())
    candidate = next(row for row in okay if row["ticker"] == selected_ticker)
    st.json(candidate.get("factors", {}))
    st.caption(candidate.get("pressure_label", "Buying-pressure proxy, not confirmed institutional inflows."))

    if st.button("Explain with local Ollama"):
        explanation = explain_with_ollama(candidate, config.ollama)
        if explanation["status"] == "available":
            st.write(explanation["text"])
        else:
            st.warning(explanation["text"])

    st.subheader("Price history")
    with st.spinner("Loading chart history..."):
        provider = DemoProvider() if scan.get("data_source") == "demo" else YFinanceProvider(
            attempts=int(config.data.get("retries", 3)),
            retry_delay=float(config.data.get("retry_delay_seconds", 1)),
            fallback_ticker_limit=int(config.data.get("fallback_ticker_limit", 20)),
        )
        prices = provider.fetch_history([selected_ticker], str(config.data.get("period", "2y"))).get(selected_ticker)
    if prices is not None and not prices.empty:
        chart = prices["Close"].to_frame("Adjusted close")
        chart["SMA 50"] = chart["Adjusted close"].rolling(50, min_periods=50).mean()
        chart["SMA 200"] = chart["Adjusted close"].rolling(200, min_periods=200).mean()
        st.line_chart(chart, y_label="Price")
    else:
        st.warning("Price history is unavailable for this chart.")

st.subheader("Data limitations")
for limitation in scan.get("limitations", []):
    st.write(f"- {limitation}")
st.write("Optional evidence providers:", scan.get("optional_evidence", {}))

st.download_button("Download CSV", candidates_csv(scan), "market-watcher.csv", "text/csv")
st.download_button("Download Markdown report", markdown_report(scan), "market-watcher.md", "text/markdown")
