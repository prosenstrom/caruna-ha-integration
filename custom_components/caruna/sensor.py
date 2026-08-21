"""Sensors for Caruna+ usage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CarunaConfigEntry
from .const import DOMAIN
from .coordinator import CarunaCoordinator
from .helpers import HELSINKI, statistic_id_for


def _attr_hours(hours: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "start": item["start"].astimezone(HELSINKI).isoformat(),
            "kwh": round(item["consumption"], 3),
        }
        for item in hours
    ]


def _start_of_helsinki_day(days_ago: int = 0) -> datetime:
    start = dt_util.now(HELSINKI).replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=days_ago)


def _start_of_helsinki_month() -> datetime:
    now = dt_util.now(HELSINKI)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True, kw_only=True)
class CarunaSensorEntityDescription(SensorEntityDescription):
    """Describes a Caruna+ sensor."""

    value_fn: Callable[[dict[str, Any]], float | datetime | str | None]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    last_reset_fn: Callable[[], datetime] | None = None


SENSORS: tuple[CarunaSensorEntityDescription, ...] = (
    CarunaSensorEntityDescription(
        key="yesterday",
        translation_key="yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda point: point.get("yesterday"),
        last_reset_fn=lambda: _start_of_helsinki_day(1),
        attrs_fn=lambda point: {
            "hours": _attr_hours(point.get("yesterday_hours") or []),
            "statistic_id": statistic_id_for(point["asset_id"]),
        },
    ),
    CarunaSensorEntityDescription(
        key="today",
        translation_key="today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda point: point.get("today"),
        last_reset_fn=_start_of_helsinki_day,
        attrs_fn=lambda point: {"hours": _attr_hours(point.get("today_hours") or [])},
    ),
    CarunaSensorEntityDescription(
        key="month",
        translation_key="month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda point: point.get("month"),
        last_reset_fn=_start_of_helsinki_month,
    ),
    CarunaSensorEntityDescription(
        key="last_hour",
        translation_key="last_hour",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda point: point.get("last_hour"),
        attrs_fn=lambda point: {
            "start": (
                point["last_hour_start"].astimezone(HELSINKI).isoformat()
                if point.get("last_hour_start")
                else None
            )
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarunaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Caruna+ sensors."""
    coordinator = entry.runtime_data
    entities: list[CarunaSensor] = []
    for asset_id in coordinator.data.get("points", {}):
        entities.extend(
            CarunaSensor(coordinator, description, asset_id) for description in SENSORS
        )
    async_add_entities(entities)


class CarunaSensor(CoordinatorEntity[CarunaCoordinator], SensorEntity):
    """A Caruna+ usage sensor."""

    entity_description: CarunaSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CarunaCoordinator,
        description: CarunaSensorEntityDescription,
        asset_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self.asset_id = asset_id
        point = coordinator.data["points"][asset_id]
        asset = point.get("asset") or {}
        self._attr_unique_id = f"{asset_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset_id)},
            name=point.get("name") or "Caruna+",
            manufacturer="Caruna",
            model=asset.get("contractProductDesc") or "Caruna+",
            serial_number=asset.get("gsrn"),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://plus.caruna.fi/",
        )

    @property
    def point(self) -> dict[str, Any]:
        """Current metering-point payload."""
        return self.coordinator.data["points"][self.asset_id]

    @property
    def native_value(self) -> float | datetime | str | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.point)

    @property
    def last_reset(self) -> datetime | None:
        """Return when a resetting total started."""
        if not self.entity_description.last_reset_fn:
            return None
        return self.entity_description.last_reset_fn()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if not self.entity_description.attrs_fn:
            return None
        return self.entity_description.attrs_fn(self.point)

    @property
    def available(self) -> bool:
        """Return True if this metering point is in the last payload."""
        return super().available and self.asset_id in self.coordinator.data.get(
            "points", {}
        )
