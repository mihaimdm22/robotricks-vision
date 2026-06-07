"""WS-A4 training-resume checkpoint detection (the pure piece; the actual resume needs ml
and is exercised by the train CI leg, not here)."""

from __future__ import annotations

from pathlib import Path

from catranger.train.train import _resume_checkpoint


def test_resume_checkpoint_found_when_last_pt_exists(tmp_path: Path) -> None:
    weights = tmp_path / "weights"
    weights.mkdir()
    last = weights / "last.pt"
    last.write_bytes(b"ckpt")
    assert _resume_checkpoint(tmp_path) == last


def test_resume_checkpoint_none_when_absent(tmp_path: Path) -> None:
    assert _resume_checkpoint(tmp_path) is None
    (tmp_path / "weights").mkdir()
    assert _resume_checkpoint(tmp_path) is None  # dir but no last.pt


def test_resume_uses_last_pt_not_best_pt(tmp_path: Path) -> None:
    # best.pt is for scoring, not resume — its presence must NOT make us "resumable".
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "best.pt").write_bytes(b"best")
    assert _resume_checkpoint(tmp_path) is None
