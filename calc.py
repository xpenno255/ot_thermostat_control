"""OT Setpoint calculation pipeline — pure Python, no HA imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .const import K_MODE_OT_REFERENCED, K_MODE_WEATHER_ONLY
from .mrt import MRTInputs, MRTResult, calculate_mrt


@dataclass
class OTCalcInputs:
    """Inputs for the full OT setpoint pipeline."""

    desired_ot: float  # schedule setpoint (operative temp target)
    current_air_temp: Optional[float]  # from active thermostat
    previous_air_temp: Optional[float]  # for rate of rise
    current_setpoint: float  # current thermostat setpoint
    mrt_inputs: MRTInputs  # passed to calculate_mrt()
    correction_gain: float  # k factor
    coast_cycles: float  # lookahead window
    max_setpoint: float
    max_step: float
    smoothing_enabled: bool
    min_setpoint: float  # floor for final setpoint (may be lower than desired_ot)
    previous_setpoint: Optional[float]  # for smoothing and rate limiting
    previous_setpoint_age_s: Optional[float]  # seconds since last setpoint was set
    previous_operative_temp: Optional[float]  # for OT rate of rise
    apparent_temp: Optional[float]  # weather apparent/RealFeel temp
    weather_k_boost: float  # max k boost from weather
    weather_ref_temp: float  # reference temp for severity
    weather_scale: float  # scale factor for severity
    k_max: float  # per-room ceiling for effective k
    weather_severity_exponent: float  # power curve exponent for severity damping
    k_adaptation_mode: str = K_MODE_WEATHER_ONLY   # "weather_only" or "ot_referenced"
    gradient_scale: float = 15.0              # °C gradient at which k reaches k_base
    gradient_exponent: float = 1.5            # power curve for gradient severity


@dataclass
class OTCalcResult:
    """Results from the OT setpoint pipeline."""

    final_setpoint: float
    raw_setpoint: float  # before clamp/smooth
    mrt_result: MRTResult
    mrt_correction: float  # k * (desired_ot - mrt)
    coast_prediction: float
    ot_rate: float  # rate of OT rise degC per cycle
    cycles_to_target: float
    dynamic_coast_cycles: float
    desired_ot: float
    operative_temp: float  # current OT = (air + mrt) / 2
    weather_severity: float  # 0.0-1.0
    effective_k: float  # k after weather adjustment
    skipped: bool = False
    skip_reason: str = ""


def _make_skipped_result(
    inputs: OTCalcInputs, reason: str
) -> OTCalcResult:
    """Build a skipped result, holding the previous setpoint if available."""
    held = inputs.previous_setpoint if inputs.previous_setpoint is not None else inputs.current_setpoint
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
    return OTCalcResult(
        final_setpoint=held,
        raw_setpoint=held,
        mrt_result=dummy_mrt,
        mrt_correction=0.0,
        coast_prediction=0.0,
        ot_rate=0.0,
        cycles_to_target=999.0,
        dynamic_coast_cycles=0.0,
        desired_ot=inputs.desired_ot,
        operative_temp=0.0,
        weather_severity=0.0,
        effective_k=inputs.correction_gain,
        skipped=True,
        skip_reason=reason,
    )


def _weather_adjusted_k(
    k_base: float,
    apparent_temp: Optional[float],
    ref_temp: float,
    scale: float,
    max_boost: float,
    k_max: float,
    exponent: float = 1.5,
) -> tuple[float, float]:
    """Adjust correction gain based on weather severity.

    Returns (k_effective, severity).
    When apparent_temp is None or >= ref_temp, returns (k_base, 0.0).
    """
    if apparent_temp is None or scale <= 0:
        return (k_base, 0.0)
    severity = max(0.0, min(1.0, (ref_temp - apparent_temp) / scale)) ** exponent
    k_effective = min(k_max, k_base + severity * max_boost)
    return (k_effective, severity)


def _ot_referenced_k(
    k_base: float,
    desired_ot: float,
    apparent_temp: Optional[float],
    gradient_scale: float,
    k_max: float,
    exponent: float,
) -> tuple[float, float]:
    """Scale correction gain using gradient between desired_OT and apparent temp.

    k scales from 0 (when apparent_temp >= desired_OT) up to k_base at
    gradient_scale below desired_OT, and continues to k_max beyond that.
    k_base acts as the correction weight at the reference gradient.

    Returns (k_effective, severity) where severity is clamped 0.0-1.0 for reporting.
    """
    if apparent_temp is None or gradient_scale <= 0:
        return (k_base, 0.0)
    gradient = desired_ot - apparent_temp
    if gradient <= 0:
        return (0.0, 0.0)
    raw_severity = (gradient / gradient_scale) ** exponent
    severity_capped = min(1.0, raw_severity)          # for sensor reporting
    k_effective = min(k_max, k_base * raw_severity)   # uncapped so it can reach k_max
    return (k_effective, severity_capped)


def calculate_setpoint(inputs: OTCalcInputs) -> OTCalcResult:
    """Full OT setpoint calculation pipeline.

    Calculates MRT, applies correction gain, intelligent coasting,
    rate limiting, and smoothing to produce a thermostat setpoint.
    """
    # 1. Input validation
    if inputs.current_air_temp is None:
        return _make_skipped_result(inputs, "current_air_temp is None")
    if inputs.mrt_inputs.t_air is None:
        return _make_skipped_result(inputs, "mrt_inputs.t_air is None")

    # 2. MRT calculation
    mrt_result = calculate_mrt(inputs.mrt_inputs)

    # 2b. Current operative temperature
    current_ot = (inputs.current_air_temp + mrt_result.mrt) / 2.0

    # 3. OT rate of rise (per cycle)
    if inputs.previous_operative_temp is not None:
        ot_rate = max(0.0, current_ot - inputs.previous_operative_temp)
    else:
        ot_rate = 0.0

    # 4. Intelligent coast (based on OT, not air temp)
    if ot_rate > 0:
        cycles_to_target = (inputs.desired_ot - current_ot) / ot_rate
    else:
        cycles_to_target = 999.0

    dynamic_coast = max(0.0, inputs.coast_cycles - cycles_to_target)
    coast_prediction = ot_rate * dynamic_coast

    # 5. K adaptation — mode selectable per hub config
    if inputs.k_adaptation_mode == K_MODE_OT_REFERENCED:
        k_effective, weather_severity = _ot_referenced_k(
            k_base=inputs.correction_gain,
            desired_ot=inputs.desired_ot,
            apparent_temp=inputs.apparent_temp,
            gradient_scale=inputs.gradient_scale,
            k_max=inputs.k_max,
            exponent=inputs.gradient_exponent,
        )
    else:
        # Default: weather_only — existing behaviour
        k_effective, weather_severity = _weather_adjusted_k(
            k_base=inputs.correction_gain,
            apparent_temp=inputs.apparent_temp,
            ref_temp=inputs.weather_ref_temp,
            scale=inputs.weather_scale,
            max_boost=inputs.weather_k_boost,
            k_max=inputs.k_max,
            exponent=inputs.weather_severity_exponent,
        )

    # 6. OT formula – correct against MRT (not OT) per v1.4.0
    mrt_correction = k_effective * (
        inputs.desired_ot - mrt_result.mrt
    )
    raw = inputs.desired_ot + mrt_correction - coast_prediction

    # 7. Clamp between min_setpoint and max_setpoint
    setpoint = max(inputs.min_setpoint, min(inputs.max_setpoint, raw))

    # 8. Round to 0.1
    setpoint = round(setpoint, 1)

    raw_setpoint = setpoint  # save pre-rate-limit value

    # 9. Rate limit
    if inputs.previous_setpoint is not None:
        delta = setpoint - inputs.previous_setpoint
        if abs(delta) > inputs.max_step:
            setpoint = inputs.previous_setpoint + inputs.max_step * (
                1.0 if delta > 0 else -1.0
            )

    # 10. Smooth (only if enough time has passed)
    if (
        inputs.smoothing_enabled
        and inputs.previous_setpoint is not None
        and inputs.previous_setpoint_age_s is not None
        and inputs.previous_setpoint_age_s > 180
    ):
        setpoint = 0.6 * setpoint + 0.4 * inputs.previous_setpoint

    # 11. Final clamp and round
    setpoint = max(inputs.min_setpoint, min(inputs.max_setpoint, setpoint))
    setpoint = round(setpoint, 1)

    return OTCalcResult(
        final_setpoint=setpoint,
        raw_setpoint=raw_setpoint,
        mrt_result=mrt_result,
        mrt_correction=round(mrt_correction, 4),
        coast_prediction=round(coast_prediction, 4),
        ot_rate=round(ot_rate, 4),
        cycles_to_target=round(cycles_to_target, 2),
        dynamic_coast_cycles=round(dynamic_coast, 2),
        desired_ot=inputs.desired_ot,
        operative_temp=round(current_ot, 4),
        weather_severity=round(weather_severity, 4),
        effective_k=round(k_effective, 4),
    )
