"""Setup, unique-id migration, and auth-failure tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from pycaruna.exceptions import CarunaAuthError
import pytest

from custom_components.caruna.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from tests.hass.common import USERNAME, mock_config_entry

pytestmark = pytest.mark.usefixtures("mock_caruna_client")


async def test_setup_creates_sensors(hass: HomeAssistant):
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    unique_ids = {
        item.unique_id for item in registry.entities.values() if item.platform == DOMAIN
    }
    assert "123456_yesterday" in unique_ids
    assert "123456_last_hour" in unique_ids

    last_hour = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_last_hour")
    )
    assert last_hour.attributes.get("state_class") == "measurement"


async def test_setup_migrates_unique_id(hass: HomeAssistant):
    entry = mock_config_entry(unique_id="111")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.unique_id == USERNAME
    assert entry.data[CONF_USERNAME] == USERNAME


async def test_setup_auth_error(hass: HomeAssistant, mock_caruna_client: MagicMock):
    mock_caruna_client.get_energy.side_effect = CarunaAuthError(
        "expired", status_code=401
    )
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry(hass: HomeAssistant):
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
