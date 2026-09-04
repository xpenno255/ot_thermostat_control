# OT Thermostat Control

Home Assistant integration that corrects evohome zone setpoints for **operative temperature**: on a cold
day the air setpoint rises by the amount needed for the room to feel like the schedule, on a mild or
sunny day it falls. Targets ramses_cc zones with the evohome cloud entity as the schedule source.

## v2 (this release)

- Steady-state comfort model from a per-room survey of surfaces, glazing and radiators
  (`custom_components/ot_thermostat_control/house/`). No tuning coefficients; U-values you can check
  with a thermal camera.
- Explicit write policy: write-on-change, manual-override hold, window and door overrides, release to
  schedule before an upward switchpoint so evohome's optimum start can act.
- **Shadow mode by default.** Migrated rooms compute and expose what they *would* write and touch nothing.
  Switch a room to `active` with its Mode select when you trust it.
- Flow temperature read from ems-esp (gated on DHW), running-mean outdoor temperature and adaptive
  comfort in the hub.

Design: `docs/v2-design.md`. Survey conventions: the README inside `house/`.

## Migration from v1

Existing entries are migrated automatically (config-entry version 2). Rooms are matched to survey files
by name or alias, start in shadow mode, and stale v1 entities are removed from the registry. v1 overrides
held on the zones expire within an hour and the zones return to their schedules.

To revert: in HACS choose *Redownload* and pick `v1.12.0`, then restart. v1 will not read the v2
config-entry version, so also restore the config-entries store from a backup taken before upgrading,
or re-add the rooms.

## Development

```
python3 -m venv .venv && .venv/bin/pip install homeassistant pytest-homeassistant-custom-component "pytest<9"
.venv/bin/python -m pytest
```
