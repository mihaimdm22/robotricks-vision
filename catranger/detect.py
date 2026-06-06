"""Object detection + tracking via Ultralytics (YOLO11 / RT-DETR).

`cat` is COCO class 15 → no training needed for the default path; both approaches in
the deck (CNN YOLO, transformer RT-DETR) run through the identical `.detect` / `.track`
surface so the rest of the pipeline never branches on backend.

Ultralytics is imported lazily inside `_load` so `import catranger` stays light and only
errors (with an install hint) when a detector is actually used.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from catranger.types import Detection

# COCO class id for "cat" (80-class COCO order). Pretrained YOLO/RT-DETR use this.
COCO_CAT_ID = 15

_INSTALL_HINT = (
    "ultralytics is required for detection (pip install ultralytics). "
    "Original import error: {err}"
)


class Detector:
    """Thin wrapper over an Ultralytics model exposing detect() and track().

    Parameters
    ----------
    backend : {"yolo", "rtdetr"}
        "yolo" -> ultralytics.YOLO (CNN, supports yolo11/yolo26/yolov8 weights and
        finetuned best.pt). "rtdetr" -> ultralytics.RTDETR (transformer, NMS-free).
    weights : str
        Model weights/handle. Can be a bare handle ("yolo11s.pt", "rtdetr-l.pt") that
        Ultralytics auto-downloads, or a path to a finetuned checkpoint ("runs/.../best.pt").
    conf, imgsz, half :
        Passed straight through to predict()/track().
    classes : Sequence[int] | None
        COCO class ids to keep (e.g. [15] for cat). None = keep all.
    """

    def __init__(
        self,
        backend: str = "yolo",
        weights: str = "yolo11s.pt",
        conf: float = 0.35,
        imgsz: int = 640,
        half: bool = True,
        classes: Optional[Sequence[int]] = None,
    ) -> None:
        self.backend = str(backend).lower()
        self.weights = weights
        self.conf = float(conf)
        self.imgsz = int(imgsz)
        self.half = bool(half)
        self.classes = list(classes) if classes is not None else None
        self._model = None  # lazy

    # ---- model loading (lazy / heavy import inside) ----
    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from ultralytics import YOLO, RTDETR  # heavy import, kept local
        except Exception as err:  # pragma: no cover - exercised only without the dep
            raise ImportError(_INSTALL_HINT.format(err=err)) from err

        if self.backend == "rtdetr":
            self._model = RTDETR(self.weights)
        elif self.backend == "yolo":
            self._model = YOLO(self.weights)
        else:
            raise ValueError(
                f"unknown detector backend {self.backend!r} (expected 'yolo' or 'rtdetr')"
            )
        return self._model

    @property
    def model(self):
        """The underlying Ultralytics model (loads it on first access)."""
        return self._load()

    @property
    def names(self) -> dict:
        """Class id -> name mapping from the loaded model."""
        m = self._load()
        return dict(getattr(m, "names", {}) or {})

    # ---- inference ----
    def detect(self, frame_bgr: np.ndarray) -> List[Detection]:
        """Run stateless detection on a single BGR frame -> list[Detection]."""
        model = self._load()
        results = model.predict(
            frame_bgr,
            conf=self.conf,
            imgsz=self.imgsz,
            half=self.half,
            classes=self.classes,
            verbose=False,
        )
        return self._to_detections(results)

    def track(
        self,
        frame_bgr: np.ndarray,
        tracker: str = "botsort.yaml",
        persist: bool = True,
    ) -> List[Detection]:
        """Run detection + multi-object tracking on a single BGR frame.

        `persist=True` keeps the Kalman state + ID counters alive across calls so track
        ids survive (partial) occlusion — call this once per frame in order.
        """
        model = self._load()
        results = model.track(
            frame_bgr,
            tracker=tracker,
            persist=persist,
            conf=self.conf,
            imgsz=self.imgsz,
            half=self.half,
            classes=self.classes,
            verbose=False,
        )
        return self._to_detections(results)

    # ---- result -> Detection conversion ----
    def _to_detections(self, results) -> List[Detection]:
        dets: List[Detection] = []
        if not results:
            return dets
        res = results[0]  # single-image inference -> one Results object
        boxes = getattr(res, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return dets

        names = dict(getattr(res, "names", {}) or self.names)

        xyxy = self._np(boxes.xyxy)
        confs = self._np(getattr(boxes, "conf", None))
        cls_ids = self._np(getattr(boxes, "cls", None))
        track_ids = self._np(getattr(boxes, "id", None))  # None when not tracking

        n = len(xyxy)
        for i in range(n):
            x1, y1, x2, y2 = (float(v) for v in xyxy[i][:4])
            cls_id = int(cls_ids[i]) if cls_ids is not None else -1
            conf = float(confs[i]) if confs is not None else 0.0
            cls_name = str(names.get(cls_id, str(cls_id)))
            tid = int(track_ids[i]) if track_ids is not None else None

            # Belt-and-suspenders class filter (Ultralytics already filters via classes=,
            # but a finetuned single-class model may not honor COCO ids).
            if self.classes is not None and cls_id not in self.classes:
                continue

            dets.append(
                Detection(
                    xyxy=(x1, y1, x2, y2),
                    conf=conf,
                    cls_id=cls_id,
                    cls_name=cls_name,
                    track_id=tid,
                )
            )
        return dets

    @staticmethod
    def _np(t):
        """Move a torch tensor / array-like to a numpy array; pass through None."""
        if t is None:
            return None
        if isinstance(t, np.ndarray):
            return t
        # torch.Tensor and Ultralytics wrappers expose .cpu().numpy()
        try:
            return t.cpu().numpy()
        except Exception:
            return np.asarray(t)
