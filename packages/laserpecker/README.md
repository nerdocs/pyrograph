# laserpecker

An open control library for LaserPecker laser engravers — because the vendor's software is Windows/macOS only
and the Android app is painful to use.

Target device: **LaserPecker 2**. The protocol is shared across the LP1–LP5 range, so other models should work
with adjusted device limits.

## Status

Tested on real hardware (LP2, firmware 3.16) over both USB and Bluetooth: reading the device works, and
engraving runs end to end — dither, upload, print start, motif on the workpiece.

| Area | State |
| --- | --- |
| Frame encoding / checksums | byte-identical to LDS 2.12.1, confirmed on device |
| Status, version, MAC, file list | **verified on hardware**, both transports |
| Serial transport (CH340, 460800) | **verified** |
| BLE transport | verified, but not re-run since the chunk-size fix |
| Preview (frame) and stop | **verified** |
| Raster upload + engrave | **verified end to end** |
| Upload file ID from image content | reasoned about, not yet re-run on a machine |
| Focus / Z-axis, settings write | implemented, **untested** — moves hardware |
| Vector / G-code jobs | not implemented |

The full list of what is still a guess is in
[`TODO.md`](https://github.com/nerdocs/pyrograph/blob/main/TODO.md).

## How it was obtained

LaserPecker Design Space 2.12.1 for Windows is an Electron app. Its renderer bundle contains the complete
command layer in readable JavaScript, and the image pipeline as a WebAssembly module that can be executed
directly. The specification —
[`docs/protocol.md`](https://github.com/nerdocs/pyrograph/blob/main/docs/protocol.md) — comes from reading
that code and running the WASM against synthetic images; the machine then confirmed it.

Decompiling for interoperability is explicitly permitted in the EU (Art. 6 Software Directive, § 40e öUrhG).

## Install

```bash
uv sync                 # or: pip install -e "."
```

Serial access on Linux needs membership in the `dialout` group; the CH340 driver is in-kernel.

## Use

```bash
laserpecker ports                      # find the device
laserpecker info                       # firmware / hardware version
laserpecker status                     # mode, progress, errors
laserpecker preview --width 30 --height 20
laserpecker engrave logo.png --width 40 --power 30 --depth 50
```

```python
from PIL import Image
from laserpecker import LaserPecker

with LaserPecker() as lp:
    print(lp.info())
    lp.engrave_image(Image.open("logo.png"), x_mm=10, y_mm=10, width_mm=40)
    lp.wait_until_done(lambda s: print(s.rate, "%"))
```

Bluetooth instead of USB:

```python
from laserpecker import LaserPecker, BleTransport

lp = LaserPecker(BleTransport("LP2-"))
```

## Safety

The laser fires on `preview` and `engrave`. Wear the goggles, do not leave a running job unattended, and keep
`stop` within reach — it is the same `0xFF` command the app uses.

## Layout

```
src/laserpecker/
    protocol.py           frames, commands, reply parsers
    transport.py          serial + BLE
    imaging.py            dithering and bit packing
    device.py             high-level API
    cli.py
tests/
```
