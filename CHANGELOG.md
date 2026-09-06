# Changelog

## 0.1.0 — unreleased

- Protocol specification reverse engineered from LaserPecker Design Space 2.12.1 (`docs/protocol.md`).
- Frame encoder/decoder, command builders and reply parsers; frames verified byte-identical to the vendor encoder.
- Serial (CH340, 460800 baud) and Bluetooth LE transports with a shared blocking interface.
- Floyd-Steinberg dithering and 1-bit/8-bit raster packing for engraving jobs.
- High-level device API: status, version, preview, focus, raster upload, engrave, progress polling.
- `laserpecker` CLI with ports, info, status, files, preview, stop and engrave commands.
- Read path verified on an LP2 (firmware 3.16) over USB and BLE; captured replies kept as test fixtures.
- Status byte 24 identified as the active-link indicator (1 = Bluetooth, 2 = USB).
- Engraving verified end to end on hardware: dither, upload, print start, motif on the workpiece.
- Documented a device state where all file transfers are refused; cause unknown, cleared by a power cycle.
- Frame reader splits several frames arriving in one read instead of discarding the trailing ones.
- Replies are matched by function code, so unsolicited acknowledgements are no longer mistaken for answers.
- Two-package layout: `laserpecker` (driver) and `pyrograph` (GUI), architecture inspired by MeerK40t.
- Documented the Android app's alternative upload method (`0xD0` packet frames) and its extra function codes.
- Status mode 1 identified as "engraving"; engraving verified over Bluetooth as well as USB.
- BLE transport closes on garbage collection — a leaked connection stops the device from advertising.
- Document model in `pyrograph`: geometry, objects, layers with laser parameters — millimetres, no Qt, no device.
- Undo/redo through commands; the document is only ever changed through one.
- Native `.pyg` container: standard SVG for geometry, JSON for parameters, original bitmaps kept lossless.
- Job creation turns a layer into a dithered raster at its own DPI, with the origin in device pixels.
- `.lpb` identified as a baked USB-stick export, not a project format; the editable vendor format is `.lp2`.
- SVG import: shapes, full path grammar including arcs, nested transforms, units and inline images.
- Brightness and contrast before dithering, so a photograph can be brought into a burnable range.
- `laserpecker dither` writes the dithered result as a PNG, to judge the settings without a device.
- `MockTransport`: an in-memory device that answers queries, takes uploads and runs a job to completion.
- Device abstraction in `pyrograph.devices`: profile, normalised status, and the LaserPecker adapter.
- `pyrograph` CLI: import an SVG, show the device, frame a document and engrave it, with `--mock`.
- SVG import drops invisible elements, so an icon's bounding-box path is no longer engraved.
