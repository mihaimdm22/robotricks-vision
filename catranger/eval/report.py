"""Assemble eval metrics into the graded `report.md` performance report.

This file is dependency-light (stdlib + the metric helpers, which are numpy-only)
so the report can be regenerated on a CPU-only box with no torch/ultralytics.

Typical use from the eval script:

    from catranger.eval import run_eval, build_report
    metrics = run_eval(results, commands, frame_times, gts=preds_and_gts)
    build_report(metrics, "report.md", thumbnails=["docs/fps.png", "docs/jerk.png"])
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from catranger.eval.metrics import (
    distance_mae,
    fps_stats,
    smoothness,
    track_stats,
)
from catranger.types import Command, FrameResult

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
    results: list[FrameResult],
    commands: list[Command],
    frame_times: list[float],
    gts: dict[str, list[float]] | None = None,
) -> dict[str, dict]:
    """Assemble every metric dict from raw per-frame outputs.

    Args:
      results:     per-frame FrameResult list (for FPS field / tracking).
      commands:    per-frame Command list (for smoothness).
      frame_times: per-frame wall times in seconds (for FPS).
      gts:         optional {"preds": [...], "gts": [...]} of predicted vs true
                   distances (meters) to populate the distance-accuracy section.

    Returns a nested dict keyed by section name; pass straight to build_report().
    """
    metrics: dict[str, dict] = {
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


def _metric_table(section: dict[str, object]) -> list[str]:
    """Render one metric dict as a 2-column markdown table."""
    lines = ["| Metric | Value |", "| --- | --- |"]
    for key, value in section.items():
        label = _LABELS.get(key, key)
        lines.append(f"| {label} | {_fmt_value(key, value)} |")
    return lines


def _verdict(metrics: dict[str, dict]) -> list[str]:
    """A short headline so the report leads with the graded numbers."""
    bullets: list[str] = []
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
        mae_s = (
            "n/a"
            if (mae is None or (isinstance(mae, float) and math.isnan(mae)))
            else f"{mae:.3g} m"
        )
        mape_s = (
            "n/a"
            if (mape is None or (isinstance(mape, float) and math.isnan(mape)))
            else f"{mape * 100.0:.1f}%"
        )
        bullets.append(
            f"- **Distance:** MAE {mae_s}, MAPE {mape_s} over "
            f"{int(dist.get('n', 0))} labeled samples."
        )
    return bullets


def build_report(
    metrics: dict[str, dict],
    out_path: str,
    title: str = "CatRanger performance report",
    thumbnails: list[str] | None = None,
) -> str:
    """Write a clean markdown performance report and return its path.

    `metrics` is the nested dict from run_eval (section -> metric dict). Unknown
    extra sections are rendered too (using their key as the header), so callers
    can attach e.g. a "reacquire" section without changing this function.
    """
    lines: list[str] = [f"# {title}", ""]

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


def main(argv: list[str] | None = None) -> int:
    """CLI driver behind `make eval` (python -m catranger.eval.report).

    Runs the pipeline over a source, collects per-frame results/commands/times,
    then run_eval() -> build_report() -> outputs/report/report.md. The pipeline
    deps (torch/ultralytics) are imported lazily HERE so importing this module
    just to call build_report() stays dependency-light (see module docstring).
    """
    ap = argparse.ArgumentParser(
        prog="catranger.eval.report",
        description="Run CatRanger over a source and write the performance report",
    )
    ap.add_argument(
        "--source", required=True, help="image dir | image | video | rtsp url | webcam index"
    )
    ap.add_argument("--config", default="cat_distance", help="task config (configs/<name>.yaml)")
    ap.add_argument("--camera", default=None, help="override camera config (e.g. tapo_c211)")
    ap.add_argument("--approach", default="A", choices=["A", "B"], help="A=YOLO11, B=RT-DETR")
    ap.add_argument(
        "--classes",
        default=None,
        help="override classes: 'all', or comma-sep COCO ids (e.g. 15 cat). "
        "Use 'all' for the generic How-Far object stills.",
    )
    ap.add_argument(
        "--no-depth", action="store_true", help="geometry only (no depth net; faster on CPU)"
    )
    ap.add_argument(
        "--device",
        default=None,
        help="cuda | cpu | mps (governs the depth net + FP16/half selection)",
    )
    ap.add_argument("--stride", type=int, default=1, help="frame stride (video/stream)")
    ap.add_argument("--max-frames", type=int, default=0, help="cap frames (0=all)")
    ap.add_argument("--out", default="outputs/report/report.md", help="report output path")
    args = ap.parse_args(argv)

    # lazy: only running the eval needs the heavy perception stack.
    from catranger.config import load_app, load_camera
    from catranger.control import Follower
    from catranger.io import frame_source, is_stream
    from catranger.pipeline import CatRanger

    app = load_app(args.config)
    if args.camera:
        app.camera = load_camera(args.camera)
    if args.classes is not None:
        app.raw["classes"] = (
            None
            if args.classes.lower() == "all"
            else [int(c) for c in args.classes.split(",") if c.strip()]
        )

    approach = "approach_a" if args.approach == "A" else "approach_b"
    ranger = CatRanger(app, approach=approach, use_depth=not args.no_depth, device=args.device)
    follower = Follower(app.get("follow", default={}))

    results: list[FrameResult] = []
    commands: list[Command] = []
    frame_times: list[float] = []

    print(
        f"[eval] source={args.source} camera={app.camera.name} approach={approach} "
        f"depth={'off' if args.no_depth else 'on'}"
    )
    if args.max_frames == 0 and (is_stream(args.source) or str(args.source).isdigit()):
        print(
            "[eval] warning: unbounded source (stream/webcam) with --max-frames 0 — every "
            "frame is buffered in memory for aggregate metrics; pass --max-frames N to bound it."
        )
    for idx, frame in frame_source(args.source, stride=args.stride, max_frames=args.max_frames):
        t0 = time.perf_counter()
        result = ranger.process(frame, frame_index=idx)
        frame_times.append(time.perf_counter() - t0)
        results.append(result)
        commands.append(follower.step(result))

    if not results:
        print("[eval] no frames processed — nothing to report")
        return 1

    # The provided inference sets ship NO distance labels, so MAE/MAPE are skipped
    # (gts=None). Pass gts={"preds":[...], "gts":[...]} (meters) to populate them.
    metrics = run_eval(results, commands, frame_times, gts=None)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    path = build_report(metrics, str(out), title=f"CatRanger performance report — {approach}")
    print(
        f"[eval] {len(results)} frames | mean {float(metrics['fps'].get('mean_fps', 0.0)):.1f} FPS "
        f"| wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
