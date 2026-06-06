# CatRanger — one target per stage. Karpathy rule: one command, reproducible.
# Package management is uv (https://docs.astral.sh/uv/): `uv sync`, `uv run`, `uv lock`.
SOURCE   ?= data/raw/how_far
APPROACH ?= A
CONFIG   ?= cat_distance

.PHONY: help install install-ml lock data doctor demo demo-video eval \
        prepare train autoresearch lint format typecheck test check clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

install:             ## sync core + dev toolchain into .venv (uv creates the venv)
	uv sync

install-ml:          ## also install perception+depth deps (torch/ultralytics/transformers) — big
	uv sync --extra ml

lock:                ## refresh uv.lock after changing dependencies
	uv lock

data:                ## symlink the provided contest inference sets into data/raw/
	uv run python scripts/setup_data.py

doctor:              ## check which backends are installed + GPU
	uv run python -m catranger.cli doctor

demo:                ## run the demo on $(SOURCE) (default: provided how_far stills)
	uv run python scripts/demo.py --source $(SOURCE) --approach $(APPROACH) --save outputs/demo

demo-video:          ## run the demo on a cat video (set SOURCE=...)
	uv run python scripts/demo.py --source $(SOURCE) --approach $(APPROACH) --show

eval:                ## run the eval harness + write the performance report
	uv run python -m catranger.eval.report --source $(SOURCE) --config $(CONFIG)

prepare:             ## download + format a cat dataset for fine-tuning
	uv run python -m catranger.train.prepare --config configs/train.yaml

train:               ## fine-tune YOLO (baseline-first; never blocks the demo)
	uv run python -m catranger.train.train --config configs/train.yaml

autoresearch:        ## frozen-metric keep/reject hyperparameter loop
	uv run python -m catranger.train.autoresearch --config configs/train.yaml

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

clean:               ## remove generated outputs + tool caches
	rm -rf outputs runs __pycache__ catranger/__pycache__ .pytest_cache .ruff_cache .mypy_cache
