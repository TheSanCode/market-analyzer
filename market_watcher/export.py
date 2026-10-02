"""CSV and Markdown export of scan results."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .scanner import SIGNAL_DISCLAIMER, ScanResult

METRIC_COLUMNS = [
    "close",
    "change_1d",
    "rvol",
    "rel_return_20d",
    "rel_return_63d",
    "sma50",
    "sma200",
    "rsi",
    "atr",
    "atr_pct",
    "obv_trend",
    "cmf",
    "sessions",
]


def results_frame(scan: ScanResult) -> pd.DataFrame:
    rows = []
    for r in scan.results:
        row = {
            "scan_id": scan.scan_id,
            "scan_started_utc": scan.started_at,
            "rank": r.rank,
            "ticker": r.ticker,
            "label": r.label,
            "score": r.score,
            "status": r.status,
            "last_bar": r.last_bar,
            "fetched_at_utc": r.fetched_at,
            "stale": r.stale,
            "simulated": r.simulated,
            "source": r.source,
        }
        for k in METRIC_COLUMNS:
            row[k] = r.metrics.get(k)
        row["risks"] = "; ".join(r.risks)
        row["missing"] = "; ".join(r.missing)
        row["warnings"] = "; ".join(r.warnings)
        row["error"] = r.error
        row["explanation"] = r.explanation
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in ("scan_id", "rank", "sessions"):
        if col in df:
            df[col] = df[col].astype("Int64")
    return df


def _md(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _fmt(v: object, spec: str) -> str:
    if v is None:
        return "n/a"
    try:
        return format(v, spec)
    except (TypeError, ValueError):
        return str(v)


def to_markdown(scan: ScanResult) -> str:
    lines: list[str] = []
    title = "Market Watcher scan"
    if scan.simulated:
        title += " - SIMULATED DEMO DATA"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> {SIGNAL_DISCLAIMER}")
    lines.append("")
    lines.append(f"- Scan id: {scan.scan_id if scan.scan_id is not None else 'unsaved'}")
    lines.append(f"- Started (UTC): {scan.started_at}")
    lines.append(f"- Finished (UTC): {scan.finished_at}")
    lines.append(f"- Provider: {_md(scan.provider)}")
    lines.append(
        f"- Benchmark: {_md(scan.benchmark)} (last bar {scan.benchmark_last_bar or 'unavailable'})"
    )
    lines.append(f"- Analysed: {len(scan.ok)}, failed: {len(scan.failed)}")
    for n in scan.notes:
        lines.append(f"- Note: {_md(n)}")
    lines.append("")
    lines.append("## Rankings")
    lines.append("")
    lines.append(
        "| Rank | Ticker | Label | Score | RVOL | Rel 20d | Rel 63d | RSI | CMF | "
        "ATR % | Last bar | Stale |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in scan.ok:
        m = r.metrics
        lines.append(
            f"| {r.rank or '-'} | {_md(r.ticker)} | {r.label} | {_fmt(r.score, '.1f')} | "
            f"{_fmt(m.get('rvol'), '.2f')} | {_fmt(m.get('rel_return_20d'), '+.1%')} | "
            f"{_fmt(m.get('rel_return_63d'), '+.1%')} | {_fmt(m.get('rsi'), '.1f')} | "
            f"{_fmt(m.get('cmf'), '+.3f')} | {_fmt(m.get('atr_pct'), '.1f')} | "
            f"{r.last_bar or 'n/a'} | {'yes' if r.stale else 'no'} |"
        )
    if scan.failed:
        lines.append("")
        lines.append("## Failed tickers")
        lines.append("")
        for r in scan.failed:
            lines.append(f"- **{_md(r.ticker)}**: {_md(r.error)}")
    lines.append("")
    lines.append("## Details")
    for r in scan.ok:
        lines.append("")
        lines.append(f"### {_md(r.ticker)} - {r.label} ({_fmt(r.score, '.1f')})")
        lines.append("")
        for e in r.evidence:
            sub = "missing" if e["sub_score"] is None else f"{e['sub_score']:+.2f}"
            lines.append(
                f"- {e['component']} (weight {e['weight']:g}, sub-score {sub}, "
                f"{e['points']:+.1f} pts): {_md(e['reason'])}"
            )
        for x in r.risks:
            lines.append(f"- Risk: {_md(x)}")
        for x in r.missing:
            lines.append(f"- Missing: {_md(x)}")
        for x in r.warnings:
            lines.append(f"- Data warning: {_md(x)}")
        if r.explanation:
            lines.append("")
            lines.append("LLM explanation (generated locally from the evidence above):")
            lines.append("")
            for ln in r.explanation.splitlines():
                lines.append(f"> {ln}")
    lines.append("")
    return "\n".join(lines)


def export_scan(scan: ScanResult, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = scan.started_at.replace(":", "").replace("-", "").replace("+0000", "Z")
    stem = f"scan_{scan.scan_id if scan.scan_id is not None else 'unsaved'}_{stamp}"
    if scan.simulated:
        stem += "_SIMULATED"
    csv_path = out / f"{stem}.csv"
    md_path = out / f"{stem}.md"
    results_frame(scan).to_csv(csv_path, index=False)
    md_path.write_text(to_markdown(scan), encoding="utf-8")
    return csv_path, md_path
