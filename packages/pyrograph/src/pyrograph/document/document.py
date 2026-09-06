"""The document: a work area of a given size holding layers of objects.

The document is plain data with read-only helpers. Every mutation goes through a command
(:mod:`pyrograph.document.commands`) so that undo works everywhere without each caller remembering to
record what it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Rect
from .layer import Layer
from .objects import DocumentObject


@dataclass
class Document:
    """Work area and layer stack. Layer 0 is the bottom of the z-order."""

    width_mm: float = 100.0
    height_mm: float = 100.0
    layers: list[Layer] = field(default_factory=lambda: [Layer()])

    def objects(self):
        """Every object in the document, bottom layer first."""
        for layer in self.layers:
            yield from layer.objects

    def find(self, object_id: str) -> tuple[int, int]:
        """Locate an object as ``(layer index, position in the layer)``."""
        for li, layer in enumerate(self.layers):
            for oi, obj in enumerate(layer.objects):
                if obj.id == object_id:
                    return li, oi
        raise KeyError(object_id)

    def object(self, object_id: str) -> DocumentObject:
        li, oi = self.find(object_id)
        return self.layers[li].objects[oi]

    def bounds(self) -> Rect | None:
        """The bounding box of all objects in visible layers, or ``None`` if there are none."""
        box: Rect | None = None
        for layer in self.layers:
            if not layer.visible:
                continue
            for obj in layer.objects:
                box = obj.bounds() if box is None else box.union(obj.bounds())
        return box
