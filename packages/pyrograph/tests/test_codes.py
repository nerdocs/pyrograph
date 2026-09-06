"""QR codes and barcodes: geometry in, burnt area out."""

import pytest
from PIL import Image

from pyrograph.codes import barcode, qr_code
from pyrograph.document import Document, LaserParams, Layer
from pyrograph.job import build_raster_job


def _rendered(obj, dpi: float = 254.0) -> Image.Image:
    document = Document(layers=[Layer(params=LaserParams(dpi=dpi), objects=[obj])])
    job = build_raster_job(document, 0)
    return Image.frombytes("L", (job.raster.width, job.raster.height), bytes(job.raster.payload))


def test_a_qr_code_is_square_and_filled():
    obj = qr_code("https://example.org", size_mm=25.0)
    box = obj.bounds()
    assert obj.fill
    assert box.width == pytest.approx(25.0) and box.height == pytest.approx(25.0)

    pixels = _rendered(obj).tobytes()
    assert set(pixels) == {0, 255}, "a code is burnt or it is not — dithering has nothing to do here"
    assert 0.3 < pixels.count(0) / len(pixels) < 0.7


def test_the_finder_patterns_sit_in_three_corners():
    """A finder pattern is a dark ring around a light ring around a dark core, in three of four corners."""
    import segno

    modules = len(list(segno.make_qr("https://example.org").matrix))
    image = _rendered(qr_code("https://example.org", size_mm=25.0))
    step = image.width / modules

    def module(column: int, row: int) -> int:
        return image.getpixel((int((column + 0.5) * step), int((row + 0.5) * step)))

    for x, y in ((0, 0), (modules - 7, 0), (0, modules - 7)):
        assert module(x, y) == 0, "outer ring"
        assert module(x + 1, y + 1) == 255, "light ring"
        assert module(x + 3, y + 3) == 0, "core"


def test_a_barcode_keeps_its_size_and_alternates():
    obj = barcode("PYRO-1", "code128", width_mm=50.0, height_mm=15.0)
    box = obj.bounds()
    assert box.width == pytest.approx(50.0) and box.height == pytest.approx(15.0)

    image = _rendered(obj)
    middle = [image.getpixel((x, image.height // 2)) for x in range(image.width)]
    assert 0 in middle and 255 in middle
    # Bars run the full height: a column is either bar or gap, never half of each.
    for x in (0, image.width // 3, image.width - 1):
        column = {image.getpixel((x, y)) for y in range(image.height)}
        assert len(column) == 1


def test_an_impossible_payload_is_reported_not_swallowed():
    with pytest.raises(Exception):
        barcode("not-a-number", "ean13")


def test_a_filled_object_is_not_stroked_by_the_layer():
    """Fill and the layer's outline together would fatten every module by a line width."""
    obj = qr_code("A", size_mm=10.0)
    document = Document(layers=[Layer(params=LaserParams(dpi=254.0, line_width_mm=1.0), objects=[obj])])
    job = build_raster_job(document, 0)
    assert job.raster.width == pytest.approx(100, abs=1)  # 10 mm at 254 dpi, no stroke bleeding outwards
