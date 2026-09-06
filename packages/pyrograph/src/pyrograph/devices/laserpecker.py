"""The LaserPecker adapter — the only place in the application that speaks LP vocabulary.

Everything device-specific is confined here: the ``px`` byte that selects a resolution, the inverted depth,
the work-mode numbers. Above this module a laser is a laser.
"""

from __future__ import annotations

from laserpecker.device import LP2_AREA, LP2_DPI, LaserPecker
from laserpecker.protocol import WorkMode, print_start
from laserpecker.transport import MockTransport, TransportError

from ..document import Rect
from ..job import RasterJob
from .base import DeviceProfile, DeviceState, DeviceStatus

LP2 = DeviceProfile(
    name="LaserPecker 2",
    width_mm=LP2_AREA[0],
    height_mm=LP2_AREA[1],
    dpi_steps=tuple(sorted(LP2_DPI.values())),
    raster=True,
    paths=False,  # the line/fill command (0x40) is not decoded yet
    rotary=True,
    autofocus=True,
)

#: The device's resolution selector, keyed by DPI — the inverse of the driver's ``LP2_DPI``.
_PX_FOR_DPI = {dpi: px for px, dpi in LP2_DPI.items()}

_STATE = {
    WorkMode.IDLE: DeviceState.IDLE,
    WorkMode.ENGRAVING: DeviceState.RUNNING,
    WorkMode.PREVIEW: DeviceState.RUNNING,
    WorkMode.ERROR: DeviceState.ERROR,
}


class LaserPeckerDevice:
    """Adapts the ``laserpecker`` driver to :class:`~pyrograph.devices.base.LaserDevice`."""

    def __init__(self, driver: LaserPecker | None = None, profile: DeviceProfile = LP2) -> None:
        self.driver = driver or LaserPecker()
        self.profile = profile

    @classmethod
    def mock(cls) -> "LaserPeckerDevice":
        """A device that only exists in memory — for development without hardware."""
        return cls(LaserPecker(MockTransport()))

    def status(self) -> DeviceStatus:
        try:
            raw = self.driver.status()
        except TransportError as error:
            return DeviceStatus(DeviceState.OFFLINE, message=str(error))
        if raw.w_state == 4:  # held — the same value the driver's status uses to mean "not finished"
            return DeviceStatus(DeviceState.PAUSED, progress=raw.rate)
        state = _STATE.get(raw.mode, DeviceState.IDLE)
        message = raw.error_text if state is DeviceState.ERROR else ""
        return DeviceStatus(state, progress=raw.rate, message=message)

    def frame(self, bounds: Rect, power: int = 1) -> None:
        self.driver.preview(bounds.x, bounds.y, bounds.width, bounds.height, power)

    def stop_frame(self) -> None:
        self.driver.preview_stop()

    def run(self, job: RasterJob, name: str = "pyrograph", progress=None) -> None:
        """Upload the raster and start engraving. Returns once the device has taken the job."""
        px = _PX_FOR_DPI.get(job.dpi)
        if px is None:
            raise ValueError(
                f"{self.profile.name} cannot engrave at {job.dpi} dpi; "
                f"use one of {', '.join(str(d) for d in self.profile.dpi_steps)}"
            )
        file_id = self.driver.upload_raster(
            job.raster, job.x_mm, job.y_mm, job.dpi, px, name, progress
        )
        self.driver.send(
            print_start(
                file_id=file_id,
                power=job.params.power,
                depth=job.params.depth,
                nx=job.x_px,
                ny=job.y_px,
                times=job.params.passes,
                speed=job.params.speed_mm_s,
            )
        )

    def pause(self) -> None:
        self.driver.pause(True)

    def resume(self) -> None:
        self.driver.pause(False)

    def abort(self) -> None:
        self.driver.abort()

    def close(self) -> None:
        self.driver.close()
