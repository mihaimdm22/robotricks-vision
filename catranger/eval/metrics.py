"""Pure numpy/stdlib metric functions for the CatRanger performance report.

These are the numbers the judges grade (cat-tracker.md sec 8):
  * FPS (p50/p95 frame time) — the hard ">=15 FPS" requirement.
  * Track continuity — #ID-switches, mean track lifetime, longest single-ID streak.
  * Distance accuracy — MAE / MAPE against any ground-truth ranges (How Far).
  * Command smoothness — per-channel jerk + rotation oscillation count.

No heavy deps: numpy only (and that lazily, so importing this module is cheap).
Everything is deterministic and works on plain Python lists, so it can run on a
machine with no GPU / no torch installed.
"""

from __future__ import annotations

from collections.abc import Sequence

# Types are stdlib-only dataclasses (catranger.types), safe to import eagerly.
from catranger.types import Command, FrameResult


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0, 100]) on an already-sorted list.

    Self-contained so we don't need numpy just for a percentile, and matches
    numpy's default ('linear') interpolation for parity with downstream tooling.
    """
    n = len(sorted_vals)
    if n == 0:
        return float("nan")
    if n == 1:
        return float(sorted_vals[0])
    rank = (q / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def fps_stats(frame_times: list[float]) -> dict[str, float]:
    """Throughput stats from per-frame wall times (seconds).

    Returns {mean_fps, p50_ms, p95_ms, n}. Non-finite / non-positive frame
    times are dropped so a single zero doesn't blow up the mean.
    """
    times = [float(t) for t in frame_times if t is not None and float(t) > 0.0]
    if not times:
        return {"mean_fps": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "n": 0}
    ms = sorted(t * 1000.0 for t in times)
    mean_dt = sum(times) / len(times)
    mean_fps = 1.0 / mean_dt if mean_dt > 0 else 0.0
    return {
        "mean_fps": float(mean_fps),
        "p50_ms": _percentile(ms, 50.0),
        "p95_ms": _percentile(ms, 95.0),
        "n": len(times),
    }


def _frame_track_ids(result: FrameResult) -> list[int]:
    """All non-None track ids present in a frame (one per observation)."""
    ids: list[int] = []
    for obs in result.observations:
        tid = obs.track_id
        if tid is not None:
            ids.append(int(tid))
    return ids


def track_stats(results: list[FrameResult]) -> dict[str, object]:
    """Track-continuity proxies derived purely from track ids across frames.

    Definitions (deliberately simple, no GT needed):
      * unique_ids            — number of distinct track ids ever seen.
      * mean_track_lifetime_frames — mean over ids of (#frames that id appears in).
      * longest_streak        — longest run of *consecutive* frames a single id
                                 stays present without a gap (occlusion-robustness).
      * num_id_switches       — #frames where the *target* id (largest box, per
                                 FrameResult.target) differs from the previous
                                 frame's target id, ignoring frames with no target.
                                 A proxy for "the followed cat's identity flipped".
    """
    seen_ids: set = set()
    lifetime: dict[int, int] = {}  # id -> total frames present
    cur_streak: dict[int, int] = {}  # id -> current consecutive run
    best_streak: dict[int, int] = {}  # id -> best consecutive run

    prev_target_id: int | None = None
    id_switches = 0

    for res in results:
        ids = _frame_track_ids(res)
        present = set(ids)
        for tid in present:
            seen_ids.add(tid)
            lifetime[tid] = lifetime.get(tid, 0) + 1
            cur_streak[tid] = cur_streak.get(tid, 0) + 1
            best_streak[tid] = max(best_streak.get(tid, 0), cur_streak[tid])
        # reset streaks for ids that vanished this frame
        for tid in list(cur_streak.keys()):
            if tid not in present:
                cur_streak[tid] = 0

        target = res.target
        tgt_id = target.track_id if target is not None else None
        if tgt_id is not None:
            if prev_target_id is not None and tgt_id != prev_target_id:
                id_switches += 1
            prev_target_id = tgt_id

    n_ids = len(seen_ids)
    mean_lifetime = (sum(lifetime.values()) / n_ids) if n_ids else 0.0
    longest = max(best_streak.values()) if best_streak else 0

    return {
        "num_id_switches": int(id_switches),
        "mean_track_lifetime_frames": float(mean_lifetime),
        "longest_streak": int(longest),
        "unique_ids": int(n_ids),
    }


def distance_mae(preds: list[float], gts: list[float]) -> dict[str, float]:
    """Distance error vs ground truth (How Far).

    Returns {mae, mape, n}. Pairs where either value is non-finite, or the GT is
    <= 0 (can't form a percentage), are skipped. `mape` is a fraction in [0, inf)
    (multiply by 100 for a percentage), defined as mean(|p - g| / g).
    """
    import math

    abs_errs: list[float] = []
    pct_errs: list[float] = []
    for p, g in zip(preds, gts):
        try:
            pf = float(p)
            gf = float(g)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(pf) and math.isfinite(gf)):
            continue
        err = abs(pf - gf)
        abs_errs.append(err)
        if gf > 0.0:
            pct_errs.append(err / gf)

    mae = float(sum(abs_errs) / len(abs_errs)) if abs_errs else float("nan")
    mape = float(sum(pct_errs) / len(pct_errs)) if pct_errs else float("nan")
    return {"mae": mae, "mape": mape, "n": len(abs_errs)}


def _command_channels(commands: Sequence[Command]):
    """Extract the four normalized control channels as parallel lists."""
    rot = [float(c.rotation) for c in commands]
    dx = [float(c.dx) for c in commands]
    dy = [float(c.dy) for c in commands]
    vf = [float(c.v_fwd) for c in commands]
    return rot, dx, dy, vf


def _mean_abs_diff(seq: Sequence[float]) -> float:
    """jerk = mean |u_t - u_{t-1}| over consecutive samples."""
    if len(seq) < 2:
        return 0.0
    diffs = [abs(seq[i] - seq[i - 1]) for i in range(1, len(seq))]
    return float(sum(diffs) / len(diffs))


def _sign_changes(seq: Sequence[float], eps: float = 1e-6) -> int:
    """Count sign flips of a signal, ignoring (near-)zero samples so a command
    that merely passes through 0 once isn't counted as an oscillation."""
    last_sign = 0
    changes = 0
    for v in seq:
        if v > eps:
            s = 1
        elif v < -eps:
            s = -1
        else:
            continue  # treat ~0 as "no opinion", keep previous sign
        if last_sign != 0 and s != last_sign:
            changes += 1
        last_sign = s
    return changes


def smoothness(commands: list[Command]) -> dict[str, object]:
    """Command-smoothness metrics (the judges grade this explicitly, sec 4.4/8).

    Returns:
      * rotation_jerk        — mean |rot_t - rot_{t-1}| (lower = smoother).
      * vfwd_jerk            — mean |v_fwd_t - v_fwd_{t-1}|.
      * dx_jerk, dy_jerk     — same for the strafe / pan channels (bonus detail).
      * rotation_oscillations — #sign changes of rotation (anti-oscillation score).
      * n                    — number of commands considered.
    """
    if not commands:
        return {
            "rotation_jerk": 0.0,
            "vfwd_jerk": 0.0,
            "dx_jerk": 0.0,
            "dy_jerk": 0.0,
            "rotation_oscillations": 0,
            "n": 0,
        }
    rot, dx, dy, vf = _command_channels(commands)
    return {
        "rotation_jerk": _mean_abs_diff(rot),
        "vfwd_jerk": _mean_abs_diff(vf),
        "dx_jerk": _mean_abs_diff(dx),
        "dy_jerk": _mean_abs_diff(dy),
        "rotation_oscillations": _sign_changes(rot),
        "n": len(commands),
    }


def synthetic_occlusion_reacquire(
    pre_id: int | None = None,
    post_id: int | None = None,
    gap_frames: int = 0,
    reacquired_frame: int | None = None,
) -> dict[str, object]:
    """Re-acquire success after a *synthetic* full occlusion (sec 8).

    The harness blacks out a centered box for ~15 frames; this helper just scores
    the outcome once the IDs before/after the gap are known. It's intentionally a
    thin stub: the actual occlusion injection + re-run lives in the demo/eval
    script (it needs the pipeline + frames), and the only graded number is
    "did the same identity come back, and how fast".

    Pass the followed track id immediately before the blackout (`pre_id`), the id
    after the cat reappears (`post_id`), the blackout length (`gap_frames`), and
    optionally the frame index at which the original id returned
    (`reacquired_frame`) to also get latency in frames. With no arguments this
    returns an empty dict, matching the "minimal stub" contract.
    """
    if pre_id is None and post_id is None:
        return {}
    reacquired = pre_id is not None and post_id is not None and int(pre_id) == int(post_id)
    out: dict[str, object] = {
        "reacquired": bool(reacquired),
        "pre_id": None if pre_id is None else int(pre_id),
        "post_id": None if post_id is None else int(post_id),
        "gap_frames": int(gap_frames),
    }
    if reacquired_frame is not None:
        out["reacquire_latency_frames"] = int(reacquired_frame)
    return out
