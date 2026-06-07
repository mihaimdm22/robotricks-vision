"""Tests for the WS-B0 overlay-JSON contract builder (catranger.web.overlay)."""

from __future__ import annotations

from catranger.types import CatObservation, Detection, DistanceResult, FrameResult
from catranger.web.overlay import build_overlay


def _obs(x1, y1, x2, y2, *, conf=0.9, tid=1, meters=2.0, lo=1.8, hi=2.2, comps=None):
    det = Detection(xyxy=(x1, y1, x2, y2), conf=conf, cls_id=15, cls_name="cat", track_id=tid)
    dist = None
    if meters is not None:
        dist = DistanceResult(meters=meters, lo=lo, hi=hi, method="fused", components=comps or {})
    return CatObservation(detection=det, distance=dist, bearing_deg=3.0)


def test_none_result_is_well_formed():
    o = build_overlay(None, 7)
    assert o["frame_id"] == 7
    assert o["dets"] == []
    assert "no_frame" in o["global_flags"]


def test_no_detections_flag():
    o = build_overlay(FrameResult(frame_index=0, width=100, height=100), 0)
    assert o["dets"] == []
    assert "no_detections" in o["global_flags"]


def test_normalizes_coords_and_marks_largest_as_target():
    small = _obs(0, 0, 10, 10, tid=1)
    big = _obs(0, 0, 80, 80, tid=2)  # larger area -> target
    res = FrameResult(frame_index=3, observations=[small, big], width=100, height=100)
    o = build_overlay(res, 3)
    assert (o["frame_w"], o["frame_h"]) == (100, 100)
    by_id = {d["track_id"]: d for d in o["dets"]}
    assert by_id[2]["is_target"] is True
    assert by_id[1]["is_target"] is False
    assert by_id[2]["xyxy_norm"] == [0.0, 0.0, 0.8, 0.8]


def test_flags_low_conf_and_no_distance():
    res = FrameResult(
        frame_index=0,
        observations=[_obs(0, 0, 10, 10, conf=0.1, meters=None)],
        width=100,
        height=100,
    )
    flags = build_overlay(res, 0)["dets"][0]["flags"]
    assert "low_conf" in flags
    assert "no_distance" in flags


def test_flags_wide_ci_and_depth_geom_disagreement():
    obs = _obs(
        0, 0, 10, 10, conf=0.9, meters=2.0, lo=1.0, hi=3.0, comps={"geometry": 1.0, "depth": 3.0}
    )
    res = FrameResult(frame_index=0, observations=[obs], width=100, height=100)
    flags = build_overlay(res, 0)["dets"][0]["flags"]
    assert "wide_ci" in flags  # half_width 1.0 > 0.3 * 2.0
    assert "depth_geom_disagree" in flags  # |1-3|/3 = 0.67 > 0.3
