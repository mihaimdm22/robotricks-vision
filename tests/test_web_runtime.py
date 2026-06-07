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

    rt._record_eval("web-eval-1", {"source": "x"})
    status = rt.jobs_status()
    assert status["counts"] == {"running": 1}
    assert status["jobs"][0]["run_key"] == "web-eval-1"
    rt._settle_eval("web-eval-1", "ok")
    assert rt.jobs_status()["counts"] == {"ok": 1}


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
