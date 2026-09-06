"""QR codes and barcodes as document objects.

Both come out as one filled :class:`~pyrograph.document.PathObject`, not as a bitmap: a code is made of
rectangles, and keeping them as geometry means the symbol stays sharp at any size and at any resolution the
layer is later rasterised at.

Neighbouring dark modules are merged into runs, so a symbol is a few dozen rectangles instead of a few
hundred — the even-odd fill in :mod:`pyrograph.job` then has that much less to do.

**Quiet zone.** Neither generator draws one. A code needs light margin around it to be readable — four
module widths for a QR code, ten for a barcode — and on a workpiece that margin is simply unburnt material.
Placing the symbol without that clearance is what makes a scanner fail.
"""

from __future__ import annotations

from .document import Path, PathObject

BARCODE_SYMBOLOGIES = ("code128", "code39", "ean13", "ean8", "isbn13", "upca", "itf")
"""The symbologies offered in the GUI — a subset of what ``python-barcode`` provides."""


def _runs(row: list[bool]) -> list[tuple[int, int]]:
    """Consecutive dark modules of one row, as ``(start, length)``."""
    out: list[tuple[int, int]] = []
    start = None
    for index, dark in enumerate(row):
        if dark and start is None:
            start = index
        elif not dark and start is not None:
            out.append((start, index - start))
            start = None
    if start is not None:
        out.append((start, len(row) - start))
    return out


def _rectangles(rows: list[list[bool]], module_mm: float) -> Path:
    """One rectangle subpath per run of dark modules, in millimetres from the top left corner."""
    segments: list = []
    for y, row in enumerate(rows):
        for start, length in _runs(row):
            box = Path.rect(start * module_mm, y * module_mm, length * module_mm, module_mm)
            segments += box.segments
    return Path(segments)


def qr_code(text: str, size_mm: float = 25.0, error: str = "M") -> PathObject:
    """A QR code of ``size_mm`` edge length, excluding the quiet zone.

    ``error`` is the error correction level (``L``, ``M``, ``Q``, ``H``); higher survives more damage at
    the cost of a denser symbol. Denser means smaller modules, and a module the laser cannot resolve makes
    the code worse, not better.
    """
    import segno

    # make_qr, not make: segno would otherwise pick a Micro QR for short payloads, and not every scanner
    # reads those.
    symbol = segno.make_qr(text, error=error)
    rows = [[bool(module) for module in row] for row in symbol.matrix]
    return PathObject(
        name=f"QR {text[:20]}",
        path=_rectangles(rows, size_mm / len(rows)),
        fill=True,
    )


def barcode(
    text: str, symbology: str = "code128", width_mm: float = 50.0, height_mm: float = 15.0
) -> PathObject:
    """A one-dimensional barcode ``width_mm`` wide and ``height_mm`` tall, without the printed digits.

    ``symbology`` is one of :data:`BARCODE_SYMBOLOGIES`. Each has its own rules about what it can encode —
    EAN-13 wants twelve digits and adds the checksum itself — and a violation raises from the library.
    """
    from barcode import get_barcode_class

    modules = get_barcode_class(symbology)(text).build()[0]
    module_mm = width_mm / len(modules)
    segments: list = []
    for start, length in _runs([character == "1" for character in modules]):
        segments += Path.rect(start * module_mm, 0.0, length * module_mm, height_mm).segments
    return PathObject(name=f"{symbology} {text[:20]}", path=Path(segments), fill=True)


__all__ = ["BARCODE_SYMBOLOGIES", "barcode", "qr_code"]
