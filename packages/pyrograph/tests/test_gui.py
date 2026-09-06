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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pyrograph.document import Document, ImageObject, Layer, Path, PathObject  # noqa: E402
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
