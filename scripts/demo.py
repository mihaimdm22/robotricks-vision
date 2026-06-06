#!/usr/bin/env python3
"""CatRanger end-to-end demo: detect + track a cat, say how far it is, optionally
follow it with the robot.

Examples:
    # on the provided Go2 stills (how_far inference set)
    python scripts/demo.py --source ~/Downloads/inference_sets_contest/how_far --save outputs/how_far_demo

    # on a video / webcam / Tapo RTSP
    python scripts/demo.py --source data/cat_demo.mp4 --approach A --show
    python scripts/demo.py --source 0 --control --hw-port /dev/ttyACM0
    python scripts/demo.py --source "rtsp://user:pass@192.168.1.50:554/stream1" --camera tapo_c211

Run from the repo root (PYTHONPATH=. handled below).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# allow running without install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from catranger.config import load_app, load_camera  # noqa: E402
from catranger.io import frame_source  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="CatRanger demo")
    p.add_argument(
        "--source", required=True, help="image dir | image | video | rtsp url | webcam index"
    )
    p.add_argument("--config", default="cat_distance", help="task config (configs/<name>.yaml)")
    p.add_argument("--camera", default=None, help="override camera config (e.g. tapo_c211)")
    p.add_argument("--approach", default="A", choices=["A", "B"], help="A=YOLO11, B=RT-DETR")
    p.add_argument(
        "--classes",
        default=None,
        help="override detected classes: 'all', or comma-sep COCO ids (e.g. 15 for cat, '0,56' people+chairs)",
    )
    p.add_argument(
        "--no-depth", action="store_true", help="disable the depth network (geometry only)"
    )
    p.add_argument("--control", action="store_true", help="run the follow controller")
    # robot link: USB serial, Bluetooth-SPP (HC-05 = a serial port), or BLE (HM-10)
    p.add_argument(
        "--hw-port",
        default=None,
        help="Arduino link: USB serial (/dev/ttyACM0) or Bluetooth-SPP port (/dev/cu.HC-05...)",
    )
    p.add_argument(
        "--ble",
        default=None,
        help="BLE address of an HM-10-style module (enables robot output over BLE)",
    )
    p.add_argument(
        "--connection",
        default="auto",
        choices=["auto", "usb", "bt", "ble", "dummy"],
        help="robot transport. 'bt'=HC-05 SPP serial (9600 baud), 'ble'=HM-10",
    )
    p.add_argument(
        "--baud", type=int, default=115200, help="serial baud (USB 115200; HC-05 SPP usually 9600)"
    )
    p.add_argument("--device", default=None, help="cuda | cpu | cuda:0")
    p.add_argument("--save", default=None, help="output dir/prefix for annotated frames/video")
    p.add_argument("--show", action="store_true", help="display a live window")
    p.add_argument("--stride", type=int, default=1, help="frame stride (video/stream)")
    p.add_argument("--max-frames", type=int, default=0, help="cap frames (0=all)")
    p.add_argument("--print-json", action="store_true", help="print per-frame JSON to stdout")
    return p.parse_args()


def main():
    args = parse_args()

    # lazy imports of the heavy pipeline so --help works without torch installed
    from catranger.pipeline import CatRanger
    from catranger.viz import draw

    app = load_app(args.config)
    if args.camera:
        app.camera = load_camera(args.camera)
    if args.classes is not None:
        app.raw["classes"] = (
            None
            if args.classes.lower() == "all"
            else [int(c) for c in args.classes.split(",") if c.strip()]
        )

    approach = "approach_a" if args.approach == "A" else "approach_b"
    ranger = CatRanger(app, approach=approach, use_depth=not args.no_depth, device=args.device)

    # resolve the robot link: --ble wins, else --hw-port (USB or BT-SPP), else none
    link_target = args.ble or args.hw_port
    connection = args.connection
    if connection == "auto":
        connection = "ble" if args.ble else ("usb" if args.hw_port else "dummy")

    follower = None
    if args.control or link_target:
        from catranger.control import Follower

        follower = Follower(app.get("follow", default={}))

    bridge = None
    if link_target:
        from catranger.hw.bluetooth import open_link

        bridge = open_link(connection, link_target, baud=args.baud)
        print(
            f"[catranger] robot link: connection={connection} target={link_target} "
            f"({type(bridge).__name__})"
        )

    writer = None
    save_dir = None
    if args.save:
        save_dir = Path(args.save)
        save_dir.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"[catranger] camera={app.camera.name} approach={approach} "
        f"depth={'off' if args.no_depth else 'on'} control={bool(follower)} hw={bool(bridge)}"
    )

    t_start = time.perf_counter()
    n = 0
    for idx, frame in frame_source(args.source, stride=args.stride, max_frames=args.max_frames):
        result = ranger.process(frame, frame_index=idx)
        command = None
        if follower is not None:
            command = follower.step(result)
            if bridge is not None:
                bridge.send(command)

        annotated = draw(
            ranger.last_undistorted if hasattr(ranger, "last_undistorted") else frame,
            result,
            command,
        )

        # report line
        tgt = result.target
        if tgt and tgt.distance:
            print(
                f"frame {idx:4d} | {len(result.observations)} cat(s) | "
                f"target id={tgt.track_id} dist={tgt.distance.meters:.2f}m "
                f"(+/-{tgt.distance.half_width:.2f}) bearing={tgt.bearing_deg:+.1f} | {result.fps:.1f} FPS"
                + (
                    f" | cmd={command.state} rot={command.rotation:+.2f} v={command.v_fwd:+.2f}"
                    if command
                    else ""
                )
            )
        if args.print_json:
            print(
                json.dumps(
                    {
                        "frame": idx,
                        "observations": [
                            {
                                "id": o.track_id,
                                "dist_m": round(o.distance.meters, 3) if o.distance else None,
                                "bearing_deg": round(o.bearing_deg, 1),
                            }
                            for o in result.observations
                        ],
                        "command": command.as_dict() if command else None,
                    }
                )
            )

        if save_dir is not None:
            if (
                str(args.source).isdigit()
                or "://" in str(args.source)
                or Path(str(args.source)).suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}
            ):
                if writer is None:
                    h, w = annotated.shape[:2]
                    writer = cv2.VideoWriter(
                        str(save_dir) + ".mp4", cv2.VideoWriter_fourcc(*"mp4v"), 15, (w, h)
                    )
                writer.write(annotated)
            else:
                save_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(save_dir / f"frame_{idx:04d}.jpg"), annotated)

        if args.show:
            cv2.imshow("catranger", annotated)
            if cv2.waitKey(1) == 27:
                break
        n += 1

    dt = time.perf_counter() - t_start
    if writer is not None:
        writer.release()
    if bridge is not None and hasattr(bridge, "close"):
        bridge.close()
    if args.show:
        cv2.destroyAllWindows()
    print(f"[catranger] done: {n} frames in {dt:.1f}s ({n / dt if dt else 0:.1f} FPS avg)")


if __name__ == "__main__":
    main()
