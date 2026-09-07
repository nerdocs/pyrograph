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

Without a correction file a blank table is written and the field is geometrically wrong. LightBurn generates
one from a nine-point calibration; there is no way to derive it from the machine.

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

* **Filled shapes come out hollow.** Hatching is not implemented, so `build_vector_job` burns the outline
  and reports the fill in `VectorJob.skipped`. A QR code is unusable this way — it is all fill.
* **Bitmaps cannot be marked at all.** A galvo has no raster format; marking an image means emitting it as
  a dot pattern, which nothing here does.
* **`galvos_per_mm` and the correction file cannot be guessed.** Both belong to the physical lens.
  `ezcad2.correction.read_scale` gets the scale out of a `.cor` file; there is no GUI for either yet, so
  they can only be passed in code.
* **Nothing is verifiable without hardware.** Field calibration in particular is not something a mock can
  answer, and the mock cannot tell a sensible command list from a nonsensical one.
