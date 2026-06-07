#!/usr/bin/env python3
"""Exhaustive macOS HC-06 SPP diagnostics — run with phone BT terminal quit."""

from __future__ import annotations

import glob
import os
import subprocess
import time

try:
    import serial
except ImportError:
    print("need pyserial")
    raise SystemExit(1)


def ports() -> list[str]:
    return sorted(p for p in glob.glob("/dev/cu.*") if "hc" in p.lower() or "HC" in p)


def sniff(label: str, open_fn, seconds: float = 4.0) -> tuple[int, bytes]:
    ser = open_fn()
    try:
        time.sleep(0.3)
        raw = b""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                n = ser.in_waiting
            except Exception:
                n = 0
            if n:
                raw += ser.read(n)
            else:
                time.sleep(0.02)
        return len(raw), raw[:200]
    finally:
        try:
            ser.close()
        except Exception:
            pass


def main() -> int:
    candidates = ports()
    if not candidates:
        print("No /dev/cu.*HC* ports — pair HC-06 in System Settings first.")
        return 1

    print("HC-06 candidate ports:", candidates)
    for port in candidates:
        print(f"\n=== {port} ===")

        def default_open(p=port):
            return serial.Serial(p, 9600, timeout=0, dsrdtr=False, rtscts=False)

        def exclusive_false(p=port):
            return serial.Serial(p, 9600, timeout=0, dsrdtr=False, rtscts=False, exclusive=False)

        def dtr_rts_low(p=port):
            s = serial.Serial(p, 9600, timeout=0, dsrdtr=False, rtscts=False)
            s.dtr = False
            s.rts = False
            time.sleep(1.0)
            return s

        def os_open(p=port):
            fd = os.open(p, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            # Wrap fd in pyserial for read API
            s = serial.Serial()
            s.port = p
            s.baudrate = 9600
            s.timeout = 0
            s._port_handle = fd  # type: ignore[attr-defined]
            s.is_open = True
            return s

        for name, fn in [
            ("pyserial default", default_open),
            ("exclusive=False", exclusive_false),
            ("dtr/rts low + 1s settle", dtr_rts_low),
        ]:
            try:
                n, sample = sniff(name, fn, 3.0)
                print(f"  [{name}] rx={n} bytes sample={sample!r}")
            except Exception as e:
                print(f"  [{name}] ERROR: {e}")

        # TX probe: send 'b', see if USB mirror shows Comanda on Mega (user may have USB)
        try:
            s = serial.Serial(port, 9600, timeout=0, dsrdtr=False, rtscts=False)
            s.dtr = False
            s.rts = False
            time.sleep(0.8)
            s.write(b"b")
            s.flush()
            time.sleep(0.5)
            rx = b""
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if s.in_waiting:
                    rx += s.read(s.in_waiting)
                time.sleep(0.02)
            print(f"  [tx b] rx after write={len(rx)} {rx[:120]!r}")
            s.close()
        except Exception as e:
            print(f"  [tx b] ERROR: {e}")

    # Try osascript connect (best-effort)
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "Run Bluetooth Connect on HC-06 if LED blinks"',
            ],
            check=False,
        )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
