"""Encryption key: saved after the first bind, and picked up again if the heat pump's key changes."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .conftest import entity_id, make_entry
from .fake_heat_pump import DEVICE_KEY, FakeHeatPump

NEW_KEY = "Nw9Kx2Lm5Pq8Rt1V"


async def setup(hass: HomeAssistant, pump: FakeHeatPump, **data: object):
    config_entry = make_entry(pump, **data)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_key_saved_after_first_bind(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    """A setup without a stored key binds once and keeps the key, so later startups skip the bind."""
    config_entry = await setup(hass, pump, encryption_key="")
    assert config_entry.data["encryption_key"] == DEVICE_KEY
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_stale_key_at_startup_heals(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    """The heat pump's Wi-Fi module was reset while Home Assistant was off."""
    pump.key = NEW_KEY
    config_entry = await setup(hass, pump)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data["encryption_key"] == NEW_KEY
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == "heat_pump"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_key_change_while_running_heals_in_one_poll(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.key = NEW_KEY
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success
    assert entry.data["encryption_key"] == NEW_KEY
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == "heat_pump"


async def test_outage_does_not_touch_key(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.drop = set(range(pump.requests + 1, pump.requests + 100))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == STATE_UNAVAILABLE
    assert entry.data["encryption_key"] == DEVICE_KEY


async def test_other_device_at_address_suggests_reconfigure(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    """The heat pump's IP address now belongs to another Gree device, with its own key."""
    pump.mac = "aabbccddeeff"
    pump.key = NEW_KEY
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert not entry.runtime_data.last_update_success
    assert "Reconfigure" in str(entry.runtime_data.last_exception)
    assert entry.data["encryption_key"] == DEVICE_KEY
