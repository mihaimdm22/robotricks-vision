"""CharBridge — drive the TESTED single-char Arduino firmware from the perception host.

The repo's primary protocol is ``C dx dy rot pan`` / ``D <cm>`` (serial_bridge.py).
The firmware the team actually flashed and verified on the rig speaks a DIFFERENT,
discrete vocabulary instead (see ``arduino/cat_ranger/cat_ranger.ino``):

    'b' = manual / stop          'f' = nudge forward ~400 ms then auto-stop
    'h' = turn left  ~90 deg     'j' = turn right ~90 deg
    'a' = autonomous (forward-until-obstacle)   [bearing-blind; NEVER used for follow]

This adapter implements the same ``send`` / ``read_distance_cm`` / ``close`` contract
as ArduinoBridge (the ``_BridgeLike`` protocol the web controller depends on) so the
existing, already-bulletproof control loop drives the proven rig unchanged.

WHY IT IS STATEFUL
------------------
The controller calls ``send(cmd)`` every frame (~15 Hz), but the firmware is an
edge-triggered automaton: sending 'f' starts a 400 ms blocking nudge during which the
firmware is DEAF (its ``delay()`` blocks ``loop()``). So this bridge must:
  * remember it is already in manual mode so a steady command emits its char ONCE,
    not 15x/second (no link spam at 9600 baud),
  * debounce: never send two motion chars closer than the blocking-primitive duration,
  * suppress sends while a turn/nudge is estimated in-flight (the deaf window),
  * gate forward nudges on the last known distance (never nudge into an obstacle).

HONEST LIMITATION (see arduino-integration-plan.md, Eng review)
---------------------------------------------------------------
Discrete 90-degree turns + 400 ms nudges cannot SMOOTHLY follow a cat — the realistic
behaviour is coarse, deliberate "face-then-nudge" stepwise tracking. 'a' autonomous
mode is bearing-blind (drives straight, ignoring where the cat is) AND has no firmware
watchdog (link loss drives forever), so this adapter NEVER uses 'a' for follow: the
self-terminating 'f' nudge means a dropped link coasts to a stop within ~400 ms.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from catranger.types import Command

# Single-char vocabulary of the tested firmware.
CH_MANUAL_STOP = "b"
CH_FORWARD = "f"
CH_BACK = "g"
CH_TURN_LEFT = "h"
CH_TURN_RIGHT = "j"

# Peripheral toggles (additive protocol — see arduino/cat_ranger/cat_ranger.ino).
CH_BUZZER_TOGGLE = "c"
CH_RGB_TOGGLE = "v"
CH_LCD_TOGGLE = "k"
CH_PERIPH_ALL_ON = "8"
CH_PERIPH_ALL_OFF = "9"

PERIPH_ACTIONS: dict[str, str] = {
    "buzzer_toggle": CH_BUZZER_TOGGLE,
    "rgb_toggle": CH_RGB_TOGGLE,
    "lcd_toggle": CH_LCD_TOGGLE,
    "all_on": CH_PERIPH_ALL_ON,
    "all_off": CH_PERIPH_ALL_OFF,
}

SONAR_RANGE_CM = 200
BUZZER_FAR_CM = 180


def _drain_distance(rx: bytes) -> tuple[bytes, int | None]:
    """Parse complete ``D <cm>\\n`` lines out of a rolling RX buffer. Returns the
    leftover (incomplete) buffer and the cm from the most recent complete D line, or
    None if no full D line was present. -1 (no echo) passes through as -1."""
    latest: int | None = None
    while b"\n" in rx:
        raw, rx = rx.split(b"\n", 1)
        line = raw.strip()
        if not line.startswith(b"D"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                latest = int(parts[1])
            except ValueError:
                continue
    return rx, latest


class CharBridge:
    """Quantizes a smooth follow ``Command`` into the tested firmware's char set.

    Pass ``transport`` (a pyserial-like object with ``write`` / ``in_waiting`` /
    ``read`` / ``close``) for tests; pass ``port`` for a real serial link. With
    neither, it is a recorder (every emitted char is appended to ``self.sent``), so
    the quantization is fully unit-testable with an injected ``clock`` — exactly like
    Follower / RobotController.
    """

    def __init__(
        self,
        port: str | None = None,
        baud: int = 9600,
        *,
        transport: object | None = None,
        clock: Callable[[], float] = time.perf_counter,
        rot_thresh: float = 0.4,
        fwd_thresh: float = 0.2,
        min_interval_s: float = 0.5,
        turn_inflight_s: float = 0.30,
        nudge_inflight_s: float = 0.45,
        safe_stop_cm: int = 20,
    ) -> None:
        self.port = port
        self.baud = baud
        self._clock = clock
        # Tuning (wide rotation deadband: a fixed 90 deg turn overshoots a small
        # bearing error into a limit cycle, so only turn when genuinely off-axis).
        self.rot_thresh = float(rot_thresh)
        self.fwd_thresh = float(fwd_thresh)
        self.min_interval_s = float(min_interval_s)
        self.turn_inflight_s = float(turn_inflight_s)
        self.nudge_inflight_s = float(nudge_inflight_s)
        self.safe_stop_cm = int(safe_stop_cm)

        # State held between every-frame send() calls.
        self.sent: list[str] = []  # every char actually emitted (recorder + debug)
        self._mode: str | None = None  # None until we've put the firmware in manual ('b')
        self._stopped = True  # have we commanded a stop since the last move?
        self._last_send_t: float | None = None  # last time ANY char went out (debounce)
        self._inflight_until = 0.0  # firmware busy in a blocking primitive until this t
        self._rx = b""  # rolling RX buffer for D-line reassembly
        self._latest_cm: int | None = None  # sticky last known distance (safety gate)
        # Host-side mirror of firmware peripheral toggles (updated when send_raw fires).
        self.periph: dict[str, bool] = {"buzzer": True, "rgb": True, "lcd": True}
        self._lcd_target_label = ""

        self._ser = transport
        if self._ser is None and port is not None:
            try:
                import serial  # lazy: only the real link needs pyserial
            except Exception as e:  # pragma: no cover - optional dep
                raise RuntimeError(
                    "pyserial is required for a real CharBridge (pip install pyserial). "
                    "Use open_link(None) / DummyBridge for hardware-free testing."
                ) from e
            self._ser = serial.Serial(port, baud, timeout=0)
            # Ensure on-rig buzzer/RGB/LCD match firmware defaults after link open.
            try:
                self.send_raw(CH_PERIPH_ALL_ON)
            except Exception:
                pass

    # ---- quantization (pure given clock + state) -------------------------------
    def _decide(self, cmd: Command, now: float) -> str:
        """Return the single char to emit this tick, or '' to stay silent."""
        # Firmware is mid blocking primitive -> it is deaf; don't pile up commands.
        if now < self._inflight_until:
            return ""

        # Classify intent. SAFE/IDLE or no drive intent -> stop.
        if cmd.state in ("SAFE", "IDLE") or (
            abs(cmd.v_fwd) <= self.fwd_thresh and abs(cmd.rotation) <= self.rot_thresh
        ):
            intent = "stop"
        elif abs(cmd.rotation) > self.rot_thresh:
            intent = "turn_right" if cmd.rotation > 0 else "turn_left"
        elif cmd.v_fwd > self.fwd_thresh:
            intent = "forward"
        elif cmd.v_fwd < -self.fwd_thresh:
            intent = "backward"
        else:
            intent = "hold"

        # Safety pre-gate: never nudge forward into a known-close obstacle. NOTE a
        # reading of -1 is the HC-SR04 no-echo sentinel = "nothing within range" =
        # clear path (matches the tested firmware, whose autonomous mode also drives
        # forward on no-echo). So only a positive reading inside the floor blocks;
        # -1 must NOT block or the rig would freeze whenever the cat is out of sonar
        # range (e.g. across an open room) and never approach.
        if intent == "forward" and self._latest_cm is not None:
            if 0 <= self._latest_cm < self.safe_stop_cm:
                intent = "stop"

        if intent == "hold":
            return ""

        if intent == "stop":
            if self._stopped:
                return ""  # already stopped — don't spam 'b'
            self._stopped = True
            self._mode = "manual"
            return CH_MANUAL_STOP

        # intent is a MOVE (turn/forward). The firmware only honours f/g/h/j in manual
        # mode, so put it there once; the move fires on a later eligible tick.
        if self._mode != "manual":
            self._mode = "manual"
            self._stopped = True
            return CH_MANUAL_STOP

        # Debounce: don't issue moves faster than the blocking primitive can finish.
        if self._last_send_t is not None and (now - self._last_send_t) < self.min_interval_s:
            return ""

        self._stopped = False
        if intent == "forward":
            self._inflight_until = now + self.nudge_inflight_s
            return CH_FORWARD
        if intent == "backward":
            self._inflight_until = now + self.nudge_inflight_s
            return CH_BACK
        if intent == "turn_left":
            self._inflight_until = now + self.turn_inflight_s
            return CH_TURN_LEFT
        self._inflight_until = now + self.turn_inflight_s  # turn_right
        return CH_TURN_RIGHT

    def _write(self, ch: str) -> None:
        self.sent.append(ch)
        self._last_send_t = self._clock()
        if self._ser is not None:
            try:
                self._ser.write(ch.encode("ascii"))  # type: ignore[attr-defined]
            except Exception:
                pass

    def _write_bytes(self, data: bytes) -> None:
        self.sent.append(data.decode("ascii", errors="replace"))
        if self._ser is not None:
            try:
                self._ser.write(data)  # type: ignore[attr-defined]
            except Exception:
                pass

    def sync_target(self, target_id: int | None, known_ids: list[int] | None = None) -> None:
        """Push tracked cat id(s) to the physical LCD via ``I<label>\\n``."""
        if known_ids:
            label = "/".join(str(i) for i in known_ids[:4])
        elif target_id is not None:
            label = str(target_id)
        else:
            label = "-"
        label = label[:16]
        if label == self._lcd_target_label:
            return
        self._lcd_target_label = label
        self._write_bytes(f"I{label}\n".encode("ascii"))

    def _apply_periph_char(self, ch: str) -> None:
        if ch == CH_BUZZER_TOGGLE:
            self.periph["buzzer"] = not self.periph["buzzer"]
        elif ch == CH_RGB_TOGGLE:
            self.periph["rgb"] = not self.periph["rgb"]
        elif ch == CH_LCD_TOGGLE:
            self.periph["lcd"] = not self.periph["lcd"]
        elif ch == CH_PERIPH_ALL_ON:
            self.periph = {"buzzer": True, "rgb": True, "lcd": True}
        elif ch == CH_PERIPH_ALL_OFF:
            self.periph = {"buzzer": False, "rgb": False, "lcd": False}

    def send_raw(self, ch: str) -> str:
        """Send a one-off peripheral command char (not debounced like motion)."""
        if not ch or len(ch) != 1:
            raise ValueError("send_raw expects a single character")
        self._apply_periph_char(ch)
        self._write(ch)
        return ch

    def periph_state(self) -> dict[str, bool]:
        return dict(self.periph)

    # ---- public interface (matches ArduinoBridge) ------------------------------
    def send(self, cmd: Command) -> str:
        """Quantize + emit. Returns the char sent this tick ('' if none)."""
        ch = self._decide(cmd, self._clock())
        if ch:
            self._write(ch)
        return ch

    def read_distance_cm(self) -> int | None:
        """Non-blocking: drain pending bytes, return the cm of the most recent
        complete ``D <cm>`` line this call (or None). Also updates the sticky
        last-known distance used by the forward safety gate."""
        if self._ser is None:
            return None
        try:
            pending = self._ser.in_waiting  # type: ignore[attr-defined]
        except Exception:
            pending = 0
        if pending:
            try:
                self._rx += self._ser.read(pending)  # type: ignore[attr-defined]
            except Exception:
                return None
        self._rx, latest = _drain_distance(self._rx)
        if latest is not None:
            self._latest_cm = latest
        return latest

    def close(self) -> None:
        """Best-effort stop ('b') then close the link, so teardown never leaves the
        rig latched in motion."""
        try:
            self._write(CH_MANUAL_STOP)
        except Exception:
            pass
        if self._ser is not None:
            try:
                self._ser.close()  # type: ignore[attr-defined]
            except Exception:
                pass
