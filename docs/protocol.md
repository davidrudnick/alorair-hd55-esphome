# HD55 CAN protocol (125 kbps / reply on 0x123)

Measured on one AlorAir Sentinel HD55 in November 2026 with a USB-CAN adapter
(Makerbase CANable 2.0, slcan firmware) on a Raspberry Pi, while operating the
front panel and checking every value against the display. Later confirmed with
the T-CAN485 and ESPHome on the same unit.

## Physical layer

| | |
|---|---|
| Connector | RJ45 "remote" jack on the unit |
| Pins | 4 = CAN-L, 5 = CAN-H, 7 = +5 V, 8 = GND (1, 2, 3, 6 unused) |
| Bit rate | **125 kbps**, standard 11-bit IDs |
| Termination | The HD55 has a built-in terminator: **110 Ω** measured across pins 4–5 with the unit unplugged from mains |
| Pin 7 (5 V) | Current rating undocumented. Not used here; the ESP32 runs from a USB-C charger |

## Finding the bit rate

| Bit rate | Poll sent | Result |
|---|---|---|
| 50 kbps | `123#0000000000000000` | no reply |
| 50 kbps | `123#0100000000000000` | no reply |
| 125 kbps | `123#0000000000000000` | reply within the same second, every time |

The unit is silent until polled, at either speed. Every ID on the bus was
logged; nothing ever came from 0x3B0.

## Poll and reply

Poll: `123#0000000000000000` (every 10 s in the ESPHome config).

Reply, ID **0x123**, 8 bytes. Example, checked against the panel:
`123#2926130003000000`

| Byte | Meaning | Example |
|---|---|---|
| 0 | Relative humidity, % | `29` = 41 |
| 1 | Setpoint, % (34 while continuous mode is on) | `26` = 38 |
| 2 | Temperature, °C | `13` = 19 |
| 3 | always 0 so far | |
| 4 | Status bits | `03` = on + compressor |
| 5–7 | always 0 so far | |

Status byte (byte 4):

| Bit | Mask | Meaning | Confirmed? |
|---|---|---|---|
| 0 | `0x01` | Power on | yes |
| 1 | `0x02` | Compressor running | yes |
| 2 | `0x04` | Defrost | yes (2026-11-23): set for 7 min with the compressor bit clear |
| 3 | `0x08` | Continuous mode | yes |
| 4 | `0x10` | Draining (pump) | no: this unit has no pump/purge button and never set it |

There is **no fan bit**: the fan's ~60 s run-on after power-off is invisible.

### Defrost

When the room is cool (seen at 15–16 °C / ~60 °F), the unit runs a timed
defrost: status goes `03` → `05` (compressor off, bit 2 on) for **exactly
7 minutes**, then back to `03`. Bytes 3 and 5–7 stay 0 throughout.

Six cycles observed on 2026-11-23, with the compressor running nonstop
(setpoint below what the room reached):

| | |
|---|---|
| Defrost length | 7:00 every time |
| Start-to-start interval | ~1 h 55 min – 2 h 06 min overnight, ~1 h 45 min by midday |
| Compressor run between defrosts | ~1 h 38 min (midday cycles) |
| Reported RH | 38 → 52–53 %, peaking as defrost ends |
| Recovery | back within ~3 % of baseline 16–21 min after defrost ends |
| Room temperature change | ≤ 1 °C |

The RH rise is meltwater evaporating near the unit's sensor, not the room
getting wetter. What triggers defrost (run time, coil temperature, or both)
isn't known.

Because polls, commands and replies all use ID 0x123, a decoder must ignore
its own traffic. The ESPHome config skips frames where byte 0 is 0 (a poll)
or ≥ 0x80 (a setpoint command).

## Commands

All on ID 0x123. Each was sent once by hand and checked on the panel and in
the next reply.

| Action | Frame | Type | Result |
|---|---|---|---|
| Setpoint N % | `[N+128, 0, 0, 0, 0, 0, 0, 0]`, e.g. `A8 00 00 00 00 00 00 00` = 40 % | absolute | byte 1 updated within 1 s; panel agreed |
| Continuous on | `A2 00 00 00 00 00 00 00` (setpoint 34) | absolute | bit 3 set within 1 s; panel showed continuous |
| Continuous off | setpoint frame for the normal target, e.g. `A6…` = 38 % | absolute | bit 3 cleared within 1 s |
| Power | `00 00 01 00 00 00 00 00` | **toggle** | off: power LED out, fan ran on. On: compressor waited out its restart delay |

Not tested: a power frame with byte 5 = `01` (posted for another unit; byte 2
worked here), and the forum's pump frame (byte 2 = `02`), since this unit has
no pump.

Because power is a toggle, a lost or duplicated frame inverts your intent.
The ESPHome Power switch only sends it when bit 0 shows the opposite of what
was asked, only while replies are arriving, and never at boot
(`restore_mode: DISABLED`).

## Behavior worth knowing

From a front-panel capture with polls every 2 s:

| Front-panel action | What the reply showed |
|---|---|
| Setpoint 38 → 39 → 38 | byte 1 followed within one poll |
| Continuous on (press down past the minimum) | setpoint byte went to 34, then bit 3 set |
| Continuous off | setpoint stepped 36 → 38; bit 3 cleared ~4 s later |
| **Short** press of power | compressor bit cleared but the unit **stayed on**; compressor restarted 3 min later |
| **Long** press (~3 s) of power | power and compressor bits cleared at once; power LED off; fan ran on ~60 s with no CAN change |
| Long press to power on | power bit set at once; compressor started exactly 3 min after it last stopped |

- The unit **keeps answering polls while off**; RH and temperature still
  update.
- The compressor has a **3-minute restart delay**, for panel and CAN alike.
  A CAN power-off/on can't short-cycle it.
- **RH jumps several percent right after the compressor stops** (41 → 51 % in
  about 4 minutes in one capture) as the fan moves air over the wet coil. Give
  any "humidity too high" alert a long delay.
- Over CAN, continuous mode follows the setpoint command at once (no panel
  entry delay).

## Comparison with other owners' units

From the [Home Assistant community thread][thread] and one public repo
(read in November 2026; summaries, not every post re-verified):

| Unit | Bit rate | Reply ID | Temp / status bytes | Notes |
|---|---|---|---|---|
| **This HD55** | **125 kbps** | **0x123** | byte 2 / byte 4 | setpoint `N+128` and power toggle `00 00 01` work |
| HD55 (kern2011, 2025) | 125 kbps | 0x3B0 | byte 2 / byte 4 | same layout; config decodes 0x3B0 only |
| HD55, serial S38, Apr 2023 (dw4417) | 125 kbps | not posted | | |
| HDi65S (jjhuff) | 50 kbps | 0x123 | byte 3 / byte 5 | the original "Variant A" |
| HD35P (disruptivepatternmat) | 50 kbps | 0x123 | byte 3 / byte 5 | |
| HD55P ([EiNSTeiN-'s repo][hd55p]) | 50 kbps | 0x123 | byte 3 / byte 5 (byte 2 = display echo) | 125 kbps errored; `RH+0x80` setpoint not accepted |
| HD55P (rachel1, 2026) | tried 50 kbps | none | | used this layout at 50 kbps, no success; 125 kbps may be worth trying |

**If your unit seems dead:** try 125 kbps with an all-zeros poll on 0x123 and
log *every* ID, not only the one your config expects.

## Open questions

- Bytes 3, 5, 6, 7 have always been 0, including during defrost. Error
  codes are plausible; the Reply Flags sensor records any change.
- The compressor LED was green during one restart delay and red during
  another. Meaning unknown.
- What the short press of the power button is for.

[thread]: https://community.home-assistant.io/t/automate-alorair-sentinel-hd55-dehumidifier/306084
[hd55p]: https://github.com/EiNSTeiN-/esphome-alorair-sentinel-hd55p
