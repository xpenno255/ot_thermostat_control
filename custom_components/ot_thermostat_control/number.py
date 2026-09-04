"""Per-room tunables: trust factor and caps."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAP_DOWN, CONF_CAP_UP, CONF_TRUST_K
from .coordinator import OTCoordinator
from .entity import OTRoomEntity

# key, name, min, max, step, unit, icon
NUMBERS = [
    (CONF_TRUST_K, "Trust k", 0.0, 1.0, 0.05, None, "mdi:tune"),
    (CONF_CAP_UP, "Cap Up", 0.0, 3.0, 0.5, "°C", "mdi:arrow-collapse-up"),
    (CONF_CAP_DOWN, "Cap Down", 0.0, 3.0, 0.5, "°C", "mdi:arrow-collapse-down"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities(OTNumber(coordinator, entry, *spec) for spec in NUMBERS)


class OTNumber(OTRoomEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, key, name, mn, mx, step, unit, icon) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def native_value(self) -> float:
        return self.coordinator.get_tunable(self._key)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_tunable(self._key, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
