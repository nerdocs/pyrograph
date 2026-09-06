"""Millimetre scales along the canvas.

A laser job is measured work: the interesting question is rarely "where on screen" but "how many
millimetres from the edge". The rulers read their range straight out of the view's transform, so they
cannot drift out of step with what is drawn — there is no second copy of the zoom factor anywhere.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QWidget

THICKNESS = 22
_STEPS = (1, 2, 5, 10, 20, 50, 100, 200, 500)
_LABEL_PX = 55
"""Wanted distance between two labelled ticks. The step is the first one that reaches it."""

_BACKGROUND = QColor("#f0f0f0")
_LINE = QColor("#707070")
_TEXT = QColor("#303030")


def _step_mm(pixels_per_mm: float) -> float:
    for step in _STEPS:
        if step * pixels_per_mm >= _LABEL_PX:
            return step
    return _STEPS[-1]


class Ruler(QWidget):
    """One scale, horizontal above the canvas or vertical to its left."""

    def __init__(self, view, horizontal: bool) -> None:
        super().__init__()
        self._view = view
        self._horizontal = horizontal
        self._cursor_mm: float | None = None
        if horizontal:
            self.setFixedHeight(THICKNESS)
        else:
            self.setFixedWidth(THICKNESS)
        font = QFont(self.font())
        font.setPointSizeF(max(6.0, font.pointSizeF() - 2))
        self.setFont(font)

    def show_cursor(self, point) -> None:
        """Mark where the pointer is, or clear the mark when it left the canvas."""
        value = None if point is None else (point.x if self._horizontal else point.y)
        if value != self._cursor_mm:
            self._cursor_mm = value
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BACKGROUND)

        pixels_per_mm = self._view.transform().m11()
        if pixels_per_mm <= 0:
            return
        length = self.width() if self._horizontal else self.height()
        start_mm = self._to_mm(0)
        step = _step_mm(pixels_per_mm)

        tick = (int(start_mm / step) - 1) * step
        while True:
            position = self._to_pixels(tick)
            if position > length:
                break
            if position >= 0:
                self._draw_tick(painter, position, tick, minor=False)
            for minor in range(1, 5):
                sub = self._to_pixels(tick + step * minor / 5)
                if 0 <= sub <= length:
                    self._draw_tick(painter, sub, None, minor=True)
            tick += step

        if self._cursor_mm is not None:
            painter.setPen(QPen(QColor("#1c7ed6")))
            position = self._to_pixels(self._cursor_mm)
            if self._horizontal:
                painter.drawLine(QPointF(position, 0), QPointF(position, THICKNESS))
            else:
                painter.drawLine(QPointF(0, position), QPointF(THICKNESS, position))

    def _draw_tick(self, painter: QPainter, position: float, label: float | None, minor: bool) -> None:
        size = 4 if minor else THICKNESS
        painter.setPen(QPen(_LINE))
        if self._horizontal:
            painter.drawLine(QPointF(position, THICKNESS - size), QPointF(position, THICKNESS))
            if label is not None:
                painter.setPen(QPen(_TEXT))
                painter.drawText(QPointF(position + 2, THICKNESS - 9), f"{label:g}")
        else:
            painter.drawLine(QPointF(THICKNESS - size, position), QPointF(THICKNESS, position))
            if label is not None:
                painter.setPen(QPen(_TEXT))
                # Vertical labels read from the bottom up, the way every drawing program writes them.
                painter.save()
                painter.translate(THICKNESS - 10, position - 2)
                painter.rotate(-90)
                painter.drawText(QPointF(0, 0), f"{label:g}")
                painter.restore()

    def _to_mm(self, pixels: float) -> float:
        point = self._view.mapToScene(int(pixels), int(pixels))
        return point.x() if self._horizontal else point.y()

    def _to_pixels(self, mm: float) -> float:
        point = self._view.mapFromScene(QPointF(mm, mm))
        return point.x() if self._horizontal else point.y()


class CanvasArea(QWidget):
    """The canvas with a ruler on two sides."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.horizontal = Ruler(view, horizontal=True)
        self.vertical = Ruler(view, horizontal=False)

        # No frame: a ruler pixel and a viewport pixel have to be the same pixel, or the scale lies.
        view.setFrameShape(QFrame.Shape.NoFrame)
        corner = QWidget()
        corner.setFixedSize(THICKNESS, THICKNESS)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(corner, 0, 0)
        layout.addWidget(self.horizontal, 0, 1)
        layout.addWidget(self.vertical, 1, 0)
        layout.addWidget(view, 1, 1)

        view.view_changed.connect(self.refresh)
        view.cursor_moved.connect(self.horizontal.show_cursor)
        view.cursor_moved.connect(self.vertical.show_cursor)

    def refresh(self) -> None:
        self.horizontal.update()
        self.vertical.update()
