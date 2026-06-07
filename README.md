# CatRanger 🐈‍⬛📏

**Detect a cat, keep its identity, and say exactly how far it is — from one ordinary camera.**

Monsson hack-a-ton 2026 entry. Combines two Monsson challenges into one product:
**Cat Tracker** (detect + track) + **How Far?** (monocular metric distance). Runs on the
Unitree Go2 inference set, on a live Tapo C211, or any webcam/video; optionally drives an
Arduino robot to follow the cat at a safe distance.

> Built on pretrained perception + classical camera geometry — **no training required to
> run.** A Karpathy-style fine-tune is an optional, time-boxed stretch (see
> [Training](#training)). Engineering rules in [`CLAUDE.md`](CLAUDE.md).

---

## What it does

```
camera ─► undistort (120° FOV) ─► DETECT (YOLO11 / RT-DETR) ─► TRACK (BoT-SORT + ReID)
                                          cat = COCO class 15        stable track IDs
                                                                          │
                              ┌───────────────────────────────────────────┤
                              ▼                                           ▼
                  DISTANCE (pinhole + metric depth, fused)       FOLLOW control
                  Z = fy·H_real / h_px  ⊕  Depth-Anything-V2       (dx, dy, rotation)
                  → meters ± confidence interval                   smooth, anti-oscillation
                              │                                           │
                              └──────────► overlay + JSON + report ◄──────┘
                                                    │
                                       (optional) Arduino robot + HC-SR04 ground truth
```

Two interchangeable detector **approaches** (the deck's "min 2 approaches" requirement):

| | Approach A | Approach B |
|---|---|---|
| Detector | **YOLO11s** (CNN, fast) | **RT-DETR-l** (transformer, NMS-free) |
| Tracker | ByteTrack | BoT-SORT + ReID (identity through full occlusion) |
| Pick when | latency / smoothness | cluttered / occluded scenes |

Distance fuses two independent estimates so it stays honest:
- **Geometry:** `Z = fy · H_real / h_pixels` with per-class real-size priors, weighted by how centered the box is (barrel distortion grows at the edges).
- **Metric depth:** Depth-Anything-V2 (metric, indoor) or UniDepthV2 (ingests the camera `K` → true metric + confidence), sampled inside the box.
- **Fused** via a confidence-weighted median, with a **confidence interval** from the estimator spread + split-conformal residuals.

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

## Web control panel

A browser console to drive the robot by hand, toggle autonomous follow, hot-swap the
detector, manage the camera + Bluetooth links, and run eval — from any device on the same
LAN. The scored perception core is untouched. The UI is a **Next.js app** (`apps/web`);
**FastAPI** (`catranger serve`, the `web` extra) is the headless API behind it.

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
(see `apps/web/README.md`).

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
| **Connections** | camera (`synthetic` \| webcam `0` \| `rtsp://…`) + robot (`bt` HC-05 / `ble` HM-10 / `usb`) with device auto-discovery; a failed real link shows honestly as a simulation fallback, never a false "connected" |
| **Eval** | run the eval pipeline over a recorded source → metric cards + the full `report.md` (FPS / tracking / smoothness; distance MAE when labels are supplied). Refused unless IDLE (it's heavy). |

Config lives in `configs/web.yaml` (host, port, fps cap, watchdog, CORS origins, control
token timeout) and `configs/models.yaml` (the registry). Cat detection needs the `ml`
extra; without it the console still streams video and drives by hand. Pre-fetch weights for
an offline demo with `make fetch-weights`. Camera over RTSP needs a Tapo **Camera Account**
(not your cloud login); HC-05 over Bluetooth is **9600** baud (see Hardware).

> The legacy zero-Node panel is still served at `http://<laptop-ip>:8080/` as a fallback
> for a live demo with no Node toolchain. The Next.js console at `:3000` is the primary UI.

**Deploy:** the marketing **landing** deploys to Vercel as a public site (Root
Directory `apps/web`); the **console stays local** — a public HTTPS page can't reach
a LAN/no-auth robot backend. See `apps/web/README.md` → *Deploy to Vercel*.

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
the heavy GPU/model paths are import-smoke-tested in CI. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## How the camera geometry works (the part that decides the score)

The Go2 intrinsics are given (`configs/camera/go2_1080p.yaml`): `fx=fy=554.3, cx=960,
cy=540`, 120° FOV, mounted ~30 cm off the floor. Two consequences we handle:

1. **Barrel distortion.** No distortion coefficients are provided, so we rectify with a
   one-parameter **FOV/division model** derived from the known 120° (`catranger/intrinsics.py`),
   then do pinhole math on the rectified frame. Edge objects are down-weighted.
2. **Known mount height = a free, label-free scale anchor.** We can fit the floor plane and
   force it to sit at 0.30 m to sanity-check metric scale on the unlabeled stills.

Switch cameras with `--camera`. The Tapo C211 has different intrinsics → it is flagged
`needs_calibration: true` and must be re-anchored before its distances are trusted.

---

## Training

Policy (see [`CLAUDE.md`](CLAUDE.md)): **the pretrained baseline always works** — it is the
guaranteed demo. Fine-tuning is a stretch, hard time-boxed, and never blocks the demo.

```bash
uv run catranger prepare        # download + format a cat dataset (Roboflow / Open Images)
uv run catranger train          # fine-tune YOLO from pretrained weights (one frozen metric: val mAP50-95)
uv run catranger autoresearch   # karpathy/autoresearch-style keep/reject loop over hyperparams
```

"Karpathy" here = a minimal single-file `train.py` + a frozen-metric keep/reject loop
(`catranger/train/autoresearch.py`, directions in `catranger/train/program.md`). We
**fine-tune**, we do not train from scratch (no labels, no time, worse generalization).
After training, point `detector.finetuned_weights` in `configs/cat_distance.yaml` at the
new `best.pt` and the demo uses it automatically.

### Overnight runs (unattended train + eval, archived to history)

Run the whole sweep + eval plan unattended, then wire in the winner in the morning:

```bash
make overnight        # run configs/overnight.yaml unattended; archive every run to runs/history/
make history          # in the morning: print the run-history index (runs/history/INDEX.md)
make promote          # wire the fine-tune winner into the pipeline (gated; asks first)
make promote-revert   # one-command rollback to the pretrained baseline
```

- **Plan** lives in [`configs/overnight.yaml`](configs/overnight.yaml): a list of `autoresearch` /
  `train` / `eval` jobs. Per-trial time budget and the training device (`mps`) live in
  `configs/train.yaml`.
- **Resilient by design**: each job runs in its own subprocess, so a torch segfault, an OOM,
  or a missing dataset takes down only that job — never the whole night. If the cat dataset
  isn't prepared, training jobs are *skipped* (logged) and the baseline evals still run.
- **History** is on-disk under `runs/history/` (gitignored — local, but stores everything):
  one timestamped dir per run with `meta.json`, `params.json`, `metrics.json`, the captured
  `run.log`, and copied artifacts (`best.pt` / `report.md`), plus an append-only `index.jsonl`
  and a rendered `INDEX.md`.
- **Promotion is gated** (the hard rule): `make promote` shows the winner + the keep/reject
  trial log and asks before editing `configs/cat_distance.yaml`; the baseline is always one
  `make promote-revert` away.

---

## Hardware — fully wireless (live-demo prop, not what's scored)

The prize is scored on Go2 footage; the Arduino+Tapo rig is a 90-second wow demo. The
laptop is the single hub and talks to **both** devices wirelessly — no Raspberry Pi
gateway needed. See `docs/research/hardware-and-strategy.md`.

```
   Laptop (CatRanger)
     ├── Wi-Fi / RTSP ─────────►  Tapo C211      (camera frames)
     └── Bluetooth    ─────────►  Arduino Mega    (motors / servo / HC-SR04)
                                  + BT module on Serial1
```

**Camera — Tapo C211 over Wi-Fi** → `catranger/hw/tapo.py` (RTSP frames + optional
pan/tilt via `pytapo`). Run on it directly:
```bash
python scripts/demo.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" --camera tapo_c211 --show
```

**Robot — Arduino over Bluetooth** → `arduino/cat_ranger/cat_ranger.ino` +
`catranger/hw/{serial_bridge,bluetooth}.py`. Same `C dx dy rot pan` / `D <cm>` protocol
on every transport. Wire the BT module to the Mega's **Serial1** (USB stays free):

| Your module | Type | How the laptop connects | Command |
|---|---|---|---|
| **HC-05 / HC-06** | Bluetooth Classic (SPP) | OS exposes it as a **serial port** → the existing serial bridge works as-is | `--connection bt --hw-port /dev/cu.HC-05... --baud 9600` |
| **HM-10 / HM-19 / AT-09** | BLE | GATT via `bleak` (`pip install bleak`) | `--connection ble --ble <address>` |
| USB cable (no BT) | wired | serial | `--connection usb --hw-port /dev/ttyACM0` |

> HC-05 (Classic SPP) is the easiest: pair it once, point `--hw-port` at the Bluetooth
> serial device, done — **zero firmware change**. Its factory baud is **9600** (not 115200).

**The HC-SR04 is your secret weapon:** ±1 cm ground truth, so on stage your model says
"1.84 m" while the sensor confirms "1.86 m" — exactly the methodological rigor the How
Far jury rewards. It also enforces a hard safe-distance stop in firmware.

Compute split: **laptop = brain** (detection / depth / control) · **Arduino = motors +
sensor** (over Bluetooth) · **Tapo = eyes** (over Wi-Fi).

---

## Deliverables map (Monsson rubric → where it lives)

| Rubric item | Where |
|---|---|
| Git repo: code + README + run instructions | this repo |
| Demo on the provided inference set | `scripts/demo.py`, `notebooks/demo.ipynb` |
| Minimum 2 approaches compared | `--approach A\|B`; `catranger/eval/` |
| Performance report | `make eval` → `outputs/report/report.md` |
| 5-min pitch (architecture, decisions, trade-offs) | `docs/00-AUDIT.md`, `docs/01-RESEARCH-ARCHITECTURE.md` |

## Repo layout

```
catranger/            # the package
  intrinsics.py        # camera geometry, FOV undistort, back-projection
  detect.py track.py   # YOLO / RT-DETR + BoT-SORT/ByteTrack
  depth.py             # Depth-Anything-V2 / UniDepthV2 metric depth
  distance.py          # pinhole + depth fusion → meters ± CI
  pipeline.py          # the orchestrator (CatRanger)
  control.py           # follow controller (anti-oscillation + state machine)
  viz.py  io.py config.py types.py cli.py
  eval/                # metrics + performance report
  train/               # prepare / train / autoresearch (Karpathy fine-tune)
  hw/                  # tapo.py, serial_bridge.py
arduino/cat_ranger/    # Arduino sketch
configs/               # camera + task + train YAML
docs/                  # audit + research + per-challenge architectures
scripts/               # demo.py, setup_data.py
```

See `docs/01-RESEARCH-ARCHITECTURE.md` for the full, fact-checked design rationale.
