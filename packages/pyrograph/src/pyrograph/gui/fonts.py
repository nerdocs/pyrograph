"""Finding the file behind a font family.

:class:`~pyrograph.document.TextObject` converts text to outlines with fontTools and therefore needs a font
*file*. Qt only ever hands out family names — neither ``QFontDatabase`` nor ``QRawFont`` exposes a path —
so the mapping is built here: scan the platform's font directories once and read each file's family name.

The scan is lazy and cached: it costs about a second on a full desktop system, and nothing at all until
somebody uses the text tool.
"""

from __future__ import annotations

import functools
import glob
import os

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont, QFontInfo

_SUFFIXES = ("ttf", "otf", "ttc")

_REGULAR = ("regular", "book", "normal", "roman", "")
"""What a font calls its upright basic cut. Not every family says "Regular" — DejaVu says "Book"."""

_STYLED = ("bold", "italic", "oblique", "light", "thin", "black", "condensed", "narrow", "semi", "extra")


def _rank(style: str) -> int:
    """Lower is more "the plain cut of this family"."""
    lowered = style.strip().lower()
    if lowered in _REGULAR:
        return 0
    return 2 if any(word in lowered for word in _STYLED) else 1


@functools.cache
def families() -> dict[str, str]:
    """Every installed family, mapped to the file holding its regular cut.

    A family usually spans several files (regular, bold, italic). Only the upright regular one is kept:
    text objects have no style attribute, and picking the bold file for "DejaVu Sans" would be a surprise.
    """
    from fontTools.ttLib import TTFont

    found: dict[str, tuple[int, str]] = {}
    for directory in QStandardPaths.standardLocations(QStandardPaths.StandardLocation.FontsLocation):
        for suffix in _SUFFIXES:
            for path in glob.iglob(os.path.join(directory, "**", f"*.{suffix}"), recursive=True):
                try:
                    font = TTFont(path, fontNumber=0, lazy=True)
                    name = font["name"]
                    family = name.getDebugName(1)
                    style = name.getDebugName(2) or ""
                    font.close()
                except Exception:  # a font directory collects broken and exotic files over the years
                    continue
                if not family:
                    continue
                rank = _rank(style)
                if family not in found or rank < found[family][0]:
                    found[family] = (rank, path)
    return {family: path for family, (_, path) in sorted(found.items())}


def path_for(family: str) -> str | None:
    """The font file for ``family``, or ``None`` if the system has no file we could read.

    Qt hands out alias families — a font selector starts on "Sans Serif", which is not a font but a
    promise. Those are resolved through Qt's own matching, otherwise the text tool refuses to work on
    exactly the family it offered by default.
    """
    table = families()
    if family in table:
        return table[family]
    return table.get(QFontInfo(QFont(family)).family())
