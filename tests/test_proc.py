"""Tests for the capped subprocess runner (catranger.proc, WS-A3).

The headline case is the process-group kill: a timeout must take down a job's
*grandchildren* (torch dataloader workers), not just the direct child.
"""

from __future__ import annotations

import sys
import time

from catranger.proc import RC_TIMEOUT, backoff_seconds, classify_failure, run_capped


def test_classify_failure_timeout_is_retryable():
    assert classify_failure(RC_TIMEOUT, "") == "retryable"


def test_classify_failure_transient_log_is_retryable():
    assert (
        classify_failure(1, "RuntimeError: CUDA out of memory. Tried to allocate...") == "retryable"
    )
    assert (
        classify_failure(1, "ConnectionResetError: [Errno 54] Connection reset by peer")
        == "retryable"
    )


def test_classify_failure_deterministic_is_permanent():
    assert classify_failure(1, "FileNotFoundError: data/cat/data.yaml") == "permanent"
    assert classify_failure(2, "ModuleNotFoundError: No module named 'ultralytics'") == "permanent"
    assert classify_failure(1, "some unrecognized failure") == "permanent"  # conservative default


def test_classify_failure_permanent_wins_over_transient_substring():
    log = "CUDA out of memory ... then ModuleNotFoundError: no module"
    assert classify_failure(1, log) == "permanent"


def test_backoff_seconds_is_capped_exponential():
    assert backoff_seconds(1) == 2.0
    assert backoff_seconds(2) == 4.0
    assert backoff_seconds(3) == 8.0
    assert backoff_seconds(99) == 60.0  # capped
    assert backoff_seconds(0) == 2.0  # clamps to attempt 1


def test_run_capped_success_captures_stdout_and_stderr():
    rc, log, secs = run_capped(
        [sys.executable, "-c", "import sys; print('hello'); sys.stderr.write('werr')"]
    )
    assert rc == 0
    assert "hello" in log
    assert "werr" in log
    assert secs >= 0.0


def test_run_capped_propagates_nonzero_returncode():
    rc, _log, _secs = run_capped([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert rc == 3


def test_run_capped_timeout_returns_rc_timeout_promptly():
    t0 = time.time()
    rc, log, _secs = run_capped(
        [sys.executable, "-c", "import time; time.sleep(10)"], timeout_s=0.5
    )
    assert rc == RC_TIMEOUT
    assert (time.time() - t0) < 5.0  # killed, did not sleep the full 10s
    assert "timeout" in log.lower()


def test_run_capped_timeout_kills_whole_process_group(tmp_path):
    """A grandchild that would write a sentinel after 3s must never run: killing the
    process group on timeout reaps the orphaned worker too."""
    sentinel = tmp_path / "child_ran.txt"
    child_py = tmp_path / "child.py"
    child_py.write_text(f"import time\ntime.sleep(3)\nopen({str(sentinel)!r}, 'w').close()\n")
    parent_py = tmp_path / "parent.py"
    parent_py.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(child_py)!r}])\n"
        "time.sleep(30)\n"
    )

    rc, _log, _secs = run_capped([sys.executable, str(parent_py)], timeout_s=0.7)
    assert rc == RC_TIMEOUT

    time.sleep(4.0)  # past the grandchild's 3s write delay
    assert not sentinel.exists(), "grandchild survived the group kill (orphaned worker)"
