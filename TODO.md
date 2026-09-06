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
- Only LP2 device data is present; `DeviceProfile` for other models is not filled in.

## Application (pyrograph)

- Document model done: geometry, objects, layers, undo, `.pyg` container, job creation
  (`docs/document-model.md`).
- **Vendor formats.** The plan assumed `.lpb` was the editable project format; it is not. `.lpb` is a baked
  USB-stick export with no importer in the vendor software, and the editable format is `.lp2` (ZIP with
  fabric.js objects). Neither is implemented. `.lpb` export is worth having, `.lp2` import needs a sample
  file to work against. Layout of both is in `docs/document-model.md`.
- SVG import handles shapes, arcs, nested transforms and units; `text`, `use`, clipping, masks and
  gradients are skipped and reported. Rounded rectangle corners are ignored.
- No DXF import.
- `TextObject` needs a font file path; no lookup by family name, no kerning.
- Everything else: editor, device abstraction, spooler, GUI.
