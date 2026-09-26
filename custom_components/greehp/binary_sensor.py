"""Status flags for the Gree heat pump."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PROP_ANTI_FREEZE, PROP_FAST_HOT_WATER, PROP_HEATER_1, PROP_HEATER_2, PROP_TANK_HEATER
from .coordinator import GreeHeatPumpCoordinator
from .entity import GreeHeatPumpEntity

RUNNING = BinarySensorDeviceClass.RUNNING

# key -> (device property, device class)
STATUS_SENSORS = {
    "tank_heater": (PROP_TANK_HEATER, RUNNING),
    "backup_heater_1": (PROP_HEATER_1, RUNNING),
    "backup_heater_2": (PROP_HEATER_2, RUNNING),
    "anti_freeze": (PROP_ANTI_FREEZE, RUNNING),
    "fast_hot_water": (PROP_FAST_HOT_WATER, None),  # A mode, shown as on/off
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(
        GreeStatusSensor(entry.runtime_data, key, prop, device_class)
        for key, (prop, device_class) in STATUS_SENSORS.items()
    )


class GreeStatusSensor(GreeHeatPumpEntity, BinarySensorEntity):
    """A 0/1 status flag reported by the heat pump."""

    def __init__(
        self, coordinator: GreeHeatPumpCoordinator, key: str, prop: str, device_class: BinarySensorDeviceClass | None
    ) -> None:
        super().__init__(coordinator, key)
        self._prop = prop
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self._prop)
        return None if value is None else value == 1
