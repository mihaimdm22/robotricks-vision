#!/usr/bin/env python3
"""Unattended overnight runner: execute a plan of train/eval jobs, archive each run.

    python scripts/overnight.py                          # uses configs/overnight.yaml
    python scripts/overnight.py --config configs/overnight.yaml
    python scripts/overnight.py --dry-run                # print the plan, run nothing
    python scripts/overnight.py --fresh                  # ignore prior state, re-run all

Kick this off before bed; review `runs/history/` in the morning. Each job runs in its
OWN subprocess, so a torch segfault, an OOM, or a missing dataset takes down only that
job — never the whole night. A per-job wall-clock cap (configs/overnight.yaml
`job_timeout_min`/`timeout_min`) kills a hung job's whole process group (WS-A3).

Crash-safe (WS-A1/A2): the plan is a durable SQLite queue (`runs/jobqueue.sqlite3`).
Re-running RESUMES — completed jobs are skipped and any job left "running" by a crash
(reboot, OOM-killer, ssh drop) is recovered on the next launch. Every job is also
archived to `runs/history/<ts>-<kind>/` via catranger.history and listed in INDEX.md.

Plan format (configs/overnight.yaml)::

    jobs:
      - kind: autoresearch          # fixed-budget keep/reject sweep (configs/train.yaml)
        config: configs/train.yaml
      - kind: train                 # a single fine-tune
        config: configs/train.yaml
      - kind: eval                  # perception eval over a source
        source: data/raw/how_far
        config: cat_distance
        approach: A                 # A=YOLO11, B=RT-DETR
        device: mps                 # cuda | cpu | mps
        no_depth: false
        stride: 1
        max_frames: 0

Baseline-first (the hard rule): if the cat dataset isn't prepared, training jobs are
SKIPPED (and logged loudly) while the eval jobs still run on the pretrained baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from catranger import history  # noqa: E402
from catranger.jobqueue import TERMINAL_STATUSES, Job, JobQueue  # noqa: E402
from catranger.proc import RC_TIMEOUT, backoff_seconds, classify_failure, run_capped  # noqa: E402

JOBQUEUE_DB = REPO / "runs" / "jobqueue.sqlite3"

RUNS_TRAIN = REPO / "runs" / "train"
BEST_TRIAL = RUNS_TRAIN / "best_trial.json"
TMP_DIR = REPO / "runs" / "overnight_tmp"


def _resolve(path_like: str) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else (REPO / p).resolve()


def _train_data_ready(train_config: str) -> bool:
    """True if the fine-tune dataset yaml referenced by train.yaml exists on disk.

    A bare built-in name (e.g. 'coco8.yaml', no separator) is treated as ready —
    ultralytics resolves those itself. Mirrors train_once()'s own check.
    """
    cfg_path = _resolve(train_config)
    if not cfg_path.exists():
        return False
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw = str(cfg.get("data", "data/cat/data.yaml"))
    if "/" not in raw and "\\" not in raw:
        return True
    return _resolve(raw).exists()


def _run(cmd: list[str], timeout_s: float | None = None) -> tuple[int, str, float]:
    """Run a job subprocess under an optional wall-clock cap, capturing combined
    stdout+stderr. On timeout the whole process group is killed (no orphaned
    dataloader workers / leaked GPU memory) and rc is RC_TIMEOUT (WS-A3). Returns
    (rc, log, secs)."""
    return run_capped(cmd, cwd=REPO, timeout_s=timeout_s)


def _do_training(job: dict, ts: str, timeout_s: float | None = None) -> dict:
    kind = str(job.get("kind", "autoresearch"))
    train_config = str(job.get("config", "configs/train.yaml"))

    if not _train_data_ready(train_config):
        msg = (
            f"cat dataset not prepared (see {train_config} 'data:'); "
            "SKIPPED — run `make prepare` first. Baseline evals still run."
        )
        print(f"[overnight] {kind}: {msg}")
        history.archive_run(
            kind, ts=ts, status="skipped", params={"config": train_config}, summary=msg
        )
        return {"kind": kind, "status": "skipped"}

    module = "catranger.train.autoresearch" if kind == "autoresearch" else "catranger.train.train"
    cmd = [sys.executable, "-m", module, "--config", train_config]
    print(f"[overnight] {kind}: {' '.join(cmd)}")
    rc, log, secs = _run(cmd, timeout_s=timeout_s)

    status = "ok" if rc == 0 else ("timeout" if rc == RC_TIMEOUT else "fail")
    metric: float | None = None
    metrics: dict | None = None
    artifacts: dict[str, str] = {}
    summary = f"TIMEOUT after {secs:.0f}s" if status == "timeout" else f"rc={rc}"
    if BEST_TRIAL.exists():
        try:
            winner = json.loads(BEST_TRIAL.read_text(encoding="utf-8"))
            metrics = winner
            metric = winner.get("metric")
            mk = winner.get("metric_key", "metric")
            summary = f"{mk}={metric} overrides={winner.get('overrides')}"
            pub = winner.get("published_weights")
            if pub:
                artifacts["best.pt"] = str(pub)
        except (OSError, ValueError):
            pass

    history.archive_run(
        kind,
        ts=ts,
        status=status,
        params={"config": train_config},
        metrics=metrics,
        metric=metric,
        metric_key=(metrics or {}).get("metric_key") if metrics else None,
        summary=summary,
        duration_s=secs,
        log_text=log,
        artifacts=artifacts,
    )
    print(f"[overnight] {kind}: {status} in {secs:.0f}s — {summary}")
    return {
        "kind": kind,
        "status": status,
        "metric": metric,
        "retryable": status in ("fail", "timeout") and classify_failure(rc, log) == "retryable",
    }


def _do_eval(job: dict, ts: str, idx: int, timeout_s: float | None = None) -> dict:
    source = str(job["source"])
    config = str(job.get("config", "cat_distance"))
    approach = str(job.get("approach", "A"))
    device = job.get("device")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    report_path = TMP_DIR / f"report_{ts}_{idx}.md"
    metrics_path = TMP_DIR / f"metrics_{ts}_{idx}.json"

    cmd = [
        sys.executable,
        "-m",
        "catranger.eval.report",
        "--source",
        source,
        "--config",
        config,
        "--approach",
        approach,
        "--out",
        str(report_path),
        "--metrics-json",
        str(metrics_path),
    ]
    if device:
        cmd += ["--device", str(device)]
    if job.get("no_depth"):
        cmd += ["--no-depth"]
    if job.get("classes") is not None:
        cmd += ["--classes", str(job["classes"])]
    if job.get("camera"):
        cmd += ["--camera", str(job["camera"])]
    if int(job.get("stride", 1)) != 1:
        cmd += ["--stride", str(int(job["stride"]))]
    if int(job.get("max_frames", 0)) != 0:
        cmd += ["--max-frames", str(int(job["max_frames"]))]

    print(f"[overnight] eval: {' '.join(cmd)}")
    rc, log, secs = _run(cmd, timeout_s=timeout_s)

    status = "ok" if rc == 0 else ("timeout" if rc == RC_TIMEOUT else "fail")
    metrics: dict | None = None
    metric: float | None = None
    summary = f"TIMEOUT after {secs:.0f}s" if status == "timeout" else f"rc={rc}"
    artifacts: dict[str, str] = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            fps = (metrics.get("metrics", {}) or {}).get("fps", {})
            metric = fps.get("mean_fps")
            n = metrics.get("n_frames")
            summary = f"approach={approach} mean_fps={metric} frames={n} source={source}"
        except (OSError, ValueError):
            pass
    if report_path.exists():
        artifacts["report.md"] = str(report_path)

    history.archive_run(
        "eval",
        ts=ts,
        status=status,
        params={"source": source, "config": config, "approach": approach, "device": device},
        metrics=metrics,
        metric=metric,
        metric_key="mean_fps",
        summary=summary,
        duration_s=secs,
        log_text=log,
        artifacts=artifacts,
    )
    print(f"[overnight] eval: {status} in {secs:.0f}s — {summary}")
    return {
        "kind": "eval",
        "status": status,
        "metric": metric,
        "retryable": status in ("fail", "timeout") and classify_failure(rc, log) == "retryable",
    }


def _run_key(plan_name: str, index: int, job: dict) -> str:
    """Deterministic, stable id for a plan job so re-running the same plan resumes
    (same key -> already enqueued -> skipped) instead of duplicating work."""
    digest = hashlib.sha1(json.dumps(job, sort_keys=True).encode()).hexdigest()[:8]
    return f"{plan_name}:{index}:{job.get('kind', '?')}:{digest}"


def _run_claimed(q: JobQueue, claimed: Job, default_timeout_min: float, max_attempts: int) -> dict:
    """Dispatch one claimed job by kind, archive it to history, and resolve it in the
    queue. A crash in a single job is caught and recorded — never kills the run. A
    retryable failure (WS-A5: timeout / OOM / transient I/O) is requeued with backoff
    until max_attempts; a permanent one (bad config / missing data) fails immediately."""
    job = dict(claimed.params)
    idx = int(job.get("_index", claimed.id))
    ts = f"{history.stamp()}-{idx}"
    tmin = float(job.get("timeout_min", default_timeout_min) or 0)
    timeout_s = tmin * 60.0 if tmin > 0 else None
    try:
        if claimed.kind in ("autoresearch", "train"):
            res = _do_training(job, ts, timeout_s=timeout_s)
        elif claimed.kind == "eval":
            res = _do_eval(job, ts, idx, timeout_s=timeout_s)
        else:
            print(f"[overnight] unknown kind {claimed.kind!r} — skipping")
            history.archive_run(
                claimed.kind or "unknown",
                ts=ts,
                status="skipped",
                params=job,
                summary=f"unknown job kind {claimed.kind!r}",
            )
            res = {"kind": claimed.kind, "status": "skipped"}
    except Exception as exc:  # a single job must never kill the night
        print(f"[overnight] {claimed.kind} crashed the runner: {exc!r}")
        history.archive_run(
            claimed.kind or "unknown", ts=ts, status="fail", params=job, summary=repr(exc)
        )
        res = {"kind": claimed.kind, "status": "fail"}

    status = res.get("status", "fail")
    if status not in TERMINAL_STATUSES:
        status = "fail"

    # WS-A5: retry transient failures; q.retry owns the queued/fail transition.
    if status in ("fail", "timeout") and res.get("retryable"):
        if q.retry(claimed.id, max_attempts=max_attempts):
            delay = backoff_seconds(claimed.attempts)
            print(
                f"[overnight] {claimed.kind} {status} (retryable) -> requeue "
                f"(attempt {claimed.attempts + 1}/{max_attempts}) after {delay:.0f}s backoff"
            )
            time.sleep(delay)
        else:
            print(f"[overnight] {claimed.kind} {status} -> giving up (max attempts reached)")
        return res

    q.complete(claimed.id, status, metric=res.get("metric"), summary=status)
    return res


def run_plan(plan_path: str, dry_run: bool = False) -> int:
    cfg_path = _resolve(plan_path)
    if not cfg_path.exists():
        print(f"[overnight] plan not found: {cfg_path}")
        return 1
    plan = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    jobs = list(plan.get("jobs", []) or [])
    if not jobs:
        print(f"[overnight] no jobs in {cfg_path}")
        return 1
    # WS-A3: per-job wall-clock cap (minutes). 0/omitted = no cap. A per-job
    # `timeout_min:` overrides the plan-level `job_timeout_min:` default.
    default_timeout_min = float(plan.get("job_timeout_min", 0) or 0)

    print(f"[overnight] {len(jobs)} job(s) from {cfg_path}")
    for i, job in enumerate(jobs):
        print(
            f"  [{i}] {job.get('kind')}: {json.dumps({k: v for k, v in job.items() if k != 'kind'})}"
        )
    if dry_run:
        print("[overnight] --dry-run: nothing executed.")
        return 0

    max_attempts = int(plan.get("max_attempts", 3))
    q = JobQueue(JOBQUEUE_DB, owner="overnight")
    try:
        # WS-A2: reclaim anything left "running" by a previous crashed run BEFORE
        # claiming new work, so kill -9 mid-sweep resumes cleanly on relaunch.
        for act in q.recover_stale(max_attempts=max_attempts):
            print(
                f"[overnight] recovery: {act['run_key']} -> {act['action']} (left running by a crash)"
            )
        # WS-A1: enqueue the plan idempotently — already-present run_keys (from a prior
        # run) are skipped, so completed jobs are not redone.
        for i, job in enumerate(jobs):
            q.enqueue(
                str(job.get("kind", "unknown")).strip() or "unknown",
                job,
                _run_key(cfg_path.name, i, job),
            )
        # Claim + run until the queue drains.
        while True:
            claimed = q.claim()
            if claimed is None:
                break
            _run_claimed(q, claimed, default_timeout_min, max_attempts)
        counts = q.counts()
    finally:
        q.close()

    ok = counts.get("ok", 0)
    total = sum(counts.values())
    detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(
        f"\n[overnight] done: {ok}/{total} ok ({detail}). "
        f"Review: `make history` or runs/history/INDEX.md"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the overnight train/eval plan, archive history.")
    ap.add_argument("--config", default="configs/overnight.yaml", help="path to the plan yaml")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ap.add_argument(
        "--fresh",
        action="store_true",
        help="drop the durable job queue first, so the whole plan re-runs from scratch "
        "(default: resume — completed jobs are skipped, crashed ones recovered)",
    )
    args = ap.parse_args(argv)
    if args.fresh and JOBQUEUE_DB.exists():
        JOBQUEUE_DB.unlink()
        print(f"[overnight] --fresh: removed {JOBQUEUE_DB}")
    return run_plan(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
