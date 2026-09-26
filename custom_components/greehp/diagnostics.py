"""Diagnostics download for the Gree heat pump (Settings → Devices & services → device → Download diagnostics)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant

from .const import CONF_ENCRYPTION_KEY, CONF_UID

# Anything that identifies or unlocks the device on the network
TO_REDACT = {CONF_ENCRYPTION_KEY, CONF_HOST, CONF_MAC, CONF_UID, "cid"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    client = coordinator.client

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "connection": {
            "encryption_version": client.encryption_version,
            "port": client.port,
            "behind_gateway": client.sub_mac != client.mac,
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
            # Since Home Assistant started: how many attempts each request to the heat pump needed
            "request_stats": client.stats.as_dict(),
        },
        # How the heat pump describes itself (firmware version, model), if it answered a scan
        "device_description": async_redact_data(coordinator.device_description, TO_REDACT)
        if coordinator.device_description
        else None,
        # Raw values as the heat pump reported them
        "device_values": coordinator.data,
        # The same state as the integration interprets it
        "interpreted": {
            "space_mode": coordinator.space_mode,
            "hot_water_on": coordinator.hot_water_on,
            "tank_temperature": coordinator.tank_temperature,
            "outlet_temperature": coordinator.outlet_temperature,
        },
    }
