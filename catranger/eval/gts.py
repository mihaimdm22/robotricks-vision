"""Distance ground-truth sidecar for the eval harness (WS-D0.1, "prove the number").

The provided inference sets ship NO distance labels, so ``eval/report.py`` runs with
``gts=None`` and the distance MAE/MAPE section is skipped. To make distance MAE a
*measurable* number you commit a small sidecar of true distances (meters) keyed by
frame index, then run::

    make eval SOURCE=data/raw/how_far GTS=data/eval/how_far.gts.json

The frame index is the position the source yields (see :func:`catranger.io.frame_source`):
for an image directory it is the 0-based natural-sorted position of the file
(:func:`catranger.io.image_files` lists them in that exact order, so you can script the
index->file mapping). The HC-SR04 rig gives you free ground truth — tape-measure a few
frames and record them here. A ready-to-copy template lives at
``configs/eval/how_far.gts.example.json``.

Sidecar format (JSON); any of these shapes is accepted::

    {"0": 1.50, "1": 2.30, "2": 0.95}              # flat: index -> meters
    {"by_index": {"0": 1.50, "1": 2.30}}           # namespaced
    {"frames": {"0": 1.50}, "_README": "note"}     # keys starting with "_" are ignored

Stdlib only (json) so this stays in the light-import tier with the rest of eval/metrics.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


def load_gts(path: str | Path) -> dict[int, float]:
    """Load a GT sidecar into ``{frame_index: true_meters}``.

    Accepts a flat map or a ``{"by_index"|"frames": {...}}`` wrapper; keys starting
    with ``"_"`` (notes/comments) are ignored. Raises :class:`ValueError` (fail loud)
    on an unreadable or wrong-shaped file — this is a tooling path, never the
    baseline demo path, so a bad sidecar should stop the eval, not run silently.
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read gts sidecar {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"gts sidecar {p} must be a JSON object, got {type(data).__name__}")
    raw = data.get("by_index") or data.get("frames") or data
    if not isinstance(raw, dict):
        raise ValueError(f"gts sidecar {p}: 'by_index'/'frames' must map index -> meters")
    out: dict[int, float] = {}
    for k, v in raw.items():
        if str(k).startswith("_"):
            continue  # note/comment field
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            raise ValueError(
                f"gts sidecar {p}: bad entry {k!r}={v!r} (need frame-index -> meters)"
            ) from None
    if not out:
        raise ValueError(f"gts sidecar {p} has no usable index -> meters entries")
    return out


def align_preds_gts(
    preds_by_index: dict[int, float], gts: dict[int, float]
) -> dict[str, list[float]]:
    """Pair predicted distances (collected per frame) with the GT sidecar by index.

    Only indices present in BOTH (and finite) are kept, in sorted index order.
    Returns ``{"preds": [...], "gts": [...]}`` ready for
    :func:`catranger.eval.report.run_eval` / :func:`catranger.eval.metrics.distance_mae`.
    """
    preds: list[float] = []
    truth: list[float] = []
    for idx in sorted(gts):
        if idx not in preds_by_index:
            continue
        p = float(preds_by_index[idx])
        g = float(gts[idx])
        if math.isfinite(p) and math.isfinite(g):
            preds.append(p)
            truth.append(g)
    return {"preds": preds, "gts": truth}
