"""TrainJob: run a training/prepare job as a background SUBPROCESS for the web
CV/Training tab — start, poll status (coarse epoch progress + a log tail), cancel,
and archive the result to runs/history.

Why a subprocess (not a worker thread like EvalJob): `train_once` is one opaque
Ultralytics `model.train` call with NO cooperative cancel hook, and it spawns
DataLoader workers. So "cancel" can only mean killing the process group — there is
no clean mid-epoch checkpoint, and we never claim one (Eng review). The actual
spawn lives in `catranger.train.runner` (the I/O edge); this module is the
testable state machine, with the runner injected so tests drive it with no torch.

One job at a time (the runtime also serializes it against eval via a shared heavy-
job lock). Heavy work is a child process, so a segfault/OOM never takes down the
control plane.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KINDS = ("prepare", "train", "autoresearch")
# Ultralytics prints per-epoch progress starting with "  <epoch>/<total> ..."
_EPOCH = re.compile(r"^\s*(\d+)/(\d+)\b")


class TrainState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


def build_command(
    kind: str,
    *,
    config: str = "configs/train.yaml",
    epochs: int | None = None,
    device: str | None = None,
    source: str | None = None,
    python: str | None = None,
) -> list[str]:
    """Build the `python -m catranger.train.<kind>` command. Pure (unit-tested)."""
    if kind not in _KINDS:
        raise ValueError(f"unknown train kind {kind!r}; use one of {_KINDS}")
    py = python or sys.executable
    if kind == "prepare":
        cmd = [py, "-m", "catranger.train.prepare", "--config", config]
        if source:
            cmd += ["--source", source]
        return cmd
    module = "catranger.train.autoresearch" if kind == "autoresearch" else "catranger.train.train"
    cmd = [py, "-m", module, "--config", config]
    if kind == "train" and epochs:
        cmd += ["--epochs", str(int(epochs))]
    if device:
        cmd += ["--device", str(device)]
    return cmd


def parse_epoch(line: str) -> tuple[int, int] | None:
    """Best-effort coarse progress: '(epoch, total)' from an Ultralytics line, or
    None. Deliberately conservative — we promise coarse progress, not a precise bar."""
    m = _EPOCH.match(line)
    if not m:
        return None
    epoch, total = int(m.group(1)), int(m.group(2))
    if 0 < epoch <= total <= 10000:
        return epoch, total
    return None


# default runner is the real subprocess spawn (I/O edge, coverage-omitted module)
def _default_runner(
    cmd: list[str],
    *,
    cwd: str,
    on_line: Callable[[str], None],
    should_cancel: Callable[[], bool],
) -> int:
    from catranger.train.runner import run_subprocess

    return run_subprocess(cmd, cwd=cwd, on_line=on_line, should_cancel=should_cancel)


class TrainJob:
    """A single, restartable background training run with pollable status."""

    def __init__(
        self,
        *,
        runner: Callable[..., int] | None = None,
        repo_root: Path | None = None,
        history_base: Path | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self._repo = repo_root or _REPO_ROOT
        self._history_base = history_base
        self._lock = threading.Lock()
        self._state = TrainState.IDLE
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._kind: str | None = None
        self._started_at: float | None = None
        self._log: deque[str] = deque(maxlen=400)
        self._epoch: int | None = None
        self._total_epochs: int | None = None
        self._rc: int | None = None
        self._error: str | None = None
        self._summary = ""
        self._result: dict[str, Any] | None = None

    # ----------------------------------------------------------------- control
    def start(
        self,
        *,
        kind: str,
        config: str = "configs/train.yaml",
        epochs: int | None = None,
        device: str | None = None,
        source: str | None = None,
    ) -> bool:
        """Start a run. Returns False if one is already running (caller nacks)."""
        cmd = build_command(kind, config=config, epochs=epochs, device=device, source=source)
        with self._lock:
            if self._state == TrainState.RUNNING:
                return False
            self._state = TrainState.RUNNING
            self._cancel.clear()
            self._kind = kind
            self._started_at = time.time()
            self._log.clear()
            self._epoch = None
            self._total_epochs = None
            self._rc = None
            self._error = None
            self._summary = ""
            self._result = None
        self._thread = threading.Thread(
            target=self._run, args=(cmd,), name="train-job", daemon=True
        )
        self._thread.start()
        return True

    def cancel(self) -> bool:
        """Terminate the training subprocess group. NOT a clean mid-epoch stop —
        the partial run dir is discarded (never published). Returns True if active."""
        with self._lock:
            if self._state != TrainState.RUNNING:
                return False
        self._cancel.set()
        return True

    def request_stop(self) -> None:
        """Best-effort cancel for shutdown / E-stop (no return value)."""
        self._cancel.set()

    # ------------------------------------------------------------------ worker
    def _run(self, cmd: list[str]) -> None:
        t0 = time.time()
        try:
            rc = self._runner(
                cmd,
                cwd=str(self._repo),
                on_line=self._on_line,
                should_cancel=self._cancel.is_set,
            )
        except Exception as exc:  # spawn failure etc. — surface, never swallow
            with self._lock:
                self._state = TrainState.ERROR
                self._error = f"{type(exc).__name__}: {exc}"
            return
        secs = time.time() - t0
        cancelled = self._cancel.is_set()
        with self._lock:
            self._rc = rc
            kind = self._kind or "train"
        status = "cancelled" if cancelled else ("ok" if rc == 0 else "fail")
        metric, metric_key, metrics, summary = self._collect_winner(kind, rc, status)
        self._archive(kind, status, secs, metric, metric_key, metrics, summary)
        with self._lock:
            self._summary = summary
            self._result = {
                "kind": kind,
                "status": status,
                "rc": rc,
                "metric": metric,
                "metric_key": metric_key,
                "metrics": metrics,
            }
            if cancelled:
                self._state = TrainState.CANCELLED
            elif rc == 0:
                self._state = TrainState.DONE
            else:
                self._state = TrainState.ERROR
                self._error = f"training exited with code {rc}"

    def _collect_winner(
        self, kind: str, rc: int, status: str
    ) -> tuple[float | None, str | None, dict | None, str]:
        """For train/autoresearch read runs/train/best_trial.json (the keep/reject
        winner) for the headline metric, mirroring scripts/overnight.py."""
        import json

        if kind == "prepare" or status != "ok":
            return None, None, None, f"{kind}: {status} (rc={rc})"
        best = self._repo / "runs" / "train" / "best_trial.json"
        if not best.exists():
            return None, None, None, f"{kind}: ok"
        try:
            winner = json.loads(best.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None, None, f"{kind}: ok"
        metric = winner.get("metric")
        mk = winner.get("metric_key", "metric")
        return metric, mk, winner, f"{mk}={metric} overrides={winner.get('overrides')}"

    def _archive(
        self,
        kind: str,
        status: str,
        secs: float,
        metric: float | None,
        metric_key: str | None,
        metrics: dict | None,
        summary: str,
    ) -> None:
        from catranger import history

        # Copy the published weights into the run dir so the CV tab's per-row
        # "Promote" can resolve runs/history/<dir>/best.pt (contract review).
        artifacts: dict[str, str] | None = None
        if status == "ok":
            best = self._repo / "runs" / "train" / "best.pt"
            if best.exists():
                artifacts = {"best.pt": str(best)}
        try:
            history.archive_run(
                kind,
                ts=f"{history.stamp()}-web",
                status=status,
                params={"via": "web"},
                metrics=metrics,
                metric=metric,
                metric_key=metric_key,
                summary=summary,
                duration_s=secs,
                log_text="\n".join(self._log),
                artifacts=artifacts,
                base=self._history_base,
            )
        except Exception:  # archiving must never crash the job thread
            pass

    def _on_line(self, line: str) -> None:
        with self._lock:
            self._log.append(line)
            ep = parse_epoch(line)
            if ep is not None:
                self._epoch, self._total_epochs = ep

    # ----------------------------------------------------------------- readers
    def status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = (time.time() - self._started_at) if self._started_at else None
            return {
                "state": self._state.value,
                "kind": self._kind,
                "started_at": self._started_at,
                "elapsed_s": round(elapsed, 1) if elapsed is not None else None,
                "epoch": self._epoch,
                "total_epochs": self._total_epochs,
                "log_tail": "\n".join(self._log),
                "rc": self._rc,
                "error": self._error,
                "summary": self._summary,
            }

    def result(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._result) if self._result is not None else None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state == TrainState.RUNNING
