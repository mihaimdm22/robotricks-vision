"""Model registry: load configs/models.yaml into validated profiles for the web
Models tab to list and hot-swap.

Pure data + YAML — no model loading happens here. A profile is just the recipe
(backend + weights + classes + tracker) that the controller hands to
catranger.detect.Detector when it (lazily) builds a pipeline. "Different
datasets" = different fine-tuned best.pt weights vs the pretrained baselines.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from typing import Any

from catranger.config import load_yaml
from catranger.detect import backend_names

# Supported detector backends come from catranger.detect (the single source of truth),
# so adding a backend there is automatically accepted here — no second list to keep in
# sync. Importing detect is light (numpy + types only); it never pulls in torch.


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
        allowed = sorted(backend_names())
        if backend not in allowed:
            raise ValueError(f"model {mid!r}: 'backend' must be one of {allowed}, got {backend!r}")
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


def _warn_class_id_drift(profile: ModelProfile) -> None:
    """Warn (never fail — WS-C5 doctrine) when a local fine-tune is paired with a
    non-zero class filter. A single-class fine-tune usually remaps cat -> class 0, so a
    classes:[15] copied from the COCO baseline would make detect.py's class filter drop
    every detection — a silent zero-recall failure. Bare auto-download handles
    (yolo11s.pt) are baselines and never warned."""
    w = profile.weights
    looks_local = "/" in w or "\\" in w or w.endswith("best.pt")
    if looks_local and profile.classes and 0 not in profile.classes:
        warnings.warn(
            f"model {profile.id!r}: fine-tuned weights {w!r} with classes={profile.classes} "
            "(no 0). A single-class fine-tune usually remaps cat -> class 0; if detections "
            "vanish, set classes: [0] in configs/models.yaml.",
            stacklevel=2,
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
            _warn_class_id_drift(profile)
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


def apply_profile(app: Any, profile: ModelProfile, *, approach_key: str = "_model") -> str:
    """Inject a ModelProfile into an AppConfig as a synthetic detector approach and
    return the approach key to pass to ``CatRanger(approach=...)`` (WS-C3, DX#1).

    This is the ONE model home: the web Models tab, ``demo --model``, and
    ``eval --model`` all build the pipeline from configs/models.yaml the same way, so a
    fine-tune added to the registry is visible to both the CLI and the console.

    DESTRUCTIVE: mutates ``app.raw`` in place. The web runtime reuses ONE cached AppConfig
    across model swaps, so every field a profile can set must be FULLY reflected here —
    including CLEARING ``classes`` when the new profile has none, or a prior model's filter
    leaks and silently drops every detection. CLI callers (demo/eval) use a fresh
    ``load_app`` per process. Never imports the (heavy) pipeline."""
    det = dict(app.raw.get("detector", {}) or {})
    det.pop("finetuned_weights", None)  # the profile's weights win
    det[approach_key] = {"backend": profile.backend, "weights": profile.weights}
    app.raw["detector"] = det
    # Always reflect the profile: set the filter, or CLEAR a stale one from a prior swap.
    if profile.classes is not None:
        app.raw["classes"] = list(profile.classes)
    else:
        app.raw.pop("classes", None)
    if profile.tracker:
        tracker = dict(app.raw.get("tracker", {}) or {})
        tracker["name"] = profile.tracker
        app.raw["tracker"] = tracker
    return approach_key
