# OT Thermostat Control v2 — design note

Status: draft under review, 2026-09-04. `core/model.py` and `core/geometry.py` are built and tested (§2–§4, §6); coordinator, policy and entities are not.

## 1. What v2 claims

On a cold day the air setpoint in a room rises by the amount needed for the room to *feel* like the
scheduled temperature, and on a mild or sunny day it falls. "Feel" means operative temperature (OT).
The claim is testable: for a room with a globe or surface measurement, predicted MRT should be within
about 0.5 K of measured across a range of outdoor temperatures. Until that test passes for one room,
v2 runs in shadow mode and writes nothing.

Everything v1 did that is not needed for this claim is dropped.

## 2. Comfort definition

Operative temperature for still indoor air (ASHRAE 55, v < 0.2 m/s):

    OT = (T_air + MRT) / 2

One definition, used everywhere: control, sensors, diagnostics. v1 used two.

MRT at the centre of the room is the area-weighted mean of the inside surface temperatures. The
person-by-the-window case is handled by a separate asymmetry term (section 4.3), not by bending MRT.

## 3. The correction, and why it no longer ramps

v1 corrected against the *current* estimated MRT. That deficit is largest when the room is coldest, so
the setpoint spiked at the morning switchpoint and the room overshot once MRT caught up. The ramp,
smoothing and coast logic were patches on that.

v2 corrects against the **steady-state** MRT the room will have once its air is at the target. That
depends on the envelope and the weather, not on how cold the room is now, so the correction is a stable
offset like a heating curve. Same weather, same setpoint, morning or evening.

Each surface facing a colder space has inside temperature

    T_s = T_air − (U / h_i) · (T_air − T_other)        h_i = 7.7 W/m²K

where T_other is outdoor air for external walls, glazing and cold roofs, ground temperature (~10 °C)
for a ground floor, and the neighbouring room's air temperature for internal walls and floors
(read from HA when that room is a zone, else T_air). Surfaces to heated rooms therefore contribute
nothing to the deficit.

Summing over all surfaces:

    MRT_ss = T_air − Σ_i A_i U_i (T_air − T_other,i) / (h_i Σ_i A_i)

Setting OT = target and solving for T_air gives a closed form. Writing
L_i = A_i U_i / (h_i Σ A) for each cold-facing surface:

    T_air = ( OT_target − ½ Σ_i L_i · T_other,i ) / ( 1 − ½ Σ_i L_i )

The **offset** is `T_air − OT_target`. It is then

1. multiplied by a per-room trust factor `k` in [0, 1] (default 0.8, calibration decides),
2. plus the solar and asymmetry terms (section 4),
3. clamped to `[−cap_down, +cap_up]`; defaults set in the hub (±1.5 °C, owner found +2 too much in v1), overridable per room,
4. rounded to the thermostat step (0.5 °C for evohome).

### Worked example: living room, assumed 2.4 m ceilings

Surfaces from `House/rooms/living_room.yaml`: W wall 18.0 m² @1.7, N bay glazing 8.3 @1.5, N wall
remainder 1.6 @1.7, S wall 6.3 @1.7, S window 2.8 @1.4, floor 30.1 @0.8 to ground at 10 °C,
E wall and ceiling to heated rooms. Total surface area ≈ 115 m².

| Outdoor | MRT_ss at 20 °C air | Air needed for OT 20 | Offset (k = 1) |
|---|---|---|---|
| 10 °C | 19.0 | 20.5 | +0.50 |
| 0 °C | 18.4 | 20.9 | +0.86 |
| −5 °C | 18.0 | 21.0 | +1.03 |

These three rows are `tests/test_model.py::test_worked_example_offsets`.

Lived experience in this room says more than that. Two honest reasons the physics might read low:
the person sits near 8 m² of glass (asymmetry, section 4.3), and the open cavity tops and cold floor
may make real U-values worse than the table. Both are exactly what the thermal-camera survey will
settle. The point of the closed form is that it is *checkable*; v1's coefficients were not.

## 4. Adjustments to the base offset

### 4.1 Solar
Solar transmitted through glazing is absorbed by the room's surfaces and lifts MRT. Summed over
glazed openings:

    S = Σ g · f_shade · I_surface · A_glass / (h_i · Σ A)         [K], capped (default 2 K)

`I_surface` comes from measured GHI (else Haurwitz clear-sky scaled by cloud cover) projected onto the
face using sun elevation *and* azimuth against the face bearing (v1 ignored elevation); `g` ≈ 0.6 for
double glazing; `f_shade` 0.3 when curtains or blinds are reported closed. `S` enters the closed form
as a constant, so sunshine lowers the required air temperature without any transient. Implemented in
`core/model.py::solar_mrt_rise`.

### 4.2 Wind
Wind raises the outside surface coefficient. Scale external-wall and glazing U by
`(1 + 0.02 · v_wind)` as v1 did; it is small and only matters on exposed faces.

### 4.3 Radiant asymmetry (optional, per room)
For rooms where glazing is more than about 25% of the external surface (living room, study bay,
kitchen), add

    ΔOT_asym = a · A_glass / Σ A · (T_air − T_glass)

with `a` default 0.5, capped at +1.0 °C. It represents "the side of you facing the window is cold".
Off by default; turned on per room by the room file.

### 4.4 Adaptive comfort (optional, hub-wide)
Running mean outdoor temperature `T_rm` (EN 16798 form, α = 0.8, yesterday's value persisted in the
hub store, exposed as a sensor). Optional target shift

    OT_target' = OT_target − b · max(0, T_rm,ref − T_rm)

with `b` default 0.05 and `T_rm,ref` 10 °C: a two-week cold spell at 0 °C lowers targets by 0.5 °C.
On by default, since it is the standard adaptive-comfort form; hub switch to disable, and the shift is
shown as its own attribute on `target_ot` so it is never invisible.

### 4.5 Occupancy
Kept from v1 as a target offset when unoccupied, applied to `OT_target` before the correction.
Weekday/weekend and time-band structure kept. The "halve the offset" rule is dropped; the number in
config is the number applied.

## 5. Inputs

| Input | Source | Fallback |
|---|---|---|
| Scheduled target | evohome cloud entity `status.setpoints.this_sp_temp`, `next_sp_temp`, `next_sp_from` | ramses `schedule` attribute if present |
| Room air temperature | room file `preferred_air_temperature_entity` (wall stat where bound, else best room sensor) | zone `current_temperature` |
| Adjacent room temperatures | the adjacent zone's air temperature | this room's T_air |
| Outdoor temperature (dry bulb) | `sensor.met_office_weoley_castle_temperature` | `weather.met_office_weoley_castle` attribute, then `weather.home` |
| Wind speed | `weather.met_office_weoley_castle`, converted via its `wind_speed_unit` | `weather.home`, then 0 m/s |
| Cloud cover (fallback only) | `weather.home` (met.no) | 50% |
| Irradiance (global horizontal) | `sensor.global_radiation_openmeteo` (REST, 15-min shortwave) | clear-sky × cloud estimate |
| Sun | `sun.sun` elevation and azimuth | — |
| Flow temperature | `number.boiler_selflowtemp`, **sampled only while `binary_sensor.boiler_dhw_active` is off**, last heating value held; 24 h minimum as sanity check | manual number in hub |
| Geometry and U-values | `House/rooms/<area>.yaml` and `House/house.yaml` | v1 room profile mapped to a synthetic surface list |
| Window/door contacts, adjacent-door contacts | room file | — |
| Global modes | `input_boolean.holiday_mode`, `input_boolean.at_home_mode` | — |

Every fallback that silently changes the answer (outdoor temperature, target) is surfaced in the
room's `status` sensor rather than hidden, as v1 did with its 5 °C default.

### 5.1 Weather sources (survey of the live instance, 2026-09-04)

Four providers are installed: met.no (`weather.home`), AccuWeather, Pirate Weather and the Met Office
site forecast for Weoley Castle. v1 used Pirate Weather plus a template that averaged Met Office
*feels-like* twice with Met Office temperature.

v2 uses **dry-bulb temperature and wind speed separately**, because conduction depends on the real air
temperature and wind enters the model through the surface coefficient. A feels-like or apparent
temperature already contains wind, so using it would count wind twice. All apparent/real-feel inputs
are therefore dropped, along with the two averaged "heating outdoor temperature" templates.

Choice: **Met Office** for temperature and wind (UK site-specific, observation-corrected), **open-meteo**
shortwave radiation for irradiance (the existing REST sensor, 15-minute resolution). Met Office does not
publish cloud cover, but cloud is only needed when irradiance is missing, and then `weather.home`
supplies it. Pirate Weather and AccuWeather are not used by v2 and can stay for other purposes.

Not used, and why: `sensor.total_solar_power_now` is PV output from the open-meteo *solar forecast*
integration mislabelled as W/m²; `sensor.garage_outdoor_motion_sensor_temperature` reads several
degrees high (sheltered or sun-struck); `sensor.outdoor_temperature_running_mean*` and
`sensor.ewma_outdoor_temperature` are fed from feels-like blends and reset or lag, so v2 computes its own
running mean from the dry-bulb source.

Better than any provider: a shaded Zigbee temperature sensor on the north wall. If one is fitted it
becomes the outdoor temperature source and the Met Office value becomes the fallback.

## 5.2 Integration dependencies

Hard (v2 cannot run a room without them):

| Need | Provided by | Notes |
|---|---|---|
| Zone control and TRV/stat readings | **ramses_cc** | `climate.ramses_cc_*`, `ramses_cc.set_zone_mode`, `sensor.thm_22_*`, `sensor.04_*` |
| Scheduled target | **evohome** (cloud) | `status.setpoints.this_sp_temp / next_sp_temp / next_sp_from`; ramses `schedule` attribute is null on most zones so this is effectively required |
| Outdoor temperature and wind | **Met Office** | falls back to met.no `weather.home`, then to a hub manual value with `status` flagging it |
| Sun position | core `sun.sun` | — |
| Room geometry | **House survey YAML** | must be present on the HA host's filesystem (e.g. `/config/ot_house/`), synced from the Homelab repo; not read over the network |

Soft (improve the answer; documented fallback when absent):

| Need | Provided by | Fallback |
|---|---|---|
| Irradiance | open-meteo REST sensor `sensor.global_radiation_openmeteo` | Haurwitz clear-sky × met.no cloud cover |
| Flow temperature, DHW state | **ems-esp** | manual hub value |
| Room air temperature | Govee BLE (via ESPHome Bluetooth proxies), Aqara FP300 and Hue via **ZHA** | zone `current_temperature` from ramses |
| Occupancy, window/door contacts | per-room template aggregates, Aqara contacts via ZHA | feature off for that room |
| Global modes | `input_boolean.holiday_mode`, `input_boolean.at_home_mode` | treated as off |

Not dependencies (present on the instance, not read by v2): Virtual MRT / Indoor Thermal Comfort
(`virtual_mrt_top`, `comfort_tool`), thermal_comfort PMV sensors, Pirate Weather, AccuWeather, the
statistics/EWMA running-mean sensors, the EN 16798 setpoint automations (off), the v0 blueprint
automations (off). v1 did not read Virtual MRT either; both compute MRT themselves. These can be
retired independently of v2.

## 6. What flow temperature is for

Radiator output at the running flow temperature:

    P = P_ΔT50 · ( (T_flow − ΔT_drop/2 − T_air) / 50 ) ^ 1.3

with `P_ΔT50` from Stelrad tables for each emitter in the room file, `ΔT_drop` 10 K default. Used for:

- **Recovery time**: how long the room takes from setback to target, from `P − loss` and a per-room
  thermal mass learned from observed warm-ups (persisted). Drives pre-heat (section 8).
- **Sanity cap**: if `P` at the current flow temperature cannot sustain the requested air temperature
  against the modelled loss, the request is capped and the status says so. Asking for 22 °C from a
  K1 in the utility at 50 °C flow on a −3 °C night is not a correction, it is a wish.

Nothing in the comfort calculation itself depends on flow temperature.

## 7. Write policy (state machine)

Evaluated every cycle. Exactly one state per room; the state is a sensor.

| State | Condition | Action |
|---|---|---|
| `off` | room disabled, hub disabled, or holiday mode | if we hold an override: release once (`follow_schedule`), then nothing |
| `outside_window` | time window enabled and now outside it | release once, then nothing |
| `manual` | zone setpoint ≠ what we last wrote **and** ≠ schedule | leave alone until the next switchpoint or `manual_hold_min` (default 120), then resume |
| `window_open` | contact open longer than `open_delay`, or within `close_delay` of closing | write `window_setpoint` |
| `door_open` | adjacent-room door open | write the plain schedule target (no correction) |
| `preheat` | within computed lead time of an upward switchpoint | write the next target plus its offset |
| `shadow` | room in shadow mode | compute everything, write nothing, expose `would_write` |
| `active` | otherwise | write `T_air` setpoint |

Write rules in `active`/`preheat`/`window_open`/`door_open`:
- write only if the value differs from what we last wrote by ≥ one thermostat step, **or** the
  current override is within 15 minutes of expiring;
- override is `temporary_override` with `duration` = `override_min` (default 60), so if HA dies the
  zone reverts to schedule within the hour;
- values rounded to 0.5 °C. v1 wrote 0.1 steps that the thermostat displayed as 0.5 anyway.

Write frequency drops from every 5 minutes to a few times an hour per room, and to nothing at all
when the answer has not changed. ramses RF traffic drops accordingly.

## 8. Pre-heat

Phase 1 (ship first): `release` to `follow_schedule` `preheat_release_min` (default 60) before an
upward switchpoint, so evohome's own optimum start can act if it is enabled. Costs nothing.

Phase 2: own pre-heat. Lead time = `(target_air − T_air) / warmup_rate`, with `warmup_rate` learned
per room per flow-temperature band from observed heating periods and persisted; bounded 0–90 min.
Replaces phase 1 once it is shown to beat it on a logged comparison.

## 9. Entities

Per room (device "OT <room>"):
- `sensor.<room>_state` — the policy state above, with `reason` and `fallbacks_in_use` attributes
- `sensor.<room>_target_ot` — schedule target after occupancy/adaptive adjustments
- `sensor.<room>_mrt_steady_state`, `sensor.<room>_operative_temperature` (current, from T_air and MRT_ss)
- `sensor.<room>_offset` — before clamp, and attributes for each component (base, solar, asymmetry)
- `sensor.<room>_air_setpoint` — what we write, or would write in shadow
- `sensor.<room>_radiator_output_w` — at the current flow temperature
- `sensor.<room>_last_write` (timestamp), `binary_sensor.<room>_window_override`
- `switch.<room>_enabled`, `switch.<room>_occupancy_enabled`, `select.<room>_mode` (`shadow`/`active`)
- `number.<room>_trust_k`, `number.<room>_cap_up`, `number.<room>_cap_down`

Hub (device "OT Global Settings"):
- `switch.global_enabled`, `sensor.running_mean_outdoor`, `sensor.flow_temperature_used`,
  `sensor.outdoor_temperature_used`, `binary_sensor.dhw_active_seen`

Gone: raw_setpoint, coast_*, cycles_to_target, overshoot_count, mrt_baseline, equilibrium_target,
weather_severity, effective_k, the four envelope numbers and the profile reset button. Envelope
values live in the room file; a `button.<room>_reload_geometry` re-reads it.

## 10. Configuration

Hub: weather entity, outdoor temperature sensor, irradiance sensor, flow-temperature entity,
DHW-active entity, manual flow temperature, adaptive comfort on/off and `b`, house file path.

Room: name, primary (ramses) and backup (evohome) climate entities, room file path (defaults to
`<house_dir>/rooms/<area_id>.yaml`), mode (shadow/active), trust `k`, caps, override minutes,
manual hold minutes, time window, occupancy block, window/door block, asymmetry on/off.

Everything geometric and every sensor entity comes from the room file so that the same survey data
serves other projects. The options flow shows the resolved values read-only, with a reload button.

## 11. Code layout and what survives from v1

```
custom_components/ot_thermostat_control/
  __init__.py        keep (hub/room entry split, reload listeners)
  config_flow.py     keep shape, replace fields
  const.py           trim heavily
  store.py           keep
  geometry.py        NEW  load and validate room/house YAML → Surface list, Emitter list
  model.py           NEW  pure: steady-state MRT, offset, solar, asymmetry, radiator output
  policy.py          NEW  pure: state machine, write decision
  coordinator.py     rewrite: gather inputs → model → policy → one optional service call
  sensor.py etc.     rewrite against the new data class
  diagnostics.py     rewrite
tests/
  test_model.py      closed-form cases, the worked example above, monotonicity in T_out
  test_policy.py     every state transition, write suppression, override refresh
  test_geometry.py   room file parsing, fallbacks, bad input
  fixtures/          a recorded cold day per room for replay
```

Deleted: `calc.py`, `mrt.py`, the coast/overshoot/smoothing/rate-limit logic, the schedule cache,
pre-heat detection, room profile table, `_DEFAULT_MAP`/`get_number_value` key space.

`model.py` and `policy.py` have no HA imports and are the only places the answer is decided. The
coordinator is glue. This is what issues #1–#5 asked for.

## 12. Rollout

1. Build with tests; `model.py` reproduces the worked example.
2. Install alongside v1 as the same domain, bumped config version with a migration that maps v1
   profiles to synthetic surfaces so existing rooms come up in **shadow** mode immediately.
3. Run shadow through October: log `would_write` against v1's `final_setpoint` and the room sensors.
4. First cold clear night: thermal-camera survey, fit U-values into `house.yaml`, rerun the
   comparison.
5. Living room to `active` first (best sensors, clearest complaint), then the rest.
6. Remove v1 code paths.

## 13. Decisions already taken (from discussion 2026-09-03/04)

- Caps default ±1.5 °C, set in the hub, per-room override. `manual` hold 120 min accepted.
- Adaptive comfort on by default. No v1 dashboard entities need preserving.
- Optimum start is enabled on the controller, so phase-1 pre-heat is worthwhile.
- Schedule is the true comfort target; correction runs both ways. No more setting schedules low.
- Steady-state correction; ramp, coast, smoothing removed.
- Flow temperature read live from ems-esp, DHW-gated, manual fallback.
- Running mean outdoor temperature computed and persisted in the hub.
- OT = (T_air + MRT)/2, one definition.
- Room geometry lives in `House/` YAML, not in the integration.

## 14. Open questions

- Is optimum start enabled on the evohome controller? Decides whether phase-1 pre-heat does anything.
- Ground temperature under the suspended floor: 10 °C constant is a guess; a floor-void sensor would fix it.
- Which HR92 is on which radiator for rooms with two (needed only for per-radiator diagnostics).
- Bathroom towel rail and landing are unzoned; they leak into the hall zone model as "heated" neighbours.
- Whether `manual` detection can be made reliable given evohome's own local-override flag on the zone.
