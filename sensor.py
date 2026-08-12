"""Diagnostic sensor entities for OT Thermostat Control."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ADVANCED_SENSORS,
    CONF_APPARENT_TEMP_ENTITY,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED_SENSOR,
    DEFAULT_ADVANCED_SENSORS,
    DOMAIN,
    ENTRY_TYPE_HUB,
)
from .coordinator import OTCoordinator, OTCoordinatorData

# (key, name_suffix, unit, device_class, icon)
# Grouped logically: core output, room conditions, MRT detail, coast/rate, weather, occupancy
CORE_SENSORS: list[tuple[str, str, str | None, SensorDeviceClass | None, str | None]] = [
    # --- Core Output ---
    ("status", "Status", None, None, "mdi:check-circle"),
    ("final_setpoint", "Final Setpoint", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("desired_ot", "Desired OT", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("active_thermostat", "Active Thermostat", None, None, "mdi:thermostat"),
    ("last_run", "Last Run", None, SensorDeviceClass.TIMESTAMP, None),
    # --- Room Conditions ---
    ("air_temp", "Air Temperature", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("operative_temperature", "Operative Temperature", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("mrt", "MRT", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
]

ADVANCED_SENSORS: list[tuple[str, str, str | None, SensorDeviceClass | None, str | None]] = [
    ("raw_setpoint", "Raw Setpoint", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("mrt_baseline", "MRT Baseline", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("equilibrium_target", "Equilibrium Target", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    ("mrt_correction", "MRT Correction", "\u00b0C", None, "mdi:thermometer-plus"),
    ("mrt_loss_term", "MRT Loss Term", "\u00b0C", None, "mdi:thermometer-minus"),
    ("mrt_solar_term", "MRT Solar Term", "\u00b0C", None, "mdi:white-balance-sunny"),
    ("coast_prediction", "Coast Prediction", "\u00b0C", None, "mdi:chart-timeline-variant"),
    ("air_rate", "OT Rate", "\u00b0C/cycle", None, "mdi:trending-up"),
    ("cycles_to_target", "Cycles to Target", None, None, "mdi:target"),
    ("dynamic_coast_cycles", "Dynamic Coast Cycles", None, None, "mdi:sail-boat"),
    ("overshoot_count", "Overshoot Count", None, None, "mdi:alert-circle"),
    ("weather_severity", "Weather Severity", None, None, "mdi:weather-windy"),
    ("effective_k", "Effective k", None, None, "mdi:tune-variant"),
    ("occupancy_status", "Occupancy Status", None, None, "mdi:account-question"),
    ("active_offset", "Active Offset", "\u00b0C", None, "mdi:account-minus"),
    ("time_window_active", "Time Window Active", None, None, "mdi:clock-check"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OT sensor entities."""
    if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
        _setup_hub_sensors(hass, entry, async_add_entities)
        return

    coordinator: OTCoordinator = entry.runtime_data

    # Read hub advanced_sensors flag (default True = backward-compatible)
    advanced = DEFAULT_ADVANCED_SENSORS
    hub = hass.data.get(DOMAIN, {}).get("hub")
    if hub:
        advanced = bool(hub.get("config", {}).get(CONF_ADVANCED_SENSORS, DEFAULT_ADVANCED_SENSORS))

    sensors = list(CORE_SENSORS)
    if advanced:
        sensors.extend(ADVANCED_SENSORS)

    async_add_entities(
        OTSensor(coordinator, entry, key, name_suffix, unit, device_class, icon)
        for key, name_suffix, unit, device_class, icon in sensors
    )


# --- Hub sensors: show live values of configured source entities ---

# (config_key, name, unit, device_class, icon)
HUB_SENSORS: list[tuple[str, str, str | None, SensorDeviceClass | None, str | None]] = [
    (CONF_WEATHER_ENTITY, "Weather Condition", None, None, "mdi:weather-partly-cloudy"),
    (CONF_OUTDOOR_TEMP_SENSOR, "Outdoor Temperature", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
    (CONF_OUTDOOR_HUMIDITY_SENSOR, "Outdoor Humidity", "%", SensorDeviceClass.HUMIDITY, None),
    (CONF_WIND_SPEED_SENSOR, "Wind Speed", "m/s", SensorDeviceClass.WIND_SPEED, None),
    (CONF_SOLAR_SENSOR, "Solar Radiation", "W/m\u00b2", SensorDeviceClass.IRRADIANCE, None),
    (CONF_APPARENT_TEMP_ENTITY, "Apparent Temperature", "\u00b0C", SensorDeviceClass.TEMPERATURE, None),
]


def _setup_hub_sensors(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create hub sensors for each configured source entity."""
    config = {**entry.data, **entry.options}
    entities = []
    for conf_key, name, unit, device_class, icon in HUB_SENSORS:
        source_entity_id = config.get(conf_key, "")
        if source_entity_id:
            entities.append(
                OTHubSensor(hass, entry, conf_key, name, unit, device_class, icon, source_entity_id)
            )
    if entities:
        async_add_entities(entities)


class OTSensor(CoordinatorEntity[OTCoordinator], SensorEntity):
    """A diagnostic sensor reading from the OT coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OTCoordinator,
        entry: ConfigEntry,
        key: str,
        name_suffix: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        icon: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_name = f"{name_suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"OT {self.coordinator.room_name}",
            "manufacturer": "OT Thermostat Control",
            "model": "v1.0.0",
        }

    @property
    def native_value(self):
        data: OTCoordinatorData | None = self.coordinator.data
        if data is None:
            return None

        result = data.result
        key = self._key

        if key == "mrt":
            return result.mrt_result.mrt
        if key == "operative_temperature":
            return result.mrt_result.operative_temp
        if key == "desired_ot":
            return result.desired_ot
        if key == "air_temp":
            return data.air_temp
        if key == "raw_setpoint":
            return result.raw_setpoint
        if key == "final_setpoint":
            return result.final_setpoint
        if key == "mrt_correction":
            return result.mrt_correction
        if key == "coast_prediction":
            return result.coast_prediction
        if key == "air_rate":
            return result.ot_rate
        if key == "cycles_to_target":
            return result.cycles_to_target
        if key == "dynamic_coast_cycles":
            return result.dynamic_coast_cycles
        if key == "active_thermostat":
            return data.active_thermostat
        if key == "status":
            return result.skip_reason if result.skipped else "ok"
        if key == "overshoot_count":
            return data.overshoot_count
        if key == "mrt_loss_term":
            return result.mrt_result.loss_term
        if key == "mrt_solar_term":
            return result.mrt_result.solar_term
        if key == "last_run":
            return data.last_run
        if key == "occupancy_status":
            return data.occupancy_status
        if key == "active_offset":
            return data.active_offset
        if key == "time_window_active":
            return "on" if data.time_window_active else "off"
        if key == "equilibrium_target":
            return data.equilibrium_target
        if key == "mrt_baseline":
            return data.mrt_baseline
        if key == "weather_severity":
            return data.weather_severity
        if key == "effective_k":
            return data.effective_k
        return None


class OTHubSensor(SensorEntity):
    """Sensor that mirrors the value of a source entity configured in the hub."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        conf_key: str,
        name: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        icon: str | None,
        source_entity_id: str,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._source_entity_id = source_entity_id
        self._attr_unique_id = f"{entry.entry_id}_hub_{conf_key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "OT Global Settings",
            "manufacturer": "OT Thermostat Control",
            "model": "Hub",
        }

    @property
    def native_value(self):
        state = self._hass.states.get(self._source_entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state

    @property
    def extra_state_attributes(self):
        return {"source_entity": self._source_entity_id}

    async def async_added_to_hass(self) -> None:
        """Track source entity state changes."""
        await super().async_added_to_hass()

        @callback
        def _state_changed(event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass, [self._source_entity_id], _state_changed
            )
        )
