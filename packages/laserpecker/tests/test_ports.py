"""Which serial ports count as a LaserPecker."""

from dataclasses import dataclass

import pytest

from laserpecker import transport


@dataclass
class _Port:
    device: str
    vid: int | None
    pid: int | None


@pytest.fixture
def ports(monkeypatch):
    """Replace the system's port list with whatever a test claims is plugged in."""

    def install(*entries: _Port):
        monkeypatch.setattr(
            "serial.tools.list_ports.comports", lambda: list(entries), raising=False
        )

    return install


CH340 = _Port("/dev/ttyUSB0", 0x1A86, 0x7523)
CH9102 = _Port("/dev/ttyACM0", 0x1A86, 0x55D4)
OTHER_WCH = _Port("/dev/ttyUSB1", 0x1A86, 0x1234)
FTDI = _Port("/dev/ttyUSB2", 0x0403, 0x6001)


def test_a_known_bridge_is_found(ports):
    ports(FTDI, CH340, CH9102)
    assert transport.list_serial_ports() == ["/dev/ttyUSB0", "/dev/ttyACM0"]


def test_an_unknown_wch_bridge_is_a_last_resort(ports):
    """Without a known product ID, any WCH bridge is better than telling the user there is nothing."""
    ports(FTDI, OTHER_WCH)
    assert transport.list_serial_ports() == ["/dev/ttyUSB1"]


def test_autodetection_does_not_guess(ports):
    """Strict is what the GUI offers unasked, so half the hobby electronics ever made must not qualify."""
    ports(FTDI, OTHER_WCH)
    assert transport.list_serial_ports(strict=True) == []

    ports(FTDI, OTHER_WCH, CH340)
    assert transport.list_serial_ports(strict=True) == ["/dev/ttyUSB0"]
