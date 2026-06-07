"""Unit tests for the CV/Training background job state machine.

The real subprocess spawn (`catranger.train.runner`) is replaced by an injected
fake runner, so these run with no torch/ultralytics and never start a real
training process — we test idle/running/done/error/cancelled transitions, the
one-at-a-time guarantee, coarse epoch parsing, command building, and history
archival, not training itself.
"""

from __future__ import annotations

import threading
import time

import pytest

from catranger import history
from catranger.web.train_job import TrainJob, build_command, parse_epoch


def _wait_state(job: TrainJob, state: str, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.status()["state"] == state:
            return True
        time.sleep(0.01)
    return False


# --------------------------------------------------------------- pure helpers
def test_build_command_prepare_train_autoresearch() -> None:
    prep = build_command("prepare", config="configs/train.yaml", source="roboflow", python="py")
    assert prep == [
        "py",
        "-m",
        "catranger.train.prepare",
        "--config",
        "configs/train.yaml",
        "--source",
        "roboflow",
    ]
    tr = build_command("train", epochs=5, device="cpu", python="py")
    assert tr[:5] == ["py", "-m", "catranger.train.train", "--config", "configs/train.yaml"]
    assert "--epochs" in tr and "5" in tr and "--device" in tr and "cpu" in tr
    ar = build_command("autoresearch", device="mps", python="py")
    assert ar[2] == "catranger.train.autoresearch"
    assert "--device" in ar and "mps" in ar
    # prepare ignores epochs/device (not applicable)
    assert "--epochs" not in build_command("prepare", python="py")


def test_build_command_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        build_command("frobnicate")


def test_parse_epoch() -> None:
    assert parse_epoch("        3/40      0.5G   1.2   0.3") == (3, 40)
    assert parse_epoch("   10/10  done") == (10, 10)
    assert parse_epoch("Starting training...") is None
    assert parse_epoch("99999/100000 nonsense") is None  # out of sane range
    assert parse_epoch("5/3 backwards") is None  # epoch > total


# --------------------------------------------------------------- state machine
def test_runs_to_done_and_archives(tmp_path) -> None:
    def fake(cmd, *, cwd, on_line, should_cancel):
        on_line("Ultralytics starting")
        on_line("        2/40   0.5G  loss")
        return 0

    job = TrainJob(runner=fake, history_base=tmp_path)
    assert job.start(kind="train", config="configs/train.yaml") is True
    assert _wait_state(job, "done")
    st = job.status()
    assert st["epoch"] == 2 and st["total_epochs"] == 40
    assert "2/40" in st["log_tail"]
    res = job.result()
    assert res is not None and res["status"] == "ok" and res["kind"] == "train"
    # archived to the injected history base
    entries = history.read_index(base=tmp_path)
    assert len(entries) == 1 and entries[0]["kind"] == "train" and entries[0]["status"] == "ok"


def test_done_reads_winner_and_archives_best_pt(tmp_path) -> None:
    import json

    # Lay out a repo where a winner + published weights exist (as after a real run).
    (tmp_path / "runs" / "train").mkdir(parents=True)
    (tmp_path / "runs" / "train" / "best_trial.json").write_text(
        json.dumps({"metric": 0.73, "metric_key": "mAP50-95", "overrides": {"lr0": 0.01}}),
        encoding="utf-8",
    )
    (tmp_path / "runs" / "train" / "best.pt").write_text("weights", encoding="utf-8")
    hist = tmp_path / "history"

    def fake(cmd, *, cwd, on_line, should_cancel):
        on_line("  5/5 done")
        return 0

    job = TrainJob(runner=fake, repo_root=tmp_path, history_base=hist)
    job.start(kind="autoresearch")
    assert _wait_state(job, "done")
    res = job.result()
    assert res is not None and res["metric"] == 0.73 and res["metric_key"] == "mAP50-95"
    assert "mAP50-95=0.73" in job.status()["summary"]
    # the published best.pt was archived into the run dir (enables per-row promote)
    entry = history.read_index(base=hist)[0]
    assert (hist / entry["dir"] / "best.pt").exists()


def test_nonzero_rc_is_error(tmp_path) -> None:
    def fake(cmd, *, cwd, on_line, should_cancel):
        on_line("boom")
        return 1

    job = TrainJob(runner=fake, history_base=tmp_path)
    job.start(kind="train")
    assert _wait_state(job, "error")
    assert "code 1" in job.status()["error"]
    assert history.read_index(base=tmp_path)[0]["status"] == "fail"


def test_spawn_exception_is_error(tmp_path) -> None:
    def boom(cmd, **kwargs):
        raise OSError("cannot spawn")

    job = TrainJob(runner=boom, history_base=tmp_path)
    job.start(kind="train")
    assert _wait_state(job, "error")
    assert "cannot spawn" in job.status()["error"]


def test_cancel_terminates(tmp_path) -> None:
    def cancellable(cmd, *, cwd, on_line, should_cancel):
        for _ in range(200):
            if should_cancel():
                return -15  # signalled
            time.sleep(0.01)
        return 0

    job = TrainJob(runner=cancellable, history_base=tmp_path)
    job.start(kind="autoresearch")
    assert _wait_state(job, "running")
    assert job.cancel() is True
    assert _wait_state(job, "cancelled")
    assert history.read_index(base=tmp_path)[0]["status"] == "cancelled"


def test_second_start_refused_while_running(tmp_path) -> None:
    release = threading.Event()

    def slow(cmd, *, cwd, on_line, should_cancel):
        release.wait(2.0)
        return 0

    job = TrainJob(runner=slow, history_base=tmp_path)
    assert job.start(kind="train") is True
    assert _wait_state(job, "running")
    assert job.start(kind="train") is False  # one at a time
    release.set()
    assert _wait_state(job, "done")
