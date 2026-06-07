"""Autoresearch keep/reject loop (the karpathy/autoresearch pattern).

    python -m catranger.train.autoresearch --config configs/train.yaml

Reads `autoresearch.trials` (a list of hyperparameter overrides) from the config and
runs each as a FIXED-BUDGET fine-tune. Each trial is judged against ONE frozen metric
(val mAP50-95). We KEEP the best trial and REJECT the rest — no moving goalposts.

What "fixed budget" means here: `autoresearch.budget_min` caps wall-clock per trial.
We estimate how many epochs fit the budget from a quick first trial's epoch time and
cap subsequent trials, and we hard-stop a trial that blows past the budget. The frozen
metric is the only thing that decides keep vs reject.

Outputs:
  runs/train/autoresearch_log.jsonl   one JSON line per trial (append-only audit log)
  runs/train/best_trial.json          the winning override + metric + published weights

Reuses train.py's `train_once` (imported), so there is exactly one training primitive.
Baseline-first: this is a stretch; the pretrained baseline runs without ever calling it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = _REPO_ROOT / "runs" / "train"
LOG_PATH = RUNS_DIR / "autoresearch_log.jsonl"
BEST_PATH = RUNS_DIR / "best_trial.json"

from catranger.train.train import _load_config, publish_weights, train_once  # noqa: E402


def _append_log(record: dict[str, Any]) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def _budget_epochs(budget_min: float, sec_per_epoch: float | None, cap: int) -> int:
    """How many epochs fit the time budget, given a measured seconds/epoch. Always >=1,
    never more than the config's epoch cap."""
    if not sec_per_epoch or sec_per_epoch <= 0:
        return cap
    fit = int((budget_min * 60.0) / sec_per_epoch)
    return max(1, min(cap, fit))


def autoresearch(
    config_path: str = "configs/train.yaml", device: str | None = None
) -> dict[str, Any]:
    cfg = _load_config(config_path)
    if device:
        cfg["device"] = device  # let the web/CLI pick the box's real device
    ar = cfg.get("autoresearch", {}) or {}
    trials: list[dict[str, Any]] = list(ar.get("trials", []) or [])
    budget_min = float(ar.get("budget_min", 5))
    epoch_cap = int(cfg.get("epochs", 40))
    metric_key = str(cfg.get("metric", "metrics/mAP50-95(B)"))

    if not trials:
        raise SystemExit(
            "no autoresearch.trials in the config; add a list of hyperparam override dicts."
        )

    print(
        f"[autoresearch] {len(trials)} trials, budget={budget_min} min/trial, "
        f"frozen metric={metric_key}"
    )

    best: dict[str, Any] | None = None
    sec_per_epoch: float | None = None  # learned from the first trial, reused as an estimate

    for i, overrides in enumerate(trials):
        # Cap this trial's epochs to fit the wall-clock budget.
        epochs = _budget_epochs(budget_min, sec_per_epoch, epoch_cap)
        name = f"autoresearch_t{i}"
        print(
            f"\n[autoresearch] === trial {i} === overrides={overrides} "
            f"epochs<= {epochs} (budget {budget_min} min)"
        )

        t0 = time.time()
        record: dict[str, Any] = {
            "trial": i,
            "name": name,
            "overrides": overrides,
            "budget_min": budget_min,
            "metric_key": metric_key,
        }
        try:
            out = train_once(cfg, overrides=overrides, name=name, epochs=epochs)
            metric = out["metric"]
            record.update({"metric": metric, "best_pt": out["best_pt"], "ok": True})
        except SystemExit as e:
            # missing deps/data: log + re-raise so the operator fixes the environment.
            record.update({"metric": None, "ok": False, "error": str(e)})
            _append_log(record)
            raise
        except Exception as e:  # a single trial failing must not kill the sweep
            record.update({"metric": None, "ok": False, "error": repr(e)})
            _append_log(record)
            print(f"[autoresearch] trial {i} FAILED: {e!r} -> REJECT")
            continue

        elapsed = time.time() - t0
        record["elapsed_s"] = round(elapsed, 1)
        # Calibrate seconds/epoch from the first successful trial for later budgeting.
        if sec_per_epoch is None and epochs > 0 and elapsed > 0:
            sec_per_epoch = elapsed / epochs

        # ---- keep/reject decision against the ONE frozen metric ----
        metric_val = record["metric"]
        is_finite = metric_val is not None and metric_val == metric_val  # not NaN
        if best is None or (is_finite and metric_val > best["metric"]):
            prev = None if best is None else best["metric"]
            best = dict(record)
            record["decision"] = "KEEP"
            print(f"[autoresearch] trial {i}: {metric_key}={metric_val} -> KEEP (prev best={prev})")
        else:
            record["decision"] = "REJECT"
            print(
                f"[autoresearch] trial {i}: {metric_key}={metric_val} -> REJECT "
                f"(best={best['metric']})"
            )

        _append_log(record)

    if best is None:
        raise SystemExit("[autoresearch] no trial produced a metric; nothing to keep.")

    # Publish the winner's weights to the stable path and record the decision.
    published = publish_weights(best["best_pt"])
    winner = {
        "metric_key": metric_key,
        "metric": best["metric"],
        "overrides": best["overrides"],
        "name": best["name"],
        "best_pt": best["best_pt"],
        "published_weights": str(published) if published else None,
        "n_trials": len(trials),
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(BEST_PATH, "w") as f:
        json.dump(winner, f, indent=2)

    print(f"\n[autoresearch] WINNER overrides={best['overrides']} {metric_key}={best['metric']}")
    print(f"[autoresearch] wrote {BEST_PATH}")
    print(f"[autoresearch] trial log -> {LOG_PATH}")
    if published is not None:
        print(
            "[autoresearch] to use the winner, set in configs/cat_distance.yaml:\n"
            f"          detector:\n"
            f"            finetuned_weights: {published}"
        )
    return winner


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fixed-budget keep/reject hyperparam sweep.")
    ap.add_argument("--config", default="configs/train.yaml", help="path to train.yaml")
    ap.add_argument("--device", default=None, help="override device (cuda|mps|cpu|0)")
    args = ap.parse_args(argv)
    autoresearch(args.config, device=args.device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
