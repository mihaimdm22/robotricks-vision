"""`catranger` CLI — thin dispatcher over the modules. argparse only (no extra deps).

catranger doctor                 # check env: which backends import, GPU, configs
catranger info  [--config ...]   # print the resolved task + camera config
catranger demo  -- <demo args>   # forwards to scripts/demo.py
catranger prepare [--config configs/train.yaml]
catranger train   [--config configs/train.yaml]
catranger autoresearch [--config configs/train.yaml]
"""

from __future__ import annotations

import argparse
import importlib
import runpy
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _check(mod: str) -> str:
    try:
        m = importlib.import_module(mod)
        v = getattr(m, "__version__", "")
        return f"  ok    {mod} {v}".rstrip()
    except Exception as e:  # noqa: BLE001
        return f"  MISS  {mod}  ({type(e).__name__})"


def cmd_doctor(_args) -> None:
    print("CatRanger doctor\n----------------")
    print("core:")
    for m in ("numpy", "cv2", "yaml"):
        print(_check(m))
    print("perception/depth:")
    for m in ("torch", "ultralytics", "transformers"):
        print(_check(m))
    print("training:")
    for m in ("roboflow", "fiftyone"):
        print(_check(m))
    print("hardware:")
    for m in ("serial", "pytapo"):
        print(_check(m))
    # GPU
    try:
        import torch

        print(
            f"gpu:  cuda_available={torch.cuda.is_available()} "
            f"device={torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}"
        )
    except Exception:
        print("gpu:  torch not installed")
    # configs present?
    cfgs = list((_REPO / "configs").rglob("*.yaml"))
    print(f"configs: {len(cfgs)} found under configs/")


def cmd_info(args) -> None:
    from catranger.config import load_app

    app = load_app(args.config)
    c = app.camera
    print(f"task config: {args.config}")
    print(
        f"camera: {c.name}  fx={c.fx} fy={c.fy} cx={c.cx} cy={c.cy} "
        f"{c.width}x{c.height} fov={c.fov_deg} mount={c.mount_height_m}m "
        f"{'(needs calibration)' if c.needs_calibration else ''}"
    )
    print(f"classes: {app.classes}")
    print(
        f"detector: {app.get('detector', 'default')} -> "
        f"{app.get('detector', app.get('detector', 'default') or 'approach_a')}"
    )
    print(f"tracker: {app.get('tracker', 'name')} reid={app.get('tracker', 'with_reid')}")
    print(f"depth: {app.get('depth', 'backend')} enabled={app.get('depth', 'enabled')}")
    print(f"size priors: {list(app.size_priors.keys())}")


def cmd_demo(args) -> None:
    sys.argv = ["scripts/demo.py"] + args.rest
    runpy.run_path(str(_REPO / "scripts" / "demo.py"), run_name="__main__")


def _run_module(modname: str, rest) -> None:
    sys.argv = [modname] + rest
    runpy.run_module(modname, run_name="__main__")


def cmd_prepare(args) -> None:
    _run_module("catranger.train.prepare", ["--config", args.config])


def cmd_train(args) -> None:
    _run_module("catranger.train.train", ["--config", args.config])


def cmd_autoresearch(args) -> None:
    _run_module("catranger.train.autoresearch", ["--config", args.config])


def app() -> None:
    parser = argparse.ArgumentParser(prog="catranger", description="CatRanger CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check environment / installed backends").set_defaults(
        fn=cmd_doctor
    )

    p_info = sub.add_parser("info", help="print resolved config")
    p_info.add_argument("--config", default="cat_distance")
    p_info.set_defaults(fn=cmd_info)

    p_demo = sub.add_parser("demo", help="run the demo (forwards args to scripts/demo.py)")
    p_demo.add_argument("rest", nargs=argparse.REMAINDER)
    p_demo.set_defaults(fn=cmd_demo)

    for name, fn in (
        ("prepare", cmd_prepare),
        ("train", cmd_train),
        ("autoresearch", cmd_autoresearch),
    ):
        pp = sub.add_parser(name, help=f"{name} (training pipeline)")
        pp.add_argument("--config", default="configs/train.yaml")
        pp.set_defaults(fn=fn)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    app()
