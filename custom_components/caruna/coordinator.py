"""Data update coordinator for Caruna+."""

from __future__ import annotations

import asyncio
import calendar
from contextlib import suppress
from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, cast

from pycaruna import TimeSpan

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.components.recorder.util import get_instance
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .client import CarunaApiError, CarunaAuthError, CarunaClient
from .const import (
    BACKFILL_YEAR_LIMIT,
    CONF_ASSET_ID,
    CONF_BACKFILL_DONE,
    CONF_COST_BACKFILL_DONE,
    CONF_CUSTOMER_ID,
    CONF_ENABLE_COST,
    CONF_POINTS,
    DOMAIN,
    REFRESH_DAYS,
    UPDATE_INTERVAL,
)
from .helpers import (
    HELSINKI,
    CostRates,
    asset_label,
    continue_sum,
    cost_statistic_id_for,
    helsinki_date,
    hour_spot,
    hourly_buckets,
    is_transient_status,
    parse_slots,
    parse_timestamp,
    payload_rows,
    resolve_cost_rates,
    row_kwh,
    statistic_id_for,
)

if TYPE_CHECKING:
    from . import CarunaConfigEntry

_LOGGER = logging.getLogger(__name__)


def _float_state(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def _sum_on_date(hours: list[dict[str, Any]], day: date) -> float | None:
    matching = [
        item["consumption"] for item in hours if helsinki_date(item["start"]) == day
    ]
    if not matching:
        return None
    return round(sum(matching), 3)


class CarunaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Caruna+ and publish hourly statistics."""

    config_entry: CarunaConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CarunaConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = CarunaClient(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        self._backfill_lock = asyncio.Lock()
        self._backfill_task: asyncio.Task[None] | None = None

    def _cost_rates(self) -> CostRates:
        return resolve_cost_rates(
            self.config_entry.options,
            lambda entity_id: _float_state(self.hass, entity_id),
        )

    def schedule_backfill(self) -> bool:
        """Start a full history import when kWh or cost still need backfill.

        Returns True if a new task was started.
        """
        options = self.config_entry.options
        cost_done = options.get(CONF_COST_BACKFILL_DONE)
        if not options.get(CONF_ENABLE_COST, True):
            cost_done = True
        if options.get(CONF_BACKFILL_DONE) and cost_done:
            return False
        if self._backfill_task is not None and not self._backfill_task.done():
            return False
        self._backfill_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_full_backfill(),
            "caruna_history_backfill",
        )
        return True

    async def async_shutdown(self) -> None:
        """Stop polling and cancel an in-flight history backfill."""
        task = self._backfill_task
        self._backfill_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.hass.async_add_executor_job(self._fetch_data)
        except CarunaAuthError as err:
            raise ConfigEntryAuthFailed("Caruna+ login failed") from err
        except CarunaApiError as err:
            raise UpdateFailed(str(err)) from err

        if not self._backfill_lock.locked():
            async with self._backfill_lock:
                rates = self._cost_rates()
                for point in data["points"].values():
                    await self._async_import_statistics(
                        point["asset_id"], point["name"], point["hours"]
                    )
                    if rates.enabled and self.config_entry.options.get(
                        CONF_COST_BACKFILL_DONE
                    ):
                        await self._async_import_cost_statistics(
                            point["asset_id"], point["name"]
                        )

        if self.hass.is_running:
            self.schedule_backfill()
        return data

    def _fetch_data(self) -> dict[str, Any]:
        points = list(self.config_entry.data.get(CONF_POINTS) or [])
        if not points:
            discovered = self.client.get_metering_points()
            points = [
                {
                    CONF_CUSTOMER_ID: item["customerId"],
                    CONF_ASSET_ID: item["assetId"],
                    "name": asset_label(item),
                    "asset": item,
                }
                for item in discovered
            ]
        if not points:
            raise UpdateFailed("No Caruna+ metering points on this account")

        today = dt_util.now(HELSINKI).date()
        result: dict[str, Any] = {"points": {}}
        for point in points:
            result["points"][point[CONF_ASSET_ID]] = self._fetch_point(point, today)
        return result

    def _fetch_point(self, point: dict[str, Any], today: date) -> dict[str, Any]:
        customer_id = point[CONF_CUSTOMER_ID]
        asset_id = point[CONF_ASSET_ID]
        start = today - timedelta(days=REFRESH_DAYS - 1)
        slots, _transient = self._fetch_daily_range(customer_id, asset_id, start, today)

        by_start = {slot["start"]: slot for slot in slots}
        hours = hourly_buckets([by_start[key] for key in sorted(by_start)])

        try:
            month_payload = self.client.get_energy(
                customer_id, asset_id, TimeSpan.MONTHLY, today.replace(day=1)
            )
            month_slots = parse_slots(month_payload)
        except CarunaApiError as err:
            _LOGGER.warning("Skipping Caruna+ month total: %s", err)
            month_slots = []
        month_total = (
            round(sum(item["consumption"] for item in month_slots), 3)
            if month_slots
            else None
        )

        yesterday = today - timedelta(days=1)
        last_hour = hours[-1] if hours else None
        return {
            "name": point.get("name") or asset_id,
            "asset": point.get("asset")
            or {
                "gsrn": point.get("gsrn"),
                "contractProductDesc": point.get("model"),
            },
            "customer_id": customer_id,
            "asset_id": asset_id,
            "hours": hours,
            "yesterday": _sum_on_date(hours, yesterday),
            "today": _sum_on_date(hours, today),
            "month": month_total,
            "last_hour": last_hour["consumption"] if last_hour else None,
            "last_hour_start": last_hour["start"] if last_hour else None,
            "yesterday_hours": [
                item for item in hours if helsinki_date(item["start"]) == yesterday
            ],
            "today_hours": [
                item for item in hours if helsinki_date(item["start"]) == today
            ],
        }

    def _fetch_daily_range(
        self, customer_id: str, asset_id: str, start: date, end: date
    ) -> tuple[list[dict[str, Any]], int]:
        slots: list[dict[str, Any]] = []
        transient = 0
        cursor = start
        while cursor <= end:
            try:
                payload = self.client.get_energy(
                    customer_id, asset_id, TimeSpan.DAILY, cursor
                )
            except CarunaApiError as err:
                _LOGGER.warning("Skipping Caruna+ day %s: %s", cursor, err)
                if is_transient_status(err.status_code):
                    transient += 1
            else:
                slots.extend(parse_slots(payload))
            cursor += timedelta(days=1)
        return slots, transient

    def _discover_months(
        self, customer_id: str, asset_id: str, today: date
    ) -> tuple[list[tuple[int, int]], bool]:
        """Return (year, month) pairs that Caruna has kWh for, newest years first."""
        months: list[tuple[int, int]] = []
        found_any = False
        incomplete = False
        for year in range(today.year, today.year - BACKFILL_YEAR_LIMIT, -1):
            try:
                payload = self.client.get_energy(
                    customer_id, asset_id, TimeSpan.YEARLY, date(year, 1, 1)
                )
            except CarunaApiError as err:
                _LOGGER.warning("Skipping Caruna+ year %s: %s", year, err)
                if is_transient_status(err.status_code):
                    incomplete = True
                if found_any:
                    break
                continue
            year_months: list[tuple[int, int]] = []
            for row in payload_rows(payload):
                if row_kwh(row) is None:
                    continue
                start = parse_timestamp(row.get("timestamp") or "")
                if start is None:
                    continue
                local_day = helsinki_date(start)
                year_months.append((local_day.year, local_day.month))
            if not year_months:
                if found_any:
                    break
                continue
            found_any = True
            months.extend(year_months)
        months.sort()
        return months, incomplete

    def _fetch_all_history(self) -> dict[str, Any]:
        points = list(self.config_entry.data.get(CONF_POINTS) or [])
        if not points:
            raise UpdateFailed("No Caruna+ metering points on this account")
        today = dt_util.now(HELSINKI).date()
        result: dict[str, Any] = {"points": {}, "incomplete": False}
        for point in points:
            customer_id = point[CONF_CUSTOMER_ID]
            asset_id = point[CONF_ASSET_ID]
            months, months_incomplete = self._discover_months(
                customer_id, asset_id, today
            )
            if months_incomplete:
                result["incomplete"] = True
            slots: list[dict[str, Any]] = []
            for year, month in months:
                last_day = calendar.monthrange(year, month)[1]
                start = date(year, month, 1)
                end = min(date(year, month, last_day), today)
                _LOGGER.info("Backfilling Caruna+ %s %04d-%02d", asset_id, year, month)
                day_slots, transient = self._fetch_daily_range(
                    customer_id, asset_id, start, end
                )
                if transient:
                    result["incomplete"] = True
                slots.extend(day_slots)
            by_start = {slot["start"]: slot for slot in slots}
            hours = hourly_buckets([by_start[key] for key in sorted(by_start)])
            result["points"][asset_id] = {
                "name": point.get("name") or asset_id,
                "asset_id": asset_id,
                "hours": hours,
            }
        return result

    async def _async_full_backfill(self) -> None:
        """Pull every Caruna hour on the meter, then the matching cost series."""
        try:
            async with self._backfill_lock:
                await self._async_run_backfill()
        except asyncio.CancelledError:
            raise
        if self.hass.is_running:
            await self.async_request_refresh()

    async def _async_run_backfill(self) -> None:
        if not self.config_entry.options.get(CONF_BACKFILL_DONE):
            _LOGGER.warning("Starting full Caruna+ history backfill")
            try:
                data = await self.hass.async_add_executor_job(self._fetch_all_history)
            except CarunaAuthError:
                _LOGGER.exception("Caruna+ backfill login failed")
                return
            except (CarunaApiError, UpdateFailed) as err:
                _LOGGER.warning("Caruna+ backfill failed: %s", err)
                return

            imported = 0
            incomplete = bool(data.get("incomplete"))
            for point in data["points"].values():
                imported += len(point["hours"])
                await self._async_import_statistics(
                    point["asset_id"], point["name"], point["hours"], rebuild=True
                )
            await get_instance(self.hass).async_block_till_done()
            if imported and not incomplete:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options={
                        **self.config_entry.options,
                        CONF_BACKFILL_DONE: True,
                    },
                )
                _LOGGER.warning(
                    "Caruna+ history backfill finished (%s hours)", imported
                )
            elif imported:
                _LOGGER.warning("Caruna+ backfill incomplete; will retry")
                return
            else:
                _LOGGER.warning("Caruna+ backfill found no hourly kWh")
                return

        rates = self._cost_rates()
        if not rates.enabled:
            return
        if self.config_entry.options.get(CONF_COST_BACKFILL_DONE):
            return

        _LOGGER.warning("Starting Caruna+ cost backfill from Nord Pool")
        points = list(self.config_entry.data.get(CONF_POINTS) or [])
        if not points:
            return
        for point in points:
            name = point.get("name") or point[CONF_ASSET_ID]
            await self._async_import_cost_statistics(
                point[CONF_ASSET_ID], name, rebuild=True
            )
        await get_instance(self.hass).async_block_till_done()
        for point in points:
            last = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                cost_statistic_id_for(point[CONF_ASSET_ID]),
                True,
                {"sum"},
            )
            if not last:
                _LOGGER.warning("Caruna+ cost backfill wrote no hours; will retry")
                return
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                CONF_COST_BACKFILL_DONE: True,
            },
        )
        _LOGGER.warning("Caruna+ cost backfill finished")

    async def _async_import_statistics(
        self,
        asset_id: str,
        name: str,
        hours: list[dict[str, Any]],
        rebuild: bool = False,
    ) -> None:
        if not hours:
            return

        stat_id = statistic_id_for(asset_id)
        current_hour = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        usable = [item for item in hours if item["start"] < current_hour]
        if not usable:
            return

        window_first: tuple[datetime, float] | None = None
        last: tuple[datetime, float] | None = None
        if not rebuild:
            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, stat_id, True, {"sum"}
            )
            last_rows = (last_stats or {}).get(stat_id) or []
            if last_rows:
                last = (
                    dt_util.utc_from_timestamp(last_rows[0]["start"]),
                    cast(float, last_rows[0]["sum"]),
                )
                from_time = usable[0]["start"]
                existing = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    from_time - timedelta(hours=1),
                    None,
                    {stat_id},
                    "hour",
                    None,
                    {"sum"},
                )
                window = (existing or {}).get(stat_id) or []
                if window:
                    window_first = (
                        dt_util.utc_from_timestamp(window[0]["start"]),
                        cast(float, window[0]["sum"]),
                    )

        running, last_start = continue_sum(
            rebuild=rebuild, window_first=window_first, last=last
        )

        statistics: list[StatisticData] = []
        for item in usable:
            start = item["start"]
            if last_start is not None and start <= last_start:
                continue
            running += item["consumption"]
            statistics.append(
                StatisticData(start=start, state=item["consumption"], sum=running)
            )
            last_start = start

        if not statistics:
            return

        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name} consumption",
                source=DOMAIN,
                statistic_id=stat_id,
                unit_class=EnergyConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            ),
            statistics,
        )
        _LOGGER.debug("Imported %s Caruna hours for %s", len(statistics), asset_id)

    async def _nordpool_spots(self, days: set[date]) -> dict[datetime, float]:
        """Return Nord Pool FI spot EUR/kWh keyed by slot start (UTC)."""
        if not days:
            return {}
        start_day = min(days)
        end_day = max(days)
        session = async_get_clientsession(self.hass)
        url = (
            "https://api.energy-charts.info/price"
            f"?bzn=FI&start={start_day.isoformat()}&end={end_day.isoformat()}"
        )
        try:
            async with session.get(url, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = await response.json()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("energy-charts FI prices failed: %s", err)
            return await self._nordpool_spots_via_service(days)

        stamps = payload.get("unix_seconds") or []
        prices = payload.get("price") or []
        by_start: dict[datetime, float] = {}
        for stamp, price in zip(stamps, prices, strict=False):
            if price is None:
                continue
            start = dt_util.utc_from_timestamp(int(stamp))
            by_start[start] = float(price) / 1000.0
        _LOGGER.debug(
            "Loaded %s FI spot slots from energy-charts (%s to %s)",
            len(by_start),
            start_day,
            end_day,
        )
        return by_start

    async def _nordpool_spots_via_service(
        self, days: set[date]
    ) -> dict[datetime, float]:
        """Fallback: official Nord Pool service, one day at a time."""
        entries = self.hass.config_entries.async_entries("nordpool")
        if not entries:
            _LOGGER.warning("Nord Pool is not configured; cannot price Caruna hours")
            return {}
        if not self.hass.services.has_service("nordpool", "get_prices_for_date"):
            return {}

        entry_id = entries[0].entry_id
        by_start: dict[datetime, float] = {}
        for day in sorted(days):
            try:
                result = await self.hass.services.async_call(
                    "nordpool",
                    "get_prices_for_date",
                    {
                        "config_entry": entry_id,
                        "date": day.isoformat(),
                        "areas": ["FI"],
                        "currency": "EUR",
                    },
                    blocking=True,
                    return_response=True,
                )
            except Exception as err:  # noqa: BLE001 — keep backfill going
                _LOGGER.warning("Nord Pool prices for %s failed: %s", day, err)
                continue
            slots = []
            if isinstance(result, dict):
                slots = result.get("FI") or []
                if not slots:
                    for value in result.values():
                        if isinstance(value, dict) and value.get("FI"):
                            slots = value["FI"]
                            break
            for slot in slots or []:
                start = dt_util.parse_datetime(str(slot.get("start") or ""))
                if start is None or slot.get("price") is None:
                    continue
                by_start[dt_util.as_utc(start)] = float(slot["price"]) / 1000.0
            await asyncio.sleep(0.25)
        return by_start

    async def _async_import_cost_statistics(
        self, asset_id: str, name: str, rebuild: bool = False
    ) -> None:
        """Write all-in EUR cost for each imported Caruna hour."""
        rates = self._cost_rates()
        if not rates.enabled:
            return

        cons_id = statistic_id_for(asset_id)
        cost_id = cost_statistic_id_for(asset_id)
        instance = get_instance(self.hass)
        origin = dt_util.parse_datetime("2015-01-01T00:00:00+00:00")
        assert origin is not None

        running = 0.0
        last_start: datetime | None = None
        if not rebuild:
            last_stats = await instance.async_add_executor_job(
                get_last_statistics, self.hass, 1, cost_id, True, {"sum"}
            )
            last_rows = (last_stats or {}).get(cost_id) or []
            if last_rows:
                last_start = dt_util.utc_from_timestamp(last_rows[0]["start"])
                running = cast(float, last_rows[0]["sum"])
                origin = last_start

        consumption = await instance.async_add_executor_job(
            statistics_during_period,
            self.hass,
            origin,
            None,
            {cons_id},
            "hour",
            None,
            {"state"},
        )
        hours = consumption.get(cons_id) or []
        if not hours:
            return

        pending: list[tuple[datetime, float]] = []
        for row in hours:
            start = dt_util.utc_from_timestamp(row["start"])
            if last_start is not None and start <= last_start:
                continue
            kwh = row.get("state")
            if kwh is None:
                continue
            pending.append((start, float(kwh)))
        pending.sort()
        if not pending:
            return

        days = {helsinki_date(start) for start, _kwh in pending}
        spots = await self._nordpool_spots(days)
        if not spots:
            _LOGGER.warning("No Nord Pool spots for Caruna cost import")
            return

        statistics: list[StatisticData] = []
        skipped = 0
        for start, kwh in pending:
            spot = hour_spot(start, spots)
            if spot is None:
                skipped += 1
                break
            cost = kwh * rates.unit_price(spot)
            running += cost
            statistics.append(StatisticData(start=start, state=cost, sum=running))

        if not statistics:
            return

        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name} cost",
                source=DOMAIN,
                statistic_id=cost_id,
                unit_class=None,
                unit_of_measurement="EUR",
            ),
            statistics,
        )
        _LOGGER.info(
            "Imported %s Caruna cost hours for %s (skipped %s without spot)",
            len(statistics),
            asset_id,
            skipped,
        )
