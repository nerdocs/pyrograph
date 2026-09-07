"""The galvo adapter — the only place in the application that speaks LMC vocabulary.

Everything device-specific is confined here: the field centred origin, the flipped Y axis, the fact that
this machine reports busy or ready and never a percentage. Above this module a laser is a laser.

The driver underneath has never run against hardware (``docs/galvo.md``), and neither has this.
"""

from __future__ import annotations

from ezcad2 import GalvoDevice, Lens, MarkParams, MockTransport, TransportError
from ezcad2 import protocol as lmc

from ..document import Point, Rect
from ..job import VectorJob
from .base import DeviceProfile, DeviceState, DeviceStatus


def profile_for(lens: Lens, name: str = "Galvo (EZCad2)") -> DeviceProfile:
    """What a galvo with this lens can do. The field follows from the lens, so it is not a constant."""
    field = lens.field_mm
    return DeviceProfile(
        name=name,
        width_mm=field,
        height_mm=field,
        dpi_steps=(),  # a vector device has no resolution steps; see DeviceProfile.nearest_dpi
        raster=False,  # no raster format exists on this hardware
        paths=True,
        rotary=False,
        autofocus=False,
        streams=True,  # the board marks while the list is still arriving
    )


class GalvoAdapter:
    """Adapts the ``ezcad2`` driver to :class:`~pyrograph.devices.base.LaserDevice`."""

    def __init__(
        self,
        driver: GalvoDevice | None = None,
        profile: DeviceProfile | None = None,
    ) -> None:
        self.driver = driver or GalvoDevice()
        self.profile = profile or profile_for(self.driver.lens)

    @classmethod
    def mock(cls, **kwargs) -> "GalvoAdapter":
        """A device that only exists in memory — for development without hardware."""
        return cls(GalvoDevice(MockTransport(), **kwargs))

    # ------------------------------------------------------------------ coordinates

    def _to_field(self, points, origin: Point) -> list[tuple[float, float]]:
        """Document millimetres to millimetres from the centre of the field.

        Two things change. The origin moves, because a galvo's zero is the middle of its field and a
        document's is a corner — the job is centred on the field, which is also where a workpiece gets
        put. And Y flips: the document counts downwards like SVG, the machine upwards.
        """
        return [(point.x - origin.x, -(point.y - origin.y)) for point in points]

    def _centre_of(self, bounds: Rect) -> Point:
        return Point(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)

    def _fits(self, bounds: Rect) -> bool:
        field = self.driver.lens.field_mm
        return bounds.width <= field and bounds.height <= field

    # ------------------------------------------------------------------ device interface

    def status(self) -> DeviceStatus:
        try:
            bits = self.driver.status()
        except TransportError as error:
            return DeviceStatus(DeviceState.OFFLINE, message=str(error))
        if self.driver.paused:
            return DeviceStatus(DeviceState.PAUSED, message="held between blocks")
        if bits & lmc.BUSY:
            # No percentage exists: the board answers busy or ready and counts nothing in between.
            return DeviceStatus(DeviceState.RUNNING, message="marking")
        return DeviceStatus(DeviceState.IDLE)

    def frame(self, bounds: Rect, power: int = 1) -> None:
        """Trace the bounding box with the red pointer. ``power`` is ignored — the pointer has none."""
        centre = self._centre_of(bounds)
        corners = [
            Point(bounds.x, bounds.y),
            Point(bounds.x + bounds.width, bounds.y),
            Point(bounds.x + bounds.width, bounds.y + bounds.height),
            Point(bounds.x, bounds.y + bounds.height),
            Point(bounds.x, bounds.y),
        ]
        self.driver.light([self._to_field(corners, centre)])

    def stop_frame(self) -> None:
        self.driver.stop_light()

    def run(self, job: VectorJob, name: str = "pyrograph", progress=None) -> None:
        """Mark the job. Returns when it is finished — this machine has no hand-over stage.

        ``name`` is unused: an LMC board stores nothing and has no notion of a job name.
        """
        if not isinstance(job, VectorJob):
            raise TypeError(
                f"{self.profile.name} runs vectors, not {type(job).__name__} — build_vector_job() makes one"
            )
        if not self._fits(job.bounds):
            field = self.driver.lens.field_mm
            raise ValueError(
                f"the job is {job.bounds.width:.1f}x{job.bounds.height:.1f} mm and the field is "
                f"{field:.1f} mm across; a bigger lens or a smaller drawing"
            )
        centre = self._centre_of(job.bounds)
        polylines = [self._to_field(line, centre) for line in job.polylines]
        self.driver.mark(polylines, self._params(job), progress=progress)

    def _params(self, job: VectorJob) -> MarkParams:
        """The layer's parameters in the driver's vocabulary.

        ``LaserParams`` was shaped around the LP2, so two of its fields have no counterpart here: depth is
        an LP-specific burn depth, and dpi means nothing to a vector device.
        """
        return MarkParams(
            power=float(job.params.power),
            speed_mm_s=float(job.params.speed_mm_s),
            passes=max(1, int(job.params.passes)),
        )

    def pause(self) -> None:
        self.driver.pause(True)

    def resume(self) -> None:
        self.driver.pause(False)

    def abort(self) -> None:
        self.driver.abort()

    def close(self) -> None:
        self.driver.close()
