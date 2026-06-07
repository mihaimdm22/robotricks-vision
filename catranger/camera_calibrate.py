"""Shared helpers for re-anchoring camera intrinsics (fx/fy) on disk."""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
CAMERA_DIR = _REPO / "configs" / "camera"

_FX = re.compile(r"^(\s*fx:\s*)[-\d.]+.*$", re.MULTILINE)
_FY = re.compile(r"^(\s*fy:\s*)[-\d.]+.*$", re.MULTILINE)
_NEEDS = re.compile(r"^(\s*needs_calibration:\s*)\w+.*$", re.MULTILINE)


def camera_yaml_path(profile: str) -> Path:
    return CAMERA_DIR / f"{profile}.yaml"


def write_focal(path: Path, focal: float, *, note: str = "") -> bool:
    """Rewrite fx/fy + flip needs_calibration:false, preserving comments."""
    text = path.read_text(encoding="utf-8")
    new = _FX.sub(rf"\g<1>{focal:.1f}{note}", text, count=1)
    new = _FY.sub(rf"\g<1>{focal:.1f}", new, count=1)
    new = _NEEDS.sub(r"\g<1>false", new, count=1)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def scale_focal(current_fy: float, median_gt_over_pred: float) -> float:
    """Apply a multiplicative distance correction to focal length."""
    if current_fy <= 0 or median_gt_over_pred <= 0:
        raise ValueError("focal length and scale must be positive")
    return float(current_fy * median_gt_over_pred)


def focal_from_hfov(width: int, height: int, hfov_deg: float) -> tuple[float, float]:
    """Estimate fx/fy from horizontal FOV and resolution (square pixels)."""
    import math

    if width <= 0 or height <= 0 or hfov_deg <= 0:
        raise ValueError("width, height, and hfov_deg must be positive")
    hfov = math.radians(float(hfov_deg))
    fx = width / (2.0 * math.tan(hfov / 2.0))
    vfov = 2.0 * math.atan(math.tan(hfov / 2.0) * height / width)
    fy = height / (2.0 * math.tan(vfov / 2.0))
    return round(fx, 1), round(fy, 1)
