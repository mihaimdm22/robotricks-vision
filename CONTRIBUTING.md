# Contributing to CatRanger

CatRanger is a small, fully type-hinted CV package. The perception/geometry **core** is
held to a high bar (lint + types + tests); the CLI glue in `scripts/` and the heavy
GPU/model backends are treated pragmatically (see [What we test](#what-we-test-and-what-we-dont)).

## Dev setup (uv)

We use [uv](https://docs.astral.sh/uv/) for everything — one tool, one lockfile.

```bash
uv sync                     # core + dev toolchain into .venv (no torch)
uv run pre-commit install   # enable the git hooks
```

Heavy extras (only if you touch detection / depth / training):

```bash
uv sync --extra ml          # torch + ultralytics + transformers (CPU wheels by default)
```

## The checks (all run in CI)

```bash
uv run ruff format catranger scripts tests     # auto-format
uv run ruff check  catranger scripts tests --fix  # lint (+ safe autofixes)
uv run mypy                                    # type-check the package
uv run pytest                                  # tests + coverage (gate: 85% on the core)
```

`make check` runs the lot the way CI does; `uv run pre-commit run --all-files` runs ruff,
mypy, and the hygiene hooks in one pass.

## What we test, and what we don't

Tests live in `tests/` and target the **deterministic pure core**: camera geometry
(`intrinsics`), distance fusion (`distance`), config loading (`config`), the graded
metric functions (`eval/metrics`), the follow state machine (`control`), the data
contracts (`types`), and frame-source routing (`io`).

The heavy GPU/model paths (`detect`, `depth`, `track`, `pipeline`, `viz`) are **not**
unit-tested with real models — that needs weights + a GPU, and mocking all of torch tests
the mock, not the code. CI guards them with an **import-smoke** job instead: it installs
the CPU torch stack and imports every heavy module, so a syntax or bad-import error there
can't ship green. If you add perception logic that *can* be checked without a model, test it.

## Conventions

- **Numbers live in YAML** (`configs/`), never hard-coded in logic.
- The pretrained baseline must always run — see [`CLAUDE.md`](CLAUDE.md).
- Ruff + mypy config live in `pyproject.toml`. The package targets **Python 3.11** and is
  fully type-hinted; keep `catranger/` clean (lint + mypy must pass). `scripts/` is leniency-
  ok (E501 is ignored there for long `--help`/example strings).
- Don't commit model weights or clips: `*.pt` / `*.mp4` are gitignored, and a pre-commit
  hook blocks files larger than 512 KB.
- Dependencies are the lockfile's job. After editing `pyproject.toml` deps, run `uv lock`
  and commit `uv.lock`. There is no `requirements.txt` — generate one with
  `uv export --no-hashes > requirements.txt` if a pip-only host needs it.
