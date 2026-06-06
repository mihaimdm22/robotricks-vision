# CatRanger — engineering rules (Karpathy-derived)

> Monsson hack-a-ton 2026. Detect a cat, keep its identity, say how far it is, and
> (optionally) drive the robot to follow. Scored on the Go2 hidden test set; the
> Arduino+Tapo rig is a live-demo prop. ~24h. Team build.

## The one rule that decides everything
If a change does not improve the **frozen metric** for the challenge we entered
(distance MAE, track continuity, FPS, command smoothness), it is demo garnish or a
distraction. Triage accordingly.

## Karpathy discipline (adopted from multica-ai/andrej-karpathy-skills)
1. **Don't assume — surface tradeoffs.** The briefs are ambiguous (How Far =
   "between objects" vs "camera→object"). We output BOTH and state the assumption in
   code comments and the README.
2. **Minimum code. Nothing speculative.** No abstraction for single-use code, no
   config knob nobody asked for. If it's not on the rubric, don't build it.
3. **Goal-driven execution.** Every task is a declarative, checkable goal:
   - "demo.py runs on a video and prints a per-cat distance" (checkable)
   - "eval prints a finite FPS and MAE float" (checkable)
   Loop until the check passes; never hand-wave "should work".
4. **One frozen metric, keep/reject loop** (the `karpathy/autoresearch` pattern).
   `catranger/train/autoresearch.py` runs fixed-budget experiments against a frozen
   eval and keeps a change only if the metric improves. No moving the goalposts.
5. **Surgical changes.** Touch the fewest files. Deterministic seeds. Config in YAML,
   never hard-coded numbers. Always keep a working `git` state that demos.

## Training policy (read before you `train.py`)
- The **pretrained baseline must always run** — it is the safety net and the
  guaranteed demo. Fine-tuning is a *stretch on top*, hard time-boxed.
- We **fine-tune** a pretrained YOLO on a cat dataset; we do **not** train from
  scratch (no labels, no time, worse generalization). "Karpathy" here = the minimal
  single-file harness + the frozen-metric keep/reject loop, not a from-scratch run.
- Hard gate: **no fine-tune may block the live demo.** If a run isn't beating the
  baseline by its time-box, revert and ship the baseline.

## Camera policy
- Develop and report against **Go2 intrinsics** (`fx=fy=554.3, cx=960, cy=540`,
  120° FOV). Any metric estimate demoed on the **Tapo C211** must be re-anchored
  (different sensor/lens) — select with `--camera go2|tapo`.
- No distortion coefficients were provided. We undistort with a one-parameter
  FOV/division model derived from the known 120°, or trust center crops. State it.

## Maintenance mode (post-hackathon)
The hack-a-ton entry shipped (v0.1.0). CatRanger is now a **maintained project** with a
test suite, linting, type-checking, pre-commit, and CI (see `CONTRIBUTING.md`). The rules
above still hold — with one scoping clarification so they don't fight maintenance:

- The frozen-metric doctrine (**"minimum code, nothing speculative, surgical changes"**)
  remains law for the **scored perception core**: `catranger/{intrinsics,distance,detect,
  depth,track,pipeline}.py`. Don't gold-plate the math or add knobs nobody asked for there.
- **Tooling, tests, CI, types, and docs are exempt** — they are now expected, not "demo
  garnish". Adding a test, a type annotation, or a lint fix is always in scope.
- **Quality gates are non-negotiable**: `ruff`, `mypy`, and `pytest` must pass
  (`make check`). New testable core logic ships with a test. Package management is `uv`.
- The pretrained-baseline-always-runs and numbers-live-in-YAML rules are permanent.
