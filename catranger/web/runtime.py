"""RobotRuntime: wires the pure RobotController to the real world.

Owns the single background control thread (the SOLE writer to the bridge), the
frame source, perception (a real CatRanger when the `ml` extra is installed, a
passthrough otherwise so the panel still streams video + drives by hand), JPEG
publication for the MJPEG endpoint, and device/model management.

Per tick: read frame -> perceive -> controller.apply(result) -> draw+encode ->
publish. The controller decides + sends; the runtime does all the I/O (cv2, torch,
serial). This is the integration edge (omitted from unit coverage); behavior is
guarded by the server route tests + the `web` CI leg.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import time
from typing import Any

import numpy as np

from catranger.types import Command, FrameResult
from catranger.web.controller import Mode, RobotController, StopReason
from catranger.web.registry import ModelProfile, ModelRegistry


def _ml_available() -> bool:
    return (
        importlib.util.find_spec("ultralytics") is not None
        and importlib.util.find_spec("torch") is not None
    )


class RobotRuntime:
    def __init__(self, web_cfg: dict | None = None, *, app_config: str = "cat_distance") -> None:
        cfg = web_cfg or {}
        self.cfg = cfg
        self.fps_cap = float(cfg.get("fps_cap", 15))
        self.jpeg_quality = int(cfg.get("jpeg_quality", 80))
        self.width = int(cfg.get("width", 960))
        self.height = int(cfg.get("height", 540))
        self.app_config = app_config

        self.controller = RobotController(
            watchdog_timeout_s=float(cfg.get("watchdog_timeout_s", 0.5)),
            safe_stop_cm=int(cfg.get("safe_stop_cm", 20)),
        )
        self.registry = ModelRegistry.from_yaml(cfg.get("models_config", "configs/models.yaml"))
        self.active_model: ModelProfile = self.registry.default
        self.model_status = "idle"
        self.model_error: str | None = None
        self.perception_available = _ml_available()

        self._app: Any = None  # lazy AppConfig (needs yaml only)
        self._ranger: Any = None  # CatRanger when ml present
        self._source: Any = None
        self.camera_spec = str(cfg.get("default_camera", "synthetic"))
        self.robot_desc = "dummy"

        self._jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        self._last_frame_ts = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.connect_robot(str(self.cfg.get("default_robot", "dummy")))
        self.connect_camera(self.camera_spec)
        self.select_model(self.active_model.id)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="control-loop", daemon=True)
        self._thread.start()
        mode = str(self.cfg.get("default_mode", "IDLE"))
        if mode != "IDLE":
            self.controller.set_mode(Mode(mode))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.controller.shutdown()
        if self._source is not None:
            try:
                self._source.close()
            except Exception:
                pass

    # ------------------------------------------------------------- the loop
    def _run(self) -> None:
        interval = 1.0 / self.fps_cap if self.fps_cap > 0 else 0.0
        idx = 0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            frame = self._source.read() if self._source is not None else None
            if frame is None:
                self.controller.camera_connected = False
                self.controller.apply(None, frame_index=idx)
            else:
                self.controller.camera_connected = True
                self._last_frame_ts = time.perf_counter()
                result, draw_frame = self._perceive(frame, idx)
                cmd = self.controller.apply(result, frame_index=idx)
                self._publish(self._encode(draw_frame, result, cmd))
            idx += 1
            self._pace(interval, t0)

    def _pace(self, interval: float, t0: float) -> None:
        if interval <= 0:
            return
        dt = time.perf_counter() - t0
        if dt < interval:
            self._stop.wait(interval - dt)

    def _perceive(self, frame: np.ndarray, idx: int) -> tuple[FrameResult, np.ndarray]:
        if self._ranger is not None:
            try:
                result = self._ranger.process(frame, idx)
                draw_frame = getattr(self._ranger, "last_undistorted", frame)
                if self.model_status != "ready":
                    self.model_status = "ready"
                    self.model_error = None
                return result, draw_frame
            except Exception as exc:
                # A per-frame inference error is NOT "ml missing". Surface the real
                # reason, fall back to passthrough so the MJPEG stream survives, but
                # leave perception_available (ml-installed) intact so the operator can
                # re-select/retry — never silently swallow it or claim the extra is absent.
                logging.getLogger("catranger.web").warning("perception error: %s", exc)
                self.model_status = "error"
                self.model_error = f"{type(exc).__name__}: {exc}"
                self._ranger = None
        h, w = frame.shape[:2]
        return FrameResult(frame_index=idx, width=int(w), height=int(h)), frame

    def _encode(self, frame: np.ndarray, result: FrameResult, cmd: Command) -> bytes | None:
        import cv2

        from catranger.viz import draw

        try:
            annotated = draw(frame, result, cmd)
        except Exception:
            annotated = frame
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        return buf.tobytes() if ok else None

    def _publish(self, jpeg: bytes | None) -> None:
        if jpeg is None:
            return
        with self._jpeg_lock:
            self._jpeg = jpeg

    # ------------------------------------------------------------- readers
    def latest_jpeg(self) -> bytes | None:
        with self._jpeg_lock:
            return self._jpeg

    def telemetry(self) -> dict:
        t = dict(self.controller.latest_telemetry)
        age_ms = (
            (time.perf_counter() - self._last_frame_ts) * 1000.0 if self._last_frame_ts else None
        )
        t.update(
            {
                "model": self.active_model.id,
                "model_name": self.active_model.name,
                "model_status": self.model_status,
                "model_error": self.model_error,
                "perception_available": self.perception_available,
                "camera": self.camera_spec,
                "robot": self.robot_desc,
                "frame_age_ms": round(age_ms, 1) if age_ms is not None else None,
                "watchdog_timeout_s": self.controller.watchdog_timeout_s,
                "safe_stop_cm": self.controller.safe_stop_cm,
                "video_stale_ms": int(self.cfg.get("video_stale_ms", 1000)),
            }
        )
        return t

    def status(self) -> dict:
        return {
            "mode": self.controller.mode.value,
            "estop": self.controller.estopped,
            "stop_reason": self.controller.stop_reason.value,
            "robot_connected": self.controller.robot_connected,
            "camera_connected": self.controller.camera_connected,
            "robot": self.robot_desc,
            "camera": self.camera_spec,
            "model": self.active_model.id,
            "model_status": self.model_status,
            "model_error": self.model_error,
            "perception_available": self.perception_available,
            "models": [
                {"id": m.id, "name": m.name, "backend": m.backend, "dataset": m.dataset}
                for m in self.registry.list()
            ],
        }

    # ------------------------------------------------------------- devices
    def connect_camera(self, spec: str) -> dict:
        from catranger.web.sources import open_source

        old = self._source
        self._source = open_source(spec, width=self.width, height=self.height)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        # report the REAL source (e.g. "synthetic" on fallback), never the requested
        # spec — so the operator is never told a camera connected when it didn't.
        self.camera_spec = self._source.label
        fell_back = self._source.label == "synthetic" and spec not in ("synthetic", "")
        return {
            "ok": True,
            "label": self._source.label,
            "warning": "camera unavailable — using synthetic source" if fell_back else None,
        }

    def connect_robot(self, connection: str, target: str | None = None, baud: int = 115200) -> dict:
        from catranger.hw.bluetooth import open_link

        bridge = open_link(connection, target, baud=baud)
        self.controller.attach(bridge=bridge)
        cls = type(bridge).__name__
        self.robot_desc = f"{connection}:{target}" if target else connection
        # open_link silently degrades to DummyBridge if a transport is unavailable —
        # surface that as a warning, never a green "connected" (DX review).
        wanted_real = connection not in ("dummy", "") and target is not None
        fell_back = wanted_real and cls == "DummyBridge"
        return {
            "ok": True,
            "bridge": cls,
            "connected": self.controller.robot_connected,
            "warning": "robot link unavailable — running in simulation (DummyBridge)"
            if fell_back
            else None,
        }

    # ------------------------------------------------------------- models
    def select_model(self, model_id: str) -> dict:
        profile = self.registry.get(model_id)  # raises KeyError on unknown
        if not self.perception_available:
            # No ml extra: record the selection for display; perception stays off.
            self.active_model = profile
            self.model_status = "unavailable"
            return {
                "ok": True,
                "model": profile.id,
                "status": "unavailable",
                "warning": "perception requires the ml extra: uv sync --extra ml",
            }
        # IDLE + zero before swapping; restore mode only on success (eng review A7).
        prev_mode = self.controller.mode
        self.controller.set_mode(Mode.IDLE)
        self.model_status = "loading"
        try:
            new_ranger = self._build_ranger(profile)
        except Exception as exc:  # keep the old model live; never null it
            self.model_status = "error"
            if not self.controller.estopped:
                self.controller.set_mode(prev_mode)
            return {"ok": False, "code": "model_load_failed", "problem": str(exc)}
        self._ranger = new_ranger
        self.active_model = profile
        self.controller.follower.reset()
        self.model_status = "ready"
        if not self.controller.estopped:
            self.controller.set_mode(prev_mode)
        return {"ok": True, "model": profile.id, "status": "ready"}

    def _build_ranger(self, profile: ModelProfile) -> Any:
        from catranger.config import load_app
        from catranger.pipeline import CatRanger

        if self._app is None:
            self._app = load_app(self.app_config)
        app = self._app
        det = dict(app.raw.get("detector", {}) or {})
        det.pop("finetuned_weights", None)  # the profile's weights win
        det["_web"] = {"backend": profile.backend, "weights": profile.weights}
        app.raw["detector"] = det
        if profile.classes is not None:
            app.raw["classes"] = profile.classes
        if profile.tracker:
            tracker = dict(app.raw.get("tracker", {}) or {})
            tracker["name"] = profile.tracker
            app.raw["tracker"] = tracker
        return CatRanger(app, approach="_web", use_depth=False)

    # one-shot estop/reset proxies so the server never reaches past this facade
    def estop(self) -> None:
        self.controller.estop()

    def reset(self) -> None:
        self.controller.reset()

    def set_mode(self, mode: str) -> bool:
        return self.controller.set_mode(Mode(mode))

    def set_manual(self, action: str, value: float = 0.0) -> None:
        self.controller.set_manual(action, value)

    def heartbeat(self) -> None:
        self.controller.heartbeat()

    @property
    def stop_reason(self) -> StopReason:
        return self.controller.stop_reason
