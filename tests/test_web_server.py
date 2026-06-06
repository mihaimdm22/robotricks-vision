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

    def connect_camera(self, spec: str) -> dict:
        self.camera = spec
        return {"ok": True, "label": spec, "warning": None}

    def connect_robot(self, connection: str, target: str | None = None, baud: int = 115200) -> dict:
        self.robot = f"{connection}:{target}" if target else connection
        return {"ok": True, "bridge": "DummyBridge", "connected": False, "warning": None}


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


def test_eval_route_is_a_501_stub(client_and_runtime) -> None:
    client, _ = client_and_runtime
    r = client.get("/api/eval")
    assert r.status_code == 501
    assert r.json()["code"] == "not_implemented"


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
