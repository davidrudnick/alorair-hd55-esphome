# Home Assistant setup

## Adding the device

1. Flash the board (`esphome run esphome/alorair-hd55.yaml`). The first flash
   is over USB; later ones go over Wi-Fi.
2. **Settings → Devices & Services**. If the ESPHome device is discovered,
   click **Configure**. If it isn't (common when the ESP32 is on a separate
   IoT VLAN, since discovery uses mDNS), choose **Add Integration → ESPHome**
   and enter the board's IP address and port `6053`.
3. Enter the `hd55_api_key` from your `secrets.yaml`.
4. Give the board a fixed IP (a DHCP reservation in your router) so Home
   Assistant doesn't lose it.

Entity IDs follow the device name, e.g. `sensor.alorair_hd55_humidity`,
`switch.alorair_hd55_power`, `number.alorair_hd55_target_humidity`.

## Dashboard

The simplest option keeps an auto-generated Overview: assign the device to
an area (**Settings → Devices & Services → ESPHome → AlorAir HD55 → Area**).
The Overview then shows its readings and controls in that area's section.

For a dedicated card on a dashboard you manage yourself, tile cards work well:

```yaml
type: grid
cards:
  - type: heading
    heading: Dehumidifier
    icon: mdi:air-humidifier
    badges:
      - type: entity
        entity: binary_sensor.alorair_hd55_dehumidifier_link
      - type: entity
        entity: binary_sensor.alorair_hd55_compressor_running
  - type: tile
    entity: sensor.alorair_hd55_humidity
    grid_options: {columns: 6}
  - type: tile
    entity: sensor.alorair_hd55_temperature
    grid_options: {columns: 6}
  - type: tile
    entity: switch.alorair_hd55_power
    grid_options: {columns: 6}
  - type: tile
    entity: switch.alorair_hd55_continuous
    grid_options: {columns: 6}
  - type: tile
    entity: number.alorair_hd55_target_humidity
    features:
      - type: numeric-input
        style: buttons
    grid_options: {columns: 12}
  - type: history-graph
    hours_to_show: 48
    entities:
      - entity: sensor.alorair_hd55_humidity
      - entity: sensor.alorair_hd55_humidity_setpoint
    grid_options: {columns: full, rows: 4}
```

## Alert ideas

- **Link lost:** `binary_sensor.alorair_hd55_dehumidifier_link` off for
  10 minutes → notify. This catches a loose cable, a tripped breaker or a dead
  ESP32 (the entity also goes *unavailable* if the ESP32 itself drops off
  Wi-Fi, so trigger on "not on").
- **Not keeping up:** humidity above setpoint + 10 for 6 hours while Power is
  on → notify (frozen coil, failed compressor, door left open). Use a long
  duration: RH jumps several percent every time the compressor stops, and
  up to ~15 % during each 7-minute defrost. Add a condition that
  `binary_sensor.alorair_hd55_defrosting` has been off for 20 minutes.
- **Unexpectedly off:** Power State off for 30 minutes when you expect it on.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Every entity **unavailable**, but the board is online | Home Assistant stopped reconnecting after the board was off for a long time. Reload the integration: Settings → Devices & Services → ESPHome → the device → **Reload** |
| **Dehumidifier Link** off, readings *unknown* | No reply for 60 s: check the RJ45 cable, CAN-H/L polarity, GND, and that the unit is plugged in. `esphome logs esphome/alorair-hd55.yaml` shows each `0x123:` reply |
| Power/Continuous switches still show a state while the link is off | ESPHome switches have no "unknown" state. They can't send anything until replies resume; trust the Link sensor |
| Setpoint reads 34 | Continuous mode is on (that's how the unit encodes it) |
| Humidity rises right after the unit stops | Normal: the fan runs ~60 s after the compressor stops and re-evaporates water from the coil |
| RH spikes ~10–15 % every ~2 h in a cool room | Defrost: **Defrosting** is on for 7 min, compressor off. RH recovers 15–20 min later |
