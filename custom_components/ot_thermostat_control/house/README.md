# House survey

Shipped inside the integration (`custom_components/ot_thermostat_control/house/`) so HACS deploys it
with the code. Edit here, commit, release. Floor plan images live in the repo at `docs/house/floor_plans/`
and are not deployed.

Machine-readable description of the house, one YAML file per room plus `house.yaml`.
Written for the OT Thermostat Control v2 rebuild but intended to be reused by any project
that needs room geometry, construction, sensors or usage (lighting, energy, presence).

## Conventions

- File name = Home Assistant area id (`living_room.yaml` ↔ area `living_room`).
- Lengths in metres, areas in m², U-values in W/m²K, orientation as compass point or bearing.
- Every measured block carries `measured_on` (ISO date) and `confidence`:
  - `surveyed`  — measured with tape, camera or read from a document.
  - `estimated` — reasoned from plans, photos or typical UK construction.
  - `unknown`   — placeholder, value is a guess and must not be trusted.
- Entity IDs are copied verbatim from HA. Do not rename entities to fit this file.
- `null` means not applicable. A missing key means not yet surveyed.

## Survey checklist (per room)

1. Tape: length, width, ceiling height. Note alcoves and bays separately if large.
2. Each external wall: which compass side, its area (length × height), construction.
3. Each window and external door: width × height of the opening, glazing type, frame, orientation, coverings.
4. What is above, below and on each side (heated room, unheated space, outside, ground).
5. Radiator: type, height × length, position, TRV model. Where the zone's temperature is measured.
6. Compass bearing of the front elevation (phone compass, stand outside, face the house).
7. Photos: one per wall, one per window, one of the radiator. Thermal photos when it is cold.

## Siting a room air-temperature sensor

- Internal wall, never an external one; 1.2–1.5 m for rooms used seated, 0.8–1.0 m for bedrooms.
- At least 1.5 m from any radiator and out of its rising plume; not above a door (warm layer).
- No direct sun, not beside a window, not behind curtains or furniture, not near a door that opens to
  outside or to a cold hall.
- Away from heat sources: TVs, PCs, cookers, presence sensors with their own electronics.
- Same spot every time you replace a sensor, so history stays comparable.

## Default U-values (W/m²K) for `estimated` construction

| Element | Typical value |
|---|---|
| Solid brick wall, 225 mm, uninsulated | 2.0 |
| Cavity wall, unfilled (1930–1980) | 1.5 |
| Cavity wall, filled | 0.5 |
| Modern insulated cavity / timber frame (post 2000) | 0.3 |
| Single glazing | 5.0 |
| Double glazing, pre-2002 air filled | 2.8 |
| Double glazing, low-E argon (2002 onwards) | 1.4 |
| Triple glazing | 1.0 |
| Solid external door | 3.0 |
| Loft, uninsulated | 2.0 |
| Loft, 100 mm insulation | 0.4 |
| Loft, 270 mm insulation | 0.15 |
| Ground floor, solid uninsulated | 0.7 |
| Ground floor, suspended timber | 0.8 |
| Internal wall to unheated space (garage, porch) | 1.5 |

Inside surface temperature for a surface facing outdoors is roughly
`T_air − (U / 7.7) × (T_air − T_out)`. Mean radiant temperature at the centre of the room is
approximately the area-weighted mean of the inside surface temperatures.

## Files

- `house.yaml` — whole-house facts and shared assumptions.
- `rooms/_template.yaml` — annotated schema. Copy to start a new room.
- `rooms/<area_id>.yaml` — one per HA area that is heated.
