"""v1 -> v2 config-entry migration and stale-entity cleanup."""
from __future__ import annotations

import glob
import os
from uuid import uuid4

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ot_thermostat_control.const import (
    CONF_MODE,
    CONF_ROOM_ID,
    DOMAIN,
    ENTRY_TYPE_HUB,
    MODE_SHADOW,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def clean_stores(hass: HomeAssistant):
    yield
    for f in glob.glob(hass.config.path(".storage", "ot_thermostat_control_*")):
        os.remove(f)


V1_ROOM = {
    "automation_delay": 6.0, "backup_climate": "climate.bedroom_2", "coast_cycles": 3.0, "correction_gain": 0.5,
    "k_adaptation_mode": "ot_referenced", "max_setpoint": 21.0, "max_step": 0.5, "name": "Spare Room",
    "orientation": "S", "override_duration": 60.0, "primary_climate": "climate.ramses_cc_01_144444_04",
    "room_profile": "two_wall_medium_window", "run_interval": 5.0, "smoothing_enabled": True,
    "time_window_enabled": True, "time_window_end": "22:30:00", "time_window_start": "06:30:00",
    "unoccupied_duration": 20.0, "weather_entity": "weather.pirateweather", "weekday_afternoon_offset": -0.5,
    "window_delay": 15.0, "window_open_delay": 5.0, "window_setpoint": 10.0,
}
V1_HUB = {
    "advanced_sensors": False, "apparent_temp_entity": "sensor.home_heating_outdoor_temperature_sensor",
    "entry_type": ENTRY_TYPE_HUB, "gradient_exponent": 1.5, "gradient_scale": 15.0, "smoothing_enabled": True,
    "weather_entity": "weather.pirateweather", "weather_ref_temp": 10.0, "weather_scale": 20.0,
    "weather_severity_exponent": 2.5,
}


async def test_v1_entries_migrate_and_stale_entities_are_removed(hass: HomeAssistant):
    hass.states.async_set("weather.pirateweather", "cloudy", {"temperature": 8.0, "wind_speed": 10.0, "wind_speed_unit": "km/h", "cloud_coverage": 80})
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": -5.0, "azimuth": 250.0})
    hass.states.async_set("climate.ramses_cc_01_144444_04", "heat", {"current_temperature": 20.0, "temperature": 18.0})
    hass.states.async_set("climate.bedroom_2", "heat", {"current_temperature": 20.0, "temperature": 18.0,
                          "status": {"setpoints": {"this_sp_temp": 18.0, "next_sp_temp": 17.5, "next_sp_from": "2030-01-01T22:00:00+00:00"}}})

    hub = MockConfigEntry(domain=DOMAIN, entry_id=f"hub_{uuid4().hex[:8]}", version=1, data=V1_HUB, options={})
    room = MockConfigEntry(domain=DOMAIN, entry_id=f"room_{uuid4().hex[:8]}", version=1, title="Spare Room",
                           data={**V1_ROOM, "correction_gain": 0.6}, options=V1_ROOM)
    hub.add_to_hass(hass)
    room.add_to_hass(hass)

    # A v1-only entity hanging off the room entry, as the live registry has today.
    registry = er.async_get(hass)
    stale = registry.async_get_or_create("sensor", DOMAIN, f"{room.entry_id}_coast_prediction", config_entry=room,
                                         suggested_object_id="ot_spare_room_coast_prediction")
    assert registry.async_get(stale.entity_id) is not None

    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    assert hub.state is ConfigEntryState.LOADED and room.state is ConfigEntryState.LOADED

    assert hub.version == 2 and room.version == 2
    assert room.data[CONF_ROOM_ID] == "bedroom_2"  # matched through the survey alias "Bedroom 2"
    assert room.data[CONF_MODE] == MODE_SHADOW
    for dead in ("k_adaptation_mode", "room_profile", "coast_cycles", "correction_gain", "weather_entity"):
        assert dead not in room.data and dead not in room.options
    for dead in ("apparent_temp_entity", "gradient_scale", "advanced_sensors"):
        assert dead not in hub.data
    assert hub.data["weather_entity"] == "weather.pirateweather"

    assert registry.async_get(stale.entity_id) is None
    coordinator = room.runtime_data
    assert coordinator.geometry is not None and coordinator.geometry.room_id == "bedroom_2"
    assert coordinator.data.state == "shadow"
    assert coordinator.data.outdoor_source == "weather.pirateweather.temperature"


async def test_config_flow_hub_then_room(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "hub"})
    assert result["type"] == "form" and result["step_id"] == "hub"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"weather_entity": "weather.home"})
    assert result["type"] == "create_entry"
    assert result["data"]["entry_type"] == ENTRY_TYPE_HUB
    assert result["data"]["weather_entity"] == "weather.home"
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "room"})
    assert result["type"] == "form" and result["step_id"] == "room"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "Living Room", "room_id": "living_room", "primary_climate": "climate.living_room_2",
        "backup_climate": "climate.living_room", "mode": "shadow",
    })
    assert result["type"] == "create_entry"
    assert result["data"]["room_id"] == "living_room" and result["data"]["mode"] == "shadow"
