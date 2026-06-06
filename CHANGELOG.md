# Changelog

All notable changes to CatRanger are documented here.

## [0.3.0] - 2026-06-07

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
