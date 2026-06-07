"""Distance fusion — geometry + (optional) depth into one metric estimate + CI.

`_weighted_median` IS the fused distance, so its tie/parity behavior is load-bearing;
a change there shifts every fused number the judges grade.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from catranger.distance import DistanceEstimator, _erode_box, _weighted_median
from catranger.intrinsics import CameraModel
from catranger.types import Detection

_PRIOR = {"cat": {"cue": "height", "real_m": 0.3, "range_m": [0.25, 0.35], "weight": 1.0}}


def _det() -> Detection:
    # height = 180 px, width = 120 px, center = (960, 490)
    return Detection(xyxy=(900.0, 400.0, 1020.0, 580.0), conf=0.9, cls_id=15, cls_name="cat")


def test_weighted_median_single_value() -> None:
    assert _weighted_median([3.0], [1.0]) == 3.0


def test_weighted_median_tie_break_is_lower_index() -> None:
    # values [1,3] equal weights: cumsum=[1,2], target 0.5*2=1.0,
    # searchsorted-left -> index 0 -> 1.0. This exact rule must not drift.
    assert _weighted_median([1.0, 3.0], [1.0, 1.0]) == 1.0


def test_weighted_median_drops_nan_values() -> None:
    assert _weighted_median([1.0, float("nan"), 5.0], [1.0, 2.0, 1.0]) == 1.0


def test_weighted_median_all_zero_weight_is_nan() -> None:
    assert math.isnan(_weighted_median([1.0, 2.0], [0.0, 0.0]))


def test_weighted_median_empty_is_nan() -> None:
    assert math.isnan(_weighted_median([], []))


def test_estimate_geometry_only(cam: CameraModel) -> None:
    est = DistanceEstimator(cam, _PRIOR)
    r = est.estimate(_det())
    assert r.method == "geometry"
    assert r.meters == pytest.approx(554.3 * 0.3 / 180.0, rel=1e-3)
    assert r.lo <= r.meters <= r.hi
    assert r.half_width > 0.0  # the prior's size range produces a real spread


def test_estimate_fused_widens_to_estimator_disagreement(cam: CameraModel) -> None:
    est = DistanceEstimator(cam, _PRIOR)
    depth = np.full((1080, 1920), 1.2, dtype=np.float64)
    r = est.estimate(_det(), depth_map=depth)
    assert r.method == "fused"
    assert not math.isnan(r.components["geometry"])
    assert r.components["depth"] == pytest.approx(1.2)
    # CI must be at least half the gap between the two estimators
    gap = 0.5 * abs(r.components["geometry"] - r.components["depth"])
    assert r.half_width >= gap - 1e-9


def test_estimate_no_prior_is_none_not_exception(cam: CameraModel) -> None:
    est = DistanceEstimator(cam, {})
    r = est.estimate(
        Detection(xyxy=(900.0, 400.0, 1020.0, 580.0), conf=0.9, cls_id=99, cls_name="dog")
    )
    assert r.method == "none"
    assert math.isnan(r.meters)


def test_calibrate_scale_median_ratio_and_stores(cam: CameraModel) -> None:
    est = DistanceEstimator(cam, _PRIOR)
    alpha = est.calibrate_scale([("cat", 1.0, 2.0), ("cat", 2.0, 4.0)])
    assert alpha["cat"] == pytest.approx(2.0)  # median(2/1, 4/2)
    assert est.alpha["cat"] == pytest.approx(2.0)  # persisted onto the estimator


def test_calibrate_scale_skips_bad_pairs(cam: CameraModel) -> None:
    est = DistanceEstimator(cam, _PRIOR)
    alpha = est.calibrate_scale([("cat", 0.0, 2.0), ("cat", "x", 1.0), ("cat", 1.0, 3.0)])
    assert alpha["cat"] == pytest.approx(3.0)  # only the (1.0, 3.0) pair survives


def test_calibrate_scale_empty_is_empty(cam: CameraModel) -> None:
    assert DistanceEstimator(cam, {}).calibrate_scale([]) == {}


# ---- WS-D1: eroded-box depth median ----


def test_erode_box_keeps_central_fraction() -> None:
    # 100-wide, 100-tall box, frac 0.2 -> keep central 80% (10px margin each side).
    assert _erode_box(0.0, 0.0, 100.0, 100.0, 0.2) == (10.0, 10.0, 90.0, 90.0)


def test_erode_box_noop_when_frac_zero() -> None:
    assert _erode_box(5.0, 6.0, 7.0, 8.0, 0.0) == (5.0, 6.0, 7.0, 8.0)


def test_box_erosion_excludes_edge_background_from_depth_median(cam: CameraModel) -> None:
    # Build a depth map where the detection box is mostly far background (5.0) with a
    # central object region (1.0). Eroding the box should sample the object, not the edges.
    det = _det()  # box (900,400)-(1020,580): 120 wide, 180 tall
    dm = np.full((1080, 1920), 5.0, dtype=np.float64)
    dm[445:535, 930:990] = 1.0  # central ~50% of the box = the "cat"

    no_erode = DistanceEstimator(cam, _PRIOR).estimate(det, depth_map=dm)
    eroded = DistanceEstimator(cam, _PRIOR, box_erosion=0.6).estimate(det, depth_map=dm)

    assert no_erode.components["depth"] == pytest.approx(5.0)  # edges dominate the full box
    assert eroded.components["depth"] == pytest.approx(1.0)  # eroded box sees the object


def test_box_erosion_falls_back_to_full_box_when_it_would_collapse(cam: CameraModel) -> None:
    # A 1px box + heavy erosion would collapse to nothing; we must fall back to the full
    # box (a real, if noisy, reading) rather than drop the detection to NaN.
    tiny = Detection(xyxy=(900.0, 400.0, 901.0, 401.0), conf=0.9, cls_id=15, cls_name="cat")
    dm = np.full((1080, 1920), 2.0, dtype=np.float64)
    z, w = DistanceEstimator(cam, _PRIOR, box_erosion=0.8)._depth(tiny, dm, None)
    assert z == pytest.approx(2.0)
    assert w == 1.0
