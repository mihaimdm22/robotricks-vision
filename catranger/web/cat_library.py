"""Persistent cat library — saved face thumbnails and last-known pose for re-acquire."""

from __future__ import annotations

import base64
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    thumb_blob      BLOB,
    last_tracker_id INTEGER,
    last_conf       REAL,
    last_dist_m     REAL,
    last_bearing_deg REAL,
    last_seen_ts    REAL,
    sighting_count  INTEGER NOT NULL DEFAULT 1,
    created_ts      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cats_last_seen ON cats (last_seen_ts DESC);
"""


class CatLibraryStore:
    """SQLite-backed catalog of seen cats (faces + metadata). Thread-safe."""

    def __init__(self, path: str = "outputs/cat_library.sqlite3") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            try:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            except sqlite3.Error:
                pass
            self._conn.commit()

    def list_cats(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, last_tracker_id, last_conf, last_dist_m, "
                "last_bearing_deg, last_seen_ts, sighting_count, created_ts, "
                "length(thumb_blob) AS thumb_bytes "
                "FROM cats ORDER BY last_seen_ts DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(self._row_to_summary(row))
        return out

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM cats").fetchone()
        return int(row["n"]) if row else 0

    def get(self, cat_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, thumb_blob, last_tracker_id, last_conf, last_dist_m, "
                "last_bearing_deg, last_seen_ts, sighting_count, created_ts "
                "FROM cats WHERE id = ?",
                (int(cat_id),),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_detail(row)

    def get_thumb_bytes(self, cat_id: int) -> bytes | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT thumb_blob FROM cats WHERE id = ?",
                (int(cat_id),),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return bytes(row[0])

    def match_by_thumb(
        self,
        thumb_jpeg: bytes,
        *,
        threshold: float = 0.55,
        limit: int = 200,
        similarity: Callable[[bytes, bytes], float] | None = None,
    ) -> int | None:
        """Return an existing library row id if ``thumb_jpeg`` matches a saved face."""
        if not thumb_jpeg:
            return None
        score_fn = similarity
        if score_fn is None:
            from catranger.web.cat_match import thumb_similarity

            score_fn = thumb_similarity
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, thumb_blob FROM cats WHERE thumb_blob IS NOT NULL "
                "ORDER BY last_seen_ts DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        best_id: int | None = None
        best_score = -1.0
        for row in rows:
            blob = row["thumb_blob"]
            if not blob:
                continue
            score = score_fn(thumb_jpeg, bytes(blob))
            if score >= float(threshold) and score > best_score:
                best_score = score
                best_id = int(row["id"])
        return best_id

    def upsert_sighting(
        self,
        *,
        library_id: int | None,
        tracker_id: int,
        thumb_jpeg: bytes | None,
        conf: float,
        dist_m: float | None,
        bearing_deg: float,
        name: str | None = None,
    ) -> int:
        """Create or refresh a library row for this tracker sighting."""
        now = time.time()
        with self._lock:
            if library_id is not None:
                row = self._conn.execute(
                    "SELECT last_conf, thumb_blob FROM cats WHERE id = ?",
                    (int(library_id),),
                ).fetchone()
                if row is not None:
                    keep_thumb = row[1]
                    if thumb_jpeg and (keep_thumb is None or float(conf) >= float(row[0] or 0.0)):
                        keep_thumb = thumb_jpeg
                    self._conn.execute(
                        "UPDATE cats SET last_tracker_id=?, last_conf=?, last_dist_m=?, "
                        "last_bearing_deg=?, last_seen_ts=?, sighting_count=sighting_count+1, "
                        "thumb_blob=COALESCE(?, thumb_blob), name=COALESCE(?, name) "
                        "WHERE id=?",
                        (
                            int(tracker_id),
                            round(float(conf), 3),
                            dist_m,
                            round(float(bearing_deg), 1),
                            now,
                            keep_thumb,
                            name,
                            int(library_id),
                        ),
                    )
                    self._conn.commit()
                    return int(library_id)

            auto_name = name or f"Cat #{int(tracker_id)}"
            cur = self._conn.execute(
                "INSERT INTO cats "
                "(name, thumb_blob, last_tracker_id, last_conf, last_dist_m, "
                "last_bearing_deg, last_seen_ts, sighting_count, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    auto_name,
                    thumb_jpeg,
                    int(tracker_id),
                    round(float(conf), 3),
                    dist_m,
                    round(float(bearing_deg), 1),
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row_id = cur.lastrowid
            if row_id is None:
                raise RuntimeError("insert cat failed: no row id")
            return int(row_id)

    def rename(self, cat_id: int, name: str) -> bool:
        clean = name.strip()
        if not clean:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE cats SET name=? WHERE id=?",
                (clean, int(cat_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete(self, cat_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM cats WHERE id=?", (int(cat_id),))
            self._conn.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "last_tracker_id": row["last_tracker_id"],
            "last_conf": row["last_conf"],
            "last_dist_m": row["last_dist_m"],
            "last_bearing_deg": row["last_bearing_deg"],
            "last_seen_ts": row["last_seen_ts"],
            "sighting_count": int(row["sighting_count"]),
            "created_ts": row["created_ts"],
            "has_thumb": bool(row["thumb_bytes"]),
        }

    @staticmethod
    def _row_to_detail(row: sqlite3.Row) -> dict[str, Any]:
        thumb = row["thumb_blob"]
        thumb_b64 = base64.standard_b64encode(bytes(thumb)).decode("ascii") if thumb else None
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "last_tracker_id": row["last_tracker_id"],
            "last_conf": row["last_conf"],
            "last_dist_m": row["last_dist_m"],
            "last_bearing_deg": row["last_bearing_deg"],
            "last_seen_ts": row["last_seen_ts"],
            "sighting_count": int(row["sighting_count"]),
            "created_ts": row["created_ts"],
            "thumb_jpeg_b64": thumb_b64,
        }
