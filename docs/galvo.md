# Galvo lasers (EZCAD2 / BJJCZ)

The protocol behind the `ezcad2` driver package and the `GalvoAdapter` in `pyrograph.devices`. Nothing
here has been run against hardware — this is a reading of two existing implementations, not a verified
protocol description like `docs/protocol.md`.

## What the hardware is

"Galvo EZCAD" almost always means a **BJJCZ / Beijing JCZ LMC controller board** (LMCV4-FIBER-M and
relatives) driving a fiber or CO2 galvo. EZCAD2 is only the Windows software in front of it.

The USB protocol was reverse engineered from capture by Bryce Schroeder
([balor](https://gitlab.com/bryce15/balor), GPL-3.0) and rewritten by MeerK40t as
[galvoplotter](https://github.com/meerk40t/galvoplotter) (MIT). LightBurn support was developed
independently.

**EZCAD3 and BSL boards speak a different protocol** and are covered by neither project.

## Transport

libusb, not serial:

| | |
| --- | --- |
| Vendor / product | `0x9588` / `0x9899` |
| Write endpoint | `0x02`, bulk |
| Read endpoint | `0x88`, bulk |
| Packet sizes | exactly `0x0C` (12 bytes) or `0x0C00` (3072 bytes) — nothing else is accepted |
| Reply | 8 bytes, read as four little-endian words |

## Commands

Every command is six little-endian 16-bit words — an opcode and five arguments:

```python
struct.pack("<6H", command, v1, v2, v3, v4, v5)
```

There are two classes. **Single commands** (`0x0002`–`0x0062`) are sent as one 12-byte packet and act at
once: `GetSerialNo 0x09`, `GetVersion 0x07`, `GotoXY 0x0D`, `Reset 0x40`, `ExecuteList 0x05`,
`StopExecute 0x1F`, `WritePort 0x21`, `Fiber_SetMo 0x33`, `GetMarkTime 0x41`.

**List commands** (`0x8001`–`0x8051`) are buffered: 256 of them are packed into one 3072-byte block and
uploaded as a unit. `listJumpTo 0x8001`, `listMarkTo 0x8005`, `listMarkSpeed 0x800C`,
`listMarkPowerRatio 0x800B`, `listMarkFreq 0x800A`, `listLaserOnDelay 0x8007`, `listPolygonDelay 0x800F`,
`listQSwitchPeriod 0x801B`, `listFiberYLPMPulseWidth 0x8026` (MOPA pulse width), `listEndOfList 0x8002`.

Status is a bit field: `BUSY = 0x04`, `READY = 0x20`, `AXIS = 0x40`.

## Why this is a streaming device

The list is not a file that gets uploaded and then started. `ExecuteList` is issued **once two blocks are
buffered**, so the board is marking while the host is still sending the rest. Sending *is* running, and
there is no point in between at which the host is free — hence `DeviceProfile.streams` (`docs/architecture.md`).

It also means there is no progress percentage to ask for. The board answers busy or ready; `GetMarkCount`
and `GetMarkTime` are counters, not a fraction. Progress can only be counted host-side, as blocks sent
against blocks total, which is why `DeviceStatus.progress` has to be allowed to be `None`.

## Units

| Quantity | Conversion |
| --- | --- |
| Position | `uint16`, `0…0xFFFF`, field centre at `0x8000` |
| Scale | `galvos_per_mm`, typically 500 — depends on lens and field size |
| Speed | `mm/s × galvos_per_mm / 1000` |
| Power | `% × 0xFFF / 100` (12 bit) |
| Frequency | period = `20000 / f_kHz` |

## Initialisation

Roughly eighteen steps before the board will mark: serial number, version, `Reset`, **correction table**,
`EnableLaser`, control / laser / delay / timing mode, standby, first-pulse killer, PWM half-period and pulse
width, fiber MO off, FPK parameters, fly resolution, `EnableZ`, analog port 1 = `0x7FF`.

## Lens correction

Every galvo lens distorts the field, so a correction table is mandatory. The `.cor` file holds a 65 × 65
grid in one of two layouts — header `LMC1COR_1.0` means doubles, otherwise 32-bit integers. It is not
transferred as a file: the host reads it and writes it row by row with `WriteCorLine 0x10`.

Without a correction file a blank table is written and the field is geometrically wrong.

**Where a `.cor` comes from.** Almost always with the machine — on the supplied stick, or in the EZCad2
folder — because it belongs to the lens that was fitted. **There is no open-source way to make one.**
MeerK40t started an editor for it (`balormk/gui/corscene.py`: burn a test pattern, twelve measurement
fields) but the export is still a placeholder that writes `b"Testing..."`, and its own dialog is titled
"Doesn't currently export". LightBurn's nine-point wizard works and is closed and commercial. EZCad2 has
a wizard too, and is Windows-only.

`ezcad2.correction.read_scale` reads `galvos_per_mm` back out of a `.cor`, which is the only place that
number can come from without measuring a test burn by hand.

## Correcting the field on the host instead

Balor's author found the board's own table did not fully linearise his machine and added a second
correction computed on the host, from a grid burnt and measured with calipers. `ezcad2.calibration`
implements that idea and `Lens.calibration` switches it on — **experimental, and normally unnecessary**.

Balor interpolates with radial basis functions and needs scipy. This uses bilinear interpolation on the
measured grid, inverted by Newton iteration: less clever, enough for barrel distortion, and it keeps the
package's dependencies at pyusb alone.

The table is balor's format, one measured point per line:

```
x_mm  y_mm  column  row  galvo_x_hex  galvo_y_hex
```

Reading it is strict on purpose — a hole in the grid names the missing row and column, because losing one
measurement out of eighty-one is easy and finding out at mark time is not.

## How it is implemented

`packages/ezcad2` is the driver — protocol, USB transport, correction files, list buffering — and knows
nothing about documents. `pyrograph.devices.ezcad2.GalvoAdapter` puts it behind `LaserDevice`.

The adapter owns two conventions the driver does not:

* **The job is centred on the field.** A document counts from a corner, a galvo from the middle of its
  field, and the middle is where a workpiece gets placed anyway.
* **Y is flipped.** Documents count downwards, following SVG; the machine counts upwards.

Fiber and CO2 share one driver with a `source` flag, as galvoplotter does — the difference is a handful of
commands (MO and the Q-switch against FPK), not a different protocol.

## What is still missing

* **Bitmaps cannot be marked at all.** A galvo has no raster format; marking an image means emitting it as
  a dot pattern, which nothing here does.
* **Hatching runs one way only.** Filled shapes are swept with parallel lines (`pyrograph.hatch`), but
  there is no cross-hatch and no offset between passes, so a second pass retraces the first.
* **Nothing is verifiable without hardware.** Field calibration in particular is not something a mock can
  answer, and the mock cannot tell a sensible command list from a nonsensical one.
* **Cloned boards cannot be initialised here.** Boards that report `0x9980` instead of `0x9899` need an
  FPGA image loaded before they answer anything. They are found and named, and the read that fails says
  why — but doing the loading would mean shipping the vendor's firmware blobs or reading a `.sys` driver
  off a Windows install, which is what MeerK40t's `clone_init` does. Use that first; a board it has
  initialised in this power cycle answers here normally.
