"""Job creation: millimetres become pixels here, and nowhere else.

The reference numbers come from the verified hardware run: 15 mm at 254 dpi is 150 px, an origin of
40 mm is 400 px.
"""

from pyrograph.document import Document, ImageObject, LaserParams, Layer, Path, PathObject, Transform
from pyrograph.job import build_raster_job


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

    assert (job.raster.width, job.raster.height) == (100, 100)
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
