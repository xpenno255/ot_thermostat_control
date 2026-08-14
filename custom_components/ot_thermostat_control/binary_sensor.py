"""Binary sensor entities for OT Thermostat Control."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_WINDOW_SENSORS, DOMAIN, ENTRY_TYPE_HUB
from .coordinator import OTCoordinator, OTCoordinatorData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OT binary sensor entities for a room entry."""
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        return

    coordinator: OTCoordinator = entry.runtime_data
    config = {**entry.data, **entry.options}

    if config.get(CONF_WINDOW_SENSORS):
        async_add_entities([OTWindowOverrideSensor(coordinator, entry)])


class OTWindowOverrideSensor(CoordinatorEntity[OTCoordinator], BinarySensorEntity):
    """Binary sensor — True when the window/door override is active."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, coordinator: OTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_window_override_active"
        self._attr_name = "Window Override Active"
        self._entry = entry

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"OT {self.coordinator.room_name}",
            "manufacturer": "OT Thermostat Control",
            "model": "v1.0.0",
        }

    @property
    def is_on(self) -> bool | None:
        data: OTCoordinatorData | None = self.coordinator.data
        if data is None:
            return None
        return data.window_override_active
