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
