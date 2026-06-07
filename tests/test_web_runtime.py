"""RobotRuntime perception-error handling (regression for the model-swap bug).

A per-frame inference error must NOT be misreported as "ml not installed": it
should surface a real error, fall back to passthrough so the video stream
survives, and keep perception_available (ml-installed) intact so the operator can
re-select/retry. These run hardware-free with a fake ranger (no torch needed).
"""

from __future__ import annotations

import numpy as np

from catranger.web.runtime import RobotRuntime


class _RaisingRanger:
    """Stands in for a CatRanger whose inference blows up every frame."""

    def process(self, frame, idx):  # noqa: ANN001
        raise RuntimeError("inference boom")


def _runtime() -> RobotRuntime:
    return RobotRuntime({"default_camera": "synthetic"})


def _frame() -> np.ndarray:
    return np.zeros((540, 960, 3), dtype=np.uint8)


def test_perceive_error_keeps_perception_available_and_reports_error() -> None:
    rt = _runtime()
    rt.perception_available = True  # simulate the ml extra being installed
    rt._ranger = _RaisingRanger()
    result, draw = rt._perceive(_frame(), 0)
    # falls back to a passthrough result so the MJPEG stream survives
    assert result.observations == []
    # a RUNTIME inference error must NOT be misreported as "ml missing"
    assert rt.perception_available is True
    assert rt.model_status == "error"
    assert rt.model_error  # a human-readable reason is captured for the UI


def test_jobs_status_empty_when_no_queue_then_reflects_recorded(tmp_path) -> None:
    # WS-B3 backend: jobs_status reads the durable queue (creating nothing until a job is
    # recorded), then reflects recorded sweeps/evals for the live panel.
    db = tmp_path / "jq.sqlite3"
    rt = RobotRuntime({"default_camera": "synthetic", "jobqueue_db": str(db)})
    assert rt.jobs_status() == {"ok": True, "jobs": [], "counts": {}}
    assert not db.exists()  # a pure read must not create the queue file

    rt._record_job("web-eval-1", "web-eval", {"source": "x"})
    status = rt.jobs_status()
    assert status["counts"] == {"running": 1}
    assert status["jobs"][0]["run_key"] == "web-eval-1"
    rt._settle_job("web-eval-1", "ok")
    assert rt.jobs_status()["counts"] == {"ok": 1}
    # WS-A7 unification: a web TRAIN job records into the same durable queue.
    rt._record_job("web-train-1", "web-train", {"kind": "autoresearch"})
    assert rt.jobs_status()["counts"] == {"ok": 1, "running": 1}
    rt._settle_job("web-train-1", "ok")
    assert rt.jobs_status()["counts"] == {"ok": 2}


def test_select_model_reports_load_failure_not_ml_missing_when_available() -> None:
    rt = _runtime()
    rt.perception_available = True

    def _boom(profile):  # noqa: ANN001, ANN202
        raise RuntimeError("build boom")

    rt._build_ranger = _boom  # type: ignore[method-assign]
    res = rt.select_model(rt.registry.default.id)
    assert res["ok"] is False
    assert res.get("code") == "model_load_failed"
    assert rt.perception_available is True  # availability flag is never clobbered


def test_sonar_zone_and_peripheral_telemetry() -> None:
    from catranger.hw.char_bridge import CharBridge

    class _Ser:
        def write(self, b: bytes) -> int:
            return len(b)

        def close(self) -> None:
            pass

    rt = _runtime()
    bridge = CharBridge(transport=_Ser())
    rt.controller.attach(bridge=bridge)
    rt.controller.robot_connected = True
    rt.controller.latest_telemetry["gt_cm"] = 45
    t = rt.telemetry()
    assert t["sonar_zone"] == "yellow"
    assert t["buzzer_active"] is True
    assert t["sonar_range_cm"] == 200
    assert t["peripherals"]["buzzer"] is True

    rt.controller.latest_telemetry["gt_cm"] = -1
    t2 = rt.telemetry()
    assert t2["sonar_no_echo"] is True
    assert t2["sonar_display_cm"] == 45
    assert t2["sonar_zone"] == "yellow"

    res = rt.set_peripheral("buzzer_toggle")
    assert res["ok"] is True
    assert res["peripherals"]["buzzer"] is False


def test_set_peripheral_requires_char_bridge() -> None:
    rt = _runtime()
    from catranger.hw.serial_bridge import DummyBridge

    rt.controller.attach(bridge=DummyBridge())
    rt.controller.robot_connected = True
    assert rt.set_peripheral("buzzer_toggle")["ok"] is False


def test_select_target_sets_preferred_and_follow() -> None:
    rt = _runtime()
    res = rt.select_target(42, follow=True)
    assert res["ok"] is True
    assert res["preferred_target_id"] == 42
    assert res["mode"] == "FOLLOW"
    assert rt._preferred_target_id == 42


def test_find_library_cat_sets_search_mode(tmp_path) -> None:
    rt = RobotRuntime(
        {
            "default_camera": "synthetic",
            "cat_library_db": str(tmp_path / "lib.sqlite3"),
        }
    )
    lib_id = rt.cat_library.upsert_sighting(
        library_id=None,
        tracker_id=3,
        thumb_jpeg=b"face",
        conf=0.8,
        dist_m=1.0,
        bearing_deg=-15.0,
        name="Whiskers",
    )
    res = rt.find_library_cat(lib_id, follow=True)
    assert res["ok"] is True
    assert rt._find_library_id == lib_id
    assert rt.controller.mode.value == "FOLLOW"
    t = rt.telemetry()
    assert t["find_library_id"] == lib_id
    assert t["find_library_name"] == "Whiskers"
