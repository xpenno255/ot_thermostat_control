"""core.geometry against snapshot copies of the House survey files."""
from pathlib import Path

import pytest

from conftest import FIXTURES
from core.geometry import load_all_rooms, load_house, load_room
from core.model import Boundary, Environment, ModelParams, required_air_temperature

HOUSE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ot_thermostat_control" / "house"  # shipped survey


def test_house_constructions_and_bearings():
    h = load_house(FIXTURES / "house.yaml")
    assert h.u_value("external_wall_main") == pytest.approx(1.7)
    assert h.u_value("nonsense") is None
    assert h.bearing("north") == pytest.approx(7.0)
    assert h.bearing("S") == pytest.approx(187.0)
    assert h.front_bearing_deg == pytest.approx(187.0)


def test_living_room_surfaces():
    h = load_house(FIXTURES / "house.yaml")
    r = load_room(FIXTURES / "rooms" / "living_room.yaml", h)
    assert r.room_id == "living_room"
    names = {s.name for s in r.surfaces}
    assert "bay_french_doors_north" in names and "window_south" in names
    # Glazing is netted off the walls it sits in (surveyed 2026-09-04: bay 6.23 m², S window 2.79 m²).
    north_wall = next(s for s in r.surfaces if s.name.startswith("north_outside"))
    bay = next(s for s in r.surfaces if s.name == "bay_french_doors_north")
    assert bay.area_m2 == pytest.approx(6.23, abs=0.01)
    assert north_wall.area_m2 == pytest.approx(7.4 - 6.23, abs=0.05)
    assert r.glazed_area_m2 == pytest.approx(6.23 + 2.79, abs=0.05)
    assert any(s.boundary is Boundary.ROOF for s in r.surfaces)  # the bay's own roof
    assert 110 < r.total_area_m2 < 120
    assert r.zone_id == "01:144444_01"
    assert r.preferred_air_temperature_entity == "sensor.thm_22_066067_temperature"
    assert len(r.emitters) == 2 and sum(e.output_dt50_w for e in r.emitters) == 7470
    floor = next(s for s in r.surfaces if s.boundary is Boundary.GROUND)
    assert floor.tilt_deg == 0.0 and floor.bearing_deg is None
    assert not [w for w in r.warnings if "skipped" in w], r.warnings


def test_living_room_matches_design_note_example():
    h = load_house(FIXTURES / "house.yaml")
    r = load_room(FIXTURES / "rooms" / "living_room.yaml", h)
    env = Environment(t_out=0.0, sun_elevation_deg=-10.0, cloud_fraction=1.0)
    c = required_air_temperature(r.surfaces, env, 20.0, ModelParams(trust_k=1.0, step=0.01, cap_up=5))
    # Surveyed glazing is smaller than the design-note sketch (6.2 vs 8.3 m² bay) but the bay roof
    # is new, so the real room lands close to the sketch's 0.86.
    assert 0.7 < c.offset_physical < 1.0


def test_utility_has_roof_and_garage_surfaces():
    h = load_house(FIXTURES / "house.yaml")
    r = load_room(FIXTURES / "rooms" / "utility.yaml", h)
    kinds = {s.boundary for s in r.surfaces}
    assert Boundary.ROOF in kinds and Boundary.UNHEATED_SPACE in kinds
    garage = next(s for s in r.surfaces if s.boundary is Boundary.UNHEATED_SPACE)
    assert garage.adjacent == "garage"
    # 1980s walls at U 0.6 offset the roof and garage: per unit area the utility
    # ends up close to the living room, not worse. Just require a real deficit.
    env = Environment(t_out=0.0, sun_elevation_deg=-10.0, cloud_fraction=1.0)
    p = ModelParams(trust_k=1.0, step=0.01, cap_up=5)
    c = required_air_temperature(r.surfaces, env, 18.0, p)
    assert 0.5 < c.offset_physical < 1.5
    assert not [w for w in r.warnings if "skipped" in w], r.warnings


def test_window_contacts_split_from_door_contacts(tmp_path):
    h = load_house(FIXTURES / "house.yaml")
    (tmp_path / "rooms").mkdir()
    (tmp_path / "rooms" / "k.yaml").write_text(
        """
room: {id: k, name: K}
geometry: {floor_area_m2: 10, height_assumed_m: 2.4}
boundaries:
  faces:
    - {face: north, boundary: outside, construction: external_wall_main, gross_area_m2: 12}
    - {face: floor, boundary: ground, construction: ground_floor_suspended, gross_area_m2: 10}
openings:
  items:
    - {id: bifold, type: glazed_door, face: north, area_m2: 4.6, construction: glazed_door_alu_dg,
       contact_sensor: [binary_sensor.bifold_a, binary_sensor.bifold_b]}
heating:
  emitters: [{plan_number: 3, type: radiator, output_dt50_w: 1000}]
sensors:
  contacts: [binary_sensor.bifold_a, binary_sensor.bifold_b, binary_sensor.kitchen_door, binary_sensor.01_x_window_open]
"""
    )
    r = load_room(tmp_path / "rooms" / "k.yaml", h)
    assert r.window_contacts == ["binary_sensor.bifold_a", "binary_sensor.bifold_b"]
    assert r.adjacent_door_contacts == ["binary_sensor.kitchen_door"]
    assert r.warnings == []


def test_bad_input_is_reported_not_fatal(tmp_path):
    h = load_house(FIXTURES / "house.yaml")
    (tmp_path / "rooms").mkdir()
    (tmp_path / "rooms" / "bad.yaml").write_text(
        """
room: {id: bad, name: Bad}
boundaries:
  faces:
    - {face: north, boundary: outside, construction: not_a_construction, gross_area_m2: 12}
    - {face: east, boundary: outside, construction: external_wall_main}
    - {face: floor, boundary: heated_room, gross_area_m2: 10}
openings:
  items:
    - {id: w, type: window, face: north}
"""
    )
    r = load_room(tmp_path / "rooms" / "bad.yaml", h)
    assert len(r.surfaces) == 1
    assert any("unknown construction" in w for w in r.warnings)
    assert any("gross_area_m2 missing" in w for w in r.warnings)
    assert any("no area" in w for w in r.warnings)
    assert any("floor_area_m2 missing" in w for w in r.warnings)


def test_shipped_house_loads_every_room_without_skips():
    house, rooms = load_all_rooms(HOUSE_DIR)
    assert len(rooms) == 9
    for r in rooms.values():
        skipped = [w for w in r.warnings if "skipped" in w or "unknown construction" in w]
        assert not skipped, (r.room_id, skipped)
        assert r.total_area_m2 > 0
