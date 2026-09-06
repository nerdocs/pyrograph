"""What every laser looks like from the application's side.

The point of this layer is that the editor never learns which machine is attached. It reads a
:class:`DeviceProfile` for what the machine can do, sends a :class:`~pyrograph.job.RasterJob`, and reads a
:class:`DeviceStatus` that means the same thing for every device — an LP2 reports mode 6 and a rate byte, a
GRBL board reports something else entirely, and neither vocabulary belongs in the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..document import Rect
from ..job import RasterJob


class DeviceState(Enum):
    """The normalised device state. Every driver maps its own vocabulary onto these five."""

    OFFLINE = "offline"
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass(frozen=True)
class DeviceStatus:
    """Where a device is right now. ``progress`` is a percentage and only meaningful while running."""

    state: DeviceState
    progress: int = 0
    message: str = ""


@dataclass(frozen=True)
class DeviceProfile:
    """What a machine is and what it can do. The GUI reads this instead of hard-coding device knowledge."""

    name: str
    width_mm: float
    height_mm: float
    dpi_steps: tuple[float, ...]
    max_power: int = 100
    raster: bool = True
    """The device runs bitmaps."""

    paths: bool = False
    """The device runs vectors directly, without rasterising them first."""

    rotary: bool = False
    autofocus: bool = False

    def nearest_dpi(self, dpi: float) -> float:
        """The supported resolution closest to ``dpi`` — a layer may ask for anything."""
        return min(self.dpi_steps, key=lambda step: abs(step - dpi))


class LaserDevice(Protocol):
    """The interface an adapter implements. Blocking, like the drivers underneath it.

    ``run`` returns when the job has been handed over, not when it has been burnt — poll :meth:`status`
    for that. Keeping it that way means the caller decides where the waiting happens.
    """

    profile: DeviceProfile

    def status(self) -> DeviceStatus: ...

    def frame(self, bounds: Rect, power: int = 1) -> None:
        """Trace a bounding box with the laser at low power, so the workpiece can be aligned.

        Returns as soon as the device has been told to start. Tracing then repeats until
        :meth:`stop_frame` ends it — the point is to leave the outline visible while the workpiece is
        being moved into place.
        """

    def stop_frame(self) -> None:
        """Stop tracing. Safe to call when nothing is being traced."""

    def run(self, job: RasterJob, name: str = "pyrograph", progress=None) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def abort(self) -> None: ...

    def close(self) -> None: ...
