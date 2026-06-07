#!/usr/bin/env python3
"""Unattended overnight runner: execute a plan of train/eval jobs, archive each run.

    python scripts/overnight.py                          # uses configs/overnight.yaml
    python scripts/overnight.py --config configs/overnight.yaml
    python scripts/overnight.py --dry-run                # print the plan, run nothing

Kick this off before bed; review `runs/history/` in the morning. Each job runs in its
OWN subprocess, so a torch segfault, an OOM, or a missing dataset takes down only that
job — never the whole night. Every job (success, failure, or skip) is archived to
`runs/history/<ts>-<kind>/` via catranger.history and listed in `runs/history/INDEX.md`.

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
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from catranger import history  # noqa: E402

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


def _run(cmd: list[str]) -> tuple[int, str, float]:
    """Run a subprocess, capturing combined stdout+stderr. Returns (rc, log, secs)."""
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    secs = time.time() - t0
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, log, secs


def _do_training(job: dict, ts: str) -> dict:
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
    rc, log, secs = _run(cmd)

    status = "ok" if rc == 0 else "fail"
    metric: float | None = None
    metrics: dict | None = None
    artifacts: dict[str, str] = {}
    summary = f"rc={rc}"
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
    return {"kind": kind, "status": status, "metric": metric}


def _do_eval(job: dict, ts: str, idx: int) -> dict:
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
    rc, log, secs = _run(cmd)

    status = "ok" if rc == 0 else "fail"
    metrics: dict | None = None
    metric: float | None = None
    summary = f"rc={rc}"
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
    return {"kind": "eval", "status": status, "metric": metric}


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

    print(f"[overnight] {len(jobs)} job(s) from {cfg_path}")
    for i, job in enumerate(jobs):
        print(
            f"  [{i}] {job.get('kind')}: {json.dumps({k: v for k, v in job.items() if k != 'kind'})}"
        )
    if dry_run:
        print("[overnight] --dry-run: nothing executed.")
        return 0

    results: list[dict] = []
    for i, job in enumerate(jobs):
        kind = str(job.get("kind", "")).strip()
        # One timestamp per job; '+i' keeps dirs unique even on a fast machine.
        ts = f"{history.stamp()}-{i}"
        try:
            if kind in ("autoresearch", "train"):
                results.append(_do_training(job, ts))
            elif kind == "eval":
                results.append(_do_eval(job, ts, i))
            else:
                print(f"[overnight] [{i}] unknown kind {kind!r} — skipping")
                history.archive_run(
                    kind or "unknown",
                    ts=ts,
                    status="skipped",
                    params=job,
                    summary=f"unknown job kind {kind!r}",
                )
        except Exception as exc:  # a single job must never kill the night
            print(f"[overnight] [{i}] {kind} crashed the runner: {exc!r}")
            history.archive_run(
                kind or "unknown", ts=ts, status="fail", params=job, summary=repr(exc)
            )
            results.append({"kind": kind, "status": "fail"})

    ok = sum(1 for r in results if r.get("status") == "ok")
    print(
        f"\n[overnight] done: {ok}/{len(results)} ok. "
        f"Review: `make history` or runs/history/INDEX.md"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the overnight train/eval plan, archive history.")
    ap.add_argument("--config", default="configs/overnight.yaml", help="path to the plan yaml")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    args = ap.parse_args(argv)
    return run_plan(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
