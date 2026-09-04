"""Per-room mode select: shadow or active."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import MODE_ACTIVE, MODE_SHADOW
from .coordinator import OTCoordinator
from .entity import OTRoomEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities([OTModeSelect(coordinator, entry)])


class OTModeSelect(OTRoomEntity, SelectEntity, RestoreEntity):
    _attr_name = "Mode"
    _attr_icon = "mdi:eye-outline"
    _attr_options = [MODE_SHADOW, MODE_ACTIVE]
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self.coordinator.mode = last.state

    async def async_select_option(self, option: str) -> None:
        self.coordinator.mode = option
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
