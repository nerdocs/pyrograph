"""Turning a layer of the document into something a laser can run.

This is the one place where millimetres become pixels. The document knows nothing about DPI; the device
knows nothing about documents. Here the layer's DPI decides the raster size, the layer's bounding box
decides the origin, and the layer's parameters ride along unchanged.

Two outputs exist, because the two device families want opposite things. An LP2's native format *is* the
raster, so a path gets stroked into pixels. A galvo has no raster format at all and wants the paths
themselves. Neither is a conversion of the other, so both are built from the document rather than one
from the other.

The LP2 still cannot take vectors — its line/fill command (`0x40`) is undecoded (``TODO.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from laserpecker.imaging import Raster, dither, pack_bits

from .document import Document, ImageObject, LaserParams, Point, Rect, Transform
from .hatch import hatch

MM_PER_INCH = 25.4


@dataclass
class RasterJob:
    """A dithered bitmap plus where it goes and how it should burn."""

    raster: Raster
    x_mm: float
    y_mm: float
    dpi: float
    params: LaserParams

    @property
    def x_px(self) -> int:
        """The origin in device pixels — what the raster header calls ``nx``."""
        return max(0, int(self.x_mm * self.dpi / MM_PER_INCH))

    @property
    def y_px(self) -> int:
        return max(0, int(self.y_mm * self.dpi / MM_PER_INCH))


@dataclass
class VectorJob:
    """Flattened outlines in document millimetres, plus how they should burn.

    Curves are already gone — a galvo moves in straight segments between two points, so the flattening
    has to happen somewhere and doing it here keeps the driver free of geometry.
    """

    polylines: list[list[Point]]
    bounds: Rect
    params: LaserParams

    skipped: list[str] = field(default_factory=list)
    """What could not be expressed as an outline, by object name. See :func:`build_vector_job`."""


def _stroke_width_mm(obj, layer) -> float:
    """How wide this object burns: its own width if it has one, else the layer's.

    A filled object without a width of its own is not stroked at all — the same as SVG's ``stroke: none``.
    Adding the layer's outline to a filled shape would fatten every QR module by a line width.
    """
    if isinstance(obj, ImageObject):
        return 0.0
    if obj.stroke_width_mm is not None:
        return obj.stroke_width_mm
    return 0.0 if obj.fill else layer.params.line_width_mm


def _fill_mask(size: tuple[int, int], lines: list[list]) -> "object":
    """A mask of the area enclosed by ``lines``, combined with the even-odd rule.

    Even-odd is what gives an "o" its hole and a QR code its light modules: a subpath inside another one
    cuts the area away instead of adding to it. Each subpath is drawn in its own bounding box and XORed
    into the mask, so a code made of four hundred small squares does not cost four hundred full-size
    images.
    """
    from PIL import Image, ImageChops, ImageDraw

    mask = Image.new("1", size, 0)
    for line in lines:
        if len(line) < 3:
            continue
        xs = [p.x for p in line]
        ys = [p.y for p in line]
        left, top = max(0, int(min(xs)) - 1), max(0, int(min(ys)) - 1)
        right, bottom = min(size[0], int(max(xs)) + 2), min(size[1], int(max(ys)) + 2)
        if right <= left or bottom <= top:
            continue
        piece = Image.new("1", (right - left, bottom - top), 0)
        ImageDraw.Draw(piece).polygon([(p.x - left, p.y - top) for p in line], fill=1)
        box = (left, top, right, bottom)
        mask.paste(ImageChops.logical_xor(mask.crop(box), piece), box)
    return mask


def _stroke(draw, points: list[tuple[float, float]], width_px: int) -> None:
    """Draw a polyline with round joints and round caps.

    Pillow's own ``joint="curve"`` rasterises the joints slightly differently from the line itself, which
    leaves notches along a wide outline, and it has no caps at all. Both matter here: SVG icon sets draw a
    dot as a zero-length segment (``<line x1="10" x2="10.01">``) that exists only because of a round cap,
    and without one the dot disappears.

    Round rather than SVG's default butt cap: the difference is half a line width, while the failure mode
    of a butt cap is losing a dot entirely.
    """
    draw.line(points, fill=0, width=width_px)
    if width_px <= 2:
        return  # a thin line needs no help; the joints are a pixel wide
    radius = width_px / 2
    for x, y in points:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=0)


def build_raster_job(
    document: Document,
    layer_index: int,
    packed: bool = False,
    inverse: bool = False,
) -> RasterJob | None:
    """Rasterise one layer at its own DPI. Returns ``None`` if the layer holds nothing to burn.

    Paths are stroked at their own ``stroke_width_mm``, or at the layer's ``line_width_mm`` where they
    carry none. Filling them is not implemented, because a laser follows outlines.
    """
    from PIL import Image, ImageChops, ImageDraw

    layer = document.layers[layer_index]
    box = None
    for obj in layer.objects:
        # A stroke straddles the path, so the ink reaches half a line width beyond the geometry.
        # Ignoring that clips the outer half of every outline — and gives a dot no area at all.
        inked = obj.bounds().grown(_stroke_width_mm(obj, layer) / 2)
        box = inked if box is None else box.union(inked)
    if box is None or box.width <= 0 or box.height <= 0:
        return None

    scale = layer.params.dpi / MM_PER_INCH
    width_px = max(1, round(box.width * scale))
    height_px = max(1, round(box.height * scale))
    # Document millimetres → canvas pixels.
    to_canvas = Transform.translate(-box.x, -box.y).then(Transform.scale(scale))

    canvas = Image.new("L", (width_px, height_px), 255)  # 255 = untouched
    draw = ImageDraw.Draw(canvas)
    for obj in layer.objects:
        placement = obj.transform.then(to_canvas)
        if isinstance(obj, ImageObject):
            source = obj.pil_image().convert("L")
            pixels_to_mm = Transform.scale(obj.width_mm / source.width, obj.height_mm / source.height)
            full = pixels_to_mm.then(placement).inverse()
            placed = source.transform(
                (width_px, height_px),
                Image.AFFINE,
                (full.a, full.c, full.e, full.b, full.d, full.f),
                resample=Image.Resampling.BICUBIC,
                fillcolor=255,
            )
            canvas = ImageChops.darker(canvas, placed)
            draw = ImageDraw.Draw(canvas)
        else:
            lines = obj.local_path().transformed(placement).polylines()
            if obj.fill:
                canvas.paste(0, None, _fill_mask(canvas.size, lines))
            width_mm = _stroke_width_mm(obj, layer)
            if width_mm > 0:
                stroke_px = max(1, round(width_mm * scale))
                for line in lines:
                    _stroke(draw, [(p.x, p.y) for p in line], stroke_px)

    mono = dither(list(canvas.tobytes()), width_px, height_px, inverse)
    payload = pack_bits(mono, width_px, height_px) if packed else bytes(mono)
    return RasterJob(
        raster=Raster(width=width_px, height=height_px, payload=payload, packed=packed),
        x_mm=box.x,
        y_mm=box.y,
        dpi=layer.params.dpi,
        params=layer.params,
    )


def build_vector_job(document: Document, layer_index: int, steps: int = 16) -> VectorJob | None:
    """Flatten one layer to outlines. Returns ``None`` if the layer holds nothing a vector device can run.

    A filled shape is swept with hatch lines (:mod:`pyrograph.hatch`), because a vector machine cannot
    darken an area — it can only run the spot across it. The outline is burnt as well where the object
    has one.

    One thing a document can express has no vector equivalent at all: a **bitmap**, which has no outline
    to follow. It is named in :attr:`VectorJob.skipped` rather than dropped in silence.
    """
    layer = document.layers[layer_index]
    polylines: list[list[Point]] = []
    skipped: list[str] = []
    box = None
    for obj in layer.objects:
        label = obj.name or type(obj).__name__
        if isinstance(obj, ImageObject):
            skipped.append(f"{label} (bitmap)")
            continue
        lines = obj.local_path().transformed(obj.transform).polylines(steps)
        if not lines:
            continue
        filled = obj.fill and layer.params.hatch_mm > 0
        if obj.fill and not filled:
            # Hatching switched off leaves the shape hollow. Burning its outline is better than burning
            # nothing at all, but it is not what the document says, so it is reported.
            skipped.append(f"{label} (fill, outline only — hatch spacing is zero)")
        if filled:
            polylines.extend(hatch(lines, layer.params.hatch_mm, layer.params.hatch_angle))
        if not filled or _stroke_width_mm(obj, layer) > 0:
            # A hatched shape without a stroke of its own is not outlined, the same rule the rasteriser
            # follows — otherwise every QR module grows by a line width.
            polylines.extend(lines)
        box = obj.bounds() if box is None else box.union(obj.bounds())

    if not polylines or box is None:
        return None
    return VectorJob(polylines=polylines, bounds=box, params=layer.params, skipped=skipped)
