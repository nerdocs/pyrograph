"""The document model — geometry, objects, layers, undo and the ``.pyg`` file format.

Nothing in here imports Qt or talks to a device. That is deliberate: the model stays testable without
hardware, and a later GUI change touches nothing below it.
"""

from .commands import (
    AddObject,
    Command,
    CommandGroup,
    MoveObject,
    RemoveObject,
    SetLayerParams,
    SetLayerVisible,
    TransformObject,
    UndoStack,
)
from .document import Document
from .geometry import Close, CubicTo, LineTo, MoveTo, Path, Point, Rect, Transform
from .layer import LaserParams, Layer
from .objects import DocumentObject, ImageObject, PathObject, TextObject, new_id
from .serialize import load_pyg, save_pyg
from .svg import SvgImport, SvgImportError, import_svg

__all__ = [
    "AddObject",
    "Close",
    "Command",
    "CommandGroup",
    "CubicTo",
    "Document",
    "DocumentObject",
    "ImageObject",
    "LaserParams",
    "Layer",
    "LineTo",
    "MoveObject",
    "MoveTo",
    "Path",
    "PathObject",
    "Point",
    "Rect",
    "RemoveObject",
    "SetLayerParams",
    "SetLayerVisible",
    "SvgImport",
    "SvgImportError",
    "TextObject",
    "Transform",
    "TransformObject",
    "UndoStack",
    "import_svg",
    "load_pyg",
    "new_id",
    "save_pyg",
]
