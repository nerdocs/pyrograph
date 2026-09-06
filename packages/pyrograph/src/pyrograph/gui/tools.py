"""What the mouse does on the canvas.

One object per mouse mode. The canvas owns the scene, the selection and the snapping; a tool only decides
what a press, a drag and a release mean, and asks the canvas to show a preview or to make a change. Adding
a tool is therefore a class here plus one line in :data:`TOOLS` — no new branch in the canvas.

Positions arrive in document millimetres, already snapped where snapping applies.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from ..document import Path, PathObject, Point, Rect, Transform

MIN_SCALE = 0.01
"""How far a scale handle may collapse a selection. Zero would destroy the geometry beyond recovery."""


class Tool:
    """A mouse mode."""

    name = ""
    label = ""
    cursor = Qt.CursorShape.CrossCursor

    def activate(self, canvas) -> None: ...

    def deactivate(self, canvas) -> None:
        """Drop whatever half-finished state the tool was holding."""

    def press(self, canvas, point: Point, event) -> None: ...

    def move(self, canvas, point: Point, event) -> None: ...

    def release(self, canvas, point: Point, event) -> None: ...

    def double_click(self, canvas, point: Point, event) -> None: ...

    def cancel(self, canvas) -> None:
        """Escape was pressed."""
        self.deactivate(canvas)


class PanTool(Tool):
    """Drag the view. The canvas' own drag mode does the work."""

    name = "pan"
    label = "Pan"
    cursor = Qt.CursorShape.OpenHandCursor


class SelectTool(Tool):
    """Click to select, drag to move, drag a handle to scale, drag the background to rubber-band select."""

    name = "select"
    label = "Select"
    cursor = Qt.CursorShape.ArrowCursor

    def __init__(self) -> None:
        self._mode = ""
        self._start = Point()
        self._anchor = Point()
        self._handle = 0
        self._bounds: Rect | None = None

    def press(self, canvas, point: Point, event) -> None:
        handle = canvas.handle_at(event.position())
        if handle is not None:
            self._mode = "scale"
            self._handle = handle
            self._bounds = canvas.selection_bounds()
            self._anchor = _anchor_for(self._bounds, handle)
            self._start = point
            canvas.begin_preview()
            return

        object_id = canvas.object_at(event.position())
        if object_id is None:
            if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                canvas.set_selection([])
            self._mode = "band"
            self._start = point
            canvas.begin_band(point)
            return

        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            canvas.toggle_selection(object_id)
        elif object_id not in canvas.selection:
            canvas.set_selection([object_id])
        self._mode = "move"
        self._start = point
        self._bounds = canvas.selection_bounds()
        canvas.begin_preview()

    def move(self, canvas, point: Point, event) -> None:
        if self._mode == "band":
            canvas.update_band(point)
        elif self._mode in ("move", "scale"):
            canvas.preview(self._transform(canvas, point, event))

    def release(self, canvas, point: Point, event) -> None:
        if self._mode == "band":
            canvas.select_in(canvas.end_band())
        elif self._mode in ("move", "scale"):
            canvas.commit_preview(self._transform(canvas, point, event))
        self._mode = ""

    def _transform(self, canvas, point: Point, event) -> Transform:
        if self._mode == "move":
            # Snap where the selection lands, not where the pointer is: the corner is what has to sit on
            # the grid line, and the pointer grabbed the object somewhere in the middle.
            box = self._bounds
            raw = Point(box.x + point.x - self._start.x, box.y + point.y - self._start.y)
            target = canvas.snap_point(raw)
            return Transform.translate(target.x - box.x, target.y - box.y)

        corner = canvas.snap_point(point)
        sx = _factor(corner.x - self._anchor.x, self._start.x - self._anchor.x)
        sy = _factor(corner.y - self._anchor.y, self._start.y - self._anchor.y)
        if self._handle in (1, 5):  # a top or bottom edge scales height only
            sx = 1.0
        if self._handle in (3, 7):
            sy = 1.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._handle in (0, 2, 4, 6):
            sx = sy = max(abs(sx), abs(sy))
        return (
            Transform.translate(-self._anchor.x, -self._anchor.y)
            .then(Transform.scale(sx, sy))
            .then(Transform.translate(self._anchor.x, self._anchor.y))
        )


def _anchor_for(bounds: Rect, handle: int) -> Point:
    """The point that stays put while ``handle`` is dragged — the one opposite it."""
    return handle_points(bounds)[(handle + 4) % 8]


def handle_points(bounds: Rect) -> list[Point]:
    """The eight handles, clockwise from the top left corner."""
    left, middle, right = bounds.x, bounds.x + bounds.width / 2, bounds.right
    top, centre, bottom = bounds.y, bounds.y + bounds.height / 2, bounds.bottom
    return [
        Point(left, top),
        Point(middle, top),
        Point(right, top),
        Point(right, centre),
        Point(right, bottom),
        Point(middle, bottom),
        Point(left, bottom),
        Point(left, centre),
    ]


def _factor(now: float, before: float) -> float:
    """The scale one axis was dragged by, kept away from zero so nothing collapses to a point."""
    if abs(before) < 1e-9:
        return 1.0
    factor = now / before
    if abs(factor) < MIN_SCALE:
        return MIN_SCALE if factor >= 0 else -MIN_SCALE
    return factor


class ShapeTool(Tool):
    """Drag out a line, a rectangle or an ellipse."""

    def __init__(self, kind: str, label: str) -> None:
        self.name = kind
        self.label = label
        self._origin: Point | None = None

    def press(self, canvas, point: Point, event) -> None:
        self._origin = canvas.snap_point(point)

    def move(self, canvas, point: Point, event) -> None:
        if self._origin is not None:
            canvas.set_ghost(self._path(self._origin, canvas.snap_point(point)))

    def release(self, canvas, point: Point, event) -> None:
        if self._origin is None:
            return
        path = self._path(self._origin, canvas.snap_point(point))
        self._origin = None
        canvas.clear_ghost()
        if path.bounds().width > 0 or path.bounds().height > 0:
            canvas.add_object(PathObject(name=self.label, path=path))

    def deactivate(self, canvas) -> None:
        self._origin = None
        canvas.clear_ghost()

    def _path(self, start: Point, end: Point) -> Path:
        if self.name == "line":
            return Path.line(start.x, start.y, end.x, end.y)
        left, top = min(start.x, end.x), min(start.y, end.y)
        width, height = abs(end.x - start.x), abs(end.y - start.y)
        if self.name == "rect":
            return Path.rect(left, top, width, height)
        return Path.ellipse(left + width / 2, top + height / 2, width / 2, height / 2)


class PolylineTool(Tool):
    """Click point after point; double-click or Enter finishes, Escape throws it away."""

    def __init__(self, close: bool) -> None:
        self.name = "polygon" if close else "polyline"
        self.label = "Polygon" if close else "Polyline"
        self._close = close
        self._points: list[Point] = []

    def press(self, canvas, point: Point, event) -> None:
        self._points.append(canvas.snap_point(point))

    def move(self, canvas, point: Point, event) -> None:
        if self._points:
            canvas.set_ghost(Path.polyline(self._points + [canvas.snap_point(point)], self._close))

    def double_click(self, canvas, point: Point, event) -> None:
        self.finish(canvas)

    def finish(self, canvas) -> None:
        points, self._points = self._points, []
        canvas.clear_ghost()
        if len(points) > 1:
            canvas.add_object(PathObject(name=self.label, path=Path.polyline(points, self._close)))

    def deactivate(self, canvas) -> None:
        self._points = []
        canvas.clear_ghost()


class PlaceTool(Tool):
    """Ask for a text, a QR code or a barcode, then drop it where it was clicked.

    The dialog itself belongs to the window — a canvas that opens dialogs is a canvas that cannot be
    tested without a screen — so the tool only reports the click.
    """

    def __init__(self, kind: str, label: str) -> None:
        self.name = kind
        self.label = label

    def press(self, canvas, point: Point, event) -> None:
        canvas.place_requested.emit(self.name, canvas.snap_point(point))


def build_tools() -> list[Tool]:
    """Every tool, in the order the palette shows them."""
    return [
        SelectTool(),
        PanTool(),
        ShapeTool("line", "Line"),
        ShapeTool("rect", "Rectangle"),
        ShapeTool("ellipse", "Ellipse"),
        PolylineTool(close=False),
        PolylineTool(close=True),
        PlaceTool("text", "Text"),
        PlaceTool("qr", "QR code"),
        PlaceTool("barcode", "Barcode"),
    ]
