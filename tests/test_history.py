"""Unit tests for catranger.history — the run-history archive + index.

Pure stdlib, deterministic (timestamps are injected), and run against a tmp base dir
so no test ever touches the real runs/history/.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from catranger import history


def test_stamp_is_sortable_and_injectable() -> None:
    s = history.stamp(datetime(2026, 6, 6, 23, 15, 0))
    assert s == "20260606-231500"
    # default path still returns a 15-char YYYYMMDD-HHMMSS string
    assert len(history.stamp()) == len("20260606-231500")


def test_archive_eval_run_writes_files_and_index(tmp_path: Path) -> None:
    report = tmp_path / "src_report.md"
    report.write_text("# report", encoding="utf-8")

    run_dir = history.archive_run(
        "eval",
        ts="20260606-231500-1",
        status="ok",
        params={"source": "data/raw/how_far", "approach": "A"},
        metrics={"metrics": {"fps": {"mean_fps": 22.5}}, "n_frames": 30},
        metric=22.5,
        metric_key="mean_fps",
        summary="approach=A mean_fps=22.5",
        duration_s=12.0,
        log_text="ran ok",
        artifacts={"report.md": str(report)},
        base=tmp_path / "history",
    )

    assert run_dir.name == "20260606-231500-1-eval"
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["kind"] == "eval" and meta["status"] == "ok" and meta["metric"] == 22.5
    assert meta["artifacts"] == ["report.md"]
    assert json.loads((run_dir / "params.json").read_text())["approach"] == "A"
    assert json.loads((run_dir / "metrics.json").read_text())["n_frames"] == 30
    assert (run_dir / "run.log").read_text() == "ran ok"
    assert (run_dir / "report.md").read_text() == "# report"

    entries = history.read_index(base=tmp_path / "history")
    assert len(entries) == 1
    assert entries[0]["dir"] == "20260606-231500-1-eval"
    assert entries[0]["metric"] == 22.5


def test_missing_artifact_is_skipped_not_fatal(tmp_path: Path) -> None:
    run_dir = history.archive_run(
        "train",
        ts="20260606-231501-0",
        artifacts={"best.pt": str(tmp_path / "does_not_exist.pt")},
        base=tmp_path / "history",
    )
    assert not (run_dir / "best.pt").exists()
    # meta has no 'artifacts' key when nothing was copied
    assert "artifacts" not in json.loads((run_dir / "meta.json").read_text())


def test_index_is_append_only_and_md_regenerates(tmp_path: Path) -> None:
    base = tmp_path / "history"
    history.archive_run("autoresearch", ts="20260606-2300-0", metric=0.71, base=base)
    history.archive_run("eval", ts="20260606-2301-1", metric=18.0, status="fail", base=base)

    entries = history.read_index(base=base)
    assert [e["kind"] for e in entries] == ["autoresearch", "eval"]

    md = (base / "INDEX.md").read_text()
    assert "autoresearch" in md and "eval" in md
    assert "2 run(s)" in md
    # rendered metric column carries the key label
    assert "0.71" in md and "18 (mean_fps)" not in md  # eval entry had no metric_key here


def test_read_index_empty_when_no_runs(tmp_path: Path) -> None:
    assert history.read_index(base=tmp_path / "nope") == []
    # render on an empty base produces the placeholder, not a crash
    text = history.render_index(base=tmp_path / "empty")
    assert "No runs archived yet" in text


def test_fmt_helpers() -> None:
    assert history._fmt_metric(None, None) == "—"
    assert history._fmt_metric(0.123456, "mAP") == "0.1235 (mAP)"
    assert history._fmt_metric("skipped", None) == "skipped"
    assert history._fmt_secs(None) == "—"
    assert history._fmt_secs(45) == "45s"
    assert history._fmt_secs(150).endswith("m")


def test_summary_pipe_is_escaped_in_md(tmp_path: Path) -> None:
    base = tmp_path / "history"
    history.archive_run("eval", ts="20260606-2302-0", summary="a|b|c", base=base)
    md = (base / "INDEX.md").read_text()
    assert "a\\|b\\|c" in md
