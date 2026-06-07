"""Lightweight appearance match for re-acquiring a saved cat face."""

from __future__ import annotations

import base64


def thumb_similarity(jpeg_a: bytes, jpeg_b: bytes) -> float:
    """Return similarity in [0, 1] using HSV histogram correlation (higher = more alike)."""
    import cv2
    import numpy as np

    def _decode(buf: bytes) -> np.ndarray | None:
        arr = np.frombuffer(buf, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img

    a = _decode(jpeg_a)
    b = _decode(jpeg_b)
    if a is None or b is None:
        return 0.0
    size = (64, 64)
    a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    b = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    a_hsv = cv2.cvtColor(a, cv2.COLOR_BGR2HSV)
    b_hsv = cv2.cvtColor(b, cv2.COLOR_BGR2HSV)
    hist_a = cv2.calcHist([a_hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    hist_b = cv2.calcHist([b_hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(hist_a, hist_a)
    cv2.normalize(hist_b, hist_b)
    score = float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))
    if not np.isfinite(score):
        return 0.0
    return max(0.0, min(1.0, score))


def thumb_similarity_b64(jpeg_a_b64: str, jpeg_b_b64: str) -> float:
    return thumb_similarity(
        base64.standard_b64decode(jpeg_a_b64),
        base64.standard_b64decode(jpeg_b_b64),
    )
