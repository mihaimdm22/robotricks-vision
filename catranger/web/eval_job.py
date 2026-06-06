"""EvalJob: run the heavy eval pipeline in a background worker thread so the web
Eval tab can start it, poll status, and read the rendered report without blocking
the async event loop or the single control thread.

One job at a time (the runtime refuses a second). The actual work is
`catranger.eval.report.run_eval_job` — the SAME code path the CLI uses — so the
web and `make eval` can never diverge. Heavy deps (torch/ultralytics) are
imported lazily inside that function, never at module load.
"""

from __future__ import annotations

import threading
import time
from enum import StrEnum
from typing import Any


class EvalState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class EvalJob:
    """A single, restartable background eval run with pollable status."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = EvalState.IDLE
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._done = 0
        self._total: int | None = None
        self._started_at: float | None = None
        self._params: dict[str, Any] = {}
        self._result: dict[str, Any] | None = None
        self._error: str | None = None

    # ----------------------------------------------------------------- control
    def start(self, **params: Any) -> bool:
        """Start a run. Returns False if one is already running (caller nacks)."""
        with self._lock:
            if self._state == EvalState.RUNNING:
                return False
            self._state = EvalState.RUNNING
            self._cancel.clear()
            self._done = 0
            self._total = None
            self._started_at = time.time()
            self._params = dict(params)
            self._result = None
            self._error = None
        self._thread = threading.Thread(target=self._run, name="eval-job", daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> bool:
        """Request cooperative cancellation. Returns True if a run was active."""
        with self._lock:
            if self._state != EvalState.RUNNING:
                return False
        self._cancel.set()
        return True

    # ------------------------------------------------------------------ worker
    def _run(self) -> None:
        from catranger.eval.report import EvalCancelled, run_eval_job

        try:
            result = run_eval_job(
                progress=self._on_progress,
                cancel=self._cancel.is_set,
                **self._params,
            )
        except EvalCancelled:
            with self._lock:
                self._state = EvalState.CANCELLED
            return
        except Exception as exc:  # surface the real reason; never swallow
            with self._lock:
                self._state = EvalState.ERROR
                self._error = f"{type(exc).__name__}: {exc}"
            return
        with self._lock:
            self._result = result
            self._state = EvalState.DONE

    def _on_progress(self, done: int, total: int | None) -> None:
        with self._lock:
            self._done = done
            self._total = total

    # ----------------------------------------------------------------- readers
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.value,
                "done": self._done,
                "total": self._total,
                "started_at": self._started_at,
                "n_frames": (self._result or {}).get("n_frames"),
                "error": self._error,
            }

    def result(self) -> dict[str, Any] | None:
        """The {markdown, metrics, approach} payload once DONE, else None."""
        with self._lock:
            if self._state != EvalState.DONE or self._result is None:
                return None
            return {
                "markdown": self._result["report_text"],
                "metrics": self._result["metrics"],
                "approach": self._result["approach"],
                "n_frames": self._result["n_frames"],
            }

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state == EvalState.RUNNING
