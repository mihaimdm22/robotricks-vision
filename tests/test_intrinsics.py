"""Camera geometry — the math that turns pixels into meters and bearings.

A regression here is a silent, constant error on the *scored* distance, so these
pin the formulas, the axis usage (fx vs fy), and the FOV-undistort center fixity.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from catranger.config import CameraConfig
from catranger.intrinsics import CameraModel


def test_distance_from_height_formula(cam: CameraModel) -> None:
    # Z = fy * H_real / h_px
    assert cam.distance_from_height(100.0, 0.3) == pytest.approx(554.3 * 0.3 / 100.0)


def test_distance_from_width_formula(cam: CameraModel) -> None:
    # Z = fx * W_real / w_px
    assert cam.distance_from_width(200.0, 0.5) == pytest.approx(554.3 * 0.5 / 200.0)


def test_nonpositive_pixel_extent_is_nan_not_exception(cam: CameraModel) -> None:
    assert math.isnan(cam.distance_from_height(0.0, 0.3))
    assert math.isnan(cam.distance_from_height(-5.0, 0.3))
    assert math.isnan(cam.distance_from_width(0.0, 0.5))


def test_height_uses_fy_width_uses_fx() -> None:
    # With fx != fy the two cues must disagree — guards against an axis swap.
    cfg = CameraConfig(name="x", fx=500.0, fy=800.0, cx=320.0, cy=240.0, width=640, height=480)
    cam = CameraModel(cfg)
    assert cam.distance_from_height(100.0, 1.0) == pytest.approx(800.0 / 100.0)
    assert cam.distance_from_width(100.0, 1.0) == pytest.approx(500.0 / 100.0)
    assert cam.distance_from_height(100.0, 1.0) != cam.distance_from_width(100.0, 1.0)


def test_bearing_zero_at_optical_center(cam: CameraModel) -> None:
    assert cam.bearing_rad(cam.cx) == pytest.approx(0.0)
    assert cam.bearing_deg(cam.cx) == pytest.approx(0.0)


def test_bearing_sign_right_is_positive(cam: CameraModel) -> None:
    assert cam.bearing_deg(cam.cx + 100.0) > 0.0
    assert cam.bearing_deg(cam.cx - 100.0) < 0.0


def test_centering_weight_peaks_at_center_and_decays(cam: CameraModel) -> None:
    center = cam.centering_weight(cam.cx, cam.cy)
    mid = cam.centering_weight(cam.cx + 200.0, cam.cy)
    far = cam.centering_weight(cam.cx + 400.0, cam.cy)
    assert center == pytest.approx(1.0)
    assert far < mid < center


def test_backproject_center_is_on_optical_axis(cam: CameraModel) -> None:
    p = cam.backproject(cam.cx, cam.cy, 3.0)
    assert p[0] == pytest.approx(0.0)
    assert p[1] == pytest.approx(0.0)
    assert p[2] == pytest.approx(3.0)


def test_inter_object_distance(cam: CameraModel) -> None:
    same = cam.inter_object_distance((cam.cx, cam.cy), 2.0, (cam.cx, cam.cy), 2.0)
    assert same == pytest.approx(0.0)
    # a pixel offset of fx at depth Z back-projects to a lateral X of exactly Z
    apart = cam.inter_object_distance((cam.cx, cam.cy), 2.0, (cam.cx + cam.fx, cam.cy), 2.0)
    assert apart == pytest.approx(2.0)


def test_undistort_none_is_identity_noop() -> None:
    cfg = CameraConfig(
        name="x",
        fx=500.0,
        fy=500.0,
        cx=320.0,
        cy=240.0,
        width=640,
        height=480,
        dist_model="none",
    )
    cam = CameraModel(cfg)
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    assert cam.undistort(img) is img


def test_fov_maps_keep_optical_center_fixed(cam: CameraModel) -> None:
    pytest.importorskip("cv2")
    cam._build_maps(cam.width, cam.height)
    assert cam._map_x is not None and cam._map_y is not None
    cy, cx = int(cam.cy), int(cam.cx)
    assert cam._map_x[cy, cx] == pytest.approx(cam.cx, abs=1.0)
    assert cam._map_y[cy, cx] == pytest.approx(cam.cy, abs=1.0)
    assert cam._map_x.shape == (cam.height, cam.width)
    assert cam._map_y.shape == (cam.height, cam.width)
