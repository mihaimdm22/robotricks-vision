# CatRanger — Documentation

> **TL;DR** — CatRanger takes a single camera feed, **detects a cat**, **keeps its
> identity** across frames, **estimates how far away it is in metres**, and (optionally)
> **drives a robot to follow it**. It ships as a Python perception core, a FastAPI +
> Next.js control console, an unattended train/eval pipeline with a durable job queue,
> and a wireless hardware rig (Tapo camera + Arduino robot). Everything is scored against
> four frozen metrics: **distance MAE, track continuity, FPS, and command smoothness**.

This folder is the canonical documentation set. It is organized so you can enter at the
level you need — a five-minute overview, a subsystem deep-dive with diagrams, an exact
API/config/CLI reference, or a step-by-step hands-on manual.

---

## Start here

| If you want to… | Read |
|---|---|
| Understand the whole system in 5 minutes | [architecture/overview.md](architecture/overview.md) |
| Install, wire the hardware, and test everything end-to-end | [guides/install-and-test.md](guides/install-and-test.md) |
| Understand the scored perception math | [architecture/perception-core.md](architecture/perception-core.md) |
| Understand the web console + control plane | [architecture/web-control-plane.md](architecture/web-control-plane.md) |
| Understand training, evaluation, and failure recovery | [architecture/training-and-reliability.md](architecture/training-and-reliability.md) |
| Wire a Tapo camera or an Arduino robot | [architecture/hardware.md](architecture/hardware.md) |
| Call the HTTP/WebSocket API | [reference/api.md](reference/api.md) |
| Look up a config key | [reference/configuration.md](reference/configuration.md) |
| Look up a command (`make`, `catranger`, scripts) | [reference/cli.md](reference/cli.md) |

---

## Documentation map

```
docs/
├── README.md                          ← you are here (index + project TL;DR)
├── architecture/
│   ├── overview.md                    System architecture, data flow, deployment, diagrams
│   ├── perception-core.md             The scored pipeline: detect→track→depth→distance fusion
│   ├── web-control-plane.md           FastAPI runtime, Next.js console, control arbiter, jobs
│   ├── training-and-reliability.md    Train/eval/keep-reject + durable job queue + crash recovery
│   └── hardware.md                    Go2 / Tapo C211 / Arduino wiring, calibration, firmware
├── reference/
│   ├── api.md                         Every REST route + the WebSocket + MJPEG protocols
│   ├── configuration.md               Every YAML config file and key
│   └── cli.md                         Every make target, `catranger` subcommand, and script
├── guides/
│   └── install-and-test.md           THE manual: install → link camera/robot → test → demo
├── 00-AUDIT.md                        Original repo audit (historical)
├── 01-RESEARCH-ARCHITECTURE.md        Original architecture research (historical)
├── 02-CATRANGER-10X-PLAN.md           The 10x improvement plan + review/audit trail
└── research/                          Deep research notes (cat-tracker, how-far, karpathy, hardware)
```

Project-root docs that complement this set:

- [`../README.md`](../README.md) — quickstart and the rubric→code deliverables map.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — dev environment, quality gates, "Extending" recipes.
- [`../CHANGELOG.md`](../CHANGELOG.md) — release history (Keep-a-Changelog).
- [`../TODOS.md`](../TODOS.md) — what is genuinely left and what it needs.
- [`../apps/web/README.md`](../apps/web/README.md) — the Next.js console app.

---

## The one rule (read before changing anything)

From [`../CLAUDE.md`](../CLAUDE.md): if a change does not improve a **frozen metric**
(distance MAE, track continuity, FPS, command smoothness), it is demo garnish for the
scored perception core (`catranger/{intrinsics,distance,detect,depth,track,pipeline}.py`).
Tooling, tests, CI, types, and docs are **exempt** — they are expected, not garnish.
Quality gates (`ruff`, `mypy`, `pytest` via `make check`) are non-negotiable.

## Conventions used in these docs

- **TL;DR** boxes open every document and most major sections.
- **Diagrams** are [Mermaid](https://mermaid.js.org/) and render natively on GitHub.
- Code references are clickable `path:line` links into the repo.
- Two assumptions are stated wherever distance is discussed, because the brief is
  ambiguous: **camera→object** vs **object→object**. CatRanger reports camera→object and
  says so. Distance is only trustworthy on a **calibrated** camera (`go2_1080p` is
  trusted; `tapo_c211` ships placeholders — see [hardware.md](architecture/hardware.md)).
