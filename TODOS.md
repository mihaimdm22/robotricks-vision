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
- [x] **CV/Training tab + Tapo intrinsics/PTZ/calibration** (local-app-plan.md) — in-browser
  `prepare`/`train`/`autoresearch` orchestrator + run-history + promote; runtime camera-profile
  re-anchor + `scripts/calibrate_camera.py`; Tapo PTZ. **Completed:** v0.4.0 (2026-06-07).
- [ ] **Console smoke test runner** — no jest/vitest is configured in `apps/web`; `next build` static-prerenders `/console` as a render smoke. Add a component test runner if the console grows. **Priority:** P3.
- [ ] **In-console dataset form** — the Training tab exposes a `source` field; surface the Roboflow
  workspace/project/`ROBOFLOW_API_KEY` (and a fiftyone-presence check) as a form so prepare isn't a
  config-file edit. **Priority:** P3.
- [ ] **Real Tapo calibration numbers** — the re-anchor mechanism + `make calibrate` ship, but
  `configs/camera/tapo_c211.yaml` still has placeholder `fx/fy` (`needs_calibration: true`). Run the
  calibration with the physical C211 to write real intrinsics. **Priority:** P1 (on the rubric).
- [ ] Not building (explicitly out of scope): auth/TLS/public exposure, WebRTC video, in-browser
  annotation/labeling, session record/replay, native mobile, multi-robot, multi-GPU training.

### Vercel deploy follow-ups (deferred at the `vercel-deploy-plan.md` /autoplan gate — Shape A)
> Shipped in this plan: public **landing** on Vercel + the **local** console keeps
> working (runtime `API_BASE` from localStorage). The hosted-console workstream was
> cut because a public HTTPS console can't reach a LAN HTTP/no-auth robot backend.
- [ ] **Hosted-console error taxonomy** — typed `mixed_content` + `cors_blocked` + cert-fail states (distinct from generic `unreachable`), and a `/healthz` reachability probe (must treat `204`/`res.ok` as success, not parse a body). **Priority:** P3. Only worth it if a hosted console becomes a real target.
- [ ] **Public backend access (needs auth first)** — a TLS tunnel (Cloudflare Tunnel / Tailscale Funnel) to `catranger serve` would let a hosted console drive a robot, but CORS is **not** auth: today anyone with the public URL could drive. Gate behind real auth before exposing. **Priority:** P3 / blocked-on-auth.
- [x] **`apps/web` unit runner** — vitest added (`make web-test`); covers `lib/letterbox.ts` + `lib/badges.ts`. **Completed:** 10x branch (2026-06-07). Follow-up: add jsdom + an `API_BASE` resolution test (localStorage > env > default) + SSR `window`-guard. **Priority:** P3.

## CatRanger 10x follow-ups (`docs/02-CATRANGER-10X-PLAN.md`)
> The 10x branch landed WS-A (failure recovery A1–A7), WS-D0 (GT plumbing + scored
> keep/reject harness), WS-C (pluggable models/datasets), B0 overlay contract + B3
> `/api/jobs` backend, D1 (config-gated), and B1/B2 console overlays (logic unit-tested,
> render not yet eyeballed). What's left, grouped by what each NEEDS to proceed:

### Needs `/run` (live server + console)
- [ ] **Visually verify B1/B2 overlays** — start `catranger serve` + the Next console; confirm the target ring + distance label + failure badge land on the burned-in box across aspect ratios. The alignment math is unit-tested; the end-to-end render is not. **Priority:** P2.
- [ ] **B3 live sweep/eval panel (UI)** — a console panel consuming `GET /api/jobs` to show overnight sweeps + web evals (queued→running→ok/fail/timeout) live, with empty/loading/reconnecting states. Backend + `make jobs` done; this is the React UI. **Priority:** P2.

### Statically gateable (no app/ml needed)
- [ ] **B2 accessibility** — mirror failure badges into an `aria-live` region (canvas text is invisible to screen readers); keyboard story for layer toggles; honor `prefers-reduced-motion`. **Priority:** P3.

### Needs ml extra + ground-truth data (each gated by `make keepreject`)
- [ ] **D0.1 — capture a distance GT set** — tape-measured / HC-SR04 distances for ~30–60 frames → `data/eval/how_far.gts.json` (template: `configs/eval/how_far.gts.example.json`). Unblocks distance MAE; `make eval GTS=…` then prints a finite MAE. **Priority:** P1 (enables all of WS-D). Needs: real measured frames.
- [ ] **D1 — activate + tune the eroded-box median** — set `depth.box_erosion` and re-fit per-class `α`; keep only if `make keepreject` shows lower MAE vs the recorded baseline. **Priority:** P2. Needs: ml extra + D0.1.
- [ ] **D2 — locked-target ReID** — single OSNet appearance template for the followed cat to survive full occlusion / second-cat intrusion. **Priority:** P2. Needs: ml + a labeled occlusion clip (D0.3).
- [ ] **D3 — detector/edge** — add a `yolo26s` model profile (NMS-free, ~43% faster CPU); TensorRT-export detector + a ViT-Small depth backbone for the Go2 Orin NX. **Priority:** P2. Needs: ml (+ Jetson for TRT).
- [ ] **D4 — command smoothness** — temporal filter on per-track Z before the controller, so the deadband→EMA→slew chain fights less. **Priority:** P3. Needs: ml + GT.
- [ ] **D0.3 — de-proxy continuity/smoothness** — score track continuity against a hand-labeled occlusion clip (the existing `synthetic_occlusion_reacquire` hook) and pair the smoothness jerk metric with a tracking-lag term so harder damping can't win for free. **Priority:** P2. Needs: a labeled occlusion clip.

### Review follow-ups (from `/review`; may already be handled by the in-flight WS-A7 heartbeat work)
- [ ] **Collision-proof the web-eval `run_key`** — append a `uuid4` suffix in `runtime.start_eval`; `web-eval-<ms>` collides on a same-millisecond double-click, letting the busy-path settle mark the live eval "skipped". **Priority:** P3.
- [ ] **Snapshot `EvalJob._on_settle` under the lock** — it's read after the lock releases, racing a concurrent `start()` (microsecond window). **Priority:** P3.
- [ ] **Confirm the `recover_stale` / `complete_by_key` cross-owner contract** — now that the progress-heartbeat keeps a live web eval's lease fresh, decide whether the overnight runner should ever reclaim a `web`-owned row, or whether `fail_orphans('web')` is the sole recoverer of web evals. **Priority:** P3.
