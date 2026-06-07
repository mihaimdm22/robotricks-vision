"""CharBridge — the host-side adapter that drives the TESTED single-char Arduino
firmware. The quantization is safety-relevant (it must not spam the 9600-baud link,
must not turn on tiny bearing errors, and must not nudge into a known obstacle), so it
is exercised here with an injected clock + a fake serial transport — no hardware.
"""

from __future__ import annotations

from catranger.hw.bluetooth import open_link
from catranger.hw.char_bridge import CharBridge
from catranger.hw.serial_bridge import DummyBridge
from catranger.types import Command


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeSerial:
    """Minimal pyserial-like transport: collects writes, serves a scripted RX buffer."""

    def __init__(self, rx: bytes = b"") -> None:
        self.written = bytearray()
        self._rx = bytearray(rx)
        self.closed = False

    def feed(self, data: bytes) -> None:
        self._rx += data

    @property
    def in_waiting(self) -> int:
        return len(self._rx)

    def read(self, n: int) -> bytes:
        out, self._rx = bytes(self._rx[:n]), self._rx[n:]
        return out

    def write(self, b: bytes) -> int:
        self.written += b
        return len(b)

    def close(self) -> None:
        self.closed = True


def _bridge(clk: FakeClock, ser: FakeSerial | None = None, **kw) -> CharBridge:
    return CharBridge(transport=ser, clock=clk, **kw)


# 1) Quantization table -------------------------------------------------------
def test_forward_intent_enters_manual_then_nudges() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    # First tick on a fresh bridge: bootstrap into manual mode ('b'), not a move yet.
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == "b"
    # Past the debounce window, a steady forward intent emits exactly one nudge.
    clk.advance(0.6)
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == "f"


def test_large_bearing_turns_correct_side() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    b.send(Command(rotation=0.9, state="TRACK"))  # bootstrap 'b'
    clk.advance(0.6)
    assert b.send(Command(rotation=0.9, state="TRACK")) == "j"  # +rot = turn right
    clk.advance(0.6)
    assert b.send(Command(rotation=-0.9, state="TRACK")) == "h"  # -rot = turn left


def test_small_bearing_does_not_turn() -> None:
    """Regression guard: a small bearing error (rotation 0.31 < rot_thresh 0.4) must
    NOT trigger a fixed 90-degree turn (that would limit-cycle on the real rig)."""
    clk = FakeClock()
    b = _bridge(clk)
    for _ in range(10):
        b.send(Command(rotation=0.31, v_fwd=0.0, state="TRACK"))
        clk.advance(0.6)
    assert "h" not in b.sent and "j" not in b.sent


def test_safe_state_stops_after_moving() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    b.send(Command(v_fwd=0.8, state="TRACK"))  # 'b'
    clk.advance(0.6)
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == "f"  # moved
    clk.advance(0.6)
    assert b.send(Command(state="SAFE")) == "b"  # SAFE -> stop


# 2) Steady command emits its char ONCE, not per-frame (no 15 Hz link spam) ----
def test_steady_command_does_not_spam_link() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    cmd = Command(v_fwd=0.8, state="TRACK")
    for _ in range(15):  # one second at ~15 Hz
        b.send(cmd)
        clk.advance(1.0 / 15.0)
    # 'b' once to enter manual, then a couple of debounced nudges — nowhere near 15.
    assert b.sent.count("b") == 1
    assert 1 <= b.sent.count("f") <= 3


# 3) Debounce >= primitive duration -------------------------------------------
def test_debounce_blocks_back_to_back_moves() -> None:
    clk = FakeClock()
    b = _bridge(clk, min_interval_s=0.5)
    b.send(Command(v_fwd=0.8, state="TRACK"))  # 'b'
    clk.advance(0.6)
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == "f"  # nudge fires
    clk.advance(0.1)  # only 0.1 s later, well inside both inflight and debounce
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == ""  # suppressed


# 4) In-flight suppression after a turn ---------------------------------------
def test_inflight_suppresses_during_blocking_primitive() -> None:
    clk = FakeClock()
    b = _bridge(clk, turn_inflight_s=0.30)
    b.send(Command(rotation=0.9, state="TRACK"))  # 'b'
    clk.advance(0.6)
    assert b.send(Command(rotation=0.9, state="TRACK")) == "j"  # turn fires
    clk.advance(0.2)  # firmware still mid delay(250) -> deaf
    assert b.send(Command(rotation=0.9, state="TRACK")) == ""


# 5) read_distance_cm ---------------------------------------------------------
def test_read_distance_parses_latest_and_passes_minus_one() -> None:
    clk = FakeClock()
    ser = FakeSerial(b"D 120\nD 184\n")
    b = _bridge(clk, ser)
    assert b.read_distance_cm() == 184  # most recent complete line
    ser.feed(b"D -1\n")
    assert b.read_distance_cm() == -1  # no-echo sentinel passes through


def test_read_distance_partial_line_returns_none_then_completes() -> None:
    clk = FakeClock()
    ser = FakeSerial(b"D 9")  # incomplete, no newline yet
    b = _bridge(clk, ser)
    assert b.read_distance_cm() is None
    ser.feed(b"9\n")  # completes "D 99\n"
    assert b.read_distance_cm() == 99


def test_read_distance_skips_non_d_chatter() -> None:
    clk = FakeClock()
    ser = FakeSerial(b"Mod manual\nD 55\n")  # a stray status line then a real reading
    b = _bridge(clk, ser)
    assert b.read_distance_cm() == 55


def test_forward_gated_by_known_close_obstacle() -> None:
    """If the last known distance is inside the safe floor, a forward intent must
    become a stop, never a nudge into the obstacle."""
    clk = FakeClock()
    ser = FakeSerial(b"D 10\n")  # 10 cm, inside the 20 cm floor
    b = _bridge(clk, ser, safe_stop_cm=20)
    b.read_distance_cm()  # primes the sticky last-known distance
    b.send(Command(v_fwd=0.8, state="TRACK"))  # bootstrap 'b'
    clk.advance(0.6)
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == ""  # gated: no 'f'
    assert "f" not in b.sent


def test_no_echo_minus_one_does_not_block_forward() -> None:
    """A -1 reading is 'no echo / nothing in range' = clear path. It must NOT gate
    forward motion (else the rig freezes whenever the cat is out of sonar range)."""
    clk = FakeClock()
    ser = FakeSerial(b"D -1\n")
    b = _bridge(clk, ser, safe_stop_cm=20)
    b.read_distance_cm()  # sticky last-known = -1
    b.send(Command(v_fwd=0.8, state="TRACK"))  # bootstrap 'b'
    clk.advance(0.6)
    assert b.send(Command(v_fwd=0.8, state="TRACK")) == "f"  # NOT gated


def test_coast_and_idle_states_stop_not_crash() -> None:
    """COAST/IDLE with no forward intent must resolve to a stop, never a move."""
    clk = FakeClock()
    b = _bridge(clk)
    b.send(Command(v_fwd=0.5, state="TRACK"))  # 'b'
    clk.advance(0.6)
    b.send(Command(v_fwd=0.5, state="TRACK"))  # 'f' -> now moving
    clk.advance(0.6)
    assert b.send(Command(rotation=0.0, v_fwd=0.0, state="COAST")) == "b"
    clk.advance(0.6)
    # already stopped -> IDLE stays silent, no crash
    assert b.send(Command(state="IDLE")) == ""


def test_manual_state_forward_still_nudges() -> None:
    """A MANUAL-state command with forward intent is driven like any other move."""
    clk = FakeClock()
    b = _bridge(clk)
    b.send(Command(v_fwd=0.6, state="MANUAL"))  # bootstrap 'b'
    clk.advance(0.6)
    assert b.send(Command(v_fwd=0.6, state="MANUAL")) == "f"


def test_backward_intent_nudges_back() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    b.send(Command(v_fwd=-0.6, state="MANUAL"))  # bootstrap 'b'
    clk.advance(0.6)
    assert b.send(Command(v_fwd=-0.6, state="MANUAL")) == "g"


# 6) close() sends 'b' and is exception-safe ----------------------------------
def test_close_sends_stop_and_closes_transport() -> None:
    clk = FakeClock()
    ser = FakeSerial()
    b = _bridge(clk, ser)
    b.close()
    assert b.sent[-1] == "b"
    assert ser.closed is True


def test_close_without_transport_is_safe() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    b.close()  # no transport -> must not raise
    assert b.sent[-1] == "b"


# 7) open_link selection + graceful degrade -----------------------------------
def test_open_link_char_without_target_is_dummy() -> None:
    link = open_link("char", None)
    assert isinstance(link, DummyBridge)


def test_open_link_char_bad_port_degrades_to_dummy() -> None:
    # A nonexistent port must degrade to DummyBridge, never crash the run.
    link = open_link("char", "/dev/cu.this-port-does-not-exist-catranger")
    assert isinstance(link, DummyBridge)


# 8) peripheral toggles -------------------------------------------------------
def test_send_raw_toggles_buzzer_and_tracks_state() -> None:
    clk = FakeClock()
    ser = FakeSerial()
    b = _bridge(clk, ser)
    assert b.periph_state()["buzzer"] is True
    assert b.send_raw("c") == "c"
    assert b.periph_state()["buzzer"] is False
    assert ser.written == b"c"


def test_send_raw_all_off() -> None:
    clk = FakeClock()
    b = _bridge(clk)
    b.send_raw("9")
    assert b.periph_state() == {"buzzer": False, "rgb": False, "lcd": False}
    b.send_raw("8")
    assert b.periph_state() == {"buzzer": True, "rgb": True, "lcd": True}


def test_sync_target_writes_i_line_once() -> None:
    ser = FakeSerial()
    b = _bridge(FakeClock(), ser)
    b.sync_target(3, [3, 7])
    assert ser.written == b"I3/7\n"
    b.sync_target(3, [3, 7])
    assert ser.written == b"I3/7\n"
    b.sync_target(None, None)
    assert ser.written == b"I3/7\nI-\n"
