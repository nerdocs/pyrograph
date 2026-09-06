"""Parser tests against replies captured from a real LP2 (firmware 3.16, hardware 01 32 1e 86).

Fixtures in ``fixtures_lp2.json`` were recorded over BLE; the USB replies are byte-identical except for
``u_b_conn``. Keeping them here means a parser change that breaks real traffic fails the suite.
"""

import json
from pathlib import Path

import pytest

from laserpecker import protocol as p

FIXTURES = json.loads((Path(__file__).parent / "fixtures_lp2.json").read_text())


def frame(name: str) -> bytes:
    return bytes.fromhex(FIXTURES[name])


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_all_captured_frames_validate(name):
    assert p.frame_complete(frame(name)), f"{name} fails header/checksum validation"


def test_version():
    version = p.parse_version(frame("version"))
    assert version.sw_version == 316  # LP2 range 315~349 → dithering supported
    assert version.hw_bytes == bytes([0x01, 0x32, 0x1E, 0x86])


def test_status_idle():
    status = p.parse_status(frame("status"))
    assert status.mode == p.WorkMode.IDLE
    assert status.error == 0
    assert status.rate == 0
    # len byte is 24, so the cover fields are absent on this firmware
    assert status.stop is None


def test_status_reports_active_link():
    # byte 24: 1 when only BLE is connected, 2 whenever USB is plugged in
    assert p.parse_status(frame("status")).u_b_conn == 1

    usb = bytes.fromhex("aabb18000600000000000000000000000000000000000000020008")
    assert p.frame_complete(usb)
    assert p.parse_status(usb).u_b_conn == 2


def test_mac():
    assert p.parse_mac(frame("mac")) == "DC:0D:30:AA:BB:CC"
    # the advertised BLE name ends with the last three octets
    assert p.parse_mac_suffix(frame("mac")) == "AABBCC"


def test_file_ids():
    ids = p.parse_file_ids(frame("file_ids"))
    assert len(ids) == 31  # the count is echoed in byte 4
    assert frame("file_ids")[4] == len(ids)
    assert ids[0] == 0x000607FB
    assert ids[-1] == 0x00060574
    assert all(0 < i < 0xFFFFFFFF for i in ids)


def test_long_file_id_frame_checksum():
    buf = frame("file_ids")
    assert len(buf) == 133
    assert buf[2] == 130  # single length byte, payload counted from func
