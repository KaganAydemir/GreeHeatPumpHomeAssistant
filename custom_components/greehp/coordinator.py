"""Data coordinator for the Gree heat pump."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
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
from .device import GreeHeatPumpClient, WrongDeviceError

_LOGGER = logging.getLogger(__name__)

# Sends per command, including resends when the device acknowledges without applying
COMMAND_ATTEMPTS = 3
# Seconds to wait before a second read-back, in case the device applies the change a little late
READBACK_DELAY = 1.0
# The command is already acknowledged, so the read-back is a quick check rather than a full poll
READBACK_RETRIES = 3
# Attempts for the bind that checks whether the device's key changed after a poll got no reply
REBIND_RETRIES = 3


class GreeHeatPumpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the heat pump and exposes its state in domain terms."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: GreeHeatPumpClient, name: str) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=name, update_interval=SCAN_INTERVAL)
        self.client = client
        # Commands resend the full base state, so they must be built from the latest data. Holding this
        # lock for every command and poll stops two commands (or a command and a slow poll carrying old
        # values) from interleaving and undoing each other's changes.
        self._lock = asyncio.Lock()
        # The heat pump's own description (firmware version etc.), if it answered a scan
        self.device_description: dict[str, Any] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        async with self._lock:
            try:
                return await self.client.get(POLLED_PROPS)
            except TimeoutError as err:
                # No reply at all. Besides an outage, this is what a changed key looks like: the device
                # ignores requests it can't decrypt. Binding still works, so check for a new key.
                if await self._rebind():
                    try:
                        return await self.client.get(POLLED_PROPS)
                    except Exception as retry_err:
                        raise UpdateFailed(f"Error communicating with heat pump: {retry_err}") from retry_err
                raise UpdateFailed(f"Error communicating with heat pump: {err}") from err
            except Exception as err:
                raise UpdateFailed(f"Error communicating with heat pump: {err}") from err

    async def _rebind(self) -> bool:
        """Bind to pick up a new key. Returns True if the key changed."""
        try:
            return await self.client.bind(max_retries=REBIND_RETRIES)
        except WrongDeviceError as err:
            raise UpdateFailed(f"{err}. If the heat pump's IP address changed, use Reconfigure") from err
        except Exception as err:
            _LOGGER.debug("Bind after a missed poll failed too (%s); the heat pump is unreachable", err)
            return False

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
        async with self._lock:
            await self._send(values)

    async def async_set_state(self, space_mode: str | None = None, hot_water: bool | None = None) -> None:
        """Set space conditioning and/or hot water; unspecified parts keep their current state."""
        async with self._lock:
            # Read the current state only once the lock is held, so a command that just finished is included
            space = self.space_mode if space_mode is None else space_mode
            dhw = self.hot_water_on if hot_water is None else hot_water

            if space == SPACE_OFF and not dhw:
                await self._send({PROP_POWER: 0})
            else:
                await self._send({PROP_POWER: 1, PROP_MODE: STATE_TO_MODE[(space, dhw)]})

    async def _send(self, values: dict[str, Any]) -> None:
        """Send a command and confirm the device applied it, resending if not. Caller must hold the lock.

        The device sometimes acknowledges a command without applying it, so the changed values are read
        back. That read also becomes the new state, so no separate refresh is needed.
        """
        payload = {k: self.data[k] for k in BASE_COMMAND_PROPS if self.data.get(k) is not None}
        payload.update(values)

        for attempt in range(1, COMMAND_ATTEMPTS + 1):
            try:
                await self.client.set(payload)
            except Exception as err:
                raise HomeAssistantError(f"Failed to send command to heat pump: {err}") from err

            try:
                current = await self._read_back(values)
            except Exception as err:
                # The command was acknowledged; a missed read isn't proof it failed. Assume it applied.
                _LOGGER.debug("Could not confirm command (%s); assuming it was applied", err)
                self.async_set_updated_data({**self.data, **payload})
                return

            self.async_set_updated_data(current)
            if not (unapplied := _unapplied(values, current)):
                return
            if attempt < COMMAND_ATTEMPTS:
                _LOGGER.warning(
                    "Heat pump acknowledged but didn't apply %s; resending (attempt %d of %d)",
                    unapplied, attempt + 1, COMMAND_ATTEMPTS,
                )

        raise HomeAssistantError(f"Heat pump didn't apply {unapplied} after {COMMAND_ATTEMPTS} attempts")

    async def _read_back(self, values: dict[str, Any]) -> dict[str, Any]:
        """Read the device state, giving it a moment and a second read if the change hasn't shown up yet."""
        current = await self.client.get(POLLED_PROPS, max_retries=READBACK_RETRIES)
        if _unapplied(values, current):
            await asyncio.sleep(READBACK_DELAY)
            current = await self.client.get(POLLED_PROPS, max_retries=READBACK_RETRIES)
        return current


def _unapplied(values: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """The requested values the device doesn't report yet, as {name: requested value}."""
    return {k: v for k, v in values.items() if current.get(k) != v}
