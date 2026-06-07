"""Target selection across frames — a thin layer over `Detector`.

The detector/tracker gives stable track ids per frame; this picks WHICH tracked cat we
actually follow and keeps that choice stable. Default policy: follow the largest box,
but require `lock_hysteresis` consecutive frames preferring a different id before we
switch the lock (prevents flip-flop between two cats), and COAST on a frame where the
locked id momentarily disappears (prevents the lost-frame twitch). See
docs/research/cat-tracker.md sec 4.4 (5) hysteresis and (6) coasting.
"""

from __future__ import annotations

import numpy as np

from catranger.detect import Detector
from catranger.types import Detection


class CatTracker:
    """Stateful target picker on top of a `Detector`.

    Parameters
    ----------
    detector : Detector
        Already-configured detector (backend / weights / classes).
    tracker_name : str
        Ultralytics tracker yaml passed to `detector.track` (botsort.yaml | bytetrack.yaml).
    lock_hysteresis : int
        Consecutive frames a challenger id must remain the best candidate before we
        switch the lock to it. 1 = switch immediately (no hysteresis).
    """

    def __init__(
        self,
        detector: Detector,
        tracker_name: str = "botsort.yaml",
        lock_hysteresis: int = 5,
    ) -> None:
        self.detector = detector
        self.tracker_name = tracker_name
        self.lock_hysteresis = max(1, int(lock_hysteresis))
        self.reset()

    def reset(self) -> None:
        """Clear all lock/coast state (call between independent clips)."""
        self.locked_id: int | None = None
        self.known_ids: set[int] = set()
        self._challenger_id: int | None = None
        self._challenger_count: int = 0
        # last Detection we returned as the target, for coasting across a missed frame
        self._last_target: Detection | None = None
        self._coast_frames: int = 0

    def _note_id(self, track_id: int | None) -> None:
        if track_id is not None:
            self.known_ids.add(int(track_id))

    def _clear_identity(self) -> None:
        """Drop accumulated tracker ids when the target is fully lost."""
        self.known_ids.clear()

    # ---- per-frame ----
    def update(self, frame_bgr: np.ndarray) -> list[Detection]:
        """Detect + track on this frame -> all current detections (track ids set)."""
        return self.detector.track(frame_bgr, tracker=self.tracker_name, persist=True)

    def select_target(self, dets: list[Detection]) -> Detection | None:
        """Pick the followed cat from this frame's detections with hysteresis + coast.

        Returns the locked Detection for this frame, the coasted last detection if the
        locked id briefly vanished, or None once there is nothing to follow.
        """
        if not dets:
            # nothing visible: coast on the last target for one frame, then give up.
            if self._last_target is not None and self._coast_frames == 0:
                self._coast_frames = 1
                return self._last_target
            self._coast_frames = 0
            self._last_target = None
            self.locked_id = None
            self._challenger_id = None
            self._challenger_count = 0
            self._clear_identity()
            return None

        # largest box = the natural target candidate this frame
        best = max(dets, key=lambda d: d.area)
        by_id = {d.track_id: d for d in dets if d.track_id is not None}

        # no usable ids (detection-only / tracker warmup): just follow the largest box.
        if best.track_id is None:
            self.locked_id = None
            self._challenger_id = None
            self._challenger_count = 0
            self._coast_frames = 0
            self._last_target = best
            return best

        # is the currently locked id still present?
        locked_det = by_id.get(self.locked_id) if self.locked_id is not None else None

        if self.locked_id is None:
            # acquire: lock immediately onto the best box's id.
            self._clear_identity()
            self.locked_id = best.track_id
            self._note_id(best.track_id)
            self._challenger_id = None
            self._challenger_count = 0
            self._coast_frames = 0
            self._last_target = best
            return best

        if locked_det is None:
            # locked id missing this frame -> COAST on the last known detection for up
            # to one frame, while letting a challenger build up hysteresis to take over.
            self._accumulate_challenger(best.track_id)
            if self._challenger_count >= self.lock_hysteresis:
                self._commit_challenger(best)
                return best
            if self._last_target is not None and self._coast_frames == 0:
                self._coast_frames = 1
                return self._last_target
            # coast budget spent: hand the lock to whatever is best now.
            self._note_id(self.locked_id)
            self.locked_id = best.track_id
            self._note_id(best.track_id)
            self._challenger_id = None
            self._challenger_count = 0
            self._coast_frames = 0
            self._last_target = best
            return best

        # locked id is visible.
        self._coast_frames = 0
        if best.track_id == self.locked_id:
            # the best box is already our target -> stay, decay any challenger.
            self._challenger_id = None
            self._challenger_count = 0
            self._last_target = locked_det
            return locked_det

        # a different id is bigger: build hysteresis before switching.
        self._accumulate_challenger(best.track_id)
        if self._challenger_count >= self.lock_hysteresis:
            self._commit_challenger(best)
            return best

        # challenger not yet trusted: keep following the locked cat.
        self._last_target = locked_det
        return locked_det

    # ---- hysteresis bookkeeping ----
    def _accumulate_challenger(self, candidate_id: int | None) -> None:
        if candidate_id is None:
            self._challenger_id = None
            self._challenger_count = 0
            return
        if candidate_id == self._challenger_id:
            self._challenger_count += 1
        else:
            self._challenger_id = candidate_id
            self._challenger_count = 1

    def _commit_challenger(self, det: Detection) -> None:
        self._note_id(self.locked_id)
        self.locked_id = det.track_id
        self._note_id(det.track_id)
        self._challenger_id = None
        self._challenger_count = 0
        self._coast_frames = 0
        self._last_target = det
