"""Temperature sensors for the Gree heat pump."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PROP_INLET_HI, PROP_INLET_LO, PROP_OUTLET_HI, PROP_OUTLET_LO, PROP_TANK_HI, PROP_TANK_LO
from .coordinator import GreeHeatPumpCoordinator
from .entity import GreeHeatPumpEntity

# key -> (Hi property, Lo property)
TEMPERATURE_SENSORS = {
    "tank_temperature": (PROP_TANK_HI, PROP_TANK_LO),
    "water_inlet_temperature": (PROP_INLET_HI, PROP_INLET_LO),
    "water_outlet_temperature": (PROP_OUTLET_HI, PROP_OUTLET_LO),
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(
        GreeTemperatureSensor(entry.runtime_data, key, hi, lo) for key, (hi, lo) in TEMPERATURE_SENSORS.items()
    )


class GreeTemperatureSensor(GreeHeatPumpEntity, SensorEntity):
    """A temperature the heat pump reports as a Hi/Lo pair."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: GreeHeatPumpCoordinator, key: str, hi_prop: str, lo_prop: str) -> None:
        super().__init__(coordinator, key)
        self._hi_prop = hi_prop
        self._lo_prop = lo_prop

    @property
    def native_value(self) -> float | None:
        return self.coordinator.split_temperature(self._hi_prop, self._lo_prop)
