"""Turning a layer of the document into something a laser can run.

This is the one place where millimetres become pixels. The document knows nothing about DPI; the device
knows nothing about documents. Here the layer's DPI decides the raster size, the layer's bounding box
decides the origin, and the layer's parameters ride along unchanged.

Only raster output exists so far, because that is the LP2's native format. Vector output waits for the
line/fill command (`0x40`) to be decoded — see ``TODO.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from laserpecker.imaging import Raster, dither, pack_bits

from .document import Document, ImageObject, LaserParams, Transform

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


def _stroke_width_mm(obj, layer) -> float:
    """How wide this object burns: its own width if it has one, else the layer's."""
    if isinstance(obj, ImageObject):
        return 0.0
    return obj.stroke_width_mm or layer.params.line_width_mm


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
            stroke_px = max(1, round(_stroke_width_mm(obj, layer) * scale))
            for line in obj.local_path().transformed(placement).polylines():
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
