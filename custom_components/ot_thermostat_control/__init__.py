"""OT Thermostat Control v2 — operative-temperature correction for evohome zones."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ENTRY_TYPE_HUB
from .hub import OTHubData
from .store import OTStore

_LOGGER = logging.getLogger(__name__)

ROOM_PLATFORMS = ["sensor", "number", "switch", "select", "button", "binary_sensor"]
HUB_PLATFORMS = ["switch", "sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {"rooms": {}})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {"rooms": {}})
    hass.data[DOMAIN].setdefault("rooms", {})
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        return await _async_setup_hub_entry(hass, entry)
    return await _async_setup_room_entry(hass, entry)


async def _async_setup_hub_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = OTStore(hass, f"hub_{entry.entry_id}")
    await store.async_load()
    hub_data = OTHubData(store=store)
    hub_data.load()
    entry.runtime_data = hub_data
    hass.data[DOMAIN]["hub"] = {"config": {**entry.data, **entry.options}, "data": hub_data}
    await hass.config_entries.async_forward_entry_setups(entry, HUB_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_hub_options_updated))
    return True


async def _async_setup_room_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import OTCoordinator

    store = OTStore(hass, entry.entry_id)
    await store.async_load()
    coordinator = OTCoordinator(hass, entry, store)
    await coordinator.async_load_geometry()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    hass.data[DOMAIN]["rooms"][coordinator.room_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ROOM_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        ok = await hass.config_entries.async_unload_platforms(entry, HUB_PLATFORMS)
        if ok:
            hass.data[DOMAIN].pop("hub", None)
        return ok
    ok = await hass.config_entries.async_unload_platforms(entry, ROOM_PLATFORMS)
    if ok:
        coordinator = entry.runtime_data
        hass.data[DOMAIN].get("rooms", {}).pop(getattr(coordinator, "room_id", None), None)
    return ok


async def _async_hub_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    hub_info = hass.data.get(DOMAIN, {}).get("hub")
    if hub_info:
        hub_info["config"] = {**entry.data, **entry.options}
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.data.get("entry_type") != ENTRY_TYPE_HUB:
            await hass.config_entries.async_reload(other.entry_id)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
