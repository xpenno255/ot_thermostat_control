"""Switches: per-room enable and occupancy, hub global enable."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import ENTRY_TYPE_HUB
from .coordinator import OTCoordinator
from .entity import OTRoomEntity, hub_device_info
from .hub import OTHubData


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        async_add_entities([OTGlobalEnableSwitch(entry.runtime_data, entry)])
        return
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities([OTEnableSwitch(coordinator, entry), OTOccupancySwitch(coordinator, entry)])


class _RestoringRoomSwitch(OTRoomEntity, SwitchEntity, RestoreEntity):
    attr: str = ""

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator, self.attr))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            setattr(self.coordinator, self.attr, last.state == "on")

    async def async_turn_on(self, **kwargs) -> None:
        setattr(self.coordinator, self.attr, True)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        setattr(self.coordinator, self.attr, False)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class OTEnableSwitch(_RestoringRoomSwitch):
    _attr_name = "Enabled"
    _attr_icon = "mdi:thermostat"
    attr = "enabled"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "enabled")


class OTOccupancySwitch(_RestoringRoomSwitch):
    _attr_name = "Occupancy Enabled"
    _attr_icon = "mdi:account-check"
    attr = "occupancy_enabled"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "occupancy_enabled")


class OTGlobalEnableSwitch(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = "Global Enabled"
    _attr_icon = "mdi:earth"

    def __init__(self, hub: OTHubData, entry: ConfigEntry) -> None:
        self._hub = hub
        self._attr_unique_id = f"{entry.entry_id}_global_enabled"
        self._attr_device_info = hub_device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._hub.global_enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._hub.global_enabled = last.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self._hub.global_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._hub.global_enabled = False
        self.async_write_ha_state()
