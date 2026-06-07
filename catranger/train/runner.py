"""Subprocess runner for the web Training tab — the I/O edge (no unit coverage).

`train_once` (Ultralytics `model.train`) is one opaque blocking call with NO
cooperative cancel hook, and it spawns DataLoader worker subprocesses. So the web
orchestrator runs training in its OWN process GROUP and cancels by killing the
whole group — a bare terminate() would orphan the workers and leak GPU memory
(Eng review). Cross-platform: POSIX uses a new session + killpg; Windows uses a
new process group + CTRL_BREAK.

The state machine that drives this lives in `catranger.web.train_job` (which IS
unit-tested, via an injected fake runner). This module is the real spawn only.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable

_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)  # Windows-only flag


def run_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    on_line: Callable[[str], None],
    should_cancel: Callable[[], bool],
    poll_interval: float = 0.1,
    grace_s: float = 5.0,
) -> int:
    """Run `cmd`, streaming combined stdout/stderr line-by-line to `on_line`, and
    terminating the whole process group if `should_cancel()` turns True. Returns
    the exit code (a negative/130 code signals a cancel-kill).

    Cancellation is polled on an INDEPENDENT watcher thread, NOT inside the stdout
    read loop — Ultralytics can sit silent for minutes (dataset scan, a long
    epoch), and a cancel that only fires on the next printed line would let E-stop
    return 'ok' while the GPU stays pinned (adversarial review / CLAUDE.md hard
    rule: E-stop must free the box)."""
    popen_kwargs: dict = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = _NEW_GROUP
    else:
        popen_kwargs["start_new_session"] = True  # own session => own process group

    proc = subprocess.Popen(cmd, **popen_kwargs)
    assert proc.stdout is not None

    stop_watch = threading.Event()

    def _watch() -> None:
        # Kill the group as soon as cancel is requested, regardless of stdout.
        while not stop_watch.wait(poll_interval):
            if should_cancel():
                _kill_group(proc, grace_s)
                return

    watcher = threading.Thread(target=_watch, name="train-cancel-watch", daemon=True)
    watcher.start()
    try:
        for line in proc.stdout:  # ends when the pipe closes (incl. on kill)
            on_line(line.rstrip("\n"))
    finally:
        rc = proc.wait()  # reap — never leave a zombie
        stop_watch.set()
        watcher.join(timeout=1.0)
    return rc


def _kill_group(proc: subprocess.Popen, grace_s: float) -> None:
    """SIGTERM the group, wait a grace period, then SIGKILL the group. The whole
    point: take the DataLoader workers down with the parent."""
    try:
        if os.name == "nt":
            proc.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    deadline = time.time() + grace_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        return
