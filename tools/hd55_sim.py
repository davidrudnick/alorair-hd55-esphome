#!/usr/bin/env python3
"""Pretend to be an AlorAir HD55 on a CAN bus, for bench-testing the T-CAN485.

Behaves like the 125 kbps / reply-on-0x123 unit in docs/protocol.md:
  - replies to an all-zeros poll on 0x123 with
    [RH, setpoint, temp, 0, status, 0, 0, 0] on 0x123
    status: bit 0 power, bit 1 compressor, bit 3 continuous
  - 0x123 [N+128, 0...]  sets the setpoint; N <= 35 means continuous mode
    (the setpoint byte then reads 34)
  - 0x123 [0, 0, 0x01, 0...] toggles power
  - the compressor runs when on and (continuous or RH > setpoint), but never
    within --comp-delay seconds of last stopping
Any other frame is logged as UNKNOWN and ignored.

Usage on the Pi (can0 already up at 125 kbps):
    python3 hd55_sim.py
Change conditions while it runs by writing JSON to ~/hd55_sim.cmd, e.g.
    echo '{"rh": 55}'        > ~/hd55_sim.cmd
    echo '{"silent": true}'  > ~/hd55_sim.cmd   # stop replying (link-loss test)
Keys: rh, temp, setpoint, power, cont, silent. The file is applied and removed.
"""
import argparse
import json
import os
import time

import can

CMD_FILE = os.path.expanduser("~/hd55_sim.cmd")


class Unit:
    def __init__(self, rh, setpoint, temp, comp_delay):
        self.rh = rh
        self.setpoint = setpoint
        self.temp = temp
        self.power = True
        self.cont = False
        self.silent = False
        self.comp = False
        self.comp_delay = comp_delay
        self.comp_allowed_at = 0.0
        self.update(time.monotonic())

    def update(self, now):
        want = self.power and (self.cont or self.rh > self.setpoint)
        if want and not self.comp and now >= self.comp_allowed_at:
            self.comp = True
            log("compressor START")
        elif not want and self.comp:
            self.comp = False
            self.comp_allowed_at = now + self.comp_delay
            log(f"compressor STOP (restart allowed in {self.comp_delay:.0f}s)")

    def reply(self):
        status = (self.power << 0) | (self.comp << 1) | (self.cont << 3)
        sp = 34 if self.cont else self.setpoint
        return bytes([self.rh, sp, self.temp, 0, status, 0, 0, 0])

    def command(self, d):
        if d[0] >= 0x80 and not any(d[1:]):
            n = d[0] - 128
            if n <= 35:
                self.cont = True
                log(f"setpoint {n} -> CONTINUOUS on")
            else:
                self.cont = False
                self.setpoint = n
                log(f"setpoint -> {n} (continuous off)")
            return True
        if d == bytes([0, 0, 1, 0, 0, 0, 0, 0]):
            self.power = not self.power
            log(f"POWER toggled -> {'ON' if self.power else 'OFF'}")
            return True
        return False

    def apply_file(self):
        try:
            with open(CMD_FILE) as f:
                changes = json.load(f)
            os.remove(CMD_FILE)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log(f"bad {CMD_FILE}: {e}")
            try:
                os.remove(CMD_FILE)
            except OSError:
                pass
            return
        for k, v in changes.items():
            if k in ("rh", "temp", "setpoint"):
                setattr(self, k, int(v))
            elif k in ("power", "cont", "silent"):
                setattr(self, k, bool(v))
            else:
                log(f"ignored unknown key {k!r}")
        log(f"applied {changes}")


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--channel", default="can0")
    p.add_argument("--interface", default="socketcan", help="python-can interface (virtual for testing)")
    p.add_argument("--rh", type=int, default=41)
    p.add_argument("--setpoint", type=int, default=38)
    p.add_argument("--temp", type=int, default=19)
    p.add_argument("--comp-delay", type=float, default=180.0,
                   help="seconds the compressor waits after stopping (real unit: 180)")
    a = p.parse_args(argv)

    unit = Unit(a.rh, a.setpoint, a.temp, a.comp_delay)
    bus = can.Bus(interface=a.interface, channel=a.channel)
    log(f"simulating HD55 on {a.channel}: RH {a.rh}, setpoint {a.setpoint}, "
        f"temp {a.temp}, compressor delay {a.comp_delay:.0f}s")
    try:
        while True:
            msg = bus.recv(timeout=0.5)
            unit.apply_file()
            unit.update(time.monotonic())
            if msg is None:
                continue
            d = bytes(msg.data)
            line = f"RX {msg.arbitration_id:03X}#{d.hex()}"
            if msg.arbitration_id != 0x123 or len(d) != 8:
                log(line + "   (ignored: not 0x123/8 bytes)")
                continue
            if not any(d):
                if unit.silent:
                    log(line + "   poll (SILENT, no reply)")
                    continue
                out = unit.reply()
                bus.send(can.Message(arbitration_id=0x123, data=out, is_extended_id=False))
                log(line + f"   poll -> TX 123#{out.hex()}")
            elif unit.command(d):
                unit.update(time.monotonic())
            else:
                log(line + "   UNKNOWN command, ignored")
    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
