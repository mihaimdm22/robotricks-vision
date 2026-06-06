"""CatRanger training subpackage — the optional, time-boxed fine-tune stretch.

The pretrained baseline (yolo11s.pt) is always the safety net; nothing in here is
required to run the demo. Three stages, one file each, all driven by configs/train.yaml:

    python -m catranger.train.prepare      --config configs/train.yaml   # get + format a cat dataset
    python -m catranger.train.train        --config configs/train.yaml   # fine-tune, one frozen metric
    python -m catranger.train.autoresearch --config configs/train.yaml   # keep/reject hyperparam loop

Karpathy discipline: one file, one frozen metric (val mAP50-95), deterministic seed,
surgical changes, a frozen eval the keep/reject loop optimizes. See program.md.

All heavy deps (ultralytics, roboflow, fiftyone) are imported lazily inside the
functions that need them, so `import catranger.train` stays light.
"""

__all__ = ["prepare", "train", "autoresearch"]
