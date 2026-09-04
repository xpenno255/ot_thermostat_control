"""Binary sensors: window override active, adjacent door open."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OTCoordinator
from .entity import OTRoomEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities([
        OTFlag(coordinator, entry, "window_override_active", "Window Override Active", BinarySensorDeviceClass.WINDOW),
        OTFlag(coordinator, entry, "adjacent_door_open", "Adjacent Door Open", BinarySensorDeviceClass.DOOR),
    ])


class OTFlag(OTRoomEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, key, name, device_class) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        d = self.snapshot
        return None if d is None else bool(getattr(d, self._key))
