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


def list_serial_ports() -> list[str]:
    """Serial ports that look like a LaserPecker.

    Any WCH bridge counts: the LP2 ships a CH340, newer units a CH9102 — the latter shows up as
    ``/dev/ttyACM*`` via cdc_acm because the in-tree ``ch341`` driver does not claim ``1a86:55d4``.
    """
    from serial.tools import list_ports

    ports = [p for p in list_ports.comports() if p.vid == WCH_VENDOR]
    known = [p.device for p in ports if p.pid in WCH_PRODUCTS]
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
    chunk_delay = 0.1

    def __init__(self, address_or_name: str, timeout: float = 20.0) -> None:
        from bleak import BleakClient, BleakScanner

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
            client = BleakClient(target)
            await client.connect()
            for service_uuid, write_uuid, notify_uuid in BLE_PROFILES:
                if any(s.uuid.lower() == service_uuid for s in client.services):
                    await client.start_notify(
                        notify_uuid, lambda _c, data: self._assembler.feed(bytes(data))
                    )
                    return client, write_uuid
            await client.disconnect()
            raise TransportError("device exposes no known LaserPecker service")

        self._client, self._write_uuid = self._run(connect())

    def _run(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def write(self, data: bytes) -> None:
        self._run(self._client.write_gatt_char(self._write_uuid, data, response=False))

    def read_frame(self, timeout: float = 3.0) -> bytes | None:
        return self._assembler.get(timeout)

    def flush_input(self) -> None:
        self._assembler.clear()

    def close(self) -> None:
        try:
            self._run(self._client.disconnect())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)


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
