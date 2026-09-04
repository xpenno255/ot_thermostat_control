"""State machine tests for core.policy (design note §7, §8)."""
from datetime import datetime, timedelta, timezone

import pytest

from core.policy import Action, OverrideMemory, PolicyInputs, PolicyParams, State, ZoneState, decide

T0 = datetime(2026, 1, 15, 7, 0, tzinfo=timezone.utc)


def inputs(**kw) -> PolicyInputs:
    base = dict(
        now=T0,
        room_enabled=True,
        hub_enabled=True,
        holiday_mode=False,
        within_time_window=True,
        shadow_mode=False,
        computed_setpoint=19.5,
        zone=ZoneState(current_setpoint=19.0, schedule_setpoint=19.0),
        memory=OverrideMemory(),
    )
    base.update(kw)
    return PolicyInputs(**base)


def held(setpoint=19.5, minutes_ago=10) -> OverrideMemory:
    return OverrideMemory(last_written_setpoint=setpoint, last_written_at=T0 - timedelta(minutes=minutes_ago))


# --- off / window / no data ------------------------------------------------


def test_disabled_room_does_nothing_when_nothing_held():
    d = decide(inputs(room_enabled=False))
    assert d.state is State.OFF and d.action is Action.NONE


def test_disabled_room_releases_a_held_override_once():
    d = decide(inputs(room_enabled=False, memory=held()))
    assert d.action is Action.RELEASE
    assert d.memory.last_written_at is None
    # second evaluation: nothing left to release
    d2 = decide(inputs(room_enabled=False, memory=d.memory))
    assert d2.action is Action.NONE


def test_hub_disabled_and_holiday_are_off():
    assert decide(inputs(hub_enabled=False)).state is State.OFF
    assert decide(inputs(holiday_mode=True)).state is State.OFF


def test_outside_time_window_releases():
    d = decide(inputs(within_time_window=False, memory=held()))
    assert d.state is State.OUTSIDE_WINDOW and d.action is Action.RELEASE


def test_no_computed_setpoint_releases_and_reports():
    d = decide(inputs(computed_setpoint=None, memory=held()))
    assert d.state is State.NO_DATA and d.action is Action.RELEASE


# --- active writes ----------------------------------------------------------


def test_first_active_cycle_writes():
    d = decide(inputs())
    assert d.state is State.ACTIVE and d.action is Action.WRITE and d.setpoint == 19.5
    assert d.memory.last_written_setpoint == 19.5 and d.memory.last_written_at == T0


def test_unchanged_setpoint_is_not_rewritten_while_override_valid():
    d = decide(inputs(memory=held(19.5, minutes_ago=10), zone=ZoneState(19.5, 19.0)))
    assert d.action is Action.NONE and "unchanged" in d.reason


def test_unchanged_setpoint_is_refreshed_near_expiry():
    d = decide(inputs(memory=held(19.5, minutes_ago=50), zone=ZoneState(19.5, 19.0)))
    assert d.action is Action.WRITE and d.setpoint == 19.5


def test_change_of_one_step_writes_smaller_change_does_not():
    p = PolicyParams(step=0.5)
    m = held(19.5, minutes_ago=10)
    assert decide(inputs(params=p, memory=m, computed_setpoint=20.0, zone=ZoneState(19.5, 19.0))).action is Action.WRITE
    assert decide(inputs(params=p, memory=m, computed_setpoint=19.7, zone=ZoneState(19.5, 19.0))).action is Action.NONE


# --- manual override ---------------------------------------------------------


def test_manual_dial_change_is_respected_then_resumes():
    # We wrote 19.5; zone now says 21.0 and schedule is 19.0 -> someone turned the dial.
    m = held(19.5, minutes_ago=10)
    d = decide(inputs(memory=m, zone=ZoneState(21.0, 19.0)))
    assert d.state is State.MANUAL and d.action is Action.NONE
    assert d.memory.manual_detected_at == T0
    # 90 minutes later, still within the 120-minute hold
    later = inputs(now=T0 + timedelta(minutes=90), memory=d.memory, zone=ZoneState(21.0, 19.0))
    assert decide(later).state is State.MANUAL
    # After the hold expires we resume and write our value again
    much_later = inputs(now=T0 + timedelta(minutes=125), memory=d.memory, zone=ZoneState(21.0, 19.0))
    d3 = decide(much_later)
    assert d3.state is State.ACTIVE and d3.action is Action.WRITE and d3.memory.manual_detected_at is None


def test_manual_hold_ends_at_next_switchpoint():
    m = held(19.5, minutes_ago=10)
    d = decide(inputs(memory=m, zone=ZoneState(21.0, 19.0, next_switchpoint_at=T0 + timedelta(minutes=30))))
    assert d.state is State.MANUAL
    after = inputs(now=T0 + timedelta(minutes=31), memory=d.memory,
                   zone=ZoneState(21.0, 21.0, next_switchpoint_at=T0 + timedelta(minutes=30)))
    # schedule now 21 too, so the zone matches schedule: not manual anymore
    assert decide(after).state is State.ACTIVE


def test_zone_at_schedule_is_not_manual():
    d = decide(inputs(memory=held(19.5), zone=ZoneState(19.0, 19.0)))
    assert d.state is State.ACTIVE


def test_zone_at_our_value_is_not_manual():
    d = decide(inputs(memory=held(19.5), zone=ZoneState(19.5, 19.0)))
    assert d.state is State.ACTIVE


# --- window / door -----------------------------------------------------------


def test_window_open_needs_delay_then_writes_setback():
    p = PolicyParams(window_open_delay_minutes=5, window_setpoint=10.0)
    d = decide(inputs(params=p, any_window_open=True))
    assert d.state is State.ACTIVE  # opened just now; delay not elapsed
    assert d.memory.window_open_since == T0
    d2 = decide(inputs(params=p, any_window_open=True, now=T0 + timedelta(minutes=6), memory=d.memory))
    assert d2.state is State.WINDOW_OPEN and d2.action is Action.WRITE and d2.setpoint == 10.0


def test_window_close_delay_keeps_setback_then_resumes():
    p = PolicyParams(window_close_delay_minutes=15)
    m = OverrideMemory(last_written_setpoint=10.0, last_written_at=T0 - timedelta(minutes=1),
                       window_open_since=T0 - timedelta(minutes=30))
    d = decide(inputs(params=p, any_window_open=False, memory=m, zone=ZoneState(10.0, 19.0)))
    assert d.state is State.WINDOW_OPEN and d.memory.window_closed_at == T0
    d2 = decide(inputs(params=p, any_window_open=False, now=T0 + timedelta(minutes=16), memory=d.memory,
                       zone=ZoneState(10.0, 19.0)))
    assert d2.state is State.ACTIVE and d2.action is Action.WRITE and d2.setpoint == 19.5


def test_adjacent_door_open_writes_plain_schedule():
    d = decide(inputs(any_adjacent_door_open=True))
    assert d.state is State.DOOR_OPEN and d.setpoint == 19.0


def test_window_beats_door():
    m = OverrideMemory(window_open_since=T0 - timedelta(minutes=10))
    d = decide(inputs(any_window_open=True, any_adjacent_door_open=True, memory=m))
    assert d.state is State.WINDOW_OPEN


# --- pre-heat ----------------------------------------------------------------


def test_preheat_release_before_upward_switchpoint():
    z = ZoneState(19.5, 18.0, next_switchpoint_at=T0 + timedelta(minutes=40), next_switchpoint_setpoint=20.0)
    d = decide(inputs(memory=held(19.5), zone=z))
    assert d.state is State.PREHEAT and d.action is Action.RELEASE
    # once released the zone follows its schedule; nothing more to do until the switchpoint passes
    z_released = ZoneState(18.0, 18.0, next_switchpoint_at=z.next_switchpoint_at, next_switchpoint_setpoint=20.0)
    d2 = decide(inputs(memory=d.memory, zone=z_released))
    assert d2.state is State.PREHEAT and d2.action is Action.NONE


def test_no_preheat_for_downward_or_distant_switchpoint():
    down = ZoneState(19.5, 20.0, next_switchpoint_at=T0 + timedelta(minutes=40), next_switchpoint_setpoint=18.0)
    far = ZoneState(19.5, 18.0, next_switchpoint_at=T0 + timedelta(minutes=200), next_switchpoint_setpoint=20.0)
    assert decide(inputs(zone=down, memory=held(19.5))).state is State.ACTIVE
    assert decide(inputs(zone=far, memory=held(19.5))).state is State.ACTIVE


# --- shadow ------------------------------------------------------------------


def test_shadow_never_acts_but_reports_would_write():
    d = decide(inputs(shadow_mode=True))
    assert d.state is State.SHADOW and d.action is Action.NONE and d.would_write == 19.5
    dw = decide(inputs(shadow_mode=True, any_window_open=True, memory=OverrideMemory(window_open_since=T0 - timedelta(minutes=10))))
    assert dw.state is State.SHADOW and dw.would_write == 10.0
    assert dw.memory.last_written_at is None


def test_shadow_still_releases_when_turned_off():
    """Switching a room off while a v1-era override is held should still release it."""
    d = decide(inputs(shadow_mode=True, room_enabled=False, memory=held()))
    assert d.action is Action.RELEASE
