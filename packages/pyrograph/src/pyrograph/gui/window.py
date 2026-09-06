"""The main window: canvas in the middle, layers on the left, the device on the right.

The window owns the document and the undo stack; the panels only ask it to do things. That keeps a single
place where a change is applied, redrawn and marked unsaved — the alternative, panels writing to the
document on their own, is how a canvas and a layer list start disagreeing about what is in the file.
"""

from __future__ import annotations

from pathlib import Path as FilePath

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMessageBox

from ..document import Document, SvgImportError, UndoStack, import_svg, load_pyg, save_pyg
from .canvas import CanvasView
from .device import DevicePanel
from .layers import LayerPanel


class MainWindow(QMainWindow):
    """One window, one document."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.canvas = CanvasView()
        self.layers = LayerPanel()
        self.device = DevicePanel()
        self.setCentralWidget(self.canvas)
        self._dock("Layers", self.layers, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._dock("Device", self.device, Qt.DockWidgetArea.RightDockWidgetArea)
        self.layers.changed.connect(self._changed)

        self._build_menus()
        self.resize(1200, 800)
        self._set_document(Document(), None)
        if path:
            self._load(path)

    def _dock(self, title: str, widget, area) -> None:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(area, dock)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self._action(file_menu, "&Open…", QKeySequence.StandardKey.Open, self.open_file)
        self._action(file_menu, "&Import SVG…", None, self.import_drawing)
        file_menu.addSeparator()
        self._action(file_menu, "&Save", QKeySequence.StandardKey.Save, self.save)
        self._action(file_menu, "Save &As…", QKeySequence.StandardKey.SaveAs, self.save_as)
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", QKeySequence.StandardKey.Quit, self.close)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = self._action(edit_menu, "&Undo", QKeySequence.StandardKey.Undo, self.undo)
        self.redo_action = self._action(edit_menu, "&Redo", QKeySequence.StandardKey.Redo, self.redo)

        view_menu = self.menuBar().addMenu("&View")
        self._action(view_menu, "&Fit to window", "Ctrl+0", self.canvas.fit)

    def _action(self, menu, text: str, shortcut, slot) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------------ document

    def _set_document(self, document: Document, path: str | None) -> None:
        self.document = document
        self.undo_stack = UndoStack(document)
        self.path = path
        self.dirty = False
        self.canvas.set_document(document)
        self.layers.set_document(document, self.undo_stack)
        self.device.set_document(document)
        self._refresh()

    def _changed(self) -> None:
        """A panel edited the document through the undo stack."""
        self.dirty = True
        self.canvas.rebuild()
        self._refresh()

    def _refresh(self) -> None:
        self.undo_action.setEnabled(self.undo_stack.can_undo)
        self.redo_action.setEnabled(self.undo_stack.can_redo)
        name = FilePath(self.path).name if self.path else "untitled"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} — pyrograph")

    def undo(self) -> None:
        self.undo_stack.undo()
        self._after_history()

    def redo(self) -> None:
        self.undo_stack.redo()
        self._after_history()

    def _after_history(self) -> None:
        self.dirty = True
        self.layers.reload()
        self.canvas.rebuild()
        self._refresh()

    # ------------------------------------------------------------------ files

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", "pyrograph documents (*.pyg)")
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        try:
            document = load_pyg(path)
        except Exception as error:
            QMessageBox.critical(self, "Open", f"{path}:\n{error}")
            return
        self._set_document(document, path)

    def import_drawing(self) -> None:
        """Replace the document with an imported SVG. Merging into the open one comes with the editor."""
        path, _ = QFileDialog.getOpenFileName(self, "Import SVG", "", "SVG drawings (*.svg)")
        if not path:
            return
        try:
            result = import_svg(path)
        except (SvgImportError, OSError) as error:
            QMessageBox.critical(self, "Import SVG", f"{path}:\n{error}")
            return
        self._set_document(result.document, None)
        self.dirty = True
        self._refresh()
        if result.skipped:
            QMessageBox.information(
                self, "Import SVG", "Not understood, left out:\n" + "\n".join(sorted(set(result.skipped)))
            )

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        try:
            save_pyg(self.document, self.path)
        except OSError as error:
            QMessageBox.critical(self, "Save", f"{self.path}:\n{error}")
            return False
        self.dirty = False
        self._refresh()
        return True

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save as", "", "pyrograph documents (*.pyg)")
        if not path:
            return False
        self.path = path if path.endswith(".pyg") else path + ".pyg"
        return self.save()

    def closeEvent(self, event) -> None:
        if self.dirty:
            answer = QMessageBox.question(
                self,
                "pyrograph",
                "The document has unsaved changes.",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer is QMessageBox.StandardButton.Cancel or (
                answer is QMessageBox.StandardButton.Save and not self.save()
            ):
                event.ignore()
                return
        self.device.shutdown()
        event.accept()
