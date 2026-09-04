"""Closed-form checks for core.model against the design-note worked example."""
import math

import pytest

from core.model import (
    Boundary,
    Emitter,
    Environment,
    ModelParams,
    Surface,
    adaptive_target_shift,
    clear_sky_ghi,
    operative_temperature,
    radiator_output_w,
    required_air_temperature,
    round_to_step,
    running_mean_outdoor,
    steady_state_mrt,
)


def living_room_surfaces() -> list[Surface]:
    """Design note §3 worked example, 2.4 m ceilings, bearings N=0 for simplicity."""
    return [
        Surface("w_wall", 18.0, 1.7, Boundary.OUTSIDE, bearing_deg=270),
        Surface("n_bay_glass", 8.3, 1.5, Boundary.OUTSIDE, bearing_deg=0, glazed=True),
        Surface("n_wall", 1.6, 1.7, Boundary.OUTSIDE, bearing_deg=0),
        Surface("s_wall", 6.3, 1.7, Boundary.OUTSIDE, bearing_deg=180),
        Surface("s_window", 2.78, 1.4, Boundary.OUTSIDE, bearing_deg=180, glazed=True),
        Surface("floor", 30.1, 0.8, Boundary.GROUND, tilt_deg=0.0),
        Surface("e_wall", 18.0, 0.0, Boundary.HEATED_ROOM, adjacent="kitchen"),
        Surface("ceiling", 30.1, 0.0, Boundary.HEATED_ROOM, tilt_deg=0.0, adjacent="bedroom"),
    ]


FULL_TRUST = ModelParams(trust_k=1.0, cap_up=5.0, cap_down=5.0, step=0.01)
NIGHT = dict(sun_elevation_deg=-10.0, cloud_fraction=1.0)


@pytest.mark.parametrize(
    "t_out, expected_offset",
    [(10.0, 0.50), (0.0, 0.86), (-5.0, 1.03)],
)
def test_worked_example_offsets(t_out, expected_offset):
    env = Environment(t_out=t_out, **NIGHT)
    c = required_air_temperature(living_room_surfaces(), env, 20.0, FULL_TRUST)
    assert c.offset_physical == pytest.approx(expected_offset, abs=0.02)
    assert not c.capped


def test_setpoint_reproduces_target_ot():
    """At the unrounded required air temperature, OT equals the target exactly."""
    env = Environment(t_out=0.0, **NIGHT)
    c = required_air_temperature(living_room_surfaces(), env, 20.0, FULL_TRUST)
    mrt = steady_state_mrt(living_room_surfaces(), env, c.t_air_required).mrt
    assert operative_temperature(c.t_air_required, mrt) == pytest.approx(20.0, abs=1e-6)


def test_offset_monotonic_in_outdoor_temperature():
    prev = None
    for t_out in range(-10, 21, 2):
        c = required_air_temperature(living_room_surfaces(), Environment(t_out=t_out, **NIGHT), 20.0, FULL_TRUST)
        if prev is not None:
            assert c.offset_physical <= prev + 1e-9
        prev = c.offset_physical


def test_mild_weather_gives_negative_offset():
    """Warm outside and warm ground: the room feels warmer than its air, so air can drop."""
    env = Environment(t_out=22.0, t_ground=22.0, **NIGHT)
    c = required_air_temperature(living_room_surfaces(), env, 20.0, FULL_TRUST)
    assert c.offset_physical < 0


def test_interior_room_has_zero_offset():
    surfaces = [
        Surface("a", 10.0, 0.0, Boundary.HEATED_ROOM),
        Surface("b", 10.0, 0.0, Boundary.HEATED_ROOM),
        Surface("floor", 12.0, 0.0, Boundary.HEATED_ROOM, tilt_deg=0.0),
    ]
    c = required_air_temperature(surfaces, Environment(t_out=-5.0, **NIGHT), 19.0, FULL_TRUST)
    assert c.offset_physical == pytest.approx(0.0)
    assert c.air_setpoint == pytest.approx(19.0)


def test_heated_neighbour_colder_than_room_adds_offset():
    surfaces = [
        Surface("party", 10.0, 1.5, Boundary.HEATED_ROOM, adjacent="hall"),
        Surface("floor", 10.0, 0.0, Boundary.HEATED_ROOM, tilt_deg=0.0),
    ]
    warm = Environment(t_out=5.0, adjacent_temps={"hall": 20.0}, **NIGHT)
    cold = Environment(t_out=5.0, adjacent_temps={"hall": 15.0}, **NIGHT)
    assert required_air_temperature(surfaces, cold, 20.0, FULL_TRUST).offset_physical > \
        required_air_temperature(surfaces, warm, 20.0, FULL_TRUST).offset_physical


def test_trust_and_caps_and_rounding():
    env = Environment(t_out=-15.0, **NIGHT)
    p = ModelParams(trust_k=0.8, cap_up=1.0, cap_down=1.5, step=0.5)
    c = required_air_temperature(living_room_surfaces(), env, 20.0, p)
    assert c.offset_trusted == pytest.approx(0.8 * c.offset_physical)
    assert c.capped
    assert c.offset_final == 1.0
    assert c.air_setpoint == 21.0


def test_wind_increases_offset():
    calm = Environment(t_out=0.0, wind_ms=0.0, **NIGHT)
    windy = Environment(t_out=0.0, wind_ms=10.0, **NIGHT)
    s = living_room_surfaces()
    assert required_air_temperature(s, windy, 20.0, FULL_TRUST).offset_physical > \
        required_air_temperature(s, calm, 20.0, FULL_TRUST).offset_physical


def test_solar_reduces_offset_on_sunlit_face_only():
    s = living_room_surfaces()
    night = Environment(t_out=5.0, **NIGHT)
    # Low winter sun due south at noon, clear sky, measured GHI.
    sunny_south = Environment(t_out=5.0, ghi_wm2=300.0, sun_elevation_deg=20.0, sun_azimuth_deg=180.0)
    sunny_north = Environment(t_out=5.0, ghi_wm2=300.0, sun_elevation_deg=20.0, sun_azimuth_deg=0.0)
    off_night = required_air_temperature(s, night, 20.0, FULL_TRUST).offset_physical
    off_south = required_air_temperature(s, sunny_south, 20.0, FULL_TRUST).offset_physical
    off_north = required_air_temperature(s, sunny_north, 20.0, FULL_TRUST).offset_physical
    assert off_south < off_night
    # The N bay is three times the S window, so sun from the north helps more.
    assert off_north < off_south
    assert steady_state_mrt(s, sunny_south, 20.0).solar_k > 0


def test_solar_is_capped():
    s = living_room_surfaces()
    blazing = Environment(t_out=5.0, ghi_wm2=1000.0, sun_elevation_deg=45.0, sun_azimuth_deg=0.0)
    p = ModelParams(solar_cap_k=0.7)
    assert steady_state_mrt(s, blazing, 20.0, p).solar_k == pytest.approx(0.7)


def test_asymmetry_term_positive_and_capped():
    env = Environment(t_out=-5.0, **NIGHT)
    p = ModelParams(trust_k=1.0, asymmetry_a=0.5, asymmetry_cap=0.3, cap_up=5.0, step=0.01)
    c = required_air_temperature(living_room_surfaces(), env, 20.0, p)
    assert 0 < c.offset_asymmetry <= 0.3


def test_clear_sky_shape():
    assert clear_sky_ghi(-5) == 0.0
    assert 0 < clear_sky_ghi(10) < clear_sky_ghi(30) < clear_sky_ghi(60) < 1100


def test_round_to_step():
    assert round_to_step(20.24, 0.5) == 20.0
    assert round_to_step(20.25, 0.5) == 20.5
    assert round_to_step(20.74, 0.5) == 20.5
    assert round_to_step(20.3, 0.1) == pytest.approx(20.3)


def test_radiator_output_derates_with_flow_temperature():
    rads = [Emitter("k3_1400", 3486), Emitter("k3_1600", 3984)]
    at_70 = radiator_output_w(rads, 70.0, 20.0)  # mean water 65, ΔT 45
    at_50 = radiator_output_w(rads, 50.0, 20.0)  # mean water 45, ΔT 25
    assert at_70 == pytest.approx(7470 * (45 / 50) ** 1.3, rel=1e-6)
    assert at_50 / 7470 == pytest.approx(0.406, abs=0.005)
    assert radiator_output_w(rads, 24.0, 20.0) == 0.0


def test_running_mean_and_adaptive_shift():
    assert running_mean_outdoor(None, 12.0) == 12.0
    assert running_mean_outdoor(10.0, 0.0) == pytest.approx(8.0)
    t = 10.0
    for _ in range(14):
        t = running_mean_outdoor(t, 0.0)
    assert t < 0.5  # a two-week cold spell converges on the new level
    assert adaptive_target_shift(12.0) == 0.0
    assert adaptive_target_shift(0.0) == pytest.approx(-0.5)


def test_leakiness_guard():
    absurd = [Surface("hole", 10.0, 200.0, Boundary.OUTSIDE)]
    with pytest.raises(ValueError):
        required_air_temperature(absurd, Environment(t_out=0.0, **NIGHT), 20.0, FULL_TRUST)
