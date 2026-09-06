# Architecture

**Inspired by [MeerK40t](https://github.com/meerk40t/meerk40t)** (MIT) — the layering below (connection,
driver, spooler, device profile), queue priorities and declarative device settings are taken as *concepts*
from that project. No code was copied.

Two packages in one repository:

| Package | PyPI | Depends on |
| --- | --- | --- |
| `laserpecker` | driver — protocol, transports, imaging. No GUI, no device registry. | pyserial, bleak, numpy |
| `pyrograph` | GUI — editor, device abstraction, adapters | laserpecker, PySide6 |

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

| | Streaming (GRBL, Ruida, K40) | Upload (LaserPecker, galvo) |
| --- | --- | --- |
| Flow | host sends motion commands continuously | job is uploaded, device runs it alone |
| Format | vector paths / G-code | bitmap + header |
| Progress | host knows the position | ask the device |
| Abort | stop the stream | send a command |

A job therefore carries **raster and paths as equals**, and the driver picks what it can execute:

```python
@dataclass
class Job:
    raster: Raster | None       # dithered bitmap, position, DPI
    paths: list[Path] | None    # vectors
    params: JobParams           # power, depth, speed, repetitions
```

MeerK40t routes everything through a streaming vocabulary (`LineCut`, `RasterCut`, …) and lets upload devices
buffer internally. That fits a K40; it fits the LP2 badly, whose native format *is* the raster.

## Device interface

```python
class LaserDevice(Protocol):
    profile: DeviceProfile
    def status() -> DeviceStatus         # normalised: idle | running | error, progress
    def frame(bounds, power)             # trace the bounding box
    def run(job: Job) -> JobHandle
    def pause() / resume() / abort()
```

`DeviceProfile` holds work area, DPI steps, laser types and capability flags (raster, vectors, rotary,
autofocus, camera). The GUI reads it instead of hard-coding device knowledge.

Adapters live in `pyrograph.devices`; `laserpecker.py` first, `grbl.py` later. If the interface proves itself,
it can become its own package.

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
