"""Serial port discovery for the web console Connections tab."""

from __future__ import annotations

import glob
import sys
from pathlib import Path
from typing import Any

_SKIP_PORT_SUBSTRINGS = (
    "bluetooth",
    "debug-console",
    "modemdebug",
    "spyglass",
)

_USB_LIKE = ("usbserial", "usbmodem", "wchusb", "ttyacm", "ttyusb", "slab_usb", "arduino")

# Classic Bluetooth SPP modules (HC-05/06) show up as /dev/cu.HC-05-* on macOS after pairing.
_BT_SPP_MARKERS = ("hc-05", "hc-06", "hc_", "rnbt", "redbear", "btspp", "serialb", "rfcomm")


def is_arduino_candidate(device: str) -> bool:
    lower = device.lower()
    return any(x in lower for x in _USB_LIKE)


def arduino_ports(ports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in ports if is_arduino_candidate(p["target"])]


def pick_usb_telemetry_port(exclude: str | None = None) -> str | None:
    """Best USB Mega port for sonar telemetry (excludes a BT SPP path)."""
    skip = (exclude or "").strip()
    for entry in arduino_ports(list_serial_ports()):
        target = str(entry.get("target") or "")
        if not target or target == skip:
            continue
        if is_bluetooth_spp_candidate(target):
            continue
        return target
    return None


def is_bluetooth_spp_candidate(device: str) -> bool:
    """True for paired HC-05/06-style SPP serial ports (not macOS junk BT ports)."""
    if _is_skipped_port(device):
        return False
    name = Path(device).name.lower()
    if "bluetooth-incoming" in name:
        return False
    return any(m in name for m in _BT_SPP_MARKERS)


def bluetooth_spp_ports(ports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in ports:
        target = p["target"]
        if not is_bluetooth_spp_candidate(target):
            continue
        label = (p.get("label") or _guess_label(target)).strip()
        lower = target.lower()
        if "hc-06" in lower:
            label = f"HC-06 Bluetooth SPP ({Path(target).name})"
        elif "hc-05" in lower:
            label = f"HC-05 Bluetooth SPP ({Path(target).name})"
        elif "rfcomm" in lower:
            label = f"Bluetooth SPP ({Path(target).name})"
        out.append({**p, "label": label, "kind": "bluetooth_spp"})
    return out


def _is_skipped_port(device: str) -> bool:
    lower = device.lower()
    return any(s in lower for s in _SKIP_PORT_SUBSTRINGS)


def _guess_label(device: str) -> str:
    name = Path(device).name.lower()
    if "usbmodem" in name:
        return f"Arduino/native USB ({Path(device).name})"
    if "usbserial" in name or "wchusb" in name:
        return f"USB serial adapter ({Path(device).name})"
    if "slab" in name:
        return f"FTDI USB ({Path(device).name})"
    if "ttyacm" in name:
        return f"ACM USB ({Path(device).name})"
    if "ttyusb" in name:
        return f"USB-UART ({Path(device).name})"
    return Path(device).name


def list_serial_ports() -> list[dict[str, Any]]:
    """Return serial ports on the host running the control server.

    Uses pyserial first, then a /dev glob fallback because macOS often exposes
    CH340/clone adapters under /dev/cu.* before list_ports picks them up.
    """
    ports: dict[str, dict[str, Any]] = {}
    try:
        from serial.tools import list_ports

        for p in list_ports.comports():
            dev = p.device
            if not dev or _is_skipped_port(dev):
                continue
            label = (p.description or "").strip()
            if p.manufacturer:
                label = f"{p.manufacturer} {label}".strip()
            if not label:
                label = _guess_label(dev)
            entry: dict[str, Any] = {
                "target": dev,
                "label": label,
                "source": "pyserial",
            }
            if p.manufacturer:
                entry["manufacturer"] = p.manufacturer
            if p.vid is not None:
                entry["vid"] = f"{p.vid:04x}"
            if p.pid is not None:
                entry["pid"] = f"{p.pid:04x}"
            ports[dev] = entry
    except Exception:
        pass

    if sys.platform == "darwin":
        patterns = ["/dev/cu.*"]
    elif sys.platform.startswith("linux"):
        patterns = ["/dev/ttyACM*", "/dev/ttyUSB*", "/dev/serial/by-id/*"]
    else:
        patterns = []

    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            if _is_skipped_port(path):
                continue
            ports.setdefault(
                path,
                {"target": path, "label": _guess_label(path), "source": "glob"},
            )

    return sorted(ports.values(), key=lambda item: item["target"])


def discover_hint(ports: list[dict[str, Any]]) -> str | None:
    usb = arduino_ports(ports)
    bt = bluetooth_spp_ports(ports)
    parts: list[str] = []
    if usb:
        parts.append(f"{len(usb)} Arduino USB port(s)")
    if bt:
        parts.append(f"{len(bt)} Bluetooth SPP port(s) (HC-05/HC-06)")
    if parts:
        return " — ".join(parts) + " on server"
    return (
        "no robot ports found. USB: plug the Mega into the Mac running catranger serve "
        "(ls /dev/cu.usbserial-* or /dev/cu.usbmodem*). Bluetooth: pair HC-05 in "
        "System Settings → Bluetooth first — then Scan should list /dev/cu.HC-05-* "
        "(not Bluetooth-Incoming-Port). HC-05 uses baud 9600."
    )
