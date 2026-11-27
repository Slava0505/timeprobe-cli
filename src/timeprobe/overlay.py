"""Display arithmetic shared by the native overlay and its tests."""

from __future__ import annotations

import math
from typing import Any


def panel_pixel(alpha: float, coverage: float = 1.0) -> bytes:
    """Premultiplied BGRA, shared by the cached palette and antialiased borders."""
    return bytes(
        [
            round((foreground * alpha + background * 0.76 * (1 - alpha)) * coverage)
            for foreground, background in ((201, 25), (230, 29), (216, 22))
        ]
        + [round((alpha + 0.76 * (1 - alpha)) * coverage * 255)]
    )


class PanelRenderer:
    """Cache geometry; composite changing glyph masks through a 256-color palette."""

    def __init__(self, width: int, height: int, scale: float):
        self.width, self.height, self.scale = width, height, scale
        self.palettes = {
            hovered: tuple(
                panel_pixel(value / 255 * (0.16 if hovered else 1)) for value in range(256)
            )
            for hovered in (False, True)
        }
        self.tables = {
            hovered: tuple(bytes(pixel[channel] for pixel in palette) for channel in range(4))
            for hovered, palette in self.palettes.items()
        }
        self.corners = []
        self.icons = {paused: self.icon_geometry(paused) for paused in (False, True)}
        radius = 6 * scale
        corner = min(math.ceil(6 * scale + 1), width // 2, height // 2)
        for y in (*range(corner), *range(height - corner, height)):
            for x in (*range(corner), *range(width - corner, width)):
                distance = math.hypot(
                    max(radius - x - 0.5, x + 0.5 - width + radius, 0),
                    max(radius - y - 0.5, y + 0.5 - height + radius, 0),
                )
                coverage = max(0.0, min(1.0, radius + 0.5 - distance))
                if coverage < 1:
                    self.corners.append((y * width + x, coverage))

    def icon_geometry(self, paused: bool):
        icon = play_coverage if paused else pause_coverage
        runs, edges = [], []
        for y in range(
            max(0, int(self.height / 2 - 16 * self.scale)),
            min(self.height, math.ceil(self.height / 2 + 16 * self.scale)),
        ):
            start = None
            end = min(self.width, math.ceil(self.width / 2 + 16 * self.scale))
            for x in range(max(0, int(self.width / 2 - 16 * self.scale)), end):
                coverage = icon(x, y, self.width, self.height, self.scale)
                if coverage == 1:
                    if start is None:
                        start = x
                else:
                    if start is not None:
                        runs.append(
                            (
                                (y * self.width + start) * 4,
                                (y * self.width + x) * 4,
                                panel_pixel(1) * (x - start),
                            )
                        )
                        start = None
                    if coverage > 0:
                        edges.append((y * self.width + x, coverage))
            if start is not None:
                runs.append(
                    (
                        (y * self.width + start) * 4,
                        (y * self.width + end) * 4,
                        panel_pixel(1) * (end - start),
                    )
                )
        return runs, edges

    def render(self, mask: bytes, hovered: bool, paused: bool) -> bytes:
        pixels = bytearray(len(mask) * 4)
        for channel, table in enumerate(self.tables[hovered]):
            pixels[channel::4] = mask.translate(table)
        if hovered:
            runs, edges = self.icons[paused]
            for start, end, pixel_run in runs:
                pixels[start:end] = pixel_run
            for index, coverage in edges:
                alpha = coverage + mask[index] / 255 * 0.16 * (1 - coverage)
                pixels[index * 4 : index * 4 + 4] = panel_pixel(alpha)
        for index, coverage in self.corners:
            alpha = mask[index] / 255 * (0.16 if hovered else 1)
            pixels[index * 4 : index * 4 + 4] = panel_pixel(alpha, coverage)
        return bytes(pixels)


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
    rows = []
    for y in range(height):
        row = mask[y * width : (y + 1) * width]
        trimmed = row.strip(b"\0")
        if trimmed:
            left = width - len(row.lstrip(b"\0"))
            rows.append((y, left, left + len(trimmed), row))
    if not rows:
        return mask
    left = min(row[1] for row in rows)
    right = max(row[2] for row in rows)
    dx = (width - (right - left)) // 2 - left
    dy = (height - (rows[-1][0] - rows[0][0] + 1)) // 2 - rows[0][0]
    centered = bytearray(width * height)
    for y, _, _, row in rows:
        start = (y + dy) * width + left + dx
        centered[start : start + right - left] = row[left:right]
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
