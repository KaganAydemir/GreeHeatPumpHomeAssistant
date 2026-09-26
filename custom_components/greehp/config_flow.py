"""Config flow for the Gree heat pump integration."""

from __future__ import annotations

# Standard library imports
import logging

# Third-party imports
import voluptuous as vol

# Home Assistant imports
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

# Local imports
from .const import (
    CONF_ENCRYPTION_KEY,
    CONF_ENCRYPTION_VERSION,
    CONF_UID,
    DEFAULT_PORT,
    DOMAIN,
)
from .device import GreeHeatPumpClient, WrongDeviceError
from .gree_protocol import test_connection, discover_gree_devices, detect_device_encryption

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Gree heat pump."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, any] = {}
        self._discovered_devices: list[dict] = []
        self._selected_device: dict | None = None

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step - show discovery or manual entry."""
        if user_input is not None:
            if user_input.get("discovery") == "discover":
                return await self.async_step_discovery()
            else:
                return await self.async_step_manual()

        # Show discovery vs manual choice
        data_schema = vol.Schema(
            {
                vol.Required("discovery", default="discover"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["discover", "manual"],
                        translation_key="discovery_method",
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_discovery(self, user_input: dict | None = None) -> FlowResult:
        """Handle device discovery."""
        if user_input is not None:
            # User selected a discovered device
            selected_device = user_input["device"]

            for device in self._discovered_devices:
                device_id = f"{device['mac']}_{device['host']}"
                if device_id == selected_device:
                    # Check if already configured
                    await self.async_set_unique_id(device["mac"])
                    self._abort_if_unique_id_configured()

                    # Store selected device for next step
                    self._selected_device = device
                    return await self.async_step_detect_encryption()

            # If no matching device found, something went wrong - go to manual
            return await self.async_step_manual()

        # Discover devices
        self._discovered_devices = await discover_gree_devices(self.hass)

        if not self._discovered_devices:
            # No devices found, go to manual entry
            return await self.async_step_manual()

        # Create device selection options
        device_options = {}
        for device in self._discovered_devices:
            device_id = f"{device['mac']}_{device['host']}"
            device_options[device_id] = f"IP: {device['host']}, MAC: {device['mac']}"

        data_schema = vol.Schema({vol.Required("device"): vol.In(device_options)})

        return self.async_show_form(step_id="discovery", data_schema=data_schema, description_placeholders={"devices_found": str(len(self._discovered_devices))})

    async def async_step_detect_encryption(self, user_input: dict | None = None) -> FlowResult:
        """Detect encryption version and configure device."""
        if user_input is not None:
            # User entered device name, proceed with setup
            device_name = user_input[CONF_NAME]

            # Create final configuration
            self._data = {
                CONF_NAME: device_name,
                CONF_HOST: self._selected_device["host"],
                CONF_MAC: self._selected_device["mac"],
                CONF_PORT: self._selected_device["port"],
                CONF_ENCRYPTION_KEY: "",
                CONF_ENCRYPTION_VERSION: self._selected_device["encryption_version"],
            }

            # Test the connection
            is_connection_valid = await test_connection(self._data)
            if not is_connection_valid:
                return self.async_show_form(
                    step_id="detect_encryption",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_NAME, default=device_name): str,
                        }
                    ),
                    errors={"base": "cannot_connect"},
                )

            return self.async_create_entry(title=device_name, data=self._data)

        # Detect encryption version for selected device
        mac_addr = self._selected_device["mac"]
        ip_addr = self._selected_device["host"]
        port = self._selected_device["port"]

        encryption_version = await detect_device_encryption(mac_addr, ip_addr, port)

        if encryption_version is None:
            # Could not detect encryption, pre-fill manual form with discovered device info
            self._data = {
                CONF_NAME: self._selected_device["name"],
                CONF_HOST: self._selected_device["host"],
                CONF_MAC: self._selected_device["mac"],
                CONF_PORT: self._selected_device["port"],
                CONF_ENCRYPTION_KEY: "",
                CONF_ENCRYPTION_VERSION: 1,  # Default to version 1
            }
            # Show manual form with error about encryption detection failure
            return self.async_show_form(
                step_id="manual",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME, default=self._data.get(CONF_NAME, "")): str,
                        vol.Required(CONF_HOST, default=self._data.get(CONF_HOST, "")): str,
                        vol.Required(CONF_MAC, default=self._data.get(CONF_MAC, "")): str,
                        vol.Required(CONF_PORT, default=self._data.get(CONF_PORT, DEFAULT_PORT)): int,
                        vol.Optional(CONF_ENCRYPTION_KEY, default=self._data.get(CONF_ENCRYPTION_KEY, "")): str,
                        vol.Optional(CONF_UID): int,
                        vol.Optional(CONF_ENCRYPTION_VERSION, default=self._data.get(CONF_ENCRYPTION_VERSION, 1)): int,
                    }
                ),
                errors={"base": "cannot_connect"},
            )

        # Store detected encryption version
        self._selected_device["encryption_version"] = encryption_version

        # Show device naming form with detected info
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self._selected_device["name"]): str,
            }
        )

        return self.async_show_form(step_id="detect_encryption", data_schema=data_schema)

    async def async_step_manual(self, user_input: dict | None = None) -> FlowResult:
        """Handle manual device entry."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)

            # Check if already configured by MAC
            await self.async_set_unique_id(self._data[CONF_MAC])
            self._abort_if_unique_id_configured()

            is_connection_valid = await test_connection(self._data)
            if not is_connection_valid:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=user_input[CONF_NAME], data=self._data)

        # Set defaults from user_input if present, else use hardcoded defaults
        defaults = user_input or self._data
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_MAC, default=defaults.get(CONF_MAC, "")): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Optional(CONF_ENCRYPTION_KEY, default=defaults.get(CONF_ENCRYPTION_KEY, "")): str,
                vol.Optional(CONF_UID): int,
                vol.Optional(CONF_ENCRYPTION_VERSION, default=defaults.get(CONF_ENCRYPTION_VERSION, 1)): int,
            }
        )
        return self.async_show_form(step_id="manual", data_schema=data_schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        """Change the heat pump's address without removing and re-adding it."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            data = entry.data
            client = GreeHeatPumpClient(
                host=user_input[CONF_HOST],
                port=user_input[CONF_PORT],
                mac=data[CONF_MAC],
                encryption_version=data.get(CONF_ENCRYPTION_VERSION, 1),
                encryption_key=data.get(CONF_ENCRYPTION_KEY),
                uid=data.get(CONF_UID),
            )
            try:
                await client.verify()
            except WrongDeviceError as err:
                _LOGGER.debug("Reconfigure: %s", err)
                errors["base"] = "wrong_device"
            except Exception as err:
                _LOGGER.debug("Reconfigure: cannot reach %s: %s", user_input[CONF_HOST], err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        defaults = user_input or entry.data
        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=data_schema, errors=errors)
