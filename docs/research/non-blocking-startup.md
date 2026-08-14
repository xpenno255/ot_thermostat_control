# Research: idiomatic non-blocking startup for HA config entries

- **Date:** 2026-08-14
- **Ticket:** [#7](https://github.com/xpenno255/ot_thermostat_control/issues/7) (part of map [#6](https://github.com/xpenno255/ot_thermostat_control/issues/6))
- **Sources:** home-assistant/core `dev` branch (version `2026.9.0.dev0` at time of reading) and developers.home-assistant.io. Line numbers refer to the `dev` branch as of 2026-08-14.

## Question

What is the idiomatic Home Assistant pattern for an integration whose `DataUpdateCoordinator` first refresh should **not** block config-entry setup? This integration has 10 config entries (9 rooms + 1 hub); each room's first refresh can sleep up to `automation_delay` (default 5 s), and observed boot delay is 20 s+.

---

## 1. How HA schedules setup of multiple config entries of one integration

**Verdict: parallel (concurrent tasks, gathered), not serial.**

After a component loads, core sets up **all** of its config entries as concurrently-gathered eager tasks — [`homeassistant/setup.py`, `_async_setup_component`, lines 467–482](https://github.com/home-assistant/core/blob/dev/homeassistant/setup.py):

```python
if entries := hass.config_entries.async_entries(
    domain, include_ignore=False, include_disabled=False
):
    await asyncio.gather(
        *(
            create_eager_task(
                entry.async_setup_locked(hass, integration=integration),
                name=(f"config entry setup {entry.title} {entry.domain} "
                      f"{entry.entry_id}"),
                loop=hass.loop,
            )
            for entry in entries
        )
    )
```

`async_setup_locked` holds `entry.setup_lock`, which is a **per-entry** lock (`config_entries.py` line 549: `_setter(self, "setup_lock", asyncio.Lock())` in `ConfigEntry.__init__`) — there is no per-domain serialization.

**Implication for the 20 s+ observation:** with 10 entries each awaiting `asyncio.sleep(5)` (the integration's sleep at `coordinator.py:759` is a non-blocking `await asyncio.sleep(delay)`), wall-clock cost should be ~max (≈5 s), not the sum. A 20 s+ stacked delay is **not** explained by core's entry scheduling on current core; worth re-measuring during implementation (candidate explanations: an older core on the live box, `ConfigEntryNotReady` retries with exponential backoff — see §3.2 — or some other await chain). Regardless, the decided intent (skip the sleep at boot) removes the delay in either case.

*(Boot semantics: the gather above is awaited during component setup, so HA's startup — and `EVENT_HOMEASSISTANT_STARTED` — waits for every entry's `async_setup_entry` to return. Whatever an entry awaits inside setup delays boot; background tasks do not.)*

## 2. Sanctioned alternatives to blocking `async_config_entry_first_refresh()`

### 2.1 What the blocking call does (baseline)

[`helpers/update_coordinator.py`, `async_config_entry_first_refresh`, lines 317–360](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/update_coordinator.py): runs `_async_setup()` then `_async_refresh(log_failures=False, ...)`, and if `last_update_success` is false it raises `ConfigEntryNotReady` with the cause attached. Docstring: *"Will automatically raise ConfigEntryNotReady if the refresh fails."*

It also **hard-requires being called during setup** (lines 339–349): it raises `ConfigEntryError` if `config_entry.state is not ConfigEntryState.SETUP_IN_PROGRESS`. So it **cannot** be moved into a background task that outlives `async_setup_entry` — the background variant must use `async_refresh()`.

### 2.2 Background first refresh via `entry.async_create_background_task` (the idiomatic pattern)

[`homeassistant/config_entries.py`, `ConfigEntry.async_create_background_task`, lines 1403–1427](https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py) — docstring:

> Create a background task tied to the config entry lifecycle. Background tasks are automatically canceled when config entry is unloaded. A background task is different from a normal task: **Will not block startup**; Will be automatically cancelled on shutdown; Calls to `async_block_till_done` will not wait for completion.

The dev blog on job APIs recommends exactly this helper for coroutines run from a config entry ([Deprecating `async_run_job` and `async_add_job`, 2024-03-13](https://developers.home-assistant.io/blog/2024/03/13/deprecate_add_run_job/)).

The coordinator docs bless the non-retrying variant: *"If you do not want to retry setup on failure, use `coordinator.async_refresh()` instead"* of `async_config_entry_first_refresh()` ([Fetching data](https://developers.home-assistant.io/docs/integration_fetching_data/)).

**Core examples doing precisely this:**

- [`smart_meter_texas/__init__.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/smart_meter_texas/__init__.py) — API takes ~30 s per read; comment: *"This avoids Home Assistant from complaining about the component taking too long"*:

  ```python
  entry.async_create_background_task(
      hass, coordinator.async_refresh(), "smart_meter_texas-coordinator-refresh"
  )
  await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
  ```

- [`home_connect/__init__.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/home_connect/__init__.py) — comment: *"We refresh each appliance coordinator in the background. to ensure that setup time is not impacted by this refresh"*:

  ```python
  entry.async_create_background_task(
      hass,
      appliance_coordinator.async_refresh(),
      f"home_connect-initial-full-refresh-{entry.entry_id}-{appliance_id}",
  )
  ```

Note both still validate connectivity cheaply *before* this (e.g. `smart_meter_texas` raises `ConfigEntryNotReady` on a client `TimeoutError` earlier in setup) — see §3.3.

### 2.3 Seeding `coordinator.data` (persisted/derived state)

- `DataUpdateCoordinator.__init__` initializes `self.data = None` and `self.last_update_success = True` (`update_coordinator.py` lines 118, 132). Nothing forbids assigning `coordinator.data = <restored>` before entities are added — the attribute is plain state.
- The sanctioned mutator is [`async_set_updated_data(data)` (lines 605–620)](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/update_coordinator.py): sets `data`, sets `last_update_success = True`, reschedules the refresh timer, and notifies listeners. Use it if entities may already be subscribed.
- Either way entities get a real state immediately at boot instead of `None`/unknown, and the scheduled/background refresh replaces it.

### 2.4 Skip-first-cycle logic inside `_async_update_data`

Not from docs, but implied by the coordinator contract: since `_async_update_data` is integration code, a first-cycle fast path (e.g. don't sleep `automation_delay` when `self.data is None`, returning stored/skipped data) keeps `async_config_entry_first_refresh()` **and** its `ConfigEntryNotReady` semantics while making the first refresh near-instant. For this integration — where the sleep is a deliberate settling delay, not I/O — this is the smallest-diff option and loses nothing.

## 3. Pitfalls

### 3.1 Entity availability at boot

`CoordinatorEntity.available` returns `coordinator.last_update_success` (`update_coordinator.py` lines 697–699), which is initialized `True` (line 132). So with a background/deferred first refresh, entities are **not** `unavailable` at boot — but `coordinator.data` is `None`, so entity properties that read `self.coordinator.data[...]` must tolerate `None` (show unknown) or the entity will throw. Seeding data (§2.3) avoids the unknown window. If the background `async_refresh()` **fails**, `last_update_success` flips `False` → entities go `unavailable` until a later refresh succeeds.

### 3.2 Losing `ConfigEntryNotReady` retry semantics

When `async_setup_entry` raises `ConfigEntryNotReady`, core puts the entry in `SETUP_RETRY` and schedules retries with exponential backoff — `config_entries.py` lines 832–871: `wait_time = min(2**self._tries * 5, SETUP_RETRY_MAX_WAIT)`, via `async_call_later`, or on `EVENT_HOMEASSISTANT_STARTED` if still booting ([Handling setup failures](https://developers.home-assistant.io/docs/integration_setup_failures/): *"Home Assistant will automatically take care of retrying set up later"*). A failed **background** `async_refresh()` gets none of this — the entry stays `LOADED`, failures are only logged, and recovery waits for the next scheduled refresh. Also note §2.1: calling `async_config_entry_first_refresh()` from the background task instead raises `ConfigEntryError` because the entry is no longer `SETUP_IN_PROGRESS`.

### 3.3 Quality scale: `test-before-setup`

[Bronze rule `test-before-setup`](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/test-before-setup/): *"When we initialize an integration, we should check if we are able to set it up correctly. This way we can immediately let the user know that it doesn't work."* Raise `ConfigEntryNotReady` / `ConfigEntryAuthFailed` / `ConfigEntryError` as appropriate; *"There are no exceptions to this rule."* A fully-background first refresh with no other validation technically skirts this; the core-blessed shape (per `smart_meter_texas`) is a **cheap synchronous check during setup** (can it reach its dependencies?) plus the expensive first data fetch in the background. For this integration the "check" is trivial (hub config + HA state machine reads — no network), so a first refresh without the sleep effectively *is* the test.

## Recommendation

For 10 entries whose refresh sleeps up to 5 s each, in preference order:

1. **Skip the `automation_delay` sleep on the first cycle** (`self.data is None`, or an explicit first-run flag) and keep `await coordinator.async_config_entry_first_refresh()`. Smallest change; keeps `ConfigEntryNotReady` retry semantics and `test-before-setup` compliance; matches the decided intent (delay preserved for normal cycles). Optionally seed from the existing `OTStore` so the first calc starts from persisted state.
2. If a genuinely slow first fetch ever appears, adopt the core pattern: validate cheaply in `async_setup_entry`, then `entry.async_create_background_task(hass, coordinator.async_refresh(), name)` before forwarding platforms (`smart_meter_texas`, `home_connect`), accepting the §3.1/§3.2 trade-offs — ideally with `coordinator.data` seeded via `async_set_updated_data` so entities have state immediately.

Either way, re-measure the boot delay after the fix: current core gathers entry setups concurrently (§1), so the observed 20 s+ stacking should be re-verified against the live instance's core version.
