"""What carries packets to an LMC board: libusb, or a pretend device for development.

The board is a bulk USB endpoint pair, not a serial port, so there is no framing to do and no reader
thread to run — every write is answered by a read of exactly eight bytes. That makes this the simplest
layer in the package, and the mock below correspondingly cheap.
"""

from __future__ import annotations

import struct
from typing import Protocol

from . import protocol as p

VENDOR = 0x9588
PRODUCT = 0x9899
WRITE_ENDPOINT = 0x02
READ_ENDPOINT = 0x88

TIMEOUT_MS = 100


class TransportError(Exception):
    pass


class Transport(Protocol):
    def write(self, packet: bytes) -> None: ...

    def read(self) -> bytes: ...

    def close(self) -> None: ...


class UsbTransport:
    """A real board over libusb.

    Requires ``pyusb`` and permission to talk to the device — on Linux that means a udev rule, otherwise
    claiming the interface fails for anyone but root (``docs/galvo.md``).
    """

    def __init__(self, index: int = 0) -> None:
        try:
            import usb.core
            import usb.util
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise TransportError("pyusb is not installed; a galvo needs it to talk over USB") from error

        self._util = usb.util
        devices = list(usb.core.find(idVendor=VENDOR, idProduct=PRODUCT, find_all=True))
        if not devices:
            raise TransportError("no LMC controller found on USB")
        try:
            self._device = devices[index]
        except IndexError:
            raise TransportError(f"only {len(devices)} controller(s) found, asked for number {index}")

        try:
            self._device.set_configuration()
            self._interface = self._device.get_active_configuration()[(0, 0)]
            if self._device.is_kernel_driver_active(self._interface.bInterfaceNumber):
                self._device.detach_kernel_driver(self._interface.bInterfaceNumber)
            usb.util.claim_interface(self._device, self._interface)
        except NotImplementedError:
            pass  # a platform that does not do kernel drivers; claiming may still have worked
        except Exception as error:
            raise TransportError(f"cannot claim the controller: {error}") from error

    def write(self, packet: bytes) -> None:
        if len(packet) not in (p.PACKET, p.LIST_PACKET):
            raise TransportError(f"the board takes {p.PACKET} or {p.LIST_PACKET} bytes, not {len(packet)}")
        try:
            self._device.write(endpoint=WRITE_ENDPOINT, data=packet, timeout=TIMEOUT_MS)
        except Exception as error:
            raise TransportError(f"write failed: {error}") from error

    def read(self) -> bytes:
        try:
            return bytes(self._device.read(endpoint=READ_ENDPOINT, size_or_buffer=p.REPLY, timeout=TIMEOUT_MS))
        except Exception as error:
            raise TransportError(f"read failed: {error}") from error

    def close(self) -> None:
        try:
            self._util.release_interface(self._device, self._interface)
            self._util.dispose_resources(self._device)
        except Exception:
            pass  # closing a link that is already gone is not an error worth reporting


class MockTransport:
    """A board that only exists in memory, so the whole chain runs without hardware.

    It answers what the driver asks and counts list blocks so a job can finish, which is enough to test
    the packet building and the marking sequence. It is not a simulator: it does not interpret the list
    commands it is given, and it cannot tell a valid job from a nonsensical one.
    """

    #: How many status polls a job stays busy for, once it has been started.
    BUSY_POLLS = 3

    def __init__(self) -> None:
        self.packets: list[bytes] = []
        """Every packet written, in order — single commands and list blocks alike."""

        self.lists: list[bytes] = []
        """Just the list blocks, for tests that care what was queued."""

        self._reply = p.command(0)
        self._executing = False
        self._polls = 0

    # ------------------------------------------------------------------ transport interface

    def write(self, packet: bytes) -> None:
        if len(packet) not in (p.PACKET, p.LIST_PACKET):
            raise TransportError(f"the board takes {p.PACKET} or {p.LIST_PACKET} bytes, not {len(packet)}")
        self.packets.append(packet)
        if len(packet) == p.LIST_PACKET:
            self.lists.append(packet)
            self._reply = p.command(0)
            return
        self._handle(struct.unpack("<6H", packet))

    def read(self) -> bytes:
        return self._reply

    def close(self) -> None:
        self._executing = False

    # ------------------------------------------------------------------ the pretend board

    def _handle(self, packet: tuple[int, ...]) -> None:
        opcode = packet[0]
        if opcode == p.EXECUTE_LIST:
            self._executing = True
            self._polls = 0
        elif opcode in (p.STOP_EXECUTE, p.STOP_LIST, p.RESET):
            self._executing = False
        self._reply = self._status_reply(opcode)

    def _status_reply(self, opcode: int) -> bytes:
        """Four words. The board reports its state in the last word of a version reply, of all places."""
        if opcode != p.GET_VERSION:
            return p.command(0)
        state = p.READY
        if self._executing:
            self._polls += 1
            if self._polls <= self.BUSY_POLLS:
                state |= p.BUSY
            else:
                self._executing = False
        return struct.pack("<4H", 0, 0, 0, state)
