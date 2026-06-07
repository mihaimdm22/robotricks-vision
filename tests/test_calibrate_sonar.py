"""Sonar-assisted camera calibration (HC-SR04 ground truth + baseline offset)."""

from __future__ import annotations

import pytest

from catranger.calibrate_sonar import (
    calibrate_camera_with_sonar,
    camera_distance_from_sonar_cm,
    collect_sonar_ratios,
    focal_scale_from_samples,
)
from catranger.camera_calibrate import scale_focal, write_focal


def test_camera_distance_from_sonar_applies_baseline() -> None:
    assert camera_distance_from_sonar_cm(100, 0.09) == pytest.approx(1.09)
    assert camera_distance_from_sonar_cm(50, 0.09) == pytest.approx(0.59)


def test_focal_scale_median() -> None:
    assert focal_scale_from_samples([1.0, 1.1, 0.9]) == pytest.approx(1.0)
    assert focal_scale_from_samples([]) is None


def test_scale_focal_multiplies_fy() -> None:
    assert scale_focal(800.0, 1.25) == pytest.approx(1000.0)


def test_collect_sonar_ratios_filters_band() -> None:
    samples = [
        (1.0, 20),  # too close
        (1.0, 100),
        (1.0, 100),
        (None, 100),
        (1.0, None),
        (1.0, 200),  # too far
    ]
    idx = 0

    def read() -> tuple[float | None, int | None]:
        nonlocal idx
        if idx >= len(samples):
            return None, None
        pair = samples[idx]
        idx += 1
        return pair

    state = {"t": 0.0}

    def clock() -> float:
        return state["t"]

    def tick(_: float) -> None:
        state["t"] += 0.02

    ratios, preds, gts = collect_sonar_ratios(
        read,
        duration_s=0.12,
        sample_interval_s=0.0,
        min_sonar_cm=25,
        max_sonar_cm=180,
        baseline_m=0.09,
        clock=clock,
        sleep=tick,
    )
    assert len(ratios) == 2
    assert all(r == pytest.approx(1.09) for r in ratios)
    assert preds == [1.0, 1.0]
    assert gts == [pytest.approx(1.09), pytest.approx(1.09)]


def test_calibrate_camera_with_sonar_writes_yaml(tmp_path, monkeypatch) -> None:
    cam_dir = tmp_path / "camera"
    cam_dir.mkdir()
    cam_path = cam_dir / "go2_1080p.yaml"
    cam_path.write_text(
        "name: go2_1080p\nfx: 800.0\nfy: 800.0\nneeds_calibration: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "catranger.calibrate_sonar.camera_yaml_path",
        lambda profile: cam_dir / f"{profile}.yaml",
    )
    monkeypatch.setattr(
        "catranger.calibrate_sonar.load_camera",
        lambda profile: type(
            "Cam",
            (),
            {"fx": 800.0, "fy": 800.0, "needs_calibration": True},
        )(),
    )

    result = calibrate_camera_with_sonar(
        "go2_1080p",
        [1.1, 1.1, 1.1],
        baseline_m=0.09,
        dry_run=False,
    )
    assert result.ok is True
    assert result.scale == pytest.approx(1.1)
    assert result.new_fy == pytest.approx(880.0)
    text = cam_path.read_text(encoding="utf-8")
    assert "fy: 880.0" in text
    assert "needs_calibration: false" in text


def test_write_focal_shared_helper(tmp_path) -> None:
    cam = tmp_path / "tapo_c211.yaml"
    cam.write_text(
        "name: tapo_c211\nfx: 1100.0   # PLACEHOLDER\nfy: 1100.0\nneeds_calibration: true\n",
        encoding="utf-8",
    )
    assert write_focal(cam, 1616.2) is True
    text = cam.read_text(encoding="utf-8")
    assert "fx: 1616.2" in text and "fy: 1616.2" in text
    assert "needs_calibration: false" in text
