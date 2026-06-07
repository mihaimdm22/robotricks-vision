"""Follow controller — the safety-critical state machine and anti-oscillation pipeline.

Uses an injected fake clock so the time-driven COAST/SEARCH transitions are
deterministic (the reason control.Follower takes a `clock` argument).
"""

from __future__ import annotations

from catranger.control import Follower, enrich_result_sonar_distance
from catranger.types import CatObservation, Detection, DistanceResult, FrameResult


class FakeClock:
    """Monotonic clock the test drives by hand."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _frame(
    track_id: int = 1,
    meters: float = 2.0,
    bearing_deg: float = 0.0,
    idx: int = 0,
    known_ids: list[int] | None = None,
) -> FrameResult:
    det = Detection(
        xyxy=(900.0, 400.0, 1020.0, 580.0), conf=0.9, cls_id=15, cls_name="cat", track_id=track_id
    )
    dist = DistanceResult(meters=meters, lo=meters - 0.1, hi=meters + 0.1, method="geometry")
    obs = CatObservation(detection=det, distance=dist, bearing_deg=bearing_deg)
    return FrameResult(
        frame_index=idx,
        observations=[obs],
        target_observation=obs,
        target_known_ids=known_ids or [track_id],
    )


def _empty(idx: int = 0) -> FrameResult:
    return FrameResult(frame_index=idx)


def test_search_when_no_target_and_no_history() -> None:
    f = Follower({})
    cmd = f.step(_empty())
    assert cmd.state == "SEARCH"
    assert cmd.v_fwd == 0.0  # never drive forward while searching


def test_acquire_then_track_sequence() -> None:
    clk = FakeClock()
    f = Follower({"acquire_frames": 3}, clock=clk)
    states = []
    for i in range(5):
        clk.advance(0.066)
        states.append(f.step(_frame(meters=2.0, idx=i)).state)
    assert states[:3] == ["ACQUIRE", "ACQUIRE", "ACQUIRE"]
    assert states[3] == "TRACK"
    assert states[4] == "TRACK"


def test_alias_track_id_does_not_reset_acquire() -> None:
    clk = FakeClock()
    f = Follower({"acquire_frames": 3}, clock=clk)
    for i in range(3):
        clk.advance(0.066)
        assert f.step(_frame(track_id=1, idx=i, known_ids=[1])).state == "ACQUIRE"
    clk.advance(0.066)
    assert f.step(_frame(track_id=7, idx=3, known_ids=[1, 7])).state == "TRACK"


def test_safe_state_never_drives_forward_from_rest() -> None:
    f = Follower({})
    cmd = f.step(_frame(meters=0.2))  # inside safe_distance (0.4 m)
    assert cmd.state == "SAFE"
    assert cmd.v_fwd <= 0.0


def test_coast_within_timeout_then_search_after() -> None:
    clk = FakeClock()
    f = Follower({"lost_timeout_s": 1.0}, clock=clk)
    clk.advance(0.1)
    f.step(_frame(meters=2.0))  # establishes last-seen time
    clk.advance(0.5)
    assert f.step(_empty()).state == "COAST"  # lost, still within timeout
    clk.advance(2.0)
    assert f.step(_empty()).state == "SEARCH"  # lost beyond timeout


def test_commands_clamped_and_slew_limited() -> None:
    clk = FakeClock()
    f = Follower({"slew_max": 0.15}, clock=clk)
    prev_rot, prev_v = 0.0, 0.0
    for i in range(10):
        clk.advance(0.066)
        cmd = f.step(_frame(meters=5.0, bearing_deg=80.0, idx=i))  # large raw demand
        assert -1.0 <= cmd.rotation <= 1.0
        assert -1.0 <= cmd.v_fwd <= 1.0
        assert abs(cmd.rotation - prev_rot) <= 0.15 + 1e-9
        assert abs(cmd.v_fwd - prev_v) <= 0.15 + 1e-9
        prev_rot, prev_v = cmd.rotation, cmd.v_fwd


def test_enrich_result_sonar_fills_missing_vision_distance() -> None:
    import math

    det = Detection(
        xyxy=(900.0, 400.0, 1020.0, 580.0), conf=0.9, cls_id=15, cls_name="cat", track_id=1
    )
    dist = DistanceResult(meters=float("nan"), lo=0.0, hi=0.0, method="geometry")
    obs = CatObservation(detection=det, distance=dist, bearing_deg=0.0)
    frame = FrameResult(frame_index=0, observations=[obs], target_observation=obs)
    enriched = enrich_result_sonar_distance(frame, gt_cm=125, baseline_m=0.09)
    assert enriched.target is not None
    assert enriched.target.distance is not None
    assert math.isfinite(enriched.target.distance.meters)
    assert enriched.target.distance.method == "sonar"
    f = Follower({})
    cmd = f.step(enriched)
    assert cmd.state in ("ACQUIRE", "TRACK", "SAFE")
