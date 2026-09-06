"""The work area — what the document looks like on the machine bed.

One scene unit is one millimetre and y grows downwards, exactly like the document model. Nothing is
converted on the way in, so the view's scale is the only zoom factor and a 0.1 mm stroke is drawn 0.1
units wide — the same width it will burn.

The scene is rebuilt wholesale from the document. That is cheap for the object counts an engraving
document has, and it keeps the canvas free of any state that could drift away from the model.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ..document import Close, CubicTo, Document, ImageObject, LineTo, MoveTo, Path
from ..document import Transform as DocTransform

GRID_MM = 10.0
"""Spacing of the background grid."""

_BED = QColor("#ffffff")
_BED_EDGE = QColor("#606060")
_GRID = QColor("#d8d8d8")
_INK = QColor("#101010")
_OUTSIDE = QColor("#3a3a3a")


def _painter_path(path: Path) -> QPainterPath:
    """Convert a document path to Qt's, curve for curve — no flattening."""
    out = QPainterPath()
    for seg in path.segments:
        if isinstance(seg, MoveTo):
            out.moveTo(seg.point.x, seg.point.y)
        elif isinstance(seg, LineTo):
            out.lineTo(seg.point.x, seg.point.y)
        elif isinstance(seg, CubicTo):
            out.cubicTo(
                seg.control1.x,
                seg.control1.y,
                seg.control2.x,
                seg.control2.y,
                seg.point.x,
                seg.point.y,
            )
        elif isinstance(seg, Close):
            out.closeSubpath()
    return out


def _qt_transform(transform: DocTransform) -> QTransform:
    """``matrix(a b c d e f)`` means the same thing in both libraries."""
    return QTransform(transform.a, transform.b, transform.c, transform.d, transform.e, transform.f)


class CanvasView(QGraphicsView):
    """Shows the work area and the objects on it. Read-only for now — no selection, no dragging."""

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(_OUTSIDE)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._document: Document | None = None

    def set_document(self, document: Document) -> None:
        self._document = document
        self.rebuild()
        self.fit()

    def rebuild(self) -> None:
        """Redraw everything from the document. Call after any change to it."""
        scene = self.scene()
        scene.clear()
        if self._document is None:
            return
        self._draw_bed(self._document)
        for layer in self._document.layers:
            if not layer.visible:
                continue
            for obj in layer.objects:
                self._draw_object(obj, layer.params.line_width_mm)
        margin = max(self._document.width_mm, self._document.height_mm) * 0.05
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))

    def fit(self) -> None:
        """Scale so that the whole work area is visible."""
        if self._document is not None:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_bed(self, document: Document) -> None:
        scene = self.scene()
        edge = QPen(_BED_EDGE)
        edge.setCosmetic(True)
        scene.addRect(0, 0, document.width_mm, document.height_mm, edge, _BED)

        grid = QPainterPath()
        x = GRID_MM
        while x < document.width_mm:
            grid.moveTo(x, 0)
            grid.lineTo(x, document.height_mm)
            x += GRID_MM
        y = GRID_MM
        while y < document.height_mm:
            grid.moveTo(0, y)
            grid.lineTo(document.width_mm, y)
            y += GRID_MM
        pen = QPen(_GRID)
        pen.setCosmetic(True)
        scene.addPath(grid, pen)

    def _draw_object(self, obj, line_width_mm: float) -> None:
        if isinstance(obj, ImageObject):
            pixmap = QPixmap.fromImage(QImage.fromData(obj.data))
            item = self.scene().addPixmap(pixmap)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            pixels_to_mm = DocTransform.scale(
                obj.width_mm / pixmap.width(), obj.height_mm / pixmap.height()
            )
            item.setTransform(_qt_transform(pixels_to_mm.then(obj.transform)))
            return

        path = _painter_path(obj.local_path().transformed(obj.transform))
        pen = QPen(_INK, obj.stroke_width_mm or line_width_mm)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)  # as the rasteriser strokes it
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.scene().addPath(path, pen)

    def wheelEvent(self, event) -> None:
        """Zoom on the wheel; the drag mode already handles panning."""
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.05 < scale < 200:
            self.scale(factor, factor)
