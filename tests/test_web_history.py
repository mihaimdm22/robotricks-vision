"""DistanceStore: append-only sqlite log behind the live history chart."""

from __future__ import annotations

from catranger.web.store import DistanceStore


def _store() -> DistanceStore:
    return DistanceStore(":memory:")


def test_record_and_recent_chronological() -> None:
    s = _store()
    for i in range(5):
        s.record(
            ts=100.0 + i,
            est_m=1.0 + i,
            lo=0.9 + i,
            hi=1.1 + i,
            gt_cm=None,
            target_id=7,
            mode="MANUAL",
        )
    rows = s.recent()
    assert [r["ts"] for r in rows] == [100.0, 101.0, 102.0, 103.0, 104.0]
    assert rows[0]["est_m"] == 1.0
    assert rows[0]["target_id"] == 7
    assert rows[0]["mode"] == "MANUAL"
    s.close()


def test_recent_limit_keeps_newest_ascending() -> None:
    s = _store()
    for i in range(10):
        s.record(
            ts=float(i), est_m=float(i), lo=None, hi=None, gt_cm=None, target_id=None, mode="IDLE"
        )
    rows = s.recent(limit=3)
    assert [r["ts"] for r in rows] == [7.0, 8.0, 9.0]  # last 3, oldest-first
    s.close()


def test_recent_since_filters() -> None:
    s = _store()
    for i in range(5):
        s.record(
            ts=float(i), est_m=float(i), lo=None, hi=None, gt_cm=None, target_id=None, mode="IDLE"
        )
    rows = s.recent(since=2.0)
    assert [r["ts"] for r in rows] == [3.0, 4.0]
    s.close()


def test_nullable_columns_roundtrip() -> None:
    s = _store()
    s.record(ts=1.0, est_m=2.0, lo=None, hi=None, gt_cm=186.0, target_id=None, mode=None)
    (row,) = s.recent()
    assert (
        row["lo"] is None and row["hi"] is None and row["target_id"] is None and row["mode"] is None
    )
    assert row["gt_cm"] == 186.0
    s.close()
