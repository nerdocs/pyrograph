"""The galvo adapter: LMC vocabulary in, normalised state out.

The coordinate change is the part worth guarding. A document counts from a corner and downwards, a galvo
from the middle of its field and upwards, and getting that wrong mirrors the job without failing.
"""

import struct

import pytest
from ezcad2 import protocol as lmc

from pyrograph.devices import DeviceState, GalvoAdapter
from pyrograph.document import Document, Layer, LineTo, MoveTo, Path, PathObject, Point, Rect
from pyrograph.job import build_raster_job, build_vector_job


@pytest.fixture
def device() -> GalvoAdapter:
    return GalvoAdapter.mock()


@pytest.fixture
def job():
    square = PathObject(
        path=Path(
            [MoveTo(Point(10, 10)), LineTo(Point(20, 10)), LineTo(Point(20, 20)), LineTo(Point(10, 20))]
        )
    )
    return build_vector_job(Document(layers=[Layer(objects=[square])]), 0)


def marks(device: GalvoAdapter) -> list[tuple[int, int]]:
    """The (x, y) of every mark command that reached the board."""
    out = []
    for block in device.driver.transport.lists:
        for i in range(0, len(block), lmc.PACKET):
            command = struct.unpack("<6H", block[i : i + lmc.PACKET])
            if command[0] == lmc.LIST_MARK_TO:
                out.append((command[1], command[2]))
    return out


def test_the_profile_says_this_machine_streams_vectors(device):
    assert device.profile.streams, "the board marks while the list is still arriving"
    assert device.profile.paths
    assert not device.profile.raster


def test_a_vector_device_does_not_snap_the_layer_dpi(device):
    """There are no resolution steps to snap to, so the layer keeps whatever it asked for."""
    assert device.profile.nearest_dpi(317.5) == 317.5


def test_an_idle_device_reports_idle(device):
    status = device.status()

    assert status.state is DeviceState.IDLE
    assert status.progress is None, "this board counts nothing between busy and ready"


def test_the_job_is_centred_on_the_field(device, job):
    """The drawing sits at 10..20 mm; its middle has to land on the middle of the field."""
    device.run(job)

    xs = [x for x, _ in marks(device)]
    ys = [y for _, y in marks(device)]
    assert min(xs) < lmc.CENTRE < max(xs)
    assert min(ys) < lmc.CENTRE < max(ys)
    assert (min(xs) + max(xs)) // 2 == pytest.approx(lmc.CENTRE, abs=1)


def test_the_y_axis_is_flipped(device):
    """The document counts downwards like SVG; the machine counts upwards."""
    line = PathObject(path=Path([MoveTo(Point(0, 0)), LineTo(Point(0, 10))]))
    job = build_vector_job(Document(layers=[Layer(objects=[line])]), 0)

    device.run(job)

    (_, y_end), = marks(device)
    assert y_end < lmc.CENTRE, "a point further down the page must come out lower on the machine"


def test_a_job_bigger_than_the_field_is_refused(device):
    """Clamping it would mark a silently cropped drawing."""
    wide = PathObject(path=Path([MoveTo(Point(0, 0)), LineTo(Point(500, 0))]))
    job = build_vector_job(Document(layers=[Layer(objects=[wide])]), 0)

    with pytest.raises(ValueError, match="field"):
        device.run(job)


def test_a_raster_job_is_refused_with_a_useful_message(device, png_bytes):
    """The panel picks the job type from the profile; a mismatch here means that logic broke."""
    from pyrograph.document import ImageObject, LaserParams

    document = Document(
        layers=[
            Layer(
                params=LaserParams(dpi=254.0),
                objects=[ImageObject(data=png_bytes, width_mm=10.0, height_mm=10.0)],
            )
        ]
    )
    raster = build_raster_job(document, 0)

    with pytest.raises(TypeError, match="vectors"):
        device.run(raster)


def test_progress_is_reported_while_sending(device, job):
    seen = []
    device.run(job, progress=lambda done, total: seen.append((done, total)))

    assert seen, "nothing reported progress"
    assert seen[-1][0] == seen[-1][1], "the last report should be the finished one"


def test_pause_is_visible_in_the_state(device):
    device.pause()
    assert device.status().state is DeviceState.PAUSED

    device.resume()
    assert device.status().state is DeviceState.IDLE


def test_framing_traces_the_box_and_stops(device):
    device.frame(Rect(10, 10, 20, 20))
    try:
        assert device.driver._light_thread is not None
    finally:
        device.stop_frame()

    assert device.driver._light_thread is None
