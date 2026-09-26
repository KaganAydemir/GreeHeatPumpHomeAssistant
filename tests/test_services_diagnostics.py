"""The read_properties action and the diagnostics download."""

from __future__ import annotations

import json

import pytest
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.greehp.const import DOMAIN
from custom_components.greehp.diagnostics import async_get_config_entry_diagnostics

from .fake_heat_pump import DEVICE_KEY, MAC, FakeHeatPump


async def test_read_properties(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    response = await hass.services.async_call(
        DOMAIN, "read_properties", {"properties": ["TemUn, OutEnvTem", "AllInWatTemHi"]}, blocking=True, return_response=True
    )
    assert response == {"values": {"TemUn": 0, "AllInWatTemHi": 124}, "no_reply": ["OutEnvTem"]}


async def test_read_properties_requires_names(hass: HomeAssistant, entry) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "read_properties", {}, blocking=True, return_response=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "read_properties", {"properties": [" , "]}, blocking=True, return_response=True)


async def test_read_properties_falls_back_to_one_at_a_time(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    """If the combined request goes unanswered, each name is asked for on its own."""
    pump.drop = set(range(pump.requests + 1, pump.requests + 4))  # the whole combined request (3 attempts)
    response = await hass.services.async_call(
        DOMAIN, "read_properties", {"properties": ["Pow", "Mod"]}, blocking=True, return_response=True
    )
    assert response == {"values": {"Pow": 1, "Mod": 2}, "no_reply": []}


async def test_diagnostics(hass: HomeAssistant, entry, pump: FakeHeatPump) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diagnostics)
    for secret in (DEVICE_KEY, MAC, "127.0.0.1"):
        assert secret not in text, secret
    assert diagnostics["device_values"]["WatBoxTemSet"] == 45
    assert diagnostics["interpreted"] == {
        "space_mode": "off",
        "hot_water_on": True,
        "tank_temperature": 41.9,
        "outlet_temperature": 33.1,
    }
    assert diagnostics["connection"]["request_stats"]["failed"] == 0
