"""Promote a fine-tune into the live pipeline — the single source of truth.

`scripts/promote.py` (the CLI) and the web Training tab both call into here, so
"promote a winner" means exactly one thing and the two surfaces can never diverge
(DRY). The config write is atomic (temp + os.replace) and comment-preserving so a
crash mid-write can never corrupt `cat_distance.yaml` (the perception core's
config — the baseline demo depends on it).

Two consumers, two writes — both done by `promote_weights()`:
  * `cat_distance.yaml:detector.finetuned_weights`  -> the CLI / demo pipeline
  * a profile in `configs/models.yaml`              -> the web Models tab dropdown

Stdlib only (no torch); safe to import without the ml extra.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_CONFIG = _REPO_ROOT / "configs" / "cat_distance.yaml"
MODELS_CONFIG = _REPO_ROOT / "configs" / "models.yaml"
BEST_TRIAL = _REPO_ROOT / "runs" / "train" / "best_trial.json"
_FT_LINE = re.compile(r"^(\s*finetuned_weights:\s*).*$", re.MULTILINE)


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash never leaves a half-written
    (corrupt) config behind. os.replace is atomic on POSIX and Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def set_finetuned_weights(value: str, *, config_path: Path | None = None) -> bool:
    """Rewrite the `finetuned_weights:` line in cat_distance.yaml (comment-
    preserving, atomic). `value` is a weights path, or "null" to revert to the
    pretrained baseline. Returns True if the file changed."""
    path = config_path or TASK_CONFIG
    text = path.read_text(encoding="utf-8")
    if not _FT_LINE.search(text):
        raise ValueError(f"no 'finetuned_weights:' line in {path}")
    comment = (
        "  # set by promote (overrides approach_a)"
        if value != "null"
        else "  # set by training to override approach_a (e.g. runs/train/best.pt)"
    )
    new = _FT_LINE.sub(rf"\g<1>{value}{comment}", text, count=1)
    if new == text:
        return False
    _atomic_write(path, new)
    return True


def upsert_model_profile(profile: dict[str, Any], *, config_path: Path | None = None) -> None:
    """Add or replace (by id) a profile in configs/models.yaml (atomic). The web
    Models tab reads this registry, so a promoted fine-tune becomes selectable."""
    path = config_path or MODELS_CONFIG
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = data or {}
    models = list(data.get("models") or [])
    models = [m for m in models if m.get("id") != profile["id"]]
    models.append(profile)
    data["models"] = models
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False))


def read_winner(path: Path | None = None) -> dict[str, Any] | None:
    """The autoresearch winner dict (runs/train/best_trial.json) or None."""
    p = path or BEST_TRIAL
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def promote_weights(
    weights: str,
    *,
    model_id: str = "cats-finetuned",
    name: str = "Fine-tuned cats",
    classes: list[int] | None = None,
    dataset: str = "fine-tuned",
    run_kind: str = "train",
    trained_at: str = "",
    metric: float | None = None,
    metric_key: str | None = None,
    duration_s: float | None = None,
    summary: str = "",
    notes: str = "promoted fine-tune",
) -> dict[str, Any]:
    """Wire `weights` into BOTH consumers: the CLI pipeline (cat_distance.yaml) and
    the web Models registry (models.yaml). Returns a summary dict. Caller validates
    the weights file exists first."""
    changed_cli = set_finetuned_weights(weights)
    profile: dict[str, Any] = {
        "id": model_id,
        "name": name,
        "backend": "yolo",
        "weights": weights,
        "classes": classes if classes is not None else [0],
        "dataset": dataset,
        "source": "fine-tuned",
        "run_kind": run_kind,
        "status": "ok",
        "notes": notes,
    }
    if trained_at:
        profile["trained_at"] = trained_at
    if metric is not None:
        profile["metric"] = metric
    if metric_key:
        profile["metric_key"] = metric_key
    if duration_s is not None:
        profile["duration_s"] = duration_s
    if summary:
        profile["summary"] = summary
    upsert_model_profile(profile)
    return {"weights": weights, "model_id": model_id, "cli_changed": changed_cli}
