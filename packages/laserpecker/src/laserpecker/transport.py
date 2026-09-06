"""Transports that carry LaserPecker frames: USB-serial and Bluetooth LE.

Both expose the same blocking interface so the rest of the library — and a Qt GUI later on — never has to
care which link is in use.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Protocol

from .protocol import frame_complete, long_frame_complete

#: WCH USB-serial bridges. LDS filters exactly these two: CH340 and CH9102.
WCH_VENDOR = 0x1A86
WCH_PRODUCTS = {0x7523, 0x55D4}
BAUD_RATE = 460800

# BLE profiles, probed in the order LDS uses.
BLE_PROFILES = [
    (
        "49535343-fe7d-4ae5-8fa9-9fafd205e455",
        "49535343-8841-43f4-a8d4-ecbe34729bb3",
        "49535343-1e4d-4bd9-ba61-23c647249616",
    ),
    (
        "0000fff0-0000-1000-8000-00805f9b34fb",
        "0000fff2-0000-1000-8000-00805f9b34fb",
        "0000fff1-0000-1000-8000-00805f9b34fb",
    ),
    (
        "0000abf0-0000-1000-8000-00805f9b34fb",
        "0000abf3-0000-1000-8000-00805f9b34fb",
        "0000abf4-0000-1000-8000-00805f9b34fb",
    ),
]


class Transport(Protocol):
    mtu: int
    chunk_delay: float

    def write(self, data: bytes) -> None: ...

    def read_frame(self, timeout: float = 3.0) -> bytes | None: ...

    def close(self) -> None: ...


class TransportError(Exception):
    pass


class _FrameAssembler:
    """Collects incoming bytes and hands out complete frames."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._frames: queue.Queue[bytes] = queue.Queue()

    def feed(self, data: bytes) -> None:
        self._buf += data
        while True:
            # Resynchronise on the header if the device sent something unexpected.
            while self._buf and self._buf[0] != 0xAA:
                del self._buf[0]
            size = self._frame_size()
            if size is None:
                return
            self._frames.put(bytes(self._buf[:size]))
            del self._buf[:size]

    def _frame_size(self) -> int | None:
        """Length of the complete frame at the head of the buffer, else None.

        The device answers some commands with several frames back to back, so a frame must be cut
        to its own length instead of handing out whatever the buffer happens to hold.
        """
        if frame_complete(self._buf):
            return self._buf[2] + 3
        if long_frame_complete(self._buf):
            return int.from_bytes(self._buf[2:6], "big") + 6
        return None

    def get(self, timeout: float) -> bytes | None:
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self) -> None:
        self._buf.clear()
        while not self._frames.empty():
            self._frames.get_nowait()


def list_serial_ports(strict: bool = False) -> list[str]:
    """Serial ports that look like a LaserPecker.

    Any WCH bridge counts: the LP2 ships a CH340, newer units a CH9102 — the latter shows up as
    ``/dev/ttyACM*`` via cdc_acm because the in-tree ``ch341`` driver does not claim ``1a86:55d4``.

    ``strict`` drops that fallback and returns only the two product IDs LDS itself filters for. A WCH
    bridge sits in half the hobby electronics ever made, so anything that offers a port to the user
    without being asked — autodetection — has to be sure it found an engraver and not an Arduino.
    """
    from serial.tools import list_ports

    ports = [p for p in list_ports.comports() if p.vid == WCH_VENDOR]
    known = [p.device for p in ports if p.pid in WCH_PRODUCTS]
    if strict:
        return known
    return known or [p.device for p in ports]


class SerialTransport:
    """USB-C connection over the built-in CH340 bridge."""

    mtu = 2048
    chunk_delay = 0.05

    def __init__(self, port: str | None = None, baudrate: int = BAUD_RATE) -> None:
        import serial

        if port is None:
            ports = list_serial_ports()
            if not ports:
                raise TransportError("no LaserPecker serial port found")
            port = ports[0]
        self.port = port
        self._serial = serial.Serial(port, baudrate, timeout=0.05)
        self._assembler = _FrameAssembler()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._serial.read(4096)
            except Exception:
                break
            if data:
                self._assembler.feed(data)

    def write(self, data: bytes) -> None:
        self._serial.write(data)

    def read_frame(self, timeout: float = 3.0) -> bytes | None:
        return self._assembler.get(timeout)

    def flush_input(self) -> None:
        self._assembler.clear()

    def close(self) -> None:
        self._stop.set()
        self._reader.join(timeout=1)
        self._serial.close()


class BleTransport:
    """Bluetooth LE connection.

    ``bleak`` is async; the event loop runs in a background thread so callers keep a blocking API.
    """

    mtu = 179
    """Payload per write. The vendor app uses 179 and the device is known to swallow that much, so it is
    the upper bound here — see :meth:`_negotiated_mtu` for why it can end up smaller."""

    chunk_delay = 0.1

    def __init__(self, address_or_name: str, timeout: float = 20.0) -> None:
        from bleak import BleakClient, BleakScanner

        self._closed = False
        self._assembler = _FrameAssembler()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        async def connect() -> tuple[object, str]:
            target = address_or_name
            if not _looks_like_address(address_or_name):
                device = await BleakScanner.find_device_by_filter(
                    lambda d, _ad: bool(d.name and address_or_name.lower() in d.name.lower()),
                    timeout=timeout,
                )
                if device is None:
                    raise TransportError(f"no BLE device matching {address_or_name!r}")
                target = device
            client = BleakClient(target, timeout=timeout)
            await client.connect()
            for service_uuid, write_uuid, notify_uuid in BLE_PROFILES:
                if any(s.uuid.lower() == service_uuid for s in client.services):
                    await client.start_notify(
                        notify_uuid, lambda _c, data: self._assembler.feed(bytes(data))
                    )
                    return client, write_uuid
            await client.disconnect()
            raise TransportError("device exposes no known LaserPecker service")

        # Scanning alone may take the full timeout, connecting and reading the services comes on top.
        self._client, self._write_uuid = self._run(connect(), timeout=2 * timeout + 10)
        self.mtu = self._negotiated_mtu()

    def _negotiated_mtu(self) -> int:
        """Payload size a single write may carry: the ATT MTU minus its three-byte header.

        A write larger than that is rejected by the stack, and the upload then fails with nothing to
        show for it. BlueZ usually negotiates far more than the 179 bytes the vendor app uses, but not
        always — an adapter that stays at the 23-byte default leaves room for 20. Capped at the class
        default because a bigger chunk than the vendor's has never been tried on a device.
        """
        try:
            return max(20, min(type(self).mtu, self._client.mtu_size - 3))
        except Exception:
            # Backends that do not expose the negotiated MTU; the vendor's size is the safe guess.
            return type(self).mtu

    def _run(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def write(self, data: bytes) -> None:
        self._run(self._client.write_gatt_char(self._write_uuid, data, response=False))

    def read_frame(self, timeout: float = 3.0) -> bytes | None:
        return self._assembler.get(timeout)

    def flush_input(self) -> None:
        self._assembler.clear()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._run(self._client.disconnect())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)

    def __del__(self) -> None:
        # A connection left open keeps the device from advertising, so it cannot be found again
        # until something disconnects it. Close on garbage collection as a safety net.
        try:
            self.close()
        except Exception:
            pass


def scan_ble(timeout: float = 10.0) -> list[tuple[str, str]]:
    """Discover LaserPecker devices over BLE; returns ``(address, name)`` pairs."""
    from bleak import BleakScanner

    async def go():
        devices = await BleakScanner.discover(timeout=timeout)
        return [
            (d.address, d.name)
            for d in devices
            if d.name and ("laserpecker" in d.name.lower() or d.name.startswith(("LP", "LX")))
        ]

    return asyncio.run(go())


def _looks_like_address(value: str) -> bool:
    parts = value.split(":")
    return len(parts) == 6 and all(len(p) == 2 for p in parts)


def write_bulk(transport: Transport, data: bytes, progress=None) -> None:
    """Write raw (unframed) payload in MTU-sized chunks, the way LDS paces uploads."""
    total = len(data)
    for offset in range(0, total, transport.mtu):
        transport.write(data[offset : offset + transport.mtu])
        if progress:
            progress(min(offset + transport.mtu, total), total)
        time.sleep(transport.chunk_delay)


class MockTransport:
    """A device that only exists in memory — for development and tests without hardware.

    It answers the queries the driver actually sends, accepts an upload and then pretends to engrave: every
    status query while a job runs advances ``rate`` until the job reports itself finished. What it is not
    is a firmware simulator; anything the driver does not ask for is answered with a plain acknowledgement.
    """

    mtu = 2048
    chunk_delay = 0.0

    #: Replies captured from an LP2 on firmware 3.16 (``tests/fixtures_lp2.json``).
    VERSION_REPLY = bytes.fromhex("aabb0b00013c01321e8600030117")
    MAC_REPLY = bytes.fromhex("aabb0b00dc0d30aabbcc0005034f")

    def __init__(self, status_ticks: int = 4) -> None:
        from . import protocol as p

        self._p = p
        self._replies: list[bytes] = []
        self._expect_payload = 0
        self._status_ticks = max(1, status_ticks)
        self._mode = p.WorkMode.IDLE
        self._w_state = 0
        self._rate = 0
        self._file_id = 0
        self.files: list[int] = []
        self.uploads: list[bytes] = []
        """Everything that was uploaded as raw payload — header first, then the raster."""

        self.commands: list[bytes] = []
        """Every command frame the device received, in order."""

    # ------------------------------------------------------------------ transport interface

    def write(self, data: bytes) -> None:
        if self._expect_payload:
            take = min(self._expect_payload, len(data))
            self.uploads[-1] += data[:take]
            self._expect_payload -= take
            if not self._expect_payload:
                self._replies.append(self._file_ack())
            data = data[take:]
            if not data:
                return
        while len(data) >= 6 and self._p.frame_complete(data):
            length = data[2]
            self._handle(data[: length + 3])
            data = data[length + 3 :]

    def read_frame(self, timeout: float = 3.0) -> bytes | None:
        return self._replies.pop(0) if self._replies else None

    def flush_input(self) -> None:
        self._replies.clear()

    def close(self) -> None:
        self._replies.clear()

    # ------------------------------------------------------------------ the pretend device

    def _handle(self, frame: bytes) -> None:
        p = self._p
        self.commands.append(frame)
        func = frame[3]
        if func == p.Func.QUERY:
            self._handle_query(frame[4])
        elif func == p.Func.FILE and frame[4] == 1:
            self._expect_payload = int.from_bytes(frame[5:9], "big")
            self.uploads.append(b"")
            self._replies.append(self._file_ack())
        elif func == p.Func.PRINT:
            self._handle_print(frame)
            self._replies.append(p.build_frame(p.Func.PRINT, [(1, 1)]))
        elif func == p.Func.STOP:
            self._mode, self._rate = p.WorkMode.IDLE, 0
            self._replies.append(p.build_frame(p.Func.STOP, [(1, 1)]))
        else:
            self._replies.append(p.build_frame(func, [(1, 1)]))

    def _handle_query(self, state: int) -> None:
        p = self._p
        if state == p.Query.STATUS:
            self._replies.append(self._status())
        elif state == p.Query.VERSION:
            self._replies.append(self.VERSION_REPLY)
        elif state == p.Query.MAC:
            self._replies.append(self.MAC_REPLY)
        elif state == p.Query.FILE_IDS:
            # Count byte, the IDs, then two trailing bytes — the shape the real reply has.
            self._replies.append(
                p.build_frame(
                    p.Func.QUERY,
                    [(len(self.files), 1)] + [(f, 4) for f in self.files] + [(0, 1), (0, 1)],
                )
            )
        # The real LP2 does not answer a name query at all, so neither do we.

    def _handle_print(self, frame: bytes) -> None:
        p = self._p
        state = frame[4]
        if state == p.PrintState.START:
            self._file_id = int.from_bytes(frame[7:11], "big")
            self._mode, self._w_state, self._rate = p.WorkMode.ENGRAVING, 1, 0
        elif state == p.PrintState.HOLD:
            self._w_state = 4
        elif state == p.PrintState.CONTINUE:
            self._w_state = 1

    def _status(self) -> bytes:
        p = self._p
        if self._mode == p.WorkMode.ENGRAVING and self._w_state != 4:
            self._rate = min(100, self._rate + 100 // self._status_ticks)
            if self._rate >= 100:
                self._mode, self._w_state = p.WorkMode.IDLE, 255
                if self._file_id not in self.files:
                    self.files.append(self._file_id)
        data = [(self._mode, 1), (self._w_state, 1), (self._rate, 1)]
        data += [(0, 1)] * 4 + [(self._file_id, 4)] + [(0, 1)] * 10
        return p.build_frame(p.Func.QUERY, data)

    def _file_ack(self) -> bytes:
        return self._p.build_frame(self._p.Func.FILE, [(1, 1), (1, 1), (0, 1)])
