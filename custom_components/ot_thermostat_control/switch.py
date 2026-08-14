"""Switch entities to enable/disable OT control and occupancy per room."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTRY_TYPE_HUB
from .coordinator import OTCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OT switch entities."""
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        hub_data = entry.runtime_data
        async_add_entities([OTGlobalEnableSwitch(hub_data, entry)])
        return

    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities([
        OTEnableSwitch(coordinator, entry),
        OTOccupancySwitch(coordinator, entry),
    ])


class OTEnableSwitch(CoordinatorEntity[OTCoordinator], SwitchEntity):
    """Switch to enable/disable OT control for this room."""

    _attr_has_entity_name = True
    _attr_name = "Enabled"
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator: OTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_enabled"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"OT {self.coordinator.room_name}",
            "manufacturer": "OT Thermostat Control",
            "model": "v1.0.0",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.enabled

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.enabled = False
        self.async_write_ha_state()


class OTOccupancySwitch(
    CoordinatorEntity[OTCoordinator], SwitchEntity, RestoreEntity
):
    """Switch to enable/disable occupancy-based setpoint adjustments."""

    _attr_has_entity_name = True
    _attr_name = "Occupancy Enabled"
    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: OTCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_occupancy_enabled"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"OT {self.coordinator.room_name}",
            "manufacturer": "OT Thermostat Control",
            "model": "v1.0.0",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator.occupancy_enabled

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self.coordinator.occupancy_enabled = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.occupancy_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.occupancy_enabled = False
        self.async_write_ha_state()


class OTGlobalEnableSwitch(SwitchEntity, RestoreEntity):
    """Global switch to enable/disable OT overrides across all rooms."""

    _attr_has_entity_name = True
    _attr_name = "Global Enabled"
    _attr_icon = "mdi:earth"

    def __init__(self, hub_data, entry: ConfigEntry) -> None:
        self._hub_data = hub_data
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_global_enabled"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OT Global Settings",
            "manufacturer": "OT Thermostat Control",
            "model": "Hub",
        }

    @property
    def is_on(self) -> bool:
        return self._hub_data.global_enabled

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._hub_data.global_enabled = last_state.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self._hub_data.global_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._hub_data.global_enabled = False
        self.async_write_ha_state()
