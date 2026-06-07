"""Dataset registry (WS-C2): load configs/datasets.yaml into validated profiles, so
"add a dataset on top" is a manifest entry — not a Python edit.

Mirrors catranger.web.registry (models). A profile names a SOURCE (one of the adapters
in catranger.train.prepare — roboflow / openimages / manual) plus that source's params.
The allowed sources are read from prepare (the single source of truth), so the registry
and the adapters can never drift. Every source normalizes to the same data/cat/
Ultralytics layout (single class cat = 0).

Pure data + YAML — no dataset is downloaded here. ``catranger.train.prepare
--dataset <id>`` resolves a profile and runs its source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from catranger.config import load_yaml
from catranger.train.prepare import source_names


@dataclass(frozen=True)
class DatasetProfile:
    """One acquirable dataset recipe."""

    id: str
    name: str
    source: str  # roboflow | openimages | manual
    params: dict[str, Any] = field(default_factory=dict)  # source-specific config block
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> DatasetProfile:
        if not isinstance(d, dict):
            raise ValueError(f"dataset entry must be a mapping, got {type(d).__name__}")
        did = d.get("id")
        if not did:
            raise ValueError("dataset entry missing required 'id'")
        source = d.get("source")
        allowed = sorted(source_names())
        if source not in allowed:
            raise ValueError(f"dataset {did!r}: 'source' must be one of {allowed}, got {source!r}")
        params = d.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"dataset {did!r}: 'params' must be a mapping if present")
        return cls(
            id=str(did),
            name=str(d.get("name", did)),
            source=str(source),
            params=dict(params),
            notes=str(d.get("notes", "")),
        )


class DatasetRegistry:
    """An ordered set of DatasetProfiles with a guaranteed-present default."""

    def __init__(self, profiles: list[DatasetProfile], default_id: str) -> None:
        self._profiles = list(profiles)
        self._by_id = {p.id: p for p in self._profiles}
        self._default_id = default_id

    @classmethod
    def from_yaml(cls, path: str | os.PathLike) -> DatasetRegistry:
        data = load_yaml(path)
        raw = data.get("datasets") or []
        if not raw:
            raise ValueError(f"no datasets defined in registry {path!s}")
        profiles: list[DatasetProfile] = []
        by_id: dict[str, DatasetProfile] = {}
        for entry in raw:
            profile = DatasetProfile.from_dict(entry)
            if profile.id in by_id:
                raise ValueError(f"duplicate dataset id {profile.id!r} in registry")
            by_id[profile.id] = profile
            profiles.append(profile)
        default_id = data.get("default") or profiles[0].id
        if default_id not in by_id:
            raise ValueError(
                f"default {default_id!r} is not a defined dataset id; have: {list(by_id)}"
            )
        return cls(profiles, default_id)

    def list(self) -> list[DatasetProfile]:
        return list(self._profiles)

    def get(self, dataset_id: str) -> DatasetProfile:
        try:
            return self._by_id[dataset_id]
        except KeyError:
            raise KeyError(
                f"unknown dataset id {dataset_id!r}; have: {list(self._by_id)}"
            ) from None

    @property
    def default(self) -> DatasetProfile:
        return self._by_id[self._default_id]
