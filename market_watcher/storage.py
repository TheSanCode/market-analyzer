"""SQLite scan history."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .scanner import ScanResult, TickerResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    simulated INTEGER NOT NULL,
    benchmark TEXT NOT NULL,
    benchmark_last_bar TEXT,
    universe TEXT NOT NULL,
    notes TEXT NOT NULL,
    config TEXT NOT NULL,
    n_ok INTEGER NOT NULL,
    n_failed INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    status TEXT NOT NULL,
    rank INTEGER,
    label TEXT NOT NULL,
    score REAL,
    last_bar TEXT,
    fetched_at TEXT,
    stale INTEGER NOT NULL,
    source TEXT,
    simulated INTEGER NOT NULL,
    error TEXT,
    metrics TEXT NOT NULL,
    evidence TEXT NOT NULL,
    risks TEXT NOT NULL,
    missing TEXT NOT NULL,
    warnings TEXT NOT NULL,
    explanation TEXT,
    PRIMARY KEY (scan_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_results_ticker ON results(ticker, scan_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def save_scan(path: str | Path, scan: ScanResult) -> int:
    with closing(connect(path)) as conn, conn:
        cur = conn.execute(
            """INSERT INTO scans (started_at, finished_at, provider, simulated, benchmark,
                   benchmark_last_bar, universe, notes, config, n_ok, n_failed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                scan.started_at,
                scan.finished_at,
                scan.provider,
                int(scan.simulated),
                scan.benchmark,
                scan.benchmark_last_bar,
                json.dumps(scan.universe),
                json.dumps(scan.notes),
                json.dumps(scan.config),
                len(scan.ok),
                len(scan.failed),
            ),
        )
        scan_id = int(cur.lastrowid)
        conn.executemany(
            """INSERT INTO results (scan_id, ticker, status, rank, label, score, last_bar,
                   fetched_at, stale, source, simulated, error, metrics, evidence, risks,
                   missing, warnings, explanation)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    scan_id,
                    r.ticker,
                    r.status,
                    r.rank,
                    r.label,
                    r.score,
                    r.last_bar,
                    r.fetched_at,
                    int(r.stale),
                    r.source,
                    int(r.simulated),
                    r.error,
                    json.dumps(r.metrics),
                    json.dumps(r.evidence),
                    json.dumps(r.risks),
                    json.dumps(r.missing),
                    json.dumps(r.warnings),
                    r.explanation,
                )
                for r in scan.results
            ],
        )
    scan.scan_id = scan_id
    return scan_id


def list_scans(path: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    with closing(connect(path)) as conn:
        rows = conn.execute(
            """SELECT id, started_at, finished_at, provider, simulated, benchmark,
                      n_ok, n_failed FROM scans ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_scan(path: str | Path, scan_id: int | None = None) -> ScanResult | None:
    """Load a scan by id, or the latest scan when ``scan_id`` is None."""
    if not Path(path).exists():
        return None
    with closing(connect(path)) as conn:
        if scan_id is None:
            row = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        else:
            row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if row is None:
            return None
        rrows = conn.execute(
            "SELECT * FROM results WHERE scan_id = ? ORDER BY rank IS NULL, rank, status, ticker",
            (row["id"],),
        ).fetchall()
    results = [
        TickerResult(
            ticker=r["ticker"],
            status=r["status"],
            label=r["label"],
            score=r["score"],
            rank=r["rank"],
            metrics=json.loads(r["metrics"]),
            evidence=json.loads(r["evidence"]),
            risks=json.loads(r["risks"]),
            missing=json.loads(r["missing"]),
            warnings=json.loads(r["warnings"]),
            error=r["error"],
            last_bar=r["last_bar"],
            fetched_at=r["fetched_at"],
            stale=bool(r["stale"]),
            source=r["source"],
            simulated=bool(r["simulated"]),
            explanation=r["explanation"],
        )
        for r in rrows
    ]
    return ScanResult(
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        provider=row["provider"],
        simulated=bool(row["simulated"]),
        benchmark=row["benchmark"],
        benchmark_last_bar=row["benchmark_last_bar"],
        universe=json.loads(row["universe"]),
        results=results,
        notes=json.loads(row["notes"]),
        config=json.loads(row["config"]),
        scan_id=row["id"],
    )


def update_explanation(path: str | Path, scan_id: int, ticker: str, text: str) -> None:
    with closing(connect(path)) as conn, conn:
        conn.execute(
            "UPDATE results SET explanation = ? WHERE scan_id = ? AND ticker = ?",
            (text, scan_id, ticker),
        )


def ticker_history(path: str | Path, ticker: str, limit: int = 100) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    with closing(connect(path)) as conn:
        rows = conn.execute(
            """SELECT s.id AS scan_id, s.started_at, s.simulated, r.label, r.score,
                      r.rank, r.last_bar, r.stale, r.status
               FROM results r JOIN scans s ON s.id = r.scan_id
               WHERE r.ticker = ? ORDER BY s.id DESC LIMIT ?""",
            (ticker, limit),
        ).fetchall()
    return [dict(r) for r in rows]
