#!/usr/bin/env python3
"""Re-anchor a camera's focal length so metric distance is correct.

The Tapo C211 ships with PLACEHOLDER intrinsics (fx=fy=1100, needs_calibration:
true). Distance is `Z = fy * H_real / h_px`, so a wrong fy scales every reading by
a constant. This solves fy from one known measurement and writes it into the YAML
(comment-preserving), flipping `needs_calibration` to false.

How to measure (no special rig):
  1. Stand an object of known real height H_real (m) at a known distance Z (m)
     from the camera (a 0.297 m A4 sheet at 2.00 m works).
  2. Open one frame from the camera, read the object's pixel height h_px.
  3. Run:
       python scripts/calibrate_camera.py --camera tapo_c211 \
           --known-height-m 0.297 --distance-m 2.00 --pixel-height-px 240
     => fx = fy = h_px * Z / H_real

Flags:
  --camera NAME          profile under configs/camera/ (default: tapo_c211)
  --known-height-m H     real object height in meters
  --distance-m Z         camera-to-object distance in meters
  --pixel-height-px h    object's height in pixels in the frame
  --dry-run              print the computed fx/fy; change nothing
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAMERA_DIR = REPO / "configs" / "camera"

_FX = re.compile(r"^(\s*fx:\s*)[-\d.]+.*$", re.MULTILINE)
_FY = re.compile(r"^(\s*fy:\s*)[-\d.]+.*$", re.MULTILINE)
_NEEDS = re.compile(r"^(\s*needs_calibration:\s*)\w+.*$", re.MULTILINE)


def solve_focal(known_height_m: float, distance_m: float, pixel_height_px: float) -> float:
    """fy = h_px * Z / H_real (pinhole). fx == fy for square pixels."""
    if known_height_m <= 0 or distance_m <= 0 or pixel_height_px <= 0:
        raise SystemExit(
            "[calibrate] --known-height-m, --distance-m, --pixel-height-px must be > 0"
        )
    return pixel_height_px * distance_m / known_height_m


def write_focal(path: Path, focal: float) -> bool:
    """Rewrite fx/fy + flip needs_calibration:false, preserving comments. Returns
    True if the file changed."""
    text = path.read_text(encoding="utf-8")
    note = "  # calibrated by scripts/calibrate_camera.py (fy = h_px*Z/H_real)"
    new = _FX.sub(rf"\g<1>{focal:.1f}{note}", text, count=1)
    new = _FY.sub(rf"\g<1>{focal:.1f}", new, count=1)
    new = _NEEDS.sub(r"\g<1>false", new, count=1)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Re-anchor a camera's focal length (fx=fy).")
    ap.add_argument("--camera", default="tapo_c211", help="profile name under configs/camera/")
    ap.add_argument("--known-height-m", type=float, required=True, help="real object height (m)")
    ap.add_argument("--distance-m", type=float, required=True, help="camera-to-object distance (m)")
    ap.add_argument("--pixel-height-px", type=float, required=True, help="object height in pixels")
    ap.add_argument("--dry-run", action="store_true", help="preview only; change nothing")
    args = ap.parse_args(argv)

    path = CAMERA_DIR / f"{args.camera}.yaml"
    if not path.exists():
        print(f"[calibrate] no camera config: {path}")
        return 1

    focal = solve_focal(args.known_height_m, args.distance_m, args.pixel_height_px)
    print(
        f"[calibrate] {args.camera}: fx = fy = {focal:.1f} "
        f"(h_px={args.pixel_height_px} * Z={args.distance_m} / H={args.known_height_m})"
    )
    if args.dry_run:
        print("[calibrate] --dry-run: file unchanged.")
        return 0
    if write_focal(path, focal):
        print(f"[calibrate] wrote fx=fy={focal:.1f}, needs_calibration: false -> {path}")
        print("[calibrate] re-select the tapo_c211 profile in the console to re-anchor live.")
    else:
        print(f"[calibrate] no fx/fy lines found to update in {path} — aborting.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
