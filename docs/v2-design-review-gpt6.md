# OT Thermostat Control v2 — critical design review

Reviewed 2026-09-07 against commit `037d818` (manifest version **2.0.7**). The [design](v2-design.md) describes an earlier implementation; the [handoff](handoff-2026-09-05.md) records **2.0.5**, nine shadow rooms, and subsequent owner decisions. This review examines the checkout, not the live HA instance. File references below are relative to `custom_components/ot_thermostat_control/` unless otherwise stated.

**Recommendation: retain shadow operation until the write-ownership, startup, and stale-input defects below are resolved.** The steady-state correction is a useful, inspectable heating-curve hypothesis. It is not yet a validated estimate of occupant MRT, and successful shadow calculations do not establish safe active operation.

Severity: **High** = resolve before active rollout, or explicitly exclude the affected room/feature; **Medium** = material accuracy, resilience, or maintainability limitation; **Low** = smaller numerical or documentation issue. No critical/unbounded heating fault was demonstrated. Temporary overrides provide a useful eventual return to schedule, conditional on the controller actually accepting their duration.

## What is sound

The separation into pure `core/model.py`, pure `core/policy.py`, and HA adaptation is valuable. For fixed boundary temperatures, `required_air_temperature()` correctly solves the implemented linear steady-state OT equation. The sign is right: colder external surfaces require higher air temperature; solar reduces that requirement. Dry-bulb outdoor temperature is the appropriate conduction input. Trust scaling, visible component offsets, caps, temporary overrides, and a shadow default are sensible protections.

Avoiding a correction proportional to the room's instantaneous warm-up deficit is also defensible: it avoids adding a second aggressive warm-up controller over evohome. That choice does not establish that surfaces are actually at equilibrium during warm-up, however.

Persistence uses temporary files and atomic replacement, with a shared-store save lock. Missing geometry is reported instead of crashing setup. The startup retry has the `@callback` correction described in the handoff. These are worthwhile improvements to retain.

## High-severity findings

### H1. Attempted writes and releases are recorded as successful

**References:** `coordinator.py::_perform()`, `_cycle()`, `_save_memory()`; `core/policy.py::_write()`, `_write_needed()`, `_release_or_none()`.

`decide()` produces memory as though its action succeeded. `_perform()` calls `ramses_cc.set_zone_mode` with `blocking=False`, catches immediate exceptions without returning failure, and even returns silently if the primary entity is absent. `_cycle()` unconditionally persists the proposed memory and publishes `last_write` and `action`.

For an unchanged target, a failed first write can therefore suppress further attempts until the nominal refresh point, normally 45 minutes later. A failed release clears ownership memory, so subsequent disabled cycles do not retry. Errors raised by the asynchronously scheduled service handler are outside `_perform()`'s immediate exception handler. A crash between service execution and persistence creates the opposite ambiguity: the zone may hold an override absent from disk.

**Required direction:** distinguish requested, service-accepted, and zone-observed state. Await service completion, retain/reconcile uncertain ownership, and retry failures with bounded backoff. A successful HA service call alone is not RF acknowledgement. Verify target, mode, and expiry from zone readback where available; expose failures and pending commands. Preserve the expiry fallback for cases where confirmation is impossible.

### H2. Release can cancel a user's newer manual override, including an explicit off setting

**References:** `core/policy.py::_holding_override()`, `_release_or_none()`, `decide()` branches 1–3; `tests/test_policy.py::test_zone_parked_at_off_floor_is_off_not_manual`.

Ownership means only “we wrote within `override_minutes`.” Off, holiday, operating-window, and floor-setpoint checks precede manual detection and do not compare the current override with ours.

Reproduced sequence: OT wrote 20.5 °C ten minutes ago; the user sets 22 °C; disabling OT returns `RELEASE`. With the user setting 5 °C instead, the off-floor branch also returns `RELEASE`. Sending `follow_schedule` can cancel the user's newer action and, in the 5 °C case, restore a higher scheduled target. The existing floor test explicitly endorses this release; it does not prove the intended “leaving alone” behaviour.

**Required direction:** relinquish ownership when a different controller/user supersedes the command. Release only a confirmed or sufficiently well-evidenced OT-owned override. Persist the issued expiry rather than recomputing it from today's configurable duration. Test disable, holiday, and schedule-window exit after manual intervention.

### H3. The first refresh happens before enable/mode restoration

**References:** `__init__.py::_async_setup_room_entry()`; `coordinator.py::__init__()`, `_cycle()`; `switch.py::_RestoringRoomSwitch.async_added_to_hass()`, `OTGlobalEnableSwitch`; `select.py::OTModeSelect.async_added_to_hass()`.

Room setup runs `async_config_entry_first_refresh()` before forwarding entity platforms. At that point `enabled` and `occupancy_enabled` are `True`, while mode comes from config rather than the restored select. A configured-active room that was disabled, or switched to shadow through its select, can write before the restored protection takes effect. A configured-shadow room restored to active has the reverse discrepancy. Restoration does not immediately refresh the coordinator.

The hub similarly starts enabled, and `_cycle()` treats an absent hub as enabled. There is no room dependency barrier ensuring that hub settings and restored global disable are ready. Hub unload removes that authority while rooms remain present. `OTGlobalEnableSwitch.async_turn_off()` does not request room refreshes, so normal release waits for their next polling cycle.

**Required direction:** load authoritative enable/mode state before any actionable refresh; gate writes on completed hub/room initialization; make global disable promptly refresh all rooms. Verify restart and options-reload behaviour with active config, restored shadow, room/global disable, and reversed entry setup order. Test an in-flight refresh during disable as well.

### H4. Stale cloud/weather attributes can authorize indefinite wrong-target writing

**References:** `coordinator.py::_float_attr()`, `_schedule()`, `_ramses_schedule()`, `_maybe_fetch_ramses_schedule()`, `_environment()`, `_cycle()`.

`_float_attr()` ignores the entity's `unknown`/`unavailable` state. `_schedule()` likewise consumes cloud `status.setpoints` whenever attributes remain present. Neither applies source-age validation. A disconnected cloud entity retaining old attributes can prevent the RF fallback entirely. Once its old `next_sp_from` passes, the next target is promoted indefinitely, including beyond subsequent switchpoints.

The six-hour outdoor cache bounds time since **OT read the attribute**, not time since the provider supplied fresh data: every room refresh rewrites the cache timestamp. A stale numeric weather attribute can thus keep the cache perpetually young. Numeric sensor states, irradiance, and neighbour snapshots also have no age limits. `float()` accepts NaN/infinity, and temperature/irradiance units are not normalized or checked.

RF schedules are cached without an expiry policy; `ramses_schedule_saved_at` is never used to decide freshness. A daily request timestamp is recorded before success, so an unavailable service at startup delays another request for a day. Readiness and RF confirmation are not tracked, and “ramses” does not distinguish live from cached data.

**Required direction:** define age, availability, finite-value, unit, and plausible-range rules per source. Use provider observation/report timestamps where possible; unchanged temperature alone is not proof of staleness. Preserve provenance and actual freshness in caches. Declare how long an old schedule may authorize writes and expose that degraded state. Retry failed schedule fetches without waiting a full day.

### H5. Manual recognition and write suppression are not a complete ownership state machine

**References:** `core/policy.py::_manual_override()`, `_write_needed()`, `decide()`; `coordinator.py::_schedule()`.

Several reproduced or directly traceable cases break the intended contract:

| Trigger | Current result | Consequence |
|---|---|---|
| Zone returns to schedule ten minutes after our write, desired correction unchanged | `ACTIVE / NONE` | Suppression compares against our remembered value, not the zone; correction is absent until refresh. A user's cancellation is also indistinguishable from controller reversion. |
| No current zone target, but schedule/model available | `ACTIVE / WRITE` | The writer operates without knowing whether the zone is manually overridden or off. |
| Manual target remains 22 °C across a switchpoint; cloud now advertises the following future switchpoint | Still `MANUAL` | Hold expiry uses the current `next_switchpoint_at`, not the deadline captured when the manual change was detected. The promised next-switchpoint release is missed. |
| Someone selects a value equal to an old OT write after that write expired | Treated as ours | `_manual_override()` compares against `last_written_setpoint` without checking its age. |
| User changes the target again during a manual hold | Original timer retained | A fresh manual action near the end of 120 minutes can be overwritten almost immediately. |

The 30-minute switchpoint grace and up-to-60-minute optimum-start exception also cannot distinguish a real manual selection of the same numeric value. They are useful lag heuristics, not evidence of authorship. The next-switchpoint unit test changes the schedule to match the manual value, so it does not exercise the moving-deadline case above.

**Required direction:** track an explicit hold deadline, observed override mode/expiry, and command acknowledgement state. Use value matching as one clue. Test sequences over time, including delayed echoes of consecutive OT writes, cancellation, repeated manual adjustments, and cloud/RF ordering in both directions. Define what permanent manual overrides should mean rather than assuming all are reclaimable after 120 minutes.

### H6. The “Operative Temperature” sensor is internally inconsistent and unsuitable for validation

**References:** `coordinator.py::_cycle()`; `core/model.py::required_air_temperature()`, `steady_state_mrt()`; `sensor.py::ROOM_SENSORS`.

The coordinator publishes `operative_temperature(measured_air, correction.mrt_at_setpoint)`. This mixes current air with the surface estimate for a different, hypothetical air temperature. With the shipped living-room geometry, target 20 °C, outside 0 °C, ground 10 °C, no sun/wind, full trust, and current air 16 °C, this gives about **17.59 °C**. Evaluating the same steady-state surface model at 16 °C air gives **15.40 °C** OT. Neither is an actual measurement of the warming room; their 2.19 K disagreement is a software semantic error before considering thermal lag.

`mrt_steady_state` can legitimately represent MRT **at the requested setpoint**, provided its name/attributes say so. A current-condition estimate must use current air and carry its equilibrium assumption. It must remain distinct from independently measured MRT/OT. Otherwise a dashboard can appear to validate the model largely because the target was used to construct the displayed comfort value.

### H7. Representative HA air temperature does not establish representative evohome control

**References:** `coordinator.py::_air_temperature()`, `_cycle()`, `_perform()`; `house/rooms/{study,hall,bedroom,bedroom_2,max_room,utility}.yaml`.

The required air setpoint does not depend on measured room air. That is intentional for this feed-forward design. But `_perform()` writes that target to evohome, which continues regulating against its bound stat/HR92. Selecting a new `preferred_air_temperature_entity` only changes diagnostics and potential neighbour inputs; it does not rebind the zone sensor or compensate for its bias.

This is substantial for the six HR92-sensed rooms. The study survey records a 2 K difference between HR92 and Govee in one afternoon observation, exceeding its predicted cold-night correction. That single observation is not a usable calibration constant, but it disproves assuming the sensors always represent the same temperature. Hall and Max Room survey prose promises height/heating-state corrections that do not exist in `_air_temperature()`.

**Activation gate:** establish how the actual evohome control sensor tracks representative occupied-zone air during heating, cooling, and sun. Prefer a correctly sited bound sensor where appropriate; do not inflate U-values to compensate for sensor bias. Living room, kitchen, and Studio have the clearest sensor/control correspondence, although their locations still need validation.

## Model soundness and medium-severity findings

### M1. MRT is a useful proxy here, not a geometric or transient solution

**References:** `core/model.py::steady_state_mrt()`, `required_air_temperature()`; design §§2–4.

For a person at a particular position, a simplified radiative MRT is `[(Σ F_i (T_si + 273.15)^4)^(1/4)] − 273.15`, with view factors summing to one. Surface area fractions generally differ from these view factors even at a room's centre. Linearizing the fourth power for modest indoor temperature differences is reasonable; equating view factors to room area fractions is the more consequential approximation for a long room or a seat near a bay. EnergyPlus explicitly distinguishes enclosure-average and occupant-location angle-factor MRT methods. [EnergyPlus Engineering Reference](https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v22.1.0/EngineeringReference.pdf)

Likewise `(air + MRT)/2` is a defensible still-air comfort approximation, not a complete comfort model for draughts, sleeping under bedding, cooking, or radiant asymmetry. The house survey explicitly records MEV, stairwell flow, and bedside use. Occupant clothing/activity need not become controller inputs, but the claim should be limited accordingly.

The surface relation `T_si = T_air − U R_si (T_air − T_other)` is consistent with a steady one-dimensional resistance model when U and `R_si=1/7.7` use compatible boundary-film assumptions. It is not a transient surface prediction. A single indoor coefficient across walls, ceilings, and cold floors ignores heat-flow direction and local convection. Warm radiators, furnishings, and their radiation exchange with occupants/surfaces are absent. Living-room radiators total 7,470 W at ΔT50, with one behind a sofa: occupied-position radiation cannot be inferred from cold-envelope area alone.

Treat this as an empirical, physically motivated equilibrium approximation. Measure its error before adding detailed dynamics. Do not restore v1's ramp/coast machinery merely because transient MRT differs from equilibrium.

### M2. Solar geometry is improved, but the gain-to-MRT conversion remains unvalidated

**References:** `core/model.py::estimate_ghi()`, `irradiance_on_surface()`, `solar_mrt_rise()`; `core/geometry.py::load_room()`.

The beam incidence calculation correctly uses elevation and azimuth. Physically, plane-of-surface beam irradiance comes from DNI times the incidence cosine. The missing information is the direct/diffuse decomposition: a fixed 80% beam allocation cannot represent both clear and overcast conditions. [Sandia PVPMC: POA beam](https://pvpmc.sandia.gov/modeling-guide/1-weather-design-inputs/plane-of-array-poa-irradiance/calculating-poa-irradiance/poa-beam/)

The low-sun denominator floor and 1,000 W/m² surface cap prevent numerical explosion but do not validate the estimate. Obstructions, reveals, ground reflection, angle-dependent glazing transmission, and separate canted-bay pane bearings are missing. The living-room and study pane surveys are collapsed to one N/S face. Areas including frames generally receive full glazing transmission; Utility partially addresses this using a lower g-value for its part-glazed door.

`g I A/(h_i ΣA)` has units of kelvin, but dimensional correctness is insufficient. It assumes absorbed solar is distributed over all surfaces with an immediate effective heat-transfer path. Surface storage, redistribution, and convective heat transfer to air are not solved; direct sunlight on occupants is absent. A 2 K MRT cap still allows roughly a degree of air-target reduction before trust scaling. Fast cloud changes can reverse that reduction well before the room releases stored heat.

`covering_closed_at_night` is also applied as a **permanent** 0.3 solar multiplier when loading geometry. There is no time or cover-entity read, and no night-time insulating/radiant effect. Shipped coverings are null, making this a latent feature defect rather than an explanation of current offsets.

Validate negative corrections on sunny and overcast afternoons separately. The open-meteo REST entity is provider-modelled radiation, not evidence of an on-site irradiance measurement. A plausible negative `would_write` is only a sign check.

### M3. U-values, wind and ground assumptions risk absorbing unrelated errors

**References:** `core/model.py::effective_u()`, `other_side_temperature()`; `house/house.yaml::constructions`; design §12.

Scaling the whole U-value by `1 + 0.02 v` is an inherited empirical rule. Wind principally changes outside-film resistance; it should not proportionally change the entire construction resistance irrespective of insulation. Every outside/roof face gets the same factor, despite the design's “exposed faces” qualification. Draughts and thermal bypass need separate evidence; folding them into U can make a fit look better while mispredicting surface temperature.

Both slab and suspended floor use U=0.8 against constant 10 °C ground. Suspended-floor void air is not necessarily deep-ground temperature, and ground-coupled slab behaviour has seasonal and geometric dependence. Loft is outdoor+1 K and the unknown garage is halfway between room and outdoors. These are reasonable starting guesses, not measured boundaries.

A thermal camera can identify cold surfaces and support this model's calibration, but one clear-night image does not uniquely identify U. Air/surface temperatures, emissivity/reflections, recent heating and solar history, film coefficients, and boundary temperatures confound that inference. In particular, check glazing measurements against an appropriate reference method. Fit on stable periods, use multiple conditions, and reserve separate days/locations for validation. The numerical U entries marked `surveyed` also need their own provenance; a surveyed construction does not imply measured heat transmission.

### M4. Heated-neighbour effects are discarded by geometry loading

**References:** `core/geometry.py::load_room()`; `core/model.py::_leak_terms()`; `tests/test_model.py::test_heated_neighbour_colder_than_room_adds_offset`.

`load_room()` assigns **U=0** to every `HEATED_ROOM` surface, regardless of construction. Thus the coordinator's adjacent temperatures cannot affect these surfaces. The pure model test uses a hand-built surface at U=1.5; it does not cover the deployed loader. “Heated” neighbours may be in setback or disabled, so the assumption fails especially for bedrooms with different schedules.

Neighbour descriptions such as `kitchen, hall` are reduced to the first token, without splitting areas. The fallback for an unknown heated neighbour is same-temperature air without a diagnostic. Either explicitly retain an adiabatic-neighbour model and remove the misleading feature claim, or specify partition conductance and meaningful area splits. Do not build a coupled whole-house solver before measurements justify it.

### M5. Adaptive reduction is an owner-selected heuristic; its readiness gate does not measure full days

**References:** `core/model.py::adaptive_target_shift()`; `hub.py::sample_outdoor()`, `running_mean_ready`; handoff “Decisions taken”.

The α=0.8 daily exponential recurrence is reasonable. The separate rule `−0.05 max(0,10−T_rm)` is not established as a standard heating-season setpoint correction merely by borrowing a running-mean form. The adaptive comfort model was developed for naturally ventilated buildings; that does not validate this particular downward shift in a radiator-heated house. [UC Berkeley CBE: adaptive comfort context](https://cbe.berkeley.edu/research-category/facade-systems/natural-ventilation/)

This is cause to correct the design's standards claim and test the effect, not to disregard the owner's accepted default. At 0 °C running mean the −0.5 K shift can cancel much of the physical correction. Keep it separately visible and evaluate its benefit independently of U/trust calibration.

The hub counts any sampled date rolled over as a completed day, including a first sample at 23:59, and does not require coverage. After a multi-day outage it folds the old partial day once and remains ready indefinitely. Every room contributes samples at its own refresh frequency, so retries, manual refreshes, room outages and caches influence temporal weighting. Use one hub sampling schedule, coverage/age tracking, and time weighting or clearly defined observation intervals.

### M6. Missing outdoor data can bypass the intended no-data policy through an exception

**References:** `coordinator.py::_cycle()`, `_async_update_data()`.

Once the hub running mean is ready, complete loss of outdoor inputs/cache leaves `d.running_mean_outdoor=None`, yet `_cycle()` passes it to `adaptive_target_shift()` if adaptive is enabled. The comparison raises `TypeError` before policy runs. `_async_update_data()` catches that and returns the old snapshot, making the update appear successful. A held override is not released through the intended no-data branch; old active/action/last-run values remain displayed until something recovers or the override expires.

The general “return old data on any exception” path has the same observability problem for malformed schedules, nonfinite values, or bad persisted fields. Publish a fresh explicit failure state and distinguish last-good data from current validity. Decide release behaviour using verified ownership, even when model calculation fails.

### M7. Shadow rollback and contact semantics need an explicit contract

**References:** `core/policy.py::decide()`, `_update_window_memory()`; `coordinator.py::_any_on()`, `_cycle()`; `core/geometry.py::load_room()`.

Switching active → shadow returns `NONE` and leaves the existing override until expiry. Conversely shadow can send `RELEASE` through off/no-data branches before reaching its shadow guard; the tests explicitly allow this. Those may be intentional cleanup choices, but “shadow writes nothing” is not an adequate operational description. Define rollback as either immediate verified release or expiry, and expose pending residual control.

An unavailable contact becomes false through `_any_on()`, so loss of an open contact looks like closure and eventually resumes heating. Polling observes transitions only every configured interval; it cannot distinguish a brief closure/reopen between cycles. Close delay applies even to an opening too brief to have reached open delay, and window memory is not updated while disabled/outside-window. Reopening during a close delay starts a fresh open delay and can briefly restore the high target.

All inferred `*_window_open` sensors are deliberately excluded. Loading all nine surveys yields **only the kitchen bifold as a physical window contact**, and only the kitchen–hall contact as an adjacent door. Do not advertise protection in the other rooms. The shadow window binary sensor follows raw contact-open status even before open delay, and becomes false during close delay despite a retained shadow setback.

The door branch writes the unadjusted schedule before preheat; an open kitchen door therefore removes occupancy/adaptive offsets and can prevent optimum-start release. Manual mode also outranks window setback. These priorities require explicit expected-behaviour tests, not just tests that each individual state is reachable.

### M8. Capability, settings, and geometry validation have gaps

**References:** `config_flow.py::async_step_room()`, `room_schema()`; `coordinator.py::__init__()`, `set_tunable()`; `core/geometry.py::load_room()`.

Room creation does not reject duplicate `room_id` or primary climate entity. Two entries can issue conflicting commands to the same zone with independent memory; the room dictionary silently replaces one coordinator for neighbour lookup. Validate identity and match configured climate/room IDs against the surveyed mapping before enabling writes.

Tunables have another authority layer: persisted number values override room options and hub defaults. Once a cap or trust number was changed, later options edits can appear accepted while the old stored value still wins. Clearing optional fields also needs care because merged entry data can restore a value omitted from options. Show resolved values and their source, with one explicit reset/inheritance mechanism.

Geometry warnings do not inhibit activation. Unknown cold constructions can be skipped, producing a deceptively small correction from an incomplete enclosure. Validation does not require positive finite areas/U-values, valid solar parameters, enclosure closure, or opening-to-surface identity. Openings are subtracted from the first non-heated face with that label, which is ambiguous for split walls; aliases normalize bearings but not the subtraction keys. Rooflights are listed as glazed but loaded with default vertical tilt. These are latent parser defects; all nine shipped files currently load without warnings.

## Lower-severity numerical issues and missing scope

**L1 — The unheated-space inverse is approximate.** `required_air_temperature()` evaluates the garage fallback at `ot_target`, although it depends on the unknown air temperature. For `T_other=a T_air+b`, the exact leak contribution is `L(1−a)` with constant `Lb`. On the shipped Utility at outside 0 °C, target 20 °C and no sun/wind, the unrounded answer produces OT=20.005545 °C instead of 20 °C. Small today, but the “exact closed form” invariant should cover this boundary type.

**M9 — Capacity and recovery are diagnostics/promises, not implemented safeguards.** `radiator_output_w()` implements the stated emitter derating formula, but `_cycle()` never compares it with room heat loss or caps an unsustainable setpoint. Thermal mass learning, warm-up-rate persistence and phase-2 preheat are absent; deferral of phase 2 is deliberate. The design's phase-1 capacity claim is not delivered either. Infiltration/MEV losses are not computed. Do not imply a capacity guarantee from the output sensor.

`hub.py::sample_flow_temp()` accepts a reading when DHW is **unknown**, because `not None` is true. It retains the last flow value indefinitely, with no age or 24-hour-minimum sanity check. A `number` such as the configured boiler flow setting is not necessarily actual radiator inlet temperature; actual return drop and valve opening are unknown. Treat radiator output as estimated available capacity at assumed temperatures, not measured delivered heat. These are medium diagnostic limitations now and would become activation blockers for a future capacity/preheat controller.

**M10 — There is no final absolute target bound.** Correction caps apply around the occupancy/adaptive-adjusted target, not around the original schedule. Setbacks can go below the controller's floor, and adjusted high schedules can exceed its range. Window/door paths bypass model rounding/clamps. The UI permits a 30-minute polling interval with a 20-minute override, guaranteeing expiry gaps, and permits three-hour overrides despite the design's within-an-hour failure claim. Validate final commands and cross-field timing constraints against the actual zone capability.

**L2 — Accepted decisions and obsolete promises are mixed together.** Keep the handoff's accepted **0.1 °C** write step; the older design's 0.5 °C is not a requirement to restore. Verify actual RF/controller readback granularity because a 0.05 °C manual-match tolerance depends on it. With 0.1 °C steps there is no additional minimum write interval or hysteresis, so weather near rounding thresholds can cause a write every cycle. Stable targets still refresh every 45 minutes at default settings, rather than traffic falling to zero indefinitely.

Other stale claims: migration does not create synthetic v1 surfaces; geometry is required. The room options UI does not expose a geometry-backed resolved mapping. House environment YAML still names v1 weather inputs but is ignored by the coordinator; the handoff's hub weather source, met.no, determines live wind rather than a separate Met Office wind chain. `entity.py` still reports model version 2.0.0. Update these descriptions after resolving behaviour so operators know what actually runs.

## Evidence reviewed and activation gates

I read the design, handoff, core implementation, coordinator, hub, setup/restoration, store, configuration/migration/entity layers, tests, and all nine room surveys plus shared constructions. All nine shipped geometries load without warnings. At outside 0 °C, ground 10 °C, no solar/wind, OT target 20 °C and full trust, their physical offsets range from **+0.352 K (Max Room)** to **+0.899 K (Bedroom)**; living room is **+0.816 K**, kitchen **+0.401 K**, study **+0.711 K**. These are model outputs, not observed comfort improvements. The design's worked-example geometry is an older sketch, not the current living-room survey.

Validation performed without code changes: **51 pure model/policy/geometry tests passed**, with plugin autoload disabled and pytest caching/bytecode writing disabled. The unknown `asyncio_mode` warning is expected with those plugins disabled. A normal full HA pytest invocation produced no output and was interrupted; **HA integration tests were not verified in this review**. In-memory probes reproduced H2/H5 and the H6/L1 numerical examples. Existing fixtures contain survey YAML, not the recorded cold-day replay datasets promised by the design.

Before activation, require both operational and physical evidence:

| Gate | Evidence required |
|---|---|
| Write ownership and recovery | Automated sequential tests for service exceptions, delayed/absent echoes, failed release, manual takeover/off, moved switchpoints, expired memory, and restart during a command. No false success or cancellation of a newer user override. |
| Startup and rollback | HA lifecycle tests with restored disabled/shadow states and hub unavailable/late. Demonstrate global disable and active→shadow behaviour, plus actual controller reversion after HA is stopped. Confirm the accepted 0.1 °C target and temporary duration over RF. |
| Input degradation | Exercise retained attributes on unavailable entities, stale cloud beyond multiple switchpoints, aged RF/outdoor caches, missing DHW gate/contact/sun, and nonfinite values. Every degraded case must have a visible source/age and a defined write outcome. |
| Sensor/control correspondence | Site and compare independent air sensors over heating-on/off and sunlight periods. Confirm which sensor evohome actually regulates against. Resolve Hall/Bedroom relocation, Spare Room sensing, and HR92-room bias before those rooms follow the pilot. |
| Independent MRT validation | Use occupied-location surface/view-factor estimates or a properly interpreted globe measurement with simultaneous air readings. Test stable cold nights at multiple outdoor temperatures, then sunny/cloudy periods and warm-up separately. Make the design's approximately ±0.5 K MRT objective measurable; report bias, error distribution, uncertainty and excluded transient conditions on held-out data. Do not validate against another virtual-MRT model. |
| Actual comfort benefit | Restore the owner's schedules to true comfort targets first, as already agreed. Pilot living room only after the previous gates pass. Compare matched baseline/active periods for occupied comfort, measured air/OT, overshoot, write frequency, manual interventions and heating demand. Stop on unexplained writes, persistent input failure or worse comfort. Expand room by room, not by calendar date alone. |

Living room remains the logical first pilot because its preferred sensor is also the bound zone sensor and the comfort complaint is clear. Confirm its shelf location relative to the radiators and occupied seating; the documented DTS92/Govee 0.8 K difference needs explanation. Kitchen is useful for floor calibration but cooking gains, an open-plan layout and contact priority confound comparisons. Study is useful for solar validation after sensor siting. Hall's small model excludes much of the stairwell/landing volume it may heat; its enclosure assumption needs clarification. Utility's sole Hue sensor near appliances/external door and its v1 schedule-only history argue for later rollout. Bedroom, Spare Room and Max Room require particular care with control-sensor bias and sleeping comfort.

Avoid fitting U, trust, solar gain, asymmetry and adaptive slope simultaneously to “feels cold.” They can compensate for each other, for sensor error, or for missing radiator/draught effects. First establish sensor validity and a night-time envelope baseline, then test solar, then evaluate optional comfort adjustments. The asymmetry term uses the same whole-room glass fraction as the base model and no occupant position; treat it as a separately evidenced empirical bias, not a measured radiant-asymmetry model. None of the shipped room files currently enables it.

## Recommended actions

1. Fix command acknowledgement/ownership, manual takeover and startup restoration before any active room.
2. Add source freshness/validity gates, explicit failed-update status, final command limits and duplicate-zone protection.
3. Correct current-OT reporting and document what the air sensor, MRT proxy and emitter-output estimate actually represent.
4. Validate sensor/control correspondence and the night-time model independently; test solar and adaptive adjustments separately.
5. Reconcile the design and survey promises with implemented behaviour, then run a logged living-room pilot with proven rollback before expanding.
