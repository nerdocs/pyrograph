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


def build_raster_job(
    document: Document,
    layer_index: int,
    packed: bool = False,
    inverse: bool = False,
) -> RasterJob | None:
    """Rasterise one layer at its own DPI. Returns ``None`` if the layer holds nothing to burn.

    Paths are stroked one pixel wide; filling them is not implemented, because a laser follows outlines.
    """
    from PIL import Image, ImageChops, ImageDraw

    layer = document.layers[layer_index]
    box = None
    for obj in layer.objects:
        box = obj.bounds() if box is None else box.union(obj.bounds())
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
            for line in obj.local_path().transformed(placement).polylines():
                draw.line([(p.x, p.y) for p in line], fill=0, width=1)

    mono = dither(list(canvas.tobytes()), width_px, height_px, inverse)
    payload = pack_bits(mono, width_px, height_px) if packed else bytes(mono)
    return RasterJob(
        raster=Raster(width=width_px, height=height_px, payload=payload, packed=packed),
        x_mm=box.x,
        y_mm=box.y,
        dpi=layer.params.dpi,
        params=layer.params,
    )
