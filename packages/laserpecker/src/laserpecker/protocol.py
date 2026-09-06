"""Frame encoding/decoding and command builders for the LaserPecker wire protocol.

See ``docs/protocol.md`` for the specification this implements.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

HEADER = b"\xaa\xbb"
LONG_HEADER = b"\xaa\xcc"

MAX_DATA_LEN = 249  # len byte is data_len + 3 and must stay below 256


class Func(IntEnum):
    """Command codes carried in byte 3 of a frame."""

    QUERY = 0x00
    PRINT = 0x01
    PREVIEW = 0x02
    FILE = 0x05
    SETTINGS = 0x06
    WIFI = 0x08
    COVER = 0x09
    FIRMWARE = 0xDD
    ALARM_OFF = 0xFD
    STOP = 0xFF


class Query(IntEnum):
    """Sub-commands of :attr:`Func.QUERY` (``data[0]``)."""

    STATUS = 0
    FILE_IDS = 1
    SETTINGS = 2
    VERSION = 3
    MAC = 5
    FILE_LIST = 7
    NAME = 8
    CONNECTIVITY = 9
    FILE_CACHED = 10
    WIFI_VERSION = 11
    CAMERA_DOMAIN = 12
    WIFI_PROGRESS = 13


class PrintState(IntEnum):
    START = 1
    CONTINUE = 2
    END = 3
    HOLD = 4
    MULTI_START = 5
    NAME_START = 6


class PreviewState(IntEnum):
    VECTOR = 1
    RECTANGLE = 2
    STOP = 3
    ROTARY_PAUSED = 4
    ROTARY_RUNNING = 5
    FOCUS = 6
    CENTER = 7
    PEN_ALIGN = 9
    FREE_ROLLING = 10
    LIFT = 11
    MULTI_RECTANGLE = 12


class WorkMode(IntEnum):
    """``mode`` byte of the working status reply — values observed on an LP2.

    Do **not** confuse this with :class:`AttachmentMode`; the ranges are unrelated.
    """

    PREVIEW = 2  # a preview is running
    ERROR = 5  # LDS aborts a job on this value
    IDLE = 6  # ready / job finished


class AttachmentMode(IntEnum):
    """Which attachment the *app* is configured for. Not the status byte."""

    PLANE = 0
    Z_AXIS = 1
    ROTARY = 2
    SLIDE = 3
    SLIDE_REPEAT = 4
    CAR = 5
    PEN = 6
    C_FLAG = 7


class DataTag(IntEnum):
    """Byte 0 of the 64-byte file header."""

    RASTER = 0x10
    RASTER_PACKED = 0x60
    LINE = 0x40
    PATH = 0x30
    GCODE = 0x20


DEVICE_ERRORS = {
    0: "no error",
    1: "not in a safe state and free mode is off",
    2: "print exceeds work area",
    3: "laser temperature alarm",
    4: "device moved during print",
    5: "laser obstructed during print",
    6: "print data error",
    7: "file index query error",
    8: "gyroscope self-test error",
    9: "flash self-test error",
    10: "image out of range",
    11: "flame-out alarm",
    12: "storage limit exceeded",
    13: "duplicate file-name limit reached",
}


class ProtocolError(Exception):
    pass


# --------------------------------------------------------------------------- framing


def build_frame(func: int, fields: list[tuple[int, int]] = ()) -> bytes:
    """Build a host→device frame.

    ``fields`` is a list of ``(value, size)`` pairs; size is 1, 2 or 4 bytes, big-endian.
    """
    data = bytearray()
    for value, size in fields:
        if size == 1:
            data += struct.pack(">B", value & 0xFF)
        elif size == 2:
            data += struct.pack(">H", value & 0xFFFF)
        elif size == 4:
            data += struct.pack(">I", value & 0xFFFFFFFF)
        else:
            raise ValueError(f"unsupported field size {size}")
    if len(data) > MAX_DATA_LEN:
        raise ProtocolError("data length exceeds the limit")
    body = bytes([func]) + bytes(data)
    checksum = sum(body) & 0xFFFF
    return HEADER + bytes([len(data) + 3]) + body + struct.pack(">H", checksum)


def frame_complete(buf: bytes) -> bool:
    """True when ``buf`` holds a complete, checksum-valid device reply."""
    if len(buf) < 6 or buf[0] != 0xAA or buf[1] != 0xBB:
        return False
    length = buf[2]
    if length < 3 or len(buf) < length + 3:
        return False
    checksum = sum(buf[3 : length + 1]) & 0xFFFF
    return checksum == int.from_bytes(buf[length + 1 : length + 3], "big")


def long_frame_complete(buf: bytes) -> bool:
    """True when ``buf`` holds a complete ``AA CC`` long frame (named file list)."""
    if len(buf) < 8 or buf[0] != 0xAA or buf[1] != 0xCC:
        return False
    length = int.from_bytes(buf[2:6], "big")
    if not length or len(buf) < length + 6:
        return False
    checksum = sum(buf[6 : length + 4]) & 0xFFFF
    return checksum == int.from_bytes(buf[length + 4 : length + 6], "big")


# --------------------------------------------------------------------------- commands


def query(state: int) -> bytes:
    return build_frame(Func.QUERY, [(state, 1), (0, 1), (0, 1), (0, 1), (0, 1)])


def query_file_cached(file_id: int, mount: int = 1) -> bytes:
    return build_frame(Func.QUERY, [(Query.FILE_CACHED, 1), (0, 1), (mount, 1), (file_id, 4)])


def file_list(mount: int = 0) -> bytes:
    """Named file listing; answered with a long ``AA CC`` frame."""
    return build_frame(Func.QUERY, [(Query.FILE_LIST, 1), (0, 1), (mount, 1), (0, 1), (0, 1)])


def stop() -> bytes:
    return build_frame(Func.STOP, [(0, 1)] * 5)


def alarm_off() -> bytes:
    return build_frame(Func.ALARM_OFF, [])


def preview_rect(
    x_mm: float,
    y_mm: float,
    w_mm: float,
    h_mm: float,
    power: int = 1,
    diameter_mm: float = 0.0,
    state: int = PreviewState.RECTANGLE,
    px: int = 4,
) -> bytes:
    """Trace a rectangle with the laser at low power to show where the job will land."""
    return build_frame(
        Func.PREVIEW,
        [
            (state, 1),
            (int(w_mm * 10), 2),
            (int(h_mm * 10), 2),
            (int(x_mm * 10), 2),
            (int(y_mm * 10), 2),
            (0, 1),
            (px, 1),
            (int(power), 1),
            (int(diameter_mm * 100), 2),
        ],
    )


def preview_stop() -> bytes:
    return preview_rect(0, 0, 0, 0, 0, 0, state=PreviewState.STOP, px=4)


def focus(direction: int, height_mm: float) -> bytes:
    """Move the stand: ``direction`` 0 = down, 1 = up, 2 = stop."""
    return build_frame(
        Func.PREVIEW,
        [
            (PreviewState.FOCUS, 1),
            (direction, 1),
            (int(height_mm * 10), 2),
            (0, 1),
            (0, 2),
            (0, 2),
            (0, 1),
            (4, 1),
            (1, 1),
        ],
    )


def open_file_transfer(payload_len: int) -> bytes:
    """Announce a raw upload of ``64 + payload_len`` bytes."""
    return build_frame(Func.FILE, [(1, 1), (64 + payload_len, 4), (0, 1)])


def delete_file(index: int, state: int = 6, mount: int = 1) -> bytes:
    """``state`` 4 = erase all, 6 = erase by index, 7 = erase by name."""
    return build_frame(Func.FILE, [(state, 1), (index, 4), (0, 1), (mount, 1)])


def print_start(
    file_id: int,
    power: int,
    depth: int,
    nx: int,
    ny: int,
    times: int = 1,
    state: int = PrintState.START,
    ltype: int = 0,
    diameter_mm: float = 0.0,
    precision: int = 0,
    fan_level: int = 0,
    frequency: int = 60,
    speed: int = 0,
    mount: int = 1,
) -> bytes:
    """Start (or stop/pause/continue) an engraving job that was uploaded before."""
    fan = [0, 127, 255][fan_level] if fan_level in (0, 1, 2) else fan_level
    return build_frame(
        Func.PRINT,
        [
            (state, 1),
            (power, 1),
            (101 - depth, 1),
            (file_id, 4),
            (nx, 2),
            (ny, 2),
            (0, 1),
            (times, 1),
            (ltype, 1),
            (int(diameter_mm * 100), 2),
            (precision, 1),
            (fan, 1),
            (frequency, 1),
            (speed, 2),
            (mount, 1),
        ],
    )


def print_pause(paused: bool = True) -> bytes:
    state = PrintState.HOLD if paused else PrintState.CONTINUE
    return print_start(0, 0, 0, 0, 0, times=0, state=state, frequency=0)


def raster_header(
    file_id: int,
    width: int,
    height: int,
    nx: int,
    ny: int,
    px: int,
    dpi: int,
    name: str = "",
    packed: bool = False,
    direction: int = 0,
    mode: int = 0,
) -> bytes:
    """The 64-byte header that precedes raw raster payload."""
    h = bytearray(64)
    h[0] = DataTag.RASTER_PACKED if packed else DataTag.RASTER
    struct.pack_into(">H", h, 1, width)
    struct.pack_into(">H", h, 3, height)
    struct.pack_into(">I", h, 5, file_id)
    h[9] = px
    struct.pack_into(">H", h, 10, nx)
    struct.pack_into(">H", h, 12, ny)
    struct.pack_into(">H", h, 14, int(dpi))
    h[16] = direction
    h[21] = mode
    encoded = name.encode("utf-8")[:29]
    h[34 : 34 + len(encoded)] = encoded
    return bytes(h)


# --------------------------------------------------------------------------- replies


@dataclass
class Status:
    mode: int
    w_state: int
    rate: int
    laser: int
    speed: int
    error: int
    file_id: int
    temp: int
    z_connect: int
    print_times: int
    angle: int
    m_state: int
    r_conn: int
    s_conn: int
    car_conn: int
    u_b_conn: int
    stop: int | None = None
    safe_key: int | None = None
    cover_conn: int | None = None
    standard: int | None = None

    @property
    def finished(self) -> bool:
        return self.mode == WorkMode.IDLE and self.w_state != 4

    @property
    def error_text(self) -> str:
        return DEVICE_ERRORS.get(self.error, f"unknown error {self.error}")


def parse_status(buf: bytes) -> Status:
    if len(buf) < 25 or buf[3] != Func.QUERY:
        raise ProtocolError("not a status reply")
    status = Status(
        mode=buf[4],
        w_state=buf[5],
        rate=buf[6],
        laser=buf[7],
        speed=buf[8],
        error=buf[9],
        file_id=int.from_bytes(buf[11:15], "big"),
        temp=buf[15],
        z_connect=buf[17],
        print_times=buf[18],
        angle=buf[19],
        m_state=buf[20],
        r_conn=buf[21],
        s_conn=buf[22],
        car_conn=buf[23],
        u_b_conn=buf[24],
    )
    if len(buf) > 27 and buf[2] > 24:
        status.stop = buf[25]
        status.safe_key = buf[26]
        status.cover_conn = buf[29]
        status.standard = buf[30]
    return status


@dataclass
class Version:
    sw_version: int
    hw_version: int
    hw_bytes: bytes = b""


def parse_version(buf: bytes) -> Version:
    if len(buf) < 10:
        raise ProtocolError("short version reply")
    # LDS concatenates the hex digits without padding; kept for comparability, raw bytes added.
    hw = "".join(f"{buf[i]:x}" for i in range(6, 10))
    return Version(
        sw_version=(buf[4] << 8) + buf[5],
        hw_version=int(hw, 16),
        hw_bytes=bytes(buf[6:10]),
    )


def parse_file_status(buf: bytes) -> int:
    """``rev`` byte of a file acknowledgement; 1 means OK."""
    if len(buf) < 6:
        raise ProtocolError("short file status reply")
    return buf[5]


def parse_file_ids(buf: bytes) -> list[int]:
    """File IDs stored on the device (query state 1)."""
    body = buf[4 : len(buf) - 3]
    return [int.from_bytes(body[i : i + 4], "big") for i in range(1, len(body) - 3, 4)]


def parse_mac(buf: bytes) -> str:
    """Full six-byte MAC as ``AA:BB:…``.

    The device's BLE advertising address is this value with the first octet incremented by one.
    """
    if len(buf) < 10:
        raise ProtocolError("short MAC reply")
    return ":".join(f"{b:02X}" for b in buf[4:10])


def parse_mac_suffix(buf: bytes) -> str:
    """Last three octets — this is what the advertised name ends with (``LaserPecker-IIAABBCC``)."""
    if len(buf) < 10:
        raise ProtocolError("short MAC reply")
    return "".join(f"{buf[i]:02X}" for i in (7, 8, 9))


def parse_name(buf: bytes) -> str:
    length = buf[2]
    return buf[6 : length].decode("utf-8", "replace").strip()
