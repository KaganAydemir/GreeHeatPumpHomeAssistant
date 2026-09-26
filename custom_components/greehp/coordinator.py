"""Data coordinator for the Gree heat pump."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    MODE_TO_STATE,
    POLLED_PROPS,
    PROP_MODE,
    PROP_POWER,
    PROP_OUTLET_HI,
    PROP_OUTLET_LO,
    PROP_TANK_HI,
    PROP_TANK_LO,
    SCAN_INTERVAL,
    SPACE_OFF,
    STATE_TO_MODE,
    BASE_COMMAND_PROPS,
)
from .device import GreeHeatPumpClient

_LOGGER = logging.getLogger(__name__)


class GreeHeatPumpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the heat pump and exposes its state in domain terms."""

    def __init__(self, hass: HomeAssistant, client: GreeHeatPumpClient, name: str) -> None:
        super().__init__(hass, _LOGGER, name=name, update_interval=SCAN_INTERVAL)
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.get(POLLED_PROPS)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with heat pump: {err}") from err

    # --- Derived state -------------------------------------------------

    @property
    def is_on(self) -> bool:
        return self.data.get(PROP_POWER) == 1

    @property
    def space_mode(self) -> str:
        """Space conditioning state: off, heat or cool."""
        if not self.is_on:
            return SPACE_OFF
        return MODE_TO_STATE.get(self.data.get(PROP_MODE), (SPACE_OFF, False))[0]

    @property
    def hot_water_on(self) -> bool:
        if not self.is_on:
            return False
        return MODE_TO_STATE.get(self.data.get(PROP_MODE), (SPACE_OFF, False))[1]

    def split_temperature(self, hi_prop: str, lo_prop: str) -> float | None:
        """Decode a temperature sent as two values: (Hi - 100) + Lo / 10."""
        hi, lo = self.data.get(hi_prop), self.data.get(lo_prop)
        if hi is None or lo is None:
            return None
        return round((hi - 100) + lo / 10, 1)

    @property
    def tank_temperature(self) -> float | None:
        return self.split_temperature(PROP_TANK_HI, PROP_TANK_LO)

    @property
    def outlet_temperature(self) -> float | None:
        return self.split_temperature(PROP_OUTLET_HI, PROP_OUTLET_LO)

    # --- Commands ------------------------------------------------------

    async def async_set_values(self, values: dict[str, Any]) -> None:
        """Send values to the device, merged with the current base state."""
        payload = {k: self.data[k] for k in BASE_COMMAND_PROPS if self.data.get(k) is not None}
        payload.update(values)
        try:
            await self.client.set(payload)
        except Exception as err:
            raise HomeAssistantError(f"Failed to send command to heat pump: {err}") from err
        # Apply optimistically, then confirm with a fresh read
        self.async_set_updated_data({**self.data, **payload})
        await self.async_request_refresh()

    async def async_set_state(self, space_mode: str | None = None, hot_water: bool | None = None) -> None:
        """Set space conditioning and/or hot water; unspecified parts keep their current state."""
        space = self.space_mode if space_mode is None else space_mode
        dhw = self.hot_water_on if hot_water is None else hot_water

        if space == SPACE_OFF and not dhw:
            await self.async_set_values({PROP_POWER: 0})
        else:
            await self.async_set_values({PROP_POWER: 1, PROP_MODE: STATE_TO_MODE[(space, dhw)]})
