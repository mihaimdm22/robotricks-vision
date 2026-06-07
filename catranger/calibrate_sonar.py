"""Calibrate camera metric distance using HC-SR04 readings as ground truth.

The ultrasonic sensor sits ahead of the camera on the chassis. When the sensor
reads ``sonar_m`` along the boresight, the camera optical center is farther from
the target by the baseline offset (default 90 mm):

    camera_gt_m = sonar_m + baseline_m
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from catranger.camera_calibrate import camera_yaml_path, scale_focal, write_focal
from catranger.config import load_camera


def camera_distance_from_sonar_cm(sonar_cm: float, baseline_m: float = 0.09) -> float:
    """Convert a raw HC-SR04 reading to camera-frame ground-truth distance (m)."""
    if sonar_cm < 0:
        return float("nan")
    return float(sonar_cm) / 100.0 + float(baseline_m)


def focal_scale_from_samples(ratios: list[float]) -> float | None:
    """Median gt/pred ratio; None if no valid samples."""
    arr = np.asarray(ratios, dtype=np.float64)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if arr.size == 0:
        return None
    return float(np.median(arr))


@dataclass
class SonarCalibrateResult:
    ok: bool
    scale: float | None = None
    old_fy: float | None = None
    new_fy: float | None = None
    n_samples: int = 0
    pred_m_mean: float | None = None
    gt_m_mean: float | None = None
    baseline_m: float = 0.09
    profile: str = ""
    dry_run: bool = False
    problem: str | None = None
    fix: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "n_samples": self.n_samples,
            "baseline_m": self.baseline_m,
            "profile": self.profile,
            "dry_run": self.dry_run,
        }
        if self.scale is not None:
            out["scale"] = round(self.scale, 4)
        if self.old_fy is not None:
            out["old_fy"] = round(self.old_fy, 1)
        if self.new_fy is not None:
            out["new_fy"] = round(self.new_fy, 1)
        if self.pred_m_mean is not None:
            out["pred_m_mean"] = round(self.pred_m_mean, 3)
        if self.gt_m_mean is not None:
            out["gt_m_mean"] = round(self.gt_m_mean, 3)
        if self.problem:
            out["problem"] = self.problem
        if self.fix:
            out["fix"] = self.fix
        return out


def collect_sonar_ratios(
    read_sample: Callable[[], tuple[float | None, int | None]],
    *,
    duration_s: float = 5.0,
    sample_interval_s: float = 0.15,
    min_sonar_cm: int = 25,
    max_sonar_cm: int = 180,
    baseline_m: float = 0.09,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[float], list[float], list[float]]:
    """Poll ``read_sample()`` until ``duration_s`` elapses.

    Returns (ratios, pred_m list, gt_m list) for diagnostics.
    """
    ratios: list[float] = []
    preds: list[float] = []
    gts: list[float] = []
    deadline = clock() + max(0.5, float(duration_s))
    while clock() < deadline:
        pred_m, sonar_cm = read_sample()
        if pred_m is not None and sonar_cm is not None and sonar_cm >= 0:
            if min_sonar_cm <= sonar_cm <= max_sonar_cm and pred_m > 0:
                gt_m = camera_distance_from_sonar_cm(sonar_cm, baseline_m)
                if np.isfinite(gt_m) and gt_m > 0:
                    ratios.append(gt_m / float(pred_m))
                    preds.append(float(pred_m))
                    gts.append(gt_m)
        sleep(sample_interval_s)
    return ratios, preds, gts


def calibrate_camera_with_sonar(
    profile: str,
    ratios: list[float],
    *,
    baseline_m: float = 0.09,
    dry_run: bool = False,
) -> SonarCalibrateResult:
    """Apply median gt/pred scale to the camera profile's fy (and fx)."""
    scale = focal_scale_from_samples(ratios)
    if scale is None:
        return SonarCalibrateResult(
            ok=False,
            n_samples=0,
            baseline_m=baseline_m,
            profile=profile,
            dry_run=dry_run,
            problem="no valid sonar/vision sample pairs",
            fix="track a cat or place a flat target in front of the rig; keep sonar 25–180 cm",
        )
    cam = load_camera(profile)
    path = camera_yaml_path(profile)
    if not path.exists():
        return SonarCalibrateResult(
            ok=False,
            n_samples=len(ratios),
            scale=scale,
            baseline_m=baseline_m,
            profile=profile,
            dry_run=dry_run,
            problem=f"camera config not found: {path.name}",
            fix="use go2_1080p or tapo_c211",
        )
    try:
        new_fy = scale_focal(cam.fy, scale)
    except ValueError as exc:
        return SonarCalibrateResult(
            ok=False,
            n_samples=len(ratios),
            scale=scale,
            old_fy=cam.fy,
            baseline_m=baseline_m,
            profile=profile,
            dry_run=dry_run,
            problem=str(exc),
        )
    note = f"  # sonar-calibrated (baseline={baseline_m:.3f}m, scale={scale:.4f}, n={len(ratios)})"
    if dry_run:
        return SonarCalibrateResult(
            ok=True,
            scale=scale,
            old_fy=cam.fy,
            new_fy=new_fy,
            n_samples=len(ratios),
            baseline_m=baseline_m,
            profile=profile,
            dry_run=True,
        )
    if not write_focal(path, new_fy, note=note):
        return SonarCalibrateResult(
            ok=False,
            n_samples=len(ratios),
            scale=scale,
            old_fy=cam.fy,
            new_fy=new_fy,
            baseline_m=baseline_m,
            profile=profile,
            problem=f"could not update fx/fy in {path.name}",
            fix="check configs/camera/*.yaml has fx/fy lines",
        )
    return SonarCalibrateResult(
        ok=True,
        scale=scale,
        old_fy=cam.fy,
        new_fy=new_fy,
        n_samples=len(ratios),
        baseline_m=baseline_m,
        profile=profile,
        dry_run=False,
    )
