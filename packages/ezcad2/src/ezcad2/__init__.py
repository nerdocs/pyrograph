"""Driver for BJJCZ LMC galvo controllers — the boards EZCad2 drives.

Fiber and CO2 galvo markers with an LMC board (LMCV4 and relatives), over USB. **EZCad3 and BSL boards
speak a different protocol and are not supported**; see ``docs/galvo.md``.

Nothing in this package has been verified against hardware.
"""

from .calibration import Calibration, read_calibration
from .correction import read_scale, read_table
from .device import GalvoDevice, Lens, MarkParams
from .transport import MockTransport, TransportError, UsbTransport, boards_present

__all__ = [
    "Calibration",
    "GalvoDevice",
    "Lens",
    "MarkParams",
    "read_calibration",
    "MockTransport",
    "TransportError",
    "UsbTransport",
    "boards_present",
    "read_scale",
    "read_table",
]
