"""Tests for the distance ground-truth sidecar loader + aligner (catranger.eval.gts, WS-D0.1)."""

from __future__ import annotations

import json

import pytest

from catranger.eval.gts import align_preds_gts, load_gts


def _write(tmp_path, obj) -> str:
    p = tmp_path / "g.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_load_gts_flat(tmp_path):
    assert load_gts(_write(tmp_path, {"0": 1.5, "1": 2.0})) == {0: 1.5, 1: 2.0}


def test_load_gts_wrapped_by_index(tmp_path):
    assert load_gts(_write(tmp_path, {"_README": "note", "by_index": {"2": 3.0}})) == {2: 3.0}


def test_load_gts_wrapped_frames(tmp_path):
    assert load_gts(_write(tmp_path, {"frames": {"5": 0.9}})) == {5: 0.9}


def test_load_gts_bad_entry_raises(tmp_path):
    with pytest.raises(ValueError):
        load_gts(_write(tmp_path, {"0": "not-a-number"}))


def test_load_gts_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        load_gts(_write(tmp_path, {"_README": "only a note, no data"}))


def test_load_gts_non_object_raises(tmp_path):
    with pytest.raises(ValueError):
        load_gts(_write(tmp_path, [1, 2, 3]))


def test_load_gts_missing_file_raises(tmp_path):
    with pytest.raises(ValueError):
        load_gts(tmp_path / "does-not-exist.json")


def test_align_matches_by_index_in_sorted_order():
    preds = {2: 0.8, 0: 1.4, 1: 2.1}
    gts = {0: 1.5, 2: 1.0}  # index 1 has no GT -> dropped
    assert align_preds_gts(preds, gts) == {"preds": [1.4, 0.8], "gts": [1.5, 1.0]}


def test_align_drops_missing_pred_and_nonfinite():
    preds = {0: 1.4, 1: float("nan")}
    gts = {0: 1.5, 1: 2.0, 3: 9.0}  # 1's pred is NaN; 3 has no pred
    assert align_preds_gts(preds, gts) == {"preds": [1.4], "gts": [1.5]}
