"""Diagnostics for OT Thermostat Control v2."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import ENTRY_TYPE_HUB


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    config = {**entry.data, **entry.options}
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        hub = entry.runtime_data
        return {
            "entry_type": "hub",
            "config": config,
            "running_mean": hub.running_mean,
            "flow_temp_used": hub.flow_temp_used,
            "flow_temp_source": hub.flow_temp_source,
            "global_enabled": hub.global_enabled,
        }
    coordinator = entry.runtime_data
    data = coordinator.data
    geometry = coordinator.geometry
    return {
        "entry_type": "room",
        "config": config,
        "mode": coordinator.mode,
        "enabled": coordinator.enabled,
        "tunables": {k: coordinator.get_tunable(k) for k in ("trust_k", "cap_up", "cap_down")},
        "store": coordinator._store._data,  # noqa: SLF001
        "geometry": None if geometry is None else {
            "room_id": geometry.room_id,
            "surfaces": [asdict(s) | {"boundary": s.boundary.value} for s in geometry.surfaces],
            "emitters": [asdict(e) for e in geometry.emitters],
            "warnings": geometry.warnings,
        },
        "last_cycle": None if data is None else {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in asdict(data).items()},
    }
