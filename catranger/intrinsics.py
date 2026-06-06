"""Camera geometry: intrinsics, FOV-model undistortion, back-projection, bearing.

The Go2 lens is 120 deg with NO distortion coefficients provided. We rectify with a
one-parameter FOV (division) model derived from the known field of view, then do
pinhole math on the rectified image. See docs/research/how-far.md sec 0.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

try:  # cv2 is in core deps but guard so import errors are obvious
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from catranger.config import CameraConfig


class CameraModel:
    """Wraps a CameraConfig with the geometry operations the pipeline needs."""

    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.fx, self.fy, self.cx, self.cy = cfg.fx, cfg.fy, cfg.cx, cfg.cy
        self.width, self.height = cfg.width, cfg.height
        self.K = np.array(
            [[self.fx, 0, self.cx], [0, self.fy, self.cy], [0, 0, 1.0]], dtype=np.float64
        )
        self._map_x: Optional[np.ndarray] = None
        self._map_y: Optional[np.ndarray] = None

    # ---- undistortion (FOV / division model from known FOV) ----
    def _build_maps(self, w: int, h: int) -> None:
        if cv2 is None:
            raise RuntimeError("opencv-python is required for undistortion")
        omega = np.deg2rad(self.cfg.fov_deg)
        xs, ys = np.meshgrid(np.arange(w), np.arange(h))
        x = (xs - self.cx) / self.fx
        y = (ys - self.cy) / self.fy
        ru = np.sqrt(x * x + y * y) + 1e-9
        # FOV model forward: distorted radius for a given undistorted radius
        rd = np.arctan(2 * ru * np.tan(omega / 2)) / omega
        scale = rd / ru
        self._map_x = (x * scale * self.fx + self.cx).astype(np.float32)
        self._map_y = (y * scale * self.fy + self.cy).astype(np.float32)

    def undistort(self, img_bgr: np.ndarray) -> np.ndarray:
        """Rectify a frame. No-op if dist_model == 'none'."""
        if self.cfg.dist_model == "none":
            return img_bgr
        if cv2 is None:
            return img_bgr
        h, w = img_bgr.shape[:2]
        if self._map_x is None or self._map_x.shape[:2] != (h, w):
            self._build_maps(w, h)
        return cv2.remap(img_bgr, self._map_x, self._map_y, cv2.INTER_LINEAR)

    # ---- pinhole geometry ----
    def distance_from_height(self, h_pixels: float, real_height_m: float) -> float:
        """Z = fy * H_real / h_pixels  (object vertical extent)."""
        if h_pixels <= 0:
            return float("nan")
        return float(self.fy * real_height_m / h_pixels)

    def distance_from_width(self, w_pixels: float, real_width_m: float) -> float:
        """Z = fx * W_real / w_pixels  (use for balls / clipped-top objects)."""
        if w_pixels <= 0:
            return float("nan")
        return float(self.fx * real_width_m / w_pixels)

    def backproject(self, u: float, v: float, Z: float) -> np.ndarray:
        """Pixel (u,v) + metric depth Z -> 3D point in camera frame (meters)."""
        X = (u - self.cx) * Z / self.fx
        Y = (v - self.cy) * Z / self.fy
        return np.array([X, Y, Z], dtype=np.float64)

    def bearing_rad(self, u: float) -> float:
        """Horizontal angle of a pixel column from the optical axis (+ = right)."""
        return float(np.arctan2(u - self.cx, self.fx))

    def bearing_deg(self, u: float) -> float:
        return float(np.degrees(self.bearing_rad(u)))

    def centering_weight(self, u: float, v: float) -> float:
        """1.0 at the optical center, decaying with radius^2. Trust centered boxes
        more because barrel distortion grows toward the edges."""
        rx = (u - self.cx) / (self.width / 2.0)
        ry = (v - self.cy) / (self.height / 2.0)
        r2 = rx * rx + ry * ry
        return float(1.0 / (1.0 + r2))

    def inter_object_distance(
        self, c1: Tuple[float, float], z1: float, c2: Tuple[float, float], z2: float
    ) -> float:
        """Euclidean metric distance between two objects given their pixel centers
        and metric depths."""
        p1 = self.backproject(c1[0], c1[1], z1)
        p2 = self.backproject(c2[0], c2[1], z2)
        return float(np.linalg.norm(p1 - p2))
