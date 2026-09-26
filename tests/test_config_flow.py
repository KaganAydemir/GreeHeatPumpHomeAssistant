"""Manual setup and reconfigure."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.greehp.const import DOMAIN

from .fake_heat_pump import DEVICE_KEY, MAC, FakeHeatPump


async def unload_all(hass: HomeAssistant) -> None:
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(config_entry.entry_id)


async def test_manual_setup(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"discovery": "manual"})
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Gree Heatpump", "host": "127.0.0.1", "mac": MAC, "port": pump.port, "encryption_version": 1},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The key the heat pump gave during setup is saved, so startup doesn't need to bind
    assert result["data"]["encryption_key"] == DEVICE_KEY
    await hass.async_block_till_done()
    created = hass.config_entries.async_entries(DOMAIN)[0]
    assert created.unique_id == MAC
    await unload_all(hass)


async def test_manual_setup_wrong_mac(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"discovery": "manual"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Gree Heatpump", "host": "127.0.0.1", "mac": "aabbccddeeff", "port": pump.port, "encryption_version": 1},
    )
    assert result["errors"] == {"base": "wrong_device"}


async def discover(hass: HomeAssistant, pump: FakeHeatPump):
    found = [{"name": "Gree 1234", "host": "127.0.0.1", "port": pump.port, "mac": MAC}]
    with patch("custom_components.greehp.config_flow.async_discover", return_value=found):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"discovery": "discover"})
        assert result["step_id"] == "discovery"
        return await hass.config_entries.flow.async_configure(result["flow_id"], {"device": f"{MAC}_127.0.0.1"})


async def test_discovery_setup(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    result = await discover(hass, pump)
    assert result["step_id"] == "detect_encryption"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Heat pump"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "name": "Heat pump",
        "host": "127.0.0.1",
        "mac": MAC,
        "port": pump.port,
        "encryption_key": DEVICE_KEY,
        "encryption_version": 1,
    }
    await hass.async_block_till_done()
    await unload_all(hass)


async def test_discovery_detects_gcm(hass: HomeAssistant) -> None:
    pump = await FakeHeatPump.start(encryption_version=2)
    try:
        result = await discover(hass, pump)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Heat pump"})
        assert result["data"]["encryption_version"] == 2
        await hass.async_block_till_done()
        await unload_all(hass)
    finally:
        pump.close()


async def test_discovery_unreachable_falls_back_to_manual(hass: HomeAssistant, pump: FakeHeatPump) -> None:
    pump.drop = set(range(1, 100))
    result = await discover(hass, pump)
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "cannot_connect"}


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
        assert entry.data["encryption_key"] == DEVICE_KEY
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


async def test_reconfigure_picks_up_new_key(hass: HomeAssistant, entry) -> None:
    """The heat pump moved and its Wi-Fi module was reset: the new key is saved along with the address."""
    moved = await FakeHeatPump.start(key="Nw9Kx2Lm5Pq8Rt1V")
    try:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", "port": moved.port})
        await hass.async_block_till_done()
        assert result["reason"] == "reconfigure_successful"
        assert entry.data["encryption_key"] == "Nw9Kx2Lm5Pq8Rt1V"
    finally:
        moved.close()
