# Gree Heat Pump for Home Assistant

A custom integration for Gree air-to-water heat pumps with a hot water tank, controlled over the local network (UDP port 7000, no cloud).

Based on [RobHofmann/HomeAssistant-GreeClimateComponent](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent). The heat pump properties were found by capturing the Gree app's traffic with Wireshark.

## Entities

| Entity | Type | What it does |
|---|---|---|
| Heating / Cooling | `climate` | Off / Heat / Cool for the radiators. Target is the flow (water outlet) temperature: 20–65 °C when heating, 5–25 °C when cooling. |
| Hot water | `water_heater` | Hot water tank on/off and target temperature (40–80 °C). |
| Tank, water inlet and water outlet temperature | `sensor` | Measured temperatures. |
| Tank electric heater, backup heaters 1 and 2, anti-freeze, fast hot water | `binary_sensor` | Status flags. |
| Quiet mode | `switch` | Quiet operation on/off. |

Heating/cooling and hot water are controlled independently; the integration sends the matching `Pow`/`Mod` combination:

| `Mod` | Heating / Cooling | Hot water |
|---|---|---|
| 1 | Heat | Off |
| 2 | Off | On |
| 3 | Cool | On |
| 4 | Heat | On |
| 5 | Cool | Off |

`Pow 0` turns both off.

## Installation

### HACS (recommended)

1. In HACS, open the menu (⋮) → **Custom repositories**.
2. Add `https://github.com/KaganAydemir/GreeHeatPumpHomeAssistant` with type **Integration**.
3. Install **Gree Heat Pump** and restart Home Assistant.

For a private repository, HACS needs a GitHub token with access to it.

### Manual

Copy `custom_components/greehp` into `/config/custom_components/` and restart Home Assistant.

## Setup

Settings → Devices & services → Add integration → **Gree Heat Pump**, then choose automatic discovery or enter the IP and MAC address by hand. Give the heat pump a fixed IP address in your router so it doesn't change.

## Diagnostics

On the device page, open ⋮ → **Download diagnostics** for a file with the heat pump's raw values and statistics on how many attempts requests needed. The encryption key, IP address, MAC address and UID are redacted, so the file is safe to attach to an issue.

## Finding more properties

The `greehp.read_properties` action (Developer Tools → Actions) reads any property names from the heat pump and returns what it answers. It only reads, so it can't change anything. The heat pump leaves out names it doesn't know, so every name that comes back with a value is a real property.

## Changes

See [CHANGES.md](CHANGES.md) for the rewrite from the original air-conditioner integration and what has been tested.

## License and credits

This project is derived from [HomeAssistant-GreeClimateComponent](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent) by Rob Hofmann and contributors, which is licensed under GPL-3.0. It was rewritten for air-to-water heat pumps in September 2026 and is also licensed under the [GNU General Public License v3.0](LICENSE).

This is an independent project. It isn't affiliated with the original project or with Gree Electric Appliances.
