# LaserPecker wire protocol (LP1 – LP5, focus: LP2)

Reverse engineered from **LaserPecker Design Space (LDS) 2.12.1 for Windows** — an Electron app whose renderer
bundle contains the complete, uncompiled command layer. Nothing here was guessed: every framing rule, command code
and field below is transcribed from `resources/app.asar → release/app/assets/index.d966f69f.js` (class
`LaserpeckerBuffer`, the `*Command` builders and the `*Result` parsers) plus the Electron main process
(`release/app/ipc/src/serial.js`, `hid.js`).

Everything marked **UNVERIFIED** was read from code but never executed against real hardware.

---

## 1. Transports

All transports carry the same frames. Only framing of the *carrier* differs.

### 1.1 USB-C (primary)

The device exposes a **CH340 USB-serial bridge**:

| Property | Value |
| --- | --- |
| USB VID:PID | `1a86:7523` (also accepted: `1a86:55d4`) |
| Baud rate | **460800** |
| Flow control | none |
| Frame delimiting | inter-byte timeout of **100 ms** (LDS uses `InterByteTimeoutParser`) |

On Linux this appears as `/dev/ttyUSB0` with the in-kernel `ch341` driver — no vendor driver needed.

### 1.2 Bluetooth LE

LDS (and the Android app) talk to one of three GATT profiles, probed in this order:

| Profile | Service | Write (no response) | Notify |
| --- | --- | --- | --- |
| **Print** (ISSC/Microchip transparent UART — this is what LP2 uses) | `49535343-fe7d-4ae5-8fa9-9fafd205e455` | `49535343-8841-43f4-a8d4-ecbe34729bb3` | `49535343-1e4d-4bd9-ba61-23c647249616` |
| Custom | `0000fff0-…` | `0000fff2-…` | `0000fff1-…` |
| ESP32 (LP5/LP2P) | `0000abf0-…` | `0000abf3-…` | `0000abf4-…` |

Chunk size used by LDS over Web-Bluetooth: **179 bytes**, 100 ms between chunks. Device names are advertised as
`LaserPecker-II…`, which the UI rewrites to `LP2-…`.

### 1.3 Bluetooth dongle (LDS only)

The official USB dongle is a **CP210x (`10c4:ea60`) at 921600 baud** running an AT firmware that bridges to
Bluetooth **SPP** (not BLE):

```
AT+DSCA\r\n              stop scanning
AT+SCAN=1,20\r\n         scan, results as CSV lines (field 2 = MAC, field 5 = name)
AT+SCAN=0\r\n            stop
AT+SPPCONN=<mac>\r\n     connect  →  replies "OK#SPPCONN"
```

After `OK#SPPCONN` the same binary frames flow over the same serial port. Text (UTF-8 decodable) lines are AT
replies, binary data is device traffic — LDS distinguishes them with a UTF-8 validity check.

### 1.4 Wi-Fi / TCP

LP5 and LP2 Plus only. Same frames over a TCP socket, MTU 1440.

---

## 2. Framing

### 2.1 Host → device

```
 0    1    2      3      4 … 4+n-1        4+n  4+n+1
+----+----+------+------+---------------+-----+-----+
| AA | BB | len  | func | data (n bytes)| ck_hi ck_lo|
+----+----+------+------+---------------+-----+-----+
```

* `len = n + 3` — payload length counted from `func` on, including the two checksum bytes.
  The total frame size is therefore `n + 6`. `len` is a single byte, so **n ≤ 249**.
* `func` — command code (§3).
* `data` — big-endian fields of 1, 2 or 4 bytes each.
* `ck = (func + Σ data bytes) & 0xFFFF`, stored **big-endian**. The header bytes and `len` are *not* covered.

### 2.2 Device → host (short frames)

Identical layout with header `AA BB`:

```
AA BB <len> <func> <payload…> <ck_hi> <ck_lo>
```

Validation as performed by LDS: `buf[0]==0xAA && buf[1]==0xBB`, `len = buf[2]`, checksum over `buf[3 … len]`
(i.e. `func` + payload), compared against the last two bytes. Replies may arrive **split across several BLE
notifications / serial reads** — accumulate until the checksum validates.

The reverse also happens: **several frames arrive back to back in one read**. A reader must cut each frame to
its own length (`len + 3`) and keep the remainder buffered, otherwise the following frames are lost.

### 2.3 Device → host (long frames)

Used for the named file listing (§3.1, state 7):

```
AA CC <len32 BE, 4 bytes> <payload…> <ck_hi> <ck_lo>
```

Checksum: sum over `payload` (offsets 6 … 6+len-3), big-endian. The long frame is *preceded* by the short ack
`AA BB 06 00 07 00 00 00 07`.

### 2.4 Raw (unframed) bulk data

File uploads bypass framing entirely: after the transfer is announced with `func 0x05`, the 64-byte file header
and the payload are written to the transport **raw**, in MTU-sized chunks (§5).

---

## 3. Commands (`func`)

| func | Name | Purpose |
| --- | --- | --- |
| `0x00` | query | read status, settings, version, files (sub-command in `data[0]`) |
| `0x01` | print | start / continue / stop / pause an engraving job |
| `0x02` | preview & motion | frame preview, focus, Z-axis / stand control |
| `0x05` | file | announce transfer, delete files |
| `0x06` | settings | write device settings |
| `0x08` | wifi | Wi-Fi provisioning |
| `0x09` | cover | compliant protective cover control |
| `0xDD` | firmware | firmware update |
| `0xFD` | alarm off | silence alarm |
| `0xFF` | stop | leave current mode ("exit") |

### 3.1 `0x00` — query

Request: `func=0x00`, `data = [state, 0, 0, 0, 0]` (5 bytes, padding differs per sub-command).

| state | Returns | Parser |
| --- | --- | --- |
| 0 | working status | `WorkStatusResult`, §4.1 |
| 1 | list of file IDs on SD card | 4-byte big-endian IDs from offset 5, stride 4 |
| 2 | device settings | `SettingResult`, §4.2 |
| 3 | firmware version | `VersionResult`, §4.3 |
| 5 | MAC address | bytes 7, 8, 9 (hex, last three octets) |
| 7 | named file list (long frame) | 8-byte hex index + NUL-terminated name, from offset 19 |
| 8 | device name | UTF-8 from offset 6, length `buf[2]-6` |
| 9 | connectivity | `deviceConnectResult`: `ble=buf[6]`, `wifi=buf[7]`, `tcp=buf[8]`, IP string from 9 |
| 10 | is file ID cached? | `data = [10, 0, mount, id32]`, `mount` 1 = SD, 0 = USB stick |
| 11 | Wi-Fi module version | text fields from offset 6 |
| 12 | camera domain | comma-separated JSON from offset 6 |
| 13 | Wi-Fi provisioning progress | — |

### 3.2 `0x01` — print start

`data` (23 bytes):

| Offset | Size | Field | Encoding |
| --- | --- | --- | --- |
| 0 | 1 | `state` | 1 start, 2 continue, 3 stop, 4 pause, 5 multi-file start, 6 start by name |
| 1 | 1 | `laser` | laser power 1–100 (%) |
| 2 | 1 | `depth` | **`101 - depth`** — the app calls the UI value "depth"/burn time |
| 3 | 4 | `name` | file ID (see §5.1) |
| 7 | 2 | `nx` | X origin **in pixels at the chosen DPI** |
| 9 | 2 | `ny` | Y origin in pixels |
| 11 | 1 | `custom` | 0 |
| 12 | 1 | `times` | repeat count |
| 13 | 1 | `ltype` | laser type: 0 = 450 nm blue, 1 = 1064 nm IR (LP4+) |
| 14 | 2 | `obj_d` | rotary object diameter × 100 (mm) |
| 16 | 1 | `precision` | acceleration class 1–5 (LX1/C1) |
| 17 | 1 | `fan_speed` | one of 0 / 127 / 255; rpm = value × 168 + 25000 |
| 18 | 1 | `frequency` | laser pulse frequency 26–60 kHz (LP5) |
| 19 | 2 | `speed` | engraving speed mm/s, 0–15000 |
| 21 | 1 | `mount` | 0 = USB stick, 1 = SD card |

Pause/continue is sent with everything except `state` zeroed.

### 3.3 `0x02` — preview and motion

All variants share `func=0x02`; `data[0]` selects the sub-mode.

| `state` | Meaning |
| --- | --- |
| 1 | vector / file-index preview |
| 2 | rectangle preview |
| 3 | stop preview |
| 4 | rotary preview, paused |
| 5 | rotary preview, running |
| 6 | focus / stand control |
| 7 | centre preview |
| 9 | pen alignment (C1) |
| 10 | free-rolling preview |
| 11 | lift-table control |
| 12 | multi-rectangle preview |

**Rectangle preview** (`state` 2, 7, 4, 5, 10) — `data`:

| Offset | Size | Field | Encoding |
| --- | --- | --- | --- |
| 0 | 1 | state | |
| 1 | 2 | `w` | width × 10 (0.1 mm) |
| 3 | 2 | `h` | height × 10 |
| 5 | 2 | `x` | X × 10 |
| 7 | 2 | `y` | Y × 10 |
| 9 | 1 | custom | 0 |
| 10 | 1 | `px` | 4 (see §6) |
| 11 | 1 | `pwr` | preview laser power |
| 12 | 2 | `obj_d` | diameter × 100 |

**Focus / stand** (`state` 6) — `[6, dir, height×10 (2), 0, 0(2), 0(2), 0, 4, 1]`, `dir`: 0 down, 1 up, 2 stop.

**Lift table** (`state` 11) — `[11, ctrl, dist×100 (2), focal×100 (2)]`, `ctrl`: 0 down, 1 up, 2 stop, 3 autofocus.

### 3.4 `0x05` — file transfer / delete

**Announce transfer** — `data = [1, total_len32, 0]` where `total_len = 64 + payload_len`
(the 64-byte header counts). `state` 1 = transfer, 2 = end.
Reply: `fileStatusResult.rev == 1` means "ready, send the data". LDS waits up to **30 minutes** here.

For line (`fill`) data the announced length is `64 + 6 × line_count`.

**Delete** — `data = [state, index32, 0, mount]`:
`state` 4 = erase everything, 6 = erase by index, 7 = erase by name (NUL-terminated string follows).

### 3.5 `0x06` — write settings

`data` = 20 single bytes: `[1, free, buzzer, view, g_view, 0, z_flag, z_dir, key_view, ir_dst, key_print,
r_flag, s_flag, dir, g_pwr, s_rep, car_flag, print_dir, 0, overscan_flag]`.
`z_dir` is sent as 0 when the UI value is 2.

### 3.6 `0x09` — protective cover

* `settingAllCoverCommand(state, value)` — `[state, value]`, value is 1 byte for `state == 8`, else 2.
* `allCoverControlCommand(state[, l_type, speed, pwr])` — for `state == 1` three extra bytes follow.
* `allCoverControlLiftingCommand(dir, dist, focal)` — `[7, dir, dist×100 (2), focal×100 (2)]`,
  `dir`: 0 down, 1 up, 3 autofocus.

### 3.7 `0xDD` — firmware update

`data = [0, size32, sw_version16 (2), crc16 (2, optional), 0]`. The CRC is CRC-16/IBM-3740 style with the
polynomial table embedded in LDS (init `0x0000` as called, table `crc16Table`, `crc = (crc >> 8) ^ table[(crc ^ b) & 0xFF]`).
BLE and Web-Serial transports omit the CRC field. After `rev == 0` the raw firmware image is streamed.

### 3.8 `0xFF` — stop

`data = [0, 0, 0, 0, 0]`. Sent before every file upload and to abort a preview.

---

## 4. Reply payloads

Offsets below are **absolute frame offsets** (byte 0 = `0xAA`), exactly as LDS indexes them.

### 4.1 Working status (`func` 0, state 0)

| Offset | Field | Meaning |
| --- | --- | --- |
| 3 | `func` | must be 0 |
| 4 | `mode` | operating state, **measured**: 2 = preview running, 5 = error, 6 = idle/finished. This is *not* the `DeviceMode` enum from the LDS renderer (plane/Z/rotary/…) — those values describe the configured attachment and are unrelated. |
| 5 | `w_state` | working sub-state; measured: 0 fresh idle, 2 during preview, 255 after a preview ended. LDS treats `mode == 6 && w_state == 4` as "still running". |
| 6 | `rate` | progress in percent |
| 7 | `laser` | current power |
| 8 | `speed` | current depth/speed setting |
| 9 | `error` | error code, see below |
| 11–14 | `name` | current file ID (32-bit BE) |
| 15 | `temp` | temperature |
| 17 | `z_connect` | Z-axis attached |
| 18 | `print_times` | completed repeats |
| 19 | `angle` | tilt angle |
| 20 | `m_state` | motion state |
| 21 | `r_conn` | rotary attached |
| 22 | `s_conn` | slide attached |
| 23 | `car_conn` | car/trolley attached |
| 24 | `u_b_cnn` | USB / dongle attached |
| 25 | `stop` | emergency stop (only if `len > 24`) |
| 26 | `safe_key` | safety key |
| 27–28 | cover bitmap | 16-bit, see `coverErrorStatusMap` |
| 29 | `cover_conn` | cover connected |
| 30 | `standard` | compliance flag |
| 31 | `s_cover_conn` | second cover (only if frame > 33 bytes) |

Error codes (index into LDS' `DeviceError`):

| Code | Meaning |
| --- | --- |
| 0 | no error |
| 1 | not in a safe state and free mode is off |
| 2 | print exceeds work area |
| 3 | laser temperature alarm |
| 4 | device moved during print |
| 5 | laser obstructed during print |
| 6 | print data error |
| 7 | file index query error |
| 8 | gyroscope self-test error |
| 9 | flash self-test error |
| 10 | image out of range |
| 11 | flame-out alarm |
| 12 | storage limit exceeded |
| 13 | duplicate file-name limit |

### 4.2 Settings (`func` 0, state 2)

Offsets 4…28: `free, buzzer, view, g_view, safe, –, z_flag, z_dir, key_view, ir_dst, key_print, r_flag, s_flag,
dir, g_pwr, s_rep, car_flag, print_dir, –, overscan_flag, LedLevel, FanLevel, FanTime(2, BE at 26), RecoverState(28)`.

### 4.3 Version (`func` 0, state 3)

* `SW_Version = (buf[4] << 8) + buf[5]` — an integer such as `370`; the model is derived from the range it falls
  into (§6).
* `HW_Version` = hex digits of bytes 6, 7, 8, 9 concatenated and parsed as hex.

### 4.4 Short acks

* `fileStatusResult` → `{func: buf[4], rev: buf[5]}` — `rev == 1` means OK.
* `deviceFocusResult` → `{func: buf[4], rev: buf[6]}`.
* `FirmwareResult` → `{func: buf[3], rev: buf[4]}`; `FirmwareOKResult` uses `buf[4]`/`buf[5]`.

---

## 5. Uploading an engraving job

Sequence used by LDS for a raster image (`sendImageFile` → `sendFile`), all over the same connection:

1. `0xFF` **stop** — wait for any reply.
2. `0x05` **announce**, `total = 64 + len(payload)` — wait for `rev == 1`.
3. Write the **64-byte file header** raw (§5.2).
4. Write the payload raw in MTU chunks, 15 ms apart. Progress is the byte count.
   Serial MTU 2048 bytes, 50 ms per chunk, max 30 chunks/s; BLE 179 bytes / 100 ms.
5. The device sends `fileStatusResult` when it has stored the file.
6. `0x01` **print start** with the same file ID, power, depth and the pixel origin.
7. Poll `0x00`/state 0 once per second: `rate` is the percentage, `mode == 6 && w_state != 4` means finished,
   `mode == 5` means error.

### 5.1 File ID

`fileId = parseInt(hashSum(MD5(name)), 16)` — a 32-bit integer derived from the file name. Any stable 32-bit
number works as long as the same value is used in the header and in `print start`. Query state 1 (or 10) tells
whether the ID is already cached on the device, which lets LDS skip the upload entirely.

### 5.2 The 64-byte file header

All multi-byte fields big-endian. Byte 0 is the **data-type tag**:

| Tag | Type |
| --- | --- |
| `0x10` | dithered raster, 1 byte per pixel |
| `0x60` | dithered raster, 1 **bit** per pixel (compressed) |
| `0x40` | line/fill data (6 bytes per line) |
| `0x30` | path data |
| `0x20` | G-code |

Raster header (`genDitherDataCommand`):

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | tag `0x10` / `0x60` |
| 1 | 2 | image width in pixels |
| 3 | 2 | image height in pixels |
| 5 | 4 | file ID |
| 9 | 1 | `px` (§6) |
| 10 | 2 | `nx` — X origin in pixels |
| 12 | 2 | `ny` — Y origin in pixels |
| 14 | 2 | `dpi` (integer part) |
| 16 | 1 | `direction` (0 normal; 1 for LP5 in non-plane modes) |
| 21 | 1 | `mode` (export mode) |
| 34… | ≤29 | file name, UTF-8, zero padded |

Line header (`genLineDataCommand`) differs: `[0x40, w(2), h(2), fileId(4 at 5), lines(4 at 9), px(13),
nx(2 at 14), ny(2 at 16), dpi(2 at 18), direction(20), name(34…)]`.

Path header (`genPathDataCommand`): `[0x30, w(2), h(2), fileId(4), –, nx(2 at 11), ny(2 at 13), dpi(2 at 16),
dataLen(4 at 18), name(34…)]`.

G-code header (`genGcodeDataCommand`): `[0x20, w(2), h(2), fileId(4), gcodeNums(4 at 9), nx(2 at 13),
ny(2 at 15), dpi(2 at 17), name(34…)]`.

### 5.3 Raster payload

Verified by executing LDS' own `image_bg.wasm` (`image_to_dither_stream`) against synthetic images:

* The image is **Floyd-Steinberg dithered to pure black/white** before packing.
* `compress = 0` → **one byte per pixel**, row-major, `0x00` = burn, `0xFF` = skip. Length `w × h`.
* `compress = 1` → **one bit per pixel**, MSB first, `0` = burn, `1` = skip. **Each row is padded to a whole
  byte**, so the length is `ceil(w / 8) × h`.
* `inverse` swaps burn/skip.

Whether the device accepts the compressed form depends on the firmware: `supportDitheringRange` in
`pc_device_config_v16.json` lists `315~349 359~369 374~399` for LP2.

The exact dither *kernel* inside the WASM is not bit-identical to a textbook Floyd-Steinberg: on a horizontal
grey ramp roughly 30 % of the pixels differ, the WASM output being shifted by about one pixel. Only the
threshold decision differs, not the packing — the device sees a valid image either way. Reproducing it
bit-for-bit would require disassembling the Rust routine and has no practical benefit.

---

## 6. Geometry, DPI and `px`

* Canvas coordinates are **millimetres**. Preview commands transmit them as `mm × 10` (0.1 mm units).
* Raster jobs work in **pixels**: `scale = dpi / 25.4`, then
  `width = ceil(w_mm × scale)`, `left = floor(x_mm × scale)` (clamped at 0).
* `px` is a hardware step size that goes with the DPI. LP2 supports:

| `px` | DPI | Label |
| --- | --- | --- |
| 4 | 254 | 1K |
| 3 | 338.667 | 1.3K |
| 2 | 508 | 2K |

  LDS also keeps `PxMap`: `4 → 10, 3 → 13, 2 → 20, 1 → 40`.

### LP2 device profile (from `pc_device_config_v16.json`)

| Property | Value |
| --- | --- |
| Work area | 100 × 100 mm |
| Camera area | 110 × 110 mm |
| Focal distance | 110 mm (max range 229.5 mm) |
| Laser | 450 nm, 5 W |
| SW version ranges | `300~349 3000~3099 350~369 3500~3599 370~399 3700~3799` |
| Dithering support | `315~349 359~369 374~399` |
| Multi-file print | `377~399 3700~3799` |
| Z axis / laser strength | yes / yes |
| Max heights | Z 2000, rotary 628, slide 300 (0.1 mm units) |

---

## 7. Verified on hardware

Confirmed on an **LP2, firmware 3.16, hardware `01 32 1e 86`**, over both transports. Captured replies live in
`tests/fixtures_lp2.json` and are asserted in `tests/test_hardware_replies.py`.

* Framing and checksums are correct on both short frames and the 133-byte file-ID reply.
* USB and BLE return byte-identical payloads — with one exception: **byte 24 of the status reply
  (`u_b_cnn`) reports the link.** Measured: `1` when only BLE is connected, `2` whenever USB is plugged in,
  including while a BLE session is open in parallel — USB appears to win. LDS never surfaces this.
* The USB bridge in this unit is a **CH340 (`1a86:7523`)** at 460800 baud, appearing as `/dev/ttyUSB0`.
  Newer units use a **CH9102 (`1a86:55d4`)**, which the in-tree `ch341` driver does *not* claim — it shows up
  as `/dev/ttyACM*` through `cdc_acm` instead.
* The USB-C **data** port sits on the power/control block (between the two `OUT 5V 2A` sockets and
  `IN 12V 5A`), not on the laser head. **Use a USB-A-to-USB-C cable**: with C-to-C the device does not
  enumerate at all — the CH340 side lacks the CC pull-down resistors that mark it as a device, so neither
  end takes the host role. A USB-A port is always host, which sidesteps the problem.
* Query state 1 returns the number of stored files in byte 4, followed by that many 32-bit IDs.
* The status reply carries `len == 24`, so the cover/safety fields (offsets 25-31) are **absent** on this
  firmware — parsers must treat them as optional.
* The settings reply is only 25 bytes long; everything LDS reads from offset 23 on (`overscan_flag`,
  `LedLevel`, `FanLevel`, `FanTime`, `RecoverState`) does not exist here.

**Not supported by firmware 3.16** — these queries are answered with silence, not an error:
state 7 (named file list), 8 (device name), 9 (connectivity), 11 (Wi-Fi version). They belong to LP5/LP2P.

### The device can get stuck refusing all file transfers

Observed once, persisting for hours across every attempted variation. **Cause unknown — only a power cycle
cleared it.**

| | Reply to `0x05` state 1 |
| --- | --- |
| Healthy | `aabb 08 05 01 01 00 00 00 00 07` — `func 0x05`, `rev = 1`, accepted |
| Stuck | `aabb 08 ff 01 <len32> …` — `func 0xFF`, refused |

The refusal is easy to mistake for an acknowledgement because it echoes the announced length. Two reliable
checks: the reply's `func` is `0xFF` instead of `0x05`, and a status query sent instead of payload gets a
normal answer — a device in receive mode swallows those bytes as data.

**Ruled out as the cause.** Each of these was re-tested after the power cycle and transfers kept working:
running a preview beforehand (the initial suspicion — it was wrong), `w_state == 255` (that value is normal
and present while transfers succeed), an open BLE session in parallel, switching between BLE and USB,
payload size 1 – 22500 bytes, `0x10` vs `0x60`, chunked vs. single write, a trailing `0x05` state 2, a
preceding `0x01` state 3, and the file-ID range.

Nothing has reproduced it since. It appeared after hours of uptime and many failed transfer attempts, so a
firmware lock-up is the best guess. A client should recognise the `0xFF` reply and tell the user to
power-cycle the device rather than retry.

Related observations:

* Unknown function codes (`0x7E`, `0x42`) get **no answer at all** — so the `0xFF` reply is specific, not a
  generic "unknown command".
* `0x05` state 2 always answers `aabb 08 05 02 01 …` (`rev = 1`), even when no data was sent. It is not a
  useful confirmation.
* Query state 10 (is-file-cached) is unsupported here, consistent with LDS using it only for LP5/LP2P.
* Right after boot the status may report `error = 1` ("not in a safe state, free mode off"). Uploads and
  engraving still worked.

### Engraving, measured end to end

Verified on hardware: dither → announce → 64-byte header → payload → `0x01` print start → the motif appears
on the workpiece. Replies observed during a successful upload:

```
rx  aabb 08 05 01 01 00 00 00 00 07     ready, send data
    <64-byte header + payload>
rx  aabb 08 05 02 01 00 00 00 00 08     stored
rx  aabb 08 ff 01 <len32>               transfer mode left
```

The device sends acknowledgements unprompted, so a reader must filter replies by `func` — otherwise the
upload confirmation is mistaken for the answer to the next status query.

### Preview, measured

A rectangle preview (`0x02` state 2) is accepted without a reply and starts immediately; the status `mode`
switches to 2 and `w_state` to 2. `0x02` state 3 stops it, but the device needs roughly a second to settle —
polling the status right away still reports the preview. LDS sleeps one second after every stop for this
reason. After the preview ends, `w_state` reads 255.

## 8. Open questions

* Semantics of `w_state` beyond "4 = running".
* Exact meaning of the `mode` byte in the raster header (export mode; only 0 observed for LP2).
* Whether LP2 firmware accepts `0x60` (bit-packed) payloads — the version range suggests yes for ≥ 3.15.
* The line/fill format (6 bytes per line) has not been decoded; it is only needed for vector fills.
* No frame was captured from real hardware yet — all reply offsets come from the LDS parsers.
