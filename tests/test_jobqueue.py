"""Tests for the durable job queue (catranger.jobqueue, WS-A1/A2).

Covers the cases the workstream exists for: atomic claim (no double-claim across two
connections), owner-scoped crash recovery (and that a fresh worker does NOT steal
another owner's live job), and a real crash-injection (claim then hard-exit, then
recover + re-run with no second completion).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from catranger.jobqueue import RUNNING, JobQueue, main, render


def _q(tmp_path, owner="overnight") -> JobQueue:
    return JobQueue(tmp_path / "jq.sqlite3", owner=owner)


def test_enqueue_is_idempotent_on_run_key(tmp_path):
    q = _q(tmp_path)
    assert q.enqueue("eval", {"a": 1}, "k0") is True
    assert q.enqueue("eval", {"a": 999}, "k0") is False  # same key -> ignored
    assert q.counts() == {"queued": 1}


def test_claim_oldest_first_marks_running_and_bumps_attempts(tmp_path):
    q = _q(tmp_path)
    q.enqueue("eval", {"i": 0}, "k0")
    q.enqueue("train", {"i": 1}, "k1")
    j = q.claim()
    assert j is not None
    assert j.run_key == "k0" and j.kind == "eval" and j.params == {"i": 0}
    assert j.status == RUNNING and j.attempts == 1
    assert q.counts() == {"running": 1, "queued": 1}


def test_claim_returns_none_when_empty(tmp_path):
    assert _q(tmp_path).claim() is None


def test_complete_sets_terminal_and_rejects_non_terminal(tmp_path):
    q = _q(tmp_path)
    q.enqueue("eval", {}, "k0")
    j = q.claim()
    assert j is not None
    with pytest.raises(ValueError):
        q.complete(j.id, "running")  # not terminal
    q.complete(j.id, "ok", metric=12.3, summary="done")
    assert q.counts() == {"ok": 1}
    assert q.claim() is None  # terminal jobs are not re-claimed


def test_two_connections_never_double_claim(tmp_path):
    q1 = JobQueue(tmp_path / "jq.sqlite3", owner="a")
    q2 = JobQueue(tmp_path / "jq.sqlite3", owner="b")
    for i in range(5):
        q1.enqueue("eval", {"i": i}, f"k{i}")
    claimed: list[str] = []
    while True:
        j1 = q1.claim()
        j2 = q2.claim()
        claimed += [j.run_key for j in (j1, j2) if j is not None]
        if j1 is None and j2 is None:
            break
    assert sorted(claimed) == [f"k{i}" for i in range(5)]
    assert len(claimed) == len(set(claimed))  # each job claimed exactly once


def test_recover_stale_reclaims_own_rows_but_not_another_owners_live_job(tmp_path):
    db = tmp_path / "jq.sqlite3"
    over = JobQueue(db, owner="overnight")
    web = JobQueue(db, owner="web")
    over.enqueue("eval", {}, "over0")
    web.enqueue("eval", {}, "web0")
    over.claim()  # over0 -> running, owner=overnight
    web.claim()  # web0  -> running, owner=web (fresh heartbeat)

    # A NEW overnight worker recovers: it reclaims its own row, leaves web's live job.
    fresh = JobQueue(db, owner="overnight")
    actions = fresh.recover_stale(stale_ttl_s=10_000, max_attempts=3)
    assert actions == [{"run_key": "over0", "action": "requeued"}]
    statuses = {j["run_key"]: j["status"] for j in fresh.list_jobs()}
    assert statuses == {"over0": "queued", "web0": "running"}  # web0 untouched

    # Now age web0's heartbeat past the TTL -> it becomes reclaimable by anyone.
    fresh._db.execute("UPDATE jobs SET heartbeat_at=0 WHERE run_key='web0'")
    actions2 = fresh.recover_stale(stale_ttl_s=1, max_attempts=3)
    assert actions2 == [{"run_key": "web0", "action": "requeued"}]


def test_recover_stale_fails_when_attempts_exhausted(tmp_path):
    q = _q(tmp_path)
    q.enqueue("eval", {}, "k0")
    q.claim()  # attempts=1
    # bump attempts to the cap so recovery gives up instead of looping forever
    q._db.execute("UPDATE jobs SET attempts=3 WHERE run_key='k0'")
    actions = q.recover_stale(max_attempts=3)
    assert actions == [{"run_key": "k0", "action": "failed"}]
    assert q.counts() == {"fail": 1}


def test_retry_requeues_until_attempts_exhausted_then_fails(tmp_path):
    q = _q(tmp_path)
    q.enqueue("eval", {}, "k0")
    j = q.claim()  # attempts=1
    assert j is not None
    assert q.retry(j.id, max_attempts=3) is True  # 1 < 3 -> requeue
    assert q.counts() == {"queued": 1}
    q.claim()  # attempts=2
    assert q.retry(j.id, max_attempts=3) is True  # 2 < 3 -> requeue
    q.claim()  # attempts=3
    assert q.retry(j.id, max_attempts=3) is False  # 3 == 3 -> give up
    assert q.counts() == {"fail": 1}


def test_retry_unknown_job_returns_false(tmp_path):
    assert _q(tmp_path).retry(999, max_attempts=3) is False


def test_record_running_inserts_external_job_and_is_idempotent(tmp_path):
    q = JobQueue(tmp_path / "jq.sqlite3", owner="web")
    rid = q.record_running("web-eval", {"source": "x"}, "web-1")
    rows = q.list_jobs()
    assert len(rows) == 1
    assert rows[0]["status"] == RUNNING and rows[0]["owner"] == "web" and rows[0]["id"] == rid
    q.complete_by_key("web-1", "ok")
    rid2 = q.record_running("web-eval", {"source": "x"}, "web-1")  # re-record same key
    assert rid2 == rid and q.counts() == {"running": 1}  # back to running, one row


def test_complete_by_key(tmp_path):
    q = JobQueue(tmp_path / "jq.sqlite3", owner="web")
    q.record_running("web-eval", {}, "web-1")
    assert q.complete_by_key("web-1", "ok") is True
    assert q.counts() == {"ok": 1}
    assert q.complete_by_key("missing", "ok") is False  # no row matched
    with pytest.raises(ValueError):
        q.complete_by_key("web-1", "running")  # not a terminal status


def test_fail_orphans_marks_only_that_owners_running_rows(tmp_path):
    db = tmp_path / "jq.sqlite3"
    web = JobQueue(db, owner="web")
    over = JobQueue(db, owner="overnight")
    web.record_running("web-eval", {}, "web-1")
    over.enqueue("eval", {}, "ov-1")
    over.claim()  # overnight job now running
    assert web.fail_orphans("web") == ["web-1"]
    statuses = {j["run_key"]: j["status"] for j in web.list_jobs()}
    assert statuses == {"web-1": "fail", "ov-1": "running"}  # overnight's live job untouched


def test_render_and_cli_main(tmp_path, capsys):
    db = tmp_path / "jq.sqlite3"
    q = JobQueue(db, owner="overnight")
    q.enqueue("eval", {}, "k0")
    j = q.claim()
    assert j is not None
    q.complete(j.id, "ok")
    q.close()

    assert "no jobs" in render([], {})
    assert main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "ok=1" in out and "k0" in out


def test_cli_main_no_queue_file(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "absent.sqlite3")]) == 0
    assert "no job queue yet" in capsys.readouterr().out


def test_crash_injection_recover_and_rerun_without_double_completion(tmp_path):
    """A worker claims a job then hard-exits (no complete). Until recovery the job is
    stuck 'running' (NOT silently re-run); after recovery it re-runs and completes once."""
    db = tmp_path / "jq.sqlite3"
    parent = JobQueue(db, owner="overnight")
    parent.enqueue("eval", {"i": 0}, "k0")

    worker = tmp_path / "worker.py"
    worker.write_text(
        "import os, sys\n"
        "from catranger.jobqueue import JobQueue\n"
        "q = JobQueue(sys.argv[1], owner='overnight')\n"
        "j = q.claim()\n"
        "sys.stdout.write(j.run_key if j else 'NONE'); sys.stdout.flush()\n"
        "os._exit(0)\n"  # hard crash: claimed but never completed
    )
    out = subprocess.run(
        [sys.executable, str(worker), str(db)], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "k0"

    # Stuck running -> a normal claim finds nothing (no double-run without recovery).
    assert parent.claim() is None
    assert parent.counts() == {"running": 1}

    # Recover (owner-scoped, immediate for our own crashed row) -> requeue -> re-run.
    assert parent.recover_stale() == [{"run_key": "k0", "action": "requeued"}]
    j = parent.claim()
    assert j is not None and j.run_key == "k0" and j.attempts == 2  # ran twice...
    parent.complete(j.id, "ok")
    assert parent.counts() == {"ok": 1}  # ...completed exactly once
