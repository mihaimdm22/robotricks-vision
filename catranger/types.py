"""Shared data contracts. Every module speaks in these types — keep them stable.

Pure stdlib + typing so this imports anywhere (no numpy/cv2 needed).
Boxes are always pixel-space `xyxy = (x1, y1, x2, y2)` in the frame they were
detected in (after undistort, if undistort is enabled).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Detection:
    """One detected (and optionally tracked) object."""

    xyxy: Tuple[float, float, float, float]
    conf: float
    cls_id: int
    cls_name: str = "cat"
    track_id: Optional[int] = None  # set by the tracker; None if detection-only

    @property
    def width(self) -> float:
        return float(self.xyxy[2] - self.xyxy[0])

    @property
    def height(self) -> float:
        return float(self.xyxy[3] - self.xyxy[1])

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.xyxy
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass
class DistanceResult:
    """Metric distance from the camera to an object, with an uncertainty band."""

    meters: float
    lo: float                 # lower bound of the confidence interval (meters)
    hi: float                 # upper bound (meters)
    method: str               # "geometry" | "depth" | "fused"
    components: Dict[str, float] = field(default_factory=dict)  # per-estimator values

    @property
    def half_width(self) -> float:
        return (self.hi - self.lo) / 2.0


@dataclass
class CatObservation:
    """A tracked cat plus everything we inferred about it this frame."""

    detection: Detection
    distance: Optional[DistanceResult] = None
    bearing_deg: float = 0.0           # horizontal angle from optical axis (+ = right)
    speed_mps: Optional[float] = None  # approach/recede speed if track history allows

    @property
    def track_id(self) -> Optional[int]:
        return self.detection.track_id


@dataclass
class FrameResult:
    """Per-frame output of the perception pipeline."""

    frame_index: int
    observations: List[CatObservation] = field(default_factory=list)
    # pairwise metric distances between tracked cats: (id_a, id_b, meters)
    inter_object: List[Tuple[int, int, float]] = field(default_factory=list)
    fps: float = 0.0
    width: int = 0
    height: int = 0

    @property
    def target(self) -> Optional[CatObservation]:
        """The currently followed cat = largest box (override in the tracker)."""
        if not self.observations:
            return None
        return max(self.observations, key=lambda o: o.detection.area)


@dataclass
class Command:
    """Control vector sent to the robot. Matches the Arduino serial protocol
    `C dx dy rot pan` after scaling to actuator units."""

    rotation: float = 0.0   # yaw rate, normalized [-1, 1] (+ = turn toward +x / right)
    dx: float = 0.0         # lateral strafe, normalized [-1, 1]
    dy: float = 0.0         # pan/tilt for the camera servo, normalized [-1, 1]
    v_fwd: float = 0.0      # forward speed, normalized [-1, 1] (+ = approach)
    state: str = "SEARCH"   # SEARCH | ACQUIRE | TRACK | COAST | REACQUIRE | SAFE
    target_id: Optional[int] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "rotation": round(self.rotation, 4),
            "dx": round(self.dx, 4),
            "dy": round(self.dy, 4),
            "v_fwd": round(self.v_fwd, 4),
            "state": self.state,
            "target_id": self.target_id,
        }
