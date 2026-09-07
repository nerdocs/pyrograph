# ezcad2

An open control library for galvo laser markers built around a **BJJCZ LMC controller** — the boards the
vendor's EZCad2 software drives. Fiber and CO2, over USB.

## Status

**Nothing here has been run against hardware.** No machine was available. The protocol was read from two
existing implementations — [balor](https://gitlab.com/bryce15/balor), which reverse engineered it from USB
captures, and [galvoplotter](https://github.com/meerk40t/galvoplotter), which rewrote it — and this is an
independent implementation of what those two agree on.

Treat every table below as "should be right", not "is right". The packet building is unit-tested against a
mock board; nothing else is proven.

| Area | State |
| --- | --- |
| Packet encoding, unit conversion | unit-tested, no hardware |
| Command list buffering and execution | unit-tested against a mock, no hardware |
| USB transport | written, never opened a real device |
| Correction file (`.cor`) reading | unit-tested against generated files, no vendor file |
| Marking, red-light framing | **unverified — this moves a laser** |
| Fiber MO / Q-switch, CO2 FPK | unverified |

## Scope

**EZCad3 and BSL controllers are not supported.** They speak a different protocol, no open reverse
engineering of it exists, and LightBurn's implementation is closed. Supporting them means starting from USB
captures against real hardware — a separate driver, not a flag in this one.

**Cloned boards** — the ones reporting `0x9980` — are found and named, but they need an FPGA image loaded
before they answer, and doing that would mean shipping the vendor's firmware. Load it with MeerK40t's
`clone_init` first; after that they work here like any other board, until the machine is powered off.

Also not implemented, because nothing here needs them yet: on-the-fly marking, the Z axis, rotary axes,
general GPIO, wobble and 3D slicing.

## Use

```python
from ezcad2 import GalvoDevice, Lens, MarkParams

device = GalvoDevice(lens=Lens(galvos_per_mm=500.0, cor_file="lens_110.cor"))
square = [[(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)]]

device.light(square)          # trace it with the red pointer
input("position the workpiece, then press enter")
device.stop_light()

device.mark(square, MarkParams(power=40, speed_mm_s=500, frequency_khz=30))
device.close()
```

Coordinates are millimetres from the centre of the field, which is where a galvo's origin actually is.

`GalvoDevice.mock()` gives an in-memory board that answers queries and runs a job to completion, so the
chain can be exercised with no laser attached.

## The two numbers you cannot guess

`galvos_per_mm` and the correction table both belong to the physical lens. A wrong scale marks the right
shape at the wrong size; a missing correction table marks a distorted field. `ezcad2.correction.read_scale`
reads the scale out of a `.cor` file, which is the only place it can come from short of measuring a test
burn.

## Licence

GPL-3.0-or-later. Protocol facts are not copyrightable and no code was copied from either project read;
balor is GPL-3.0 and galvoplotter is MIT, so either would have been compatible anyway.
