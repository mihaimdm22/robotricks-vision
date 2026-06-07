# CatRanger — one target per stage. Karpathy rule: one command, reproducible.
# Package management is uv (https://docs.astral.sh/uv/): `uv sync`, `uv run`, `uv lock`.
SOURCE   ?= data/raw/how_far
APPROACH ?= A
CONFIG   ?= cat_distance

.PHONY: help install install-ml lock data doctor demo demo-video eval \
        prepare train autoresearch keepreject overnight promote promote-revert history jobs \
        lint format typecheck test check clean web web-setup web-test fetch-weights

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

install:             ## sync core + dev toolchain into .venv (uv creates the venv)
	uv sync

install-ml:          ## also install perception+depth deps (torch/ultralytics/transformers) — big
	uv sync --extra ml

install-web:         ## install the web control panel deps (fastapi/uvicorn) + ml for detection
	uv sync --extra ml --extra web

lock:                ## refresh uv.lock after changing dependencies
	uv lock

data:                ## symlink the provided contest inference sets into data/raw/
	uv run python scripts/setup_data.py

doctor:              ## check which backends are installed + GPU
	uv run python -m catranger.cli doctor

serve:               ## launch the web control panel (http://localhost:8080)
	uv run python -m catranger.cli serve

demo:                ## run the demo on $(SOURCE) (default: provided how_far stills)
	uv run python scripts/demo.py --source $(SOURCE) --approach $(APPROACH) --save outputs/demo

demo-video:          ## run the demo on a cat video (set SOURCE=...)
	uv run python scripts/demo.py --source $(SOURCE) --approach $(APPROACH) --show

eval:                ## run the eval harness + report (set GTS=path for distance MAE; see configs/eval/)
	uv run python -m catranger.eval.report --source $(SOURCE) --config $(CONFIG) $(if $(GTS),--gts $(GTS),)

prepare:             ## format a cat dataset (set DATASET=<id> to use configs/datasets.yaml)
	uv run python -m catranger.train.prepare --config configs/train.yaml $(if $(DATASET),--dataset $(DATASET),)

train:               ## fine-tune YOLO (baseline-first; never blocks the demo)
	uv run python -m catranger.train.train --config configs/train.yaml

autoresearch:        ## frozen-metric keep/reject hyperparameter loop
	uv run python -m catranger.train.autoresearch --config configs/train.yaml

keepreject:          ## keep/reject a change on the frozen metrics (BASELINE=base.json CANDIDATE=cand.json)
	uv run python -m catranger.eval.keepreject --baseline $(BASELINE) --candidate $(CANDIDATE)

overnight:           ## run the unattended overnight plan (configs/overnight.yaml), archive history
	uv run python scripts/overnight.py --config configs/overnight.yaml

promote:             ## morning: wire the fine-tune winner into the pipeline (gated; baseline-safe)
	uv run python scripts/promote.py

promote-revert:      ## roll the pipeline back to the pretrained baseline
	uv run python scripts/promote.py --revert

history:             ## print the run-history archive index (runs/history/INDEX.md)
	uv run python -m catranger.history

jobs:                ## print the durable job queue (live state; sibling of GET /api/jobs)
	uv run python -m catranger.jobqueue

lint:                ## ruff lint (with safe autofixes)
	uv run ruff check catranger scripts tests --fix

format:              ## ruff format
	uv run ruff format catranger scripts tests

typecheck:           ## mypy (the package)
	uv run mypy

test:                ## pytest + coverage
	uv run pytest

check:               ## everything CI runs: format-check, lint, types, tests
	uv run ruff format --check catranger scripts tests
	uv run ruff check catranger scripts tests
	uv run mypy
	uv run pytest

web-setup:           ## install web console deps (Python web extra + pnpm)
	uv sync --extra ml --extra web
	pnpm install --dir apps/web

web:                 ## run FastAPI + the Next.js console together (cross-platform)
	uv run python scripts/web.py

web-test:            ## run the console's TypeScript unit tests (vitest)
	pnpm --dir apps/web test

fetch-weights:       ## pre-download detector weights so the demo runs offline
	uv run python scripts/fetch_weights.py

clean:               ## remove generated outputs + tool caches
	rm -rf outputs runs __pycache__ catranger/__pycache__ .pytest_cache .ruff_cache .mypy_cache
