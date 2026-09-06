"""The small dialogs: text, QR code, barcode, array.

Each one asks for what a generator needs and returns a finished
:class:`~pyrograph.document.DocumentObject` — or ``None`` when it was cancelled. Keeping the object
construction here means the canvas never has to know that a QR code exists; it only reports where it was
clicked.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ..codes import BARCODE_SYMBOLOGIES, barcode, qr_code
from ..document import DocumentObject, Point, TextObject, Transform
from . import fonts


class _Dialog(QDialog):
    """A form with an OK and a Cancel button. Saves every dialog below the same six lines."""

    def __init__(self, parent, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = QFormLayout()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(buttons)

    def exec(self) -> int:
        """Open with the cursor in the first field.

        The button box exists before the caller has filled the form, so it comes first in the focus chain
        and would take the keyboard: typing would go nowhere and Space would confirm the dialog. Focusing
        as if by Tab also selects what the field already holds, so a default value is simply typed over.
        """
        row = self.form.itemAt(0, QFormLayout.ItemRole.FieldRole)
        if row is not None and row.widget() is not None:
            row.widget().setFocus(Qt.FocusReason.TabFocusReason)
        return super().exec()


def ask_text(parent, at: Point) -> DocumentObject | None:
    """A line of text in a chosen family, placed with its baseline at ``at``."""
    dialog = _Dialog(parent, "Text")
    content = QLineEdit("Text")
    family = QFontComboBox()
    size = QDoubleSpinBox(minimum=1.0, maximum=500.0, value=10.0, decimals=1, suffix=" mm")
    dialog.form.addRow("Text", content)
    dialog.form.addRow("Font", family)
    dialog.form.addRow("Height", size)
    if dialog.exec() != QDialog.DialogCode.Accepted or not content.text():
        return None

    path = fonts.path_for(family.currentFont().family())
    if path is None:
        QMessageBox.warning(
            parent,
            "Text",
            f"No font file found for {family.currentFont().family()!r}. "
            "Text is converted to outlines from the file, so the family has to exist on disk.",
        )
        return None
    return TextObject(
        name=content.text()[:20],
        text=content.text(),
        font_path=path,
        size_mm=size.value(),
        transform=Transform.translate(at.x, at.y),
    )


def ask_qr(parent, at: Point) -> DocumentObject | None:
    dialog = _Dialog(parent, "QR code")
    content = QLineEdit()
    size = QDoubleSpinBox(minimum=2.0, maximum=500.0, value=25.0, decimals=1, suffix=" mm")
    error = QComboBox()
    error.addItems(["L — 7 %", "M — 15 %", "Q — 25 %", "H — 30 %"])
    error.setCurrentIndex(1)
    dialog.form.addRow("Content", content)
    dialog.form.addRow("Size", size)
    dialog.form.addRow("Error correction", error)
    if dialog.exec() != QDialog.DialogCode.Accepted or not content.text():
        return None
    obj = qr_code(content.text(), size.value(), "LMQH"[error.currentIndex()])
    obj.transform = Transform.translate(at.x, at.y)
    return obj


def ask_barcode(parent, at: Point) -> DocumentObject | None:
    dialog = _Dialog(parent, "Barcode")
    content = QLineEdit()
    symbology = QComboBox()
    symbology.addItems(BARCODE_SYMBOLOGIES)
    width = QDoubleSpinBox(minimum=5.0, maximum=500.0, value=50.0, decimals=1, suffix=" mm")
    height = QDoubleSpinBox(minimum=2.0, maximum=200.0, value=15.0, decimals=1, suffix=" mm")
    dialog.form.addRow("Content", content)
    dialog.form.addRow("Symbology", symbology)
    dialog.form.addRow("Width", width)
    dialog.form.addRow("Height", height)
    if dialog.exec() != QDialog.DialogCode.Accepted or not content.text():
        return None
    try:
        obj = barcode(content.text(), symbology.currentText(), width.value(), height.value())
    except Exception as error:  # every symbology rejects its own kind of invalid input
        QMessageBox.warning(parent, "Barcode", str(error))
        return None
    obj.transform = Transform.translate(at.x, at.y)
    return obj


def ask_array(parent, spacing_mm: float) -> tuple[int, int, float, float] | None:
    """Columns, rows and the step between copies. ``spacing_mm`` seeds the step with the selection's size."""
    dialog = _Dialog(parent, "Duplicate as array")
    columns = QSpinBox(minimum=1, maximum=100, value=2)
    rows = QSpinBox(minimum=1, maximum=100, value=2)
    dx = QDoubleSpinBox(minimum=-500.0, maximum=500.0, value=spacing_mm, decimals=1, suffix=" mm")
    dy = QDoubleSpinBox(minimum=-500.0, maximum=500.0, value=spacing_mm, decimals=1, suffix=" mm")
    dialog.form.addRow("Columns", columns)
    dialog.form.addRow("Rows", rows)
    dialog.form.addRow("Step across", dx)
    dialog.form.addRow("Step down", dy)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return columns.value(), rows.value(), dx.value(), dy.value()


ASK = {"text": ask_text, "qr": ask_qr, "barcode": ask_barcode}
"""Which dialog a place tool opens."""
