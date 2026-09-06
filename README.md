# pyrograph

Open laser engraving software for Linux, macOS and Windows — because the vendor's software is Windows/macOS
only and the mobile app is painful to use.

Two packages in one repository:

| Package | PyPI | What it is |
| --- | --- | --- |
| [`laserpecker`](packages/laserpecker) | `laserpecker` | Driver library: protocol, transports, imaging. No GUI. |
| [`pyrograph`](packages/pyrograph) | `pyrograph` | The application: document model, devices, GUI, CLI. |

Reference device: **LaserPecker 2**, firmware 3.16. The protocol is shared across LP1–LP5, and the device
abstraction is designed so other engravers can be added.

## Status

The driver's read path is verified on real hardware over both USB and Bluetooth; engraving works over both.
The application has a document model, SVG import, job creation, a device abstraction and a command line —
SVG to engraved workpiece runs end to end. `pyrograph-gui` opens an editor: draw and place objects,
generate QR codes and barcodes, arrange them on the bed and engrave.

Developing without an engraver: both CLIs take `--mock`, which drives a device that only exists in memory.

See [`docs/`](docs/) for the protocol specification, connection guide and architecture.

## Development

```bash
uv sync
uv run pytest
uv run laserpecker ports
```

## Credits

The layered device architecture — connection, driver, spooler, device profile — is **inspired by
[MeerK40t](https://github.com/meerk40t/meerk40t)** (MIT), which supports K40, GRBL, Ruida, Moshiboard, NewlyDraw
and JCZ galvo lasers. No code was taken from it; the concepts were, and credit belongs to that project.

The protocol was reverse engineered from LaserPecker Design Space 2.12.1. Decompiling for interoperability is
permitted in the EU (Art. 6 Software Directive, § 40e öUrhG).

## Licence

GPL-3.0-or-later.
