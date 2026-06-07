"""The overlay-JSON contract (WS-B0): the per-detection payload the console draws on a
canvas over the MJPEG frame.

Today's telemetry (``web/controller.py``) carries only single-target scalars; crisp
client-side overlays and failure badges (WS-B1/B2) need per-box geometry + flags. This
module is the single source of truth for that payload. Coordinates are NORMALIZED to
[0,1] so the client maps them onto the letterboxed video rect independent of the encoder
resolution.

Pure (``catranger.types`` only) so it is unit-tested without torch/cv2. The runtime
builds one of these per processed frame and ships it on the existing telemetry WS.
"""

from __future__ import annotations

import math

from catranger.types import FrameResult

# Per-detection flag thresholds. Display heuristics only (NOT scored core), so it is
# fine for the runtime to override these from configs/web.yaml `overlay:`.
_DEFAULT_LOW_CONF = 0.40  # detection conf below this -> "low_conf"
_DEFAULT_WIDE_CI_FRAC = 0.30  # CI half-width > frac*meters -> "wide_ci"
_DEFAULT_DISAGREE_FRAC = 0.30  # |geom-depth|/max > frac -> "depth_geom_disagree"


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _norm_xyxy(xyxy: tuple[float, float, float, float], w: int, h: int) -> list[float]:
    """Pixel xyxy -> normalized [0,1] xyxy, clamped to the frame."""
    x1, y1, x2, y2 = xyxy
    fw = float(w) if w else 1.0
    fh = float(h) if h else 1.0
    return [_clamp01(x1 / fw), _clamp01(y1 / fh), _clamp01(x2 / fw), _clamp01(y2 / fh)]


def build_overlay(
    result: FrameResult | None,
    frame_id: int,
    *,
    low_conf: float | None = None,
    wide_ci_frac: float | None = None,
    disagree_frac: float | None = None,
) -> dict:
    """Build the normalized overlay payload for one frame.

    Schema::

        {frame_id, frame_w, frame_h,
         dets: [{track_id, cls, xyxy_norm:[x1,y1,x2,y2], conf, dist_m, dist_lo,
                 dist_hi, bearing_deg, is_target, flags:[...]}],
         global_flags: [...]}

    Returns a well-formed empty payload for a None/empty result (passthrough frames).
    """
    lc = _DEFAULT_LOW_CONF if low_conf is None else float(low_conf)
    wcf = _DEFAULT_WIDE_CI_FRAC if wide_ci_frac is None else float(wide_ci_frac)
    df = _DEFAULT_DISAGREE_FRAC if disagree_frac is None else float(disagree_frac)

    if result is None:
        return {
            "frame_id": int(frame_id),
            "frame_w": 0,
            "frame_h": 0,
            "dets": [],
            "global_flags": ["no_frame"],
        }

    w, h = int(result.width), int(result.height)
    target = result.target
    dets: list[dict] = []
    for obs in result.observations:
        det = obs.detection
        dist = obs.distance
        flags: list[str] = []
        meters = lo = hi = None
        if dist is not None and math.isfinite(dist.meters):
            meters = round(float(dist.meters), 3)
            lo = round(float(dist.lo), 3)
            hi = round(float(dist.hi), 3)
            if meters > 0 and dist.half_width > wcf * meters:
                flags.append("wide_ci")
            g = dist.components.get("geometry", float("nan"))
            d = dist.components.get("depth", float("nan"))
            if math.isfinite(g) and math.isfinite(d):
                denom = max(abs(g), abs(d), 1e-6)
                if abs(g - d) / denom > df:
                    flags.append("depth_geom_disagree")
        else:
            flags.append("no_distance")
        if float(det.conf) < lc:
            flags.append("low_conf")
        dets.append(
            {
                "track_id": det.track_id,
                "cls": det.cls_name,
                "xyxy_norm": _norm_xyxy(det.xyxy, w, h),
                "conf": round(float(det.conf), 3),
                "dist_m": meters,
                "dist_lo": lo,
                "dist_hi": hi,
                "bearing_deg": round(float(obs.bearing_deg), 1),
                "is_target": bool(target is not None and obs is target),
                "flags": flags,
            }
        )

    global_flags: list[str] = [] if dets else ["no_detections"]
    return {
        "frame_id": int(frame_id),
        "frame_w": w,
        "frame_h": h,
        "dets": dets,
        "global_flags": global_flags,
    }
