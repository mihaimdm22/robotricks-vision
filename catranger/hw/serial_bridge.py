"""Serial bridge to the Arduino Mega chassis (the wow-factor rig).

Tiny, fixed protocol — this is the WHOLE contract between the laptop/Pi and the
robot:

    Laptop/Pi -> Arduino :  "C <dx> <dy> <rot> <pan>\\n"   (4 ints)
    Arduino  -> Laptop/Pi:  "D <cm>\\n"                    (HC-SR04 ground truth)

The Arduino expects ints; CatRanger's Command uses normalized floats in [-1, 1].
This module owns that scaling. The field mapping (documented so the .ino and this
file never drift apart):

    Command field   norm range   serial field   actuator
    -------------   ----------   ------------   ----------------------------------
    Command.dx      [-1, 1]      dx  [-255,255] lateral strafe (chassis, if used)
    Command.v_fwd   [-1, 1]      dy  [-255,255] FORWARD drive  (+ = approach)
    Command.rotation[-1, 1]      rot [-255,255] yaw / turn-in-place (+ = right)
    Command.dy      [-1, 1]      pan [0, 180]   camera PAN servo angle

    NOTE the deliberate cross-wiring of the two "dy"s:
      * Command.v_fwd (forward speed) -> serial "dy"  (the Arduino differential mix
        treats `dy` as the forward axis: l = dy+rot, r = dy-rot).
      * Command.dy (camera pan/tilt, per types.py) -> serial "pan" servo angle.
    This matches types.py (Command.dy == "pan/tilt for the camera servo") and the
    Arduino sketch's `drive(dx, dy, rot)` + `pan.write(p)` exactly.

Use DummyBridge (or open_bridge(None)) to develop the whole pipeline with no
hardware attached — it just records/prints the commands it would have sent.
"""

from __future__ import annotations

from catranger.types import Command

# Servo travel for the camera pan mount. Command.dy in [-1, 1] maps linearly onto
# [SERVO_MIN, SERVO_MAX] with 90 deg = centered.
SERVO_MIN = 0
SERVO_MAX = 180
# Motor PWM magnitude for the drive/turn/strafe axes (matches analogWrite range).
MOTOR_MAX = 255


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _to_motor(norm: float) -> int:
    """normalized [-1, 1] -> signed PWM int [-MOTOR_MAX, MOTOR_MAX]."""
    return int(round(_clamp(float(norm), -1.0, 1.0) * MOTOR_MAX))


def _to_servo(norm: float) -> int:
    """normalized [-1, 1] -> servo angle int [SERVO_MIN, SERVO_MAX], 0 -> 90."""
    span = (SERVO_MAX - SERVO_MIN) / 2.0
    mid = (SERVO_MAX + SERVO_MIN) / 2.0
    return int(round(mid + _clamp(float(norm), -1.0, 1.0) * span))


def encode(cmd: Command) -> str:
    """Build the exact wire line 'C <dx> <dy> <rot> <pan>\\n' from a Command,
    applying the field mapping documented at the top of this module."""
    dx = _to_motor(cmd.dx)  # lateral strafe
    dy = _to_motor(cmd.v_fwd)  # forward drive  (serial 'dy' axis)
    rot = _to_motor(cmd.rotation)  # yaw / turn
    pan = _to_servo(cmd.dy)  # camera pan servo angle
    return f"C {dx} {dy} {rot} {pan}\n"


class ArduinoBridge:
    """Real serial link to the Arduino Mega over USB (pyserial, lazy-imported)."""

    def __init__(self, port: str = "/dev/ttyACM0", baud: int = 115200) -> None:
        self.port = port
        self.baud = baud
        try:
            import serial  # lazy: only the real bridge needs pyserial
        except Exception as e:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "pyserial is required for ArduinoBridge "
                "(pip install pyserial). Use DummyBridge / open_bridge(None) for "
                "hardware-free testing."
            ) from e
        # timeout=0 -> non-blocking reads so read_distance_cm never stalls the loop.
        self._ser = serial.Serial(port, baud, timeout=0)
        self._rx = b""  # rolling RX buffer for line reassembly

    def send(self, cmd: Command) -> str:
        """Scale + write a Command as 'C dx dy rot pan\\n'. Returns the wire line."""
        line = encode(cmd)
        self._ser.write(line.encode("ascii"))
        return line

    def read_distance_cm(self) -> int | None:
        """Non-blocking: drain pending bytes, return the cm from the most recent
        complete 'D <cm>\\n' line, or None if no full line arrived. -1 from the
        sensor (no echo) is passed through as -1 (still an int, distinct from None).
        """
        try:
            pending = self._ser.in_waiting
        except Exception:
            pending = 0
        if pending:
            self._rx += self._ser.read(pending)
        latest: int | None = None
        while b"\n" in self._rx:
            raw, self._rx = self._rx.split(b"\n", 1)
            line = raw.strip()
            if not line.startswith(b"D"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    latest = int(parts[1])
                except ValueError:
                    continue
        return latest

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class DummyBridge:
    """Drop-in stand-in for ArduinoBridge with no hardware. Records every wire
    line it would have sent (and optionally prints them) so the pipeline/demo can
    run end-to-end on a laptop with nothing plugged in."""

    def __init__(self, port: str | None = None, baud: int = 115200, verbose: bool = False) -> None:
        self.port = port
        self.baud = baud
        self.verbose = verbose
        self.sent: list[str] = []

    def send(self, cmd: Command) -> str:
        line = encode(cmd)
        self.sent.append(line)
        if self.verbose:
            print("[DummyBridge] ->", line.strip())
        return line

    def read_distance_cm(self) -> int | None:
        """No sensor attached -> always None (matches 'nothing arrived')."""
        return None

    def close(self) -> None:
        return None


def open_bridge(port: str | None = None, baud: int = 115200, verbose: bool = False):
    """Factory: real ArduinoBridge when a port is given and pyserial is installed,
    otherwise a DummyBridge. Both share the same interface (send / read_distance_cm
    / close), so callers never branch on hardware presence.

        bridge = open_bridge("/dev/ttyACM0")   # real
        bridge = open_bridge()                  # dummy (testing)
    """
    if port is None:
        return DummyBridge(port=port, baud=baud, verbose=verbose)
    try:
        return ArduinoBridge(port=port, baud=baud)
    except RuntimeError:
        # pyserial missing or port unavailable -> degrade gracefully to dummy.
        return DummyBridge(port=port, baud=baud, verbose=verbose)
