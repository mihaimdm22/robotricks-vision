"""Frame sources — routing + the natural-sort ordering that keeps per-frame metrics aligned."""

from __future__ import annotations

import os

import numpy as np
import pytest

from catranger import io


def test_is_stream_classification() -> None:
    assert io.is_stream("rtsp://user:pass@host:554/stream1")
    assert io.is_stream("http://host/feed")
    assert not io.is_stream("data/clip.mp4")
    assert not io.is_stream("0")


def test_natural_key_orders_numerically() -> None:
    names = ["frame10.jpg", "frame2.jpg", "frame1.jpg"]
    assert sorted(names, key=io._natural_key) == ["frame1.jpg", "frame2.jpg", "frame10.jpg"]


def test_unknown_source_raises_value_error() -> None:
    pytest.importorskip("cv2")
    with pytest.raises(ValueError):
        list(io.frame_source("mystery.xyz"))


def test_image_dir_yielded_in_natural_order(tmp_path, monkeypatch) -> None:
    pytest.importorskip("cv2")
    for name in ["frame10.jpg", "frame2.jpg", "frame1.jpg"]:
        (tmp_path / name).write_bytes(b"x")

    seen: list[str] = []

    def fake_imread(path: str):
        seen.append(path)
        return np.zeros((2, 2, 3), dtype=np.uint8)

    monkeypatch.setattr(io.cv2, "imread", fake_imread)
    out = list(io.frame_source(str(tmp_path)))
    # os.path.basename, not rsplit("/"), so the assertion holds on Windows too
    # (paths come back with "\" there).
    assert [os.path.basename(p) for p in seen] == ["frame1.jpg", "frame2.jpg", "frame10.jpg"]
    assert len(out) == 3


def test_image_files_natural_order_and_filters(tmp_path) -> None:
    # listing only (no cv2): keep image exts, drop others, natural-sort by number.
    for name in ["frame10.jpg", "frame2.JPG", "frame1.png", "notes.txt", "clip.mp4"]:
        (tmp_path / name).write_bytes(b"x")
    names = [f.name for f in io.image_files(tmp_path)]
    assert names == ["frame1.png", "frame2.JPG", "frame10.jpg"]


def test_image_files_non_directory_returns_empty(tmp_path) -> None:
    f = tmp_path / "single.jpg"
    f.write_bytes(b"x")
    assert io.image_files(f) == []
    assert io.image_files(tmp_path / "missing") == []


def test_unreadable_image_raises_file_not_found(tmp_path, monkeypatch) -> None:
    pytest.importorskip("cv2")
    monkeypatch.setattr(io.cv2, "imread", lambda _p: None)
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        list(io.frame_source(str(f)))
