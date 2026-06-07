#!/usr/bin/env python3
"""Pre-fetch detector weights so the demo runs with no network (M5).

Triggers ultralytics to download the model-registry's YOLO and RT-DETR weights into its
local cache. We never commit `*.pt` — they're gitignored and blocked by the
>512 KB pre-commit hook — so "offline" means "warm the cache", not "vendor a
binary". Run once while online; afterwards `catranger serve` boots offline.

    python scripts/fetch_weights.py
    make fetch-weights
"""

from __future__ import annotations


def main() -> int:
    try:
        from ultralytics import YOLO
    except Exception:
        print("[weights] ultralytics not installed — run: uv sync --extra ml")
        return 1

    from ultralytics import RTDETR

    from catranger.web.registry import ModelRegistry

    reg = ModelRegistry.from_yaml("configs/models.yaml")
    warmed = 0
    for profile in reg.list():
        try:
            if profile.backend == "yolo":
                YOLO(profile.weights)  # downloads into the ultralytics cache if absent
            elif profile.backend == "rtdetr":
                RTDETR(profile.weights)
            else:
                print(f"[weights] skip: {profile.id} (backend {profile.backend!r})")
                continue
            print(f"[weights] ok: {profile.id} ({profile.weights})")
            warmed += 1
        except Exception as exc:
            print(f"[weights] FAILED {profile.id}: {type(exc).__name__}: {exc}")
    print(f"[weights] warmed {warmed} model(s); the demo can now boot offline")
    return 0 if warmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
