"""Noticing that an engraver was plugged in.

pyserial has no event to subscribe to, so the port list is polled. That is cheap — reading it is a look at
the operating system's device table, no traffic on any port and nothing that could disturb a machine
already at work — and it is the same mechanism every other host program uses.

Only ports whose USB product ID is one of the two LaserPecker ships are reported. The bridge chip's vendor
alone is not evidence: the same WCH chip sits in half the hobby electronics ever made, and offering an
Arduino as "your engraver" is worse than offering nothing.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

INTERVAL_MS = 2000
"""How often the port list is read. Plugging in a cable is a human-scale event; a second either way is
not worth a busier loop."""


class PortWatcher(QObject):
    """Watches the serial ports and reports engravers that were not there a moment ago."""

    appeared = Signal(str)
    """A port showed up. Everything present at the first scan counts as having shown up — a machine that
    was already plugged in when the program started is just as new to the program."""

    def __init__(self, ports=None, parent=None) -> None:
        super().__init__(parent)
        if ports is None:
            from laserpecker.transport import list_serial_ports

            def ports() -> list[str]:
                return list_serial_ports(strict=True)

        self._ports = ports
        self._seen: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self.scan)

    def start(self) -> None:
        self.scan()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def scan(self) -> None:
        """Read the port list once and report what is new."""
        try:
            current = set(self._ports())
        except Exception:
            return  # a machine without pyserial, or a platform that will not enumerate; not fatal
        for port in sorted(current - self._seen):
            self.appeared.emit(port)
        self._seen = current
