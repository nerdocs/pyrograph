"""Turn an image into the raster payload the device expects.

The engraver only understands pure black/white, so a grayscale image is Floyd-Steinberg dithered first —
the same approach LDS takes in its ``image_to_dither_stream`` WASM routine. Two payload encodings exist:
one byte per pixel (``0x10``) or one bit per pixel (``0x60``), see ``docs/protocol.md`` §5.3.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Raster:
    """A dithered image ready for upload."""

    width: int
    height: int
    payload: bytes
    packed: bool


def adjust_levels(pixels: list[int], brightness: float = 0.0, contrast: float = 0.0) -> list[int]:
    """Shift brightness and stretch contrast before dithering. Both range from -100 to 100, 0 = unchanged.

    A photograph almost never dithers well as it comes: the dither only decides black or white per pixel,
    so everything depends on where the midtones sit beforehand. The vendor pipeline takes the same two
    knobs (``image_to_dither_stream``); its arithmetic lives in WASM and is not readable, so this is the
    conventional formula — contrast pivots around mid grey, brightness is a plain offset.
    """
    offset = brightness * 2.55
    c = contrast * 2.55
    factor = (259.0 * (c + 255.0)) / (255.0 * (259.0 - c))
    return [min(255, max(0, round(factor * (p - 128) + 128 + offset))) for p in pixels]


def dither(pixels: list[int], width: int, height: int, inverse: bool = False) -> list[int]:
    """Floyd-Steinberg dither a grayscale buffer to 0 (burn) / 255 (skip)."""
    buf = [float(p) for p in pixels]
    for y in range(height):
        for x in range(width):
            i = y * width + x
            old = buf[i]
            new = 255.0 if old >= 128 else 0.0
            buf[i] = new
            err = old - new
            if x + 1 < width:
                buf[i + 1] += err * 7 / 16
            if y + 1 < height:
                if x > 0:
                    buf[i + width - 1] += err * 3 / 16
                buf[i + width] += err * 5 / 16
                if x + 1 < width:
                    buf[i + width + 1] += err * 1 / 16
    out = [0 if v < 128 else 255 for v in buf]
    if inverse:
        out = [255 - v for v in out]
    return out


def pack_bits(mono: list[int], width: int, height: int) -> bytes:
    """One bit per pixel, MSB first, each row padded to a full byte. 0 = burn."""
    stride = (width + 7) // 8
    out = bytearray(stride * height)
    for y in range(height):
        row = y * stride
        for x in range(width):
            if mono[y * width + x]:  # 255 = skip → bit set
                out[row + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def image_to_raster(
    image,
    width_mm: float,
    dpi: float,
    packed: bool = False,
    inverse: bool = False,
    brightness: float = 0.0,
    contrast: float = 0.0,
) -> Raster:
    """Scale a Pillow image to the requested physical width at ``dpi``, adjust levels and dither it.

    The height follows from the image's aspect ratio. Pair this with :func:`raster_to_image` to judge
    ``brightness`` and ``contrast`` on screen before burning them into a workpiece.
    """
    from PIL import Image

    scale = dpi / 25.4  # pixels per millimetre
    target_w = max(1, round(width_mm * scale))
    target_h = max(1, round(target_w * image.height / image.width))
    grey = image.convert("L").resize((target_w, target_h), Image.LANCZOS)
    pixels = list(grey.tobytes())
    if brightness or contrast:
        pixels = adjust_levels(pixels, brightness, contrast)
    mono = dither(pixels, target_w, target_h, inverse)

    if packed:
        payload = pack_bits(mono, target_w, target_h)
    else:
        payload = bytes(mono)
    return Raster(width=target_w, height=target_h, payload=payload, packed=packed)


def raster_to_image(raster: Raster):
    """Turn a raster back into a Pillow image — what the device will actually burn, as a preview."""
    from PIL import Image

    if not raster.packed:
        return Image.frombytes("L", (raster.width, raster.height), raster.payload)
    image = Image.frombytes("1", (raster.width, raster.height), raster.payload)
    return image.convert("L")


def file_id_from_name(name: str) -> int:
    """Derive the 32-bit file ID from a name, mirroring LDS' MD5-based scheme.

    Any stable 32-bit value works; this one just keeps re-uploads of the same name idempotent.
    """
    import hashlib

    return int.from_bytes(hashlib.md5(name.encode("utf-8")).digest()[:4], "big")
