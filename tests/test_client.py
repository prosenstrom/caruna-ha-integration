"""Unit tests for the synchronous Caruna+ session wrapper."""

from datetime import date
from unittest.mock import Mock, patch

from pycaruna.exceptions import CarunaApiError, CarunaAuthError
import pytest


def test_login_stores_token_and_user(caruna_modules):
    client_mod = caruna_modules.client
    result = {
        "token": "tok",
        "expiresAt": 1_900_000_000,
        "user": {"ownCustomerNumbers": ["123"]},
    }
    with patch.object(client_mod, "Authenticator") as auth_cls:
        auth_cls.return_value.login.return_value = result
        with patch.object(client_mod, "CarunaPlus") as api_cls:
            client = client_mod.CarunaClient("a@b.fi", "secret")
            assert client.login() == result
            assert client.customer_ids() == ["123"]
            api_cls.assert_called_once_with("tok")


def test_get_metering_points_dedupes(caruna_modules):
    client_mod = caruna_modules.client
    client = client_mod.CarunaClient("a@b.fi", "secret")
    client._token = "tok"
    client._expires_at = 9_999_999_999
    client._user = {"ownCustomerNumbers": ["1", "2"]}
    api = Mock()
    api.get_metering_points.side_effect = [
        [{"assetId": "a", "customerId": "1"}],
        [{"assetId": "a", "customerId": "2"}, {"assetId": "b", "customerId": "2"}],
    ]
    client._api = api
    points = client.get_metering_points()
    assert [p["assetId"] for p in points] == ["a", "b"]


def test_get_metering_points_raises_without_customer_ids(caruna_modules):
    client_mod = caruna_modules.client
    client = client_mod.CarunaClient("a@b.fi", "secret")
    client._token = "tok"
    client._expires_at = 9_999_999_999
    client._user = {"userType": "unknown"}
    client._api = Mock()
    with pytest.raises(CarunaApiError, match="no customer numbers"):
        client.get_metering_points()


def test_get_energy_retries_after_auth_error(caruna_modules):
    client_mod = caruna_modules.client
    client = client_mod.CarunaClient("a@b.fi", "secret")
    client._token = "tok"
    client._expires_at = 9_999_999_999
    api = Mock()
    api.get_energy.side_effect = [
        CarunaAuthError("expired", status_code=401),
        {"results": [{"data": []}]},
    ]
    client._api = api
    with patch.object(client, "login") as login:
        payload = client.get_energy(
            "c", "a", client_mod.TimeSpan.DAILY, date(2026, 8, 16)
        )
    login.assert_called_once()
    assert payload == {"results": [{"data": []}]}
    assert api.get_energy.call_count == 2


def test_get_energy_does_not_retry_api_error(caruna_modules):
    client_mod = caruna_modules.client
    client = client_mod.CarunaClient("a@b.fi", "secret")
    client._token = "tok"
    client._expires_at = 9_999_999_999
    api = Mock()
    api.get_energy.side_effect = CarunaApiError("server", status_code=500)
    client._api = api
    with patch.object(client, "login") as login:
        with pytest.raises(CarunaApiError, match="server"):
            client.get_energy("c", "a", client_mod.TimeSpan.DAILY, date(2026, 8, 16))
    login.assert_not_called()


def test_login_defaults_expiry_when_missing(caruna_modules):
    client_mod = caruna_modules.client
    result = {"token": "tok", "user": {"ownCustomerNumbers": ["123"]}}
    with patch.object(client_mod, "Authenticator") as auth_cls:
        auth_cls.return_value.login.return_value = result
        with patch.object(client_mod, "CarunaPlus"):
            with patch.object(client_mod.time, "time", return_value=1_000_000):
                client = client_mod.CarunaClient("a@b.fi", "secret")
                client.login()
    assert client._expires_at == 1_000_000 + client_mod.TOKEN_TTL_SECONDS


def test_ensure_session_logs_in_when_token_missing(caruna_modules):
    client_mod = caruna_modules.client
    client = client_mod.CarunaClient("a@b.fi", "secret")
    with patch.object(client, "login") as login:
        client.ensure_session()
    login.assert_called_once()


def test_auth_error_is_exported(caruna_modules):
    assert caruna_modules.client.CarunaAuthError is CarunaAuthError
