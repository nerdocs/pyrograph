"""Talking to the laser without freezing the window.

Every call into the driver blocks — connecting waits for a handshake, an upload runs for minutes. All of
them therefore live on :class:`DeviceWorker`, which sits on its own thread; the panel only sends signals to
it and displays what comes back.

The worker stays on one thread on purpose: a serial port or a BLE session tolerates exactly one writer.
While a job runs, the worker's wait loop pumps its own event queue, so *pause* and *abort* still reach the
device — they are handled between two status polls, on the same thread, instead of racing the transport
from the GUI thread.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..devices import DeviceState, DeviceStatus, LaserPeckerDevice
from ..document import Document
from ..job import build_raster_job

POLL_MS = 1000
"""How often an idle device is asked how it is doing."""

_COLOUR = {
    DeviceState.OFFLINE: "#808080",
    DeviceState.IDLE: "#2e9e4f",
    DeviceState.RUNNING: "#1c7ed6",
    DeviceState.PAUSED: "#d9a406",
    DeviceState.ERROR: "#d63939",
}


class DeviceWorker(QObject):
    """The driver, one thread away from the GUI. Every slot here blocks and that is fine."""

    opened = Signal(str)
    closed = Signal()
    status = Signal(object)
    progress = Signal(str, int)
    failed = Signal(str)
    busy = Signal(bool)
    framing = Signal(bool)
    """The device started or stopped tracing the outline."""

    def __init__(self) -> None:
        super().__init__()
        self.device: LaserPeckerDevice | None = None
        self._timer: QTimer | None = None
        self._busy = False
        self._stop = False
        self._framing = False
        self._traced = False
        """Whether the device has reported itself running since framing started — see :meth:`_poll`."""

    @Slot()
    def start(self) -> None:
        """Create the poll timer on the worker's own thread — a QTimer belongs to the thread it runs in."""
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    @Slot(str, str)
    def open_device(self, mode: str, address: str) -> None:
        try:
            self.device = self._connect(mode, address)
        except Exception as error:  # a driver mishap must not take the window down with it
            self.failed.emit(str(error))
            return
        self.opened.emit(self.device.profile.name)
        self._poll()
        self._timer.start()

    @staticmethod
    def _connect(mode: str, address: str) -> LaserPeckerDevice:
        if mode == "mock":
            return LaserPeckerDevice.mock()
        from laserpecker.device import LaserPecker
        from laserpecker.transport import BleTransport, SerialTransport

        if mode == "ble":
            return LaserPeckerDevice(LaserPecker(BleTransport(address)))
        return LaserPeckerDevice(LaserPecker(SerialTransport(address or None)))

    @Slot()
    def close_device(self) -> None:
        self._timer.stop()
        if self.device is not None:
            # Closing the port does not stop the machine: it would keep tracing the outline with nobody
            # left to tell it otherwise.
            self.stop_frame()
            self.device.close()
            self.device = None
        self.closed.emit()

    @Slot(object, int)
    def frame(self, bounds, power: int) -> None:
        if self.device is None:
            return
        self._framing, self._traced = True, False
        self.framing.emit(True)
        try:
            self.device.frame(bounds, power)
        except Exception as error:
            self._set_framing(False)
            self.failed.emit(str(error))

    @Slot()
    def stop_frame(self) -> None:
        if self.device is None:
            return
        try:
            self.device.stop_frame()
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self._set_framing(False)

    def _set_framing(self, framing: bool) -> None:
        if self._framing != framing:
            self._framing = framing
            self.framing.emit(framing)

    @Slot(object, str)
    def engrave(self, document: Document, name: str) -> None:
        """Rasterise every visible layer and burn it, one layer after another.

        ``document`` is the caller's private copy, so building the rasters here — which takes seconds on a
        large image — does not block the window either.
        """
        if self.device is None or self._busy:
            return
        self._busy, self._stop = True, False
        self.busy.emit(True)
        try:
            for index, layer in enumerate(document.layers):
                if not layer.visible or self._stop:
                    continue
                layer.params.dpi = self.device.profile.nearest_dpi(layer.params.dpi)
                self.progress.emit(f"rasterising {layer.name}", 0)
                job = build_raster_job(document, index)
                if job is None:
                    continue
                self.device.run(
                    job,
                    name=f"{name}-{index}",
                    progress=lambda done, total: self.progress.emit("uploading", done * 100 // total),
                )
                self._wait(layer.name)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self._busy = False
            self.busy.emit(False)
            self.progress.emit("", 0)

    def _wait(self, label: str) -> None:
        """Poll until the device stops running, letting queued pause/abort calls through in between."""
        while not self._stop:
            state = self.device.status()
            self.status.emit(state)
            if state.state is not DeviceState.RUNNING:
                return
            self.progress.emit(f"engraving {label}", state.progress)
            QCoreApplication.processEvents()
            QThread.msleep(200)

    @Slot(bool)
    def pause(self, paused: bool) -> None:
        if self.device is not None:
            self.device.pause() if paused else self.device.resume()

    @Slot()
    def abort(self) -> None:
        self._stop = True
        if self.device is not None:
            self.device.abort()

    def _poll(self) -> None:
        if self.device is None or self._busy:
            return  # while a job runs, the wait loop reports the state
        status = self.device.status()
        self.status.emit(status)
        if not self._framing:
            return
        # Framing ends when the device says it stopped — but only once it has said it started. The first
        # poll after the command can still arrive before the machine has begun to move.
        if status.state is DeviceState.RUNNING:
            self._traced = True
        elif self._traced:
            self._set_framing(False)


class DevicePanel(QWidget):
    """Connect, align, engrave. Holds the worker thread and knows nothing about the protocol."""

    open_requested = Signal(str, str)
    close_requested = Signal()
    frame_requested = Signal(object, int)
    stop_frame_requested = Signal()
    engrave_requested = Signal(object, str)
    pause_requested = Signal(bool)
    abort_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._document: Document | None = None
        self._connected = False
        self._framing = False
        self._busy = False

        self.mode = QComboBox()
        for label, value in (("Mock (no hardware)", "mock"), ("USB", "usb"), ("Bluetooth", "ble")):
            self.mode.addItem(label, value)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.address = QLineEdit(placeholderText="auto")
        self.address.setEnabled(False)
        self.connect_button = QPushButton("Connect", clicked=self._toggle_connection)

        self.state_dot = QLabel("●")
        self.state_text = QLabel("not connected")

        self.frame_button = QPushButton("Frame", clicked=self.frame)
        self.frame_button.setToolTip("Trace the outline at low power so the workpiece can be lined up")
        self.stop_button = QPushButton("Stop", clicked=self.stop_frame)
        self.stop_button.setToolTip("Stop tracing")
        self.engrave_button = QPushButton("Engrave", clicked=self.engrave)
        self.pause_button = QPushButton("Pause", checkable=True)
        self.pause_button.toggled.connect(self.pause_requested)
        self.abort_button = QPushButton("Abort", clicked=self.abort_requested)
        self.progress = QProgressBar(textVisible=True)
        self.progress.setFormat("%p%")
        self.progress.hide()

        connection = QFormLayout()
        connection.addRow("Connection", self.mode)
        connection.addRow("Address", self.address)
        connection.addRow(self.connect_button)
        connection_box = QGroupBox("Connection")
        connection_box.setLayout(connection)

        state = QHBoxLayout()
        state.addWidget(self.state_dot)
        state.addWidget(self.state_text, 1)

        job = QVBoxLayout()
        job.addLayout(state)
        # Each action next to the control that ends it: framing above, engraving below.
        framing = QHBoxLayout()
        framing.addWidget(self.frame_button)
        framing.addWidget(self.stop_button)
        job.addLayout(framing)
        job.addWidget(self.engrave_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.abort_button)
        job.addLayout(buttons)
        job.addWidget(self.progress)
        job_box = QGroupBox("Job")
        job_box.setLayout(job)

        layout = QVBoxLayout(self)
        layout.addWidget(connection_box)
        layout.addWidget(job_box)
        layout.addStretch(1)

        self._thread = QThread(self)
        self.worker = DeviceWorker()
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.start)
        self.open_requested.connect(self.worker.open_device)
        self.close_requested.connect(self.worker.close_device)
        self.frame_requested.connect(self.worker.frame)
        self.stop_frame_requested.connect(self.worker.stop_frame)
        self.engrave_requested.connect(self.worker.engrave)
        self.pause_requested.connect(self.worker.pause)
        self.abort_requested.connect(self.worker.abort)
        self.worker.opened.connect(self._opened)
        self.worker.closed.connect(self._closed)
        self.worker.status.connect(self._show_status)
        self.worker.progress.connect(self._show_progress)
        self.worker.failed.connect(self._show_error)
        self.worker.busy.connect(self._set_busy)
        self.worker.framing.connect(self._set_framing)
        self._thread.start()
        self._update_buttons()

    def set_document(self, document: Document) -> None:
        self._document = document

    def shutdown(self) -> None:
        """Stop the worker thread. The window calls this before it closes."""
        if self._connected:
            self.close_requested.emit()
        self._thread.quit()
        self._thread.wait(5000)

    # ------------------------------------------------------------------ user actions

    def _mode_changed(self) -> None:
        mock = self.mode.currentData() == "mock"
        self.address.setEnabled(not mock)
        self.address.setPlaceholderText("auto" if self.mode.currentData() == "usb" else "name or address")

    def _toggle_connection(self) -> None:
        if self._connected:
            self.close_requested.emit()
        else:
            self.connect_button.setEnabled(False)
            self.state_text.setText("connecting…")
            self.open_requested.emit(self.mode.currentData(), self.address.text().strip())

    def frame(self) -> None:
        """Trace the document's bounding box so the workpiece can be aligned."""
        bounds = self._document.bounds() if self._document else None
        if bounds is None:
            QMessageBox.information(self, "Frame", "Nothing to frame — the document is empty.")
            return
        self.frame_requested.emit(bounds, 1)

    def stop_frame(self) -> None:
        """Stop tracing. The device keeps going otherwise — the outline is meant to stay visible."""
        self.stop_frame_requested.emit()

    def engrave(self) -> None:
        """Send every visible layer to the device."""
        if self._document is None or self._document.bounds() is None:
            QMessageBox.information(self, "Engrave", "Nothing to engrave — the document is empty.")
            return
        # The worker gets its own copy: it rasterises on its thread while the document stays editable.
        self.engrave_requested.emit(copy.deepcopy(self._document), "pyrograph")

    # ------------------------------------------------------------------ worker replies

    def _opened(self, name: str) -> None:
        self._connected = True
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self.mode.setEnabled(False)
        self.address.setEnabled(False)
        self.state_text.setText(f"{name}: connected")
        self._update_buttons()

    def _closed(self) -> None:
        self._connected = False
        self._framing = False
        self.connect_button.setText("Connect")
        self.connect_button.setEnabled(True)
        self.mode.setEnabled(True)
        self._mode_changed()
        self._show_status(DeviceStatus(DeviceState.OFFLINE, message="not connected"))
        self._update_buttons()

    def _show_status(self, status: DeviceStatus) -> None:
        self.state_dot.setStyleSheet(f"color: {_COLOUR[status.state]}")
        if self._framing and status.state is DeviceState.RUNNING:
            return  # the poll would overwrite "framing" with the device's own word for it
        self.state_text.setText(f"{status.state.value} {status.message}".strip())

    def _show_progress(self, label: str, percent: int) -> None:
        self.progress.setVisible(bool(label))
        self.progress.setFormat(f"{label} %p%")
        self.progress.setValue(percent)

    def _show_error(self, message: str) -> None:
        self.connect_button.setEnabled(True)
        if not self._connected:
            self.state_text.setText("not connected")
        QMessageBox.warning(self, "Device", message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_buttons()
        if not busy:
            self.pause_button.setChecked(False)

    def _set_framing(self, framing: bool) -> None:
        self._framing = framing
        self._update_buttons()
        if framing:
            # Name the state after what was started. The device only knows it is "running".
            self.state_dot.setStyleSheet(f"color: {_COLOUR[DeviceState.RUNNING]}")
            self.state_text.setText("framing")

    def _update_buttons(self) -> None:
        idle = self._connected and not self._busy and not self._framing
        self.frame_button.setEnabled(idle)
        self.engrave_button.setEnabled(idle)
        self.stop_button.setEnabled(self._connected and self._framing)
        self.pause_button.setEnabled(self._connected and self._busy)
        self.abort_button.setEnabled(self._connected and self._busy)
        # Disconnecting stays available while framing: it stops the machine on the way out, and a moving
        # head is the moment you least want the button greyed.
        self.connect_button.setEnabled(not self._busy)
