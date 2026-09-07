# Architecture

**Inspired by [MeerK40t](https://github.com/meerk40t/meerk40t)** (MIT) — the layering below (connection,
driver, spooler, device profile), queue priorities and declarative device settings are taken as *concepts*
from that project. No code was copied.

Two packages in one repository:

| Package | PyPI | Depends on |
| --- | --- | --- |
| `laserpecker` | driver — protocol, transports, imaging. No GUI, no device registry. | pyserial, bleak, numpy |
| `ezcad2` | driver — BJJCZ LMC galvo boards. No GUI, no device registry. | pyusb |
| `pyrograph` | GUI — editor, device abstraction, adapters | laserpecker, ezcad2, PySide6 |

The driver stays usable on its own. Whoever only wants to script an LP2 should not inherit an abstraction layer.

## Layers

```
GUI  ──►  Spooler  ──►  Driver  ──►  Connection  ──►  device
          queue         commands     serial/BLE/mock
```

* **Connection** — moves bytes. Interchangeable, including a mock for development without hardware.
* **Driver** — turns a device-independent job into device commands. One per device family.
* **Spooler** — job queue. Keeps the GUI responsive; the file-transfer handshake alone may block for minutes.
* **Device** — profile and configuration: work area, DPI steps, laser types, capabilities.

## Job model

Two device families exist and an abstraction must serve both:

| | Streaming (GRBL, Ruida, K40, galvo) | Upload (LaserPecker) |
| --- | --- | --- |
| Flow | host sends motion commands continuously | job is uploaded, device runs it alone |
| Format | vector paths / G-code / command list | bitmap + header |
| Progress | host counts what it has sent | ask the device |
| Abort | stop the stream | send a command |

A galvo looks like an upload device — it takes a command list in 3 KB blocks — but it starts executing that
list while the rest is still arriving (`docs/galvo.md`). There is no moment where the job belongs to the
machine and the host is free, which is what `DeviceProfile.streams` marks.

A job therefore carries **raster and paths as equals** — as two job types rather than one with two optional
halves, since no device runs both and a job that carries the wrong one is a mistake worth catching:

```python
RasterJob(raster, x_mm, y_mm, dpi, params)      # dithered bitmap and where it goes
VectorJob(polylines, bounds, params, skipped)   # flattened outlines in document millimetres
```

`build_raster_job` and `build_vector_job` both build from the document; neither converts the other. The
caller asks `profile.raster` which one the machine wants.

`VectorJob.skipped` names what could not be expressed — a bitmap has no outline, and a filled shape burns
as an outline only, because hatching is not implemented. Reporting that beats dropping geometry silently.

MeerK40t routes everything through a streaming vocabulary (`LineCut`, `RasterCut`, …) and lets upload devices
buffer internally. That fits a K40; it fits the LP2 badly, whose native format *is* the raster.

## Device interface

```python
class LaserDevice(Protocol):
    profile: DeviceProfile
    def status() -> DeviceStatus         # normalised: offline | idle | running | paused | error
    def frame(bounds, power)             # trace the bounding box
    def run(job, name, progress)         # returns once the device has taken the job
    def pause() / resume() / abort() / close()
```

`run` deliberately does not return a handle: it blocks until the device has taken the job over, and progress
is read back from `status()`. Whoever wants to wait decides where the waiting happens — a CLI polls, a GUI
will let the spooler do it.

For a machine with `profile.streams` set there is no earlier moment to return at than the end of the job, so
`run` returns only once it is finished and there is nothing left to poll. The caller reads the flag rather
than guessing; both the CLI and the device panel skip their wait loop for such a device.

`DeviceProfile` holds work area, DPI steps and capability flags (raster, paths, rotary, autofocus, streams).
The GUI reads it instead of hard-coding device knowledge; `nearest_dpi()` snaps a layer's resolution to a
step the machine actually has.

Two things follow from serving more than one device family, and both are load-bearing:

* **A driver may answer "I don't know".** `DeviceStatus.progress` is `None` where no percentage exists — a
  galvo controller reports busy or ready and nothing in between. Reporting that as `0` would be a lie the
  GUI cannot see through; it draws a busy bar instead of a stalled one.
* **The normalised state carries a device-specific word alongside it.** `DeviceStatus.state` is the same
  five words everywhere, `message` is whatever that machine calls its sub-state ("held", "door open", an
  error text). The GUI prints it and never branches on it. MeerK40t splits this the same way, into a major
  and a minor state.

Adapters live in `pyrograph.devices`: `laserpecker.py` and `ezcad2.py`. The second one is what made the
interface honest — it forced out the assumptions that only held for an LP2 (a percentage always exists, a
job is handed over before it runs, every machine has DPI steps). If the interface keeps holding, it can
become its own package.

## Developing without hardware

`laserpecker.transport.MockTransport` is a device that only exists in memory. It answers the queries the
driver sends, accepts an upload and then advances a progress counter until the job reports itself finished,
so the whole chain — document, job, adapter, driver — runs and is testable with no engraver attached. Both
CLIs expose it as `--mock`. It is not a firmware simulator: anything the driver does not ask for is
answered with a plain acknowledgement.

## Priority in the queue

Jobs carry a priority. While the queue is paused, only priority > 0 runs — that is how "resume" and "abort"
get through a halted queue. Taken from MeerK40t's `hold_work(priority)`.

## Declarative device settings

Per-device settings are described as data (attribute, type, default, label, section), and the settings dialog
is generated from that. A new device then needs no new GUI code. MeerK40t does the same with its "choices"
system.

## What we deliberately do not copy

* **Kernel/service/console system.** MeerK40t ships a small operating system with a global registry and
  string commands (`device add lhystudios`). Powerful for seven device families, hard to type-check and to
  test. Out of proportion here.
* **CutCode as the only intermediate format** — see above.

MeerK40t is MIT licensed and could legally be reused in this GPL-3.0 project. We take the concepts, not the
code: ideas are not copyrightable, so no attribution obligation arises. Credit where due — the architecture
below is informed by reading it.
