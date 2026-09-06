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
- CLI lacks `delete` (file removal) and a way to engrave an already uploaded file ID.
- `MockTransport` answers only what the driver asks for; it is no firmware simulator.
- Only LP2 device data is present; `DeviceProfile` for other models is not filled in.
- **Material data, paper, 20 mm motif at 254 dpi:** power 15 / depth 30 leaves nothing at all; power 30 /
  depth 50 marks a filled area solidly, a 0.1 mm outline barely, a 0.3 mm outline clearly. No other
  material has been measured.

## Application (pyrograph)

- Document model done: geometry, objects, layers, undo, `.pyg` container, job creation
  (`docs/document-model.md`).
- **Vendor formats.** The plan assumed `.lpb` was the editable project format; it is not. `.lpb` is a baked
  USB-stick export with no importer in the vendor software, and the editable format is `.lp2` (ZIP with
  fabric.js objects). Neither is implemented. `.lpb` export is worth having, `.lp2` import needs a sample
  file to work against. Layout of both is in `docs/document-model.md`.
- SVG import handles shapes, arcs, nested transforms, units and fill/stroke inheritance; `text`, `use`,
  clipping, masks and gradients are skipped and reported. Rounded rectangle corners are ignored.
- **No scale/move operations.** An imported icon is a few millimetres wide and there is no command to
  resize it — only the editor will bring that.
- No DXF import.
- `stroke-linecap` and `stroke-linejoin` are not read; the rasteriser always draws them round. The
  difference to a butt cap is half a line width, and round is what keeps icon dots alive.
- **Scaling must scale `stroke_width_mm` with the geometry.** There is no scale operation yet, so every
  caller does it by hand — the first one that forgets gets a hairline on a large motif.
- **No spooler.** `LaserDevice.run()` blocks until the job is handed over and the caller polls
  `status()`. A queue with priorities (`docs/architecture.md`) is only worth building once the GUI
  needs to stay responsive.
- Only the LP2 profile exists; `pyrograph.devices` has no second adapter to prove the interface.
- `TextObject` needs a font file path; no lookup by family name, no kerning.
- Everything else: editor, spooler.

## GUI (`pyrograph-gui`)

- First slice done: canvas, layer panel with laser parameters, device panel on a worker thread
  (`docs/gui.md`). Headless tests run on Qt's `offscreen` platform.
- **No object editing.** The canvas is read-only — no selection, no move, no scale, no rotate. That needs
  the missing model commands first (see "No scale/move operations" above).
- **Import replaces the document** instead of merging into the open one. Also drops the undo history.
- Objects are drawn but not named or listed; there is no object tree next to the layer list.
- No layer management: layers cannot be added, renamed, reordered or deleted, and objects cannot be
  moved between them, so `MoveObject` has no GUI at all.
- Frame runs at power 1, hard-coded. No focus/Z control, no rotary UI, no device settings dialog —
  the declarative settings from `docs/architecture.md` are not built.
- Engraving hands the worker a deep copy; a second job cannot be queued while one runs (no spooler).
- The device profile is not read by the canvas: the work area comes from the document, so a document
  larger than the machine bed is not flagged.
- BLE connects by name or address typed by hand; `scan_ble()` exists but there is no scan dialog.
