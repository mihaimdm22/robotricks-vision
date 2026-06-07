"""`catranger` CLI — thin dispatcher over the modules. argparse only (no extra deps).

catranger doctor                 # check env: which backends import, GPU, configs
catranger info  [--config ...]   # print the resolved task + camera config
catranger demo  -- <demo args>   # forwards to scripts/demo.py
catranger serve [--config web] [--host H] [--port P]   # web control panel
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


def cmd_serve(args) -> None:
    # The web UI is optional: lazy-import so `catranger --help` works without it.
    try:
        import uvicorn
    except Exception:
        print(
            "the web control panel needs the 'web' extra (and 'ml' for cat detection):\n"
            "    uv sync --extra ml --extra web"
        )
        raise SystemExit(1) from None

    import socket

    from catranger.config import load_yaml
    from catranger.web.runtime import RobotRuntime
    from catranger.web.server import create_app

    cfg = load_yaml(args.config) if args.config else {}
    host = args.host or cfg.get("host", "0.0.0.0")
    port = int(args.port or cfg.get("port", 8080))

    # Preflight the port so the operator gets problem+fix, not a traceback.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("" if host == "0.0.0.0" else host, port))
    except OSError:
        print(f"port {port} is already in use — choose another with --port, or stop that process")
        raise SystemExit(1) from None
    finally:
        probe.close()

    runtime = RobotRuntime(cfg)
    if not runtime.perception_available:
        print(
            "[catranger] note: cat detection needs the 'ml' extra (uv sync --extra ml). "
            "Running in teleop + video mode (manual drive works, no detection)."
        )
    app = create_app(runtime)
    from catranger.web.server import _console_url

    console = _console_url(cfg)
    bind = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"[catranger] API + legacy panel: http://{bind}:{port}/")
    print(f"[catranger] full console (Cats tab): {console}")
    print("  run `make web` to start the Next.js dev server if it is not already up")
    uvicorn.run(app, host=host, port=port, log_level="info")


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

    p_serve = sub.add_parser("serve", help="launch the web control panel")
    p_serve.add_argument("--config", default="web", help="web config (configs/web.yaml)")
    p_serve.add_argument("--host", default=None, help="override bind host (default from web.yaml)")
    p_serve.add_argument(
        "--port", default=None, type=int, help="override port (default from web.yaml)"
    )
    p_serve.set_defaults(fn=cmd_serve)

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
