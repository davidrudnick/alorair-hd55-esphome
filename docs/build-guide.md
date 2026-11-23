# Monitoring an AlorAir Sentinel HD55 with a LilyGo T-CAN485 and Home Assistant

A step-by-step guide compiled from the Home Assistant community thread
("Automate Alorair Sentinel HD55 dehumidifier", topic 306084), the tinymicros
protocol wiki, and the working ESPHome configs posted by jjhuff, dw4417,
disruptivepatternmat, and kern2011.

It uses a **Makerbase CANable 2.0 (USB-CAN adapter) on a Raspberry Pi 3
Model B** as a diagnostic tool. The CANable lets you *measure* things the
thread mostly had to *guess*: which protocol variant your unit speaks, whether
the T-CAN485 is actually transmitting, and what's really on the wire.

The "this unit" sections describe the author's HD55, which turned out to be a
hybrid of the forum variants; [protocol.md](protocol.md) has the measured
details.

---

## 1. How this works (read first)

The HD55's RJ45 "remote control" jack is not Ethernet. It's a CAN bus. The
factory remote and the dehumidifier exchange 8-byte CAN frames over it. The
T-CAN485 is an ESP32 dev board with an onboard CAN transceiver, so it can
impersonate the remote: poll the unit and decode the replies into Home
Assistant sensors via ESPHome.

**Critical fact: there are two protocol variants in the field**, and you won't
know which one your unit speaks until you try.

| | **Variant A ("old", tinymicros)** | **Variant B ("new", ~2023+ units)** | **This unit (measured 2026-11-07)** |
|---|---|---|---|
| Bit rate | 50 kbps | 125 kbps | **125 kbps** |
| Unit replies on CAN ID | 0x123 | 0x3b0 | **0x123** |
| Reply layout | byte0=RH, byte1=setpoint, byte3=temp °C, byte5=status bits | byte0=RH, byte1=setpoint, byte2=temp °C, byte4=status | **B layout** |
| Reported by | jjhuff (HDi65S), several HD55s | dw4417 (HD55, serial S38, Apr 2023), kern2011 (HD55) | this guide's Phase A |

**This unit is a hybrid:** Variant B's bit rate and byte layout, but it
replies on Variant A's ID (0x123). First capture, confirmed against the front
panel: `123#2926130003000000` = 41% RH, 38% setpoint, 19 °C, status `0x03`
(on + compressor running). It answered the all-zeros poll immediately, and
the HD55 measured 110 Ω across CAN-H/CAN-L, so **it has a built-in
terminator**. Configs from the forum will not work unmodified; use "This
unit" in §9.

One forum member's HD55 made April 2023 with a serial starting "S38" was the
125 kbps / new variant; older units and at least one HDi65S were 50 kbps / old
variant.

The unit appears to mostly stay quiet until something talks to it, so the
poller sends a frame on ID 0x123 every few seconds and the unit replies. Note
that in Variant A the poll and the reply share ID 0x123, which makes the two
directions hard to tell apart from ESPHome logs alone. The CANable shows you
both sides.

### Where the CANable fits

The original approach was "flash the T-CAN485, look at logs, toggle settings
until something works." With three unknowns stacked up (bit rate, T-CAN485
GPIO quirks, wiring), a silent log could mean any of them. The CANable takes
those unknowns apart:

| Phase | Hardware on the bus | What it answers |
|---|---|---|
| **A. Identify** (§6) | HD55 + CANable | Which variant, bit rate, and byte layout *your* unit uses |
| **B. Bench test** (§7) | T-CAN485 + CANable (no HD55) | Is the T-CAN485 transmitting? Does ESPHome decode correctly? |
| **C. Install** (§11) | HD55 + T-CAN485 + CANable tap | Live view of both directions while you troubleshoot |
| **D. Control** (§14, optional) | HD55 + CANable | Test command frames by hand before automating them |

By the time you flash the T-CAN485 you already know the right config, and you
know the board works.

---

## 2. Parts list

- **LilyGo T-CAN485** (ESP32 + CAN transceiver + RS485; you only use the CAN side)
- **Makerbase CANable 2.0** (USB-to-CAN adapter; diagnostic tool)
- **Raspberry Pi 3 Model B** (1 GB) booting from an **external USB SSD**, with
  a 5 V / 2.5 A micro-USB supply (the official one is ideal, since the Pi also
  powers the SSD). More than enough for this; CAN at 50–125 kbps is a trivial
  load. It has built-in **2.4 GHz-only Wi-Fi**, so it can sit in the crawlspace
  on Wi-Fi if your 2.4 GHz signal reaches; otherwise use Ethernet or headless
  logging to a file (§6.5).
- **One sacrificial Ethernet cable** (any Cat5/5e/6). Cut one end off; the
  crimped end plugs into the HD55's RJ45 jack.
- **Recommended: an RJ45 screw-terminal breakout** (or a small terminal block /
  Wago lever connectors). You'll want to land the CANable and the T-CAN485 on
  the same CAN-H/CAN-L/GND at the same time in Phase C, which is much easier
  than double-stuffing screw terminals.
- **Multimeter** for checking termination (§3.4)
- **USB-C cable** for flashing the T-CAN485 (and optionally permanent power)
- Optional: small enclosure. The unit lives in a crawlspace for most people,
  so weather/dust protection is worth it.

No relays, no 24 V supply, no opening the dehumidifier. The RJ45 jack is
external.

**Tip: you don't have to take the Pi into the crawlspace.** CAN at 50–125
kbps tolerates very long runs. A long Ethernet patch cable from the HD55 to a
breakout near the Pi (or near your desk) works fine, with CAN-H/L on the blue
twisted pair. That's also the answer if Wi-Fi doesn't reach the crawlspace.

## 3. Pinouts and wiring

### 3.1 HD55 RJ45 jack (per tinymicros, confirmed in-thread)

Looking into the receptacle with the tab down, pin 1 on the left:

| RJ45 pin | T568B wire color | Signal |
|---|---|---|
| 4 | Solid blue | **CAN-L** |
| 5 | Blue/white stripe | **CAN-H** |
| 7 | Brown/white stripe | VCC (5V) |
| 8 | Solid brown | **GND** |
| 1,2,3,6 | n/a | not connected |

### 3.2 Connections to the T-CAN485

| Ethernet wire | T-CAN485 terminal |
|---|---|
| Blue/white (pin 5) | CAN-H |
| Solid blue (pin 4) | CAN-L |
| Solid brown (pin 8) | GND |
| Brown/white (pin 7, 5V) | **not connected on this install**: the T-CAN485 runs from a USB-C wall charger (*see note*) |

### 3.3 Connections to the CANable 2.0

| Ethernet wire | CANable terminal |
|---|---|
| Blue/white (pin 5) | CANH |
| Solid blue (pin 4) | CANL |
| Solid brown (pin 8) | GND |
| Brown/white (pin 7, 5V) | **leave unconnected** (the CANable is powered by USB) |

Check the silkscreen on your board for terminal labels and the location of
the **120 Ω termination** jumper or switch; Makerbase has shipped a few
layouts.

Notes (apply to both boards):

- **Ground is required.** Several people in the thread got nothing back until
  they connected GND in addition to CAN-H/L. Don't skip it.
- The HD55's 5V rail powered the factory remote and one member powers his
  LilyGo from it successfully, but the current budget is unverified. For
  bring-up, power the T-CAN485 over USB-C; once everything works you can try
  the RJ45 5V. **Never** connect the HD55's 5V to the CANable or the Pi.
- If you get zero frames after everything else checks out, **swap CAN-H and
  CAN-L**. One member's mystery non-working setup turned out to be exactly
  this miscabling.

### 3.4 Termination (new; matters once there are 2–3 nodes)

A CAN bus wants a 120 Ω resistor at each end (about 60 Ω total measured
across CAN-H/CAN-L). At 50–125 kbps over a few meters it's forgiving: one
terminator usually works, but **zero terminators often fails**, which looks
exactly like "wrong bit rate."

Measure before you start, with everything **unpowered** (HD55 unplugged from
mains, boards unplugged from USB):

1. **HD55 alone:** meter across the blue/white and solid blue wires of the
   cable plugged into the unit.
   - ~120 Ω: the HD55 has its own terminator.
   - Open / megohms: it doesn't.
2. **T-CAN485 alone:** meter across its CAN-H/CAN-L terminals. Same reading
   rules. (Not documented clearly for this board, so measure.)
3. **CANable:** measure with the termination jumper/switch on and off to
   confirm which position is which.

Then aim for **one or two** 120 Ω terminators total in each phase:

| Phase | Setup | Turn the CANable's 120 Ω... |
|---|---|---|
| A | HD55 + CANable | **ON** if the HD55 read open; either way if it read ~120 Ω (ON gives the ideal 60 Ω) |
| B | T-CAN485 + CANable | **ON** unless the T-CAN485 has its own *and* you want exactly 60 Ω, in which case ON is still right |
| C | HD55 + T-CAN485 + CANable | **OFF** if the HD55 and T-CAN485 are already providing two; ON if only one of them is terminated |

Re-measure the whole bus unpowered after wiring Phase C. 60 Ω is ideal, 120 Ω
is fine, 40 Ω (three terminators) usually still works at these speeds but is
worth fixing.

## 4. T-CAN485 board specifics (the part everyone gets stuck on)

Multiple people in the thread had a T-CAN485 that "didn't work" with configs
that were fine on other hardware. The board has three control GPIOs that must
be driven at boot or the CAN transceiver never wakes up:

| GPIO | Function | Required state |
|---|---|---|
| GPIO23 | CAN transceiver SE (silent/enable) pin | **LOW** (drive it off) |
| GPIO16 | 5V boost enable | HIGH |
| GPIO19 | RS485 enable | HIGH (harmless to set; needed if you ever use RS485) |
| GPIO27 | CAN TX | used by canbus config |
| GPIO26 | CAN RX | used by canbus config |
| GPIO4 | Onboard WS2812 status LED | optional |

The fix that unblocked at least two stuck members was adding the GPIO23
output (kkr16's "nvm, I fixed it" post) or the full three-pin `on_boot` block
(disruptivepatternmat's "this is all needed" post). It's baked into the config
in §9. **The bench test in §7 proves this directly**: if the CANable sees the
T-CAN485's polls, the transceiver is awake.

## 5. Set up the CANable on the Raspberry Pi

### 5.1 Prepare the Pi

The Pi is set up for **key-based SSH login** and **passwordless `sudo`**. That
way everything after this section can be run non-interactively from the Mac,
including from scripts or a coding agent driving the Pi over SSH.

1. **Flash the SSD.** Plug the external SSD into the Mac. In **Raspberry Pi
   Imager**, choose **Raspberry Pi 3** as the device, **Raspberry Pi OS Lite
   (64-bit)** as the OS (under "Raspberry Pi OS (other)"), and the SSD as the
   storage. Double-check its name and size; flashing erases it. In the
   customisation settings:
   - **Hostname:** `hd55-pi`
   - **User:** a username and password. Keep the password; it's your console
     fallback.
   - **Wi-Fi:** your **2.4 GHz** SSID and password (the Pi 3B has no 5 GHz
     radio), and your country. Skip this if you'll only use Ethernet.
   - **SSH / remote access:** enable SSH and choose **public-key
     authentication only**. Paste in the Mac's public key. To copy it to the
     clipboard:

     ```bash
     pbcopy < ~/.ssh/id_ed25519.pub
     ```

   - **Raspberry Pi Connect:** not needed.
2. **Boot from the SSD.** Plug the SSD into one of the Pi's USB ports, with no
   SD card in the slot, then connect power. The first boot takes a few minutes
   (it expands the filesystem and applies your settings). Find the Pi on the
   network (`hd55-pi.local`, or look it up in your router's client list).

   The Pi 3 Model B (unlike the 3B+) only boots from USB once USB boot has
   been enabled in its one-time-programmable memory. If this Pi has booted
   from USB before, it's already done. If it sits with no activity on the
   SSD, see the "USB mass storage boot" page in the Raspberry Pi
   documentation: you boot once from an SD card with
   `program_usb_boot_mode=1` in `config.txt`. If it reboots repeatedly or
   shows a lightning-bolt icon, the SSD is drawing more power than the Pi
   can supply; use the 2.5 A supply or a powered USB hub.
3. **Add an SSH alias on the Mac** so the Pi is just `ssh hd55-pi`. Append
   this to `~/.ssh/config`, replacing the user (and the hostname with an IP
   if `.local` doesn't resolve):

   ```
   Host hd55-pi
       HostName hd55-pi.local
       User <your-pi-username>
       IdentityFile ~/.ssh/id_ed25519
   ```

4. **Confirm key login works without a prompt:**

   ```bash
   ssh -o BatchMode=yes hd55-pi 'echo key login OK'
   ```

   If this fails, the key wasn't installed. If the Pi was already set up
   without Imager's key option, install the key yourself (this one prompts
   for the Pi password once):

   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519.pub hd55-pi
   ```

   Then optionally turn off password logins on the Pi: set
   `PasswordAuthentication no` in `/etc/ssh/sshd_config` and run
   `sudo systemctl restart ssh`. Do this only after the `BatchMode` test
   passes, or you can lock yourself out.
5. **Confirm passwordless `sudo`:**

   ```bash
   ssh hd55-pi 'sudo -n true && echo passwordless sudo OK'
   ```

   Older Raspberry Pi OS releases granted this to the first user
   automatically; the trixie-based release flashed by Imager 2.x does not
   (confirmed on this install). If it prints `a password is required`, SSH in
   interactively and run the following once. `visudo -c` validates the file
   so a typo can't break `sudo`.

   ```bash
   echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/010_$USER-nopasswd
   sudo chmod 440 /etc/sudoers.d/010_$USER-nopasswd
   sudo visudo -cf /etc/sudoers.d/010_$USER-nopasswd
   ```

   This means anyone holding your SSH key has root on the Pi. That's
   acceptable for a single-purpose diagnostic box on your LAN; don't expose
   it to the internet.
6. **Install the CAN tools and the probe script:**

   ```bash
   ssh hd55-pi 'sudo apt update && sudo apt install -y can-utils python3-can'
   ```

   ```bash
   scp hd55_probe.py hd55-pi:
   ```

Once steps 4 and 5 both print OK, the Pi can be driven entirely from the Mac.
You only need to be physically present for wiring, termination, and pressing
the dehumidifier's buttons.

### 5.2 Figure out which firmware the CANable has

Plug the CANable into the Pi and run:

```bash
ip link show type can; ls /dev/ttyACM* 2>/dev/null
```

- **A `/dev/ttyACM0` appears, no `can0`** → **slcan** firmware (what
  Makerbase usually ships). Use §5.3a.
- **`can0` appears on its own** → **candleLight** (gs_usb) firmware. Use §5.3b.

Either firmware is fine for everything in this guide. Don't reflash unless
you have a reason to.

**If `lsusb` shows `0483:df11 STM Device in DFU Mode` instead**, the CANable
started in its firmware-update bootloader. This happened once on this setup
when the Pi cold-booted with the CANable already plugged in. The firmware is
untouched: unplug the CANable's USB, wait a few seconds, and plug it back in
(without pressing any button on the board). It should return as
`CANable2 ... normaldotcom/canable2`.

### 5.3a Bring up `can0` (slcan firmware)

```bash
sudo modprobe slcan
sudo slcand -o -c -s2 /dev/ttyACM0 can0   # -s2 = 50 kbps, -s4 = 125 kbps
sudo ip link set can0 up
```

To change bit rate:

```bash
sudo ip link set can0 down; sudo pkill slcand
```

then rerun the three lines above with the new `-s` value. (For a listen-only
interface, replace `-o` with `-l`. Not all slcan firmware builds honor it; see
§6.2 for why it's optional here.)

### 5.3b Bring up `can0` (candleLight firmware)

```bash
sudo ip link set can0 type can bitrate 50000   # or 125000
sudo ip link set can0 up
```

To change bit rate: `sudo ip link set can0 down`, then repeat the two lines.
Add `listen-only on` to the first line for a passive interface.

### 5.4 Tools you'll use

| Command | What it does |
|---|---|
| `candump -td -x can0` | Live view of every frame, with time deltas and RX/TX direction |
| `candump -l can0` | Log everything to a `candump-<date>.log` file |
| `cansend can0 123#0000000000000000` | Send one frame (ID `123`, 8 data bytes) |
| `python3 hd55_probe.py` | Poll every 5 s and decode replies as Variant A or B |
| `ip -details -statistics link show can0` | Bus state and error counters (useful for spotting a wrong bit rate) |

### 5.5 If you use the Mac instead

macOS has no SocketCAN, so `candump`/`cansend` aren't available, but the probe
script works over the stock slcan firmware:

```bash
python3 -m venv ~/hd55-venv && ~/hd55-venv/bin/pip install python-can pyserial
```

```bash
ls /dev/tty.usbmodem*
```

```bash
~/hd55-venv/bin/python hd55_probe.py --slcan /dev/tty.usbmodemXXXX --bitrate 50000
```

For a live frame table: `~/hd55-venv/bin/python -m can.viewer -i slcan -c
/dev/tty.usbmodemXXXX -b 50000`. If the CANable turns out to have candleLight
firmware, use the Pi; candleLight on macOS needs extra libusb setup that
isn't worth it here.

## 6. Phase A: identify your unit's protocol with the CANable

Goal: walk away knowing your bit rate, reply ID, and byte layout, so §9's
config choice is a lookup instead of trial and error.

Wire HD55 ↔ CANable (§3.3), set termination (§3.4), power on the dehumidifier.

### 6.1 Listen first (30 seconds per bit rate)

Bring up `can0` at **50 kbps** and run:

```bash
candump -td -x can0
```

The unit is expected to be silent. If you *do* see frames unprompted, that's
useful (note the IDs) and you've already found your bit rate.

### 6.2 Poll at 50 kbps

In a second SSH session (or stop `candump` first):

```bash
python3 hd55_probe.py
```

This sends an all-zeros frame on 0x123 every 5 s, the poll kern2011's unit
answered. Interpret the output:

- `RX 123#...   [A] RH=..` with plausible values → **Variant A**. Done.
- `RX 3B0#...   [B] RH=..` → Variant B at 50 kbps (not reported in the thread,
  but believe the wire).
- Nothing → go to 6.3.

If the all-zeros poll gets no reply, try jjhuff's poll before changing bit
rate: `python3 hd55_probe.py --poll 0100000000000000`.

On listen-only: with no factory remote on the bus, the only node you could
disturb is the HD55 itself, and a few error frames at the wrong bit rate are
harmless. Normal mode is fine, and the CANable needs to be in normal mode
anyway to send polls and to ACK the unit's replies.

### 6.3 Poll at 125 kbps

Switch `can0` to 125 kbps (§5.3) and rerun the probe. `RX 3B0#...` →
**Variant B**.

### 6.4 Still nothing at either rate

1. `ip -details -statistics link show can0`. A state of `ERROR-PASSIVE` or
   `BUS-OFF`, or climbing error counters, means the CANable is seeing *something*
   it can't decode: wrong bit rate, swapped H/L, or missing termination.
   Clean counters with no RX means nothing is answering at all.
2. Swap CAN-H/CAN-L at the CANable.
3. Re-check GND and termination (§3.4).
4. Try other common rates: 100 kbps and 250 kbps (`-s3` / `-s5`, or
   `bitrate 100000` / `250000`).
5. Confirm the unit is on (some may only answer when powered on, not just
   plugged in).

If none of that works, your unit may be a newer protocol (see §13, item 8).
Save a `candump -l` log of a polling session and post it to the HA thread.

### 6.5 Record a reference capture (do this; it pays off later)

Once the unit is answering, capture a few minutes while you use the
dehumidifier's **front panel**:

```bash
candump -l can0 &
python3 hd55_probe.py --interval 2
```

While it runs, write down the time of each action:
change the setpoint up and down, toggle continuous mode, power off, power on,
and (if you can) wait for the compressor to start and the pump to run.

Afterwards, line up your notes with the decoded output. You'll see exactly
which status bits flip for power, compressor, continuous, and draining **on
your unit**, which is the one thing the forum configs disagree on (byte 5 vs.
byte 6 for the compressor bit in Variant A, for example). Fix §9's lambdas to
match what you saw.

If Wi-Fi doesn't reach the Pi in the crawlspace, start those two commands
before you lose the connection (prefix them with `nohup` so they survive the
SSH session dropping), then copy the log file off later. `candump -l` writes a
self-describing log you can replay with `canplayer` or read with any text
editor.

## 7. Phase B: bench-test the T-CAN485 against the CANable

Do this at your desk, without the dehumidifier. It isolates the T-CAN485 from
every unit-side variable.

1. Wire T-CAN485 ↔ CANable: CAN-H↔CANH, CAN-L↔CANL, GND↔GND. CANable
   termination **ON** (§3.4).
2. Bring `can0` up at the bit rate you found in Phase A.
3. Flash the T-CAN485 with the matching config from §9 (via §8).
4. On the Pi:

   ```bash
   candump -td can0
   ```

   You should see the T-CAN485's poll every 10 s, e.g.
   `can0  123   [8]  01 00 00 00 00 00 00 00`.

   - **Polls arrive** → transceiver is awake, GPIO23/16/19 are right, wiring is
     right. Item 2 of §13 is ruled out for good.
   - **Nothing arrives** → it's the board or config, not the dehumidifier.
     Check the `on_boot` block and the three outputs, and confirm both ends
     use the same bit rate.

5. **Pretend to be the dehumidifier.** Send a fake reply and watch the
   ESPHome log and the Home Assistant entities update:

   ```bash
   # Variant A: RH 67%, setpoint 40%, 23 °C, power on, compressor running
   cansend can0 123#4328001708010400
   ```

   ```bash
   # Variant B: RH 67%, setpoint 40%, 23 °C, power on + compressor running
   cansend can0 3B0#4328170003000000
   ```

   ```bash
   # This unit (0x123, B layout): the real first capture, 41%, 38%, 19 °C, on + compressor
   cansend can0 123#2926130003000000
   ```

   Change values (e.g. `RH` byte `50` = 80%) and confirm the sensors follow.
   Now you know the decoding works before you ever crawl under the house.

Why the CANable must be in **normal** (not listen-only) mode here: CAN
requires at least one *other* node to acknowledge each frame. With only the
T-CAN485 and a listen-only CANable on the bus, every poll goes un-ACKed and
the ESP32 retries it endlessly, which shows up as stuck TX, error floods, or
an apparently locked-up board. If you saw "TCAN locks up / log floods" during
testing with no unit attached, this is a likely cause.

### This unit: bench plan with the simulator

For this unit the bench uses two prepared files:

- [`esphome/alorair-hd55.yaml`](../esphome/alorair-hd55.yaml): the complete
  T-CAN485 config (125 kbps, 0x123 B-layout decoding, all-zeros poll,
  Target Humidity / Power / Continuous controls with the safe-toggle rule, and
  a **Dehumidifier Link** connectivity sensor that goes off, and blanks the
  readings, after 60 s without a reply). Copy
  [`esphome/secrets.yaml.example`](../esphome/secrets.yaml.example) to
  `secrets.yaml` and fill it in before flashing. It validates and compiles on ESPHome 2026.10.2.
- [`tools/hd55_sim.py`](../tools/hd55_sim.py): runs on the Pi and behaves like this HD55. It
  answers polls, applies setpoint / continuous / power commands, enforces the
  3-minute compressor delay, and logs anything else as UNKNOWN. Change its
  conditions live with `echo '{"rh": 55}' > ~/hd55_sim.cmd`; use
  `{"silent": true}` to stop replying.

Setup: T-CAN485 CAN-H/CAN-L/GND → CANable CANH/CANL/GND, CANable 120 Ω
**on**, CANable in normal mode at 125 kbps. **Both the CANable and the
T-CAN485 plug into the Pi's USB ports**, so the Pi powers the T-CAN485,
flashes it, and reads its serial log, all over SSH. No dehumidifier on the
bus. Measure the T-CAN485's own termination first.

- **First flash from the Pi:** compile on the Mac (a Pi 3B is too slow to
  build ESPHome comfortably), copy `firmware.factory.bin` to the Pi, and
  write it with esptool (`sudo apt install esptool`):
  `esptool --chip esp32 --port /dev/serial/by-id/<T-CAN485 port> write-flash 0x0 firmware.factory.bin`.
  Later updates go over Wi-Fi with `esphome run`/`upload` from the Mac.
- **Serial log on the Pi:** `python3 -m serial.tools.miniterm <port> 115200`,
  or let the Home Assistant ESPHome logs do it once the device is adopted.
- **USB power:** the Pi 3B's USB ports share about 1.2 A across the SSD,
  the CANable, and the T-CAN485. Check `vcgencmd get_throttled` stays `0x0`.
  If it doesn't, power the T-CAN485 from a separate USB charger instead.
- The CANable and T-CAN485 may both appear as `/dev/ttyACM*`. Always use
  their `/dev/serial/by-id/` paths (`~/can-up.sh` already does for the
  CANable).

| # | Test | Pass |
|---|---|---|
| 1 | Transceiver alive: `candump can0` with the simulator stopped | `123#0000000000000000` every 10 s |
| 2 | Decoding: start `hd55_sim.py` | HA shows 41%, setpoint 38, 19 °C, Power on, Compressor on, Link on |
| 3 | State changes: `{"rh": 55}`, `{"cont": true}`, `{"power": false}` | Each entity follows within one poll |
| 4 | Controls: Target Humidity 45, Continuous on/off, Power off/on in HA | Simulator log shows `AD…`, `A2…`, then `AD…`, then `0000010000000000` |
| 5 | Safe toggle: Power **on** while the simulator reports on | **Nothing sent**; HA switch stays on |
| 6 | Reboot safety: power-cycle and OTA-update the T-CAN485 | Only polls after boot, **no** control frames |
| 7 | Link loss: `{"silent": true}`, wait 60 s, then `{"silent": false}` | Link goes off and readings go unknown; both recover |

The author's results: all seven tests passed (see [protocol.md](protocol.md) for the protocol they exercise).

## 8. Flash a base ESPHome config

1. In Home Assistant: **Settings → Add-ons → ESPHome Device Builder** (install
   if you don't have it), or run the ESPHome command-line tool on your
   computer; either works.
2. **New Device**, name it `alorair-hd55`, pick **ESP32** (generic `esp32dev`).
3. Flash the minimal generated config over USB first so OTA and Wi-Fi work.
   Subsequent flashes can be wireless, which is convenient once it's in the
   crawlspace.
4. Confirm the device shows online in the ESPHome dashboard, then replace the
   config with the one below.

## 9. The monitoring config

Use the variant you identified in Phase A. **For this unit, use "This unit
(125 kbps, replies on 0x123, B layout)" below**, which builds on the Variant A
config. If you skipped Phase A, start with Variant A and fall back to B.

### Variant A (50 kbps, replies on 0x123)

This is jjhuff's known-good T-CAN485 config with the boot-time GPIO fixes
merged in. **Verify the status-bit lambdas against your §6.5 capture**; the
compressor bit in particular (byte 6 here) is inconsistent across posts.

```yaml
esphome:
  name: alorair-hd55
  friendly_name: AlorAir HD55
  on_boot:
    - priority: 800
      then:
        - output.turn_on: enable_pin       # RS485 enable
        - output.turn_off: can_se_pin      # CAN transceiver SE -> active
        - output.turn_on: enable_5v_pin    # board 5V rail
  platformio_options:
    build_unflags: -Werror=all
    board_build.flash_mode: dio

esp32:
  board: esp32dev
  framework:
    type: arduino

logger:
  level: DEBUG

api:
  encryption:
    key: !secret hd55_api_key

ota:
  - platform: esphome

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  ap:
    ssid: "HD55 Fallback"

captive_portal:
web_server:
  port: 80

# --- T-CAN485 hardware enable pins (required!) ---
output:
  - platform: gpio
    id: enable_pin
    pin: GPIO19
  - platform: gpio
    id: can_se_pin
    pin: GPIO23
  - platform: gpio
    id: enable_5v_pin
    pin: GPIO16

light:
  - platform: neopixelbus
    type: GRB
    variant: WS2812
    pin: GPIO04
    num_leds: 1
    name: "Status LED"

# --- CAN bus ---
# Protocol refs:
#   https://tinymicros.com/wiki/AlorAir_Sentinel_HD55_Dehumidifier
#   https://community.home-assistant.io/t/automate-alorair-sentinel-hd55-dehumidifier/306084
canbus:
  - platform: esp32_can
    id: hd55_can
    tx_pin: GPIO27
    rx_pin: GPIO26
    can_id: 0x05          # dummy node id required by ESPHome
    bit_rate: 50kbps      # Variant A. Use 125kbps for Variant B
    use_extended_id: false
    on_frame:
      # ---- Variant A reply frame ----
      - can_id: 0x123
        then:
          - logger.log:
              format: "0x123: %02x %02x %02x %02x %02x %02x %02x %02x"
              args: ['x[0]','x[1]','x[2]','x[3]','x[4]','x[5]','x[6]','x[7]']
          - sensor.template.publish:
              id: humidity_actual
              state: !lambda 'return x[0];'
          - sensor.template.publish:
              id: humidity_setpoint
              state: !lambda 'return x[1];'
          - sensor.template.publish:
              id: temperature
              state: !lambda 'return x[3];'
          - binary_sensor.template.publish:
              id: power
              state: !lambda 'return (x[5] & 0x01) == 0x01;'
          - binary_sensor.template.publish:
              id: running
              state: !lambda 'return (x[6] & 0x04) == 0x04;'
          - binary_sensor.template.publish:
              id: continuous
              state: !lambda 'return (x[5] & 0x08) == 0x08;'
          - binary_sensor.template.publish:
              id: draining
              state: !lambda 'return (x[5] & 0x10) == 0x10;'
      # ---- Variant B reply frame (logged so you can detect it) ----
      - can_id: 0x3b0
        then:
          - logger.log:
              format: "0x3b0: %02x %02x %02x %02x %02x %02x %02x %02x"
              args: ['x[0]','x[1]','x[2]','x[3]','x[4]','x[5]','x[6]','x[7]']

# --- Poll the unit; it replies to traffic on 0x123 ---
# Use whichever poll payload your unit answered in Phase A.
interval:
  - interval: 10s
    then:
      - canbus.send:
          can_id: 0x123
          use_extended_id: false
          data: [0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]

sensor:
  - platform: uptime
    name: Uptime
    disabled_by_default: true
  - platform: wifi_signal
    name: WiFi Signal
    update_interval: 60s
    disabled_by_default: true

  - platform: template
    name: Humidity
    id: humidity_actual
    accuracy_decimals: 0
    unit_of_measurement: "%"
    device_class: humidity
    state_class: measurement
  - platform: template
    name: Humidity Setpoint
    id: humidity_setpoint
    accuracy_decimals: 0
    unit_of_measurement: "%"
    device_class: humidity
    state_class: measurement
  - platform: template
    name: Temperature
    id: temperature
    accuracy_decimals: 0
    unit_of_measurement: "°C"
    device_class: temperature
    state_class: measurement

binary_sensor:
  - platform: template
    name: Power
    id: power
    device_class: power
  - platform: template
    name: Compressor Running
    id: running
    device_class: running
  - platform: template
    name: Continuous Mode
    id: continuous
  - platform: template
    name: Draining
    id: draining
    device_class: running
    # This unit has no pump/purge button, so bit 4 probably never sets.
    # Kept but disabled by default; enable it in HA if it ever changes.
    disabled_by_default: true
```

### Variant B (125 kbps, replies on 0x3b0)

Change two things:

```yaml
    bit_rate: 125kbps
```

and decode the **0x3b0** frame instead, where the byte layout differs
(temperature moves to byte 2, status to byte 4). Replace the 0x3b0 handler
with kern2011's decoding:

```yaml
      - can_id: 0x3b0
        then:
          - logger.log:
              format: "0x3b0: %02x %02x %02x %02x %02x %02x %02x %02x"
              args: ['x[0]','x[1]','x[2]','x[3]','x[4]','x[5]','x[6]','x[7]']
          - lambda: |-
              id(humidity_actual).publish_state(x[0]);     // byte 0 = RH %
              id(humidity_setpoint).publish_state(x[1]);   // byte 1 = setpoint %
              id(temperature).publish_state(x[2]);         // byte 2 = temp °C
              const uint8_t status = x[4];                 // byte 4 = status
              // bit 0 = on, bit 1 = compressor running,
              // bit 3 = continuous mode, bit 4 = pump draining
              id(power).publish_state(status & 0x01);
              id(running).publish_state(status & 0x02);
              id(continuous).publish_state(status & 0x08);
              id(draining).publish_state(status & 0x10);
```

You can also delete the Variant A `0x123` handler in this case; nothing should
reply on 0x123 and keeping it only risks decoding stray frames.

The polling frame stays the same (sent on 0x123 at either bit rate;
kern2011's unit answered an all-zeros poll, dw4417's answered any frame).

### This unit (125 kbps, replies on 0x123, B layout)

Start from the Variant A config and change three things:

1. `bit_rate: 125kbps`
2. Replace the whole `- can_id: 0x123` handler with the one below, and
   delete the `0x3b0` handler.
3. Make the poll all zeros (the payload this unit answered in Phase A):
   `data: [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]`

```yaml
      - can_id: 0x123
        then:
          - logger.log:
              format: "0x123: %02x %02x %02x %02x %02x %02x %02x %02x"
              args: ['x[0]','x[1]','x[2]','x[3]','x[4]','x[5]','x[6]','x[7]']
          - lambda: |-
              // The poll also uses ID 0x123. A real reply never has RH = 0,
              // so skip anything that looks like a poll.
              if (x.size() < 8 || x[0] == 0) return;
              id(humidity_actual).publish_state(x[0]);     // byte 0 = RH %
              id(humidity_setpoint).publish_state(x[1]);   // byte 1 = setpoint %
              id(temperature).publish_state(x[2]);         // byte 2 = temp °C
              const uint8_t status = x[4];                 // byte 4 = status
              // Bits 0 (on), 1 (compressor), 3 (continuous) confirmed by the
              // 2026-11-07 front-panel capture. Bit 4 (draining) is from
              // kern2011's Variant B config and not yet confirmed here.
              id(power).publish_state(status & 0x01);
              id(running).publish_state(status & 0x02);
              id(continuous).publish_state(status & 0x08);
              id(draining).publish_state(status & 0x10);
```

**This unit's behavior, from the 2026-11-07 capture**
(`captures/capture-20261107-1634.txt`):

| Front-panel action | What the CAN reply showed |
|---|---|
| Setpoint 38 → 39 → 38 | Byte 1 followed within one 2 s poll (`26` → `27` → `26`) |
| Continuous mode on | Setpoint stepped below minimum (byte 1 = `22`, 34%), then bit 3 set |
| Continuous mode off | Setpoint stepped 36 → 38, bit 3 cleared ~4 s later |
| Short press of power | Compressor bit cleared but **unit stayed on** (bit 0 set, display on). Compressor restarted 3 min later. Not a real power-off |
| Long press (~3 s) of power | Bits 0 and 1 cleared at once; power LED off; fan ran on ~60 s; nothing on CAN marked the fan stopping |
| Long press to power on | Bit 0 set at once; compressor and fan started exactly 3 min after the compressor last stopped (protection delay) |

Implications for Home Assistant:

- The unit **answers polls while off**, so RH and temperature keep updating
  and `Power` correctly reads off.
- **There is no fan bit.** The ~60 s post-shutdown fan run is invisible.
- **RH rises several percent right after the compressor stops** (41 → 51% in
  this capture) as the fan re-evaporates water from the coil. Give any
  "RH above setpoint" alert a long delay so this doesn't trip it.
- While continuous mode is on, the setpoint sensor reads 34%. Use the
  `Continuous Mode` sensor, not the setpoint, to detect it.

To decode this unit with the probe script, add `--layout b`:
`python3 hd55_probe.py --layout b`.

### Verification

Open the ESPHome log stream. Within ~10 s of boot you should see lines like:

```
[D][canbus:072]: received can message (#1) std can_id=0x123 size=8
[D][main]: 0x123: 43 28 00 17 08 01 04 00
```

That example decodes to 67% RH, 40% setpoint, 23 °C, unit on. Sanity-check the
decoded values against the unit's own display before trusting them.

## 10. Home Assistant integration

1. **Settings → Devices & Services**. The ESPHome device should be
   auto-discovered; click **Configure** and enter the API encryption key.
2. You now have entities like `sensor.alorair_hd55_humidity`,
   `sensor.alorair_hd55_temperature`, `binary_sensor.alorair_hd55_power`, etc.
3. Useful follow-ons:
   - **Alert automation**: notify if `Draining` stays on > 10 min (pump
     problem) or RH stays above setpoint + 10% for > 6 h (unit not keeping up
     / frozen coil / failed compressor).
   - **Dead-man check**: notify if the ESPHome device or the humidity sensor
     goes `unavailable`. In a crawlspace, silent failure is the failure mode
     you actually care about.
   - **History graph card** of RH vs. setpoint vs. temperature.

## 11. Phase C: install, with the CANable as a tap

CAN is a shared bus, so the CANable can sit on the same wires as the T-CAN485
and the HD55 and see both directions.

1. Land the HD55 cable, the T-CAN485, and the CANable on the same CAN-H /
   CAN-L / GND (breakout or terminal block). Re-check termination (§3.4).
2. Bring `can0` up at your unit's bit rate. Normal mode is fine: the CANable
   only ACKs and never transmits unless you run `cansend` or the probe
   script. **Don't run `hd55_probe.py` now**; the T-CAN485 is the poller, and
   two pollers is a known cause of trouble (§13, item 5).
3. Watch:

   ```bash
   candump -td -x can0
   ```

   Every ~10 s you should see the T-CAN485's poll followed by the unit's
   reply. Compare the reply bytes to what ESPHome logs and what HA shows.

4. Once it's been solid for a day or two, remove the CANable. The T-CAN485
   doesn't need it.

### This unit: as installed (2026-11-22)

The CANable was **not** used on the installed bus; Phase B covered what it
would have shown.

| Item | As installed |
|---|---|
| Wiring | Patch cable → RJ45 breakout; terminal 5 → CAN-H, 4 → CAN-L, 8 → GND, 7 empty |
| Power | USB-C wall charger (pin 7's current rating is unknown, so it isn't used) |
| Termination | HD55 110 Ω + T-CAN485 130 Ω (both built in) ≈ 60 Ω. No resistor added |
| Network | 2.4 GHz Wi-Fi on an IoT VLAN, fixed IP via a DHCP reservation, about −68 dBm at the unit |
| Home Assistant | ESPHome integration added by IP (mDNS discovery doesn't cross VLANs); device assigned to an area, so the auto-generated Overview shows its status and controls |

Operating notes:

- **Firmware updates** go over the air:
  ```bash
  cd esphome && esphome run alorair-hd55.yaml --device <board-ip>
  ```
- **Live log** (CAN replies, decoded values):
  `esphome logs alorair-hd55.yaml --device <board-ip>`
- **If every entity shows "unavailable"** after the board has been unpowered
  for a while, Home Assistant may have stopped reconnecting. Reload the
  integration: Settings → Devices & Services → ESPHome → AlorAir HD55 →
  Reload.
- **Dehumidifier Link** off means no reply for 60 s (loose cable, unit
  unplugged). Readings and status go unknown; the Power and Continuous
  switches keep their last state but can't send anything until it's back.

## 12. Leaving the CANable in place long-term (optional)

Not needed, but if you want an independent watchdog or a raw-frame history,
the Pi can stay on the bus running `candump -l` under a systemd service, with
log rotation. Most people won't bother; ESPHome + the dead-man automation in
§10 covers the real risk.

## 13. Troubleshooting checklist

Work top to bottom; each item burned someone in the thread. The CANable turns
most of these from guesses into checks.

1. **No frames at all** → the bit rate is the most likely cause, and it
   depends on your unit's manufacture date. Don't toggle blindly: run Phase A
   (§6) with the CANable to find it.
2. **T-CAN485 seems mute** → confirm the three GPIO outputs (19, 23, 16) and
   the `on_boot` block are present. Without GPIO23 driven the transceiver is
   mute. Prove it with the bench test (§7): if the CANable sees polls, the
   board is fine.
3. **Still nothing** → verify GND is connected, then try swapping CAN-H/L.
   Check termination (§3.4); zero terminators fails in ways that look like a
   bit-rate problem.
4. **Garbage interleaved with good data** (e.g., RH=1%, temp=43 °C alternating
   with plausible readings) → you're probably decoding the poll direction too.
   In Variant A the poll and reply share ID 0x123. Use `candump -x` on the tap
   (§11) to see exactly which frames arrive and when, then filter in the
   lambda (e.g., ignore frames where `x[0] == 0x01 && x[1] == 0x00`) or
   only decode the frame ID your unit actually replies on.
5. **T-CAN485 locks up / log floods** → make sure you're sending the poll on an
   interval, not free-running, and that only one node is polling (don't run
   `hd55_probe.py` while the T-CAN485 is on the bus; unplug the factory
   remote if you have one inline). On the bench, also make sure some other
   node is ACKing (§7, last paragraph).
6. **`Reading failed: BAD_INDICATOR` in logs** → populate the `api:` section
   (encryption key); an empty api block caused this for one member.
7. **Values plausible but a status sensor is wrong** (e.g., "Compressor
   Running" never changes) → your unit's status bits differ from the forum
   config. Use your §6.5 reference capture to find the right bit.
8. **HDi90 / very new units** → as of early 2026 at least one owner of a new
   HDi90 gets no response on any combination tried so far; if you ever swap to
   a newer unit, the protocol may have changed again. A CANable capture
   (§6.4–6.5) is the most useful thing you could post to the thread.

## 14. Optional: control (beyond monitoring)

Monitoring is the main goal, but the same link supports control, with
caveats. The CANable lets you try commands by hand and watch
the unit react before you put them in ESPHome.

- **Setpoint**: send `[RH + 128, 0, 0, 0, 0, 0, 0, 0]` on 0x123 (e.g., 55% →
  0xB7). Confirmed working on both variants, and **confirmed on this unit
  2026-11-07**: `123#A800000000000000` set 40% (panel and the next reply's
  byte 1 both showed 40 within 1 s), and `123#A600000000000000` restored 38%. Test from the Pi with the
  T-CAN485 disconnected:

  ```bash
  cansend can0 123#B700000000000000
  ```

  The front panel should show 55%, and the next reply's byte 1 should read
  `37` (55). This is an absolute command, so it's safe to repeat.
- **Power toggle**: a frame with the "Power button" byte set toggles state.
  It doesn't set an absolute on/off, so a missed or duplicated frame inverts
  your intent. kern2011's revised config uses `restore_mode: DISABLED` on the
  switches specifically because ESPHome replaying switch state at boot was
  power-cycling the unit.
- Position of the control byte differs between variants (byte 2 vs. byte 5
  in different working configs). Try the frames from those posted configs one
  at a time with `cansend`, watching the unit and the next reply's power bit,
  to learn which one your unit honors. Avoid sending arbitrary bytes to
  "discover" commands; unknown frames could trigger modes you didn't intend.

### This unit: confirmed control (2026-11-07)

Each frame below was sent once from the Pi, with the result checked on the
front panel and in the next reply:

| Action | Frame on 0x123 | Type | Result |
|---|---|---|---|
| Setpoint N % | `[N+128, 0,0,0,0,0,0,0]`, e.g. `A8…` = 40% | absolute | byte 1 = N within 1 s |
| Continuous **on** | `A200000000000000` (setpoint 34) | absolute | bit 3 set within 1 s; panel shows continuous |
| Continuous **off** | setpoint frame for the normal target, e.g. `A600000000000000` (38%) | absolute | bit 3 cleared within 1 s (no lag, unlike the panel) |
| Power **toggle** | `0000010000000000` (byte 2 = `01`) | **toggle** | off: bits 0+1 cleared at once, power LED off, fan ran on. On: bit 0 set at once; compressor waits out its 3-minute delay |

Byte 5 (the other forum candidate) was not needed and wasn't tested.

**Safe-toggle rule for power:** read bit 0 first, and send the toggle only if
the unit isn't already in the state you want. Then confirm bit 0 changed. The
ESPHome controls below do exactly that, and use `restore_mode: DISABLED` so
a reboot of the T-CAN485 never sends a toggle.

```yaml
number:
  - platform: template
    name: Target Humidity
    id: target_humidity
    min_value: 36
    max_value: 90
    step: 1
    unit_of_measurement: "%"
    optimistic: true
    restore_value: true
    initial_value: 38
    set_action:
      - canbus.send:
          can_id: 0x123
          use_extended_id: false
          data: !lambda 'return std::vector<uint8_t>{(uint8_t)(x + 128), 0, 0, 0, 0, 0, 0, 0};'

switch:
  - platform: template
    name: Power
    lambda: 'return id(power).state;'
    restore_mode: DISABLED
    turn_on_action:
      - if:
          condition:
            binary_sensor.is_off: power
          then:
            - canbus.send:
                can_id: 0x123
                use_extended_id: false
                data: [0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]
    turn_off_action:
      - if:
          condition:
            binary_sensor.is_on: power
          then:
            - canbus.send:
                can_id: 0x123
                use_extended_id: false
                data: [0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]

  - platform: template
    name: Continuous
    lambda: 'return id(continuous).state;'
    restore_mode: DISABLED
    turn_on_action:
      - canbus.send:
          can_id: 0x123
          use_extended_id: false
          data: [0xA2, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]   # setpoint 34
    turn_off_action:
      - canbus.send:
          can_id: 0x123
          use_extended_id: false
          data: !lambda 'return std::vector<uint8_t>{(uint8_t)(id(target_humidity).state + 128), 0, 0, 0, 0, 0, 0, 0};'
```

The `Target Humidity` number remembers your normal setpoint, so turning
continuous off returns to it. These controls haven't been run on the
T-CAN485 yet; check them during the Phase B bench test (§7), where the
CANable shows exactly what each switch sends.

CAN-side on/off is the *safe* way to switch the unit (it preserves the
compressor cool-down/purge cycle), unlike cutting mains power with a smart
plug. If you only ever want monitoring, never sending anything but the poll
frame is also fine.

## 15. References

- HA community thread: https://community.home-assistant.io/t/automate-alorair-sentinel-hd55-dehumidifier/306084
- Protocol wiki: https://tinymicros.com/wiki/AlorAir_Sentinel_HD55_Dehumidifier
- Board: https://www.lilygo.cc/products/t-can485 / https://github.com/Xinyuan-LilyGO/T-CAN485
- ESPHome esp32_can docs: https://esphome.io/components/canbus/esp32_can/
- CANable docs and firmware updater: https://canable.io/
- can-utils (candump, cansend, slcand): https://github.com/linux-can/can-utils
- python-can: https://python-can.readthedocs.io/
- Probe script: [`tools/hd55_probe.py`](../tools/hd55_probe.py)
- Simulator: [`tools/hd55_sim.py`](../tools/hd55_sim.py)
- Measured protocol for this unit: [protocol.md](protocol.md)
