"""The wire format of a BJJCZ LMC controller — the board EZCad2 drives.

Everything here is pure arithmetic on bytes, so all of it is testable without a laser attached. The
protocol is small: every command is six little-endian words, and the board accepts packets of exactly two
sizes. What makes it awkward is not the encoding but the buffering, which lives in :mod:`ezcad2.device`.

Read from the reverse engineering in `balor <https://gitlab.com/bryce15/balor>`_ and
`galvoplotter <https://github.com/meerk40t/galvoplotter>`_; see ``docs/galvo.md``. **Not verified against
hardware** — no machine was available.
"""

from __future__ import annotations

import struct

PACKET = 0x0C
"""Bytes in one command: an opcode and five arguments, each a 16-bit word."""

LIST_PACKET = 0x0C00
"""Bytes in one list block. The board takes these two sizes and rejects everything else."""

COMMANDS_PER_LIST = LIST_PACKET // PACKET  # 256

REPLY = 8
"""Every reply is eight bytes, read as four words."""

# ---------------------------------------------------------------- single commands, acted on at once

DISABLE_LASER = 0x0002
ENABLE_LASER = 0x0004
EXECUTE_LIST = 0x0005
SET_PWM_PULSE_WIDTH = 0x0006
GET_VERSION = 0x0007
GET_SERIAL_NO = 0x0009
GET_LIST_STATUS = 0x000A
GET_POSITION_XY = 0x000C
GOTO_XY = 0x000D
WRITE_COR_LINE = 0x0010
RESET_LIST = 0x0012
WRITE_COR_TABLE = 0x0015
SET_CONTROL_MODE = 0x0016
SET_DELAY_MODE = 0x0017
SET_MAX_POLY_DELAY = 0x0018
SET_END_OF_LIST = 0x0019
SET_FIRST_PULSE_KILLER = 0x001A
SET_LASER_MODE = 0x001B
SET_TIMING = 0x001C
SET_STANDBY = 0x001D
SET_PWM_HALF_PERIOD = 0x001E
STOP_EXECUTE = 0x001F
STOP_LIST = 0x0020
WRITE_PORT = 0x0021
WRITE_ANALOG_PORT_1 = 0x0022
SET_FPK_PARAM_2 = 0x002E
FIBER_SET_MO = 0x0033
ENABLE_Z = 0x003A
RESET = 0x0040
GET_MARK_TIME = 0x0041

# ---------------------------------------------------------------- list commands, buffered then run

LIST_JUMP_TO = 0x8001
LIST_END_OF_LIST = 0x8002
LIST_LASER_ON_POINT = 0x8003
LIST_DELAY_TIME = 0x8004
LIST_MARK_TO = 0x8005
LIST_JUMP_SPEED = 0x8006
LIST_LASER_ON_DELAY = 0x8007
LIST_LASER_OFF_DELAY = 0x8008
LIST_MARK_FREQ = 0x800A
LIST_MARK_POWER_RATIO = 0x800B
LIST_MARK_SPEED = 0x800C
LIST_JUMP_DELAY = 0x800D
LIST_POLYGON_DELAY = 0x800F
LIST_WRITE_PORT = 0x8011
LIST_QSWITCH_PERIOD = 0x801B
LIST_FIBER_OPEN_MO = 0x8021
LIST_FIBER_YLPM_PULSE_WIDTH = 0x8026
LIST_READY_MARK = 0x8051

# ---------------------------------------------------------------- status bits

BUSY = 0x04
READY = 0x20
AXIS = 0x40

# ---------------------------------------------------------------- coordinate space

CENTRE = 0x8000
"""Middle of the field. Coordinates are unsigned 16-bit, so the corners are 0 and 0xFFFF."""

MAX = 0xFFFF


def command(opcode: int, *args: int) -> bytes:
    """One command packet: the opcode and up to five arguments, little-endian.

    Arguments that are not given are sent as zero — the board expects all six words either way.
    """
    if len(args) > 5:
        raise ValueError(f"a command carries at most five arguments, got {len(args)}")
    values = list(args) + [0] * (5 - len(args))
    return struct.pack("<6H", opcode, *values)


def words(reply: bytes) -> tuple[int, int, int, int]:
    """The four words of a reply. Anything shorter than eight bytes is a truncated read."""
    if len(reply) < REPLY:
        raise ValueError(f"a reply is {REPLY} bytes, got {len(reply)}")
    return struct.unpack("<4H", bytes(reply[:REPLY]))


def galvos(mm: float, galvos_per_mm: float, origin: int = CENTRE) -> int:
    """Millimetres from the centre of the field to a device coordinate, clamped to the field.

    Clamping rather than raising is deliberate: a job that reaches past the lens is a job that was laid
    out too big, and refusing the whole thing at the first stray point helps nobody. The caller checks
    the bounds against :attr:`~ezcad2.device.GalvoDevice.field_mm` before it starts.
    """
    return max(0, min(MAX, round(origin + mm * galvos_per_mm)))


def speed(mm_s: float, galvos_per_mm: float) -> int:
    """Millimetres per second to the board's galvos-per-millisecond."""
    return max(1, int(mm_s * abs(galvos_per_mm) / 1000.0))


def power(percent: float) -> int:
    """Percent to the board's 12-bit scale."""
    return max(0, min(0xFFF, round(percent * 0xFFF / 100.0)))


def frequency(khz: float) -> int:
    """Kilohertz to a Q-switch period, in ticks of the board's 20 MHz reference."""
    if khz <= 0:
        raise ValueError("frequency must be positive")
    return round(20000.0 / khz) & 0xFFFF
