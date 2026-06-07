"""M1 model registry: parse/validate configs/models.yaml, default selection,
and safe lookup. Pure data logic, no model loading."""

from __future__ import annotations

import textwrap
import types
from pathlib import Path

import pytest

from catranger.web.registry import ModelProfile, ModelRegistry, apply_profile

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


def test_accepted_backends_come_from_detect_no_sync_drift() -> None:
    # WS-C1 / DX#4: the registry validates against detect.py's backend registry, so the
    # two can never drift. Adding a backend in detect.py is automatically accepted here.
    from catranger.detect import backend_names

    assert backend_names() == {"yolo", "rtdetr"}


def test_listing_models_does_not_import_torch_or_ultralytics() -> None:
    # WS-C1 / Eng#8: validating + listing models must NOT pull in the heavy backends
    # (in the base env torch/ultralytics aren't installed, so an eager import would
    # raise — this asserts the lazy discipline holds).
    import sys

    import catranger.detect  # noqa: F401  (import is the thing under test)

    shipped = Path(__file__).resolve().parent.parent / "configs" / "models.yaml"
    ModelRegistry.from_yaml(shipped).list()
    assert "torch" not in sys.modules
    assert "ultralytics" not in sys.modules


def test_finetune_with_nonzero_classes_warns(tmp_path: Path) -> None:
    # WS-C4 / Eng#9: a local fine-tune paired with classes:[15] (copied from the COCO
    # baseline) would silently drop every detection — warn (never fail).
    y = textwrap.dedent(
        """
        default: ft
        models:
          - id: ft
            backend: yolo
            weights: runs/detect/train/weights/best.pt
            classes: [15]
        """
    )
    with pytest.warns(UserWarning, match="class 0"):
        ModelRegistry.from_yaml(_write(tmp_path, y))


def test_apply_profile_injects_synthetic_approach_and_profile_wins() -> None:
    # WS-C3 / DX#1: one model home. apply_profile injects the profile as a synthetic
    # approach and returns the key; the profile's weights/classes/tracker win.
    app = types.SimpleNamespace(
        raw={"detector": {"conf": 0.3, "finetuned_weights": "old"}, "tracker": {"name": "old.yaml"}}
    )
    profile = ModelProfile(
        id="m",
        name="m",
        backend="rtdetr",
        weights="runs/best.pt",
        classes=[0],
        tracker="bytetrack.yaml",
    )
    key = apply_profile(app, profile)
    assert key == "_model"
    assert app.raw["detector"]["_model"] == {"backend": "rtdetr", "weights": "runs/best.pt"}
    assert "finetuned_weights" not in app.raw["detector"]  # profile weights win
    assert app.raw["classes"] == [0]
    assert app.raw["tracker"]["name"] == "bytetrack.yaml"


def test_apply_profile_custom_key_and_no_classes_leaves_classes_untouched() -> None:
    app = types.SimpleNamespace(raw={"detector": {}})
    profile = ModelProfile(id="m", name="m", backend="yolo", weights="yolo11s.pt")  # classes=None
    key = apply_profile(app, profile, approach_key="_web")
    assert key == "_web"
    assert app.raw["detector"]["_web"]["backend"] == "yolo"
    assert "classes" not in app.raw  # untouched when the profile has none
    assert app.raw["tracker"]["name"] == "botsort.yaml"  # default tracker applied


def test_apply_profile_clears_stale_classes_on_swap() -> None:
    # Regression (review P1): the runtime reuses one AppConfig across model swaps. Switching
    # to a profile WITHOUT classes must CLEAR the prior model's filter, or it leaks and
    # silently drops every detection (zero-recall).
    app = types.SimpleNamespace(raw={"detector": {}})
    apply_profile(app, ModelProfile(id="a", name="a", backend="yolo", weights="a.pt", classes=[15]))
    assert app.raw["classes"] == [15]
    apply_profile(app, ModelProfile(id="b", name="b", backend="yolo", weights="b.pt"))  # no classes
    assert "classes" not in app.raw  # cleared, not leaked from model "a"


def test_baseline_and_zero_class_finetune_do_not_warn(tmp_path: Path, recwarn) -> None:
    # Bare handles (baselines) and correctly-remapped fine-tunes (classes:[0]) are silent.
    y = textwrap.dedent(
        """
        default: base
        models:
          - id: base
            backend: yolo
            weights: yolo11s.pt
            classes: [15]
          - id: ft0
            backend: yolo
            weights: runs/detect/train/weights/best.pt
            classes: [0]
        """
    )
    ModelRegistry.from_yaml(_write(tmp_path, y))
    assert not [w for w in recwarn.list if "class 0" in str(w.message)]
