"""The in-memory device: enough of a device that the whole driver runs against it."""

from PIL import Image

from laserpecker import protocol as p
from laserpecker.device import LaserPecker
from laserpecker.transport import MockTransport


def _device() -> LaserPecker:
    return LaserPecker(MockTransport())


def test_queries_are_answered_with_the_captured_replies():
    device = _device()
    info = device.info()
    assert info.sw_version == 316
    assert info.mac == "DC:0D:30:AA:BB:CC"


def test_a_fresh_device_is_idle():
    status = _device().status()
    assert status.mode == p.WorkMode.IDLE
    assert status.rate == 0


def test_an_engraving_run_progresses_and_finishes():
    device = _device()
    device.engrave_image(Image.linear_gradient("L"), x_mm=40, y_mm=40, width_mm=15)

    assert device.status().mode == p.WorkMode.ENGRAVING
    final = device.wait_until_done(poll=0.0)
    assert final.rate == 100
    assert final.finished


def test_the_upload_arrives_whole_and_the_file_is_listed():
    device = _device()
    file_id = device.engrave_image(Image.linear_gradient("L"), x_mm=40, y_mm=40, width_mm=15)
    device.wait_until_done(poll=0.0)

    # 15 mm at 254 dpi is 150 px square, preceded by the 64-byte header.
    assert len(device.transport.uploads) == 1
    assert len(device.transport.uploads[0]) == 64 + 150 * 150
    assert device.file_ids() == [file_id]


def test_pausing_stops_the_progress():
    device = _device()
    device.engrave_image(Image.linear_gradient("L"), x_mm=0, y_mm=0, width_mm=5)
    device.status()

    device.pause()
    held = device.status().rate
    assert device.status().rate == held  # no further progress while held

    device.pause(False)
    assert device.status().rate > held


def test_stop_returns_the_device_to_idle():
    device = _device()
    device.engrave_image(Image.linear_gradient("L"), x_mm=0, y_mm=0, width_mm=5)

    device.abort()
    assert device.status().mode == p.WorkMode.IDLE
