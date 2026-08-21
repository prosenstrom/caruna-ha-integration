"""Constants for the Caruna+ integration."""

from datetime import timedelta

DOMAIN = "caruna"

DEFAULT_NAME = "Caruna+"
UPDATE_INTERVAL = timedelta(hours=1)
# After a full backfill, only re-fetch the last few days for late Caruna hours.
REFRESH_DAYS = 3
# Walk this many calendar years backward until a year has no kWh.
BACKFILL_YEAR_LIMIT = 20

CONF_POINTS = "points"
CONF_CUSTOMER_ID = "customer_id"
CONF_ASSET_ID = "asset_id"
CONF_BACKFILL_DONE = "backfill_done"
CONF_COST_BACKFILL_DONE = "cost_backfill_done"

CONF_ENABLE_COST = "enable_cost"
CONF_VAT = "vat"
CONF_MARGIN = "margin"
CONF_TRANSFER = "transfer"
CONF_TAX = "tax"

DEFAULT_ENABLE_COST = True
DEFAULT_VAT = 25.5
DEFAULT_MARGIN = 0.0
DEFAULT_TRANSFER = 0.0
# Finnish electricity tax, EUR/kWh, billed amount including VAT.
DEFAULT_TAX = 0.0282752

# Unmigrated entries without option keys still read these template sensors.
LEGACY_ENTITY_MARGIN = "sensor.sahko_marginaali"
LEGACY_ENTITY_TRANSFER = "sensor.sahko_siirto"
LEGACY_ENTITY_TAX = "sensor.sahko_sahkovero"
