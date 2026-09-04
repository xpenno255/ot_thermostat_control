"""Button: reload the room's survey geometry from disk."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OTCoordinator
from .entity import OTRoomEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities([OTReloadGeometryButton(coordinator, entry)])


class OTReloadGeometryButton(OTRoomEntity, ButtonEntity):
    _attr_name = "Reload Geometry"
    _attr_icon = "mdi:file-refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "reload_geometry")

    async def async_press(self) -> None:
        await self.coordinator.async_load_geometry()
        await self.coordinator.async_request_refresh()
