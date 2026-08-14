"""Button entity to reset MRT parameters to the selected room profile."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ROOM_PROFILE,
    DEFAULT_ROOM_PROFILE,
    DOMAIN,
    ROOM_PROFILES,
)
from .coordinator import OTCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the profile reset button."""
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities([OTProfileResetButton(coordinator, entry)])


class OTProfileResetButton(CoordinatorEntity[OTCoordinator], ButtonEntity):
    """Button that resets f_out, f_win, k_loss, k_solar to the selected profile."""

    _attr_has_entity_name = True
    _attr_name = "Reset to Profile"
    _attr_icon = "mdi:restore"

    def __init__(
        self,
        coordinator: OTCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_reset_profile"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"OT {self.coordinator.room_name}",
            "manufacturer": "OT Thermostat Control",
            "model": "v1.0.0",
        }

    async def async_press(self) -> None:
        """Reset MRT parameters to the currently selected room profile."""
        config = {**self._entry.data, **self._entry.options}
        profile_key = config.get(CONF_ROOM_PROFILE, DEFAULT_ROOM_PROFILE)
        profile = ROOM_PROFILES.get(profile_key, {})

        if not profile:
            _LOGGER.warning(
                "OT %s: unknown profile '%s', cannot reset",
                self.coordinator.room_name,
                profile_key,
            )
            return

        for key in ("f_out", "f_win", "k_loss", "k_solar"):
            if key in profile:
                self.coordinator.set_number_value(key, profile[key])

        _LOGGER.info(
            "OT %s: reset MRT parameters to profile '%s': %s",
            self.coordinator.room_name,
            profile_key,
            profile,
        )

        # Trigger a coordinator refresh so number entities pick up new values
        await self.coordinator.async_request_refresh()
