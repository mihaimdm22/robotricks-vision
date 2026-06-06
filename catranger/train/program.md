# Autoresearch program — CatRanger cat-detector fine-tune

The research directions the keep/reject loop (`autoresearch.py`) explores. This is the
`program.md` of the karpathy/autoresearch pattern: **one frozen metric, one file
(`train.py`), a fixed budget per experiment, and an automated keep/reject rule.** We
steal the *loop*, not from-scratch training — we always *fine-tune* the pretrained
`yolo11s.pt` (COCO already knows "cat" = class 15).

> Baseline-first invariant: the pretrained baseline must always run. Every direction
> below is a *stretch on top* and is hard time-boxed. If nothing beats the baseline
> inside its budget, we revert and ship the baseline.

## The one frozen metric

**val mAP50-95 (B)** — config key `metric: metrics/mAP50-95(B)`, read from
`results.results_dict` after each run. It is the *only* number that decides keep vs
reject. We do not move the goalpost, swap the metric mid-sweep, or average in vibes.
Higher is better.

Fixed comparison harness (frozen across all trials):
- same dataset + `val` split (`data/cat/data.yaml` from `prepare.py`),
- same `imgsz`, same `seed` (deterministic),
- same base model (`yolo11s.pt`),
- per-trial wall-clock cap = `autoresearch.budget_min`.

## Hypotheses (the trials)

Each is a small, surgical hyperparameter override merged onto the base train args.

| # | Override | Hypothesis | Why it might move mAP50-95 |
|---|---|---|---|
| 0 | `lr0=0.01, mosaic=1.0` | Ultralytics defaults are a strong baseline. | Reference point; full mosaic = max augmentation variety. |
| 1 | `lr0=0.005, mosaic=0.5` | A *gentler* fine-tune preserves the COCO prior better on a small cat set. | Lower LR avoids catastrophic forgetting of the pretrained features; half-mosaic reduces label noise from mosaic-cut cats. |
| 2 | `lr0=0.02, mosaic=1.0, degrees=10.0` | **The Go2 OOD direction.** Rotation augmentation simulates the low, wide-angle *dog's-eye* view the hidden test set is shot from. | The Go2 camera sits ~30 cm off the floor with a 120° FOV; cats appear tilted/foreshortened vs upright web photos. `degrees=10` teaches rotation invariance for that out-of-distribution viewpoint. |

These three map exactly to `configs/train.yaml` `autoresearch.trials`. Add a row there
to add a hypothesis — no code change.

### Candidate follow-on directions (add as trials when budget allows)
- `scale` / `perspective` augmentation — more dog's-eye geometry coverage.
- `hsv_v` down — break-room lighting is dim; test brightness robustness.
- `mosaic=0.0` for the last N epochs (`close_mosaic`) — standard YOLO endgame trick.
- `freeze=10` — freeze the backbone, fine-tune only the head on a tiny set.

## Keep/reject rule

For each trial, in order:

1. Run `train_once(cfg, overrides, epochs=budget_fit)` — epochs capped so the run fits
   `budget_min` (estimated from the first trial's seconds/epoch).
2. Read the frozen metric (val mAP50-95).
3. **KEEP** the trial iff its metric is finite and strictly greater than the current
   best; otherwise **REJECT**. The very first finite trial seeds the best.
4. Append the full record (overrides, metric, decision, elapsed) to
   `runs/train/autoresearch_log.jsonl`.

After the sweep: the winner's `best.pt` is copied to `runs/train/best.pt`, and the
winning override + metric is written to `runs/train/best_trial.json`. To deploy, set
`detector.finetuned_weights: runs/train/best.pt` in `configs/cat_distance.yaml`. The
demo still runs untouched if you don't.

## Guardrails (Karpathy discipline)

- **No goalpost moving.** The metric and the harness are frozen before the sweep.
- **Time-box is law.** A trial that can't beat the baseline in its budget is rejected
  and reverted; a fine-tune never blocks the live demo.
- **Reproducible.** Deterministic seed, single config YAML, one training primitive
  (`train_once`) shared by the CLI and the loop.
- **Surgical.** Trials are tiny override dicts. Nothing speculative gets built to run one.
