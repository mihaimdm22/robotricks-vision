"""Scored keep/reject harness (WS-D0.2): decide whether a perception-config change is
KEPT or REVERTED on the FROZEN metrics — distance MAE, FPS, track continuity, command
smoothness — vs a recorded baseline.

This is the gate every WS-D metric mover must pass, and it is deliberately SEPARATE from
``catranger.train.autoresearch`` (which optimizes detection mAP, not these four — the gap
the review flagged). It does not run eval itself: it compares two metrics-json files that
``catranger.eval.report --metrics-json`` already produces, so "apply a config delta" is
just running ``make eval`` twice (baseline vs candidate) and letting this decide.

Faithfulness (docs/02 §12): only FAITHFUL metrics gate by default — FPS always, MAE when a
GT sidecar (``--gts``) was supplied. Track continuity and command smoothness are proxies:
reported and advisory, never hard gates unless you pass ``--gate-proxies``.

Pure decision logic (json + stdlib) so it unit-tests without torch; the eval that feeds it
is the heavy path, not this.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetricSpec:
    name: str
    lower_is_better: bool
    faithful: bool  # True -> gates by default; False -> proxy (advisory unless --gate-proxies)


# The frozen-metric family, mapped to the flat keys extract_scored() produces.
_SPECS: dict[str, MetricSpec] = {
    "mae": MetricSpec("mae", lower_is_better=True, faithful=True),
    "mean_fps": MetricSpec("mean_fps", lower_is_better=False, faithful=True),
    "id_switches": MetricSpec("id_switches", lower_is_better=True, faithful=False),
    "longest_streak": MetricSpec("longest_streak", lower_is_better=False, faithful=False),
    "rotation_jerk": MetricSpec("rotation_jerk", lower_is_better=True, faithful=False),
}


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def load_metrics(path: str | Path) -> dict:
    """Load a metrics dict from a report --metrics-json file (a {"metrics": {...}} wrapper)
    or a bare metrics dict. Raises ValueError on an unreadable/wrong-shaped file."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read metrics json {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"metrics json {p} must be a JSON object, got {type(data).__name__}")
    inner = data.get("metrics")
    return inner if isinstance(inner, dict) else data


def extract_scored(metrics: dict) -> dict[str, float]:
    """Flatten run_eval's nested metrics into the comparable frozen-metric scalars. MAE is
    included only when the distance section has labeled samples (n>0, i.e. a GT sidecar was
    used) — otherwise it is unmeasured and simply absent (it can't gate)."""
    out: dict[str, float] = {}
    fps = metrics.get("fps") or {}
    if _finite(fps.get("mean_fps")):
        out["mean_fps"] = float(fps["mean_fps"])
    dist = metrics.get("distance") or {}
    if dist.get("n") and _finite(dist.get("mae")):
        out["mae"] = float(dist["mae"])
    tr = metrics.get("tracking") or {}
    if _finite(tr.get("num_id_switches")):
        out["id_switches"] = float(tr["num_id_switches"])
    if _finite(tr.get("longest_streak")):
        out["longest_streak"] = float(tr["longest_streak"])
    sm = metrics.get("smoothness") or {}
    if _finite(sm.get("rotation_jerk")):
        out["rotation_jerk"] = float(sm["rotation_jerk"])
    return out


def _pick_primary(baseline: dict, candidate: dict) -> str:
    """MAE is the headline metric when measurable in both; else FPS (always faithful)."""
    if "mae" in baseline and "mae" in candidate:
        return "mae"
    return "mean_fps"


def decide(
    baseline: dict[str, float],
    candidate: dict[str, float],
    *,
    primary: str | None = None,
    rel_tol: float = 0.0,
    gate_proxies: bool = False,
) -> dict:
    """Keep iff the PRIMARY metric improves (beyond a rel_tol noise band) AND no gated
    metric regresses. Faithful metrics always gate; proxies gate only with gate_proxies.
    Returns a structured decision: {verdict, primary, reason, metrics: {name: {...}}}.
    """
    primary = primary or _pick_primary(baseline, candidate)
    rows: dict[str, dict] = {}
    regressed_gates: list[str] = []
    for name in sorted(set(baseline) | set(candidate)):
        if name not in _SPECS:
            continue
        spec = _SPECS[name]
        b, c = baseline.get(name), candidate.get(name)
        if not (_finite(b) and _finite(c)):
            rows[name] = {"baseline": b, "candidate": c, "status": "n/a"}
            continue
        bf, cf = float(b), float(c)  # type: ignore[arg-type]
        tol_abs = abs(rel_tol) * abs(bf)
        delta = cf - bf
        if spec.lower_is_better:
            improved, regressed = delta < -tol_abs, delta > tol_abs
        else:
            improved, regressed = delta > tol_abs, delta < -tol_abs
        status = "improved" if improved else ("regressed" if regressed else "unchanged")
        rows[name] = {
            "baseline": bf,
            "candidate": cf,
            "delta": delta,
            "pct": (delta / abs(bf) * 100.0) if bf else float("nan"),
            "status": status,
            "lower_is_better": spec.lower_is_better,
            "faithful": spec.faithful,
        }
        if (spec.faithful or gate_proxies) and regressed:
            regressed_gates.append(name)

    primary_row = rows.get(primary)
    if primary_row is None or primary_row.get("status") == "n/a":
        verdict, reason = "reject", f"primary metric {primary!r} missing in baseline or candidate"
    elif primary_row["status"] != "improved":
        verdict, reason = "reject", f"primary {primary} did not improve ({primary_row['status']})"
    elif regressed_gates:
        verdict, reason = "reject", f"gated metric(s) regressed: {regressed_gates}"
    else:
        verdict, reason = "keep", f"primary {primary} improved with no gated regressions"
    return {"verdict": verdict, "primary": primary, "reason": reason, "metrics": rows}


def format_report(decision: dict) -> str:
    """Human-readable keep/reject summary."""
    lines = [
        f"keep/reject: {decision['verdict'].upper()}  (primary={decision['primary']})",
        f"  reason: {decision['reason']}",
        "  metric          baseline   candidate     change   status",
    ]
    for name, r in decision["metrics"].items():
        if r.get("status") == "n/a":
            lines.append(f"  {name:<14}  {'—':>8}   {'—':>8}        n/a   (missing)")
            continue
        arrow = "↓ better" if r["lower_is_better"] else "↑ better"
        flag = "" if r.get("faithful") else " [proxy]"
        lines.append(
            f"  {name:<14}  {r['baseline']:>8.4g}   {r['candidate']:>8.4g}  "
            f"{r['pct']:>+7.1f}%   {r['status']}{flag}  ({arrow})"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="catranger.eval.keepreject",
        description="Keep/reject a config change on the frozen metrics vs a baseline "
        "(compares two `report --metrics-json` files).",
    )
    ap.add_argument("--baseline", required=True, help="baseline metrics-json (the recorded run)")
    ap.add_argument("--candidate", required=True, help="candidate metrics-json (the change)")
    ap.add_argument(
        "--primary",
        default=None,
        choices=sorted(_SPECS),
        help="metric that must improve to KEEP (default: mae if measured in both, else mean_fps)",
    )
    ap.add_argument(
        "--rel-tol",
        type=float,
        default=0.0,
        help="noise band: a change within rel_tol*|baseline| counts as unchanged (e.g. 0.02)",
    )
    ap.add_argument(
        "--gate-proxies",
        action="store_true",
        help="also let proxy regressions (continuity/smoothness) block KEEP (default: advisory)",
    )
    args = ap.parse_args(argv)
    try:
        base = extract_scored(load_metrics(args.baseline))
        cand = extract_scored(load_metrics(args.candidate))
    except ValueError as exc:
        print(f"[keepreject] {exc}")
        return 1
    decision = decide(
        base, cand, primary=args.primary, rel_tol=args.rel_tol, gate_proxies=args.gate_proxies
    )
    print(format_report(decision))
    # exit 0 = KEEP, 2 = REJECT — scriptable for an automated sweep.
    return 0 if decision["verdict"] == "keep" else 2


if __name__ == "__main__":
    raise SystemExit(main())
