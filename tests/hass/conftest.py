"""Home Assistant fixtures for Caruna+ config-flow and setup tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from pycaruna import TimeSpan
import pytest

from tests.hass.common import DAILY_PAYLOAD, METER


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Discover custom_components/caruna in these tests."""


@pytest.fixture
def mock_caruna_client() -> Generator[MagicMock]:
    """Patch CarunaClient in the config flow and coordinator."""
    client = MagicMock()
    client.login.return_value = {
        "token": "tok",
        "user": {"ownCustomerNumbers": ["111"]},
    }
    client.customer_ids.return_value = ["111"]
    client.get_metering_points.return_value = [METER]

    def _get_energy(_customer_id, _asset_id, timespan, _day):
        if timespan == TimeSpan.YEARLY:
            return {"results": [{"data": []}]}
        return DAILY_PAYLOAD

    client.get_energy.side_effect = _get_energy

    with (
        patch(
            "custom_components.caruna.config_flow.CarunaClient",
            return_value=client,
        ),
        patch(
            "custom_components.caruna.coordinator.CarunaClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def mock_statistics() -> Generator[None]:
    """Avoid a real recorder while still running setup."""

    async def _run(func, *args, **kwargs):
        return func(*args, **kwargs)

    instance = MagicMock()
    instance.async_add_executor_job = AsyncMock(side_effect=_run)
    instance.async_block_till_done = AsyncMock()

    with (
        patch(
            "custom_components.caruna.coordinator.get_instance",
            return_value=instance,
        ),
        patch(
            "custom_components.caruna.coordinator.get_last_statistics",
            return_value={},
        ),
        patch(
            "custom_components.caruna.coordinator.statistics_during_period",
            return_value={},
        ),
        patch("custom_components.caruna.coordinator.async_add_external_statistics"),
    ):
        yield


@pytest.fixture(autouse=True)
def auto_mock_statistics(mock_statistics: None) -> None:
    """Keep setup off the real recorder in every hass test."""
