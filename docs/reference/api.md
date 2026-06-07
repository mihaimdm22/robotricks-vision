# API Reference

> **TL;DR** — The control plane exposes **REST** routes under `/api/*` for commands and
> queries, a **WebSocket** at `/ws` for the live control loop, and an **MJPEG** stream at
> `/video`. Errors use a typed envelope (never a stack trace). The console is a separate
> origin, so CORS origins come from `configs/web.yaml`. Source: `catranger/web/server.py`.

Base URL when run locally: `http://localhost:8080` (`catranger serve`).

---

## Error envelope

Every failed request returns this shape (the operator gets *cause* + *fix*, never a
trace):

```json
{ "ok": false, "code": "bad_mode", "problem": "unknown mode 'X'",
  "cause": "mode must be IDLE, MANUAL, or FOLLOW", "fix": "send one of IDLE|MANUAL|FOLLOW" }
```

Success responses include `"ok": true`. HTTP status is `400` by default; notable
overrides: `404` (unknown model / report not ready), `409` (E-stop latched, or training
holds the GPU).

---

## REST — control

### `GET /api/status`
Full runtime snapshot: mode, E-stop state, models + active model, camera/robot connection,
last telemetry.

### `POST /api/control`
Manual drive intent.
```json
{ "action": "forward|back|left|right|pan|stop", "value": 0.0 }
```
→ `{ "ok": true }`. `400 bad_action` if the action is unknown.

### `POST /api/mode`
```json
{ "mode": "IDLE|MANUAL|FOLLOW" }
```
→ `{ "ok": true, "mode": "FOLLOW" }`.
`409 train_active` if a training run holds the GPU; `409 estopped` if E-stop is latched;
`400 bad_mode` otherwise.

### `POST /api/estop`  /  `POST /api/reset`
Latch / clear the emergency stop. `estop` → `{ "ok": true, "estop": true }`; `reset` →
`{ "ok": true, "estop": false }`. **Never gated** by anything.

---

## REST — models

### `GET /api/models`
→ `{ "ok": true, "models": [...], "active": "<id>", "status": "<model_status>" }`.

Each model includes `id`, `name`, `backend`, `dataset`, plus run-history fields
(`run_kind`, `trained_at`, `metric`, `metric_key`, `duration_s`, `summary`, `notes`)
from `configs/models.yaml`. Weights paths are never exposed.

### `POST /api/models/select`
```json
{ "id": "<model id from configs/models.yaml>" }
```
Rebuilds the pipeline atomically. `404 unknown_model` if the id is not registered.

---

## REST — camera

### `POST /api/camera/connect`
```json
{ "spec": "synthetic | <webcam index> | <rtsp url> | <file path>",
  "camera": "go2_1080p | tapo_c211 | null" }
```
`camera` selects the intrinsics profile and **re-anchors distance**.

### `POST /api/camera/disconnect`
Reverts to the `synthetic` source.

### `POST /api/camera/ptz`
```json
{ "pan": 0.0, "tilt": 0.0 }   // each in [-1,1]; +pan = right, +tilt = up
```
Runs off the event loop (blocking `pytapo` call). Returns `{ "ok": true, ... }` or the
error envelope with the upstream status.

### `POST /api/camera/ptz/preset`
```json
{ "name": "<preset name>" }
```

---

## REST — robot

### `POST /api/robot/connect`
```json
{ "connection": "dummy|usb|bt|ble", "target": "<port/address|null>", "baud": 115200 }
```
(HC-05 Classic BT uses `baud: 9600`.)

### `POST /api/robot/disconnect`
Reverts to the `dummy` robot.

### `GET /api/robot/discover`
Enumerate serial ports / probe BLE (off the event loop). → device list.

### `GET /api/robot/flash/readiness`
Probe whether `arduino-cli` and the bundled sketch (`arduino/cat_ranger`) are available on the server.

### `POST /api/robot/flash`
```json
{ "port": "/dev/cu.usbmodem14101" }
```
Compile + upload the CatRanger firmware over USB. Disconnects the runtime robot link first (the port cannot be shared). Poll `GET /api/robot/flash/status` until `state` is `done` or `error`.

### `GET /api/robot/flash/status`
Background flash job state: `idle | running | done | error`.

---

## REST — evaluation

### `POST /api/eval/run`
```json
{ "source": "<image dir|image|video|rtsp url>", "approach": "A|B",
  "classes": "all | <comma-sep COCO ids> | null", "max_frames": 0, "use_depth": false }
```
`approach` A=YOLO11, B=RT-DETR. `max_frames: 0` = all. Returns the started job, or the
error envelope (e.g. another heavy job is running).

### `GET /api/eval/status`
Live job state (`queued|running|done|...`).

### `GET /api/eval/report`
The finished frozen-metric report. `404 eval_not_ready` until one completes.

### `POST /api/eval/cancel`
Cancel the running eval.

---

## REST — training (CV)

### `GET /api/train/readiness`
Whether the training prerequisites (dataset, weights, device) are present.

### `POST /api/train/run`
```json
{ "kind": "prepare|train|autoresearch", "config": null,
  "epochs": null, "device": "cuda|mps|cpu|0|null", "source": null }
```

### `GET /api/train/status` · `GET /api/train/report`
Live status; finished report (`404 train_not_ready` until one completes).

### `POST /api/train/cancel`
Cancel the running training job.

### `GET /api/train/history?limit=50`
The run-history archive (sibling of `runs/history/INDEX.md`).

### `POST /api/train/promote`
```json
{ "weights": null, "run_dir": "runs/history/<dir>|null",
  "model_id": null, "name": null }
```
Wire a fine-tune winner into the live pipeline (gated, baseline-safe).

---

## REST — observability

### `GET /api/history?limit=600&since=<ts>`
Recorded distance samples (model estimate + CI vs HC-SR04) for the live chart.
→ `{ "samples": [...] }` (empty when no store is attached).

### `GET /api/jobs?limit=200`
Durable job-queue state (overnight sweeps + web eval/training).
→ `{ "ok": true, "jobs": [...], "counts": {...} }`.

### `GET /healthz`
→ `204 No Content`.

---

## Streams

### `GET /video` — MJPEG
`multipart/x-mixed-replace; boundary=frame`. Each part is a JPEG **with detection boxes
burned in**. The stream coalesces on the latest frame — slow clients skip frames, they
never backpressure the capture loop. Cancels cleanly on browser disconnect.

### `WS /ws` — telemetry + control

**Server → client**

*Telemetry* (pushed on a timer at `fps_cap` Hz):
```json
{ "type": "telemetry", "...runtime telemetry...",
  "you_are_controller": true, "controller_id": "<id>" }
```
The telemetry payload embeds the **overlay** (see below).

*Nack* (rejected intent):
```json
{ "type": "nack", "code": "observer", "problem": "...", "fix": "..." }
```

**Client → server** (`{ "type": ... }`):

| `type` | Effect | Token required |
|---|---|---|
| `estop` | latch emergency stop | **no** (checked first) |
| `reset` | clear E-stop | **no** |
| `claim` / `claim_control` / `request_control` | take the drive token | — |
| `heartbeat` | renew token lease + MANUAL watchdog | — |
| `intent` | `{action, value}` manual drive | **yes** (auto-claim if free) |
| `mode` | `{mode}` switch IDLE/MANUAL/FOLLOW | **yes**; `nack train_active` if training |

---

## Overlay contract (`web/overlay.py`)

The normalized per-frame payload the console draws on a canvas over the MJPEG frame.
Coordinates are normalized to `[0,1]` so they map onto the letterboxed video at any
resolution.

```json
{
  "frame_id": 1234,
  "frame_w": 1920,
  "frame_h": 1080,
  "dets": [
    {
      "track_id": 7,
      "cls": "cat",
      "xyxy_norm": [0.31, 0.40, 0.52, 0.78],
      "conf": 0.91,
      "dist_m": 1.84,
      "dist_lo": 1.62,
      "dist_hi": 2.06,
      "bearing_deg": -4.2,
      "is_target": true,
      "flags": ["wide_ci"]
    }
  ],
  "global_flags": []
}
```

| Field | Meaning |
|---|---|
| `xyxy_norm` | box `[x1,y1,x2,y2]` normalized + clamped to `[0,1]` |
| `dist_m` / `dist_lo` / `dist_hi` | fused distance + CI; `null` when no distance |
| `is_target` | this detection is the followed cat |
| `flags` (per det) | `low_conf`, `wide_ci`, `depth_geom_disagree`, `no_distance` |
| `global_flags` | `no_detections`, `no_frame` |

Per-detection flag thresholds default in `overlay.py` and are overridable from
`configs/web.yaml` `overlay:` (`low_conf`, `wide_ci_frac`, `disagree_frac`). They are
display heuristics, **not** scored core. See
[web-control-plane.md §6](../architecture/web-control-plane.md).
