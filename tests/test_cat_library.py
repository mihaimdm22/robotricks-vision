"""Cat library store and appearance match."""

from __future__ import annotations

import numpy as np
import pytest

from catranger.web.cat_library import CatLibraryStore
from catranger.web.cat_match import thumb_similarity


def test_cat_library_upsert_and_list(tmp_path) -> None:
    db = tmp_path / "cats.sqlite3"
    store = CatLibraryStore(str(db))
    cid = store.upsert_sighting(
        library_id=None,
        tracker_id=7,
        thumb_jpeg=b"jpeg-bytes",
        conf=0.9,
        dist_m=1.2,
        bearing_deg=5.0,
    )
    assert cid == 1
    cid2 = store.upsert_sighting(
        library_id=cid,
        tracker_id=7,
        thumb_jpeg=b"jpeg-bytes-2",
        conf=0.95,
        dist_m=1.1,
        bearing_deg=4.0,
    )
    assert cid2 == cid
    rows = store.list_cats()
    assert len(rows) == 1
    assert rows[0]["name"] == "Cat #7"
    assert rows[0]["sighting_count"] == 2
    assert store.rename(cid, "Mittens")
    detail = store.get(cid)
    assert detail is not None and detail["name"] == "Mittens"
    assert store.delete(cid)
    assert store.get(cid) is None
    store.close()


def test_thumb_similarity_identical_jpeg() -> None:
    pytest.importorskip("cv2")
    import cv2

    img = np.zeros((80, 80, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (70, 70), (0, 128, 255), -1)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    data = buf.tobytes()
    score = thumb_similarity(data, data)
    assert score > 0.99


def test_cat_library_merges_same_face_new_tracker(tmp_path) -> None:
    """A new tracker id for the same cat should match an existing library row."""
    pytest.importorskip("cv2")
    import cv2

    img = np.zeros((80, 80, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 10), (70, 70), (180, 120, 90), -1)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    thumb = buf.tobytes()

    store = CatLibraryStore(str(tmp_path / "cats.sqlite3"))
    first = store.upsert_sighting(
        library_id=None,
        tracker_id=1,
        thumb_jpeg=thumb,
        conf=0.9,
        dist_m=1.0,
        bearing_deg=0.0,
    )
    matched = store.match_by_thumb(thumb, threshold=0.55)
    assert matched == first

    second = store.upsert_sighting(
        library_id=matched,
        tracker_id=4,
        thumb_jpeg=thumb,
        conf=0.88,
        dist_m=1.1,
        bearing_deg=2.0,
    )
    assert second == first
    rows = store.list_cats()
    assert len(rows) == 1
    assert rows[0]["sighting_count"] == 2
    assert rows[0]["last_tracker_id"] == 4
    store.close()
