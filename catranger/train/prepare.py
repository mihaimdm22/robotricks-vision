"""Acquire + format a cat detection dataset to data/cat/ in Ultralytics layout.

One command:

    python -m catranger.train.prepare --config configs/train.yaml

Picks the source from `dataset.source` in the config: {roboflow, openimages, manual}.
  - roboflow:    roboflow pip pkg + api key from env (dataset.roboflow.*). Fastest path.
  - openimages:  fiftyone pulls class "Cat" boxes, exports YOLOv5 format.
  - manual:      scaffolds the dir layout + prints labeling instructions. No deps.

End state (all sources): data/cat/ contains train/ val/ image+label dirs and a
data.yaml that `train.py` feeds straight into `YOLO.train(data=...)`. Single class: cat.

Karpathy rule: heavy deps (roboflow, fiftyone) are imported lazily; if a source's
package or API key is missing we fail with a one-line install/fix hint, never a
cryptic ImportError. Nothing here is required for the demo — the baseline runs without it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:  # avoid a runtime import cycle (datasets.py imports source_names below)
    from catranger.datasets import DatasetProfile

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Single source of truth for where the formatted dataset lands.
DATA_DIR = _REPO_ROOT / "data" / "cat"
DATA_YAML = DATA_DIR / "data.yaml"
# Ultralytics single-class map. Cat is the only class we fine-tune for.
CLASS_NAMES = {0: "cat"}


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def _load_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    if not p.exists():
        raise FileNotFoundError(f"train config not found: {p}")
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _write_data_yaml(root: Path, train_rel: str, val_rel: str) -> Path:
    """Write the Ultralytics dataset yaml `train.py` consumes. Absolute `path` so it
    resolves no matter what cwd ultralytics runs from."""
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "path": str(root.resolve()),
        "train": train_rel,
        "val": val_rel,
        "names": CLASS_NAMES,
        "nc": len(CLASS_NAMES),
    }
    with open(DATA_YAML, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False)
    return DATA_YAML


# --------------------------------------------------------------------------- #
# source: roboflow
# --------------------------------------------------------------------------- #
def _prepare_roboflow(cfg: dict[str, Any]) -> Path:
    rf_cfg = (cfg.get("dataset", {}) or {}).get("roboflow", {}) or {}
    workspace = rf_cfg.get("workspace", "")
    project = rf_cfg.get("project", "")
    version = int(rf_cfg.get("version", 1))
    api_key_env = rf_cfg.get("api_key_env", "ROBOFLOW_API_KEY")

    if not workspace or not project:
        raise SystemExit(
            "roboflow source needs dataset.roboflow.workspace and .project in the config.\n"
            "  Pick a cat-detection project on https://universe.roboflow.com and copy its\n"
            "  workspace/project slugs + version into configs/train.yaml."
        )
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise SystemExit(
            f"missing Roboflow API key: set ${api_key_env}.\n"
            f"  export {api_key_env}=<key from https://app.roboflow.com/settings/api>"
        )

    try:
        from roboflow import Roboflow  # lazy: only needed for this source
    except Exception as e:  # pragma: no cover - depends on env
        raise SystemExit(
            "roboflow package not installed. `pip install roboflow`\n"
            f"  (original import error: {e})"
        )

    print(f"[prepare] roboflow: {workspace}/{project} v{version} -> yolov11 format")
    rf = Roboflow(api_key=api_key)
    proj = rf.workspace(workspace).project(project)
    # yolov11 export == Ultralytics YOLO layout with a data.yaml.
    dataset = proj.version(version).download("yolov11", location=str(DATA_DIR))

    rf_yaml = Path(getattr(dataset, "location", str(DATA_DIR))) / "data.yaml"
    # Roboflow already writes a usable data.yaml; normalize it so train.py finds the
    # same keys (absolute path, single class) regardless of the project's own naming.
    _normalize_downloaded_yaml(
        Path(dataset.location) if hasattr(dataset, "location") else DATA_DIR, rf_yaml
    )
    return DATA_YAML


def _normalize_downloaded_yaml(root: Path, src_yaml: Path) -> None:
    """Re-emit data/cat/data.yaml with an absolute path + our single-class map,
    pointing at whatever train/val split the download produced."""
    train_rel, val_rel = "train/images", "valid/images"
    if src_yaml.exists():
        try:
            with open(src_yaml) as f:
                d = yaml.safe_load(f) or {}
            train_rel = _rel_or_default(d.get("train"), train_rel)
            val_rel = _rel_or_default(d.get("val") or d.get("valid"), val_rel)
        except Exception:
            pass
    _write_data_yaml(root if root.exists() else DATA_DIR, train_rel, val_rel)


def _rel_or_default(value: Any, default: str) -> str:
    if not value:
        return default
    s = str(value).replace("\\", "/")
    # strip leading ../ and absolute roots so the path is relative to data.yaml's `path`
    for token in ("../", "./"):
        while s.startswith(token):
            s = s[len(token) :]
    return s or default


# --------------------------------------------------------------------------- #
# source: openimages (via fiftyone)
# --------------------------------------------------------------------------- #
def _prepare_openimages(cfg: dict[str, Any]) -> Path:
    oi_cfg = (cfg.get("dataset", {}) or {}).get("openimages", {}) or {}
    classes = list(oi_cfg.get("classes", ["Cat"]))
    max_samples = int(oi_cfg.get("max_samples", 2000))

    try:
        import fiftyone as fo  # lazy
        import fiftyone.zoo as foz
    except Exception as e:  # pragma: no cover - depends on env
        raise SystemExit(
            f"fiftyone not installed. `pip install fiftyone`\n  (original import error: {e})"
        )

    if DATA_DIR.exists():
        # fiftyone's YOLOv5 exporter refuses to overwrite; start clean.
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[prepare] open-images-v7: classes={classes} max_samples={max_samples}")
    split_counts = {"train": max_samples, "validation": max(1, max_samples // 5)}
    export_dir = str(DATA_DIR)
    # fiftyone uses "validation"; Ultralytics wants "val". Export each split then map.
    split_map = {"train": "train", "validation": "val"}
    for fo_split, yolo_split in split_map.items():
        ds = foz.load_zoo_dataset(
            "open-images-v7",
            split=fo_split,
            label_types=["detections"],
            classes=classes,
            max_samples=split_counts[fo_split],
            only_matching=True,
            dataset_name=f"catranger-oi-{fo_split}",
        )
        ds.export(
            export_dir=export_dir,
            dataset_type=fo.types.YOLOv5Dataset,
            label_field="ground_truth",
            split=yolo_split,
            classes=["cat"],
        )
        try:
            ds.delete()
        except Exception:
            pass

    # YOLOv5Dataset writes a dataset.yaml; standardize to data/cat/data.yaml.
    _write_data_yaml(DATA_DIR, "images/train", "images/val")
    return DATA_YAML


# --------------------------------------------------------------------------- #
# source: manual
# --------------------------------------------------------------------------- #
def _prepare_manual(cfg: dict[str, Any]) -> Path:
    """No download. Scaffold the Ultralytics dir layout + print what to drop where."""
    for split in ("train", "val"):
        (DATA_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)
    _write_data_yaml(DATA_DIR, "images/train", "images/val")

    print(
        f"\n[prepare] manual scaffold ready at {DATA_DIR}\n"
        "  Drop your data like this (Ultralytics format, single class 'cat' = id 0):\n"
        f"    {DATA_DIR}/images/train/*.jpg   + {DATA_DIR}/labels/train/*.txt\n"
        f"    {DATA_DIR}/images/val/*.jpg     + {DATA_DIR}/labels/val/*.txt\n"
        "  Each label .txt has one line per box:  0 cx cy w h   (all normalized 0..1)\n"
        "  Then run:  python -m catranger.train.train --config configs/train.yaml\n"
    )
    return DATA_YAML


# --------------------------------------------------------------------------- #
# entry
# --------------------------------------------------------------------------- #
_SOURCES = {
    "roboflow": _prepare_roboflow,
    "openimages": _prepare_openimages,
    "manual": _prepare_manual,
}


def source_names() -> frozenset[str]:
    """Registered dataset-source names — the source of truth configs/datasets.yaml is
    validated against (catranger.datasets), so adding a source here is a one-file change."""
    return frozenset(_SOURCES)


def prepare_from_profile(profile: DatasetProfile) -> Path:
    """Acquire/format the dataset described by a DatasetProfile (configs/datasets.yaml),
    reusing the exact same source adapters as the config-driven path."""
    src = profile.source
    if src not in _SOURCES:  # defensive; the registry already validates against source_names()
        raise SystemExit(f"unknown dataset source {src!r}; choose one of {sorted(_SOURCES)}")
    cfg = {"dataset": {"source": src, src: dict(profile.params)}}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_yaml = _SOURCES[src](cfg)
    print(f"[prepare] dataset {profile.id!r} ({src}) -> {data_yaml}")
    return data_yaml


def prepare(config_path: str = "configs/train.yaml", source: str | None = None) -> Path:
    """Acquire/format the dataset and return the path to data/cat/data.yaml."""
    cfg = _load_config(config_path)
    src = (source or (cfg.get("dataset", {}) or {}).get("source", "manual")).lower()
    if src not in _SOURCES:
        raise SystemExit(f"unknown dataset.source '{src}'; choose one of {sorted(_SOURCES)}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_yaml = _SOURCES[src](cfg)
    print(f"[prepare] done. dataset yaml -> {data_yaml}")
    print(f"[prepare] next: python -m catranger.train.train --config {config_path}")
    return data_yaml


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prepare a cat dataset for YOLO fine-tuning.")
    ap.add_argument("--config", default="configs/train.yaml", help="path to train.yaml")
    ap.add_argument(
        "--source",
        default=None,
        choices=sorted(_SOURCES),
        help="override dataset.source from the config",
    )
    ap.add_argument(
        "--dataset",
        default=None,
        help="dataset id from configs/datasets.yaml (WS-C2; overrides --config/--source)",
    )
    ap.add_argument(
        "--datasets-config",
        default="configs/datasets.yaml",
        help="dataset registry path (used with --dataset)",
    )
    args = ap.parse_args(argv)
    if args.dataset:
        from catranger.datasets import DatasetRegistry

        try:
            profile = DatasetRegistry.from_yaml(args.datasets_config).get(args.dataset)
        except KeyError as exc:
            print(f"[prepare] {exc}")
            return 1
        prepare_from_profile(profile)
        return 0
    prepare(args.config, args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
