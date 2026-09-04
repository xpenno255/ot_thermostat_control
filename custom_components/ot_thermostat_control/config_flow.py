"""Config and options flows for OT Thermostat Control v2."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_ADAPTIVE_ENABLED,
    CONF_ADAPTIVE_REF,
    CONF_ADAPTIVE_SLOPE,
    CONF_ASYMMETRY_ENABLED,
    CONF_BACKUP_CLIMATE,
    CONF_CAP_DOWN,
    CONF_CAP_UP,
    CONF_DHW_ACTIVE_ENTITY,
    CONF_FLOW_TEMP_ENTITY,
    CONF_GROUND_TEMP,
    CONF_HOUSE_DIR,
    CONF_IRRADIANCE_SENSOR,
    CONF_MANUAL_FLOW_TEMP,
    CONF_MANUAL_HOLD,
    CONF_MODE,
    CONF_NAME,
    CONF_OCCUPANCY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_OVERRIDE_DURATION,
    CONF_PREHEAT_RELEASE,
    CONF_PRIMARY_CLIMATE,
    CONF_ROOM_ID,
    CONF_RUN_INTERVAL,
    CONF_TIME_WINDOW_ENABLED,
    CONF_TIME_WINDOW_END,
    CONF_TIME_WINDOW_START,
    CONF_TRUST_K,
    CONF_UNOCCUPIED_DURATION,
    CONF_WEATHER_ENTITY,
    CONF_WEEKDAY_AFTERNOON_OFFSET,
    CONF_WEEKDAY_EVENING_OFFSET,
    CONF_WEEKDAY_MORNING_OFFSET,
    CONF_WEEKEND_AFTERNOON_OFFSET,
    CONF_WEEKEND_EVENING_OFFSET,
    CONF_WEEKEND_MORNING_OFFSET,
    CONF_WINDOW_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_SETPOINT,
    DEFAULT_ADAPTIVE_ENABLED,
    DEFAULT_ADAPTIVE_REF,
    DEFAULT_ADAPTIVE_SLOPE,
    DEFAULT_CAP,
    DEFAULT_GROUND_TEMP,
    DEFAULT_HOUSE_DIR,
    DEFAULT_MANUAL_FLOW_TEMP,
    DEFAULT_MANUAL_HOLD,
    DEFAULT_MODE,
    DEFAULT_OVERRIDE_DURATION,
    DEFAULT_PREHEAT_RELEASE,
    DEFAULT_RUN_INTERVAL,
    DEFAULT_TIME_WINDOW_ENABLED,
    DEFAULT_TIME_WINDOW_END,
    DEFAULT_TIME_WINDOW_START,
    DEFAULT_TRUST_K,
    DEFAULT_UNOCCUPIED_DURATION,
    DEFAULT_WEEKDAY_AFTERNOON_OFFSET,
    DEFAULT_WEEKDAY_EVENING_OFFSET,
    DEFAULT_WEEKDAY_MORNING_OFFSET,
    DEFAULT_WEEKEND_AFTERNOON_OFFSET,
    DEFAULT_WEEKEND_EVENING_OFFSET,
    DEFAULT_WEEKEND_MORNING_OFFSET,
    DEFAULT_WINDOW_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DEFAULT_WINDOW_SETPOINT,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_ROOM,
    MODE_ACTIVE,
    MODE_SHADOW,
)

OPTIONAL_HUB_ENTITIES = (CONF_OUTDOOR_TEMP_SENSOR, CONF_IRRADIANCE_SENSOR, CONF_FLOW_TEMP_ENTITY, CONF_DHW_ACTIVE_ENTITY, CONF_HOUSE_DIR)
OPTIONAL_ROOM_KEYS = (CONF_OCCUPANCY_SENSOR, CONF_TRUST_K, CONF_CAP_UP, CONF_CAP_DOWN)


def _flatten(user_input: dict) -> dict:
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict) and key.endswith("_section"):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _strip_empty(flat: dict, keys: tuple[str, ...]) -> dict:
    for key in keys:
        if key in flat and (flat[key] is None or flat[key] == ""):
            flat.pop(key)
    return flat


def _num(mn: float, mx: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    cfg = selector.NumberSelectorConfig(min=mn, max=mx, step=step, mode=selector.NumberSelectorMode.BOX)
    if unit:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(cfg)


def _entity(domain: str, device_class: str | None = None) -> selector.EntitySelector:
    cfg = selector.EntitySelectorConfig(domain=domain)
    if device_class:
        cfg["device_class"] = device_class
    return selector.EntitySelector(cfg)


def list_room_ids(house_dir: Path) -> list[str]:
    rooms = house_dir / "rooms"
    if not rooms.is_dir():
        return []
    return sorted(p.stem for p in rooms.glob("*.yaml") if not p.name.startswith("_"))


def bundled_house_dir() -> Path:
    return Path(__file__).parent / DEFAULT_HOUSE_DIR


def resolve_house_dir(hass: HomeAssistant, hub_config: dict[str, Any] | None) -> Path:
    raw = (hub_config or {}).get(CONF_HOUSE_DIR)
    if not raw:
        return bundled_house_dir()
    p = Path(str(raw))
    return p if p.is_absolute() else Path(hass.config.path(str(raw)))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def hub_schema(d: dict[str, Any] | None = None) -> vol.Schema:
    d = d or {}
    return vol.Schema(
        {
            vol.Required(CONF_WEATHER_ENTITY, default=d.get(CONF_WEATHER_ENTITY, "")): _entity("weather"),
            vol.Optional("sources_section"): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_OUTDOOR_TEMP_SENSOR, description={"suggested_value": d.get(CONF_OUTDOOR_TEMP_SENSOR)}): _entity("sensor", "temperature"),
                        vol.Optional(CONF_IRRADIANCE_SENSOR, description={"suggested_value": d.get(CONF_IRRADIANCE_SENSOR)}): _entity("sensor", "irradiance"),
                        vol.Optional(CONF_FLOW_TEMP_ENTITY, description={"suggested_value": d.get(CONF_FLOW_TEMP_ENTITY)}): selector.EntitySelector(
                            selector.EntitySelectorConfig(domain=["number", "sensor"])
                        ),
                        vol.Optional(CONF_DHW_ACTIVE_ENTITY, description={"suggested_value": d.get(CONF_DHW_ACTIVE_ENTITY)}): _entity("binary_sensor"),
                        vol.Required(CONF_MANUAL_FLOW_TEMP, default=d.get(CONF_MANUAL_FLOW_TEMP, DEFAULT_MANUAL_FLOW_TEMP)): _num(30, 80, 1, "°C"),
                        vol.Required(CONF_GROUND_TEMP, default=d.get(CONF_GROUND_TEMP, DEFAULT_GROUND_TEMP)): _num(0, 20, 0.5, "°C"),
                    }
                )
            ),
            vol.Optional("comfort_section"): section(
                vol.Schema(
                    {
                        vol.Required(CONF_CAP_UP, default=d.get(CONF_CAP_UP, DEFAULT_CAP)): _num(0, 3, 0.5, "°C"),
                        vol.Required(CONF_CAP_DOWN, default=d.get(CONF_CAP_DOWN, DEFAULT_CAP)): _num(0, 3, 0.5, "°C"),
                        vol.Required(CONF_ADAPTIVE_ENABLED, default=d.get(CONF_ADAPTIVE_ENABLED, DEFAULT_ADAPTIVE_ENABLED)): selector.BooleanSelector(),
                        vol.Required(CONF_ADAPTIVE_SLOPE, default=d.get(CONF_ADAPTIVE_SLOPE, DEFAULT_ADAPTIVE_SLOPE)): _num(0, 0.2, 0.01),
                        vol.Required(CONF_ADAPTIVE_REF, default=d.get(CONF_ADAPTIVE_REF, DEFAULT_ADAPTIVE_REF)): _num(0, 20, 0.5, "°C"),
                    }
                )
            ),
            vol.Optional("advanced_section"): section(
                vol.Schema({vol.Optional(CONF_HOUSE_DIR, description={"suggested_value": d.get(CONF_HOUSE_DIR)}): selector.TextSelector()}),
                {"collapsed": True},
            ),
        }
    )


def room_schema(room_ids: list[str], d: dict[str, Any] | None = None) -> vol.Schema:
    d = d or {}
    room_options = room_ids or [d.get(CONF_ROOM_ID, "")]
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): selector.TextSelector(),
            vol.Required(CONF_ROOM_ID, default=d.get(CONF_ROOM_ID, room_options[0])): selector.SelectSelector(
                selector.SelectSelectorConfig(options=room_options, mode=selector.SelectSelectorMode.DROPDOWN, custom_value=True)
            ),
            vol.Required(CONF_PRIMARY_CLIMATE, default=d.get(CONF_PRIMARY_CLIMATE, "")): _entity("climate"),
            vol.Required(CONF_BACKUP_CLIMATE, default=d.get(CONF_BACKUP_CLIMATE, "")): _entity("climate"),
            vol.Required(CONF_MODE, default=d.get(CONF_MODE, DEFAULT_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[MODE_SHADOW, MODE_ACTIVE], translation_key="mode")
            ),
            vol.Optional("comfort_section"): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_TRUST_K, description={"suggested_value": d.get(CONF_TRUST_K)}): _num(0, 1, 0.05),
                        vol.Optional(CONF_CAP_UP, description={"suggested_value": d.get(CONF_CAP_UP)}): _num(0, 3, 0.5, "°C"),
                        vol.Optional(CONF_CAP_DOWN, description={"suggested_value": d.get(CONF_CAP_DOWN)}): _num(0, 3, 0.5, "°C"),
                        vol.Required(CONF_ASYMMETRY_ENABLED, default=d.get(CONF_ASYMMETRY_ENABLED, False)): selector.BooleanSelector(),
                    }
                )
            ),
            vol.Optional("policy_section"): section(
                vol.Schema(
                    {
                        vol.Required(CONF_OVERRIDE_DURATION, default=d.get(CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION)): _num(20, 180, 5, "min"),
                        vol.Required(CONF_MANUAL_HOLD, default=d.get(CONF_MANUAL_HOLD, DEFAULT_MANUAL_HOLD)): _num(0, 480, 10, "min"),
                        vol.Required(CONF_PREHEAT_RELEASE, default=d.get(CONF_PREHEAT_RELEASE, DEFAULT_PREHEAT_RELEASE)): _num(0, 180, 5, "min"),
                        vol.Required(CONF_RUN_INTERVAL, default=d.get(CONF_RUN_INTERVAL, DEFAULT_RUN_INTERVAL)): _num(1, 30, 1, "min"),
                        vol.Required(CONF_WINDOW_SETPOINT, default=d.get(CONF_WINDOW_SETPOINT, DEFAULT_WINDOW_SETPOINT)): _num(5, 20, 0.5, "°C"),
                        vol.Required(CONF_WINDOW_OPEN_DELAY, default=d.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY)): _num(0, 30, 1, "min"),
                        vol.Required(CONF_WINDOW_DELAY, default=d.get(CONF_WINDOW_DELAY, DEFAULT_WINDOW_DELAY)): _num(0, 60, 1, "min"),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Optional("time_window_section"): section(
                vol.Schema(
                    {
                        vol.Required(CONF_TIME_WINDOW_ENABLED, default=d.get(CONF_TIME_WINDOW_ENABLED, DEFAULT_TIME_WINDOW_ENABLED)): selector.BooleanSelector(),
                        vol.Required(CONF_TIME_WINDOW_START, default=d.get(CONF_TIME_WINDOW_START, DEFAULT_TIME_WINDOW_START)): selector.TimeSelector(),
                        vol.Required(CONF_TIME_WINDOW_END, default=d.get(CONF_TIME_WINDOW_END, DEFAULT_TIME_WINDOW_END)): selector.TimeSelector(),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Optional("occupancy_section"): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_OCCUPANCY_SENSOR, description={"suggested_value": d.get(CONF_OCCUPANCY_SENSOR)}): _entity("binary_sensor", "occupancy"),
                        vol.Required(CONF_UNOCCUPIED_DURATION, default=d.get(CONF_UNOCCUPIED_DURATION, DEFAULT_UNOCCUPIED_DURATION)): _num(0, 60, 1, "min"),
                        vol.Required(CONF_WEEKDAY_MORNING_OFFSET, default=d.get(CONF_WEEKDAY_MORNING_OFFSET, DEFAULT_WEEKDAY_MORNING_OFFSET)): _num(-3, 0, 0.1, "°C"),
                        vol.Required(CONF_WEEKDAY_AFTERNOON_OFFSET, default=d.get(CONF_WEEKDAY_AFTERNOON_OFFSET, DEFAULT_WEEKDAY_AFTERNOON_OFFSET)): _num(-3, 0, 0.1, "°C"),
                        vol.Required(CONF_WEEKDAY_EVENING_OFFSET, default=d.get(CONF_WEEKDAY_EVENING_OFFSET, DEFAULT_WEEKDAY_EVENING_OFFSET)): _num(-3, 0, 0.1, "°C"),
                        vol.Required(CONF_WEEKEND_MORNING_OFFSET, default=d.get(CONF_WEEKEND_MORNING_OFFSET, DEFAULT_WEEKEND_MORNING_OFFSET)): _num(-3, 0, 0.1, "°C"),
                        vol.Required(CONF_WEEKEND_AFTERNOON_OFFSET, default=d.get(CONF_WEEKEND_AFTERNOON_OFFSET, DEFAULT_WEEKEND_AFTERNOON_OFFSET)): _num(-3, 0, 0.1, "°C"),
                        vol.Required(CONF_WEEKEND_EVENING_OFFSET, default=d.get(CONF_WEEKEND_EVENING_OFFSET, DEFAULT_WEEKEND_EVENING_OFFSET)): _num(-3, 0, 0.1, "°C"),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


class OTConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(step_id="user", menu_options=["hub", "room"])

    async def async_step_hub(self, user_input: dict[str, Any] | None = None):
        for entry in self._async_current_entries():
            if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
                return self.async_abort(reason="hub_already_configured")
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_HUB_ENTITIES)
            flat["entry_type"] = ENTRY_TYPE_HUB
            return self.async_create_entry(title="OT Global Settings", data=flat)
        return self.async_show_form(step_id="hub", data_schema=hub_schema())

    async def async_step_room(self, user_input: dict[str, Any] | None = None):
        hub_cfg = (self.hass.data.get(DOMAIN, {}).get("hub") or {}).get("config")
        room_ids = await self.hass.async_add_executor_job(list_room_ids, resolve_house_dir(self.hass, hub_cfg))
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_ROOM_KEYS)
            flat["entry_type"] = ENTRY_TYPE_ROOM
            return self.async_create_entry(title=flat[CONF_NAME], data=flat)
        return self.async_show_form(step_id="room", data_schema=room_schema(room_ids))

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry):
        if config_entry.data.get("entry_type") == ENTRY_TYPE_HUB:
            return OTHubOptionsFlow()
        return OTRoomOptionsFlow()


class OTRoomOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_ROOM_KEYS)
            return self.async_create_entry(title="", data=flat)
        hub_cfg = (self.hass.data.get(DOMAIN, {}).get("hub") or {}).get("config")
        room_ids = await self.hass.async_add_executor_job(list_room_ids, resolve_house_dir(self.hass, hub_cfg))
        return self.async_show_form(step_id="init", data_schema=room_schema(room_ids, current))


class OTHubOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            flat = _strip_empty(_flatten(user_input), OPTIONAL_HUB_ENTITIES)
            return self.async_create_entry(title="", data=flat)
        return self.async_show_form(step_id="init", data_schema=hub_schema(current))
