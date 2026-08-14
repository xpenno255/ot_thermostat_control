"""Number entities for OT Thermostat Control tuneable parameters."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OTCoordinator

_LOGGER = logging.getLogger(__name__)

# (key, name_suffix, min, max, step, unit, icon)
# Grouped: envelope params, correction params, coast/weather params
NUMBERS: list[tuple[str, str, float, float, float, str | None, str]] = [
    # --- Envelope ---
    ("f_out", "Exterior Envelope (f_out)", 0.0, 2.0, 0.01, None, "mdi:wall"),
    ("f_win", "Window Share (f_win)", 0.0, 1.0, 0.01, None, "mdi:window-open"),
    ("k_loss", "Insulation Loss (k_loss)", 0.0, 1.0, 0.01, None, "mdi:snowflake-thermometer"),
    ("k_solar", "Solar Gain (k_solar)", 0.0, 2.0, 0.01, None, "mdi:weather-sunny"),
    ("thermal_alpha", "MRT Smoothing (alpha)", 0.05, 0.95, 0.05, None, "mdi:chart-bell-curve"),
    # --- Correction ---
    ("correction_gain", "Correction Gain (k)", 0.0, 3.0, 0.1, None, "mdi:tune"),
    ("k_max", "k Maximum", 0.0, 2.0, 0.1, None, "mdi:arrow-collapse-up"),
    # --- Coast / Weather ---
    ("coast_cycles", "Coast Cycles", 0.0, 10.0, 0.1, None, "mdi:sail-boat"),
    ("weather_k_boost", "Weather k Boost", 0.0, 1.5, 0.1, None, "mdi:weather-windy"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OT number entities."""
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities(
        OTNumber(coordinator, entry, key, name_suffix, mn, mx, step, unit, icon)
        for key, name_suffix, mn, mx, step, unit, icon in NUMBERS
    )


class OTNumber(CoordinatorEntity[OTCoordinator], RestoreNumber):
    """A tuneable number parameter backed by RestoreNumber."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: OTCoordinator,
        entry: ConfigEntry,
        key: str,
        name_suffix: str,
        minimum: float,
        maximum: float,
        step: float,
        unit: str | None,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name_suffix
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_native_value = coordinator.get_number_value(key)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"OT {self.coordinator.room_name}",
            "manufacturer": "OT Thermostat Control",
            "model": "v1.0.0",
        }

    async def async_added_to_hass(self) -> None:
        """Restore previous value on startup."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self._attr_native_value = last.native_value
            self.coordinator.set_number_value(self._key, last.native_value)
        else:
            self._attr_native_value = self.coordinator.get_number_value(self._key)

    async def async_set_native_value(self, value: float) -> None:
        """Update the number value."""
        self._attr_native_value = value
        self.coordinator.set_number_value(self._key, value)
        self.async_write_ha_state()
