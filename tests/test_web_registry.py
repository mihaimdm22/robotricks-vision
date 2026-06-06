"""M1 model registry: parse/validate configs/models.yaml, default selection,
and safe lookup. Pure data logic, no model loading."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from catranger.web.registry import ModelProfile, ModelRegistry

_VALID = textwrap.dedent(
    """
    default: yolo11s
    models:
      - id: yolo11s
        name: "YOLO11s (COCO pretrained)"
        backend: yolo
        weights: yolo11s.pt
        classes: [15]
        tracker: botsort.yaml
        dataset: "COCO (pretrained)"
        notes: "Baseline."
      - id: rtdetr-l
        name: "RT-DETR-L"
        backend: rtdetr
        weights: rtdetr-l.pt
        classes: [15]
        tracker: botsort.yaml
        dataset: "COCO (pretrained)"
        notes: "Transformer."
    """
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "models.yaml"
    p.write_text(text)
    return p


def test_parses_valid_registry_and_lists_profiles(tmp_path: Path) -> None:
    reg = ModelRegistry.from_yaml(_write(tmp_path, _VALID))
    ids = [m.id for m in reg.list()]
    assert ids == ["yolo11s", "rtdetr-l"]
    assert all(isinstance(m, ModelProfile) for m in reg.list())


def test_default_resolves_to_the_named_profile(tmp_path: Path) -> None:
    reg = ModelRegistry.from_yaml(_write(tmp_path, _VALID))
    assert reg.default.id == "yolo11s"
    assert reg.default.backend == "yolo"


def test_get_returns_the_requested_profile(tmp_path: Path) -> None:
    reg = ModelRegistry.from_yaml(_write(tmp_path, _VALID))
    assert reg.get("rtdetr-l").backend == "rtdetr"


def test_unknown_id_raises_keyerror_with_a_helpful_message(tmp_path: Path) -> None:
    reg = ModelRegistry.from_yaml(_write(tmp_path, _VALID))
    with pytest.raises(KeyError, match="nope"):
        reg.get("nope")


def test_malformed_profile_missing_backend_is_rejected(tmp_path: Path) -> None:
    bad = textwrap.dedent(
        """
        default: x
        models:
          - id: x
            weights: x.pt
        """
    )
    with pytest.raises(ValueError, match="backend"):
        ModelRegistry.from_yaml(_write(tmp_path, bad))


def test_bad_backend_value_is_rejected(tmp_path: Path) -> None:
    bad = textwrap.dedent(
        """
        default: x
        models:
          - id: x
            backend: tensorflow
            weights: x.pt
        """
    )
    with pytest.raises(ValueError, match="backend"):
        ModelRegistry.from_yaml(_write(tmp_path, bad))


def test_malformed_profile_missing_weights_is_rejected(tmp_path: Path) -> None:
    bad = textwrap.dedent(
        """
        default: x
        models:
          - id: x
            backend: yolo
        """
    )
    with pytest.raises(ValueError, match="weights"):
        ModelRegistry.from_yaml(_write(tmp_path, bad))


def test_duplicate_model_id_is_rejected(tmp_path: Path) -> None:
    bad = textwrap.dedent(
        """
        default: dup
        models:
          - id: dup
            backend: yolo
            weights: a.pt
          - id: dup
            backend: rtdetr
            weights: b.pt
        """
    )
    with pytest.raises(ValueError, match="duplicate"):
        ModelRegistry.from_yaml(_write(tmp_path, bad))


def test_default_must_reference_an_existing_model(tmp_path: Path) -> None:
    bad = textwrap.dedent(
        """
        default: ghost
        models:
          - id: real
            backend: yolo
            weights: real.pt
        """
    )
    with pytest.raises(ValueError, match="default"):
        ModelRegistry.from_yaml(_write(tmp_path, bad))


def test_empty_registry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="(?i)no models"):
        ModelRegistry.from_yaml(_write(tmp_path, "models: []\n"))


def test_the_shipped_registry_loads_and_baseline_is_first(tmp_path: Path) -> None:
    """The committed configs/models.yaml must be valid and lead with the baseline."""
    shipped = Path(__file__).resolve().parent.parent / "configs" / "models.yaml"
    reg = ModelRegistry.from_yaml(shipped)
    assert reg.list(), "shipped registry is empty"
    assert reg.default.backend == "yolo"  # the always-available COCO baseline
