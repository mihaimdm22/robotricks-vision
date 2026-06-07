"""Follow controller: FrameResult -> Command, with the anti-oscillation pipeline and
the SEARCH/ACQUIRE/TRACK/COAST/SAFE state machine from docs/research/cat-tracker.md sec 4.

Errors (from result.target):
  bearing (rad)            -> rotation = kp_rot * bearing      (+ = turn right toward cat)
  distance err = Z - setpoint -> v_fwd = kp_fwd * err          (+ err = too far = approach)

Anti-oscillation, applied per channel EXACTLY in this order each frame:
  1) deadband   -> zero the raw command if |raw| < deadband
  2) EMA        -> u = alpha*raw + (1-alpha)*u_prev
  3) slew-limit -> |u - u_prev| <= slew_max
  4) clamp      -> saturate to [-1, 1]

Pure stdlib + math. No heavy deps.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from catranger.types import Command, FrameResult


def _deadband(x: float, band: float) -> float:
    return 0.0 if abs(x) < band else x


def _ema(raw: float, prev: float, alpha: float) -> float:
    return alpha * raw + (1.0 - alpha) * prev


def _slew(u: float, prev: float, slew_max: float) -> float:
    if slew_max <= 0:
        return u
    delta = u - prev
    if delta > slew_max:
        delta = slew_max
    elif delta < -slew_max:
        delta = -slew_max
    return prev + delta


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class Follower:
    """Stateful P-controller that turns per-frame perception into a smooth Command."""

    def __init__(self, follow_cfg: dict, clock: Callable[[], float] = time.perf_counter):
        # Injectable monotonic clock; defaults to the real one. Tests pass a fake
        # so the COAST/SEARCH lost-timeout logic is deterministic and exercisable.
        self._clock = clock
        cfg = follow_cfg or {}
        self.setpoint = float(cfg.get("setpoint_distance_m", 1.5))
        self.kp_rot = float(cfg.get("kp_rot", 1.2))
        self.kp_fwd = float(cfg.get("kp_fwd", 0.8))
        self.deadband_rot = float(cfg.get("deadband_rot", 0.05))
        self.deadband_dist = float(cfg.get("deadband_dist_m", 0.20))
        self.alpha = float(cfg.get("ema_alpha", 0.30))
        self.slew_max = float(cfg.get("slew_max", 0.15))
        self.lost_timeout_s = float(cfg.get("lost_timeout_s", 1.0))
        self.safe_distance = float(cfg.get("safe_distance_m", 0.4))
        # frames to lock onto a target before declaring TRACK
        self.acquire_frames = int(cfg.get("acquire_frames", 3))

        self.reset()

    def reset(self) -> None:
        # per-channel smoothing state
        self.u_prev: dict[str, float] = {"rotation": 0.0, "v_fwd": 0.0}
        self.state = "SEARCH"
        self.target_id: int | None = None
        self._acquire_count = 0
        self._last_seen_t: float | None = None
        self._last_bearing_rad = 0.0  # last observed bearing, for SEARCH sweep
        self._coast_cmd = Command(state="SEARCH")

    def set_search_bearing_deg(self, bearing_deg: float | None) -> None:
        """Bias SEARCH rotation toward a remembered bearing (e.g. library re-acquire)."""
        if bearing_deg is None:
            return
        self._last_bearing_rad = math.radians(float(bearing_deg))

    def _smooth(self, channel: str, raw: float) -> float:
        prev = self.u_prev.get(channel, 0.0)
        u = _deadband(raw, self.deadband_rot if channel == "rotation" else self.deadband_dist)
        u = _ema(u, prev, self.alpha)
        u = _slew(u, prev, self.slew_max)
        u = _clamp(u)
        self.u_prev[channel] = u
        return u

    def step(self, result: FrameResult) -> Command:
        now = self._clock()
        target = result.target if result is not None else None

        # ---------------- no target -> COAST then SEARCH ----------------
        if target is None or target.distance is None or not math.isfinite(target.distance.meters):
            elapsed = (now - self._last_seen_t) if self._last_seen_t is not None else None
            if elapsed is not None and elapsed <= self.lost_timeout_s:
                # COAST: decay the last command toward zero
                rot = _clamp(self.u_prev.get("rotation", 0.0) * 0.8)
                v = _clamp(self.u_prev.get("v_fwd", 0.0) * 0.8)
                self.u_prev["rotation"] = rot
                self.u_prev["v_fwd"] = v
                self.state = "COAST"
                self._acquire_count = 0
                return Command(
                    rotation=rot,
                    v_fwd=v,
                    state="COAST",
                    target_id=self.target_id,
                )
            # SEARCH: rotate slowly toward last-seen bearing, no forward motion
            self.state = "SEARCH"
            self.target_id = None
            self._acquire_count = 0
            sweep = 0.3 * (1.0 if self._last_bearing_rad >= 0 else -1.0)
            rot = self._smooth("rotation", sweep)
            # zero forward channel smoothly
            v = self._smooth("v_fwd", 0.0)
            return Command(rotation=rot, v_fwd=v, state="SEARCH", target_id=None)

        # ---------------- have a target ----------------
        det = target.detection
        # bearing: prefer the precomputed bearing_deg, convert to radians
        bearing_rad = math.radians(target.bearing_deg)
        self._last_bearing_rad = bearing_rad
        self._last_seen_t = now

        z = float(target.distance.meters)

        # target-lock hysteresis / acquire counter
        known = set(result.target_known_ids or [])
        if self.target_id != det.track_id:
            if self.target_id is None or det.track_id not in known:
                self._acquire_count = 0
            self.target_id = det.track_id

        # ---------------- SAFE: too close -> back off / stop ----------------
        if z < self.safe_distance:
            self.state = "SAFE"
            # back off proportionally to how far inside the safe radius we are
            err = z - self.setpoint  # strongly negative -> reverse
            rot_raw = self.kp_rot * bearing_rad
            v_raw = self.kp_fwd * err  # negative -> back off
            rot = self._smooth("rotation", rot_raw)
            v = self._smooth("v_fwd", v_raw)
            return Command(
                rotation=rot,
                v_fwd=v,
                state="SAFE",
                target_id=self.target_id,
            )

        # ---------------- ACQUIRE -> TRACK ----------------
        if self._acquire_count < self.acquire_frames:
            self._acquire_count += 1
            self.state = "ACQUIRE"
        else:
            self.state = "TRACK"

        # P-control errors
        dist_err = z - self.setpoint  # >0 too far -> approach (positive v_fwd)
        rot_raw = self.kp_rot * bearing_rad
        v_raw = self.kp_fwd * dist_err

        rotation = self._smooth("rotation", rot_raw)
        v_fwd = self._smooth("v_fwd", v_raw)

        return Command(
            rotation=rotation,
            v_fwd=v_fwd,
            state=self.state,
            target_id=self.target_id,
        )
