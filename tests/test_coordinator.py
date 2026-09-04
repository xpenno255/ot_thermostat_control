"""Coordinator integration test: hub + living room in shadow mode, then active."""
from __future__ import annotations

import glob
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from conftest import FIXTURES
from custom_components.ot_thermostat_control.const import (
    CONF_BACKUP_CLIMATE,
    CONF_HOUSE_DIR,
    CONF_MODE,
    CONF_NAME,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PRIMARY_CLIMATE,
    CONF_ROOM_ID,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_ROOM,
    MODE_ACTIVE,
    MODE_SHADOW,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def clean_stores(hass: HomeAssistant):
    """The test config dir is shared; drop our JSON stores so tests do not see each other's memory."""
    yield
    for f in glob.glob(hass.config.path(".storage", "ot_thermostat_control_*")):
        os.remove(f)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _set_states(hass: HomeAssistant, t_out: float = 0.0, air: float = 19.0, zone_sp: float = 19.0) -> None:
    hass.states.async_set("sensor.met_office_weoley_castle_temperature", str(t_out), {"unit_of_measurement": "°C"})
    hass.states.async_set("weather.home", "cloudy", {"wind_speed": 10.8, "wind_speed_unit": "km/h", "cloud_coverage": 100})
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": -10.0, "azimuth": 300.0})
    hass.states.async_set("sensor.thm_22_066067_temperature", str(air), {"unit_of_measurement": "°C"})
    hass.states.async_set("climate.living_room_2", "heat", {"current_temperature": air, "temperature": zone_sp})
    hass.states.async_set(
        "climate.living_room", "heat",
        {"current_temperature": air, "temperature": zone_sp,
         "status": {"setpoints": {"this_sp_temp": 19.0, "next_sp_temp": 18.0, "next_sp_from": "2030-01-01T23:00:00+00:00"}}},
    )
    hass.states.async_set("input_boolean.holiday_mode", "off")


async def _setup(hass: HomeAssistant, mode: str) -> tuple[MockConfigEntry, MockConfigEntry, list]:
    calls: list = []

    async def fake_set_zone_mode(call):
        calls.append(dict(call.data))

    hass.services.async_register("ramses_cc", "set_zone_mode", fake_set_zone_mode)
    _set_states(hass)

    hub = MockConfigEntry(
        domain=DOMAIN, title="OT Global Settings", entry_id=_uid("hub"), version=2,
        data={"entry_type": ENTRY_TYPE_HUB, CONF_WEATHER_ENTITY: "weather.home",
              CONF_OUTDOOR_TEMP_SENSOR: "sensor.met_office_weoley_castle_temperature",
              CONF_HOUSE_DIR: str(FIXTURES)},
    )
    room = MockConfigEntry(
        domain=DOMAIN, title="Living Room", entry_id=_uid("room"), version=2,
        data={"entry_type": ENTRY_TYPE_ROOM, CONF_NAME: "Living Room", CONF_ROOM_ID: "living_room",
              CONF_PRIMARY_CLIMATE: "climate.living_room_2", CONF_BACKUP_CLIMATE: "climate.living_room",
              CONF_MODE: mode},
    )
    hub.add_to_hass(hass)
    room.add_to_hass(hass)
    # Setting up the first entry loads the whole domain, including the room entry.
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    assert room.state is ConfigEntryState.LOADED, room.state
    return hub, room, calls


async def test_shadow_mode_computes_and_writes_nothing(hass: HomeAssistant):
    hub, room, calls = await _setup(hass, MODE_SHADOW)
    coordinator = room.runtime_data
    d = coordinator.data
    assert coordinator.geometry is not None and not coordinator.geometry.warnings
    assert d.state == "shadow"
    assert d.schedule_setpoint == 19.0
    assert d.target_ot == pytest.approx(19.0)  # adaptive shift waits for 3 full days of running mean
    assert d.adaptive_shift == 0.0
    assert d.air_temp == 19.0 and d.air_temp_source == "sensor.thm_22_066067_temperature"
    assert d.outdoor_temp == 0.0 and d.wind_ms == pytest.approx(3.0)
    assert d.offset_physical is not None and 0.6 < d.offset_physical < 1.0
    assert d.air_setpoint in (19.5, 20.0)
    assert d.would_write == d.air_setpoint
    assert d.radiator_output_w is not None and d.radiator_output_w > 2000
    assert calls == []
    assert d.fallbacks == []

    st = hass.states.get("sensor.ot_living_room_state")
    assert st is not None and st.state == "shadow"
    assert hass.states.get("sensor.ot_living_room_air_setpoint").state == str(d.air_setpoint)
    assert hass.states.get("select.ot_living_room_mode").state == "shadow"
    assert hass.states.get("sensor.ot_global_settings_running_mean_outdoor_temperature").state == "0.0"


async def test_active_mode_writes_once_then_holds(hass: HomeAssistant):
    hub, room, calls = await _setup(hass, MODE_ACTIVE)
    coordinator = room.runtime_data
    assert coordinator.data.state == "active"
    assert len(calls) == 1
    assert calls[0]["mode"] == "temporary_override"
    assert calls[0]["entity_id"] == "climate.living_room_2"
    assert calls[0]["setpoint"] == coordinator.data.air_setpoint

    # Zone now reports what we wrote; next cycle must not rewrite.
    _set_states(hass, zone_sp=calls[0]["setpoint"])
    await coordinator.async_refresh()
    assert len(calls) == 1
    assert "unchanged" in coordinator.data.reason


async def test_manual_dial_change_is_left_alone(hass: HomeAssistant):
    hub, room, calls = await _setup(hass, MODE_ACTIVE)
    coordinator = room.runtime_data
    assert len(calls) == 1
    _set_states(hass, zone_sp=22.0)  # someone turned it up
    await coordinator.async_refresh()
    assert coordinator.data.state == "manual"
    assert len(calls) == 1


async def test_disabling_room_releases_override(hass: HomeAssistant):
    hub, room, calls = await _setup(hass, MODE_ACTIVE)
    coordinator = room.runtime_data
    assert len(calls) == 1, (coordinator.data.state, coordinator.data.reason, coordinator.data.fallbacks)
    coordinator.enabled = False
    await coordinator.async_refresh()
    assert coordinator.data.state == "off"
    assert calls[-1]["mode"] == "follow_schedule"


async def test_missing_room_file_is_reported_not_fatal(hass: HomeAssistant):
    calls: list = []
    hass.services.async_register("ramses_cc", "set_zone_mode", lambda call: calls.append(call))
    _set_states(hass)
    hub = MockConfigEntry(domain=DOMAIN, entry_id=_uid("hub"), version=2,
                          data={"entry_type": ENTRY_TYPE_HUB, CONF_WEATHER_ENTITY: "weather.home", CONF_HOUSE_DIR: str(FIXTURES)})
    room = MockConfigEntry(domain=DOMAIN, entry_id=_uid("room"), version=2,
                           data={"entry_type": ENTRY_TYPE_ROOM, CONF_NAME: "Nowhere", CONF_ROOM_ID: "nowhere",
                                 CONF_PRIMARY_CLIMATE: "climate.living_room_2", CONF_BACKUP_CLIMATE: "climate.living_room"})
    hub.add_to_hass(hass); room.add_to_hass(hass)
    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()
    assert room.state is ConfigEntryState.LOADED
    d = room.runtime_data.data
    assert d.state == "no_data"
    assert any("geometry" in f for f in d.fallbacks)
    assert calls == []


def test_hub_running_mean_needs_three_days():
    from custom_components.ot_thermostat_control.hub import OTHubData

    hub = OTHubData()
    t = datetime(2026, 1, 1, 0)
    for day in range(4):
        for hour in range(0, 24, 6):
            hub.sample_outdoor(0.0 if day else 10.0, t + timedelta(days=day, hours=hour))
    assert hub.days_completed == 3
    assert hub.running_mean_ready
    assert 0 < hub.running_mean < 10
