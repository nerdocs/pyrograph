"""Device abstraction: one interface, one profile per machine, one adapter per driver.

`architecture.md` explains why this lives in the application and not in the driver — whoever only wants to
script an LP2 should not inherit an abstraction layer.
"""

from .base import DeviceProfile, DeviceState, DeviceStatus, LaserDevice
from .ezcad2 import GalvoAdapter, profile_for
from .laserpecker import LP2, LaserPeckerDevice

__all__ = [
    "LP2",
    "DeviceProfile",
    "DeviceState",
    "DeviceStatus",
    "GalvoAdapter",
    "LaserDevice",
    "LaserPeckerDevice",
    "profile_for",
]
