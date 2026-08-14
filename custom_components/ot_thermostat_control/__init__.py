"""OT Thermostat Control — operative temperature correction for evohome zones."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ENTRY_TYPE_HUB

_LOGGER = logging.getLogger(__name__)

ROOM_PLATFORMS = ["sensor", "number", "switch", "button", "binary_sensor"]
HUB_PLATFORMS = ["switch", "sensor"]


@dataclass
class OTHubData:
    """Runtime data for the global hub entry."""

    global_enabled: bool = True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the OT Thermostat Control domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OT Thermostat Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        return await _async_setup_hub_entry(hass, entry)
    return await _async_setup_room_entry(hass, entry)


async def _async_setup_hub_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up the global hub entry."""
    hub_data = OTHubData()
    entry.runtime_data = hub_data
    hass.data[DOMAIN]["hub"] = {
        "config": {**entry.data, **entry.options},
        "data": hub_data,
    }

    await hass.config_entries.async_forward_entry_setups(entry, HUB_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_hub_options_updated))
    return True


async def _async_setup_room_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up a room entry."""
    from .coordinator import OTCoordinator
    from .store import OTStore

    store = OTStore(hass, entry.entry_id)
    await store.async_load()

    coordinator = OTCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, ROOM_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        ok = await hass.config_entries.async_unload_platforms(entry, HUB_PLATFORMS)
        if ok:
            hass.data[DOMAIN].pop("hub", None)
        return ok
    return await hass.config_entries.async_unload_platforms(entry, ROOM_PLATFORMS)


async def _async_hub_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle hub options update — refresh cached config and reload all rooms."""
    hub_info = hass.data.get(DOMAIN, {}).get("hub")
    if hub_info:
        hub_info["config"] = {**entry.data, **entry.options}

    # Reload all room entries so they pick up new hub config
    for other_entry in hass.config_entries.async_entries(DOMAIN):
        if other_entry.data.get("entry_type") != ENTRY_TYPE_HUB:
            await hass.config_entries.async_reload(other_entry.entry_id)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle room options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
