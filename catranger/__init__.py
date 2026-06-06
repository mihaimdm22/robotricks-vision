"""CatRanger — detect + track a cat and estimate how far it is.

Monsson hack-a-ton 2026. Core (config/intrinsics/io/types) imports with only
numpy+opencv+pyyaml. Perception/depth/training backends are imported lazily so
`import catranger` stays light and fails loudly only when a backend is actually used.
"""

__version__ = "0.1.0"

from catranger.types import (
    Detection,
    DistanceResult,
    CatObservation,
    FrameResult,
    Command,
)
from catranger.config import CameraConfig, AppConfig, load_camera, load_app, load_yaml
from catranger.intrinsics import CameraModel

__all__ = [
    "Detection",
    "DistanceResult",
    "CatObservation",
    "FrameResult",
    "Command",
    "CameraConfig",
    "AppConfig",
    "load_camera",
    "load_app",
    "load_yaml",
    "CameraModel",
]
