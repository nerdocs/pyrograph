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


@dataclass
class Layer:
    """A named group of objects sharing one set of laser parameters."""

    name: str = "Layer"
    params: LaserParams = field(default_factory=LaserParams)
    visible: bool = True
    objects: list[DocumentObject] = field(default_factory=list)
