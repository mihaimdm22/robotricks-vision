# TODOS

Remaining work for the CatRanger Monsson hack-a-ton entry. Organized by component,
then priority (P0 = do first). The pretrained baseline already runs and is verified
end-to-end; everything below is polish, hardware bring-up, or stretch.

## Submission & Pitch
- [ ] **Generate the performance report on the provided inference set**
  - **Priority:** P0
  - `make eval` (or run `scripts/demo.py` over `data/raw/how_far` + a cat clip) → `outputs/report/report.md`. This is a graded deliverable: the 2-approach comparison + the numbers.
- [ ] **Run the demo notebook top-to-bottom on the provided data**
  - **Priority:** P0
  - `notebooks/demo.ipynb` must execute clean on `data/raw/` — it's the "demo on the provided mini inference set" deliverable.
- [ ] **5-minute pitch deck**
  - **Priority:** P0
  - Architecture diagram, the 2-approach comparison, trade-offs, the headline number, and a "how the team collaborated" note. Source material is in `docs/`.
- [ ] **Record a fallback demo video** of the robot following the cat
  - **Priority:** P1
  - Live hardware fails on stage; a clip never does. Show the clip, then attempt live as a bonus.

## Hardware bring-up (HC-05 / ZS-040)
- [ ] **Wire the HC-05 to the Mega Serial1 and bench-test the link**
  - **Priority:** P1
  - VCC→5V, GND→GND, TXD→RX1 (D19), RXD←TX1 (D18) via a 5V→3.3V divider (1k + 2k). Flash `arduino/cat_ranger/cat_ranger.ino` as-is.
  - Pair (PIN 1234/0000) → `python scripts/test_link.py --connection bt --hw-port /dev/cu.HC-05-XXXX --baud 9600` (servo sweep + HC-SR04 stream). Add `--drive` to test wheels.
- [ ] **Full wireless follow demo** (Tapo over Wi-Fi + robot over Bluetooth)
  - **Priority:** P1
  - `scripts/demo.py --source "rtsp://USER:PASS@IP:554/stream1" --camera tapo_c211 --control --connection bt --hw-port /dev/cu.HC-05-XXXX --baud 9600 --show`
- [ ] **HC-SR04 ground-truth "1.84 m vs 1.86 m" stage moment**
  - **Priority:** P2
  - The rigor flex for the How Far jury: model estimate vs ultrasonic GT, live.

## Camera & calibration
- [ ] **Re-anchor the Tapo C211 intrinsics**
  - **Priority:** P1
  - `configs/camera/tapo_c211.yaml` is a placeholder (`needs_calibration: true`). Hold a known-size object at a known distance, solve for the effective focal length, overwrite fx/fy. Wrong intrinsics = wrong meters on Tapo frames.

## Performance / runtime
- [ ] **Run on a CUDA GPU for real-time**
  - **Priority:** P1
  - CPU on Apple Silicon is ~0.3–0.4 FPS at 1080p. On a GPU it's 30–60+ FPS. Try `--device mps` on the Mac for a few× speedup in the meantime.
- [ ] **Optional: TensorRT / smaller depth model for the demo machine**
  - **Priority:** P3
  - `yolo export format=engine half=True`; or swap to a Depth-Anything-V2-Small variant if the demo box is weak.

## Training (stretch — never blocks the demo)
- [ ] **Download a cat dataset**
  - **Priority:** P2
  - `catranger prepare` — needs a Roboflow API key + project (set in `configs/train.yaml`), or switch `dataset.source: openimages` and install `fiftyone`.
- [ ] **Fine-tune YOLO on low-angle cats + run the autoresearch loop**
  - **Priority:** P2
  - `catranger train` then `catranger autoresearch` on the GPU. Go/no-go: only if the baseline is green and time allows. Point `detector.finetuned_weights` at the new `best.pt`.

## Testing & robustness
- [ ] **Test the BLE path against real hardware** (only if using HM-10, not HC-05)
  - **Priority:** P3
  - `pip install bleak`, then `--connection ble --ble <address>`. Not exercised yet (HC-05/SPP needs no new code).
- [ ] **Validate on actual cat footage**
  - **Priority:** P2
  - No local cat clips. Pull one with `scripts/setup_data.py --cat-url <url>` or point a webcam at a cat to tune `A_target`, conf, and the low-angle case.

## Completed
- [x] Build the full CatRanger pipeline (detect + track + monocular distance + control). **Completed:** v0.1.0 (2026-06-06)
- [x] Two compared detector approaches (YOLO11 / RT-DETR). **Completed:** v0.1.0 (2026-06-06)
- [x] Geometry + metric-depth fusion with confidence interval. **Completed:** v0.1.0 (2026-06-06)
- [x] Karpathy-style fine-tune harness + autoresearch keep/reject loop. **Completed:** v0.1.0 (2026-06-06)
- [x] Wireless hardware integration (Tapo Wi-Fi + Arduino Bluetooth/USB) + firmware. **Completed:** v0.1.0 (2026-06-06)
- [x] Eval metrics + auto performance-report generator. **Completed:** v0.1.0 (2026-06-06)
- [x] Full audit + fact-checked research + per-challenge architecture docs. **Completed:** v0.1.0 (2026-06-06)
- [x] Verified end-to-end on the provided Go2 data + shipped (PR #1). **Completed:** v0.1.0 (2026-06-06)

## Web Control Platform (post-/autoplan, deferred / follow-ups)
- [x] **Eval tab** (M3) — `run_eval_job` + background `EvalJob` + `/api/eval/*`; UI renders metric cards + report.md. **Completed:** v0.3.0 (2026-06-06).
- [x] **Single-controller token** (M5) — `ControlArbiter`, WS-gated drive intents, ungated E-stop. **Completed:** v0.3.0 (2026-06-06).
- [x] **Device auto-discovery** (M5) — `/api/robot/discover` + Connections pick-list. **Completed:** v0.3.0 (2026-06-06).
- [x] **Offline weights** (M5) — `scripts/fetch_weights.py` warms the ultralytics cache (`make fetch-weights`); weights stay gitignored. **Completed:** v0.3.0 (2026-06-06).
- [ ] **Console smoke test runner** — no jest/vitest is configured in `apps/web`; `next build` static-prerenders `/console` as a render smoke. Add a component test runner if the console grows. **Priority:** P3.
- [ ] Not building (explicitly out of scope): auth/TLS/public exposure, WebRTC video, in-browser training/annotation, session record/replay, native mobile, multi-robot.
