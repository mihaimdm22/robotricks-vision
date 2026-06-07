"""Run a subprocess under a wall-clock cap, killing its whole process group on timeout.

Used by the overnight runner (WS-A3, and later the durable job queue) so a hung job —
a stuck dataloader, a wedged model download — is killed at its timeout instead of
hanging the whole night, and its orphaned child workers (torch dataloader processes)
and leaked GPU/MPS memory go with it. Killing only the direct child (plain
``subprocess.run(timeout=...)``) would leave those grandchildren alive.

Stdlib only (subprocess/os/signal), POSIX (``start_new_session``). Returns
``(returncode, combined_log, seconds)``; a timeout returns :data:`RC_TIMEOUT` so the
caller can classify it as a first-class "timeout" failure (WS-A5).
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

# Distinct from any normal program exit code (mirrors GNU coreutils `timeout`), so
# callers can tell "killed by our watchdog" apart from the job's own return code.
RC_TIMEOUT = 124

_GRACE_S = 5.0  # SIGTERM -> wait -> SIGKILL window


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """SIGTERM then (after a grace period) SIGKILL the child's whole process group.

    Never raises — the process may already be gone by the time we signal it.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, OSError):
            return
        try:
            proc.wait(timeout=_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            continue  # still alive after SIGTERM -> escalate to SIGKILL


# Failure classification for the retry policy (WS-A5). Prefer structured signals
# (RC_TIMEOUT) over log scraping; default to PERMANENT so a deterministic failure (bad
# config, missing dataset, import error) never wastes the night being retried.
_RETRYABLE_PATTERNS = (
    "out of memory",
    "cuda error",
    "cublas",
    "cudnn",
    "unable to allocate",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "timed out",
    "read timed out",
    "remote end closed",
)
_PERMANENT_PATTERNS = (
    "no such file",
    "filenotfounderror",
    "modulenotfounderror",
    "importerror",
    "assertionerror",
    "permission denied",
)


def classify_failure(rc: int, log: str) -> str:
    """Classify a failed job as ``"retryable"`` (transient) or ``"permanent"``.

    ``rc == RC_TIMEOUT`` is retryable by definition (bounded by max_attempts upstream).
    Otherwise scan the log: explicit permanent markers win first, then retryable markers,
    else PERMANENT — conservative, so an unknown/deterministic failure is not retried.
    """
    if rc == RC_TIMEOUT:
        return "retryable"
    text = (log or "").lower()
    if any(p in text for p in _PERMANENT_PATTERNS):
        return "permanent"
    if any(p in text for p in _RETRYABLE_PATTERNS):
        return "retryable"
    return "permanent"


def backoff_seconds(attempt: int, *, base: float = 2.0, cap: float = 60.0) -> float:
    """Capped exponential backoff for a 1-based attempt number: ``min(cap, base*2**(n-1))``.
    Gives a still-recovering GPU time to release memory before the next try (jitter, if
    wanted, is applied by the caller)."""
    n = max(1, int(attempt))
    return float(min(cap, base * (2.0 ** (n - 1))))


def run_capped(
    cmd: list[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout_s: float | None = None,
) -> tuple[int, str, float]:
    """Run ``cmd`` capturing combined stdout+stderr, under an optional wall-clock cap.

    On timeout the WHOLE process group is killed (so torch dataloader workers don't
    orphan and leak device memory) and the return code is :data:`RC_TIMEOUT`.

    Returns ``(returncode, log, seconds)``. ``timeout_s=None`` means no cap (a plain
    blocking run, matching the previous ``subprocess.run`` behavior).
    """
    t0 = time.time()
    # start_new_session=True puts the child in its own process group so we can signal
    # the whole tree, not just the direct child (POSIX).
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        try:
            # Drain the pipes from the now-dead group — but bounded: a grandchild that
            # escaped the group (called setsid / double-forked) still holds the write end,
            # and an unbounded drain would hang the very night the timeout exists to save.
            out, err = proc.communicate(timeout=_GRACE_S)
        except subprocess.TimeoutExpired:
            for stream in (proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            out, err = "", ""
    secs = time.time() - t0
    log = (out or "") + (err or "")
    if timed_out:
        log += f"\n[proc] killed: exceeded {timeout_s}s wall-clock timeout\n"
        return RC_TIMEOUT, log, secs
    return proc.returncode, log, secs
