"""Undo/redo.

Every change to a document is a command with ``do()`` and ``undo()``, and the document is only ever
changed through one. That rule is cheap now and painful to retrofit: as soon as one code path mutates the
document directly, undo silently loses steps.

A command records the state it needs for ``undo()`` when it runs, not when it is constructed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .document import Document
from .layer import LaserParams
from .objects import DocumentObject


class Command(ABC):
    """One reversible change."""

    @abstractmethod
    def do(self, document: Document) -> None: ...

    @abstractmethod
    def undo(self, document: Document) -> None: ...


class UndoStack:
    """Executes commands against one document and keeps the history."""

    def __init__(self, document: Document) -> None:
        self.document = document
        self._done: list[Command] = []
        self._undone: list[Command] = []

    def execute(self, command: Command) -> None:
        command.do(self.document)
        self._done.append(command)
        self._undone.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    def undo(self) -> None:
        if not self._done:
            return
        command = self._done.pop()
        command.undo(self.document)
        self._undone.append(command)

    def redo(self) -> None:
        if not self._undone:
            return
        command = self._undone.pop()
        command.do(self.document)
        self._done.append(command)


@dataclass
class AddObject(Command):
    """Insert an object into a layer, at the top of its z-order unless ``index`` says otherwise."""

    layer_index: int
    obj: DocumentObject
    index: int | None = None

    def do(self, document: Document) -> None:
        objects = document.layers[self.layer_index].objects
        if self.index is None:
            self.index = len(objects)
        objects.insert(self.index, self.obj)

    def undo(self, document: Document) -> None:
        document.layers[self.layer_index].objects.pop(self.index)


@dataclass
class RemoveObject(Command):
    """Take an object out of the document, remembering where it was."""

    object_id: str
    _position: tuple[int, int] = field(default=(0, 0), init=False)
    _obj: DocumentObject | None = field(default=None, init=False)

    def do(self, document: Document) -> None:
        li, oi = document.find(self.object_id)
        self._position = (li, oi)
        self._obj = document.layers[li].objects.pop(oi)

    def undo(self, document: Document) -> None:
        li, oi = self._position
        document.layers[li].objects.insert(oi, self._obj)


@dataclass
class MoveObject(Command):
    """Move an object to another layer or another position in the z-order. Geometry is untouched."""

    object_id: str
    to_layer: int
    to_index: int | None = None
    _from: tuple[int, int] = field(default=(0, 0), init=False)

    def do(self, document: Document) -> None:
        li, oi = document.find(self.object_id)
        self._from = (li, oi)
        obj = document.layers[li].objects.pop(oi)
        target = document.layers[self.to_layer].objects
        if self.to_index is None:
            self.to_index = len(target)
        target.insert(self.to_index, obj)

    def undo(self, document: Document) -> None:
        obj = document.layers[self.to_layer].objects.pop(self.to_index)
        li, oi = self._from
        document.layers[li].objects.insert(oi, obj)


@dataclass
class SetLayerVisible(Command):
    """Show or hide a layer. Undoable like everything else — a hidden layer is not engraved."""

    layer_index: int
    visible: bool
    _previous: bool = field(default=True, init=False)

    def do(self, document: Document) -> None:
        layer = document.layers[self.layer_index]
        self._previous = layer.visible
        layer.visible = self.visible

    def undo(self, document: Document) -> None:
        document.layers[self.layer_index].visible = self._previous


@dataclass
class SetLayerParams(Command):
    """Replace a layer's laser parameters."""

    layer_index: int
    params: LaserParams
    _previous: LaserParams | None = field(default=None, init=False)

    def do(self, document: Document) -> None:
        layer = document.layers[self.layer_index]
        self._previous = layer.params
        layer.params = self.params

    def undo(self, document: Document) -> None:
        document.layers[self.layer_index].params = self._previous
