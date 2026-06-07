<!-- /autoplan restore point: ~/.gstack/projects/mihaimdm22-robotricks-vision/catranger-10x-improvements-autoplan-restore-20260607-061030.md -->
# CatRanger — the 10x plan

> **Plan in:** a pasted generic "Cat Tracker Platform" architecture (Next.js + FastAPI,
> overnight sweeps, recovery, registries). **Plan out:** a grounded, surgical evolution of
> the CatRanger system that *already exists* — not a rebuild.
>
> **Reviewed by `/autoplan`** (CEO → Design → Eng → DX, full depth). Voices: independent Claude
> subagents per phase **[subagent-only — Codex CLI unavailable on this box: the ChatGPT account
> rejects every model id]** plus a 9-agent grounding pass (5 codebase audits + 4 cited web-research
> streams). The review found three *factual* flaws in the first draft and they are fixed below
> (see the **Decision Audit Trail** and **§13 Review Report**). The one decision left for the
> human is **sequencing** (§6 + the final gate).
>
> **The finding that reframes everything:** ~80% of what the pasted doc proposes is already
> built, and built well. The 10x is **(a) making the scored metric provable** and **(b) making
> the existing system robust/observable/extensible** along the three axes you asked for — failure
> recovery, real-time visualization, pluggable models/datasets — **plus the handful of changes
> that actually move the frozen metrics.** Greenfield rebuild would be the most expensive way to
> go backwards.

---

## Implementation status (blended order — see §6)

Landed (all behind `make check`: ruff + mypy + pytest, coverage ≥ 85%):
- ✅ **A3** per-job timeout + process-group kill — `catranger/proc.py` (+ overnight wiring, config). Orphan-kill tested.
- ✅ **B0** overlay-JSON contract — `catranger/web/overlay.py` (+ runtime producer, `web.yaml`, TS types).
- ✅ **D0.1** distance-GT plumbing — `catranger/eval/gts.py` + `report.py --gts` + `io.image_files` + `make eval GTS=…` + template.
- ✅ **A1/A2** durable SQLite job queue + owner-scoped crash recovery — `catranger/jobqueue.py` (+ overnight `--fresh`/resume). Two-process + crash-injection tested.
- ✅ **A5** retry policy — `proc.classify_failure` (retryable: timeout/OOM/transient I/O; permanent: bad config/missing data, conservative default) + `backoff_seconds` (capped exponential) + `JobQueue.retry`; overnight retries transient failures up to `max_attempts`, fails permanent ones immediately.
- ✅ **A6** crash-safe artifacts — `history.py` copies via temp + `os.replace` (atomic) and records a `sha256` per artifact in `meta.json`; `meta.json` itself is written atomically.
- ✅ **A4** training resume — `train.py` `--resume {auto,never,force}` resumes from `last.pt` (optimizer/scheduler/epoch), exception-falls-back to a clean run; a retried overnight `train` job auto-resumes (stable run dir). Checkpoint-detection unit-tested.
- ✅ **A7** web eval persistence — each web eval is recorded in the shared durable queue (`owner='web'`) via `record_running`/`complete_by_key` + an `EvalJob` settle callback; `fail_orphans('web')` at server start surfaces evals interrupted by a crash. Owner-scoping keeps the overnight runner and web server from disturbing each other's jobs (Eng#1).
- ✅ **B3 backend** — `GET /api/jobs` (+ `runtime.jobs_status`) exposes the durable queue (overnight sweeps + web evals: jobs + counts) read-only over HTTP, the server contract the live sweep panel consumes. Plus `python -m catranger.jobqueue` / `make jobs` for the same view in the terminal. Route-contract + real-runtime tested.
- 🟡 **B1 (canvas overlay)** — `OverlayCanvas.tsx` draws the crisp target ring + distance/ID/bearing labels over the burned-in boxes from the B0 overlay JSON; alignment math isolated in pure `lib/letterbox.ts` (object-contain content rect), dpr-crisp, `ResizeObserver`, dims when not live. **tsc + ESLint clean; alignment math unit-tested** (vitest in `apps/web`, `make web-test`). Still **visually unverified** end-to-end (needs `/run` to confirm the ring lands on the burned-in box).
- 🟡 **B2 (failure badges)** — `lib/badges.ts`: ≤1 badge per detection by severity precedence (`pickBadge`) + per-track `BadgeDebouncer` (N-frame persistence kills blips) + `badgeStyle` (glyph+text, never hue-only) — the Design#4/#5 arbitration. **Unit-tested** (6 cases) and integrated into the canvas (debounced per `frame_id`). Render is **visually unverified** (pending `/run`).
- ✅ **C6** Extending docs — CONTRIBUTING "Extending CatRanger": copy-paste recipes for add-a-model / add-a-dataset / add-a-backend + the keep/reject and crash-safe-overnight flows.
- ✅ **D1 (eroded-box median)** — `distance.py` samples the central `(1-box_erosion)` of each box for the depth median (kills edge background bleed); config-gated `depth.box_erosion` (default 0 = unchanged baseline), falls back to the full box on collapse. Golden-frame tested; activate via `keepreject` once GT exists.
- ✅ **C1/C4** pluggable detector backends (builder dict, no sync-trap, lazy-import preserved) + class-id drift guard — `detect.py` + `registry.py`.
- ✅ **C2** `datasets.yaml` registry — `catranger/datasets.py` + `configs/datasets.yaml` + `prepare --dataset`/`make prepare DATASET=` (sources read from `prepare._SOURCES`, no drift).
- ✅ **C3** one model home — `apply_profile` in `registry.py`; `--model <id>` in `demo.py` + `eval` resolve `configs/models.yaml` (web runtime refactored onto the same helper). `--classes` still wins.
- ✅ **D0.2** scored keep/reject harness — `catranger/eval/keepreject.py` + `make keepreject BASELINE= CANDIDATE=`. Gates a config change on the FROZEN metrics (separate from the mAP autoresearch loop); faithful metrics (FPS always, MAE when GT'd) gate, proxies advisory (§12). Exit 0=keep / 2=reject.

**WS-D0 foundation is now complete** (D0.1 GT plumbing + D0.2 scored harness): a config change
can be measured against the frozen metric and kept/reverted — every WS-D metric mover is unblocked.

**WS-A failure recovery is COMPLETE** (A1–A7: durable queue + owner-scoped recovery + per-job
timeout/group-kill + retry/backoff + crash-safe artifacts + training resume + web eval persistence).

Pending: **B1 visual verification** (run the console against a live overlay feed; confirm the ring/
label lands on the burned-in box — the math is unit-tested, the end-to-end render is not);
**B2 a11y** (mirror badges into an `aria-live` region — canvas text is invisible to screen
readers) + visual check; the **B3 panel UI** (consume `/api/jobs`); **D0.3**
(occlusion clip + lag term to
de-proxy continuity/smoothness — needs labeled data), and the rest of **WS-D**: D1's depth-net
selection + per-class α re-fit (run-time ops needing ml + GT), **D2** (locked-target ReID),
**D3** (YOLO26 + TensorRT + small depth backbone), **D4** (temporal-Z smoothing) — each gated by
`keepreject`. Deferred by YAGNI: the formal `Detector` `typing.Protocol`.

## 0. North star (restated — with an honesty correction from review)

The only thing that counts is the **frozen metric**: **distance MAE, track continuity, FPS,
command smoothness** (CLAUDE.md). The review (CEO#4) forced an honest correction the first draft
glossed — **today these metrics are not equally real** (see **§12 Metric faithfulness**):

| Metric | State today | Consequence |
|---|---|---|
| **FPS** | **Faithful** — measured directly in `eval/metrics.py` | Trust it; gate on it. |
| **Track continuity** | **Proxy** — `track_stats()` counts id churn, *no GT* | Needs a labeled occlusion clip to be real. |
| **Command smoothness** | **Proxy + gameable** — jerk on *self-emitted* commands; harder damping "wins" for free | Must be paired with a tracking-lag term. |
| **Distance MAE** | **Unmeasured** — `eval/report.py:369` runs with `gts=None`; provided set has no distance labels | **Cannot be kept/rejected until a GT set exists.** |

Every item below is tagged with which metric it moves, or **[plumbing]** (reliability/
extensibility), **[demo]**, or **[foundation]** (makes a metric measurable).

CLAUDE.md scoping holds: scored core (`intrinsics, distance, detect, depth, track, pipeline`)
stays surgical; tooling/web/tests/CI/docs are exempt; **the pretrained baseline always runs.**

> **Context correction (review CEO#3/#5):** the project is in **post-hackathon maintenance mode**
> (CLAUDE.md "Maintenance mode"; v0.1.0 shipped; git log shows v0.3.x). The CEO voice anchored on
> `docs/00-AUDIT.md`'s frozen "deadline is today" text — that is stale. There is **no live
> competition clock**. So this is "make the maintained project dramatically better," not "ship a
> report tonight." The valid kernel of that voice survives as the sequencing decision in §6.

---

## 1. What already exists (build on this — do not rebuild)

| Capability | Where it lives | State |
|---|---|---|
| Frame→undistort→detect+track→distance→bearing/speed→inter-object | `catranger/pipeline.py` | Solid; lazy heavy imports; FP16-guarded |
| Metric distance (geometry + depth median, fused, CI + per-class α) | `catranger/distance.py` | Sound math; honest CI |
| Detector wrapper (YOLO / RT-DETR, one `detect`/`track` surface) | `catranger/detect.py` | Lazy import; backend hardcoded in `_load` |
| Monocular metric depth (DepthAnythingV2 / UniDepthV2 w/ K + conf) | `catranger/depth.py` | Pluggable by string name |
| FastAPI control plane: REST + 1 telemetry/control WS + MJPEG | `catranger/web/server.py` | Typed errors `{ok,code,problem,cause,fix}` |
| Live runtime: single control thread, hot model swap, MJPEG publish | `catranger/web/runtime.py` | Sole-writer thread; tick errors swallowed |
| Telemetry payload (what the console gets) | `catranger/web/controller.py:226` | **Single-target scalars only** — no per-box data |
| Model registry (YAML → validated profiles, default) | `catranger/web/registry.py` + `configs/models.yaml` | Backends limited to `{yolo, rtdetr}` |
| Background eval job (one at a time, pollable) | `catranger/web/eval_job.py` | **In-memory only** |
| Overnight runner (per-job subprocess, archive every run) | `scripts/overnight.py` | Crash-isolated; **no resume/retry/timeout** |
| Run history (append-only `index.jsonl` + `INDEX.md`) | `catranger/history.py` | **Zero-dep post-hoc log**, not a queue |
| Autoresearch keep/reject | `catranger/train/autoresearch.py` | **Optimizes mAP50-95, NOT the frozen metrics** |
| Dataset prep adapters (`roboflow / openimages / manual`) | `catranger/train/prepare.py` `_SOURCES` | A real adapter registry already |
| Eval harness (FPS/continuity/smoothness; MAE iff GT) | `catranger/eval/{metrics,report}.py` | `distance_mae()` exists but is fed `gts=None` |
| Next.js console (Video/Models/Eval/Drive/Connections) | `apps/web/src/components/console/*` | MJPEG `<img>` + WS telemetry + REST history |
| Overlays | `catranger/viz.py` (cv2, **server-burned**) | Boxes + text baked into JPEG |
| Quality gates | `Makefile check`, `pyproject.toml`, CI | ruff + mypy + pytest, `web` leg |

**Research verdict (4 cited web-research streams):** the perception design is already on the 2025
SOTA path. The wins are *tuning + edge-fitting + measurement + reliability*, not redesign.

---

## 2. The asks, reframed against reality

1. **"Failure recovery"** — the perception loop already survives per-tick errors; the gap is
   **durability of in-flight sweep/eval state** (a parent crash between overnight jobs loses the
   night with no trace) and **no resume/retry/timeout**.
2. **"Real-time visualization"** — video + telemetry already stream; the gaps are a **per-detection
   overlay contract that does not exist yet** (today's telemetry is single-target scalars), **crisp
   failure-aware overlays**, and **a live view of sweeps/eval** (today you read `INDEX.md` later).
3. **"Add models and datasets on top"** — models are YAML-pluggable *within two hardcoded backends*
   and live in **two disjoint config homes** (web `models.yaml` vs CLI `cat_distance.yaml`
   `approach_a/b`); datasets aren't a first-class registry. The gap is a thin Protocol + builder
   dict, **one** model home, and a `datasets.yaml` registry.

And the prerequisite the review surfaced (CEO#1/#2):

4. **"Prove the number" [foundation]** — distance MAE is unmeasurable today and no keep/reject
   harness scores the *frozen* metrics. Without this, WS-D cannot be accepted or rejected at all.

---

## 3. Premises (the human gate — confirm before committing)

- **P1.** Deliverable = **evolve existing CatRanger**, not the greenfield platform the pasted doc
  describes. *(All review voices: strongly confirmed.)*
- **P2 (corrected).** The frozen metric rules — **but it must first be made measurable.** A
  scored-core change is only kept if it holds/improves a **real** (not proxy) metric. Distance MAE
  needs a GT set; continuity/smoothness need GT/anti-gaming before they can gate changes.
- **P3.** **Single box, Python, `uv`.** Recovery uses **stdlib `sqlite3`**, not Prefect/Dagster/
  Ray/Celery.
- **P4.** **Baseline-always-runs is inviolable.** Every feature degrades to "the baseline demos."
- **P5 (new, from review).** **Maintenance mode, no competition clock.** Priorities are set by
  long-run project value, not a deadline.

---

## 4. Workstreams

### WS-D0 — Prove the number (metric foundation) **[foundation]** — NEW (review CEO#1/#2/#4)

The enabling work WS-D silently assumed. Small, decisive, and the only work that retires the
project's central unknown ("what *is* our distance MAE?").

- **D0.1 GT eval set.** Capture/borrow ~30–60 frames at tape-measured distances (the HC-SR04 rig
  gives free GT), commit a `gts.json` sidecar wired into `run_eval_job(gts=…)`. Acceptance:
  `make eval` prints a **finite MAE float**. *(Makes MAE real.)*
- **D0.2 Scored keep/reject harness.** A thin runner distinct from the mAP autoresearch loop:
  apply a config delta → run eval over a **fixed** clip set → compare MAE / continuity / FPS /
  smoothness to a frozen `baseline.json` → keep or revert. This is what every WS-D item plugs into.
  *(Replaces the first draft's false "reuse the existing autoresearch loop" claim.)*
- **D0.3 Make the proxies honest.** Score continuity against ≥1 hand-labeled occlusion clip
  (pre/post id) via the existing `synthetic_occlusion_reacquire` hook; pair smoothness jerk with a
  tracking-lag term so harder damping can't win for free.

### WS-D — Metric movers (scored core; surgical) **[metric]** — each gated by D0.2

(Research: distance/tracking SOTA stream. Now correctly gated on the WS-D0 harness, not mAP.)

- **D1. Distance MAE:** (a) keep/reject over `{DAv2-metric-indoor, UniDepthV2, Metric3D v2}` on
  real cat clips (no universal winner — pick on *our* eval); (b) **erode the bbox** before the
  depth median (stop background bleed); (c) **re-fit per-class α** (DAv2 indoor scale ≠ Go2 `fx`).
  Touches `distance.py` + config. **Biggest MAE lever — but a hypothesis until D0.1 lands.**
- **D2. Track continuity:** keep BoT-SORT + ReID; add a **single OSNet appearance template for the
  locked cat** to survive full occlusion / second-cat intrusion. Gated on D0.3's occlusion clip.
- **D3. FPS / edge:** swap `yolo11s → yolo26s` (config-only; NMS-free → less jitter, ~43% faster
  CPU); TensorRT-export detector + a **ViT-Small** depth backbone; keep depth `every_n`.
- **D4. Command smoothness:** reduce **upstream** distance noise (eroded median + temporal Z
  filter) so the existing deadband→EMA→slew→clamp controller fights less. Scored with the lag term.

### WS-A — Failure recovery (durable, crash-only) **[plumbing]**

Stdlib-only durable job state. **Revised for the Eng review's correctness findings.**

- **A1. SQLite job table in a NEW `catranger/jobqueue.py`** (Eng#5 — *not* bolted onto
  `history.py`, whose zero-dep append-only contract stays intact; `history.py` becomes a read-only
  projection of completed rows). Columns: status `queued→running→ok|fail|skipped`, `attempts`,
  deterministic `run_key`, `owner`, `started_at`, `heartbeat_at`. `PRAGMA journal_mode=WAL`,
  `busy_timeout=30000`, `BEGIN IMMEDIATE` on claim; **a fresh connection per process** (Eng#4 — the
  `DistanceStore` single-shared-connection idiom is *not* multi-process safe).
- **A2. Startup recovery sweep — ownership-scoped (Eng#1, critical fix).** Reclaim only rows whose
  `owner` is *this* runner **or** whose `heartbeat_at` is stale beyond a TTL — **never** every
  `running` row. This is what makes A2 and A7 coexist.
- **A3. Per-job timeout with process-group kill (Eng#2).** `start_new_session=True` +
  `os.killpg(SIGTERM→SIGKILL)` on `TimeoutExpired`, so orphaned dataloader workers and leaked
  GPU/MPS memory don't survive to OOM the next retry. **Highest-value, lowest-risk WS-A piece.**
- **A4. Resume training — exception-based fallback (Eng#3).** `resume=True` from a deterministic
  `runs/train/<run_key>/weights/last.pt`; on **any** exception (corrupt/truncated checkpoint,
  missing `args.yaml`, version mismatch — not just "no last.pt") log it and restart clean with a
  fresh name. Validate `last.pt` (sha256 from A6) before trusting resume. Score/publish `best.pt`.
- **A5. Retry policy — structured signals first (Eng#6).** Treat `TimeoutExpired` as a first-class
  `timeout` class in the parent; have subprocesses emit a machine-readable `failure.json`; fall
  back to log-string heuristics last. Retry only retryable (CUDA/MPS OOM, timeout, transient I/O),
  bounded (2–3), `min(cap, base·2^n)·jitter`. Never naively re-run an OOM (resume / reduce batch).
- **A6. Artifact integrity.** temp + `os.replace` (atomic) + `sha256` in `meta.json`.
- **A7. Persist `EvalJob`** in the A1 table **under `owner='web'`** (Eng#1) so a web eval survives a
  server restart and the overnight sweep never reclaims it.

### WS-B — Real-time visualization **[demo + plumbing]**

Keep MJPEG (research-confirmed correct baseline). **Revised for the Design review's findings.**

- **B0. Overlay-JSON contract — FIRST (Design#1, critical fix).** This does **not** exist today;
  define and ship it before B1. Schema (normalized so it survives any encoder resolution):
  `{ frame_id, frame_w, frame_h, dets:[{track_id, xyxy_norm:[0..1×4], conf, dist_m, dist_lo,
  dist_hi, bearing_deg, is_target, flags:[…]}], global_flags:[…] }`, pushed on the existing WS
  alongside each frame. Requires extending `controller.py`/`runtime.py` to emit per-detection data.
- **B1. Hybrid overlays.** Boxes stay **burned in** (alignment, cheap); distance/ID/bearing text +
  target ring drawn client-side on a `<canvas>` over the `<img>`, from B0's JSON. **Spatial
  mapping is part of B1 (Design#3):** compute the object-contain **letterbox content rect** from
  `frame_w/h`, map `xyxy_norm` into it, size the backing store ×`devicePixelRatio`, re-derive on
  `ResizeObserver`.
- **B2. Failure visualization (Design#4).** Badges with **arbitration**: ≤1 badge per detection
  (precedence `model_error > track-lost > out-of-range > low-confidence > depth/geometry-disagree`),
  global/safety states stay in the existing `StatusBanner` (not duplicated), debounce N frames
  before showing. One shared **color-token table** (Design#5) sourced from the console CSS vars,
  hue = semantics + glyph/text (color-blind safe).
- **B3. Live sweep/eval view.** A console panel streaming the A1 job table (SSE/WS) — watch
  `queued→running→ok/fail`, retries, and the startup-recovery sweep live, tail logs. Specify
  **empty / loading / reconnecting / completed** states (Design#6).
- **B4. Honest sync + transport (Design#7).** Be explicit: over MJPEG, `frame_id` enables **stall
  detection** (id stops advancing → dim/clear the overlay, like `TelemetryStrip`), **not** exact
  pixel-frame matching; latest-frame coalescing keeps drift ≤~1 frame. Serve over **HTTP/2** (avoid
  starving `/api/*`); **assert one fixed encoder resolution**; `bufferedAmount` send-skip on the
  telemetry push. **A11y (Design#9):** mirror every failure into an `aria-live` region; keyboard
  toggles; `prefers-reduced-motion`.
- **B5. (Gated stretch) WebRTC via `aiortc`** — only if sub-100ms glass-to-glass becomes a scored
  need. `viz.py` drops into `MediaStreamTrack.recv()`; SDP rides the existing WS. **Not now.**

### WS-C — Pluggable models + datasets ("add on top") **[plumbing]**

Make the implicit contracts explicit, no plugin framework. **Revised for Eng + DX findings.**

- **C1. `Detector`/`DepthEstimator` `typing.Protocol`** (non-runtime-checkable — Eng#8) + a
  module-level builder dict in `detect.py`/`depth.py` (`_BACKENDS = {"yolo": lambda w: YOLO(w), …}`,
  still lazy-imported). **`registry.py` imports those keys** instead of duplicating the
  `{yolo,rtdetr}` set (DX#4 — kills the two-file sync trap). Conformance is tested against a pure
  **stub** (mypy enforces structural conformance); a test asserts `import catranger.detect` +
  `registry.list()` do **not** import torch (preserves lazy discipline).
- **C2. `datasets.yaml` registry** mirroring `models.yaml` (reuse the `from_dict`/`from_yaml`
  validation pattern), normalizing every source to `data/cat/` + `{0: cat}`; promote `prepare.py`'s
  `_SOURCES` to first-class, add `coco` (`ultralytics convert_coco`) + `hf` (`fiftyone
  load_from_hub`). Default `train.yaml` `source: manual` so a fresh-clone `make prepare` succeeds
  (DX#7).
- **C3. One model home (DX#1, important).** Unify on `models.yaml`; let demo/eval take `--model
  <id>` resolving against the registry (keep `--approach A|B` as sugar for the two default ids), so
  a fine-tuned model added once is visible to *both* the web tab and the CLI.
- **C4. Class-id drift guard (Eng#9).** The registry cross-checks a fine-tune's `classes:` against
  its dataset's canonical map and **warns** (not fails, per C5) when an `nc=1` model is paired with
  a non-`[0]` filter (which would silently drop every detection). Keep `detect.py`'s filter.
- **C5. Optional `version:`+`sha256:`** on `models.yaml` (local `best.pt` only, **warn-not-fail** —
  never blocks the baseline).
- **C6. "Extending CatRanger" docs (DX#3).** CONTRIBUTING recipes: add a model, add a backend, add
  a dataset — each copy-paste-complete and ending in a checkable command.

---

## 5. Architecture delta (new vs existing)

```
                        EXISTING (keep)                         10x ADDITIONS
  pipeline.CatRanger.process()                  D1 eroded-box median + temporal Z (distance.py)
   undistort→detect/track→distance→bearing      D2 locked-target OSNet template
                                                D3 yolo26 + TRT + small depth (config)
                                                C1 Detector/DepthEstimator Protocol + _BACKENDS
  web.runtime / web.server (REST+/ws+/video)    B0 per-detection overlay-JSON + frame_id
  web.registry (models.yaml)                    B3 /events sweep+eval topic; C2 datasets.yaml
  web.eval_job (in-memory)                       A7 persist via jobqueue (owner='web')
  scripts/overnight.py + history.py             A1 jobqueue.py (NEW; history.py = projection)
   (per-job subprocess, archive)                A2 owner-scoped recovery  A3 timeout+killpg
  train.autoresearch (mAP keep/reject)          D0.2 SCORED keep/reject harness (NEW, separate)
  eval/{metrics,report} (gts=None)              D0.1 gts.json GT set → finite MAE
  apps/web console                              B1/B2 canvas overlays + arbitrated badges; B3 panel
```

Two SQLite files, by design (Eng#4): `outputs/history.sqlite3` (distance log) and the new
`runs/jobqueue.sqlite3` (durable queue). No broker, no second service.

---

## 6. Milestones & the sequencing decision

> **DECIDED (autoplan gate, blended order):** land the cheap no-regret items **first** —
> `A3` (per-job timeout + killpg), `B0` (overlay-JSON contract), `D0.1` (GT set so `make eval`
> prints a finite MAE) — **then** the operator/dev plumbing in the order you asked for
> (`WS-A` recovery → `WS-B` viz → `WS-C` pluggability), with the **`D0.2` scored keep/reject
> harness as the gate on any scored-core (`WS-D`) change.** Premises P1–P5 confirmed.
>
> Concrete first slice: `D0.1` (GT) + `A3` (timeout) + `B0` (contract) → then `A1/A2` (jobqueue) →
> `B1/B2/B3` (overlays + sweep panel) → `C1/C3` (Protocol + one model home) → `D0.2` harness →
> `WS-D` metric movers (each keep/reject-gated).

**The two orderings that were weighed (blended, above, was chosen):**

- **Order A (review-recommended): foundation-first.** `WS-D0` (prove the number) → `WS-D` metric
  movers → then the plumbing you asked for (`WS-A/B/C`). Rationale: you can't call anything "10x"
  until the metric is provable; WS-D is undeliverable without D0; the plumbing is valuable but
  `[plumbing]`. *(CEO#7/#8/#9.)*
- **Order B (your stated order): plumbing-first.** `WS-A` (recovery) → `WS-B` (viz) → `WS-C`
  (pluggability) → `WS-D0`+`WS-D` last. Rationale: recovery/viz/pluggability are what you explicitly
  asked for and have standalone value (a better dev/operator loop) independent of the metric.

Either way, **`A3` (per-job timeout) and `B0` (overlay contract) are cheap, no-regret, and can land
first**, and every scored-core change waits on `D0.2`. Hardware stays a ≤3h demo prop.

---

## 7. Acceptance criteria (checkable — Karpathy rule 3)

- **D0:** `make eval` prints a **finite distance MAE** float against the committed GT set. *(first)*
- **D0:** the scored keep/reject harness rejects a config delta that worsens MAE/continuity/FPS and
  keeps one that improves it, vs a frozen `baseline.json`. *(checkable)*
- **D:** each metric mover is accepted only if it holds/improves a **real** metric via D0.2.
- **A:** `kill -9` `overnight.py` mid-sweep → relaunch resumes remaining jobs, records the crashed
  one, and (two-process test) never reclaims a live `owner='web'` eval. *(checkable)*
- **A:** a hung job is killed at timeout **with no orphaned worker PIDs**; a corrupt `last.pt`
  falls back to a clean start. *(checkable)*
- **B:** console renders vector-crisp labels aligned to the **letterboxed** video rect; a
  `track-lost` badge appears within the debounce window; overlay **dims when telemetry stalls**.
- **B:** a live panel shows jobs transitioning in real time, with empty/loading/reconnect states.
- **C:** adding a backend = one `_BACKENDS` entry (no `registry.py` edit); adding a dataset = one
  `datasets.yaml` entry; a fine-tune added once shows in **both** CLI and web. *(checkable)*
- **C:** `import catranger.detect` and `registry.list()` do **not** import torch. *(checkable)*
- **All:** `make check` (ruff + mypy + pytest) green; new core logic ships with a test.

---

## 8. Alternatives weighed (review CEO#7 — real options, not straw men)

| Option | Effect on a *provable* outcome | Verdict |
|---|---|---|
| **Prove the number** (D0: GT + scored harness) | Converts "we think it's accurate" → "MAE X% (n=N), CI coverage Y" | **Highest leverage** — adopted as WS-D0 |
| Metric movers (WS-D) | Real metric gains, but only *after* D0 makes them measurable | Adopted, gated on D0 |
| Failure recovery (WS-A) | Reliability of producing numbers overnight; no direct metric move | Adopted; A3 no-regret, rest is `[plumbing]` |
| Real-time viz (WS-B) | Operator insight + demo; surfaces failures | Adopted; high demo value |
| Pluggability (WS-C) | Velocity to try new models/datasets → indirectly feeds WS-D | Adopted |
| Greenfield rebuild | Negative — duplicates a working system | **Rejected** |
| Prefect/Dagster/Ray/Celery | Broker + 2nd backup story for a single-box sweep | **Rejected** (P3) |
| entry_points/pluggy/pydantic-in-core | YAGNI at 2 backends | **Rejected** |
| WebRTC/WebCodecs now | Latency infra before latency is the proven bottleneck | **Deferred** (B5) |
| RF-DETR / YOLO12 now | Need fine-tune / heavier deploy / CPU caveats | **Deferred** unless YOLO26 recall is the bottleneck |

---

## 9. Failure modes registry

| Mode | Trigger | Guard |
|---|---|---|
| MAE unfalsifiable | no distance GT | **D0.1 GT set** |
| Keep/reject scores wrong thing | autoresearch = mAP | **D0.2 scored harness** |
| Smoothness gamed by damping | self-emitted jerk proxy | **D0.3 lag term** |
| Parent runner crash between jobs | reboot/OOM/ssh-drop | A1 + A2 owner-scoped sweep |
| Web eval reclaimed by overnight | shared table, naive sweep | **A2 owner scoping (Eng#1)** |
| Hung job + leaked GPU mem | no timeout / orphan workers | **A3 timeout + killpg (Eng#2)** |
| Resume on corrupt last.pt | crash mid-epoch | **A4 exception-based fallback (Eng#3)** |
| Overlay drift / phantom truth | canvas vs MJPEG; stale link | **B1 letterbox map + B4 stall-dim (Design#3/#7)** |
| Badge christmas-tree | failure cascade | **B2 precedence+budget+debounce (Design#4)** |
| Backend added in one file only | detect.py vs registry.py | **C1 single source of truth (DX#4)** |
| Silent zero-recall | nc=1 model + classes:[15] | **C4 drift warning (Eng#9)** |
| torch imported to list models | runtime-checkable Protocol | **C1 stub conformance + no-import test (Eng#8)** |
| New feature regresses metric | scored-core change | D0.2 keep/reject; `promote-revert` |

---

## 10. Test plan hooks (CI-aligned; `make check` stays green)

- **WS-D0:** assert finite MAE on the GT set; harness keeps-good / rejects-bad vs `baseline.json`.
- **WS-A:** **two-process** claim contention (each job runs once); **crash-injection** (`SIGKILL` a
  claimed row, relaunch, assert reclaim + no double-run); **timeout** asserts no orphan PIDs;
  **corrupt-last.pt** resume fallback. (Single-process unit tests alone are insufficient — Eng#7.)
- **WS-B:** server test for the B0 overlay-JSON shape; frontend test for letterbox alignment math +
  badge precedence + stall-dim.
- **WS-C:** registry validation (malformed → typed error) for both YAMLs; stub Protocol conformance;
  **no-torch-import** assertion; class-id drift warning.
- **WS-D:** golden-frame distance tests (eroded vs full median); harness rejects a non-improving
  change. Numbers live in YAML, never hardcoded.

---

## 11. Rollback / safety

Every workstream degrades to "baseline still demos": A* only help a run *complete*; B* are additive
UI over the unchanged MJPEG/telemetry path; C* default to the baseline profile; D* are individually
`promote`/`promote-revert`-able and keep/reject-gated (revert to pretrained baseline on regression).

---

## 12. Metric faithfulness (new — review CEO#4)

A 10x that optimizes a proxy can *lower* the real (hidden-set) score (Goodhart). Before any
scored-core change, know which signal you're moving:

- **Faithful — gate freely:** FPS.
- **Proxy — make real first (D0.3):** track continuity (`track_stats` counts id churn, no GT →
  score vs a labeled occlusion clip); command smoothness (jerk on self-emitted commands, gameable →
  pair with a tracking-lag term).
- **Unmeasured — make measurable first (D0.1):** distance MAE (`gts=None` today).

Rule: **proxy-only metrics must not gate scored-core changes** until D0 upgrades them.

---

## 13. Review report (autoplan)

**Source:** `subagent-only` (Codex CLI unavailable — ChatGPT account rejects every model id) +
9-agent grounding pass. Consensus tables below: the second column is the independent Claude
subagent; Codex is `N/A` (unavailable); a single critical finding is flagged regardless.

```
CEO consensus            Subagent   Codex   Result
 premises valid?         concern    N/A     2 premises were factually wrong → fixed (P2 corrected)
 right problem?          concern    N/A     evolve-not-rebuild ✓; "prove the number" added (WS-D0)
 scope calibration?      concern    N/A     sequencing → human gate
 alternatives explored?  gap        N/A     §8 added
 6-month trajectory?     concern    N/A     milestone order = the open decision
DESIGN consensus
 overlay contract?       gap        N/A     B0 added (was claimed to exist; it didn't)
 hierarchy/states?       gap/concern N/A    B1/B2/B3 now specify hierarchy + states + a11y
 canvas alignment?       concern    N/A     B1 letterbox mapping specified
 frame_id sync?          concern    N/A     B4 reframed as stall-detection (honest)
ENG consensus
 architecture sound?     concern    N/A     jobqueue split; "one store" corrected
 concurrency/durability? concern    N/A     A2 owner-scoping resolves A2↔A7 contradiction
 error paths?            concern    N/A     A3 killpg; A4 exception fallback; A5 structured signals
 test coverage?          gap        N/A     two-process + crash-injection tests added
DX consensus
 docs findable?          gap        N/A     C6 Extending docs
 extension ergonomics?   concern    N/A     C1 single source of truth; C3 one model home
 errors actionable?      sound      N/A     already strong; backend error msg improved
```

### Decision Audit Trail

| # | Phase | Decision | Class | Principle | Rationale |
|---|---|---|---|---|---|
| 1 | CEO | Add WS-D0 GT set (MAE measurable) | Mechanical | P1 goal-driven | `report.py:369 gts=None` — MAE unfalsifiable today |
| 2 | CEO | Add scored keep/reject harness; drop "reuse autoresearch" | Mechanical | P1 | `autoresearch.py:60` optimizes mAP, not frozen metric |
| 3 | CEO | Add §12 metric-faithfulness; honest proxy/faithful/unmeasured | Mechanical | P1 completeness | proxies are gameable (Goodhart) |
| 4 | CEO | Correct maintenance-mode framing (no deadline) | Mechanical | explicit | CEO voice anchored on stale `00-AUDIT.md` |
| 5 | CEO | Add §8 real alternatives | Mechanical | P1 | first draft straw-manned options |
| 6 | CEO | **Sequencing (foundation-first vs plumbing-first)** | **User Challenge** | — | **→ final gate (not auto-decided)** |
| 7 | Design | Add B0 overlay-JSON contract first | Mechanical | P1/P5 | telemetry is single-target scalars only |
| 8 | Design | Specify letterbox spatial mapping (B1) | Mechanical | P5 explicit | object-contain bars cause offset |
| 9 | Design | Badge precedence+budget+debounce (B2) | Mechanical | P1 | failure cascade overwhelms operator |
| 10 | Design | Reframe frame_id as stall-detection (B4) | Mechanical | P5 | MJPEG `<img>` exposes no per-frame id |
| 11 | Design | Add states + color tokens + a11y | Mechanical | P1 completeness | regressed existing a11y baseline |
| 12 | Eng | jobqueue.py module; history.py = projection (A1) | Mechanical | P5 explicit | history.py is zero-dep append-only by contract |
| 13 | Eng | Owner-scoped recovery sweep (A2) | Mechanical | P5 | resolves A2↔A7 cross-process contradiction |
| 14 | Eng | Process-group kill on timeout (A3) | Mechanical | P1 | orphan dataloader workers leak GPU mem |
| 15 | Eng | Exception-based resume fallback (A4) | Mechanical | P1 | corrupt last.pt throws, not "absent" |
| 16 | Eng | Per-process connection; "two files" stated (A1) | Mechanical | P5 | shared-connection idiom not multi-process safe |
| 17 | Eng | Structured failure signals over log-scraping (A5) | Mechanical | P5 | string match brittle across versions |
| 18 | Eng | Two-process + crash-injection tests (§10) | Mechanical | P1 | the cases WS-A exists for |
| 19 | Eng | Non-runtime-checkable Protocol + no-import test (C1) | Mechanical | P5 | isinstance would force torch import |
| 20 | Eng | Class-id drift warning (C4) | Mechanical | P1 | nc=1 + classes:[15] → silent zero-recall |
| 21 | DX | Unify model config home; `--model` (C3) | Mechanical | P4 DRY | two disjoint homes confuse contributors |
| 22 | DX | registry imports keys from builder dict (C1) | Mechanical | P4 DRY | kills the two-file sync trap |
| 23 | DX | Extending docs (C6); README claim tightened | Mechanical | P1 | product thesis was undocumented |
| 24 | DX | Default train.yaml source=manual; history filters | Mechanical | P5 | fresh-clone `make prepare` fails today |

**Completion summary:** CEO — 1 evolve-not-rebuild premise confirmed, 2 factual flaws fixed, 1 user
challenge to the gate. Design — WS-B rebuilt around a real overlay contract + honest sync + states +
a11y. Eng — WS-A correctness (ownership, killpg, resume, module split) + test plan hardened; WS-C
lazy-import discipline preserved. DX — extension ergonomics unified + documented. Cross-phase theme:
**the first draft asserted infrastructure that doesn't exist (MAE GT, scored keep/reject, overlay
contract) — all now made explicit deliverables.** One decision remains for the human: **§6 sequencing.**
