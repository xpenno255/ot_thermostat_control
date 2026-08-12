"""MRT and Operative Temperature calculation — pure Python, no HA imports."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .const import H_C_STILL, H_R


@dataclass
class MRTInputs:
    """Inputs for MRT calculation."""

    t_air: float  # indoor air temperature degC
    t_outdoor: float  # outdoor temperature degC
    wind_speed_ms: float  # wind speed m/s
    cloud_coverage: float  # 0-100 %
    f_out: float
    f_win: float
    k_loss: float
    k_solar: float
    orientation_azimuth: float  # degrees
    sun_elevation: float  # degrees (from sun.sun entity)
    sun_azimuth: float  # degrees
    thermal_alpha: float = 0.3
    solar_radiation: Optional[float] = None  # W/m2, None = use heuristic
    previous_mrt: Optional[float] = None  # for smoothing continuity
    outdoor_humidity: Optional[float] = None  # outdoor RH 0-100%, None = wind-only fallback


@dataclass
class MRTResult:
    """Results from MRT calculation."""

    mrt: float  # final smoothed MRT
    operative_temp: float  # operative temperature
    loss_term: float  # heat loss component
    solar_term: float  # solar gain component
    mrt_unclamped: float
    mrt_clamped: float
    radiation_used: float  # actual radiation value used (sensor or heuristic)
    t_out_effective: float  # after wind chill


def calculate_mrt(inputs: MRTInputs) -> MRTResult:
    """Calculate Mean Radiant Temperature and Operative Temperature.

    Uses room geometry factors, outdoor conditions, and solar position to
    estimate MRT, then derives operative temperature from MRT and air temp.
    """
    # Use raw outdoor temperature for building heat loss calculation.
    # Wind effects on the building envelope are already captured by the
    # (1 + 0.02 * wind_speed) multiplier on the loss term.
    t_out_eff = inputs.t_outdoor

    # Solar radiation
    daylight_factor = max(0.0, min(1.0, (inputs.sun_elevation + 6.0) / 66.0))

    if inputs.solar_radiation is not None:
        rad = min(inputs.solar_radiation, 1300.0)
    else:
        # Heuristic from cloud coverage
        base = 100.0 * daylight_factor
        cloud_factor = max(0.0, 1.0 - (0.9 * inputs.cloud_coverage / 100.0))
        rad = max(0.0, min(1000.0, base * cloud_factor * daylight_factor))

    # Solar incidence factor (cosine of angle between sun and window)
    az_diff = abs(inputs.sun_azimuth - inputs.orientation_azimuth)
    if az_diff > 180:
        az_diff = 360 - az_diff
    azimuth_diff_rad = math.radians(az_diff)

    if az_diff <= 90:
        incidence = min(1.0, math.cos(azimuth_diff_rad) + 0.1)
    else:
        incidence = 0.1  # diffuse baseline

    # MRT formula
    loss = (
        inputs.k_loss
        * (inputs.t_air - t_out_eff)
        * (inputs.f_out + 1.5 * inputs.f_win)
        * (1 + 0.02 * inputs.wind_speed_ms)
    )
    solar = inputs.k_solar * (rad / 400.0) * incidence * inputs.f_win
    mrt_unclamped = inputs.t_air - loss + solar

    # Dynamic clamping
    lower = max(t_out_eff + 2.0, inputs.t_air - 3.0)
    upper = inputs.t_air + 4.0
    mrt_clamped = max(lower, min(upper, mrt_unclamped))

    # Exponential smoothing
    if inputs.previous_mrt is not None:
        mrt_final = (
            (1 - inputs.thermal_alpha) * inputs.previous_mrt
            + inputs.thermal_alpha * mrt_clamped
        )
    else:
        mrt_final = mrt_clamped

    # Operative temperature
    a_factor = H_R / (H_C_STILL + H_R)  # approx 0.603
    operative_temp = (1 - a_factor) * inputs.t_air + a_factor * mrt_final

    mrt_final = round(mrt_final, 2)
    operative_temp = round(operative_temp, 2)

    return MRTResult(
        mrt=mrt_final,
        operative_temp=operative_temp,
        loss_term=round(loss, 4),
        solar_term=round(solar, 4),
        mrt_unclamped=round(mrt_unclamped, 2),
        mrt_clamped=round(mrt_clamped, 2),
        radiation_used=round(rad, 2),
        t_out_effective=round(t_out_eff, 2),
    )
