"""Domestic hot water (boiler tank) for the Gree heat pump."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_HEAT_PUMP,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DHW_MAX_TEMP, DHW_MIN_TEMP, PROP_DHW_SET
from .coordinator import GreeHeatPumpCoordinator
from .entity import GreeHeatPumpEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([GreeHotWater(entry.runtime_data)])


class GreeHotWater(GreeHeatPumpEntity, WaterHeaterEntity):
    """Boiler tank. On/off maps onto the device's combined Mod value."""

    _attr_operation_list = [STATE_OFF, STATE_HEAT_PUMP]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = DHW_MIN_TEMP
    _attr_max_temp = DHW_MAX_TEMP

    def __init__(self, coordinator: GreeHeatPumpCoordinator) -> None:
        super().__init__(coordinator, "hot_water")

    @property
    def current_operation(self) -> str:
        return STATE_HEAT_PUMP if self.coordinator.hot_water_on else STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.tank_temperature

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.get(PROP_DHW_SET)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_set_values({PROP_DHW_SET: int(temperature)})

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self.coordinator.async_set_state(hot_water=operation_mode != STATE_OFF)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_state(hot_water=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_state(hot_water=False)
