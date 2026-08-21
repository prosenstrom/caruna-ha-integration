# Caruna+ Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![CI](https://github.com/prosenstrom/caruna-ha-integration/actions/workflows/ci.yml/badge.svg)](https://github.com/prosenstrom/caruna-ha-integration/actions/workflows/ci.yml)

Home Assistant custom component for [Caruna+](https://plus.caruna.fi/) metering data. It wraps [prosenstrom/pycaruna](https://github.com/prosenstrom/pycaruna) the same way [Oma Helen](https://github.com/carohauta/oma-helen-ha-integration) wraps `oma-helen-cli`.

Caruna is the **grid / siirto** company (DSO). This is not an electricity retailer integration. Sales (myynti) still come from your contract and, if you want day-ahead spot, from Nord Pool.

Login is the plus.caruna.fi **email and password**, not Suomi.fi. Usage is delayed (often yesterday’s hours), not live watts.

## What it provides

- Sensors per metering point: yesterday, today, this month, last hour
- Hourly consumption statistics for the Energy dashboard (`caruna:<asset>_consumption`)
- Optional hourly cost statistics (`caruna:<asset>_cost`) using Nord Pool FI spot plus the rates you configure
- Automatic backfill of history on first run, then a three-day refresh each hour

Cost formula, EUR/kWh:

`(spot + margin) × (1 + VAT %) + transfer + tax`

Spot is Nord Pool FI (energy-charts.info, with the official Nord Pool integration as fallback). Monthly retailer fees and Caruna perusmaksu are not included.

## How to install

The recommended way is to install via HACS.

[![Open your Home Assistant instance and open the Caruna+ custom component repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=prosenstrom&repository=caruna-ha-integration&category=integration)

Requires Home Assistant **2025.8** or later.

Then restart Home Assistant and add **Caruna+** via **Settings → Devices & services → Add integration**.

### How to install manually

This is not the recommended way.

```shell
cd /config/custom_components   # create the folder if needed
git clone https://github.com/prosenstrom/caruna-ha-integration.git caruna_tmp
mv caruna_tmp/custom_components/caruna .
rm -rf caruna_tmp
```

Restart Home Assistant, then add **Caruna+** from the UI.

## Cost options

After setup, open the integration → Configure. Rates are EUR/kWh except VAT, which is a percent.

| Option | Meaning | Suggested starting point |
|---|---|---|
| Import hourly cost statistics | Write the cost series next to kWh | on |
| VAT | Applied to spot + retailer margin | 25.5 |
| Retailer margin | Greenely / Helen / other sales margin | 0 unless you know it |
| Grid transfer | Caruna siirto, billed snt/kWh as EUR/kWh | your product, e.g. 0.0526 |
| Electricity tax | Finnish electricity tax including VAT | 0.0282752 |

Changing rates re-imports the cost series. Consumption history is left alone.

Example matching a Greenely spot contract on Caruna Yleissiirto:

- VAT 25.5
- Margin 0.0039
- Transfer 0.0526
- Tax 0.0282752

New installs default extra rates to 0 except Finnish electricity tax, so cost is spot × VAT + tax until you set your own contract.

## Energy dashboard

Add the imported statistics (search for the metering-point name, or ids like `caruna:123456_consumption` and `caruna:123456_cost`). Cost is an external statistic, so Home Assistant will not accept a live price entity here.

Yesterday / today sensors stay `unknown` until Caruna publishes those days. Month and last hour can still have values.

## Caveats

- Requires Home Assistant 2025.8 or later
- Requires the 2026 Caruna+ API client (`pycaruna` from `prosenstrom/pycaruna`), not upstream `Jalle19/pycaruna` 1.0.3
- Token lasts about an hour; the integration logs in again as needed
- After a password change, Home Assistant will ask to reauthenticate
- Not live power. For that, activate the meter HAN / P1 port in Caruna+

## Development

```
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The Python client lives in a separate repository: [prosenstrom/pycaruna](https://github.com/prosenstrom/pycaruna).
