"""Noticing that an engraver was plugged in.

There is no event to subscribe to, so the device list is polled. That is cheap — reading it is a look at
the operating system's device table, no traffic on any port and nothing that could disturb a machine
already at work — and it is the same mechanism every other host program uses.

Two kinds of machine are looked for, because they announce themselves differently. A LaserPecker appears as
a serial port, and only ports whose USB product ID is one of the two it ships are reported: the bridge
chip's vendor alone is not evidence, since the same WCH chip sits in half the hobby electronics ever made,
and offering an Arduino as "your engraver" is worse than offering nothing. A galvo has no serial port at
all — its board is a raw USB device, found by the identity pair only LMC controllers carry.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

INTERVAL_MS = 2000
"""How often the port list is read. Plugging in a cable is a human-scale event; a second either way is
not worth a busier loop."""


class PortWatcher(QObject):
    """Watches what is plugged in and reports machines that were not there a moment ago."""

    appeared = Signal(str)
    """A LaserPecker showed up on this serial port. Everything present at the first scan counts as having
    shown up — a machine that was already plugged in when the program started is just as new to the
    program."""

    galvo_appeared = Signal()
    """A galvo controller showed up. It carries no port name, so there is nothing to pass on: the board is
    found by its USB identity when the connection is opened."""

    def __init__(self, ports=None, galvos=None, parent=None) -> None:
        super().__init__(parent)
        if ports is None:
            from laserpecker.transport import list_serial_ports

            def ports() -> list[str]:
                return list_serial_ports(strict=True)

        if galvos is None:
            from ezcad2 import boards_present as galvos

        self._ports = ports
        self._galvos = galvos
        self._seen: set[str] = set()
        self._galvo_seen = False
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self.scan)

    def start(self) -> None:
        self.scan()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def scan(self) -> None:
        """Read both device lists once and report what is new."""
        try:
            current = set(self._ports())
        except Exception:
            current = self._seen  # no pyserial, or a platform that will not enumerate; not fatal
        for port in sorted(current - self._seen):
            self.appeared.emit(port)
        self._seen = current

        try:
            galvo = self._galvos() > 0
        except Exception:
            galvo = self._galvo_seen
        if galvo and not self._galvo_seen:
            self.galvo_appeared.emit()
        self._galvo_seen = galvo
