# Configuration Reference

> **TL;DR** — Every tunable number lives in a YAML file under `configs/` — **never
> hard-coded** (Karpathy rule 5). Cameras, models, datasets, the perception/follow
> pipeline, the web server, training, and the overnight plan each have their own file.
> This page lists every file and key. Distance is only trustworthy on a **calibrated**
> camera; intrinsics are selected per camera, not baked in.

```
configs/
├── camera/go2_1080p.yaml      # contest camera intrinsics (trusted)
├── camera/tapo_c211.yaml      # demo camera intrinsics (PLACEHOLDER — calibrate!)
├── cat_distance.yaml          # the perception + follow pipeline (scored core)
├── models.yaml                # detector registry (web "Models" tab)
├── datasets.yaml              # dataset registry (prepare.py)
├── train.yaml                 # fine-tune + autoresearch knobs
├── web.yaml                   # FastAPI server + console + overlay
├── overnight.yaml             # unattended overnight plan
└── eval/how_far.gts.example.json   # ground-truth sidecar template
```

---

## `camera/*.yaml` — intrinsics

Selected with `--camera go2_1080p|tapo_c211` (CLI) or the `camera` field on
`/api/camera/connect`.

| Key | Go2 | Tapo | Meaning |
|---|---|---|---|
| `fx`, `fy` | `554.3` | `1100` *(placeholder)* | focal length px — sets the distance scale |
| `cx`, `cy` | `960`, `540` | `960`, `540` | principal point |
| `width`, `height` | `1920×1080` | `1920×1080` | sensor resolution |
| `fov_deg` | `120` | `110` | field of view (drives the FOV undistort) |
| `dist_model` | `none` | `fov` | `none` = trust centers; `fov` = one-parameter undistort |
| `mount_height_m` | `0.30` | `0.15` | camera height off the floor |
| `needs_calibration` | `false` | `true` | Tapo distances flagged uncalibrated until re-anchored |

> **Calibrate Tapo:** `make calibrate H=<m> Z=<m> PX=<px>` sets `fx=fy=PX·Z/H`. See
> [hardware.md §calibrate](../architecture/hardware.md).

---

## `cat_distance.yaml` — perception + follow (the scored core)

| Section | Key | Default | Meaning |
|---|---|---|---|
| top | `camera` | `go2_1080p` | intrinsics profile to load |
| top | `classes` | `[15]` | COCO ids to keep (15 = cat) |
| top | `class_names` | `{15: cat}` | id → label |
| `detector` | `approach_a` | `{yolo, yolo11s.pt}` | CNN detector (default; "min 2 approaches") |
| `detector` | `approach_b` | `{rtdetr, rtdetr-l.pt}` | transformer, NMS-free |
| `detector` | `conf` / `imgsz` / `half` | `0.35` / `640` / `true` | threshold / input size / FP16 |
| `detector` | `finetuned_weights` | `null` | overrides approach_a when training promotes a winner |
| `tracker` | `name` | `botsort.yaml` | BoT-SORT (or `bytetrack.yaml`) |
| `tracker` | `with_reid` | `true` | appearance ReID → identity through occlusion |
| `tracker` | `lock_hysteresis` | `5` | frames to switch the followed target id |
| `depth` | `enabled` | `true` | run the metric depth net |
| `depth` | `backend` | `depth_anything_v2_metric_indoor` | depth model (or `unidepth_v2`) |
| `depth` | `every_n` | `5` | run depth every Nth frame (protect FPS) |
| `depth` | `box_erosion` | `0.0` | WS-D1: shrink box before in-box depth median (0=off) |
| `size_priors` | `<class>` | per-class | `{cue: height|width, real_m, range_m:[lo,hi], weight}` |
| `follow` | `setpoint_distance_m` | `1.5` | distance to hold the cat at |
| `follow` | `kp_rot` / `kp_fwd` | `1.2` / `0.8` | yaw gain (rad) / forward gain (m) |
| `follow` | `deadband_rot` / `deadband_dist_m` | `0.05` / `0.20` | ignore tiny errors |
| `follow` | `ema_alpha` | `0.30` | smoothing (lower = smoother, more lag) |
| `follow` | `slew_max` | `0.15` | max command change per frame |
| `follow` | `lost_timeout_s` | `1.0` | coast this long before SEARCH |
| `follow` | `safe_distance_m` | `0.4` | software back-off / stop threshold |

> `box_erosion` and any prior tweak are **frozen-metric gated** — only change them if
> `make keepreject` shows the distance MAE improves.

---

## `models.yaml` — detector registry

Each entry is a hot-swappable profile in the console "Models" tab. The first/default
(`yolo11s`) is the **COCO baseline that always runs**.

| Key | Meaning |
|---|---|
| `default` | id of the boot model (must exist below) |
| `models[].id` / `name` | handle / human label |
| `models[].backend` | `yolo` \| `rtdetr` |
| `models[].weights` | bare handle (auto-download) or a `best.pt` path (fine-tune) |
| `models[].classes` | COCO ids to keep (single-class fine-tunes often remap cat→0) |
| `models[].tracker` | tracker yaml |
| `models[].dataset` / `notes` | provenance / guidance |

**Add a model:** add an entry, point `weights` at a `best.pt`. Only keep it if it beats
the baseline on the frozen metric. (Backends extend via `detect._BACKENDS`.)

---

## `datasets.yaml` — dataset registry

| Key | Meaning |
|---|---|
| `default` | dataset id used when none is passed |
| `datasets[].id` / `name` | handle / label |
| `datasets[].source` | `manual` \| `openimages` \| `roboflow` |
| `datasets[].params` | source-specific (e.g. `classes`, `max_samples`, Roboflow slugs + `api_key_env`) |
| `datasets[].notes` | deps / instructions |

**Add a dataset:** add an entry, then `make prepare DATASET=<id>`. Validated against
`prepare.source_names()` by `catranger/datasets.py`.

---

## `train.yaml` — fine-tune + autoresearch

| Section | Key | Default | Meaning |
|---|---|---|---|
| top | `base_model` | `yolo11s.pt` | pretrained starting point (never from scratch) |
| top | `data` | `data/cat/data.yaml` | Ultralytics dataset yaml (from `prepare.py`) |
| top | `epochs` / `imgsz` / `batch` | `40` / `640` / `16` | training schedule |
| top | `seed` | `0` | deterministic |
| top | `device` | `mps` | `mps` \| CUDA id \| `cpu` |
| top | `patience` | `12` | early stop |
| top | `metric` | `metrics/mAP50-95(B)` | the frozen number autoresearch optimizes |
| `dataset` | `source` + per-source blocks | `roboflow` | acquisition (`prepare.py`) |
| `autoresearch` | `budget_min` | `5` | minutes per experiment |
| `autoresearch` | `trials` | list of knob dicts | the keep/reject sweep grid |

---

## `web.yaml` — server + console + overlay

| Section | Key | Default | Meaning |
|---|---|---|---|
| server | `host` / `port` | `0.0.0.0` / `8080` | bind address (use `127.0.0.1` to lock to this machine) |
| video | `fps_cap` | `15` | publish/encode rate cap |
| video | `jpeg_quality` | `80` | MJPEG quality (lower = less bandwidth) |
| video | `video_stale_ms` | `1000` | "VIDEO STALE" threshold |
| history | `history_db` | `outputs/history.sqlite3` | distance-over-time log |
| history | `history_hz` | `4` | samples/sec persisted |
| overlay | `low_conf` | `0.40` | "low_conf" badge threshold |
| overlay | `wide_ci_frac` | `0.30` | "wide_ci" badge threshold |
| overlay | `disagree_frac` | `0.30` | "depth_geom_disagree" badge threshold |
| safety | `watchdog_timeout_s` | `0.5` | MANUAL dead-man's switch |
| safety | `safe_stop_cm` | `20` | UI mirror of the firmware hard stop |
| console | `control_idle_timeout_s` | `8` | drive-token idle release |
| console | `ptz_min_interval_s` | `0.3` | Tapo pan/tilt throttle |
| console | `cors_origins` | localhost:3000 | browser origins allowed to call `/api/*` |
| boot | `default_model` | `yolo11s` | boot model (must exist in `models.yaml`) |
| boot | `default_mode` | `IDLE` | never auto-arm motors |
| boot | `default_robot` | `dummy` | `dummy`\|`usb`\|`bt`\|`ble` |
| boot | `default_camera` | `synthetic` | webcam index / video path / rtsp url / `synthetic` |

> **Single worker, no reload:** one `RobotController` = one writer to the serial/BLE link;
> multiple uvicorn workers would race the bridge.

---

## `overnight.yaml` — unattended plan

| Key | Default | Meaning |
|---|---|---|
| `job_timeout_min` | `0` | per-job wall-clock cap (0 = none); timeout kills the whole process group → status `timeout` |
| `max_attempts` | `3` | transient-failure retry cap (capped exponential backoff); also bounds crash-recovery requeues |
| `jobs[]` | — | ordered steps: `{kind: autoresearch\|eval, config, source?, approach?, device?, timeout_min?}` |

Training jobs auto-skip if the cat dataset isn't prepared (baseline-first); evals still
run on the pretrained baseline.

---

## `eval/how_far.gts.example.json` — ground-truth sidecar

Template for the distance ground truth that turns proxy metrics into a **measurable MAE**.
Loaded by `eval/gts.py`; pass with `make eval GTS=<path>`. Pairs predictions to GT by
frame index (`align_preds_gts`). See
[training-and-reliability.md §2](../architecture/training-and-reliability.md).
