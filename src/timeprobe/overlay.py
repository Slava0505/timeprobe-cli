"""Display arithmetic shared by the native overlay and its tests."""

from __future__ import annotations

import math
from typing import Any


def display_time(session: dict[str, Any], keep_hours: bool = False) -> tuple[str, bool]:
    target = session["target_seconds"]
    actual = session["elapsed_seconds"]
    if target is None:
        value, prefix = math.floor(actual), ""
    elif actual < target:
        value, prefix = math.ceil(target - actual), ""
    else:
        value, prefix = math.floor(actual - target), "+"
    hours, remaining = divmod(max(0, value), 3600)
    minutes, seconds = divmod(remaining, 60)
    wide = keep_hours or hours > 0
    text = f"{minutes:02d}:{seconds:02d}"
    if wide:
        text = f"{hours}:{text}"
    return prefix + text, wide
