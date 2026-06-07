# Install, Link & Test Manual

> **TL;DR** — Go from a clean checkout to a working CatRanger in four stages, each one
> verifiable before you move on: **(1) install** the right dependency tier, **(2) run the
> offline demo + tests** to prove the brain works, **(3) bring up the web console** with no
> hardware, then **(4) link the real camera and robot** and run the full follow demo. Every
> step ends with a *checkable goal* — a command whose printed output tells you it passed.
> If a stage fails, stop and fix it before continuing; the next stage assumes it.

```mermaid
flowchart LR
  s1["1 · Install<br/>uv + extras"] --> s2["2 · Verify offline<br/>demo + make check"]
  s2 --> s3["3 · Console<br/>(no hardware)"]
  s3 --> s4["4 · Link hardware<br/>camera + robot"]
  s4 --> s5["5 · Full follow demo"]
```

---

## 0. Prerequisites

| Need | Why | Check |
|---|---|---|
| **Python ≥ 3.11** | package floor (PEP 604 unions) | `python3 --version` |
| **[uv](https://docs.astral.sh/uv/)** | the only package manager used | `uv --version` |
| **git** | clone | `git --version` |
| **Node ≥ 18 + pnpm** | *only* for the Next.js console | `pnpm --version` |
| **Arduino IDE** (optional) | *only* to flash the robot | — |

```bash
git clone <repo-url> && cd rome      # the project root (contains Makefile, pyproject.toml)
```

> Everything below is run from the project root. `uv` creates and manages `.venv`
> automatically — you do **not** `pip install` or activate a venv by hand.

---

## 1. Install — pick your tier

The package is layered so the pure-math core installs with three tiny deps; heavy backends
are opt-in extras. Install only what you need.

| You want to… | Command | Pulls |
|---|---|---|
| Run tests / pure-math core only | `make install` | numpy, opencv, pyyaml + dev tools |
| Run detection / the demo / depth | `make install-ml` | + torch, ultralytics, transformers, lap |
| Run the web console | `make web-setup` | ml + fastapi/uvicorn + `pnpm install` (apps/web) |
| Acquire/format datasets + fine-tune | `uv sync --extra train` | + roboflow, fiftyone |
| Use real hardware (Tapo/serial) | `uv sync --extra hw` | + pyserial, pytapo |
| Use a BLE robot module | `uv sync --extra hw` then `uv pip install bleak` | + bleak |

**Recommended first install** (covers stages 2–3):

```bash
make web-setup        # = uv sync --extra ml --extra web  +  pnpm install in apps/web
make fetch-weights    # pre-download detector weights so the demo runs offline
make data             # symlink the provided contest inference sets into data/raw/ (optional)
```

**✅ Checkable goal:**
```bash
uv run catranger doctor        # lists installed backends + GPU
```
Expect a report that names the detector backend(s) and whether a GPU (CUDA/MPS) is present.
A missing backend here means the matching extra wasn't installed — fix before continuing.

---

## 2. Verify offline — prove the brain works (no hardware)

### 2a. Run the perception demo on the provided stills

```bash
uv run python scripts/demo.py --source data/raw/how_far --camera go2_1080p --save outputs/how_far_demo
# or simply:
make demo
```

**✅ Checkable goal:** the command prints a **per-cat distance in metres** for each frame
and writes annotated frames to `outputs/how_far_demo/`. A finite distance (e.g. `cat 1.84 m
[1.62, 2.06]`) means detect→track→distance is working end to end.

### 2b. Run the demo on a video / webcam (live tracking)

```bash
uv run python scripts/demo.py --source path/to/cat.mp4 --approach A --show   # CNN
uv run python scripts/demo.py --source 0 --approach B --show                 # webcam, RT-DETR
```
**✅ Checkable goal:** a window shows boxes that keep a **stable track ID** on a moving cat,
with a live distance readout.

### 2c. Run the quality gates

```bash
make check        # ruff format-check + ruff lint + mypy + pytest (coverage gate 85%)
```
**✅ Checkable goal:** all four legs pass. This is exactly what CI runs.

### 2d. Run an eval and read the frozen metrics

```bash
make eval                                   # FPS / continuity / smoothness on the stills
make eval GTS=configs/eval/how_far.gts.example.json   # + distance MAE (needs real GT to be meaningful)
```
**✅ Checkable goal:** the report prints a **finite FPS** and (with GT) a **finite MAE**
float. See [training-and-reliability.md](../architecture/training-and-reliability.md) for
what the numbers mean and the keep/reject loop.

---

## 3. Bring up the web console — no hardware

```bash
make web          # FastAPI :8080 + Next.js console :3000 together
# cross-platform equivalent:
uv run python scripts/web.py
```

Open **http://localhost:3000/console**.

It boots **safe and hardware-free**: a synthetic video source, a `DummyBridge`, mode
`IDLE` — nothing moves. Two processes run: the console (`:3000`) talks straight to the API
(`:8080`) over REST + one WebSocket + MJPEG.

**✅ Checkable goals (click through):**

1. **Video** — the Control tab shows the synthetic stream with overlays.
2. **API health** — `curl -s localhost:8080/healthz` returns `204`; `curl -s
   localhost:8080/api/status` returns JSON with `mode: "IDLE"`.
3. **Drive (simulated)** — switch to MANUAL, use the drive pad / W-A-S-D; telemetry shows
   the command changing. (Dummy robot → nothing physical moves.)
4. **E-stop** — press E-stop; the banner latches and explains *why* the robot stopped;
   RESET clears it.
5. **Models** — the Models tab lists `yolo11s` (baseline) and `rtdetr-l`; hot-swap works.
6. **Jobs** — `curl -s localhost:8080/api/jobs` (or `make jobs`) returns the queue.

> **LAN / phone access:** set `NEXT_PUBLIC_API_BASE` to this laptop's LAN IP (e.g.
> `http://192.168.1.42:8080`) and add it to `cors_origins` in `configs/web.yaml`. Bind host
> is `0.0.0.0` by default. See [`apps/web/README.md`](../../apps/web/README.md).

> **No-Node fallback:** a legacy zero-build panel is served at `http://<laptop-ip>:8080/`
> for a live demo with no Node toolchain.

---

## 4. Link the hardware

The laptop is the hub. Link the **camera over Wi-Fi** and the **robot over Bluetooth**
independently — each has its own verification. Background:
[hardware.md](../architecture/hardware.md).

### 4a. Camera — Tapo C211 over Wi-Fi (RTSP)

1. In the **Tapo app** → *Advanced* → **Camera Account**, set a username + password
   (this is the RTSP login, **not** your cloud account).
2. Find the camera's LAN IP (router admin or the Tapo app).
3. Build the URL: `rtsp://USER:PASS@CAM_IP:554/stream1` (1080p) or `…/stream2` (~360p).

```bash
uv run python scripts/demo.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" --camera tapo_c211 --show
```
**✅ Checkable goal:** live Tapo frames appear with detection boxes.

4. **Calibrate before trusting distance.** The Tapo profile ships placeholder `fx/fy`
   (`needs_calibration: true`), so the console flags its distances "uncalibrated".
   Photograph an object of known height `H` at known distance `Z`, read its pixel height
   `PX`:
   ```bash
   make calibrate H=0.297 Z=2.0 PX=240    # A4 sheet (0.297 m) at 2.0 m, 240 px tall
   ```
   **✅ Checkable goal:** `configs/camera/tapo_c211.yaml` now has real `fx=fy=PX·Z/H`; the
   console no longer flags Tapo distance as uncalibrated, and a re-measured known object
   reads within a few % of truth.

5. In the **console**: Connections tab → enter the RTSP URL → pick the `tapo_c211` profile
   (re-anchors distance live) → pan/tilt from the PTZ controls on the video pane.

### 4b. Robot — flash the Arduino firmware

1. Open `arduino/cat_ranger/cat_ranger.ino` in the Arduino IDE.
2. Confirm the link defines for your setup:
   - **Bluetooth module on Serial1** (default): `#define LINK Serial1` / `LINK_BAUD 9600`.
   - **USB cable**: `#define LINK Serial` / `LINK_BAUD 115200`.
3. Wire per [hardware.md §wiring](../architecture/hardware.md) (BT module TXD→D19,
   RXD←D18 *through a divider*, VCC→5V, GND→GND; servo signal→D9).
4. Flash to the Mega over USB.

**✅ Checkable goal:** open the Serial Monitor at the link baud; you should see `D <cm>`
lines streaming at ~20 Hz (the HC-SR04 distance; `-1` = out of range). Wave a hand in front
of the sensor and the number changes.

### 4c. Robot — bench-test the link first (no camera, no ML)

Before wiring the robot into the full pipeline, prove the link in isolation with
`scripts/test_link.py`. By default it **only sweeps the camera servo and prints the
HC-SR04 distance — no motor movement** (safe on a bench); add `--drive` to briefly pulse
the wheels.

```bash
python scripts/test_link.py --connection bt  --hw-port /dev/cu.HC-05-DevB --baud 9600  # HC-05
python scripts/test_link.py --connection ble --ble <BLE-ADDRESS>                       # HM-10
python scripts/test_link.py --connection usb --hw-port /dev/ttyACM0                    # USB
```

**✅ Checkable goal:** the servo sweeps and `D <cm>` values print — pairing, the serial/BLE
link, the `C dx dy rot pan` → `D <cm>` protocol, and the HC-SR04 are all confirmed.

### 4d. Robot — connect from the laptop

Pick the transport that matches your module:

| Module | Pair / find the device | Connect |
|---|---|---|
| **HC-05 / HC-06** (Classic SPP) | pair once in OS Bluetooth → it appears as a serial port (`/dev/cu.HC-05…` on macOS, `COMx` on Windows) | `--connection bt --hw-port <port> --baud 9600` |
| **HM-10 / AT-09** (BLE) | `uv pip install bleak`; find the address | `--connection ble --ble <address>` |
| **USB cable** | plug in | `--connection usb --hw-port /dev/ttyACM0` |

Discover available ports:
```bash
curl -s localhost:8080/api/robot/discover    # or use the Connections tab
```

In the **console** Connections tab, choose the transport + device. A failed real link shows
honestly as a **simulation fallback** — never a false "connected".

**✅ Checkable goal:** with the robot connected and mode MANUAL, a forward nudge moves the
wheels; the telemetry `D <cm>` matches the Serial Monitor. A too-close reading
(`< safe_stop_cm`) refuses to drive forward (firmware hard stop).

---

## 5. The full follow demo

With camera + robot linked and calibrated:

**From the console:** Control tab → switch to **FOLLOW**. The robot should turn toward the
cat and approach to `setpoint_distance_m` (1.5 m), backing off inside `safe_distance_m`.

**Or headless:**
```bash
uv run python scripts/demo.py --source "rtsp://USER:PASS@CAM_IP:554/stream1" \
    --camera tapo_c211 --control --connection bt --hw-port /dev/cu.HC-05... --baud 9600
```

**✅ Checkable goals:**
1. The robot **steers toward** the cat (rotation tracks bearing).
2. It **holds ~1.5 m** and backs off when too close.
3. Motion is **smooth** (no oscillation — the anti-oscillation pipeline is working).
4. The model distance and the HC-SR04 `D <cm>` **agree within a few cm** (your headline
   "1.84 m model / 1.86 m sensor" demo moment).
5. **E-stop** from any console client stops the robot instantly.

---

## 6. Test everything — the verification matrix

| Subsystem | Command / action | Pass criterion |
|---|---|---|
| Environment | `uv run catranger doctor` | backends + GPU reported |
| Perception math | `make demo` | finite per-cat distance printed |
| Tracking | demo `--show` on a video | stable track ID on a moving cat |
| Quality gates | `make check` | format/lint/types/tests all pass |
| Web tests | `make web-test` | vitest + tsc + eslint pass |
| Eval / metrics | `make eval [GTS=…]` | finite FPS (+ MAE with GT) |
| Keep/reject | `make keepreject BASELINE=… CANDIDATE=…` | exit 0 (keep) / 2 (reject) |
| Reliability | `make overnight` then `make jobs` | jobs reach terminal status; recovers if killed |
| API | `curl localhost:8080/healthz` | `204` |
| Camera link | demo on `rtsp://…` | live Tapo frames + boxes |
| Calibration | `make calibrate …` | known object reads within a few % |
| Robot link (bench) | `python scripts/test_link.py --connection … ` | servo sweeps; `D <cm>` prints |
| Robot link (drive) | Serial Monitor + MANUAL nudge | `D <cm>` streams; wheels move |
| Safety (sw) | drive toward an obstacle | SAFE state backs off |
| Safety (fw) | obstacle `< safe_stop_cm` | firmware zeroes motors regardless of command |
| Safety (E-stop) | press E-stop (any client) | robot stops, banner latches |
| Full follow | FOLLOW mode | steers + holds setpoint + smooth |

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `catranger doctor` shows no detector backend | `ml` extra not installed | `make install-ml` |
| Demo can't fetch weights | offline / first run | `make fetch-weights` while online |
| RTSP won't open | wrong account or URL | use the **Camera Account**, verify `CAM_IP`, try `/stream2` |
| Tapo distance looks wrong | placeholder intrinsics | `make calibrate H= Z= PX=` |
| HC-05 won't connect | wrong baud | use **9600**, not 115200 |
| Serial Monitor shows nothing | TX/RX swapped or no divider | TXD→D19, RXD←D18 *through divider* |
| "VIDEO STALE" in console | no fresh frame within `video_stale_ms` | check the camera link |
| Mode switch refused (409) | training holds the GPU, or E-stop latched | cancel training / press RESET |
| Console can't reach API | CORS / wrong API base | add origin to `cors_origins`, set `NEXT_PUBLIC_API_BASE` |
| Robot drifts / oscillates | follow gains | tune `kp_rot`/`ema_alpha`/`slew_max` in `configs/cat_distance.yaml` |

---

## 8. Where things live

| What | Path |
|---|---|
| Configs | `configs/` ([reference](../reference/configuration.md)) |
| Commands | `make` / `catranger` / `scripts/` ([reference](../reference/cli.md)) |
| API | `catranger/web/server.py` ([reference](../reference/api.md)) |
| Firmware | `arduino/cat_ranger/cat_ranger.ino` |
| Run history | `runs/history/INDEX.md` (`make history`) |
| Job queue | `runs/jobqueue.sqlite3` (`make jobs`) |
| Architecture | [docs/architecture/](../architecture/) |
