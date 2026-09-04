"""Shared entity base classes."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OTCoordinator, OTCoordinatorData

VERSION = "2.0.0"


class OTRoomEntity(CoordinatorEntity[OTCoordinator]):
    """Base for per-room entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OTCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"OT {self.coordinator.room_name}",
            manufacturer="OT Thermostat Control",
            model=VERSION,
        )

    @property
    def snapshot(self) -> OTCoordinatorData | None:
        return self.coordinator.data


def hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="OT Global Settings",
        manufacturer="OT Thermostat Control",
        model="Hub",
    )
