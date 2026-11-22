from __future__ import annotations

import pytest

from timeprobe.overlay import display_time


@pytest.mark.parametrize(
    "actual,target,expected",
    [
        (0, None, "00:00"),
        (65.9, None, "01:05"),
        (3601.2, None, "1:00:01"),
        (742.2, 1800, "17:38"),
        (1799.1, 1800, "00:01"),
        (1800, 1800, "+00:00"),
        (1943.8, 1800, "+02:23"),
        (5461, 1800, "+1:01:01"),
    ],
)
def test_display_countdown_elapsed_and_overtime(actual, target, expected):
    assert display_time({"elapsed_seconds": actual, "target_seconds": target})[0] == expected


def test_hours_layout_does_not_shrink_at_hour_boundary():
    initial = {"elapsed_seconds": 0, "target_seconds": 3601}
    assert display_time(initial) == ("1:00:01", True)
    later = {"elapsed_seconds": 2, "target_seconds": 3601}
    assert display_time(later, keep_hours=True) == ("0:59:59", True)
