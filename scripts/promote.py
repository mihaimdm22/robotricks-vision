#!/usr/bin/env python3
"""Morning 'wire it up': promote the autoresearch winner into the live pipeline.

    python scripts/promote.py                 # show the winner + trial log, confirm, wire it in
    python scripts/promote.py --yes           # skip the confirmation prompt
    python scripts/promote.py --dry-run       # preview the config edit, change nothing
    python scripts/promote.py --eval data/raw/how_far   # + run a confirm eval (archived)
    python scripts/promote.py --revert        # roll the pipeline back to the pretrained baseline

Reads `runs/train/best_trial.json` (written by autoresearch) and sets
`detector.finetuned_weights` in `configs/cat_distance.yaml` so the perception pipeline
picks up the fine-tuned weights. The pretrained baseline is ALWAYS one `--revert` away
— per the hard rule, a fine-tune may never block the demo. The promotion itself is
archived to `runs/history/` so the morning's decision is on the record too.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from catranger import history  # noqa: E402

BEST_TRIAL = REPO / "runs" / "train" / "best_trial.json"
LOG_PATH = REPO / "runs" / "train" / "autoresearch_log.jsonl"
TASK_CONFIG = REPO / "configs" / "cat_distance.yaml"
_FT_LINE = re.compile(r"^(\s*finetuned_weights:\s*).*$", re.MULTILINE)


def _set_finetuned_weights(value: str) -> bool:
    """Rewrite the `finetuned_weights:` line in cat_distance.yaml. Returns True if it
    changed something. Comment-preserving (line-level edit, not a yaml round-trip)."""
    text = TASK_CONFIG.read_text(encoding="utf-8")
    if not _FT_LINE.search(text):
        print(f"[promote] no 'finetuned_weights:' line in {TASK_CONFIG} — aborting.")
        return False
    comment = (
        "  # set by scripts/promote.py (overrides approach_a)"
        if value != "null"
        else "  # set by training to override approach_a (e.g. runs/train/best.pt)"
    )
    new = _FT_LINE.sub(rf"\g<1>{value}{comment}", text, count=1)
    if new == text:
        return False
    TASK_CONFIG.write_text(new, encoding="utf-8")
    return True


def _print_trial_log() -> None:
    if not LOG_PATH.exists():
        return
    print(f"\n[promote] keep/reject trial log ({LOG_PATH.name}):")
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        print(
            f"  trial {r.get('trial')}: {r.get('metric_key')}={r.get('metric')} "
            f"-> {r.get('decision', '?')}  overrides={r.get('overrides')}"
        )


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _run_confirm_eval(source: str) -> None:
    out = REPO / "outputs" / "report" / "promote_confirm.md"
    metrics = REPO / "outputs" / "report" / "promote_confirm.json"
    cmd = [
        sys.executable,
        "-m",
        "catranger.eval.report",
        "--source",
        source,
        "--config",
        "cat_distance",
        "--out",
        str(out),
        "--metrics-json",
        str(metrics),
    ]
    print(f"[promote] confirm eval (fine-tune wired in): {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    log = (proc.stdout or "") + (proc.stderr or "")
    print(log)
    parsed = None
    metric = None
    if metrics.exists():
        try:
            parsed = json.loads(metrics.read_text(encoding="utf-8"))
            metric = (parsed.get("metrics", {}) or {}).get("fps", {}).get("mean_fps")
        except ValueError:
            pass
    history.archive_run(
        "promote-eval",
        ts=f"{history.stamp()}-pe",
        status="ok" if proc.returncode == 0 else "fail",
        params={"source": source, "config": "cat_distance", "weights": "finetuned"},
        metrics=parsed,
        metric=metric,
        metric_key="mean_fps",
        summary=f"confirm eval after promote, source={source}",
        log_text=log,
        artifacts={"report.md": str(out)} if out.exists() else None,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Promote the fine-tune winner into the pipeline.")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--dry-run", action="store_true", help="preview only; change nothing")
    ap.add_argument("--revert", action="store_true", help="reset to the pretrained baseline")
    ap.add_argument(
        "--eval", default=None, help="run a confirm eval on this source after promoting"
    )
    args = ap.parse_args(argv)

    if args.revert:
        if args.dry_run:
            print("[promote] --dry-run: would set finetuned_weights: null (baseline).")
            return 0
        if _set_finetuned_weights("null"):
            print(f"[promote] reverted to baseline: finetuned_weights: null in {TASK_CONFIG.name}")
            history.archive_run(
                "revert",
                ts=f"{history.stamp()}-rv",
                status="ok",
                summary="pipeline reverted to pretrained baseline",
            )
        else:
            print("[promote] already on baseline (no change).")
        return 0

    if not BEST_TRIAL.exists():
        print(
            f"[promote] no winner yet: {BEST_TRIAL} missing.\n"
            "  Run the sweep first: `make autoresearch` (or `make overnight`)."
        )
        return 1

    winner = json.loads(BEST_TRIAL.read_text(encoding="utf-8"))
    weights = winner.get("published_weights") or str(REPO / "runs" / "train" / "best.pt")
    metric = winner.get("metric")
    metric_key = winner.get("metric_key", "metric")

    print(f"[promote] winner: {metric_key}={metric}")
    print(f"[promote]   overrides: {winner.get('overrides')}")
    print(f"[promote]   weights:   {weights}")
    _print_trial_log()

    if not Path(weights).exists():
        print(f"\n[promote] weights file missing: {weights} — aborting.")
        return 1

    print(
        "\n[promote] HARD RULE: a fine-tune may never block the demo. Promote only if it "
        "beats the baseline; you can always `python scripts/promote.py --revert`."
    )
    if args.dry_run:
        print(f"[promote] --dry-run: would set finetuned_weights: {weights}")
        return 0
    if not args.yes and not _confirm("Wire this fine-tune into configs/cat_distance.yaml?"):
        print("[promote] aborted — pipeline unchanged (still on baseline / current config).")
        return 0

    if _set_finetuned_weights(weights):
        print(f"[promote] wired in: finetuned_weights: {weights}")
    else:
        print("[promote] config already pointed at these weights (no change).")
    history.archive_run(
        "promote",
        ts=f"{history.stamp()}-pr",
        status="ok",
        params={"weights": weights, "overrides": winner.get("overrides")},
        metric=metric,
        metric_key=metric_key,
        summary=f"promoted fine-tune ({metric_key}={metric}) into cat_distance.yaml",
        artifacts={"best.pt": weights},
    )

    if args.eval:
        _run_confirm_eval(args.eval)

    print("\n[promote] done. Review: `make history`. Roll back anytime: `make promote-revert`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
