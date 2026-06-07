"""WS-C2 dataset registry: parse/validate configs/datasets.yaml, default selection,
safe lookup, and no source-name drift vs catranger.train.prepare. Pure data logic."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from catranger.datasets import DatasetProfile, DatasetRegistry

_VALID = textwrap.dedent(
    """
    default: manual
    datasets:
      - id: manual
        name: "Manual scaffold"
        source: manual
        notes: "no download"
      - id: oi
        name: "Open Images Cat"
        source: openimages
        params:
          classes: ["Cat"]
          max_samples: 100
    """
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "datasets.yaml"
    p.write_text(text)
    return p


def test_parses_valid_registry_and_lists_profiles(tmp_path: Path) -> None:
    reg = DatasetRegistry.from_yaml(_write(tmp_path, _VALID))
    assert [d.id for d in reg.list()] == ["manual", "oi"]
    assert all(isinstance(d, DatasetProfile) for d in reg.list())
    assert reg.get("oi").params == {"classes": ["Cat"], "max_samples": 100}


def test_default_resolves(tmp_path: Path) -> None:
    reg = DatasetRegistry.from_yaml(_write(tmp_path, _VALID))
    assert reg.default.id == "manual" and reg.default.source == "manual"


def test_unknown_id_raises_keyerror(tmp_path: Path) -> None:
    reg = DatasetRegistry.from_yaml(_write(tmp_path, _VALID))
    with pytest.raises(KeyError, match="nope"):
        reg.get("nope")


def test_missing_id_rejected(tmp_path: Path) -> None:
    bad = "datasets:\n  - source: manual\n"
    with pytest.raises(ValueError, match="id"):
        DatasetRegistry.from_yaml(_write(tmp_path, bad))


def test_bad_source_rejected(tmp_path: Path) -> None:
    bad = "datasets:\n  - id: x\n    source: kaggle\n"
    with pytest.raises(ValueError, match="source"):
        DatasetRegistry.from_yaml(_write(tmp_path, bad))


def test_bad_params_type_rejected(tmp_path: Path) -> None:
    bad = "datasets:\n  - id: x\n    source: manual\n    params: [1, 2]\n"
    with pytest.raises(ValueError, match="params"):
        DatasetRegistry.from_yaml(_write(tmp_path, bad))


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    bad = textwrap.dedent(
        """
        datasets:
          - id: dup
            source: manual
          - id: dup
            source: openimages
        """
    )
    with pytest.raises(ValueError, match="duplicate"):
        DatasetRegistry.from_yaml(_write(tmp_path, bad))


def test_default_must_exist(tmp_path: Path) -> None:
    bad = "default: ghost\ndatasets:\n  - id: real\n    source: manual\n"
    with pytest.raises(ValueError, match="default"):
        DatasetRegistry.from_yaml(_write(tmp_path, bad))


def test_empty_registry_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="(?i)no datasets"):
        DatasetRegistry.from_yaml(_write(tmp_path, "datasets: []\n"))


def test_sources_come_from_prepare_no_drift() -> None:
    # WS-C2: the registry validates against prepare's adapter names (single source of
    # truth), so adding a source in prepare.py is automatically accepted here.
    from catranger.train.prepare import source_names

    assert source_names() == {"roboflow", "openimages", "manual"}


def test_shipped_registry_loads(tmp_path: Path) -> None:
    shipped = Path(__file__).resolve().parent.parent / "configs" / "datasets.yaml"
    reg = DatasetRegistry.from_yaml(shipped)
    assert reg.list(), "shipped dataset registry is empty"
    assert reg.default.source in {"manual", "openimages", "roboflow"}
