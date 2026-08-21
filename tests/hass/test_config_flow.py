"""Config flow tests for Caruna+."""

from __future__ import annotations

from unittest.mock import MagicMock

from pycaruna.exceptions import CarunaApiError, CarunaAuthError
import pytest

from custom_components.caruna.const import CONF_ASSET_ID, CONF_POINTS, DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.hass.common import PASSWORD, USERNAME, mock_config_entry

pytestmark = pytest.mark.usefixtures("mock_caruna_client")


async def test_form_creates_entry(hass: HomeAssistant, mock_caruna_client: MagicMock):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "  A@B.FI ", CONF_PASSWORD: PASSWORD},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "  A@B.FI "
    assert result["result"].unique_id == USERNAME
    assert result["data"][CONF_POINTS][0][CONF_ASSET_ID] == "123456"
    mock_caruna_client.login.assert_called_once()


async def test_form_invalid_auth(hass: HomeAssistant, mock_caruna_client: MagicMock):
    mock_caruna_client.login.side_effect = CarunaAuthError("nope", status_code=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass: HomeAssistant, mock_caruna_client: MagicMock):
    mock_caruna_client.login.side_effect = CarunaApiError("down", status_code=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_form_no_customer_ids(hass: HomeAssistant, mock_caruna_client: MagicMock):
    mock_caruna_client.customer_ids.return_value = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_customer_ids"


async def test_form_no_metering_points(
    hass: HomeAssistant, mock_caruna_client: MagicMock
):
    mock_caruna_client.get_metering_points.return_value = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_metering_points"


async def test_form_already_configured(hass: HomeAssistant):
    entry = mock_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_succeeds(hass: HomeAssistant):
    entry = mock_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=dict(entry.data),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: USERNAME, CONF_PASSWORD: "new-secret"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-secret"


async def test_reauth_unique_id_mismatch(hass: HomeAssistant):
    entry = mock_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=dict(entry.data),
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "other@b.fi", CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_USERNAME] == USERNAME
