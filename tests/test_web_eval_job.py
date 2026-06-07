"""Unit tests for the M3 background eval job state machine.

The heavy pipeline (`run_eval_job`) is monkeypatched so these run with no
torch/ultralytics — we test the job's idle/running/done/error/cancelled
transitions and the one-at-a-time guarantee, not perception.
"""

from __future__ import annotations

import threading
import time

import catranger.eval.report as report_mod
from catranger.web.eval_job import EvalJob


def _wait_state(job: EvalJob, state: str, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.status()["state"] == state:
            return True
        time.sleep(0.01)
    return False


def test_job_runs_to_done_and_exposes_result(monkeypatch) -> None:
    def fake(**kwargs):
        return {
            "metrics": {"fps": {"mean_fps": 30.0}},
            "report_path": "outputs/report/report.md",
            "report_text": "# report",
            "n_frames": 5,
            "approach": "approach_a",
        }

    monkeypatch.setattr(report_mod, "run_eval_job", fake)
    job = EvalJob()
    assert job.start(source="x") is True
    assert _wait_state(job, "done")
    result = job.result()
    assert result is not None
    assert result["markdown"] == "# report"
    assert result["metrics"]["fps"]["mean_fps"] == 30.0


def test_job_surfaces_errors(monkeypatch) -> None:
    def boom(**kwargs):
        raise ValueError("bad source")

    monkeypatch.setattr(report_mod, "run_eval_job", boom)
    job = EvalJob()
    job.start(source="x")
    assert _wait_state(job, "error")
    assert "bad source" in job.status()["error"]
    assert job.result() is None


def test_second_start_is_refused_while_running(monkeypatch) -> None:
    release = threading.Event()

    def slow(**kwargs):
        release.wait(2.0)
        return {
            "metrics": {},
            "report_path": "p",
            "report_text": "",
            "n_frames": 0,
            "approach": "approach_a",
        }

    monkeypatch.setattr(report_mod, "run_eval_job", slow)
    job = EvalJob()
    assert job.start(source="x") is True
    assert _wait_state(job, "running")
    assert job.start(source="y") is False  # one at a time
    release.set()
    assert _wait_state(job, "done")


def _wait_settled(settled: list, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while not settled and time.time() < deadline:
        time.sleep(0.01)


def test_on_settle_fires_ok_on_done(monkeypatch) -> None:
    monkeypatch.setattr(
        report_mod,
        "run_eval_job",
        lambda **k: {
            "metrics": {},
            "report_path": "p",
            "report_text": "",
            "n_frames": 0,
            "approach": "approach_a",
        },
    )
    settled: list[str] = []
    job = EvalJob()
    job.start(on_settle=settled.append, source="x")
    assert _wait_state(job, "done")
    _wait_settled(settled)
    assert settled == ["ok"]  # WS-A7: durable queue gets the terminal status


def test_on_settle_fires_fail_on_error(monkeypatch) -> None:
    def boom(**kwargs):
        raise ValueError("bad source")

    monkeypatch.setattr(report_mod, "run_eval_job", boom)
    settled: list[str] = []
    job = EvalJob()
    job.start(on_settle=settled.append, source="x")
    assert _wait_state(job, "error")
    _wait_settled(settled)
    assert settled == ["fail"]


def test_on_progress_forwards_ticks(monkeypatch) -> None:
    def fake(progress=None, **kwargs):
        if progress is not None:
            progress(1, 10)
            progress(7, 10)
        return {
            "metrics": {},
            "report_path": "p",
            "report_text": "",
            "n_frames": 0,
            "approach": "approach_a",
        }

    monkeypatch.setattr(report_mod, "run_eval_job", fake)
    ticks: list[tuple[int, int | None]] = []
    job = EvalJob()
    job.start(on_progress=lambda done, total: ticks.append((done, total)), source="x")
    assert _wait_state(job, "done")
    assert ticks == [(1, 10), (7, 10)]  # WS-A7: runtime refreshes the durable-queue lease


def test_cancel_marks_cancelled(monkeypatch) -> None:
    def cancellable(cancel=None, **kwargs):
        from catranger.eval.report import EvalCancelled

        for _ in range(200):
            if cancel and cancel():
                raise EvalCancelled("cancelled")
            time.sleep(0.01)
        return {
            "metrics": {},
            "report_path": "p",
            "report_text": "",
            "n_frames": 0,
            "approach": "approach_a",
        }

    monkeypatch.setattr(report_mod, "run_eval_job", cancellable)
    job = EvalJob()
    job.start(source="x")
    assert _wait_state(job, "running")
    assert job.cancel() is True
    assert _wait_state(job, "cancelled")
