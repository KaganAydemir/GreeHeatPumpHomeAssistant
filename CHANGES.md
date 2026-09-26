# Changelog

## 4.7.0 (2026-09-27)

### Added

- **Firmware version on the device page.** At startup, the integration asks the heat pump to describe itself, the same way discovery does but sent only to its address. It shows the reported firmware version and model ID on the device page. The model name is only replaced when the unit reports a real one; many just say "gree". This runs in the background, so startup isn't slowed, and a heat pump that doesn't answer is simply left as it was.
- **Diagnostics include the heat pump's description,** with its MAC address redacted.

## 4.6.0 (2026-09-27)

### Fixed

- **Discovery no longer freezes Home Assistant.** While searching for heat pumps during setup, the original code waited for replies in a way that blocked all of Home Assistant for up to 5 seconds: automations, the UI and other integrations paused. It now waits without blocking.
- **Discovery lists each heat pump once,** even if it answers more than one broadcast address.

### Changed

- **Read properties needs at least one property name.** It used to try a built-in list when none was given, but those four names are known not to exist on these heat pumps.
- **Tidied the network code** taken from the original project: standard Python names (`async_request`, `async_bind`, `async_discover`) instead of `FetchResult`, `BindDevice` and `discover_gree_devices`; the standard `json` module instead of an optional `simplejson`; and log messages that are only built when debug logging is on.

## 4.5.0 (2026-09-27)

### Added

- **The encryption key is saved after the first connection,** so startup no longer has to ask the heat pump for its key each time. Setups made before this version save it on their next start.
- **A changed key is picked up automatically.** The heat pump's key changes when its Wi-Fi module is reset or re-paired. Requests encrypted with the old key then get no reply. When a poll gets no reply, the integration binds once more, using Gree's generic key, which still works:
  - **A different key comes back:** it's used and saved, and the integration carries on within that poll. The log notes that the key changed.
  - **The same key comes back:** it's reported as a normal outage.
  - **A different heat pump answers** at that address: the error suggests using Reconfigure.
- **Reconfigure saves the heat pump's current key** along with the new address.

### Changed

- **Setup uses the same connection code as the rest of the integration.** Manual setup and discovery now check that the heat pump answering is the one with the entered MAC address, so a mistyped MAC shows a clear error. Discovery detects the encryption version by connecting with each in turn.
- Removed the original project's separate connection test, which also wrote the encryption key to the debug log.

## 4.4.1 (2026-09-26)

No changes in behaviour. This release adds automated testing and publishes versions as GitHub releases.

### Added

- **Tests** that run the integration inside a real Home Assistant against a fake heat pump. The fake speaks the Gree protocol and can drop requests, reply late or ignore commands. They cover setup, every mode combination, commands and their read-back, overlapping commands, the Read properties action, diagnostics, and setup and reconfigure forms.
- **GitHub Actions** runs the tests, Home Assistant's `hassfest` check and the HACS check on every push and weekly.
- **GitHub releases:** pushing a version tag publishes a release with that version's notes, so HACS shows proper version numbers.

### Changed

- The Read properties action has an icon, as Home Assistant now expects.
- The manifest's keys are in the order Home Assistant's checks expect.

## 4.4.0 (2026-09-26)

### Changed

- **Fast hot water is now a switch** instead of a read-only sensor. It sends `FastHtWter` and is confirmed by the read-back check, so if the heat pump doesn't accept it, Home Assistant shows an error and the switch stays off. Confirmed on a real unit: the heat pump accepts both on and off, even while it's powered off. Whether it has any effect while hot water is off isn't known.
- The old fast hot water sensor is removed automatically. The startup cleanup now compares entity type as well as ID, so an entity that changes type doesn't linger as unavailable.

## 4.3.0 (2026-09-26)

### Added

- **Reconfigure** (Settings → Devices & services → Gree Heat Pump → ⋮ → Reconfigure) changes the heat pump's IP address or port without removing and re-adding it, so entities, history and automations stay as they are. The new address is checked before saving:
  - It must be the same heat pump, confirmed by the MAC address in its reply. Otherwise the form reports that a different device answered.
  - The heat pump must answer a normal read with the configured encryption key. Otherwise the form reports that it can't connect.

### Changed

- The encryption key is no longer written to the debug log when binding to the heat pump.

## 4.2.0 (2026-09-26)

### Added

- **Diagnostics download** (device page → ⋮ → Download diagnostics). The file contains:
  - The integration's settings, with the encryption key, IP address, MAC address and UID redacted.
  - The raw values the heat pump reported, and how the integration interprets them.
  - The result of the last update.
  - Request statistics since Home Assistant started: how many requests needed 1, 2, 3 or more attempts, and how many failed. This shows how often the heat pump drops requests.

## 4.1.1 (2026-09-26)

### Fixed

- **No more misleading errors in the log.** When all attempts to reach the heat pump failed, the network code logged an error even if the caller recovered, for example when a command's read-back got no reply but the command had been acknowledged. It now logs this at debug level and leaves reporting to the caller:
  - Failed polls are still logged by Home Assistant, which also marks the entities unavailable.
  - Failed commands still show as an error in Home Assistant.

## 4.1.0 (2026-09-26)

### Added

- **Commands are checked after sending.** The heat pump sometimes acknowledges a command without applying it. After each command, the integration reads the heat pump's values back:
  - If the change shows up, that read becomes the new state straight away.
  - If it doesn't, the integration waits a second and reads again, in case the heat pump is just slow. If the change still hasn't applied, it resends the command, up to 3 sends in total.
  - If none of them apply, Home Assistant shows an error such as `Heat pump didn't apply {'WatBoxTemSet': 44} after 3 attempts`, and the entities keep showing the real values.
  - If the read-back gets no reply, the command is assumed to have applied, because the heat pump did acknowledge it.

## 4.0.1 (2026-09-26)

### Fixed

- **Commands that happened close together could undo each other.** Every command resends the current setpoints along with the change, and it built them from values read before the other command finished. For example:
  - Changing the hot water target while turning heating on could lose the new target.
  - Turning heating and hot water off at the same moment could leave the heat pump on in heating-only mode.
  - A slow poll that returned old values after a command could make the next command revert it.

  Commands and polls now take turns, and each command works out its values from the latest state.

## 4.0.0 (2026-09-26)

First release as a heat pump integration. This version is a rewrite of [HomeAssistant-GreeClimateComponent](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent), which was built for Gree air conditioners.

### Why the rewrite

The air-conditioner integration maps `Mod` to AC modes, where `Mod 2` means *dry*. On Gree air-to-water heat pumps, `Mod` means something else: it combines two independent things, space heating/cooling and the hot water tank. A heat pump that was only heating water showed up as **Dry**, and there was no clean way to control heating and hot water separately.

### How modes work now

Heating/cooling and hot water are separate entities. The integration works out the matching `Pow`/`Mod` pair:

| `Pow` | `Mod` | Heating / Cooling | Hot water |
|---|---|---|---|
| 0 | any | Off | Off |
| 1 | 1 | Heat | Off |
| 1 | 2 | Off | On |
| 1 | 3 | Cool | On |
| 1 | 4 | Heat | On |
| 1 | 5 | Cool | Off |

For example, turning heating off while hot water is on sends `Mod 2`, and turning hot water off while heating sends `Mod 1`.

### Added

- **Heating / Cooling** (`climate`): Off, Heat and Cool. The target is the flow (water outlet) temperature: 20–65 °C for heating, 5–25 °C for cooling. The current temperature is the measured outlet temperature.
- **Hot water** (`water_heater`): tank on/off and target temperature, 40–80 °C.
- **Temperature sensors:** tank, water inlet and water outlet.
- **Status sensors:** tank electric heater, backup heaters 1 and 2, anti-freeze protection, fast hot water.
- **Quiet mode** (`switch`).
- **`greehp.read_properties` action:** reads any property names from the heat pump and returns what it answers. It only reads, so it can't change anything. Useful for finding properties on other models.
- English and Turkish translations.
- HACS support.

### Changed

- All entities share one coordinator that polls every 30 seconds with a single request.
- Home Assistant handles unit conversion. The integration works in °C internally.
- **Networking:**
  - Each request keeps one socket open across its retries, so a late reply is still accepted.
  - Resends happen after about 1 second instead of 2.5 seconds or more. These heat pumps typically answer within 50 ms or not at all.
  - Command replies are checked for the device's result code, so a rejected command shows up as an error in Home Assistant instead of failing silently.
  - Errors say what happened, for example `No reply from <ip>:7000 after 8 attempts`.

### Removed

- Air-conditioner features: fan and swing modes, X-Fan, lights, health, sleep and related switches, HVAC mode options, external temperature sensor, temperature sensor offset, and the options flow.
- Preset-based mode switching, now replaced by separate heating/cooling and hot water entities.
- Translations that only covered AC features.

### Upgrading from earlier `greehp` versions

Existing config entries keep working, so there's no need to add the device again. On startup, entities from the old version (the climate entity and the heating temperature number) are removed. Dashboards and automations that used them need to point to the new entities.

## Protocol notes

These properties were found by capturing the Gree app's traffic and confirmed on one Gree air-to-water heat pump with a hot water tank. Other models may differ, and `greehp.read_properties` can check what a unit supports.

| Property | Meaning | Values |
|---|---|---|
| `Pow` | Power | 0 off, 1 on |
| `Mod` | Operating mode | See the mode table above |
| `WatBoxTemSet` | Hot water target | 40–80 °C |
| `HeWatOutTemSet` | Heating flow target | 20–65 °C |
| `CoWatOutTemSet` | Cooling flow target | 5–25 °C |
| `Quiet` | Quiet mode | 0 / 1 |
| `WatBoxTemHi` / `Lo` | Tank temperature | `(Hi - 100) + Lo / 10` °C |
| `AllInWatTemHi` / `Lo` | Water inlet temperature | same encoding |
| `AllOutWatTemHi` / `Lo` | Water outlet temperature | same encoding |
| `WatBoxElcHeRunSta` | Tank electric heater running | 0 / 1 |
| `ElcHe1RunSta`, `ElcHe2RunSta` | Backup heaters running | 0 / 1 |
| `AnFrzzRunSta` | Anti-freeze protection active | 0 / 1 |
| `FastHtWter` | Fast hot water mode | 0 / 1 |
| `TemUn` | Temperature unit | 0 (not used) |

**Other findings:**
- **Unknown names:** the heat pump leaves them out of its reply instead of answering `0`, so any name that returns a value is a real property.
- **No outside temperature:** it isn't reported over Wi-Fi, even though the unit's own display shows it. `OutEnvTem`, which Gree air conditioners use, isn't supported, and the Gree app doesn't request an outside temperature. A weather integration or separate sensor can fill the gap.
- **Commands:** they include `Pow`, `Mod`, `WatBoxTemSet` and `HeWatOutTemSet`, plus whatever is changing. A successful command reply looks like `{"t":"res","r":200,"opt":[…],"p":[…],"val":[…]}`.
- **Dropped requests:** the heat pump sometimes ignores a request completely, and retries handle this.

## Known issues and limitations

- **Switching to Heat or Cool** (`Mod 4`, `Mod 3`, `Mod 1`, `Mod 5`) follows the mode table but hasn't been tested on a real unit yet. Power, hot water, setpoints, quiet mode and fast hot water have been tested.
- **Inlet and outlet decoding:** these temperatures are assumed to use the same encoding as the tank temperature. That fits the observed values but hasn't been checked against the unit's display.
