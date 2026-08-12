"""DataUpdateCoordinator for OT Thermostat Control."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .calc import OTCalcInputs, OTCalcResult, calculate_setpoint
from .const import (
    CONF_AIR_TEMP_SENSOR,
    CONF_AUTOMATION_DELAY,
    CONF_BACKUP_CLIMATE,
    COAST_STABLE_CYCLES_THRESHOLD,
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
    CONF_OUTDOOR_HUMIDITY_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SPEED_SENSOR,
    CONF_APPARENT_TEMP_ENTITY,
    CONF_K_MAX,
    CONF_WEATHER_K_BOOST,
    CONF_WEATHER_REF_TEMP,
    CONF_WEATHER_SCALE,
    CONF_WEATHER_SEVERITY_EXPONENT,
    CONF_K_ADAPTATION_MODE,
    CONF_GRADIENT_SCALE,
    CONF_GRADIENT_EXPONENT,
    DEFAULT_K_ADAPTATION_MODE,
    DEFAULT_GRADIENT_SCALE,
    DEFAULT_GRADIENT_EXPONENT,
    DEFAULT_AUTOMATION_DELAY,
    DEFAULT_COAST_CYCLES,
    DEFAULT_CORRECTION_GAIN,
    DEFAULT_MAX_SETPOINT,
    DEFAULT_MAX_STEP,
    DEFAULT_MIN_SETPOINT,
    DEFAULT_ORIENTATION,
    DEFAULT_OVERRIDE_DURATION,
    DEFAULT_ROOM_PROFILE,
    DEFAULT_RUN_INTERVAL,
    DEFAULT_SMOOTHING_ENABLED,
    DEFAULT_MRT_BASELINE_ALPHA,
    DEFAULT_THERMAL_ALPHA,
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
    DEFAULT_K_MAX,
    DEFAULT_WEATHER_K_BOOST,
    DEFAULT_WEATHER_REF_TEMP,
    DEFAULT_WEATHER_SCALE,
    DEFAULT_WEATHER_SEVERITY_EXPONENT,
    DOMAIN,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_SETPOINT,
    CONF_WINDOW_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    DEFAULT_WINDOW_SETPOINT,
    CONF_ADJACENT_SENSORS,
    DEFAULT_WINDOW_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    ENTITY_AT_HOME_MODE,
    ENTITY_HOLIDAY_MODE,
    MORNING_START,
    MORNING_END,
    AFTERNOON_END,
    EVENING_END,
    ORIENTATION_AZIMUTHS,
    ROOM_PROFILES,
)
from .mrt import MRTInputs
from .store import OTStore

_LOGGER = logging.getLogger(__name__)


class OTCoordinatorData:
    """Snapshot of coordinator state consumed by entities."""

    def __init__(
        self,
        result: OTCalcResult,
        enabled: bool,
        overshoot_count: int,
        active_thermostat: str = "",
        air_temp: float | None = None,
        last_run: datetime | None = None,
        occupancy_status: str = "unknown",
        active_offset: float = 0.0,
        time_window_active: bool = True,
        operative_temp: float | None = None,
        equilibrium_target: float | None = None,
        mrt_baseline: float | None = None,
        weather_severity: float = 0.0,
        effective_k: float = 0.0,
        window_override_active: bool = False,
    ) -> None:
        self.result = result
        self.enabled = enabled
        self.overshoot_count = overshoot_count
        self.active_thermostat = active_thermostat
        self.air_temp = air_temp
        self.last_run = last_run
        self.occupancy_status = occupancy_status
        self.active_offset = active_offset
        self.time_window_active = time_window_active
        self.operative_temp = operative_temp
        self.equilibrium_target = equilibrium_target
        self.mrt_baseline = mrt_baseline
        self.weather_severity = weather_severity
        self.effective_k = effective_k
        self.window_override_active = window_override_active


class OTCoordinator(DataUpdateCoordinator[OTCoordinatorData]):
    """Coordinator for a single OT-controlled room."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, store: OTStore
    ) -> None:
        self._entry = entry
        self._store = store
        self._enabled = True
        self._occupancy_enabled = True
        self._stable_above_count: int = 0
        self._prev_window_open: bool = False

        # Merge data + options
        self._config: dict[str, Any] = {**entry.data, **entry.options}

        # Restore window-open state from persisted store (prevents resetting
        # detection delay on HA restart when door was already open)
        if self._store.get("window_open_time") is not None:
            self._prev_window_open = True

        interval = timedelta(
            minutes=self._config.get(CONF_RUN_INTERVAL, DEFAULT_RUN_INTERVAL)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"OT {self._config[CONF_NAME]}",
            update_interval=interval,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def room_name(self) -> str:
        return self._config[CONF_NAME]

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def occupancy_enabled(self) -> bool:
        return self._occupancy_enabled

    @occupancy_enabled.setter
    def occupancy_enabled(self, value: bool) -> None:
        self._occupancy_enabled = value

    # ------------------------------------------------------------------
    # Number entity runtime overrides
    # ------------------------------------------------------------------

    _correction_gain: float | None = None
    _coast_cycles: float | None = None
    _f_out: float | None = None
    _f_win: float | None = None
    _k_loss: float | None = None
    _k_solar: float | None = None
    _weather_k_boost: float | None = None
    _k_max: float | None = None
    _thermal_alpha: float | None = None

    _ATTR_MAP: dict[str, str] = {
        CONF_CORRECTION_GAIN: "_correction_gain",
        CONF_COAST_CYCLES: "_coast_cycles",
        "f_out": "_f_out",
        "f_win": "_f_win",
        "k_loss": "_k_loss",
        "k_solar": "_k_solar",
        CONF_WEATHER_K_BOOST: "_weather_k_boost",
        CONF_K_MAX: "_k_max",
        "thermal_alpha": "_thermal_alpha",
    }

    _DEFAULT_MAP: dict[str, float] = {
        CONF_CORRECTION_GAIN: DEFAULT_CORRECTION_GAIN,
        CONF_COAST_CYCLES: DEFAULT_COAST_CYCLES,
        CONF_WEATHER_K_BOOST: DEFAULT_WEATHER_K_BOOST,
        CONF_K_MAX: DEFAULT_K_MAX,
        CONF_WEATHER_SEVERITY_EXPONENT: DEFAULT_WEATHER_SEVERITY_EXPONENT,
    }

    def get_number_value(self, key: str) -> float:
        """Get a tuneable number value (entity override > store > config > profile)."""
        attr = self._ATTR_MAP.get(key)
        if attr:
            val = getattr(self, attr, None)
            if val is not None:
                return val

        stored = self._store.get(key)
        if stored is not None:
            return float(stored)

        if key in self._DEFAULT_MAP:
            return float(self._config.get(key, self._DEFAULT_MAP[key]))

        profile_key = self._config.get(CONF_ROOM_PROFILE, DEFAULT_ROOM_PROFILE)
        profile = ROOM_PROFILES.get(profile_key, {})
        if key in profile:
            return profile[key]

        if key == "thermal_alpha":
            return DEFAULT_THERMAL_ALPHA

        return 0.0

    def set_number_value(self, key: str, value: float) -> None:
        """Set a tuneable number value (called by number entities)."""
        attr = self._ATTR_MAP.get(key)
        if attr:
            setattr(self, attr, value)
        self._store.set(key, value)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_float_state(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_float_attr(self, entity_id: str, attr: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        val = state.attributes.get(attr)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _get_hub_config(self) -> dict[str, Any]:
        """Find the hub entry and return its merged config.

        Returns empty dict if no hub exists (backwards-compat fallback).
        """
        hub_info = self.hass.data.get(DOMAIN, {}).get("hub")
        if hub_info is None:
            _LOGGER.warning(
                "OT %s: no global hub found, using per-room config (deprecated)",
                self.room_name,
            )
            return {}
        return hub_info.get("config", {})

    def _is_global_enabled(self) -> bool:
        """Check if global overrides are enabled via the hub switch."""
        hub_info = self.hass.data.get(DOMAIN, {}).get("hub")
        if hub_info is None:
            return True  # No hub = no global disable
        return hub_info["data"].global_enabled

    def _is_holiday_mode(self) -> bool:
        """Check if holiday mode is active. Returns False if entity missing."""
        state = self.hass.states.get(ENTITY_HOLIDAY_MODE)
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        return state.state == "on"

    def _is_at_home_mode(self) -> bool:
        """Check if at-home mode is active. Returns False if entity missing."""
        state = self.hass.states.get(ENTITY_AT_HOME_MODE)
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        return state.state == "on"

    def _is_within_time_window(self) -> bool:
        """Check if current time is within the configured operating window.

        Returns True if time window is disabled (run 24/7) or if currently
        within the window.
        """
        if not self._config.get(
            CONF_TIME_WINDOW_ENABLED, DEFAULT_TIME_WINDOW_ENABLED
        ):
            return True  # Feature disabled = always active

        now = dt_util.now()
        current_minutes = now.hour * 60 + now.minute

        start_str = self._config.get(
            CONF_TIME_WINDOW_START, DEFAULT_TIME_WINDOW_START
        )
        end_str = self._config.get(
            CONF_TIME_WINDOW_END, DEFAULT_TIME_WINDOW_END
        )

        # Parse "HH:MM" or "HH:MM:SS" strings to minutes
        s_parts = str(start_str).split(":")
        e_parts = str(end_str).split(":")
        start_min = int(s_parts[0]) * 60 + int(s_parts[1])
        end_min = int(e_parts[0]) * 60 + int(e_parts[1])

        if start_min <= end_min:
            return start_min <= current_minutes < end_min
        # Wraps midnight (e.g., 22:00 - 06:30)
        return current_minutes >= start_min or current_minutes < end_min

    def _get_occupancy_offset(self) -> tuple[str, float]:
        """Determine occupancy status and the applicable offset.

        Returns (status, offset) where status is
        "occupied" | "unoccupied" | "no_sensor" | "disabled" and offset
        is the raw (un-halved) value for the current time period (0.0 if none).
        """
        if not self._occupancy_enabled:
            return ("disabled", 0.0)

        sensor_id = self._config.get(CONF_OCCUPANCY_SENSOR, "")
        if not sensor_id:
            return ("no_sensor", 0.0)

        state = self.hass.states.get(sensor_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return ("no_sensor", 0.0)

        if state.state != "off":
            # Sensor is "on" = occupied
            return ("occupied", 0.0)

        # Sensor is "off" = not occupied. Check duration.
        unoccupied_duration = float(
            self._config.get(
                CONF_UNOCCUPIED_DURATION, DEFAULT_UNOCCUPIED_DURATION
            )
        )
        now = dt_util.utcnow()
        last_changed = state.last_changed
        if last_changed is not None:
            elapsed_min = (now - last_changed).total_seconds() / 60.0
            if elapsed_min < unoccupied_duration:
                return ("occupied", 0.0)  # Not long enough yet

        # Unoccupied long enough — determine which offset to use
        offset = self._pick_time_period_offset()
        return ("unoccupied", offset)

    def _pick_time_period_offset(self) -> float:
        """Pick the occupancy offset for the current time period.

        Uses weekend offsets if actual weekend OR at_home_mode is on.
        Returns 0.0 if outside all defined periods (night).
        """
        now = dt_util.now()
        current_minutes = now.hour * 60 + now.minute

        is_weekend = now.weekday() >= 5 or self._is_at_home_mode()

        # Determine time period
        if MORNING_START <= current_minutes < MORNING_END:
            period = "morning"
        elif MORNING_END <= current_minutes < AFTERNOON_END:
            period = "afternoon"
        elif AFTERNOON_END <= current_minutes < EVENING_END:
            period = "evening"
        else:
            return 0.0  # Outside all periods — no offset

        # Select the right config key and default
        key_map = {
            True: {
                "morning": (CONF_WEEKEND_MORNING_OFFSET, DEFAULT_WEEKEND_MORNING_OFFSET),
                "afternoon": (CONF_WEEKEND_AFTERNOON_OFFSET, DEFAULT_WEEKEND_AFTERNOON_OFFSET),
                "evening": (CONF_WEEKEND_EVENING_OFFSET, DEFAULT_WEEKEND_EVENING_OFFSET),
            },
            False: {
                "morning": (CONF_WEEKDAY_MORNING_OFFSET, DEFAULT_WEEKDAY_MORNING_OFFSET),
                "afternoon": (CONF_WEEKDAY_AFTERNOON_OFFSET, DEFAULT_WEEKDAY_AFTERNOON_OFFSET),
                "evening": (CONF_WEEKDAY_EVENING_OFFSET, DEFAULT_WEEKDAY_EVENING_OFFSET),
            },
        }
        key, default = key_map[is_weekend][period]
        return float(self._config.get(key, default))

    def _pick_active_thermostat(self) -> str:
        """Return entity_id of the thermostat with the most recent report."""
        primary = self._config.get(CONF_PRIMARY_CLIMATE, "")
        backup = self._config.get(CONF_BACKUP_CLIMATE, "")

        if not primary:
            return backup

        primary_state = self.hass.states.get(primary)
        if primary_state is None or primary_state.state in (
            "unknown",
            "unavailable",
        ):
            return backup if backup else primary

        if not backup:
            return primary

        backup_state = self.hass.states.get(backup)
        if backup_state is None or backup_state.state in (
            "unknown",
            "unavailable",
        ):
            return primary

        # Compare last_reported (HA 2024.4+) or last_updated
        p_time = primary_state.attributes.get(
            "last_reported", primary_state.last_updated
        )
        b_time = backup_state.attributes.get(
            "last_reported", backup_state.last_updated
        )
        if b_time and p_time and b_time > p_time:
            return backup
        return primary

    def _get_scheduled_setpoint(self, entity_id: str) -> float | None:
        """Read the evohome schedule and return the active setpoint for now.

        Parses the 'schedule' attribute on the climate entity to find the
        switchpoint that is currently active (most recent switchpoint whose
        time_of_day has passed today). This avoids reading the 'temperature'
        attribute which may reflect our own override.

        The schedule is cached in the store so that if the entity enters an
        'unknown' state (e.g. after an HA upgrade) the last-known schedule
        is used instead of falling back to the 'temperature' attribute.
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            return None

        schedule = state.attributes.get("schedule")

        # Cache / retrieve schedule
        cache_key = f"cached_schedule_{entity_id}"
        if schedule and isinstance(schedule, list):
            # Live schedule available — cache it
            cached = self._store.get(cache_key)
            if cached != schedule:
                self._store.set(cache_key, schedule)
                _LOGGER.debug(
                    "OT %s cached schedule for %s", self.room_name, entity_id
                )
        else:
            # No live schedule — try cached version
            schedule = self._store.get(cache_key)
            if schedule and isinstance(schedule, list):
                _LOGGER.info(
                    "OT %s using cached schedule for %s (live schedule unavailable)",
                    self.room_name,
                    entity_id,
                )
            else:
                _LOGGER.warning(
                    "OT %s no schedule available for %s (live and cache both empty)",
                    self.room_name,
                    entity_id,
                )
                return None

        return self._resolve_schedule_setpoint(schedule)

    def _resolve_schedule_setpoint(self, schedule: list) -> float | None:
        """Find the active setpoint from a schedule switchpoint list."""
        now = dt_util.now()
        dow = now.weekday()  # 0=Monday
        current_time = now.strftime("%H:%M")

        # Find today's switchpoints
        today_switchpoints = []
        for day in schedule:
            if day.get("day_of_week") == dow:
                today_switchpoints = day.get("switchpoints", [])
                break

        if not today_switchpoints:
            return None

        # Find the most recent switchpoint that has passed
        active_setpoint = None
        for sp in today_switchpoints:
            sp_time = sp.get("time_of_day", "")
            sp_heat = sp.get("heat_setpoint")
            if sp_time <= current_time and sp_heat is not None:
                active_setpoint = float(sp_heat)

        if active_setpoint is None:
            # Before first switchpoint today — use last switchpoint from
            # yesterday (wrap around)
            yesterday_dow = (dow - 1) % 7
            for day in schedule:
                if day.get("day_of_week") == yesterday_dow:
                    yesterday_sps = day.get("switchpoints", [])
                    if yesterday_sps:
                        last_sp = yesterday_sps[-1]
                        active_setpoint = float(last_sp.get("heat_setpoint", 0))
                    break

        return active_setpoint

    def _get_next_switchpoint_setpoint(
        self, entity_id: str
    ) -> float | None:
        """Get the next upcoming switchpoint setpoint (for pre-heat detection)."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None

        schedule = state.attributes.get("schedule")
        if not schedule or not isinstance(schedule, list):
            # Try cached schedule
            cache_key = f"cached_schedule_{entity_id}"
            schedule = self._store.get(cache_key)
            if not schedule or not isinstance(schedule, list):
                return None

        now = dt_util.now()
        dow = now.weekday()
        current_time = now.strftime("%H:%M")

        for day in schedule:
            if day.get("day_of_week") == dow:
                for sp in day.get("switchpoints", []):
                    if sp.get("time_of_day", "") > current_time:
                        heat = sp.get("heat_setpoint")
                        return float(heat) if heat is not None else None
                break
        return None

    def _is_window_open(self) -> bool:
        """Return True if any configured window/door sensor is open."""
        sensors = self._config.get(CONF_WINDOW_SENSORS, [])
        if not sensors:
            self._prev_window_open = False
            return False

        currently_open = any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == "on"
            for entity_id in sensors
        )

        if self._prev_window_open and not currently_open:
            # Transition: open → all closed. Start cooldown, clear open timer.
            self._store.set("window_close_time", dt_util.utcnow().isoformat())
            self._store.set("window_open_time", None)
            _LOGGER.debug("OT %s window closed — cooldown started", self.room_name)
        elif currently_open and not self._prev_window_open:
            # Transition: closed → open. Record open time, reset cooldown.
            self._store.set("window_open_time", dt_util.utcnow().isoformat())
            self._store.set("window_close_time", None)
            _LOGGER.debug("OT %s window opened — detection delay started", self.room_name)

        self._prev_window_open = currently_open
        return currently_open

    def _is_window_cooling_down(self) -> bool:
        """Return True if within the post-close cooldown window."""
        close_time_str = self._store.get("window_close_time")
        if not close_time_str:
            return False

        close_time = dt_util.parse_datetime(str(close_time_str))
        if close_time is None:
            self._store.set("window_close_time", None)
            return False

        delay_minutes = int(
            self._config.get(CONF_WINDOW_DELAY, DEFAULT_WINDOW_DELAY)
        )
        if dt_util.utcnow() < close_time + timedelta(minutes=delay_minutes):
            return True

        # Cooldown expired — clear and resume normal operation
        self._store.set("window_close_time", None)
        _LOGGER.debug("OT %s window cooldown expired — resuming normal setpoint", self.room_name)
        return False

    def _is_window_delay_elapsed(self, window_open: bool) -> bool:
        """Return True if the open-detection delay has elapsed (or is disabled)."""
        if not window_open:
            return False
        open_delay = int(
            self._config.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY)
        )
        if open_delay <= 0:
            return True
        open_time_str = self._store.get("window_open_time")
        if not open_time_str:
            return True  # No timestamp — treat as elapsed (safety fallback)
        open_time = dt_util.parse_datetime(str(open_time_str))
        if open_time is None:
            self._store.set("window_open_time", None)
            return True
        elapsed = dt_util.utcnow() >= open_time + timedelta(minutes=open_delay)
        if elapsed:
            _LOGGER.debug(
                "OT %s window detection delay elapsed — override activating",
                self.room_name,
            )
        return elapsed

    def _is_adjacent_open(self) -> bool:
        """Return True if any configured adjacent-room door sensor is open."""
        sensors = self._config.get(CONF_ADJACENT_SENSORS, [])
        if not sensors:
            return False
        return any(
            (state := self.hass.states.get(entity_id)) is not None
            and state.state == "on"
            for entity_id in sensors
        )

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> OTCoordinatorData:
        """Fetch entity data and run the calculation pipeline."""
        try:
            return await self._do_update()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("OT update failed for %s", self.room_name)
            # Return last data if available, otherwise a dummy
            if self.data is not None:
                return self.data
            raise UpdateFailed(f"OT update failed: {exc}") from exc

    async def _do_update(self) -> OTCoordinatorData:
        """Inner update logic."""
        # 1. Check enabled
        if not self._enabled:
            if self.data is not None:
                return OTCoordinatorData(
                    result=self.data.result,
                    enabled=False,
                    overshoot_count=self.data.overshoot_count,
                    active_thermostat=self.data.active_thermostat,
                    air_temp=self.data.air_temp,
                    last_run=self.data.last_run,
                )
            from .calc import OTCalcResult
            from .mrt import MRTResult

            dummy_mrt = MRTResult(
                mrt=0.0,
                operative_temp=0.0,
                loss_term=0.0,
                solar_term=0.0,
                mrt_unclamped=0.0,
                mrt_clamped=0.0,
                radiation_used=0.0,
                t_out_effective=0.0,
            )
            dummy = OTCalcResult(
                final_setpoint=0.0,
                raw_setpoint=0.0,
                mrt_result=dummy_mrt,
                mrt_correction=0.0,
                coast_prediction=0.0,
                ot_rate=0.0,
                cycles_to_target=999.0,
                dynamic_coast_cycles=0.0,
                desired_ot=0.0,
                skipped=True,
                skip_reason="disabled",
                operative_temp=0.0,
                weather_severity=0.0,
                effective_k=0.0,
            )
            return OTCoordinatorData(
                result=dummy,
                enabled=False,
                overshoot_count=self._store.get("overshoot_count", 0),
            )

        # 1a. Hub config (shared weather/sensor settings)
        hub = self._get_hub_config()

        # 1b. Check holiday mode (always active, hardcoded entity)
        if self._is_holiday_mode():
            _LOGGER.debug("OT %s skipped: holiday mode active", self.room_name)
            return self._skipped_data("holiday mode active")

        # 1c. Check time window
        time_window_active = self._is_within_time_window()
        if not time_window_active:
            _LOGGER.debug(
                "OT %s skipped: outside time window", self.room_name
            )
            return self._skipped_data("outside time window")

        # 2. Automation delay
        delay = self._config.get(CONF_AUTOMATION_DELAY, DEFAULT_AUTOMATION_DELAY)
        if delay and delay > 0:
            await asyncio.sleep(delay)

        # 3. Active thermostat and air temp
        active = self._pick_active_thermostat()
        if not active:
            return self._skipped_data("no thermostat configured")

        air_temp = self._get_float_attr(active, "current_temperature")
        if air_temp is None:
            # Fallback to dedicated air temp sensor
            sensor = self._config.get(CONF_AIR_TEMP_SENSOR, "")
            if sensor:
                air_temp = self._get_float_state(sensor)
        if air_temp is None:
            return self._skipped_data("air temperature unavailable")

        # 4. Desired OT from schedule (NOT temperature attribute, to avoid
        #    reading back our own override)
        primary = self._config.get(CONF_PRIMARY_CLIMATE, "")
        schedule_entity = primary if primary else active
        desired_ot = self._get_scheduled_setpoint(schedule_entity)
        if desired_ot is None:
            return self._skipped_data("schedule setpoint unavailable")

        # Pre-heat detection: evohome may start heating towards the next
        # switchpoint before it activates. Only consider upward transitions
        # (next setpoint higher than current) — evohome never pre-heats for
        # a downward change. Compare the zone's current target against the
        # next switchpoint to confirm pre-heat is actually active, rather
        # than comparing against our own override.
        next_sp = self._get_next_switchpoint_setpoint(schedule_entity)
        if next_sp is not None and next_sp > desired_ot:
            zone_sp = self._get_float_attr(schedule_entity, "temperature")
            if zone_sp is not None and zone_sp >= next_sp:
                _LOGGER.debug(
                    "OT %s pre-heat detected: schedule=%.1f, next=%.1f, zone=%.1f",
                    self.room_name,
                    desired_ot,
                    next_sp,
                    zone_sp,
                )
                desired_ot = next_sp

        # 4b. Occupancy offset — adjusts desired_ot when room is unoccupied
        occupancy_status, occupancy_offset = self._get_occupancy_offset()
        active_offset = 0.0
        if occupancy_status == "unoccupied" and occupancy_offset != 0.0:
            # Blueprint halves the offset: desired_ot += offset / 2
            active_offset = round(occupancy_offset / 2.0, 2)
            desired_ot = desired_ot + active_offset
            _LOGGER.debug(
                "OT %s occupancy offset: %.2f (half of %.2f), desired_ot=%.1f",
                self.room_name, active_offset, occupancy_offset, desired_ot,
            )

        # 5. Weather data — dedicated sensors override weather entity attributes
        weather_id = hub.get(CONF_WEATHER_ENTITY) or self._config.get(CONF_WEATHER_ENTITY, "")

        # Outdoor temperature: dedicated sensor > weather entity attribute
        outdoor_temp_sensor = hub.get(CONF_OUTDOOR_TEMP_SENSOR) or self._config.get(CONF_OUTDOOR_TEMP_SENSOR, "")
        t_outdoor = (
            self._get_float_state(outdoor_temp_sensor)
            if outdoor_temp_sensor
            else None
        )
        if t_outdoor is None:
            t_outdoor = (
                self._get_float_attr(weather_id, "temperature")
                if weather_id
                else None
            )
        if t_outdoor is None:
            t_outdoor = 5.0  # safe fallback

        # Wind speed: dedicated sensor > weather entity attribute
        # Dedicated sensors report m/s; weather entity reports km/h
        wind_sensor = hub.get(CONF_WIND_SPEED_SENSOR) or self._config.get(CONF_WIND_SPEED_SENSOR, "")
        wind_speed: float | None = None
        if wind_sensor:
            raw = self._get_float_state(wind_sensor)
            if raw is not None:
                # Check unit — HA wind_speed sensors can be km/h or m/s
                ws_state = self.hass.states.get(wind_sensor)
                unit = (
                    ws_state.attributes.get("unit_of_measurement", "")
                    if ws_state
                    else ""
                )
                if unit in ("km/h", "km/hr"):
                    wind_speed = raw / 3.6
                elif unit == "mph":
                    wind_speed = raw * 0.44704
                else:
                    # Assume m/s
                    wind_speed = raw
        if wind_speed is None:
            raw = (
                self._get_float_attr(weather_id, "wind_speed")
                if weather_id
                else None
            )
            if raw is not None:
                # HA weather entities always report km/h
                wind_speed = raw / 3.6
            else:
                wind_speed = 0.0

        # Cloud coverage (weather entity only, no dedicated sensor)
        cloud_coverage = (
            self._get_float_attr(weather_id, "cloud_coverage")
            if weather_id
            else None
        )
        if cloud_coverage is None:
            cloud_coverage = 50.0

        # Outdoor humidity: dedicated sensor > weather entity attribute
        humidity_sensor = hub.get(CONF_OUTDOOR_HUMIDITY_SENSOR) or self._config.get(CONF_OUTDOOR_HUMIDITY_SENSOR, "")
        outdoor_humidity = (
            self._get_float_state(humidity_sensor)
            if humidity_sensor
            else None
        )
        if outdoor_humidity is None:
            outdoor_humidity = (
                self._get_float_attr(weather_id, "humidity")
                if weather_id
                else None
            )

        # Apparent temperature (for weather-adaptive k)
        apparent_temp_entity = hub.get(CONF_APPARENT_TEMP_ENTITY) or self._config.get(CONF_APPARENT_TEMP_ENTITY, "")
        apparent_temp: float | None = None
        if apparent_temp_entity:
            apparent_temp = self._get_float_state(apparent_temp_entity)

        # 6. Sun data
        sun_elevation = self._get_float_attr("sun.sun", "elevation") or 0.0
        sun_azimuth = self._get_float_attr("sun.sun", "azimuth") or 180.0

        # 7. Solar sensor (optional)
        solar_sensor = hub.get(CONF_SOLAR_SENSOR) or self._config.get(CONF_SOLAR_SENSOR, "")
        solar_radiation: float | None = None
        if solar_sensor:
            solar_radiation = self._get_float_state(solar_sensor)

        # 8. Orientation
        orientation = self._config.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)
        orientation_azimuth = ORIENTATION_AZIMUTHS.get(orientation, 180.0)

        # 9. Build MRTInputs
        previous_mrt = self._store.get("previous_mrt")
        if previous_mrt is not None:
            previous_mrt = float(previous_mrt)

        mrt_inputs = MRTInputs(
            t_air=air_temp,
            t_outdoor=t_outdoor,
            wind_speed_ms=wind_speed,
            cloud_coverage=cloud_coverage,
            f_out=self.get_number_value("f_out"),
            f_win=self.get_number_value("f_win"),
            k_loss=self.get_number_value("k_loss"),
            k_solar=self.get_number_value("k_solar"),
            orientation_azimuth=orientation_azimuth,
            sun_elevation=sun_elevation,
            sun_azimuth=sun_azimuth,
            thermal_alpha=self.get_number_value("thermal_alpha"),
            solar_radiation=solar_radiation,
            previous_mrt=previous_mrt,
            outdoor_humidity=outdoor_humidity,
        )

        # 10. Build OTCalcInputs
        previous_air_temp = self._store.get("previous_air_temp")
        if previous_air_temp is not None:
            previous_air_temp = float(previous_air_temp)

        previous_operative_temp = self._store.get("previous_operative_temp")
        if previous_operative_temp is not None:
            previous_operative_temp = float(previous_operative_temp)

        previous_setpoint = self._store.get("previous_setpoint")
        if previous_setpoint is not None:
            previous_setpoint = float(previous_setpoint)

        previous_setpoint_time = self._store.get("previous_setpoint_time")
        previous_setpoint_age_s: float | None = None
        if previous_setpoint_time is not None:
            try:
                prev_dt = datetime.fromisoformat(str(previous_setpoint_time))
                previous_setpoint_age_s = (
                    dt_util.utcnow() - prev_dt
                ).total_seconds()
            except (ValueError, TypeError):
                previous_setpoint_age_s = None

        # Current setpoint on the thermostat
        current_setpoint = self._get_float_attr(active, "temperature")
        if current_setpoint is None:
            current_setpoint = desired_ot

        # Min setpoint: configured value or fall back to desired_ot
        min_setpoint_config = self._config.get(CONF_MIN_SETPOINT)
        if min_setpoint_config is not None:
            min_setpoint = float(min_setpoint_config)
        else:
            min_setpoint = desired_ot

        calc_inputs = OTCalcInputs(
            desired_ot=desired_ot,
            current_air_temp=air_temp,
            previous_air_temp=previous_air_temp,
            current_setpoint=current_setpoint,
            mrt_inputs=mrt_inputs,
            correction_gain=self.get_number_value(CONF_CORRECTION_GAIN),
            coast_cycles=self.get_number_value(CONF_COAST_CYCLES),
            max_setpoint=float(
                self._config.get(CONF_MAX_SETPOINT, DEFAULT_MAX_SETPOINT)
            ),
            min_setpoint=min_setpoint,
            max_step=float(self._config.get(CONF_MAX_STEP, DEFAULT_MAX_STEP)),
            smoothing_enabled=bool(
                hub.get(CONF_SMOOTHING_ENABLED, self._config.get(CONF_SMOOTHING_ENABLED, DEFAULT_SMOOTHING_ENABLED))
            ),
            previous_setpoint=previous_setpoint,
            previous_setpoint_age_s=previous_setpoint_age_s,
            previous_operative_temp=previous_operative_temp,
            apparent_temp=apparent_temp,
            weather_k_boost=self.get_number_value(CONF_WEATHER_K_BOOST),
            weather_ref_temp=float(
                hub.get(CONF_WEATHER_REF_TEMP, self._config.get(CONF_WEATHER_REF_TEMP, DEFAULT_WEATHER_REF_TEMP))
            ),
            weather_scale=float(
                hub.get(CONF_WEATHER_SCALE, self._config.get(CONF_WEATHER_SCALE, DEFAULT_WEATHER_SCALE))
            ),
            k_max=self.get_number_value(CONF_K_MAX),
            weather_severity_exponent=float(
                hub.get(CONF_WEATHER_SEVERITY_EXPONENT, self._config.get(CONF_WEATHER_SEVERITY_EXPONENT, DEFAULT_WEATHER_SEVERITY_EXPONENT))
            ),
            k_adaptation_mode=str(
                self._config.get(CONF_K_ADAPTATION_MODE, DEFAULT_K_ADAPTATION_MODE)
            ),
            gradient_scale=float(
                hub.get(CONF_GRADIENT_SCALE, self._config.get(CONF_GRADIENT_SCALE, DEFAULT_GRADIENT_SCALE))
            ),
            gradient_exponent=float(
                hub.get(CONF_GRADIENT_EXPONENT, self._config.get(CONF_GRADIENT_EXPONENT, DEFAULT_GRADIENT_EXPONENT))
            ),
        )

        # 11. Calculate
        result = calculate_setpoint(calc_inputs)

        # 11b. Window/door sensor override
        window_open = self._is_window_open()
        window_delay_elapsed = self._is_window_delay_elapsed(window_open)
        window_cooling = self._is_window_cooling_down()
        window_active = (window_open and window_delay_elapsed) or window_cooling

        # 11c. Adjacent room open check — pause correction, write scheduled setpoint
        adjacent_open = self._is_adjacent_open()

        # 12. Apply override via ramses_cc if not skipped
        if not result.skipped and self._enabled and self._is_global_enabled():
            primary = self._config.get(CONF_PRIMARY_CLIMATE, "")
            override_entity = primary if primary else active
            override_duration = int(
                self._config.get(CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION)
            )
            if window_active:
                setpoint_to_write = float(
                    self._config.get(CONF_WINDOW_SETPOINT, DEFAULT_WINDOW_SETPOINT)
                )
            elif adjacent_open:
                setpoint_to_write = desired_ot
            else:
                setpoint_to_write = result.final_setpoint
            if window_active:
                _LOGGER.debug(
                    "OT %s window override: writing %.1f°C (open=%s, delay_elapsed=%s, cooling=%s)",
                    self.room_name,
                    setpoint_to_write,
                    window_open,
                    window_delay_elapsed,
                    window_cooling,
                )
            elif adjacent_open:
                _LOGGER.debug(
                    "OT %s adjacent open: reverting to scheduled setpoint %.1f°C",
                    self.room_name,
                    setpoint_to_write,
                )
            try:
                await self.hass.services.async_call(
                    "ramses_cc",
                    "set_zone_mode",
                    {
                        "entity_id": override_entity,
                        "setpoint": setpoint_to_write,
                        "mode": "temporary_override",
                        "duration": {"minutes": override_duration},
                    },
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to call ramses_cc.set_zone_mode for %s",
                    self.room_name,
                )

        # 13. Operative temperature from calc result
        operative_temp = result.operative_temp
        mrt = result.mrt_result.mrt

        # MRT baseline: very slow EMA for stable equilibrium estimate
        mrt_baseline_prev = self._store.get("mrt_baseline")
        if mrt_baseline_prev is not None:
            mrt_baseline_prev = float(mrt_baseline_prev)
            alpha_bl = DEFAULT_MRT_BASELINE_ALPHA
            mrt_baseline = round(
                alpha_bl * mrt + (1.0 - alpha_bl) * mrt_baseline_prev, 2
            )
        else:
            mrt_baseline = mrt  # seed with first reading

        # Equilibrium air target: the air temp needed for comfort given
        # the slow-moving MRT baseline.  Factor of 0.5 accounts for
        # thermostat cycling (air settles ~halfway between desired and
        # full setpoint).
        k = result.effective_k
        equilibrium_target = round(
            desired_ot + k * (desired_ot - mrt_baseline) * 0.5, 2
        )

        # 14. Adaptive coast tuning — based on operative temperature
        # Coast only decays after 3 consecutive cycles at/above target,
        # preventing the approach phase from eroding coast before it is used.
        overshoot_count = self._store.get("overshoot_count", 0)
        if not result.skipped and result.ot_rate > 0:
            if operative_temp > desired_ot + 0.2:
                # Overshoot — increase coast and reset stable counter
                new_coast = min(
                    10.0, self.get_number_value(CONF_COAST_CYCLES) + 0.5
                )
                self.set_number_value(CONF_COAST_CYCLES, new_coast)
                self._stable_above_count = 0
                overshoot_count += 1
                self._store.set("overshoot_count", overshoot_count)
            elif operative_temp >= desired_ot:
                # At or near target — only decay after COAST_STABLE_CYCLES_THRESHOLD consecutive cycles (15 min)
                self._stable_above_count += 1
                if self._stable_above_count >= COAST_STABLE_CYCLES_THRESHOLD:
                    new_coast = max(
                        0.0, self.get_number_value(CONF_COAST_CYCLES) - 0.05
                    )
                    self.set_number_value(CONF_COAST_CYCLES, new_coast)
                    self._stable_above_count = 0
            else:
                # Approaching from below — leave coast unchanged
                self._stable_above_count = 0

        # 15. Update store
        self._store.set("previous_air_temp", air_temp)
        self._store.set("previous_operative_temp", result.operative_temp)
        self._store.set("mrt_baseline", mrt_baseline)
        if not result.skipped:
            self._store.set("previous_mrt", result.mrt_result.mrt)
            self._store.set("previous_setpoint", result.final_setpoint)
            self._store.set(
                "previous_setpoint_time", dt_util.utcnow().isoformat()
            )
        await self._store.async_save()

        now = dt_util.utcnow()
        return OTCoordinatorData(
            result=result,
            enabled=self._enabled,
            overshoot_count=overshoot_count,
            active_thermostat=active,
            air_temp=air_temp,
            last_run=now,
            occupancy_status=occupancy_status,
            active_offset=active_offset,
            time_window_active=time_window_active,
            operative_temp=operative_temp,
            equilibrium_target=equilibrium_target,
            mrt_baseline=mrt_baseline,
            weather_severity=result.weather_severity,
            effective_k=result.effective_k,
            window_override_active=window_active,
        )

    def _skipped_data(self, reason: str) -> OTCoordinatorData:
        """Return a skipped OTCoordinatorData with a dummy result."""
        from .mrt import MRTResult

        dummy_mrt = MRTResult(
            mrt=0.0,
            operative_temp=0.0,
            loss_term=0.0,
            solar_term=0.0,
            mrt_unclamped=0.0,
            mrt_clamped=0.0,
            radiation_used=0.0,
            t_out_effective=0.0,
        )
        dummy = OTCalcResult(
            final_setpoint=0.0,
            raw_setpoint=0.0,
            mrt_result=dummy_mrt,
            mrt_correction=0.0,
            coast_prediction=0.0,
            ot_rate=0.0,
            cycles_to_target=999.0,
            dynamic_coast_cycles=0.0,
            desired_ot=0.0,
            skipped=True,
            skip_reason=reason,
            operative_temp=0.0,
            weather_severity=0.0,
            effective_k=0.0,
        )
        _LOGGER.warning("OT %s skipped: %s", self.room_name, reason)
        return OTCoordinatorData(
            result=dummy,
            enabled=self._enabled,
            overshoot_count=self._store.get("overshoot_count", 0),
            last_run=dt_util.utcnow(),
        )
