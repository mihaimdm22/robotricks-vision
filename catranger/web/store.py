"""DistanceStore: a tiny SQLite log of distance readings over time.

The control loop appends one row per (throttled) sample; the web layer reads the
recent series for the live history chart and `GET /api/history`. Plain stdlib
sqlite3 — no external deps, survives restarts. A single connection guarded by a
lock (the control thread writes; request-handler threads read).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS distance_samples (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,   -- unix epoch seconds (wall clock)
    est_m     REAL,               -- fused metric distance estimate
    lo        REAL,               -- CI lower bound (m)
    hi        REAL,               -- CI upper bound (m)
    gt_cm     REAL,               -- HC-SR04 ground truth (cm), NULL if none
    target_id INTEGER,
    target_ids TEXT,
    mode      TEXT
);
CREATE INDEX IF NOT EXISTS idx_distance_ts ON distance_samples (ts);
"""

_COLS = ("ts", "est_m", "lo", "hi", "gt_cm", "target_id", "target_ids", "mode")


class DistanceStore:
    def __init__(self, path: str = "outputs/history.sqlite3") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the control thread writes, request threads read;
        # all access is serialized by self._lock so this is safe.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            # WAL keeps readers from blocking the single writer (no-op on :memory:);
            # synchronous=NORMAL is safe under WAL and avoids an fsync per commit,
            # so the ~4 Hz write from the control thread can't stall the loop.
            try:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            except sqlite3.Error:
                pass
            self._conn.commit()

    def _migrate(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(distance_samples)")}
        if "target_ids" not in cols:
            self._conn.execute("ALTER TABLE distance_samples ADD COLUMN target_ids TEXT")

    def record(
        self,
        ts: float,
        est_m: float | None,
        lo: float | None,
        hi: float | None,
        gt_cm: float | None,
        target_id: int | None,
        mode: str | None,
        target_ids: list[int] | None = None,
    ) -> None:
        ids_json = json.dumps(target_ids) if target_ids else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO distance_samples "
                "(ts, est_m, lo, hi, gt_cm, target_id, target_ids, mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, est_m, lo, hi, gt_cm, target_id, ids_json, mode),
            )
            self._conn.commit()

    def recent(self, limit: int = 600, since: float | None = None) -> list[dict[str, Any]]:
        """Newest-up-to-`limit` samples in chronological (ascending ts) order.
        If `since` is given, only rows with ts > since (still capped by limit)."""
        limit = max(1, min(int(limit), 10000))
        with self._lock:
            if since is not None:
                rows = self._conn.execute(
                    "SELECT ts, est_m, lo, hi, gt_cm, target_id, target_ids, mode "
                    "FROM distance_samples "
                    "WHERE ts > ? ORDER BY ts ASC LIMIT ?",
                    (float(since), limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT ts, est_m, lo, hi, gt_cm, target_id, target_ids, mode "
                    "FROM distance_samples "
                    "ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                rows = list(reversed(rows))
        out: list[dict[str, Any]] = []
        for r in rows:
            row = {c: r[c] for c in _COLS}
            raw_ids = row.pop("target_ids", None)
            if raw_ids:
                try:
                    row["target_ids"] = json.loads(str(raw_ids))
                except json.JSONDecodeError:
                    row["target_ids"] = []
            else:
                row["target_ids"] = [row["target_id"]] if row.get("target_id") is not None else []
            out.append(row)
        return out

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
