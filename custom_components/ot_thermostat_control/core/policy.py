"""Write policy: decide what, if anything, to write to the zone (design note §7, §8).

Pure functions over plain inputs. The coordinator gathers the inputs from Home
Assistant, calls `decide`, and performs the single action returned. Nothing in
here knows about entities, services or time zones; times are `datetime` values
supplied by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    zone_off_setpoint: float = 5.0  # a zone parked at or below this is off (evohome floor), not manual
    # Final absolute bounds on any written target. Applied inside _write so the value
    # remembered as ours is exactly the value transmitted (ownership depends on it).
    zone_setpoint_min: float = 5.0
    zone_setpoint_max: float = 30.0


@dataclass(frozen=True)
class ZoneState:
    """What the zone looks like right now."""

    current_setpoint: float | None  # zone's target as reported by ramses
    schedule_setpoint: float | None  # what the schedule says it should be now
    next_switchpoint_at: datetime | None = None
    next_switchpoint_setpoint: float | None = None
    previous_schedule_setpoint: float | None = None  # value before the last schedule change
    schedule_changed_at: datetime | None = None  # when the schedule source last changed value


@dataclass(frozen=True)
class OverrideMemory:
    """What we last did, persisted by the coordinator."""

    last_written_setpoint: float | None = None
    last_written_at: datetime | None = None
    manual_detected_at: datetime | None = None
    manual_release_at: datetime | None = None  # hold deadline frozen at detection time
    manual_setpoint: float | None = None  # the hand-set value; a different value restarts the hold
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
    """Leave the zone alone; release once if the zone still carries OUR override.

    Releasing blindly would cancel a newer manual override (someone turned the dial,
    or parked the zone at the off floor, after our write). So only send follow_schedule
    when the zone's current setpoint still matches what we wrote; if it differs, the
    override was superseded — relinquish ownership without touching the zone. If the
    zone is unreadable, do nothing and let the temporary override expire on its own.
    """
    m = inp.memory
    if not _holding_override(m, inp.now, inp.params):
        return Decision(state, Action.NONE, None, reason, m)
    cur = inp.zone.current_setpoint
    tol = inp.params.step / 2 + 1e-6
    cleared = replace(m, last_written_setpoint=None, last_written_at=None)
    if cur is not None and m.last_written_setpoint is not None and abs(cur - m.last_written_setpoint) < tol:
        return Decision(state, Action.RELEASE, None, reason + "; releasing held override", cleared)
    if cur is not None:
        return Decision(state, Action.NONE, None, reason + "; zone changed by another hand, leaving alone", cleared)
    return Decision(state, Action.NONE, None, reason + "; zone unreadable, letting override expire", m)


def _update_window_memory(inp: PolicyInputs) -> OverrideMemory:
    m = inp.memory
    if inp.any_window_open:
        if m.window_open_since is None:
            return replace(m, window_open_since=inp.now, window_closed_at=None)
        return m
    if m.window_open_since is not None:
        # transition open -> closed: start the close delay
        return replace(m, window_open_since=None, window_closed_at=inp.now)
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
    # While a manual hold stands, the dial belongs to the user: even a value equal to
    # our own earlier write is their (re)adjustment, not our command echoing back.
    hold_standing = (
        m.manual_detected_at is not None
        and m.manual_release_at is not None
        and inp.now < m.manual_release_at
    )
    # Only an override still in force counts as ours; an expired write's value could
    # equally be a fresh manual selection of the same number.
    matches_ours = (
        not hold_standing
        and m.last_written_setpoint is not None
        and _holding_override(m, inp.now, p)
        and abs(z.current_setpoint - m.last_written_setpoint) < tol
    )
    matches_schedule = z.schedule_setpoint is not None and abs(z.current_setpoint - z.schedule_setpoint) < tol
    if matches_ours or matches_schedule:
        return False
    # Around a switchpoint the cloud schedule source lags the zone by minutes: a zone already
    # sitting at the next switchpoint's value is following its schedule, not a hand. Before the
    # switchpoint the window must also cover evohome's optimum start, which raises the zone to
    # the next value up to preheat_release_minutes early.
    if z.next_switchpoint_setpoint is not None and z.next_switchpoint_at is not None and abs(
        z.current_setpoint - z.next_switchpoint_setpoint
    ) < tol:
        ahead = (z.next_switchpoint_at - inp.now).total_seconds()
        before = max(p.switchpoint_grace_minutes, p.preheat_release_minutes) * 60
        if -p.switchpoint_grace_minutes * 60 <= ahead <= before:
            return False
    # Just after a switchpoint the zone lags the schedule the other way: still holding the
    # previous scheduled value while the source already reports the new one.
    if (
        z.previous_schedule_setpoint is not None
        and z.schedule_changed_at is not None
        and abs(z.current_setpoint - z.previous_schedule_setpoint) < tol
        and timedelta(0) <= inp.now - z.schedule_changed_at <= timedelta(minutes=p.switchpoint_grace_minutes)
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
    p = inp.params
    bounded = min(max(target, p.zone_setpoint_min), p.zone_setpoint_max)
    if bounded != target:
        reason += f"; clamped {target} to zone bounds -> {bounded}"
        target = bounded
    if not _write_needed(target, m, inp):
        return Decision(state, Action.NONE, None, reason + "; unchanged, override still valid", m)
    new_m = replace(m, last_written_setpoint=target, last_written_at=inp.now)
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

    # 2. Zone deliberately off (parked at the evohome floor): hands off, and never "manual".
    if inp.zone.current_setpoint is not None and inp.zone.current_setpoint <= p.zone_off_setpoint + p.step / 2:
        return _release_or_none(State.OFF, f"zone setpoint {inp.zone.current_setpoint} at off floor; leaving alone", inp)

    # 3. Manual override detection and hold. The hold deadline is frozen when the manual
    # change is first seen (min of the hold duration and the then-upcoming switchpoint),
    # so a schedule source that later advertises the following switchpoint cannot extend
    # it. A hand moving the dial to a different value restarts the hold.
    m = _update_window_memory(inp)
    if _manual_override(inp):
        tol = p.step / 2 + 1e-6
        readjusted = m.manual_setpoint is not None and inp.zone.current_setpoint is not None \
            and abs(inp.zone.current_setpoint - m.manual_setpoint) >= tol
        if m.manual_detected_at is None or readjusted:
            since = inp.now
            release_at = since + timedelta(minutes=p.manual_hold_minutes)
            if inp.zone.next_switchpoint_at is not None and inp.now < inp.zone.next_switchpoint_at < release_at:
                release_at = inp.zone.next_switchpoint_at
        else:
            since = m.manual_detected_at
            release_at = m.manual_release_at or (since + timedelta(minutes=p.manual_hold_minutes))
        if inp.now < release_at:
            m2 = replace(m, manual_detected_at=since, manual_release_at=release_at,
                         manual_setpoint=inp.zone.current_setpoint)
            return Decision(State.MANUAL, Action.NONE, None,
                            f"zone setpoint {inp.zone.current_setpoint} set by hand; holding", m2)
        # hold expired: fall through and resume, forgetting the manual mark and our stale write
        m = OverrideMemory(window_open_since=m.window_open_since, window_closed_at=m.window_closed_at)
    elif m.manual_detected_at is not None:
        m = replace(m, manual_detected_at=None, manual_release_at=None, manual_setpoint=None)

    # 4. Window / door overrides beat the model.
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

    # 5. Nothing to correct with.
    if inp.computed_setpoint is None:
        return _release_or_none(State.NO_DATA, "no computed setpoint", inp)

    # 6. Phase-1 pre-heat: release ahead of an upward switchpoint so evohome's optimum start can act.
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

    # 7. Normal operation.
    target = inp.computed_setpoint
    if inp.shadow_mode:
        return Decision(State.SHADOW, Action.NONE, None, "shadow mode", m, would_write=target)
    return _write(State.ACTIVE, target, "model setpoint", inp, m)
