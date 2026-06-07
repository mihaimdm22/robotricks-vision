"""Frame sources. One generator handles an image dir, a single image, a video file,
an RTSP stream (Tapo C211), or a webcam index — so the rest of the code never cares
where frames come from.

    for idx, frame_bgr in frame_source("data/cat_demo.mp4"):
        ...
    for idx, frame_bgr in frame_source("rtsp://user:pass@192.168.1.50:554/stream1"):
        ...
    for idx, frame_bgr in frame_source("0"):           # webcam
        ...
    for idx, frame_bgr in frame_source("data/raw/how_far"):  # image directory
        ...
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


def _require_cv2() -> None:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for frame I/O (pip install opencv-python)")


def is_stream(source: str) -> bool:
    return str(source).lower().startswith(("rtsp://", "http://", "https://", "udp://"))


def image_files(path: str | Path) -> list[Path]:
    """Image files in a directory, in the SAME natural-sorted order frame_source yields
    them — so a distance-GT sidecar (catranger.eval.gts) can be keyed by that 0-based
    index. Returns [] for a non-directory. Stdlib only (no cv2): lists, never reads."""
    p = Path(path)
    if not p.is_dir():
        return []
    return sorted(
        (f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS),
        key=lambda f: _natural_key(f.name),
    )


def frame_source(
    source: str, stride: int = 1, max_frames: int = 0
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield (index, frame_bgr). `stride` skips frames (video/stream only);
    `max_frames` caps the count (0 = unlimited)."""
    _require_cv2()
    s = str(source)

    # webcam index
    if s.isdigit():
        yield from _from_capture(int(s), stride, max_frames)
        return

    # network stream
    if is_stream(s):
        yield from _from_capture(s, stride, max_frames, backend=cv2.CAP_FFMPEG)
        return

    p = Path(s)
    if p.is_dir():
        for i, f in enumerate(image_files(p)):
            if max_frames and i >= max_frames:
                break
            img = cv2.imread(str(f))
            if img is not None:
                yield i, img
        return

    if p.suffix.lower() in IMAGE_EXTS:
        img = cv2.imread(str(p))
        if img is None:
            raise FileNotFoundError(f"could not read image {p}")
        yield 0, img
        return

    if p.suffix.lower() in VIDEO_EXTS:
        yield from _from_capture(str(p), stride, max_frames)
        return

    raise ValueError(f"unrecognized source: {source}")


def _from_capture(target, stride, max_frames, backend=None):
    cap = cv2.VideoCapture(target, backend) if backend is not None else cv2.VideoCapture(target)
    if not cap.isOpened():
        raise RuntimeError(f"could not open capture: {target}")
    idx, emitted = 0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % max(1, stride) == 0:
                yield emitted, frame
                emitted += 1
                if max_frames and emitted >= max_frames:
                    break
            idx += 1
    finally:
        cap.release()


def source_meta(source: str) -> dict:
    """Best-effort (width, height, fps, nframes) for a video/stream; empty for images."""
    _require_cv2()
    s = str(source)
    if Path(s).is_dir() or Path(s).suffix.lower() in IMAGE_EXTS:
        return {}
    cap = cv2.VideoCapture(int(s) if s.isdigit() else s)
    meta = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": float(cap.get(cv2.CAP_PROP_FPS)),
        "nframes": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    cap.release()
    return meta


def _natural_key(name: str):
    import re

    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]
