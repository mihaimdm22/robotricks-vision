"""Shared fixtures for the CatRanger test suite.

Tests target the deterministic pure-core (geometry, distance fusion, config, the
metric functions, the follow state machine, frame I/O routing). The heavy GPU/model
paths (detect/depth/track) are import-smoke-tested in CI, not unit-tested here.
"""

from __future__ import annotations

import pytest

from catranger.config import CameraConfig
from catranger.intrinsics import CameraModel


@pytest.fixture
def cfg() -> CameraConfig:
    """Go2 1080p intrinsics — the camera we develop and report against."""
    return CameraConfig(
        name="go2",
        fx=554.3,
        fy=554.3,
        cx=960.0,
        cy=540.0,
        width=1920,
        height=1080,
        fov_deg=120.0,
        dist_model="fov",
    )


@pytest.fixture
def cam(cfg: CameraConfig) -> CameraModel:
    return CameraModel(cfg)
