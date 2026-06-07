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
from pathlib import Path
from typing import Any

import numpy as np

from catranger.types import Command, FrameResult
from catranger.web.controller import Mode, RobotController, StopReason
from catranger.web.eval_job import EvalJob
from catranger.web.registry import ModelProfile, ModelRegistry
from catranger.web.store import DistanceStore
from catranger.web.train_job import TrainJob

# Repo root, so runs/ paths resolve correctly no matter the server's CWD
# (`catranger serve` does not chdir here; archives live under the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _ml_available() -> bool:
    return (
        importlib.util.find_spec("ultralytics") is not None
        and importlib.util.find_spec("torch") is not None
    )


def _is_stream_spec(spec: str) -> bool:
    """True for rtsp/http(s) URLs — checked without importing the heavy io module."""
    return "://" in spec


def _redact_spec(spec: str) -> str:
    """Hide credentials in a 'scheme://user:pass@host...' spec for display/telemetry/
    logs. The Tapo rtsp URL embeds the Camera Account password; it must never leak
    into a telemetry frame or a log line (DX review)."""
    if "://" not in spec:
        return spec
    scheme, _, rest = spec.partition("://")
    if "@" in rest:
        rest = "***@" + rest.split("@", 1)[1]
    return f"{scheme}://{rest}"


def _parse_rtsp(spec: str) -> tuple[str, str, str, str]:
    """(host, user, pwd, stream) from rtsp://user:pass@host:port/stream. Used to
    build a TapoCamera PTZ handle from the live source spec (creds stay in memory)."""
    body = spec.split("://", 1)[-1]
    creds, sep, hostpart = body.partition("@")
    if not sep:  # no credentials in the URL
        hostpart, creds = creds, ""
    user, _, pwd = creds.partition(":")
    host = hostpart.split("/", 1)[0].split(":", 1)[0]
    stream = hostpart.split("/", 1)[1] if "/" in hostpart else "stream1"
    return host, user, pwd, stream


def _eval_err(code: str, problem: str, cause: str, fix: str, status: int = 400) -> dict:
    """Typed eval error mirroring the server's {ok, code, problem, cause, fix}
    shape; `status` is carried so the route can map it to an HTTP code."""
    return {
        "ok": False,
        "code": code,
        "problem": problem,
        "cause": cause,
        "fix": fix,
        "status": status,
    }


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
        self._models_config = str(cfg.get("models_config", "configs/models.yaml"))
        self.registry = ModelRegistry.from_yaml(self._models_config)
        self.active_model: ModelProfile = self.registry.default
        self.model_status = "idle"
        self.model_error: str | None = None
        self.perception_available = _ml_available()

        self._ranger: Any = None  # CatRanger when ml present
        self._source: Any = None
        _default_cam = str(cfg.get("default_camera", "synthetic"))
        self._raw_camera_spec = _default_cam  # real spec (may carry rtsp creds) — never displayed
        self.camera_spec = _redact_spec(_default_cam)  # redacted, safe for telemetry/status
        # Camera intrinsics profile: None => the app's default (go2_1080p). Selecting
        # tapo_c211 re-anchors distance (the Tapo's fx/fy differ from the Go2's).
        self.camera_profile: str | None = None
        self.camera_calibrated = True  # go2 is calibrated; tapo placeholder is not
        # Tapo PTZ handle (built only when a tapo_c211 rtsp source is connected).
        self._tapo: Any = None
        self._tapo_lock = threading.Lock()
        self._last_ptz_ts = 0.0
        self._ptz_min_interval = float(cfg.get("ptz_min_interval_s", 0.3))
        self.robot_desc = "dummy"

        self._jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        # Guards self._source against the control thread reading it while a REST
        # handler thread (connect_camera) swaps + closes it.
        self._source_lock = threading.Lock()
        self._last_frame_ts = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # distance history (sqlite) + the live chart's latest CI band
        self.store = DistanceStore(str(cfg.get("history_db", "outputs/history.sqlite3")))
        self._history_interval = 1.0 / float(cfg.get("history_hz", 4) or 4)
        self._last_record_ts = 0.0
        self._last_dist: tuple[float | None, float | None, float | None] = (None, None, None)

        # M3: one background eval job, started/polled from the Eval tab.
        self.eval_job = EvalJob()
        # CV/Training tab: one background training job (subprocess). Eval and train
        # are mutually exclusive — both saturate CPU/GPU (shared heavy-job slot).
        self.train_job = TrainJob()
        # One real lock guards the eval/train check-and-start so two concurrent
        # requests can't both pass their "is the other running?" check (TOCTOU).
        self._heavy_lock = threading.Lock()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.connect_robot(str(self.cfg.get("default_robot", "dummy")))
        # use the RAW spec (camera_spec is redacted — would connect with ***).
        self.connect_camera(self._raw_camera_spec)
        self.select_model(self.active_model.id)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="control-loop", daemon=True)
        self._thread.start()
        mode = str(self.cfg.get("default_mode", "IDLE"))
        if mode != "IDLE":
            self.controller.set_mode(Mode(mode))

    def stop(self) -> None:
        self._stop.set()
        self.train_job.request_stop()  # don't leave a training subprocess orphaned
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.controller.shutdown()
        if self._source is not None:
            try:
                self._source.close()
            except Exception:
                pass
        self.store.close()

    # ------------------------------------------------------------- the loop
    def _run(self) -> None:
        interval = 1.0 / self.fps_cap if self.fps_cap > 0 else 0.0
        idx = 0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                with self._source_lock:
                    frame = self._source.read() if self._source is not None else None
                if frame is None:
                    self.controller.camera_connected = False
                    self.controller.apply(None, frame_index=idx)
                    self._last_dist = (None, None, None)
                else:
                    self.controller.camera_connected = True
                    self._last_frame_ts = time.perf_counter()
                    result, draw_frame = self._perceive(frame, idx)
                    cmd = self.controller.apply(result, frame_index=idx)
                    self._publish(self._encode(draw_frame, result, cmd))
                    self._observe(result)
            except Exception:
                # The control thread is the SOLE writer to the robot — a transient
                # tick error (camera mid-swap, a bad frame, a history-store write)
                # must never kill it.
                logging.getLogger("catranger.web").exception("control loop tick failed")
            idx += 1
            self._pace(interval, t0)

    def _observe(self, result: FrameResult) -> None:
        """Cache the target's distance + CI for telemetry, and append a throttled
        sample to the history store (model estimate vs HC-SR04 truth over time)."""
        est = lo = hi = None
        target_id = None
        tgt = result.target
        if tgt is not None:
            target_id = tgt.track_id
            d = tgt.distance
            if d is not None and np.isfinite(d.meters):
                est, lo, hi = round(d.meters, 3), round(d.lo, 3), round(d.hi, 3)
        self._last_dist = (est, lo, hi)
        if est is None:
            return
        now = time.perf_counter()
        if now - self._last_record_ts < self._history_interval:
            return
        self._last_record_ts = now
        gt = self.controller.latest_telemetry.get("gt_cm")
        gt_cm = float(gt) if isinstance(gt, (int, float)) and gt >= 0 else None
        self.store.record(
            ts=time.time(),
            est_m=est,
            lo=lo,
            hi=hi,
            gt_cm=gt_cm,
            target_id=target_id,
            mode=self.controller.mode.value,
        )

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
                "camera_profile": self.camera_profile,
                "camera_calibrated": self.camera_calibrated,
                "robot": self.robot_desc,
                "frame_age_ms": round(age_ms, 1) if age_ms is not None else None,
                "target_dist_lo": self._last_dist[1],
                "target_dist_hi": self._last_dist[2],
                "watchdog_timeout_s": self.controller.watchdog_timeout_s,
                "safe_stop_cm": self.controller.safe_stop_cm,
                "video_stale_ms": int(self.cfg.get("video_stale_ms", 1000)),
                # M3: surface (don't hide) that eval is competing for CPU/GPU.
                "eval_running": self.eval_job.running,
                # CV tab: same honesty for a training run (UI shows a warn pill).
                "train_running": self.train_job.running,
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
            "camera_profile": self.camera_profile,
            "camera_calibrated": self.camera_calibrated,
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
    def connect_camera(self, spec: str, camera: str | None = None) -> dict:
        from catranger.web.sources import open_source

        # Open the new source OUTSIDE the lock (it can be slow), then swap under
        # the lock so the control thread never reads a half-swapped/closed source.
        new = open_source(spec, width=self.width, height=self.height)
        with self._source_lock:
            old = self._source
            self._source = new
        if old is not None:
            try:
                old.close()  # safe now: the loop reads `new` on its next tick
            except Exception:
                pass
        # report the REAL source (e.g. "synthetic" on fallback), never the requested
        # spec — so the operator is never told a camera connected when it didn't.
        # Redact creds: the label carries the rtsp URL (with the Tapo password).
        self._raw_camera_spec = spec
        self.camera_spec = _redact_spec(new.label)
        fell_back = new.label == "synthetic" and spec not in ("synthetic", "")
        result: dict[str, Any] = {
            "ok": True,
            "label": self.camera_spec,
            "warning": self._diagnose_camera(spec) if fell_back else None,
        }
        # Optionally re-anchor distance intrinsics to a camera profile in the same
        # call (the Connections-tab dropdown). Without this, Tapo frames keep the
        # Go2 intrinsics and every distance is wrong by a constant (frozen rubric).
        if camera:
            re = self.reanchor_camera(camera)
            result["camera_profile"] = re.get("camera_profile")
            result["calibrated"] = re.get("calibrated")
            if re.get("warning") and not result["warning"]:
                result["warning"] = re.get("warning")
        else:
            result["camera_profile"] = self.camera_profile
            result["calibrated"] = self.camera_calibrated
        self._set_tapo_handle(spec, self.camera_profile)
        return result

    def _diagnose_camera(self, spec: str) -> str:
        """When a real camera fell back to synthetic, say WHY (DX review): for an
        rtsp source, distinguish 'host unreachable' from 'reached but refused'
        (almost always the missing Tapo Camera Account) so the operator knows what
        to fix — not a generic 'unavailable'."""
        if not spec.lower().startswith("rtsp://"):
            return "camera unavailable — using synthetic source"
        import socket

        body = spec.split("://", 1)[-1]
        if "@" in body:
            body = body.split("@", 1)[1]
        hostport = body.split("/", 1)[0]
        host = hostport.split(":", 1)[0]
        port = int(hostport.split(":", 1)[1]) if ":" in hostport else 554
        try:
            socket.create_connection((host, port), timeout=2.0).close()
        except OSError:
            return (
                f"cannot reach {host}:{port} — check the camera IP and that it is on "
                "this LAN (using synthetic for now)"
            )
        return (
            "reached the camera but RTSP was refused — set a Tapo Camera Account "
            "(Tapo app -> Advanced -> Camera Account), NOT your cloud login, and verify "
            "the stream path (using synthetic for now)"
        )

    def _set_tapo_handle(self, spec: str, profile: str | None) -> None:
        """Build (or clear) the TapoCamera PTZ handle. PTZ is only available when the
        active camera is a Tapo rtsp source — the runtime otherwise opens generic
        OpenCV and has no pan/tilt handle (Eng/DX review)."""
        self._tapo = None
        if profile == "tapo_c211" and spec.lower().startswith("rtsp://"):
            try:
                from catranger.hw.tapo import TapoCamera

                host, user, pwd, stream = _parse_rtsp(spec)
                if host:
                    self._tapo = TapoCamera(host, user, pwd, stream)
            except Exception:
                self._tapo = None

    # ------------------------------------------------------------------- PTZ
    def ptz_move(self, pan: float, tilt: float) -> dict:
        """Relative camera pan/tilt (pytapo, blocking — the server route runs this
        in a threadpool). Throttled to spare the motor controller."""
        if self._tapo is None:
            return _eval_err(
                "ptz_no_camera",
                "no Tapo camera connected for PTZ",
                "the active camera isn't a Tapo rtsp source (PTZ needs one)",
                "connect the Tapo rtsp URL and select the tapo_c211 profile",
                status=409,
            )
        now = time.monotonic()
        if now - self._last_ptz_ts < self._ptz_min_interval:
            return {"ok": True, "throttled": True}
        with self._tapo_lock:
            try:
                self._tapo.move(float(pan), float(tilt))
            except Exception as exc:
                return _eval_err(
                    "ptz_failed",
                    "pan/tilt command failed",
                    str(exc),
                    "pip install pytapo and set the Tapo Camera Account (not the cloud login)",
                )
        self._last_ptz_ts = now
        return {"ok": True}

    def ptz_preset(self, name: str) -> dict:
        if self._tapo is None:
            return _eval_err(
                "ptz_no_camera",
                "no Tapo camera connected for PTZ",
                "the active camera isn't a Tapo rtsp source (PTZ needs one)",
                "connect the Tapo rtsp URL and select the tapo_c211 profile",
                status=409,
            )
        with self._tapo_lock:
            try:
                self._tapo.preset(str(name))
            except Exception as exc:
                return _eval_err(
                    "ptz_failed",
                    f"could not recall preset {name!r}",
                    str(exc),
                    "create the preset in the Tapo app, or check pytapo + Camera Account",
                )
        return {"ok": True}

    def reanchor_camera(self, profile_name: str) -> dict:
        """Re-anchor the distance estimator to a camera intrinsics profile
        (go2_1080p | tapo_c211) WITHOUT a restart. Rebuilds the ranger (intrinsics
        are frozen into CameraModel at construction, so an in-place mutation would
        race the control loop — Eng review C1) and swaps it atomically."""
        from catranger.config import load_camera

        try:
            cam = load_camera(profile_name)
        except Exception as exc:
            return _eval_err(
                "camera_bad_profile",
                f"unknown camera profile {profile_name!r}",
                str(exc),
                "use a profile under configs/camera/ (go2_1080p or tapo_c211)",
            )
        self.camera_profile = profile_name
        self.camera_calibrated = not cam.needs_calibration
        warning = (
            None
            if self.camera_calibrated
            else f"{profile_name} intrinsics are UNCALIBRATED (placeholder fx/fy) — "
            "distances are guesses until you calibrate (see scripts/calibrate_camera.py)"
        )
        # Rebuild perception with the new intrinsics and swap atomically (the
        # control loop reads self._ranger as a single reference; assignment is
        # atomic in CPython — same discipline select_model relies on).
        if self.perception_available and self._ranger is not None:
            try:
                new_ranger = self._build_ranger(self.active_model)
            except Exception as exc:
                return {
                    "ok": True,
                    "camera_profile": profile_name,
                    "calibrated": self.camera_calibrated,
                    "warning": f"intrinsics set, but perception rebuild failed: {exc}",
                }
            self._ranger = new_ranger
            self.controller.follower.reset()
        return {
            "ok": True,
            "camera_profile": profile_name,
            "calibrated": self.camera_calibrated,
            "warning": warning,
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
        from catranger.config import load_app, load_camera
        from catranger.pipeline import CatRanger

        # Load a FRESH AppConfig every build and mutate only this local copy. A
        # cached/shared `app` mutated in place would (a) leak the camera profile
        # across model swaps and (b) be left half-mutated if a build raised,
        # silently poisoning the next ranger (adversarial review C2/#1).
        app = load_app(self.app_config)
        # Re-anchor intrinsics to the selected camera profile (Tapo vs Go2). The
        # default (None) keeps the app config's camera (go2_1080p).
        if self.camera_profile:
            app.camera = load_camera(self.camera_profile)
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

    # --------------------------------------------------------------- eval (M3)
    def start_eval(self, params: dict) -> dict:
        """Validate + launch a background eval run. Returns {ok} or a typed error
        dict {ok=False, code, problem, cause, fix}. Eval is heavy and competes for
        CPU/GPU, so it is refused unless the robot is IDLE (never while driving)."""
        source = str(params.get("source") or "").strip()
        if not source:
            return _eval_err(
                "eval_bad_source",
                "no eval source given",
                "the Eval tab sent an empty source",
                "enter an image dir, image, or video path (e.g. data/raw/how_far)",
            )
        if source.isdigit():
            return _eval_err(
                "eval_bad_source",
                f"refusing to eval a live webcam (index {source})",
                "a webcam source would fight the live control camera for the device",
                "point eval at a recorded image dir or video file instead",
            )
        if not _is_stream_spec(source) and not Path(source).exists():
            return _eval_err(
                "eval_bad_source",
                f"source not found: {source}",
                "the path does not exist on the server",
                "check the path; the provided set lives under data/raw/",
            )
        if not self.perception_available:
            return _eval_err(
                "eval_unavailable",
                "eval needs the ml extra",
                "torch/ultralytics are not installed",
                "uv sync --extra ml, then restart the server",
            )
        if self.controller.mode != Mode.IDLE:
            return _eval_err(
                "eval_not_idle",
                "switch to IDLE before running eval",
                "eval is CPU/GPU-heavy and would starve the live control loop",
                "set mode IDLE (or E-stop), then run eval",
                status=409,
            )
        max_frames = max(0, int(params.get("max_frames") or 0))  # never negative
        # Atomic: refuse if EITHER heavy job is active, then start — under one lock
        # so two concurrent requests can't both win the slot (TOCTOU, adversarial).
        with self._heavy_lock:
            if self.train_job.running:
                return _eval_err(
                    "heavy_job_busy",
                    "a training run is in progress",
                    "training and eval both saturate CPU/GPU — only one heavy job at a time",
                    "wait for training to finish or cancel it, then run eval",
                    status=409,
                )
            started = self.eval_job.start(
                source=source,
                config=self.app_config,
                approach=str(params.get("approach", "A")),
                classes=params.get("classes"),
                use_depth=bool(params.get("use_depth", False)),
                device=params.get("device"),
                max_frames=max_frames,
                gts=params.get("gts"),
                # separate path from the CLI's `make eval` (outputs/report/report.md)
                # so a concurrent CLI run can't clobber the web report mid-read.
                out="outputs/report/web-eval.md",
            )
        if not started:
            return _eval_err(
                "eval_busy",
                "an eval run is already in progress",
                "only one eval job runs at a time",
                "wait for it to finish (or cancel it) before starting another",
                status=409,
            )
        return {"ok": True, "state": "running"}

    def eval_status(self) -> dict:
        return {"ok": True, **self.eval_job.status()}

    def eval_result(self) -> dict | None:
        return self.eval_job.result()

    def cancel_eval(self) -> dict:
        return {"ok": True, "cancelled": self.eval_job.cancel()}

    # ------------------------------------------------------------- training (CV)
    @property
    def training_active(self) -> bool:
        return self.train_job.running

    def _train_data_ready(self, config: str) -> bool:
        """True if the fine-tune dataset yaml referenced by train.yaml exists. A
        bare built-in name (e.g. coco8.yaml) is treated as ready (ultralytics
        resolves it). Mirrors train_once()/overnight's own check."""
        from catranger.config import load_yaml

        try:
            cfg = load_yaml(config)
        except Exception:
            return False
        raw = str(cfg.get("data", "data/cat/data.yaml"))
        if "/" not in raw and "\\" not in raw:
            return True
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        return p.exists()

    def train_readiness(self) -> dict:
        """What the CV tab needs to render its readiness strip + disable dead
        buttons (DX review): ml extra, dataset, and whether a job is running."""
        config = str(self.cfg.get("train_config", "configs/train.yaml"))
        return {
            "ok": True,
            "ml_available": self.perception_available,
            "dataset_ready": self._train_data_ready(config),
            "running": self.train_job.running,
            "eval_running": self.eval_job.running,
            "idle": self.controller.mode == Mode.IDLE,
        }

    def start_train(self, params: dict) -> dict:
        """Validate + launch a background training job (prepare|train|autoresearch)
        as a subprocess. Heavy: refused unless IDLE and no other heavy job runs."""
        kind = str(params.get("kind", "")).strip()
        if kind not in ("prepare", "train", "autoresearch"):
            return _eval_err(
                "train_bad_kind",
                f"unknown training kind {kind!r}",
                "kind must be prepare, train, or autoresearch",
                "send kind=prepare|train|autoresearch",
            )
        config = str(params.get("config") or self.cfg.get("train_config", "configs/train.yaml"))
        # train/autoresearch need torch + a prepared dataset; prepare needs neither.
        if kind in ("train", "autoresearch"):
            if not self.perception_available:
                return _eval_err(
                    "train_unavailable",
                    "training needs the ml extra",
                    "torch/ultralytics are not installed",
                    "uv sync --extra ml, then restart the server",
                )
            if not self._train_data_ready(config):
                return _eval_err(
                    "train_no_dataset",
                    "no prepared dataset",
                    "the dataset yaml in train.yaml ('data:') does not exist yet",
                    "run a 'prepare' job first (or `make prepare`)",
                    status=409,
                )
        if self.controller.mode != Mode.IDLE:
            return _eval_err(
                "train_not_idle",
                "switch to IDLE before training",
                "training is CPU/GPU-heavy and would starve the live control loop",
                "set mode IDLE (or E-stop), then start training",
                status=409,
            )
        # Atomic check-and-start under the shared heavy-job lock (TOCTOU fix).
        with self._heavy_lock:
            if self.eval_job.running:
                return _eval_err(
                    "heavy_job_busy",
                    "an eval run is in progress",
                    "training and eval both saturate CPU/GPU — only one heavy job at a time",
                    "wait for eval to finish or cancel it, then train",
                    status=409,
                )
            started = self.train_job.start(
                kind=kind,
                config=config,
                epochs=params.get("epochs"),
                device=params.get("device"),
                source=params.get("source"),
            )
        if not started:
            return _eval_err(
                "train_busy",
                "a training run is already in progress",
                "only one training job runs at a time",
                "wait for it to finish (or cancel it) before starting another",
                status=409,
            )
        return {"ok": True, "state": "running", "kind": kind}

    def train_status(self) -> dict:
        return {"ok": True, **self.train_job.status()}

    def train_result(self) -> dict | None:
        return self.train_job.result()

    def cancel_train(self) -> dict:
        return {"ok": True, "cancelled": self.train_job.cancel()}

    def train_history(self, limit: int = 50) -> dict:
        """The runs/history index (newest first) for the CV tab's run table."""
        from catranger import history

        entries = history.read_index()
        entries.reverse()
        return {"ok": True, "runs": entries[: max(1, int(limit))]}

    def promote_model(self, params: dict) -> dict:
        """Promote a fine-tune into BOTH the CLI pipeline (cat_distance.yaml) and the
        web Models registry (models.yaml), then hot-reload the registry so it's
        immediately selectable (T3). Reuses catranger.train.promote (single source)."""
        from catranger.train import promote as promote_mod

        weights = str(params.get("weights") or "").strip()
        run_dir = str(params.get("run_dir") or "").strip()
        history_root = (_REPO_ROOT / "runs" / "history").resolve()
        # Resolve the weights to promote, in order of specificity:
        #   explicit weights > a history run dir's archived best.pt > the
        #   autoresearch winner > the stable published path train.py writes.
        # Paths are anchored to the repo root (the server's CWD is not guaranteed)
        # and run_dir is contained to runs/history (no `../` traversal).
        if not weights and run_dir:
            cand = (history_root / run_dir / "best.pt").resolve()
            if cand.is_relative_to(history_root) and cand.exists():
                weights = str(cand)
        if not weights:
            winner = promote_mod.read_winner()
            weights = str((winner or {}).get("published_weights") or "").strip()
        if not weights:
            stable = _REPO_ROOT / "runs" / "train" / "best.pt"
            if stable.exists():
                weights = str(stable)
        if not weights:
            return _eval_err(
                "promote_no_winner",
                "no weights to promote",
                "no weights/run_dir given and no trained weights found under runs/",
                "run a train/autoresearch job first, or pass an explicit weights path",
                status=409,
            )
        if not Path(weights).exists():
            return _eval_err(
                "promote_weights_missing",
                f"weights file not found: {weights}",
                "the path does not exist on the server",
                "check the run's best.pt path under runs/",
            )
        model_id = str(params.get("model_id") or "cats-finetuned")
        name = str(params.get("name") or "Fine-tuned cats")
        try:
            summary = promote_mod.promote_weights(weights, model_id=model_id, name=name)
        except Exception as exc:
            return _eval_err(
                "promote_failed",
                "could not promote the fine-tune",
                str(exc),
                "check configs/cat_distance.yaml has a 'finetuned_weights:' line",
            )
        # Hot-reload the registry so the new profile shows in the Models tab now.
        # Surface a reload failure (don't swallow): a malformed profile would
        # otherwise report success here yet brick the next server boot.
        try:
            self.registry = ModelRegistry.from_yaml(self._models_config)
        except Exception as exc:
            return _eval_err(
                "promote_registry_invalid",
                "promoted the weights, but the model registry failed to reload",
                str(exc),
                "the new profile in configs/models.yaml may be malformed — check it",
                status=500,
            )
        return {"ok": True, **summary}

    # ----------------------------------------------------------- discovery (M5)
    def discover_devices(self) -> dict:
        """Best-effort device discovery for the Connections tab: serial ports
        always, BLE only if bleak is installed. Never raises — an empty list with
        a hint beats a traceback."""
        serial_ports: list[dict] = []
        try:
            from serial.tools import list_ports

            serial_ports = [
                {"target": p.device, "label": p.description or p.device}
                for p in list_ports.comports()
            ]
        except Exception:  # pyserial absent or platform quirk
            serial_ports = []
        ble_available = importlib.util.find_spec("bleak") is not None
        return {
            "ok": True,
            "serial": serial_ports,
            "ble_available": ble_available,
            "hint": None if serial_ports else "no serial ports found — plug in the USB/BT adapter",
        }

    # one-shot estop/reset proxies so the server never reaches past this facade
    def estop(self) -> None:
        # E-stop also tears down any heavy job so the box is freed for the operator.
        self.train_job.request_stop()
        self.eval_job.cancel()
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
