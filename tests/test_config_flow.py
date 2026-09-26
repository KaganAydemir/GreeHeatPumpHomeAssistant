"""Manual setup and reconfigure."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.greehp.const import DOMAIN

from .fake_heat_pump import MAC, FakeHeatPump


async def test_manual_setup(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"discovery": "manual"})
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Gree Heatpump", "host": "127.0.0.1", "mac": MAC, "port": pump.port, "encryption_version": 1},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    created = hass.config_entries.async_entries(DOMAIN)[0]
    assert created.unique_id == MAC
    await hass.config_entries.async_unload(created.entry_id)


async def test_reconfigure_to_new_address(hass: HomeAssistant, entry) -> None:
    moved = await FakeHeatPump.start()
    try:
        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", "port": moved.port})
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["port"] == moved.port
        # Reloaded against the new address
        assert entry.runtime_data.client.port == moved.port
    finally:
        moved.close()


async def test_reconfigure_rejects_other_device(hass: HomeAssistant, entry) -> None:
    other = await FakeHeatPump.start(mac="aabbccddeeff")
    try:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", "port": other.port})
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "wrong_device"}
    finally:
        other.close()


async def test_reconfigure_nothing_there(hass: HomeAssistant, entry) -> None:
    silent = await FakeHeatPump.start()
    silent.drop = set(range(1, 100))
    try:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", "port": silent.port})
        assert result["errors"] == {"base": "cannot_connect"}
    finally:
        silent.close()
