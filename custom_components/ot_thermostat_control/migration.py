"""Config-entry migration from v1 (version 1) to v2 (version 2)."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_MODE,
    CONF_NAME,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_ROOM_ID,
    CONF_WEATHER_ENTITY,
    DEFAULT_HOUSE_DIR,
    ENTRY_TYPE_HUB,
    MODE_SHADOW,
)

_LOGGER = logging.getLogger(__name__)

# v1 keys with no meaning in v2. Removed so the options form is not cluttered.
DEAD_ROOM_KEYS = {
    "air_temp_sensor", "weather_entity", "room_profile", "orientation", "solar_sensor", "outdoor_temp_sensor",
    "outdoor_humidity_sensor", "wind_speed_sensor", "correction_gain", "max_setpoint", "min_setpoint",
    "coast_cycles", "max_step", "smoothing_enabled", "apparent_temp_entity", "weather_k_boost",
    "weather_ref_temp", "weather_scale", "weather_severity_exponent", "k_max", "k_adaptation_mode",
    "gradient_scale", "gradient_exponent", "window_sensors", "adjacent_sensors", "automation_delay",
}
DEAD_HUB_KEYS = {
    "solar_sensor", "outdoor_humidity_sensor", "wind_speed_sensor", "apparent_temp_entity", "weather_ref_temp",
    "weather_scale", "weather_severity_exponent", "smoothing_enabled", "advanced_sensors", "gradient_scale",
    "gradient_exponent",
}

# Entity unique_id suffixes that v2 creates for a room; anything else from this entry is stale.
V2_ROOM_SUFFIXES = {
    "state", "target_ot", "air_setpoint", "would_write", "air_temp", "mrt_steady_state", "operative_temp",
    "offset_final", "offset_physical", "schedule_setpoint", "radiator_output_w", "flow_temp_used", "outdoor_temp",
    "solar_k", "occupancy_status", "last_write", "last_run", "trust_k", "cap_up", "cap_down", "enabled",
    "occupancy_enabled", "mode", "reload_geometry", "window_override_active", "adjacent_door_open",
}
V2_HUB_SUFFIXES = {"global_enabled", "hub_running_mean", "hub_flow_temp_used", "hub_outdoor_used"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def resolve_room_id(house_dir: Path, name: str) -> str:
    """Match a v1 room name to a survey file by id, name or alias."""
    slug = _slug(name)
    rooms = house_dir / "rooms"
    if (rooms / f"{slug}.yaml").exists():
        return slug
    if rooms.is_dir():
        for p in rooms.glob("*.yaml"):
            if p.name.startswith("_"):
                continue
            try:
                info = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("room") or {}
            except Exception:  # noqa: BLE001
                continue
            names = [info.get("name", "")] + list(info.get("aliases") or [])
            if any(_slug(str(n)) == slug for n in names if n):
                return p.stem
    return slug


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version >= 2:
        return True
    _LOGGER.info("Migrating %s '%s' from v1 to v2", entry.domain, entry.title)
    data, options = dict(entry.data), dict(entry.options)
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        merged = {**data, **options}
        for k in DEAD_HUB_KEYS:
            data.pop(k, None)
            options.pop(k, None)
        # v1 had no dedicated outdoor sensor; keep whatever weather entity was set.
        data.setdefault(CONF_WEATHER_ENTITY, merged.get(CONF_WEATHER_ENTITY, ""))
        data.pop(CONF_OUTDOOR_TEMP_SENSOR, None) if not merged.get(CONF_OUTDOOR_TEMP_SENSOR) else None
    else:
        house_dir = Path(__file__).parent / DEFAULT_HOUSE_DIR
        name = str({**data, **options}.get(CONF_NAME) or entry.title)
        room_id = await hass.async_add_executor_job(resolve_room_id, house_dir, name)
        for k in DEAD_ROOM_KEYS:
            data.pop(k, None)
            options.pop(k, None)
        data[CONF_ROOM_ID] = room_id
        data[CONF_MODE] = MODE_SHADOW  # every migrated room starts in shadow
        options.pop(CONF_MODE, None)
        data.setdefault("entry_type", "room")
    hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
    return True


def async_remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Remove registry entries left over from v1 for this config entry."""
    registry = er.async_get(hass)
    allowed = V2_HUB_SUFFIXES if entry.data.get("entry_type") == ENTRY_TYPE_HUB else V2_ROOM_SUFFIXES
    prefix = f"{entry.entry_id}_"
    removed = 0
    for reg_entry in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        uid = str(reg_entry.unique_id)
        suffix = uid[len(prefix):] if uid.startswith(prefix) else uid
        if suffix not in allowed:
            registry.async_remove(reg_entry.entity_id)
            removed += 1
    if removed:
        _LOGGER.info("OT %s: removed %d stale v1 entities", entry.title, removed)
    return removed
