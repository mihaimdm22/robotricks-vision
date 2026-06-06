"""CatRanger web control platform (optional `web` extra).

The browser control plane on top of the perception/hardware core: a safety-first
RobotController (mode + manual drive + watchdog + latched E-stop), a model
registry for hot-swapping detectors, and a FastAPI server (added in M2).

This subpackage is the operator-facing edge, analogous to `catranger.hw`. The
controller + registry import with only the base deps; the FastAPI server is
imported lazily by `catranger serve` so `import catranger.web` stays light and the
scored perception core is never touched.
"""

from __future__ import annotations

from catranger.web.controller import ManualVector, Mode, RobotController, StopReason
from catranger.web.registry import ModelProfile, ModelRegistry

__all__ = [
    "ManualVector",
    "Mode",
    "ModelProfile",
    "ModelRegistry",
    "RobotController",
    "StopReason",
]
