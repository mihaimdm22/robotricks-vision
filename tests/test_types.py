"""Shared data contracts — the geometry properties every module relies on."""

from __future__ import annotations

import pytest

from catranger.types import (
    CatObservation,
    Command,
    Detection,
    DistanceResult,
    FrameResult,
)


def test_detection_box_geometry() -> None:
    d = Detection(xyxy=(10.0, 20.0, 40.0, 60.0), conf=0.9, cls_id=15)
    assert d.width == 30.0
    assert d.height == 40.0
    assert d.area == 1200.0
    assert d.center == (25.0, 40.0)


def test_distance_result_half_width() -> None:
    r = DistanceResult(meters=2.0, lo=1.5, hi=2.5, method="fused")
    assert r.half_width == pytest.approx(0.5)


def test_frame_target_is_none_when_empty() -> None:
    assert FrameResult(frame_index=0).target is None


def test_frame_target_is_largest_box() -> None:
    small = CatObservation(detection=Detection(xyxy=(0.0, 0.0, 10.0, 10.0), conf=0.5, cls_id=15))
    big = CatObservation(detection=Detection(xyxy=(0.0, 0.0, 100.0, 100.0), conf=0.5, cls_id=15))
    fr = FrameResult(frame_index=0, observations=[small, big])
    assert fr.target is big


def test_command_as_dict_rounds_and_carries_state() -> None:
    d = Command(rotation=0.123456, v_fwd=-0.2, state="TRACK", target_id=3).as_dict()
    assert d["rotation"] == pytest.approx(0.1235, abs=1e-4)
    assert d["state"] == "TRACK"
    assert d["target_id"] == 3
