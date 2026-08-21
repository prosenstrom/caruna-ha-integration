"""Unit tests for Caruna+ parse, label, and cost helpers."""

from datetime import UTC, datetime

import pytest


def test_asset_label_joins_address_and_product(caruna_modules):
    helpers = caruna_modules.helpers
    label = helpers.asset_label(
        {
            "assetId": "123456",
            "address": {
                "streetName": "Testikatu",
                "houseNumber": "1",
                "postOffice": "Helsinki",
            },
            "contractProductDesc": "Yleissiirto 25 A",
        }
    )
    assert label == "Testikatu 1, Helsinki, Yleissiirto 25 A"


def test_asset_label_falls_back_to_asset_id(caruna_modules):
    assert caruna_modules.helpers.asset_label({"assetId": "abc"}) == "abc"


def test_statistic_ids(caruna_modules):
    helpers = caruna_modules.helpers
    assert helpers.statistic_id_for("123456") == "caruna:123456_consumption"
    assert helpers.cost_statistic_id_for("123456") == "caruna:123456_cost"
    assert helpers.statistic_id_for("A B") == "caruna:a_b_consumption"


def test_parse_slots_reads_total_consumption(caruna_modules):
    payload = {
        "results": [
            {
                "data": [
                    {
                        "timestamp": "2026-08-15T21:00:00.000Z",
                        "temperature": 12.1,
                        "totalConsumption": 1.33,
                    },
                    {
                        "timestamp": "2026-08-15T21:15:00.000Z",
                        "totalConsumption": 0.4,
                    },
                    {"timestamp": "2026-08-15T21:30:00.000Z", "consumption": None},
                ]
            }
        ]
    }
    slots = caruna_modules.helpers.parse_slots(payload)
    assert len(slots) == 2
    assert slots[0]["consumption"] == 1.33
    assert slots[0]["start"] == datetime(2026, 8, 15, 21, 0, tzinfo=UTC)
    hours = caruna_modules.helpers.hourly_buckets(slots)
    assert len(hours) == 1
    assert hours[0]["consumption"] == pytest.approx(1.73)
    assert hours[0]["start"] == datetime(2026, 8, 15, 21, 0, tzinfo=UTC)


def test_parse_slots_accepts_legacy_consumption_key(caruna_modules):
    payload = {
        "results": [
            {
                "data": [
                    {
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "consumption": 2.5,
                        "totalcost": 0.1,
                    }
                ]
            }
        ]
    }
    slots = caruna_modules.helpers.parse_slots(payload)
    assert slots[0]["consumption"] == 2.5
    assert slots[0]["cost"] == 0.1


def test_row_kwh_prefers_consumption(caruna_modules):
    helpers = caruna_modules.helpers
    assert helpers.row_kwh({"consumption": 1, "totalConsumption": 9}) == 1.0
    assert helpers.row_kwh({"invoicedConsumption": 3}) == 3.0
    assert helpers.row_kwh({}) is None


def test_unit_price_matches_finnish_spot_plus_addons(caruna_modules):
    helpers = caruna_modules.helpers
    rates = helpers.CostRates(
        enabled=True,
        vat_multiplier=1.255,
        margin=0.0039,
        transfer=0.0526,
        tax=0.0282752,
    )
    # (0.05 + 0.0039) * 1.255 + 0.0526 + 0.0282752
    assert rates.unit_price(0.05) == pytest.approx(0.1485197)


def test_cost_rates_from_options_defaults(caruna_modules):
    helpers = caruna_modules.helpers
    const = caruna_modules.const
    rates = helpers.cost_rates_from_options({})
    assert rates.enabled is True
    assert rates.margin == 0.0
    assert rates.transfer == 0.0
    assert rates.tax == const.DEFAULT_TAX
    assert rates.vat_multiplier == pytest.approx(1.255)


def test_resolve_cost_rates_uses_options_when_saved(caruna_modules):
    helpers = caruna_modules.helpers
    const = caruna_modules.const
    rates = helpers.resolve_cost_rates(
        {
            const.CONF_MARGIN: 0.01,
            const.CONF_TRANSFER: 0.02,
            const.CONF_TAX: 0.03,
            const.CONF_VAT: 25.5,
            const.CONF_ENABLE_COST: True,
        },
        lambda _entity: 99.0,
    )
    assert rates.margin == 0.01
    assert rates.transfer == 0.02
    assert rates.tax == 0.03


def test_resolve_cost_rates_legacy_entities(caruna_modules):
    helpers = caruna_modules.helpers
    const = caruna_modules.const
    states = {
        const.LEGACY_ENTITY_MARGIN: 0.0039,
        const.LEGACY_ENTITY_TRANSFER: 0.0526,
        const.LEGACY_ENTITY_TAX: 0.0282752,
    }
    rates = helpers.resolve_cost_rates({}, states.get)
    assert rates.margin == 0.0039
    assert rates.transfer == 0.0526
    assert rates.tax == 0.0282752


def test_resolve_cost_rates_no_legacy_entities(caruna_modules):
    helpers = caruna_modules.helpers
    rates = helpers.resolve_cost_rates({}, lambda _entity: None)
    assert rates.margin == 0.0
    assert rates.transfer == 0.0


def test_hour_spot_averages_quarter_hours(caruna_modules):
    helpers = caruna_modules.helpers
    hour = datetime(2026, 8, 15, 21, 0, tzinfo=UTC)
    spots = {
        datetime(2026, 8, 15, 21, 0, tzinfo=UTC): 0.04,
        datetime(2026, 8, 15, 21, 15, tzinfo=UTC): 0.06,
        datetime(2026, 8, 15, 21, 30, tzinfo=UTC): 0.08,
        datetime(2026, 8, 15, 21, 45, tzinfo=UTC): 0.02,
        datetime(2026, 8, 15, 22, 0, tzinfo=UTC): 9.0,
    }
    assert helpers.hour_spot(hour, spots) == pytest.approx(0.05)


def test_hour_spot_missing_returns_none(caruna_modules):
    helpers = caruna_modules.helpers
    hour = datetime(2026, 8, 15, 21, 0, tzinfo=UTC)
    later = datetime(2026, 8, 15, 22, 0, tzinfo=UTC)
    assert helpers.hour_spot(hour, {}) is None
    assert helpers.hour_spot(hour, {later: 0.04}) is None


def test_parse_timestamp_naive_is_helsinki(caruna_modules):
    helpers = caruna_modules.helpers
    moment = helpers.parse_timestamp("2026-01-01T00:00:00")
    assert moment == datetime(2025, 12, 31, 22, 0, tzinfo=UTC)


def test_helsinki_date_uses_finnish_calendar(caruna_modules):
    helpers = caruna_modules.helpers
    # 21:00 UTC on 15 Aug is 00:00 on 16 Aug in Helsinki (EEST).
    moment = datetime(2026, 8, 15, 21, 0, tzinfo=UTC)
    assert helpers.helsinki_date(moment).isoformat() == "2026-08-16"


def test_account_unique_id_normalizes_email(caruna_modules):
    helpers = caruna_modules.helpers
    assert helpers.account_unique_id("  A@B.FI ") == "a@b.fi"


def test_continue_sum_falls_back_to_last_when_window_missing(caruna_modules):
    helpers = caruna_modules.helpers
    last_start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    running, start = helpers.continue_sum(
        rebuild=False,
        window_first=None,
        last=(last_start, 100.0),
    )
    assert running == 100.0
    assert start == last_start


def test_continue_sum_prefers_window_overlap(caruna_modules):
    helpers = caruna_modules.helpers
    window_start = datetime(2026, 8, 14, 21, 0, tzinfo=UTC)
    last_start = datetime(2026, 8, 16, 20, 0, tzinfo=UTC)
    running, start = helpers.continue_sum(
        rebuild=False,
        window_first=(window_start, 10.0),
        last=(last_start, 99.0),
    )
    assert running == 10.0
    assert start == window_start


def test_continue_sum_rebuild_starts_at_zero(caruna_modules):
    helpers = caruna_modules.helpers
    last_start = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    running, start = helpers.continue_sum(
        rebuild=True,
        window_first=None,
        last=(last_start, 100.0),
    )
    assert running == 0.0
    assert start is None


def test_is_transient_status(caruna_modules):
    helpers = caruna_modules.helpers
    assert helpers.is_transient_status(None)
    assert helpers.is_transient_status(500)
    assert helpers.is_transient_status(503)
    assert not helpers.is_transient_status(404)
    assert not helpers.is_transient_status(400)


def test_resolve_cost_rates_partial_legacy_uses_defaults(caruna_modules):
    helpers = caruna_modules.helpers
    const = caruna_modules.const
    rates = helpers.resolve_cost_rates(
        {},
        lambda entity_id: {const.LEGACY_ENTITY_TAX: 0.0282752}.get(entity_id),
    )
    assert rates.tax == 0.0282752
    assert rates.margin == const.DEFAULT_MARGIN
    assert rates.transfer == const.DEFAULT_TRANSFER


def test_rates_changed(caruna_modules):
    helpers = caruna_modules.helpers
    const = caruna_modules.const
    old = {const.CONF_MARGIN: 0.0, const.CONF_TRANSFER: 0.0, const.CONF_TAX: 0.02}
    new = {**old, const.CONF_MARGIN: 0.0039}
    assert helpers.rates_changed(old, new)
    assert not helpers.rates_changed(old, old)


def test_suggested_cost_options_from_legacy(caruna_modules):
    helpers = caruna_modules.helpers
    const = caruna_modules.const
    suggested = helpers.suggested_cost_options(
        {},
        lambda entity_id: {
            const.LEGACY_ENTITY_MARGIN: 0.0039,
            const.LEGACY_ENTITY_TRANSFER: 0.0526,
            const.LEGACY_ENTITY_TAX: 0.0282752,
        }.get(entity_id),
    )
    assert suggested[const.CONF_MARGIN] == 0.0039
    assert suggested[const.CONF_TRANSFER] == 0.0526
    assert suggested[const.CONF_ENABLE_COST] is True
