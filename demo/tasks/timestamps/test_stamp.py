from datetime import datetime, timezone

from stamp import iso_utc


def test_timestamps_use_z_suffix_not_offset():
    dt = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert iso_utc(dt) == "2026-06-28T12:00:00Z"
