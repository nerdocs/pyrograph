# pyrograph

Open laser engraving software for Linux, macOS and Windows — design a job, place it on the bed, burn it.

Reference device: **LaserPecker 2**, firmware 3.16. The protocol is shared across LP1–LP5, and the device
abstraction is built so other engravers can be added.

## Why this exists

**Nothing drove the machine on Linux.** The vendor ships desktop software for Windows and macOS only. What
is left is a phone app, which is a poor way to place a motif on a workpiece to the millimetre.

**Engraving is local work.** A cable, a machine on the desk, a file that never has to leave the room.
Software for that should not need an account or a network connection, and with a closed-source app there is
no way to check what it does with the drawing you feed it. Not being able to answer that question is reason
enough to prefer something whose source you can read. pyrograph talks to the engraver over USB or Bluetooth
and to nothing else — there is no telemetry, no update check, no account.

## What it does

`pyrograph-gui` opens an editor: draw and place objects, import SVG, generate QR codes and barcodes, arrange
everything on the bed, then frame the outline and engrave. Vector geometry stays geometry until the job is
built, so a code or a glyph is as sharp as the resolution allows.

Two packages in one repository:

| Package | What it is |
| --- | --- |
| [`laserpecker`](packages/laserpecker) | Driver library: protocol, transports, imaging. No GUI. |
| [`pyrograph`](packages/pyrograph) | The application: document model, devices, GUI, CLI. |

The driver is usable on its own — `laserpecker status`, `laserpecker engrave image.png` — if all you want
is to push a bitmap at the machine from a script. `pyrograph` has a command line of its own for the
document side: `import`, `frame`, `engrave`.

## Status

The read path is verified on real hardware over both USB and Bluetooth, and engraving works over both. SVG
to engraved workpiece runs end to end.

Not there yet: node editing, grouping, rotation from the canvas, a job spooler, device settings, and merging
an import into the open document. See [`TODO.md`](TODO.md) for the gaps, including the parts of the protocol
that are still guesses.

## Install

```bash
uv sync
uv run pyrograph-gui
```

Connecting the machine — cables, ports, permissions — is in [`docs/connection.md`](docs/connection.md).

**No engraver?** There is a mock device that only exists in memory, so the whole chain runs without
hardware — `--mock` on the command line, "Mock (no hardware)" in the window's connection box:

```bash
uv run pyrograph import drawing.svg drawing.pyg
uv run pyrograph --mock engrave drawing.pyg
uv run pytest
```

## Documentation

[`docs/`](docs/) holds the protocol specification, the connection guide, the architecture and the document
model. [`docs/protocol.md`](docs/protocol.md) is the one to read if you are here for the machine rather than
for the editor — framing, commands, replies and the file upload, with the open questions marked as open.

## How it was built

The protocol was reverse engineered from LaserPecker Design Space 2.12.1. The encoder produces frames that
are byte-identical to the vendor's, and the read path and engraving were confirmed on an LP2 over both USB
and Bluetooth. What has *not* been run against a machine is marked as such, in the documentation and in
`TODO.md`, because a plausible guess and a measurement are not the same thing. Decompiling for
interoperability is permitted in the EU (Art. 6 Software Directive, § 40e öUrhG).

The code was written with [Claude Code](https://claude.com/claude-code): reading captured frames, arguing
about the layering, and hunting the bugs that only appear once a machine is at the other end of the cable.
Worth saying plainly rather than leaving for someone to notice — it says something about how the code reads,
and nothing about who maintains it.

## Credits

The layered device architecture — connection, driver, spooler, device profile — is **inspired by
[MeerK40t](https://github.com/meerk40t/meerk40t)** (MIT), which supports K40, GRBL, Ruida, Moshiboard,
NewlyDraw and JCZ galvo lasers. No code was taken from it; the concepts were, and credit belongs to that
project. If your laser is not a LaserPecker, go there first.

## Licence

GPL-3.0-or-later.
