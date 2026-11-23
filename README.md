# AlorAir Sentinel HD55 → ESPHome → Home Assistant

Monitor and control an **AlorAir Sentinel HD55** dehumidifier from Home
Assistant over its RJ45 "remote" jack, which is a CAN bus, using a **LilyGo
T-CAN485** (ESP32 + CAN transceiver) running ESPHome.

This repo documents one HD55 whose protocol doesn't match any config posted in
the [Home Assistant community thread][thread]: it runs at **125 kbps** but
replies on CAN ID **0x123** (not 0x3B0), using the newer byte layout. If your
unit looked dead with the existing configs, this may be why.

**Status:** installed and running on the real unit since November 2026.
Monitoring and control (power, setpoint, continuous mode) are confirmed
against the front panel. See [docs/protocol.md](docs/protocol.md).

## What you get in Home Assistant

| Entity | Type | Notes |
|---|---|---|
| Humidity | sensor | % RH from the unit's own sensor |
| Humidity Setpoint | sensor | 34 while continuous mode is on |
| Temperature | sensor | °C from the unit |
| Power State, Compressor Running, Continuous Mode | binary_sensor | from the status byte |
| Dehumidifier Link | binary_sensor (diagnostic) | off after 60 s without a reply; readings and status then go *unknown* instead of freezing |
| Target Humidity | number | sets the setpoint; follows changes made on the panel |
| Power | switch | the CAN command is a **toggle**, so it is only sent when the unit reports the opposite state, and never at boot |
| Continuous | switch | on = setpoint 34; off = back to Target Humidity |
| Draining | binary_sensor | disabled by default (unconfirmed; this unit has no pump) |

## Protocol in one table

| | |
|---|---|
| Bit rate | 125 kbps, standard 11-bit IDs |
| Poll | `123#0000000000000000` |
| Reply (ID 0x123) | byte 0 RH %, byte 1 setpoint %, byte 2 temp °C, byte 4 status |
| Status bits | 0 power, 1 compressor, 3 continuous, (4 draining, unconfirmed) |
| Setpoint | `123#<N+128>00000000000000`, absolute |
| Continuous | on = setpoint 34; off = setpoint back to your target |
| Power | `123#0000010000000000`, **toggle** |

Full details, behavior notes and a comparison with other owners' units:
[docs/protocol.md](docs/protocol.md).

## Repo layout

| Path | What it is |
|---|---|
| [`esphome/alorair-hd55.yaml`](esphome/alorair-hd55.yaml) | Complete ESPHome config for the T-CAN485 |
| [`esphome/secrets.yaml.example`](esphome/secrets.yaml.example) | Copy to `secrets.yaml` and fill in |
| [`docs/protocol.md`](docs/protocol.md) | Measured protocol, behavior, control frames, comparison with other units |
| [`docs/home-assistant.md`](docs/home-assistant.md) | Adding the device to HA, dashboard and alert suggestions, troubleshooting |
| [`docs/build-guide.md`](docs/build-guide.md) | Full build guide: wiring, termination, identifying your unit's protocol with a USB-CAN adapter, bench testing, install |
| [`tools/hd55_probe.py`](tools/hd55_probe.py) | Poll a unit and decode replies (python-can; Linux SocketCAN or slcan on macOS) |
| [`tools/hd55_sim.py`](tools/hd55_sim.py) | Pretend to be the HD55 on a bench bus, for testing the ESP32 safely |

## Quick start

1. **Identify your unit first.** Units differ (50 vs 125 kbps, reply ID
   0x123 vs 0x3B0, byte layout). If you have a USB-CAN adapter, follow
   Phase A in the [build guide](docs/build-guide.md); otherwise flash this
   config and watch the ESPHome log for `0x123:` lines.
2. Wire the T-CAN485 to the HD55's RJ45 jack: pin 5 → CAN-H, pin 4 → CAN-L,
   pin 8 → GND. **Leave pin 7 (5 V) unconnected** and power the board from a
   USB-C charger; the jack's current rating is undocumented.
3. `cp esphome/secrets.yaml.example esphome/secrets.yaml`, fill it in, then
   `esphome run esphome/alorair-hd55.yaml`.
4. Add the device in Home Assistant (Settings → Devices & Services → ESPHome)
   and enter the API key. See [docs/home-assistant.md](docs/home-assistant.md).

The HD55 has a built-in 120 Ω terminator, and so does the T-CAN485, so the
two-node bus needs no extra resistor.

## Safety and disclaimer

Not affiliated with or endorsed by AlorAir. This talks to your appliance's
control bus; frames other than the ones documented here were never sent and
may do things nobody has characterized. Use at your own risk. Switching the
unit off over CAN keeps its normal shutdown behavior (fan run-on, 3-minute
compressor restart delay), unlike cutting mains power.

## Credits

Built on work shared in the [Home Assistant community thread][thread] and the
tinymicros HD55 protocol wiki, especially kern2011's byte layout and the
T-CAN485 GPIO23 enable fix from kkr16 and disruptivepatternmat.

## License

[MIT](LICENSE).

[thread]: https://community.home-assistant.io/t/automate-alorair-sentinel-hd55-dehumidifier/306084
