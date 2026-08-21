"""Config flow for Caruna+."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import CarunaApiError, CarunaAuthError, CarunaClient
from .const import (
    CONF_ASSET_ID,
    CONF_BACKFILL_DONE,
    CONF_COST_BACKFILL_DONE,
    CONF_CUSTOMER_ID,
    CONF_ENABLE_COST,
    CONF_MARGIN,
    CONF_POINTS,
    CONF_TAX,
    CONF_TRANSFER,
    CONF_VAT,
    DOMAIN,
)
from .helpers import (
    asset_label,
    default_options,
    rates_changed,
    suggested_cost_options,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


def _float_state(hass, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def _options_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ENABLE_COST): BooleanSelector(),
            vol.Required(CONF_VAT): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            vol.Required(CONF_MARGIN): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=1,
                    step=0.0001,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="EUR/kWh",
                )
            ),
            vol.Required(CONF_TRANSFER): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=1,
                    step=0.0001,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="EUR/kWh",
                )
            ),
            vol.Required(CONF_TAX): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=1,
                    step=0.0000001,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="EUR/kWh",
                )
            ),
        }
    )


class CarunaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Caruna+."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> CarunaOptionsFlow:
        """Return the options flow."""
        return CarunaOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect Caruna+ email and password."""
        errors: dict[str, str] = {}
        if user_input:
            client = CarunaClient(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            try:
                await self.hass.async_add_executor_job(client.login)
                points = await self.hass.async_add_executor_job(
                    client.get_metering_points
                )
            except CarunaAuthError as err:
                _LOGGER.warning("Caruna+ login rejected: %s", err)
                errors["base"] = "invalid_auth"
            except CarunaApiError as err:
                _LOGGER.warning("Caruna+ connection failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while connecting to Caruna+")
                errors["base"] = "unknown"
            else:
                if not points:
                    return self.async_abort(reason="no_metering_points")

                customer_ids = client.customer_ids()
                unique = customer_ids[0] if customer_ids else user_input[CONF_USERNAME]
                await self.async_set_unique_id(str(unique))

                stored_points = [
                    {
                        CONF_CUSTOMER_ID: item["customerId"],
                        CONF_ASSET_ID: item["assetId"],
                        "name": asset_label(item),
                        "gsrn": item.get("gsrn"),
                        "model": item.get("contractProductDesc"),
                    }
                    for item in points
                ]
                data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_POINTS: stored_points,
                }
                if self.source == SOURCE_REAUTH:
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=data
                    )
                self._abort_if_unique_id_configured()
                title = (
                    stored_points[0]["name"] if len(stored_points) == 1 else "Caruna+"
                )
                return self.async_create_entry(
                    title=title, data=data, options=default_options()
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle expired or changed Caruna+ credentials."""
        return await self.async_step_user()


class CarunaOptionsFlow(OptionsFlowWithReload):
    """Cost-rate options for the Energy dashboard series."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit VAT, margin, transfer, and tax."""
        if user_input is not None:
            previous = dict(self.config_entry.options)
            options = {
                **previous,
                CONF_ENABLE_COST: bool(user_input[CONF_ENABLE_COST]),
                CONF_VAT: float(user_input[CONF_VAT]),
                CONF_MARGIN: float(user_input[CONF_MARGIN]),
                CONF_TRANSFER: float(user_input[CONF_TRANSFER]),
                CONF_TAX: float(user_input[CONF_TAX]),
            }
            if not options[CONF_ENABLE_COST]:
                options[CONF_COST_BACKFILL_DONE] = True
            elif rates_changed(previous, options):
                options[CONF_COST_BACKFILL_DONE] = False
            options.setdefault(
                CONF_BACKFILL_DONE, previous.get(CONF_BACKFILL_DONE, False)
            )
            return self.async_create_entry(data=options)

        suggested = suggested_cost_options(
            self.config_entry.options,
            lambda entity_id: _float_state(self.hass, entity_id),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(), suggested
            ),
        )
