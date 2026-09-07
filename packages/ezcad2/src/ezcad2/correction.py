"""Reading a ``.cor`` lens correction file.

Every galvo lens distorts its field, so the board keeps a 65 × 65 grid of offsets and applies it to every
coordinate. The file is not transferred as a file: it is read here and written row by row with
``WriteCorLine`` (:mod:`ezcad2.device`).

The grid cannot be derived from the machine — it comes from a calibration against a printed target, which
is what EZCad2's and LightBurn's wizards produce. Without one, the board gets a blank table and the field
is geometrically wrong, which is fine for a first light test and useless for real work.
"""

from __future__ import annotations

import struct
from pathlib import Path

GRID = 65
"""Points per axis. The table is always this size; the file format only differs in how it stores them."""

_LABEL = "LMC1COR_1.0"
_LABEL_BYTES = 0x16


def _offset(value: float) -> int:
    """One grid offset to the board's encoding, where a negative value moves into the high half."""
    rounded = int(round(value))
    if rounded < 0:
        rounded = -rounded + 0x8000
    return rounded & 0xFFFF


def read_table(path: str | Path) -> list[tuple[int, int]]:
    """The correction grid as ``GRID * GRID`` ``(dx, dy)`` pairs, in the order the board expects them.

    Two layouts exist and the label at the front says which: the newer one stores doubles, the older one
    32-bit integers.
    """
    with open(path, "rb") as f:
        label = f.read(_LABEL_BYTES)
        try:
            is_float = label.decode("utf-16") == _LABEL
        except UnicodeDecodeError:
            is_float = False
        if is_float:
            f.read(0x1FA)  # header, not understood beyond the scale below
            return _read_grid(f, "d", 8)
        f.read(0x0E)
        return _read_grid(f, "i", 4)


def _read_grid(f, code: str, size: int) -> list[tuple[int, int]]:
    table = []
    for _ in range(GRID * GRID):
        raw = f.read(size * 2)
        if len(raw) < size * 2:
            raise ValueError("correction file ends early; it does not hold a full 65×65 grid")
        dx, dy = struct.unpack(f"<2{code}", raw)
        table.append((_offset(dx), _offset(dy)))
    return table


def read_scale(path: str | Path) -> float:
    """The ``galvos_per_mm`` the file was calibrated at.

    Worth reading because it is the one place that number can come from without measuring a test burn by
    hand — the file and the lens belong together. The direction is not guesswork: MeerK40t derives the
    field size from the same value as ``65536 / scale``, so a larger scale is a smaller field.
    """
    with open(path, "rb") as f:
        label = f.read(_LABEL_BYTES)
        try:
            is_float = label.decode("utf-16") == _LABEL
        except UnicodeDecodeError:
            is_float = False
        if is_float:
            f.read(2)
            return struct.unpack("<63d", f.read(0x1F8))[43]
        f.read(6)
        return struct.unpack("<d", f.read(8))[0]
