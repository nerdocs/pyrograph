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
CLONE_PRODUCT = 0x9980
"""Cloned boards announce themselves with a different product ID until their FPGA has been loaded.

They are common on cheap machines. This driver cannot do the loading — it needs either the vendor's
firmware blobs or a ``.sys`` driver file off a Windows install — but it finds such a board and says so,
which beats reporting that nothing is plugged in. MeerK40t's ``clone_init`` does the loading; a board it
has already initialised in this power cycle answers here normally.
"""

PRODUCTS = {PRODUCT: "LMC controller", CLONE_PRODUCT: "cloned board"}

WRITE_ENDPOINT = 0x02
READ_ENDPOINT = 0x88

TIMEOUT_MS = 100


class TransportError(Exception):
    pass


def find_boards() -> list[int]:
    """The product ID of every galvo controller plugged in, cloned ones included.

    Reads the operating system's USB device table and touches no board — nothing here claims an interface
    or sends a byte, so it is safe to call while one is marking. Returns an empty list rather than raising
    when pyusb is missing or the platform will not enumerate: "none found" is the useful answer either way.
    """
    try:
        import usb.core
    except ImportError:
        return []
    found = []
    for product in PRODUCTS:
        try:
            found += [product] * len(
                list(usb.core.find(idVendor=VENDOR, idProduct=product, find_all=True))
            )
        except Exception:
            continue
    return found


def boards_present() -> int:
    """How many galvo controllers are plugged in."""
    return len(find_boards())


class Transport(Protocol):
    needs_firmware: bool
    """Whether this is a cloned board still waiting for its FPGA image."""

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
        devices = []
        for product in PRODUCTS:
            devices += [
                (product, device)
                for device in usb.core.find(idVendor=VENDOR, idProduct=product, find_all=True)
            ]
        if not devices:
            raise TransportError("no galvo controller found on USB")
        try:
            product, self._device = devices[index]
        except IndexError:
            raise TransportError(f"only {len(devices)} controller(s) found, asked for number {index}")

        self.needs_firmware = product == CLONE_PRODUCT
        """A cloned board that has not been initialised will not answer. See :data:`CLONE_PRODUCT`."""

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
            if self.needs_firmware:
                raise TransportError(
                    "the board is a clone whose FPGA has not been loaded, so it does not answer. "
                    "Initialise it with MeerK40t's 'clone_init' first; this driver cannot do it."
                ) from error
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
        self.needs_firmware = False
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
