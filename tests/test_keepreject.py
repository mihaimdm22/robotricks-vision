"""WS-D0.2 scored keep/reject harness: extraction + decision logic on the frozen metrics."""

from __future__ import annotations

import json

import pytest

from catranger.eval.keepreject import (
    decide,
    extract_scored,
    format_report,
    load_metrics,
    main,
)

# A realistic run_eval metrics dict (with a labeled distance section).
_METRICS = {
    "fps": {"mean_fps": 30.0, "n": 100},
    "distance": {"mae": 0.40, "mape": 0.10, "n": 50},
    "tracking": {"num_id_switches": 3, "longest_streak": 40, "unique_ids": 5},
    "smoothness": {"rotation_jerk": 0.05, "n": 100},
}


def test_load_metrics_unwraps_and_bare(tmp_path):
    wrapped = tmp_path / "w.json"
    wrapped.write_text(json.dumps({"metrics": _METRICS, "n_frames": 100}))
    assert load_metrics(wrapped)["fps"]["mean_fps"] == 30.0
    bare = tmp_path / "b.json"
    bare.write_text(json.dumps(_METRICS))
    assert load_metrics(bare)["distance"]["mae"] == 0.40


def test_load_metrics_bad_file_raises(tmp_path):
    with pytest.raises(ValueError):
        load_metrics(tmp_path / "missing.json")


def test_extract_scored_flattens_all_frozen_metrics():
    s = extract_scored(_METRICS)
    assert s == {
        "mean_fps": 30.0,
        "mae": 0.40,
        "id_switches": 3.0,
        "longest_streak": 40.0,
        "rotation_jerk": 0.05,
    }


def test_extract_scored_omits_mae_without_labels():
    m = dict(_METRICS, distance={"mae": float("nan"), "mape": float("nan"), "n": 0})
    assert "mae" not in extract_scored(m)


def test_decide_keeps_when_primary_mae_improves_and_no_gate_regresses():
    base = extract_scored(_METRICS)
    cand = dict(base, mae=0.30)  # MAE 0.40 -> 0.30 (better), FPS unchanged
    d = decide(base, cand)
    assert d["primary"] == "mae"
    assert d["verdict"] == "keep"
    assert d["metrics"]["mae"]["status"] == "improved"


def test_decide_rejects_when_faithful_gate_regresses_even_if_primary_improves():
    base = extract_scored(_METRICS)
    cand = dict(base, mae=0.30, mean_fps=20.0)  # MAE better but FPS 30 -> 20 (faithful regress)
    d = decide(base, cand)
    assert d["verdict"] == "reject"
    assert "mean_fps" in d["reason"]


def test_decide_primary_falls_back_to_fps_without_mae():
    base = {"mean_fps": 30.0, "rotation_jerk": 0.05}
    cand = {"mean_fps": 35.0, "rotation_jerk": 0.05}
    d = decide(base, cand)
    assert d["primary"] == "mean_fps"
    assert d["verdict"] == "keep"


def test_decide_proxy_regression_is_advisory_by_default_but_gates_on_opt_in():
    base = extract_scored(_METRICS)
    # MAE improves (primary), but a proxy (rotation_jerk) regresses.
    cand = dict(base, mae=0.30, rotation_jerk=0.20)
    assert decide(base, cand)["verdict"] == "keep"  # proxy advisory by default
    assert decide(base, cand, gate_proxies=True)["verdict"] == "reject"


def test_decide_rel_tol_treats_small_change_as_unchanged():
    base = {"mean_fps": 30.0}
    cand = {"mean_fps": 30.2}  # +0.7%, within a 2% band -> not an improvement
    assert decide(base, cand, rel_tol=0.02)["verdict"] == "reject"
    assert decide(base, cand, rel_tol=0.0)["verdict"] == "keep"  # strict: any gain keeps


def test_decide_rejects_when_primary_missing():
    d = decide({"mean_fps": 30.0}, {"rotation_jerk": 0.05}, primary="mae")
    assert d["verdict"] == "reject"
    assert "missing" in d["reason"]


def test_format_report_is_readable():
    d = decide(extract_scored(_METRICS), dict(extract_scored(_METRICS), mae=0.30))
    text = format_report(d)
    assert "KEEP" in text
    assert "mae" in text and "[proxy]" in text  # proxies labeled


def _dump(tmp_path, name, metrics):
    p = tmp_path / name
    p.write_text(json.dumps({"metrics": metrics, "n_frames": 100}))
    return str(p)


def test_main_exit_codes_keep_reject_and_bad_file(tmp_path, capsys):
    base = _dump(tmp_path, "base.json", _METRICS)
    better = _dump(
        tmp_path, "better.json", dict(_METRICS, distance={"mae": 0.30, "mape": 0.1, "n": 50})
    )
    # MAE improves but FPS regresses -> a faithful gate blocks KEEP.
    worse = _dump(
        tmp_path,
        "worse.json",
        dict(
            _METRICS, distance={"mae": 0.30, "mape": 0.1, "n": 50}, fps={"mean_fps": 20.0, "n": 100}
        ),
    )

    assert main(["--baseline", base, "--candidate", better]) == 0  # KEEP
    assert "KEEP" in capsys.readouterr().out

    assert main(["--baseline", base, "--candidate", worse]) == 2  # REJECT (FPS regressed)
    assert "REJECT" in capsys.readouterr().out

    assert main(["--baseline", base, "--candidate", str(tmp_path / "nope.json")]) == 1  # bad file
