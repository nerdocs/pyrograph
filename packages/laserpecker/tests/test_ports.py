"""Which serial ports count as a LaserPecker, and how big a Bluetooth write may be."""

from dataclasses import dataclass
from types import SimpleNamespace

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


def _ble(mtu_size):
    """A BleTransport that never connected — only its chunk arithmetic is under test."""
    ble = transport.BleTransport.__new__(transport.BleTransport)
    ble._client = SimpleNamespace(mtu_size=mtu_size)
    return ble


def test_the_chunk_size_follows_the_negotiated_mtu():
    """A write past the ATT MTU is rejected outright, so an adapter stuck at the default must shrink it."""
    assert _ble(23)._negotiated_mtu() == 20


def test_the_chunk_size_never_exceeds_the_vendors():
    """179 bytes is what the device is known to swallow; a roomier MTU is no reason to try more."""
    assert _ble(517)._negotiated_mtu() == 179


def test_an_unknown_mtu_falls_back_to_the_vendors():
    ble = transport.BleTransport.__new__(transport.BleTransport)
    ble._client = object()  # a backend that does not expose the negotiated MTU
    assert ble._negotiated_mtu() == 179
