"""Gree heat pump integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .binary_sensor import STATUS_SENSORS
from .const import CONF_ENCRYPTION_KEY, CONF_ENCRYPTION_VERSION, CONF_UID, DEFAULT_PORT, DOMAIN
from .coordinator import GreeHeatPumpCoordinator
from .device import GreeHeatPumpClient
from .sensor import TEMPERATURE_SENSORS
from .services import async_register_services
from .switch import SWITCHES

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.WATER_HEATER, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]
# Every entity this integration creates, as (platform, key). Anything else registered for the entry is
# removed as stale, including an entity whose key moved to another platform.
EXPECTED_ENTITIES = {
    (Platform.CLIMATE, "space"),
    (Platform.WATER_HEATER, "hot_water"),
    *((Platform.SENSOR, key) for key in TEMPERATURE_SENSORS),
    *((Platform.BINARY_SENSOR, key) for key in STATUS_SENSORS),
    *((Platform.SWITCH, key) for key in SWITCHES),
}

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

GreeHeatPumpConfigEntry = ConfigEntry[GreeHeatPumpCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions once for the integration."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GreeHeatPumpConfigEntry) -> bool:
    """Set up the heat pump from a config entry."""
    data = entry.data
    client = GreeHeatPumpClient(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        mac=data[CONF_MAC],
        encryption_version=data.get(CONF_ENCRYPTION_VERSION, 1),
        encryption_key=data.get(CONF_ENCRYPTION_KEY),
        uid=data.get(CONF_UID),
    )
    coordinator = GreeHeatPumpCoordinator(hass, client, data.get(CONF_NAME, entry.title))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _remove_stale_entities(hass, entry, client.sub_mac)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GreeHeatPumpConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
    """Drop entities left over from older versions."""
    registry = er.async_get(hass)
    expected = {(str(platform), f"{mac}_{key}") for platform, key in EXPECTED_ENTITIES}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (entity.domain, entity.unique_id) not in expected:
            _LOGGER.info("Removing stale entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)
