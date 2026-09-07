"""Correcting the field in software instead of in the board — experimental.

The board applies its own ``.cor`` table and that is the normal way to get a straight field
(:mod:`ezcad2.correction`). Balor's author found the built-in table did not fully linearise his machine
and added a second correction on the host, computed from a grid he burnt and measured by hand. This is
that idea, in a smaller form.

**When to reach for this:** only when no ``.cor`` file exists for the lens, or when one is loaded and the
field is still visibly off. It is more work than it sounds — a grid of intersections measured with
calipers — and a table full of measuring mistakes bends the field instead of straightening it.

Balor interpolates with radial basis functions and needs scipy for it. This uses bilinear interpolation
on the measured grid, inverted by iteration. That is less clever and enough for barrel distortion, which
is smooth: it buys the correction without adding scipy to a package that otherwise needs only pyusb.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from . import protocol as p


@dataclass(frozen=True)
class Calibration:
    """A measured map from device coordinates to real millimetres, used backwards.

    The grid is regular in galvo units — those are the positions that were commanded — and irregular in
    millimetres, because that is what the distortion did to them. Going from a wanted millimetre position
    to the galvo units that land there is therefore the inverse of what was measured, which is why
    :meth:`to_galvo` iterates rather than looks up.
    """

    galvo_x: list[int]
    """The commanded X positions, ascending. One per grid column."""

    galvo_y: list[int]
    mm_x: list[list[float]]
    """Measured X, indexed ``[row][column]`` — row over ``galvo_y``, column over ``galvo_x``."""

    mm_y: list[list[float]]

    @property
    def size(self) -> tuple[int, int]:
        return len(self.galvo_x), len(self.galvo_y)

    def to_mm(self, x: float, y: float) -> tuple[float, float]:
        """Where a pair of galvo units actually lands, in millimetres. The measured direction."""
        col, fx = _cell(self.galvo_x, x)
        row, fy = _cell(self.galvo_y, y)
        return (
            _bilinear(self.mm_x, row, col, fx, fy),
            _bilinear(self.mm_y, row, col, fx, fy),
        )

    def to_galvo(self, x_mm: float, y_mm: float, galvos_per_mm: float) -> tuple[int, int]:
        """The galvo units that put the spot at ``x_mm, y_mm``.

        Newton's method on a map that is smooth by construction: guess linearly, see where that lands,
        push the guess by the error. Barrel distortion is gentle, so this closes in within a few rounds;
        the loop is capped because a table full of measuring errors need not converge at all.
        """
        x = p.CENTRE + x_mm * galvos_per_mm
        y = p.CENTRE + y_mm * galvos_per_mm
        for _ in range(12):
            landed_x, landed_y = self.to_mm(x, y)
            error_x, error_y = x_mm - landed_x, y_mm - landed_y
            if abs(error_x) < 1e-4 and abs(error_y) < 1e-4:
                break
            x += error_x * galvos_per_mm
            y += error_y * galvos_per_mm
        return max(0, min(p.MAX, round(x))), max(0, min(p.MAX, round(y)))


def _cell(axis: list[int], value: float) -> tuple[int, float]:
    """Which interval of ``axis`` holds ``value``, and how far into it — clamped at both ends.

    Clamping extrapolates the edge cell rather than refusing: a point just outside the measured area is
    better placed approximately than not at all, and the field is checked against the lens elsewhere.
    """
    index = min(max(bisect_right(axis, value) - 1, 0), len(axis) - 2)
    span = axis[index + 1] - axis[index]
    return index, (value - axis[index]) / span if span else 0.0


def _bilinear(table: list[list[float]], row: int, col: int, fx: float, fy: float) -> float:
    top = table[row][col] * (1 - fx) + table[row][col + 1] * fx
    bottom = table[row + 1][col] * (1 - fx) + table[row + 1][col + 1] * fx
    return top * (1 - fy) + bottom * fy


def read_calibration(path: str | Path) -> Calibration:
    """Read a measured grid in balor's format.

    One point per line, whitespace separated::

        measured_x_mm  measured_y_mm  column  row  galvo_x_hex  galvo_y_hex

    The galvo columns are hexadecimal without a prefix, which is how balor writes them. Lines that are
    blank or start with ``#`` are skipped, so a table can be annotated while it is being filled in — and
    it will be, because the measuring is done by hand.
    """
    points: dict[tuple[int, int], tuple[float, float, int, int]] = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 6:
            raise ValueError(f"line {number}: expected six columns, got {len(parts)}")
        try:
            mm_x, mm_y = float(parts[0]), float(parts[1])
            col, row = int(parts[2]), int(parts[3])
            gx, gy = int(parts[4], 16), int(parts[5], 16)
        except ValueError as error:
            raise ValueError(f"line {number}: {error}") from error
        points[(row, col)] = (mm_x, mm_y, gx, gy)

    if not points:
        raise ValueError("the calibration file holds no points")

    rows = sorted({row for row, _ in points})
    cols = sorted({col for _, col in points})
    missing = [(r, c) for r in rows for c in cols if (r, c) not in points]
    if missing:
        raise ValueError(
            f"the grid has a hole at row {missing[0][0]}, column {missing[0][1]} — "
            f"{len(missing)} of {len(rows) * len(cols)} points are missing"
        )
    if len(rows) < 2 or len(cols) < 2:
        raise ValueError("a grid needs at least two rows and two columns to interpolate between")

    galvo_x = [points[(rows[0], c)][2] for c in cols]
    galvo_y = [points[(r, cols[0])][3] for r in rows]
    if galvo_x != sorted(galvo_x) or galvo_y != sorted(galvo_y):
        raise ValueError("the grid's galvo coordinates must ascend with its column and row numbers")

    return Calibration(
        galvo_x=galvo_x,
        galvo_y=galvo_y,
        mm_x=[[points[(r, c)][0] for c in cols] for r in rows],
        mm_y=[[points[(r, c)][1] for c in cols] for r in rows],
    )
