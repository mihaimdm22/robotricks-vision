"""Model registry: load configs/models.yaml into validated profiles for the web
Models tab to list and hot-swap.

Pure data + YAML — no model loading happens here. A profile is just the recipe
(backend + weights + classes + tracker) that the controller hands to
catranger.detect.Detector when it (lazily) builds a pipeline. "Different
datasets" = different fine-tuned best.pt weights vs the pretrained baselines.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from catranger.config import load_yaml

# Detector backends supported by catranger.detect.Detector.
_BACKENDS = {"yolo", "rtdetr"}


@dataclass(frozen=True)
class ModelProfile:
    """One selectable detector recipe."""

    id: str
    name: str
    backend: str  # "yolo" | "rtdetr"
    weights: str  # bare handle (auto-downloaded) or a path to best.pt
    classes: list[int] | None = None
    tracker: str = "botsort.yaml"
    dataset: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> ModelProfile:
        if not isinstance(d, dict):
            raise ValueError(f"model entry must be a mapping, got {type(d).__name__}")
        mid = d.get("id")
        if not mid:
            raise ValueError("model entry missing required 'id'")
        backend = d.get("backend")
        if backend not in _BACKENDS:
            raise ValueError(
                f"model {mid!r}: 'backend' must be one of {sorted(_BACKENDS)}, got {backend!r}"
            )
        weights = d.get("weights")
        if not weights:
            raise ValueError(f"model {mid!r}: missing required 'weights'")
        classes = d.get("classes")
        return cls(
            id=str(mid),
            name=str(d.get("name", mid)),
            backend=str(backend),
            weights=str(weights),
            classes=[int(c) for c in classes] if classes is not None else None,
            tracker=str(d.get("tracker", "botsort.yaml")),
            dataset=str(d.get("dataset", "")),
            notes=str(d.get("notes", "")),
        )


class ModelRegistry:
    """An ordered set of ModelProfiles with a guaranteed-present default."""

    def __init__(self, profiles: list[ModelProfile], default_id: str) -> None:
        self._profiles = list(profiles)
        self._by_id = {p.id: p for p in self._profiles}
        self._default_id = default_id

    @classmethod
    def from_yaml(cls, path: str | os.PathLike) -> ModelRegistry:
        data = load_yaml(path)
        raw = data.get("models") or []
        if not raw:
            raise ValueError(f"no models defined in registry {path!s}")
        profiles: list[ModelProfile] = []
        by_id: dict[str, ModelProfile] = {}
        for entry in raw:
            profile = ModelProfile.from_dict(entry)
            if profile.id in by_id:
                raise ValueError(f"duplicate model id {profile.id!r} in registry")
            by_id[profile.id] = profile
            profiles.append(profile)
        default_id = data.get("default") or profiles[0].id
        if default_id not in by_id:
            raise ValueError(
                f"default {default_id!r} is not a defined model id; have: {list(by_id)}"
            )
        return cls(profiles, default_id)

    def list(self) -> list[ModelProfile]:
        return list(self._profiles)

    def get(self, model_id: str) -> ModelProfile:
        try:
            return self._by_id[model_id]
        except KeyError:
            raise KeyError(f"unknown model id {model_id!r}; have: {list(self._by_id)}") from None

    @property
    def default(self) -> ModelProfile:
        return self._by_id[self._default_id]
