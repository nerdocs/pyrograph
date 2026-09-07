"""What every laser looks like from the application's side.

The point of this layer is that the editor never learns which machine is attached. It reads a
:class:`DeviceProfile` for what the machine can do, sends a :class:`~pyrograph.job.RasterJob`, and reads a
:class:`DeviceStatus` that means the same thing for every device — an LP2 reports mode 6 and a rate byte, a
GRBL board reports something else entirely, and neither vocabulary belongs in the GUI.

Two rules keep that promise from quietly becoming "whatever the LP2 does". The application asks the
profile what a machine *is* instead of assuming, and a driver that cannot answer something says so —
:attr:`DeviceStatus.progress` is ``None`` where a percentage does not exist, rather than a zero that
reads like one. Adding a second kind of machine should mean writing an adapter, not editing the GUI.
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
    """Where a device is right now — a normalised state plus whatever the machine calls it.

    ``state`` is the same five words for every device; ``message`` is that device's own word for the
    sub-state and belongs on screen next to it, not just when something went wrong: "held", "door open",
    "cover", an error text. The GUI prints it verbatim and never branches on it.

    ``progress`` is a percentage, and ``None`` when the machine cannot say. That is not a failure — a
    galvo controller reports busy or ready and nothing in between. A caller that needs a number to show
    must handle the absence of one rather than reading it as zero.
    """

    state: DeviceState
    progress: int | None = None
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

    streams: bool = False
    """The device has no hand-over stage — sending the job *is* running it.

    An LP2 uploads a raster, then starts it, so there is a moment where the job belongs to the machine
    and :meth:`LaserDevice.run` can return while it burns. A galvo controller has no such moment: it
    executes the command list while the list is still being sent. For those devices ``run`` returns only
    when the job is over, and polling :meth:`LaserDevice.status` afterwards would just find an idle
    machine — so the caller must not wait for one.
    """

    def nearest_dpi(self, dpi: float) -> float:
        """The supported resolution closest to ``dpi`` — a layer may ask for anything.

        A device that runs vectors has no resolution steps to snap to, so it takes the layer's own value
        unchanged rather than pretending to have an opinion about it.
        """
        if not self.dpi_steps:
            return dpi
        return min(self.dpi_steps, key=lambda step: abs(step - dpi))


class LaserDevice(Protocol):
    """The interface an adapter implements. Every method blocks, like the drivers underneath it.

    Blocking here means synchronous, not that anything freezes: the caller already runs this on a thread
    of its own, and the transports keep their own reader threads. Putting the concurrency above and below
    this layer, never inside it, is what keeps an adapter readable.

    ``run`` returns when the device has taken the job over — which for a machine with
    :attr:`DeviceProfile.streams` set is only once the job is finished, because such a machine has no
    earlier moment to return at. Whether to then poll :meth:`status` until the burn ends is therefore not
    the caller's guess to make; it reads ``streams`` and does the one or the other.
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
