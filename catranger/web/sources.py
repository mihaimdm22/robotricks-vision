"""Pollable, non-blocking frame sources for the web run loop.

The control loop must never block on a camera read (a stalled RTSP read freezes
the watchdog -> latched motors, per the eng review). So every source exposes a
non-blocking ``read() -> frame | None``:

  * ``SyntheticSource`` generates frames in-process (zero hardware) — the safe
    default + the fallback when a real camera is unavailable, so the panel always
    streams something and a contributor can develop the UI on a laptop.
  * ``CameraSource`` runs a daemon grabber thread that continuously pulls from a
    cv2.VideoCapture (webcam index / rtsp url / video file) into a latest-frame
    slot and reconnects with backoff; ``read()`` just returns the latest snapshot.

This is the I/O edge (omitted from unit coverage, like ``catranger.hw``); it is
smoke-tested via the server route tests and the dedicated ``web`` CI leg.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Protocol

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - cv2 is a base dep but stay defensive
    cv2 = None  # type: ignore[assignment]


class FrameSource(Protocol):
    def read(self) -> np.ndarray | None: ...
    def close(self) -> None: ...
    @property
    def label(self) -> str: ...


class SyntheticSource:
    """In-process test pattern: a sweeping marker + a live clock so a frozen
    stream is visually obvious. No camera, no network."""

    def __init__(self, width: int = 960, height: int = 540) -> None:
        self.width = int(width)
        self.height = int(height)
        self._i = 0

    @property
    def label(self) -> str:
        return "synthetic"

    def read(self) -> np.ndarray | None:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (30, 30, 30)
        self._i += 1
        if cv2 is not None:
            # a marker sweeping left<->right so motion is visible (anti-freeze cue)
            phase = (self._i % 120) / 120.0
            cx = int(40 + phase * (self.width - 80))
            cy = self.height // 2
            cv2.circle(frame, (cx, cy), 18, (0, 200, 255), -1)
            cv2.putText(
                frame,
                f"SIMULATION - synthetic source  frame {self._i}",
                (20, 36),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (200, 200, 200),
                2,
                cv2.LINE_AA,
            )
        return frame

    def close(self) -> None:
        return None


class CameraSource:
    """cv2.VideoCapture behind a daemon grabber thread (non-blocking read +
    auto-reconnect). Handles a webcam index, an rtsp:// url, or a video file
    (looped). ``read()`` returns the most recent frame or None until the first
    grab lands."""

    def __init__(
        self,
        spec: str,
        *,
        width: int = 960,
        height: int = 540,
        reconnect_backoff_s: float = 1.0,
    ) -> None:
        if cv2 is None:
            raise RuntimeError("opencv-python is required for CameraSource")
        self.spec = str(spec)
        self.width = int(width)
        self.height = int(height)
        self._backoff = float(reconnect_backoff_s)
        self._is_file = not self.spec.isdigit() and "://" not in self.spec
        # RTSP over TCP is far more robust than the default UDP on a busy LAN.
        if self.spec.lower().startswith("rtsp://"):
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

        self._latest: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connected = False
        self._thread = threading.Thread(target=self._grab_loop, name="cam-grabber", daemon=True)
        self._thread.start()

    @property
    def label(self) -> str:
        return f"camera:{self.spec}"

    @property
    def connected(self) -> bool:
        return self._connected

    def _open(self) -> cv2.VideoCapture | None:
        cap = (
            cv2.VideoCapture(int(self.spec)) if self.spec.isdigit() else cv2.VideoCapture(self.spec)
        )
        return cap if cap.isOpened() else None

    def _grab_loop(self) -> None:
        cap = None
        while not self._stop.is_set():
            if cap is None:
                cap = self._open()
                if cap is None:
                    self._connected = False
                    self._stop.wait(self._backoff)
                    continue
                self._connected = True
            ok, frame = cap.read()
            if not ok:
                if self._is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop video files
                    continue
                # live stream dropped: release + reconnect
                cap.release()
                cap = None
                self._connected = False
                continue
            with self._lock:
                self._latest = frame
        if cap is not None:
            cap.release()

    def read(self) -> np.ndarray | None:
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


def open_source(
    spec: str | None,
    *,
    width: int = 960,
    height: int = 540,
) -> FrameSource:
    """Build a frame source from a spec ("synthetic" | webcam index | rtsp url |
    file path). Falls back to a SyntheticSource when a real camera can't open, so
    the panel always has something to stream (DX: zero-hardware boot)."""
    if not spec or spec == "synthetic" or cv2 is None:
        return SyntheticSource(width, height)
    try:
        cam = CameraSource(spec, width=width, height=height)
    except Exception:
        return SyntheticSource(width, height)
    # give the grabber a brief moment to land a first frame; else fall back
    for _ in range(20):
        if cam.read() is not None:
            return cam
        time.sleep(0.05)
    if cam.connected:
        return cam  # connected but slow first frame — keep it
    cam.close()
    return SyntheticSource(width, height)
