from __future__ import annotations

import csv
import io
from typing import Any


def candidates_csv(scan: dict[str, Any]) -> str:
    columns = [
        "ticker",
        "sector",
        "signal",
        "score",
        "coverage",
        "status",
        "close",
        "rvol_20",
        "return_20",
        "return_60",
        "relative_20",
        "relative_60",
        "sma_50",
        "sma_200",
        "rsi_14",
        "atr_14",
        "obv",
        "cmf_20",
        "data_timestamp",
        "error",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for candidate in scan.get("candidates", []):
        writer.writerow(candidate)
    return output.getvalue()


def markdown_report(scan: dict[str, Any]) -> str:
    lines = [
        "# Market Watcher scan",
        "",
        f"- Scan ID: {scan.get('scan_id') or 'not saved'}",
        f"- Timestamp: {scan.get('created_at')}",
        f"- Dataset: **{str(scan.get('data_source', 'unknown')).upper()}**",
        f"- Benchmark: {scan.get('benchmark')}",
        "",
        "> Scores are heuristic research rankings, not probabilities of profit or investment advice.",
        "> Price/volume indicators are buying-pressure proxies, not confirmed institutional inflows.",
        "",
        "| Ticker | Sector | Signal | Score | 20d return | 20d relative | RVOL20 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in scan.get("candidates", []):
        lines.append(
            "| {ticker} | {sector} | {signal} | {score} | {return_20} | {relative_20} | {rvol_20} |".format(
                ticker=row.get("ticker", ""),
                sector=row.get("sector", ""),
                signal=row.get("signal", ""),
                score=row.get("score", "—"),
                return_20=_percent(row.get("return_20")),
                relative_20=_percent(row.get("relative_20")),
                rvol_20=row.get("rvol_20", "—"),
            )
        )
    lines.extend(["", "## Data limitations", ""])
    lines.extend(f"- {limitation}" for limitation in scan.get("limitations", []))
    lines.extend(["", "## Unavailable evidence providers", ""])
    lines.extend(
        f"- {name}: unavailable until a provider is connected."
        for name in ("ETF net flows", "SEC disclosures", "options flow", "news")
    )
    return "\n".join(lines) + "\n"


def _percent(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"
