"""The work area — what the document looks like on the machine bed, and where it is edited.

One scene unit is one millimetre and y grows downwards, exactly like the document model. Nothing is
converted on the way in, so the view's scale is the only zoom factor and a 0.1 mm stroke is drawn 0.1
units wide — the same width it will burn.

The canvas owns the scene, the selection and the snapping, and it never writes to the document: an edit
leaves as a :class:`~pyrograph.document.Command` on :attr:`CanvasView.edit_requested`, and the window
decides when it goes on the undo stack. What a press and a drag *mean* belongs to the active tool
(:mod:`pyrograph.gui.tools`).

The scene is rebuilt wholesale from the document. That is cheap for the object counts an engraving
document has, and it keeps the canvas free of any state that could drift away from the model.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from ..document import (
    AddObject,
    Close,
    CommandGroup,
    CubicTo,
    Document,
    DocumentObject,
    ImageObject,
    LineTo,
    MoveTo,
    Path,
    Point,
    Rect,
    TransformObject,
)
from ..document import Transform as DocTransform
from .tools import SelectTool, Tool, handle_points

HANDLE_PX = 8
"""Edge length of a scale handle, in screen pixels — it must not grow when the view zooms in."""

SNAP_PX = 6
"""How close the pointer has to come to a snap candidate, in screen pixels."""

_BED = QColor("#ffffff")
_BED_EDGE = QColor("#606060")
_GRID = QColor("#d8d8d8")
_INK = QColor("#101010")
_OUTSIDE = QColor("#3a3a3a")
_MARK = QColor("#1c7ed6")
_BROKEN = QColor("#d63939")


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


def _intersects(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


class CanvasView(QGraphicsView):
    """Shows the work area, holds the selection, and hands the mouse to the active tool."""

    edit_requested = Signal(object)
    """A :class:`~pyrograph.document.Command` the window should execute."""

    selection_changed = Signal()
    cursor_moved = Signal(object)
    """The pointer's position in millimetres, or ``None`` when it left the canvas."""

    place_requested = Signal(str, object)
    """A place tool was clicked: the kind (``text``, ``qr``, ``barcode``) and where."""

    view_changed = Signal()
    """The view was scrolled, zoomed or resized — the rulers have to follow."""

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(_OUTSIDE)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)

        self._document: Document | None = None
        self._items: dict[str, object] = {}
        self._bounds: dict[str, Rect] = {}
        self._locked: set[str] = set()
        self._overlay: list = []
        self._ghost = None
        self._band = None
        self._band_origin = Point()
        self._preview_base: dict[str, QTransform] = {}
        self._preview_bounds: Rect | None = None

        self.selection: list[str] = []
        self.target_layer = 0
        self.grid_mm = 10.0
        self.snap_to_grid = True
        self.snap_to_objects = True
        self.tool: Tool = SelectTool()
        self.setCursor(self.tool.cursor)

    # ------------------------------------------------------------------ document and drawing

    def set_document(self, document: Document) -> None:
        self._document = document
        self.selection = []
        self.rebuild()
        self.fit()
        self.selection_changed.emit()

    def rebuild(self) -> None:
        """Redraw everything from the document. Call after any change to it."""
        scene = self.scene()
        scene.clear()
        self._items, self._bounds, self._overlay, self._ghost, self._band = {}, {}, [], None, None
        self._locked = set()
        if self._document is None:
            return
        self._draw_bed(self._document)
        live = set()
        for layer in self._document.layers:
            if not layer.visible:
                continue
            for obj in layer.objects:
                live.add(obj.id)
                self._draw_object(obj, layer.params.line_width_mm)
        self.selection = [object_id for object_id in self.selection if object_id in live]
        margin = max(self._document.width_mm, self._document.height_mm) * 0.05
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-margin, -margin, margin, margin))
        self._update_overlay()

    def fit(self) -> None:
        """Scale so that the whole work area is visible."""
        if self._document is not None:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.view_changed.emit()

    def _draw_bed(self, document: Document) -> None:
        scene = self.scene()
        edge = QPen(_BED_EDGE)
        edge.setCosmetic(True)
        scene.addRect(0, 0, document.width_mm, document.height_mm, edge, _BED)

        step = self.grid_mm
        if step <= 0:
            return  # a step of zero would advance the loops below by nothing at all
        grid = QPainterPath()
        x = step
        while x < document.width_mm:
            grid.moveTo(x, 0)
            grid.lineTo(x, document.height_mm)
            x += step
        y = step
        while y < document.height_mm:
            grid.moveTo(0, y)
            grid.lineTo(document.width_mm, y)
            y += step
        pen = QPen(_GRID)
        pen.setCosmetic(True)
        scene.addPath(grid, pen)

    def _draw_object(self, obj: DocumentObject, line_width_mm: float) -> None:
        if isinstance(obj, ImageObject):
            pixmap = QPixmap.fromImage(QImage.fromData(obj.data))
            if pixmap.isNull():
                # Data no image library here can decode. Marking the place it claims beats letting the
                # redraw fail: a rebuild that raises takes undo down with it, and there is no way back
                # out of a document that cannot be drawn.
                item = self._draw_broken(obj)
            else:
                item = self.scene().addPixmap(pixmap)
                item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
                pixels_to_mm = DocTransform.scale(
                    obj.width_mm / pixmap.width(), obj.height_mm / pixmap.height()
                )
                item.setTransform(_qt_transform(pixels_to_mm.then(obj.transform)))
        else:
            path = _painter_path(obj.local_path().transformed(obj.transform))
            width = obj.stroke_width_mm if obj.stroke_width_mm is not None else line_width_mm
            if obj.fill and obj.stroke_width_mm is None:
                pen = QPen(Qt.PenStyle.NoPen)  # filled and unstroked, like the rasteriser draws it
            else:
                pen = QPen(_INK, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)  # as the rasteriser strokes it
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            brush = QBrush(_INK) if obj.fill else QBrush(Qt.BrushStyle.NoBrush)
            item = self.scene().addPath(path, pen, brush)
        item.setData(0, obj.id)
        self._items[obj.id] = item
        self._bounds[obj.id] = obj.bounds()
        if obj.locked:
            self._locked.add(obj.id)

    def _draw_broken(self, obj: ImageObject):
        """The outline an undecodable image would have occupied, so it can still be found and removed."""
        pen = QPen(_BROKEN)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        item = self.scene().addRect(QRectF(0, 0, obj.width_mm, obj.height_mm), pen)
        item.setTransform(_qt_transform(obj.transform))
        return item

    # ------------------------------------------------------------------ selection

    def set_selection(self, ids: list[str]) -> None:
        # Locked objects are filtered here rather than at every call site: nothing that cannot be
        # selected can be moved, scaled, aligned or deleted either, which is the whole of what locking
        # is supposed to mean.
        ids = [i for i in ids if i not in self._locked]
        if ids != self.selection:
            self.selection = ids
            self._update_overlay()
            self.selection_changed.emit()

    def toggle_selection(self, object_id: str) -> None:
        selection = [i for i in self.selection if i != object_id]
        if len(selection) == len(self.selection):
            selection.append(object_id)
        self.set_selection(selection)

    def select_all(self) -> None:
        self.set_selection(list(self._items))

    def select_in(self, rect: Rect, add: bool = False) -> None:
        """Select what the rectangle covers, adding to the selection instead of replacing it if asked."""
        found = [i for i, box in self._bounds.items() if _intersects(box, rect)]
        if add:
            found = self.selection + [i for i in found if i not in self.selection]
        self.set_selection(found)

    def selection_bounds(self) -> Rect | None:
        """The bounding box of everything selected, in millimetres."""
        box = None
        for object_id in self.selection:
            other = self._bounds[object_id]
            box = other if box is None else box.union(other)
        return box

    def object_at(self, position) -> str | None:
        """The topmost object under the pointer. A locked one is not there as far as the mouse cares —
        otherwise it would swallow the click and block the band select that was meant to go around it."""
        for item in self.items(position.toPoint()):
            if item.data(0) and item.data(0) not in self._locked:
                return item.data(0)
        return None

    def handle_at(self, position) -> int | None:
        for item in self.items(position.toPoint()):
            if item.data(1) is not None:
                return item.data(1)
        return None

    def _update_overlay(self) -> None:
        for item in self._overlay:
            self.scene().removeItem(item)
        self._overlay = []
        bounds = self.selection_bounds()
        if bounds is None:
            return
        self._draw_overlay(bounds)

    def _draw_overlay(self, bounds: Rect) -> None:
        pen = QPen(_MARK)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        frame = self.scene().addRect(QRectF(bounds.x, bounds.y, bounds.width, bounds.height), pen)
        frame.setZValue(10)
        self._overlay.append(frame)

        solid = QPen(_MARK)
        solid.setCosmetic(True)
        for index, point in enumerate(handle_points(bounds)):
            handle = self.scene().addRect(
                QRectF(-HANDLE_PX / 2, -HANDLE_PX / 2, HANDLE_PX, HANDLE_PX), solid, _BED
            )
            handle.setPos(point.x, point.y)
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            handle.setZValue(11)
            handle.setData(1, index)
            self._overlay.append(handle)

    # ------------------------------------------------------------------ what tools ask for

    def snap_point(self, point: Point) -> Point:
        """The nearest grid line or object edge, if one is within :data:`SNAP_PX` of ``point``."""
        tolerance = SNAP_PX / max(self.transform().m11(), 1e-6)
        others = [box for i, box in self._bounds.items() if i not in self.selection]
        xs = [v for box in others for v in (box.x, box.x + box.width / 2, box.right)]
        ys = [v for box in others for v in (box.y, box.y + box.height / 2, box.bottom)]
        return Point(self._snap(point.x, tolerance, xs), self._snap(point.y, tolerance, ys))

    def _snap(self, value: float, tolerance: float, edges: list[float]) -> float:
        best, distance = value, tolerance
        if self.snap_to_grid and self.grid_mm > 0:
            grid = round(value / self.grid_mm) * self.grid_mm
            if abs(grid - value) < distance:
                best, distance = grid, abs(grid - value)
        if self.snap_to_objects:
            for edge in edges:
                if abs(edge - value) < distance:
                    best, distance = edge, abs(edge - value)
        return best

    def begin_preview(self) -> None:
        """Remember where the selected items sit, so a drag can show the result before committing."""
        self._preview_base = {i: self._items[i].transform() for i in self.selection if i in self._items}
        self._preview_bounds = self.selection_bounds()

    def preview(self, transform: DocTransform) -> None:
        matrix = _qt_transform(transform)
        for object_id, base in self._preview_base.items():
            self._items[object_id].setTransform(base * matrix)
        if self._preview_bounds is not None:
            for item in self._overlay:
                self.scene().removeItem(item)
            self._overlay = []
            self._draw_overlay(_transformed_rect(self._preview_bounds, transform))

    def commit_preview(self, transform: DocTransform) -> None:
        """Turn the previewed drag into one undoable change."""
        ids, self._preview_base, self._preview_bounds = list(self._preview_base), {}, None
        if transform.is_identity or not ids:
            self.rebuild()
            return
        self.edit_requested.emit(CommandGroup([TransformObject(i, transform) for i in ids]))

    def set_ghost(self, path: Path) -> None:
        """Show the shape a drawing tool is about to create."""
        self.clear_ghost()
        pen = QPen(_MARK)
        pen.setCosmetic(True)
        self._ghost = self.scene().addPath(_painter_path(path), pen)
        self._ghost.setZValue(9)

    def clear_ghost(self) -> None:
        if self._ghost is not None:
            self.scene().removeItem(self._ghost)
            self._ghost = None

    def begin_band(self, point: Point) -> None:
        pen = QPen(_MARK)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._band_origin = point
        self._band = self.scene().addRect(QRectF(point.x, point.y, 0, 0), pen)
        self._band.setZValue(9)

    def update_band(self, point: Point) -> None:
        if self._band is not None:
            origin = self._band_origin
            self._band.setRect(
                QRectF(
                    min(origin.x, point.x),
                    min(origin.y, point.y),
                    abs(point.x - origin.x),
                    abs(point.y - origin.y),
                )
            )

    def end_band(self) -> Rect:
        rect = self._band.rect()
        self.scene().removeItem(self._band)
        self._band = None
        return Rect(rect.x(), rect.y(), rect.width(), rect.height())

    def add_object(self, obj: DocumentObject) -> None:
        """Put a newly drawn object into the layer the layer panel has selected."""
        self.edit_requested.emit(AddObject(self.target_layer, obj))

    # ------------------------------------------------------------------ input

    def set_tool(self, tool: Tool) -> None:
        self.tool.deactivate(self)
        self.tool = tool
        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
            if tool.name == "pan"
            else QGraphicsView.DragMode.NoDrag
        )
        self.setCursor(tool.cursor)
        tool.activate(self)

    def _mm(self, position) -> Point:
        scene = self.mapToScene(position.toPoint())
        return Point(scene.x(), scene.y())

    def mousePressEvent(self, event) -> None:
        if self.tool.name == "pan":
            super().mousePressEvent(event)
            return
        if event.button() is Qt.MouseButton.LeftButton:
            self.tool.press(self, self._mm(event.position()), event)

    def mouseMoveEvent(self, event) -> None:
        point = self._mm(event.position())
        self.cursor_moved.emit(point)
        if self.tool.name == "pan":
            super().mouseMoveEvent(event)
            return
        self.tool.move(self, point, event)

    def mouseReleaseEvent(self, event) -> None:
        if self.tool.name == "pan":
            super().mouseReleaseEvent(event)
            return
        if event.button() is Qt.MouseButton.LeftButton:
            self.tool.release(self, self._mm(event.position()), event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tool.name != "pan" and event.button() is Qt.MouseButton.LeftButton:
            self.tool.double_click(self, self._mm(event.position()), event)

    def leaveEvent(self, event) -> None:
        self.cursor_moved.emit(None)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.tool.cancel(self)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and hasattr(self.tool, "finish"):
            self.tool.finish(self)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        """Zoom on the wheel; panning is the pan tool's or the scrollbars' job."""
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.05 < scale < 200:
            self.scale(factor, factor)
            self.view_changed.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.view_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view_changed.emit()


def _transformed_rect(rect: Rect, transform: DocTransform) -> Rect:
    """The bounding box of ``rect`` after ``transform`` — used to keep the handles on a dragged selection."""
    corners = [
        transform.apply(Point(rect.x, rect.y)),
        transform.apply(Point(rect.right, rect.y)),
        transform.apply(Point(rect.right, rect.bottom)),
        transform.apply(Point(rect.x, rect.bottom)),
    ]
    return Rect.from_points(corners)
