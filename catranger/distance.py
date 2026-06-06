"""Metric distance per object: geometry-from-size + (optional) metric depth net,
fused into a single distance with an honest confidence interval.

See docs/research/how-far.md secs 1-5 for the math:
  - geometry:  Z_geo = fy * H_real / h_px   (height cue) or fx * W_real / w_px (width cue)
  - depth:     Z_depth = robust median of the metric depth map inside the box
  - fuse:      centering-weighted median of the available estimates
  - CI:        half-width = max(inter-estimator spread, geometry range spread,
                                conformal q * Z)
  - calibrate: per-class multiplicative scale alpha_c = median(gt / pred)

Pure numpy. No heavy deps.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from catranger.intrinsics import CameraModel
from catranger.types import Detection, DistanceResult


def _weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    """Weighted median of finite, positively-weighted samples. NaN-safe."""
    z = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    ok = np.isfinite(z) & np.isfinite(w) & (w > 0)
    z, w = z[ok], w[ok]
    if z.size == 0:
        return float("nan")
    if z.size == 1:
        return float(z[0])
    order = np.argsort(z)
    z, w = z[order], w[order]
    c = np.cumsum(w)
    idx = int(np.searchsorted(c, 0.5 * c[-1]))
    idx = min(idx, z.size - 1)
    return float(z[idx])


class DistanceEstimator:
    """Turn a Detection (+ optional depth map) into a metric DistanceResult."""

    def __init__(
        self,
        camera: CameraModel,
        size_priors: Dict[str, Dict],
        conformal_q: Optional[float] = None,
    ):
        self.camera = camera
        self.size_priors = size_priors or {}
        self.conformal_q = conformal_q
        # per-class multiplicative correction (filled by calibrate_scale)
        self.alpha: Dict[str, float] = {}

    # ---- geometry ----
    def _geometry(self, det: Detection) -> Tuple[float, Optional[Tuple[float, float]]]:
        """Return (Z_geo, range_m) using the per-class size prior. range_m is the
        prior's [lo, hi] real-size band used later for an uncertainty spread."""
        prior = self.size_priors.get(det.cls_name)
        if not prior:
            return float("nan"), None
        cue = str(prior.get("cue", "height")).lower()
        real_m = float(prior.get("real_m", 0.0))
        rng = prior.get("range_m")
        rng_t: Optional[Tuple[float, float]] = None
        if rng and len(rng) == 2:
            rng_t = (float(rng[0]), float(rng[1]))
        if real_m <= 0:
            return float("nan"), rng_t
        if cue == "width":
            z = self.camera.distance_from_width(det.width, real_m)
        else:
            z = self.camera.distance_from_height(det.height, real_m)
        alpha = float(self.alpha.get(det.cls_name, 1.0))
        if np.isfinite(z):
            z = alpha * z
        return float(z), rng_t

    def _geometry_spread(
        self, det: Detection, rng_t: Optional[Tuple[float, float]]
    ) -> float:
        """Distance spread implied by the prior's real-size range_m (the same pixel
        extent at the size-band edges gives a near/far distance bracket)."""
        prior = self.size_priors.get(det.cls_name)
        if not prior or not rng_t:
            return 0.0
        cue = str(prior.get("cue", "height")).lower()
        lo_m, hi_m = rng_t
        if cue == "width":
            z_lo = self.camera.distance_from_width(det.width, lo_m)
            z_hi = self.camera.distance_from_width(det.width, hi_m)
        else:
            z_lo = self.camera.distance_from_height(det.height, lo_m)
            z_hi = self.camera.distance_from_height(det.height, hi_m)
        if not (np.isfinite(z_lo) and np.isfinite(z_hi)):
            return 0.0
        alpha = float(self.alpha.get(det.cls_name, 1.0))
        return 0.5 * abs(alpha * z_hi - alpha * z_lo)

    # ---- depth ----
    def _depth(
        self,
        det: Detection,
        depth_map: Optional[np.ndarray],
        depth_conf: Optional[np.ndarray],
    ) -> Tuple[float, float]:
        """Robust median depth inside the box plus a confidence weight."""
        if depth_map is None:
            return float("nan"), 0.0
        dm = np.asarray(depth_map)
        h, w = dm.shape[:2]
        x1, y1, x2, y2 = det.xyxy
        # clip box to map bounds
        xi1 = int(max(0, min(w - 1, np.floor(min(x1, x2)))))
        yi1 = int(max(0, min(h - 1, np.floor(min(y1, y2)))))
        xi2 = int(max(0, min(w, np.ceil(max(x1, x2)))))
        yi2 = int(max(0, min(h, np.ceil(max(y1, y2)))))
        if xi2 <= xi1 or yi2 <= yi1:
            return float("nan"), 0.0
        patch = dm[yi1:yi2, xi1:xi2].astype(np.float64).ravel()
        valid = np.isfinite(patch) & (patch > 0)
        patch = patch[valid]
        if patch.size == 0:
            return float("nan"), 0.0
        z = float(np.median(patch))
        # confidence weight: median of conf inside the box, else 1.0
        w_conf = 1.0
        if depth_conf is not None:
            dc = np.asarray(depth_conf)
            if dc.shape[:2] == dm.shape[:2]:
                cpatch = dc[yi1:yi2, xi1:xi2].astype(np.float64).ravel()
                cpatch = cpatch[np.isfinite(cpatch)]
                if cpatch.size:
                    w_conf = float(max(0.0, np.median(cpatch)))
        return z, w_conf

    # ---- public API ----
    def estimate(
        self,
        det: Detection,
        depth_map: Optional[np.ndarray] = None,
        depth_conf: Optional[np.ndarray] = None,
    ) -> DistanceResult:
        cx, cy = det.center
        prior = self.size_priors.get(det.cls_name, {})
        geo_weight = float(prior.get("weight", 0.0)) if prior else 0.0

        z_geo, rng_t = self._geometry(det)
        z_depth, w_conf = self._depth(det, depth_map, depth_conf)

        have_geo = np.isfinite(z_geo) and z_geo > 0
        have_depth = np.isfinite(z_depth) and z_depth > 0

        values: List[float] = []
        weights: List[float] = []
        if have_geo:
            w_geo = max(0.0, geo_weight) * self.camera.centering_weight(cx, cy)
            # guard: if the prior weight is zero but geometry is all we have, give it a floor
            if w_geo <= 0:
                w_geo = self.camera.centering_weight(cx, cy)
            values.append(z_geo)
            weights.append(w_geo)
        if have_depth:
            w_d = w_conf if w_conf > 0 else 1.0
            values.append(z_depth)
            weights.append(w_d)

        if not values:
            return DistanceResult(
                meters=float("nan"),
                lo=float("nan"),
                hi=float("nan"),
                method="none",
                components={"geometry": float(z_geo), "depth": float(z_depth)},
            )

        z = _weighted_median(values, weights)
        if not np.isfinite(z):
            # fall back to a simple mean of what we have
            z = float(np.nanmean([v for v in values if np.isfinite(v)]))

        # method label
        if have_geo and have_depth:
            method = "fused"
        elif have_geo:
            method = "geometry"
        else:
            method = "depth"

        # ---- confidence interval half-width ----
        hw_candidates = [0.0]
        if have_geo and have_depth:
            hw_candidates.append(0.5 * abs(z_geo - z_depth))
        spread = self._geometry_spread(det, rng_t)
        if spread > 0:
            hw_candidates.append(spread)
        if self.conformal_q is not None and np.isfinite(z):
            hw_candidates.append(float(self.conformal_q) * abs(z))
        half_width = max(hw_candidates)

        lo = max(0.0, z - half_width)
        hi = max(lo, z + half_width)

        return DistanceResult(
            meters=float(z),
            lo=float(lo),
            hi=float(hi),
            method=method,
            components={
                "geometry": float(z_geo) if have_geo else float("nan"),
                "depth": float(z_depth) if have_depth else float("nan"),
            },
        )

    def calibrate_scale(
        self, samples: Sequence[Tuple[str, float, float]]
    ) -> Dict[str, float]:
        """Per-class multiplicative scale alpha_c = median(gt / pred).

        `samples` is a list of (cls_name, pred_meters, gt_meters). Returns the
        fitted alpha dict and also stores it on the estimator so subsequent
        estimate() calls apply the correction to the geometry term.
        """
        by_cls: Dict[str, List[float]] = {}
        for cls_name, pred, gt in samples:
            try:
                pred_f = float(pred)
                gt_f = float(gt)
            except (TypeError, ValueError):
                continue
            if not (np.isfinite(pred_f) and np.isfinite(gt_f)) or pred_f <= 0:
                continue
            by_cls.setdefault(str(cls_name), []).append(gt_f / pred_f)
        alpha: Dict[str, float] = {}
        for cls_name, ratios in by_cls.items():
            arr = np.asarray(ratios, dtype=np.float64)
            arr = arr[np.isfinite(arr) & (arr > 0)]
            if arr.size:
                alpha[cls_name] = float(np.median(arr))
        self.alpha.update(alpha)
        return alpha
