"""Display arithmetic shared by the native overlay and its tests."""

from __future__ import annotations

import math
from typing import Any


def center_ink(mask: bytes, width: int, height: int) -> bytes:
    """Center the visible pixels, independent of a font's ascender/descender metrics."""
    occupied = [index for index, value in enumerate(mask) if value]
    if not occupied:
        return mask
    left = min(index % width for index in occupied)
    right = max(index % width for index in occupied)
    top, bottom = occupied[0] // width, occupied[-1] // width
    dx = (width - (right - left + 1)) // 2 - left
    dy = (height - (bottom - top + 1)) // 2 - top
    centered = bytearray(width * height)
    for index in occupied:
        x, y = index % width + dx, index // width + dy
        if 0 <= x < width and 0 <= y < height:
            centered[y * width + x] = mask[index]
    return bytes(centered)


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
