"""Layers and their laser parameters.

Parameters live on the layer, not on the object — the same split LightBurn and LaserPecker's own software
use. An object inherits the settings of the layer it sits in, and moving it to another layer is how you
change how it burns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .objects import DocumentObject


@dataclass
class LaserParams:
    """What the laser does with a layer. Device-independent; the driver maps it onto its own encoding."""

    power: int = 60
    """Laser power, 1..100 %."""

    depth: int = 10
    """Burn depth, 1..100. The LP2 inverts this on the wire; that is the driver's business, not ours."""

    passes: int = 1
    """How often the job is repeated."""

    speed_mm_s: int = 0
    """Engraving speed in mm/s. 0 means "leave it to the device"."""

    dpi: float = 254.0
    """Resolution the layer is rasterised at when the job is built."""

    line_width_mm: float = 0.1
    """How wide a path is stroked when it is rasterised.

    A hairline burns much fainter than a filled area: neighbouring rows of a solid patch reinforce each
    other, a single-pixel line gets exactly one pass. Measured on paper at power 30 — a 0.1 mm line is
    barely visible where a filled square is solid black.
    """

    hatch_mm: float = 0.1
    """How far apart the lines are that fill a solid area on a vector machine.

    A galvo cannot darken an area, only sweep the spot across it, so a filled shape is burnt as parallel
    lines this far apart (:mod:`pyrograph.hatch`). Roughly the width the spot burns is what closes the
    area without going over it twice: wider leaves stripes, narrower costs time and heat. A raster device
    ignores this — it fills by darkening pixels.
    """

    hatch_angle: float = 0.0
    """Which way those lines run, in degrees. Zero is horizontal."""


@dataclass
class Layer:
    """A named group of objects sharing one set of laser parameters."""

    name: str = "Layer"
    params: LaserParams = field(default_factory=LaserParams)
    visible: bool = True
    objects: list[DocumentObject] = field(default_factory=list)
