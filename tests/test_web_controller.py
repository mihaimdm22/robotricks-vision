"""M1 controller: the safety-critical decision core + run-loop plumbing.

All deterministic, hardware-free. The run loop takes injected collaborators
(frame iterator, bridge, process fn) and an injectable clock — mirroring the
Follower's testable design — so the watchdog, E-stop latch, mode arbitration,
and shutdown-sends-zero behaviors are exercised without a real device.
"""

from __future__ import annotations

from catranger.types import (
    CatObservation,
    Command,
    Detection,
    DistanceResult,
    FrameResult,
)
from catranger.web.controller import ManualVector, Mode, RobotController, StopReason


class FakeClock:
    """Mutable monotonic clock for deterministic watchdog tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class RecordingBridge:
    """DummyBridge-shaped stand-in that records every Command it is sent."""

    def __init__(self, gt_cm: int | None = None, fail: bool = False) -> None:
        self.sent: list[Command] = []
        self.closed = False
        self._gt = gt_cm
        self._fail = fail

    def send(self, cmd: Command) -> str:
        if self._fail:
            raise RuntimeError("link down")
        self.sent.append(cmd)
        return "ok"

    def read_distance_cm(self) -> int | None:
        return self._gt

    def close(self) -> None:
        self.closed = True


def _target_frame() -> FrameResult:
    """A FrameResult with one in-range tracked cat (a follow target)."""
    det = Detection(xyxy=(100, 100, 200, 260), conf=0.9, cls_id=15, track_id=7)
    dist = DistanceResult(meters=2.0, lo=1.8, hi=2.2, method="fused")
    obs = CatObservation(detection=det, distance=dist, bearing_deg=0.0)
    return FrameResult(frame_index=0, observations=[obs])


# --------------------------------------------------------------- ManualVector


def test_manual_vector_maps_actions_to_command_fields() -> None:
    mv = ManualVector()
    mv.apply("forward", 0.6)
    mv.apply("right", 0.4)
    mv.apply("pan", -0.5)
    cmd = mv.to_command()
    assert cmd.v_fwd == 0.6  # forward -> +v_fwd
    assert cmd.rotation == 0.4  # right -> +rotation
    assert cmd.dy == -0.5  # pan -> camera servo (Command.dy)


def test_manual_vector_left_and_back_are_negative() -> None:
    mv = ManualVector()
    mv.apply("back", 0.7)
    mv.apply("left", 0.3)
    cmd = mv.to_command()
    assert cmd.v_fwd == -0.7
    assert cmd.rotation == -0.3


def test_manual_vector_clamps_out_of_range_input() -> None:
    mv = ManualVector()
    mv.apply("forward", 9.0e9)
    mv.apply("right", -50.0)
    cmd = mv.to_command()
    assert cmd.v_fwd == 1.0
    assert cmd.rotation == -1.0


def test_manual_vector_stop_zeros_all_axes() -> None:
    mv = ManualVector()
    mv.apply("forward", 1.0)
    mv.apply("right", 1.0)
    mv.apply("stop", 0.0)
    cmd = mv.to_command()
    assert (cmd.v_fwd, cmd.rotation, cmd.dy) == (0.0, 0.0, 0.0)


def test_manual_vector_rejects_unknown_action() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown manual action"):
        ManualVector().apply("teleport", 1.0)


# --------------------------------------------------------------- decide / mode


def test_idle_mode_commands_zero() -> None:
    c = RobotController(clock=FakeClock())
    cmd = c.decide()
    assert cmd.v_fwd == 0.0 and cmd.rotation == 0.0
    assert c.stop_reason == StopReason.NONE


def test_manual_fresh_intent_passes_through() -> None:
    clk = FakeClock()
    c = RobotController(clock=clk, watchdog_timeout_s=0.5)
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 0.5)
    cmd = c.decide()
    assert cmd.v_fwd == 0.5
    assert c.stop_reason == StopReason.NONE


def test_manual_stale_intent_triggers_watchdog_zero() -> None:
    clk = FakeClock()
    c = RobotController(clock=clk, watchdog_timeout_s=0.5)
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 0.8)
    clk.t += 1.0  # exceed the 0.5s dead-man window
    cmd = c.decide()
    assert cmd.v_fwd == 0.0 and cmd.rotation == 0.0
    assert c.stop_reason == StopReason.WATCHDOG


def test_manual_with_no_intent_yet_is_watchdog_stopped() -> None:
    c = RobotController(clock=FakeClock(), watchdog_timeout_s=0.5)
    c.set_mode(Mode.MANUAL)
    cmd = c.decide()
    assert cmd.v_fwd == 0.0
    assert c.stop_reason == StopReason.WATCHDOG


def test_heartbeat_refreshes_the_watchdog() -> None:
    clk = FakeClock()
    c = RobotController(clock=clk, watchdog_timeout_s=0.5)
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 0.4)
    clk.t += 0.4
    c.heartbeat()  # keep-alive before the window closes
    clk.t += 0.4  # 0.4s since heartbeat < 0.5s window
    cmd = c.decide()
    assert cmd.v_fwd == 0.4
    assert c.stop_reason == StopReason.NONE


# --------------------------------------------------------------- E-stop latch


def test_estop_zeros_and_latches_to_idle() -> None:
    c = RobotController(clock=FakeClock())
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 1.0)
    c.estop()
    cmd = c.decide()
    assert cmd.v_fwd == 0.0
    assert c.stop_reason == StopReason.ESTOP
    assert c.mode == Mode.IDLE


def test_estop_blocks_mode_change_until_reset() -> None:
    c = RobotController(clock=FakeClock())
    c.estop()
    changed = c.set_mode(Mode.MANUAL)
    assert changed is False  # refused while latched
    assert c.mode == Mode.IDLE
    c.reset()
    assert c.set_mode(Mode.MANUAL) is True
    assert c.mode == Mode.MANUAL


def test_estop_is_sticky_against_a_later_manual_intent() -> None:
    """A second client jabbing the drive pad must NOT clear a latched E-stop."""
    c = RobotController(clock=FakeClock())
    c.set_mode(Mode.MANUAL)
    c.estop()
    c.set_manual("forward", 1.0)  # conflicting intent from another client
    cmd = c.decide()
    assert cmd.v_fwd == 0.0
    assert c.stop_reason == StopReason.ESTOP


# --------------------------------------------------------------- arbitration


def test_follow_uses_follower_output_and_ignores_manual_vector() -> None:
    class StubFollower:
        def step(self, result: FrameResult) -> Command:
            return Command(v_fwd=0.33, rotation=0.11, state="TRACK")

        def reset(self) -> None:  # noqa: D401 - matches Follower interface
            pass

    c = RobotController(clock=FakeClock(), follower=StubFollower())
    c.set_mode(Mode.FOLLOW)
    c.set_manual("forward", 1.0)  # must be ignored in FOLLOW
    cmd = c.decide(_target_frame())
    assert cmd.v_fwd == 0.33 and cmd.rotation == 0.11


def test_manual_mode_ignores_the_follower() -> None:
    class LoudFollower:
        def step(self, result: FrameResult) -> Command:
            return Command(v_fwd=0.99, rotation=0.99)

        def reset(self) -> None:
            pass

    clk = FakeClock()
    c = RobotController(clock=clk, follower=LoudFollower())
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 0.2)
    cmd = c.decide(_target_frame())
    assert cmd.v_fwd == 0.2  # manual wins, follower ignored


def test_follow_with_no_target_reports_target_lost() -> None:
    c = RobotController(clock=FakeClock())
    c.set_mode(Mode.FOLLOW)
    c.decide(FrameResult(frame_index=0, observations=[]))
    assert c.stop_reason == StopReason.TARGET_LOST


# --------------------------------------------------------------- firmware safe-stop


def test_firmware_safe_stop_neutralizes_forward_in_manual() -> None:
    clk = FakeClock()
    c = RobotController(clock=clk, watchdog_timeout_s=0.5, safe_stop_cm=20)
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 1.0)
    cmd = c.decide(gt_cm=12)  # obstacle inside the 20cm floor
    assert cmd.v_fwd == 0.0
    assert c.stop_reason == StopReason.FIRMWARE_SAFE_STOP


# --------------------------------------------------------------- run loop / shutdown


def test_apply_sends_the_decided_command_to_the_bridge() -> None:
    clk = FakeClock()
    bridge = RecordingBridge(gt_cm=150)
    c = RobotController(clock=clk)
    c.attach(bridge=bridge)
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 0.5)
    c.apply(FrameResult(frame_index=0), frame_index=0)
    assert bridge.sent[-1].v_fwd == 0.5
    # telemetry is published for the server/UI to read
    assert c.latest_telemetry["mode"] == "MANUAL"
    assert c.latest_telemetry["gt_cm"] == 150


def test_bridge_send_failure_degrades_and_keeps_motors_safe() -> None:
    c = RobotController(clock=FakeClock())
    c.attach(bridge=RecordingBridge(fail=True))
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 1.0)
    # a raising bridge must not crash apply(); controller degrades to a dummy
    c.apply(FrameResult(frame_index=0), frame_index=0)
    assert c.robot_connected is False
    assert c.stop_reason == StopReason.LINK_LOST


def test_shutdown_sends_a_final_zero_and_closes_the_bridge() -> None:
    bridge = RecordingBridge()
    c = RobotController(clock=FakeClock())
    c.attach(bridge=bridge)
    c.set_mode(Mode.MANUAL)
    c.set_manual("forward", 1.0)
    c.shutdown()
    assert bridge.closed is True
    last = bridge.sent[-1]
    assert (last.v_fwd, last.rotation, last.dx, last.dy) == (0.0, 0.0, 0.0, 0.0)
    assert c.mode == Mode.IDLE
