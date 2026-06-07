"""Fine-tune a pretrained YOLO on the cat dataset. One file, one frozen metric.

    python -m catranger.train.train --config configs/train.yaml

Karpathy discipline:
  - We FINE-TUNE yolo11s.pt (COCO-pretrained), never train from scratch.
  - ONE frozen metric: val mAP50-95 (config key `metric`, default metrics/mAP50-95(B)).
  - Deterministic seed (config `seed`) so a run is reproducible / comparable.
  - Surgical: the whole thing is `YOLO(base).train(**args)` + read one number.

After training it copies best.pt to a stable path and prints the exact line to paste
into configs/cat_distance.yaml so the pipeline picks up the fine-tuned weights. The
pretrained baseline is untouched — fine-tuning only ever ADDS an override.

ultralytics is imported lazily so `import catranger.train.train` stays light and the
baseline demo never depends on a training install.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRIC = "metrics/mAP50-95(B)"
# Stable, predictable place the rest of the project points at.
STABLE_WEIGHTS = _REPO_ROOT / "runs" / "train" / "best.pt"


def _load_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    if not p.exists():
        raise FileNotFoundError(f"train config not found: {p}")
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _resolve(path_like: str) -> str:
    """Resolve a config path (e.g. data/cat/data.yaml) against the repo root."""
    p = Path(path_like)
    return str(p if p.is_absolute() else (_REPO_ROOT / p).resolve())


def _read_metric(results: Any, metric_key: str) -> float:
    """Pull the one frozen number out of an ultralytics results object.

    Ultralytics exposes `results.results_dict` keyed like 'metrics/mAP50-95(B)'.
    We fall back across a couple of aliases so a key typo never silently returns 0.
    """
    rd: dict[str, Any] = {}
    if results is not None and hasattr(results, "results_dict"):
        rd = dict(results.results_dict or {})
    if metric_key in rd:
        return float(rd[metric_key])
    aliases = [
        metric_key,
        metric_key.replace("mAP50-95", "mAP50-95"),
        "metrics/mAP50-95(B)",
        "metrics/mAP50(B)",
    ]
    for k in aliases:
        if k in rd:
            return float(rd[k])
    # last resort: box.map (mAP50-95) if the maps API is present
    box = getattr(results, "box", None)
    if box is not None and hasattr(box, "map"):
        try:
            return float(box.map)
        except Exception:
            pass
    return float("nan")


def train_once(
    cfg: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    name: str | None = None,
    epochs: int | None = None,
) -> dict[str, Any]:
    """Run one fine-tune and return {metric, metric_key, best_pt, name, args}.

    This is the single training primitive both the CLI and autoresearch.py call.
    `overrides` are hyperparameter knobs merged on top of the base train args (the
    keep/reject loop sweeps these). `epochs`/`name` let the caller cap budget + isolate
    the run directory. ultralytics is imported here, lazily.
    """
    try:
        from ultralytics import YOLO  # lazy: only needed to actually train
    except Exception as e:  # pragma: no cover - depends on env
        raise SystemExit(
            f"ultralytics not installed. `pip install ultralytics`\n  (original import error: {e})"
        )

    overrides = dict(overrides or {})
    metric_key = str(cfg.get("metric", DEFAULT_METRIC))
    base_model = str(cfg.get("base_model", "yolo11s.pt"))
    raw_data = str(cfg.get("data", "data/cat/data.yaml"))
    data_yaml = _resolve(raw_data)
    if not Path(data_yaml).exists():
        # A bare name (no path separator) like "coco8.yaml" is a built-in ultralytics
        # dataset it resolves itself — pass it through. Only a real repo path that's
        # missing is an error (you forgot to run prepare).
        if "/" not in raw_data and "\\" not in raw_data:
            data_yaml = raw_data
        else:
            raise SystemExit(
                f"dataset yaml not found: {data_yaml}\n"
                "  run `python -m catranger.train.prepare --config configs/train.yaml` first."
            )

    train_args: dict[str, Any] = {
        "data": data_yaml,
        "epochs": int(epochs if epochs is not None else cfg.get("epochs", 40)),
        "imgsz": int(cfg.get("imgsz", 640)),
        "batch": int(cfg.get("batch", 16)),
        "seed": int(cfg.get("seed", 0)),  # deterministic, comparable runs
        "deterministic": True,
        "device": cfg.get("device", 0),
        "project": _resolve(str(cfg.get("project", "runs/train"))),
        "name": name or str(cfg.get("name", "cat_finetune")),
        "patience": int(cfg.get("patience", 12)),
        "exist_ok": True,
        "pretrained": True,  # FINE-TUNE, never from scratch
        "verbose": True,
    }
    # Hyperparameter overrides (lr0, mosaic, degrees, ...) win over the base args.
    train_args.update(overrides)

    print(
        f"[train] fine-tune {base_model} -> {train_args['name']} "
        f"(epochs={train_args['epochs']}, seed={train_args['seed']})"
    )
    if overrides:
        print(f"[train] overrides: {overrides}")

    model = YOLO(base_model)
    results = model.train(**train_args)
    metric = _read_metric(results, metric_key)

    run_dir = Path(train_args["project"]) / str(train_args["name"])
    best_pt = run_dir / "weights" / "best.pt"

    print(f"[train] FROZEN METRIC {metric_key} = {metric:.5f}")
    return {
        "metric": metric,
        "metric_key": metric_key,
        "best_pt": str(best_pt),
        "run_dir": str(run_dir),
        "name": train_args["name"],
        "overrides": overrides,
        "epochs": train_args["epochs"],
        "seed": train_args["seed"],
    }


def publish_weights(best_pt: str) -> Path | None:
    """Copy a run's best.pt to the stable path the project points at. Returns it,
    or None if the source is missing (e.g. a 0-epoch dry run)."""
    src = Path(best_pt)
    if not src.exists():
        print(f"[train] WARN: best weights not found at {src} (nothing to publish)")
        return None
    STABLE_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, STABLE_WEIGHTS)
    return STABLE_WEIGHTS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fine-tune a pretrained YOLO on cats.")
    ap.add_argument("--config", default="configs/train.yaml", help="path to train.yaml")
    ap.add_argument("--epochs", type=int, default=None, help="override config epochs")
    ap.add_argument("--name", default=None, help="override run name")
    ap.add_argument("--device", default=None, help="override device (cuda|mps|cpu|0)")
    args = ap.parse_args(argv)

    cfg = _load_config(args.config)
    if args.device:
        cfg["device"] = args.device  # let the web/CLI pick the box's real device
    out = train_once(cfg, name=args.name, epochs=args.epochs)

    # One number, printed alone, so a harness/grep can read it.
    print(f"{out['metric']:.5f}")

    published = publish_weights(out["best_pt"])
    if published is not None:
        print(f"[train] published best weights -> {published}")
        print(
            "[train] to use the fine-tuned model, set in configs/cat_distance.yaml:\n"
            f"          detector:\n"
            f"            finetuned_weights: {published}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
