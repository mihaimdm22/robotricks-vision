# Changelog

All notable changes to CatRanger are documented here.

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
