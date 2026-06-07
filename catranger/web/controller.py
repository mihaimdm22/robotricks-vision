"""RobotController: the safety-critical control core for the web platform.

Owns the run state (mode, manual drive vector, latched E-stop, watchdog) and the
per-tick decision — which Command to send given the mode and the latest
perception result — plus a single-writer .tick()/.shutdown() that talk to the
hardware bridge.

Designed for dependency injection so every safety behavior is unit-testable with
zero hardware: an injectable clock (like Follower), an injectable follower, and
injected run-loop collaborators (bridge, process fn) via .attach().

Import-safe: pulls only stdlib + catranger.types + catranger.control (no fastapi,
torch, or cv2). Heavy collaborators (a real pipeline, a real bridge) are injected
at runtime, never imported at module load. In M2 a single background thread calls
.tick() in a loop and is the SOLE writer to the bridge (no serial races); the
async server only reads published snapshots.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol

from catranger.control import Follower
from catranger.types import Command, FrameResult


class Mode(StrEnum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    FOLLOW = "FOLLOW"


class StopReason(StrEnum):
    """Why the robot is (not) moving — surfaced to the operator as a banner so a
    stop is never ambiguous (watchdog vs E-stop vs firmware 20cm vs lost target)."""

    NONE = "NONE"
    ESTOP = "ESTOP"
    WATCHDOG = "WATCHDOG"
    FIRMWARE_SAFE_STOP = "FIRMWARE_SAFE_STOP"
    TARGET_LOST = "TARGET_LOST"
    LINK_LOST = "LINK_LOST"
    CAMERA_LOST = "CAMERA_LOST"


_ACTIONS = ("forward", "back", "backward", "left", "right", "pan", "stop")


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


class ManualVector:
    """Operator drive intent in normalized [-1, 1] axes, mapped to a Command.

    forward/back -> v_fwd (+ = approach), left/right -> rotation (+ = turn right),
    pan -> Command.dy (camera pan servo). All inputs clamped server-side so a
    malformed client value can never escape [-1, 1].
    """

    def __init__(self) -> None:
        self.v_fwd = 0.0
        self.rotation = 0.0
        self.pan = 0.0

    def apply(self, action: str, value: float = 0.0) -> None:
        v = _clamp(float(value))
        if action == "forward":
            self.v_fwd = v
        elif action in ("back", "backward"):
            self.v_fwd = -v
        elif action == "right":
            self.rotation = v
        elif action == "left":
            self.rotation = -v
        elif action == "pan":
            self.pan = v
        elif action == "stop":
            self.v_fwd = self.rotation = self.pan = 0.0
        else:
            raise ValueError(f"unknown manual action {action!r}; expected one of {list(_ACTIONS)}")

    def to_command(self) -> Command:
        return Command(
            rotation=_clamp(self.rotation), v_fwd=_clamp(self.v_fwd), dy=_clamp(self.pan)
        )


class _FollowerLike(Protocol):
    def step(self, result: FrameResult) -> Command: ...
    def reset(self) -> None: ...


class _BridgeLike(Protocol):
    def send(self, cmd: Command) -> str: ...
    def read_distance_cm(self) -> int | None: ...
    def close(self) -> None: ...


class RobotController:
    """Single source of truth for what command the robot should execute."""

    def __init__(
        self,
        *,
        follow_cfg: dict | None = None,
        follower: _FollowerLike | None = None,
        clock: Callable[[], float] = time.perf_counter,
        watchdog_timeout_s: float = 0.5,
        safe_stop_cm: int = 20,
    ) -> None:
        self._clock = clock
        self.watchdog_timeout_s = float(watchdog_timeout_s)
        self.safe_stop_cm = int(safe_stop_cm)
        self.follower: _FollowerLike = (
            follower if follower is not None else Follower(follow_cfg or {}, clock=clock)
        )

        self._lock = threading.RLock()
        self.mode = Mode.IDLE
        self.manual = ManualVector()
        self.stop_reason = StopReason.NONE
        self._last_intent_ts: float | None = None
        self._estop = False

        # run-loop collaborators (injected via attach)
        self._bridge: _BridgeLike | None = None
        self.robot_connected = False
        self.camera_connected = False
        self._last_gt: int | None = None
        self.latest_telemetry: dict[str, Any] = {}

    # ---------------------------------------------------------------- intents
    def set_mode(self, mode: Mode | str) -> bool:
        """Switch mode. Refused (returns False) while E-stop is latched."""
        with self._lock:
            if self._estop:
                return False
            self.mode = Mode(mode)
            return True

    def set_manual(self, action: str, value: float = 0.0) -> None:
        with self._lock:
            self.manual.apply(action, value)
            self._last_intent_ts = self._clock()

    def heartbeat(self) -> None:
        """Keep-alive from the browser; refreshes the watchdog without changing intent."""
        with self._lock:
            self._last_intent_ts = self._clock()

    def estop(self) -> None:
        """Latch an emergency stop: zero the intent, drop to IDLE, refuse mode
        changes until reset()."""
        with self._lock:
            self._estop = True
            self.mode = Mode.IDLE
            self.manual.apply("stop")

    def reset(self) -> None:
        """Clear a latched E-stop (the deliberate ARM/RESET step). Mode stays IDLE."""
        with self._lock:
            self._estop = False
            self.stop_reason = StopReason.NONE

    @property
    def estopped(self) -> bool:
        return self._estop

    # ---------------------------------------------------------------- decision
    def decide(self, result: FrameResult | None = None, gt_cm: int | None = None) -> Command:
        """The per-tick command decision. Pure given (state, clock, result, gt)."""
        with self._lock:
            now = self._clock()

            if self._estop:
                self.stop_reason = StopReason.ESTOP
                return Command(state="SAFE")

            if self.mode == Mode.IDLE:
                self.stop_reason = StopReason.NONE
                return Command(state="IDLE")

            if self.mode == Mode.MANUAL:
                ts = self._last_intent_ts
                if ts is None or (now - ts) > self.watchdog_timeout_s:
                    self.stop_reason = StopReason.WATCHDOG
                    return Command(state="SEARCH")
                cmd = self.manual.to_command()
                cmd.state = "MANUAL"
                if gt_cm is not None and 0 <= gt_cm < self.safe_stop_cm and cmd.v_fwd > 0:
                    # obstacle inside the firmware floor: neutralize forward, keep turn
                    self.stop_reason = StopReason.FIRMWARE_SAFE_STOP
                    return Command(rotation=cmd.rotation, v_fwd=0.0, dy=cmd.dy, state="SAFE")
                self.stop_reason = StopReason.NONE
                return cmd

            # FOLLOW: hand off to the autonomous Follower (existing core)
            follow_result = result if result is not None else FrameResult(frame_index=0)
            cmd = self.follower.step(follow_result)
            self.stop_reason = (
                StopReason.NONE if follow_result.target is not None else StopReason.TARGET_LOST
            )
            return cmd

    # --------------------------------------------------------------- run loop
    def attach(self, *, bridge: _BridgeLike) -> None:
        """Inject the hardware bridge (the SOLE writer is this controller). A
        DummyBridge reads as 'simulation', not 'connected'."""
        self._bridge = bridge
        self.robot_connected = type(bridge).__name__ != "DummyBridge"

    def apply(self, result: FrameResult | None = None, frame_index: int = 0) -> Command:
        """One control iteration on an ALREADY-computed perception result: decide ->
        send -> read GT -> publish telemetry. Perception + drawing live in the runtime
        (this stays pure: no cv2/torch). Never raises on a dead bridge."""
        cmd = self.decide(result, gt_cm=self._last_gt)
        self._safe_send(cmd)
        self._last_gt = self._safe_read_gt()
        target = result.target if result is not None else None
        known_ids = list(result.target_known_ids) if result is not None else []
        with self._lock:
            self.latest_telemetry = {
                "frame_index": frame_index,
                "mode": self.mode.value,
                "stop_reason": self.stop_reason.value,
                "command": cmd.as_dict(),
                "gt_cm": self._last_gt,
                "estop": self._estop,
                "robot_connected": self.robot_connected,
                "camera_connected": self.camera_connected,
                "n_cats": len(result.observations) if result is not None else 0,
                "fps": round(result.fps, 1) if result is not None else None,
                "target_id": target.track_id if target is not None else None,
                "target_ids": known_ids,
                "target_dist_m": (
                    round(target.distance.meters, 2)
                    if target is not None and target.distance is not None
                    else None
                ),
                "target_bearing_deg": round(target.bearing_deg, 1) if target is not None else None,
            }
        return cmd

    def shutdown(self) -> None:
        """Fail-safe teardown: latch stop, send a final all-zero command, close the
        bridge. So a Ctrl-C never leaves motors latched."""
        with self._lock:
            self._estop = True
            self.mode = Mode.IDLE
        self._safe_send(Command())  # all-zero
        bridge = self._bridge
        if bridge is not None:
            try:
                bridge.close()
            except Exception:
                pass

    # ----------------------------------------------------------------- helpers
    def _safe_send(self, cmd: Command) -> None:
        bridge = self._bridge
        if bridge is None:
            return
        try:
            bridge.send(cmd)
        except Exception:
            self._degrade_bridge()

    def _safe_read_gt(self) -> int | None:
        bridge = self._bridge
        if bridge is None:
            return None
        try:
            return bridge.read_distance_cm()
        except Exception:
            return None

    def _degrade_bridge(self) -> None:
        """A failed link must not crash the loop: fall back to a DummyBridge and
        surface the loss. The control thread stays the single writer."""
        from catranger.hw.serial_bridge import DummyBridge

        self.robot_connected = False
        self.stop_reason = StopReason.LINK_LOST
        self._bridge = DummyBridge()
