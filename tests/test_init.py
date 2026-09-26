"""Setup, entity states, stale entity cleanup and availability."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.greehp.const import DOMAIN

from .conftest import entity_id, make_entry
from .fake_heat_pump import MAC, FakeHeatPump


async def test_entities_reflect_heat_pump(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    """Pow 1 / Mod 2 is hot water only: heating off, hot water on."""
    climate = hass.states.get(entity_id(hass, "climate", "space"))
    assert climate.state == "off"
    assert climate.attributes["current_temperature"] == 33.1  # outlet: (133 - 100) + 1 / 10
    assert climate.attributes["temperature"] == 48

    water = hass.states.get(entity_id(hass, "water_heater", "hot_water"))
    assert water.state == "heat_pump"
    assert water.attributes["current_temperature"] == 41.9  # tank: (141 - 100) + 9 / 10
    assert water.attributes["temperature"] == 45

    assert hass.states.get(entity_id(hass, "sensor", "tank_temperature")).state == "41.9"
    assert hass.states.get(entity_id(hass, "sensor", "water_inlet_temperature")).state == "24.3"
    assert hass.states.get(entity_id(hass, "sensor", "water_outlet_temperature")).state == "33.1"
    for key in ("tank_heater", "backup_heater_1", "backup_heater_2", "anti_freeze"):
        assert hass.states.get(entity_id(hass, "binary_sensor", key)).state == STATE_OFF
    for key in ("quiet", "fast_hot_water"):
        assert hass.states.get(entity_id(hass, "switch", key)).state == STATE_OFF


async def test_modes_map_to_entities(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    """Each Pow/Mod combination shows up as the right heating/cooling and hot water state."""
    cases = {
        (0, 4): ("off", "off"),
        (1, 1): ("heat", "off"),
        (1, 2): ("off", "heat_pump"),
        (1, 3): ("cool", "heat_pump"),
        (1, 4): ("heat", "heat_pump"),
        (1, 5): ("cool", "off"),
    }
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    for (power, mode), (space, hot_water) in cases.items():
        pump.state.update(Pow=power, Mod=mode)
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity_id(hass, "climate", "space")).state == space, (power, mode)
        assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == hot_water, (power, mode)
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_cooling_target_uses_cooling_setpoint(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    pump.state.update(Mod=5)
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    climate = hass.states.get(entity_id(hass, "climate", "space"))
    assert climate.state == "cool"
    assert climate.attributes["temperature"] == 25
    assert (climate.attributes["min_temp"], climate.attributes["max_temp"]) == (5, 25)
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_stale_entities_removed(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    """Entities from older versions go; an entity that changed platform doesn't linger."""
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = [
        ("climate", f"{DOMAIN}_{MAC}"),  # AC-era climate entity
        ("number", f"{MAC}_heating_temperature"),  # AC-era number
        ("binary_sensor", f"{MAC}_fast_hot_water"),  # fast hot water before it became a switch
    ]
    for platform, unique_id in stale:
        registry.async_get_or_create(platform, DOMAIN, unique_id, config_entry=config_entry)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for platform, unique_id in stale:
        assert registry.async_get_entity_id(platform, DOMAIN, unique_id) is None, (platform, unique_id)
    assert entity_id(hass, "switch", "fast_hot_water")
    assert len(er.async_entries_for_config_entry(registry, config_entry.entry_id)) == 11
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_unavailable_when_heat_pump_stops_answering(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.drop = set(range(pump.requests + 1, pump.requests + 100))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == STATE_UNAVAILABLE


async def test_setup_retries_when_unreachable(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    pump.drop = set(range(1, 100))
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_binds_when_no_key_stored(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    """Without a stored key, the integration binds to get one, then works normally."""
    config_entry = make_entry(pump, encryption_key="")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == "heat_pump"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_device_page_shows_firmware(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert device.sw_version == "V1.2.1"
    assert device.model_id == "10001"
    assert device.model == "Heat pump"  # the unit only says "gree", so the generic model stays
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_no_scan_reply_leaves_device_page(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    pump.answer_scans = False
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.LOADED
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert device.sw_version is None
    assert device.model == "Heat pump"
    await hass.config_entries.async_unload(config_entry.entry_id)
