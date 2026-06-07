# CatRanger web (Next.js)

The web front-end for **[CatRanger](../../README.md)** — a computer-vision system that
implements and adapts two Monsson hack-a-ton 2026 challenges,
[How Far?](https://hackaton.ambasada.pro/challenges/monsson-how-far/) (monocular metric
distance) and [Cat Tracker](https://hackaton.ambasada.pro/challenges/monsson-cat-tracker/)
(detect · track · follow).

This package is a marketing landing page (`/`) **and** the live robot control
console (`/console`). The console talks to the Python FastAPI control plane
(`catranger serve`) — Next.js owns all UI; Python owns the camera, YOLO, and the
serial/BLE robot link.

> Heads up: this is a customized Next.js 16 / React 19. Read the matching guide
> under `node_modules/next/dist/docs/` before changing framework code (see
> `AGENTS.md`). Node ≥ 20.9 (`.nvmrc` pins 22).

## Run it (two processes)

The console needs the API running. Easiest — one command from the **repo root**:

```bash
make web            # Unix
# or, anywhere (Windows/macOS/Linux):
uv run python scripts/web.py
```

That starts FastAPI on `:8080` and the Next.js dev server on `:3000`. Open
http://localhost:3000/console.

Prefer two terminals? 

```bash
# terminal A (repo root)
catranger serve                 # FastAPI control plane on :8080

# terminal B
pnpm install                    # first time only
pnpm dev                        # Next.js on :3000
```

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8080` | Base URL of `catranger serve`. The REST calls, the MJPEG `<img>`, and the control WebSocket all derive from it. |

Copy `.env.example` → `.env.local` to override. For **phone / LAN** access set
`NEXT_PUBLIC_API_BASE` to the host machine's LAN IP (e.g.
`http://192.168.1.42:8080`), bind the API on `0.0.0.0` (the default in
`configs/web.yaml`), and add that origin to `cors_origins` in `configs/web.yaml`.

There is **no Next.js proxy/rewrite** in the path: the browser talks straight to
FastAPI. This keeps the WebSocket (`/ws`) and MJPEG (`/video`) robust — a dev
proxy's WS upgrade is flaky.

## Deploy to Vercel (landing only)

The **marketing landing (`/`) deploys to Vercel** as the public, shareable site —
it needs no backend. The **console (`/console`) stays a local tool**: a public
HTTPS page can't reach a LAN `http://` robot backend (mixed content + CORS + no
public address), and the backend is no-auth/LAN-only by design. The landing's
CTAs link to this repo's run-locally docs, not the console.

Vercel project settings (the repo is a monorepo; `apps/web` is its own pnpm
workspace root):

| Setting | Value |
| --- | --- |
| **Root Directory** | `apps/web` (required — the lockfile/workspace live here, not at repo root) |
| Framework | Next.js (auto-detected) |
| Install / Build | `pnpm install` / `pnpm build` (pnpm auto-detected from the lockfile) |
| **Node.js Version** | **22** — set this in *Project Settings → Node.js Version*. Vercel does **not** read `.nvmrc` (that's local-only); `engines`/the dashboard govern. |
| Environment | none required for the landing. Do **not** set `NEXT_PUBLIC_API_BASE` (it bakes a backend URL into the bundle). |

`apps/web/vercel.json` pins the framework + commands so the config is reviewable
in-repo. Verify the first **preview** deploy (landing renders, no `sharp`/build
warnings) before promoting to production.

> **Console retargeting (local).** `NEXT_PUBLIC_API_BASE` is the build-time
> default; the in-app **Backend URL** field (Connections tab) overrides it at
> runtime (saved in the browser), so one build points at any LAN box — no rebuild.

## What the console does

- **Control** — IDLE / MANUAL / FOLLOW, press-and-hold drive (W/A/S/D or the
  pad), release-to-stop, camera pan. E-STOP + ARM/RESET live in the persistent
  header and are always reachable (even for observers).
- **Single-controller token** — one operator drives; others are read-only
  observers and can "Request control". E-stop is never gated by the token.
- **Models** — hot-swap the detector.
- **Connections** — connect a camera (synthetic / webcam / RTSP) or the robot
  (USB / BT / BLE), with device auto-discovery.
- **Eval** — run the eval pipeline over a recorded source and render the
  performance report (FPS / tracking / smoothness; distance MAE when labels are
  supplied). Refused unless the robot is IDLE (it's CPU/GPU-heavy).

## Build

```bash
pnpm build      # production build (also runs TypeScript)
pnpm lint       # ESLint
```
