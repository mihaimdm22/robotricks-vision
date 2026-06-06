"""Assemble eval metrics into the graded `report.md` performance report.

This file is dependency-light (stdlib + the metric helpers, which are numpy-only)
so the report can be regenerated on a CPU-only box with no torch/ultralytics.

Typical use from the eval script:

    from catranger.eval import run_eval, build_report
    metrics = run_eval(results, commands, frame_times, gts=preds_and_gts)
    build_report(metrics, "report.md", thumbnails=["docs/fps.png", "docs/jerk.png"])
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from catranger.types import Command, FrameResult
from catranger.eval.metrics import (
    distance_mae,
    fps_stats,
    smoothness,
    track_stats,
)

# Pretty labels + how to render each metric key. Anything not listed falls back
# to a plain str() with 4-dp rounding for floats.
_LABELS = {
    "mean_fps": "Mean FPS",
    "p50_ms": "Frame time p50 (ms)",
    "p95_ms": "Frame time p95 (ms)",
    "num_id_switches": "ID switches (target)",
    "mean_track_lifetime_frames": "Mean track lifetime (frames)",
    "longest_streak": "Longest single-ID streak (frames)",
    "unique_ids": "Unique track IDs",
    "mae": "Distance MAE (m)",
    "mape": "Distance MAPE (%)",
    "rotation_jerk": "Rotation jerk (mean |Δ|)",
    "vfwd_jerk": "Forward-speed jerk (mean |Δ|)",
    "dx_jerk": "Strafe jerk (mean |Δ|)",
    "dy_jerk": "Pan jerk (mean |Δ|)",
    "rotation_oscillations": "Rotation oscillations (sign flips)",
    "n": "Samples",
    "reacquired": "Re-acquired same ID",
    "pre_id": "Pre-occlusion ID",
    "post_id": "Post-occlusion ID",
    "gap_frames": "Occlusion gap (frames)",
    "reacquire_latency_frames": "Re-acquire latency (frames)",
}

_SECTION_TITLES = {
    "fps": "Throughput (FPS)",
    "tracking": "Track continuity",
    "distance": "Distance accuracy (How Far)",
    "smoothness": "Command smoothness",
    "reacquire": "Synthetic-occlusion re-acquire",
}

# Keys rendered as a percentage (value stored as a [0,1] fraction).
_PERCENT_KEYS = {"mape"}


def run_eval(
    results: List[FrameResult],
    commands: List[Command],
    frame_times: List[float],
    gts: Optional[Dict[str, List[float]]] = None,
) -> Dict[str, dict]:
    """Assemble every metric dict from raw per-frame outputs.

    Args:
      results:     per-frame FrameResult list (for FPS field / tracking).
      commands:    per-frame Command list (for smoothness).
      frame_times: per-frame wall times in seconds (for FPS).
      gts:         optional {"preds": [...], "gts": [...]} of predicted vs true
                   distances (meters) to populate the distance-accuracy section.

    Returns a nested dict keyed by section name; pass straight to build_report().
    """
    metrics: Dict[str, dict] = {
        "fps": fps_stats(frame_times),
        "tracking": track_stats(results),
        "smoothness": smoothness(commands),
    }
    if gts and gts.get("preds") is not None and gts.get("gts") is not None:
        metrics["distance"] = distance_mae(list(gts["preds"]), list(gts["gts"]))
    return metrics


def _fmt_value(key: str, value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "n/a"
        if key in _PERCENT_KEYS:
            return f"{value * 100.0:.2f}"
        return f"{value:.4g}"
    return str(value)


def _metric_table(section: Dict[str, object]) -> List[str]:
    """Render one metric dict as a 2-column markdown table."""
    lines = ["| Metric | Value |", "| --- | --- |"]
    for key, value in section.items():
        label = _LABELS.get(key, key)
        lines.append(f"| {label} | {_fmt_value(key, value)} |")
    return lines


def _verdict(metrics: Dict[str, dict]) -> List[str]:
    """A short headline so the report leads with the graded numbers."""
    bullets: List[str] = []
    fps = metrics.get("fps", {})
    if fps.get("n"):
        mean_fps = float(fps.get("mean_fps", 0.0))
        ok = "PASS" if mean_fps >= 15.0 else "BELOW TARGET"
        bullets.append(
            f"- **Throughput:** {mean_fps:.1f} FPS mean "
            f"(p95 {float(fps.get('p95_ms', 0.0)):.1f} ms/frame) — "
            f"≥15 FPS requirement: **{ok}**."
        )
    sm = metrics.get("smoothness", {})
    if sm.get("n"):
        bullets.append(
            f"- **Smoothness:** rotation jerk "
            f"{float(sm.get('rotation_jerk', 0.0)):.4g}, "
            f"{int(sm.get('rotation_oscillations', 0))} rotation oscillations "
            f"over {int(sm.get('n', 0))} commands."
        )
    tr = metrics.get("tracking", {})
    if tr:
        bullets.append(
            f"- **Tracking:** {int(tr.get('unique_ids', 0))} unique IDs, "
            f"longest single-ID streak {int(tr.get('longest_streak', 0))} frames, "
            f"{int(tr.get('num_id_switches', 0))} target ID switches."
        )
    dist = metrics.get("distance")
    if dist and dist.get("n"):
        mae = dist.get("mae")
        mape = dist.get("mape")
        mae_s = "n/a" if (mae is None or (isinstance(mae, float) and math.isnan(mae))) else f"{mae:.3g} m"
        mape_s = "n/a" if (mape is None or (isinstance(mape, float) and math.isnan(mape))) else f"{mape * 100.0:.1f}%"
        bullets.append(
            f"- **Distance:** MAE {mae_s}, MAPE {mape_s} over "
            f"{int(dist.get('n', 0))} labeled samples."
        )
    return bullets


def build_report(
    metrics: Dict[str, dict],
    out_path: str,
    title: str = "CatRanger performance report",
    thumbnails: Optional[List[str]] = None,
) -> str:
    """Write a clean markdown performance report and return its path.

    `metrics` is the nested dict from run_eval (section -> metric dict). Unknown
    extra sections are rendered too (using their key as the header), so callers
    can attach e.g. a "reacquire" section without changing this function.
    """
    lines: List[str] = [f"# {title}", ""]

    verdict = _verdict(metrics)
    if verdict:
        lines.append("## Summary")
        lines.append("")
        lines.extend(verdict)
        lines.append("")

    # Stable, readable ordering: known sections first, then any extras.
    known_order = ["fps", "tracking", "distance", "smoothness", "reacquire"]
    seen = set()
    ordered_keys = [k for k in known_order if k in metrics]
    ordered_keys += [k for k in metrics if k not in known_order]

    for key in ordered_keys:
        if key in seen:
            continue
        seen.add(key)
        section = metrics.get(key)
        if not isinstance(section, dict) or not section:
            continue
        header = _SECTION_TITLES.get(key, key.replace("_", " ").title())
        lines.append(f"## {header}")
        lines.append("")
        lines.extend(_metric_table(section))
        lines.append("")

    if thumbnails:
        lines.append("## Plots")
        lines.append("")
        for path in thumbnails:
            name = path.rsplit("/", 1)[-1]
            lines.append(f"![{name}]({path})")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `catranger.eval.report.build_report`. Metrics defined in "
        "`docs/research/cat-tracker.md` §8._"
    )
    lines.append("")

    text = "\n".join(lines)
    with open(out_path, "w") as f:
        f.write(text)
    return out_path
