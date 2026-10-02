from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def initialize_database(path: str | Path) -> None:
    database_path = Path(path).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                data_source TEXT NOT NULL,
                result_json TEXT NOT NULL
            )
            """
        )


def save_scan(path: str | Path, scan: dict[str, Any]) -> int:
    initialize_database(path)
    created_at = scan.get("created_at") or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(Path(path).expanduser()) as connection:
        cursor = connection.execute(
            "INSERT INTO scans (created_at, data_source, result_json) VALUES (?, ?, ?)",
            (created_at, scan.get("data_source", "unknown"), json.dumps(scan, allow_nan=False)),
        )
        scan_id = int(cursor.lastrowid)
        scan["scan_id"] = scan_id
        connection.execute(
            "UPDATE scans SET result_json = ? WHERE scan_id = ?",
            (json.dumps(scan, allow_nan=False), scan_id),
        )
    return scan_id


def list_scans(path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    database_path = Path(path).expanduser()
    if not database_path.exists():
        return []
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT scan_id, created_at, data_source FROM scans ORDER BY scan_id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [{"scan_id": row[0], "created_at": row[1], "data_source": row[2]} for row in rows]


def load_scan(path: str | Path, scan_id: int) -> dict[str, Any] | None:
    database_path = Path(path).expanduser()
    if not database_path.exists():
        return None
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT result_json FROM scans WHERE scan_id = ?", (int(scan_id),)
        ).fetchone()
    return json.loads(row[0]) if row else None
