"""Shared fixtures for the document model tests."""

import glob
import io

import pytest

from pyrograph.document import ImageObject, Path, PathObject, Transform


@pytest.fixture
def font_path() -> str:
    """A TrueType file to render text with. Skips the test when the system has none."""
    for pattern in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/**/DejaVuSans.ttf",
        "/usr/share/fonts/**/*.ttf",
    ):
        found = sorted(glob.glob(pattern, recursive=True))
        if found:
            return found[0]
    pytest.skip("no TrueType font found on this system")


@pytest.fixture
def png_bytes() -> bytes:
    """A 4×2 greyscale PNG: left half black, right half white."""
    from PIL import Image

    image = Image.new("L", (4, 2), 255)
    for y in range(2):
        for x in range(2):
            image.putpixel((x, y), 0)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def sample_objects(png_bytes) -> list:
    return [
        PathObject(id="opath", name="frame", path=Path.rect(0, 0, 10, 5)),
        ImageObject(
            id="oimage",
            data=png_bytes,
            width_mm=20.0,
            height_mm=10.0,
            transform=Transform.translate(30.0, 5.0),
        ),
    ]
