# Gree Heat Pump integration: changes (v4.0.0)

The `greehp` custom component was rewritten from an air-conditioner integration into one built for the heat pump.
The integration lives in `custom_components/greehp/` (the layout HACS expects). The original code is kept locally in `greehp_backup_original/`, which isn't part of the repository.

> **Status:** deployed on 2026-09-26. Confirmed working: reading all properties, power off/on, Quiet on/off, hot water targets 40–44 °C, and command reply checking (replies look like `{"t":"res","r":200,"opt":[…],"p":[…],"val":[…]}`). Once, a command was replied to but not applied (44 °C at 21:49:01), and that hasn't happened again since. Not tested yet: switching to heating or cooling.

## The problem

The old code reused the upstream AC mode table, where `Mod 2` means `dry`.
On this heat pump, `Mod` combines two independent things: space heating/cooling (radiators) and the boiler (hot water tank).
When only the boiler was running (`Mod=2`), the card showed **"Dry"**.
The "Boyler / Boyler ve Kalorifer / Kapali" presets were a workaround for this.

## The new model

| `Pow` | `Mod` | Heating / Cooling | Hot water (boiler) |
|---|---|---|---|
| 0 | any | Off | Off |
| 1 | 1 | Heat | Off |
| 1 | 2 | Off | On |
| 1 | 3 | Cool | On |
| 1 | 4 | Heat | On |
| 1 | 5 | Cool | Off |

This table is in `const.py` (`MODE_TO_STATE` / `STATE_TO_MODE`).
The two sides are controlled independently, and the integration works out the right `Pow`/`Mod` pair.
For example, turning off heating while the boiler is on sends `Mod 2`.
Turning off the boiler while heating sends `Mod 1`.
Turning off both sends `Pow 0`.

## Entities

All entities belong to one device.

| Entity | Platform | Device property | Range |
|---|---|---|---|
| Heating / Cooling (*Kalorifer / Soğutma*) | `climate` | modes Off / Heat / Cool; target `HeWatOutTemSet` (heat) or `CoWatOutTemSet` (cool); current temperature is the water outlet (flow) temperature | 20–65 °C / 5–25 °C |
| Hot water (*Boyler*) | `water_heater` | on/off through `Mod`; target `WatBoxTemSet`; current temperature is the tank reading | 40–80 °C |
| Tank temperature (*Boyler sıcaklığı*) | `sensor` | `(WatBoxTemHi - 100) + WatBoxTemLo / 10` | – |
| Water inlet temperature (*Su giriş sıcaklığı*) | `sensor` | `(AllInWatTemHi - 100) + AllInWatTemLo / 10` | – |
| Water outlet temperature (*Su çıkış sıcaklığı*) | `sensor` | `(AllOutWatTemHi - 100) + AllOutWatTemLo / 10` | – |
| Tank electric heater, Backup heater 1 and 2, Anti-freeze protection | `binary_sensor` (running) | `WatBoxElcHeRunSta`, `ElcHe1RunSta`, `ElcHe2RunSta`, `AnFrzzRunSta` (0/1) | – |
| Fast hot water (*Hızlı sıcak su*) | `binary_sensor` | `FastHtWter` (0/1). Read-only, because writing it is untested. | – |
| Quiet mode (*Sessiz mod*) | `switch` | `Quiet` (0/1) | – |

When the integration loads, it deletes entities left over from the old version: the old climate entity and the heating temperature number.
Dashboard cards that used them need the new entity IDs.

## Code structure

| File | Role |
|---|---|
| `device.py` (new) | `GreeHeatPumpClient`: binds to the device and fetches the key, encrypts messages (ECB and GCM), reads properties (`get`) and sends commands (`set`). |
| `coordinator.py` (new) | `DataUpdateCoordinator` that polls every 30 s. Turns `Pow`/`Mod` into `space_mode`, `hot_water_on` and `tank_temperature`. Its `async_set_state()` works out the right `Pow`/`Mod` pair. |
| `entity.py` | Shared base for all entities: device info, `unique_id = <mac>_<key>`, entity names from translations. |
| `climate.py` | Rewritten; about 90 lines instead of 730. |
| `water_heater.py` (new) | Boiler entity. |
| `sensor.py` | Rewritten; the three Hi/Lo temperatures (tank, water inlet, water outlet). |
| `binary_sensor.py` (new) | Heater, anti-freeze and fast hot water status flags. |
| `switch.py` | Rewritten; quiet mode. |
| `__init__.py` | Builds the client and coordinator and stores them in `entry.runtime_data`. Removes stale entities. `ENTITY_KEYS` is built from the sensor tables, so a new sensor can't be mistaken for a stale one and deleted. |
| `const.py` | Property names, setpoint limits, the mode table and `CANDIDATE_PROPS` for probing. |
| `services.py`, `services.yaml` (new) | The `greehp.read_properties` action (see [Read properties action](#read-properties-action)). |
| `config_flow.py` | Keeps discovery and manual setup. Removes the options flow and YAML import. |
| `gree_protocol.py` | `FetchResult` rewritten to keep one socket per request (see [Retries](#retries)). Everything else unchanged apart from import cleanup. |
| `translations/en.json`, `translations/tr.json` (new) | Heat pump wording only. |
| `icons.json` | Radiator, water boiler, thermometer and volume icons. |
| `manifest.json` | Version 4.0.0, `iot_class: local_polling`, `integration_type: device`, dependency on `network`. |

### Removed

- `number.py`: the heating temperature is now the climate target.
- `select.py`: the external temperature sensor option.
- `helpers.py`: Fahrenheit and sensor-offset helpers. Home Assistant now converts units itself.
- AC-only features: fan, swing, X-Fan, lights, health, sleep and the other switches, HVAC mode options, the temperature sensor offset and the available-check option.
- 9 AC-only translation files (de, he, hu, it, pl, pt-BR, ro, ru, zh-Hans).

## Behaviour details

- **Commands** always include `Pow`, `Mod`, `WatBoxTemSet` and `HeWatOutTemSet`, plus whatever changed. The old working code always sent those four.
- **Reads** match values to the property names the device sends back (`cols`). If the device doesn't support a property, the other values can't end up under the wrong name.
- **Messages** are sent without spaces, the same as the old code.
- **Updates** show on the card straight away, then a fresh read confirms them. If the device doesn't answer, the entities show as unavailable instead of keeping stale values.
- **Encryption:** the stored key and version from the config entry are used. If there is no key, the client fetches one from the device on first contact.

## Retries

The logs from the original code showed reads succeeding only on attempt 2 or 4, and one took about 8 s.
The old `FetchResult` opened a new socket for every attempt. A reply that arrived just after its attempt timed out went to a closed socket and was lost.
It also waited for replies in a background thread, which kept blocking after the timeout.

The new `FetchResult` works like this:

- **One socket per request.** It stays open for every retry of that request and is closed afterwards. Any valid reply is accepted, even a late one from an earlier attempt. Nothing is shared between polls, so a stale reply can't be taken as the answer to a later request.
- **Asyncio UDP, no threads.** It uses `loop.create_datagram_endpoint`, bound explicitly to `0.0.0.0:<random port>`. Without the explicit bind, Windows refuses to receive on the socket. Linux doesn't need it, but it's correct everywhere.
- **Filtering and error handling.** Packets from other IP addresses are ignored. A garbled or undecodable packet is skipped, and the code keeps waiting for a valid one.
- **Fresh decryption object for every reply.** GCM decryption objects can only be used once, so one bad packet no longer breaks the later ones.
- **Faster resends.** Real logs showed the heat pump answers within 20–45 ms or not at all: every retry succeeded about 20 ms after a resend, never late. Each attempt now waits 1 s plus 0.2 s per retry (1.0 s, 1.2 s, 1.4 s, …), 8 attempts at most, instead of 2.5 s, 2.8 s, 3.1 s, …. A request that needed 4 attempts now takes about 3.6 s instead of 8.4 s.
- **Readable errors.** When every attempt fails, the error says what happened (`No reply from 192.168.1.51:7000 after 8 attempts`) instead of a bare `TimeoutError` with no message. That message shows up in HA when a command fails.
- **Command replies are checked.** `GreeHeatPumpClient.set` logs the reply. If the result code `r` is anything other than 200, it raises `Heat pump rejected the command (result code …)`. This happened once in real use: the heat pump replied to a 44 °C command but didn't apply it. Tested against the fake heat pump with `r=200` (accepted) and `r=400` (rejected).

`FetchResult` now takes a function that creates a cipher (`make_cipher`) instead of a cipher object. All three callers were updated: `device.py`, `GetDeviceKey` and `GetDeviceKeyGCM`.

**Tested** on this PC (Python 3.11) against a fake heat pump on localhost. Home Assistant was stubbed out, and the requests went through the real `GreeHeatPumpClient`. All 8 scenarios passed:

| Scenario | Result |
|---|---|
| Immediate reply | 0.0 s, 1 request |
| First request dropped | 1.0 s, 2 requests |
| Reply to attempt 1 arrives after 1.5 s | used at 1.5 s. The old code would have discarded it and depended on a later retry. |
| Garbage packet, then valid reply | 0.0 s |
| Duplicate replies | first one used |
| GCM: garbage, then two replies | 0.0 s |
| GCM: late reply | 1.5 s |
| No reply (2 retries) | `TimeoutError: No reply from … after 2 attempts` after 2.2 s |

## Read properties action

`greehp.read_properties` (new `services.py` and `services.yaml`) reads any property names from the heat pump and returns what it answers. It only reads, so it can't change anything on the heat pump. It's for finding properties the integration doesn't use yet, such as outside temperature or flow temperature.

- **Input:** a list of names, or one string with names separated by commas or spaces. Duplicates are ignored. If the list is empty, it tries `CANDIDATE_PROPS` in `const.py`: names from other Gree projects, none of them confirmed on this unit.
- **Output:** `values` (name → value the heat pump returned) and `no_reply` (names it didn't answer).
- **Strategy:** it asks for all names in one request first. If the heat pump ignores that request, it asks for each name on its own, so one unknown name can't hide the others. Probes use 3 attempts instead of 8.
- **Caveat:** some Gree firmware answers unknown names with `0` or `""`, so a `0` doesn't prove a property exists. Compare temperatures with the control screen.
- `GreeHeatPumpClient.get` gained an optional `max_retries` for this. The action is registered once in `async_setup`, and `CONFIG_SCHEMA` is set to config-entry-only.

**First real run (2026-09-26):** the heat pump answered all the names except `OutEnvTem`. It leaves unknown names out rather than answering `0`, so every value it returned is a real property: `AllInWatTemHi/Lo` = 124/3 (24.3 °C), `AllOutWatTemHi/Lo` = 133/1 (33.1 °C), and `WatBoxElcHeRunSta`, `ElcHe1RunSta`, `ElcHe2RunSta`, `AnFrzzRunSta`, `FastHtWter` and `TemUn` = 0. All of these except `TemUn` are now polled and shown as entities.

**Tested** with Home Assistant stubbed out, against three fake heat pumps: one that leaves out unknown names, one that answers `0` for them, and one that ignores any request containing an unknown name. All 5 scenarios passed, including the one-at-a-time fallback, the default candidate list and a comma-separated string.

## Checks against the logs from the original code

These values come from the logs of the original code, run through the new logic:

- `Pow=1, Mod=2` → Heating / Cooling **Off**, Hot water **Heat pump** (on).
- `WatBoxTemHi=142, WatBoxTemLo=0` → **42.0 °C**; `141, 9` → **41.9 °C**.
- `WatBoxTemSet=45`, `HeWatOutTemSet=48` → both inside the new limits.

## Deploying

**Through HACS:** add this repository as a custom repository (type Integration), install or update **Gree Heat Pump**, and restart Home Assistant. See the README.

**By hand:** copy `custom_components/greehp` over `/config/custom_components/greehp` (Samba, File Editor or Studio Code Server add-on), then restart Home Assistant.

Either way, the existing config entry keeps working; you don't need to add the device again. Keep only one copy of the integration inside `/config/custom_components/`: a second folder with the same `greehp` domain would clash.

## Open items

- If a command is replied to but not applied again, check its `Command reply` line. If `r` is 200 and `val` matches `p`, the heat pump is acknowledging commands it didn't apply, and the fix is to read the value back and resend.
- Confirm that switching to Heat or Cool sends and applies `Mod 4` (boiler + heating) / `Mod 3` (boiler + cooling).
- Outside temperature: not found yet. `OutEnvTem`, `OutEnvTemHi`/`Lo` and `EnvTemHi`/`Lo` all got no reply. The next step is to capture the Gree app's status request with Wireshark and read the real name from its `cols` list. The heat pump may also simply not report it over Wi-Fi.
- Confirm the inlet and outlet decoding against the control screen, if it shows water temperatures.
