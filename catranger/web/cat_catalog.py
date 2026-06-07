"""Live cat catalog for the console — tracker ids, distances, and tiny crop thumbnails."""

from __future__ import annotations

import base64
import math
from typing import Any

import numpy as np

from catranger.types import CatObservation, FrameResult


def _bbox_center(xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = xyxy
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _bbox_moved_enough(
    xyxy: tuple[float, float, float, float],
    prev_xyxy: tuple[float, float, float, float] | None,
    *,
    min_shift_px: float = 10.0,
) -> bool:
    if prev_xyxy is None:
        return True
    cx, cy = _bbox_center(xyxy)
    px, py = _bbox_center(prev_xyxy)
    dx, dy = cx - px, cy - py
    return (dx * dx + dy * dy) ** 0.5 >= min_shift_px


def _obs_to_card(
    obs: CatObservation,
    *,
    frame_bgr: np.ndarray | None,
    thumb_px: int,
    locked_id: int | None,
    preferred_id: int | None,
    prev_thumb: str | None,
    prev_xyxy: tuple[float, float, float, float] | None,
    encode_thumbs: bool,
) -> dict[str, Any] | None:
    tid = obs.detection.track_id
    if tid is None:
        return None
    tid = int(tid)
    dist_m = None
    if obs.distance is not None and math.isfinite(obs.distance.meters):
        dist_m = round(float(obs.distance.meters), 2)
    thumb_b64 = prev_thumb
    xyxy_raw = obs.detection.xyxy
    xyxy: tuple[float, float, float, float] = (
        float(xyxy_raw[0]),
        float(xyxy_raw[1]),
        float(xyxy_raw[2]),
        float(xyxy_raw[3]),
    )
    refresh_thumb = (
        encode_thumbs
        and frame_bgr is not None
        and (not prev_thumb or _bbox_moved_enough(xyxy, prev_xyxy))
    )
    if refresh_thumb and frame_bgr is not None:
        thumb_b64 = _crop_thumb_b64(frame_bgr, xyxy, thumb_px) or prev_thumb
    return {
        "id": tid,
        "conf": round(float(obs.detection.conf), 2),
        "dist_m": dist_m,
        "bearing_deg": round(float(obs.bearing_deg), 1),
        "is_locked": locked_id is not None and tid == int(locked_id),
        "is_preferred": preferred_id is not None and tid == int(preferred_id),
        "thumb_jpeg_b64": thumb_b64,
        "area": float(obs.detection.area),
        "_xyxy": xyxy,
    }


def _merge_prev_card_fields(card: dict[str, Any], prev: dict[str, Any] | None) -> None:
    """Carry stable client fields across catalog rebuilds (avoid UI flicker)."""
    if not prev:
        return
    if prev.get("library_id") is not None and card.get("library_id") is None:
        card["library_id"] = prev["library_id"]


def build_cat_catalog(
    frame_bgr: np.ndarray | None,
    result: FrameResult | None,
    *,
    locked_id: int | None,
    preferred_id: int | None,
    previous: list[dict[str, Any]] | None = None,
    encode_thumbs: bool = True,
    max_cats: int = 8,
    thumb_px: int = 72,
) -> list[dict[str, Any]]:
    """Return sorted cat cards for telemetry (largest first).

    Cards are built from live observations plus the followed target (which may be
    coasting off-frame). Known tracker ids are kept from ``previous`` across brief
    dropouts so the picker stays in sync with telemetry/LCD target ids.
    """
    prev_by_id = {int(c["id"]): c for c in (previous or []) if c.get("id") is not None}
    if result is None:
        return list(previous or [])

    cards_by_id: dict[int, dict[str, Any]] = {}

    def ingest(obs: CatObservation) -> None:
        prev = prev_by_id.get(int(obs.track_id)) if obs.track_id is not None else None
        card = _obs_to_card(
            obs,
            frame_bgr=frame_bgr,
            thumb_px=thumb_px,
            locked_id=locked_id,
            preferred_id=preferred_id,
            prev_thumb=(prev or {}).get("thumb_jpeg_b64") if prev else None,
            prev_xyxy=(prev or {}).get("_xyxy") if prev else None,
            encode_thumbs=encode_thumbs,
        )
        if card is not None:
            _merge_prev_card_fields(card, prev)
            cards_by_id[card["id"]] = card

    def synthetic_card(tid: int) -> dict[str, Any]:
        old = prev_by_id.get(tid) or {}
        card = {
            "id": tid,
            "conf": round(float(old.get("conf", 0.0)), 2),
            "dist_m": old.get("dist_m"),
            "bearing_deg": round(float(old.get("bearing_deg", 0.0)), 1),
            "is_locked": locked_id is not None and tid == int(locked_id),
            "is_preferred": preferred_id is not None and tid == int(preferred_id),
            "thumb_jpeg_b64": old.get("thumb_jpeg_b64"),
            "area": float(old.get("area", 0.0)),
        }
        if old.get("library_id") is not None:
            card["library_id"] = old["library_id"]
        return card

    for obs in result.observations:
        ingest(obs)

    # Followed target may be coasting (not in observations this frame).
    target = result.target
    if target is not None and target.track_id is not None:
        ingest(target)

    known_ids = {int(i) for i in (result.target_known_ids or [])}
    for kid in known_ids:
        if kid in cards_by_id:
            continue
        if kid in prev_by_id:
            old = dict(prev_by_id[kid])
            old["is_locked"] = locked_id is not None and kid == int(locked_id)
            old["is_preferred"] = preferred_id is not None and kid == int(preferred_id)
            if "area" not in old:
                old["area"] = 0.0
            _merge_prev_card_fields(old, prev_by_id.get(kid))
            cards_by_id[kid] = old
        else:
            cards_by_id[kid] = synthetic_card(kid)

    if preferred_id is not None:
        pid = int(preferred_id)
        if pid not in cards_by_id:
            cards_by_id[pid] = synthetic_card(pid)
            cards_by_id[pid]["is_preferred"] = True

    if not cards_by_id:
        return []

    cards = sorted(cards_by_id.values(), key=lambda c: float(c.get("area", 0)), reverse=True)
    out = cards[: max(1, int(max_cats))]
    for c in out:
        c.pop("area", None)
    return out


def _crop_thumb_b64(
    frame_bgr: np.ndarray,
    xyxy: tuple[float, float, float, float],
    thumb_px: int,
) -> str | None:
    import cv2

    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in xyxy)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    thumb = cv2.resize(crop, (thumb_px, thumb_px), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 72])
    if not ok:
        return None
    return base64.standard_b64encode(buf.tobytes()).decode("ascii")
