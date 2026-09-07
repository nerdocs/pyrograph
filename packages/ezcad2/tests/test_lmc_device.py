"""The driver against a mock board: buffering, the marking sequence, and the things that move a laser.

None of this proves the board would agree — it proves the driver builds what balor and galvoplotter say
it should, and that it does not, say, leave the laser gate open after a job.
"""

import struct

import pytest
from ezcad2 import GalvoDevice, Lens, MarkParams, MockTransport
from ezcad2 import protocol as p


@pytest.fixture
def device() -> GalvoDevice:
    return GalvoDevice.mock()


def opcodes(transport: MockTransport) -> list[int]:
    """Every single command sent, in order. List blocks are not commands and are left out."""
    return [
        struct.unpack("<6H", packet)[0] for packet in transport.packets if len(packet) == p.PACKET
    ]


def list_commands(transport: MockTransport) -> list[tuple[int, ...]]:
    """Every list command sent, unpacked, with the end-of-list padding removed."""
    out = []
    for block in transport.lists:
        for i in range(0, len(block), p.PACKET):
            command = struct.unpack("<6H", block[i : i + p.PACKET])
            if command[0] != p.LIST_END_OF_LIST:
                out.append(command)
    return out


def test_a_fresh_device_is_idle(device):
    assert not device.is_busy()
    assert device.is_ready()


def test_initialisation_writes_a_blank_table_when_there_is_no_calibration(device):
    """A blank table is a wrong field, but it is honest — and it is what EZCad2 does too."""
    device.init()

    sent = opcodes(device.transport)
    assert p.WRITE_COR_TABLE in sent
    assert p.WRITE_COR_LINE not in sent, "there is no calibration to write"


def test_initialisation_happens_once(device):
    device.init()
    first = len(device.transport.packets)
    device.init()

    assert len(device.transport.packets) == first


def test_marking_sends_a_jump_to_the_start_and_marks_the_rest(device):
    """The first point of an outline is travelled to dark; only the rest is burnt."""
    device.mark([[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]])

    commands = [c[0] for c in list_commands(device.transport)]
    assert commands.count(p.LIST_JUMP_TO) == 1
    assert commands.count(p.LIST_MARK_TO) == 2


def test_a_single_point_is_not_a_stroke(device):
    device.mark([[(0.0, 0.0)], [(0.0, 0.0), (5.0, 5.0)]])

    commands = [c[0] for c in list_commands(device.transport)]
    assert commands.count(p.LIST_JUMP_TO) == 1, "the lone point should not have been travelled to"
    assert commands.count(p.LIST_MARK_TO) == 1


def test_marking_closes_the_laser_gate_afterwards(device):
    """Leaving the master oscillator open after a job is the kind of bug that burns a workpiece."""
    device.mark([[(0.0, 0.0), (5.0, 0.0)]])

    mo = [
        struct.unpack("<6H", packet)[1]
        for packet in device.transport.packets
        if len(packet) == p.PACKET and struct.unpack("<6H", packet)[0] == p.FIBER_SET_MO
    ]
    assert mo[-1] == 0, "the fiber source was left switched on"


def test_a_co2_source_never_touches_the_fiber_oscillator():
    device = GalvoDevice.mock(source="co2")
    device.mark([[(0.0, 0.0), (5.0, 0.0)]])

    assert p.FIBER_SET_MO not in opcodes(device.transport)


def test_an_unknown_source_is_refused():
    with pytest.raises(ValueError):
        GalvoDevice.mock(source="plasma")


def test_a_long_job_is_split_into_blocks_and_started(device):
    """More commands than fit in one block must not silently lose the remainder."""
    line = [(float(i) / 100, 0.0) for i in range(600)]
    device.mark([line])

    assert len(device.transport.lists) >= 3
    assert p.EXECUTE_LIST in opcodes(device.transport)
    marks = [c for c in list_commands(device.transport) if c[0] == p.LIST_MARK_TO]
    assert len(marks) == 599


def test_a_short_job_is_started_too(device):
    """The board self-starts at the third block; a job smaller than that has to be told."""
    device.mark([[(0.0, 0.0), (1.0, 1.0)]])

    assert len(device.transport.lists) == 1
    assert p.EXECUTE_LIST in opcodes(device.transport)


def test_every_block_is_a_full_packet(device):
    """The board rejects anything that is not exactly 12 or 3072 bytes."""
    device.mark([[(float(i) / 50, 0.0) for i in range(400)]])

    assert all(len(block) == p.LIST_PACKET for block in device.transport.lists)


def test_passes_repeat_the_whole_job(device):
    device.mark([[(0.0, 0.0), (5.0, 0.0)]], MarkParams(passes=3))

    marks = [c for c in list_commands(device.transport) if c[0] == p.LIST_MARK_TO]
    assert len(marks) == 3


def test_parameters_reach_the_list(device):
    device.mark([[(0.0, 0.0), (5.0, 0.0)]], MarkParams(power=25.0, speed_mm_s=200.0, frequency_khz=20.0))

    by_opcode = {c[0]: c[1] for c in list_commands(device.transport)}
    assert by_opcode[p.LIST_MARK_POWER_RATIO] == p.power(25.0)
    assert by_opcode[p.LIST_MARK_SPEED] == p.speed(200.0, 500.0)
    assert by_opcode[p.LIST_QSWITCH_PERIOD] == p.frequency(20.0)


def test_the_field_follows_from_the_lens():
    assert Lens(galvos_per_mm=500.0).field_mm == pytest.approx(131.07, abs=0.01)
    assert Lens(galvos_per_mm=1000.0).field_mm < Lens(galvos_per_mm=500.0).field_mm


def test_aborting_stops_the_board(device):
    device.abort()

    sent = opcodes(device.transport)
    assert p.STOP_EXECUTE in sent
    assert p.STOP_LIST in sent


def test_framing_traces_until_it_is_stopped(device):
    """The board runs a list once, so the repeat has to come from the driver."""
    device.light([[(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0), (-5.0, -5.0)]])
    try:
        assert device._light_thread is not None and device._light_thread.is_alive()
    finally:
        device.stop_light()
    assert device._light_thread is None


def test_a_cloned_board_counts_as_a_board():
    """A clone that is invisible looks like nothing plugged in, which is the wrong thing to report."""
    from ezcad2.transport import CLONE_PRODUCT, PRODUCT, PRODUCTS

    assert set(PRODUCTS) == {PRODUCT, CLONE_PRODUCT}
    assert PRODUCTS[CLONE_PRODUCT] == "cloned board"


def test_a_mock_board_needs_no_firmware(device):
    """The flag has to exist on every transport, or the read path branches on a missing attribute."""
    assert device.transport.needs_firmware is False
