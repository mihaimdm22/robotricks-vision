"""Bluetooth link to the Arduino chassis. Two flavours, same `C dx dy rot pan` /
`D <cm>` protocol as the USB bridge (encode() is shared with serial_bridge.py):

  1) CLASSIC Bluetooth (HC-05 / HC-06, SPP). The OS exposes the paired module as a
     plain serial port, so the existing ArduinoBridge works UNCHANGED — just give it
     the Bluetooth serial device instead of the USB one:
         macOS :  /dev/cu.HC-05-DevB        (or whatever you named it)
         Linux :  /dev/rfcomm0              (after `rfcomm bind`)
     Note HC-05's factory SPP baud is 9600, not 115200 — pass baud=9600 unless you
     reconfigured it via AT commands. `list_bt_serial_ports()` helps you find it.

  2) BLE (HM-10 / HM-19 / AT-09 / JDY-08, transparent UART). No serial port; the host
     talks GATT. `BLEBridge` (below) connects with `bleak` and writes/notifies on the
     module's UART characteristic (default FFE1, the HM-10 family). The Arduino side is
     IDENTICAL to the Classic case — the module bridges BLE<->UART transparently, so the
     sketch still just reads Serial1.

Use `open_link(...)` as the single entry point; it returns something with the same
send / read_distance_cm / close interface as DummyBridge, so callers never branch.
"""

from __future__ import annotations

import glob
import sys
import threading
from typing import Any

from catranger.hw.serial_bridge import ArduinoBridge, DummyBridge, encode
from catranger.types import Command

# HM-10 / HM-19 / AT-09 family expose a single transparent-UART characteristic.
# Nordic UART Service (NUS) split TX/RX UUIDs are also supported via the kwargs.
HM10_SERVICE = "0000ffe0-0000-1000-8000-00805f9b34fb"
HM10_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"  # write + notify on the same char
NUS_TX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host -> device (write)
NUS_RX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # device -> host (notify)


def list_bt_serial_ports() -> list[str]:
    """Best-effort list of candidate Bluetooth SPP serial devices for HC-05/06."""
    if sys.platform == "darwin":
        return sorted(glob.glob("/dev/cu.*"))  # filter by name (HC-05, RNBT, ...) yourself
    # linux
    return sorted(glob.glob("/dev/rfcomm*") + glob.glob("/dev/ttyUSB*"))


def open_bt_spp(port: str, baud: int = 9600) -> ArduinoBridge:
    """Classic Bluetooth (SPP) is just a serial port -> reuse ArduinoBridge.
    Defaults to 9600 (HC-05 factory baud), unlike USB's 115200."""
    return ArduinoBridge(port=port, baud=baud)


class BLEBridge:
    """BLE link to an HM-10-style transparent-UART module via `bleak`.

    Speaks the same protocol as the serial/SPP bridge: send() writes the encoded
    `C ...` line to the UART characteristic; an internal notify handler reassembles
    incoming `D <cm>` lines so read_distance_cm() is non-blocking.

    `address` is the BLE peripheral address (macOS: a CoreBluetooth UUID; Linux/Win:
    a MAC). `char` defaults to the HM-10 FFE1 characteristic; pass NUS_TX/NUS_RX for a
    Nordic-UART module.
    """

    def __init__(
        self,
        address: str,
        char: str = HM10_CHAR,
        rx_char: str | None = None,
        connect_timeout: float = 15.0,
    ) -> None:
        try:
            from bleak import BleakClient  # lazy: only the BLE path needs bleak
        except Exception as e:  # pragma: no cover - optional dep
            raise RuntimeError(
                "bleak is required for BLEBridge (pip install bleak). "
                "Use open_bridge(None) / DummyBridge for hardware-free testing."
            ) from e

        self._BleakClient = BleakClient
        self.address = address
        self.tx_char = char  # host -> device (write)
        self.rx_char = rx_char or char  # device -> host (notify); HM-10 = same char
        self._rx = b""
        self._latest: int | None = None
        self._lock = threading.Lock()

        # bleak is asyncio; run a private event loop in a daemon thread and marshal
        # the sync send/read calls onto it.
        import asyncio

        self._asyncio = asyncio
        self._loop = asyncio.new_event_loop()
        self._client: Any = None  # bleak client, created in _connect()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._call(self._connect(connect_timeout))

    # ---- event loop plumbing ----
    def _run_loop(self) -> None:
        self._asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro):
        """Run a coroutine on the bg loop from a sync caller and wait for it."""
        fut = self._asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    async def _connect(self, timeout: float) -> None:
        self._client = self._BleakClient(self.address, timeout=timeout)
        await self._client.connect()

        def _on_notify(_handle, data: bytearray) -> None:
            with self._lock:
                self._rx += bytes(data)
                while b"\n" in self._rx:
                    raw, self._rx = self._rx.split(b"\n", 1)
                    line = raw.strip()
                    if line.startswith(b"D"):
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                self._latest = int(parts[1])
                            except ValueError:
                                pass

        try:
            await self._client.start_notify(self.rx_char, _on_notify)
        except Exception:
            pass  # some FFE1 modules are write-only; distance read just stays None

    # ---- public interface (matches ArduinoBridge) ----
    def send(self, cmd: Command) -> str:
        line = encode(cmd)
        self._call(self._client.write_gatt_char(self.tx_char, line.encode("ascii"), response=False))
        return line

    def read_distance_cm(self) -> int | None:
        with self._lock:
            return self._latest

    def close(self) -> None:
        try:
            self._call(self._client.disconnect())
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


def open_link(
    connection: str = "auto",
    target: str | None = None,
    baud: int = 115200,
    verbose: bool = False,
):
    """Unified factory for every robot link. `connection`:

        "usb"   -> ArduinoBridge(target, baud)            # USB serial (default 115200)
        "bt"    -> ArduinoBridge(target, baud or 9600)    # Classic BT-SPP serial port
        "ble"   -> BLEBridge(target)                       # HM-10 BLE
        "char"  -> CharBridge(target, baud or 9600)        # TESTED single-char firmware
        "dummy" -> DummyBridge                             # no hardware
        "auto"  -> ble if target looks like a BLE addr/uuid, else serial, else dummy

    Always returns an object with send / read_distance_cm / close. Degrades to
    DummyBridge if the requested transport's deps/hardware are unavailable.

    NOTE "char" is for the single-char firmware in arduino/cat_ranger/cat_ranger.ino
    (Adafruit Motor Shield rig); "usb"/"bt"/"ble" speak the C/D protocol. Pick the one
    matching the sketch flashed on your Arduino.
    """
    conn = (connection or "auto").lower()
    if conn == "dummy" or (conn == "auto" and not target):
        return DummyBridge(port=target, verbose=verbose)
    if target is None:
        # a real transport was requested but no port/address was given
        return DummyBridge(port=target, verbose=verbose)

    if conn == "char":
        from catranger.hw.char_bridge import CharBridge

        try:
            return CharBridge(port=target, baud=9600 if baud == 115200 else baud)
        except Exception as e:
            # Bulletproof demo: any link failure (no pyserial, bad/locked port)
            # degrades to a recorder instead of crashing the run.
            print(f"[catranger] char link unavailable ({e}); using DummyBridge")
            return DummyBridge(port=target, verbose=verbose)

    if conn == "ble":
        try:
            return BLEBridge(target)
        except RuntimeError as e:
            print(f"[catranger] BLE unavailable ({e}); using DummyBridge")
            return DummyBridge(port=target, verbose=verbose)

    if conn == "bt":
        try:
            return open_bt_spp(target, baud=9600 if baud == 115200 else baud)
        except RuntimeError:
            return DummyBridge(port=target, verbose=verbose)

    # usb / auto-with-target -> serial
    try:
        return ArduinoBridge(port=target, baud=baud)
    except RuntimeError:
        return DummyBridge(port=target, verbose=verbose)
