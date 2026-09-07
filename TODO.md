# TODO

## Protocol — open questions

- **`0xD0` packet upload.** The Android app uploads via numbered 216-byte packets instead of raw data
  (`docs/protocol.md`). Not implemented. Worth having as a fallback: per-packet checksum, sequence number and
  flow control. It is also the best probe if the device ever refuses transfers again — if packets get through
  while the raw path is refused, that is a real lead instead of a guess.
- **The stuck state.** Once the device refused all file transfers for hours; only a power cycle helped. Cause
  unknown, never reproduced. Preview, `w_state 255`, BLE sessions and transport switching were all ruled out.
- **Line/fill format (`0x40`)** — 6 bytes per line, undecoded. Needed for vector engraving instead of raster.
- **`w_state` semantics** beyond "1 while engraving, 255 after a job, 0 on a fresh boot".
- **Settings write (`0x06`)** is implemented from the LDS code but never sent to a device. Untested.
- **Focus / Z-axis (`0x02` state 6, 11)** untested — moves hardware, so test with care.
- **Firmware update (`0xDD`)** documented, deliberately not implemented.

## Driver

- Dithering runs in pure Python; large images need a vectorised (numpy) path.
- `adjust_levels` uses the conventional brightness/contrast formula; the vendor's arithmetic sits in WASM
  and could not be read, so the two will not match pixel for pixel.
- The dither result differs from the vendor WASM on roughly 30 % of pixels on a grey ramp (same packing,
  different threshold decision). Cosmetic, documented.
- **Unverified on hardware:** the content-derived upload file ID (`file_id_for_raster`). It explains the
  observed failure — the device re-engraved the previous motif because the ID came from the job name and
  the device keeps the file it already has — but the fix itself has only been reasoned about, not run
  against a machine. First engraving of a changed image after a previous one is the test.
- **BLE unverified since the chunk-size fix.** `bleak` was an optional extra and simply not installed, so
  every Bluetooth path died on the import; it is a plain dependency now. The transport also caps its chunk
  at the negotiated ATT MTU instead of always writing 179 bytes — reasoned about, not run against a
  machine. A scan, a `status` and one upload over BLE is the test.
- **No disconnect handling on BLE.** If the link drops, nothing notices: every call waits out its timeout
  and there is no reconnect. `BleakClient` takes a `disconnected_callback` that would make it visible.
- CLI lacks `delete` (file removal) and a way to engrave an already uploaded file ID. `delete_file` is
  built but never sent to a device.
- **Uploaded files accumulate.** Every distinct image leaves a file on the device, and nothing removes it.
  The file-ID query answers in a single 133-byte frame, which holds 31 IDs — the captured reply had exactly
  31, so what happens beyond that, and what the device does when its storage is full, is unknown. Deleting
  the previous upload before sending the next one is the obvious next step, but the delete command is
  untested.
- `MockTransport` answers only what the driver asks for; it is no firmware simulator.
- Only LP2 device data is present; `DeviceProfile` for other models is not filled in.
- **Material data, paper, 20 mm motif at 254 dpi:** power 15 / depth 30 leaves nothing at all; power 30 /
  depth 50 marks a filled area solidly, a 0.1 mm outline barely, a 0.3 mm outline clearly. No other
  material has been measured.

## Application (PyroGraph)

- Document model done: geometry, objects, layers, undo, `.pyg` container, job creation
  (`docs/document-model.md`).
- **Vendor formats.** The plan assumed `.lpb` was the editable project format; it is not. `.lpb` is a baked
  USB-stick export with no importer in the vendor software, and the editable format is `.lp2` (ZIP with
  fabric.js objects). Neither is implemented. `.lpb` export is worth having, `.lp2` import needs a sample
  file to work against. Layout of both is in `docs/document-model.md`.
- SVG import handles shapes, arcs, nested transforms, units and fill/stroke inheritance; `text`, `use`,
  clipping, masks and gradients are skipped and reported. Rounded rectangle corners are ignored.
- **SVG `fill` is not imported.** The model can fill an area now (`DocumentObject.fill`), but the importer
  still turns every shape into an outline. A filled logo therefore comes in hollow.
- No DXF import.
- `stroke-linecap` and `stroke-linejoin` are not read; the rasteriser always draws them round. The
  difference to a butt cap is half a line width, and round is what keeps icon dots alive.
- Filling uses the even-odd rule for every object; SVG's `fill-rule: nonzero` is not honoured. It differs
  only where a path overlaps itself.
- **No spooler.** `LaserDevice.run()` blocks until the job is handed over and the caller polls
  `status()`. A queue with priorities (`docs/architecture.md`) is only worth building once the GUI
  needs to stay responsive.
- **The galvo adapter has never touched hardware.** `packages/ezcad2` and `pyrograph.devices.ezcad2` are
  built from balor and galvoplotter (`docs/galvo.md`), tested against a mock and nothing else. The USB
  transport has never opened a real board, and marking moves a laser — first contact needs the red-light
  framing tried before anything is fired.
- **No hatching.** `build_vector_job` burns outlines only, so a filled shape comes out hollow and a QR
  code is unusable on a galvo. The fill is reported in `VectorJob.skipped` rather than dropped silently,
  but reporting it is not doing it.
- **No way to produce a `.cor` file.** One has to come with the machine; nothing open source can make one
  (`docs/galvo.md`). Worth knowing that MeerK40t got most of the way — test pattern and measurement UI in
  `balormk/gui/corscene.py` — and stopped at the export, so the format is the only part left.
- **The host-side field correction is unproven.** Bilinear inversion of a measured grid, tested against a
  synthetic distortion and never against a real lens. It is off by default and marked experimental.
- **The CLI has no lens settings.** `--galvo` always runs at the 500 galvos/mm default; only the window
  reads the stored correction file. A `--cor-file` flag would fix it.
- **A galvo cannot engrave a bitmap at all.** No dot-pattern output exists, so an image is skipped.
- The LP2 still has no vector path — its line/fill command (`0x40`) is undecoded, so `paths=False` there.
- `TextObject` needs a font file path; no lookup by family name, no kerning.
- Everything else: editor, spooler.

## GUI (`pyrograph-gui`)

- Done: canvas with tools (select/move/scale, line, rectangle, ellipse, polyline, polygon, text, QR,
  barcode), clipboard, align/distribute/mirror/rotate/array, rulers, grid and snapping, layer panel,
  device panel on a worker thread (`docs/gui.md`). Headless tests run on Qt's `offscreen` platform.
- **Never run on hardware:** the wait loop now waits for the device to report *running* before an idle
  reply ends a job. The five-second grace period is a guess — measure how long an LP2 actually takes to
  switch modes after `print_start` and set it from that. A multi-layer document is the test.
- Warnings go through `DeviceWorker.warned` — a missing correction file, geometry a job left out. Only
  the device panel raises them; nothing else in the window has a use for it yet.
- **Settings exist only for the galvo.** `QSettings` now holds the lens data, but nothing else in the
  program is configurable, and there is no general preferences dialog to hang the next thing on.
- **No rotation from the canvas.** Only the menu's 90° steps; there is no rotation handle and no free
  angle. `Transform.rotate` is there, the interaction is not.
- **No node editing** — a path's points cannot be moved once it is drawn. Together with grouping, the
  biggest thing still missing from "editor".
- **Import replaces the document** instead of merging into the open one. Also drops the undo history.
- Objects are drawn but not listed; there is no object tree next to the layer list, and an object's name
  is only visible in the file.
- No layer management: layers cannot be added, renamed, reordered or deleted, and objects cannot be
  moved between them, so `MoveObject` has no GUI at all.
- No properties panel: an object's exact position and size can only be dragged, not typed in.
- Frame runs at power 1, hard-coded, and always traces the whole document, never the selection.
- No focus/Z control, no rotary UI, no device settings dialog — the declarative settings from
  `docs/architecture.md` are not built.
- Engraving hands the worker a deep copy; a second job cannot be queued while one runs (no spooler).
- The device profile is not read by the canvas: the work area comes from the document, so a document
  larger than the machine bed is not flagged.
- Autodetection covers USB only — LaserPecker serial ports and galvo boards; Bluetooth has a Scan button,
  because there is nothing to poll.
- Autodetection only offers what it found; there is no setting for connecting to it straight away.
- Objects can be locked in the model and the GUI honours it, but nothing can *set* the flag — it only
  arrives through a file. A lock toggle needs the object list that does not exist yet.
- The font scan reads every file in the font directories (~2 s on a full desktop) and is only cached for
  the session. A missing family reports itself, but there is no way to pick a file by hand.
- Barcodes carry no human-readable digits underneath, and neither generator draws its quiet zone —
  the clearance has to be kept free by placing the code with room around it.
- Undo/redo have no visible history, and the window has no "revert to saved".
- An image the platform cannot decode is drawn as a red dashed outline, and engraving such a document
  fails the whole job with Pillow's `UnidentifiedImageError` reported as a device error. Refusing the one
  object and burning the rest would be friendlier, but silently dropping geometry from a job needs more
  thought than a `try` around the decode.
- The canvas bed comes from the document, so an SVG larger than the machine draws a work area the LP2
  does not have. The device profile knows the real size and is not consulted.
