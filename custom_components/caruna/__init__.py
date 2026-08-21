"""The Caruna+ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant

from .coordinator import CarunaCoordinator

PLATFORMS = [Platform.SENSOR]

type CarunaConfigEntry = ConfigEntry[CarunaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CarunaConfigEntry) -> bool:
    """Set up Caruna+ from a config entry."""
    coordinator = CarunaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _on_started(_event: Event) -> None:
        coordinator.schedule_backfill()
        await coordinator.async_request_refresh()

    if hass.is_running:
        coordinator.schedule_backfill()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CarunaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
