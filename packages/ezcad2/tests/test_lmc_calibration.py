"""The experimental host-side field correction: reading a measured grid, and undoing what it measured."""

import pytest
from ezcad2 import protocol as p
from ezcad2.calibration import read_calibration


def write_grid(path, distort=0.0, per_mm=500.0, half=4, step=0x1000):
    """A measured grid for a lens with ``distort`` worth of barrel distortion.

    ``distort`` of zero is a perfect lens: the measured millimetres are exactly what was commanded. A
    positive value pulls the corners in, which is what barrel distortion does.
    """
    lines = ["# x_mm y_mm column row galvo_x galvo_y"]
    for row in range(-half, half + 1):
        for col in range(-half, half + 1):
            gx, gy = p.CENTRE + col * step, p.CENTRE + row * step
            x_mm, y_mm = (gx - p.CENTRE) / per_mm, (gy - p.CENTRE) / per_mm
            shrink = 1.0 - distort * (x_mm**2 + y_mm**2) / 10000.0
            lines.append(f"{x_mm * shrink:.4f} {y_mm * shrink:.4f} {col} {row} {gx:04X} {gy:04X}")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_grid_is_read_with_its_shape(tmp_path):
    grid = read_calibration(write_grid(tmp_path / "cal.csv"))

    assert grid.size == (9, 9)


def test_comments_and_blank_lines_are_skipped(tmp_path):
    """The table is filled in by hand over an afternoon; it will have notes in it."""
    path = write_grid(tmp_path / "cal.csv")
    path.write_text(path.read_text() + "\n# measured 2026-09-08, second attempt\n\n")

    assert read_calibration(path).size == (9, 9)


def test_a_perfect_lens_needs_no_correction(tmp_path):
    """With nothing to undo, the answer has to match the plain linear conversion."""
    grid = read_calibration(write_grid(tmp_path / "cal.csv", distort=0.0))

    for x_mm, y_mm in ((0.0, 0.0), (10.0, -5.0), (-3.5, 7.25)):
        assert grid.to_galvo(x_mm, y_mm, 500.0) == (p.galvos(x_mm, 500.0), p.galvos(y_mm, 500.0))


def test_a_distorted_lens_is_corrected_outwards(tmp_path):
    """Barrel distortion pulls a point in, so hitting the mark means commanding further out."""
    grid = read_calibration(write_grid(tmp_path / "cal.csv", distort=1.0))

    x, _y = grid.to_galvo(20.0, 0.0, 500.0)
    assert x > p.galvos(20.0, 500.0), "the correction has to push past the uncorrected position"


def test_the_correction_lands_where_it_was_asked_to(tmp_path):
    """The whole point: feed the answer back through the measured map and arrive at the target."""
    grid = read_calibration(write_grid(tmp_path / "cal.csv", distort=1.0))

    for x_mm, y_mm in ((0.0, 0.0), (15.0, 15.0), (-20.0, 8.0), (5.5, -12.25)):
        landed = grid.to_mm(*grid.to_galvo(x_mm, y_mm, 500.0))
        assert landed == pytest.approx((x_mm, y_mm), abs=0.01)


def test_a_grid_with_a_hole_says_which_point_is_missing(tmp_path):
    """Losing one measurement in eighty-one is easy; finding out at mark time is not."""
    path = write_grid(tmp_path / "cal.csv")
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:5] + lines[6:]))

    with pytest.raises(ValueError, match="hole at row"):
        read_calibration(path)


def test_a_short_line_is_refused(tmp_path):
    path = tmp_path / "cal.csv"
    path.write_text("0.0 0.0 0 0\n")

    with pytest.raises(ValueError, match="six columns"):
        read_calibration(path)


def test_an_empty_table_is_refused(tmp_path):
    path = tmp_path / "cal.csv"
    path.write_text("# nothing measured yet\n")

    with pytest.raises(ValueError, match="no points"):
        read_calibration(path)


def test_a_device_uses_the_calibration_when_it_has_one(tmp_path):
    """The driver has to actually consult the table, not just carry it around."""
    import struct

    from ezcad2 import GalvoDevice, Lens

    grid = read_calibration(write_grid(tmp_path / "cal.csv", distort=1.0))
    device = GalvoDevice.mock(lens=Lens(galvos_per_mm=500.0, calibration=grid))
    device.mark([[(0.0, 0.0), (20.0, 0.0)]])

    marks = [
        struct.unpack("<6H", block[i : i + p.PACKET])
        for block in device.transport.lists
        for i in range(0, len(block), p.PACKET)
    ]
    end = next(m for m in marks if m[0] == p.LIST_MARK_TO)
    assert end[1] > p.galvos(20.0, 500.0), "the mark went to the uncorrected position"
