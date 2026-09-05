"""Write policy: decide what, if anything, to write to the zone (design note §7, §8).

Pure functions over plain inputs. The coordinator gathers the inputs from Home
Assistant, calls `decide`, and performs the single action returned. Nothing in
here knows about entities, services or time zones; times are `datetime` values
supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class State(str, Enum):
    OFF = "off"
    OUTSIDE_WINDOW = "outside_window"
    MANUAL = "manual"
    WINDOW_OPEN = "window_open"
    DOOR_OPEN = "door_open"
    PREHEAT = "preheat"
    SHADOW = "shadow"
    ACTIVE = "active"
    NO_DATA = "no_data"


class Action(str, Enum):
    NONE = "none"  # nothing to do
    WRITE = "write"  # set a temporary override to `setpoint`
    RELEASE = "release"  # return the zone to its schedule (follow_schedule)


@dataclass(frozen=True)
class PolicyParams:
    step: float = 0.1  # thermostat resolution; writes below this are suppressed
    override_minutes: int = 60
    refresh_before_expiry_minutes: int = 15
    manual_hold_minutes: int = 120
    window_open_delay_minutes: int = 5
    window_close_delay_minutes: int = 15
    preheat_release_minutes: int = 60  # phase-1 pre-heat: release this long before an upward switchpoint
    window_setpoint: float = 10.0
    switchpoint_grace_minutes: int = 30  # tolerance for schedule-source lag either side of a switchpoint


@dataclass(frozen=True)
class ZoneState:
    """What the zone looks like right now."""

    current_setpoint: float | None  # zone's target as reported by ramses
    schedule_setpoint: float | None  # what the schedule says it should be now
    next_switchpoint_at: datetime | None = None
    next_switchpoint_setpoint: float | None = None


@dataclass(frozen=True)
class OverrideMemory:
    """What we last did, persisted by the coordinator."""

    last_written_setpoint: float | None = None
    last_written_at: datetime | None = None
    manual_detected_at: datetime | None = None
    window_open_since: datetime | None = None
    window_closed_at: datetime | None = None


@dataclass(frozen=True)
class PolicyInputs:
    now: datetime
    room_enabled: bool
    hub_enabled: bool
    holiday_mode: bool
    within_time_window: bool
    shadow_mode: bool
    computed_setpoint: float | None  # from the model; None if it could not be computed
    zone: ZoneState
    memory: OverrideMemory
    any_window_open: bool = False
    any_adjacent_door_open: bool = False
    params: PolicyParams = field(default_factory=PolicyParams)


@dataclass(frozen=True)
class Decision:
    state: State
    action: Action
    setpoint: float | None  # value to write when action is WRITE
    reason: str
    memory: OverrideMemory  # updated memory for the coordinator to persist
    would_write: float | None = None  # in shadow mode: what ACTIVE would have written


# ---------------------------------------------------------------------------


def _holding_override(m: OverrideMemory, now: datetime, p: PolicyParams) -> bool:
    """True if an override we wrote is probably still in force on the zone."""
    if m.last_written_at is None:
        return False
    return now - m.last_written_at < timedelta(minutes=p.override_minutes)


def _override_expiring(m: OverrideMemory, now: datetime, p: PolicyParams) -> bool:
    if m.last_written_at is None:
        return True
    remaining = timedelta(minutes=p.override_minutes) - (now - m.last_written_at)
    return remaining <= timedelta(minutes=p.refresh_before_expiry_minutes)


def _release_or_none(state: State, reason: str, inp: PolicyInputs) -> Decision:
    """Leave the zone alone; release once if we still hold an override."""
    m = inp.memory
    if _holding_override(m, inp.now, inp.params):
        cleared = OverrideMemory(
            last_written_setpoint=None,
            last_written_at=None,
            manual_detected_at=m.manual_detected_at,
            window_open_since=m.window_open_since,
            window_closed_at=m.window_closed_at,
        )
        return Decision(state, Action.RELEASE, None, reason + "; releasing held override", cleared)
    return Decision(state, Action.NONE, None, reason, m)


def _update_window_memory(inp: PolicyInputs) -> OverrideMemory:
    m = inp.memory
    if inp.any_window_open:
        if m.window_open_since is None:
            return OverrideMemory(m.last_written_setpoint, m.last_written_at, m.manual_detected_at, inp.now, None)
        return m
    if m.window_open_since is not None:
        # transition open -> closed: start the close delay
        return OverrideMemory(m.last_written_setpoint, m.last_written_at, m.manual_detected_at, None, inp.now)
    return m


def _window_override_active(m: OverrideMemory, inp: PolicyInputs) -> bool:
    p = inp.params
    if inp.any_window_open and m.window_open_since is not None:
        return inp.now - m.window_open_since >= timedelta(minutes=p.window_open_delay_minutes)
    if not inp.any_window_open and m.window_closed_at is not None:
        return inp.now - m.window_closed_at < timedelta(minutes=p.window_close_delay_minutes)
    return False


def _manual_override(inp: PolicyInputs) -> bool:
    """Zone setpoint differs from both what we wrote and the schedule: someone touched the dial."""
    z, m, p = inp.zone, inp.memory, inp.params
    if z.current_setpoint is None or z.schedule_setpoint is None:
        return False  # without a schedule reference we cannot tell manual from scheduled
    tol = p.step / 2 + 1e-6
    matches_ours = m.last_written_setpoint is not None and abs(z.current_setpoint - m.last_written_setpoint) < tol
    matches_schedule = z.schedule_setpoint is not None and abs(z.current_setpoint - z.schedule_setpoint) < tol
    if matches_ours or matches_schedule:
        return False
    # Around a switchpoint the cloud schedule source lags the zone by minutes: a zone already
    # sitting at the next switchpoint's value is following its schedule, not a hand.
    if (
        z.next_switchpoint_setpoint is not None
        and z.next_switchpoint_at is not None
        and abs(z.current_setpoint - z.next_switchpoint_setpoint) < tol
        and abs((z.next_switchpoint_at - inp.now).total_seconds()) <= p.switchpoint_grace_minutes * 60
    ):
        return False
    # If we never wrote anything, a non-schedule setpoint is still someone else's doing.
    return True


def _write_needed(target: float, m: OverrideMemory, inp: PolicyInputs) -> bool:
    p = inp.params
    if m.last_written_setpoint is None:
        return True
    if abs(target - m.last_written_setpoint) >= p.step - 1e-6:
        return True
    return _override_expiring(m, inp.now, p)


def _write(state: State, target: float, reason: str, inp: PolicyInputs, m: OverrideMemory) -> Decision:
    if not _write_needed(target, m, inp):
        return Decision(state, Action.NONE, None, reason + "; unchanged, override still valid", m)
    new_m = OverrideMemory(target, inp.now, m.manual_detected_at, m.window_open_since, m.window_closed_at)
    return Decision(state, Action.WRITE, target, reason, new_m)


def decide(inp: PolicyInputs) -> Decision:
    """One policy evaluation. Exactly one state; at most one action."""
    p = inp.params

    # 1. Off / holiday / outside window: hands off, releasing anything we hold.
    if not inp.room_enabled or not inp.hub_enabled or inp.holiday_mode:
        why = "room disabled" if not inp.room_enabled else ("hub disabled" if not inp.hub_enabled else "holiday mode")
        return _release_or_none(State.OFF, why, inp)
    if not inp.within_time_window:
        return _release_or_none(State.OUTSIDE_WINDOW, "outside operating window", inp)

    # 2. Manual override detection and hold.
    m = _update_window_memory(inp)
    if _manual_override(inp):
        since = m.manual_detected_at or inp.now
        held_for = inp.now - since
        past_switchpoint = inp.zone.next_switchpoint_at is not None and m.manual_detected_at is not None \
            and inp.zone.next_switchpoint_at <= inp.now
        if held_for < timedelta(minutes=p.manual_hold_minutes) and not past_switchpoint:
            m2 = OverrideMemory(m.last_written_setpoint, m.last_written_at, since, m.window_open_since, m.window_closed_at)
            return Decision(State.MANUAL, Action.NONE, None,
                            f"zone setpoint {inp.zone.current_setpoint} set by hand; holding", m2)
        # hold expired: fall through and resume, forgetting the manual mark and our stale write
        m = OverrideMemory(None, None, None, m.window_open_since, m.window_closed_at)
    elif m.manual_detected_at is not None:
        m = OverrideMemory(m.last_written_setpoint, m.last_written_at, None, m.window_open_since, m.window_closed_at)

    # 3. Window / door overrides beat the model.
    if _window_override_active(m, inp):
        target = p.window_setpoint
        state, reason = State.WINDOW_OPEN, ("window open" if inp.any_window_open else "window recently closed")
        if inp.shadow_mode:
            return Decision(State.SHADOW, Action.NONE, None, reason + " (shadow)", m, would_write=target)
        return _write(state, target, reason, inp, m)

    if inp.any_adjacent_door_open and inp.zone.schedule_setpoint is not None:
        target = inp.zone.schedule_setpoint
        if inp.shadow_mode:
            return Decision(State.SHADOW, Action.NONE, None, "adjacent door open (shadow)", m, would_write=target)
        return _write(State.DOOR_OPEN, target, "adjacent door open; plain schedule target", inp, m)

    # 4. Nothing to correct with.
    if inp.computed_setpoint is None:
        return _release_or_none(State.NO_DATA, "no computed setpoint", inp)

    # 5. Phase-1 pre-heat: release ahead of an upward switchpoint so evohome's optimum start can act.
    z = inp.zone
    if (
        z.next_switchpoint_at is not None
        and z.next_switchpoint_setpoint is not None
        and z.schedule_setpoint is not None
        and z.next_switchpoint_setpoint > z.schedule_setpoint
        and timedelta(0) <= z.next_switchpoint_at - inp.now <= timedelta(minutes=p.preheat_release_minutes)
    ):
        if inp.shadow_mode:
            return Decision(State.SHADOW, Action.NONE, None, "pre-heat release window (shadow)", m, would_write=None)
        return _release_or_none(State.PREHEAT, "upward switchpoint soon; leaving zone to optimum start", inp)

    # 6. Normal operation.
    target = inp.computed_setpoint
    if inp.shadow_mode:
        return Decision(State.SHADOW, Action.NONE, None, "shadow mode", m, would_write=target)
    return _write(State.ACTIVE, target, "model setpoint", inp, m)
