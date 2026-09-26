"""Switches for the Gree heat pump."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PROP_FAST_HOT_WATER, PROP_QUIET
from .coordinator import GreeHeatPumpCoordinator
from .entity import GreeHeatPumpEntity

# key -> device property (0 off, 1 on)
SWITCHES = {
    "quiet": PROP_QUIET,
    "fast_hot_water": PROP_FAST_HOT_WATER,
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(GreeSwitch(entry.runtime_data, key, prop) for key, prop in SWITCHES.items())


class GreeSwitch(GreeHeatPumpEntity, SwitchEntity):
    """A 0/1 setting on the heat pump."""

    def __init__(self, coordinator: GreeHeatPumpCoordinator, key: str, prop: str) -> None:
        super().__init__(coordinator, key)
        self._prop = prop

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self._prop)
        return None if value is None else value == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_values({self._prop: 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_values({self._prop: 0})
