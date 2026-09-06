"""The main window: tools on the left, canvas in the middle, layers and the device around it.

The window owns the document, the undo stack and the clipboard; the panels and the canvas only ask it to
do things. That keeps a single place where a change is applied, redrawn and marked unsaved — the
alternative, panels writing to the document on their own, is how a canvas and a layer list start
disagreeing about what is in the file.

Everything that changes the document arrives as a :class:`~pyrograph.document.Command` and goes through
:meth:`MainWindow.apply`. There is no second path.
"""

from __future__ import annotations

from pathlib import Path as FilePath

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from ..document import (
    AddObject,
    CommandGroup,
    Document,
    RemoveObject,
    SvgImportError,
    Transform,
    UndoStack,
    import_svg,
    load_pyg,
    save_pyg,
)
from . import arrange, dialogs, icons
from .canvas import CanvasView
from .device import DevicePanel
from .layers import LayerPanel
from .rulers import CanvasArea
from .tools import build_tools

PASTE_OFFSET_MM = 2.0
"""How far a pasted copy sits from its original, so it is visible instead of hiding underneath."""

GRID_STEPS = (1.0, 2.0, 5.0, 10.0, 20.0)


class MainWindow(QMainWindow):
    """One window, one document."""

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.canvas = CanvasView()
        self.layers = LayerPanel()
        self.device = DevicePanel()
        self.setCentralWidget(CanvasArea(self.canvas))
        self._dock("Layers", self.layers, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._dock("Device", self.device, Qt.DockWidgetArea.RightDockWidgetArea)

        self._clipboard: list = []
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_status_bar()

        self.layers.changed.connect(self._changed)
        self.layers.current_changed.connect(self._layer_selected)
        self.canvas.edit_requested.connect(self.apply)
        self.canvas.selection_changed.connect(self._selection_changed)
        self.canvas.cursor_moved.connect(self._show_position)
        self.canvas.place_requested.connect(self._place)

        self.resize(1300, 850)
        self._set_document(Document(), None)
        if path:
            self._load(path)

    def _dock(self, title: str, widget, area) -> None:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(area, dock)

    # ------------------------------------------------------------------ actions, menus, toolbars

    def _action(self, text: str, slot, shortcut=None, icon=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        if icon is not None:
            action.setIcon(icon)
        action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        keys = QKeySequence.StandardKey
        self.act_open = self._action("&Open…", self.open_file, keys.Open, icons.themed("document-open"))
        self.act_import = self._action("&Import SVG…", self.import_drawing)
        self.act_save = self._action("&Save", self.save, keys.Save, icons.themed("document-save"))
        self.act_save_as = self._action("Save &As…", self.save_as, keys.SaveAs)
        self.act_quit = self._action("&Quit", self.close, keys.Quit)

        self.act_undo = self._action("&Undo", self.undo, keys.Undo, icons.themed("edit-undo"))
        self.act_redo = self._action("&Redo", self.redo, keys.Redo, icons.themed("edit-redo"))
        self.act_cut = self._action("Cu&t", self.cut, keys.Cut, icons.themed("edit-cut"))
        self.act_copy = self._action("&Copy", self.copy, keys.Copy, icons.themed("edit-copy"))
        self.act_paste = self._action("&Paste", self.paste, keys.Paste, icons.themed("edit-paste"))
        self.act_delete = self._action("&Delete", self.delete, keys.Delete, icons.themed("edit-delete"))
        self.act_select_all = self._action("Select &All", self.canvas.select_all, keys.SelectAll)

        self.act_frame = self._action("&Frame", self.device.frame)
        self.act_engrave = self._action("&Engrave", self.device.engrave)
        self.act_fit = self._action("&Fit to window", self.canvas.fit, "Ctrl+0")

        self._selection_actions = [
            self.act_cut,
            self.act_copy,
            self.act_delete,
        ]

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.act_open, self.act_import])
        file_menu.addSeparator()
        file_menu.addActions([self.act_save, self.act_save_as])
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([self.act_undo, self.act_redo])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_cut, self.act_copy, self.act_paste, self.act_delete])
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_select_all)

        modify = self.menuBar().addMenu("&Modify")
        align = modify.addMenu("&Align")
        for label, edge in (
            ("&Left", "left"),
            ("&Centre", "centre"),
            ("&Right", "right"),
            ("&Top", "top"),
            ("&Middle", "middle"),
            ("&Bottom", "bottom"),
        ):
            align.addAction(self._action(label, lambda _=False, e=edge: self._align(e)))
        spread = modify.addMenu("&Distribute")
        spread.addAction(self._action("&Horizontally", lambda: self._distribute(True)))
        spread.addAction(self._action("&Vertically", lambda: self._distribute(False)))
        modify.addSeparator()
        modify.addAction(self._action("Mirror &horizontally", lambda: self._mirror(True)))
        modify.addAction(self._action("Mirror &vertically", lambda: self._mirror(False)))
        modify.addAction(self._action("Rotate 90° &clockwise", lambda: self._rotate(90)))
        modify.addAction(self._action("Rotate 90° &anticlockwise", lambda: self._rotate(-90)))
        modify.addSeparator()
        modify.addAction(self._action("Duplicate as a&rray…", self._array))

        view = self.menuBar().addMenu("&View")
        view.addAction(self.act_fit)
        grid = view.addMenu("&Grid")
        group = QActionGroup(self)
        for step in GRID_STEPS:
            action = self._action(f"{step:g} mm", lambda _=False, s=step: self._set_grid(s))
            action.setCheckable(True)
            action.setChecked(step == self.canvas.grid_mm)
            group.addAction(action)
            grid.addAction(action)
        view.addSeparator()
        self.act_snap_grid = self._toggle(view, "Snap to &grid", self.canvas.snap_to_grid, self._set_snap)
        self.act_snap_objects = self._toggle(
            view, "Snap to &objects", self.canvas.snap_to_objects, self._set_snap
        )

    def _toggle(self, menu, text: str, checked: bool, slot) -> QAction:
        action = QAction(text, self, checkable=True, checked=checked)
        action.toggled.connect(slot)
        menu.addAction(action)
        return action

    def _build_toolbars(self) -> None:
        bar = QToolBar("Main", self)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.addActions([self.act_open, self.act_save])
        bar.addSeparator()
        bar.addActions([self.act_cut, self.act_copy, self.act_paste, self.act_delete])
        bar.addSeparator()
        bar.addActions([self.act_undo, self.act_redo])
        bar.addSeparator()
        bar.addActions([self.act_frame, self.act_engrave])
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)

        palette = QToolBar("Tools", self)
        palette.setOrientation(Qt.Orientation.Vertical)
        colour = self.palette().text().color()
        group = QActionGroup(self)
        for tool in build_tools():
            action = QAction(icons.tool_icon(tool.name, colour), tool.label, self, checkable=True)
            action.setToolTip(tool.label)
            action.triggered.connect(lambda _=False, t=tool: self.canvas.set_tool(t))
            action.setChecked(tool.name == self.canvas.tool.name)
            group.addAction(action)
            palette.addAction(action)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, palette)

    def _build_status_bar(self) -> None:
        self._position = QLabel("")
        self._size = QLabel("")
        self.statusBar().addPermanentWidget(self._position)
        self.statusBar().addPermanentWidget(self._size)

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

    def apply(self, command) -> None:
        """Execute a change and let everything catch up. The only way the document is ever modified."""
        if command is None:
            return
        self.undo_stack.execute(command)
        self._changed()

    def _changed(self) -> None:
        self.dirty = True
        self.canvas.rebuild()
        self.layers.reload()
        self._refresh()

    def _refresh(self) -> None:
        self.act_undo.setEnabled(self.undo_stack.can_undo)
        self.act_redo.setEnabled(self.undo_stack.can_redo)
        self.act_paste.setEnabled(bool(self._clipboard))
        self._selection_changed()
        name = FilePath(self.path).name if self.path else "untitled"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} — pyrograph")

    def undo(self) -> None:
        self.undo_stack.undo()
        self._changed()

    def redo(self) -> None:
        self.undo_stack.redo()
        self._changed()

    # ------------------------------------------------------------------ selection and clipboard

    def _selection_changed(self) -> None:
        selected = bool(self.canvas.selection)
        for action in self._selection_actions:
            action.setEnabled(selected)
        bounds = self.canvas.selection_bounds()
        if bounds is None:
            self._size.setText("")
        else:
            self._size.setText(
                f"{len(self.canvas.selection)} selected  "
                f"{bounds.width:.1f} × {bounds.height:.1f} mm"
            )

    def _show_position(self, point) -> None:
        self._position.setText("" if point is None else f"{point.x:7.1f} {point.y:7.1f} mm")

    def _layer_selected(self, index: int) -> None:
        self.canvas.target_layer = max(0, index)

    def copy(self) -> None:
        self._clipboard = [self.document.object(i).clone() for i in self.canvas.selection]
        self.act_paste.setEnabled(bool(self._clipboard))

    def cut(self) -> None:
        self.copy()
        self.delete()

    def paste(self) -> None:
        if not self._clipboard:
            return
        clones = []
        for source in self._clipboard:
            clone = source.clone()
            clone.transform = clone.transform.then(
                Transform.translate(PASTE_OFFSET_MM, PASTE_OFFSET_MM)
            )
            clones.append(clone)
        self.apply(CommandGroup([AddObject(self.canvas.target_layer, c) for c in clones]))
        self.canvas.set_selection([c.id for c in clones])
        # Pasting again moves on: otherwise every copy lands on the last one.
        self._clipboard = clones

    def delete(self) -> None:
        if self.canvas.selection:
            self.apply(CommandGroup([RemoveObject(i) for i in self.canvas.selection]))

    def _place(self, kind: str, point) -> None:
        obj = dialogs.ASK[kind](self, point)
        if obj is not None:
            self.apply(AddObject(self.canvas.target_layer, obj))
            self.canvas.set_selection([obj.id])

    # ------------------------------------------------------------------ modify

    def _align(self, edge: str) -> None:
        self.apply(arrange.align(self.document, self.canvas.selection, edge))

    def _distribute(self, horizontal: bool) -> None:
        self.apply(arrange.distribute(self.document, self.canvas.selection, horizontal))

    def _mirror(self, horizontal: bool) -> None:
        self.apply(arrange.mirror(self.document, self.canvas.selection, horizontal))

    def _rotate(self, degrees: float) -> None:
        self.apply(arrange.rotate(self.document, self.canvas.selection, degrees))

    def _array(self) -> None:
        bounds = self.canvas.selection_bounds()
        if bounds is None:
            return
        answer = dialogs.ask_array(self, round(max(bounds.width, bounds.height) + 5, 1))
        if answer is not None:
            self.apply(arrange.array(self.document, self.canvas.selection, *answer))

    def _set_grid(self, step: float) -> None:
        self.canvas.grid_mm = step
        self.canvas.rebuild()

    def _set_snap(self) -> None:
        self.canvas.snap_to_grid = self.act_snap_grid.isChecked()
        self.canvas.snap_to_objects = self.act_snap_objects.isChecked()

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
        """Replace the document with an imported SVG. Merging into the open one comes later."""
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
