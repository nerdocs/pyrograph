"""SVG import: user units become millimetres, every shape becomes a path.

The expected numbers are computed from the SVG specification, not from a previous run. One CSS pixel is
1/96 inch = 0.264583… mm.
"""

import base64
import math

import pytest

from pyrograph.document import ImageObject, PathObject, Point, Rect, SvgImportError, import_svg
from pyrograph.document.svg import PX_MM, parse_path_data, parse_transform


def _box(rect: Rect) -> tuple:
    """A rectangle as a plain tuple, so ``pytest.approx`` can compare it."""
    return (rect.x, rect.y, rect.width, rect.height)


def _svg(body: str, attrs: str = 'width="100mm" height="100mm" viewBox="0 0 100 100"') -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>'.encode()


def test_viewbox_maps_user_units_onto_the_physical_size():
    # 200 user units across 100 mm → one unit is half a millimetre.
    result = import_svg(
        _svg('<rect x="0" y="0" width="20" height="10"/>', 'width="100mm" height="50mm" viewBox="0 0 200 100"')
    )
    assert result.document.width_mm == 100.0
    assert result.document.objects().__next__().bounds().width == 10.0


def test_without_a_viewbox_user_units_are_css_pixels():
    result = import_svg(_svg('<rect x="0" y="0" width="96" height="96"/>', 'width="50mm" height="50mm"'))
    box = next(result.document.objects()).bounds()
    assert math.isclose(box.width, 96 * PX_MM)  # 96 px = 1 inch = 25.4 mm
    assert math.isclose(box.width, 25.4)


def test_without_any_size_the_content_defines_the_work_area():
    result = import_svg(_svg('<rect x="0" y="0" width="96" height="48"/>', ""))
    assert math.isclose(result.document.width_mm, 25.4)
    assert math.isclose(result.document.height_mm, 12.7)


def test_nested_group_transforms_compose():
    result = import_svg(
        _svg('<g transform="translate(10 0)"><g transform="scale(2)"><rect width="5" height="5"/></g></g>')
    )
    # Inner scale first, then the outer translate: 5×5 becomes 10×10 at x = 10.
    assert _box(next(result.document.objects()).bounds()) == pytest.approx((10.0, 0.0, 10.0, 10.0))


def test_every_basic_shape_becomes_a_path():
    result = import_svg(
        _svg(
            '<circle cx="10" cy="10" r="5"/>'
            '<ellipse cx="10" cy="10" rx="5" ry="2"/>'
            '<line x1="0" y1="0" x2="10" y2="10"/>'
            '<polyline points="0,0 10,0 10,10"/>'
            '<polygon points="0,0 10,0 10,10"/>'
            '<rect width="4" height="4"/>'
        )
    )
    objects = list(result.document.objects())
    assert len(objects) == 6
    assert all(isinstance(obj, PathObject) for obj in objects)
    assert _box(objects[0].bounds()) == pytest.approx((5.0, 5.0, 10.0, 10.0))  # the circle


def test_unsupported_elements_are_reported_not_dropped_silently():
    result = import_svg(_svg('<text x="0" y="0">hi</text><rect width="1" height="1"/>'))
    assert result.skipped == ["text"]
    assert len(list(result.document.objects())) == 1


def test_hidden_elements_are_skipped():
    result = import_svg(_svg('<rect width="1" height="1" display="none"/>'))
    assert list(result.document.objects()) == []


def test_an_inline_image_is_imported_with_its_placement(png_bytes):
    href = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    result = import_svg(_svg(f'<image x="5" y="5" width="20" height="10" href="{href}"/>'))

    image = next(result.document.objects())
    assert isinstance(image, ImageObject)
    assert image.data == png_bytes
    assert _box(image.bounds()) == pytest.approx((5.0, 5.0, 20.0, 10.0))


def test_an_image_next_to_the_file_is_read_from_disk(tmp_path, png_bytes):
    (tmp_path / "photo.png").write_bytes(png_bytes)
    (tmp_path / "drawing.svg").write_bytes(_svg('<image width="10" height="10" href="photo.png"/>'))

    image = next(import_svg(tmp_path / "drawing.svg").document.objects())
    assert image.data == png_bytes


def test_a_non_svg_root_is_rejected():
    with pytest.raises(SvgImportError):
        import_svg(b"<html></html>")


# ---------------------------------------------------------------------------------------- path data


def test_relative_commands_accumulate():
    path = parse_path_data("m 10 10 l 5 0 l 0 5 z")
    assert _box(path.bounds()) == pytest.approx((10.0, 10.0, 5.0, 5.0))


def test_repeated_moveto_coordinates_are_linetos():
    assert _box(parse_path_data("M 0 0 10 0 10 10").bounds()) == pytest.approx((0.0, 0.0, 10.0, 10.0))


def test_horizontal_and_vertical_shorthands():
    assert _box(parse_path_data("M 0 0 H 10 V 5 h -4 v -2").bounds()) == pytest.approx((0.0, 0.0, 10.0, 5.0))


def test_smooth_cubic_mirrors_the_previous_handle():
    explicit = parse_path_data("M 0 0 C 0 10 10 10 10 0 C 10 -10 20 -10 20 0")
    shorthand = parse_path_data("M 0 0 C 0 10 10 10 10 0 S 20 -10 20 0")
    assert shorthand.to_svg_d() == explicit.to_svg_d()


def test_a_quadratic_becomes_the_equivalent_cubic():
    # Q 5 10 10 0 peaks at half the control height: 5 mm.
    assert _box(parse_path_data("M 0 0 Q 5 10 10 0").bounds()) == pytest.approx((0.0, 0.0, 10.0, 5.0))


def test_a_half_circle_arc_spans_its_radius():
    # From (0,0) to (20,0) over a radius-10 arc: a half circle, 10 deep. Sweep 1 runs in the direction of
    # growing angles, which with y pointing down puts the bulge above the chord.
    assert _box(parse_path_data("M 0 0 A 10 10 0 0 1 20 0").bounds()) == pytest.approx(
        (0.0, -10.0, 20.0, 10.0), abs=0.01
    )


def test_arc_sweep_flips_the_side():
    assert _box(parse_path_data("M 0 0 A 10 10 0 0 0 20 0").bounds()) == pytest.approx(
        (0.0, 0.0, 20.0, 10.0), abs=0.01
    )


def test_too_small_arc_radii_are_scaled_up():
    # A radius of 1 cannot span 20 units; the spec says to grow it until it just fits.
    assert _box(parse_path_data("M 0 0 A 1 1 0 0 1 20 0").bounds()) == pytest.approx(
        (0.0, -10.0, 20.0, 10.0), abs=0.01
    )


def test_unterminated_path_data_is_an_error():
    with pytest.raises(SvgImportError):
        parse_path_data("M 0 0 L 10")


# ---------------------------------------------------------------------------------------- transforms


def test_transform_list_applies_left_to_right():
    # translate then scale: the leftmost wraps the rest, so the scaled point is moved afterwards.
    transform = parse_transform("translate(10 0) scale(2)")
    assert transform.apply(Point(5, 0)).x == 20.0


def test_rotate_around_a_point():
    rotated = parse_transform("rotate(90 5 5)").apply(Point(5, 0))
    assert rotated.x == pytest.approx(10.0)
    assert rotated.y == pytest.approx(5.0)


# ------------------------------------------------------------------------------------- visibility


def test_an_element_that_is_neither_filled_nor_stroked_is_skipped():
    # Icon sets ship exactly this as an invisible bounding box; engraving it would burn a rectangle.
    result = import_svg(
        _svg('<path d="M0 0h24v24H0z" fill="none" stroke="none"/><path d="M0 0 L 5 5" stroke="black"/>')
    )
    assert len(list(result.document.objects())) == 1


def test_paint_is_inherited_from_the_root_and_from_groups():
    # The root strokes, so an unadorned child is visible; the one that switches the stroke off is not.
    result = import_svg(
        _svg('<path d="M0 0 L 5 5"/><path d="M0 0 L 5 5" stroke="none"/>', 'fill="none" stroke="black"')
    )
    assert len(list(result.document.objects())) == 1


def test_paint_in_a_style_attribute_counts_too():
    result = import_svg(_svg('<path d="M0 0 L 5 5" style="fill:none;stroke:none"/>'))
    assert list(result.document.objects()) == []


def test_visibility_hidden_is_skipped():
    result = import_svg(_svg('<rect width="1" height="1" visibility="hidden"/>'))
    assert list(result.document.objects()) == []
