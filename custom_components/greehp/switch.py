"""Switches for the Gree heat pump."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PROP_QUIET
from .coordinator import GreeHeatPumpCoordinator
from .entity import GreeHeatPumpEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([GreeQuietSwitch(entry.runtime_data)])


class GreeQuietSwitch(GreeHeatPumpEntity, SwitchEntity):
    """Quiet mode."""

    def __init__(self, coordinator: GreeHeatPumpCoordinator) -> None:
        super().__init__(coordinator, "quiet")

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(PROP_QUIET)
        return None if value is None else value == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_values({PROP_QUIET: 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_values({PROP_QUIET: 0})
