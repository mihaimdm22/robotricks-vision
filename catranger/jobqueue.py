"""Durable, crash-only job queue (WS-A1/A2) — stdlib sqlite3, single file, no broker.

Promotes the overnight runner from "archive after the fact" to a real state machine
(``queued -> running -> ok|fail|skipped|timeout``) that survives a parent-process
crash: on restart, jobs left ``running`` by a dead worker are reclaimed (requeued or
failed), so ``kill -9`` mid-sweep == a clean resume of the remaining work.

Ownership is explicit (the WS-A1 review fix): :meth:`recover_stale` reclaims only rows
this worker previously owned, OR rows whose heartbeat is stale beyond a TTL — never
every ``running`` row. That lets a second writer (e.g. the web ``EvalJob``,
``owner='web'``) share the same DB without the overnight runner stealing its live job.

Connection hygiene (review fix): ONE connection per process (never shared across
processes), WAL + ``busy_timeout``, and ``BEGIN IMMEDIATE`` for the atomic claim — the
``DistanceStore`` single-shared-connection idiom is NOT multi-process safe and is not
used here. ``history.py`` stays the zero-dep append-only archive; this is the queue.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

QUEUED = "queued"
RUNNING = "running"
TERMINAL_STATUSES = frozenset({"ok", "fail", "skipped", "timeout"})

# The one durable queue file, shared by the overnight runner (owner='overnight') and the
# web server's eval job (owner='web') — owner-scoping (recover_stale/fail_orphans) keeps
# each from disturbing the other's in-flight jobs.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "runs" / "jobqueue.sqlite3"

# A running row whose heartbeat is older than this (and owned by another worker) is
# treated as abandoned by a crash. Tunable per call.
_DEFAULT_STALE_TTL_S = 1800.0


@dataclass(frozen=True)
class Job:
    """A claimed unit of work handed back to the caller."""

    id: int
    run_key: str
    kind: str
    params: dict[str, Any]
    status: str
    attempts: int


class JobQueue:
    """A single-file SQLite durable queue. Open ONE per process; never share the
    connection across processes (open a fresh JobQueue in each)."""

    def __init__(self, db_path: str | Path, *, owner: str = "overnight") -> None:
        self.owner = owner
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> autocommit; we drive transactions explicitly so the
        # claim can use BEGIN IMMEDIATE (acquires the write lock up front, so two
        # workers never claim the same row).
        self._db = sqlite3.connect(self.path, isolation_level=None, timeout=30.0)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_key      TEXT UNIQUE NOT NULL,
                kind         TEXT NOT NULL,
                params       TEXT NOT NULL,
                status       TEXT NOT NULL,
                owner        TEXT NOT NULL DEFAULT '',
                attempts     INTEGER NOT NULL DEFAULT 0,
                created_at   REAL NOT NULL,
                started_at   REAL,
                heartbeat_at REAL,
                finished_at  REAL,
                metric       REAL,
                summary      TEXT NOT NULL DEFAULT ''
            )
            """
        )

    def close(self) -> None:
        self._db.close()

    # ---------------------------------------------------------------- enqueue
    def enqueue(self, kind: str, params: dict, run_key: str) -> bool:
        """Add a queued job. Idempotent: a ``run_key`` already present (in ANY status)
        is left untouched, so re-running the same plan resumes instead of duplicating.
        Returns True if a new row was inserted, False if it already existed."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO jobs (run_key, kind, params, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_key, str(kind), json.dumps(params, sort_keys=True), QUEUED, time.time()),
        )
        return cur.rowcount > 0

    # ------------------------------------------------------------------ claim
    def claim(self) -> Job | None:
        """Atomically claim the oldest queued job for this owner (status -> running,
        attempts += 1). Returns None if nothing is queued. BEGIN IMMEDIATE serializes
        claims across connections/processes, so a job is never claimed twice."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT id, run_key, kind, params, attempts FROM jobs "
                "WHERE status=? ORDER BY id LIMIT 1",
                (QUEUED,),
            ).fetchone()
            if row is None:
                self._db.execute("COMMIT")
                return None
            now = time.time()
            self._db.execute(
                "UPDATE jobs SET status=?, owner=?, attempts=attempts+1, "
                "started_at=?, heartbeat_at=? WHERE id=?",
                (RUNNING, self.owner, now, now, row["id"]),
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return Job(
            id=int(row["id"]),
            run_key=str(row["run_key"]),
            kind=str(row["kind"]),
            params=json.loads(row["params"]),
            status=RUNNING,
            attempts=int(row["attempts"]) + 1,
        )

    def heartbeat(self, job_id: int) -> None:
        """Refresh a running job's lease (only if THIS owner holds it). Used by a
        long-lived worker so another process's TTL sweep won't reclaim a live job."""
        self._db.execute(
            "UPDATE jobs SET heartbeat_at=? WHERE id=? AND owner=?",
            (time.time(), int(job_id), self.owner),
        )

    def complete(
        self, job_id: int, status: str, *, metric: float | None = None, summary: str = ""
    ) -> None:
        """Mark a job terminal (ok|fail|skipped|timeout) and release ownership."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(
                f"complete() needs a terminal status {sorted(TERMINAL_STATUSES)}, got {status!r}"
            )
        self._db.execute(
            "UPDATE jobs SET status=?, owner='', finished_at=?, metric=?, summary=? WHERE id=?",
            (status, time.time(), metric, summary, int(job_id)),
        )

    # ----------------------------------------- externally-managed jobs (WS-A7)
    def record_running(self, kind: str, params: dict, run_key: str) -> int:
        """Record an EXTERNALLY-run job (e.g. a web eval) directly as ``running`` owned by
        this queue — it does NOT go through claim(). Idempotent on run_key (re-recording
        re-marks it running and bumps attempts). Returns the row id."""
        now = time.time()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                "INSERT INTO jobs (run_key, kind, params, status, owner, attempts, "
                "created_at, started_at, heartbeat_at) VALUES (?,?,?,?,?,1,?,?,?) "
                "ON CONFLICT(run_key) DO UPDATE SET status=excluded.status, "
                "owner=excluded.owner, started_at=excluded.started_at, "
                "heartbeat_at=excluded.heartbeat_at, attempts=jobs.attempts+1",
                (
                    run_key,
                    str(kind),
                    json.dumps(params, sort_keys=True),
                    RUNNING,
                    self.owner,
                    now,
                    now,
                    now,
                ),
            )
            row = self._db.execute("SELECT id FROM jobs WHERE run_key=?", (run_key,)).fetchone()
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return int(row["id"])

    def complete_by_key(
        self, run_key: str, status: str, *, metric: float | None = None, summary: str = ""
    ) -> bool:
        """Terminal-mark an externally-run job by run_key (WS-A7). Returns True if a row
        matched. Used by the web eval's settle callback (which runs in the job's thread,
        so it opens its own short-lived connection)."""
        if status not in TERMINAL_STATUSES:
            allowed = sorted(TERMINAL_STATUSES)
            raise ValueError(f"complete_by_key needs a terminal status {allowed}, got {status!r}")
        cur = self._db.execute(
            "UPDATE jobs SET status=?, owner='', finished_at=?, metric=?, summary=? "
            "WHERE run_key=?",
            (status, time.time(), metric, summary, run_key),
        )
        return cur.rowcount > 0

    def fail_orphans(
        self, owner: str | None = None, *, summary: str = "interrupted by restart"
    ) -> list[str]:
        """Mark every ``running`` row for ``owner`` (default this queue's) as ``fail`` — for
        externally-run jobs (web evals) that can't resume after a crash (WS-A7). Returns the
        affected run_keys. Call at startup before serving."""
        who = owner or self.owner
        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute(
                "SELECT run_key FROM jobs WHERE status=? AND owner=?", (RUNNING, who)
            ).fetchall()
            self._db.execute(
                "UPDATE jobs SET status='fail', owner='', finished_at=?, summary=? "
                "WHERE status=? AND owner=?",
                (time.time(), summary, RUNNING, who),
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return [str(r["run_key"]) for r in rows]

    def retry(self, job_id: int, *, max_attempts: int = 3) -> bool:
        """Requeue a failed job for another attempt if it has tries left, else mark it
        ``fail`` (WS-A5). ``attempts`` was already bumped at claim, so a job claimed once
        has attempts=1. Returns True if requeued (the caller should back off before it is
        re-claimed)."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT attempts FROM jobs WHERE id=?", (int(job_id),)
            ).fetchone()
            if row is None:
                self._db.execute("COMMIT")
                return False
            if int(row["attempts"]) < max_attempts:
                self._db.execute(
                    "UPDATE jobs SET status=?, owner='' WHERE id=?", (QUEUED, int(job_id))
                )
                requeued = True
            else:
                self._db.execute(
                    "UPDATE jobs SET status='fail', owner='', finished_at=?, "
                    "summary='retry: exceeded max attempts' WHERE id=?",
                    (time.time(), int(job_id)),
                )
                requeued = False
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return requeued

    # ------------------------------------------------------ crash recovery (A2)
    def recover_stale(
        self, *, stale_ttl_s: float = _DEFAULT_STALE_TTL_S, max_attempts: int = 3
    ) -> list[dict]:
        """Reclaim rows left ``running`` by a crash. Owner-scoped: only rows THIS worker
        owned, OR rows whose heartbeat is older than ``stale_ttl_s`` (abandoned by any
        dead worker). Requeue if ``attempts < max_attempts``, else mark ``fail``. A live
        job another owner is heartbeating is never touched. Returns the actions taken.
        """
        cutoff = time.time() - float(stale_ttl_s)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            rows = self._db.execute(
                "SELECT id, run_key, attempts FROM jobs "
                "WHERE status=? AND (owner=? OR heartbeat_at IS NULL OR heartbeat_at < ?)",
                (RUNNING, self.owner, cutoff),
            ).fetchall()
            actions: list[dict] = []
            for r in rows:
                if int(r["attempts"]) < max_attempts:
                    self._db.execute(
                        "UPDATE jobs SET status=?, owner='' WHERE id=?", (QUEUED, r["id"])
                    )
                    actions.append({"run_key": str(r["run_key"]), "action": "requeued"})
                else:
                    self._db.execute(
                        "UPDATE jobs SET status='fail', owner='', finished_at=?, "
                        "summary='crashed: exceeded max attempts' WHERE id=?",
                        (time.time(), r["id"]),
                    )
                    actions.append({"run_key": str(r["run_key"]), "action": "failed"})
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return actions

    # ---------------------------------------------------------------- readers
    def counts(self) -> dict[str, int]:
        """{status: count} across all jobs (for the morning summary / B3 panel)."""
        rows = self._db.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").fetchall()
        return {str(r["status"]): int(r["c"]) for r in rows}

    def list_jobs(self) -> list[dict]:
        """Every job row as a dict, oldest first (read-only projection for B3)."""
        rows = self._db.execute(
            "SELECT id, run_key, kind, status, owner, attempts, metric, summary, "
            "started_at, finished_at FROM jobs ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def render(jobs: list[dict], counts: dict[str, int]) -> str:
    """Terminal view of the durable queue (the CLI sibling of the /api/jobs endpoint)."""
    if not jobs:
        return "no jobs in the queue"
    lines = ["  ".join(f"{k}={v}" for k, v in sorted(counts.items())), ""]
    lines.append(f"{'status':<9} {'kind':<13} {'owner':<9} {'att':>3}  run_key")
    for j in jobs:
        lines.append(
            f"{str(j['status']):<9} {str(j['kind']):<13} {str(j['owner']):<9} "
            f"{int(j['attempts']):>3}  {j['run_key']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """`python -m catranger.jobqueue` — print the durable job queue (the CLI sibling of
    GET /api/jobs; `make history` reviews the archive, this reviews the live queue)."""
    ap = argparse.ArgumentParser(description="Show the CatRanger durable job queue.")
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH), help="queue db path")
    ap.add_argument("--limit", type=int, default=50, help="show the most recent N jobs")
    args = ap.parse_args(argv)
    if not Path(args.db).exists():
        print(f"no job queue yet at {args.db} (run `make overnight`)")
        return 0
    q = JobQueue(args.db, owner="cli")
    try:
        jobs = q.list_jobs()
        counts = q.counts()
    finally:
        q.close()
    print(render(jobs[-args.limit :] if args.limit else jobs, counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
