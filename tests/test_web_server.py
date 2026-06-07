"""Route-contract tests for the FastAPI control plane.

Skipped unless the `web` extra is installed (base-deps CI `test` job), so the
core gate stays light. A FakeRuntime delegates the pure state ops to a REAL
RobotController (so E-stop/mode/watchdog semantics are exercised through the
HTTP layer) and stubs the I/O (video/models/devices).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from catranger.web.controller import RobotController  # noqa: E402
from catranger.web.server import _mjpeg_chunk, create_app  # noqa: E402


class FakeRuntime:
    fps_cap = 15

    def __init__(self) -> None:
        self.controller = RobotController()
        self.started = False
        self.stopped = False
        self._models = [
            {"id": "yolo11s", "name": "YOLO11s", "backend": "yolo", "dataset": "COCO"},
            {"id": "rtdetr-l", "name": "RT-DETR-L", "backend": "rtdetr", "dataset": "COCO"},
        ]
        self.camera = "synthetic"
        self.robot = "dummy"
        self._eval_running = False
        self._eval_result: dict | None = None
        self._train_running = False
        self._train_result: dict | None = None

    # lifecycle
    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    # readers
    def status(self) -> dict:
        return {
            "mode": self.controller.mode.value,
            "estop": self.controller.estopped,
            "stop_reason": self.controller.stop_reason.value,
            "robot_connected": self.controller.robot_connected,
            "camera_connected": self.controller.camera_connected,
            "robot": self.robot,
            "camera": self.camera,
            "model": "yolo11s",
            "model_status": "ready",
            "perception_available": False,
            "models": self._models,
        }

    def telemetry(self) -> dict:
        return {
            "mode": self.controller.mode.value,
            "estop": self.controller.estopped,
            "stop_reason": self.controller.stop_reason.value,
        }

    def latest_jpeg(self) -> bytes:
        return b"\xff\xd8\xff\xe0jpegbytes\xff\xd9"

    # pure ops -> real controller
    def set_manual(self, action: str, value: float = 0.0) -> None:
        self.controller.set_manual(action, value)

    def set_mode(self, mode: str) -> bool:
        return self.controller.set_mode(mode)

    def estop(self) -> None:
        self.controller.estop()

    def reset(self) -> None:
        self.controller.reset()

    def heartbeat(self) -> None:
        self.controller.heartbeat()

    # stubbed I/O
    def select_model(self, model_id: str) -> dict:
        if model_id not in [m["id"] for m in self._models]:
            raise KeyError(model_id)
        return {"ok": True, "model": model_id, "status": "ready"}

    def connect_camera(self, spec: str, camera: str | None = None) -> dict:
        self.camera = spec
        self.camera_profile = camera
        return {"ok": True, "label": spec, "warning": None, "camera_profile": camera}

    def connect_robot(self, connection: str, target: str | None = None, baud: int = 115200) -> dict:
        self.robot = f"{connection}:{target}" if target else connection
        return {"ok": True, "bridge": "DummyBridge", "connected": False, "warning": None}

    # eval (M3) — a controllable fake job for route-contract tests
    def start_eval(self, params: dict) -> dict:
        if not params.get("source"):
            return {
                "ok": False,
                "code": "eval_bad_source",
                "problem": "no source",
                "cause": "",
                "fix": "",
                "status": 400,
            }
        if self._eval_running:
            return {
                "ok": False,
                "code": "eval_busy",
                "problem": "already running",
                "cause": "",
                "fix": "",
                "status": 409,
            }
        if self._train_running:
            return {
                "ok": False,
                "code": "heavy_job_busy",
                "problem": "training running",
                "cause": "",
                "fix": "",
                "status": 409,
            }
        self._eval_running = True
        return {"ok": True, "state": "running"}

    def eval_status(self) -> dict:
        return {
            "ok": True,
            "state": "running" if self._eval_running else "idle",
            "done": 0,
            "total": None,
            "started_at": None,
            "n_frames": None,
            "error": None,
        }

    def eval_result(self) -> dict | None:
        return self._eval_result

    def cancel_eval(self) -> dict:
        self._eval_running = False
        return {"ok": True, "cancelled": True}

    # training (CV tab) — a controllable fake for route-contract tests
    @property
    def training_active(self) -> bool:
        return self._train_running

    def train_readiness(self) -> dict:
        return {
            "ok": True,
            "ml_available": False,
            "dataset_ready": True,
            "running": self._train_running,
            "eval_running": self._eval_running,
            "idle": self.controller.mode.value == "IDLE",
        }

    def start_train(self, params: dict) -> dict:
        kind = params.get("kind")
        if kind not in ("prepare", "train", "autoresearch"):
            return {"ok": False, "code": "train_bad_kind", "problem": "bad", "status": 400}
        if self.controller.mode.value != "IDLE":
            return {"ok": False, "code": "train_not_idle", "problem": "not idle", "status": 409}
        if self._eval_running:
            return {"ok": False, "code": "heavy_job_busy", "problem": "eval running", "status": 409}
        if self._train_running:
            return {"ok": False, "code": "train_busy", "problem": "already", "status": 409}
        self._train_running = True
        return {"ok": True, "state": "running", "kind": kind}

    def train_status(self) -> dict:
        return {"ok": True, "state": "running" if self._train_running else "idle", "kind": None}

    def train_result(self) -> dict | None:
        return self._train_result

    def cancel_train(self) -> dict:
        self._train_running = False
        return {"ok": True, "cancelled": True}

    def train_history(self, limit: int = 50) -> dict:
        return {"ok": True, "runs": []}

    def promote_model(self, params: dict) -> dict:
        if not (params.get("weights") or params.get("run_dir")):
            return {"ok": False, "code": "promote_no_winner", "problem": "none", "status": 409}
        return {
            "ok": True,
            "weights": params.get("weights") or f"runs/history/{params['run_dir']}/best.pt",
            "model_id": "cats-finetuned",
        }

    def ptz_move(self, pan: float, tilt: float) -> dict:
        return {"ok": False, "code": "ptz_no_camera", "problem": "no tapo", "status": 409}

    def ptz_preset(self, name: str) -> dict:
        return {"ok": False, "code": "ptz_no_camera", "problem": "no tapo", "status": 409}

    # discovery (M5)
    def discover_devices(self) -> dict:
        return {"ok": True, "serial": [], "ble_available": False, "hint": "no serial ports found"}


@pytest.fixture
def client_and_runtime():
    rt = FakeRuntime()
    with TestClient(create_app(rt)) as client:
        yield client, rt


def test_lifespan_starts_and_stops_the_runtime() -> None:
    rt = FakeRuntime()
    with TestClient(create_app(rt)):
        assert rt.started is True
    assert rt.stopped is True


def test_status_returns_the_state_snapshot(client_and_runtime) -> None:
    client, _ = client_and_runtime
    body = client.get("/api/status").json()
    assert body["mode"] == "IDLE"
    assert body["model"] == "yolo11s"
    assert len(body["models"]) == 2


def test_control_applies_a_manual_intent(client_and_runtime) -> None:
    client, rt = client_and_runtime
    r = client.post("/api/control", json={"action": "forward", "value": 0.5})
    assert r.json() == {"ok": True}
    assert rt.controller.manual.v_fwd == 0.5


def test_control_rejects_an_unknown_action(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/control", json={"action": "teleport", "value": 1.0})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_action"


def test_mode_switch_succeeds(client_and_runtime) -> None:
    client, rt = client_and_runtime
    r = client.post("/api/mode", json={"mode": "manual"})
    assert r.json() == {"ok": True, "mode": "MANUAL"}
    assert rt.controller.mode.value == "MANUAL"


def test_mode_switch_blocked_while_estopped(client_and_runtime) -> None:
    client, _ = client_and_runtime
    client.post("/api/estop")
    r = client.post("/api/mode", json={"mode": "MANUAL"})
    assert r.status_code == 409
    assert r.json()["code"] == "estopped"


def test_estop_then_reset(client_and_runtime) -> None:
    client, rt = client_and_runtime
    client.post("/api/estop")
    assert rt.controller.estopped is True
    client.post("/api/reset")
    assert rt.controller.estopped is False


def test_models_list(client_and_runtime) -> None:
    client, _ = client_and_runtime
    body = client.get("/api/models").json()
    assert body["active"] == "yolo11s"
    assert {m["id"] for m in body["models"]} == {"yolo11s", "rtdetr-l"}


def test_select_known_model(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/models/select", json={"id": "rtdetr-l"})
    assert r.json()["ok"] is True


def test_select_unknown_model_is_404(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/models/select", json={"id": "ghost"})
    assert r.status_code == 404
    assert r.json()["code"] == "unknown_model"


def test_camera_connect(client_and_runtime) -> None:
    client, rt = client_and_runtime
    r = client.post("/api/camera/connect", json={"spec": "0"})
    assert r.json()["ok"] is True
    assert rt.camera == "0"


def test_robot_connect_reports_bridge_class(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/robot/connect", json={"connection": "bt", "target": "/dev/cu.HC-05"})
    body = r.json()
    assert body["bridge"] == "DummyBridge"
    assert body["connected"] is False  # honest: a dummy fallback is not "connected"


def test_eval_run_starts_and_rejects_a_second_run(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/eval/run", json={"source": "data/raw/how_far"})
    assert r.json() == {"ok": True, "state": "running"}
    busy = client.post("/api/eval/run", json={"source": "data/raw/how_far"})
    assert busy.status_code == 409
    assert busy.json()["code"] == "eval_busy"


def test_eval_run_rejects_empty_source(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/eval/run", json={"source": ""})
    assert r.status_code == 400
    assert r.json()["code"] == "eval_bad_source"


def test_eval_status_reports_state(client_and_runtime) -> None:
    client, _ = client_and_runtime
    assert client.get("/api/eval/status").json()["state"] == "idle"
    client.post("/api/eval/run", json={"source": "data/raw/how_far"})
    assert client.get("/api/eval/status").json()["state"] == "running"


def test_eval_report_404_until_done_then_returns_payload(client_and_runtime) -> None:
    client, rt = client_and_runtime
    assert client.get("/api/eval/report").status_code == 404
    assert client.get("/api/eval/report").json()["code"] == "eval_not_ready"
    rt._eval_result = {"markdown": "# report", "metrics": {"fps": {"mean_fps": 30.0}}}
    body = client.get("/api/eval/report").json()
    assert body["ok"] is True
    assert body["markdown"] == "# report"


def test_robot_discover_returns_a_list(client_and_runtime) -> None:
    client, _ = client_and_runtime
    body = client.get("/api/robot/discover").json()
    assert body["ok"] is True
    assert isinstance(body["serial"], list)


def _wait_until_controller(ws) -> None:
    """Claim the token and block until telemetry confirms the server processed it
    (removes the two-connection ordering race)."""
    ws.send_json({"type": "claim"})
    for _ in range(100):
        msg = ws.receive_json()
        if msg.get("type") == "telemetry" and msg.get("you_are_controller"):
            return
    raise AssertionError("never became controller")


def test_ws_estop_works_from_an_observer(client_and_runtime) -> None:
    # The 2nd connection is an observer, but E-stop is NEVER gated by the token —
    # the observer must still be able to stop the robot.
    client, rt = client_and_runtime
    with client.websocket_connect("/ws") as holder:
        holder.receive_json()
        _wait_until_controller(holder)
        with client.websocket_connect("/ws") as observer:
            observer.receive_json()
            observer.send_json({"type": "estop"})
            for _ in range(100):
                if observer.receive_json().get("estop"):
                    break
            assert rt.controller.estopped is True


def test_ws_observer_drive_intent_is_nacked(client_and_runtime) -> None:
    client, rt = client_and_runtime
    with client.websocket_connect("/ws") as holder:
        holder.receive_json()
        _wait_until_controller(holder)
        with client.websocket_connect("/ws") as observer:
            observer.receive_json()
            observer.send_json({"type": "intent", "action": "left", "value": 1.0})
            nack = None
            for _ in range(100):
                m = observer.receive_json()
                if m.get("type") == "nack":
                    nack = m
                    break
            assert nack is not None and nack["code"] == "observer"


def test_mjpeg_chunk_framing() -> None:
    # Test the framing contract directly — an infinite StreamingResponse deadlocks
    # TestClient teardown, so we unit-test the pure framing + assert the route exists.
    jpeg = b"\xff\xd8\xff\xe0body\xff\xd9"
    chunk = _mjpeg_chunk(jpeg)
    assert chunk.startswith(b"--frame\r\n")
    assert b"Content-Type: image/jpeg\r\n" in chunk
    assert f"Content-Length: {len(jpeg)}".encode() in chunk
    assert chunk.endswith(jpeg + b"\r\n")


def test_video_route_is_registered(client_and_runtime) -> None:
    client, _ = client_and_runtime
    paths = {getattr(r, "path", None) for r in client.app.routes}
    assert "/video" in paths


def test_ws_pushes_telemetry_and_accepts_heartbeat(client_and_runtime) -> None:
    client, _ = client_and_runtime
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "telemetry"
        assert msg["mode"] == "IDLE"
        ws.send_json({"type": "heartbeat"})


# --------------------------------------------------------- camera profile / PTZ
def test_camera_connect_passes_profile(client_and_runtime) -> None:
    client, rt = client_and_runtime
    r = client.post("/api/camera/connect", json={"spec": "rtsp://h/s", "camera": "tapo_c211"})
    assert r.json()["ok"] is True
    assert rt.camera_profile == "tapo_c211"


def test_ptz_without_tapo_is_409(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/camera/ptz", json={"pan": 0.5, "tilt": 0.0})
    assert r.status_code == 409
    assert r.json()["code"] == "ptz_no_camera"
    rp = client.post("/api/camera/ptz/preset", json={"name": "home"})
    assert rp.status_code == 409


# ------------------------------------------------------------- training routes
def test_train_readiness(client_and_runtime) -> None:
    client, _ = client_and_runtime
    body = client.get("/api/train/readiness").json()
    assert body["ok"] is True and body["idle"] is True


def test_train_run_and_busy(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/train/run", json={"kind": "train"})
    assert r.json()["ok"] is True and r.json()["state"] == "running"
    busy = client.post("/api/train/run", json={"kind": "train"})
    assert busy.status_code == 409 and busy.json()["code"] == "train_busy"


def test_train_run_bad_kind(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/train/run", json={"kind": "frobnicate"})
    assert r.status_code == 400 and r.json()["code"] == "train_bad_kind"


def test_train_run_refused_when_not_idle(client_and_runtime) -> None:
    client, _ = client_and_runtime
    client.post("/api/mode", json={"mode": "MANUAL"})
    r = client.post("/api/train/run", json={"kind": "train"})
    assert r.status_code == 409 and r.json()["code"] == "train_not_idle"


def test_train_blocks_eval_and_vice_versa(client_and_runtime) -> None:
    client, _ = client_and_runtime
    client.post("/api/train/run", json={"kind": "train"})
    # eval refused while training holds the heavy-job slot
    r = client.post("/api/eval/run", json={"source": "data/raw/how_far"})
    assert r.status_code == 409 and r.json()["code"] == "heavy_job_busy"


def test_mode_switch_blocked_while_training(client_and_runtime) -> None:
    # T1: a drive switch is refused (not silently cancelling training).
    client, _ = client_and_runtime
    client.post("/api/train/run", json={"kind": "train"})
    r = client.post("/api/mode", json={"mode": "MANUAL"})
    assert r.status_code == 409 and r.json()["code"] == "train_active"


def test_train_cancel_then_can_drive(client_and_runtime) -> None:
    client, _ = client_and_runtime
    client.post("/api/train/run", json={"kind": "train"})
    assert client.post("/api/train/cancel").json()["cancelled"] is True
    assert client.post("/api/mode", json={"mode": "MANUAL"}).json()["ok"] is True


def test_train_history_route(client_and_runtime) -> None:
    client, _ = client_and_runtime
    body = client.get("/api/train/history").json()
    assert body["ok"] is True and isinstance(body["runs"], list)


def test_promote_without_winner_is_409(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/train/promote", json={})
    assert r.status_code == 409 and r.json()["code"] == "promote_no_winner"


def test_promote_with_weights(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/train/promote", json={"weights": "runs/train/best.pt"})
    assert r.json()["ok"] is True and r.json()["model_id"] == "cats-finetuned"


def test_promote_with_run_dir(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.post("/api/train/promote", json={"run_dir": "20260607-web-train"})
    assert r.json()["ok"] is True
    assert r.json()["weights"].endswith("/best.pt")
