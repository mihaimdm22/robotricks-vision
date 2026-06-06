"""FastAPI control plane: REST intents + one telemetry/control WebSocket + an
MJPEG video stream, serving the static panel.

`create_app(runtime)` takes the runtime as a dependency so tests inject a fake
(no threads, no hardware) and exercise every route contract. Production builds a
real RobotRuntime via `catranger serve`.

Design choices from the review: errors are typed {ok, code, problem, cause, fix}
(never a stack trace to the operator); the MJPEG response coalesces on the latest
published frame (slow clients skip, never backpressure the loop); the WS pushes
telemetry on a timer and accepts intent/heartbeat/mode/estop.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_STATIC = Path(__file__).resolve().parent / "static"
_BOUNDARY = "frame"


# --------------------------------------------------------------------- schemas
class ControlIntent(BaseModel):
    action: str  # forward|back|left|right|pan|stop
    value: float = 0.0


class ModeIntent(BaseModel):
    mode: str  # IDLE|MANUAL|FOLLOW


class ModelSelect(BaseModel):
    id: str


class CameraConnect(BaseModel):
    spec: str  # "synthetic" | webcam index | rtsp url | file path


class RobotConnect(BaseModel):
    connection: str = "dummy"  # dummy|usb|bt|ble
    target: str | None = None
    baud: int = 115200


def _err(code: str, problem: str, cause: str, fix: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "code": code, "problem": problem, "cause": cause, "fix": fix},
        status_code=status,
    )


def _mjpeg_chunk(jpeg: bytes, boundary: str = _BOUNDARY) -> bytes:
    """One multipart/x-mixed-replace part: boundary + headers + jpeg. Includes
    Content-Length (some browsers are flaky on reconnect without it)."""
    return (
        f"--{boundary}\r\n".encode()
        + b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
        + jpeg
        + b"\r\n"
    )


def create_app(runtime: Any) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="CatRanger Control", lifespan=lifespan)
    app.state.runtime = runtime

    # ----------------------------------------------------------------- pages
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    if _STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    # ------------------------------------------------------------------ REST
    @app.get("/api/status")
    def status() -> dict:
        return runtime.status()

    @app.post("/api/control")
    def control(intent: ControlIntent) -> dict:
        try:
            runtime.set_manual(intent.action, intent.value)
        except ValueError as exc:
            return _err(
                "bad_action",
                str(exc),
                "the client sent an unrecognized drive action",
                "use one of: forward, back, left, right, pan, stop",
            )  # type: ignore[return-value]
        return {"ok": True}

    @app.post("/api/mode")
    def mode(intent: ModeIntent) -> dict:
        try:
            target = intent.mode.upper()
            ok = runtime.set_mode(target)
        except ValueError:
            return _err(
                "bad_mode",
                f"unknown mode {intent.mode!r}",
                "mode must be IDLE, MANUAL, or FOLLOW",
                "send one of IDLE|MANUAL|FOLLOW",
            )  # type: ignore[return-value]
        if not ok:
            return _err(
                "estopped",
                "mode change refused: E-stop is latched",
                "the robot is in a latched emergency stop",
                "press RESET/ARM to clear the E-stop, then switch mode",
                status=409,
            )  # type: ignore[return-value]
        return {"ok": True, "mode": target}

    @app.post("/api/estop")
    def estop() -> dict:
        runtime.estop()
        return {"ok": True, "estop": True}

    @app.post("/api/reset")
    def reset() -> dict:
        runtime.reset()
        return {"ok": True, "estop": False}

    @app.get("/api/models")
    def models() -> dict:
        s = runtime.status()
        return {"models": s["models"], "active": s["model"], "status": s["model_status"]}

    @app.post("/api/models/select")
    def select_model(sel: ModelSelect) -> dict:
        try:
            return runtime.select_model(sel.id)
        except KeyError:
            return _err(
                "unknown_model",
                f"no model with id {sel.id!r}",
                "the id is not in configs/models.yaml",
                "GET /api/models for valid ids, or add it to configs/models.yaml",
                status=404,
            )  # type: ignore[return-value]

    @app.post("/api/camera/connect")
    def camera_connect(req: CameraConnect) -> dict:
        return runtime.connect_camera(req.spec)

    @app.post("/api/camera/disconnect")
    def camera_disconnect() -> dict:
        return runtime.connect_camera("synthetic")

    @app.post("/api/robot/connect")
    def robot_connect(req: RobotConnect) -> dict:
        return runtime.connect_robot(req.connection, req.target, req.baud)

    @app.post("/api/robot/disconnect")
    def robot_disconnect() -> dict:
        return runtime.connect_robot("dummy")

    @app.get("/api/eval")
    def eval_stub() -> JSONResponse:
        return JSONResponse(
            {
                "ok": False,
                "code": "not_implemented",
                "problem": "the eval tab is not built yet",
                "cause": "reserved seam — eval lands in a follow-up milestone",
                "fix": "use `make eval` (catranger/eval) from the CLI for now",
            },
            status_code=501,
        )

    @app.get("/api/history")
    def history(limit: int = 600, since: float | None = None) -> dict:
        """Recorded distance samples (model estimate + CI vs HC-SR04) over time,
        for the live history chart. Empty when no store is attached (test fakes)."""
        store = getattr(runtime, "store", None)
        if store is None:
            return {"samples": []}
        return {"samples": store.recent(limit=limit, since=since)}

    # ----------------------------------------------------------------- video
    @app.get("/video")
    async def video(request: Request) -> StreamingResponse:
        # async generator (not a threadpool sync gen): it checks client disconnect
        # and awaits sleep, so it cancels cleanly when the browser tab closes —
        # no per-client thread is left spinning.
        async def frames():
            while not await request.is_disconnected():
                jpeg = runtime.latest_jpeg()
                if jpeg is None:
                    await asyncio.sleep(0.05)
                    continue
                yield _mjpeg_chunk(jpeg)
                await asyncio.sleep(0.05)

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
            headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
        )

    @app.get("/healthz")
    def healthz() -> Response:
        return Response(status_code=204)

    # -------------------------------------------------------------------- WS
    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        hz = float(getattr(runtime, "fps_cap", 15)) or 15.0

        async def push_telemetry() -> None:
            while True:
                await websocket.send_json({"type": "telemetry", **runtime.telemetry()})
                await asyncio.sleep(1.0 / hz)

        sender = asyncio.create_task(push_telemetry())
        try:
            while True:
                msg = await websocket.receive_json()
                kind = msg.get("type")
                if kind == "intent":
                    try:
                        runtime.set_manual(msg.get("action", "stop"), float(msg.get("value", 0.0)))
                    except (ValueError, TypeError):
                        pass
                elif kind == "heartbeat":
                    runtime.heartbeat()
                elif kind == "mode":
                    runtime.set_mode(str(msg.get("mode", "IDLE")).upper())
                elif kind == "estop":
                    runtime.estop()
                elif kind == "reset":
                    runtime.reset()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()

    return app
