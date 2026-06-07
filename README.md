<div align="center">

<img src="docs/assets/landing-hero.png" alt="CatRanger — track every move" width="100%">

# CatRanger 🐈‍⬛📏

**Detect a cat, keep its identity, and say exactly how far it is — in meters, with an honest
confidence interval — from one ordinary camera. Then see where it will be, and follow it.**

[![CI](https://github.com/mihaimdm22/robotricks-vision/actions/workflows/ci.yml/badge.svg)](https://github.com/mihaimdm22/robotricks-vision/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-2A6DB2)](https://mypy-lang.org/)
[![Web: Next.js 16](https://img.shields.io/badge/web-Next.js%2016-000000?logo=nextdotjs)](apps/web)
[![Monsson hack-a-ton 2026](https://img.shields.io/badge/Monsson-hack--a--ton%202026-ff6b1a)](https://hackaton.ambasada.pro/)

</div>

CatRanger is a single computer-vision system that **implements and adapts two official
[Monsson hack-a-ton 2026](https://hackaton.ambasada.pro/) challenge themes** — *How Far?*
and *Cat Tracker* — into one product. From one ordinary camera it detects a cat, holds its
identity through occlusion, estimates the metric distance with a calibrated confidence
interval, predicts where the cat is heading, and (optionally) drives an Arduino robot to
follow it at a safe distance. It runs on the Unitree Go2 inference set, on a live Tapo C211,
or on any webcam/video.

> **No training required to run.** CatRanger is built on pretrained perception plus classical
> camera geometry, so the baseline is the guaranteed demo. A Karpathy-style fine-tune is an
> optional, time-boxed stretch on top — it never blocks the demo (see [Training](#training-fine-tune-keepreject)).
> Engineering rules: [`CLAUDE.md`](CLAUDE.md).

> 📚 **Full documentation** — architecture deep-dives, API/config/CLI reference, and a
> step-by-step install/link/test manual — lives in **[`docs/README.md`](docs/README.md)**.
> New here? Start with the [Architecture Overview](docs/architecture/overview.md) or the
> [Install & Test Manual](docs/guides/install-and-test.md).

---

## Table of contents

- [Two Monsson challenges, one system](#two-monsson-challenges-one-system)
- [What it does](#what-it-does)
- [Computer vision — the scored core](#computer-vision--the-scored-core)
- [Camera geometry (the part that decides the score)](#camera-geometry-the-part-that-decides-the-score)
- [Install](#install)
- [Quickstart](#quickstart)
- [Training (fine-tune, keep/reject)](#training-fine-tune-keepreject)
- [Web control panel](#web-control-panel)
- [Hardware — fully wireless](#hardware--fully-wireless)
- [Development](#development)
- [Deliverables map](#deliverables-map-monsson-rubric--where-it-lives)
- [Repo layout](#repo-layout)
- [License & acknowledgements](#license--acknowledgements)

---

## Two Monsson challenges, one system

CatRanger competes on two of the three Monsson challenges and **adapts them into a single
pipeline** — the cat is detected and tracked (*Cat Tracker*), and the same tracked box feeds
the monocular distance estimate (*How Far?*). The themes are Monsson's; the implementation is
ours.

### 🎯 [How Far?](https://hackaton.ambasada.pro/challenges/monsson-how-far/) — monocular metric distance

> Given a crop and its class, estimate how many meters away it is, accurately, from one image.
> Target: **MAE < 15%** on a hidden Go2 test set.

| How it's judged | How CatRanger addresses it |
|---|---|
| **MAE** on the hidden test set | Geometry ⊕ metric-depth fusion → meters; `make eval GTS=…` prints a finite MAE against ground truth |
| **Behavior at extreme distances** (out-of-distribution) | Per-class size priors + edge-box down-weighting (barrel distortion grows at the frame edges); a CPU-only geometry baseline (`--no-depth`) degrades gracefully |
| **Quality of the uncertainty estimate** | A real confidence interval from estimator spread **+ split-conformal residuals** — calibrated CIs, the challenge's stretch goal |
| **Methodological rigor** | A live HC-SR04 ultrasonic ±1 cm ground truth on the rig, deterministic seeds, and a frozen-metric keep/reject loop (no eyeballing) |

### 🐈 [Cat Tracker](https://hackaton.ambasada.pro/challenges/monsson-cat-tracker/) — detect, track, follow

> From a single robot camera, find the cat, keep its identity, and steer the robot to follow
> it at a safe distance, all in real time at **≥ 15 FPS**.

| How it's judged | How CatRanger addresses it |
|---|---|
| **Detection accuracy** | YOLO11 or RT-DETR on the undistorted frame (cat = COCO class 15) |
| **Robustness to occlusion** | BoT-SORT **+ ReID** keeps identity through full occlusion — the challenge's stretch goal |
| **End-to-end latency** | Profiled FPS; the YOLO11s + ByteTrack path is the low-latency option |
| **Command quality** (smooth, no oscillation) | An anti-oscillation follow controller emitting `(dx, dy, rotation)`, smoothed, with a hard ultrasonic stop in firmware |
| **Predictive following** (stretch) | Per-track motion is extrapolated over an adjustable lead time — a ghost box shows the landing spot before the cat arrives |

---

## What it does

```mermaid
flowchart LR
    CAM["📷 One camera<br/>RTSP · webcam · video"] --> UND["Undistort<br/>120° FOV model"]
    UND --> DET["Detect<br/>YOLO11 / RT-DETR<br/>cat = COCO class 15"]
    DET --> TRK["Track<br/>BoT-SORT + ReID<br/>stable identity"]
    TRK --> DIST["Distance ± CI<br/>geometry ⊕ metric depth"]
    TRK --> PRED["Predict<br/>where it will be"]
    DIST --> OUT["Overlay + JSON report"]
    PRED --> CTL["Follow control<br/>dx · dy · rotation"]
    OUT --> HW[("Optional rig:<br/>Arduino robot + HC-SR04<br/>±1 cm ground truth")]
    CTL --> HW
```

<div align="center">

<img src="docs/assets/cv-annotated-frame.png" alt="An annotated CatRanger frame: a tracked cat at 1.84 m with its 95% CI, a predicted ghost box where it will be, and the HC-SR04 ground-truth reading" width="62%">

<em>What CatRanger produces: a tracked identity, a metric distance with a 95% CI, a predicted
"where it will be" box, and a live ground-truth cross-check.</em>

</div>

Two interchangeable detector **approaches** (the deck's "min 2 approaches" requirement):

| | Approach A | Approach B |
|---|---|---|
| Detector | **YOLO11s** (CNN, fast) | **RT-DETR-l** (transformer, NMS-free) |
| Tracker | ByteTrack | BoT-SORT + ReID (identity through full occlusion) |
| Pick when | latency / smoothness | cluttered / occluded scenes |

---

## Computer vision — the scored core

The perception core (`catranger/{intrinsics,detect,track,depth,distance,pipeline}.py`) is the
part that gets graded, so it is held to the frozen-metric discipline in [`CLAUDE.md`](CLAUDE.md):
minimum code, deterministic seeds, and config in YAML — never hard-coded numbers.

**Detect.** A pretrained detector finds the cat on the undistorted frame. "cat" is COCO class
15, so the baseline needs no training. Swap detectors by id (`--model`) — YOLO11 (CNN) or
RT-DETR (transformer, NMS-free).

**Track.** BoT-SORT + ReID (or ByteTrack for the fast path) assigns a stable track id and
holds it through partial **and full** occlusion, measured as track breaks per sequence.

**Distance ± CI.** Distance fuses two **independent** estimates so the number stays honest:

```mermaid
flowchart TB
    BOX["Detected box + class"] --> GEO["Geometry<br/>Z = fy · H_real / h_px<br/>per-class size priors"]
    BOX --> DEP["Metric depth<br/>Depth-Anything-V2 / UniDepthV2<br/>sampled inside the box"]
    GEO --> FUSE{"Confidence-weighted median"}
    DEP --> FUSE
    FUSE --> CI["meters ± CI<br/>estimator spread + split-conformal residuals"]
```

- **Geometry:** `Z = fy · H_real / h_pixels` with per-class real-size priors, weighted by how
  centered the box is (barrel distortion grows at the edges).
- **Metric depth:** Depth-Anything-V2 (metric, indoor) or UniDepthV2 (ingests the camera `K`
  → true metric + per-pixel confidence), sampled inside the box.
- **Fused** via a confidence-weighted median, with a **confidence interval** from the
  estimator spread + split-conformal residuals.

**Predict & follow.** Per-track motion is extrapolated over a lead time (the "where it will
be" ghost box), and the anti-oscillation controller turns target position/size into smooth
`(dx, dy, rotation)` commands.

<div align="center">

<img src="docs/assets/landing-architecture.png" alt="The CatRanger pipeline and the two interchangeable detector approaches" width="88%">

</div>

Deep dive: [`docs/architecture/perception-core.md`](docs/architecture/perception-core.md) ·
[`docs/research/how-far.md`](docs/research/how-far.md) ·
[`docs/research/cat-tracker.md`](docs/research/cat-tracker.md).

---

## Camera geometry (the part that decides the score)

The Go2 intrinsics are given (`configs/camera/go2_1080p.yaml`): `fx=fy=554.3, cx=960,
cy=540`, 120° FOV, mounted ~30 cm off the floor. Two consequences we handle:

1. **Barrel distortion.** No distortion coefficients are provided, so we rectify with a
   one-parameter **FOV/division model** derived from the known 120° (`catranger/intrinsics.py`),
   then do pinhole math on the rectified frame. Edge objects are down-weighted.
2. **Known mount height = a free, label-free scale anchor.** We can fit the floor plane and
   force it to sit at 0.30 m to sanity-check metric scale on the unlabeled stills.

Switch cameras with `--camera`. The Tapo C211 has different intrinsics → it is flagged
`needs_calibration: true` and must be re-anchored before its distances are trusted.

### Calibrating distance with the HC-SR04 (ground truth)

Distance is `Z = fy · H_real / h_px`, so a wrong focal length `fy` scales **every** reading
by a constant — calibration is all about anchoring `fy`. We anchor it against the rig's
**HC-SR04 ultrasonic sensor**, which streams the true distance as `D <cm>` at ~20 Hz (±1 cm)
over Bluetooth.

1. **Anchor `fy` (one-shot).** Put an object of known real height `H_real` in view, read the
   sonar's true distance `Z`, read the object's pixel height `h_px`, and solve
   `fy = h_px · Z / H_real`:
   ```bash
   make calibrate H=0.297 Z=2.0 PX=240   # A4 sheet (0.297 m) at the sonar's 2.0 m, 240 px tall
   ```
   `scripts/calibrate_camera.py` writes the solved `fx=fy` into the camera YAML and flips
   `needs_calibration: false`; re-select the profile in the console to re-anchor live. The
   sonar just replaces a tape measure for `Z` — same role, ±1 cm instead of hand-measured.
2. **Score it with a real MAE.** The provided stills ship unlabeled, so drop per-frame sonar
   readings into the ground-truth sidecar (`configs/eval/how_far.gts.example.json` →
   `data/eval/how_far.gts.json`, frame index → true meters) and `make eval … GTS=…` prints a
   finite distance **MAE**. Live, it is the honesty cross-check the *How Far?* jury rewards:
   the model says "1.84 m" while the sensor confirms "1.86 m".

The HC-SR04 is **independent ground truth, not online sensor-fusion** — the per-frame estimate
stays camera-only (geometry ⊕ depth). The sonar calibrates it, scores it, and (separately)
enforces a hard safe-distance stop in firmware.

---

## Install

Uses [uv](https://docs.astral.sh/uv/) — one tool, one lockfile:

```bash
uv sync              # core + dev toolchain into .venv  (alias: make install)
uv sync --extra ml   # + torch + ultralytics + transformers  (big; GPU recommended)
make doctor          # check what's installed + GPU
make data            # symlink the provided contest inference sets into data/raw/
```

No uv yet? `pipx install uv` (or see the uv docs). A pip-only host can regenerate a
pinned requirements file from the lockfile: `uv export --no-hashes > requirements.txt`.

A GPU is recommended for real-time. Without one, the geometry path still runs on CPU
(`--no-depth`), just without the depth-net fusion.

## Quickstart

```bash
# 1) distance on the provided Go2 stills (how_far inference set) → annotated frames
uv run python scripts/demo.py --source data/raw/how_far --save outputs/how_far_demo

# 2) live cat tracking + distance on a video / webcam
uv run python scripts/demo.py --source data/cat_demo.mp4 --approach A --show
uv run python scripts/demo.py --source 0 --approach B --show

# 3) on the Tapo C211 (re-anchor intrinsics first — see Hardware)
uv run python scripts/demo.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" --camera tapo_c211 --show

# 4) follow with the robot
uv run python scripts/demo.py --source 0 --control --hw-port /dev/ttyACM0
```

`make demo` runs #1 by default. `uv run catranger doctor` / `catranger info` inspect the env and config.

---

## Training (fine-tune, keep/reject)

Policy (see [`CLAUDE.md`](CLAUDE.md)): **the pretrained baseline always works** — it is the
guaranteed demo. Fine-tuning is a stretch, hard time-boxed, and never blocks the demo. We
**fine-tune** a pretrained YOLO; we do **not** train from scratch (no labels, no time, worse
generalization).

```mermaid
flowchart LR
    DS["Dataset<br/>Roboflow · Open Images · manual"] --> PREP["prepare.py<br/>→ data.yaml"]
    PREP --> TRAIN["train.py<br/>fine-tune yolo11s · seed · resumable"]
    TRAIN --> EVAL["eval<br/>frozen metrics + ground truth"]
    EVAL --> KR{"keep / reject<br/>vs baseline"}
    KR -->|"metric improves"| PROMOTE["promote.py<br/>wire in · gated · baseline-safe"]
    KR -->|"no improvement"| BASE["stay on baseline"]
    PROMOTE -. "make promote-revert" .-> BASE
```

```bash
uv run catranger prepare        # download + format a cat dataset (Roboflow / Open Images)
uv run catranger train          # fine-tune YOLO from pretrained weights (one frozen metric: val mAP50-95)
uv run catranger autoresearch   # karpathy/autoresearch-style keep/reject loop over hyperparams
```

"Karpathy" here = a minimal single-file `train.py` + a frozen-metric keep/reject loop
(`catranger/train/autoresearch.py`). After training, point `detector.finetuned_weights` in
`configs/cat_distance.yaml` at the new `best.pt` and the demo uses it automatically (or run
`make promote`).

<div align="center">

<img src="docs/assets/landing-training.png" alt="The CatRanger training story: baseline always runs, fine-tune a pretrained YOLO, keep only if the frozen metric moves, and a pluggable models/datasets stack" width="88%">

</div>

> **Prerequisite — a dataset.** `train`/`autoresearch` need a prepared dataset
> (`data/cat/`). `prepare` pulls one from **Roboflow** (set `dataset.roboflow.*` in
> `configs/train.yaml` + `ROBOFLOW_API_KEY`) or **Open Images** (`pip install fiftyone`).
> Until then the train commands stop with a clear "run prepare first". Pick the box's
> device with `--device cuda|mps|cpu` (default `mps` in `configs/train.yaml`); CPU works
> but is slow. NB: `scripts/setup_data.py` (`make data`) symlinks the contest *inference*
> sets for eval/demo — it is **not** a training dataset.

**The same operations are in the console** under the **CV → Training** tab (launch,
live progress, cancel, run-history, promote) — see [Web control panel](#web-control-panel).
Training there is IDLE-gated and shares one "heavy job" slot with eval; the pretrained
baseline keeps running throughout and is always one `make promote-revert` away.

### Overnight runs (unattended train + eval, archived to history)

Run the whole sweep + eval plan unattended, then wire in the winner in the morning:

```bash
make overnight        # run configs/overnight.yaml unattended; resumes if re-run after a crash
make jobs             # the live durable queue (queued/running/ok/fail/timeout); also GET /api/jobs
make history          # in the morning: print the run-history index (runs/history/INDEX.md)
make promote          # wire the fine-tune winner into the pipeline (gated; asks first)
make promote-revert   # one-command rollback to the pretrained baseline
```

- **Plan** lives in [`configs/overnight.yaml`](configs/overnight.yaml): a list of `autoresearch` /
  `train` / `eval` jobs. Per-trial time budget and the training device (`mps`) live in
  `configs/train.yaml`. `job_timeout_min` / `max_attempts` tune the watchdog + retries.
- **Crash-safe (durable queue).** The plan is a SQLite job queue (`runs/jobqueue.sqlite3`):
  each job is crash-isolated in its own subprocess with a wall-clock **timeout** (kills the
  whole process group, no orphaned dataloader workers), and **re-running resumes** — completed
  jobs are skipped, a job left running by a crash (reboot / OOM / ssh-drop) is recovered, and
  transient failures retry with backoff. `--fresh` re-runs the whole plan; if the cat dataset
  isn't prepared, training jobs are *skipped* and the baseline evals still run.
- **History** is on-disk under `runs/history/` (gitignored): one timestamped dir per run with
  `meta.json`, `params.json`, `metrics.json`, the captured `run.log`, and copied artifacts
  (`best.pt` / `report.md`), plus an append-only `index.jsonl` and a rendered `INDEX.md`.
- **Promotion is gated** (the hard rule): `make promote` shows the winner + the keep/reject
  trial log and asks before editing `configs/cat_distance.yaml`; the baseline is always one
  `make promote-revert` away.

### Measuring accuracy + extending

- **Distance MAE, measured.** The provided stills ship no distance labels, so MAE is skipped
  by default. Drop tape-measured / HC-SR04 distances into a GT sidecar (template:
  [`configs/eval/how_far.gts.example.json`](configs/eval/how_far.gts.example.json)), then
  `make eval GTS=data/eval/how_far.gts.json` prints a finite MAE.
- **Keep/reject on the frozen metric.** `make keepreject BASELINE=base.json CANDIDATE=cand.json`
  compares two `--metrics-json` eval runs and KEEPs a perception change only if it holds or
  improves the frozen metric (FPS faithful; MAE faithful once GT'd; continuity/smoothness are
  proxies). A scored-core change is gated, never eyeballed.
- **Add a model / dataset / backend on top.** A model is one entry in `configs/models.yaml`
  (visible to both the CLI `--model <id>` and the web Models tab); a dataset is one entry in
  `configs/datasets.yaml` (`make prepare DATASET=<id>`); a detector backend is one builder in
  `detect.py`. Copy-paste recipes in [`CONTRIBUTING.md`](CONTRIBUTING.md).

Deep dive: [`docs/architecture/training-and-reliability.md`](docs/architecture/training-and-reliability.md).

---

## Web control panel

A browser console to drive the robot by hand, toggle autonomous follow, hot-swap the
detector, manage the camera + Bluetooth links, and run eval — from any device on the same
LAN. The scored perception core is untouched. The UI is a **Next.js app** (`apps/web`);
**FastAPI** (`catranger serve`, the `web` extra) is the headless API behind it.

<div align="center">

<img src="docs/assets/console.png" alt="The CatRanger local control console: live video, drive pad, mode switch, camera PTZ, and Control/Models/Connections/CV tabs" width="92%">

<em>The local control console, shown in its safe disconnected state — it boots hardware-free
in <code>IDLE</code> with a latched E-stop until you start <code>catranger serve</code> and connect a robot.</em>

</div>

```bash
make web-setup            # uv sync --extra ml --extra web  +  pnpm install (apps/web)
make web                  # FastAPI :8080 + Next.js console :3000 together
# cross-platform equivalent (Windows/macOS/Linux):
uv run python scripts/web.py
```

Open **http://localhost:3000/console**. Two processes run: the Next.js console (`:3000`)
talks straight to the FastAPI API (`:8080`) over REST + one WebSocket + the MJPEG stream —
no proxy in the path. For phone/LAN access, set `NEXT_PUBLIC_API_BASE` to this laptop's LAN
IP (e.g. `http://192.168.1.42:8080`) and add it to `cors_origins` in `configs/web.yaml`
(see [`apps/web/README.md`](apps/web/README.md)).

It boots **safe and hardware-free**: a synthetic video source + a DummyBridge, mode `IDLE`
— nothing moves until you connect a robot and switch to MANUAL/FOLLOW. Safety is built in: a
watchdog dead-man's switch, a latched E-stop reachable from any client (even observers), a
single-controller drive token so two operators can't fight one robot, a persistent banner
that says *why* the robot stopped, distinct video stale/unreachable states, and the
firmware's 20 cm hard-stop underneath it all.

| Tab | What it does |
|---|---|
| **Control** | live video, press-and-hold drive pad (or W/A/S/D), IDLE/MANUAL/FOLLOW, speed + camera-pan sliders, E-stop; one operator holds the drive token, others observe + can request control |
| **Models** | hot-swap the detector from `configs/models.yaml` (YOLO11 ↔ RT-DETR ↔ a fine-tuned `best.pt`); the COCO baseline is the always-available default |
| **Connections** | camera (`synthetic` \| webcam `0` \| `rtsp://…`) **+ an intrinsics profile** (`go2_1080p` / `tapo_c211`) so distance re-anchors live; robot (`bt` HC-05 / `ble` HM-10 / `usb`) with device auto-discovery; a failed real link shows honestly as a simulation fallback, never a false "connected" |
| **CV** | two sub-views. **Eval**: run the eval pipeline over a recorded source → metric cards + the full `report.md` (FPS / tracking / smoothness; distance MAE when labels are supplied). **Training**: launch `prepare` / `train` / `autoresearch` as background jobs (live progress + log tail + cancel), browse `runs/history`, and **promote** a winner into both the pipeline and the Models tab. Both are heavy → refused unless IDLE. |

Config lives in `configs/web.yaml` and `configs/models.yaml`. Cat detection + training need
the `ml` extra; without it the console still streams video and drives by hand. Tapo distance
is only correct after calibrating its intrinsics — see [Hardware](#hardware--fully-wireless).

> The legacy zero-Node panel is still served at `http://<laptop-ip>:8080/` as a fallback
> for a live demo with no Node toolchain. The Next.js console at `:3000` is the primary UI.

**Deploy:** the marketing **landing** deploys to Vercel as a public site (Root
Directory `apps/web`); the **console stays local** — a public HTTPS page can't reach
a LAN/no-auth robot backend. See [`apps/web/README.md`](apps/web/README.md) → *Deploy to Vercel*.

---

## Hardware — fully wireless

The prize is scored on Go2 footage; the Arduino+Tapo rig is a 90-second wow demo (a live
prop, not what's scored). The laptop is the single hub and talks to **both** devices
wirelessly — no Raspberry Pi gateway needed. See [`docs/architecture/hardware.md`](docs/architecture/hardware.md).

```
   Laptop (CatRanger)
     ├── Wi-Fi / RTSP ─────────►  Tapo C211      (camera frames)
     └── Bluetooth    ─────────►  Arduino Mega    (motors / servo / HC-SR04)
                                  + BT module on Serial1
```

**Camera — Tapo C211 over Wi-Fi** → `catranger/hw/tapo.py` (RTSP frames + optional
pan/tilt via `pytapo`). RTSP needs a Tapo **Camera Account** (Tapo app → Advanced → Camera
Account), *not* your cloud login.

> **Calibrate before trusting Tapo distance.** `configs/camera/tapo_c211.yaml` ships
> placeholder `fx/fy` (`needs_calibration: true`), so distances on Tapo frames are
> guesses (the console flags them "uncalibrated") until you re-anchor:
> ```bash
> make calibrate H=0.297 Z=2.0 PX=240    # A4 sheet (0.297 m) at 2.0 m, 240 px tall
> ```

**Robot — Arduino over Bluetooth** → `arduino/cat_ranger/cat_ranger.ino` +
`catranger/hw/{serial_bridge,bluetooth,char_bridge}.py`. Wire the BT module to the Mega's
**Serial1** (USB stays free):

| Your module | Type | How the laptop connects | Command |
|---|---|---|---|
| **HC-05 / HC-06** | Bluetooth Classic (SPP) | OS exposes it as a **serial port** → the existing serial bridge works as-is | `--connection bt --hw-port /dev/cu.HC-05... --baud 9600` |
| **HM-10 / HM-19 / AT-09** | BLE | GATT via `bleak` (`pip install bleak`) | `--connection ble --ble <address>` |
| USB cable (no BT) | wired | serial | `--connection usb --hw-port /dev/ttyACM0` |

> HC-05 (Classic SPP) is the easiest: pair it once, point `--hw-port` at the Bluetooth
> serial device, done — **zero firmware change**. Its factory baud is **9600** (not 115200).

The flashed Adafruit Motor Shield sketch speaks a discrete `b/f/h/j` command set, so the host
drives it through `CharBridge` (`--connection char`). It streams the same `D <cm>` ground
truth; see [`docs/guides/arduino-bench-check.md`](docs/guides/arduino-bench-check.md) for the
pre-demo rig checklist.

**The HC-SR04 is your secret weapon:** ±1 cm ground truth, so on stage your model says
"1.84 m" while the sensor confirms "1.86 m" — exactly the methodological rigor the *How
Far?* jury rewards. It also enforces a hard safe-distance stop in firmware.

Compute split: **laptop = brain** (detection / depth / control) · **Arduino = motors +
sensor** (over Bluetooth) · **Tapo = eyes** (over Wi-Fi).

---

## Development

`uv sync` installs the dev toolchain (ruff, mypy, pytest, pre-commit). Run the full gate
with `make check`, or piecemeal:

```bash
make lint        # ruff check --fix
make format      # ruff format
make typecheck   # mypy
make test        # pytest + coverage (gate: 85% on the pure core)
uv run pre-commit install   # run the hooks on every commit
```

Tests cover the deterministic core (geometry, distance, metrics, control state machine);
the heavy GPU/model paths are import-smoke-tested in CI. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Deliverables map (Monsson rubric → where it lives)

| Rubric item | Where |
|---|---|
| Git repo: code + README + run instructions | this repo |
| Demo on the provided inference set | `scripts/demo.py`, `notebooks/demo.ipynb` |
| Minimum 2 approaches compared | `--approach A\|B`; `catranger/eval/` |
| Performance report | `make eval` → `outputs/report/report.md` |
| 5-min pitch (architecture, decisions, trade-offs) | [`docs/00-AUDIT.md`](docs/00-AUDIT.md), [`docs/01-RESEARCH-ARCHITECTURE.md`](docs/01-RESEARCH-ARCHITECTURE.md) |

## Repo layout

```
catranger/            # the package
  intrinsics.py        # camera geometry, FOV undistort, back-projection
  detect.py track.py   # YOLO / RT-DETR + BoT-SORT/ByteTrack
  depth.py             # Depth-Anything-V2 / UniDepthV2 metric depth
  distance.py          # pinhole + depth fusion → meters ± CI
  pipeline.py          # the orchestrator (CatRanger)
  control.py           # follow controller (anti-oscillation + state machine)
  eval/                # metrics + performance report
  train/               # prepare / train / autoresearch (Karpathy fine-tune)
  hw/                  # tapo.py, serial_bridge.py, char_bridge.py
  web/                 # FastAPI control plane (catranger serve)
arduino/cat_ranger/    # Arduino sketch
apps/web/              # Next.js landing + control console
configs/               # camera + task + train YAML
docs/                  # audit + research + per-challenge architectures
scripts/               # demo.py, setup_data.py, web.py
```

See [`docs/01-RESEARCH-ARCHITECTURE.md`](docs/01-RESEARCH-ARCHITECTURE.md) for the full,
fact-checked design rationale.

---

## License & acknowledgements

A Monsson hack-a-ton 2026 entry, June 5–7 2026, ThePlace · Mamaia. No formal open-source
license is declared yet, so default copyright applies (all rights reserved by the authors)
until one is added.

- **Challenge themes** *How Far?* and *Cat Tracker* are by **[Monsson](https://hackaton.ambasada.pro/)**
  for the Unitree Go2 Edu track — implemented and adapted here.
- Built on [Ultralytics](https://github.com/ultralytics/ultralytics) (YOLO11 / RT-DETR /
  BoT-SORT), [Depth-Anything-V2](https://github.com/DepthAnything/Depth-Anything-V2) /
  UniDepthV2, [uv](https://github.com/astral-sh/uv), and [Next.js](https://nextjs.org/).
- The team: see the [landing page](apps/web) `#team` section.
