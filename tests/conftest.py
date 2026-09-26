"""Shared fixtures: a fake heat pump on localhost and the integration set up against it."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.greehp.const import DOMAIN

from .fake_heat_pump import DEVICE_KEY, MAC, FakeHeatPump


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components/."""


@pytest.fixture(autouse=True)
def fast_timing() -> None:
    """Resend and re-read quickly so tests with dropped requests don't take seconds each."""
    with (
        patch("custom_components.greehp.gree_protocol.RESEND_AFTER", 0.05),
        patch("custom_components.greehp.gree_protocol.RESEND_BACKOFF", 0.01),
        patch("custom_components.greehp.coordinator.READBACK_DELAY", 0.05),
    ):
        yield


@pytest.fixture(autouse=True)
def allow_localhost(socket_enabled: None) -> None:
    """The fake heat pump is a real UDP socket on 127.0.0.1."""


@pytest.fixture
async def pump() -> AsyncGenerator[FakeHeatPump]:
    fake = await FakeHeatPump.start()
    yield fake
    fake.close()


def make_entry(pump: FakeHeatPump, **data: object) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Gree Heatpump",
        unique_id=MAC,
        data={
            "name": "Gree Heatpump",
            "host": "127.0.0.1",
            "port": pump.port,
            "mac": MAC,
            "encryption_key": DEVICE_KEY,
            "encryption_version": 1,
            **data,
        },
    )


@pytest.fixture
async def entry(hass: HomeAssistant, pump: FakeHeatPump) -> AsyncGenerator[MockConfigEntry]:
    """The integration, set up and loaded against the fake heat pump."""
    config_entry = make_entry(pump)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    """Entity ID of one of the integration's entities, by its key (e.g. "hot_water")."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{MAC}_{key}")
    assert found, f"no {platform} entity with key {key}"
    return found
