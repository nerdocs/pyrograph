"""The wire format: packet shape and unit conversion.

Everything here is arithmetic, so it is the one part of this package that can be proven without a laser.
"""

import struct

import pytest
from ezcad2 import protocol as p


def test_a_command_is_six_little_endian_words():
    packet = p.command(p.LIST_MARK_TO, 0x1234, 0x5678)

    assert len(packet) == p.PACKET
    assert struct.unpack("<6H", packet) == (p.LIST_MARK_TO, 0x1234, 0x5678, 0, 0, 0)


def test_a_command_takes_at_most_five_arguments():
    """The sixth word would silently overwrite the next command in a list block."""
    with pytest.raises(ValueError):
        p.command(p.LIST_MARK_TO, 1, 2, 3, 4, 5, 6)


def test_a_list_block_holds_two_hundred_and_fifty_six_commands():
    assert p.COMMANDS_PER_LIST == 256
    assert p.COMMANDS_PER_LIST * p.PACKET == p.LIST_PACKET


def test_a_reply_shorter_than_eight_bytes_is_a_truncated_read():
    with pytest.raises(ValueError):
        p.words(b"\x00\x01\x02")


def test_the_field_centre_is_the_origin():
    """A galvo's zero is the middle of its field, not a corner."""
    assert p.galvos(0.0, 500.0) == p.CENTRE
    assert p.galvos(10.0, 500.0) == p.CENTRE + 5000
    assert p.galvos(-10.0, 500.0) == p.CENTRE - 5000


def test_a_point_past_the_lens_is_clamped_not_wrapped():
    """Sixteen bits wrap around; a point off the right edge would come out on the left."""
    assert p.galvos(1000.0, 500.0) == p.MAX
    assert p.galvos(-1000.0, 500.0) == 0


def test_speed_is_galvos_per_millisecond():
    assert p.speed(1000.0, 500.0) == 500
    assert p.speed(0.001, 500.0) >= 1, "a speed must never round down to a standstill"


def test_power_is_twelve_bit():
    assert p.power(0) == 0
    assert p.power(100) == 0xFFF
    assert p.power(50) == pytest.approx(0xFFF // 2, abs=1)
    assert p.power(150) == 0xFFF, "a percentage above a hundred is a mistake, not more power"


def test_frequency_becomes_a_period():
    """The board counts ticks between pulses, so the conversion inverts."""
    assert p.frequency(20.0) == 1000
    assert p.frequency(40.0) < p.frequency(20.0)

    with pytest.raises(ValueError):
        p.frequency(0)
