"""Tests for the shared promote logic (catranger.train.promote).

Promote edits the perception core's config (cat_distance.yaml), so the write must
be atomic + comment-preserving and the models.yaml upsert must produce a profile
the registry can load. These guard the "baseline always runs" rule.
"""

from __future__ import annotations

import yaml

from catranger.train import promote
from catranger.web.registry import ModelRegistry


def test_set_finetuned_weights_preserves_comments(tmp_path) -> None:
    cfg = tmp_path / "cat_distance.yaml"
    cfg.write_text("detector:\n  finetuned_weights: null   # keep this comment\n", encoding="utf-8")
    assert promote.set_finetuned_weights("runs/train/best.pt", config_path=cfg) is True
    text = cfg.read_text(encoding="utf-8")
    assert "finetuned_weights: runs/train/best.pt" in text
    # revert round-trips back to baseline
    assert promote.set_finetuned_weights("null", config_path=cfg) is True
    assert "finetuned_weights: null" in cfg.read_text(encoding="utf-8")


def test_set_finetuned_weights_missing_line_raises(tmp_path) -> None:
    cfg = tmp_path / "cat_distance.yaml"
    cfg.write_text("detector:\n  conf: 0.35\n", encoding="utf-8")
    try:
        promote.set_finetuned_weights("x", config_path=cfg)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_upsert_model_profile_is_loadable(tmp_path) -> None:
    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {
                "default": "yolo11s",
                "models": [
                    {"id": "yolo11s", "name": "base", "backend": "yolo", "weights": "yolo11s.pt"}
                ],
            }
        ),
        encoding="utf-8",
    )
    promote.upsert_model_profile(
        {
            "id": "cats-finetuned",
            "name": "FT",
            "backend": "yolo",
            "weights": "best.pt",
            "classes": [0],
        },
        config_path=models,
    )
    reg = ModelRegistry.from_yaml(models)
    assert {p.id for p in reg.list()} == {"yolo11s", "cats-finetuned"}
    # upsert again with same id replaces (no duplicate -> registry would raise on dup)
    promote.upsert_model_profile(
        {"id": "cats-finetuned", "name": "FT2", "backend": "yolo", "weights": "best2.pt"},
        config_path=models,
    )
    reg2 = ModelRegistry.from_yaml(models)
    assert reg2.get("cats-finetuned").weights == "best2.pt"


def test_read_winner_missing_is_none(tmp_path) -> None:
    assert promote.read_winner(tmp_path / "nope.json") is None
