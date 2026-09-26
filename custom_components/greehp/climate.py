"""Space heating/cooling (radiators / underfloor) for the Gree heat pump."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COOLING_MAX_TEMP,
    COOLING_MIN_TEMP,
    HEATING_MAX_TEMP,
    HEATING_MIN_TEMP,
    PROP_COOLING_SET,
    PROP_HEATING_SET,
    SPACE_COOL,
    SPACE_HEAT,
    SPACE_OFF,
)
from .coordinator import GreeHeatPumpCoordinator
from .entity import GreeHeatPumpEntity

SPACE_TO_HVAC = {SPACE_OFF: HVACMode.OFF, SPACE_HEAT: HVACMode.HEAT, SPACE_COOL: HVACMode.COOL}
HVAC_TO_SPACE = {v: k for k, v in SPACE_TO_HVAC.items()}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([GreeSpaceClimate(entry.runtime_data)])


class GreeSpaceClimate(GreeHeatPumpEntity, ClimateEntity):
    """Heating/cooling circuit. Target is the flow (water outlet) temperature."""

    _attr_hvac_modes = list(SPACE_TO_HVAC.values())
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: GreeHeatPumpCoordinator) -> None:
        super().__init__(coordinator, "space")
        # Mode to return to on turn_on
        self._last_active_mode = SPACE_HEAT

    @property
    def _is_cooling(self) -> bool:
        return self.coordinator.space_mode == SPACE_COOL

    @property
    def hvac_mode(self) -> HVACMode:
        return SPACE_TO_HVAC[self.coordinator.space_mode]

    @property
    def current_temperature(self) -> float | None:
        """Flow temperature: the water leaving the heat pump."""
        return self.coordinator.outlet_temperature

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.get(PROP_COOLING_SET if self._is_cooling else PROP_HEATING_SET)

    @property
    def min_temp(self) -> float:
        return COOLING_MIN_TEMP if self._is_cooling else HEATING_MIN_TEMP

    @property
    def max_temp(self) -> float:
        return COOLING_MAX_TEMP if self._is_cooling else HEATING_MAX_TEMP

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        space = HVAC_TO_SPACE[hvac_mode]
        if space != SPACE_OFF:
            self._last_active_mode = space
        await self.coordinator.async_set_state(space_mode=space)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_state(space_mode=self._last_active_mode)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_state(space_mode=SPACE_OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        prop = PROP_COOLING_SET if self._is_cooling else PROP_HEATING_SET
        await self.coordinator.async_set_values({prop: int(temperature)})

    def _handle_coordinator_update(self) -> None:
        if self.coordinator.space_mode != SPACE_OFF:
            self._last_active_mode = self.coordinator.space_mode
        super()._handle_coordinator_update()
