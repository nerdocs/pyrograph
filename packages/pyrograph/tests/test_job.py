"""Job creation: millimetres become pixels here, and nowhere else.

The reference numbers come from the verified hardware run: 15 mm at 254 dpi is 150 px, an origin of
40 mm is 400 px.
"""

from pyrograph.document import (
    Document,
    CubicTo,
    ImageObject,
    LaserParams,
    Layer,
    LineTo,
    MoveTo,
    Path,
    PathObject,
    Point,
    Transform,
)
from pyrograph.job import build_raster_job, build_vector_job


def test_raster_size_and_origin_follow_the_layer_dpi(png_bytes):
    image = ImageObject(
        data=png_bytes, width_mm=15.0, height_mm=15.0, transform=Transform.translate(40.0, 40.0)
    )
    document = Document(layers=[Layer(params=LaserParams(dpi=254.0), objects=[image])])

    job = build_raster_job(document, 0)

    assert (job.raster.width, job.raster.height) == (150, 150)
    assert (job.x_mm, job.y_mm) == (40.0, 40.0)
    assert (job.x_px, job.y_px) == (400, 400)


def test_a_higher_dpi_produces_a_bigger_raster(png_bytes):
    image = ImageObject(data=png_bytes, width_mm=15.0, height_mm=15.0)
    document = Document(layers=[Layer(params=LaserParams(dpi=508.0), objects=[image])])

    job = build_raster_job(document, 0)

    assert (job.raster.width, job.raster.height) == (300, 300)
    assert job.dpi == 508.0


def test_the_layer_parameters_ride_along(png_bytes):
    params = LaserParams(power=42, depth=7, passes=3, speed_mm_s=120, dpi=254.0)
    image = ImageObject(data=png_bytes, width_mm=10.0, height_mm=10.0)
    document = Document(layers=[Layer(params=params, objects=[image])])

    assert build_raster_job(document, 0).params == params


def test_packed_output_is_one_bit_per_pixel(png_bytes):
    image = ImageObject(data=png_bytes, width_mm=10.0, height_mm=10.0)
    document = Document(layers=[Layer(objects=[image])])

    plain = build_raster_job(document, 0)
    packed = build_raster_job(document, 0, packed=True)

    assert len(plain.raster.payload) == 100 * 100
    assert len(packed.raster.payload) == ((100 + 7) // 8) * 100
    assert packed.raster.packed


def test_a_path_is_stroked_into_the_raster():
    document = Document(
        layers=[Layer(params=LaserParams(dpi=254.0), objects=[PathObject(path=Path.rect(0, 0, 10, 10))])]
    )
    job = build_raster_job(document, 0)

    # 10 mm of geometry plus half the 0.1 mm stroke on each side — the ink, not the path.
    assert (job.raster.width, job.raster.height) == (101, 101)
    assert any(value == 0 for value in job.raster.payload)


def test_an_empty_layer_produces_no_job():
    assert build_raster_job(Document(), 0) is None


def test_the_line_width_decides_how_much_actually_burns():
    # A hairline deposits far less energy than a wide stroke — on paper the difference is visible or not.
    def burnt(line_width_mm: float) -> int:
        document = Document(
            layers=[
                Layer(
                    params=LaserParams(dpi=254.0, line_width_mm=line_width_mm),
                    objects=[PathObject(path=Path.rect(0, 0, 10, 10))],
                )
            ]
        )
        return build_raster_job(document, 0).raster.payload.count(0)

    assert burnt(0.3) > 2 * burnt(0.1)


def test_a_line_width_below_one_pixel_still_draws():
    document = Document(
        layers=[
            Layer(
                params=LaserParams(dpi=254.0, line_width_mm=0.001),
                objects=[PathObject(path=Path.rect(0, 0, 10, 10))],
            )
        ]
    )
    assert build_raster_job(document, 0).raster.payload.count(0) > 0


def test_an_objects_own_stroke_width_beats_the_layer():
    def burnt(stroke_width_mm):
        document = Document(
            layers=[
                Layer(
                    params=LaserParams(dpi=254.0, line_width_mm=0.1),
                    objects=[PathObject(path=Path.rect(0, 0, 10, 10), stroke_width_mm=stroke_width_mm)],
                )
            ]
        )
        return build_raster_job(document, 0).raster.payload.count(0)

    assert burnt(0.5) > burnt(None)


def test_a_zero_length_segment_burns_a_dot():
    # SVG icon sets draw a dot this way; it exists only because the cap is round.
    dot = PathObject(path=Path([MoveTo(Point(5, 5)), LineTo(Point(5.01, 5))]), stroke_width_mm=1.0)
    document = Document(layers=[Layer(params=LaserParams(dpi=254.0), objects=[dot])])

    job = build_raster_job(document, 0)
    assert job.raster.payload.count(0) > 20  # a 1 mm dot at 254 dpi is roughly 10 px across


def test_a_vector_job_keeps_the_outlines_instead_of_pixels():
    """A galvo has no raster format; the paths themselves are what it runs."""
    square = PathObject(
        path=Path([MoveTo(Point(0, 0)), LineTo(Point(10, 0)), LineTo(Point(10, 10))])
    )
    document = Document(layers=[Layer(objects=[square])])

    job = build_vector_job(document, 0)

    assert len(job.polylines) == 1
    assert [(p.x, p.y) for p in job.polylines[0]] == [(0, 0), (10, 0), (10, 10)]
    assert (job.bounds.width, job.bounds.height) == (10, 10)


def test_a_vector_job_flattens_curves():
    """A galvo moves in straight segments, so the curve has to be gone before the driver sees it."""
    curve = PathObject(path=Path([MoveTo(Point(0, 0)), CubicTo(Point(0, 5), Point(5, 5), Point(5, 0))]))
    document = Document(layers=[Layer(objects=[curve])])

    job = build_vector_job(document, 0, steps=8)

    assert len(job.polylines[0]) == 9, "one start point plus a point per step"


def test_a_vector_job_reports_what_it_cannot_express(png_bytes):
    """A bitmap has no outline to follow — dropping it in silence would burn less than was asked."""
    document = Document(
        layers=[
            Layer(
                objects=[
                    ImageObject(data=png_bytes, width_mm=10.0, height_mm=10.0, name="photo"),
                    PathObject(path=Path.rect(0, 0, 5, 5), name="frame"),
                ]
            )
        ]
    )

    job = build_vector_job(document, 0)

    assert any("photo" in note and "bitmap" in note for note in job.skipped)
    assert job.polylines, "the path still made it into the job"


def test_a_filled_shape_is_hatched():
    """A vector machine cannot darken an area, so the inside has to be swept with lines."""
    document = Document(
        layers=[
            Layer(
                params=LaserParams(hatch_mm=1.0),
                objects=[PathObject(path=Path.rect(0, 0, 10, 10), fill=True)],
            )
        ]
    )

    job = build_vector_job(document, 0)

    assert len(job.polylines) >= 9, "a 10 mm square at 1 mm spacing needs about ten passes"
    assert not job.skipped
    for line in job.polylines:
        assert len(line) == 2, "a hatch line runs straight across"


def test_a_hatch_spacing_of_zero_says_the_fill_was_left_out():
    """Switching hatching off is allowed, but the shape then comes out hollow and that has to be said."""
    document = Document(
        layers=[
            Layer(
                params=LaserParams(hatch_mm=0.0),
                objects=[PathObject(path=Path.rect(0, 0, 10, 10), fill=True, name="patch")],
            )
        ]
    )

    job = build_vector_job(document, 0)

    assert any("patch" in note and "fill" in note for note in job.skipped)


def test_a_filled_shape_without_a_stroke_is_not_outlined():
    """The same rule the rasteriser follows: outlining a code would fatten every module."""
    filled = Document(
        layers=[
            Layer(
                params=LaserParams(hatch_mm=2.0),
                objects=[PathObject(path=Path.rect(0, 0, 10, 10), fill=True)],
            )
        ]
    )
    outlined = Document(
        layers=[
            Layer(
                params=LaserParams(hatch_mm=2.0),
                objects=[PathObject(path=Path.rect(0, 0, 10, 10), fill=True, stroke_width_mm=0.2)],
            )
        ]
    )

    assert all(len(line) == 2 for line in build_vector_job(filled, 0).polylines)
    assert any(len(line) > 2 for line in build_vector_job(outlined, 0).polylines), "the outline is missing"


def test_a_layer_with_nothing_vectorial_makes_no_job(png_bytes):
    document = Document(
        layers=[Layer(objects=[ImageObject(data=png_bytes, width_mm=10.0, height_mm=10.0)])]
    )

    assert build_vector_job(document, 0) is None
