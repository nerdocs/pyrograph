# PyroGraph

Laser engraving software for Linux, macOS and Windows. Draw a job, place it on the bed, burn it.

Built for the **LaserPecker 2**, on top of the [`laserpecker`](https://pypi.org/project/laserpecker/)
driver. The protocol is the same across LP1–LP5.

![The PyroGraph window](https://raw.githubusercontent.com/nerdocs/pyrograph/main/docs/screenshot.png)

## Why

The vendor's desktop software is Windows and macOS only, so on Linux all you get is the phone app — a bad
way to place a motif to the millimetre. And engraving happens over a cable, between a PC and a machine on
the desk: it does not need an account or an internet connection. PyroGraph talks to the engraver and to
nothing else.

## What it does

- Draw lines, rectangles, ellipses, polylines and polygons
- Import SVG
- Place text, QR codes and barcodes
- Move, scale, align, distribute, mirror, rotate, duplicate as a grid
- Layers, each with its own power, depth, speed and resolution
- Trace the outline to line up the workpiece, then engrave

## Use

```bash
pip install pyrograph
pyrograph-gui
```

There is a command line too, and a mock device that only exists in memory, so the whole chain runs without
hardware:

```bash
pyrograph import drawing.svg drawing.pyg
pyrograph --mock engrave drawing.pyg
```

Serial access on Linux needs membership in the `dialout` group; the CH340 driver is in-kernel.

## Status

Reading the device and engraving both work on real hardware, over USB and over Bluetooth. SVG to engraved
workpiece runs end to end.

Missing: node editing, grouping, rotating from the canvas, a job queue and device settings. The full list
is in [`TODO.md`](https://github.com/nerdocs/pyrograph/blob/main/TODO.md).

## Safety

The laser fires when you frame or engrave. Wear the goggles, do not leave a running job unattended, and
keep the Stop button within reach.

## More

Source, documentation and the protocol specification:
[github.com/nerdocs/pyrograph](https://github.com/nerdocs/pyrograph)

GPL-3.0-or-later.
