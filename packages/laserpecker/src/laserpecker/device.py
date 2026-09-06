"""High-level control of a LaserPecker engraver."""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import protocol as p
from .imaging import Raster, file_id_from_name, image_to_raster
from .transport import SerialTransport, Transport, TransportError, write_bulk

#: DPI steps LP2 supports, mapped to the ``px`` byte of the raster header.
LP2_DPI = {4: 254.0, 3: 338.66666, 2: 508.0}

#: LP2 work area in millimetres.
LP2_AREA = (100.0, 100.0)


@dataclass
class DeviceInfo:
    sw_version: int
    hw_version: int
    name: str | None = None
    mac: str | None = None


class LaserPecker:
    """Blocking control interface.

    ``transport`` defaults to the first CH340 serial port found.
    """

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or SerialTransport()

    # ------------------------------------------------------------------ plumbing

    def request(self, frame: bytes, timeout: float = 3.0, expect_func: int | None = None) -> bytes:
        """Send a frame and wait for the device's reply.

        The device emits unsolicited acknowledgements (a finished upload, a print start), so a reply may be
        preceded by unrelated frames. ``expect_func`` skips those instead of mistaking one for the answer.
        """
        if hasattr(self.transport, "flush_input"):
            self.transport.flush_input()
        self.transport.write(frame)
        deadline = time.monotonic() + timeout
        while True:
            reply = self.transport.read_frame(max(0.1, deadline - time.monotonic()))
            if reply is None:
                raise TransportError("no reply from device")
            if expect_func is None or reply[3] == expect_func:
                return reply
            if time.monotonic() >= deadline:
                raise TransportError("no matching reply from device")

    def send(self, frame: bytes) -> None:
        """Fire and forget — used for preview updates that are not acknowledged."""
        self.transport.write(frame)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "LaserPecker":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ queries

    def status(self) -> p.Status:
        return p.parse_status(self.request(p.query(p.Query.STATUS), expect_func=p.Func.QUERY))

    def info(self) -> DeviceInfo:
        version = p.parse_version(self.request(p.query(p.Query.VERSION)))
        info = DeviceInfo(sw_version=version.sw_version, hw_version=version.hw_version)
        try:
            info.mac = p.parse_mac(self.request(p.query(p.Query.MAC)))
        except (TransportError, p.ProtocolError):
            pass
        try:
            # LP2 firmware 3.16 does not answer this one; short timeout keeps info() responsive.
            info.name = p.parse_name(self.request(p.query(p.Query.NAME), timeout=1.0))
        except (TransportError, p.ProtocolError):
            pass
        return info

    def file_ids(self) -> list[int]:
        return p.parse_file_ids(self.request(p.query(p.Query.FILE_IDS)))

    # ------------------------------------------------------------------ motion

    def stop(self) -> bytes:
        """Leave the current mode (preview, print, …)."""
        return self.request(p.stop())

    def preview(
        self,
        x_mm: float,
        y_mm: float,
        w_mm: float,
        h_mm: float,
        power: int = 1,
    ) -> None:
        """Trace the bounding box so the workpiece can be aligned."""
        self.send(p.preview_rect(x_mm, y_mm, w_mm, h_mm, power))

    def preview_stop(self) -> bytes:
        return self.request(p.preview_stop())

    def focus(self, direction: int, height_mm: float = 0.0) -> bytes:
        """Move the stand — 0 down, 1 up, 2 stop."""
        return self.request(p.focus(direction, height_mm))

    def alarm_off(self) -> None:
        self.send(p.alarm_off())

    # ------------------------------------------------------------------ engraving

    def upload_raster(
        self,
        raster: Raster,
        file_id: int,
        x_mm: float,
        y_mm: float,
        dpi: float,
        px: int,
        name: str = "",
        progress=None,
    ) -> None:
        """Push a dithered image to the device (steps 1–5 of docs/protocol.md §5)."""
        scale = dpi / 25.4
        nx = max(0, int(x_mm * scale))
        ny = max(0, int(y_mm * scale))

        self.request(p.stop())

        reply = self.request(p.open_file_transfer(len(raster.payload)), timeout=60.0)
        if reply[3] != p.Func.FILE or p.parse_file_status(reply) != 1:
            # A 0xFF frame instead of 0x05 means the device is stuck; only a power cycle is
            # known to clear it (docs/protocol.md, "stuck refusing all file transfers").
            raise TransportError(
                f"device refused the file transfer (reply {reply.hex()}); "
                "power-cycle the device and try again"
            )

        header = p.raster_header(
            file_id=file_id,
            width=raster.width,
            height=raster.height,
            nx=nx,
            ny=ny,
            px=px,
            dpi=int(dpi),
            name=name,
            packed=raster.packed,
        )
        self.transport.write(header)
        write_bulk(self.transport, raster.payload, progress)

        reply = self.transport.read_frame(timeout=60.0)
        if reply is None or p.parse_file_status(reply) != 1:
            raise TransportError("device did not acknowledge the upload")

    def engrave_image(
        self,
        image,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        power: int = 30,
        depth: int = 50,
        times: int = 1,
        px: int = 4,
        packed: bool = False,
        name: str = "claude",
        progress=None,
    ) -> int:
        """Dither, upload and start an engraving job. Returns the file ID."""
        dpi = LP2_DPI[px]
        raster = image_to_raster(image, width_mm, dpi, packed=packed)
        file_id = file_id_from_name(name)
        self.upload_raster(raster, file_id, x_mm, y_mm, dpi, px, name, progress)

        scale = dpi / 25.4
        self.send(
            p.print_start(
                file_id=file_id,
                power=power,
                depth=depth,
                nx=max(0, int(x_mm * scale)),
                ny=max(0, int(y_mm * scale)),
                times=times,
            )
        )
        return file_id

    def wait_until_done(self, on_progress=None, poll: float = 1.0) -> p.Status:
        """Poll the status until the job finishes or the device reports an error."""
        while True:
            status = self.status()
            if on_progress:
                on_progress(status)
            if status.mode == p.WorkMode.ERROR:
                raise TransportError(f"device error: {status.error_text}")
            if status.finished:
                return status
            time.sleep(poll)

    def pause(self, paused: bool = True) -> None:
        self.send(p.print_pause(paused))

    def abort(self) -> bytes:
        return self.request(p.stop())
