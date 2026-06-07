# Changelog

All notable changes to CatRanger are documented here.

## [0.7.0] - 2026-06-07

Integrate the team's **tested, on-the-rig** Arduino firmware (Adafruit Motor Shield,
single-char protocol) with the perception host, without rewriting the proven drive
logic. The host can now drive that rig and read its live HC-SR04 ground truth — pure
live-demo capability; the scored perception core is untouched (CLAUDE.md maintenance
scope). Also reconciles `pyproject.toml` (was 0.5.0) forward to the project version.

### Added
- **`CharBridge`** (`catranger/hw/char_bridge.py`) — host-side adapter that quantizes
  the smooth `Follower` command into the tested firmware's discrete `b/f/h/j`
  vocabulary, exposed through the existing `send`/`read_distance_cm`/`close` bridge
  contract so the already-bulletproof web controller drives the rig unchanged. Stateful
  (emits each mode char once, never per-frame), injectable clock, per-char debounce ≥
  the firmware's blocking-primitive duration, in-flight suppression, and a forward
  safety gate. Never uses autonomous `a` for follow (bearing-blind + no link-loss
  failsafe); the self-terminating `f` nudge means a dropped link coasts to a stop.
- **`open_link("char", ...)`** transport selector + `--connection char` in
  `scripts/test_link.py`, degrading to `DummyBridge` on any link failure.
- **Bench-test checklist** (`docs/guides/arduino-bench-check.md`) — the 5-minute
  pre-demo rig verification a teammate runs without reading code.
- 18 `CharBridge` unit tests (`tests/test_char_bridge.py`).

### Changed
- **Firmware** (`arduino/cat_ranger/cat_ranger.ino`) is now the team's tested sketch
  made canonical, with surgical additive changes only: emit `D <cm>` telemetry on the
  Bluetooth link (~10 Hz, no-echo `999` mapped to `-1`), move status acks to USB so
  they can't fragment `D` lines, refresh distance on the telemetry timer (not every
  loop), and **boot into manual mode** so a dropped bootstrap `b` never strands the
  rig ignoring drive commands. Drive/turn/sensor/RGB/buzzer/LCD logic untouched.
- `pyproject.toml` version reconciled 0.5.0 → 0.7.0 (it lagged the CHANGELOG).

## [0.6.0] - 2026-06-07

Landing "10x": the public site (`apps/web`) gains four content-driven sections that
tell the architecture and team story for the demo and deck, on the existing
mechanical-movement brand (glass/glow, drive-orange→motion-purple, Space Grotesk). No
new design tokens; the scored perception core is untouched (web-only, CLAUDE.md
maintenance scope).

### Added
- **Architecture section** (`#architecture`). The end-to-end pipeline as a six-stage
  flow (Capture → Undistort → Detect → Track → Distance → Predict & follow), the two
  interchangeable detector approaches (YOLO11s/ByteTrack vs RT-DETR-l/BoT-SORT+ReID),
  and the distance-fusion explainer (geometry `Z = fy·H/h_px` ⊕ metric depth →
  confidence-weighted median ± CI). Content sourced from the README so it stays honest.
- **Metrics proof band** (`#metrics`). The frozen-metric doctrine made visible —
  distance MAE (the scored metric), real-time FPS, track continuity through occlusion,
  and ±1 cm ultrasonic ground truth. Named dimensions, not invented numbers.
- **Team section** (`#team`). Four members with roles and profile links.
  `TeamAvatar` renders `public/team/<slug>.jpg` when present (build-time `fs` existence
  check, so missing photos never 404 via `next/image`) and falls back to a branded
  initials disc otherwise. Drop a JPG in and rebuild — no code change.
- **Docs section** (`#docs`). Go-deeper cards linking to the README/quickstart, the
  research & architecture doc, the audit, and this changelog.
- Six landing icons (`layers`, `gauge`, `users`, `book`, `linkedin`, plus existing) and
  refreshed nav + footer wiring for the new anchors.

## [0.5.0] - 2026-06-07

The "10x" reliability + extensibility release: unattended runs survive crashes, the
scored metric is measurable and gated, models/datasets are pluggable, and the live
console gains crisp overlays — merged with the v0.4.0 local-control app (CV/Training +
Tapo). The scored perception core (`intrinsics/distance/detect/depth/track/pipeline`)
stays surgical; new work is tooling/web/tests (CLAUDE.md maintenance scope). Planned and
reviewed via `/autoplan` (`docs/02-CATRANGER-10X-PLAN.md`).

### Added
- **Failure recovery (WS-A).** Durable SQLite job queue (`catranger/jobqueue.py`) with
  owner-scoped crash recovery: re-running `make overnight` resumes — completed jobs are
  skipped, a job left running by a crash is recovered, and transient failures retry with
  capped exponential backoff. A per-job wall-clock timeout kills the whole process group
  (`catranger/proc.py`), so a hung job/dataloader can't hang the night. Crash-safe
  artifacts (temp + `os.replace` + sha256, `history.py`). Training resume from `last.pt`
  (`train --resume`). The live queue is observable via `make jobs` / `GET /api/jobs`.
- **Prove the number (WS-D0).** A distance ground-truth sidecar (`make eval GTS=…`,
  template `configs/eval/how_far.gts.example.json`) makes distance MAE measurable, and a
  scored keep/reject harness (`make keepreject`) gates a config change on the FROZEN
  metrics (distance MAE, FPS, continuity, smoothness) — separate from the mAP autoresearch
  loop. First metric mover: a config-gated eroded-box depth median (`depth.box_erosion`).
- **Pluggable models & datasets (WS-C).** Detector backends are a builder dict in
  `detect.py` (no second list to keep in sync); a `configs/datasets.yaml` registry mirrors
  `models.yaml`; one model home (`--model` / `apply_profile`) so a fine-tune added once is
  visible to both the CLI and the web console. "Extending CatRanger" recipes in CONTRIBUTING.
- **Live console overlays (WS-B).** A crisp target ring + distance/ID/bearing labels and
  arbitrated, debounced failure badges drawn on a `<canvas>` over the MJPEG frame, from a
  new per-detection overlay-JSON contract on the telemetry socket. Object-contain
  alignment + badge logic unit-tested (vitest, `make web-test`).

### Changed
- Web training (the v0.4.0 CV tab) now flows through the durable job queue (`owner='web'`)
  like eval — recorded, heartbeated, and settled — so a training run shows in `/api/jobs`
  / `make jobs` and an interrupted run is surfaced on restart. Eval and training share one
  durable row + heartbeat (they are mutually exclusive on the single heavy-job slot).
- `_build_ranger` now loads a fresh `AppConfig` per model swap and re-anchors the camera
  profile through the shared `apply_profile` helper — so no stale class filter or camera
  leaks across swaps, and a failed build never leaves a half-mutated config.

### Fixed
- Switching models no longer leaks a prior model's class filter (which would silently drop
  every detection — a zero-recall failure). The console `BadgeDebouncer` no longer grows
  unbounded as tracks come and go. `proc.run_capped` bounds its post-kill pipe drain so a
  detached grandchild can't hang the runner.

## [0.4.0] - 2026-06-07

Local control app: a full in-browser **CV/Training** tab and **Tapo C211** camera
controls (intrinsics re-anchor + calibration + PTZ), built on the existing two-process
console. The scored perception core (`intrinsics/distance/detect/depth/track/pipeline`)
is untouched. Planned and reviewed via `/autoplan` (`local-app-plan.md`).

### Added
- **In-browser training orchestrator** (CV tab → Training): launch `prepare` / `train` /
  `autoresearch` as background **subprocess** jobs with live coarse progress + a log tail,
  a run-history table (`runs/history/`), and per-run **promote**. New
  `catranger/web/train_job.py` (state machine, injected runner — unit-tested),
  `catranger/train/runner.py` (process-group spawn + an independent cancel watcher that
  kills a stalled job so E-stop always frees the GPU), and `/api/train/{run,status,report,
  cancel,history,readiness}` + `/api/train/promote`. Eval and training share ONE
  heavy-job slot (mutually exclusive under a lock); both are IDLE-gated.
- **Tapo intrinsics re-anchor**: `/api/camera/connect` accepts a camera profile
  (`go2_1080p` | `tapo_c211`); the runtime rebuilds the ranger and atomically swaps it so
  distance is correct on Tapo frames. Telemetry carries `camera_profile` /
  `camera_calibrated`; the console shows a warn-toned, qualified ("~ uncalibrated")
  distance until the camera is calibrated.
- **Camera calibration helper**: `scripts/calibrate_camera.py` solves `fx = fy = h*Z/H`
  and writes `configs/camera/<cam>.yaml` (`make calibrate H=.. Z=.. PX=..`).
- **Tapo PTZ**: the runtime holds a `TapoCamera` handle for an active Tapo source;
  throttled, threadpooled `/api/camera/ptz[/preset]`; "Camera pan/tilt" controls on the
  video pane (the chassis turn is now "Body yaw"). PTZ is its own device — not
  drive-token-gated.
- **Single-source promote** (`catranger/train/promote.py`): atomic, comment-preserving
  write of `cat_distance.yaml:finetuned_weights` **and** a `configs/models.yaml` profile
  (+ live registry reload) so a promoted fine-tune is live in both the CLI pipeline and
  the console Models tab. `scripts/promote.py` delegates to it.
- `--device` flag on `catranger train` / `catranger autoresearch`.
- Tests: `tests/test_web_train_job.py`, `test_train_promote.py`,
  `test_calibrate_and_camera.py`, and training/PTZ/camera-profile/T1-gate route contracts
  in `test_web_server.py`.

### Changed
- **Safety**: switching to MANUAL/FOLLOW is refused (typed `train_active`, not a silent
  cancel) while a training job holds the GPU; E-stop and shutdown terminate the training
  subprocess group.
- **Credential hygiene**: rtsp credentials are redacted from telemetry / status / logs.
- Camera-connect failures on an rtsp source now report a specific cause (host unreachable
  vs RTSP refused → set a Tapo Camera Account) instead of a generic "unavailable".
- Console: the standalone Eval tab moves under a new **CV** tab (Eval / Training
  sub-toggle); `configs/web.yaml` gains `train_config` and `ptz_min_interval_s`.
- README + Makefile document the in-console training, Tapo calibration, and Camera Account.

### Notes
- The Tapo profile ships placeholder intrinsics (`needs_calibration: true`) — run
  `make calibrate` with the physical camera for accurate distance; the UI flags it until
  then. In-console dataset prep exposes a source field; Roboflow workspace/key still come
  from `configs/train.yaml` (a deeper in-UI dataset form is a fast-follow).

## [0.3.2] - 2026-06-07

Web control panel: a live distance-history chart and the operator UI restyled to the
CatRanger brand identity. No perception/geometry behavior changed; the control core and
`app.js` behavior are untouched.

### Added
- **Distance history** (`catranger/web/store.py`): a stdlib-`sqlite3` log of distance over
  time — model estimate ± confidence interval vs HC-SR04 ground truth — recorded from the
  control loop (throttled by `history_hz`) and persisted across restarts. New
  `GET /api/history?limit=&since=`. The write is wrapped so a sqlite error can never take
  down the control thread.
- **Live history chart** in the panel: a dependency-free `<canvas>` chart that backfills
  from `/api/history` on load, then appends live points from the telemetry WebSocket
  (estimate line + CI band + HC-SR04 line).
- Telemetry now carries the CI band (`target_dist_lo` / `target_dist_hi`).
- `tests/test_web_history.py` — `DistanceStore` record/recent (ordering, limit, since, nullable columns).

### Changed
- **Control panel restyled** to the mechanical-movement brand: drive orange + motion purple
  on a dark neon-glass canvas, Space Grotesk / Geist / Geist Mono (self-hosted in
  `static/fonts/`), radial glows + engineering grid. Safety affordances stay red/amber. No
  markup ids/classes/`data-*` or JS behavior changed.
- `configs/web.yaml`: added `history_db` and `history_hz`.

## [0.3.1] - 2026-06-06

Prepare the web frontend for Vercel deployment. Scope decided at an `/autoplan`
gate (Shape A): the **marketing landing** ships to Vercel as a public site; the
**control console stays a local tool** (a public HTTPS page can't reach a LAN/
no-auth robot backend). No Python touched — the scored perception core and the
control plane are untouched.

### Added
- **Runtime Backend URL** (`apps/web`): the console resolves its API origin at
  runtime — `localStorage` override > `NEXT_PUBLIC_API_BASE` (build default) >
  `http://localhost:8080` — so one build points at any LAN box without a rebuild.
  A "Backend URL" field in the Connections tab saves it; the change remounts the
  telemetry WebSocket + MJPEG stream against the new origin via
  `useSyncExternalStore` (SSR-safe, no hydration mismatch).
- **No-backend state**: the console shows a "runs locally" help banner (with a
  jump to the Backend URL field) instead of a wall of failed-fetch errors when no
  backend is reachable.
- **Vercel config**: `apps/web/vercel.json` (framework + pnpm commands),
  `packageManager` pin, a *Deploy to Vercel* README section (Root Directory
  `apps/web`, Node 22 in project settings, leave `NEXT_PUBLIC_API_BASE` unset).

### Changed
- **Landing honesty for a public URL**: the distance card is relabelled "Example
  readout" (was a pulsing "LIVE DISTANCE" mock); footer/nav links now point to
  real anchors and the repo (dead `href="#"` links removed, "Admin"/"Live demo"
  dropped); console CTAs link to run-locally docs, not a `/console` that can't
  reach a robot.
- Connection error messages now include the typed `cause`, not just problem + fix.

## [0.3.0] - 2026-06-06

Web platform M3 + M5, and the control console migrated to Next.js. The scored
perception core (`intrinsics/distance/detect/depth/track/pipeline`) is untouched.

### Added
- **M3 — Eval tab**: run the eval pipeline from the browser over a recorded source
  and render the report. `catranger/eval/report.py` now exposes a reusable
  `run_eval_job()` (the single heavy eval path, shared by the CLI `make eval` and
  the web); `catranger/web/eval_job.py` runs it in a background worker
  (idle/running/done/error/cancelled, one-at-a-time, cooperative cancel). Routes
  `POST /api/eval/run` · `GET /api/eval/status` · `GET /api/eval/report` ·
  `POST /api/eval/cancel`. Refused unless the robot is IDLE (it is CPU/GPU-heavy).
  Distance MAE/MAPE shows only when ground-truth labels are supplied.
- **M5 — control-plane hardening**: a single-controller drive token
  (`catranger/web/arbiter.py`) so one operator drives and others observe and can
  request control; **E-stop and reset are never gated by the token**. Device
  auto-discovery (`GET /api/robot/discover`, serial + BLE-availability). Offline
  weights pre-fetch (`scripts/fetch_weights.py`, `make fetch-weights`).
- **Next.js control console** (`apps/web`, `/console`): the full operator UI ported
  from the vanilla panel into React with the design system — persistent safety
  header (always-loud E-STOP), prioritized status banner, video pane with distinct
  stale/unreachable states, telemetry strip that greys out on link loss, press-and-
  hold drive pad (pointer-capture + window keyboard gated on focus + blur->stop),
  Models / Connections / Eval tabs, observer lock + "request control". Talks
  straight to FastAPI via `NEXT_PUBLIC_API_BASE` (no proxy); operational (non-glass)
  design variant; landing CTAs now open `/console`.
- **Cross-platform launcher** `scripts/web.py` + `make web` / `web-setup` (runs
  FastAPI + Next.js together on Windows/macOS/Linux); `apps/web/.env.example`,
  `.nvmrc`, Node `engines`.
- Tests: `tests/test_web_arbiter.py`, `tests/test_web_eval_job.py`, and
  eval/discovery/two-WS-arbitration route-contract cases in `tests/test_web_server.py`.

### Changed
- `catranger/web/server.py`: config-gated CORS (origins in `configs/web.yaml`), the
  WebSocket gates drive/mode intents through the arbiter while leaving E-stop/reset
  ungated, and telemetry is per-connection (`you_are_controller`). The legacy
  vanilla panel + `/` mount are kept as a zero-Node demo fallback.
- `configs/web.yaml`: `cors_origins`, `control_idle_timeout_s`.

### Fixed
- `tests/test_io.py`: natural-order assertion now uses `os.path.basename` so it
  passes on Windows (back-slash paths), not just POSIX.

## [0.2.0] - 2026-06-06

Repo hardening — the hack-a-ton entry is now a maintained project. No perception/geometry
behavior changed; the guaranteed pretrained demo is untouched.

### Added
- **Test suite** (`tests/`): 52 pytest cases over the deterministic core — camera geometry,
  distance fusion + the load-bearing weighted-median tie-break, the graded eval metrics,
  config resolution, data contracts, frame-source ordering, and the follow state machine
  (SEARCH/ACQUIRE/TRACK/COAST/SAFE). ~89% coverage on the pure core; CI gate at 85%.
- **Tooling via `uv`**: `uv.lock` for reproducible installs; dev toolchain in a PEP 735
  `[dependency-groups]`; torch pinned to the CPU index for lockability.
- **Ruff** lint + format and **mypy** type-checking (both configured in `pyproject.toml`,
  both clean), **pre-commit** hooks (ruff, mypy, nbstripout, large-file guard), and
  **GitHub Actions CI** (lint+types, pytest matrix on 3.11–3.13, CPU-torch import-smoke).
- `CONTRIBUTING.md`; `make` targets `lint` / `format` / `typecheck` / `test` / `check`.

### Changed
- **Python floor 3.9 → 3.11** (`requires-python`): the code already used PEP 604 unions.
- Package management moved from pip/`requirements.txt` to `uv` (single source of truth:
  `pyproject.toml` + `uv.lock`); README and Makefile updated.
- `control.Follower` gained an optional injectable `clock` (default unchanged) so the
  safety-critical lost-target timeout logic is deterministically testable.
- `CLAUDE.md`: added a "Maintenance mode" section scoping the frozen-metric doctrine to the
  perception core while exempting tooling/tests/CI/docs.

### Removed
- `requirements.txt` (replaced by `pyproject.toml` + `uv.lock`; regenerate with `uv export`
  if a pip-only host needs it) and the unused `typer` dependency.
- Linter-surfaced dead code: an unused `cx` local in `control.py` and a pointless walrus
  assignment in `scripts/demo.py`.

## [0.1.1] - 2026-06-06

### Fixed
- **`make eval` now produces the performance report.** `catranger.eval.report` had no CLI
  entry point, so `make eval` exited silently without writing `outputs/report/report.md`.
  Added a `main()` driver that runs the pipeline over a `--source` and writes the report
  (FPS, track continuity, command smoothness; distance MAE when labels are supplied).
- **RT-DETR (approach B) no longer crashes on CPU.** FP16 (`half`) inference was passed to
  Ultralytics regardless of device, segfaulting the RT-DETR path on CPU/MPS (SIGSEGV).
  `half` is now forced off unless the device is CUDA, where FP16 is actually supported.
  This also speeds up approach A on CPU.

### Changed
- Tapo C211 camera config documents the manual focal-length re-anchor procedure instead of
  referencing a `catranger calibrate` command that does not exist.

## [0.1.0] - 2026-06-06

Initial CatRanger build for the Monsson hack-a-ton 2026 (Cat Tracker + How Far,
combined: detect a cat and say how far it is). Verified end-to-end on the provided
Go2 inference data with real models.

### Added
- **Perception pipeline** (`catranger/`): config-driven camera geometry (FOV undistort,
  pinhole back-projection), YOLO11 / RT-DETR detection with BoT-SORT/ByteTrack tracking,
  Depth-Anything-V2 / UniDepthV2 metric depth, geometry+depth fused distance with a
  confidence interval, follow controller (deadband → EMA → slew anti-oscillation),
  overlay viz, and a unified frame-source IO (image dir / video / RTSP / webcam).
- **Two compared detector approaches** (`--approach A|B`) per the deck requirement.
- **Eval + report** (`catranger/eval/`): FPS, track continuity, distance MAE, command
  smoothness → auto-generated `report.md`.
- **Karpathy-style training** (`catranger/train/`): minimal single-file YOLO fine-tune
  (never from scratch), an `autoresearch` frozen-metric keep/reject loop, and the
  engineering-discipline rules in `CLAUDE.md`. Baseline always runs; fine-tune is a
  time-boxed stretch.
- **Wireless hardware integration** (`catranger/hw/`, `arduino/`): Tapo C211 over
  Wi-Fi/RTSP; Arduino Mega over Bluetooth — HC-05/06 (Classic SPP, reuses the serial
  bridge) or HM-10 (BLE via `bleak`); HC-SR04 ground-truth distance + safe-stop firmware.
- **Demo + tooling**: `scripts/demo.py`, `scripts/test_link.py` (robot-link bring-up),
  `scripts/setup_data.py`, `Makefile`, `notebooks/demo.ipynb`, `catranger doctor` CLI.
- **Docs** (`docs/`): full audit, fact-checked SOTA research, and per-challenge
  architecture write-ups.

### Verified
- Real YOLO11 detection + multi-frame tracking on the provided `mental_map` clips.
- Depth-Anything-V2 metric depth + geometry fusion (suitcase ~1.06 m ±0.23).
- 1-epoch YOLO fine-tune via the training harness (frozen metric reported, weights published).
- Eval metrics, report generation, and the Bluetooth/serial link layer (incl. DummyBridge).

### Known limitations
- Real-time needs a CUDA GPU (CPU on Apple Silicon is ~0.3–0.4 FPS at 1080p; try `--device mps`).
- Tapo C211 intrinsics are a placeholder (`needs_calibration: true`) — re-anchor before trusting metric distance on Tapo frames.
- Dataset download (`catranger prepare`) needs a Roboflow API key or `fiftyone`; not exercised against real keys.
- BLE path and the physical robot were not tested against live hardware.
