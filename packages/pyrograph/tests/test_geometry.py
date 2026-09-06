"""Geometry: transform composition and exact bounding boxes.

The expected values are computed by hand in the comments, not taken from a previous run.
"""

import math

from pyrograph.document import CubicTo, LineTo, MoveTo, Path, Point, Rect, Transform


def test_composition_applies_the_first_transform_first():
    # Move by (2, 3), then scale by 10 → (0, 0) lands on (20, 30).
    combined = Transform.translate(2, 3).then(Transform.scale(10))
    assert combined.apply(Point(0, 0)) == Point(20, 30)
    # The other order scales first → (2, 3).
    other = Transform.scale(10).then(Transform.translate(2, 3))
    assert other.apply(Point(0, 0)) == Point(2, 3)


def test_inverse_undoes_the_transform():
    transform = Transform.translate(4, -2).then(Transform.rotate(30)).then(Transform.scale(3, 5))
    point = transform.apply(Point(7, 11))
    back = transform.inverse().apply(point)
    assert math.isclose(back.x, 7, abs_tol=1e-9)
    assert math.isclose(back.y, 11, abs_tol=1e-9)


def test_rotated_square_bounds_grow_to_the_diagonal():
    # A 10 mm square turned 45° around its centre: the bounding box is the diagonal, 10·√2.
    square = Path.rect(0, 0, 10, 10)
    rotated = square.transformed(Transform.rotate(45, Point(5, 5)))
    box = rotated.bounds()
    diagonal = 10 * math.sqrt(2)
    assert math.isclose(box.width, diagonal, abs_tol=1e-9)
    assert math.isclose(box.height, diagonal, abs_tol=1e-9)
    assert math.isclose(box.x, 5 - diagonal / 2, abs_tol=1e-9)
    assert math.isclose(box.y, 5 - diagonal / 2, abs_tol=1e-9)


def test_cubic_bounds_use_the_curve_not_the_control_points():
    # Symmetric arch from (0,0) to (10,0) with both handles at y = 10.
    # B(0.5).y = 3/8·10 + 3/8·10 = 7.5 — well below the control points.
    path = Path([MoveTo(Point(0, 0)), CubicTo(Point(0, 10), Point(10, 10), Point(10, 0))])
    box = path.bounds()
    assert math.isclose(box.height, 7.5, abs_tol=1e-9)
    assert math.isclose(box.width, 10.0, abs_tol=1e-9)


def test_rect_union_covers_both():
    assert Rect(0, 0, 10, 10).union(Rect(20, -5, 10, 10)) == Rect(0, -5, 30, 15)


def test_path_survives_the_svg_round_trip():
    path = Path(
        [
            MoveTo(Point(1.5, -2.25)),
            LineTo(Point(10.0, 0.0)),
            CubicTo(Point(1, 2), Point(3, 4), Point(5.5, 6.5)),
        ]
    )
    assert Path.from_svg_d(path.to_svg_d()) == path


def test_transform_survives_the_svg_round_trip():
    transform = Transform.rotate(17.5, Point(3, 4))
    assert Transform.from_svg(transform.to_svg()) == transform
