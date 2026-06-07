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

import base64
import importlib.util
import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from catranger.calibrate_sonar import (
    calibrate_camera_with_sonar,
    collect_sonar_ratios,
)
from catranger.hw.char_bridge import BUZZER_FAR_CM, SONAR_RANGE_CM
from catranger.types import Command, FrameResult
from catranger.web.cat_catalog import _crop_thumb_b64, build_cat_catalog
from catranger.web.cat_library import CatLibraryStore
from catranger.web.cat_match import thumb_similarity
from catranger.web.controller import Mode, RobotController, StopReason
from catranger.web.eval_job import EvalJob
from catranger.web.flash_job import FlashJob
from catranger.web.overlay import build_overlay
from catranger.web.registry import ModelProfile, ModelRegistry, apply_profile
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
    # WS-A7: how often a running web eval refreshes its durable-queue lease. Well under
    # JobQueue's stale TTL (1800s) so a concurrent overnight recover_stale never reclaims a
    # live heavy job; throttled so we don't open a sqlite connection per processed frame/epoch.
    _HEAVY_HEARTBEAT_S = 60.0

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
        # WS-B0: per-frame overlay-JSON contract (per-detection boxes/dist/flags) the
        # console draws on a canvas. Display thresholds live in configs/web.yaml.
        self._overlay_cfg = dict(cfg.get("overlay", {}) or {})
        self._last_overlay: dict | None = None
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
        self._sonar_display_cm: int | None = None
        self._preferred_target_id: int | None = None
        self._cat_catalog: list[dict] = []
        cat_hz = float(cfg.get("cat_catalog_hz", 2) or 2)
        self._cat_catalog_interval = 1.0 / cat_hz if cat_hz > 0 else 0.5
        self._last_cat_catalog_ts = 0.0
        self._session_seen: dict[int, dict] = {}
        lib_db = str(cfg.get("cat_library_db", "outputs/cat_library.sqlite3"))
        self.cat_library = CatLibraryStore(lib_db)
        self._tracker_to_library: dict[int, int] = {}
        self._find_library_id: int | None = None
        self._find_library_name: str | None = None
        self._match_threshold = float(cfg.get("cat_match_threshold", 0.55))

        # M3: one background eval job, started/polled from the Eval tab.
        self.eval_job = EvalJob()
        # Connections tab: flash Arduino firmware over USB (arduino-cli).
        self.flash_job = FlashJob()
        # WS-A7: durable-queue row id of the running HEAVY web job (eval OR train — they
        # share one slot via _heavy_lock) + its last heartbeat (monotonic). The worker
        # refreshes the lease on progress ticks so a long job is never reclaimed as
        # "crashed" by another worker's (e.g. overnight) TTL sweep.
        self._heavy_row_id: int | None = None
        self._heavy_hb_at = 0.0
        # CV/Training tab: one background training job (subprocess). Eval and train
        # are mutually exclusive — both saturate CPU/GPU (shared heavy-job slot).
        self.train_job = TrainJob()
        # One real lock guards the eval/train check-and-start so two concurrent
        # requests can't both pass their "is the other running?" check (TOCTOU).
        self._heavy_lock = threading.Lock()

    # ------------------------------------------------------------ jobqueue (A7)
    def _open_jobs(self):
        """Open a SHORT-LIVED web-owned job queue connection. Per-operation (not cached)
        because eval bookkeeping spans threads (REST handler + the eval worker) and a
        sqlite connection is single-thread. Returns None if anything fails — durable
        bookkeeping must never break eval itself."""
        try:
            from catranger.jobqueue import DEFAULT_DB_PATH, JobQueue

            return JobQueue(self.cfg.get("jobqueue_db") or DEFAULT_DB_PATH, owner="web")
        except Exception:
            logging.getLogger("catranger.web").warning("jobqueue unavailable", exc_info=True)
            return None

    def _record_job(self, run_key: str, kind: str, meta: dict) -> None:
        """Record a starting heavy web job (kind='web-eval' or 'web-train') in the durable
        queue and remember its row id for heartbeats. Best-effort; never breaks the job."""
        self._heavy_row_id = None
        self._heavy_hb_at = time.monotonic()  # fresh heartbeat at record_running
        q = self._open_jobs()
        if q is None:
            return
        try:
            self._heavy_row_id = q.record_running(kind, meta, run_key)
        except Exception:
            logging.getLogger("catranger.web").warning("jobqueue record failed", exc_info=True)
        finally:
            q.close()

    def _heartbeat_job(self) -> None:
        """Refresh the running heavy job's durable-queue lease (throttled to
        ``_HEAVY_HEARTBEAT_S``). Called from the worker thread on each progress tick so a
        long eval/train keeps its lease fresh and is never reclaimed as "crashed" by
        another worker's (e.g. overnight) TTL sweep. Best-effort; never raises."""
        row_id = self._heavy_row_id
        if row_id is None:
            return
        now = time.monotonic()
        if now - self._heavy_hb_at < self._HEAVY_HEARTBEAT_S:
            return
        self._heavy_hb_at = now
        q = self._open_jobs()
        if q is None:
            return
        try:
            q.heartbeat(row_id)
        except Exception:
            logging.getLogger("catranger.web").warning("jobqueue heartbeat failed", exc_info=True)
        finally:
            q.close()

    def _settle_job(self, run_key: str, status: str) -> None:
        q = self._open_jobs()
        if q is None:
            return
        try:
            q.complete_by_key(run_key, status if status in ("ok", "fail", "skipped") else "fail")
        except Exception:
            logging.getLogger("catranger.web").warning("jobqueue settle failed", exc_info=True)
        finally:
            q.close()

    def jobs_status(self, limit: int = 200) -> dict:
        """Durable job-queue state — overnight sweeps (owner='overnight') AND web eval/train
        (owner='web') — for the live sweep panel (WS-B3) and ops/curl. Read-only; empty
        (and creates nothing) until a sweep or eval has actually run."""
        from catranger.jobqueue import DEFAULT_DB_PATH

        path = self.cfg.get("jobqueue_db") or DEFAULT_DB_PATH
        if not Path(path).exists():
            return {"ok": True, "jobs": [], "counts": {}}
        q = self._open_jobs()
        if q is None:
            return {"ok": True, "jobs": [], "counts": {}}
        try:
            jobs = q.list_jobs()
            counts = q.counts()
        except Exception:
            logging.getLogger("catranger.web").warning("jobqueue read failed", exc_info=True)
            return {"ok": True, "jobs": [], "counts": {}}
        finally:
            q.close()
        return {"ok": True, "jobs": jobs[-int(limit) :] if limit else jobs, "counts": counts}

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        # WS-A7: mark any web eval left "running" by a previous crash as interrupted.
        q = self._open_jobs()
        if q is not None:
            try:
                orphans = q.fail_orphans("web")
                if orphans:
                    logging.getLogger("catranger.web").info(
                        "recovered %d interrupted web eval(s) from a prior run", len(orphans)
                    )
            except Exception:
                logging.getLogger("catranger.web").warning(
                    "jobqueue recovery failed", exc_info=True
                )
            finally:
                q.close()
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
        self.cat_library.close()

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
                    self._last_overlay = build_overlay(None, idx)
                else:
                    self.controller.camera_connected = True
                    self._last_frame_ts = time.perf_counter()
                    result, draw_frame = self._perceive(frame, idx)
                    self._try_match_library_target(draw_frame, result)
                    cmd = self.controller.apply(result, frame_index=idx)
                    self._publish(self._encode(draw_frame, result, cmd))
                    self._observe(result)
                    self._maybe_update_cat_catalog(draw_frame, result)
                    self._last_overlay = build_overlay(
                        result,
                        idx,
                        low_conf=self._overlay_cfg.get("low_conf"),
                        wide_ci_frac=self._overlay_cfg.get("wide_ci_frac"),
                        disagree_frac=self._overlay_cfg.get("disagree_frac"),
                    )
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
        target_ids: list[int] = []
        tgt = result.target
        if tgt is not None:
            target_id = tgt.track_id
            target_ids = list(result.target_known_ids or [])
            if target_id is not None and target_id not in target_ids:
                target_ids = [target_id, *target_ids]
            elif not target_ids and target_id is not None:
                target_ids = [target_id]
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
            target_ids=target_ids or None,
            mode=self.controller.mode.value,
        )

    def _maybe_update_cat_catalog(self, frame: np.ndarray, result: FrameResult) -> None:
        now = time.perf_counter()
        encode_thumbs = (now - self._last_cat_catalog_ts) >= self._cat_catalog_interval
        if encode_thumbs:
            self._last_cat_catalog_ts = now
        locked: int | None = None
        if self._ranger is not None:
            locked = self._ranger.tracker.locked_id
        elif result.target is not None:
            locked = result.target.track_id
        live = build_cat_catalog(
            frame if encode_thumbs else None,
            result,
            locked_id=locked,
            preferred_id=self._preferred_target_id,
            previous=self._cat_catalog,
            encode_thumbs=encode_thumbs,
        )
        live_ids = set()
        for card in live:
            card["in_view"] = True
            tid = int(card["id"])
            live_ids.add(tid)
            self._session_seen[tid] = dict(card)
            if encode_thumbs and card.get("thumb_jpeg_b64"):
                self._register_library_sighting(card)

        merged: dict[int, dict] = {int(c["id"]): c for c in live}
        for tid, prev in self._session_seen.items():
            if tid in live_ids:
                continue
            off = dict(prev)
            off["in_view"] = False
            off["is_locked"] = locked is not None and tid == int(locked)
            off["is_preferred"] = self._preferred_target_id is not None and tid == int(
                self._preferred_target_id
            )
            merged[tid] = off

        self._cat_catalog = sorted(
            merged.values(),
            key=lambda c: (not c.get("in_view", True), -float(c.get("conf", 0))),
        )

    def _register_library_sighting(self, card: dict) -> None:
        tid = int(card["id"])
        thumb_b64 = card.get("thumb_jpeg_b64")
        if not thumb_b64:
            return
        try:
            thumb = base64.standard_b64decode(thumb_b64)
        except Exception:
            return
        lib_id = self._tracker_to_library.get(tid)
        if lib_id is None:
            lib_id = self.cat_library.match_by_thumb(thumb, threshold=self._match_threshold)
        lib_id = self.cat_library.upsert_sighting(
            library_id=lib_id,
            tracker_id=tid,
            thumb_jpeg=thumb,
            conf=float(card.get("conf", 0.0)),
            dist_m=card.get("dist_m"),
            bearing_deg=float(card.get("bearing_deg", 0.0)),
        )
        self._tracker_to_library[tid] = lib_id
        card["library_id"] = lib_id

    def _try_match_library_target(self, frame: np.ndarray, result: FrameResult) -> None:
        if self._find_library_id is None or self._ranger is None:
            return
        template = self.cat_library.get_thumb_bytes(self._find_library_id)
        if template is None:
            return
        best_tid: int | None = None
        best_score = 0.0
        for obs in result.observations:
            tid = obs.track_id
            if tid is None:
                continue
            crop_b64 = _crop_thumb_b64(frame, obs.detection.xyxy, 72)
            if not crop_b64:
                continue
            try:
                crop = base64.standard_b64decode(crop_b64)
            except Exception:
                continue
            score = thumb_similarity(template, crop)
            if score > best_score:
                best_score = score
                best_tid = int(tid)
        if best_tid is None or best_score < self._match_threshold:
            return
        self._find_library_id = None
        self._find_library_name = None
        self.select_target(best_tid, follow=True)

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
        gt = t.get("gt_cm")
        gt_cm = int(gt) if isinstance(gt, int) else None
        if gt_cm is not None and gt_cm >= 0:
            self._sonar_display_cm = gt_cm
        display_cm = gt_cm if gt_cm is not None and gt_cm >= 0 else self._sonar_display_cm
        bridge = self.controller._bridge
        periph = (
            bridge.periph_state()
            if bridge is not None and hasattr(bridge, "periph_state")
            else None
        )
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
                "ptz_available": self._tapo is not None,
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
                # WS-B0: per-detection overlay contract (boxes/dist/flags + frame_id)
                # the console draws on a canvas over the MJPEG frame.
                "overlay": self._last_overlay,
                # HC-SR04 + on-rig peripherals (CharBridge firmware).
                "peripherals": periph,
                "sonar_range_cm": SONAR_RANGE_CM,
                "sonar_display_cm": display_cm,
                "sonar_no_echo": gt_cm == -1,
                "sonar_zone": self._sonar_zone(display_cm),
                "sonar_obstacle": (
                    display_cm is not None and 0 <= display_cm <= self.controller.safe_stop_cm
                ),
                "buzzer_active": bool(
                    periph
                    and periph.get("buzzer")
                    and display_cm is not None
                    and 0 <= display_cm <= BUZZER_FAR_CM
                ),
                "preferred_target_id": self._preferred_target_id,
                "cats": self._cat_catalog,
                "find_library_id": self._find_library_id,
                "find_library_name": self._find_library_name,
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
            "ptz_available": self._tapo is not None,
            "model": self.active_model.id,
            "model_status": self.model_status,
            "model_error": self.model_error,
            "perception_available": self.perception_available,
            "models": [m.to_public_dict() for m in self.registry.list()],
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
        # RTSP streams are the Tapo C211 in this project — the default go2_1080p profile
        # disables pan/tilt and uses the wrong intrinsics. Auto-select tapo_c211 unless
        # the operator explicitly picked another profile for a non-RTSP source.
        profile = camera
        profile_note: str | None = None
        if spec.lower().startswith("rtsp://") and profile in (None, "go2_1080p"):
            profile = "tapo_c211"
            profile_note = (
                "RTSP detected — switched camera profile to tapo_c211 "
                "(required for pan/tilt and Tapo distance intrinsics)"
            )
        if profile:
            re = self.reanchor_camera(profile)
            result["camera_profile"] = re.get("camera_profile")
            result["calibrated"] = re.get("calibrated")
            if re.get("warning") and not result["warning"]:
                result["warning"] = re.get("warning")
            elif profile_note and not result["warning"]:
                result["warning"] = profile_note
            elif profile_note and result["warning"]:
                result["warning"] = f"{profile_note}; {result['warning']}"
        else:
            result["camera_profile"] = self.camera_profile
            result["calibrated"] = self.camera_calibrated
        self._set_tapo_handle(spec)
        result["ptz_available"] = self._tapo is not None
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

    def _set_tapo_handle(self, spec: str) -> None:
        """Build (or clear) the TapoCamera PTZ handle from an RTSP URL with credentials.

        Pan/tilt uses ONVIF on the same host — independent of the intrinsics profile
        dropdown, so a mistaken go2_1080p selection does not disable the motor.
        """
        self._tapo = None
        if not spec.lower().startswith("rtsp://"):
            return
        try:
            from catranger.hw.tapo import TapoCamera

            host, user, pwd, stream = _parse_rtsp(spec)
            if host and user and pwd:
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
                    "enable Third-Party Compatibility (Tapo app -> Me -> Tapo Lab), "
                    "set a Camera Account, and run uv sync --extra hw",
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
                    "create the preset in the Tapo app, or check ONVIF + Camera Account",
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
        # cached/shared `app` mutated in place would (a) leak the camera profile or
        # class filter across model swaps and (b) be left half-mutated if a build
        # raised, silently poisoning the next ranger (review C2/#1).
        app = load_app(self.app_config)
        # Re-anchor intrinsics to the selected camera profile (Tapo vs Go2). The
        # default (None) keeps the app config's camera (go2_1080p).
        if self.camera_profile:
            app.camera = load_camera(self.camera_profile)
        # WS-C3: the one model home — apply_profile injects backend/weights/classes/
        # tracker (and clears a stale class filter) on this fresh copy.
        approach = apply_profile(app, profile, approach_key="_web")
        ranger = CatRanger(app, approach=approach, use_depth=False)
        if self._preferred_target_id is not None:
            ranger.set_preferred_target(self._preferred_target_id)
        return ranger

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
        # WS-A7: record the eval in the durable queue BEFORE starting, so a fast finish
        # never settles before the row exists. A refused (busy) start is un-recorded below.
        run_key = f"web-eval-{int(time.time() * 1000)}"
        # Atomic: refuse if EITHER heavy job is active, then record + start — under one
        # lock so two concurrent requests can't both win the slot (TOCTOU, adversarial).
        with self._heavy_lock:
            if self.train_job.running:
                return _eval_err(
                    "heavy_job_busy",
                    "a training run is in progress",
                    "training and eval both saturate CPU/GPU — only one heavy job at a time",
                    "wait for training to finish or cancel it, then run eval",
                    status=409,
                )
            self._record_job(
                run_key,
                "web-eval",
                {"source": source, "approach": str(params.get("approach", "A"))},
            )
            started = self.eval_job.start(
                on_settle=lambda status: self._settle_job(run_key, status),
                on_progress=lambda done, total: self._heartbeat_job(),
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
            self._settle_job(run_key, "skipped")  # busy: release the row we just recorded
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
        # WS-A7: record the training run in the durable queue (owner='web') so it shows
        # in /api/jobs / `make jobs` alongside evals + sweeps, and an interrupted run is
        # surfaced on restart. Recorded BEFORE start (inside the lock) like eval.
        run_key = f"web-train-{kind}-{int(time.time() * 1000)}"
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
            self._record_job(run_key, "web-train", {"kind": kind, "config": config})
            started = self.train_job.start(
                kind=kind,
                config=config,
                epochs=params.get("epochs"),
                device=params.get("device"),
                source=params.get("source"),
                on_settle=lambda status: self._settle_job(run_key, status),
                on_progress=lambda epoch, total: self._heartbeat_job(),
            )
        if not started:
            self._settle_job(run_key, "skipped")  # busy: release the row we just recorded
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
        winner = promote_mod.read_winner()
        promote_kw: dict[str, Any] = {"model_id": model_id, "name": name}
        if run_dir:
            stamp = run_dir.rsplit("/", 1)[-1]
            promote_kw["trained_at"] = stamp
            if "-" in stamp:
                promote_kw["run_kind"] = stamp.rsplit("-", 1)[-1]
        if winner:
            if winner.get("metric") is not None:
                promote_kw["metric"] = winner.get("metric")
            if winner.get("metric_key"):
                promote_kw["metric_key"] = winner.get("metric_key")
            if winner.get("duration_s") is not None:
                promote_kw["duration_s"] = winner.get("duration_s")
            if winner.get("summary"):
                promote_kw["summary"] = winner.get("summary")
            promote_kw.setdefault("run_kind", "autoresearch")
        try:
            summary = promote_mod.promote_weights(weights, **promote_kw)
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

    # -------------------------------------------------------- flash firmware (USB)
    def flash_readiness(self) -> dict:
        from catranger.hw.arduino_flash import readiness

        ready = readiness()
        return {"ok": bool(ready.get("ok")), **ready}

    def start_flash(self, port: str | None = None) -> dict:
        """Compile + upload cat_ranger.ino via arduino-cli. Disconnects the robot
        bridge first — the USB serial port cannot be shared with runtime control."""
        from catranger.hw.arduino_flash import readiness

        ready = readiness()
        if not ready.get("ok"):
            return {
                "ok": False,
                "code": "flash_unavailable",
                "problem": str(ready.get("problem") or "flash not available"),
                "fix": ready.get("fix"),
            }
        if self.flash_job.status()["state"] == "running":
            return {
                "ok": False,
                "code": "flash_busy",
                "problem": "a firmware flash is already in progress",
                "fix": "wait for it to finish, then retry",
                "status": 409,
            }
        # Release the serial port before arduino-cli upload grabs it.
        self.connect_robot("dummy")
        started = self.flash_job.start(port or None)
        if not started:
            return {
                "ok": False,
                "code": "flash_busy",
                "problem": "a firmware flash is already in progress",
                "status": 409,
            }
        return {"ok": True, "state": "running", "port": port}

    def flash_status(self) -> dict:
        return {"ok": True, **self.flash_job.status()}

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

    def set_peripheral(self, action: str) -> dict[str, Any]:
        """Toggle HC-SR04 feedback peripherals on the CharBridge firmware (buzzer/RGB/LCD)."""
        from catranger.hw.char_bridge import PERIPH_ACTIONS, CharBridge

        ch = PERIPH_ACTIONS.get(action)
        if ch is None:
            return {"ok": False, "error": f"unknown peripheral action {action!r}"}
        bridge = self.controller._bridge
        if bridge is None or not getattr(self.controller, "robot_connected", False):
            return {"ok": False, "error": "robot not connected"}
        if not isinstance(bridge, CharBridge):
            return {"ok": False, "error": "peripheral control requires CharBridge firmware"}
        try:
            bridge.send_raw(ch)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "peripherals": bridge.periph_state()}

    def select_target(
        self,
        track_id: int | None,
        *,
        follow: bool = False,
    ) -> dict[str, Any]:
        """Pick which tracked cat to follow (None = auto largest box)."""
        from catranger.web.controller import Mode

        self._find_library_id = None
        self._find_library_name = None
        self._preferred_target_id = int(track_id) if track_id is not None else None
        if self._ranger is not None:
            self._ranger.set_preferred_target(self._preferred_target_id)
        self.controller.follower.reset()
        if follow and not self.controller.estopped:
            self.controller.set_mode(Mode.FOLLOW)
        return {
            "ok": True,
            "preferred_target_id": self._preferred_target_id,
            "mode": self.controller.mode.value,
        }

    def list_library_cats(self, *, limit: int = 200) -> list[dict[str, Any]]:
        cats = self.cat_library.list_cats(limit=limit)
        for row in cats:
            row["thumb_jpeg_b64"] = None
            if row.get("has_thumb"):
                detail = self.cat_library.get(int(row["id"]))
                if detail:
                    row["thumb_jpeg_b64"] = detail.get("thumb_jpeg_b64")
        return cats

    def get_library_cat(self, cat_id: int) -> dict[str, Any] | None:
        return self.cat_library.get(cat_id)

    def rename_library_cat(self, cat_id: int, name: str) -> dict[str, Any]:
        ok = self.cat_library.rename(cat_id, name)
        return {"ok": ok}

    def delete_library_cat(self, cat_id: int) -> dict[str, Any]:
        ok = self.cat_library.delete(cat_id)
        if ok:
            self._tracker_to_library = {
                tid: lid for tid, lid in self._tracker_to_library.items() if lid != int(cat_id)
            }
            if self._find_library_id == int(cat_id):
                self._find_library_id = None
                self._find_library_name = None
        return {"ok": ok}

    def find_library_cat(
        self,
        library_id: int,
        *,
        follow: bool = True,
    ) -> dict[str, Any]:
        """Drive/search to re-acquire a saved cat by appearance + last bearing."""
        from catranger.web.controller import Mode

        cat = self.cat_library.get(int(library_id))
        if cat is None:
            return {"ok": False, "error": f"unknown library cat id {library_id}"}

        self._find_library_id = int(library_id)
        self._find_library_name = str(cat["name"])
        last_tid = cat.get("last_tracker_id")
        bearing = cat.get("last_bearing_deg")

        if last_tid is not None and self._ranger is not None:
            known = set(self._ranger.tracker.known_ids)
            if int(last_tid) in known or int(last_tid) in self._session_seen:
                self._preferred_target_id = int(last_tid)
                self._ranger.set_preferred_target(self._preferred_target_id)
            else:
                self._preferred_target_id = None
                self._ranger.set_preferred_target(None)
        else:
            self._preferred_target_id = None
            if self._ranger is not None:
                self._ranger.set_preferred_target(None)

        self.controller.follower.reset()
        if bearing is not None:
            self.controller.follower.set_search_bearing_deg(float(bearing))

        if follow and not self.controller.estopped:
            self.controller.set_mode(Mode.FOLLOW)

        return {
            "ok": True,
            "find_library_id": self._find_library_id,
            "find_library_name": self._find_library_name,
            "mode": self.controller.mode.value,
        }

    def calibrate_with_sonar(
        self,
        *,
        profile: str | None = None,
        baseline_m: float | None = None,
        duration_s: float | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Re-anchor fx/fy using live vision distance vs HC-SR04 (+ baseline offset)."""
        cfg = self.cfg.get("sonar_calibration", {}) or {}
        baseline = float(baseline_m if baseline_m is not None else cfg.get("baseline_m", 0.09))
        duration = float(duration_s if duration_s is not None else cfg.get("duration_s", 5.0))
        min_samples = int(cfg.get("min_samples", 8))
        min_cm = int(cfg.get("min_sonar_cm", 25))
        max_cm = int(cfg.get("max_sonar_cm", 180))
        cam_profile = profile or self.camera_profile or "go2_1080p"

        if not self.controller.robot_connected:
            return _eval_err(
                "robot_not_connected",
                "robot not connected — no HC-SR04 ground truth",
                "CharBridge/USB link is required for sonar calibration",
                "connect the robot in Connections (usb @ 9600)",
                status=409,
            )
        if self._ranger is None:
            return _eval_err(
                "perception_off",
                "perception is not running",
                "select a model and connect a camera first",
                "Models tab → pick a detector; Connections → connect camera",
                status=409,
            )

        def _read_sample() -> tuple[float | None, int | None]:
            with self.controller._lock:
                t = dict(self.controller.latest_telemetry)
            pred = t.get("target_dist_m")
            pred_m = float(pred) if isinstance(pred, (int, float)) and pred > 0 else None
            gt = t.get("gt_cm")
            sonar_cm = int(gt) if isinstance(gt, int) else None
            if sonar_cm is None and isinstance(gt, float) and gt >= 0:
                sonar_cm = int(gt)
            return pred_m, sonar_cm

        ratios, preds, gts = collect_sonar_ratios(
            _read_sample,
            duration_s=duration,
            min_sonar_cm=min_cm,
            max_sonar_cm=max_cm,
            baseline_m=baseline,
        )
        if len(ratios) < min_samples:
            return _eval_err(
                "insufficient_samples",
                f"only {len(ratios)} valid pairs (need {min_samples})",
                "vision target or sonar was missing during the sample window",
                "point the rig at a tracked cat or flat target; hold steady 25–180 cm from sonar",
                status=409,
            )

        result = calibrate_camera_with_sonar(
            cam_profile,
            ratios,
            baseline_m=baseline,
            dry_run=dry_run,
        )
        if not result.ok:
            body = result.as_dict()
            body["code"] = "calibrate_failed"
            body["status"] = 400
            return body

        out = result.as_dict()
        out["pred_m_mean"] = round(float(np.mean(preds)), 3) if preds else None
        out["gt_m_mean"] = round(float(np.mean(gts)), 3) if gts else None

        if dry_run:
            out["warning"] = "dry run — camera YAML unchanged"
            return out

        re = self.reanchor_camera(cam_profile)
        out["calibrated"] = re.get("calibrated", True)
        out["camera_profile"] = cam_profile
        if re.get("warning"):
            out["warning"] = re["warning"]
        return out

    @staticmethod
    def _sonar_zone(cm: int | None) -> str | None:
        if cm is None or cm < 0:
            return None
        if cm <= 40:
            return "red"
        if cm <= 80:
            return "yellow"
        if cm <= 120:
            return "green"
        if cm <= 160:
            return "cyan"
        return "blue"

    @property
    def stop_reason(self) -> StopReason:
        return self.controller.stop_reason
