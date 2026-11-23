#!/usr/bin/env python3
"""Poll an AlorAir HD55 over CAN and decode replies for both protocol variants.

Raspberry Pi (CANable already up as can0):
    python3 hd55_probe.py
Mac (CANable with stock slcan firmware):
    python3 hd55_probe.py --slcan /dev/tty.usbmodemXXXX --bitrate 50000
Listen only (never transmit):
    add --no-poll

Variant A replies on 0x123 (temp in byte 3, status in byte 5).
Variant B replies on 0x3B0 (temp in byte 2, status in byte 4).
Some units reply on 0x123 at 125 kbps with the B byte layout (see
docs/protocol.md): pass --layout b to decode 0x123 that way.
"""
import argparse
import time

import can


def decode_b(d):
    # bit 0 = on, bit 1 = compressor, bit 3 = continuous, bit 4 = draining
    flags = [name for bit, name in ((0, "on"), (1, "comp"), (3, "cont"), (4, "drain"))
             if d[4] >> bit & 1]
    return (f"[B] RH={d[0]}% set={d[1]}% temp={d[2]}C "
            f"b4={d[4]:08b} ({','.join(flags) or '-'})")


def decode(msg, layout):
    d = msg.data
    if len(d) < 8:
        return None
    if msg.arbitration_id == 0x123:
        if layout == "b":
            return decode_b(d)
        return (f"[A] RH={d[0]}% set={d[1]}% temp={d[3]}C "
                f"b5={d[5]:08b} b6={d[6]:08b}")
    if msg.arbitration_id == 0x3B0:
        return decode_b(d)
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--channel", default="can0", help="SocketCAN interface (Linux)")
    p.add_argument("--slcan", help="serial port for slcan (Mac), e.g. /dev/tty.usbmodem1234")
    p.add_argument("--bitrate", type=int, default=50000, help="slcan only: 50000 or 125000")
    p.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    p.add_argument("--poll", default="0000000000000000", help="poll payload as 16 hex chars")
    p.add_argument("--no-poll", action="store_true", help="listen only, send nothing")
    p.add_argument("--layout", choices=("a", "b"), default="a",
                   help="byte layout for replies on 0x123 (0x3B0 is always b)")
    a = p.parse_args()

    if a.slcan:
        bus = can.Bus(interface="slcan", channel=a.slcan, bitrate=a.bitrate)
    else:
        bus = can.Bus(interface="socketcan", channel=a.channel)

    poll = can.Message(arbitration_id=0x123, data=bytes.fromhex(a.poll),
                       is_extended_id=False)
    next_poll = 0.0
    try:
        while True:
            now = time.monotonic()
            if not a.no_poll and now >= next_poll:
                bus.send(poll)
                print(f"{time.strftime('%H:%M:%S')} TX 123#{a.poll}")
                next_poll = now + a.interval
            msg = bus.recv(timeout=0.2)
            if msg is None:
                continue
            line = f"{time.strftime('%H:%M:%S')} RX {msg.arbitration_id:03X}#{msg.data.hex()}"
            decoded = decode(msg, a.layout)
            print(f"{line}   {decoded}" if decoded else line)
    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
