"""Steady-state operative-temperature model (design note §2–§4, §6).

All functions are pure. Temperatures in °C, areas m², U-values W/m²K,
irradiance W/m², wind m/s, angles degrees.

Sign convention: an *offset* is (air setpoint − OT target). Positive means
the air must run warmer than the schedule to feel like the schedule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

H_I_DEFAULT = 7.7  # inside surface heat-transfer coefficient, W/m²K
GROUND_TEMP_DEFAULT = 10.0


class Boundary(str, Enum):
    """What is on the far side of a surface."""

    OUTSIDE = "outside"
    GROUND = "ground"
    HEATED_ROOM = "heated_room"
    UNHEATED_SPACE = "unheated_space"
    LOFT = "loft"
    ROOF = "roof"


@dataclass(frozen=True)
class Surface:
    """One inside surface of the room."""

    name: str
    area_m2: float
    u_value: float
    boundary: Boundary
    bearing_deg: float | None = None  # outward normal; None for floor/ceiling/internal
    tilt_deg: float = 90.0  # 90 = vertical wall, 0 = horizontal
    glazed: bool = False
    g_value: float = 0.6  # solar transmittance of glazing
    shade_factor: float = 1.0  # 1.0 open, 0.0 fully covered
    adjacent: str | None = None  # room id for HEATED_ROOM / UNHEATED_SPACE


@dataclass(frozen=True)
class Emitter:
    """A radiator or similar, rated at ΔT50."""

    name: str
    output_dt50_w: float
    exponent: float = 1.3


@dataclass(frozen=True)
class Environment:
    """Weather, sun and neighbouring-room state for one evaluation."""

    t_out: float
    wind_ms: float = 0.0
    ghi_wm2: float | None = None  # global horizontal irradiance if measured
    cloud_fraction: float | None = None  # 0..1, used only when ghi is None
    sun_elevation_deg: float = 0.0
    sun_azimuth_deg: float = 180.0
    t_ground: float = GROUND_TEMP_DEFAULT
    adjacent_temps: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelParams:
    """Tunables. Defaults follow the design note."""

    h_i: float = H_I_DEFAULT
    wind_coeff: float = 0.02  # U multiplier per m/s on outside faces
    trust_k: float = 0.8  # fraction of the physical offset applied
    cap_up: float = 1.5
    cap_down: float = 1.5
    step: float = 0.5  # thermostat resolution
    asymmetry_a: float = 0.0  # 0 disables the radiant-asymmetry term
    asymmetry_cap: float = 1.0
    loft_delta: float = 1.0  # loft air = t_out + loft_delta
    unheated_fraction: float = 0.5  # unheated space sits this far from t_out towards t_air
    solar_cap_k: float = 2.0  # cap on the MRT rise from solar gain


@dataclass(frozen=True)
class MRTBreakdown:
    """Steady-state MRT and how it was made."""

    mrt: float
    t_air: float
    solar_k: float  # MRT rise from transmitted solar, already included in mrt
    total_area_m2: float
    surface_temps: Mapping[str, float]


@dataclass(frozen=True)
class Correction:
    """Result of `required_air_temperature`."""

    ot_target: float
    t_air_required: float  # physical answer before trust/caps
    offset_physical: float
    offset_trusted: float
    offset_asymmetry: float
    offset_final: float  # after trust, asymmetry and caps, before rounding
    air_setpoint: float  # ot_target + offset_final, rounded to step
    capped: bool
    mrt_at_setpoint: float
    solar_k: float
    sum_l: float  # Σ L_i, a dimensionless "leakiness" of the room


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def round_to_step(value: float, step: float) -> float:
    """Round to the nearest multiple of `step` (0.5 → thermostat resolution)."""
    if step <= 0:
        return value
    return round(math.floor(value / step + 0.5) * step, 6)


def clear_sky_ghi(sun_elevation_deg: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance, W/m²."""
    if sun_elevation_deg <= 0:
        return 0.0
    s = math.sin(math.radians(sun_elevation_deg))
    return 1098.0 * s * math.exp(-0.057 / s)


def estimate_ghi(env: Environment) -> float:
    """Measured GHI if available, else clear-sky scaled by cloud cover."""
    if env.ghi_wm2 is not None:
        return max(0.0, env.ghi_wm2)
    cloud = 0.5 if env.cloud_fraction is None else min(1.0, max(0.0, env.cloud_fraction))
    return clear_sky_ghi(env.sun_elevation_deg) * (1.0 - 0.75 * cloud)


def irradiance_on_surface(surface: Surface, env: Environment) -> float:
    """Irradiance reaching a surface, W/m², from GHI, sun position and orientation.

    Beam fraction 0.8 of GHI is projected onto the surface; the remaining 0.2 is
    treated as diffuse and half of it reaches a vertical surface. Crude, but it
    gives the right shape: nothing at night, most on the sun-facing face.
    """
    ghi = estimate_ghi(env)
    if ghi <= 0.0 or env.sun_elevation_deg <= 0.0:
        return 0.0
    elev = math.radians(env.sun_elevation_deg)
    tilt = math.radians(surface.tilt_deg)
    # Beam normal irradiance from GHI; floor sin(elev) so low sun does not explode.
    beam_normal = 0.8 * ghi / max(math.sin(elev), 0.2)
    if surface.bearing_deg is None:
        cos_incidence = math.sin(elev) if surface.tilt_deg < 45 else 0.0
    else:
        az_diff = math.radians(env.sun_azimuth_deg - surface.bearing_deg)
        cos_incidence = (
            math.cos(elev) * math.sin(tilt) * math.cos(az_diff)
            + math.sin(elev) * math.cos(tilt)
        )
    beam = beam_normal * max(0.0, cos_incidence)
    diffuse = 0.2 * ghi * (0.5 if surface.tilt_deg >= 45 else 1.0)
    return min(1000.0, beam + diffuse)


def other_side_temperature(
    surface: Surface, env: Environment, t_air: float, params: ModelParams
) -> float:
    """Temperature on the far side of a surface."""
    b = surface.boundary
    if b is Boundary.OUTSIDE or b is Boundary.ROOF:
        return env.t_out
    if b is Boundary.LOFT:
        return env.t_out + params.loft_delta
    if b is Boundary.GROUND:
        return env.t_ground
    if b is Boundary.UNHEATED_SPACE:
        if surface.adjacent and surface.adjacent in env.adjacent_temps:
            return env.adjacent_temps[surface.adjacent]
        return env.t_out + params.unheated_fraction * (t_air - env.t_out)
    # HEATED_ROOM
    if surface.adjacent and surface.adjacent in env.adjacent_temps:
        return env.adjacent_temps[surface.adjacent]
    return t_air


def effective_u(surface: Surface, env: Environment, params: ModelParams) -> float:
    """U-value with the wind factor applied to faces exposed to outside air."""
    if surface.boundary in (Boundary.OUTSIDE, Boundary.ROOF):
        return surface.u_value * (1.0 + params.wind_coeff * max(0.0, env.wind_ms))
    return surface.u_value


def solar_mrt_rise(
    surfaces: list[Surface], env: Environment, params: ModelParams
) -> float:
    """MRT rise, K, from solar transmitted through glazing and absorbed by the room.

    Transmitted power g·I·A spreads over all inside surfaces and lifts their
    temperature by that power / (h_i · ΣA). Capped by `solar_cap_k`.
    """
    total_area = sum(s.area_m2 for s in surfaces)
    if total_area <= 0:
        return 0.0
    power = 0.0
    for s in surfaces:
        if not s.glazed:
            continue
        power += s.g_value * s.shade_factor * irradiance_on_surface(s, env) * s.area_m2
    return min(params.solar_cap_k, power / (params.h_i * total_area))


# ---------------------------------------------------------------------------
# Core model
# ---------------------------------------------------------------------------


def _leak_terms(
    surfaces: list[Surface], env: Environment, t_air_for_other: float, params: ModelParams
) -> tuple[float, float, float]:
    """Return (Σ L_i, Σ L_i·T_other_i, ΣA) with L_i = A_i·U_i/(h_i·ΣA)."""
    total_area = sum(s.area_m2 for s in surfaces)
    if total_area <= 0:
        raise ValueError("room has no surfaces")
    sum_l = 0.0
    sum_lt = 0.0
    for s in surfaces:
        if s.boundary is Boundary.HEATED_ROOM and (
            not s.adjacent or s.adjacent not in env.adjacent_temps
        ):
            continue  # same temperature both sides: no leak
        l_i = s.area_m2 * effective_u(s, env, params) / (params.h_i * total_area)
        sum_l += l_i
        sum_lt += l_i * other_side_temperature(s, env, t_air_for_other, params)
    return sum_l, sum_lt, total_area


def steady_state_mrt(
    surfaces: list[Surface], env: Environment, t_air: float, params: ModelParams | None = None
) -> MRTBreakdown:
    """Steady-state MRT for a room whose air is at `t_air`."""
    p = params or ModelParams()
    total_area = sum(s.area_m2 for s in surfaces)
    if total_area <= 0:
        raise ValueError("room has no surfaces")
    temps: dict[str, float] = {}
    weighted = 0.0
    for s in surfaces:
        u = effective_u(s, env, p)
        t_other = other_side_temperature(s, env, t_air, p)
        t_s = t_air - (u / p.h_i) * (t_air - t_other)
        temps[s.name] = t_s
        weighted += t_s * s.area_m2
    solar = solar_mrt_rise(surfaces, env, p)
    mrt = weighted / total_area + solar
    return MRTBreakdown(mrt=mrt, t_air=t_air, solar_k=solar, total_area_m2=total_area, surface_temps=temps)


def operative_temperature(t_air: float, mrt: float) -> float:
    """ASHRAE 55 operative temperature for still air."""
    return 0.5 * (t_air + mrt)


def required_air_temperature(
    surfaces: list[Surface],
    env: Environment,
    ot_target: float,
    params: ModelParams | None = None,
) -> Correction:
    """Air temperature at which the room's steady-state OT equals `ot_target`.

    Closed form from OT = ½(T_air + MRT_ss) with
    MRT_ss = T_air − Σ L_i (T_air − T_other_i) + S:

        T_air = (OT − ½ Σ L_i T_other_i − ½ S) / (1 − ½ Σ L_i)
    """
    p = params or ModelParams()
    # T_other for heated neighbours defaults to T_air itself, which drops out;
    # use ot_target as the stand-in when computing unheated-space temperatures.
    sum_l, sum_lt, total_area = _leak_terms(surfaces, env, ot_target, p)
    solar = solar_mrt_rise(surfaces, env, p)
    denom = 1.0 - 0.5 * sum_l
    if denom <= 0.1:
        raise ValueError("room leakiness too high for the model (Σ L ≥ 1.8)")
    t_air = (ot_target - 0.5 * sum_lt - 0.5 * solar) / denom

    offset_physical = t_air - ot_target
    offset_trusted = p.trust_k * offset_physical

    # Radiant asymmetry: how much colder the glazing is than the air, weighted
    # by its share of the surfaces. Represents sitting by a cold window.
    asym = 0.0
    if p.asymmetry_a > 0:
        glass_area = sum(s.area_m2 for s in surfaces if s.glazed)
        if glass_area > 0:
            glass_t = 0.0
            for s in surfaces:
                if s.glazed:
                    u = effective_u(s, env, p)
                    glass_t += s.area_m2 * (t_air - (u / p.h_i) * (t_air - other_side_temperature(s, env, t_air, p)))
            glass_t /= glass_area
            asym = min(p.asymmetry_cap, max(0.0, p.asymmetry_a * (glass_area / total_area) * (t_air - glass_t)))

    offset = offset_trusted + asym
    capped = False
    if offset > p.cap_up:
        offset, capped = p.cap_up, True
    elif offset < -p.cap_down:
        offset, capped = -p.cap_down, True

    setpoint = round_to_step(ot_target + offset, p.step)
    mrt_sp = steady_state_mrt(surfaces, env, setpoint, p).mrt
    return Correction(
        ot_target=ot_target,
        t_air_required=t_air,
        offset_physical=offset_physical,
        offset_trusted=offset_trusted,
        offset_asymmetry=asym,
        offset_final=offset,
        air_setpoint=setpoint,
        capped=capped,
        mrt_at_setpoint=mrt_sp,
        solar_k=solar,
        sum_l=sum_l,
    )


# ---------------------------------------------------------------------------
# Emitters, running mean, adaptive comfort
# ---------------------------------------------------------------------------


def radiator_output_w(
    emitters: list[Emitter], t_flow: float, t_air: float, dt_drop: float = 10.0
) -> float:
    """Total emitter output at the running flow temperature.

    P = P50 · ((T_flow − ΔT_drop/2 − T_air) / 50)^n, zero if the mean water
    temperature is not above the room.
    """
    mean_water = t_flow - 0.5 * dt_drop
    dt = mean_water - t_air
    if dt <= 0:
        return 0.0
    return sum(e.output_dt50_w * (dt / 50.0) ** e.exponent for e in emitters)


def running_mean_outdoor(previous: float | None, today_mean: float, alpha: float = 0.8) -> float:
    """EN 16798 running mean: T_rm = α·T_rm,prev + (1−α)·T_yesterday."""
    if previous is None:
        return today_mean
    return alpha * previous + (1.0 - alpha) * today_mean


def adaptive_target_shift(t_rm: float, reference: float = 10.0, slope: float = 0.05) -> float:
    """Downward shift of the OT target in a cold spell; 0 when T_rm ≥ reference."""
    return -slope * max(0.0, reference - t_rm)
