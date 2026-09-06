"""Icons for the tool palette, drawn instead of shipped.

Ten small pictograms are not worth an asset pipeline, a licence question and a set of files that have to be
kept in sync with the code. They are drawn with the same painter that draws the canvas, in the palette's
own text colour, so they follow a light or dark theme without a second set of images.

The toolbar above the canvas uses the desktop's icon theme (``document-open`` and friends); those exist
everywhere and looking native beats looking hand-drawn.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE = 24


def _pen(painter: QPainter, width: float = 1.6) -> QPen:
    pen = QPen(painter.pen())
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    return pen


def _arrow(painter: QPainter) -> None:
    path = QPainterPath(QPointF(7, 4))
    for point in ((17, 13), (12, 13.5), (14.5, 19), (12, 20), (9.5, 14.5), (6, 18)):
        path.lineTo(*point)
    path.closeSubpath()
    painter.fillPath(path, painter.pen().color())


def _hand(painter: QPainter) -> None:
    _pen(painter)
    painter.drawRoundedRect(QRectF(8, 9, 9, 11), 3, 3)
    for x in (10.5, 13.5):
        painter.drawLine(QPointF(x, 9), QPointF(x, 4.5))
    painter.drawLine(QPointF(8, 12), QPointF(5, 15))


def _line(painter: QPainter) -> None:
    _pen(painter)
    painter.drawLine(QPointF(5, 19), QPointF(19, 5))


def _rect(painter: QPainter) -> None:
    _pen(painter)
    painter.drawRect(QRectF(4, 6, 16, 12))


def _ellipse(painter: QPainter) -> None:
    _pen(painter)
    painter.drawEllipse(QRectF(4, 6, 16, 12))


def _polyline(painter: QPainter) -> None:
    _pen(painter)
    path = QPainterPath(QPointF(4, 17))
    for point in ((9, 7), (14, 15), (20, 6)):
        path.lineTo(*point)
    painter.drawPath(path)


def _polygon(painter: QPainter) -> None:
    _pen(painter)
    path = QPainterPath(QPointF(12, 4))
    for point in ((20, 10), (17, 19), (7, 19), (4, 10)):
        path.lineTo(*point)
    path.closeSubpath()
    painter.drawPath(path)


def _text(painter: QPainter) -> None:
    _pen(painter, 2.0)
    painter.drawLine(QPointF(5, 6), QPointF(19, 6))
    painter.drawLine(QPointF(12, 6), QPointF(12, 19))


def _qr(painter: QPainter) -> None:
    _pen(painter, 1.3)
    for x, y in ((4, 4), (14, 4), (4, 14)):
        painter.drawRect(QRectF(x, y, 6, 6))
        painter.fillRect(QRectF(x + 2, y + 2, 2, 2), painter.pen().color())
    for x, y in ((14, 14), (18, 14), (14, 18), (18, 18), (16, 16)):
        painter.fillRect(QRectF(x, y, 2, 2), painter.pen().color())


def _barcode(painter: QPainter) -> None:
    colour = painter.pen().color()
    for x, width in ((4, 1), (6, 2), (9.5, 1), (12, 3), (16, 1), (18, 2)):
        painter.fillRect(QRectF(x, 5, width, 14), colour)


_DRAW = {
    "select": _arrow,
    "pan": _hand,
    "line": _line,
    "rect": _rect,
    "ellipse": _ellipse,
    "polyline": _polyline,
    "polygon": _polygon,
    "text": _text,
    "qr": _qr,
    "barcode": _barcode,
}


def tool_icon(name: str, colour) -> QIcon:
    """The pictogram for a tool, drawn in ``colour``."""
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(colour))
    _DRAW[name](painter)
    painter.end()
    return QIcon(pixmap)


def themed(name: str) -> QIcon:
    """A desktop icon by name. An empty icon where the theme has none — the button keeps its label."""
    return QIcon.fromTheme(name)
