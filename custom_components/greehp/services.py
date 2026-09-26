"""Actions for the Gree heat pump integration."""

from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_READ_PROPERTIES = "read_properties"
ATTR_PROPERTIES = "properties"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

# Probing unknown names shouldn't take the full 8 attempts each
PROBE_RETRIES = 3

READ_PROPERTIES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROPERTIES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration-wide actions."""

    async def read_properties(call: ServiceCall) -> ServiceResponse:
        """Read arbitrary properties from the heat pump. Read-only; never changes the device."""
        # Accept a list, or names separated by commas/spaces in a single string
        names = list(dict.fromkeys(n for item in call.data[ATTR_PROPERTIES] for n in re.split(r"[,\s]+", item) if n))
        if not names:
            raise ServiceValidationError("Enter at least one property name")

        coordinator = _get_coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        client = coordinator.client

        try:
            # One request for everything; the device usually answers for all names at once
            values = await client.get(names, max_retries=PROBE_RETRIES)
        except Exception as err:
            # An unknown name may make the device ignore the whole request, so ask one at a time
            _LOGGER.debug("Combined read failed (%s), reading properties one at a time", err)
            values = {}
            for name in names:
                try:
                    values.update(await client.get([name], max_retries=PROBE_RETRIES))
                except Exception:
                    _LOGGER.debug("No reply for property %s", name)

        return {
            "values": values,
            "no_reply": [name for name in names if name not in values],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_PROPERTIES,
        read_properties,
        schema=READ_PROPERTIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _get_coordinator(hass: HomeAssistant, entry_id: str | None):
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError("No loaded Gree heat pump found")
    if len(entries) > 1:
        raise ServiceValidationError("More than one heat pump is set up; choose one with config_entry_id")
    if entries[0].runtime_data is None:
        raise HomeAssistantError("Heat pump is not ready yet")
    return entries[0].runtime_data
