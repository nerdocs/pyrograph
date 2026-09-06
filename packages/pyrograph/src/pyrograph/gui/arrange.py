"""Aligning, mirroring, rotating and duplicating a selection.

Everything in here returns a :class:`~pyrograph.document.Command` and changes nothing itself, so the window
puts it on the undo stack like any other edit and one menu entry stays one undo step.

The reference for aligning is the selection's own bounding box, except when a single object is selected —
then there is nothing to align it to but the work area, which is what "centre this on the bed" means.
"""

from __future__ import annotations

from ..document import (
    AddObject,
    CommandGroup,
    Document,
    Point,
    Rect,
    Transform,
    TransformObject,
)

EDGES = ("left", "centre", "right", "top", "middle", "bottom")


def _bounds(document: Document, ids: list[str]) -> Rect | None:
    box = None
    for object_id in ids:
        other = document.object(object_id).bounds()
        box = other if box is None else box.union(other)
    return box


def _offset_to(box: Rect, target: Rect, edge: str) -> tuple[float, float]:
    if edge == "left":
        return target.x - box.x, 0.0
    if edge == "right":
        return target.right - box.right, 0.0
    if edge == "centre":
        return (target.x + target.width / 2) - (box.x + box.width / 2), 0.0
    if edge == "top":
        return 0.0, target.y - box.y
    if edge == "bottom":
        return 0.0, target.bottom - box.bottom
    return 0.0, (target.y + target.height / 2) - (box.y + box.height / 2)


def align(document: Document, ids: list[str], edge: str) -> CommandGroup | None:
    """Line the selection up on one edge — or centre a single object on the work area."""
    if not ids:
        return None
    target = _bounds(document, ids) if len(ids) > 1 else Rect(0, 0, document.width_mm, document.height_mm)
    commands = []
    for object_id in ids:
        dx, dy = _offset_to(document.object(object_id).bounds(), target, edge)
        if dx or dy:
            commands.append(TransformObject(object_id, Transform.translate(dx, dy)))
    return CommandGroup(commands) if commands else None


def distribute(document: Document, ids: list[str], horizontal: bool) -> CommandGroup | None:
    """Space the selection evenly between the two outermost objects. Needs at least three."""
    if len(ids) < 3:
        return None
    boxes = {i: document.object(i).bounds() for i in ids}
    centre = (lambda b: b.x + b.width / 2) if horizontal else (lambda b: b.y + b.height / 2)
    order = sorted(ids, key=lambda i: centre(boxes[i]))
    first, last = centre(boxes[order[0]]), centre(boxes[order[-1]])
    gap = (last - first) / (len(order) - 1)
    commands = []
    for index, object_id in enumerate(order[1:-1], start=1):
        delta = first + gap * index - centre(boxes[object_id])
        if delta:
            move = Transform.translate(delta, 0.0) if horizontal else Transform.translate(0.0, delta)
            commands.append(TransformObject(object_id, move))
    return CommandGroup(commands) if commands else None


def _about_centre(document: Document, ids: list[str], transform_at: object) -> CommandGroup | None:
    box = _bounds(document, ids)
    if box is None:
        return None
    cx, cy = box.x + box.width / 2, box.y + box.height / 2
    transform = transform_at(cx, cy)
    return CommandGroup([TransformObject(i, transform) for i in ids])


def mirror(document: Document, ids: list[str], horizontal: bool) -> CommandGroup | None:
    """Flip the selection about its own centre."""
    scale = Transform.scale(-1.0, 1.0) if horizontal else Transform.scale(1.0, -1.0)
    return _about_centre(
        document,
        ids,
        lambda cx, cy: Transform.translate(-cx, -cy).then(scale).then(Transform.translate(cx, cy)),
    )


def rotate(document: Document, ids: list[str], degrees: float) -> CommandGroup | None:
    """Turn the selection about its own centre."""
    return _about_centre(
        document, ids, lambda cx, cy: Transform.rotate(degrees, Point(cx, cy))
    )


def array(
    document: Document,
    ids: list[str],
    columns: int,
    rows: int,
    dx_mm: float,
    dy_mm: float,
) -> CommandGroup | None:
    """Copy the selection into a ``columns`` × ``rows`` grid, the original staying in place.

    Each copy lands in the layer of the object it was made from, so a two-layer design keeps its
    parameters instead of collapsing onto one.
    """
    if not ids or columns * rows <= 1:
        return None
    commands = []
    for column in range(columns):
        for row in range(rows):
            if column == 0 and row == 0:
                continue
            for object_id in ids:
                layer_index, _ = document.find(object_id)
                clone = document.object(object_id).clone()
                clone.transform = clone.transform.then(
                    Transform.translate(column * dx_mm, row * dy_mm)
                )
                commands.append(AddObject(layer_index, clone))
    return CommandGroup(commands)
