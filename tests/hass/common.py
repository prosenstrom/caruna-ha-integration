"""Shared test data for Home Assistant tests."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.caruna.const import CONF_ASSET_ID, CONF_CUSTOMER_ID, DOMAIN
from custom_components.caruna.helpers import default_options
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

USERNAME = "a@b.fi"
PASSWORD = "secret"

METER = {
    "customerId": "111",
    "assetId": "123456",
    "gsrn": "643000000000000000",
    "contractProductDesc": "Yleissiirto",
    "address": {
        "streetName": "Testikatu",
        "houseNumber": "1",
        "postOffice": "Helsinki",
    },
}

DAILY_PAYLOAD = {
    "results": [
        {
            "data": [
                {
                    "timestamp": "2026-08-15T21:00:00.000Z",
                    "totalConsumption": 1.5,
                }
            ]
        }
    ]
}


def mock_config_entry(**kwargs) -> MockConfigEntry:
    """Config entry with one metering point."""
    data = {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        "points": [
            {
                CONF_CUSTOMER_ID: "111",
                CONF_ASSET_ID: "123456",
                "name": "Testikatu 1, Helsinki, Yleissiirto",
                "gsrn": METER["gsrn"],
                "model": METER["contractProductDesc"],
            }
        ],
    }
    data.update(kwargs.pop("data", {}))
    return MockConfigEntry(
        domain=DOMAIN,
        title="Testikatu 1, Helsinki, Yleissiirto",
        data=data,
        options=kwargs.pop("options", default_options()),
        unique_id=kwargs.pop("unique_id", USERNAME),
        **kwargs,
    )
