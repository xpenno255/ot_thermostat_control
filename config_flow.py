"""Config flow for OT Thermostat Control."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_AIR_TEMP_SENSOR,
    CONF_AUTOMATION_DELAY,
    CONF_BACKUP_CLIMATE,
    CONF_COAST_CYCLES,
    CONF_CORRECTION_GAIN,
    CONF_MAX_SETPOINT,
    CONF_MAX_STEP,
    CONF_MIN_SETPOINT,
    CONF_NAME,
    CONF_OCCUPANCY_SENSOR,
    CONF_ORIENTATION,
    CONF_OVERRIDE_DURATION,
    CONF_PRIMARY_CLIMATE,
    CONF_ROOM_PROFILE,
    CONF_RUN_INTERVAL,
    CONF_SMOOTHING_ENABLED,
    CONF_TIME_WINDOW_ENABLED,
    CONF_TIME_WINDOW_END,
    CONF_TIME_WINDOW_START,
    CONF_UNOCCUPIED_DURATION,
    CONF_WEEKDAY_AFTERNOON_OFFSET,
    CONF_WEEKDAY_EVENING_OFFSET,
    CONF_WEEKDAY_MORNING_OFFSET,
    CONF_WEEKEND_AFTERNOON_OFFSET,
    CONF_WEEKEND_EVENING_OFFSET,
    CONF_WEEKEND_MORNING_OFFSET,
    CONF_APPARENT_TEMP_ENTITY,
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_REF_TEMP,
    CONF_WEATHER_SCALE,
    CONF_WEATHER_SEVERITY_EXPONENT,
    CONF_K_ADAPTATION_MODE,
    CONF_GRADIENT_SCALE,
    CONF_GRADIENT_EXPONENT,
    CONF_WIND_SPEED_SENSOR,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_SETPOINT,
    CONF_WINDOW_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_ADJACENT_SENSORS,
    DEFAULT_AUTOMATION_DELAY,
    DEFAULT_COAST_CYCLES,
    DEFAULT_CORRECTION_GAIN,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MAX_STEP,
    DEFAULT_ORIENTATION,
    DEFAULT_OVERRIDE_DURATION,
    DEFAULT_ROOM_PROFILE,
    DEFAULT_RUN_INTERVAL,
    DEFAULT_SMOOTHING_ENABLED,
    DEFAULT_WEATHER_REF_TEMP,
    DEFAULT_WEATHER_SCALE,
    DEFAULT_WEATHER_SEVERITY_EXPONENT,
    DEFAULT_K_ADAPTATION_MODE,
    DEFAULT_GRADIENT_SCALE,
    DEFAULT_GRADIENT_EXPONENT,
    K_MODE_WEATHER_ONLY,
    K_MODE_OT_REFERENCED,
    DEFAULT_TIME_WINDOW_ENABLED,
    DEFAULT_TIME_WINDOW_END,
    DEFAULT_TIME_WINDOW_START,
    DEFAULT_UNOCCUPIED_DURATION,
    DEFAULT_WEEKDAY_AFTERNOON_OFFSET,
    DEFAULT_WEEKDAY_EVENING_OFFSET,
    DEFAULT_WEEKDAY_MORNING_OFFSET,
    DEFAULT_WEEKEND_AFTERNOON_OFFSET,
    DEFAULT_WEEKEND_EVENING_OFFSET,
    DEFAULT_WEEKEND_MORNING_OFFSET,
    DEFAULT_WINDOW_SETPOINT,
    DEFAULT_WINDOW_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    CONF_ADVANCED_SENSORS,
    DEFAULT_ADVANCED_SENSORS,
    DOMAIN,
    ENTRY_TYPE_HUB,
    ENTRY_TYPE_ROOM,
    ORIENTATION_AZIMUTHS,
    ROOM_PROFILES,
)

ORIENTATION_OPTIONS = list(ORIENTATION_AZIMUTHS.keys())
ROOM_PROFILE_OPTIONS = list(ROOM_PROFILES.keys())


def _flatten_input(user_input: dict) -> dict:
    """Flatten section-based input into a single dict."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict) and key.endswith("_section"):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _build_hub_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the hub config/options schema with sections."""
    d = defaults or {}

    return vol.Schema(
        {
            # --- Core fields (always visible) ---
            vol.Required(
                CONF_WEATHER_ENTITY,
                default=d.get(CONF_WEATHER_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            # --- Hub sensors section ---
            vol.Optional("hub_sensors_section"): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_SOLAR_SENSOR,
                            description={
                                "suggested_value": d.get(CONF_SOLAR_SENSOR),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor",
                                device_class="irradiance",
                            )
                        ),
                        vol.Optional(
                            CONF_OUTDOOR_TEMP_SENSOR,
                            description={
                                "suggested_value": d.get(CONF_OUTDOOR_TEMP_SENSOR),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor",
                                device_class="temperature",
                            )
                        ),
                        vol.Optional(
                            CONF_OUTDOOR_HUMIDITY_SENSOR,
                            description={
                                "suggested_value": d.get(CONF_OUTDOOR_HUMIDITY_SENSOR),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor",
                                device_class="humidity",
                            )
                        ),
                        vol.Optional(
                            CONF_WIND_SPEED_SENSOR,
                            description={
                                "suggested_value": d.get(CONF_WIND_SPEED_SENSOR),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor",
                                device_class="wind_speed",
                            )
                        ),
                        vol.Optional(
                            CONF_APPARENT_TEMP_ENTITY,
                            description={
                                "suggested_value": d.get(CONF_APPARENT_TEMP_ENTITY),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor",
                                device_class="temperature",
                            )
                        ),
                    }
                )
            ),
            # --- Hub weather section ---
            vol.Optional("hub_weather_section"): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_WEATHER_REF_TEMP,
                            default=d.get(CONF_WEATHER_REF_TEMP, DEFAULT_WEATHER_REF_TEMP),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-10.0,
                                max=20.0,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEATHER_SCALE,
                            default=d.get(CONF_WEATHER_SCALE, DEFAULT_WEATHER_SCALE),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1.0,
                                max=30.0,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEATHER_SEVERITY_EXPONENT,
                            default=d.get(
                                CONF_WEATHER_SEVERITY_EXPONENT,
                                DEFAULT_WEATHER_SEVERITY_EXPONENT,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.5,
                                max=3.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(
                            CONF_SMOOTHING_ENABLED,
                            default=d.get(
                                CONF_SMOOTHING_ENABLED, DEFAULT_SMOOTHING_ENABLED
                            ),
                        ): selector.BooleanSelector(),
                        vol.Required(
                            CONF_ADVANCED_SENSORS,
                            default=d.get(CONF_ADVANCED_SENSORS, DEFAULT_ADVANCED_SENSORS),
                        ): selector.BooleanSelector(),
                    }
                )
            ),
            # --- K adaptation section ---
            vol.Optional("hub_k_section"): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_GRADIENT_SCALE,
                            default=d.get(CONF_GRADIENT_SCALE, DEFAULT_GRADIENT_SCALE),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=5.0,
                                max=30.0,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_GRADIENT_EXPONENT,
                            default=d.get(CONF_GRADIENT_EXPONENT, DEFAULT_GRADIENT_EXPONENT),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.5,
                                max=3.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                    }
                )
            ),
        }
    )


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the config/options schema with sections."""
    d = defaults or {}

    return vol.Schema(
        {
            # --- Core fields (always visible) ---
            vol.Required(
                CONF_NAME,
                default=d.get(CONF_NAME, ""),
            ): selector.TextSelector(),
            vol.Required(
                CONF_PRIMARY_CLIMATE,
                default=d.get(CONF_PRIMARY_CLIMATE, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Required(
                CONF_BACKUP_CLIMATE,
                default=d.get(CONF_BACKUP_CLIMATE, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            # --- Environment section ---
            vol.Optional("environment_section"): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_AIR_TEMP_SENSOR,
                            description={
                                "suggested_value": d.get(CONF_AIR_TEMP_SENSOR),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="sensor",
                                device_class="temperature",
                            )
                        ),
                        vol.Required(
                            CONF_ROOM_PROFILE,
                            default=d.get(CONF_ROOM_PROFILE, DEFAULT_ROOM_PROFILE),
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=ROOM_PROFILE_OPTIONS,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key="room_profile",
                            )
                        ),
                        vol.Required(
                            CONF_ORIENTATION,
                            default=d.get(CONF_ORIENTATION, DEFAULT_ORIENTATION),
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=ORIENTATION_OPTIONS,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                                translation_key="orientation",
                            )
                        ),
                    }
                )
            ),
            # --- Occupancy section (optional) ---
            vol.Optional("occupancy_section"): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_OCCUPANCY_SENSOR,
                            description={
                                "suggested_value": d.get(CONF_OCCUPANCY_SENSOR),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="binary_sensor",
                                device_class="occupancy",
                            )
                        ),
                        vol.Required(
                            CONF_UNOCCUPIED_DURATION,
                            default=d.get(
                                CONF_UNOCCUPIED_DURATION, DEFAULT_UNOCCUPIED_DURATION
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=30,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                        vol.Required(
                            CONF_WEEKDAY_MORNING_OFFSET,
                            default=d.get(
                                CONF_WEEKDAY_MORNING_OFFSET,
                                DEFAULT_WEEKDAY_MORNING_OFFSET,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-3.0,
                                max=0.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEEKDAY_AFTERNOON_OFFSET,
                            default=d.get(
                                CONF_WEEKDAY_AFTERNOON_OFFSET,
                                DEFAULT_WEEKDAY_AFTERNOON_OFFSET,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-3.0,
                                max=0.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEEKDAY_EVENING_OFFSET,
                            default=d.get(
                                CONF_WEEKDAY_EVENING_OFFSET,
                                DEFAULT_WEEKDAY_EVENING_OFFSET,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-3.0,
                                max=0.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEEKEND_MORNING_OFFSET,
                            default=d.get(
                                CONF_WEEKEND_MORNING_OFFSET,
                                DEFAULT_WEEKEND_MORNING_OFFSET,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-3.0,
                                max=0.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEEKEND_AFTERNOON_OFFSET,
                            default=d.get(
                                CONF_WEEKEND_AFTERNOON_OFFSET,
                                DEFAULT_WEEKEND_AFTERNOON_OFFSET,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-3.0,
                                max=0.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WEEKEND_EVENING_OFFSET,
                            default=d.get(
                                CONF_WEEKEND_EVENING_OFFSET,
                                DEFAULT_WEEKEND_EVENING_OFFSET,
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=-3.0,
                                max=0.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                    }
                )
            ),
            # --- Comfort section ---
            vol.Optional("comfort_section"): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_K_ADAPTATION_MODE,
                            default=d.get(CONF_K_ADAPTATION_MODE, DEFAULT_K_ADAPTATION_MODE),
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[K_MODE_WEATHER_ONLY, K_MODE_OT_REFERENCED],
                                translation_key="k_adaptation_mode",
                            )
                        ),
                        vol.Required(
                            CONF_CORRECTION_GAIN,
                            default=d.get(CONF_CORRECTION_GAIN, DEFAULT_CORRECTION_GAIN),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.0,
                                max=3.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(
                            CONF_MAX_SETPOINT,
                            default=d.get(CONF_MAX_SETPOINT, DEFAULT_MAX_SETPOINT),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=15.0,
                                max=30.0,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Optional(
                            CONF_MIN_SETPOINT,
                            description={
                                "suggested_value": d.get(CONF_MIN_SETPOINT),
                            },
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=5.0,
                                max=20.0,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_OVERRIDE_DURATION,
                            default=d.get(
                                CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=10,
                                max=180,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                    }
                )
            ),
            # --- Advanced section ---
            vol.Optional("advanced_section"): section(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_RUN_INTERVAL,
                            default=d.get(CONF_RUN_INTERVAL, DEFAULT_RUN_INTERVAL),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=1,
                                max=30,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                        vol.Required(
                            CONF_AUTOMATION_DELAY,
                            default=d.get(
                                CONF_AUTOMATION_DELAY, DEFAULT_AUTOMATION_DELAY
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=60,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="sec",
                            )
                        ),
                        vol.Required(
                            CONF_COAST_CYCLES,
                            default=d.get(CONF_COAST_CYCLES, DEFAULT_COAST_CYCLES),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.0,
                                max=10.0,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(
                            CONF_MAX_STEP,
                            default=d.get(CONF_MAX_STEP, DEFAULT_MAX_STEP),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0.1,
                                max=2.0,
                                step=0.1,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(
                            CONF_TIME_WINDOW_ENABLED,
                            default=d.get(
                                CONF_TIME_WINDOW_ENABLED,
                                DEFAULT_TIME_WINDOW_ENABLED,
                            ),
                        ): selector.BooleanSelector(),
                        vol.Required(
                            CONF_TIME_WINDOW_START,
                            default=d.get(
                                CONF_TIME_WINDOW_START,
                                DEFAULT_TIME_WINDOW_START,
                            ),
                        ): selector.TimeSelector(),
                        vol.Required(
                            CONF_TIME_WINDOW_END,
                            default=d.get(
                                CONF_TIME_WINDOW_END,
                                DEFAULT_TIME_WINDOW_END,
                            ),
                        ): selector.TimeSelector(),
                    }
                )
            ),
            # --- Door/Window section (optional) ---
            vol.Optional("window_section"): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_WINDOW_SENSORS,
                            description={
                                "suggested_value": d.get(CONF_WINDOW_SENSORS),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="binary_sensor",
                                multiple=True,
                            )
                        ),
                        vol.Required(
                            CONF_WINDOW_SETPOINT,
                            default=d.get(
                                CONF_WINDOW_SETPOINT, DEFAULT_WINDOW_SETPOINT
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=5,
                                max=20,
                                step=0.5,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="\u00b0C",
                            )
                        ),
                        vol.Required(
                            CONF_WINDOW_DELAY,
                            default=d.get(
                                CONF_WINDOW_DELAY, DEFAULT_WINDOW_DELAY
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=5,
                                max=60,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                        vol.Required(
                            CONF_WINDOW_OPEN_DELAY,
                            default=d.get(
                                CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY
                            ),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=0,
                                max=30,
                                step=1,
                                mode=selector.NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        ),
                        vol.Optional(
                            CONF_ADJACENT_SENSORS,
                            description={
                                "suggested_value": d.get(CONF_ADJACENT_SENSORS),
                            },
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="binary_sensor",
                                multiple=True,
                            )
                        ),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


class OTConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OT Thermostat Control."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Show menu: Global Settings or Room."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["hub", "room"],
        )

    async def async_step_hub(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle hub configuration."""
        # Enforce single hub
        for entry in self._async_current_entries():
            if entry.data.get("entry_type") == ENTRY_TYPE_HUB:
                return self.async_abort(reason="hub_already_configured")

        if user_input is not None:
            flat = _flatten_input(user_input)

            # Strip empty optional sensor keys
            for key in (CONF_SOLAR_SENSOR, CONF_OUTDOOR_TEMP_SENSOR, CONF_OUTDOOR_HUMIDITY_SENSOR, CONF_WIND_SPEED_SENSOR, CONF_APPARENT_TEMP_ENTITY):
                if not flat.get(key):
                    flat.pop(key, None)

            flat["entry_type"] = ENTRY_TYPE_HUB

            return self.async_create_entry(
                title="OT Global Settings",
                data=flat,
            )

        return self.async_show_form(
            step_id="hub",
            data_schema=_build_hub_schema(),
        )

    async def async_step_room(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle room configuration."""
        if user_input is not None:
            flat = _flatten_input(user_input)

            # Strip empty optional entity selectors (room-specific only)
            for key in (CONF_AIR_TEMP_SENSOR, CONF_OCCUPANCY_SENSOR, CONF_MIN_SETPOINT, CONF_WINDOW_SENSORS, CONF_ADJACENT_SENSORS):
                if not flat.get(key):
                    flat.pop(key, None)

            flat["entry_type"] = ENTRY_TYPE_ROOM

            return self.async_create_entry(
                title=flat[CONF_NAME],
                data=flat,
            )

        return self.async_show_form(
            step_id="room",
            data_schema=_build_schema(),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow handler."""
        if config_entry.data.get("entry_type") == ENTRY_TYPE_HUB:
            return OTHubOptionsFlow(config_entry)
        return OTOptionsFlow(config_entry)


class OTOptionsFlow(OptionsFlow):
    """Handle options flow for OT Thermostat Control."""

    def __init__(self, config_entry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        if user_input is not None:
            flat = _flatten_input(user_input)

            # Strip empty optional entity selectors (room-specific only)
            for key in (CONF_AIR_TEMP_SENSOR, CONF_OCCUPANCY_SENSOR, CONF_MIN_SETPOINT, CONF_WINDOW_SENSORS, CONF_ADJACENT_SENSORS):
                if not flat.get(key):
                    flat.pop(key, None)

            return self.async_create_entry(title="", data=flat)

        # Merge data + options to get current values
        current = {**self._config_entry.data, **self._config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(current),
        )


class OTHubOptionsFlow(OptionsFlow):
    """Handle options flow for OT Global Hub."""

    def __init__(self, config_entry) -> None:
        """Initialise options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the hub options."""
        if user_input is not None:
            flat = _flatten_input(user_input)

            # Strip empty optional hub sensor keys
            for key in (CONF_SOLAR_SENSOR, CONF_OUTDOOR_TEMP_SENSOR, CONF_OUTDOOR_HUMIDITY_SENSOR, CONF_WIND_SPEED_SENSOR, CONF_APPARENT_TEMP_ENTITY):
                if not flat.get(key):
                    flat.pop(key, None)

            return self.async_create_entry(title="", data=flat)

        # Merge data + options to get current values
        current = {**self._config_entry.data, **self._config_entry.options}

        return self.async_show_form(
            step_id="init",
            data_schema=_build_hub_schema(current),
        )
