"""The device abstraction: LP vocabulary in, normalised state out."""

import pytest
from laserpecker.device import LaserPecker
from laserpecker.protocol import PreviewState
from laserpecker.transport import MockTransport

from pyrograph.devices import LP2, DeviceState, LaserPeckerDevice
from pyrograph.document import Document, ImageObject, LaserParams, Layer, Rect
from pyrograph.job import build_raster_job


@pytest.fixture
def device() -> LaserPeckerDevice:
    return LaserPeckerDevice.mock()


@pytest.fixture
def job(png_bytes):
    document = Document(
        layers=[
            Layer(
                params=LaserParams(power=42, depth=7, passes=2, dpi=254.0),
                objects=[ImageObject(data=png_bytes, width_mm=15.0, height_mm=15.0)],
            )
        ]
    )
    return build_raster_job(document, 0)


def test_an_idle_device_reports_idle(device):
    assert device.status().state is DeviceState.IDLE


def test_a_running_job_reports_progress(device, job):
    device.run(job)

    first = device.status()
    assert first.state is DeviceState.RUNNING
    assert 0 < first.progress < 100

    while device.status().state is DeviceState.RUNNING:
        pass
    assert device.status().state is DeviceState.IDLE


def test_pause_and_resume_are_visible_in_the_state(device, job):
    device.run(job)
    device.pause()
    assert device.status().state is DeviceState.PAUSED

    device.resume()
    assert device.status().state is DeviceState.RUNNING


def test_abort_returns_the_device_to_idle(device, job):
    device.run(job)
    device.abort()
    assert device.status().state is DeviceState.IDLE


def test_a_silent_device_is_offline():
    class Silent(MockTransport):
        def read_frame(self, timeout: float = 3.0) -> None:
            return None

    device = LaserPeckerDevice(LaserPecker(Silent()))
    status = device.status()
    assert status.state is DeviceState.OFFLINE
    assert status.message


def test_the_upload_carries_the_whole_raster(device, job):
    device.run(job)
    # 64-byte header plus one byte per pixel.
    assert len(device.driver.transport.uploads[0]) == 64 + job.raster.width * job.raster.height


def test_an_unsupported_resolution_is_refused(device, job):
    from dataclasses import replace

    with pytest.raises(ValueError, match="dpi"):
        device.run(replace(job, dpi=300.0))


def test_the_profile_snaps_a_layer_dpi_to_a_supported_step():
    assert LP2.nearest_dpi(280.0) == 254.0  # 26 below 254, 59 below 338.67
    assert LP2.nearest_dpi(320.0) == 338.66666
    assert LP2.nearest_dpi(600.0) == 508.0


def test_framing_sends_the_box_in_tenths_of_a_millimetre(device):
    device.frame(Rect(5.0, 2.0, 20.0, 10.0))

    body = device.driver.transport.commands[-1][4:]
    assert body[0] == PreviewState.RECTANGLE
    assert body[1:3] == (200).to_bytes(2, "big")  # width 20 mm
    assert body[3:5] == (100).to_bytes(2, "big")  # height 10 mm
    assert body[5:7] == (50).to_bytes(2, "big")  # x 5 mm
    assert body[7:9] == (20).to_bytes(2, "big")  # y 2 mm
