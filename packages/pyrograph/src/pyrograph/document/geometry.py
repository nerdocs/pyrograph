"""Geometry primitives of the document model.

Everything here is measured in **millimetres**. The coordinate system matches SVG's: x grows to the right,
y grows downwards, the origin sits in the top left corner of the work area. No pixels, no DPI — those enter
only when a job is built (``pyrograph.job``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


def _num(value: float) -> str:
    """Format a number for SVG so that reading it back yields the same float."""
    return repr(float(value))


@dataclass(frozen=True)
class Point:
    """A position in millimetres."""

    x: float = 0.0
    y: float = 0.0


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in millimetres."""

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @classmethod
    def from_points(cls, points: list[Point]) -> "Rect":
        """The smallest rectangle containing all ``points``."""
        if not points:
            raise ValueError("cannot build a rectangle from no points")
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        return cls(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def union(self, other: "Rect") -> "Rect":
        """The smallest rectangle containing both."""
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return Rect(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)


@dataclass(frozen=True)
class Transform:
    """A 2D affine transform, stored as SVG stores it: ``matrix(a b c d e f)``.

    The full 3×3 matrix is ``[[a, c, e], [b, d, f], [0, 0, 1]]``; the bottom row is constant, so only six
    numbers are kept.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def translate(cls, dx: float, dy: float) -> "Transform":
        return cls(e=dx, f=dy)

    @classmethod
    def scale(cls, sx: float, sy: float | None = None) -> "Transform":
        return cls(a=sx, d=sx if sy is None else sy)

    @classmethod
    def rotate(cls, degrees: float, origin: Point | None = None) -> "Transform":
        """Rotate clockwise (the visual direction in a y-down coordinate system) around ``origin``."""
        rad = math.radians(degrees)
        cos, sin = math.cos(rad), math.sin(rad)
        rotation = cls(a=cos, b=sin, c=-sin, d=cos)
        if origin is None:
            return rotation
        return cls.translate(-origin.x, -origin.y).then(rotation).then(cls.translate(origin.x, origin.y))

    def then(self, other: "Transform") -> "Transform":
        """Apply ``self`` first, then ``other`` — the matrix product ``other · self``."""
        return Transform(
            a=other.a * self.a + other.c * self.b,
            b=other.b * self.a + other.d * self.b,
            c=other.a * self.c + other.c * self.d,
            d=other.b * self.c + other.d * self.d,
            e=other.a * self.e + other.c * self.f + other.e,
            f=other.b * self.e + other.d * self.f + other.f,
        )

    def apply(self, point: Point) -> Point:
        return Point(
            self.a * point.x + self.c * point.y + self.e,
            self.b * point.x + self.d * point.y + self.f,
        )

    def inverse(self) -> "Transform":
        det = self.a * self.d - self.b * self.c
        if det == 0.0:
            raise ValueError("transform is not invertible")
        return Transform(
            a=self.d / det,
            b=-self.b / det,
            c=-self.c / det,
            d=self.a / det,
            e=(self.c * self.f - self.d * self.e) / det,
            f=(self.b * self.e - self.a * self.f) / det,
        )

    @property
    def is_identity(self) -> bool:
        return self == Transform()

    def to_svg(self) -> str:
        return "matrix({})".format(" ".join(_num(v) for v in (self.a, self.b, self.c, self.d, self.e, self.f)))

    @classmethod
    def from_svg(cls, text: str) -> "Transform":
        """Read back what :meth:`to_svg` wrote. Only the ``matrix(…)`` form is understood."""
        match = re.fullmatch(r"\s*matrix\(([^)]*)\)\s*", text)
        if not match:
            raise ValueError(f"unsupported transform: {text!r}")
        values = [float(v) for v in match.group(1).replace(",", " ").split()]
        if len(values) != 6:
            raise ValueError(f"a matrix needs six numbers, got {len(values)}")
        return cls(*values)


# --------------------------------------------------------------------------------------- path segments


@dataclass(frozen=True)
class MoveTo:
    point: Point


@dataclass(frozen=True)
class LineTo:
    point: Point


@dataclass(frozen=True)
class CubicTo:
    """A cubic Bézier from the current point via two control points to ``point``."""

    control1: Point
    control2: Point
    point: Point


@dataclass(frozen=True)
class Close:
    pass


Segment = MoveTo | LineTo | CubicTo | Close


def _cubic_extrema(p0: float, p1: float, p2: float, p3: float) -> list[float]:
    """The values a cubic Bézier coordinate takes at its endpoints and at its local extrema."""
    values = [p0, p3]
    # B'(t)/3 = A·t² + B·t + C
    qa = -p0 + 3 * p1 - 3 * p2 + p3
    qb = 2 * p0 - 4 * p1 + 2 * p2
    qc = p1 - p0
    if abs(qa) < 1e-12:
        roots = [-qc / qb] if abs(qb) > 1e-12 else []
    else:
        disc = qb * qb - 4 * qa * qc
        if disc < 0:
            roots = []
        else:
            sq = math.sqrt(disc)
            roots = [(-qb + sq) / (2 * qa), (-qb - sq) / (2 * qa)]
    for t in roots:
        if 0.0 < t < 1.0:
            u = 1.0 - t
            values.append(u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3)
    return values


def _cubic_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    return Point(
        u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
        u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
    )


@dataclass
class Path:
    """A sequence of segments, possibly consisting of several subpaths."""

    segments: list[Segment] = field(default_factory=list)

    @classmethod
    def rect(cls, x: float, y: float, width: float, height: float) -> "Path":
        return cls(
            [
                MoveTo(Point(x, y)),
                LineTo(Point(x + width, y)),
                LineTo(Point(x + width, y + height)),
                LineTo(Point(x, y + height)),
                Close(),
            ]
        )

    def transformed(self, transform: Transform) -> "Path":
        out: list[Segment] = []
        for seg in self.segments:
            if isinstance(seg, MoveTo):
                out.append(MoveTo(transform.apply(seg.point)))
            elif isinstance(seg, LineTo):
                out.append(LineTo(transform.apply(seg.point)))
            elif isinstance(seg, CubicTo):
                out.append(
                    CubicTo(
                        transform.apply(seg.control1),
                        transform.apply(seg.control2),
                        transform.apply(seg.point),
                    )
                )
            else:
                out.append(seg)
        return Path(out)

    def bounds(self) -> Rect:
        """The tight bounding box. Bézier curves contribute their true extrema, not their control points."""
        xs: list[float] = []
        ys: list[float] = []
        current = Point()
        for seg in self.segments:
            if isinstance(seg, (MoveTo, LineTo)):
                xs.append(seg.point.x)
                ys.append(seg.point.y)
                current = seg.point
            elif isinstance(seg, CubicTo):
                xs += _cubic_extrema(current.x, seg.control1.x, seg.control2.x, seg.point.x)
                ys += _cubic_extrema(current.y, seg.control1.y, seg.control2.y, seg.point.y)
                current = seg.point
        if not xs:
            return Rect()
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def polylines(self, steps: int = 16) -> list[list[Point]]:
        """Flatten to polylines — one per subpath. Used by the rasteriser, not by the model."""
        lines: list[list[Point]] = []
        current: list[Point] = []
        start = Point()
        for seg in self.segments:
            if isinstance(seg, MoveTo):
                if len(current) > 1:
                    lines.append(current)
                start = seg.point
                current = [seg.point]
            elif isinstance(seg, LineTo):
                current.append(seg.point)
            elif isinstance(seg, CubicTo):
                p0 = current[-1] if current else Point()
                for i in range(1, steps + 1):
                    current.append(_cubic_point(p0, seg.control1, seg.control2, seg.point, i / steps))
            elif isinstance(seg, Close) and current:
                current.append(start)
                lines.append(current)
                current = [start]
        if len(current) > 1:
            lines.append(current)
        return lines

    def to_svg_d(self) -> str:
        parts: list[str] = []
        for seg in self.segments:
            if isinstance(seg, MoveTo):
                parts.append(f"M {_num(seg.point.x)} {_num(seg.point.y)}")
            elif isinstance(seg, LineTo):
                parts.append(f"L {_num(seg.point.x)} {_num(seg.point.y)}")
            elif isinstance(seg, CubicTo):
                parts.append(
                    "C {} {} {} {} {} {}".format(
                        _num(seg.control1.x),
                        _num(seg.control1.y),
                        _num(seg.control2.x),
                        _num(seg.control2.y),
                        _num(seg.point.x),
                        _num(seg.point.y),
                    )
                )
            else:
                parts.append("Z")
        return " ".join(parts)

    @classmethod
    def from_svg_d(cls, d: str) -> "Path":
        """Read back what :meth:`to_svg_d` wrote: absolute ``M``, ``L``, ``C`` and ``Z`` only.

        Importing arbitrary foreign SVG needs a fuller parser; that is a separate concern from our own
        container.
        """
        tokens = re.findall(r"[MLCZmlcz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
        segments: list[Segment] = []
        i = 0
        while i < len(tokens):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                segments.append(Close())
                continue
            if cmd in "ml":
                raise ValueError("relative path commands are not supported")
            count = {"M": 2, "L": 2, "C": 6}.get(cmd)
            if count is None:
                raise ValueError(f"unsupported path command: {cmd!r}")
            nums = [float(tokens[i + n]) for n in range(count)]
            i += count
            if cmd == "M":
                segments.append(MoveTo(Point(nums[0], nums[1])))
            elif cmd == "L":
                segments.append(LineTo(Point(nums[0], nums[1])))
            else:
                segments.append(
                    CubicTo(Point(nums[0], nums[1]), Point(nums[2], nums[3]), Point(nums[4], nums[5]))
                )
        return cls(segments)
