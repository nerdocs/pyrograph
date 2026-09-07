"""Command line for pyrograph.

The window is its own executable (``pyrograph-gui``); the subcommands below drive the same document model
and device abstraction from a terminal, so the chain SVG → document → job → laser stays scriptable and
testable end to end. ``--mock`` runs it all against a device that only exists in memory.
"""

from __future__ import annotations

import argparse
import sys
import time

from .devices import DeviceState, LaserPeckerDevice
from .document import import_svg, load_pyg, save_pyg
from .job import build_raster_job


def _open_device(args) -> LaserPeckerDevice:
    if args.mock:
        return LaserPeckerDevice.mock()
    from laserpecker.device import LaserPecker
    from laserpecker.transport import BleTransport

    return LaserPeckerDevice(LaserPecker(BleTransport(args.ble)) if args.ble else LaserPecker())


def _wait(device: LaserPeckerDevice, label: str) -> None:
    while True:
        status = device.status()
        if status.state is DeviceState.ERROR:
            raise SystemExit(f"device error: {status.message}")
        if status.state is not DeviceState.RUNNING:
            print(f"\r{label} done      ")
            return
        done = "" if status.progress is None else f" {status.progress}%"
        print(f"\r{label}{done}", end="", flush=True)
        time.sleep(0.5)


def cmd_import(args) -> int:
    result = import_svg(args.input)
    save_pyg(result.document, args.output)
    objects = sum(len(layer.objects) for layer in result.document.layers)
    print(f"{args.output}: {objects} objects, {result.document.width_mm}x{result.document.height_mm} mm")
    if result.skipped:
        print(f"skipped, not understood: {', '.join(result.skipped)}", file=sys.stderr)
    return 0


def cmd_info(args) -> int:
    device = _open_device(args)
    profile, status = device.profile, device.status()
    print(f"{profile.name}: {profile.width_mm}x{profile.height_mm} mm, dpi {profile.dpi_steps}")
    print(f"state: {status.state.value} {status.message}".rstrip())
    device.close()
    return 0


def cmd_frame(args) -> int:
    document = load_pyg(args.file)
    bounds = document.bounds()
    if bounds is None:
        raise SystemExit("nothing to frame — the document is empty")
    device = _open_device(args)
    print(f"tracing {bounds.width:.1f}x{bounds.height:.1f} mm at ({bounds.x:.1f}, {bounds.y:.1f})")
    device.frame(bounds, args.power)
    device.close()
    return 0


def cmd_engrave(args) -> int:
    document = load_pyg(args.file)
    device = _open_device(args)
    for index, layer in enumerate(document.layers):
        if not layer.visible:
            continue
        layer.params.dpi = device.profile.nearest_dpi(layer.params.dpi)
        job = build_raster_job(document, index)
        if job is None:
            continue
        print(f"layer {layer.name!r}: {job.raster.width}x{job.raster.height} px at {job.dpi} dpi")
        if args.dry_run:
            continue
        device.run(job, name=f"{args.name}-{index}", progress=_upload_progress)
        print()
        if not device.profile.streams:
            # See DeviceProfile.streams: a streaming machine is already done here, nothing left to poll.
            _wait(device, f"layer {layer.name!r}")
    device.close()
    return 0


def _upload_progress(done: int, total: int) -> None:
    print(f"\rupload {done * 100 // total}%", end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyrograph", description="Design, position and engrave")
    parser.add_argument("--mock", action="store_true", help="use a device that only exists in memory")
    parser.add_argument("--ble", help="connect over BLE to this address or name instead of USB")
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("import", help="convert an SVG into a .pyg document")
    convert.add_argument("input")
    convert.add_argument("output")
    convert.set_defaults(func=cmd_import)

    sub.add_parser("info", help="show the device profile and state").set_defaults(func=cmd_info)

    frame = sub.add_parser("frame", help="trace the document's bounding box with the laser")
    frame.add_argument("file")
    frame.add_argument("--power", type=int, default=1)
    frame.set_defaults(func=cmd_frame)

    engrave = sub.add_parser("engrave", help="engrave every visible layer of a .pyg document")
    engrave.add_argument("file")
    engrave.add_argument("--name", default="pyrograph", help="job name stored on the device")
    engrave.add_argument("--dry-run", action="store_true", help="build the jobs but do not send them")
    engrave.set_defaults(func=cmd_engrave)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
