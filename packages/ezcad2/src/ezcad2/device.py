"""The driver: turning polylines into list commands and getting them onto the board.

The awkward part of an LMC board is not its encoding but its buffering. Commands are collected into
blocks of 256 and uploaded whole, and the board starts marking once two blocks are queued — so sending
and marking overlap and there is no moment where the job has been "handed over" and the host is free.
Everything in this module follows from that.

**Nothing here has been run against hardware.** The protocol was read from balor and galvoplotter
(``docs/galvo.md``); the sequences below are what those two agree on, not what a machine confirmed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import protocol as p
from .correction import GRID, read_table
from .transport import MockTransport, Transport, TransportError, UsbTransport


@dataclass(frozen=True)
class MarkParams:
    """How a job burns. Speeds are millimetres per second, delays microseconds, power a percentage."""

    power: float = 50.0
    speed_mm_s: float = 100.0
    travel_mm_s: float = 2000.0
    frequency_khz: float = 30.0
    passes: int = 1

    delay_laser_on: int = 100
    delay_laser_off: int = 100
    delay_polygon: int = 100
    delay_jump: int = 200


@dataclass(frozen=True)
class Lens:
    """What the attached lens does to the coordinate space.

    ``galvos_per_mm`` is the whole calibration in one number and cannot be guessed — it belongs to the
    physical lens. A ``.cor`` file records the one it was calibrated at (:func:`ezcad2.correction.read_scale`).
    """

    galvos_per_mm: float = 500.0
    cor_file: str | Path | None = None

    @property
    def field_mm(self) -> float:
        """How wide the addressable field is. The board's 16 bits have to cover it."""
        return p.MAX / self.galvos_per_mm


class GalvoDevice:
    """An LMC controller. Every method blocks; the concurrency belongs to the caller.

    The one exception is :meth:`light`, which has to keep tracing an outline while the caller moves the
    workpiece — the board will not repeat a list on its own, so a thread here does it.
    """

    LIGHT_PIN = 8
    LASER_PIN = 0

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        source: str = "fiber",
        lens: Lens | None = None,
    ) -> None:
        if source not in ("fiber", "co2"):
            raise ValueError(f"source is 'fiber' or 'co2', not {source!r}")
        self.transport = transport if transport is not None else UsbTransport()
        self.source = source
        self.lens = lens or Lens()

        self._port_bits = 0
        self._blocks = 0
        """List blocks sent since the last reset — the board starts marking once two are queued."""

        self._executing = False
        self._paused = False
        self._light_thread: threading.Thread | None = None
        self._lighting = False
        self._initialised = False

    @classmethod
    def mock(cls, **kwargs) -> "GalvoDevice":
        """A device that only exists in memory — for development without hardware."""
        return cls(MockTransport(), **kwargs)

    # ------------------------------------------------------------------ raw commands

    def _command(self, opcode: int, *args: int) -> tuple[int, int, int, int]:
        self.transport.write(p.command(opcode, *args))
        return p.words(self.transport.read())

    def status(self) -> int:
        """The board's status bits. They ride in the last word of a version reply, oddly enough."""
        return self._command(p.GET_VERSION)[3]

    def is_busy(self) -> bool:
        return bool(self.status() & p.BUSY)

    def is_ready(self) -> bool:
        return bool(self.status() & p.READY)

    def wait_ready(self, timeout: float = 10.0) -> None:
        """Block until the board will take another block, or give up and say so."""
        deadline = time.monotonic() + timeout
        while not self.is_ready():
            if time.monotonic() > deadline:
                raise TransportError("the controller never reported itself ready")
            time.sleep(0.01)

    def wait_idle(self, timeout: float = 3600.0) -> None:
        """Block until the board has finished marking. A long job is a long wait, hence the hour."""
        deadline = time.monotonic() + timeout
        while self.is_busy():
            if time.monotonic() > deadline:
                raise TransportError("the controller is still busy after an hour")
            time.sleep(0.05)

    # ------------------------------------------------------------------ bring-up

    def init(self) -> None:
        """Get the board into a state where it will accept a job. Idempotent."""
        if self._initialised:
            return
        self._command(p.GET_SERIAL_NO)
        self._command(p.GET_VERSION)
        self._command(p.RESET)
        self._write_correction()
        self._command(p.ENABLE_LASER)
        self._command(p.SET_CONTROL_MODE, 0)
        self._command(p.SET_LASER_MODE, 1)
        self._command(p.SET_DELAY_MODE, 1)
        self._command(p.SET_TIMING, 1)
        self._command(p.SET_STANDBY, 2000, 20)
        self._command(p.SET_FIRST_PULSE_KILLER, 200)
        self._command(p.SET_PWM_HALF_PERIOD, 125)
        self._command(p.SET_PWM_PULSE_WIDTH, 125)
        if self.source == "fiber":
            self._command(p.FIBER_SET_MO, 0)  # master oscillator off until we actually mark
        self._command(p.SET_FPK_PARAM_2, 0xFFB, 1, 409, 100)
        self._command(p.ENABLE_Z)
        self._command(p.WRITE_ANALOG_PORT_1, 0x7FF)
        self._initialised = True

    def _write_correction(self) -> None:
        """Upload the lens table, or a blank one if there is no file.

        A blank table is not a correct field — it is the honest fallback when nobody has calibrated the
        machine yet, and it is what EZCad2 does too.
        """
        if self.lens.cor_file is None:
            self._command(p.WRITE_COR_TABLE, 0)
            return
        table = read_table(self.lens.cor_file)
        if len(table) != GRID * GRID:
            raise ValueError(f"a correction table holds {GRID * GRID} points, got {len(table)}")
        self._command(p.WRITE_COR_TABLE, 1)
        for index, (dx, dy) in enumerate(table):
            self._command(p.WRITE_COR_LINE, dx, dy, 0 if index == 0 else 1)

    # ------------------------------------------------------------------ list building

    def _mark_commands(self, polylines, params: MarkParams) -> list[bytes]:
        """Every list command for one pass over ``polylines``, as 12-byte packets.

        Built in full before anything is sent, so the caller can be told how far along it is — the board
        itself only ever reports busy or ready.
        """
        to_galvo = self.lens.galvos_per_mm
        out = [
            p.command(p.LIST_READY_MARK),
            p.command(p.LIST_MARK_SPEED, p.speed(params.speed_mm_s, to_galvo)),
            p.command(p.LIST_JUMP_SPEED, p.speed(params.travel_mm_s, to_galvo)),
            p.command(p.LIST_MARK_POWER_RATIO, p.power(params.power)),
            p.command(p.LIST_QSWITCH_PERIOD, p.frequency(params.frequency_khz)),
            p.command(p.LIST_LASER_ON_DELAY, params.delay_laser_on),
            p.command(p.LIST_LASER_OFF_DELAY, params.delay_laser_off),
            p.command(p.LIST_POLYGON_DELAY, params.delay_polygon),
            p.command(p.LIST_JUMP_DELAY, params.delay_jump),
        ]
        if self.source == "fiber":
            out.append(p.command(p.LIST_FIBER_OPEN_MO, 1))
        for line in polylines:
            if len(line) < 2:
                continue  # a single point is not a stroke; dwelling on it is a different command
            first, *rest = line
            out.append(p.command(p.LIST_JUMP_TO, *self._point(first)))
            for point in rest:
                out.append(p.command(p.LIST_MARK_TO, *self._point(point)))
        if self.source == "fiber":
            out.append(p.command(p.LIST_FIBER_OPEN_MO, 0))
        out.append(p.command(p.LIST_END_OF_LIST))
        return out

    def _point(self, point) -> tuple[int, int]:
        """A point in millimetres from the field centre to device coordinates."""
        per_mm = self.lens.galvos_per_mm
        return p.galvos(point[0], per_mm), p.galvos(point[1], per_mm)

    def _send(self, commands: list[bytes], progress=None) -> None:
        """Upload the commands in blocks, starting the board once it has enough to chew on.

        Marking overlaps with sending from the third block onward, so ``progress`` counts blocks handed
        over, which is as close to a percentage as this hardware gets.
        """
        blocks = [
            commands[i : i + p.COMMANDS_PER_LIST] for i in range(0, len(commands), p.COMMANDS_PER_LIST)
        ]
        for done, block in enumerate(blocks, start=1):
            if self._paused:
                self.wait_idle()
            self.wait_ready()
            padding = b"".join(p.command(p.LIST_END_OF_LIST) for _ in range(p.COMMANDS_PER_LIST - len(block)))
            self.transport.write(b"".join(block) + padding)
            self._command(p.SET_END_OF_LIST, 0)
            self._blocks += 1
            if self._blocks > 2 and not self._executing:
                self._command(p.EXECUTE_LIST)
                self._executing = True
            if progress is not None:
                progress(done, len(blocks))
        if not self._executing:
            # A job small enough to fit in one or two blocks never tripped the threshold above.
            self._command(p.EXECUTE_LIST)
            self._executing = True

    # ------------------------------------------------------------------ jobs

    def mark(self, polylines, params: MarkParams | None = None, progress=None) -> None:
        """Burn ``polylines`` — millimetres, relative to the centre of the field.

        Returns when the job is done, not when it has been sent: on this hardware those are the same
        thing. ``progress`` is called with ``(blocks_sent, blocks_total)``.
        """
        params = params or MarkParams()
        self.init()
        self._command(p.RESET_LIST)
        self._blocks = 0
        self._executing = False
        self.port_on(self.LASER_PIN)
        if self.source == "fiber":
            self._command(p.FIBER_SET_MO, 1)
        try:
            commands = self._mark_commands(polylines, params)
            for _ in range(max(1, params.passes)):
                self._send(commands, progress)
                self.wait_idle()
        finally:
            if self.source == "fiber":
                self._command(p.FIBER_SET_MO, 0)
            self.port_off(self.LASER_PIN)
            self._executing = False

    def light(self, polylines) -> None:
        """Trace an outline with the red pointer until :meth:`stop_light`, so a workpiece can be aligned.

        Returns as soon as the tracing has started. The board runs a list once and stops, so the repeat
        happens here — this is the only thread in the package.
        """
        self.stop_light()
        self.init()
        self._lighting = True
        self._light_thread = threading.Thread(target=self._light_loop, args=(list(polylines),), daemon=True)
        self._light_thread.start()

    def _light_loop(self, polylines) -> None:
        travel = p.speed(2000.0, self.lens.galvos_per_mm)
        self.port_off(self.LASER_PIN)
        self.port_on(self.LIGHT_PIN)
        try:
            while self._lighting:
                self._command(p.RESET_LIST)
                self._blocks = 0
                self._executing = False
                commands = [p.command(p.LIST_READY_MARK), p.command(p.LIST_JUMP_SPEED, travel)]
                for line in polylines:
                    for point in line:
                        commands.append(p.command(p.LIST_JUMP_TO, *self._point(point)))
                commands.append(p.command(p.LIST_END_OF_LIST))
                self._send(commands)
                self.wait_idle()
        except TransportError:
            pass  # the link died while tracing; stop quietly rather than raise on a daemon thread
        finally:
            self.port_off(self.LIGHT_PIN)

    def stop_light(self) -> None:
        """Stop tracing. Safe to call when nothing is being traced."""
        self._lighting = False
        if self._light_thread is not None:
            self._light_thread.join(timeout=2.0)
            self._light_thread = None

    # ------------------------------------------------------------------ control

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self, paused: bool = True) -> None:
        """Hold before the next block. The board has no pause of its own, so this is the only place.

        A job already inside the board finishes first — up to two blocks' worth of marking.
        """
        self._paused = paused

    def abort(self) -> None:
        self._lighting = False
        self._paused = False
        self._command(p.STOP_EXECUTE)
        self._command(p.STOP_LIST)
        self._executing = False
        self._blocks = 0

    def port_on(self, bit: int) -> None:
        self._port_bits |= 1 << bit
        self._command(p.WRITE_PORT, self._port_bits)

    def port_off(self, bit: int) -> None:
        self._port_bits &= ~(1 << bit)
        self._command(p.WRITE_PORT, self._port_bits)

    def goto(self, x_mm: float, y_mm: float) -> None:
        """Point the galvos somewhere without firing."""
        self._command(p.GOTO_XY, *self._point((x_mm, y_mm)))

    def mark_time(self) -> int:
        """How long the last list took, in the board's own units. Always queried with a 3."""
        return self._command(p.GET_MARK_TIME, 3)[1]

    def close(self) -> None:
        self.stop_light()
        try:
            if self.source == "fiber":
                self._command(p.FIBER_SET_MO, 0)
        except TransportError:
            pass  # the link is going away anyway
        self.transport.close()
