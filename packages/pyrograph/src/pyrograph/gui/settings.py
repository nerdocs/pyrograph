"""Machine settings that outlive a session.

A galvo cannot be used out of the box the way a LaserPecker can. Its scale and the shape of its field
belong to the lens screwed onto it, and no protocol reveals either — they arrive as a ``.cor`` file with
the machine. Until someone tells the program which lens is fitted, every job is marked at a guessed size.

So these settings are not a preferences panel in the usual sense: without them the device does not work
properly, which is why the dialog leads with the correction file and explains what happens without one.
Values are kept in :class:`~PySide6.QtCore.QSettings` — under Linux that is a file in ``~/.config``.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

ORGANISATION = "pyrograph"
APPLICATION = "pyrograph"

DEFAULT_GALVOS_PER_MM = 500.0
"""What a galvo falls back to. A guess about someone else's machine, and marked as one in the dialog."""


def settings() -> QSettings:
    return QSettings(ORGANISATION, APPLICATION)


def galvo_source() -> str:
    """Which laser is in the machine. Fiber and CO2 differ in how they are switched on and off."""
    return settings().value("galvo/source", "fiber", type=str)


def galvo_lens():
    """Build a :class:`ezcad2.Lens` from what was saved, or the default one if nothing was.

    Returns the lens and a list of complaints: a correction file that has moved or a calibration table
    that will not parse must not stop the program from opening, but the user has to hear about it —
    silently falling back to the default would mark at the wrong size with no explanation.
    """
    from ezcad2 import Lens, read_calibration

    stored = settings()
    problems: list[str] = []
    cor_file = stored.value("galvo/cor_file", "", type=str) or None
    scale = stored.value("galvo/galvos_per_mm", DEFAULT_GALVOS_PER_MM, type=float)

    calibration = None
    if stored.value("galvo/host_correction", False, type=bool):
        path = stored.value("galvo/calibration_file", "", type=str)
        if path:
            try:
                calibration = read_calibration(path)
            except (OSError, ValueError) as error:
                problems.append(f"the calibration table was not used: {error}")

    if cor_file:
        from pathlib import Path

        if not Path(cor_file).exists():
            problems.append(f"the correction file {cor_file} is gone; the field will be distorted")
            cor_file = None

    return Lens(galvos_per_mm=scale, cor_file=cor_file, calibration=calibration), problems


class _FileRow(QHBoxLayout):
    """A path with a Browse button. Two of these, so it is worth the six lines."""

    def __init__(self, placeholder: str, caption: str, pattern: str, parent: QDialog) -> None:
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(placeholderText=placeholder)
        self._caption, self._pattern, self._parent = caption, pattern, parent
        browse = QPushButton("Browse…", clicked=self._browse)
        self.addWidget(self.edit, 1)
        self.addWidget(browse)

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self._parent, self._caption, "", self._pattern)
        if path:
            self.edit.setText(path)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, value: str) -> None:
        self.edit.setText(value)


class GalvoSettings(QDialog):
    """Which lens is on the galvo, and how to compensate for it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Galvo settings")
        self.setMinimumWidth(520)

        self.source = QComboBox()
        for label, value in (("Fiber", "fiber"), ("CO₂", "co2")):
            self.source.addItem(label, value)

        self.cor_file = _FileRow("none — the field will be distorted", "Correction file", "*.cor", self)
        self.cor_file.edit.textChanged.connect(self._cor_file_changed)

        self.scale = QDoubleSpinBox(decimals=2, minimum=1.0, maximum=20000.0, singleStep=10.0)
        self.scale.setSuffix(" galvos/mm")
        self.field = QLabel()

        lens = QFormLayout()
        lens.addRow("Correction file", self.cor_file)
        lens.addRow("Scale", self.scale)
        lens.addRow("Field size", self.field)
        lens_box = _group(
            "Lens",
            lens,
            "The correction file comes with the machine and belongs to the lens fitted to it. Loading one "
            "fills in the scale it was calibrated at.",
        )

        machine = QFormLayout()
        machine.addRow("Laser source", self.source)
        machine_box = _group("Machine", machine)

        self.host_correction = QCheckBox("Correct the field in software as well")
        self.host_correction.toggled.connect(self._host_correction_toggled)
        self.calibration_file = _FileRow("measured grid", "Calibration table", "*.csv *.txt", self)

        experimental = QFormLayout()
        experimental.addRow(self.host_correction)
        experimental.addRow("Measured grid", self.calibration_file)
        experimental_box = _group(
            "Software field correction (experimental)",
            experimental,
            "Untested, and rarely needed — the correction file above is what a working machine uses. Turn "
            "this on only if the machine came without one, or the field is still bent with it loaded. The "
            "grid is one measured point per line: x_mm y_mm column row galvo_x galvo_y.",
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(machine_box)
        layout.addWidget(lens_box)
        layout.addWidget(experimental_box)
        layout.addStretch(1)  # let each group keep its natural height instead of sharing the slack
        layout.addWidget(buttons)

        self._load()

    # ------------------------------------------------------------------ reacting to edits

    def _cor_file_changed(self, path: str) -> None:
        """Take the scale from the file, because that is where it is right.

        A correction file records the scale it was calibrated at, so typing one in by hand is only for
        machines that arrived without a file.
        """
        path = path.strip()
        if not path:
            self._show_field()
            return
        from ezcad2 import read_scale

        try:
            self.scale.setValue(read_scale(path))
        except (OSError, ValueError, IndexError):
            # Not fatal: the file may still hold a usable table, and the board will say so soon enough.
            pass
        self._show_field()

    def _host_correction_toggled(self, on: bool) -> None:
        self.calibration_file.edit.setEnabled(on)

    def _show_field(self) -> None:
        size = 0xFFFF / self.scale.value() if self.scale.value() else 0
        self.field.setText(f"{size:.1f} × {size:.1f} mm")

    # ------------------------------------------------------------------ storage

    def _load(self) -> None:
        stored = settings()
        self.source.setCurrentIndex(
            max(0, self.source.findData(stored.value("galvo/source", "fiber", type=str)))
        )
        self.scale.setValue(stored.value("galvo/galvos_per_mm", DEFAULT_GALVOS_PER_MM, type=float))
        self.cor_file.setText(stored.value("galvo/cor_file", "", type=str))
        self.host_correction.setChecked(stored.value("galvo/host_correction", False, type=bool))
        self.calibration_file.setText(stored.value("galvo/calibration_file", "", type=str))
        self.calibration_file.edit.setEnabled(self.host_correction.isChecked())
        self.scale.valueChanged.connect(self._show_field)
        self._show_field()

    def _accept(self) -> None:
        """Check what was entered before storing it — a bad table should fail here, not mid-job."""
        if self.host_correction.isChecked():
            path = self.calibration_file.text()
            if not path:
                QMessageBox.warning(
                    self,
                    "Galvo settings",
                    "Software correction needs a measured grid. Pick a file, or switch the correction off.",
                )
                return
            from ezcad2 import read_calibration

            try:
                grid = read_calibration(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Galvo settings", f"That grid cannot be used: {error}")
                return
            columns, rows = grid.size
            QMessageBox.information(
                self, "Galvo settings", f"Grid read: {columns} × {rows} measured points."
            )

        stored = settings()
        stored.setValue("galvo/source", self.source.currentData())
        stored.setValue("galvo/galvos_per_mm", self.scale.value())
        stored.setValue("galvo/cor_file", self.cor_file.text())
        stored.setValue("galvo/host_correction", self.host_correction.isChecked())
        stored.setValue("galvo/calibration_file", self.calibration_file.text())
        self.accept()


def _group(title: str, form: QFormLayout, note: str = "") -> QGroupBox:
    """A titled group of fields, with an optional explanation under them.

    The note sits beside the form rather than in a row of it: a word-wrapped label inside a
    ``QFormLayout`` reports a height for one line and gets clipped at the bottom of the box.
    """
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.addLayout(form)
    if note:
        label = QLabel(note)
        label.setWordWrap(True)
        label.setStyleSheet("color: palette(mid);")
        layout.addWidget(label)
    return box
