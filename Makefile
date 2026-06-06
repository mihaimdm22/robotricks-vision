# CatRanger — one target per stage. Karpathy rule: one command, reproducible.
PY      ?= .venv/bin/python
SOURCE  ?= data/raw/how_far
APPROACH?= A
CONFIG  ?= cat_distance

.PHONY: help venv install install-ml data doctor demo demo-video eval prepare train autoresearch clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

venv:                ## create the virtualenv
	python3 -m venv .venv && $(PY) -m pip install -U pip

install:             ## install core deps (numpy/opencv/pyyaml)
	$(PY) -m pip install -e .

install-ml:          ## install perception+depth deps (torch/ultralytics/transformers) — big
	$(PY) -m pip install -e ".[ml]"

data:                ## symlink the provided contest inference sets into data/raw/
	$(PY) scripts/setup_data.py

doctor:              ## check which backends are installed + GPU
	PYTHONPATH=. $(PY) -m catranger.cli doctor

demo:                ## run the demo on $(SOURCE) (default: provided how_far stills)
	PYTHONPATH=. $(PY) scripts/demo.py --source $(SOURCE) --approach $(APPROACH) --save outputs/demo

demo-video:          ## run the demo on a cat video (set SOURCE=...)
	PYTHONPATH=. $(PY) scripts/demo.py --source $(SOURCE) --approach $(APPROACH) --show

eval:                ## run the eval harness + write the performance report
	PYTHONPATH=. $(PY) -m catranger.eval.report --source $(SOURCE) --config $(CONFIG)

prepare:             ## download + format a cat dataset for fine-tuning
	PYTHONPATH=. $(PY) -m catranger.train.prepare --config configs/train.yaml

train:               ## fine-tune YOLO (baseline-first; never blocks the demo)
	PYTHONPATH=. $(PY) -m catranger.train.train --config configs/train.yaml

autoresearch:        ## frozen-metric keep/reject hyperparameter loop
	PYTHONPATH=. $(PY) -m catranger.train.autoresearch --config configs/train.yaml

clean:               ## remove generated outputs
	rm -rf outputs runs __pycache__ catranger/__pycache__
