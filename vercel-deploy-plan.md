<!-- /autoplan restore point: new file, no prior state (created 2026-06-06) -->
# CatRanger — Vercel deployment plan (Next.js frontend)

> Status: draft 2026-06-06 on branch `vercel`. Goal: publish the CatRanger web
> frontend (`apps/web`, Next.js 16.2.7) to Vercel. The Python FastAPI control
> plane is **not** deployable to Vercel and is explicitly out of scope to move.
> This plan decides exactly what goes to Vercel, how the hosted console reaches a
> backend (or doesn't), and what stays a local tool.

---

## 1. Current state (what we're deploying from)

- **Monorepo**: repo root is the Python package (`catranger`). The web app is
  `apps/web/`, and `apps/web/` is its **own pnpm workspace root** —
  `pnpm-workspace.yaml` + `pnpm-lock.yaml` live there, not at repo root. Vercel's
  *Root Directory* must therefore be `apps/web`.
- **Framework**: Next.js **16.2.7** / React **19.2.4**, Tailwind v4, App Router,
  `motion`. `package.json` pins `engines.node >= 20.9.0`; `.nvmrc` pins 22.
  `apps/web/AGENTS.md` is a hard rule: "This is NOT the Next.js you know — read
  `node_modules/next/dist/docs/` before writing framework code." That rule binds
  this plan too (any `next.config.ts` / route / build-setting change).
- **Two routes**:
  - `/` — marketing landing. Pure static content from `src/lib/content.ts` (mock
    copy + a mock `liveDistance`). No backend calls, no secrets, no env at build.
    **Vercel-safe as-is.**
  - `/console` — client component. All REST/MJPEG/WS calls derive from
    `API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080"`
    (`src/lib/api.ts`). `NEXT_PUBLIC_*` is **inlined into the client bundle at
    build time**, so one Vercel build bakes in exactly one backend URL.
- **Backend** (`catranger/web/server.py`, `runtime.py`): FastAPI + a single
  long-lived stateful control thread that owns OpenCV capture, torch/ultralytics
  inference, MJPEG streaming (`/video`), a control WebSocket (`/ws`), and the
  serial/BLE bridge. CORS is a config-gated allowlist in `configs/web.yaml`
  (`cors_origins`, currently `localhost:3000` / `127.0.0.1:3000`).

## 2. The one hard constraint (surfaced, not buried)

**Vercel can host the Next.js frontend. It cannot host the control plane, and a
public HTTPS frontend cannot talk to a LAN HTTP backend.** Three independent
blockers, all real:

1. **No home for the backend.** `RobotRuntime` is a persistent, single-threaded,
   stateful process doing hardware I/O and torch inference with MJPEG/WS streams.
   Vercel runs stateless, short-lived serverless/edge functions with payload and
   duration limits and no long-lived sockets. Non-starter — and moving it is an
   explicit non-goal (§7).
2. **Mixed content.** A page served over `https://…vercel.app` cannot `fetch`,
   `<img src>`-stream, or open a WebSocket to `http://` / `ws://` (a LAN box).
   Browsers hard-block it. So the hosted console can only reach a backend that is
   itself `https://` + `wss://`.
3. **Build-time URL bake.** `NEXT_PUBLIC_API_BASE` is frozen into the bundle at
   `next build`. One Vercel deployment = one fixed backend URL. That is wrong for
   the real usage pattern (a different LAN demo box every time).

These mean the "obvious" read — *deploy the whole console to Vercel and point it
at the robot* — does not work without extra moving parts (a public TLS tunnel to
the backend) that also collide with the project's "no auth, LAN-only" stance (§7,
existing `web-platform-plan.md` non-goals).

## 3. Decision — what actually ships to Vercel (RESOLVED: Shape A)

**Scope chosen at the /autoplan gate (User Challenge R12): landing public,
console stays a local tool.** Both review voices recommended this; it matches the
frozen-metric doctrine ("deployment is garnish → minimum code").

- Vercel hosts the Next.js app built from `apps/web`. We keep **one build** (no
  route fork), but the **public landing `/` is the only advertised deliverable.**
- **Landing `/`** is the public, shareable marketing URL. Backend-free. (Fix the
  mock-as-live + dead-link issues first — see §4.0.)
- **Un-link the console from the public site.** The hero/nav/footer "Open Console"
  CTAs (`content.ts`) currently point at `/console`; repoint them to the repo's
  "run it locally" docs so a public visitor is never dropped onto a control panel
  for a robot they cannot reach. The `/console` route still exists in the build,
  but a stray visitor who types the URL sees a plain **"no backend — this console
  runs locally"** disconnected state, not a broken screen (light R3, §4.2).
- **Console stays a local tool** (`pnpm dev` / local `next start` → `catranger
  serve` on the same LAN, where `http://` works). The one convenience we keep:
  resolve `API_BASE` from `localStorage` at **runtime** so the *local* console can
  be pointed at any LAN IP (phone access) without editing `.env.local` + rebuild.

**Why Vercel (R11).** The branch targets Vercel and the landing is a zero-config
Next 16 app; Vercel gives per-PR preview deploys and reads the lockfile/`engines`
directly. A pure static export to GitHub/Cloudflare Pages is viable (the landing
is static), but loses preview deploys and adds an export step; not worth it here.

**Explicitly NOT in this plan (deferred to `TODOS.md`):** the hosted-console
workstream — mixed-content/CORS typed error taxonomy, the `/healthz` reachability
probe, and a public TLS tunnel (Cloudflare/Tailscale/ngrok) to the backend. The
tunnel is the only way a *hosted* console could drive a robot, and it exposes a
**no-auth control plane to a public URL** (CORS is not auth — anyone with the link
could drive). Against the LAN-only/no-auth non-goal; revisit only with auth.

## 4. Frontend changes (the only code we touch)

Minimum, all in `apps/web` (the scored perception core is untouched — frozen).
Backend: **no code change** (CORS already config-gated in `configs/web.yaml`).

**4.0 — Make the public landing honest (R7, blocks go-live).**
- Relabel the `LiveDistanceCard` mock as **"Example readout"** (not a pulsing
  green "LIVE DISTANCE") — `live-distance.tsx`, `content.ts:liveDistance`. Don't
  present fabricated "1.84 m / Mochi / HC-SR04 truth" as a live feed on a public
  URL.
- Kill the dead links: 11 footer `href="#"` (`footer.tsx`) + nav "Docs"
  (`content.ts`). Remove "Admin"/"Live demo" (imply features that don't exist);
  repoint the rest to real anchors or the repo, or drop them.

**4.1 — Runtime `API_BASE` (local-tool convenience). Do it correctly (R4/R5/R6):**
- `src/lib/api.ts`: resolve at runtime, **lazily, inside the functions** —
  `localStorage["catranger.apiBase"]` → `NEXT_PUBLIC_API_BASE` →
  `http://localhost:8080`. **Guard `typeof window !== "undefined"`** (the
  `/console` route prerenders server-side; `localStorage` is `undefined` there —
  an unguarded read throws `ReferenceError` at build). Convert **`VIDEO_URL`
  const → `videoURL()` function** and resolve inside `req()` (every REST call) and
  `wsURL()`. Update the one value-import call site: **`VideoPane.tsx:38`**
  (`VIDEO_URL` → `videoURL()`).
- A saved base must re-point the **live** WS + MJPEG: `useTelemetry` reads
  `wsURL()` once in an effect keyed `[send]` (`:93`), so a localStorage change
  alone won't reconnect. Keep the base in React state and **remount `Console` via
  a `key`** on change (simplest explicit fix; no rewrite of the reconnect loop).
- The "Backend URL" field lives in the **Connections tab** (local use), reusing
  the existing `Msg` pattern; render the full `problem`+`cause`+`fix` (R14 —
  current `ConnectionsTab` drops `cause`). No `/healthz` probe, no mixed-content
  taxonomy here (deferred — those only matter for the hosted-console story).

**4.2 — `/console` no-backend state (light R3).** When `link === "disconnected"`
and no base is configured, render a top-level "No backend connected — this
console runs locally; start `catranger serve` (see README)" banner instead of
silent failed-fetch toasts. Cheap hygiene for a stray visitor; not the full
hosted first-run flow (deferred).

**4.3 — Docs (R7-adjacent / DX R3).** Edit (not create) `apps/web/.env.example` +
`README.md`: state plainly that `NEXT_PUBLIC_API_BASE` is **baked at build time**
(on Vercel, changing it needs a redeploy — typically leave it **unset**), and the
runtime Backend URL field is the per-session override for local use. Add a Vercel
section: Root Directory `apps/web`, build `pnpm build`, install `pnpm install`,
**set Node 22 in Vercel project settings** (`.nvmrc` is local-only — Vercel
ignores it; `engines`/dashboard govern), no env required for the landing.

**4.4 — `vercel.json` (R10, decide now).** Commit a minimal `apps/web/vercel.json`
pinning framework + Root Directory so the monorepo config is reviewable in-repo,
not dashboard-only. Verify against `node_modules/next/dist/docs/` per AGENTS.md
before adding any build knob. Add `packageManager` to `package.json` to pin the
pnpm major (R9). Before promoting: check the preview build for `sharp`/
`ignoredBuiltDependencies` warnings and confirm `next/image` works on the landing,
or set `images.unoptimized` deliberately (R9).

## 5. Frozen metrics — untouched

Distance MAE, track continuity, FPS, command smoothness all live in
`catranger/{intrinsics,distance,detect,depth,track,pipeline}.py` and the eval
pipeline. **This plan changes none of them.** Deployment is infrastructure for
the marketing site + a convenience for the console; per CLAUDE.md it is "demo
garnish" relative to the scored core, so it must not touch the core or add knobs
there. Success here is measured only by: the landing is live, and the console
either drives a reachable backend or says exactly why it can't.

## 6. Success criteria (checkable)

1. `https://<project>.vercel.app/` serves the landing; `next build` + `next lint`
   clean; the public landing shows no "LIVE" mock and no dead `href="#"` links
   (R7); `next/image` renders (R9).
2. The public landing's console CTAs point at run-locally docs/repo, not a dead
   `/console` (R12 un-link).
3. A stray visit to `/console` on the hosted URL shows the "no backend — runs
   locally" banner, never a blank/stack-trace screen (light R3).
4. **Local** console: `pnpm dev` + `catranger serve` works at the default
   `http://localhost:8080`; entering a LAN IP in the Backend URL field re-points
   video + telemetry + drive **without a rebuild** (R6 remount verified).
5. Build with **no env set** succeeds (landing needs none); `localStorage` resolve
   does not break the `/console` prerender (R5 SSR guard verified).
6. `make check` (ruff + mypy + pytest) stays green — no Python touched.

## 7. Non-goals (explicit)

Running FastAPI / `RobotRuntime` on Vercel (impossible — stateful hardware loop);
standing up and operating a public tunnel to the backend as a supported feature;
adding auth/TLS to the backend; WebRTC; serving the Next build from FastAPI in
prod; SSR data-fetching from the backend at build time (landing stays static
mock content). Any of these → `TODOS.md`, not this plan.

## 8. Test / verification plan

`apps/web` has **no test runner today** (R8: no vitest/jest, zero test files).
Standing one up for one resolver is more scope than this garnish-tier change
warrants, so for Shape A we verify by **TypeScript + lint + build + manual**, and
defer the vitest+jsdom runner to `TODOS.md` (it pays off when the frontend grows
more pure logic). If the runner is added, the first test is the `API_BASE`
resolution order (localStorage > env > default) + SSR `window`-guard.

- **Build/type**: `pnpm build` + `pnpm lint` clean from `apps/web`; confirm the
  Vercel preview with Root Directory `apps/web` reproduces it; build with no env.
- **Manual (local)**: `pnpm dev` + `catranger serve` at default; set a LAN IP in
  the Backend URL field → video/telemetry/drive re-point without rebuild (R6);
  E-stop. Stray `/console` with no backend → the "runs locally" banner (R3).
- **Manual (preview)**: landing renders; no "LIVE" mock, no dead links (R7);
  `next/image` OK (R9); console CTAs go to run-locally docs, not `/console`.
- **Regression**: local default path unchanged; `make check` green.

## 9. Risks

1. **Mixed content silently breaks the hosted console** — mitigated by the
   explicit `mixedContentBlocked` detection + typed error (criterion #4).
2. **Vercel monorepo/root-dir misconfig** (it's a nested pnpm workspace) — pin
   Root Directory = `apps/web`; verify the first preview build before promoting.
3. **Next.js 16 custom build vs Vercel defaults** — follow AGENTS.md
   (`node_modules/next/dist/docs/`); don't assume App Router/build conventions.
4. **No-auth backend exposed via a tunnel** if a user follows the advanced path —
   documented as at-your-own-risk; auth is a separate plan.
5. **`NEXT_PUBLIC_API_BASE` confusion** (build-time vs runtime override) —
   mitigated by README + `.env.example` wording and the in-UI field being the
   source of truth for the hosted console.

## 10. Sequencing (Shape A)

1. **Landing honesty (§4.0, R7)** — relabel mock, kill dead links, repoint console
   CTAs. (unblocks a clean public go-live; smallest, highest-value)
2. **Runtime `API_BASE` (§4.1, R4/R5/R6)** — lazy+window-guarded resolve;
   `VIDEO_URL`→`videoURL()` + `VideoPane.tsx:38`; `Console` `key`-remount on base
   change; Backend URL field rendering full `problem/cause/fix`.
3. **`/console` no-backend banner (§4.2, light R3).**
4. **Docs (§4.3)** — `.env.example` build-vs-runtime note, `apps/web/README` +
   root README Vercel section.
5. **Vercel project (§4.4)** — `vercel.json` + `packageManager`; Root Directory
   `apps/web`, Node 22 in settings; preview deploy; verify §6 criteria 1–6 +
   `sharp`/`next/image`; promote to production.
6. `make check` green; merge.

> Deferred to `TODOS.md` (the hosted-console workstream, cut at the gate):
> mixed-content + CORS typed error taxonomy; `/healthz` reachability probe;
> vitest+jsdom runner; public TLS tunnel (needs auth first).

---

## GSTACK REVIEW REPORT — /autoplan (4 independent voices)

Run on Windows; gstack Codex/bash machinery is Unix-only and `codex` is not
installed, so review ran in **single-model / subagent-only mode** — four
independent Claude subagents (CEO, Design, Eng, DX), each reading the plan + the
real code with no shared context. All verdicts: **APPROVE-WITH-CHANGES**. Every
load-bearing premise was verified against code (see C3 below) and held.

### Consensus table (CONFIRMED = ≥2 voices independently agree)

| # | Finding | Voices | Sev | Disposition |
|---|---------|--------|-----|-------------|
| R1 | **CORS, not mixed-content, is the real hosted-console dead end.** The hosted Vercel origin must be in `cors_origins` (`server.py:100-108`) or every REST `fetch` fails as the generic `unreachable` — indistinguishable from "server down". Plan only enumerates the mixed-content trap. | Eng+DX+Design | high | auto: add CORS to the typed-error taxonomy + risks; distinct typed hint; promote the `cors_origins` edit to a first-class step |
| R2 | **`/healthz` returns `204`; the probe is mis-specified.** `req()` calls `r.json()` (`api.ts:39`) → a 204 resolves to `{}` with `r.ok` true (false "reachable"), while CORS/mixed-content throw → `unreachable`. Inconsistent across the exact states it must disambiguate. | Design+DX | med | auto: probe checks `res.ok`, never parses a body |
| R3 | **First-visit hosted console = wall of failed-fetch errors, not a designed empty state.** `useTelemetry` opens the WS on mount (`Console.tsx:33`), `VideoPane` `<img>`s a dead URL; the "Backend URL" field is buried in the non-default Connections tab. §6.2 says this must never happen. | CEO+Design | high | auto: top-level first-run empty state ("No backend — hosted demo; set a Backend URL or run locally") + deep-link to the field |
| R4 | **Runtime-resolve change list (§4.1) is incomplete.** Must convert `VIDEO_URL` const→function (`api.ts:15`), fix `req()` (every REST call, `api.ts:35`), `wsURL()`, AND update `VideoPane.tsx:38` (imports `VIDEO_URL` as a value → breaks). Plan named only `VIDEO_URL`/`wsURL`. | Eng | high | auto: enumerate all four sites + `VideoPane` |
| R5 | **`localStorage` is `undefined` during SSR/prerender of `/console`** (server component at `page.tsx`). A resolver touching it at module-eval throws `ReferenceError`; `VIDEO_URL` is interpolated in JSX that renders during SSR. | Eng | high | auto: lazy resolve inside functions, `typeof window !== "undefined"` guard |
| R6 | **A saved Backend URL won't re-point the live WS/MJPEG.** `useTelemetry` reads `wsURL()` once in an effect keyed `[send]` (`:93`); MJPEG cache-buster won't bump. Criterion #3 silently fails until reload. | Eng | high | auto: store base in React state/context + remount `Console` via `key` on change |
| R7 | **Marketing landing is NOT "safe as-is" for a public URL.** `LiveDistanceCard` renders mock numbers ("1.84 m", track "Mochi", pulsing green **"LIVE DISTANCE"**) as if live; 11 footer links + nav "Docs" are `href="#"` ("Admin"/"Live demo" imply features that don't exist). | Design | high | auto: relabel mock as "Example/Sample"; remove/repoint dead links; drop "Admin"/"Live demo" |
| R8 | **No test infra exists in `apps/web`** (no vitest/jest, zero test files). §8/§10 promise unit tests as a one-liner. | Eng | high | auto: scope vitest+jsdom as explicit setup work in §10, or downgrade §8 to manual + state it |
| R9 | **Vercel ignores `.nvmrc`** (uses dashboard Node setting + `engines`); no `packageManager` pin; `sharp` in `ignoredBuiltDependencies` may break `next/image` optimization at runtime on the landing. | DX | med | auto: set Node 22 in project settings + tighten `engines`; add `packageManager`; verify `sharp`/`next/image` on preview or set `images.unoptimized` deliberately |
| R10 | **`vercel.json` left conditional** despite monorepo root-dir being risk #2; dashboard-only config is a team-build DX smell. | DX | low | auto: commit a minimal `vercel.json` (or a README "Vercel settings" table) — decide now, not "if needed" |
| R11 | **Cheaper/static hosts dismissed without analysis** (static export → GitHub/Cloudflare Pages); plan never says *why Vercel*. | CEO | med | auto: add one paragraph justifying Vercel (preview deploys, zero-config Next 16) vs static-export-to-Pages |
| R12 | **`mixedContentBlocked` + reachability + Save/Reset is gold-plated for a hosted dead-end.** The honest minimum that adds value is runtime-resolve from localStorage (a *local-tool* win: one build, any LAN IP). | CEO | med | → **USER CHALLENGE** (scope; see below) |
| R13 | **No-auth control plane: CORS is not auth.** Adding the Vercel origin to `cors_origins` for a tunneled backend means anyone who loads the public URL can drive the robot — the public frontend itself is the attack surface. | Eng | high | auto (correctly scoped already): sharpen README warning specificity; tunnel stays a non-goal |
| R14 | `ConnectionsTab` renders only `problem — fix`, drops `cause` (`:25,46`); the mixed-content message's most useful line is `cause`. | Design | med | auto: render full `problem`+`cause`+`fix` for the new states |
| C3 | **Premises verified, all hold (positive).** Backend can't run on Vercel (stateful control thread); `/healthz` exists (`server.py:262`); `next.config.ts` empty → no rewrite escape hatch, mixed-content blocker is real. | CEO(+Eng) | — | accept framing (→ premise gate) |

### Cross-phase theme (highest-confidence signal)
**The hosted `/console` cannot reach its goal, and the plan partly admits it.** CEO
and Design independently said: a public control console for an unreachable LAN
robot is, at best, a nicer error message — and at worst a broken-looking demo or
(via the tunnel recipe) a security exposure. The strategic decision — *do we ship
`/console` to the public URL at all, or go landing-only-public with the console
as a local tool* — is the User Challenge elevated to the gate (R12).

### Decision audit (auto-decided via the 6 principles)
R1, R2, R4, R5, R6, R9, R10, R14 — **explicit-over-clever + completeness** (P5,
P1): correctness/specification gaps in the one new feature; folded into the plan.
R3, R7 — **completeness** (P1): missing designed states / public-URL honesty;
folded. R8 — **completeness** (P1): scope the test runner explicitly. R11 —
**pragmatic** (P3): one justifying paragraph. R13 — already correctly scoped;
sharpen wording. **R12 is a User Challenge — NOT auto-decided** (scope change to
the user's stated "deploy" direction; surfaced at the final gate).

### Gate decisions (user)
- **Premise gate (D2):** framing accepted — backend can't go on Vercel; hosted
  console can't drive a LAN robot; ship the frontend, console degrades.
- **R12 / scope (D3):** **Shape A — landing public, console stays local.** The
  hosted-console workstream (mixed-content/CORS taxonomy, `/healthz` probe, TLS
  tunnel, vitest runner) is cut from this plan and deferred to `TODOS.md`. Kept:
  the runtime `API_BASE` resolve (done correctly per R4/R5/R6) as a *local-tool*
  convenience, the landing-honesty fixes (R7), and the Vercel mechanics (R9/R10).

### Decision Audit Trail

| # | Phase | Decision | Class | Principle | Rationale |
|---|-------|----------|-------|-----------|-----------|
| R1 | Eng/DX | Defer CORS/mixed-content typed taxonomy | auto→deferred | P3 | only matters for hosted console (cut at gate) |
| R2 | Design/DX | Defer `/healthz` 204-aware probe | auto→deferred | P3 | part of cut hosted-console story |
| R3 | Design | Light no-backend banner on `/console` | auto | P1 | cheap hygiene; full first-run flow deferred |
| R4 | Eng | Enumerate all 4 rewrite sites + `VideoPane.tsx:38` | auto | P5 | runtime-resolve is wrong if half-wired |
| R5 | Eng | Lazy + `window`-guard `localStorage` | auto | P5 | unguarded read breaks `/console` prerender |
| R6 | Eng | `key`-remount `Console` on base change | auto | P5 | saved base must re-point live WS/MJPEG |
| R7 | Design | Fix landing: mock-as-live + dead links | auto | P1 | public-URL honesty; blocks go-live |
| R8 | Eng | Defer vitest runner; verify build+manual | auto | P2/P3 | runner > scope for one resolver (garnish tier) |
| R9 | DX | Node 22 in settings, `packageManager`, sharp check | auto | P1 | `.nvmrc` ignored by Vercel; image opt risk |
| R10 | DX | Commit minimal `vercel.json` | auto | P5 | reviewable in-repo > dashboard-only |
| R11 | CEO | One paragraph justifying Vercel vs Pages | auto | P3 | branch targets Vercel; preview deploys win |
| R12 | CEO | **Shape A** (landing public, console local) | **user challenge** | — | user chose A at D3 |
| R13 | Eng | Tunnel stays non-goal; sharpen no-auth warning | auto | P4/P5 | CORS≠auth; public URL = attack surface |
| R14 | Design | Render full `problem/cause/fix` for new states | auto | P5 | `ConnectionsTab` currently drops `cause` |

> **Review mode:** single-model (`[subagent-only]`) — `codex` not installed on
> this Windows host; the four independent Claude subagents are the voices.
> No cross-phase disagreements (all four converged on APPROVE-WITH-CHANGES and on
> the console-is-a-dead-end theme); no taste decisions split the voices.

## IMPLEMENTATION STATUS (Shape A, on branch `vercel`)

**Frontend (`apps/web`, the only code touched — scored core untouched):**
- `src/lib/api.ts` — runtime origin resolution: `localStorage["catranger.apiBase"]`
  → `NEXT_PUBLIC_API_BASE` → `http://localhost:8080`, resolved lazily + window-
  guarded (`storedApiBase`/`apiBase`/`setApiBase`/`clearApiBase`/`videoURL`/`wsURL`);
  `req()` resolves per-call; error `cause`/`fix` reference the effective base (R4/R5).
- `components/console/VideoPane.tsx` — `VIDEO_URL` value → `videoURL()` call (R4).
- `components/console/Console.tsx` — split into `Console` (holds the effective base
  as a `key`) + `ConsoleBody`; a saved Backend URL remounts the WS + MJPEG (R6).
  Added the "no backend — runs locally" help banner on never-connected (R3).
- `components/console/ConnectionsTab.tsx` — "Backend URL" field (Save & reconnect /
  Reset), threads `onApiBaseChange` up to remount; error rendering now includes
  `cause` (R14).
- `lib/content.ts` + `components/site/{cta,footer,live-distance}.tsx` — landing
  honesty (R7): mock relabelled "Example readout" (no live pulse); console CTAs →
  repo/run-locally; footer links typed with real anchors, "Admin"/"Live demo"
  dropped, no more `href="#"`.

**Config/docs:** `apps/web/vercel.json` (framework + pnpm commands, R10),
`package.json` `packageManager: pnpm@10.32.0` (R9), `.env.example` build-vs-runtime
note (DX R3), `apps/web/README.md` *Deploy to Vercel* section (Root Directory
`apps/web`, Node 22 in settings, leave `NEXT_PUBLIC_API_BASE` unset), root README
deploy note. Deferred items logged in `TODOS.md`.

**Verification:** `pnpm lint` clean; `pnpm build` clean — TypeScript clean, both
`/` and `/console` **prerender as static** (confirms the SSR `localStorage` guard,
R5) and the build runs with **no env set** (criterion #5). `next/image` is unused
(plain `<img>`), so the `sharp` image-optimization risk (R9) is moot. No Python
touched → `make check` Python gate unchanged from its green baseline. Runtime
Backend-URL remount (R6) is type-checked + logic-verified; live drive against a LAN
backend is a manual step at deploy time (criterion #4).
