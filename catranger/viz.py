"""Overlay drawing: annotate a frame with detections, distances, bearings, the control
vector arrow, and the controller state + FPS. Pure cv2/numpy. Returns a copy.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from catranger.types import Command, FrameResult

_GREEN = (0, 255, 0)
_YELLOW = (0, 255, 255)
_WHITE = (255, 255, 255)
_RED = (0, 0, 255)
_CYAN = (255, 255, 0)
_FONT = 0 if cv2 is None else cv2.FONT_HERSHEY_SIMPLEX


def _put(img, text, org, color, scale=0.6, thick=2):
    """Text with a dark outline so it reads on any background."""
    cv2.putText(img, text, org, _FONT, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, org, _FONT, scale, color, thick, cv2.LINE_AA)


def draw(
    frame_bgr: np.ndarray,
    result: FrameResult,
    command: Optional[Command] = None,
) -> np.ndarray:
    """Return an annotated copy of `frame_bgr`."""
    if frame_bgr is None:
        return frame_bgr
    img = frame_bgr.copy()
    if cv2 is None:
        return img

    h, w = img.shape[:2]
    target = result.target if result is not None else None
    target_id = target.track_id if target is not None else None

    for obs in (result.observations if result is not None else []):
        det = obs.detection
        x1, y1, x2, y2 = (int(round(v)) for v in det.xyxy)
        is_target = (
            target is not None
            and det.track_id is not None
            and det.track_id == target_id
        ) or (target is not None and obs is target)
        color = _GREEN if is_target else _YELLOW
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2 if is_target else 1)

        # label: id + distance +/- CI
        tid = det.track_id if det.track_id is not None else -1
        parts = [f"id={tid}"]
        if obs.distance is not None and math.isfinite(obs.distance.meters):
            parts.append(f"{obs.distance.meters:.2f}m")
            hw = obs.distance.half_width
            if math.isfinite(hw) and hw > 0:
                parts.append(f"+/-{hw:.2f}")
        label = " ".join(parts)
        ty = y1 - 8 if y1 - 8 > 12 else y1 + 18
        _put(img, label, (x1, ty), color, scale=0.55, thick=2)

        # bearing + speed under the box
        sub = f"{obs.bearing_deg:+.1f}deg"
        if obs.speed_mps is not None and math.isfinite(obs.speed_mps):
            sub += f" {obs.speed_mps:+.2f}m/s"
        _put(img, sub, (x1, min(h - 6, y2 + 18)), color, scale=0.5, thick=1)

    # inter-object distances (top-left list)
    if result is not None and result.inter_object:
        oy = 90
        for (ia, ib, d) in result.inter_object[:5]:
            _put(img, f"{ia}<->{ib}: {d:.2f}m", (12, oy), _CYAN, scale=0.5, thick=1)
            oy += 20

    # control arrow from frame center
    if command is not None:
        cx, cy = w // 2, h // 2
        # rotation -> horizontal component (+ right), v_fwd -> vertical (+ up = forward)
        scale = min(w, h) * 0.25
        ex = int(cx + command.rotation * scale)
        ey = int(cy - command.v_fwd * scale)
        cv2.circle(img, (cx, cy), 4, _WHITE, -1)
        acolor = _RED if command.state == "SAFE" else _GREEN
        cv2.arrowedLine(img, (cx, cy), (ex, ey), acolor, 3, tipLength=0.25)

    # HUD: state + fps + command summary
    state = command.state if command is not None else (
        "TRACK" if target is not None else "SEARCH"
    )
    fps = result.fps if result is not None else 0.0
    _put(img, f"{state}  {fps:4.1f} FPS", (12, 28), _WHITE, scale=0.7, thick=2)
    if command is not None:
        cmd_txt = f"rot={command.rotation:+.2f} v={command.v_fwd:+.2f}"
        if command.target_id is not None:
            cmd_txt += f" id={command.target_id}"
        _put(img, cmd_txt, (12, 56), _WHITE, scale=0.6, thick=2)

    return img
