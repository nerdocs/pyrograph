# The GUI

Qt Widgets (PySide6), started with `pyrograph-gui [file.pyg]`.

```
┌──────────────────────────────────────────────────────────────────────┐
│ File  Edit  Modify  View                                             │
│ Open Save │ Cut Copy Paste Delete │ Undo Redo │ Frame Engrave        │
├───┬───────────────┬──────────────────────────────┬───────────────────┤
│ ▶ │ Layers        │  0    20    40    60    80   │ Connection        │
│ ✋│ ☑ Codes (5)   │ ┌────────────────────────┐   │  Mock / USB / BLE │
│ ╱ │ ☑ Photo (1)   │0│  ▣▣  ▌▌▌▌▌▌▌▌         │   │ ───────────────── │
│ ▭ │               │ │                       │   │ Job               │
│ ○ │ Laser params  │2│  ┌──▫────▫──┐         │   │  ● idle           │
│ ∿ │  power, depth │0│  ▫  selected ▫        │   │  Frame            │
│ ⬠ │  passes,speed │ │  └──▫────▫──┘         │   │  Engrave          │
│ T │  dpi, line w. │4│                       │   │  Pause   Abort    │
│ ▩ │               │0└────────────────────────┘   │                   │
│ ▌▌│               │                              │                   │
├───┴───────────────┴──────────────────────────────┴───────────────────┤
│                                    24.5  18.0 mm │ 1 selected 40 × 24 mm │
└──────────────────────────────────────────────────────────────────────┘
```

## Where things live

| Module | Does |
| --- | --- |
| `gui/window.py` | Owns the document, the undo stack and the clipboard; menus, toolbars, files |
| `gui/canvas.py` | The work area as a `QGraphicsScene`, the selection, snapping |
| `gui/tools.py` | What a press and a drag mean — one class per mouse mode |
| `gui/rulers.py` | Millimetre scales, and the widget that puts them around the canvas |
| `gui/layers.py` | Layer stack and the laser parameters of the selected layer |
| `gui/device.py` | Connecting, framing, engraving — on a worker thread |
| `gui/arrange.py` | Align, distribute, mirror, rotate, array — each returns a command |
| `gui/dialogs.py` | Text, QR code, barcode, array |
| `gui/icons.py` | The tool pictograms, drawn rather than shipped |
| `gui/fonts.py` | Family name → font file, which Qt does not tell us |

Qt is confined to `pyrograph.gui`. Everything below it (`document`, `job`, `devices`, `codes`) stays
importable without a display, which is what keeps the chain scriptable from the CLI and testable without
hardware.

## One way in

Every change to the document is a `Command` and goes through `MainWindow.apply`. The canvas does not write
to the model — it emits `edit_requested`, and the window executes, redraws and marks the file unsaved in
one place. A canvas and a layer list that each edit the model on their own is how the two start disagreeing
about what is in the file.

That is also why a drag is *previewed* rather than applied: while the mouse is down, the Qt items are moved
about; on release, one `CommandGroup` describes the whole thing. Moving three objects is one undo step.

## Tools

| Tool | What it does |
| --- | --- |
| Select | Click to select, Shift-click to add, drag to move, drag a handle to scale, drag the background to rubber-band select. Shift while scaling a corner keeps the proportions |
| Pan | Drag the view |
| Line, Rectangle, Ellipse | Drag out the shape |
| Polyline, Polygon | Click point after point; double-click or Enter finishes, Escape discards |
| Text | Click, then choose the content, family and height |
| QR code, Barcode | Click, then enter the content and size |

Adding a tool is a class in `gui/tools.py` and one line in `build_tools()` — the canvas has no branch per
tool. A tool only receives millimetres and asks the canvas for a preview, a ghost outline or an edit.

## Scaling scales the stroke

A `TransformObject` multiplies the object's own `stroke_width_mm` by the transform's scale factor. Without
that, enlarging a motif turns a solid outline into a hairline: the geometry grows, the ink does not.
Objects that leave their width to the layer keep leaving it to the layer.

## Snapping

Snapping pulls to whatever is closer, within six screen pixels: the drawn grid, or another object's left,
centre and right edge (top, middle, bottom vertically). Both can be switched off in the View menu, and the
grid spacing is the same number that is drawn — what you see is what you snap to.

When a selection is dragged, it is the selection's *corner* that snaps, not the pointer: the corner is what
has to sit on the line, and the pointer grabbed the object somewhere in the middle.

## Filled areas

`DocumentObject.fill` burns the enclosed area instead of the outline, combining subpaths with the even-odd
rule — that is what puts the hole into an "o" and the light modules into a QR code. A filled object with no
stroke width of its own is not stroked at all, the same as SVG's `stroke: none`; adding the layer's outline
to a code would fatten every module by a line width.

The rasteriser draws each subpath in its own bounding box and XORs it into a mask, so a symbol made of four
hundred small squares does not cost four hundred full-size images.

## Codes

`pyrograph.codes` turns text into a filled path, not a bitmap: a code is rectangles, and keeping it as
geometry means it stays sharp at any size and any resolution. Adjacent dark modules are merged into runs.

Neither generator draws a quiet zone. A code needs light margin — four module widths for a QR code, ten for
a barcode — and on a workpiece that margin is simply unburnt material.

## Text needs a file, Qt has none

`TextObject` converts text to outlines with fontTools and therefore needs a font *file*. Neither
`QFontDatabase` nor `QRawFont` exposes a path, so `gui/fonts.py` scans the platform's font directories once
and reads each file's family name. The scan is lazy and cached — about a second, and nothing at all until
the text tool is used. Alias families ("Sans Serif") are resolved through Qt's own matching first.

## The device, off the GUI thread

Every driver call blocks: connecting waits for a handshake, an upload runs for minutes. They all run on
`DeviceWorker`, which lives on its own `QThread`; the panel only emits signals at it and displays what
comes back.

The worker stays a *single* thread on purpose — a serial port or a BLE session tolerates exactly one
writer. While a job runs, the worker's wait loop calls `processEvents()` between two status polls, so
*pause* and *abort* are handled on that same thread instead of racing the transport from the GUI thread.

Engraving hands the worker a deep copy of the document. Rasterising a large image takes seconds, and this
way it happens on the worker thread while the document stays editable.

An idle device is polled once a second; while a job runs, the wait loop reports the state instead.

## Not there yet

Node editing, rotation from the canvas, grouping, a spooler, device settings, merging an import into the
open document. See `TODO.md` for the gaps and `docs/ideas.md` for what could come.
