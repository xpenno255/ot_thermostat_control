# Physics model — v2.1.0, released 13 September 2026

The scheduled temperature is the desired operative temperature (OT), adjusted only by the
existing explicit occupancy setbacks. Cold weather changes the air temperature needed to
achieve that OT; it no longer automatically lowers the desired comfort temperature.

This revision replaces the previous combined-film shortcut with a linearised, steady-state
surface heat balance. It conserves energy within its assumptions. It is still a room-average
estimate, not a validated measurement of personal comfort or a building simulation.

## Changes for existing installations

- Old `adaptive_enabled`, `adaptive_slope` and `adaptive_reference` settings have no control
  effect, including values saved in entry options. The options form no longer offers them.
  The existing `adaptive_shift` diagnostic remains zero for dashboard compatibility.
- Running-mean outdoor temperature remains a diagnostic. It cannot change a thermostat target.
- Occupancy, trust (default 0.8), correction caps (default ±1.5 K), mode, manual-override policy,
  0.1°C resolution, absolute command bounds and override duration are unchanged.
- Surface, solar and wind calculations change, so existing calibration should be reassessed.
  No room is automatically switched into active mode or rebound to a different sensor.

The retired rule was a custom cold-weather setback, not a standard adaptive-comfort correction
for this heating system. The ASHRAE adaptive method described by CBE requires, among other
conditions, no operating heating system. [CBE applicability](https://comfort.cbe.berkeley.edu/).

## Surface heat balance

For inside surface i, use positive conductance K_i from that surface to the other-side air:

```
K_i = 1 / (1/U_effective,i − R_inside,reference)
R_inside,reference = 1/7.7 m²K/W

0 = K_i (T_other,i − T_surface,i)
    + h_c (T_air − T_surface,i)
    + h_r (MRT − T_surface,i)
    + q_solar

MRT = sum(A_i T_surface,i) / sum(A_i)
```

Defaults are h_c=3.0 and h_r=4.7 W/(m²K). These are separate surface convection and linearised
radiation coefficients. They are not the person's heat-transfer coefficients used to define OT.
Radiation exchanged between surfaces cancels when summed over the enclosure. It does not
transfer net heat to the air. A zero U describes an insulated boundary, not a surface forced
to air temperature.

Separating conduction, convection, absorbed shortwave and internal longwave exchange follows
the heat-balance structure described in the [EnergyPlus engineering reference](https://bigladdersoftware.com/epx/docs/26-1/engineering-reference/inside-heat-balance.html).
Our common MRT node, uniform absorption and fixed linear coefficients are deliberately simpler
than EnergyPlus; this implementation does not claim equivalent accuracy.

Other-side temperatures are affine functions `T_other = a*T_air + b`. Known neighbour
temperatures use a=0; an unknown heated neighbour uses a=1, b=0. An unknown unheated space uses
the configured fraction (default halfway between outdoors and room air). Multiple neighbours
contribute by surveyed area fraction, or equal fractions with a warning for legacy text lists.
The inverse includes all air-dependent terms exactly.

Eliminating surface temperatures gives `MRT = A*T_air + B + S`. With still-air
`OT ≈ (T_air + MRT)/2`, the physical required air temperature is:

```
T_air_required = (2*OT_target − B − S) / (1 + A)
```

The same surface equations produce the current-condition OT diagnostic, evaluated at the
measured room air temperature. The compatibility diagnostic `sum_l` is now `1−A`, the effective
MRT slope deficit, rather than the old area-weighted U/h_i sum.

Invalid/nonfinite inputs and U-values that leave no positive surface-to-boundary resistance
are rejected. Typical floor U-values often use a different reference film; the current survey
uses the common 1/7.7 convention for consistency and needs surface-temperature calibration.

## Wind and solar

Wind replaces only the outside film resistance:

```
R_outside(v) = 1 / (5.7 + 3.8*v + 4.7)
U_effective = 1 / (1/U_survey − 0.04 + R_outside(v))
```

The convection part uses the McAdams correlation, with a separate 4.7 W/(m²K) approximation
for exterior radiation. U equals its nominal value around 3.84 m/s under these assumptions,
decreases in calm conditions and approaches a finite limit as wind rises. Weather wind is
only a proxy for facade wind; terrain, direction, infiltration and sky-temperature effects
remain unmodelled. [EnergyPlus exterior convection correlations](https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v22.1.0/EngineeringReference.pdf).

Solar uses the supplied GHI and calendar day to estimate direct-normal and diffuse-horizontal
irradiance using the Erbs diffuse-fraction relation. An isotropic sky and ground albedo 0.2
provide tilted diffuse/reflected radiation. Below 3° solar elevation the estimate is all
diffuse; at night it is zero. Horizontal projection preserves GHI, including when DNI is
bounded. [Erbs decomposition documentation](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.erbs.html).

Glazing g-value, area and fixed shading multiply projected irradiance. Credited transmitted
power is absorbed uniformly over the enclosure. Convection and construction conductance
determine its temperature effect; internal radiation is redistribution. The existing 2 K
solar cap limits credited power before evaluating surface temperatures, preserving a
consistent balance for the credited fraction. It is an uncertainty limit, not an energy sink
or a claim to model the uncredited power.

Missing irradiance or sun position receives no solar heating credit. The configured GHI can
itself be forecast-derived; calling it a sensor does not make it a site measurement. Cloud
estimates remain available in the pure irradiance helpers, but cannot lower the target alone.
`covering_closed_at_night` does not permanently shade daytime windows. The survey can set
fixed `shade_factor`, rooflight tilt and compass bearing; live blind states are not connected.

## Example commands

Calculated using the current survey, OT schedule 20°C, outdoors 0°C, ground 10°C, no solar or
wind, no occupancy offset, default trust/caps, no optional glazing bias, and no neighbour
readings (unknown heated neighbours follow the room's hypothetical air temperature):

| Room | Physical offset | Air command |
|---|---:|---:|
| Living room | +1.656 K | 21.3°C |
| Kitchen | +0.832 K | 20.7°C |
| Bedroom | +1.775 K | 21.4°C |
| Study | +1.391 K | 21.1°C |
| Spare Room | +1.298 K | 21.0°C |
| Hall | +0.741 K | 20.6°C |
| Studio | +1.392 K | 21.1°C |
| Max Room | +0.675 K | 20.5°C |
| Utility | +1.882 K | 21.5°C (capped) |

These replace the adaptive-only examples given during the initial review. Removing adaptive
alone left the old surface model intact; this revision also corrects how the enclosure
exchanges heat. These numbers are predictions, not recommended measured room temperatures.

## Remaining limits and validation

The common radiant node uses area weighting and linearised radiation; it is not an occupant
view-factor calculation. Surface thermal storage, direct sunshine on a person, furniture and
hot-radiator radiation are not represented. The optional glazing bias is explicitly labelled
empirical and is off by default. It is not a measured radiant-asymmetry calculation.

Internal walls/floors default to provisional U=1.5 W/(m²K); actual construction and adjacency
fractions need surveying. Ground at a constant 10°C is another site assumption. Updating a
preferred HA air sensor does not change evohome's bound regulating sensor.

Radiator output remains a capacity estimate using ΔT50 ratings, exponent 1.3 and an assumed
10 K flow/return drop. It neither measures delivered heat nor limits the command by capacity.
Radiator radiant output cannot safely be inferred from boiler flow setting alone, particularly
with closed valves. A full emitter/air/envelope energy model requires additional information.

Validate first on stable cold nights with well-sited air and surface/globe measurements, then
check sunny periods separately. Do not compensate for a biased HR92 by fitting wall U-values.
Mathematical consistency is necessary but does not establish the accuracy of the defaults.

Tests cover an independent uniform-enclosure series-resistance solution, individual surface
and whole-room energy conservation, zero net internal radiation, inverse OT with mixed and
air-dependent boundaries, solar conservation/projection, finite wind limits, survey loading,
unit conversion, missing-data handling and existing adaptive-enabled configurations. Existing
thermostat policy tests remain in the full suite; command acknowledgement and offline preheat
issues from the review are separate control-policy work and are not fixed by this revision.
