"""Command line front-end — mainly a probe for verifying the protocol against real hardware."""

from __future__ import annotations

import argparse
import sys

from . import protocol as p
from .device import LP2_DPI, LaserPecker
from .transport import BleTransport, MockTransport, SerialTransport, list_serial_ports, scan_ble


def _connect(args) -> LaserPecker:
    if args.mock:
        return LaserPecker(MockTransport())
    if args.ble:
        return LaserPecker(BleTransport(args.ble))
    return LaserPecker(SerialTransport(args.port))


def cmd_ports(args) -> int:
    ports = list_serial_ports()
    if ports:
        print("\n".join(ports))
    else:
        print("no LaserPecker serial port found")
        print("(the USB-C data port sits on the power/control block, not on the laser head)")
    if args.ble_scan or not ports:
        print("scanning for Bluetooth devices ...")
        found = scan_ble()
        for address, name in found:
            print(f"{address}  {name}")
        if not found:
            print("no LaserPecker found on Bluetooth (the device only advertises while it is switched on)")
    return 0


def cmd_files(args) -> int:
    with _connect(args) as device:
        ids = device.file_ids()
        print(f"{len(ids)} file(s) stored on the device")
        for file_id in ids:
            print(f"  0x{file_id:08x}")
    return 0


def cmd_info(args) -> int:
    with _connect(args) as device:
        info = device.info()
        print(f"software version: {info.sw_version}")
        print(f"hardware version: {info.hw_version}")
        if info.name:
            print(f"name:             {info.name}")
        if info.mac:
            print(f"mac:              {info.mac}")
    return 0


def cmd_status(args) -> int:
    with _connect(args) as device:
        status = device.status()
        try:
            mode = p.WorkMode(status.mode).name.lower()
        except ValueError:
            mode = f"unknown ({status.mode})"
        print(f"mode:        {mode}")
        print(f"work state:  {status.w_state}")
        print(f"progress:    {status.rate}%")
        print(f"power/depth: {status.laser}/{status.speed}")
        print(f"temperature: {status.temp}")
        print(f"error:       {status.error_text}")
    return 0


def cmd_preview(args) -> int:
    with _connect(args) as device:
        device.preview(args.x, args.y, args.width, args.height, args.power)
        print("preview running — press Enter to stop")
        input()
        device.preview_stop()
    return 0


def cmd_stop(args) -> int:
    with _connect(args) as device:
        device.stop()
    return 0


def cmd_engrave(args) -> int:
    from PIL import Image

    image = Image.open(args.image)
    with _connect(args) as device:
        def show(done: int, total: int) -> None:
            print(f"\rupload {done * 100 // total}%", end="", flush=True)

        device.engrave_image(
            image,
            x_mm=args.x,
            y_mm=args.y,
            width_mm=args.width,
            power=args.power,
            depth=args.depth,
            times=args.times,
            px=args.px,
            packed=args.packed,
            brightness=args.brightness,
            contrast=args.contrast,
            name=args.name,
            progress=show,
        )
        print()
        device.wait_until_done(lambda s: print(f"\rengraving {s.rate}%", end="", flush=True))
        print("\ndone")
    return 0


def cmd_dither(args) -> int:
    """Render what the device would burn, without a device — for judging brightness and contrast."""
    from PIL import Image

    from .imaging import image_to_raster, raster_to_image

    raster = image_to_raster(
        Image.open(args.image),
        args.width,
        LP2_DPI[args.px],
        brightness=args.brightness,
        contrast=args.contrast,
    )
    raster_to_image(raster).save(args.output)
    print(f"{args.output}: {raster.width}x{raster.height} px")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="laserpecker", description="Control a LaserPecker engraver")
    parser.add_argument("--port", help="serial port (default: first CH340 found)")
    parser.add_argument("--ble", help="connect over BLE to this address or name instead")
    parser.add_argument("--mock", action="store_true", help="use a device that only exists in memory")
    sub = parser.add_subparsers(dest="command", required=True)

    ports = sub.add_parser("ports", help="list connectable devices")
    ports.add_argument("--ble-scan", action="store_true", help="also scan for BLE devices")
    ports.set_defaults(func=cmd_ports)

    sub.add_parser("info", help="show firmware and hardware version").set_defaults(func=cmd_info)
    sub.add_parser("status", help="show the working status").set_defaults(func=cmd_status)
    sub.add_parser("files", help="list file IDs stored on the device").set_defaults(func=cmd_files)
    sub.add_parser("stop", help="leave the current mode").set_defaults(func=cmd_stop)

    preview = sub.add_parser("preview", help="trace a rectangle with the laser")
    preview.add_argument("--x", type=float, default=0.0)
    preview.add_argument("--y", type=float, default=0.0)
    preview.add_argument("--width", type=float, default=20.0)
    preview.add_argument("--height", type=float, default=20.0)
    preview.add_argument("--power", type=int, default=1)
    preview.set_defaults(func=cmd_preview)

    engrave = sub.add_parser("engrave", help="dither an image and engrave it")
    engrave.add_argument("image")
    engrave.add_argument("--x", type=float, default=0.0)
    engrave.add_argument("--y", type=float, default=0.0)
    engrave.add_argument("--width", type=float, default=30.0, help="physical width in mm")
    engrave.add_argument("--power", type=int, default=30, help="laser power 1-100")
    engrave.add_argument("--depth", type=int, default=50, help="burn depth 1-100")
    engrave.add_argument("--times", type=int, default=1)
    engrave.add_argument("--px", type=int, choices=sorted(LP2_DPI), default=4)
    engrave.add_argument("--packed", action="store_true", help="send 1 bit per pixel")
    engrave.add_argument("--brightness", type=float, default=0.0, help="-100..100, applied before dithering")
    engrave.add_argument("--contrast", type=float, default=0.0, help="-100..100, applied before dithering")
    engrave.add_argument("--name", default="claude")
    engrave.set_defaults(func=cmd_engrave)

    preview_dither = sub.add_parser("dither", help="write the dithered result as a PNG, without engraving")
    preview_dither.add_argument("image")
    preview_dither.add_argument("output")
    preview_dither.add_argument("--width", type=float, default=30.0, help="physical width in mm")
    preview_dither.add_argument("--px", type=int, choices=sorted(LP2_DPI), default=4)
    preview_dither.add_argument("--brightness", type=float, default=0.0, help="-100..100")
    preview_dither.add_argument("--contrast", type=float, default=0.0, help="-100..100")
    preview_dither.set_defaults(func=cmd_dither)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
