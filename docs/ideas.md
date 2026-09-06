# Ideas

Features worth having, none of them decided. Most are inspired by [MeerK40t](https://github.com/meerk40t/meerk40t)
and filtered for what makes sense on an upload device whose native format is a raster. `TODO.md` holds what is
missing from what exists; this file holds what does not exist yet at all.

## Editing

- **Node editor** — drag path points and their Bézier handles, add/remove points, convert corner ↔ smooth. The one
  tool that turns an importer into an editor.
- **Boolean path operations** — union, difference, intersection, exclusive or. Needs a clipping library
  (`pyclipper`, MIT), because doing it correctly is a research project of its own.
- **Offset / inset** — grow or shrink an outline by a distance. Same library, and what you want for a cut allowance.
- **Hatch fill** — fill an area with parallel lines at an angle and spacing instead of a raster. Only worth building
  once the line/fill command (`0x40`) is decoded; until then the raster path is the only way to fill anything.
- **Group / ungroup** — a group as a real object with its own transform, not a selection that forgets itself.
- **Guides** — draggable guide lines that objects snap to.
- **Measure tool** — click two points, read the distance. Trivial next to the rest, and constantly useful.

## Generating

- **Vectorise an image** — trace a bitmap into paths (`potrace`). Turns a logo screenshot into something scalable.
- **Living hinge** — the slit patterns that make plywood bend. A parameterised generator, popular in laser circles.
- **Box / finger joint generator** — a box with tabbed sides from three measurements and the material thickness.
- **Serial numbers and word lists** — objects carrying placeholders (`{serial}`, `{name}`) plus a list of values, so
  one job engraves n different pieces. Together with the QR and barcode generators this is what makes labelling real.
- **Wobble / dot patterns** — the effect operations MeerK40t applies to a path before it is sent.

## Images

- Brightness, contrast, gamma and inversion in the GUI. The driver's `adjust_levels` already does the work.
- A choice of dithering method (Floyd–Steinberg, ordered, halftone, threshold) per image, with a live preview.
- Halftone / screen angle for photographic motifs — a laser resolves dots better than grey.

## Job and device

- **Spooler** — the queue from `docs/architecture.md`: several jobs, priorities, a running one that can be paused
  while the next is prepared. The architecture is designed for it; nothing is built.
- **Simulation and time estimate** — show the dithered result and how long it will burn *before* uploading. Worth
  most on the LP2, where the upload alone takes minutes.
- **Material library** — power, depth, passes and speed per material and thickness, applied to a layer with one
  click. The paper measurements in `TODO.md` would be the first entry.
- **Placements / repeat positions** — engrave the same motif at n positions on the bed without duplicating objects.
- **Registration marks** — align a workpiece that was moved or is being engraved a second time.
- **Camera** — a webcam over the bed showing the workpiece under the design. MeerK40t does the perspective
  correction from four markers.
- **Focus and rotary UI** — the driver has the commands (`0x02` states), nothing exposes them. Untested hardware
  moves, so this wants care.
- **Device settings dialog generated from data** — the declarative settings described in `docs/architecture.md`.

## Files

- **`.lpb` export** — the baked format the vendor writes to a USB stick, so a job can be engraved without a host.
- **`.lp2` import** — the vendor's editable project format, once a sample file exists to work against.
- **DXF import** — the format CAD hands out.
- **Recent files**, and reopening the last document on start.

## View

- Zoom presets (fit, 100 %, to selection), an overview thumbnail.
- Dark canvas / high-contrast mode for a workshop screen.
- Show the machine's origin and travel direction on the bed, the way MeerK40t draws its red and green axes.
