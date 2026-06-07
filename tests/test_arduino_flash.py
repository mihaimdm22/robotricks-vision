"""Unit tests for arduino-cli flash helper (mocked subprocess)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from catranger.hw import arduino_flash as af


def test_readiness_reports_missing_cli(tmp_path: Path) -> None:
    sketch = tmp_path / "cat_ranger"
    sketch.mkdir()
    with patch.object(af, "find_cli", return_value=None):
        out = af.readiness(sketch_dir=sketch)
    assert out["ok"] is False
    assert "arduino-cli" in str(out.get("problem", ""))


def test_readiness_ok_when_cli_and_sketch_present(tmp_path: Path) -> None:
    sketch = tmp_path / "cat_ranger"
    sketch.mkdir()
    with patch.object(af, "find_cli", return_value="/usr/bin/arduino-cli"):
        out = af.readiness(sketch_dir=sketch)
    assert out["ok"] is True
    assert out["arduino_cli"] == "/usr/bin/arduino-cli"


def test_flash_sketch_success(tmp_path: Path) -> None:
    sketch = tmp_path / "cat_ranger"
    sketch.mkdir()

    def fake_run(cmd: list[str], *, timeout: float = 300) -> tuple[int, str]:
        joined = " ".join(cmd)
        if "core install" in joined or "lib install" in joined:
            return 0, "already installed"
        if "compile" in joined:
            return 0, "Sketch uses 12345 bytes"
        if "upload" in joined:
            assert "-p" in cmd and "/dev/ttyACM0" in cmd
            return 0, "Done uploading"
        return 1, "unexpected"

    with (
        patch.object(af, "find_cli", return_value="/usr/bin/arduino-cli"),
        patch.object(af, "_run", side_effect=fake_run),
    ):
        out = af.flash_sketch("/dev/ttyACM0", sketch_dir=sketch, install_deps=True)

    assert out["ok"] is True
    assert out["port"] == "/dev/ttyACM0"


def test_flash_sketch_compile_failure(tmp_path: Path) -> None:
    sketch = tmp_path / "cat_ranger"
    sketch.mkdir()

    def fake_run(cmd: list[str], *, timeout: float = 300) -> tuple[int, str]:
        if "compile" in " ".join(cmd):
            return 1, "error: AFMotor.h: No such file"
        return 0, "ok"

    with (
        patch.object(af, "find_cli", return_value="/usr/bin/arduino-cli"),
        patch.object(af, "_run", side_effect=fake_run),
    ):
        out = af.flash_sketch(None, sketch_dir=sketch, install_deps=False)

    assert out["ok"] is False
    assert out["code"] == "flash_compile_failed"
