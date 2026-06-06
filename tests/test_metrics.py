"""Eval metrics — the numbers the judges grade. Pin the definitions exactly."""

from __future__ import annotations

import numpy as np
import pytest

from catranger.eval.metrics import (
    _percentile,
    _sign_changes,
    distance_mae,
    fps_stats,
    smoothness,
    synthetic_occlusion_reacquire,
    track_stats,
)
from catranger.types import CatObservation, Command, Detection, FrameResult


def _fr(idx: int, ids: list[int]) -> FrameResult:
    obs = [
        CatObservation(
            detection=Detection(xyxy=(0.0, 0.0, 10.0, 10.0), conf=0.9, cls_id=15, track_id=tid)
        )
        for tid in ids
    ]
    return FrameResult(frame_index=idx, observations=obs)


def test_fps_uses_inverse_mean_dt_not_mean_of_fps() -> None:
    # dts 0.05 + 0.15 -> mean dt 0.1 -> 10 FPS. Mean of per-frame fps would be 13.3.
    assert fps_stats([0.05, 0.15])["mean_fps"] == pytest.approx(10.0)


def test_fps_drops_nonpositive_and_none() -> None:
    s = fps_stats([0.1, 0.0, -1.0, None, 0.1])  # type: ignore[list-item]
    assert s["n"] == 2
    assert s["mean_fps"] == pytest.approx(10.0)


def test_fps_empty_is_zeros() -> None:
    assert fps_stats([]) == {"mean_fps": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "n": 0}


def test_percentile_matches_numpy_linear() -> None:
    vals = [0.01, 0.02, 0.03, 0.04, 0.05]
    assert _percentile(vals, 95.0) == pytest.approx(float(np.percentile(vals, 95.0)))
    assert _percentile(vals, 50.0) == pytest.approx(float(np.percentile(vals, 50.0)))


def test_distance_mae_basic() -> None:
    r = distance_mae([1.0, 2.0, 3.0], [1.5, 2.0, 2.0])
    assert r["mae"] == pytest.approx(0.5)  # mean(|.5|, 0, |1|)
    assert r["n"] == 3


def test_distance_mae_skips_nonfinite_but_counts_zero_gt_in_mae() -> None:
    r = distance_mae([1.0, float("nan"), 2.0], [1.0, 5.0, 0.0])
    assert r["n"] == 2  # nan pred dropped; (2, gt=0) still counts toward MAE
    assert r["mae"] == pytest.approx(1.0)


def test_track_stats_counts_target_switches_and_streaks() -> None:
    frames = [_fr(0, [1]), _fr(1, [1]), _fr(2, [2]), _fr(3, [2])]
    s = track_stats(frames)
    assert s["unique_ids"] == 2
    assert s["num_id_switches"] == 1  # target id 1,1,2,2 -> one flip
    assert s["longest_streak"] == 2


def test_sign_changes_ignores_zero_crossing() -> None:
    assert _sign_changes([1.0, 0.0, 1.0]) == 0  # passes through zero, same sign
    assert _sign_changes([1.0, -1.0, 1.0]) == 2
    assert _sign_changes([1.0, 1.0, 1.0]) == 0


def test_smoothness_jerk_and_empty() -> None:
    cmds = [Command(rotation=0.0), Command(rotation=0.2), Command(rotation=0.1)]
    s = smoothness(cmds)
    assert s["rotation_jerk"] == pytest.approx((0.2 + 0.1) / 2)
    assert s["n"] == 3
    empty = smoothness([])
    assert empty["n"] == 0
    assert empty["rotation_oscillations"] == 0


def test_occlusion_reacquire_scoring() -> None:
    assert synthetic_occlusion_reacquire() == {}
    hit = synthetic_occlusion_reacquire(pre_id=5, post_id=5, gap_frames=15, reacquired_frame=3)
    assert hit["reacquired"] is True
    assert hit["reacquire_latency_frames"] == 3
    miss = synthetic_occlusion_reacquire(pre_id=5, post_id=6, gap_frames=10)
    assert miss["reacquired"] is False
