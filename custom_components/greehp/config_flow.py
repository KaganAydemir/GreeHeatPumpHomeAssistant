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
from .gree_protocol import async_discover

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Gree heat pump."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, any] = {}
        self._discovered_devices: list[dict] = []
        self._selected_device: dict | None = None
        self._client: GreeHeatPumpClient | None = None

    async def _connect(
        self, host: str, port: int, mac: str, versions: list[int], key: str | None = None, uid: int | None = None
    ) -> str | None:
        """Connect with the first encryption version that works. Returns an error key, or None on success.

        On success the connected client, which holds the heat pump's current key, is kept in self._client.
        """
        for version in versions:
            client = GreeHeatPumpClient(host, port, mac, encryption_version=version, encryption_key=key or None, uid=uid)
            try:
                await client.verify()
            except WrongDeviceError as err:
                _LOGGER.debug("Setup: %s", err)
                return "wrong_device"
            except Exception as err:
                _LOGGER.debug("Setup: no connection to %s with encryption version %s: %s", host, version, err)
                continue
            self._client = client
            return None
        return "cannot_connect"

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
        self._discovered_devices = await async_discover(self.hass)

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
        """Connect to the discovered device, detecting its encryption version, then ask for a name."""
        device = self._selected_device
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_HOST: device["host"],
                    CONF_MAC: device["mac"],
                    CONF_PORT: device["port"],
                    CONF_ENCRYPTION_KEY: self._client.key,
                    CONF_ENCRYPTION_VERSION: self._client.encryption_version,
                },
            )

        if error := await self._connect(device["host"], device["port"], device["mac"], versions=[1, 2]):
            # Fall back to the manual form, prefilled with what discovery found
            self._data = {CONF_NAME: device["name"], CONF_HOST: device["host"], CONF_MAC: device["mac"], CONF_PORT: device["port"]}
            return self._show_manual_form(self._data, {"base": error})

        return self.async_show_form(
            step_id="detect_encryption",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=device["name"]): str}),
        )

    async def async_step_manual(self, user_input: dict | None = None) -> FlowResult:
        """Handle manual device entry."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)

            # Check if already configured by MAC
            await self.async_set_unique_id(self._data[CONF_MAC])
            self._abort_if_unique_id_configured()

            data = self._data
            error = await self._connect(
                data[CONF_HOST],
                data[CONF_PORT],
                data[CONF_MAC],
                versions=[data.get(CONF_ENCRYPTION_VERSION, 1)],
                key=data.get(CONF_ENCRYPTION_KEY),
                uid=data.get(CONF_UID),
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(title=data[CONF_NAME], data={**data, CONF_ENCRYPTION_KEY: self._client.key})

        return self._show_manual_form(user_input or self._data, errors)

    def _show_manual_form(self, defaults: dict, errors: dict) -> FlowResult:
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
            error = await self._connect(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                data[CONF_MAC],
                versions=[data.get(CONF_ENCRYPTION_VERSION, 1)],
                key=data.get(CONF_ENCRYPTION_KEY),
                uid=data.get(CONF_UID),
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={**user_input, CONF_ENCRYPTION_KEY: self._client.key}
                )

        defaults = user_input or entry.data
        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=data_schema, errors=errors)
