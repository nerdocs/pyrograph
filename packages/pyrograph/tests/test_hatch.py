"""Filling an outline with lines.

The interesting cases are the ones a scan line gets wrong: a hole that must stay unburnt, and a vertex
the line passes exactly through, which counts twice if the intervals are not half-open and inverts
everything to the right of it.
"""

import pytest

from pyrograph.document import Point
from pyrograph.hatch import hatch


def square(x, y, size):
    return [
        Point(x, y),
        Point(x + size, y),
        Point(x + size, y + size),
        Point(x, y + size),
        Point(x, y),
    ]


def spans_at(lines, y, tolerance=1e-6):
    """The x ranges covered at height ``y``, sorted."""
    out = []
    for line in lines:
        if abs(line[0].y - y) < tolerance and abs(line[1].y - y) < tolerance:
            out.append(tuple(sorted((line[0].x, line[1].x))))
    return sorted(out)


def test_a_square_is_filled_across_its_width():
    lines = hatch([square(0, 0, 10)], spacing_mm=1.0)

    assert lines, "nothing was filled"
    for line in lines:
        assert len(line) == 2
        assert min(p.x for p in line) == pytest.approx(0.0)
        assert max(p.x for p in line) == pytest.approx(10.0)


def test_the_spacing_is_what_was_asked_for():
    heights = sorted({round(line[0].y, 6) for line in hatch([square(0, 0, 10)], spacing_mm=2.0)})

    gaps = [b - a for a, b in zip(heights, heights[1:])]
    assert all(gap == pytest.approx(2.0) for gap in gaps)


def test_a_thin_shape_still_gets_a_line():
    """Starting the sweep at the very edge would miss anything thinner than one step."""
    lines = hatch([square(0, 0, 0.4)], spacing_mm=1.0)

    assert len(lines) == 1


def test_a_hole_stays_unburnt():
    """Even-odd, the same rule the rasteriser uses: a subpath inside another one cuts the area away."""
    ring = [square(0, 0, 10), square(3, 3, 4)]

    lines = hatch(ring, spacing_mm=1.0)

    spans = spans_at(lines, 5.5)
    assert len(spans) == 2, f"the hole was filled in: {spans}"
    assert spans[0] == pytest.approx((0.0, 3.0))
    assert spans[1] == pytest.approx((7.0, 10.0))


def test_two_separate_shapes_are_both_filled():
    lines = hatch([square(0, 0, 4), square(10, 0, 4)], spacing_mm=1.0)

    spans = spans_at(lines, 2.5)
    assert len(spans) == 2
    assert spans[0] == pytest.approx((0.0, 4.0))
    assert spans[1] == pytest.approx((10.0, 14.0))


def test_a_scan_line_through_a_vertex_does_not_invert_the_rest():
    """A diamond: at its widest point the line meets two vertices exactly.

    Counted twice, the inside and the outside swap and everything to the right burns instead.
    """
    diamond = [Point(5, 0), Point(10, 5), Point(5, 10), Point(0, 5), Point(5, 0)]

    lines = hatch([diamond], spacing_mm=0.5)

    for line in lines:
        assert min(p.x for p in line) >= -1e-6
        assert max(p.x for p in line) <= 10 + 1e-6
    for height in {round(line[0].y, 6) for line in lines}:
        assert len(spans_at(lines, height)) == 1, f"the inside broke apart at y={height}"
    widest = max(abs(line[1].x - line[0].x) for line in lines)
    assert widest == pytest.approx(10.0, abs=0.6), "the middle of the diamond should be the widest span"


def test_lines_alternate_direction():
    """The spot starts the next line where it finished the last one, instead of flying back."""
    lines = hatch([square(0, 0, 10)], spacing_mm=1.0)

    forwards = [line[0].x < line[1].x for line in lines]
    assert forwards[:4] == [True, False, True, False]


def test_the_angle_turns_the_sweep():
    """At ninety degrees the lines run up and down instead of across."""
    lines = hatch([square(0, 0, 10)], spacing_mm=1.0, angle_deg=90.0)

    assert lines
    for line in lines:
        assert line[0].x == pytest.approx(line[1].x, abs=1e-6), "the line is not vertical"


def test_an_open_path_encloses_nothing():
    """Not an error — a line has no inside, so there is nothing to fill."""
    assert hatch([[Point(0, 0), Point(10, 10)]], spacing_mm=1.0) == []


def test_no_geometry_fills_nothing():
    assert hatch([], spacing_mm=1.0) == []


def test_a_spacing_of_zero_is_refused():
    """It would be an infinite number of lines, so it has to be caught rather than attempted."""
    with pytest.raises(ValueError):
        hatch([square(0, 0, 10)], spacing_mm=0.0)
