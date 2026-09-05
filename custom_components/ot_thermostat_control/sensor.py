"""Sensors for OT Thermostat Control v2 (design note §9)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ENTRY_TYPE_HUB
from .coordinator import OTCoordinator
from .entity import OTRoomEntity, hub_device_info
from .hub import OTHubData

TEMP = ("°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT)
DELTA = ("°C", None, SensorStateClass.MEASUREMENT)
PLAIN = (None, None, None)
WATTS = ("W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT)

# key, name, (unit, device_class, state_class), icon, diagnostic?
ROOM_SENSORS: list[tuple[str, str, tuple, str | None, bool]] = [
    ("state", "State", PLAIN, "mdi:state-machine", False),
    ("target_ot", "Target OT", TEMP, None, False),
    ("air_setpoint", "Air Setpoint", TEMP, None, False),
    ("would_write", "Would Write", TEMP, "mdi:pencil-outline", False),
    ("air_temp", "Air Temperature", TEMP, None, False),
    ("mrt_steady_state", "MRT Steady State", TEMP, None, False),
    ("operative_temp", "Operative Temperature", TEMP, None, False),
    ("offset_final", "Offset", DELTA, "mdi:thermometer-plus", False),
    ("offset_physical", "Offset Physical", DELTA, "mdi:thermometer-plus", True),
    ("schedule_setpoint", "Schedule Setpoint", TEMP, None, True),
    ("radiator_output_w", "Radiator Output", WATTS, "mdi:radiator", True),
    ("flow_temp_used", "Flow Temperature Used", TEMP, None, True),
    ("outdoor_temp", "Outdoor Temperature Used", TEMP, None, True),
    ("solar_k", "Solar MRT Rise", DELTA, "mdi:white-balance-sunny", True),
    ("occupancy_status", "Occupancy Status", PLAIN, "mdi:account-question", True),
    ("last_write", "Last Write", (None, SensorDeviceClass.TIMESTAMP, None), None, True),
    ("last_run", "Last Run", (None, SensorDeviceClass.TIMESTAMP, None), None, True),
]

HUB_SENSORS: list[tuple[str, str, tuple, str | None]] = [
    ("running_mean", "Running Mean Outdoor Temperature", TEMP, "mdi:chart-line"),
    ("flow_temp_used", "Flow Temperature Used", TEMP, "mdi:water-thermometer"),
    ("outdoor_used", "Outdoor Temperature Used", TEMP, None),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        hub: OTHubData = entry.runtime_data
        async_add_entities(OTHubSensor(hub, entry, *spec) for spec in HUB_SENSORS)
        return
    coordinator: OTCoordinator = entry.runtime_data
    async_add_entities(OTRoomSensor(coordinator, entry, *spec) for spec in ROOM_SENSORS)


class OTRoomSensor(OTRoomEntity, SensorEntity):
    def __init__(self, coordinator, entry, key, name, spec, icon, diagnostic) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement, self._attr_device_class, self._attr_state_class = spec
        self._attr_icon = icon
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        d = self.snapshot
        return None if d is None else getattr(d, self._key, None)

    @property
    def extra_state_attributes(self):
        d = self.snapshot
        if d is None:
            return None
        if self._key == "state":
            return {
                "reason": d.reason,
                "action": d.action,
                "mode": d.mode,
                "fallbacks": d.fallbacks,
                "geometry_warnings": d.geometry_warnings,
                "window_override_active": d.window_override_active,
                "adjacent_door_open": d.adjacent_door_open,
                "time_window_active": d.time_window_active,
            }
        if self._key == "target_ot":
            return {
                "schedule_setpoint": d.schedule_setpoint,
                "schedule_source": d.schedule_source,
                "occupancy_offset": d.occupancy_offset,
                "adaptive_shift": d.adaptive_shift,
                "next_switchpoint_at": d.next_switchpoint_at,
                "next_switchpoint_setpoint": d.next_switchpoint_setpoint,
            }
        if self._key == "offset_final":
            return {
                "physical": d.offset_physical,
                "trusted": d.offset_trusted,
                "asymmetry": d.offset_asymmetry,
                "capped": d.capped,
                "sum_l": d.sum_l,
                "solar_k": d.solar_k,
            }
        if self._key == "air_temp":
            return {"source": d.air_temp_source, "zone_setpoint": d.zone_setpoint}
        if self._key == "outdoor_temp":
            return {"source": d.outdoor_source, "wind_ms": d.wind_ms, "ghi_wm2": d.ghi_wm2, "cloud_fraction": d.cloud_fraction}
        if self._key == "radiator_output_w":
            return {"installed_output_dt50_w": d.installed_output_dt50_w, "glazed_area_m2": d.glazed_area_m2, "total_area_m2": d.total_area_m2}
        return None


class OTHubSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: OTHubData, entry: ConfigEntry, key: str, name: str, spec: tuple, icon: str | None) -> None:
        self._hub = hub
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_hub_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement, self._attr_device_class, self._attr_state_class = spec
        self._attr_icon = icon
        self._attr_device_info = hub_device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._hub.add_listener(self.async_write_ha_state)
        self.async_on_remove(lambda: self._hub.remove_listener(self.async_write_ha_state))

    @property
    def native_value(self):
        return getattr(self._hub, self._key, None)

    @property
    def extra_state_attributes(self):
        if self._key == "flow_temp_used":
            return {"source": self._hub.flow_temp_source, "dhw_active": self._hub.dhw_active_seen}
        return None
