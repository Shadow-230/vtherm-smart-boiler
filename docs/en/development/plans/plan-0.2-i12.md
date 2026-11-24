# Plan 0.2, step I12 — Data through `vtherm_api`

Status: history — kept as it was written, in English only; only the ✅ of a finished step is still added. The current documents: [the documentation map](../../README.md).

Goal: the data exchanged between VT, SmartPI and the plugin goes through `vtherm_api` wherever
the API has it, and what nobody uses goes. What the API lacks is listed below, with the reason
each item cannot move yet. A step of 0.2 after I11, before the first release (the user's
decisions of 2026-11-24), listed in `docs/en/development/plan.md`.

## The user's decisions (2026-11-24)

1. Data between VT, SmartPI and the plugin should go through `vtherm_api`. First, move what the
   API already has.
2. Remove what is not needed: the plugin's own public API in `hass.data`; the seven demand
   fields the feature manager offered (nothing reads them: "if we don't use it, remove it");
   support for VT older than 10.6.5.
3. Everything that cannot go through the API: a list (below).

## Facts (checked on 2026-11-24)

- VT hands each thermostat to the feature manager's factory (`factory.create(self)`, VT 10.6.5
  `base_thermostat.py`), and retries late-registered factories when a thermostat starts; a
  thermostat already running when the plugin registers gets no manager until VT's reload. VT
  calls the manager's `stop_listening` when it removes the thermostat.
- `vtherm_api` (0.11.0 to 0.13.1, `interfaces.py`) declares the thermostat by its `unique_id`,
  not its entity ID, and `InterfaceThermostatRuntime` with `current_temperature`,
  `target_temperature`, `vtherm_hvac_mode`, `hvac_action`, `is_device_active`, `hvac_off_reason`,
  `cycle_min`, `is_overpowering_detected`, `on_percent`; `last_temperature_measure` in
  `InterfaceTemperatureTimestampRuntime` (0.12.0). 0.12.0 and 0.13.1 were released on
  2026-11-23.
- In VT 10.6.5 each of these is filled from the same field as the attribute the plugin read
  (`update_custom_attributes`); `vtherm_hvac_mode` has the climate state's values ("sleep"
  included). The attributes are a snapshot rounded by Home Assistant to a tenth; the members are
  live.
- **The same for every kind of VT thermostat and every mode** (the user's point, 2026-11-24):
  VT builds those attributes in `BaseThermostat` from the same properties for `over_switch`,
  `over_valve`, `over_climate` and `over_climate` with valve regulation; a type changes only how a
  property is worked out (`is_device_active` in `thermostat_valve.py` and
  `thermostat_climate_valve.py`), and the attribute carries that value too. `cycle_min` is
  `BaseThermostat`'s for every type. The modes — heat, auto, heat_cool, cool, dry, fan_only, off,
  and VT's own "sleep" — read as the climate's state with the same value does; "sleep" and a mode
  before VT's start are not known to the plugin either way, so the attribute's reading stays.
  VT's central mode reaches a zone as its mode, target or `hvac_off_reason`.
- **`on_percent` is not a plain read:** VT 10.6.5's `ThermostatProp.on_percent` calls the
  algorithm's `update_realized_power` whenever safety or the duty cap clamps the value
  (`thermostat_prop.py`). Reading it from the plugin every few seconds would act on SmartPI.
- SmartPI (0.6.7, `dev-1.0`) registers as a proportional algorithm and offers nothing through
  the API; its learning switch is its own Home Assistant service.

## Steps

### I12.1 Zone reads through `vtherm_api` ✅

`vtherm_link.py` keeps the thermostats VT handed to the manager (`register_thermostat`, forgotten
at `stop_listening`), finds a zone's by the unique ID in VT's registry entry, and reads from it,
while VT shows the climate running: the room temperature (to a tenth) and when it was measured,
the target, the mode, whether the zone heats, whether its device is on, power shedding, why VT
keeps it off, its cycle. A member missing, failing, or of another type keeps the attribute's
value; a thermostat VT never handed over is read from its attributes as before. The manager finds
its zone by the unique ID too. Diagnostics list the zones read through the API.

### I12.2 Nothing outside the API, nothing unused ✅

The public API in `hass.data` (`water-interface.md` §3.2) and the seven demand fields of the
manager (`demand_count` … `opening_threshold`) removed; the plugin's own entities still show the
demand. The specification records the removal (its section 8).

### I12.3 VT 10.6.5 the oldest supported 🔒

Waits for the user's consent to two things: VT 10.6.5's sources in `vendor/` for the local real-VT
tests (today VT 10.5.1), and the `workflow` scope for one push (CI fetches VT 10.5.1 and SmartPI
0.4.0 for its real-VT tests). Then: the version check, the code kept only for older VT removed,
the user guide's requirements.

### I12.4 What `vtherm_api` lacks 🔒

A discussion with VT's and SmartPI's authors, opened only with the user's consent to publish
(`research/2026-11-24-vtherm-api-exchange-paths.md`, the proposal).

## What cannot go through `vtherm_api` now

| What | Direction | Today | Why not through the API |
|---|---|---|---|
| The zone's duty cycle (`on_percent`) | VT → plugin | attribute | declared, but VT 10.6.5's getter acts on the algorithm (Facts) |
| Valve opening (`valve_open_percent`) | VT → plugin | attribute | not declared; the API's valve hook covers only `over_climate` valve regulation and tells commands, not the state |
| The devices on (`device_actives`), their power, mean power over the cycle | VT → plugin | attributes | not declared; the power hook tells commands per cycle, not the state |
| The duty cap (`max_on_percent`) | VT → plugin | attribute | not declared |
| VT has started the thermostat (`is_ready`) | VT → plugin | attribute | not declared |
| VT's safety mode | VT → plugin | attribute | not declared |
| Used by VT's central boiler, the algorithm's name, the thermostat's type | VT → plugin | attribute (`configuration`) | not declared |
| Auto-TPI learning | VT → plugin | attributes | not declared (VT's private handler) |
| SmartPI's learning switch and its phase | SmartPI → plugin | attribute, diagnostic sensor | SmartPI offers nothing through the API |
| Pause and resume SmartPI's learning | plugin → SmartPI | SmartPI's service | no API call; changing SmartPI's object would skip its own save and refresh |
| A consumer's key (`water_factor`) | algorithm → plugin | `specific_states` | the API has no channel from an algorithm to a feature manager |
| VT's central mode | VT → plugin | `select` entity | not declared |
| VT's central boiler: configured, its state | VT → plugin | VT's entry and binary sensor | only an event, sent on the central boiler's own entity |
| Every value of a thermostat VT started before the plugin registered | VT → plugin | attributes | VT hands the thermostat over only when it starts |
| The room sensor VT reads, the devices VT drives | VT → plugin | VT's config entry | not declared |
| What VT's central boiler kept (its commands, delay, thresholds), read once when moving over | VT → plugin | VT's config entry | not declared |
