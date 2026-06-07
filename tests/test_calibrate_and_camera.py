"""Tests the plan's §6 named as owed: the calibration solver, rtsp credential
redaction, and the camera-profile re-anchor (the on-rubric distance path)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from catranger.web.runtime import RobotRuntime, _parse_rtsp, _redact_spec

_REPO = Path(__file__).resolve().parents[1]


def _load_calibrate():
    spec = importlib.util.spec_from_file_location(
        "calibrate_camera", _REPO / "scripts" / "calibrate_camera.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- calibration
def test_solve_focal() -> None:
    cal = _load_calibrate()
    # fy = h_px * Z / H_real ; A4 (0.297 m) at 2 m, 240 px -> 240*2/0.297
    assert cal.solve_focal(0.297, 2.0, 240.0) == 240.0 * 2.0 / 0.297


def test_write_focal_flips_needs_calibration(tmp_path) -> None:
    cal = _load_calibrate()
    cam = tmp_path / "tapo_c211.yaml"
    cam.write_text(
        "name: tapo_c211\nfx: 1100.0   # PLACEHOLDER\nfy: 1100.0\nneeds_calibration: true\n",
        encoding="utf-8",
    )
    assert cal.write_focal(cam, 1616.2) is True
    text = cam.read_text(encoding="utf-8")
    assert "fx: 1616.2" in text and "fy: 1616.2" in text
    assert "needs_calibration: false" in text


# --------------------------------------------------------------- redaction
def test_redact_spec_hides_credentials() -> None:
    assert _redact_spec("rtsp://Andrei:Andrei12@192.168.0.5:554/stream1") == (
        "rtsp://***@192.168.0.5:554/stream1"
    )
    assert _redact_spec("camera:rtsp://u:p@host/s") == "camera:rtsp://***@host/s"
    assert _redact_spec("synthetic") == "synthetic"  # no creds, untouched


def test_parse_rtsp() -> None:
    assert _parse_rtsp("rtsp://u:p@10.0.0.2:554/stream2") == ("10.0.0.2", "u", "p", "stream2")
    # no creds, default stream
    assert _parse_rtsp("rtsp://10.0.0.2:554") == ("10.0.0.2", "", "", "stream1")


# --------------------------------------------------------------- re-anchor
def test_reanchor_sets_profile_and_calibration_flag(tmp_path) -> None:
    rt = RobotRuntime(web_cfg={"history_db": str(tmp_path / "h.sqlite3")})
    # tapo profile is a placeholder -> calibrated False, warning surfaced
    res = rt.reanchor_camera("tapo_c211")
    assert res["ok"] is True and res["camera_profile"] == "tapo_c211"
    assert res["calibrated"] is False and "UNCALIBRATED" in (res["warning"] or "")
    assert rt.camera_profile == "tapo_c211" and rt.camera_calibrated is False
    # go2 is calibrated -> no warning
    res2 = rt.reanchor_camera("go2_1080p")
    assert res2["calibrated"] is True and res2["warning"] is None
    rt.store.close()


def test_reanchor_unknown_profile_is_typed_error(tmp_path) -> None:
    rt = RobotRuntime(web_cfg={"history_db": str(tmp_path / "h.sqlite3")})
    res = rt.reanchor_camera("nope")
    assert res["ok"] is False and res["code"] == "camera_bad_profile"
    rt.store.close()


def test_diagnose_camera_distinguishes_causes(tmp_path) -> None:
    rt = RobotRuntime(web_cfg={"history_db": str(tmp_path / "h.sqlite3")})
    # non-rtsp -> generic
    assert "synthetic" in rt._diagnose_camera("0")
    # rtsp to a refused port -> 'cannot reach' (Camera-Account hint reserved for reachable)
    msg = rt._diagnose_camera("rtsp://127.0.0.1:1/stream1")
    assert "cannot reach 127.0.0.1:1" in msg
    rt.store.close()
