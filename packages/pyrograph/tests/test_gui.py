"""The GUI, without a display.

Qt's ``offscreen`` platform runs the real widgets and the real worker thread, so these tests cover what a
screenshot would otherwise have to prove: the canvas builds items from the document, an edit lands on the
undo stack, and a job reaches the device — here the mock one — and comes back.
"""

import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pyrograph.document import Document, ImageObject, Layer, Path, PathObject, Point  # noqa: E402
from pyrograph.gui import arrange  # noqa: E402
from pyrograph.gui.device import DevicePanel  # noqa: E402
from pyrograph.gui.tools import SelectTool, ShapeTool  # noqa: E402
from pyrograph.gui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, png_bytes):
    document = Document(
        width_mm=100.0,
        height_mm=100.0,
        layers=[
            Layer(
                objects=[
                    PathObject(path=Path.rect(10, 10, 30, 20)),
                    ImageObject(data=png_bytes, width_mm=20.0, height_mm=10.0),
                ]
            )
        ],
    )
    window = MainWindow()
    window._set_document(document, None)
    yield window
    window.device.shutdown()


def _pump(app, until, timeout: float = 30.0) -> bool:
    """Run the event loop until ``until()`` holds, so the worker thread's replies get delivered."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


def test_canvas_draws_the_bed_and_every_object(window):
    # the work area rectangle, its grid, and one item per object
    assert len(window.canvas.scene().items()) == 4


def test_hidden_layer_is_not_drawn(window):
    window.document.layers[0].visible = False
    window.canvas.rebuild()
    assert len(window.canvas.scene().items()) == 2


def test_layer_edit_goes_through_the_undo_stack(window):
    window.layers.power.setValue(42)
    window.layers._apply_params()
    assert window.document.layers[0].params.power == 42
    assert window.dirty
    window.undo()
    assert window.document.layers[0].params.power == 60


def test_visibility_toggle_is_undoable(window):
    window.layers._list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert window.document.layers[0].visible is False
    window.undo()
    assert window.document.layers[0].visible is True
    assert window.layers._list.item(0).checkState() is Qt.CheckState.Checked


def test_engraving_runs_against_the_mock_device(app, window):
    panel = window.device
    panel.open_requested.emit("mock", "")
    assert _pump(app, lambda: panel._connected), "the mock device never connected"

    panel.engrave_requested.emit(window.document, "test")
    assert _pump(app, lambda: panel.worker._busy), "the job never started"
    assert _pump(app, lambda: not panel.worker._busy), "the job never finished"
    assert panel.engrave_button.isEnabled()

    panel.close_requested.emit()
    assert _pump(app, lambda: not panel._connected)


def _event(view, kind, point_mm, modifiers=Qt.KeyboardModifier.NoModifier):
    """A mouse event at a position given in document millimetres."""
    position = QPointF(view.mapFromScene(QPointF(*point_mm)))
    return QMouseEvent(
        kind,
        position,
        view.viewport().mapToGlobal(position.toPoint()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        modifiers,
    )


def _drag(view, start_mm, end_mm, modifiers=Qt.KeyboardModifier.NoModifier):
    view.mousePressEvent(_event(view, QEvent.Type.MouseButtonPress, start_mm, modifiers))
    view.mouseMoveEvent(_event(view, QEvent.Type.MouseMove, end_mm, modifiers))
    view.mouseReleaseEvent(_event(view, QEvent.Type.MouseButtonRelease, end_mm, modifiers))


@pytest.fixture
def drawing(app):
    """A window on an empty 100 × 100 mm document, sized so millimetres map to pixels sensibly."""
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window._set_document(Document(width_mm=100.0, height_mm=100.0), None)
    app.processEvents()
    yield window
    window.device.shutdown()


def test_the_rectangle_tool_adds_an_object(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (20, 20), (60, 40))

    objects = drawing.document.layers[0].objects
    assert len(objects) == 1
    assert objects[0].bounds().width == pytest.approx(40.0, abs=0.5)
    assert drawing.dirty
    drawing.undo()
    assert not drawing.document.layers[0].objects


def test_dragging_an_object_moves_it_and_undoes_as_one_step(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (20, 20), (40, 40))
    before = drawing.document.layers[0].objects[0].bounds()

    drawing.canvas.set_tool(SelectTool())
    _drag(drawing.canvas, (30, 30), (50, 30))
    after = drawing.document.layers[0].objects[0].bounds()
    assert after.x == pytest.approx(before.x + 20.0, abs=0.5)
    assert after.y == pytest.approx(before.y, abs=0.5)

    drawing.undo()
    assert drawing.document.layers[0].objects[0].bounds().x == pytest.approx(before.x)


def test_a_handle_scales_the_selection_and_its_stroke(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (20, 20), (40, 40))
    obj = drawing.document.layers[0].objects[0]
    obj.stroke_width_mm = 0.4
    drawing.canvas.set_tool(SelectTool())
    drawing.canvas.set_selection([obj.id])

    box = drawing.canvas.selection_bounds()
    _drag(drawing.canvas, (box.right, box.bottom), (box.right + 20, box.bottom + 20))
    assert obj.bounds().width == pytest.approx(40.0, abs=1.0)
    assert obj.stroke_width_mm == pytest.approx(0.8, abs=0.05)


def test_dragging_the_background_selects_what_it_covers(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (10, 10), (30, 30))
    _drag(drawing.canvas, (60, 60), (80, 80))

    drawing.canvas.set_tool(SelectTool())
    _drag(drawing.canvas, (5, 5), (40, 40))
    assert len(drawing.canvas.selection) == 1
    _drag(drawing.canvas, (2, 2), (95, 95))
    assert len(drawing.canvas.selection) == 2


def test_copy_and_paste_add_an_offset_duplicate(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (20, 20), (40, 40))
    original = drawing.document.layers[0].objects[0]
    drawing.canvas.set_selection([original.id])

    drawing.copy()
    drawing.paste()
    objects = drawing.document.layers[0].objects
    assert len(objects) == 2
    assert objects[1].id != original.id
    assert objects[1].bounds().x == pytest.approx(original.bounds().x + 2.0)

    drawing.undo()
    assert len(drawing.document.layers[0].objects) == 1


def test_delete_removes_the_selection_in_one_step(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (10, 10), (30, 30))
    _drag(drawing.canvas, (60, 60), (80, 80))
    drawing.canvas.select_all()

    drawing.delete()
    assert not drawing.document.layers[0].objects
    drawing.undo()
    assert len(drawing.document.layers[0].objects) == 2


def test_align_moves_everything_onto_one_edge(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (10, 10), (30, 30))
    _drag(drawing.canvas, (60, 60), (80, 80))
    drawing.canvas.select_all()

    drawing._align("left")
    lefts = {round(o.bounds().x, 3) for o in drawing.document.layers[0].objects}
    assert len(lefts) == 1


def test_an_array_copies_into_a_grid(drawing):
    drawing.canvas.set_tool(ShapeTool("rect", "Rectangle"))
    _drag(drawing.canvas, (10, 10), (20, 20))
    drawing.canvas.select_all()

    drawing.apply(arrange.array(drawing.document, drawing.canvas.selection, 3, 2, 15.0, 15.0))
    assert len(drawing.document.layers[0].objects) == 6
    drawing.undo()
    assert len(drawing.document.layers[0].objects) == 1


def test_snapping_pulls_a_drawn_corner_onto_the_grid(drawing):
    drawing.canvas.grid_mm = 10.0
    drawing.canvas.snap_to_grid = True
    assert drawing.canvas.snap_point(Point(20.4, 39.6)) == Point(20.0, 40.0)

    drawing.canvas.snap_to_grid = False
    assert drawing.canvas.snap_point(Point(20.4, 39.6)) == Point(20.4, 39.6)


def test_the_place_dialogs_hand_back_a_positioned_object(app, monkeypatch):
    """The dialogs are accepted without a screen, so the wiring from click to object is covered."""
    from PySide6.QtWidgets import QDialog, QLineEdit

    from pyrograph.gui import dialogs

    # Patch our own dialog class, not QDialog: a C++ slot does not take a Python override reliably.
    monkeypatch.setattr(dialogs._Dialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QLineEdit, "text", lambda self: "PYRO-1")

    for kind in ("qr", "barcode", "text"):
        obj = dialogs.ASK[kind](None, Point(12.0, 34.0))
        assert obj is not None, kind
        assert obj.fill, kind
        assert obj.bounds().x == pytest.approx(12.0, abs=1.0), kind


def test_framing_runs_until_it_is_stopped(app, window):
    panel = window.device
    panel.open_requested.emit("mock", "")
    assert _pump(app, lambda: panel._connected)
    assert not panel.stop_button.isEnabled(), "nothing to stop yet"

    panel.frame()
    assert _pump(app, lambda: panel._framing), "framing never started"
    assert panel.stop_button.isEnabled()
    assert not panel.frame_button.isEnabled(), "the machine is already tracing"
    assert not panel.engrave_button.isEnabled(), "the head is moving"
    assert panel.state_text.text() == "framing"

    panel.stop_frame()
    assert _pump(app, lambda: not panel._framing), "framing never stopped"
    assert panel.frame_button.isEnabled()
    assert not panel.stop_button.isEnabled()


def test_disconnecting_stops_the_machine_first(app, window):
    """Closing the port leaves the device tracing with nobody left to tell it otherwise."""
    panel = window.device
    panel.open_requested.emit("mock", "")
    assert _pump(app, lambda: panel._connected)
    panel.frame()
    assert _pump(app, lambda: panel._framing)

    stopped = []
    device = panel.worker.device
    device.stop_frame = lambda: stopped.append(True)

    panel.close_requested.emit()
    assert _pump(app, lambda: not panel._connected)
    assert stopped == [True]
    assert not panel._framing


def test_a_plugged_in_engraver_is_offered(app):
    """Selected, not connected: opening the port stays the user's move."""
    panel = DevicePanel()
    ports: list[str] = []
    panel.watcher._ports = lambda: list(ports)
    assert panel.mode.currentData() == "mock"

    ports.append("/dev/ttyUSB0")
    panel.watcher.scan()
    assert panel.mode.currentData() == "usb"
    assert panel.address.text() == "/dev/ttyUSB0"
    assert not panel._connected

    panel.state_text.setText("untouched")
    panel.watcher.scan()
    assert panel.state_text.text() == "untouched", "the same port must not report itself twice"

    ports.clear()
    panel.watcher.scan()
    ports.append("/dev/ttyACM0")
    panel.watcher.scan()
    assert panel.address.text() == "/dev/ttyACM0", "unplugging and replugging reports again"
    panel.shutdown()


def test_a_connection_chosen_by_hand_is_left_alone(app):
    panel = DevicePanel()
    ports: list[str] = []
    panel.watcher._ports = lambda: list(ports)

    panel.mode.setCurrentIndex(panel.mode.findData("ble"))
    panel.address.setText("LaserPecker-1234")
    panel._chosen_by_hand()

    ports.append("/dev/ttyUSB0")
    panel.watcher.scan()
    assert panel.mode.currentData() == "ble"
    assert panel.address.text() == "LaserPecker-1234"
    panel.shutdown()
