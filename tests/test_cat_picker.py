"""Preferred-target locking and cat catalog thumbnails."""

from __future__ import annotations

import numpy as np

from catranger.detect import Detection
from catranger.track import CatTracker
from catranger.types import CatObservation, DistanceResult, FrameResult
from catranger.web.cat_catalog import build_cat_catalog


class _FakeDetector:
    def track(self, frame_bgr, tracker="botsort.yaml", persist=True):
        return list(self._dets)

    def __init__(self, dets: list[Detection]):
        self._dets = dets


def _det(tid: int, area: int) -> Detection:
    side = int(area**0.5)
    return Detection(xyxy=(0.0, 0.0, float(side), float(side)), conf=0.9, cls_id=15, track_id=tid)


def test_preferred_id_locks_smaller_cat():
    det = _FakeDetector([_det(1, 400), _det(2, 100)])
    trk = CatTracker(det, lock_hysteresis=5)
    trk.set_preferred_id(2)
    picked = trk.select_target(det._dets)
    assert picked is not None and picked.track_id == 2


def test_preferred_id_returns_none_when_missing():
    det = _FakeDetector([_det(1, 400)])
    trk = CatTracker(det, lock_hysteresis=1)
    trk.set_preferred_id(99)
    assert trk.select_target(det._dets) is None


def test_build_cat_catalog_includes_thumb() -> None:
    import cv2

    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (80, 100), (0, 255, 0), -1)
    det = Detection(xyxy=(20.0, 20.0, 80.0, 100.0), conf=0.88, cls_id=15, track_id=7)
    dist = DistanceResult(meters=1.2, lo=1.0, hi=1.4, method="geometry", components={})
    obs = CatObservation(detection=det, distance=dist, bearing_deg=5.0, speed_mps=None)
    result = FrameResult(
        frame_index=0,
        observations=[obs],
        width=160,
        height=120,
        target_observation=obs,
        target_known_ids=[7],
    )
    cards = build_cat_catalog(frame, result, locked_id=7, preferred_id=7)
    assert len(cards) == 1
    assert cards[0]["id"] == 7
    assert cards[0]["thumb_jpeg_b64"] is not None


def test_build_cat_catalog_includes_coasted_target() -> None:
    """Followed target can be off-frame (coast) while still identified."""
    live = _det(1, 400)
    coast = _det(7, 900)
    dist = DistanceResult(meters=1.0, lo=0.9, hi=1.1, method="geometry", components={})
    live_obs = CatObservation(detection=live, distance=dist, bearing_deg=0.0, speed_mps=None)
    coast_obs = CatObservation(detection=coast, distance=dist, bearing_deg=2.0, speed_mps=None)
    result = FrameResult(
        frame_index=3,
        observations=[live_obs],
        target_observation=coast_obs,
        target_known_ids=[7, 1],
        width=640,
        height=480,
    )
    cards = build_cat_catalog(None, result, locked_id=7, preferred_id=7, encode_thumbs=False)
    ids = {c["id"] for c in cards}
    assert 7 in ids
    assert 1 in ids


def test_build_cat_catalog_synthesizes_known_id_without_previous() -> None:
    """First frame after lock: known id must appear even before a stored thumbnail."""
    dist = DistanceResult(meters=1.0, lo=0.9, hi=1.1, method="geometry", components={})
    obs = CatObservation(detection=_det(1, 400), distance=dist, bearing_deg=0.0, speed_mps=None)
    result = FrameResult(
        frame_index=2,
        observations=[obs],
        target_known_ids=[7],
        width=640,
        height=480,
    )
    cards = build_cat_catalog(None, result, locked_id=7, preferred_id=7, encode_thumbs=False)
    ids = {c["id"] for c in cards}
    assert 1 in ids
    assert 7 in ids


def test_build_cat_catalog_keeps_known_id_from_previous() -> None:
    """Brief dropout must not empty the picker while tracker still knows the id."""
    prev = [
        {
            "id": 7,
            "conf": 0.9,
            "dist_m": 1.2,
            "bearing_deg": 0.0,
            "is_locked": True,
            "is_preferred": True,
            "thumb_jpeg_b64": "abc",
            "area": 1000.0,
        }
    ]
    result = FrameResult(
        frame_index=4,
        observations=[],
        target_known_ids=[7],
        width=640,
        height=480,
    )
    cards = build_cat_catalog(
        None,
        result,
        locked_id=7,
        preferred_id=7,
        previous=prev,
        encode_thumbs=False,
    )
    assert len(cards) == 1
    assert cards[0]["id"] == 7
    assert cards[0]["thumb_jpeg_b64"] == "abc"
