"""Monocular metric depth.

Default backend = Depth Anything V2 (Metric, Indoor, Large) via 🤗 transformers:
`AutoImageProcessor` + `AutoModelForDepthEstimation`, model id
`depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf`. Output is metric depth in
meters (max_depth=20 indoor head), resized back to the input frame's HxW; no per-pixel
confidence is produced (returns None).

Alt backend = UniDepthV2 (`lpiccinelli/unidepth-v2-vitl14`): ingests our intrinsics K
to produce TRUE metric depth + a per-pixel confidence map. See docs/research/how-far.md
sec 2 for both call signatures.

All heavy deps (torch / transformers / unidepth) are imported lazily inside methods so
`import catranger` stays light and only errors — with an install hint — when depth runs.
"""

from __future__ import annotations

import numpy as np

# canonical HF / hub handles for the supported backends
_DAV2_METRIC_INDOOR_ID = "depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf"
_UNIDEPTH_V2_ID = "lpiccinelli/unidepth-v2-vitl14"

DepthOutput = tuple[np.ndarray, np.ndarray | None]


class DepthNet:
    """Metric monocular depth estimator.

    Parameters
    ----------
    backend : str
        "depth_anything_v2_metric_indoor" (default, transformers) or "unidepth_v2".
    device : str | None
        Torch device ("cuda" / "cpu"). None -> cuda if available else cpu (resolved lazily).
    """

    def __init__(
        self,
        backend: str = "depth_anything_v2_metric_indoor",
        device: str | None = None,
    ) -> None:
        self.backend = str(backend).lower()
        self._device = device  # resolved on first load
        self._model = None
        self._processor = None  # transformers image processor (DAv2 only)

    # ---- device / availability ----
    def _resolve_device(self) -> str:
        if self._device is not None:
            return self._device
        try:
            import torch

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            self._device = "cpu"
        return self._device

    def available(self) -> bool:
        """True if this backend's deps import (torch + the backend library)."""
        try:
            import torch  # noqa: F401

            if self.backend == "unidepth_v2":
                from unidepth.models import UniDepthV2  # noqa: F401
            else:
                from transformers import (  # noqa: F401
                    AutoImageProcessor,
                    AutoModelForDepthEstimation,
                )
            return True
        except Exception:
            return False

    # ---- model loading (lazy / heavy imports inside) ----
    def _load(self):
        if self._model is not None:
            return self._model
        if self.backend == "unidepth_v2":
            self._model = self._load_unidepth()
        elif self.backend in ("depth_anything_v2_metric_indoor", "depth_anything_v2"):
            self._model = self._load_dav2()
        else:
            raise ValueError(
                f"unknown depth backend {self.backend!r} "
                "(expected 'depth_anything_v2_metric_indoor' or 'unidepth_v2')"
            )
        return self._model

    def _load_dav2(self):
        try:
            import torch  # noqa: F401
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        except Exception as err:  # pragma: no cover
            raise ImportError(
                "transformers + torch are required for the Depth Anything V2 backend "
                "(pip install 'transformers>=4.45' torch). "
                f"Original import error: {err}"
            ) from err
        device = self._resolve_device()
        self._processor = AutoImageProcessor.from_pretrained(_DAV2_METRIC_INDOOR_ID)
        model = AutoModelForDepthEstimation.from_pretrained(_DAV2_METRIC_INDOOR_ID)
        model = model.to(device).eval()
        return model

    def _load_unidepth(self):
        try:
            import torch  # noqa: F401
            from unidepth.models import UniDepthV2
        except Exception as err:  # pragma: no cover
            raise ImportError(
                "UniDepth is required for the unidepth_v2 backend "
                "(pip install git+https://github.com/lpiccinelli-eth/UniDepth). "
                f"Original import error: {err}"
            ) from err
        device = self._resolve_device()
        model = UniDepthV2.from_pretrained(_UNIDEPTH_V2_ID)
        model = model.to(device).eval()
        return model

    # ---- inference ----
    def infer(self, frame_bgr: np.ndarray, K: np.ndarray | None = None) -> DepthOutput:
        """Estimate metric depth for a BGR frame.

        Returns (depth_HxW_float32_meters, confidence_or_None). `K` (3x3 intrinsics) is
        used only by the unidepth_v2 backend to produce true metric depth; it is ignored
        by Depth Anything V2 (whose scale is baked into the indoor head).
        """
        if self.backend == "unidepth_v2":
            return self._infer_unidepth(frame_bgr, K)
        return self._infer_dav2(frame_bgr)

    def _infer_dav2(self, frame_bgr: np.ndarray) -> DepthOutput:
        import torch

        model = self._load()
        # _load() -> _load_dav2() sets the processor for this backend
        assert self._processor is not None
        h, w = frame_bgr.shape[:2]
        # BGR -> RGB for the HF processor. ascontiguousarray() is required: a bare
        # [..., ::-1] view has a negative stride, which transformers>=5 rejects in
        # torch.from_numpy ("tensors with negative strides are not supported").
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        inputs = self._processor(images=rgb, return_tensors="pt")
        device = self._resolve_device()
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        # Prefer the processor's post-process (interpolates to size + strips padding).
        depth = None
        try:
            post = self._processor.post_process_depth_estimation(outputs, target_sizes=[(h, w)])
            depth = post[0]["predicted_depth"]
        except Exception:
            # Fallback for older transformers without post_process_depth_estimation.
            pred = outputs.predicted_depth  # (1, h', w')
            depth = torch.nn.functional.interpolate(
                pred.unsqueeze(1), size=(h, w), mode="bicubic", align_corners=False
            ).squeeze(1)[0]

        depth_np = depth.detach().cpu().numpy().astype(np.float32)
        if depth_np.shape[:2] != (h, w):  # belt-and-suspenders resize
            depth_np = _resize_depth(depth_np, w, h)
        return depth_np, None

    def _infer_unidepth(self, frame_bgr: np.ndarray, K: np.ndarray | None) -> DepthOutput:
        import torch

        model = self._load()
        h, w = frame_bgr.shape[:2]
        device = self._resolve_device()

        rgb = frame_bgr[:, :, ::-1].copy()  # HxWx3 uint8 RGB
        rgb_t = torch.from_numpy(rgb).permute(2, 0, 1).to(device)  # 3,H,W uint8

        K_t = None
        if K is not None:
            K_t = torch.as_tensor(np.asarray(K, dtype=np.float32)).to(device)

        with torch.no_grad():
            pred = model.infer(rgb_t, K_t) if K_t is not None else model.infer(rgb_t)

        depth_np = _to_hw_float32(pred["depth"], w, h)
        conf_np = None
        conf = pred.get("confidence") if isinstance(pred, dict) else None
        if conf is not None:
            conf_np = _to_hw_float32(conf, w, h)
        return depth_np, conf_np


# ---- numpy helpers ----
def _squeeze_to_hw(t) -> np.ndarray:
    """Torch/np tensor of shape (..., H, W) -> 2D float32 numpy (H, W)."""
    try:
        arr = t.detach().cpu().numpy()
    except Exception:
        arr = np.asarray(t)
    arr = np.asarray(arr, dtype=np.float32)
    while arr.ndim > 2:
        arr = arr[0]
    return arr


def _resize_depth(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    try:
        import cv2

        return cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    except Exception:
        # nearest-neighbour fallback without cv2
        ys = (np.linspace(0, arr.shape[0] - 1, h)).astype(np.int64)
        xs = (np.linspace(0, arr.shape[1] - 1, w)).astype(np.int64)
        return arr[ys][:, xs].astype(np.float32)


def _to_hw_float32(t, w: int, h: int) -> np.ndarray:
    arr = _squeeze_to_hw(t)
    if arr.shape[:2] != (h, w):
        arr = _resize_depth(arr, w, h)
    return arr
