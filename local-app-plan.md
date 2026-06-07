<!-- /autoplan restore point: /Users/davidmarin/.gstack/projects/mihaimdm22-robotricks-vision/delhi-autoplan-restore-20260607-060804.md -->
# CatRanger — Local control app: Arduino + Tapo + a CV/Training tab

> Status: draft 2026-06-07 on branch `delhi`. Request: "apps/web is the landing
> page deployed on Vercel (sussur.store). I want the rest of the app to run
> **locally** with Arduino control over **Bluetooth** (live demo) and **cable**
> (easy testing), control of the **Tapo C211** (`rtsp://Andrei:Andrei12@192.168.200.122:554/stream1`),
> and a **computer-vision training tab/page** that incorporates the CV and evals."
>
> The headline finding of this plan: **most of this already ships.** The honest
> job is to name the small real delta, not rebuild the console. DRY is law here.

---

## 1. What already ships (the leverage map — read this first)

A working local app already exists and was shipped across PRs #4–#9. Two
processes: `catranger serve` (FastAPI :8080) + Next.js `/console` (:3000),
launchable with one command (`make web` / `uv run python scripts/web.py`).

| Your ask | Already exists? | Where |
|----------|-----------------|-------|
| Runs locally | ✅ Yes | `scripts/web.py` (cross-platform), `make web`; landing on Vercel, console stays local (`vercel-deploy-plan.md` Shape A) |
| Arduino over **Bluetooth** (live demo) | ✅ Yes | Connections tab → `bt` (HC-05 SPP, 9600) and `ble` (HM-10/bleak); `catranger/hw/bluetooth.py:open_link`, `/api/robot/connect` |
| Arduino over **cable** (testing) | ✅ Yes | Connections tab → `usb` serial (115200); `catranger/hw/serial_bridge.py:ArduinoBridge`; bench tool `scripts/test_link.py` |
| Device discovery / pick-list | ✅ Yes | `GET /api/robot/discover` (serial ports + BLE availability) |
| **Tapo C211** as camera feed | ⚠️ Partial | Connections tab camera field accepts `rtsp://…`; `/api/camera/connect` opens it via OpenCV+FFmpeg (RTSP-over-TCP). **Gap: intrinsics — see §3.** |
| **Eval** in the browser | ✅ Yes | Eval tab → `/api/eval/{run,status,report,cancel}`, background `EvalJob`, metric cards + report.md |
| **Training** in the browser | ❌ No | CLI only: `catranger prepare/train/autoresearch`, `scripts/overnight.py`, archive in `runs/history/`. **In-browser training was an explicit non-goal** (web-platform-plan §7, TODOS) |
| Safety core (E-stop, watchdog, drive token, modes) | ✅ Yes | `controller.py`, `arbiter.py`, server WS; E-stop/reset ungated |
| Model hot-swap | ✅ Yes | Models tab → `/api/models`, `/api/models/select`; `configs/models.yaml` |

**Frozen perception core (untouched — CLAUDE.md law):**
`catranger/{intrinsics,distance,detect,depth,track,pipeline}.py`. Frozen metrics:
distance MAE, track continuity, FPS, command smoothness. This plan surfaces and
feeds them; it does not edit them.

## 2. Goal + success criteria (checkable)

Close the small real gap between "what the user pictured" and "what ships":
make the Tapo usable with **correct distance**, and add a **CV/Training surface**
that orchestrates the existing train/autoresearch/eval/history code — without
rebuilding any of it, and without ever blocking the guaranteed pretrained demo.

1. In the running console, connecting the Tapo RTSP URL **and** selecting the
   `tapo_c211` camera profile re-anchors distance at runtime (no server restart);
   telemetry shows which camera profile is active. (Distance correctness.)
2. A Training tab can launch a fine-tune (`train`) and the keep/reject sweep
   (`autoresearch`) as a **background job** (mirrors `EvalJob`: idle→running→
   done→error, one-at-a-time, **IDLE-gated**, cancellable, live progress + log
   tail), and shows the `runs/history/` run table. The pretrained baseline keeps
   running the whole time; training never grabs the live camera/serial.
3. A finished fine-tune can be **promoted** to a `configs/models.yaml` profile so
   it appears in the Models tab (closes train→serve loop). The baseline profiles
   stay; promotion is additive.
4. `make check` (ruff + mypy + pytest) green; new core logic has tests;
   `next build` + `next lint` clean.

## 3. The genuine delta (everything new is here)

### 3a. Tapo intrinsics at runtime (distance-correctness bug, P1 — THE on-rubric win)
Today the web runtime hardcodes `app_config="cat_distance"` whose camera is
`go2_1080p` (`fx=fy=554.3`). Connecting the Tapo RTSP stream swaps the *pixels*
but keeps Go2 intrinsics → **every Tapo distance is wrong by a constant factor**
`fy_tapo/fy_go2` (`Z = fy·H/h_px`). The re-anchor site is
`runtime._build_ranger` → `load_app(self.app_config)`; the pattern to copy is the
CLI eval path `report.py:262-263` (`app.camera = load_camera(camera)`). The CLI
honors `--camera tapo_c211`; the web API does not.

- **Re-anchor = REBUILD the ranger, not "swap intrinsics under the source lock"
  (Eng C1, verified).** `CatRanger` freezes `CameraModel`→`DistanceEstimator` at
  construction (`pipeline.py:59,108`); the `_source_lock` guards only `_source`,
  and the control loop reads `_ranger` lock-free. So mutating `fx/fy` in place is
  a data race on the metric-critical object. The correct primitive is the one
  `select_model` already uses (`runtime.py:337-354`): thread the camera profile
  into `_build_ranger`, build a fresh ranger off-loop, then **atomically assign
  `self._ranger`**. `/api/camera/connect` accepts an optional `camera` profile
  (`go2_1080p` | `tapo_c211`); telemetry adds `camera_profile` + `calibrated`.
- **Calibration honesty is the on-rubric crux (Design F9 CRITICAL + DX 4.2 +
  CEO F4).** `tapo_c211.yaml` ships `fx/fy=1100` placeholders
  (`needs_calibration: true`). Today connect-success is **green** and the Distance
  stat is unqualified — so a dropdown alone ships a confident WRONG number, the
  exact failure this plan exists to prevent. Required: (1) real calibration
  numbers via a documented procedure **and a `--calibrate` helper promoted from
  optional to must-ship** (known-size object → solve `fx`); (2) the profile
  carries `calibrated` (from `needs_calibration`); (3) when uncalibrated, the
  connect message is **warn-toned, never green**, and the Distance stat is
  visibly qualified (e.g. "~ / uncalibrated"). Numbers live in YAML.
- **PTZ is more than "wiring" (Eng H5 + DX 2.4, verified).** The runtime never
  holds a `TapoCamera` — `connect_camera`→`open_source` opens generic OpenCV
  RTSP, so there is no `move()`/`preset()` handle to call. Fork 2-B requires the
  runtime to construct & hold a `TapoCamera` (which needs the **Camera Account**
  creds, parsed from the rtsp spec) when the active camera is a Tapo. PTZ routes
  run pytapo (blocking) via `run_in_threadpool`, throttled (min-interval, YAML),
  with a lock on the lazy handle; refuse PTZ when the active camera isn't a Tapo.

### 3b. CV/Training tab (the new feature the user asked for — OFF the frozen rubric)
> CEO review (verified in code) reshaped this section. The original "TrainJob
> mirrors EvalJob with cooperative cancel" was **false**: `train_once`
> (`train.py:143-144`) is a single opaque `model.train(**args)` Ultralytics call
> with **no cancel hook** — the only stop is killing the subprocess (a hard kill
> mid-epoch leaves the run dir undefined). And there is **no `data/` and no
> `runs/`** yet, so a fresh box's "Run training" button errors until someone runs
> dataset `prepare` (Roboflow key or OpenImages/fiftyone) out of band. Under
> CLAUDE.md's "one rule," this feature **moves nothing on the frozen metric** —
> it is demo garnish relative to §3a. Build it deliberately small and honest.

This is a console tab that **surfaces and optionally launches existing code** —
it reimplements nothing and reuses the shipped scripts (DRY is law):
`scripts/overnight.py` (subprocess job runner + dataset-readiness skip + history
archive), `catranger/history.py` (`runs/history/` archive, stdlib-only, zero-GPU),
`scripts/setup_data.py` / `catranger.train.prepare` (dataset), and
`scripts/promote.py` (the **canonical** promote path → writes
`configs/cat_distance.yaml:detector.finetuned_weights`, gated, `--revert`,
archives the decision).

Scope is the gate's Fork 1 (see §4). Whichever depth is chosen:
- **Reuse, never reinvent.** No net-new `TrainJob` with a false cancel promise.
  If launching, shell out to the existing overnight-style subprocess; if
  promoting, call into `scripts/promote.py`'s `_set_finetuned_weights`
  (refactor it to a callable) — do **not** invent a second `models.yaml` writer
  that diverges from `cat_distance.yaml` (CEO F3).
- **IDLE-gated** like eval (no training while the robot drives); the **pretrained
  baseline always runs** and is one `--revert` away (hard rule).
- Degrade gracefully with explicit states: "no dataset prepared", "no GPU / runs
  on CPU is slow", "ml extra absent". Cancel = subprocess terminate only, stated
  as such (no per-epoch cooperative cancel; that's an Ultralytics-callback change
  we are not making in the training core).
- The existing **Eval tab** sits beside it so the surface "incorporates the CV
  and evals" as asked.

### 3c. Training-tab UI spec (Design F1–F8 — the densest tab in the app)
The plan must hand the implementer a hierarchy, not a parts bin. Reuse the
**operational** design system (`op-surface`/`op-btn`, reserved stop/warn/ok/dim
palette) — never the marketing `.glass`/`.glow` aesthetic. Top-to-bottom order:
1. **Readiness strip (always first):** ml-extra ✓/✗, dataset ✓/✗ (with source),
   device, baseline-running ✓ — backed by a `/api/train/readiness` route that
   reuses `overnight._train_data_ready` so UI and runner agree.
2. **Launch panel** (train / autoresearch + device + epochs). Button
   **disabled-with-reason when mode != IDLE** (mirror `DrivePad` `lockMsg`); never
   auto-force IDLE (offer an explicit "Set IDLE & train" secondary action). Keep
   the server refusal for the post-render race.
3. **Live progress + log tail** (only while running): reuse EvalTab's `<pre>`
   styling, auto-scroll, capped lines; coarse `epoch N/M` progress.
4. **Run-history table** (`runs/history` index).
5. **Promote = a per-row action on a finished run** (like ModelsTab "use"), with a
   confirm step — not a floating global button.

State→treatment table the implementer owes (each must be specified, not imagined):
no-dataset (warn, blocks) · ml-absent (warn, blocks, distinct copy) · no-GPU
(dim/warn, non-blocking) · running (progress+stop) · done · error (red card) ·
**cancelled (neutral/warn, "partial run dir may exist" — NOT red)** · promote
success ("now selectable in Models") · promote fail (red) · blocked-not-IDLE.
`train_running` joins telemetry → a **warn pill** in `TelemetryStrip` ("training
running — FPS may drop"); it must NOT enter the safety `StatusBanner`. The stop
button is a plain neutral `op-btn`, never red, never near E-STOP.

Tab count hits 5 (Control/Models/Connections/Eval/Training). Group **Eval +
Training under one "CV" tab** with a sub-toggle (gate taste decision) or wrap the
tab row. PTZ controls live **on/under the VideoPane** (they aim *that* image),
labelled "Camera pan/tilt" to disambiguate from the chassis "Body yaw/Turn"
(today both say "Pan" — Design F11); PTZ is its own device, not drive-token-gated,
works in any mode, disabled-with-reason when the active camera isn't a Tapo.

### 3d. Credential hygiene (DX 4.1, verified leak)
The rtsp spec carries `user:pass`; today `camera_spec` is returned in
`status()`/`telemetry()` (`runtime.py:246,267`) → **the Tapo password leaks into
every telemetry frame + WS**. Redact to `rtsp://***@host:554/stream1` in any
label/telemetry/log. Creds stay runtime-only (in-memory), never written to a
git-tracked YAML. No-auth localhost is acceptable for this LAN demo tool (auth is
an explicit non-goal), but the leak must be closed.

## 4. Scope decisions — LOCKED AT THE GATE (2026-06-07)

- **Fork 1 = A — Full in-browser training orchestrator.** User chose the full
  build over the CEO's B recommendation. The CEO/Eng/DX concerns are now **hard
  engineering requirements** that make A safe (not reasons to cut it):
  - **Dataset-prep is a first-class FORM, not a button (DX 1.1/1.2).** The tab
    surfaces `dataset.source` and edits the Roboflow `workspace`/`project` +
    `ROBOFLOW_API_KEY` (a form, not a config-file edit), pre-checks `fiftyone`
    for OpenImages, and explains the three sources. It wires ONLY to
    `catranger.train.prepare` — **NOT `scripts/setup_data.py`** (that symlinks the
    contest *inference* sets, produces no labels, useless for fine-tuning). Until
    a dataset exists, train/autoresearch are disabled-with-reason (no dead button).
  - **Device selector (DX 1.3).** `configs/train.yaml` defaults `device: mps` —
    wrong on CUDA/CPU boxes. The tab auto-detects + lets the operator pick
    `cuda|mps|cpu`, threads it through (`train.py` gains/honors `--device`), and
    shows a pre-launch CPU-time warning so nobody starts a 3-hour CPU run blind.
  - **Single heavy-job mutex (Eng H1, verified).** Eval and train both saturate
    CPU/GPU; today `start_eval` gates only on mode, not on "another heavy job
    running." A shared runtime lock makes eval + train mutually exclusive; the
    second is refused with a typed `heavy_job_busy` 409 naming the conflict.
  - **Cancel = kill the process GROUP + reap, never publish (Eng H2, verified).**
    `model.train` spawns DataLoader workers; a bare `terminate()` orphans them and
    leaks GPU memory. Launch with `start_new_session=True`; cancel =
    SIGTERM-group → wait(grace) → SIGKILL-group → `wait()` reap (Windows:
    `CREATE_NEW_PROCESS_GROUP` + taskkill). Cancelled runs **do not** publish;
    promote validates the weights load first. UI labels it "stop (terminates the
    run)", never implying a clean checkpoint.
  - **Coarse progress from `results.csv`, not stdout-scraping (Eng H3).**
    `overnight.py` captures output only after exit (no live tail), and Ultralytics
    uses `\r` bars. Poll `runs/train/<name>/results.csv` (one row/epoch) for a
    version-stable epoch count + stream `Popen` stdout into a bounded deque for the
    log tail. Promise only coarse progress (epoch N/M), stated as such.
  - **Promote must close the loop for the WEB pipeline (Eng C2, verified).**
    `_build_ranger` pops `finetuned_weights` (`runtime.py:364`) — the web Models
    tab reads the `models.yaml` profile, NOT `cat_distance.yaml`. So browser
    promote = (1) upsert a `models.yaml` profile pointing at the published weights
    **+ reload the in-memory `ModelRegistry`** so it's immediately selectable, and
    (2) reuse `promote.py:_set_finetuned_weights` (refactored to a callable,
    atomic temp+`os.replace`, locked) to keep the CLI/demo pipeline in sync +
    `--revert` + history archive. (Scope of (2) is a gate taste decision.)
  - **Typed errors, never `SystemExit` (Eng M2 + DX 2.1, verified).** `prepare`/
    `train` raise `SystemExit` with CLI hints; as a subprocess that's a bare
    nonzero rc. The route pre-flights via `overnight._train_data_ready` +
    `_ml_available` and maps failures to the existing `{ok,code,problem,cause,fix}`
    shape: `train_no_dataset`, `train_unavailable`, `train_not_idle`,
    `heavy_job_busy`, `train_bad_kind`.
  - **Reuse the launch/archive path:** `scripts/overnight.py` subprocess pattern +
    `catranger/history.py` (index-table read for v1; per-run drill-down deferred).
  - **IDLE-gated; baseline always one `--revert` away** (hard rule). E-stop also
    terminates the train subprocess (Eng H4).
- **Fork 2 = B — Tapo feed + runtime intrinsics re-anchor (with real calibration)
  + wire existing PTZ.** §3a delivers correct distance (the on-rubric win, must
  ship complete). Plus wire `hw/tapo.py` `move`/`preset` into the console for a
  pan/tilt tracking-camera demo (wiring existing code).
- **Fork 3 = A — Keep the two-process local app.** Add the tab(s); keep the
  one-command launch (`make web` / `scripts/web.py`). No desktop shell.

**Taste decisions locked at the final gate (2026-06-07):**
- **T1 — Drive-while-training = refuse the drive switch** with a clear "stop
  training to drive" message (no silent loss of a long run). E-stop always works.
- **T2 — One "CV" tab** holding both Eval and Training (sub-toggle inside); the
  tab row stays Control/Models/Connections/CV.
- **T3 — Promote updates BOTH** a `models.yaml` profile (live in the console
  Models tab via registry reload) AND `cat_distance.yaml` via `promote.py` (live
  in the CLI/demo pipeline) — one "promote", no divergence.

## 5. Non-goals (explicit)
Editing the frozen perception core; rebuilding any existing tab/transport;
auth/TLS/public exposure of the backend; hosting the backend or training on
Vercel; WebRTC; in-browser image annotation/labeling; multi-GPU/distributed
training; native mobile. Any of these → `TODOS.md`.

## 6. Test plan
- Python (unit): camera re-anchor changes distance for the same pixels (the
  on-rubric guarantee — asserts a NEW ranger is built, not in-place mutation);
  `--calibrate` helper solves `fx` from (H_real, Z, h_px) and writes
  `tapo_c211.yaml` with `needs_calibration: false`; `history.read_index` parse over
  a synthetic `index.jsonl`; refactored `_set_finetuned_weights` callable writes a
  valid `cat_distance.yaml` (atomic) and `--revert` restores baseline;
  `models.yaml` profile upsert produces a profile `ModelRegistry.from_yaml` loads;
  rtsp credential redaction in telemetry/label.
- Python (route-contract via `FakeRuntime`): `/api/train/*` busy refusal
  (`heavy_job_busy` when eval running), IDLE-gate (`train_not_idle`),
  `train_no_dataset`/`train_unavailable` pre-flight, status transitions, cancel
  returns terminate-not-cooperative. Extend `FakeRuntime` with
  `start_train/train_status/cancel_train/train_history/train_readiness` stubs.
  **Do NOT real-train in CI** (no GPU/dataset): assert command construction + that
  cancel calls process-group kill via a fake `Popen`.
- Frontend: `next build` + `next lint` clean; Training tab + readiness states +
  uncalibrated-distance qualifier render against a mocked API; manual checklist
  (prepare→train→stop→promote→appears in Models; Tapo connect + profile + PTZ;
  uncalibrated warning shown; cancelled is not red).
- Gate: `make check` green; baseline demo path unchanged.
- Frontend: `next build` + `next lint` clean; Training tab renders against a
  mocked API; manual checklist (launch a tiny job, watch progress, cancel,
  promote, see it in Models; connect Tapo + profile, see distance change).
- Gate: `make check` green; baseline demo path unchanged.

## 7. Risks
1. Training starves the box / fights the camera — mitigated: IDLE-gated, runs over
   a dataset (never the live camera), subprocess isolation, baseline always runs.
2. GPU/dataset absent on the demo box — mitigated: explicit degraded states; the
   tab is a stretch surface, not on the demo critical path.
3. Tapo intrinsics still a placeholder — re-anchor wires the *mechanism*; correct
   *numbers* need the calibration step (called out, owned).
4. Editing `configs/models.yaml` from a route (promote) — keep it additive + a
   schema-validated write; never clobber baseline profiles.
5. Next.js 16 "not the Next.js you know" — follow `apps/web/AGENTS.md`; verify the
   local docs path before writing framework code.

## 8. Sequencing (CEO re-ordered: on-rubric first, garnish last)
1. **Tapo intrinsics re-anchor + real calibration (§3a)** — the only frozen-rubric
   item. Ship it complete (mechanism *and* real `fx/fy` numbers), not half.
2. Training surface per the chosen Fork-1 depth: history read (`runs/history/`)
   beside the existing Eval tab → (if B) launch via the `scripts/overnight.py`
   subprocess + reuse `scripts/promote.py` for promote.
3. (If Fork 2-B) wire existing Tapo PTZ into the runtime camera path.
4. Docs + tests; `make check`; manual verification on real hardware/camera.

---

## CEO REVIEW (Phase 1) — strategy & scope

**Review mode:** `[subagent-only]` — `codex` is installed but its account rejects
every model (`gpt-5.4`/`gpt-5.1*`/`gpt-5*` → "not supported with a ChatGPT
account"), so the CEO voice is one independent Claude subagent + direct code
verification (same mode as this repo's prior two /autoplan runs).

### Premise challenge
- **P1 — "~85% already ships."** VERIFIED. Local two-process app, Arduino
  USB/BT/BLE, Tapo RTSP source, in-browser eval, safety core all exist (§1).
- **P2 — "the on-rubric win is Tapo distance correctness."** VERIFIED. Web
  runtime never re-anchors intrinsics; CLI does (`report.py:262-263`). Moves
  distance MAE → legitimately P1.
- **P3 — "in-browser training is the headline new ask."** TRUE the user asked;
  but the code says it's a trap as a full orchestrator: no `data/`/`runs/`,
  `train_once` has no cancel hook, off the frozen rubric. → goes to the gate.
- **P4 — "build it DRY by reusing existing jobs."** The original draft violated
  this (net-new `TrainJob` + a second `models.yaml` promote). Corrected to reuse
  `overnight.py` + `promote.py` + `history.py` + `setup_data.py`.

### Implementation alternatives (for the training surface)
| Approach | Effort (CC) | Risk | Reuse | Note |
|----------|-------------|------|-------|------|
| A Full orchestrator (new TrainJob, cancel, promote→models.yaml) | ~1 day | high | low | false cancel guarantee; off-rubric; dead button w/o dataset |
| B Launch via `overnight.py` subprocess + history + reuse `promote.py` | ~½ day | med | high | honors ask, reuses ~90%, honest cancel=terminate |
| C Read-only surface (history + existing Eval tab) | ~2 hr | low | highest | smallest; may under-deliver the explicit "train" intent |

### Dream-state delta
12-month ideal: one local app where you pick a camera (auto-correct intrinsics),
drive the robot over any transport, and the perception you run is the perception
you measured. This plan reaches it for the camera/distance axis (§3a); the
training surface is a convenience that should never compete with that or with the
guaranteed pretrained demo.

### CEO dual-voices consensus (subagent-only)
| # | Dimension | Claude subagent | Codex | Consensus |
|---|-----------|-----------------|-------|-----------|
| 1 | Premises valid? | yes (85% ships verified) | N/A | accept (1 voice + code) |
| 2 | Right problem? | Tapo distance = yes; full trainer = no | N/A | gate it |
| 3 | Scope calibration | invert: rubric first, garnish last | N/A | adopted |
| 4 | Alternatives explored | 1-C/1-B/overnight-reuse/calibrate-helper under-weighed | N/A | adopted |
| 5 | DRY / doctrine | promote dup + net-new TrainJob violate it | N/A | fixed |
| 6 | 6-month trajectory | risk: train tab unused, Tapo still wrong at demo | N/A | re-sequenced |

### NOT in scope (deferred → TODOS.md)
Full in-browser training orchestrator with per-epoch cooperative cancel (needs an
Ultralytics-callback change to the training core — not worth it); a second
`models.yaml` promote writer; in-browser annotation/labeling; multi-GPU training;
Electron/Tauri packaging; auth/TLS/public backend; running training on Vercel.

### Failure-modes registry
| Mode | Trigger | Mitigation |
|------|---------|------------|
| Wrong Tapo distance at demo | dropdown ships, calibration doesn't | calibration is must-ship in §3a, gated as P1 |
| Dead "Run training" button | no dataset on box | explicit "no dataset prepared" state; reuse `setup_data.py`/`prepare` |
| Hard-kill corrupts run dir | subprocess terminate mid-epoch | document terminate-only; `exist_ok` reruns; never the baseline path |
| Promote diverges from CLI | two promote mechanisms | single source: refactor `promote.py` `_set_finetuned_weights` |
| Training starves control loop | run while driving | IDLE-gate (mirror eval); baseline always one `--revert` away |

### Decision Audit Trail
| # | Phase | Decision | Class | Principle | Rationale |
|---|-------|----------|-------|-----------|-----------|
| F1 | CEO | Note `hw/tapo.py` PTZ exists; label §3b off-rubric | auto | P4/DRY | PTZ is wiring not building; apply frozen-metric triage |
| F2 | CEO | Drop "cooperative cancel"; cancel=subprocess terminate | auto | P5 explicit | `train_once` has no cancel hook (verified) |
| F2b | CEO | Training depth (A/B/C) | **gate** | — | reverses a non-goal; user judgment required |
| F3 | CEO | Reuse `scripts/promote.py`, not a `models.yaml` writer | auto | P4 DRY | canonical promote writes `cat_distance.yaml`; avoid divergence |
| F4 | CEO | Re-sequence: Tapo calibration first, garnish last | auto | P1/P2 | only §3a moves the frozen metric |
| F5 | CEO | Reuse `overnight.py`/`history.py`/`setup_data.py` | auto | P4 DRY | ~90% of the launch/archive path already ships |
| Tapo | CEO | Tapo scope (A/B/C) | **gate** | — | "controls" is ambiguous (feed vs PTZ) |
| Pkg | CEO | Packaging (A/B) | **gate** | — | two-process already satisfies "runs locally" |

**PHASE 1 COMPLETE.** Codex: unavailable. Claude subagent: 6 findings (1 critical,
3 high, 1 medium), all verified in code. Consensus: single-voice + code evidence.
3 scope decisions elevated to the premise gate. Passing to the gate before Design/Eng/DX.

---

## DESIGN / ENG / DX REVIEW (Phases 2–3.5) — post-gate, scope locked A/B/A

All `[subagent-only]` (codex unavailable). Three independent Claude voices, no
shared context, each read the plan + real code. The load-bearing CRITICAL/HIGH
findings were re-verified directly in code before folding (see inline notes).

### ENG consensus (subagent-only)
| # | Dimension | Subagent | Verified | Disposition |
|---|-----------|----------|----------|-------------|
| 1 | Architecture sound? | re-anchor + promote mechanisms WRONG as drafted | C1,C2 ✓ | auto-fixed (§3a/§3b) |
| 2 | Concurrency safe? | eval+train can both run; cancel leaks worker group | H1,H2 ✓ | auto-fixed (heavy-job mutex; killpg+reap) |
| 3 | Progress feasible? | subprocess can't use eval's callback | H3 | auto: results.csv + bounded deque |
| 4 | Safety/IDLE gate | TOCTOU + no reverse gate; E-stop must kill train | H4 | auto + 1 TASTE (reverse policy) |
| 5 | PTZ feasible? | runtime holds no TapoCamera; blocking pytapo | H5 ✓ | auto-fixed (§3a) |
| 6 | Tests/atomicity | config write non-atomic; no per-run history read | M1,M3,M4 | auto (atomic write; index-only v1) |

### DESIGN consensus (subagent-only)
| # | Dimension | Subagent | Disposition |
|---|-----------|----------|-------------|
| 1 | Honest states | uncalibrated distance shows green/confident by default | **F9 CRITICAL** auto-fixed (§3a/§3c) |
| 2 | Hierarchy | no layout for densest tab | F1 auto (§3c layout) |
| 3 | Missing states | cancelled→red, IDLE-gate, ml/dataset/GPU collapsed | F3,F5,F4 auto (§3c table) |
| 4 | Safety legibility | train_running pill not banner; stop not red | F7,F8 auto (§3c) |
| 5 | PTZ vs chassis pan | two "Pan" controls collide | F11 auto (rename + on-video) |
| 6 | Force IDLE? | recommend explicit, never auto | F6 auto |
| 7 | System fit | reuse op-system; group Eval+Training | F12 auto; F13 TASTE (tab grouping) |

### DX consensus (subagent-only)
| # | Dimension | Subagent | Disposition |
|---|-----------|----------|-------------|
| 1 | TTHW to trained model | dataset-source UX is the real cliff; device:mps trap | 1.1,1.3 auto (form+selector) |
| 2 | Error messages | SystemExit not typed; Tapo failures all generic | 2.1,2.3 auto (typed catalog) |
| 3 | Next docs rule | path absent pre-install; rule followable after | 3.1 auto (install-order note + C4 fallback gate) |
| 4 | Tapo onboarding | Camera Account gotcha invisible; creds leak; calibration | 4.1,4.2 auto (redact; calibrate must-ship; inline hint) |
| 5 | Run-story docs | no README/Makefile updates for new surfaces | 5.1,5.2 auto (docs deliverable) |

### Cross-phase themes (independent agreement = highest confidence)
1. **Tapo calibration honesty** — CEO F4 + Design F9 (critical) + DX 4.2. A profile
   dropdown without real numbers + an honest UI ships a confident wrong distance —
   the one frozen-rubric item, failed. The single most important thing to get right.
2. **Typed error taxonomy for new routes** — Eng M2/M3 + DX 2.1/2.3. New failures
   must follow `{ok,code,problem,cause,fix}`, never `SystemExit`/generic fallback.
3. **Heavy-job / IDLE safety** — Eng H1/H4 + Design F5/F6/F7. Training must not
   fight the control loop; "IDLE-gated like eval" is necessary but insufficient.
4. **Promote→serve loop reality** — Eng C2 + Design F2 + CEO F3. Closing it in the
   browser needs a `models.yaml` profile + registry reload, not just `promote.py`.

### Decision Audit Trail (Phases 2–3.5)
| # | Phase | Decision | Class | Principle | Rationale |
|---|-------|----------|-------|-----------|-----------|
| C1 | Eng | Re-anchor rebuilds ranger + atomic swap | auto | P5 | in-place mutation is a data race (verified) |
| C2 | Eng | Promote upserts models.yaml + reloads registry (+ promote.py sync) | auto | P1 | `_build_ranger` pops finetuned_weights (verified) |
| H1 | Eng | Single heavy-job mutex (eval XOR train) | auto | P1 | both saturate GPU; isolation ≠ no contention |
| H2 | Eng | Cancel = killpg + reap, no publish | auto | P5 | bare terminate orphans Ultralytics workers |
| H3 | Eng | Progress from results.csv + bounded log deque | auto | P5 | overnight captures only post-exit; \r bars |
| H4 | Eng | E-stop kills train; reverse drive-gate policy | auto + **TASTE** | P1 | refuse-drive vs auto-cancel both viable |
| H5 | Eng | Runtime holds TapoCamera for PTZ; threadpool+throttle | auto | P5 | no handle today; blocking pytapo |
| M1 | Eng | Atomic temp+os.replace config write, locked | auto | P1 | corrupting cat_distance.yaml breaks baseline |
| F9 | Design | Uncalibrated → warn (not green) + qualified distance | auto | P1 | honesty on the rubric item |
| F1 | Design | Training-tab layout + state→treatment table | auto | P1/P5 | densest tab; no imagined states |
| F3 | Design | cancelled renders neutral, not red | auto | P5 | copied EvalTab only handles error |
| F11 | Design | Rename pan controls; PTZ on VideoPane, ungated | auto | P5 | two "Pan" controls = safety confusion |
| F13 | Design | Eval+Training grouping | **TASTE** | — | one "CV" tab vs two tabs |
| 1.1 | DX | Dataset-source form (roboflow/fiftyone), prepare-only | auto | P1 | dead button otherwise; setup_data.py ≠ labels |
| 1.3 | DX | Device selector + CPU-time warning | auto | P1 | mps default wrong off-Mac |
| 2.1 | DX | Typed error catalog for train/Tapo routes | auto | P5 | SystemExit breaks the error contract |
| 2.3 | DX | Distinguish Tapo auth/unreachable/generic | auto | P1 | Camera Account gotcha invisible at failure |
| 3.1 | DX | Impl step-0 gate: verify next docs path + fallback | auto | P5 | AGENTS.md rule unfollowable pre-install |
| 4.1 | DX | Redact rtsp creds in telemetry/logs | auto | P1 | password leak (verified) |
| 4.2 | DX | `--calibrate` helper promoted to must-ship | auto | P1 | the on-rubric deliverable |
| 5.1 | DX | README + Makefile run-story for new surfaces | auto | P1 | operator can't run from source |
| — | DX | Promote scope: web-only vs web+CLI sync | **TASTE** | — | completeness vs effort |

**PHASES 2–3.5 COMPLETE.** Eng: 2 critical + 5 high + 4 medium (criticals verified
in code). Design: 1 critical + 4 high + rest medium/low. DX: 5 high + 7 medium.
All folded via the 6 principles except **3 taste decisions** → final gate.
Cross-phase themes: calibration honesty, typed errors, heavy-job safety, promote loop.

---

## IMPLEMENTATION STATUS (approved A/B/A; T1/T2/T3 locked) — 2026-06-07

**Backend (Python) — shipped + gate-green (ruff, mypy, 152 pytest pass, cov 91%):**
- `catranger/web/runtime.py` — camera-profile re-anchor (rebuilds ranger + atomic
  swap, Eng C1); rtsp credential redaction (`_redact_spec`, DX 4.1); TapoCamera PTZ
  handle (`_set_tapo_handle`/`ptz_move`/`ptz_preset`, throttled, Eng H5); training
  orchestrator methods (`start_train`/`train_status`/`train_result`/`cancel_train`/
  `train_history`/`train_readiness`/`promote_model`) with the heavy-job mutex
  (eval XOR train, H1), typed errors (M2), IDLE-gate, `training_active` (T1); E-stop +
  shutdown kill the train subprocess (H4); telemetry adds `camera_profile`,
  `camera_calibrated`, `train_running`.
- `catranger/web/train_job.py` (NEW, unit-tested 90%) — subprocess state machine,
  injected runner, coarse `results`/epoch progress, bounded log tail, history archive.
- `catranger/train/runner.py` (NEW) — process-group spawn + killpg/CTRL_BREAK cancel
  + reap (H2), cross-platform.
- `catranger/train/promote.py` (NEW) — single-source promote: atomic+comment-preserving
  `set_finetuned_weights` (M1) + `upsert_model_profile` (registry) + `promote_weights`
  (both consumers, C2/T3). `scripts/promote.py` now delegates to it (DRY).
- `catranger/train/{train,autoresearch}.py` — `--device` flag (DX 1.3).
- `catranger/web/server.py` — routes: extended `/api/camera/connect` (profile),
  `/api/camera/ptz[/preset]` (threadpool), `/api/train/{run,status,report,cancel,
  history,readiness}`, `/api/train/promote`; T1 `train_active` gate on `/api/mode` + WS.
- `scripts/calibrate_camera.py` (NEW) — solve `fx=fy=h·Z/H`, write yaml (DX 4.2).
- `configs/web.yaml` — `train_config`, `ptz_min_interval_s`.
- Tests: `tests/test_web_train_job.py`, `tests/test_train_promote.py`, extended
  `tests/test_web_server.py` (train/ptz/camera-profile/T1 route contracts).
- Docs: README (CV tab, Tapo profile/PTZ/calibration, dataset prereq), Makefile
  (`calibrate` target).

**Frontend (Next.js) — building (delegated):** CV tab (Eval+Training sub-toggle, T2),
Training UI (readiness/launch/progress/log/history/promote per Design §3c), camera
profile dropdown + uncalibrated qualifier (F9), PTZ on VideoPane (F11), `train_running`
warn pill (F7). Verified by `pnpm build` + `pnpm lint`.
