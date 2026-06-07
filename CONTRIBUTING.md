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

## Extending CatRanger ("add models and datasets on top")

The two registries and the backend dict are the single source of truth — adding a model
or dataset is a YAML edit, and the validation/CLI/web all pick it up automatically.

### Add a model (fine-tuned or a new pretrained variant)

Add an entry to [`configs/models.yaml`](configs/models.yaml). It appears in the web
**Models** tab *and* the CLI (one model home — `--model`), with no code change:

```yaml
models:
  - id: cats-finetuned
    name: "YOLO11s — low-angle cats (fine-tuned)"
    backend: yolo                       # must be a registered backend (see below)
    weights: runs/train/best.pt         # bare handle (auto-download) or a path to best.pt
    classes: [0]                        # a single-class fine-tune usually remaps cat -> 0
    tracker: botsort.yaml
    dataset: "Roboflow low-angle cats"
```

```bash
make eval SOURCE=data/raw/how_far --model cats-finetuned     # CLI
python scripts/demo.py --source <clip> --model cats-finetuned
# or pick it in the web console's Models tab
```

⚠️ A single-class fine-tune emits class id **0**; copying `classes: [15]` (COCO cat) from
the baseline makes the detector drop every box. The registry **warns** on that mismatch.

### Add a dataset

Add an entry to [`configs/datasets.yaml`](configs/datasets.yaml) naming a source
(`manual` | `openimages` | `roboflow`) and its params, then prepare it:

```yaml
datasets:
  - id: roboflow-low-angle-cats
    name: "Roboflow — low-angle cats"
    source: roboflow
    params: { workspace: your-ws, project: your-proj, version: 1 }
```

```bash
make prepare DATASET=roboflow-low-angle-cats     # -> data/cat/ (Ultralytics layout, cat=0)
# (needs `uv sync --extra train` for roboflow/openimages; `manual` needs nothing)
```

### Add a detector backend

Backends live in **one place** — the `_BACKENDS` dict in
[`catranger/detect.py`](catranger/detect.py). The model registry reads its names, so
there is no second list to keep in sync:

```python
def _build_rfdetr(weights: str):
    from rfdetr import RFDETR        # import the heavy lib INSIDE the builder (lazy)
    return RFDETR(weights)

_BACKENDS = {"yolo": _build_yolo, "rtdetr": _build_rtdetr, "rfdetr": _build_rfdetr}
```

If the model isn't Ultralytics-shaped, also map its raw output to `list[Detection]` in
`Detector._to_detections`. Then `backend: rfdetr` is valid in `models.yaml` immediately.

### Validate a perception change (keep/reject on the frozen metric)

A change to the scored core (`distance`, `depth`, `detect`, …) is only kept if it holds or
improves the frozen metric — never eyeballed. The harness compares two eval runs:

```bash
make eval SOURCE=<set> GTS=<gt.json> --metrics-json base.json   # baseline
# ...apply your change...
make eval SOURCE=<set> GTS=<gt.json> --metrics-json cand.json   # candidate
make keepreject BASELINE=base.json CANDIDATE=cand.json          # exit 0=keep, 2=reject
```

`GTS` is a distance ground-truth sidecar (template:
[`configs/eval/how_far.gts.example.json`](configs/eval/how_far.gts.example.json)) — without
it, distance MAE can't be measured (FPS still gates).

### Run a sweep unattended (crash-safe)

`make overnight` runs the plan in [`configs/overnight.yaml`](configs/overnight.yaml) as a
durable SQLite queue: each job is crash-isolated, has a wall-clock cap, and **re-running
resumes** (completed jobs are skipped; a job left running by a crash is recovered;
transient failures retry with backoff). `--fresh` re-runs the whole plan from scratch;
`make history` reviews results.

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
