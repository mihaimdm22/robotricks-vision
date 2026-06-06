# Changelog

All notable changes to CatRanger are documented here.

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
