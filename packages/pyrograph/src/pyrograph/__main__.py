"""Command line for pyrograph.

The window is its own executable (``pyrograph-gui``); the subcommands below drive the same document model
and device abstraction from a terminal, so the chain SVG → document → job → laser stays scriptable and
testable end to end. ``--mock`` runs it all against a device that only exists in memory.
"""

from __future__ import annotations

import argparse
import sys
import time

from .devices import DeviceState, GalvoAdapter, LaserDevice, LaserPeckerDevice
from .document import import_svg, load_pyg, save_pyg
from .job import build_raster_job, build_vector_job


def _open_device(args) -> LaserDevice:
    if args.galvo:
        return _open_galvo(args)
    if args.mock:
        return LaserPeckerDevice.mock()
    from laserpecker.device import LaserPecker
    from laserpecker.transport import BleTransport

    return LaserPeckerDevice(LaserPecker(BleTransport(args.ble)) if args.ble else LaserPecker())


def _open_galvo(args) -> LaserDevice:
    """A galvo with the lens it was told about.

    The scale belongs to the physical lens, so a correction file is worth more than a flag: it carries the
    scale it was calibrated at, and it is what straightens the field. ``--galvos-per-mm`` overrides it for
    a machine that arrived without a file.
    """
    from ezcad2 import GalvoDevice, Lens, MockTransport, read_scale

    scale = args.galvos_per_mm
    if scale is None and args.cor_file:
        try:
            scale = read_scale(args.cor_file)
        except (OSError, ValueError, IndexError) as error:
            print(f"could not read the scale from {args.cor_file}: {error}", file=sys.stderr)
    if scale is None:
        scale = 500.0
        print(
            "no lens given, assuming 500 galvos/mm — the job will be the wrong size unless that is "
            "your machine (see --cor-file)",
            file=sys.stderr,
        )

    lens = Lens(galvos_per_mm=scale, cor_file=args.cor_file)
    transport = MockTransport() if args.mock else None
    return GalvoAdapter(GalvoDevice(transport, source=args.source, lens=lens))


def _wait(device: LaserDevice, label: str) -> None:
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
    kind = f"dpi {profile.dpi_steps}" if profile.dpi_steps else "vectors, no fixed resolution"
    print(f"{profile.name}: {profile.width_mm:.1f}x{profile.height_mm:.1f} mm, {kind}")
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
        if device.profile.raster:
            job = build_raster_job(document, index)
        else:
            job = build_vector_job(document, index)
        if job is None:
            continue
        print(f"layer {layer.name!r}: {_describe(job)}")
        for note in getattr(job, "skipped", ()):
            print(f"  not engraved: {note}", file=sys.stderr)
        if args.dry_run:
            continue
        device.run(job, name=f"{args.name}-{index}", progress=_upload_progress)
        print()
        if not device.profile.streams:
            # See DeviceProfile.streams: a streaming machine is already done here, nothing left to poll.
            _wait(device, f"layer {layer.name!r}")
    device.close()
    return 0


def _describe(job) -> str:
    """One line about what a job holds — the two kinds measure themselves differently."""
    if hasattr(job, "raster"):
        return f"{job.raster.width}x{job.raster.height} px at {job.dpi} dpi"
    points = sum(len(line) for line in job.polylines)
    return f"{len(job.polylines)} outlines, {points} points, {job.bounds.width:.1f}x{job.bounds.height:.1f} mm"


def _upload_progress(done: int, total: int) -> None:
    print(f"\rsending {done * 100 // total}%", end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyrograph", description="Design, position and engrave")
    parser.add_argument("--mock", action="store_true", help="use a device that only exists in memory")
    parser.add_argument("--ble", help="connect over BLE to this address or name instead of USB")
    parser.add_argument(
        "--galvo", action="store_true", help="talk to an EZCad2 galvo controller instead of a LaserPecker"
    )
    galvo = parser.add_argument_group("galvo", "which lens is fitted — see docs/galvo.md")
    galvo.add_argument("--cor-file", help="lens correction file (.cor), as supplied with the machine")
    galvo.add_argument(
        "--galvos-per-mm",
        type=float,
        help="scale of the fitted lens; read from --cor-file when that is given",
    )
    galvo.add_argument(
        "--source", choices=("fiber", "co2"), default="fiber", help="which laser is in the machine"
    )
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
