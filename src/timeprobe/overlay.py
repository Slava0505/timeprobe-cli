"""Display arithmetic shared by the native overlay and its tests."""

from __future__ import annotations

import math
from typing import Any


def triangle_coverage(x: int, y: int, scale: float, points_left: bool) -> float:
    """160% edge triangle with 2.5-pixel rounded corners and antialiased edges."""
    size = scale * 1.6
    radius = 2.5 * scale
    px = x + 0.5
    if not points_left:
        px = 24 * scale - px
    py = abs(y + 0.5 - 24 * scale)
    # Inset the triangle by the corner radius, then expand its signed distance.
    # This preserves straight edges and rounds all three corners with circular arcs.
    left = 12 * scale - 7 * size + radius * math.hypot(14, 15) / 15
    right = 12 * scale + 7 * size - radius
    width = right - left
    half_height = width * 15 / 14
    px -= left
    projection = max(0.0, min(1.0, (px * width + py * half_height) / (width**2 + half_height**2)))
    diagonal = math.hypot(px - projection * width, py - projection * half_height)
    vertical = math.hypot(px - width, max(0.0, py - half_height))
    distance = min(diagonal, vertical)
    if px > width or py > px * 15 / 14:
        distance = -distance
    return max(0.0, min(1.0, distance + radius + 0.5))


def play_coverage(x: int, y: int, width: int, height: int, scale: float) -> float:
    """Antialiased coverage for the resume triangle centered in the timer."""
    scale *= 1.4
    px = x + 0.5 - width / 2
    py = abs(y + 0.5 - height / 2)
    diagonal = ((7 * scale - px) * 0.72 - py) / math.hypot(1, 0.72)
    distance = min(px + 4 * scale, 7 * scale - px, diagonal)
    return max(0.0, min(1.0, distance + 0.5))


def pause_coverage(x: int, y: int, width: int, height: int, scale: float) -> float:
    """Two 6.5-by-21.5 bars with a six-pixel gap, in base widget units."""
    px = abs(x + 0.5 - width / 2)
    py = abs(y + 0.5 - height / 2)
    distance = min(3.25 * scale - abs(px - 6.25 * scale), 10.75 * scale - py)
    return max(0.0, min(1.0, distance + 0.5))


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
