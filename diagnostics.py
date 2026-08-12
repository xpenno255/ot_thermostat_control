"""Diagnostics support for OT Thermostat Control."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import OTCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: OTCoordinator = entry.runtime_data
    data = coordinator.data

    last_result: dict[str, Any] = {}
    if data is not None:
        r = data.result
        last_result = {
            "final_setpoint": r.final_setpoint,
            "raw_setpoint": r.raw_setpoint,
            "mrt": r.mrt_result.mrt,
            "operative_temp": r.mrt_result.operative_temp,
            "mrt_correction": r.mrt_correction,
            "coast_prediction": r.coast_prediction,
            "air_rate": r.air_rate,
            "cycles_to_target": r.cycles_to_target,
            "dynamic_coast_cycles": r.dynamic_coast_cycles,
            "desired_ot": r.desired_ot,
            "loss_term": r.mrt_result.loss_term,
            "solar_term": r.mrt_result.solar_term,
            "mrt_unclamped": r.mrt_result.mrt_unclamped,
            "mrt_clamped": r.mrt_result.mrt_clamped,
            "radiation_used": r.mrt_result.radiation_used,
            "t_out_effective": r.mrt_result.t_out_effective,
            "skipped": r.skipped,
            "skip_reason": r.skip_reason,
            "air_temp": data.air_temp,
            "active_thermostat": data.active_thermostat,
            "last_run": data.last_run.isoformat() if data.last_run else None,
            "overshoot_count": data.overshoot_count,
        }

    return {
        "config": {**entry.data, **entry.options},
        "store": coordinator._store._data,
        "last_result": last_result,
        "enabled": coordinator.enabled,
        "number_values": {
            "correction_gain": coordinator.get_number_value("correction_gain"),
            "coast_cycles": coordinator.get_number_value("coast_cycles"),
            "f_out": coordinator.get_number_value("f_out"),
            "f_win": coordinator.get_number_value("f_win"),
            "k_loss": coordinator.get_number_value("k_loss"),
            "k_solar": coordinator.get_number_value("k_solar"),
            "thermal_alpha": coordinator.get_number_value("thermal_alpha"),
        },
    }
