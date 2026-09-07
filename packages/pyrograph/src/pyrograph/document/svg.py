"""Importing foreign SVG.

Reading our own container is :mod:`pyrograph.document.serialize`; this is the other direction — an SVG
that some other program wrote, with all the freedom the format allows. The two are kept apart on purpose:
our writer only ever emits four path commands, and a reader that has to cope with arcs, nested transforms
and user units has no business constraining it.

What is understood: ``path``, ``rect``, ``circle``, ``ellipse``, ``line``, ``polyline``, ``polygon``,
``image``, and ``g`` nesting with the ``transform`` attribute. Everything is converted to millimetres via
``width``/``height`` and ``viewBox``.

What is not: ``text`` (would need to resolve a font by family name — that is the GUI's job), ``use``,
clipping, masks and gradients. Unsupported elements are skipped; :func:`import_svg` reports them.
"""

from __future__ import annotations

import base64
import math
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from .document import Document
from .geometry import Close, CubicTo, LineTo, MoveTo, Path, Point, Transform
from .layer import Layer
from .objects import DocumentObject, ImageObject, PathObject

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

#: One CSS pixel in millimetres — the anchor the whole unit system hangs off.
PX_MM = 25.4 / 96.0

_UNITS_MM = {
    "": PX_MM,
    "px": PX_MM,
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "pt": 25.4 / 72.0,
    "pc": 25.4 / 6.0,
    "q": 0.25,
}

_NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
_LENGTH_RE = re.compile(rf"^\s*({_NUMBER})\s*([a-zA-Z%]*)\s*$")
_PATH_TOKEN_RE = re.compile(rf"([MmZzLlHhVvCcSsQqTtAa])|({_NUMBER})")
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")

#: Control-point distance that turns a quarter circle into a cubic Bézier.
_KAPPA = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)


class SvgImportError(ValueError):
    """The file is not usable as SVG."""


@dataclass
class SvgImport:
    """The result of reading an SVG file."""

    document: Document
    skipped: list[str] = field(default_factory=list)
    """Tag names that were encountered but not understood, in document order, without duplicates."""


# ------------------------------------------------------------------------------------- lengths, transforms


def _length(value: str | None, default: float | None = None) -> float | None:
    """A length attribute in millimetres. Percentages are not resolvable without a viewport."""
    if value is None:
        return default
    match = _LENGTH_RE.match(value)
    if not match:
        return default
    factor = _UNITS_MM.get(match.group(2).lower())
    if factor is None:
        return default
    return float(match.group(1)) * factor


def _number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_transform(text: str | None) -> Transform:
    """Read an SVG ``transform`` attribute. Several transforms compose left to right."""
    result = Transform()
    if not text:
        return result
    for name, raw in _TRANSFORM_RE.findall(text):
        values = [float(v) for v in re.findall(_NUMBER, raw)]
        if name == "matrix" and len(values) == 6:
            step = Transform(*values)
        elif name == "translate":
            step = Transform.translate(values[0], values[1] if len(values) > 1 else 0.0)
        elif name == "scale":
            step = Transform.scale(values[0], values[1] if len(values) > 1 else values[0])
        elif name == "rotate":
            origin = Point(values[1], values[2]) if len(values) >= 3 else None
            step = Transform.rotate(values[0], origin)
        elif name == "skewX":
            step = Transform(c=math.tan(math.radians(values[0])))
        elif name == "skewY":
            step = Transform(b=math.tan(math.radians(values[0])))
        else:
            continue
        # The leftmost transform is applied last, so it wraps everything to its right.
        result = step.then(result)
    return result


# ------------------------------------------------------------------------------------------ path geometry


def _quadratic_to_cubic(p0: Point, q: Point, p1: Point) -> CubicTo:
    """A quadratic Bézier is a cubic whose handles sit two thirds of the way to the single control point."""
    return CubicTo(
        Point(p0.x + 2 / 3 * (q.x - p0.x), p0.y + 2 / 3 * (q.y - p0.y)),
        Point(p1.x + 2 / 3 * (q.x - p1.x), p1.y + 2 / 3 * (q.y - p1.y)),
        p1,
    )


def _arc_to_cubics(p0: Point, rx: float, ry: float, rotation: float, large: bool, sweep: bool, p1: Point):
    """Convert an elliptical arc to cubic segments (SVG 1.1, implementation notes F.6)."""
    if rx == 0 or ry == 0 or (p0.x == p1.x and p0.y == p1.y):
        return [LineTo(p1)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    dx2, dy2 = (p0.x - p1.x) / 2.0, (p0.y - p1.y) / 2.0
    x1 = cos_phi * dx2 + sin_phi * dy2
    y1 = -sin_phi * dx2 + cos_phi * dy2

    # Scale the radii up if they are too small to span the two endpoints.
    lam = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)

    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, numerator / denominator))
    if large == sweep:
        factor = -factor
    cx1 = factor * rx * y1 / ry
    cy1 = -factor * ry * x1 / rx

    cx = cos_phi * cx1 - sin_phi * cy1 + (p0.x + p1.x) / 2.0
    cy = sin_phi * cx1 + cos_phi * cy1 + (p0.y + p1.y) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        length = math.hypot(ux, uy) * math.hypot(vx, vy)
        value = math.acos(max(-1.0, min(1.0, dot / length)))
        return -value if ux * vy - uy * vx < 0 else value

    start = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    sweep_angle = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and sweep_angle > 0:
        sweep_angle -= 2 * math.pi
    elif sweep and sweep_angle < 0:
        sweep_angle += 2 * math.pi

    # A cubic approximates at most a quarter turn well.
    steps = max(1, math.ceil(abs(sweep_angle) / (math.pi / 2)))
    delta = sweep_angle / steps
    handle = 4.0 / 3.0 * math.tan(delta / 4.0)

    def on_ellipse(theta: float) -> Point:
        return Point(
            cx + rx * math.cos(theta) * cos_phi - ry * math.sin(theta) * sin_phi,
            cy + rx * math.cos(theta) * sin_phi + ry * math.sin(theta) * cos_phi,
        )

    def tangent(theta: float) -> Point:
        return Point(
            -rx * math.sin(theta) * cos_phi - ry * math.cos(theta) * sin_phi,
            -rx * math.sin(theta) * sin_phi + ry * math.cos(theta) * cos_phi,
        )

    segments = []
    theta = start
    current = p0
    for _ in range(steps):
        end_theta = theta + delta
        end = on_ellipse(end_theta)
        t0, t1 = tangent(theta), tangent(end_theta)
        segments.append(
            CubicTo(
                Point(current.x + handle * t0.x, current.y + handle * t0.y),
                Point(end.x - handle * t1.x, end.y - handle * t1.y),
                end,
            )
        )
        theta, current = end_theta, end
    return segments


def parse_path_data(d: str) -> Path:
    """Parse an SVG ``d`` attribute in full — relative commands, shorthands and arcs included."""
    tokens = [(cmd, num) for cmd, num in _PATH_TOKEN_RE.findall(d)]
    segments: list = []
    index = 0
    command = ""
    current = Point()
    start = Point()
    last_cubic: Point | None = None
    last_quadratic: Point | None = None

    def take(count: int) -> list[float]:
        nonlocal index
        values = []
        while len(values) < count:
            if index >= len(tokens) or tokens[index][0]:
                raise SvgImportError(f"path data ended mid-command: {d[:60]!r}")
            values.append(float(tokens[index][1]))
            index += 1
        return values

    def take_flag() -> int:
        """One arc flag.

        A flag is a single character and needs no separator after it, so ``a5 5 0 0130 0`` is legal SVG
        and both of its flags sit inside one number token — which is exactly what an optimiser writes.
        """
        nonlocal index
        if index >= len(tokens) or tokens[index][0]:
            raise SvgImportError(f"path data ended mid-command: {d[:60]!r}")
        text = tokens[index][1]
        if text[0] not in "01":
            raise SvgImportError(f"an arc flag is 0 or 1, got {text!r}")
        if len(text) == 1:
            index += 1
        else:
            tokens[index] = ("", text[1:])  # the rest of the token is the next value
        return int(text[0])

    while index < len(tokens):
        if tokens[index][0]:
            command = tokens[index][0]
            index += 1
            if command in "Zz":
                segments.append(Close())
                current = start
                last_cubic = last_quadratic = None
                continue
        elif command in ("M", "m"):
            command = "L" if command == "M" else "l"  # repeated moveto coordinates are implicit linetos
        elif not command:
            raise SvgImportError("path data does not start with a command")

        relative = command.islower()
        upper = command.upper()
        ox, oy = (current.x, current.y) if relative else (0.0, 0.0)

        if upper == "M":
            x, y = take(2)
            current = start = Point(x + ox, y + oy)
            segments.append(MoveTo(current))
            last_cubic = last_quadratic = None
        elif upper == "L":
            x, y = take(2)
            current = Point(x + ox, y + oy)
            segments.append(LineTo(current))
            last_cubic = last_quadratic = None
        elif upper == "H":
            (x,) = take(1)
            current = Point(x + ox, current.y)
            segments.append(LineTo(current))
            last_cubic = last_quadratic = None
        elif upper == "V":
            (y,) = take(1)
            current = Point(current.x, y + oy)
            segments.append(LineTo(current))
            last_cubic = last_quadratic = None
        elif upper in ("C", "S"):
            if upper == "C":
                x1, y1, x2, y2, x, y = take(6)
                c1 = Point(x1 + ox, y1 + oy)
            else:
                x2, y2, x, y = take(4)
                # The first handle mirrors the previous one; without a previous cubic it sits on the point.
                c1 = (
                    Point(2 * current.x - last_cubic.x, 2 * current.y - last_cubic.y)
                    if last_cubic
                    else current
                )
            c2 = Point(x2 + ox, y2 + oy)
            current = Point(x + ox, y + oy)
            segments.append(CubicTo(c1, c2, current))
            last_cubic, last_quadratic = c2, None
        elif upper in ("Q", "T"):
            if upper == "Q":
                x1, y1, x, y = take(4)
                q = Point(x1 + ox, y1 + oy)
            else:
                x, y = take(2)
                q = (
                    Point(2 * current.x - last_quadratic.x, 2 * current.y - last_quadratic.y)
                    if last_quadratic
                    else current
                )
            end = Point(x + ox, y + oy)
            segments.append(_quadratic_to_cubic(current, q, end))
            current, last_quadratic, last_cubic = end, q, None
        elif upper == "A":
            rx, ry, rotation = take(3)
            large, sweep = take_flag(), take_flag()
            x, y = take(2)
            end = Point(x + ox, y + oy)
            segments += _arc_to_cubics(current, rx, ry, rotation, bool(large), bool(sweep), end)
            current = end
            last_cubic = last_quadratic = None
        else:
            raise SvgImportError(f"unknown path command: {command!r}")

    return Path(segments)


def _ellipse_path(cx: float, cy: float, rx: float, ry: float) -> Path:
    """Four cubic segments — the standard kappa approximation, well under a tenth of a pixel off."""
    ox, oy = rx * _KAPPA, ry * _KAPPA
    return Path(
        [
            MoveTo(Point(cx + rx, cy)),
            CubicTo(Point(cx + rx, cy + oy), Point(cx + ox, cy + ry), Point(cx, cy + ry)),
            CubicTo(Point(cx - ox, cy + ry), Point(cx - rx, cy + oy), Point(cx - rx, cy)),
            CubicTo(Point(cx - rx, cy - oy), Point(cx - ox, cy - ry), Point(cx, cy - ry)),
            CubicTo(Point(cx + ox, cy - ry), Point(cx + rx, cy - oy), Point(cx + rx, cy)),
            Close(),
        ]
    )


def _shape_path(tag: str, element: ET.Element) -> Path | None:
    """The outline of a basic shape, in the element's own coordinate system."""
    if tag == "path":
        return parse_path_data(element.get("d", ""))
    if tag == "rect":
        width, height = _number(element.get("width")), _number(element.get("height"))
        if width <= 0 or height <= 0:
            return None
        # Rounded corners (rx/ry) are ignored — a laser outline rarely depends on them.
        return Path.rect(_number(element.get("x")), _number(element.get("y")), width, height)
    if tag == "circle":
        r = _number(element.get("r"))
        return _ellipse_path(_number(element.get("cx")), _number(element.get("cy")), r, r) if r > 0 else None
    if tag == "ellipse":
        rx, ry = _number(element.get("rx")), _number(element.get("ry"))
        if rx <= 0 or ry <= 0:
            return None
        return _ellipse_path(_number(element.get("cx")), _number(element.get("cy")), rx, ry)
    if tag == "line":
        return Path(
            [
                MoveTo(Point(_number(element.get("x1")), _number(element.get("y1")))),
                LineTo(Point(_number(element.get("x2")), _number(element.get("y2")))),
            ]
        )
    if tag in ("polyline", "polygon"):
        numbers = [float(v) for v in re.findall(_NUMBER, element.get("points", ""))]
        points = [Point(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]
        if len(points) < 2:
            return None
        segments = [MoveTo(points[0])] + [LineTo(p) for p in points[1:]]
        if tag == "polygon":
            segments.append(Close())
        return Path(segments)
    return None


# ------------------------------------------------------------------------------------------------ images


def _image_data(element: ET.Element, base_dir: str | None) -> bytes | None:
    """The bitmap behind an ``<image>``: inline data URI, or a file next to the SVG."""
    href = element.get("href") or element.get(XLINK_HREF)
    if not href:
        return None
    if href.startswith("data:"):
        header, _, payload = href.partition(",")
        if ";base64" in header:
            return base64.b64decode(payload)
        return urllib.parse.unquote_to_bytes(payload)
    if base_dir is None or "://" in href:
        return None
    path = os.path.normpath(os.path.join(base_dir, urllib.parse.unquote(href)))
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as handle:
        return handle.read()


# ------------------------------------------------------------------------------------------------- walker

#: SVG's initial values: shapes are filled black, not stroked, and a stroke would be one unit wide.
_INITIAL_PAINT = ("black", "none", "1")

_PAINT_PROPERTIES = ("fill", "stroke", "stroke-width")


def _property(element: ET.Element, name: str) -> str | None:
    """One presentation property, taken from ``style`` where it is set there and from the attribute else.

    Both spellings mean the same thing in SVG and both turn up in the wild — Inkscape writes almost
    everything into ``style``, an icon set almost everything as attributes.
    """
    style = element.get("style", "")
    if style:
        match = re.search(rf"(?:^|;)\s*{name}\s*:\s*([^;]+)", style)
        if match:
            return match.group(1).strip()
    return element.get(name)


def _hidden(element: ET.Element) -> bool:
    """Whether the element is switched off and therefore draws nothing."""
    return _property(element, "display") == "none" or _property(element, "visibility") == "hidden"


def _paint(element: ET.Element, inherited: tuple[str, str, str]) -> tuple[str, str, str]:
    """The element's effective ``fill``, ``stroke`` and ``stroke-width``, falling back to what it inherits.

    All three inherit in SVG, and an icon set relies on it: the root sets the stroke, every path below it
    just draws.
    """
    result = []
    for index, name in enumerate(_PAINT_PROPERTIES):
        value = _property(element, name)
        result.append(value if value else inherited[index])
    return result[0], result[1], result[2]


def _stroke_width_mm(paint: tuple[str, str, str], transform: Transform) -> float | None:
    """The stroke width in millimetres, or ``None`` when the element is not stroked at all.

    A renderer scales the stroke along with the geometry, so the width goes through the same transform.
    For a non-uniform or rotated one there is no single factor; the square root of the determinant is the
    usual stand-in, and it is exact whenever the scaling is uniform.
    """
    if paint[1] == "none":
        return None  # only filled — its outline is the layer's business, not the file's
    match = _LENGTH_RE.match(paint[2])
    if not match:
        return None
    scale = math.sqrt(abs(transform.a * transform.d - transform.b * transform.c))
    return float(match.group(1)) * scale


def _walk(
    element: ET.Element,
    transform: Transform,
    base_dir: str | None,
    out: list,
    skipped: list,
    paint: tuple[str, str, str] = _INITIAL_PAINT,
) -> None:
    for child in element:
        if not isinstance(child.tag, str) or not child.tag.startswith(f"{{{SVG_NS}}}"):
            continue  # comments, processing instructions, foreign namespaces
        tag = child.tag[len(SVG_NS) + 2 :]
        if _hidden(child):
            # Before the group branch below, so a hidden group takes its whole subtree with it. An
            # Inkscape drawing keeps its switched-off layers in the file, and engraving one would burn
            # what the author put away.
            continue
        combined = parse_transform(child.get("transform")).then(transform)
        child_paint = _paint(child, paint)

        if tag in ("g", "svg", "a"):
            _walk(child, combined, base_dir, out, skipped, child_paint)
            continue
        if child_paint[0] == "none" and child_paint[1] == "none":
            # Neither filled nor stroked: the element draws nothing. Icon sets ship such paths as an
            # invisible bounding box, and engraving one would burn a rectangle around the motif.
            continue

        if tag == "image":
            data = _image_data(child, base_dir)
            width, height = _number(child.get("width")), _number(child.get("height"))
            if data and width > 0 and height > 0:
                placement = Transform.translate(_number(child.get("x")), _number(child.get("y")))
                out.append(
                    ImageObject(
                        name=child.get("id", ""),
                        data=data,
                        width_mm=width,
                        height_mm=height,
                        transform=placement.then(combined),
                    )
                )
            continue

        path = _shape_path(tag, child)
        if path is not None:
            if path.segments:
                # The transform is baked into the coordinates: after import everything is plain millimetres.
                out.append(
                    PathObject(
                        name=child.get("id", ""),
                        path=path.transformed(combined),
                        stroke_width_mm=_stroke_width_mm(child_paint, combined),
                    )
                )
        elif tag not in ("defs", "title", "desc", "metadata", "style") and tag not in skipped:
            skipped.append(tag)


def import_svg(source: str | os.PathLike | bytes) -> SvgImport:
    """Read an SVG file (or its bytes) into a document with one layer.

    Coordinates end up in millimetres: ``width``/``height`` give the physical size, ``viewBox`` gives the
    coordinate system, and the ratio between them is the scale. Without either, user units are read as CSS
    pixels and the work area is taken from the content.
    """
    base_dir = None
    try:
        if isinstance(source, bytes):
            root = ET.fromstring(source)
        else:
            base_dir = os.path.dirname(os.path.abspath(os.fspath(source)))
            root = ET.parse(os.fspath(source)).getroot()
    except ET.ParseError as error:
        # A file that is not well-formed is a bad SVG like any other; callers should not have to catch
        # ElementTree's own exception on top of ours to say so.
        raise SvgImportError(f"not well-formed XML: {error}") from error
    if root.tag != f"{{{SVG_NS}}}svg":
        raise SvgImportError(f"root element is {root.tag!r}, not an SVG")

    width_mm = _length(root.get("width"))
    height_mm = _length(root.get("height"))
    view_box = [float(v) for v in re.findall(_NUMBER, root.get("viewBox", ""))]

    if len(view_box) == 4 and view_box[2] > 0 and view_box[3] > 0:
        vx, vy, vw, vh = view_box
        width_mm = width_mm if width_mm else vw * PX_MM
        height_mm = height_mm if height_mm else vh * PX_MM
        root_transform = Transform.translate(-vx, -vy).then(Transform.scale(width_mm / vw, height_mm / vh))
    else:
        root_transform = Transform.scale(PX_MM)

    objects: list[DocumentObject] = []
    skipped: list[str] = []
    _walk(root, root_transform, base_dir, objects, skipped, _paint(root, _INITIAL_PAINT))

    if not width_mm or not height_mm:
        # No declared size: let the content define the work area.
        box = None
        for obj in objects:
            box = obj.bounds() if box is None else box.union(obj.bounds())
        width_mm = width_mm or (box.right if box else 100.0)
        height_mm = height_mm or (box.bottom if box else 100.0)

    document = Document(width_mm=width_mm, height_mm=height_mm, layers=[Layer(objects=objects)])
    return SvgImport(document=document, skipped=skipped)
