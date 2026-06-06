"""Config loading — bare-name resolution into configs/ and safe nested lookups."""

from __future__ import annotations

import pytest

from catranger.config import AppConfig, load_app, load_camera, load_yaml


def test_load_yaml_resolves_bare_camera_name() -> None:
    d = load_yaml("go2_1080p")  # -> configs/camera/go2_1080p.yaml
    assert d["fx"] == pytest.approx(554.3)


def test_load_camera_go2_defaults() -> None:
    c = load_camera("go2_1080p")
    assert c.fx == pytest.approx(554.3)
    assert c.width == 1920
    assert c.dist_model == "none"  # provided config disables undistort by default


def test_load_yaml_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_yaml("does_not_exist_xyz")


def test_appconfig_get_nested_default_and_short_circuit() -> None:
    app = AppConfig(raw={"detector": {"name": "yolo"}}, camera=load_camera("go2_1080p"))
    assert app.get("detector", "name") == "yolo"
    assert app.get("detector", "missing", default="d") == "d"
    assert app.get("nope", default=None) is None
    # walking into a non-dict node short-circuits to the default
    assert app.get("detector", "name", "deeper", default="x") == "x"


def test_load_app_cat_distance_resolves_camera_and_priors() -> None:
    app = load_app("cat_distance")
    assert app.camera.fx == pytest.approx(554.3)
    assert "cat" in app.size_priors
    assert app.get("follow", "setpoint_distance_m") == pytest.approx(1.5)
