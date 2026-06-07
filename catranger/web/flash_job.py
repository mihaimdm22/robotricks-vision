"""Background Arduino firmware flash job for the Connections tab."""

from __future__ import annotations

import threading
import time
from enum import StrEnum
from typing import Any


class FlashState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class FlashJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = FlashState.IDLE
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._port: str | None = None
        self._result: dict[str, Any] | None = None
        self._error: str | None = None

    def start(self, port: str | None) -> bool:
        with self._lock:
            if self._state == FlashState.RUNNING:
                return False
            self._state = FlashState.RUNNING
            self._started_at = time.time()
            self._port = port
            self._result = None
            self._error = None
        self._thread = threading.Thread(target=self._run, name="flash-job", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        from catranger.hw.arduino_flash import flash_sketch

        try:
            result = flash_sketch(self._port)
        except Exception as exc:  # pragma: no cover - surfaced to UI
            with self._lock:
                self._state = FlashState.ERROR
                self._error = str(exc)
            return

        with self._lock:
            if result.get("ok"):
                self._state = FlashState.DONE
                self._result = result
            else:
                self._state = FlashState.ERROR
                self._error = str(result.get("problem") or result.get("code") or "flash failed")
                self._result = result

    def status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = None
            if self._started_at is not None and self._state == FlashState.RUNNING:
                elapsed = round(time.time() - self._started_at, 1)
            out: dict[str, Any] = {
                "state": self._state.value,
                "elapsed_s": elapsed,
                "port": self._port,
            }
            if self._result is not None:
                out["result"] = self._result
            if self._error is not None:
                out["error"] = self._error
            return out
