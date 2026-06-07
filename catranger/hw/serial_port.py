"""Serial port open helpers — especially HC-05/HC-06 on macOS.

Phone terminal apps often open SPP without toggling DTR/RTS. pyserial defaults can
reset or confuse some HC-06 modules when the Mac opens ``/dev/cu.HC-06``.
"""

from __future__ import annotations

import time
from typing import Any


def is_bluetooth_spp_port(port: str | None) -> bool:
    if not port:
        return False
    low = port.lower()
    if "bluetooth-incoming" in low:
        return False
    markers = ("hc-05", "hc-06", "hc05", "hc06", "rnbt", "rfcomm", "devb")
    return any(m in low for m in markers)


def open_serial_port(port: str, baud: int, *, bluetooth_spp: bool | None = None) -> Any:
    """Open a pyserial handle. ``bluetooth_spp`` defaults from the port name."""
    import serial

    spp = is_bluetooth_spp_port(port) if bluetooth_spp is None else bluetooth_spp
    if spp:
        ser = serial.Serial(
            port,
            baud,
            timeout=0,
            dsrdtr=False,
            rtscts=False,
        )
        # Match typical phone terminal behaviour — avoid reset pulses on open.
        ser.dtr = False
        ser.rts = False
        # Let the RF link come up; do NOT reset_input_buffer on macOS SPP — some
        # stacks never deliver bytes after a flush (phone terminal apps don't flush).
        time.sleep(0.6)
        return ser
    return serial.Serial(port, baud, timeout=0)
