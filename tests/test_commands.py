"""Commands: what gets sent, read-back confirmation, and commands that overlap."""

from __future__ import annotations

import asyncio

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import entity_id
from .fake_heat_pump import FakeHeatPump


async def call(hass: HomeAssistant, domain: str, service: str, target: str, **data: object) -> None:
    await hass.services.async_call(domain, service, {"entity_id": target, **data}, blocking=True)


# --- Mode mapping --------------------------------------------------------


async def test_heating_on_keeps_hot_water(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    await call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="heat")
    assert (pump.state["Pow"], pump.state["Mod"]) == (1, 4)
    await call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="cool")
    assert (pump.state["Pow"], pump.state["Mod"]) == (1, 3)
    await call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="off")
    assert (pump.state["Pow"], pump.state["Mod"]) == (1, 2)


async def test_hot_water_off_keeps_heating(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    await call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="heat")
    await call(hass, "water_heater", "turn_off", entity_id(hass, "water_heater", "hot_water"))
    assert (pump.state["Pow"], pump.state["Mod"]) == (1, 1)
    assert hass.states.get(entity_id(hass, "climate", "space")).state == "heat"
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).state == "off"


async def test_both_off_powers_down(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    await call(hass, "water_heater", "turn_off", entity_id(hass, "water_heater", "hot_water"))
    assert pump.state["Pow"] == 0
    await call(hass, "water_heater", "turn_on", entity_id(hass, "water_heater", "hot_water"))
    assert (pump.state["Pow"], pump.state["Mod"]) == (1, 2)


async def test_climate_turn_on_restores_last_mode(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    climate = entity_id(hass, "climate", "space")
    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="cool")
    await call(hass, "climate", "turn_off", climate)
    await call(hass, "climate", "turn_on", climate)
    assert pump.state["Mod"] == 3


# --- Setpoints and switches ----------------------------------------------


async def test_hot_water_target(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    await call(hass, "water_heater", "set_temperature", entity_id(hass, "water_heater", "hot_water"), temperature=44)
    assert pump.state["WatBoxTemSet"] == 44
    assert hass.states.get(entity_id(hass, "water_heater", "hot_water")).attributes["temperature"] == 44


async def test_climate_target_follows_mode(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    climate = entity_id(hass, "climate", "space")
    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    await call(hass, "climate", "set_temperature", climate, temperature=50)
    assert pump.state["HeWatOutTemSet"] == 50
    await call(hass, "climate", "set_hvac_mode", climate, hvac_mode="cool")
    await call(hass, "climate", "set_temperature", climate, temperature=18)
    assert pump.state["CoWatOutTemSet"] == 18
    assert pump.state["HeWatOutTemSet"] == 50


@pytest.mark.parametrize(("key", "prop"), [("quiet", "Quiet"), ("fast_hot_water", "FastHtWter")])
async def test_switches(hass: HomeAssistant, entry, pump: FakeHeatPump, key: str, prop: str) -> None:
    switch = entity_id(hass, "switch", key)
    await call(hass, "switch", "turn_on", switch)
    assert pump.state[prop] == 1
    assert hass.states.get(switch).state == "on"
    await call(hass, "switch", "turn_off", switch)
    assert pump.state[prop] == 0
    assert hass.states.get(switch).state == "off"


# --- Read-back confirmation ----------------------------------------------


async def test_ignored_command_is_resent(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    """The heat pump acknowledges once without applying; the integration notices and resends."""
    pump.ignore_commands = 1
    await call(hass, "water_heater", "set_temperature", entity_id(hass, "water_heater", "hot_water"), temperature=44)
    assert pump.commands == 2
    assert pump.state["WatBoxTemSet"] == 44


async def test_never_applied_raises_and_shows_real_value(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.ignore_commands = 99
    water = entity_id(hass, "water_heater", "hot_water")
    with pytest.raises(HomeAssistantError, match="didn't apply"):
        await call(hass, "water_heater", "set_temperature", water, temperature=44)
    assert pump.commands == 3
    assert hass.states.get(water).attributes["temperature"] == 45


async def test_rejected_command_raises(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.result_code = 400
    with pytest.raises(HomeAssistantError, match="rejected"):
        await call(hass, "switch", "turn_on", entity_id(hass, "switch", "quiet"))
    assert pump.state["Quiet"] == 0


async def test_missed_read_back_assumes_applied(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    """The command is acknowledged but every read-back is dropped: trust the acknowledgement."""
    first_read_back = pump.requests + 2
    pump.drop = set(range(first_read_back, first_read_back + 50))
    water = entity_id(hass, "water_heater", "hot_water")
    await call(hass, "water_heater", "set_temperature", water, temperature=44)
    assert hass.states.get(water).attributes["temperature"] == 44


async def test_dropped_requests_are_retried(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.drop = {pump.requests + 1, pump.requests + 2}
    await call(hass, "water_heater", "set_temperature", entity_id(hass, "water_heater", "hot_water"), temperature=44)
    assert pump.state["WatBoxTemSet"] == 44


# --- Overlapping commands (4.0.1) ----------------------------------------


async def test_overlapping_commands_both_apply(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    pump.reply_delay = 0.03
    await asyncio.gather(
        call(hass, "water_heater", "set_temperature", entity_id(hass, "water_heater", "hot_water"), temperature=44),
        call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="heat"),
    )
    assert (pump.state["WatBoxTemSet"], pump.state["Mod"]) == (44, 4)


async def test_both_off_at_once_powers_down(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    await call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="heat")
    pump.reply_delay = 0.03
    await asyncio.gather(
        call(hass, "climate", "set_hvac_mode", entity_id(hass, "climate", "space"), hvac_mode="off"),
        call(hass, "water_heater", "turn_off", entity_id(hass, "water_heater", "hot_water")),
    )
    assert pump.state["Pow"] == 0


async def test_slow_poll_does_not_undo_command(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    """A poll carrying old values that lands after a command must not make the next command revert it."""
    pump.status_delays = [0.03]
    poll = asyncio.create_task(entry.runtime_data.async_refresh())
    await asyncio.sleep(0.01)
    await call(hass, "water_heater", "set_temperature", entity_id(hass, "water_heater", "hot_water"), temperature=44)
    await poll
    await call(hass, "switch", "turn_on", entity_id(hass, "switch", "quiet"))
    assert (pump.state["WatBoxTemSet"], pump.state["Quiet"]) == (44, 1)
