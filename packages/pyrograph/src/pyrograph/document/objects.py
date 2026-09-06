"""The things a document is made of.

Two rules hold for every object here, and both are easy to violate later:

1. **An object stores its source, never a device-ready derivative.** ``ImageObject`` keeps the original
   bitmap; dithering depends on DPI and target size and therefore belongs to job creation. Otherwise
   resizing an object would degrade it a little more each time.
2. **Objects do not know the device.** No pixels, no DPI, no ``px`` byte — millimetres only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .geometry import Close, CubicTo, LineTo, MoveTo, Path, Point, Rect, Transform


def new_id() -> str:
    """A document-unique identifier, usable verbatim as an XML ``id``."""
    return "o" + uuid.uuid4().hex[:12]


@dataclass
class DocumentObject:
    """Base class: identity, placement and edit state. Geometry comes from the subclasses."""

    id: str = field(default_factory=new_id)
    name: str = ""
    transform: Transform = field(default_factory=Transform)
    locked: bool = False

    def local_path(self) -> Path:
        """The object's outline in its own coordinate system, before ``transform``."""
        raise NotImplementedError

    def bounds(self) -> Rect:
        """The bounding box in document millimetres, after ``transform``."""
        return self.local_path().transformed(self.transform).bounds()


@dataclass
class PathObject(DocumentObject):
    """A vector outline. Kept as a path; rasterising happens when the job is built."""

    path: Path = field(default_factory=Path)

    def local_path(self) -> Path:
        return self.path


@dataclass
class ImageObject(DocumentObject):
    """A bitmap placed on a rectangle of ``width_mm`` × ``height_mm``.

    ``data`` holds the *original* encoded image (PNG), byte for byte as it entered the document, so a
    round trip through the file format is lossless.

    The two sizes are the rectangle *before* ``transform``, like every other object's local geometry. With
    the usual identity transform they are the size on the workpiece; an import that carries a scale in the
    transform is the exception, and :meth:`bounds` accounts for it either way.
    """

    data: bytes = b""
    width_mm: float = 0.0
    height_mm: float = 0.0

    def local_path(self) -> Path:
        return Path.rect(0.0, 0.0, self.width_mm, self.height_mm)

    def pil_image(self):
        """Decode ``data``. Only the rasteriser needs this — the model itself stays image-library free."""
        import io

        from PIL import Image

        return Image.open(io.BytesIO(self.data))


@dataclass
class TextObject(DocumentObject):
    """A line of text with a font file. Converts to a path on demand.

    ``font_path`` names a font file on disk; there is no lookup by family name, because that needs a font
    database and belongs to the GUI. The baseline sits at y = 0, the text starts at x = 0.
    """

    text: str = ""
    font_path: str = ""
    size_mm: float = 10.0

    def local_path(self) -> Path:
        return self.to_path()

    def to_path(self) -> Path:
        """Convert the text to glyph outlines, scaled so that one em equals ``size_mm``."""
        from fontTools.pens.basePen import BasePen
        from fontTools.ttLib import TTFont

        if not self.text:
            return Path()

        font = TTFont(self.font_path, fontNumber=0, lazy=True)
        glyph_set = font.getGlyphSet()
        cmap = font.getBestCmap()
        scale = self.size_mm / font["head"].unitsPerEm

        class _PathPen(BasePen):
            """Collects glyph outlines, flipping the font's y-up axis to the document's y-down one."""

            def __init__(self, glyphs, offset: float) -> None:
                super().__init__(glyphs)
                self.segments: list = []
                self.offset = offset

            def _p(self, pt) -> Point:
                return Point(pt[0] * scale + self.offset, -pt[1] * scale)

            def _moveTo(self, pt):
                self.segments.append(MoveTo(self._p(pt)))

            def _lineTo(self, pt):
                self.segments.append(LineTo(self._p(pt)))

            def _curveToOne(self, c1, c2, pt):
                self.segments.append(CubicTo(self._p(c1), self._p(c2), self._p(pt)))

            def _closePath(self):
                self.segments.append(Close())

        segments: list = []
        pen_x = 0.0
        for char in self.text:
            name = cmap.get(ord(char))
            if name is None:
                continue
            pen = _PathPen(glyph_set, pen_x)
            glyph_set[name].draw(pen)
            segments += pen.segments
            pen_x += glyph_set[name].width * scale
        font.close()
        return Path(segments)
