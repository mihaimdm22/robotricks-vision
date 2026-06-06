"""Unit tests for the M5 single-controller drive token (ControlArbiter).

Pure state machine with an injectable clock — no FastAPI, no threads.
"""

from __future__ import annotations

from catranger.web.arbiter import ControlArbiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_first_intent_auto_claims_the_token() -> None:
    arb = ControlArbiter(clock=FakeClock())
    a = arb.connect()
    assert arb.note_intent(a) is True
    assert arb.holder == a


def test_second_connection_is_an_observer() -> None:
    arb = ControlArbiter(clock=FakeClock())
    a, b = arb.connect(), arb.connect()
    assert arb.note_intent(a) is True
    assert arb.note_intent(b) is False  # a holds the token
    assert arb.is_holder(a) and not arb.is_holder(b)


def test_explicit_claim_takes_over_last_wins() -> None:
    arb = ControlArbiter(clock=FakeClock())
    a, b = arb.connect(), arb.connect()
    arb.note_intent(a)
    res = arb.claim(b)
    assert res == {"holder": b, "displaced": a}
    assert arb.is_holder(b) and not arb.is_holder(a)


def test_idle_timeout_releases_the_token() -> None:
    clk = FakeClock()
    arb = ControlArbiter(idle_timeout_s=5.0, clock=clk)
    a, b = arb.connect(), arb.connect()
    arb.note_intent(a)
    clk.advance(6.0)  # a went quiet past the lease
    assert arb.note_intent(b) is True  # b can now take a free token
    assert arb.holder == b


def test_heartbeat_keeps_the_lease_alive() -> None:
    clk = FakeClock()
    arb = ControlArbiter(idle_timeout_s=5.0, clock=clk)
    a, b = arb.connect(), arb.connect()
    arb.note_intent(a)
    clk.advance(3.0)
    arb.heartbeat(a)
    clk.advance(3.0)  # 6s since claim, but only 3s since heartbeat
    assert arb.note_intent(b) is False  # a still holds it
    assert arb.holder == a


def test_disconnect_releases_the_token() -> None:
    arb = ControlArbiter(clock=FakeClock())
    a, b = arb.connect(), arb.connect()
    arb.note_intent(a)
    arb.disconnect(a)
    assert arb.holder is None
    assert arb.note_intent(b) is True
