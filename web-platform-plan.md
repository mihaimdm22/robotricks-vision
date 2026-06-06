# CatRanger Web Platform — M3 + M5 + Next.js unification (reconstructed plan)

> Status: reconstructed 2026-06-06. The original `web-platform-plan.md` from the
> earlier `/autoplan` run was a transient artifact and is not in git; this rebuilds
> it from the shipped code (PR #4 backend, PR #5 landing page) and the
> `TODOS.md` "Web Control Platform" deferred list. Scope confirmed with the user:
> **M3 = Eval tab**, **M5 = control-plane hardening**, plus the **Next.js
> unification** (the console UI moves to Next.js; FastAPI becomes a headless API).

---

## 1. Current state (what actually shipped)

Two disconnected web tiers exist today:

- **FastAPI control plane** — `catranger/web/` (PR #4, "M1 M2 M4"):
  - `controller.py` — `RobotController`: safety core (mode IDLE/MANUAL/FOLLOW,
    manual drive vector, latched E-stop, watchdog dead-man's switch, typed
    `StopReason`). Pure, unit-tested, no I/O.
  - `runtime.py` — `RobotRuntime`: the integration edge. Owns the **single**
    background control thread (sole writer to the serial/BLE bridge), the camera
    source, perception (`CatRanger` when the `ml` extra is present, passthrough
    otherwise), JPEG publication, model hot-swap.
  - `registry.py` — `ModelRegistry` from `configs/models.yaml` (hot-swappable
    detector profiles).
  - `server.py` — FastAPI app: REST `/api/*`, one telemetry/control WebSocket
    `/ws`, MJPEG `/video`, `/healthz`. Typed errors `{ok, code, problem, cause,
    fix}`. **Currently also serves a vanilla-JS panel** from `static/`
    (`index.html` + `app.js` + `style.css`).
  - `GET /api/eval` is a **501 stub** ("reserved seam — eval lands in a follow-up
    milestone"). The static panel's Eval tab says "run `make eval` from the CLI."
  - Tests: `tests/test_web_{controller,registry,runtime,server}.py` via a
    `FakeRuntime` + FastAPI `TestClient`. Dedicated `web` CI leg.

- **Next.js landing page** — `apps/web/` (PR #5):
  - Next.js **16.2.7** / React **19.2.4**, Tailwind v4, `motion`. App Router.
  - Marketing site only (`src/app/page.tsx` + `src/components/site/*`), mock data,
    **not wired to the backend**. Shared primitives in `src/components/ui.tsx`
    (`GlassCard`, `BadgeChip`, `GradientButton`, `SectionHeading`, …) — the seed
    of the app-wide design system.
  - `apps/web/AGENTS.md`: **"This is NOT the Next.js you know"** — read
    `node_modules/next/dist/docs/` before writing any code. Treat as a hard rule.

The eval pipeline itself is solid and reusable: `catranger/eval/report.py`
exposes `run_eval(results, commands, frame_times, gts)` →
`build_report(metrics, out_path)` (markdown). `main()` drives the heavy pipeline
(`CatRanger.process` per frame) behind `make eval` /
`python -m catranger.eval.report --source ... --config ...`.

## 2. Goal + frozen metrics

Unify the web tier on Next.js with Python doing only what Python must (OpenCV
capture, YOLO inference, serial/BLE), finish the two skipped milestones, and hold
the line on the scored perception core.

**Frozen perception metrics (untouched — we do NOT edit `catranger/{intrinsics,
distance,detect,depth,track,pipeline}.py`):** distance MAE, track continuity,
FPS, command smoothness. The Eval tab *surfaces* these; it must not change them.

**Web-tier success criteria (checkable):**
1. `catranger serve` + `next dev` → the console at a Next.js route streams live
   MJPEG video, shows live telemetry over WS, and drives the robot (MANUAL) with
   the same press-and-hold / watchdog semantics as the vanilla panel.
2. Eval tab: click "Run eval" → a background job runs the eval pipeline over a
   chosen source and the rendered `report.md` + metric cards appear, without
   stalling the live control loop or fighting the camera/serial.
3. Two browsers open the console → only one holds the drive token; the other is a
   read-only observer that can still hit E-stop. No serial races.
4. `make check` (ruff + mypy + pytest) green; new core logic has tests;
   `next build` + `next lint` clean.

## 3. Architecture decision — Next.js UI + FastAPI headless API

Python **cannot** be removed: `RobotRuntime` is a long-lived, stateful, single
control thread that owns OpenCV capture, torch/ultralytics inference, and the
serial/BLE bridge. Node can't host that. So "everything on Next.js" =
**the entire UI/frontend moves to Next.js; FastAPI keeps only the API surface.**

```
                 ┌────────────────────────── Next.js (apps/web) ──────────────────────────┐
  browser  ───▶  │  /            marketing landing (existing)                              │
                 │  /console     control console (NEW: drive + telemetry + video + models) │
                 │  /console#eval Eval tab (NEW: run + render report)                      │
                 │  src/lib/api.ts  typed client  ─┐                                       │
                 └─────────────────────────────────┼───────────────────────────────────────┘
                                                    │  HTTP /api/*, WS /ws, MJPEG /video
                                                    ▼
                 ┌──────────────── FastAPI (catranger/web/server.py) ─────────────────────┐
                 │  REST /api/*   WS /ws   MJPEG /video   /healthz   (static panel REMOVED) │
                 │            └── RobotRuntime (single control thread, hardware, ML) ──┐    │
                 └──────────────────────────────────────────────────────────────────────────┘
```

**Origin / transport (key eng decision).** MJPEG (`<img src>`) and the control
WebSocket want a single origin to avoid CORS and WS-upgrade pain. Decision:
expose a **configurable API base** via `NEXT_PUBLIC_API_BASE` (e.g.
`http://localhost:8080` in dev). The client derives the WS URL and the video src
from it. This is robust and does not depend on Next.js rewrites proxying a WS
upgrade (historically flaky). We *also* add a `next.config.ts` `rewrites()` map
for `/api`, `/video`, `/healthz` as a dev convenience (HTTP only). FastAPI gains
a narrow CORS allowlist (the Next dev origin) guarded behind config — off by
default, on for dev. No auth/TLS (explicitly out of scope, LAN-only).

**Static panel.** Remove `catranger/web/static/*` and the `/` + `/static` mounts
from `server.py` (the console now lives in Next.js). Keep `/healthz`. This
deletes a second, now-duplicate UI — DRY.

## 4. M3 — Eval tab

Eval is a **heavy, minutes-long batch job** (YOLO over a source; needs the `ml`
extra). It must not block the async event loop, the control thread, or grab the
live camera. Design: a single background eval job, owned by the runtime,
pollable.

**Backend (`catranger/web/`):**
- New `eval_job.py` — `EvalJob`: runs the eval pipeline in a worker thread.
  Reuse `catranger.eval.report.run_eval` / `build_report`; refactor the heavy
  loop out of `report.main()` into a reusable
  `run_eval_job(source, *, config, approach, classes, max_frames, on_progress)`
  returning `(metrics, report_md_path)` so both the CLI and the web call one code
  path (DRY). The job runs over a **file/dir/video source** (defaults to
  `configs`-driven `data/raw/how_far`), never the live control camera.
- Runtime methods: `start_eval(params) -> {ok|error}` (refuse if one is already
  running → typed `eval_busy`), `eval_status() -> {state, progress, frames,
  started_at}` with `state ∈ idle|running|done|error`, `eval_result() ->
  {markdown, metrics}` once done.
- Server routes (replace the 501 stub):
  - `POST /api/eval/run` body `{source?, approach?, classes?, max_frames?}`
  - `GET  /api/eval/status`
  - `GET  /api/eval/report` → `{ok, markdown, metrics}` or typed
    `eval_not_ready` / `eval_failed`.
- Concurrency + resource honesty: only one job; while running, telemetry carries
  an `eval_running` flag so the UI warns "eval is running — live FPS may drop."
  (We do not auto-pause the robot; we surface it. Flagged as a known tradeoff.)

**Frontend (Next.js):**
- Eval tab in the console: source/approach/max-frames form → "Run eval" → poll
  `/api/eval/status` → on `done`, render metric **cards** from the structured
  `metrics` JSON (FPS, distance MAE/MAPE, tracking continuity, smoothness) plus
  the full `report.md` rendered as markdown. Use a small, well-maintained
  markdown renderer (`react-markdown` + `remark-gfm`) — Layer-1 dependency, not a
  hand-rolled parser.
- Empty/loading/error/busy states all specified (no "imagination" states).

**Tests:** route-contract tests with a `FakeRuntime` exposing a fake eval job
(idle→running→done→error transitions, busy refusal, not-ready). A unit test for
`run_eval_job` over a tiny synthetic source asserting it returns finite metrics +
writes a report (mirrors the existing eval-report test discipline).

## 5. M5 — control-plane hardening

Headline (P1, the real safety win): **single-controller token.** Today any WS
client can drive; two operators = racing intents to one serial writer.

- **Drive token.** First WS client to send an intent (or explicitly
  `claim_control`) holds the token and may drive; others are **observers**
  (telemetry + video, drive intents ignored with an `observer` nack). Token
  released on disconnect or idle-timeout; an observer can `request_control` →
  last-claim-wins takeover with a banner to the displaced operator ("control
  taken over"). **E-stop and reset are available to everyone, always** (safety
  must never be gated by the token). Implemented in `RobotController` (pure,
  unit-testable: claim/release/observer arbitration with the injectable clock) +
  surfaced in telemetry (`controller_id`, `you_are_controller`).
- **Device auto-discovery (P3).** `GET /api/robot/discover` → serial ports
  (`serial.tools.list_ports`) and, if `bleak` present, a short BLE scan; the
  Connections tab renders a pick-list instead of requiring a typed target.
  Degrades gracefully (empty list + hint) when transports are absent.
- **Offline weights (P3).** Vendor/pre-cache `yolo11s.pt` and document a
  `make fetch-weights` step so the demo runs with no network on first launch.

Scope discipline: the token is the substantive deliverable; discovery + offline
weights are small, in-blast-radius add-ons. If either grows past ~½ day, it
splits to a follow-up — it must never block the console working.

## 6. Next.js unification (the migration)

- **Console route** `apps/web/src/app/console/page.tsx` (client component) +
  `src/components/console/*`: port the vanilla panel feature-for-feature into
  React using the existing design system (`ui.tsx` primitives, Tailwind tokens):
  persistent safety header (SIM/LIVE badge, mode badge, E-STOP, ARM/RESET),
  stop-reason banner, video pane with VIDEO-STALE overlay, primary telemetry
  strip (distance / ground truth / target), diagnostics pills, and tabs
  (Control / Models / Connections / Eval).
- **API client** `src/lib/api.ts`: typed wrappers over REST, a `useTelemetry`
  hook (WS with auto-reconnect + heartbeat), press-and-hold drive (W/A/S/D +
  pointer) preserving the 120 ms re-send + release-to-stop watchdog contract.
  Types mirror the server's telemetry/error shapes.
- **Read the local Next docs first.** Per `apps/web/AGENTS.md`, before writing
  route handlers, `next.config.ts` rewrites, client components, or data fetching,
  read the matching guide under `apps/web/node_modules/next/dist/docs/`. No
  assumptions from training data on App Router conventions.
- **Run story.** `make web` (or a documented two-terminal flow) runs
  `catranger serve` (:8080) + `next dev` (:3000). README + `apps/web/README.md`
  updated. Marketing landing's CTA ("Open Console") now links to `/console`.

## 7. Non-goals (explicitly out of scope)

Auth / TLS / public internet exposure; WebRTC video (MJPEG stays); in-browser
training/annotation; session record/replay; native mobile; multi-robot;
serving the Next.js build *from* FastAPI in production (Next runs as its own
process). Any of these → `TODOS.md`, not this plan.

## 8. Test plan

- **Python:** `run_eval_job` unit test (finite metrics + report written over a
  synthetic source); eval route-contract tests (run/status/report, busy refusal,
  not-ready); controller token arbitration unit tests (claim/observer/takeover,
  E-stop ungated); discovery route returns a list / graceful-empty. Keep
  `runtime.py`/`server.py` on the integration side (route tests via FakeRuntime),
  matching the existing coverage policy.
- **Frontend:** `next build` + `next lint` clean; a smoke test of the console
  page rendering with a mocked API; manual verification checklist (drive, E-stop
  from observer, eval run-to-render, stale overlay).
- **Gate:** `make check` green.

## 9. Risks

1. **WS through a proxy** — mitigated by the configurable `NEXT_PUBLIC_API_BASE`
   (connect WS straight to FastAPI), rewrites only a dev nicety.
2. **Eval starves the control loop** on a weak demo box — surfaced via
   `eval_running` warning; eval uses its own pipeline over a file source, never
   the live camera; document running eval while IDLE.
3. **Next.js 16 breaking changes** — mitigated by the read-the-local-docs rule.
4. **Two-process run friction** — mitigated by a single `make web` target + docs.
5. **Removing the static panel** loses the no-Next fallback — acceptable per the
   "everything on Next.js" goal; the API is still curl-able for emergencies.

## 10. Sequencing

1. Headless API: strip static panel + mounts, add config-gated CORS, keep
   `/healthz`. (small, unblocks everything)
2. Next.js console port (Control/Models/Connections) + `api.ts` + `useTelemetry`.
3. M3 eval: `run_eval_job` refactor → routes → Eval tab + report rendering.
4. M5 hardening: drive token (core) → discovery → offline weights.
5. Docs + `make web` + tests; `make check`; manual verification.

---

## GSTACK REVIEW REPORT (4 independent voices: CEO / Eng / Design / DX)

Run on Windows; gstack Codex/bash machinery is Unix-only, so review used four
independent Claude subagents (each read the plan + real code with no shared
context). Verdicts: **CEO** — decouple milestones from the rewrite, keep the
demo safety net, fix the empty-distance gap. **Eng** — sound, conditionally
approve; move arbitration to the server/WS layer; verify the Next-docs path
exists. **Design** — safety-UX-incomplete; promote stop-reason taxonomy,
observer/link-lost states, release-to-stop to tested first-class reqs; add an
operational (non-glass) variant. **DX** — not demo-ready; `make web` is
Unix-only on a Windows repo and the onboarding docs are still boilerplate.

### Consensus table (CONFIRMED = ≥2 voices independently agree)

| # | Finding | Voices | Sev | Disposition |
|---|---------|--------|-----|-------------|
| C1 | Deleting `static/` removes the only zero-Node demo fallback | CEO+Eng+DX | crit | **USER CHALLENGE** → ask |
| C2 | Eval distance MAE/MAPE is always empty (`gts=None`), and `data/raw/how_far` isn't in the repo | CEO+Eng | crit | auto: scope cards to available metrics; eval source REQUIRED + path-validated |
| C3 | Eval worker starves the live control loop on a weak box | CEO+Eng+Design | high | auto: gate `start_eval` to refuse unless mode==IDLE |
| C4 | `node_modules/next/dist/docs/` path the AGENTS.md rule depends on may not exist | Eng+DX | high | auto: verify at impl step 0; fall back to pinned release notes if absent |
| C5 | `make web` doesn't exist and is Unix-only (repo is Windows) | DX | crit | auto: cross-platform `scripts/web.py` (`uv run`) + documented 2-terminal PowerShell/bash |
| C6 | Arbitration must live in server/WS layer (controller has no conn identity) | Eng | high | auto: `ControlArbiter` in server; per-conn telemetry merge |
| C7 | Safety-UX must be first-class + tested: stop-reason taxonomy, observer state, link-lost telemetry state, release-to-stop | Design | crit | auto: lift typed `STOP_TEXT`, 3 telemetry-link states, `setPointerCapture`+window listeners, StrictMode-safe timers, blur/visibility→stop |
| C8 | Marketing glass/neon aesthetic wrong for a dense safety console | Design | high | auto: operational variant (solid surfaces, reserved red/amber/green, no idle anim near status); reuse only type+spacing tokens |
| C9 | E-stop/reset must be ungated by token AND visually exempt from all lockouts | CEO+Eng+Design | crit | auto: whitelist estop/reset before holder check + test; E-STOP always full-opacity/clickable |
| C10 | `NEXT_PUBLIC_API_BASE` makes CORS mandatory; rewrites become dead/split-brain | Eng | med | auto: drop rewrites; client always uses API base; CORS origin in `configs/web.yaml` |
| C11 | Token must expire on heartbeat age, not only clean `WebSocketDisconnect` | Eng | med | auto: expire on stale heartbeat (reuse 200ms client heartbeat) |
| C12 | `react-markdown` over-scoped for our own trusted report | CEO | low | auto: render cards from metrics JSON + raw report in `<pre>`; no dep |
| C13 | Offline-weights `.pt` contradicts the >512 KB pre-commit gate | DX | med | auto: fetch-on-demand into gitignored cache via cross-platform script; never commit weights |
| C14 | Onboarding: missing `.env.example`, `pnpm install` step, Node pin, real READMEs | DX | high | auto: ship `.env.example` + client default, pin Node `engines`/`.nvmrc`, rewrite both READMEs |
| C15 | `run_eval_job` must carry `use_depth/device/stride/camera` or DRY claim is false | Eng | med | auto: thread all four through the shared path; `main()` calls it |
| C16 | Discovery `list_ports`/BLE scan are blocking in async route | Eng | low | auto: `asyncio.to_thread` |
| C17 | Keyboard driving fires while typing in form inputs | Design | med | auto: gate on `activeElement` not input/textarea/select |

### Cross-phase theme (highest-confidence signal)
**Don't sacrifice the guaranteed demo for the rewrite.** Three of four voices
independently said: keep the static panel as the zero-Node fallback and verify
the Next console on the actual demo hardware before deleting anything. This is
the one decision elevated to the user (C1).

### Decision audit (auto-decided via the 6 principles)
All C2–C17 auto-decided and folded into the plan above (safety+completeness
dominate; explicit-over-clever for arbitration; DRY for the eval path; pragmatic
for dropping react-markdown/rewrites). C1 is a User Challenge — not auto-decided.

## IMPLEMENTATION STATUS (shipped on branch feat/web-m3-m5-nextjs-console)

User decisions at the gate: C1 = **keep static panel as fallback**; eval distance
= **show only when GT supplied**; **implement the full plan**.

**Backend (Python):**
- `catranger/eval/report.py` — extracted `run_eval_job()` (the one heavy eval
  path; CLI `main()` now delegates to it; carries use_depth/device/stride/camera).
- `catranger/web/eval_job.py` — `EvalJob` (idle/running/done/error/cancelled,
  one-at-a-time, cooperative cancel).
- `catranger/web/arbiter.py` — `ControlArbiter` (drive token; auto-claim,
  takeover, idle + disconnect expiry).
- `catranger/web/runtime.py` — `start_eval` (IDLE-gated, source-validated, typed
  errors), `eval_status/result/cancel`, `discover_devices`, `eval_running`
  telemetry.
- `catranger/web/server.py` — config-gated CORS, eval routes, `/api/robot/discover`
  (threadpool), arbiter-gated WS with **E-stop/reset ungated**, per-connection
  `you_are_controller`. Static panel + `/` KEPT (fallback).
- `configs/web.yaml` — `cors_origins`, `control_idle_timeout_s`.

**Frontend (Next.js, all client):** `apps/web/src/lib/{api,useTelemetry,
stopReasons}.ts`, `src/components/console/*` (SafetyHeader, StatusBanner,
VideoPane, TelemetryStrip, DrivePad, Models/Connections/Eval tabs, Console),
`src/app/console/page.tsx`; operational CSS variant in `globals.css`; landing
CTAs → `/console`.

**Tooling/docs:** `scripts/web.py` (cross-platform launcher), `scripts/
fetch_weights.py`, Makefile `web`/`web-setup`/`fetch-weights`, `apps/web/
.env.example` + `.nvmrc` + engines, README + apps/web/README rewrites.

**Tests:** `tests/test_web_arbiter.py`, `test_web_eval_job.py`, eval/discovery/
two-WS-arbitration cases in `test_web_server.py` (replaced the 501-stub test).

**Verification:** ruff clean; mypy clean (32 files); pytest 63/63 web pass
(full suite 116 pass, 1 pre-existing unrelated Windows path failure in
`test_io.py`); `next build` + `next lint` clean; live server smoke test of
status/eval/discover/WS endpoints passed.

