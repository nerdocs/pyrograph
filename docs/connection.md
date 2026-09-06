# Connecting

Two transports, same protocol. USB is faster and more reliable, BLE needs no cable.

## USB-C

**Use a USB-A-to-USB-C cable.** C-to-C does not work: the CH340 behind the port has no CC pull-down
resistors, so neither side takes the host role and the device never enumerates. A USB-A port is always host.

**The data port is on the power/control block**, not on the laser head — the USB-C socket between the two
`OUT 5V 2A` sockets and `IN 12V 5A`.

| | |
| --- | --- |
| Bridge chip | CH340 (`1a86:7523`) — newer units: CH9102 (`1a86:55d4`) |
| Baud rate | 460800, 8N1, no flow control |
| Device node | `/dev/ttyUSB0` (CH340) or `/dev/ttyACM0` (CH9102 via `cdc_acm`) |

### Linux

The `ch341` driver is in-tree and loads automatically. It does **not** claim the CH9102 (`1a86:55d4`) —
that one appears as `/dev/ttyACM*`. If it enumerates but no node appears:

```bash
sudo modprobe usbserial vendor=0x1a86 product=0x55d4
```

Serial access requires the `dialout` group:

```bash
sudo usermod -aG dialout $USER   # log out and back in
```

### Checking

```bash
lsusb | grep 1a86        # device present at all?
ls /dev/ttyUSB* /dev/ttyACM*
laserpecker ports
```

If `lsusb` shows nothing, it is the cable or the port — no driver issue.

## Bluetooth LE

The device advertises as `LaserPecker-II<mac-suffix>`, e.g. `LaserPecker-IIAABBCC`. The suffix is the last
three octets of its MAC; the BLE address has the first octet incremented by one.

| | |
| --- | --- |
| Service | `49535343-fe7d-4ae5-8fa9-9fafd205e455` (Microchip transparent UART) |
| Write | `49535343-8841-43f4-a8d4-ecbe34729bb3`, without response |
| Notify | `49535343-1e4d-4bd9-ba61-23c647249616` |
| Chunk size | 179 bytes, 100 ms apart |

```bash
laserpecker ports --ble-scan
laserpecker --ble DD:0D:30:AA:BB:CC status
```

No pairing needed. Replies may arrive split across several notifications — collect until the checksum
validates.

## Which link is active

Byte 24 of the status reply: `1` when only BLE is connected, `2` whenever USB is plugged in (USB wins if
both are).

## Firmware

LDS requires LP2 firmware ≥ 3.14 / 3.58 / 3.74. Older firmware answers fewer queries; states 7, 8, 9 and 11
are silently ignored on 3.16.
