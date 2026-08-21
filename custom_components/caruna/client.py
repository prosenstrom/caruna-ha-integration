"""Synchronous Caruna+ client. Run from an executor thread."""

from __future__ import annotations

from datetime import date
import logging
import threading
import time
from typing import Any

from pycaruna import Authenticator, CarunaPlus, TimeSpan, customer_ids_from_user
from pycaruna.exceptions import CarunaApiError, CarunaAuthError

from .helpers import TOKEN_TTL_SECONDS

_LOGGER = logging.getLogger(__name__)

__all__ = ["CarunaApiError", "CarunaAuthError", "CarunaClient"]


class CarunaClient:
    """Caruna+ session on top of prosenstrom/pycaruna."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._token: str | None = None
        self._expires_at = 0
        self._user: dict[str, Any] = {}
        self._api: CarunaPlus | None = None
        self._lock = threading.Lock()

    def login(self) -> dict[str, Any]:
        """Log in and store the token."""
        with self._lock:
            return self._login_unlocked()

    def _login_unlocked(self) -> dict[str, Any]:
        result = Authenticator(self._username, self._password).login()
        self._token = result["token"]
        expires = result.get("expiresAt")
        self._expires_at = (
            int(expires) if expires else int(time.time()) + TOKEN_TTL_SECONDS
        )
        self._user = result.get("user") or {}
        self._api = CarunaPlus(self._token)
        return result

    def ensure_session(self) -> None:
        """Log in when there is no token or it is about to expire."""
        now = int(time.time())
        if self._token and now < self._expires_at - 60:
            return
        self.login()

    def customer_ids(self) -> list[str]:
        """Customer numbers the logged-in user can access."""
        return customer_ids_from_user(self._user)

    def get_metering_points(self) -> list[dict[str, Any]]:
        """Return metering points for every customer on the account."""
        self.ensure_session()
        assert self._api is not None
        customer_ids = self.customer_ids()
        _LOGGER.debug(
            "Caruna+ userType=%s customer_ids=%s",
            self._user.get("userType"),
            customer_ids,
        )
        if not customer_ids:
            raise CarunaApiError(
                "Logged in, but the token has no customer numbers "
                f"(userType={self._user.get('userType')})"
            )

        points: list[dict[str, Any]] = []
        seen: set[str] = set()
        for customer_id in customer_ids:
            for asset in self._api.get_metering_points(customer_id):
                asset_id = str(asset.get("assetId") or "")
                if not asset_id or asset_id in seen:
                    continue
                seen.add(asset_id)
                points.append(asset)
        if not points:
            _LOGGER.warning(
                "Caruna+ login ok but no meters. userType=%s customers=%s",
                self._user.get("userType"),
                customer_ids,
            )
        return points

    def get_energy(
        self,
        customer_id: str,
        asset_id: str,
        timespan: TimeSpan,
        day: date,
    ) -> dict[str, Any]:
        """Fetch energy data for one day/month/year window."""
        self.ensure_session()
        assert self._api is not None
        try:
            return self._api.get_energy(
                customer_id,
                asset_id,
                timespan,
                day.year,
                day.month,
                day.day,
            )
        except CarunaAuthError:
            _LOGGER.debug("Energy call unauthorized, logging in again")
            self.login()
            assert self._api is not None
            return self._api.get_energy(
                customer_id,
                asset_id,
                timespan,
                day.year,
                day.month,
                day.day,
            )
