# The GUI

Qt Widgets (PySide6), started with `pyrograph-gui [file.pyg]`. The first slice shows a document and runs it
on a machine; editing objects on the canvas comes later.

```
┌──────────────────────────────────────────────────────────┐
│ File   Edit   View                                       │
├───────────────┬──────────────────────────┬───────────────┤
│ Layers        │                          │ Connection    │
│ ☑ Outline (2) │      ┌──────────┐        │  Mock / USB   │
│ ☑ Photo (1)   │      │  motif   │        │  / Bluetooth  │
│               │      └──────────┘        │ ───────────── │
│ Laser params  │        work area         │ Job           │
│  power, depth │       (grid: 10 mm)      │  ● idle       │
│  passes,speed │                          │  Frame        │
│  dpi, line w. │                          │  Engrave      │
│               │                          │  Pause  Abort │
└───────────────┴──────────────────────────┴───────────────┘
```

## Where things live

| Module | Does |
| --- | --- |
| `gui/window.py` | Owns the document and the undo stack; menus, files, dirty state |
| `gui/canvas.py` | The work area as a `QGraphicsScene`, one scene unit = one millimetre |
| `gui/layers.py` | Layer list with visibility, laser parameters of the selected layer |
| `gui/device.py` | Connecting, framing, engraving — on a worker thread |

Qt is confined to `pyrograph.gui`. Everything below it (`document`, `job`, `devices`) stays importable
without a display, which is what keeps the chain scriptable from the CLI and testable without hardware.

## The canvas

The scene is measured in millimetres, y downwards, exactly like the document model — no conversion, so the
view's scale is the only zoom factor and a 0.4 mm stroke is drawn 0.4 units wide. Paths keep their Bézier
curves (`QPainterPath.cubicTo`), and strokes get round caps and joins because that is how the rasteriser
draws them: what you see is the width that will burn.

The scene is rebuilt wholesale after every change. For the object counts an engraving document has that is
cheap, and it leaves no view state that could drift away from the model.

Mouse: wheel zooms, drag pans, `Ctrl+0` fits the work area.

## Editing

Every change goes through the undo stack, including layer visibility — a hidden layer is not engraved, so
hiding one is an edit, not a view setting. Parameter edits are applied when a field loses focus or Enter is
pressed, so typing "60" leaves one undo step behind instead of two.

The window applies the change, redraws and marks the document unsaved in one place; panels never write to
the document themselves. A canvas and a layer list that each edit the model on their own is how the two
start disagreeing about what is in the file.

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

Selecting, moving and scaling objects; a spooler for queued jobs; device settings; merging an import into
the open document instead of replacing it. See `TODO.md`.
