"""macOS Classic Bluetooth (HC-06) workarounds.

Investigation shows a common failure mode on macOS: ``/dev/cu.HC-06`` opens and
**TX reaches the Mega**, but **RX stays at 0 bytes** (phone Serial Terminal still
works both ways). Firmware mirrors ``D <cm>`` to USB when ``CATRANGER_POLL_USB`` is
enabled, so we can command over BT and read sonar over USB.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catranger.hw.char_bridge import CharBridge


def hybrid_telemetry_port(bt_port: str | None) -> str | None:
    """USB port for sonar lines when macOS HC-06 RX is silent."""
    if sys.platform != "darwin" or not bt_port:
        return None
    from catranger.hw.serial_discovery import pick_usb_telemetry_port

    return pick_usb_telemetry_port(exclude=bt_port)


def verify_bt_command_tx(bt_port: str, usb_echo_port: str | None, baud: int = 9600) -> bool:
    """True when a char written on the BT port shows up on USB debug (Comanda:)."""
    if not usb_echo_port:
        return False
    from catranger.hw.serial_port import open_serial_port

    usb = open_serial_port(usb_echo_port, baud, bluetooth_spp=False)
    bt = open_serial_port(bt_port, baud, bluetooth_spp=True)
    try:
        time.sleep(0.4)
        while usb.in_waiting:
            usb.read(usb.in_waiting)
        bt.write(b"b")
        bt.flush()
        time.sleep(0.5)
        buf = b""
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if usb.in_waiting:
                buf += usb.read(usb.in_waiting)
            time.sleep(0.02)
        return b"Comanda:" in buf
    finally:
        try:
            bt.close()
        except Exception:
            pass
        try:
            usb.close()
        except Exception:
            pass


def open_char_bridge_with_macos_hybrid(
    bt_port: str,
    baud: int = 9600,
) -> tuple[CharBridge, str | None]:
    """Open CharBridge on BT; auto-attach USB telemetry sidecar on macOS when needed."""
    from catranger.hw.char_bridge import CharBridge

    def _has_telemetry(bridge: CharBridge, seconds: float = 2.5) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if bridge.read_distance_cm() is not None:
                return True
            time.sleep(0.05)
        return False

    bridge = CharBridge(port=bt_port, baud=baud)
    if _has_telemetry(bridge):
        return bridge, None

    telem = hybrid_telemetry_port(bt_port)
    if not telem:
        return bridge, None

    bridge.close()
    bridge = CharBridge(port=bt_port, baud=baud, telemetry_port=telem)
    return bridge, telem
