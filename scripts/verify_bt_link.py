#!/usr/bin/env python3
"""Quick HC-05/HC-06 link check without the web console.

Usage (Mega on external power, USB unplugged from laptop, HC-06 connected in macOS BT):

    python scripts/verify_bt_link.py --port /dev/cu.HC-06 --baud 9600

Pass: sees optional boot line ``CR BT ready`` and streaming ``D <cm>`` telemetry.
Fail: no bytes — fix wiring/power before using the console.
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("pyserial required: uv pip install pyserial", file=sys.stderr)
    raise SystemExit(1)

from catranger.hw.serial_port import open_serial_port


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="e.g. /dev/cu.HC-06 on macOS")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument(
        "--telemetry-port",
        default=None,
        help="USB port for D lines when BT RX is silent (macOS HC-06)",
    )
    p.add_argument("--seconds", type=float, default=5.0, help="listen window")
    args = p.parse_args()

    print(f"Opening {args.port} @ {args.baud} …")
    if args.telemetry_port:
        print(f"Telemetry sidecar: {args.telemetry_port} (hybrid macOS mode)")
    print(
        "Note: HC-06 allows one link — close Serial Bluetooth Terminal on the phone "
        "and disconnect phone BT to HC-06 before testing from the Mac."
    )
    try:
        if args.telemetry_port:
            from catranger.hw.char_bridge import CharBridge

            bridge = CharBridge(port=args.port, baud=args.baud, telemetry_port=args.telemetry_port)
            deadline = time.monotonic() + args.seconds
            d_lines: list[str] = []
            boot = False
            print(f"Listening {args.seconds:.0f}s on USB telemetry …")
            while time.monotonic() < deadline:
                cm = bridge.read_distance_cm()
                if cm is not None:
                    d_lines.append(f"D {cm}")
                time.sleep(0.05)
            bridge.close()
            if d_lines:
                print(f"PASS (hybrid): {len(d_lines)} D sample(s); last: {d_lines[-1]}")
                return 0
            print("FAIL (hybrid): USB sidecar saw no D lines.")
            return 1

        ser = open_serial_port(args.port, args.baud)
    except serial.SerialException as e:
        print(f"FAIL: could not open port: {e}")
        print("Hint: pair HC-06 in System Settings → Bluetooth, click Connect, then retry.")
        return 1

    # Listen first (phone terminal apps don't flush the port on open).
    listen_first = 2.0
    deadline = time.monotonic() + listen_first
    raw = b""
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            raw += chunk

    if not raw:
        ser.write(b"b")  # manual mode bootstrap if still silent

    deadline = time.monotonic() + args.seconds
    d_lines: list[str] = []
    boot = False

    print(f"Listening {args.seconds:.0f}s (expect CR BT ready + D lines) …")
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            raw += chunk
            while b"\n" in raw:
                line, raw = raw.split(b"\n", 1)
                text = line.decode("ascii", errors="replace").strip()
                if not text:
                    continue
                print(f"  << {text}")
                if text == "CR BT ready":
                    boot = True
                if text.startswith("D "):
                    d_lines.append(text)

    ser.close()

    if d_lines:
        print(f"PASS: {len(d_lines)} D telemetry line(s); last: {d_lines[-1]}")
        if boot:
            print("      Boot banner seen — BT UART path is alive.")
        return 0

    if boot:
        print("PARTIAL: boot banner only, no D telemetry yet — check sonar / firmware.")
        return 1

    print("FAIL: 0 bytes from Mega on this port.")
    print(
        "Checklist: (1) Mega MUST be powered — plug USB into Mac or use barrel "
        "battery (unplugging USB kills the board without external supply). "
        "(2) LCD shows Gata, HC-06 LED solid red. (3) Phone BT terminal fully "
        "quit — HC-06 allows one link. (4) If phone shows D129 but Mac never "
        "does, macOS SPP may be the limit — use USB in the console for control, "
        "or swap HC-06 for an HM-10 BLE module."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
