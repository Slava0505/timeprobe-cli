from __future__ import annotations

import math

import pytest

from timeprobe.overlay import (
    PanelRenderer,
    center_ink,
    display_time,
    pause_coverage,
    play_coverage,
    triangle_coverage,
)


@pytest.mark.parametrize("scale", [1, 1.5, 4])
@pytest.mark.parametrize("hovered,paused", [(False, False), (True, False), (True, True)])
def test_palette_renderer_matches_original_compositing(scale, hovered, paused):
    width, height = round(124 * scale), round(48 * scale)
    mask = bytes((index * 37) % 256 for index in range(width * height))
    expected = bytearray()
    for y in range(height):
        for x in range(width):
            radius = 6 * scale
            distance = math.hypot(
                max(radius - x - 0.5, x + 0.5 - width + radius, 0),
                max(radius - y - 0.5, y + 0.5 - height + radius, 0),
            )
            coverage = max(0, min(1, radius + 0.5 - distance))
            alpha = mask[y * width + x] / 255 * (0.16 if hovered else 1)
            if hovered:
                icon = play_coverage if paused else pause_coverage
                icon_alpha = icon(x, y, width, height, scale)
                alpha = icon_alpha + alpha * (1 - icon_alpha)
            expected.extend(
                round((fg * alpha + bg * 0.76 * (1 - alpha)) * coverage)
                for fg, bg in ((201, 25), (230, 29), (216, 22))
            )
            expected.append(round((alpha + 0.76 * (1 - alpha)) * coverage * 255))
    renderer = PanelRenderer(width, height, scale)
    assert renderer.render(mask, hovered, paused) == bytes(expected)


@pytest.mark.parametrize("width,height", [(1, 1), (7, 9), (32, 17)])
def test_center_ink_preserves_sparse_and_full_masks(width, height):
    for mask in (
        bytes(width * height),
        bytes([255] * (width * height)),
        bytes(127 if index % 7 == 2 else 0 for index in range(width * height)),
    ):
        occupied = [index for index, value in enumerate(mask) if value]
        if not occupied:
            assert center_ink(mask, width, height) == mask
            continue
        left = min(index % width for index in occupied)
        right = max(index % width for index in occupied)
        top, bottom = occupied[0] // width, occupied[-1] // width
        dx = (width - (right - left + 1)) // 2 - left
        dy = (height - (bottom - top + 1)) // 2 - top
        expected = bytearray(width * height)
        for index in occupied:
            expected[(index // width + dy) * width + index % width + dx] = mask[index]
        assert center_ink(mask, width, height) == bytes(expected)


@pytest.mark.parametrize("scale", [1, 1.5, 2, 8])
def test_play_triangle_has_smooth_edges_and_preserves_area(scale):
    width, height = round(124 * scale), round(48 * scale)
    values = []
    for y in range(height):
        for x in range(width):
            coverage = play_coverage(x, y, width, height, scale)
            assert 0 <= coverage <= 1
            assert coverage == pytest.approx(play_coverage(x, height - 1 - y, width, height, scale))
            values.append(coverage)
    assert any(0 < value < 1 for value in values)
    assert max(values) == 1
    assert sum(values) == pytest.approx(11 * (11 * 0.72) * (scale * 1.4) ** 2, rel=0.03)


@pytest.mark.parametrize("scale", [1, 1.5, 2, 8])
def test_selected_pause_bar_dimensions_and_symmetry(scale):
    width, height = round(124 * scale), round(48 * scale)
    values = []
    for y in range(height):
        for x in range(width):
            coverage = pause_coverage(x, y, width, height, scale)
            assert 0 <= coverage <= 1
            assert coverage == pytest.approx(pause_coverage(width - 1 - x, y, width, height, scale))
            values.append(coverage)
    assert sum(values) == pytest.approx(2 * 6.5 * 21.5 * scale**2, rel=0.02)


@pytest.mark.parametrize("scale", [1, 1.5, 2, 8])
def test_triangle_has_smooth_symmetric_edges_and_preserves_area(scale):
    width, height = round(24 * scale), round(48 * scale)
    values = []
    for y in range(height):
        for x in range(width):
            coverage = triangle_coverage(x, y, scale, True)
            assert 0 <= coverage <= 1
            assert coverage == pytest.approx(triangle_coverage(x, height - 1 - y, scale, True))
            assert coverage == pytest.approx(triangle_coverage(width - 1 - x, y, scale, False))
            values.append(coverage)
    assert any(0 < value < 1 for value in values)
    assert max(values) == 1
    size = scale * 1.6
    area = 14 * 30 / 2 * size**2
    semiperimeter = (math.hypot(14, 15) + 15) * size
    rounded_loss = (2.5 * scale) ** 2 * (semiperimeter**2 / area - math.pi)
    assert sum(values) == pytest.approx(area - rounded_loss, rel=0.02)


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


def test_visible_ink_is_centered_instead_of_font_line_box():
    mask = bytearray(10 * 10)
    for y in (6, 7):
        for x in (1, 2, 3, 4):
            mask[y * 10 + x] = 255
    centered = center_ink(bytes(mask), 10, 10)
    points = [(i % 10, i // 10) for i, value in enumerate(centered) if value]
    assert min(x for x, _ in points) == 3
    assert max(x for x, _ in points) == 6
    assert min(y for _, y in points) == 4
    assert max(y for _, y in points) == 5
    assert sum(centered) == sum(mask)
