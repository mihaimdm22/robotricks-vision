"""End-to-end perception pipeline: frame -> undistort -> detect+track -> per-object
metric distance + bearing + speed -> inter-object distances -> FrameResult.

Heavy backends (Detector / DepthNet) are constructed lazily-by-import inside their
own modules; this file only wires them together. Importing catranger.pipeline stays
light until you instantiate CatRanger.
"""

from __future__ import annotations

import time
from collections import deque

import numpy as np

from catranger.config import AppConfig
from catranger.distance import DistanceEstimator
from catranger.intrinsics import CameraModel
from catranger.types import CatObservation, Detection, DistanceResult, FrameResult

# Go2 streams at ~15 FPS; used as the time base for speed when no clock is supplied.
_DEFAULT_FPS = 15.0
_HISTORY_LEN = 15


def _device_is_cuda(device: str | None) -> bool:
    """True only when inference runs on a CUDA GPU (where FP16/half is safe).

    FP16 is CUDA-only: passing half=True on CPU/MPS gives no speedup and crashes
    the Ultralytics RT-DETR path with a native SIGSEGV. We use this to force half
    off everywhere except CUDA. `device` may be None (auto), "cpu", "mps",
    "cuda"/"cuda:0", or a bare GPU index like "0".
    """
    if device is None:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False
    d = str(device).lower()
    return d.startswith("cuda") or d.isdigit()


class CatRanger:
    """Build detector + (optional) depth net + distance estimator, then process frames."""

    def __init__(
        self,
        app: AppConfig,
        approach: str = "approach_a",
        use_depth: bool = True,
        device: str | None = None,
    ):
        self.app = app
        self.approach = approach
        self.device = device

        self.camera = CameraModel(app.camera)

        # ---- detector config resolution ----
        det_cfg = app.get("detector", default={}) or {}
        approach_cfg = det_cfg.get(approach, {}) or {}
        finetuned = det_cfg.get("finetuned_weights")
        weights = finetuned or approach_cfg.get("weights", "yolo11s.pt")
        backend = approach_cfg.get("backend", "yolo")
        conf = float(det_cfg.get("conf", 0.35))
        imgsz = int(det_cfg.get("imgsz", 640))
        half = bool(det_cfg.get("half", True))
        # FP16 is CUDA-only: on CPU/MPS it never helps and segfaults the RT-DETR
        # path. Force it off unless we're actually on a CUDA device.
        if half and not _device_is_cuda(device):
            half = False

        from catranger.detect import Detector  # lazy: pulls ultralytics only here

        self.detector = Detector(
            backend=backend,
            weights=weights,
            conf=conf,
            imgsz=imgsz,
            half=half,
            classes=app.classes,
        )

        # ---- tracker name ----
        self.tracker_name = app.get("tracker", "name", default="botsort.yaml")
        lock_hysteresis = int(app.get("tracker", "lock_hysteresis", default=5) or 5)

        from catranger.track import CatTracker  # lazy: uses Detector

        self.tracker = CatTracker(
            self.detector,
            tracker_name=self.tracker_name,
            lock_hysteresis=lock_hysteresis,
        )

        # ---- depth net (optional) ----
        depth_cfg = app.get("depth", default={}) or {}
        self.depth_enabled = bool(use_depth and depth_cfg.get("enabled", False))
        self.depth_every_n = max(1, int(depth_cfg.get("every_n", 5)))
        self.depth = None
        if self.depth_enabled:
            from catranger.depth import DepthNet  # lazy: pulls transformers only here

            net = DepthNet(
                backend=depth_cfg.get("backend", "depth_anything_v2_metric_indoor"),
                device=device,
            )
            if net.available():
                self.depth = net
            else:
                self.depth = None

        # ---- distance estimator ----
        conformal_q = app.get("uncertainty", "conformal_q", default=None)
        box_erosion = float(app.get("depth", "box_erosion", default=0.0) or 0.0)
        self.distance = DistanceEstimator(
            self.camera, app.size_priors, conformal_q=conformal_q, box_erosion=box_erosion
        )

        # ---- per-track history for speed: track_id -> deque[(frame_index, center, Z)] ----
        self._history: dict[int, deque[tuple[int, tuple[float, float], float]]] = {}
        self._last_depth: np.ndarray | None = None
        self._last_depth_conf: np.ndarray | None = None
        self._last_t = time.perf_counter()

    # ---- helpers ----
    def _speed(
        self,
        track_id: int | None,
        known_ids: list[int],
        frame_index: int,
        center: tuple[float, float],
        z: float,
    ) -> float | None:
        """Approach speed in m/s (positive = closing). Uses d(Z)/dt over the track
        history with a ~15 FPS assumption for the time base. Falls back across alias
        ids when BoT-SORT reassigns the same cat."""
        if track_id is None or not np.isfinite(z):
            return None
        lookup_ids = [track_id] + [i for i in known_ids if i != track_id]
        hist: deque[tuple[int, tuple[float, float], float]] | None = None
        for tid in lookup_ids:
            candidate = self._history.get(tid)
            if candidate:
                hist = candidate
                break
        if hist is None:
            hist = self._history.setdefault(track_id, deque(maxlen=_HISTORY_LEN))
        speed: float | None = None
        if hist:
            f0, _c0, z0 = hist[0]
            df = frame_index - f0
            if df > 0 and np.isfinite(z0):
                dt = df / _DEFAULT_FPS
                if dt > 0:
                    # approach speed = -dZ/dt (Z shrinking -> cat approaching -> positive)
                    speed = float(-(z - z0) / dt)
        hist.append((frame_index, center, float(z)))
        return speed

    # ---- main entry ----
    def process(self, frame_bgr: np.ndarray, frame_index: int = 0) -> FrameResult:
        t0 = time.perf_counter()

        frame = self.camera.undistort(frame_bgr)
        # expose for overlay: detections are in undistorted-frame coords, so the
        # demo/notebook draw on this frame, not the raw input.
        self.last_undistorted = frame
        h, w = frame.shape[:2]

        dets: list[Detection] = self.tracker.update(frame)
        target_det = self.tracker.select_target(dets)
        known_ids = sorted(self.tracker.known_ids)

        # depth: run every Nth frame, cache otherwise
        depth_map = self._last_depth
        depth_conf = self._last_depth_conf
        if self.depth is not None and (frame_index % self.depth_every_n == 0):
            try:
                depth_map, depth_conf = self.depth.infer(frame, K=self.camera.K)
            except Exception:
                depth_map, depth_conf = self._last_depth, self._last_depth_conf
            self._last_depth, self._last_depth_conf = depth_map, depth_conf

        observations: list[CatObservation] = []
        for det in dets:
            dist: DistanceResult = self.distance.estimate(
                det, depth_map=depth_map, depth_conf=depth_conf
            )
            cx, _cy = det.center
            bearing = self.camera.bearing_deg(cx)
            z = dist.meters if (dist and np.isfinite(dist.meters)) else float("nan")
            speed = self._speed(det.track_id, known_ids, frame_index, det.center, z)
            observations.append(
                CatObservation(
                    detection=det,
                    distance=dist,
                    bearing_deg=bearing,
                    speed_mps=speed,
                )
            )

        target_observation = self._resolve_target_observation(
            target_det, observations, depth_map, depth_conf, frame_index, known_ids
        )

        # prune history of tracks no longer present (keep aliases for the followed cat)
        live_ids = {o.track_id for o in observations if o.track_id is not None}
        alias_ids = set(known_ids)
        for tid in list(self._history.keys()):
            if tid not in live_ids and tid not in alias_ids:
                del self._history[tid]

        # pairwise inter-object metric distances
        inter_object: list[tuple[int, int, float]] = []
        usable = [
            o
            for o in observations
            if o.track_id is not None and o.distance is not None and np.isfinite(o.distance.meters)
        ]
        for i in range(len(usable)):
            for j in range(i + 1, len(usable)):
                a, b = usable[i], usable[j]
                # all four are guaranteed non-None by the `usable` filter above
                assert a.distance is not None and b.distance is not None
                assert a.track_id is not None and b.track_id is not None
                d = self.camera.inter_object_distance(
                    a.detection.center,
                    a.distance.meters,
                    b.detection.center,
                    b.distance.meters,
                )
                inter_object.append((int(a.track_id), int(b.track_id), float(d)))

        dt = max(1e-6, time.perf_counter() - t0)
        fps = float(1.0 / dt)
        self._last_t = time.perf_counter()

        return FrameResult(
            frame_index=frame_index,
            observations=observations,
            inter_object=inter_object,
            fps=fps,
            width=int(w),
            height=int(h),
            target_observation=target_observation,
            target_known_ids=known_ids,
        )

    def _resolve_target_observation(
        self,
        target_det: Detection | None,
        observations: list[CatObservation],
        depth_map: np.ndarray | None,
        depth_conf: np.ndarray | None,
        frame_index: int,
        known_ids: list[int],
    ) -> CatObservation | None:
        if target_det is None:
            return None
        for obs in observations:
            if obs.detection is target_det:
                return obs
        tid = target_det.track_id
        if tid is not None:
            for obs in observations:
                if obs.track_id == tid:
                    return obs
        # Coast frame: locked id vanished but tracker still returns the last box.
        dist = self.distance.estimate(target_det, depth_map=depth_map, depth_conf=depth_conf)
        cx, _cy = target_det.center
        bearing = self.camera.bearing_deg(cx)
        z = dist.meters if (dist and np.isfinite(dist.meters)) else float("nan")
        speed = self._speed(tid, known_ids, frame_index, target_det.center, z)
        return CatObservation(
            detection=target_det,
            distance=dist,
            bearing_deg=bearing,
            speed_mps=speed,
        )

    def reset(self) -> None:
        self.tracker.reset()
        self._history.clear()
        self._last_depth = None
        self._last_depth_conf = None
        self._last_t = time.perf_counter()

    def set_preferred_target(self, track_id: int | None) -> None:
        """Lock follow mode onto a specific tracker id (None = largest-box auto)."""
        self.tracker.set_preferred_id(track_id)
