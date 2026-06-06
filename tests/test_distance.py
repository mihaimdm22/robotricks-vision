"""Distance fusion — geometry + (optional) depth into one metric estimate + CI.

`_weighted_median` IS the fused distance, so its tie/parity behavior is load-bearing;
a change there shifts every fused number the judges grade.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from catranger.distance import DistanceEstimator, _weighted_median
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
