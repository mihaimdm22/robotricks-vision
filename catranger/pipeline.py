"""End-to-end perception pipeline: frame -> undistort -> detect+track -> per-object
metric distance + bearing + speed -> inter-object distances -> FrameResult.

Heavy backends (Detector / DepthNet) are constructed lazily-by-import inside their
own modules; this file only wires them together. Importing catranger.pipeline stays
light until you instantiate CatRanger.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from catranger.config import AppConfig
from catranger.distance import DistanceEstimator
from catranger.intrinsics import CameraModel
from catranger.types import CatObservation, Detection, DistanceResult, FrameResult

# Go2 streams at ~15 FPS; used as the time base for speed when no clock is supplied.
_DEFAULT_FPS = 15.0
_HISTORY_LEN = 15


def _device_is_cuda(device: Optional[str]) -> bool:
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
        device: Optional[str] = None,
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

        # ---- depth net (optional) ----
        depth_cfg = app.get("depth", default={}) or {}
        self.depth_enabled = bool(use_depth and depth_cfg.get("enabled", False))
        self.depth_every_n = max(1, int(depth_cfg.get("every_n", 5)))
        self.depth = None
        if self.depth_enabled:
            from catranger.depth import DepthNet  # lazy: pulls transformers only here

            net = DepthNet(
                backend=depth_cfg.get(
                    "backend", "depth_anything_v2_metric_indoor"
                ),
                device=device,
            )
            if net.available():
                self.depth = net
            else:
                self.depth = None

        # ---- distance estimator ----
        conformal_q = app.get("uncertainty", "conformal_q", default=None)
        self.distance = DistanceEstimator(
            self.camera, app.size_priors, conformal_q=conformal_q
        )

        # ---- per-track history for speed: track_id -> deque[(frame_index, center, Z)] ----
        self._history: Dict[int, Deque[Tuple[int, Tuple[float, float], float]]] = {}
        self._last_depth: Optional[np.ndarray] = None
        self._last_depth_conf: Optional[np.ndarray] = None
        self._last_t = time.perf_counter()

    # ---- helpers ----
    def _speed(
        self, track_id: Optional[int], frame_index: int, center: Tuple[float, float], z: float
    ) -> Optional[float]:
        """Approach speed in m/s (positive = closing). Uses d(Z)/dt over the track
        history with a ~15 FPS assumption for the time base."""
        if track_id is None or not np.isfinite(z):
            return None
        hist = self._history.setdefault(track_id, deque(maxlen=_HISTORY_LEN))
        speed: Optional[float] = None
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

        dets: List[Detection] = self.detector.track(
            frame, tracker=self.tracker_name, persist=True
        )

        # depth: run every Nth frame, cache otherwise
        depth_map = self._last_depth
        depth_conf = self._last_depth_conf
        if self.depth is not None and (frame_index % self.depth_every_n == 0):
            try:
                depth_map, depth_conf = self.depth.infer(frame, K=self.camera.K)
            except Exception:
                depth_map, depth_conf = self._last_depth, self._last_depth_conf
            self._last_depth, self._last_depth_conf = depth_map, depth_conf

        observations: List[CatObservation] = []
        for det in dets:
            dist: DistanceResult = self.distance.estimate(
                det, depth_map=depth_map, depth_conf=depth_conf
            )
            cx, _cy = det.center
            bearing = self.camera.bearing_deg(cx)
            z = dist.meters if (dist and np.isfinite(dist.meters)) else float("nan")
            speed = self._speed(det.track_id, frame_index, det.center, z)
            observations.append(
                CatObservation(
                    detection=det,
                    distance=dist,
                    bearing_deg=bearing,
                    speed_mps=speed,
                )
            )

        # prune history of tracks no longer present
        live_ids = {o.track_id for o in observations if o.track_id is not None}
        for tid in list(self._history.keys()):
            if tid not in live_ids:
                del self._history[tid]

        # pairwise inter-object metric distances
        inter_object: List[Tuple[int, int, float]] = []
        usable = [
            o
            for o in observations
            if o.track_id is not None
            and o.distance is not None
            and np.isfinite(o.distance.meters)
        ]
        for i in range(len(usable)):
            for j in range(i + 1, len(usable)):
                a, b = usable[i], usable[j]
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
        )

    def reset(self) -> None:
        self._history.clear()
        self._last_depth = None
        self._last_depth_conf = None
        self._last_t = time.perf_counter()
