"""Pure helpers for Caruna+ parsing, labels, and cost. No Home Assistant import."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pycaruna import energy_kwh

from .const import (
    CONF_ENABLE_COST,
    CONF_MARGIN,
    CONF_TAX,
    CONF_TRANSFER,
    CONF_VAT,
    DEFAULT_ENABLE_COST,
    DEFAULT_MARGIN,
    DEFAULT_TAX,
    DEFAULT_TRANSFER,
    DEFAULT_VAT,
    DOMAIN,
    LEGACY_ENTITY_MARGIN,
    LEGACY_ENTITY_TAX,
    LEGACY_ENTITY_TRANSFER,
)

HELSINKI = ZoneInfo("Europe/Helsinki")
TOKEN_TTL_SECONDS = 50 * 60


def account_unique_id(username: str) -> str:
    """Stable config-entry unique id for a Caruna+ login."""
    return username.strip().lower()


def helsinki_date(moment: datetime) -> date:
    """Calendar date of a timestamp in Europe/Helsinki."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=HELSINKI)
    return moment.astimezone(HELSINKI).date()


def is_transient_status(status_code: int | None) -> bool:
    """True when a Caruna error should be retried (5xx or unknown)."""
    return status_code is None or status_code >= 500


def continue_sum(
    *,
    rebuild: bool,
    window_first: tuple[datetime, float] | None,
    last: tuple[datetime, float] | None,
) -> tuple[float, datetime | None]:
    """Running sum and last start to continue an external statistic series.

    Prefer the first row in the refresh window so late Caruna hours can be
    rewritten. If that window does not overlap existing statistics, continue
    from the global last row instead of restarting at 0.
    """
    if rebuild:
        return 0.0, None
    if window_first is not None:
        return window_first[1], window_first[0]
    if last is not None:
        return last[1], last[0]
    return 0.0, None


def asset_label(asset: dict[str, Any]) -> str:
    """Human-readable metering-point name."""
    address = asset.get("address") or {}
    street = f"{address.get('streetName', '')} {address.get('houseNumber', '')}".strip()
    city = address.get("postOffice") or ""
    product = asset.get("contractProductDesc") or ""
    return ", ".join(part for part in (street, city, product) if part) or str(
        asset.get("assetId")
    )


def stat_slug(asset_id: str) -> str:
    """Stable statistic id fragment for one metering point."""
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in asset_id).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug


def statistic_id_for(asset_id: str) -> str:
    """External statistic id for one metering point."""
    return f"{DOMAIN}:{stat_slug(asset_id)}_consumption"


def cost_statistic_id_for(asset_id: str) -> str:
    """External statistic id for all-in energy cost."""
    return f"{DOMAIN}:{stat_slug(asset_id)}_cost"


def payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a normalized Caruna energy payload into data rows."""
    rows: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        rows.extend(result.get("data") or [])
    return rows


def row_kwh(row: dict[str, Any]) -> float | None:
    """kWh from a current or older Caruna energy row."""
    value = energy_kwh(row)
    return float(value) if value is not None else None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a Caruna timestamp into UTC.

    Naive values are Europe/Helsinki wall time, not UTC.
    """
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=HELSINKI)
    return moment.astimezone(UTC)


def parse_slots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Caruna energy payload into timestamped consumption slots."""
    slots: list[dict[str, Any]] = []
    for row in payload_rows(payload):
        kwh = row_kwh(row)
        if kwh is None:
            continue
        start = parse_timestamp(row.get("timestamp"))
        if start is None:
            continue
        cost = row.get("totalcost")
        if cost is None:
            cost = row.get("totalFee")
        slots.append(
            {
                "start": start,
                "consumption": float(kwh),
                "temperature": row.get("temperature"),
                "cost": cost,
            }
        )
    slots.sort(key=lambda item: item["start"])
    return slots


def hourly_buckets(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum 15-minute (or other) slots into whole hours."""
    buckets: dict[datetime, dict[str, Any]] = {}
    for slot in slots:
        hour = slot["start"].replace(minute=0, second=0, microsecond=0)
        bucket = buckets.setdefault(
            hour, {"start": hour, "consumption": 0.0, "cost": 0.0, "temperature": None}
        )
        bucket["consumption"] += slot["consumption"]
        if slot.get("cost") is not None:
            bucket["cost"] += float(slot["cost"])
        if slot.get("temperature") is not None:
            bucket["temperature"] = slot["temperature"]
    return [buckets[key] for key in sorted(buckets)]


def hour_spot(hour_start: datetime, spots: dict[datetime, float]) -> float | None:
    """Average Nord Pool FI slots that fall inside this hour, EUR/kWh."""
    hour_start = hour_start.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)
    values = [price for start, price in spots.items() if hour_start <= start < hour_end]
    if not values:
        return None
    return sum(values) / len(values)


@dataclass(frozen=True)
class CostRates:
    """All-in variable cost pieces, EUR/kWh except VAT which is a multiplier."""

    enabled: bool
    vat_multiplier: float
    margin: float
    transfer: float
    tax: float

    def unit_price(self, spot: float) -> float:
        """EUR/kWh for one hour: (spot + margin) × VAT + transfer + tax."""
        return (spot + self.margin) * self.vat_multiplier + self.transfer + self.tax


def vat_multiplier(vat_percent: float) -> float:
    """Convert a VAT percent (25.5) to a multiplier (1.255)."""
    return 1.0 + float(vat_percent) / 100.0


def default_options() -> dict[str, Any]:
    """Options written on first config-entry create."""
    return {
        CONF_ENABLE_COST: DEFAULT_ENABLE_COST,
        CONF_VAT: DEFAULT_VAT,
        CONF_MARGIN: DEFAULT_MARGIN,
        CONF_TRANSFER: DEFAULT_TRANSFER,
        CONF_TAX: DEFAULT_TAX,
    }


def cost_rates_from_options(options: Mapping[str, Any]) -> CostRates:
    """Build cost rates from config-entry options only."""
    vat = float(options.get(CONF_VAT, DEFAULT_VAT))
    return CostRates(
        enabled=bool(options.get(CONF_ENABLE_COST, DEFAULT_ENABLE_COST)),
        vat_multiplier=vat_multiplier(vat),
        margin=float(options.get(CONF_MARGIN, DEFAULT_MARGIN)),
        transfer=float(options.get(CONF_TRANSFER, DEFAULT_TRANSFER)),
        tax=float(options.get(CONF_TAX, DEFAULT_TAX)),
    )


def cost_option_keys_present(options: Mapping[str, Any]) -> bool:
    """True when the user has saved the cost options form at least once."""
    return any(
        key in options
        for key in (CONF_MARGIN, CONF_TRANSFER, CONF_TAX, CONF_ENABLE_COST)
    )


def resolve_cost_rates(
    options: Mapping[str, Any],
    get_float_state: Callable[[str], float | None] | None = None,
) -> CostRates:
    """Options first; pre-options installs fall back to legacy template sensors."""
    rates = cost_rates_from_options(options)
    if cost_option_keys_present(options) or get_float_state is None:
        return rates

    margin = get_float_state(LEGACY_ENTITY_MARGIN)
    transfer = get_float_state(LEGACY_ENTITY_TRANSFER)
    tax = get_float_state(LEGACY_ENTITY_TAX)
    if margin is None and transfer is None and tax is None:
        return rates
    return CostRates(
        enabled=rates.enabled,
        vat_multiplier=rates.vat_multiplier,
        margin=DEFAULT_MARGIN if margin is None else margin,
        transfer=DEFAULT_TRANSFER if transfer is None else transfer,
        tax=DEFAULT_TAX if tax is None else tax,
    )


def suggested_cost_options(
    options: Mapping[str, Any],
    get_float_state: Callable[[str], float | None] | None = None,
) -> dict[str, Any]:
    """Values to pre-fill the options form."""
    rates = resolve_cost_rates(options, get_float_state)
    vat = float(options.get(CONF_VAT, DEFAULT_VAT))
    return {
        CONF_ENABLE_COST: rates.enabled,
        CONF_VAT: vat,
        CONF_MARGIN: rates.margin,
        CONF_TRANSFER: rates.transfer,
        CONF_TAX: rates.tax,
    }


def rates_changed(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    """True when cost formula inputs changed."""
    keys = (CONF_ENABLE_COST, CONF_VAT, CONF_MARGIN, CONF_TRANSFER, CONF_TAX)
    return any(old.get(key) != new.get(key) for key in keys)
