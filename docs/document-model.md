# Document model

The layer everything else in `pyrograph` hangs off. It imports neither Qt nor a device driver, which is
what makes it testable without hardware — and what keeps a later GUI change from reaching into the data.

## Rules

* **Millimetres as float, everywhere.** No pixels, no DPI, no device units in the model. The conversion
  happens once, when a job is built.
* **Vectors stay paths.** Rasterising is a property of the job, not of the document.
* **Laser parameters live on the layer**, as in LightBurn and the vendor software. An object inherits the
  settings of the layer it sits in; moving it to another layer is how you change how it burns.
* **Objects store their source, never a derivative.** `ImageObject` keeps the original bitmap; the dither
  result depends on DPI and target size and would degrade a little on every resize.
* **Every mutation goes through a command.** The document is only ever changed through a `Command`, so undo
  cannot silently lose a step.

## Coordinate system

SVG's: x to the right, y **downwards**, origin in the top left of the work area. Rotation angles are
therefore clockwise as seen on screen. Fonts are y-up, so `TextObject` flips the axis when it converts
glyphs to a path; the baseline sits at y = 0.

## Package layout

```
pyrograph/
├── document/
│   ├── geometry.py     Point, Rect, Transform, Path with segments
│   ├── objects.py      DocumentObject, PathObject, ImageObject, TextObject
│   ├── layer.py        Layer, LaserParams
│   ├── document.py     Document — work area and layer stack
│   ├── commands.py     Command, UndoStack and the concrete operations
│   └── serialize.py    .pyg read/write
└── job.py              Document + layer → RasterJob
```

`Transform` is an SVG `matrix(a b c d e f)`; `a.then(b)` applies `a` first. `Path.bounds()` computes the
true extrema of a cubic Bézier rather than the hull of its control points, so a curve never reports a box
larger than it is.

`TextObject` needs a font *file* — there is no lookup by family name, because that requires a font database
and belongs to the GUI. Outlines come from `fontTools`; kerning is not applied, only advance widths.

## The `.pyg` container

```
project.pyg (ZIP)
├── document.svg     geometry — standard SVG, opens in Inkscape
├── project.json     layers, laser parameters, object metadata
└── images/*.png     the original bitmaps, byte for byte
```

**`document.svg` stays valid SVG on its own.** No custom namespace, no foreign attributes — everything of
ours lives in `project.json` and refers to SVG elements by `id`. That keeps the geometry readable by other
tools and our data out of a format that is not ours.

MeerK40t stores SVG with its own namespace: good for interoperability, awkward for the LP2's main use case,
because a large photo has to be base64-inlined into XML. Keeping bitmaps as separate ZIP members avoids
that without giving up the standard geometry.

One duplication follows from the rule and is worth knowing: a `TextObject` appears in the SVG as its glyph
outline, so other tools render it correctly, while `project.json` keeps the editable text, font and size.
On reading, the JSON wins and the outline is regenerated.

Two consequences of the current implementation:

* The container's own reader only accepts what its writer emits — absolute `M`, `L`, `C`, `Z`. Foreign SVG
  goes through the importer below instead, which is deliberately a separate piece of code: a reader that
  has to cope with arcs and nested transforms has no business constraining the writer.
* `preview.png` is not written. Nothing consumes it yet; a reader ignores unknown members anyway.

## Importing foreign SVG

`pyrograph.document.import_svg(source)` reads someone else's SVG into a document with one layer and
returns an `SvgImport` — the document plus the tag names it did not understand, so nothing disappears
without a trace.

Units are the point of the exercise. `width`/`height` give the physical size, `viewBox` gives the
coordinate system, and the ratio between them is the scale. Without a `viewBox`, user units are CSS pixels
(1 px = 1/96 in); without any size at all, the content defines the work area. Group transforms are
composed and baked into the coordinates, so after an import everything is plain millimetres.

Understood: `path` (the full grammar — relative commands, shorthands, elliptical arcs), `rect`, `circle`,
`ellipse`, `line`, `polyline`, `polygon`, `image` (data URI or a file next to the SVG), and `g` nesting.

Elements that draw nothing are dropped: `display="none"`, `visibility="hidden"`, and anything whose
effective `fill` and `stroke` are both `none`. `fill`/`stroke` are inherited from the root and from groups,
because icon sets ship an invisible full-canvas path as a bounding box — engraving it would burn a
rectangle around the motif.

Not understood, and reported in `skipped`: `text` (would need to resolve a font by family name — the GUI's
job), `use`, clipping, masks, gradients. Rounded rectangle corners are ignored.

## Job creation

`pyrograph.job.build_raster_job(document, layer_index)` is the only place where millimetres become pixels.
The layer's DPI decides the raster size, the layer's bounding box decides the origin, the layer's parameters
ride along unchanged. Paths are stroked at the layer's `line_width_mm` — a laser follows outlines, it does
not fill them. Vector output waits for the line/fill command (`0x40`) to be decoded.

The stroke width matters more than it looks. Measured on paper at power 30: a filled area comes out solid
black, the same settings with a 0.1 mm hairline are barely visible, and 0.3 mm is clearly legible. In a
filled patch neighbouring rows reinforce each other; a single-pixel line gets exactly one pass.

At 254 dpi one millimetre is exactly ten pixels, which makes the numbers easy to check against a hardware
run: 15 mm is 150 px, an origin of 40 mm is `nx = 400`.

## Why not the vendor formats natively

The vendor software has two of them, and neither fits.

**`.lp2`** is the editable project: a ZIP whose payload is serialised **fabric.js** objects, with parameters
in LaserPecker vocabulary (`lightSource`, `precision`, `dpi/px`, `materialKey`). A program meant for more
than one device family would carry that coupling around forever.

**`.lpb`** is not a project file at all — see below.

## `.lpb` is an export, not a document

Read out of Design Space 2.12.1: `.lpb` is a flat binary produced by *Export as LPB*, meant to be run from
a USB stick. There is no importer — the vendor software opens `lp`, `lp2`, `svg`, `dxf`, gcode and images,
and `.lpb` is not among them.

Layout, as far as the exporter shows:

```
"LPDT"                  magic, 4 bytes
uint16 header length
  version               1 byte
  bound x, y            2 bytes each, tenths of a millimetre
  bound width, height   2 bytes each, tenths of a millimetre
  file count            1 byte
  mode                  1 byte   0 normal, 1 third axis, 2 rotary, 3 slide, 4 multi-file, 5 cart, 6 pen
  firmware version      4 bytes
then per file:
  uint16 header length
    data length         4 bytes
    power               1 byte
    speed level         1 byte   stored as 101 − depth, the same inversion as on the wire
    light source        1 byte
    passes              1 byte
    object diameter     2 bytes, hundredths of a millimetre
    precision           1 byte
    frequency           1 byte
    speed               2 bytes, mm/s
  the command frame (the same encoding the device receives) followed by the payload
```

So the content is a **baked raster plus parameters**, the same bytes that go over the wire — no editable
geometry. Importing one can therefore only ever yield a bitmap and its settings, never the objects that
produced it. Export is the useful direction; the editable exchange format is `.lp2`.
