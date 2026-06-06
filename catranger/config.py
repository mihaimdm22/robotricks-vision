"""Config loading. Numbers live in YAML, never hard-coded in logic (Karpathy rule 5).

`CameraConfig` is the metric-critical one: get fx/fy wrong and every distance is off
by a constant. `AppConfig` is the loose bag of task settings (detector, depth, follow,
size priors) kept as a dict so adding a knob doesn't require touching this file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "configs"


def load_yaml(path: str | os.PathLike) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        # allow bare names like "go2_1080p" or "cat_distance"
        for cand in (_CONFIG_DIR / p, _CONFIG_DIR / "camera" / p):
            for suffix in ("", ".yaml", ".yml"):
                c = cand.with_name(cand.name + suffix) if suffix else cand
                if c.exists():
                    p = c
                    break
            if p.exists():
                break
    with open(p) as f:
        return yaml.safe_load(f) or {}


@dataclass
class CameraConfig:
    name: str
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    fov_deg: float = 120.0
    dist_model: str = "fov"  # "fov" (one-param division model) | "none"
    mount_height_m: float = 0.30  # camera height above the floor (Go2 dog's-eye)
    needs_calibration: bool = False  # True for the Tapo until re-anchored
    rtsp: str | None = None  # stream URL template for live cameras

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CameraConfig:
        return cls(
            name=d.get("name", "camera"),
            fx=float(d["fx"]),
            fy=float(d["fy"]),
            cx=float(d["cx"]),
            cy=float(d["cy"]),
            width=int(d["width"]),
            height=int(d["height"]),
            fov_deg=float(d.get("fov_deg", 120.0)),
            dist_model=str(d.get("dist_model", "fov")),
            mount_height_m=float(d.get("mount_height_m", 0.30)),
            needs_calibration=bool(d.get("needs_calibration", False)),
            rtsp=d.get("rtsp"),
        )


def load_camera(name_or_path: str = "go2_1080p") -> CameraConfig:
    """Load a camera config by bare name (configs/camera/<name>.yaml) or path."""
    return CameraConfig.from_dict(load_yaml(name_or_path))


@dataclass
class AppConfig:
    """Task config (detector, tracker, depth, follow, size priors). Loose by design."""

    raw: dict[str, Any]
    camera: CameraConfig

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    # convenience accessors used across the codebase
    @property
    def size_priors(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("size_priors", {})

    @property
    def classes(self) -> list | None:
        return self.raw.get("classes")


def load_app(path: str = "cat_distance") -> AppConfig:
    raw = load_yaml(path)
    cam_ref = raw.get("camera", "go2_1080p")
    camera = load_camera(cam_ref) if isinstance(cam_ref, str) else CameraConfig.from_dict(cam_ref)
    return AppConfig(raw=raw, camera=camera)
