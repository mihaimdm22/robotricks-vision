"""CatRanger evaluation harness — the graded performance report (cat-tracker.md §8).

Pure numpy/stdlib: no torch/ultralytics, so metrics + report can be (re)generated
on a CPU-only box from already-collected per-frame outputs.

    from catranger.eval import run_eval, build_report
    metrics = run_eval(results, commands, frame_times)
    build_report(metrics, "report.md")
"""

from catranger.eval.metrics import (
    distance_mae,
    fps_stats,
    smoothness,
    synthetic_occlusion_reacquire,
    track_stats,
)
from catranger.eval.report import build_report, run_eval

__all__ = [
    "fps_stats",
    "track_stats",
    "distance_mae",
    "smoothness",
    "synthetic_occlusion_reacquire",
    "run_eval",
    "build_report",
]
