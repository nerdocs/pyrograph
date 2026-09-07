"""Protocol tests.

The expected byte strings were derived from LDS 2.12.1's own encoder (``LaserpeckerBuffer``), the payload
encodings from executing its ``image_bg.wasm`` on synthetic images.
"""

from laserpecker import protocol as p
from laserpecker.imaging import pack_bits
from laserpecker.transport import _FrameAssembler


def test_frame_layout_and_checksum():
    frame = p.build_frame(0x02, [(2, 1), (0x0100, 2)])
    assert frame == bytes([0xAA, 0xBB, 6, 0x02, 0x02, 0x01, 0x00, 0x00, 0x05])
    assert p.frame_complete(frame)


def test_checksum_covers_func_and_data_only():
    frame = p.build_frame(0xFF, [(0, 1)] * 5)
    assert frame[:4] == bytes([0xAA, 0xBB, 8, 0xFF])
    assert frame[-2:] == bytes([0x00, 0xFF])


def test_status_query_is_eleven_bytes():
    assert p.query(p.Query.STATUS) == bytes([0xAA, 0xBB, 8, 0, 0, 0, 0, 0, 0, 0, 0])


def test_print_start_inverts_depth():
    frame = p.print_start(file_id=1, power=30, depth=40, nx=0, ny=0)
    assert frame[4] == p.PrintState.START
    assert frame[5] == 30
    assert frame[6] == 101 - 40


def test_preview_uses_tenths_of_a_millimetre():
    frame = p.preview_rect(x_mm=5.0, y_mm=2.5, w_mm=10.0, h_mm=20.0, power=3)
    body = frame[4:]
    assert body[1:3] == (100).to_bytes(2, "big")  # width 10 mm
    assert body[3:5] == (200).to_bytes(2, "big")  # height 20 mm
    assert body[5:7] == (50).to_bytes(2, "big")  # x 5 mm
    assert body[7:9] == (25).to_bytes(2, "big")  # y 2.5 mm


def test_file_transfer_adds_header_length():
    frame = p.open_file_transfer(1000)
    assert int.from_bytes(frame[5:9], "big") == 1064


def test_raster_header():
    header = p.raster_header(
        file_id=0xDEADBEEF, width=320, height=240, nx=10, ny=20, px=4, dpi=254, name="test"
    )
    assert len(header) == 64
    assert header[0] == p.DataTag.RASTER
    assert header[1:3] == (320).to_bytes(2, "big")
    assert header[3:5] == (240).to_bytes(2, "big")
    assert header[5:9] == bytes.fromhex("deadbeef")
    assert header[9] == 4
    assert header[10:12] == (10).to_bytes(2, "big")
    assert header[12:14] == (20).to_bytes(2, "big")
    assert header[14:16] == (254).to_bytes(2, "big")
    assert header[34:38] == b"test"


def test_packed_header_uses_compressed_tag():
    assert p.raster_header(1, 8, 8, 0, 0, 4, 254, packed=True)[0] == p.DataTag.RASTER_PACKED


def test_bit_packing_matches_wasm_output():
    # LDS' image_to_dither_stream with compress=1 on a 16x8 image with a single black pixel
    # at (0,0) returns 7f ff ff … — MSB first, 0 = burn.
    mono = [255] * (16 * 8)
    mono[0] = 0
    packed = pack_bits(mono, 16, 8)
    assert packed[:2] == bytes([0x7F, 0xFF])
    assert len(packed) == 16


def test_bit_packing_pads_rows_to_byte_boundary():
    mono = [0] * (12 * 4)
    assert len(pack_bits(mono, 12, 4)) == 8  # ceil(12/8) * 4


def test_status_parser():
    body = bytes(
        [0x00, 0x06, 0x04, 0x2A, 0x1E, 0x32, 0x00]  # func, mode, w_state, rate, laser, speed, error
        + [0x00, 0x00, 0x00, 0x00, 0x01]  # padding + file id
        + [0x19, 0x00, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    )
    frame = bytes([0xAA, 0xBB, len(body) + 2]) + body + b"\x00\x00"
    status = p.parse_status(frame)
    assert status.mode == p.WorkMode.IDLE
    assert status.rate == 42
    assert status.laser == 30
    assert status.file_id == 1
    assert status.error_text == "no error"
    assert not status.finished  # w_state == 4 means still running


def test_version_parser():
    frame = bytes([0xAA, 0xBB, 0x0A, 0x00, 0x01, 0x72, 0x01, 0x02, 0x03, 0x04, 0x00, 0x00])
    version = p.parse_version(frame)
    assert version.sw_version == 370  # 0x0172 → LP2 range 370~399
    assert version.hw_version == 0x1234


def test_frames_are_cut_apart_when_they_arrive_together():
    assembler = _FrameAssembler()
    assembler.feed(p.query(p.Query.STATUS) + p.stop())
    assert assembler.get(0.0) == p.query(p.Query.STATUS)
    assert assembler.get(0.0) == p.stop()


def test_a_stray_header_byte_does_not_swallow_the_frames_behind_it():
    """0xAA turns up in payload noise. Waiting for it to become a frame would never end."""
    assembler = _FrameAssembler()
    assembler.feed(b"\xaa\x00\x11\x22" + p.stop())
    assert assembler.get(0.0) == p.stop()
