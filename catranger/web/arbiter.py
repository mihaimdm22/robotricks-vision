"""ControlArbiter: single-controller token for the web console (M5).

The problem: the control thread is the SOLE writer to the serial/BLE bridge, but
any number of browsers can open a WebSocket. Without arbitration, two operators
race drive intents into one robot. The arbiter grants a *drive token* to one
connection; others are read-only observers.

This lives in the server/WS layer (not RobotController) on purpose: a token is a
connection-level concept, and "release on disconnect / idle" only the WS layer
can observe. RobotController stays pure and identity-free.

Safety rule: E-stop and reset are NEVER gated by the token — the server applies
them before any holder check. The arbiter only decides who may *drive*.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class ControlArbiter:
    """Last-claim-wins drive token with idle + disconnect expiry."""

    def __init__(
        self,
        *,
        idle_timeout_s: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self.idle_timeout_s = float(idle_timeout_s)
        self._holder: int | None = None
        self._last_seen: float = 0.0
        self._next_id = 1
        self._connections: set[int] = set()

    # ------------------------------------------------------------- connections
    def connect(self) -> int:
        """Register a new WS connection; returns its opaque id."""
        with self._lock:
            cid = self._next_id
            self._next_id += 1
            self._connections.add(cid)
            return cid

    def disconnect(self, cid: int) -> None:
        with self._lock:
            self._connections.discard(cid)
            if self._holder == cid:
                self._holder = None

    # ------------------------------------------------------------------ token
    def claim(self, cid: int) -> dict:
        """Explicit claim / takeover. Returns {holder, displaced}."""
        with self._lock:
            self._expire(self._clock())
            displaced = self._holder if self._holder not in (None, cid) else None
            self._holder = cid
            self._last_seen = self._clock()
            return {"holder": cid, "displaced": displaced}

    def note_intent(self, cid: int) -> bool:
        """A drive/mode intent arrived from cid. Auto-claims a free token and
        refreshes the holder's lease. Returns True iff cid may drive."""
        with self._lock:
            self._expire(self._clock())
            if self._holder is None:
                self._holder = cid
            if self._holder == cid:
                self._last_seen = self._clock()
                return True
            return False

    def heartbeat(self, cid: int) -> None:
        """Refresh the holder's lease without changing intent (keep-alive)."""
        with self._lock:
            if self._holder == cid:
                self._last_seen = self._clock()

    def release(self, cid: int) -> None:
        with self._lock:
            if self._holder == cid:
                self._holder = None

    def is_holder(self, cid: int) -> bool:
        with self._lock:
            self._expire(self._clock())
            return self._holder == cid

    def _expire(self, now: float) -> None:
        if self._holder is not None and (now - self._last_seen) > self.idle_timeout_s:
            self._holder = None

    @property
    def holder(self) -> int | None:
        with self._lock:
            self._expire(self._clock())
            return self._holder
