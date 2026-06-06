#!/usr/bin/env python3
"""Bench test the robot link (Bluetooth HC-05 / BLE / USB) WITHOUT the camera or ML.

Use this first when wiring up the Arduino: it confirms pairing, the serial/BLE link,
the `C dx dy rot pan` -> `D <cm>` protocol, the servo, and the HC-SR04 stream.

    # HC-05 (ZS-040, Bluetooth Classic) — pair it first, then:
    python scripts/test_link.py --connection bt --hw-port /dev/cu.HC-05-DevB --baud 9600

    # HM-10 (BLE):
    python scripts/test_link.py --connection ble --ble <BLE-ADDRESS>

    # USB cable:
    python scripts/test_link.py --connection usb --hw-port /dev/ttyACM0

By default it ONLY sweeps the camera servo and prints the HC-SR04 distance (no motor
movement — safe on a bench). Add --drive to also pulse the wheels briefly.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catranger.hw.bluetooth import open_link  # noqa: E402
from catranger.types import Command  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="CatRanger robot-link bench test")
    ap.add_argument("--connection", default="auto", choices=["auto", "usb", "bt", "ble", "dummy"])
    ap.add_argument("--hw-port", default=None, help="serial / Bluetooth-SPP port")
    ap.add_argument("--ble", default=None, help="BLE address (HM-10)")
    ap.add_argument("--baud", type=int, default=9600, help="serial baud (HC-05 SPP = 9600)")
    ap.add_argument("--seconds", type=float, default=10.0, help="how long to run")
    ap.add_argument("--drive", action="store_true", help="ALSO pulse the wheels (robot will MOVE)")
    args = ap.parse_args()

    target = args.ble or args.hw_port
    conn = args.connection
    if conn == "auto":
        conn = "ble" if args.ble else ("usb" if args.hw_port else "dummy")

    link = open_link(conn, target, baud=args.baud)
    print(f"[link] {type(link).__name__} connection={conn} target={target}")
    if type(link).__name__ == "DummyBridge":
        print("[link] NOTE: no real hardware — this is a dry run (commands printed, no device).")

    # a gentle scripted sequence: center -> pan left -> pan right -> center.
    # pan is Command.dy in [-1,1] -> servo [0,180]. v_fwd stays 0 unless --drive.
    t0 = time.perf_counter()
    last_print = 0.0
    seq = [(-1.0, "pan left"), (0.0, "center"), (1.0, "pan right"), (0.0, "center")]
    i = 0
    while time.perf_counter() - t0 < args.seconds:
        pan, label = seq[i % len(seq)]
        v = 0.0
        if args.drive and (i % len(seq)) in (1, 3):
            v = 0.25  # brief forward nudge on the 'center' steps only
        cmd = Command(dy=pan, v_fwd=v, rotation=0.0, state="TRACK")
        wire = link.send(cmd)
        cm = link.read_distance_cm()
        now = time.perf_counter()
        if now - last_print > 0.5:
            print(
                f"  t={now - t0:4.1f}s  sent {wire.strip():18s}  distance={cm if cm is not None else '--'} cm  [{label}]"
            )
            last_print = now
        time.sleep(0.5)
        i += 1

    # always stop + center on exit
    link.send(Command(dy=0.0, v_fwd=0.0, rotation=0.0, state="SAFE"))
    if hasattr(link, "close"):
        link.close()
    print("[link] done (stopped + centered).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
