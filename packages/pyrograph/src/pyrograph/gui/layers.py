"""The layer panel — the layer stack and the laser parameters of the selected layer.

Parameters sit on the layer, not on the object (see :mod:`pyrograph.document.layer`), so this one panel is
where a document is told how it burns. Every edit goes through the undo stack; the panel itself never
writes to the document.

Edits are applied on ``editingFinished`` rather than on every keystroke, so typing "60" into a spin box
leaves one undo step behind instead of two.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..document import Document, LaserParams, SetLayerParams, SetLayerVisible, UndoStack


class LayerPanel(QWidget):
    """Layer list with visibility checkboxes, plus the parameter form for the selected layer."""

    changed = Signal()
    """A layer was edited — the document needs redrawing and the window needs marking dirty."""

    current_changed = Signal(int)
    """Another layer was selected. New objects go into it."""

    def __init__(self) -> None:
        super().__init__()
        self._document: Document | None = None
        self._undo: UndoStack | None = None
        self._loading = False

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_params)
        self._list.currentRowChanged.connect(self.current_changed)
        self._list.itemChanged.connect(self._toggle_visible)

        self.power = QSpinBox(minimum=1, maximum=100, suffix=" %")
        self.depth = QSpinBox(minimum=1, maximum=100)
        self.passes = QSpinBox(minimum=1, maximum=99)
        self.speed = QSpinBox(minimum=0, maximum=1000, suffix=" mm/s")
        self.speed.setSpecialValueText("device default")
        self.dpi = QDoubleSpinBox(minimum=1.0, maximum=4000.0, decimals=0, suffix=" dpi")
        self.line_width = QDoubleSpinBox(minimum=0.01, maximum=10.0, decimals=2, singleStep=0.05, suffix=" mm")
        self.hatch = QDoubleSpinBox(minimum=0.0, maximum=10.0, decimals=2, singleStep=0.05, suffix=" mm")
        self.hatch.setSpecialValueText("outline only")
        self.hatch.setToolTip(
            "How far apart the lines are that fill a solid area on a machine that cannot raster"
        )
        self.hatch_angle = QDoubleSpinBox(minimum=-90.0, maximum=90.0, decimals=0, suffix="°")
        self.hatch_angle.setToolTip("Which way those lines run; zero is horizontal")
        self._fields = (
            self.power,
            self.depth,
            self.passes,
            self.speed,
            self.dpi,
            self.line_width,
            self.hatch,
            self.hatch_angle,
        )
        for field in self._fields:
            field.editingFinished.connect(self._apply_params)

        form = QFormLayout()
        form.addRow("Power", self.power)
        form.addRow("Depth", self.depth)
        form.addRow("Passes", self.passes)
        form.addRow("Speed", self.speed)
        form.addRow("Resolution", self.dpi)
        form.addRow("Line width", self.line_width)
        form.addRow("Fill spacing", self.hatch)
        form.addRow("Fill angle", self.hatch_angle)
        box = QGroupBox("Laser parameters")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addWidget(box)
        self._enable(False)

    def set_document(self, document: Document, undo: UndoStack) -> None:
        self._document = document
        self._undo = undo
        self.reload()

    def reload(self) -> None:
        """Rebuild the list from the document — after loading, importing, undo or redo."""
        if self._document is None:
            return
        row = self._list.currentRow()
        self._loading = True
        self._list.clear()
        for layer in self._document.layers:
            item = QListWidgetItem(f"{layer.name} ({len(layer.objects)})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            self._list.addItem(item)
        self._loading = False
        self._list.setCurrentRow(min(max(row, 0), self._list.count() - 1))

    @property
    def current_index(self) -> int:
        return self._list.currentRow()

    def _enable(self, on: bool) -> None:
        for field in self._fields:
            field.setEnabled(on)

    def _show_params(self, row: int) -> None:
        self._enable(row >= 0)
        if self._document is None or row < 0:
            return
        params = self._document.layers[row].params
        self._loading = True
        self.power.setValue(params.power)
        self.depth.setValue(params.depth)
        self.passes.setValue(params.passes)
        self.speed.setValue(params.speed_mm_s)
        self.dpi.setValue(params.dpi)
        self.line_width.setValue(params.line_width_mm)
        self.hatch.setValue(params.hatch_mm)
        self.hatch_angle.setValue(params.hatch_angle)
        self._loading = False

    def _apply_params(self) -> None:
        if self._loading or self._document is None or self.current_index < 0:
            return
        params = LaserParams(
            power=self.power.value(),
            depth=self.depth.value(),
            passes=self.passes.value(),
            speed_mm_s=self.speed.value(),
            dpi=self.dpi.value(),
            line_width_mm=self.line_width.value(),
            hatch_mm=self.hatch.value(),
            hatch_angle=self.hatch_angle.value(),
        )
        if params == self._document.layers[self.current_index].params:
            return  # focus left a spin box nobody touched
        self._undo.execute(SetLayerParams(self.current_index, params))
        self.changed.emit()

    def _toggle_visible(self, item: QListWidgetItem) -> None:
        if self._loading or self._undo is None:
            return
        visible = item.checkState() is Qt.CheckState.Checked
        self._undo.execute(SetLayerVisible(self._list.row(item), visible))
        self.changed.emit()
