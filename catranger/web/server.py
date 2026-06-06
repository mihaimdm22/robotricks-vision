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
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from catranger.web.arbiter import ControlArbiter

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


class EvalRun(BaseModel):
    source: str  # image dir | image | video | rtsp url (NOT a webcam index)
    approach: str = "A"  # A=YOLO11, B=RT-DETR
    classes: str | None = None  # 'all' | comma-sep COCO ids
    max_frames: int = 0  # 0 = all
    use_depth: bool = False  # off by default: faster on a CPU demo box


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

    # The Next.js console is a separate origin (e.g. http://localhost:3000), so the
    # browser's fetch() to /api/* needs CORS. Origins live in configs/web.yaml
    # (numbers/strings in YAML, never hard-coded); empty list = same-origin only.
    cfg = getattr(runtime, "cfg", {}) or {}
    cors_origins = list(cfg.get("cors_origins", []) or [])
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # M5: single-controller drive token (one operator drives; others observe).
    arbiter = ControlArbiter(idle_timeout_s=float(cfg.get("control_idle_timeout_s", 8.0)))
    app.state.arbiter = arbiter

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
            )
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
            )
        if not ok:
            return _err(
                "estopped",
                "mode change refused: E-stop is latched",
                "the robot is in a latched emergency stop",
                "press RESET/ARM to clear the E-stop, then switch mode",
                status=409,
            )
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
            )

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

    @app.get("/api/robot/discover")
    async def robot_discover() -> dict:
        # serial port enumeration / BLE probe can block — keep it off the loop.
        return await run_in_threadpool(runtime.discover_devices)

    # ------------------------------------------------------------------ eval
    @app.post("/api/eval/run")
    def eval_run(req: EvalRun) -> JSONResponse:
        res = runtime.start_eval(req.model_dump())
        if not res.get("ok"):
            status = int(res.pop("status", 400))
            return JSONResponse(res, status_code=status)
        return JSONResponse(res)

    @app.get("/api/eval/status")
    def eval_status() -> dict:
        return runtime.eval_status()

    @app.get("/api/eval/report")
    def eval_report() -> JSONResponse:
        result = runtime.eval_result()
        if result is None:
            return _err(
                "eval_not_ready",
                "no finished eval report yet",
                "no eval run has completed since the server started",
                "POST /api/eval/run, poll /api/eval/status until state=done",
                status=404,
            )
        return JSONResponse({"ok": True, **result})

    @app.post("/api/eval/cancel")
    def eval_cancel() -> dict:
        return runtime.cancel_eval()

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
        cid = arbiter.connect()

        async def push_telemetry() -> None:
            # Telemetry is per-connection: the same robot state, but each client is
            # told whether IT holds the drive token (you_are_controller).
            while True:
                await websocket.send_json(
                    {
                        "type": "telemetry",
                        **runtime.telemetry(),
                        "you_are_controller": arbiter.is_holder(cid),
                        "controller_id": arbiter.holder,
                    }
                )
                await asyncio.sleep(1.0 / hz)

        async def nack(code: str, problem: str, fix: str) -> None:
            await websocket.send_json(
                {"type": "nack", "code": code, "problem": problem, "fix": fix}
            )

        sender = asyncio.create_task(push_telemetry())
        try:
            while True:
                msg = await websocket.receive_json()
                kind = msg.get("type")

                # SAFETY: E-stop and reset are NEVER gated by the token. Any client,
                # holder or observer, can stop the robot. Checked first, on purpose.
                if kind == "estop":
                    runtime.estop()
                    continue
                if kind == "reset":
                    runtime.reset()
                    continue

                if kind in ("claim", "claim_control", "request_control"):
                    arbiter.claim(cid)
                    continue

                if kind == "heartbeat":
                    arbiter.heartbeat(cid)  # keep the token lease alive
                    if arbiter.is_holder(cid):
                        runtime.heartbeat()  # refresh the MANUAL watchdog
                    continue

                # Drive + mode require the token (auto-claimed if it's free).
                if kind in ("intent", "mode"):
                    if not arbiter.note_intent(cid):
                        await nack(
                            "observer",
                            "another operator holds control",
                            "press 'Request control' to take over",
                        )
                        continue
                    if kind == "intent":
                        try:
                            runtime.set_manual(
                                msg.get("action", "stop"), float(msg.get("value", 0.0))
                            )
                        except (ValueError, TypeError):
                            pass
                    else:  # mode
                        runtime.set_mode(str(msg.get("mode", "IDLE")).upper())
        except WebSocketDisconnect:
            pass
        finally:
            arbiter.disconnect(cid)
            sender.cancel()

    return app
