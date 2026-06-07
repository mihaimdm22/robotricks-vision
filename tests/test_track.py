"""Tests for CatTracker target lock + known id aliasing."""

from __future__ import annotations

from catranger.detect import Detection
from catranger.track import CatTracker


class _FakeDetector:
    def track(self, frame_bgr, tracker="botsort.yaml", persist=True):
        return list(self._dets)

    def __init__(self, dets: list[Detection]):
        self._dets = dets


def _det(tid: int, area: int) -> Detection:
    side = int(area**0.5)
    return Detection(xyxy=(0.0, 0.0, float(side), float(side)), conf=0.9, cls_id=15, track_id=tid)


def test_known_ids_accumulate_on_id_switch_after_hysteresis():
    det = _FakeDetector([_det(1, 100)])
    trk = CatTracker(det, lock_hysteresis=2)
    trk.select_target(det._dets)
    assert trk.known_ids == {1}

    # locked id missing; challenger id=2 wins after hysteresis
    det._dets = [_det(2, 120)]
    trk.select_target(det._dets)
    trk.select_target(det._dets)
    assert trk.locked_id == 2
    assert trk.known_ids == {1, 2}


def test_known_ids_clear_after_full_loss():
    det = _FakeDetector([_det(5, 100)])
    trk = CatTracker(det, lock_hysteresis=1)
    trk.select_target(det._dets)
    assert trk.known_ids == {5}
    trk.select_target([])
    trk.select_target([])  # coast then give up
    assert trk.locked_id is None
    assert trk.known_ids == set()
