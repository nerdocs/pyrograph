"""Filling an outline with lines, because a laser cannot fill anything else.

A raster device paints a filled shape by darkening pixels. A vector device has no such thing: it can only
move the spot, so an area is burnt by sweeping it back and forth across the inside. That is hatching, and
it is the only way a galvo marks a QR code — which is nothing but filled squares.

The sweep uses the even-odd rule, the same one the rasteriser uses (``job.py``), so a subpath inside
another cuts a hole rather than adding to it: the counter of an "o" stays unburnt, and so do the light
modules of a code.
"""

from __future__ import annotations

from math import cos, radians, sin

from .document import Point


def hatch(
    polylines: list[list[Point]], spacing_mm: float, angle_deg: float = 0.0
) -> list[list[Point]]:
    """Sweep the area enclosed by ``polylines`` with parallel lines ``spacing_mm`` apart.

    ``angle_deg`` turns the sweep; zero is horizontal. Lines alternate direction, so the spot runs to the
    end of one and starts the next where it already is — a galvo that returned to the same side every
    time would spend half the job travelling.

    Returns line segments, each a list of two points, in millimetres. An empty list means there was no
    enclosed area to fill, which is not an error: an open path encloses nothing.
    """
    if spacing_mm <= 0:
        raise ValueError(f"hatch spacing must be positive, got {spacing_mm}")

    turn = radians(-angle_deg)
    rotated = [[_turn(point, turn) for point in line] for line in polylines]
    edges = [edge for line in rotated for edge in zip(line, line[1:])]
    if not edges:
        return []

    ys = [point.y for line in rotated for point in line]
    back = radians(angle_deg)
    out: list[list[Point]] = []
    # Start half a step in, or half the height for a shape thinner than one step — beginning at the very
    # edge would miss a shape narrower than the spacing entirely, and a hairline shape is still a shape.
    y = min(ys) + min(spacing_mm, max(ys) - min(ys)) / 2
    flip = False
    while y <= max(ys):
        spans = _spans(edges, y)
        if flip:
            spans.reverse()
        for start, end in spans:
            if flip:
                start, end = end, start
            out.append([_turn(Point(start, y), back), _turn(Point(end, y), back)])
        flip = not flip
        y += spacing_mm
    return out


def _turn(point: Point, angle: float) -> Point:
    if not angle:
        return point
    c, s = cos(angle), sin(angle)
    return Point(point.x * c - point.y * s, point.x * s + point.y * c)


def _spans(edges, y: float) -> list[tuple[float, float]]:
    """Where the scan line at ``y`` is inside the shape, as ``(from, to)`` pairs.

    Each edge is counted on a half-open interval — its lower end belongs to it, its upper end does not.
    That is what stops a line passing exactly through a vertex from crossing twice and inverting
    everything to the right of it.
    """
    crossings = []
    for a, b in edges:
        low, high = (a, b) if a.y <= b.y else (b, a)
        if low.y <= y < high.y:
            crossings.append(low.x + (y - low.y) * (high.x - low.x) / (high.y - low.y))
    crossings.sort()
    return list(zip(crossings[::2], crossings[1::2]))
