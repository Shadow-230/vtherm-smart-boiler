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

### I12.3 VT 10.6.5 the oldest supported 🔒 (moved to I12.6 by the second part)

Waits for the user's consent to two things: VT 10.6.5's sources in `vendor/` for the local real-VT
tests (today VT 10.5.1), and the `workflow` scope for one push (CI fetches VT 10.5.1 and SmartPI
0.4.0 for its real-VT tests). Then: the version check, the code kept only for older VT removed,
the user guide's requirements.

### I12.4 What `vtherm_api` lacks 🔒 (replaced by the second part's review of every gap)

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

## Second part: the review of every gap (the user's decisions of 2026-11-24 and 2026-11-25)

The user went through every gap of the list above, one at a time
(`research/2026-11-24-api-only-analysis.md` sections 12–19), then had the API needs analysed
again on those answers (`research/2026-11-25-api-reanalysis.md`). The rule became: **VT
integration goes only through `vtherm_api`; no fallback for what the API has.** What the plugin
reads from Home Assistant after this part is none of VT's data: VT's version and whether VT is
loaded (Home Assistant's integrations), the user's own devices VT names through `entry_infos`
(the room thermometer, the window sensor), the helper below (the user's entity and its recorder
history), and Home Assistant's registries (an entity's area, a relay's platform).

### Decisions

1. **VT decides whether the boiler heats** ("Zgoda", 2026-11-25). VT's central boiler, with its
   own thresholds and activation delay, commands a helper (an `input_boolean`), as VT's author
   recommends for a boiler that needs more than on/off (VT #2107); the plugin follows the
   helper's state and `CENTRAL_BOILER_EVENT`, and adds the water temperature and its safety
   rules. The plugin's own demand (count, devices, power, opening), VT's activation delay carried
   over and their settings go. Control is blocked while VT's central boiler is not set, while its
   command targets anything but the helper (two controllers), or without the helper.
2. **No learning pauses** ("Tak, usuwamy"): pausing a zone algorithm is the user's, not a
   plugin's (SmartPI's author: no setup-dependent logic; VT's author: special needs in
   automations). The plugin no longer pauses SmartPI or anything else, nor reads SmartPI; it
   publishes one "boiler gives no heat" binary sensor with its reason, which the user picks in
   SmartPI 1.0 (its new "heating unavailable" input, `dev-1.0`, 2026-11-24) or uses in an
   automation.
3. **No water interface** ("Usuwamy"): nothing reads it; the manager's properties, the
   `smart_boiler` attribute and `water-interface.md` go. The manager stays: VT hands its
   thermostats over through it.
4. **No frost protection of the plugin's**: it is VT's (its frost preset and central mode).
5. **Rooms from VT**: no zone list of the plugin's; the rooms are the thermostats VT hands over,
   marked "used by the central boiler". The mapping of thermostats to circuits is a separate
   element (the water temperature and the heat source), dealt with apart.
6. **The Boiler page has no rooms list**; it shows how many rooms call, with a link to VT.
7. **The oldest VT is the newest stable at the beta** (10.6.5 today), raised when a VT change is
   needed; no `vtherm_api` floor above VT's own pin.
8. Gap by gap: the duty cycle, valve and cap from the power hook (only for the correction, the
   critical zone, the low-flow alarm and the lowest-water evidence); "started" from the first
   `refresh_state`; VT's safety mode from `SAFETY_EVENT`, a room left out of the curve's
   judgement while in it, or while its thermometer is unavailable, or before a measurement newer
   than the plugin's restart; the critical zone skips a room with an open window and one still
   warming after it closes; the analyses' "was the boiler called" from the helper's history; one
   "reload VT once" repair at a first installation; the zones' past days not rebuilt from the
   recorder.
9. An issue to VT's author on the safety state (`get_feature_manager("safety")` from
   `vtherm_api`'s guide finds nothing, VT naming its built-in managers after the thermostat),
   published only with the user's consent after reading it.

### Facts (checked on 2026-11-25 over the network: VT 10.6.5, `main` 78f7e54; `vtherm_api` 0.13.1)

- `InterfaceThermostatRuntime` declares `entity_id`, `name`, `unique_id` and `entry_infos`;
  `entry_infos` (also given to the manager's `post_init`) is the thermostat's settings merged over
  VT's central entry's data whenever the central entry exists (`base_thermostat.py` 405–468), so it
  carries VT's central boiler settings (`use_central_boiler_feature`,
  `central_boiler_activation_service`, `central_boiler_deactivation_service`,
  `central_boiler_activation_delay_sec`) — to confirm with a real-VT test.
- VT calls the manager's `refresh_state` first in `init_underlyings_completed`, which runs only
  once `is_ready` (725–760, 1027–1040).
- VT calls every manager's `add_custom_attributes` before each write of its climate's state but
  four over_climate setters (fan, humidity, swing).
- The power hook `async_on_underlying_power` fires at each cycle start (over_switch), valve update
  (over_valve, over_climate with valve regulation) and stop, never for plain over_climate, only on
  managers whose `is_configured` is true.
- VT's central boiler counts as configured only with a command (`_is_configured`); it decides
  once every VTherm has started; `CENTRAL_BOILER_EVENT` carries `central_boiler` or
  `delayed_activation_sec`, only after its command succeeded, never on keep-alive or a cancelled
  delay; `PluginClimate` drops it (another entity's event).
- VT 10.6.5 keeps its API while a plugin is registered (`vtherm_central_api.py` `remove_entry`).
- `SAFETY_EVENT` carries `type` start or end (`feature_safety_manager.py` 190–232); built-in
  managers are named after the thermostat (`base_manager.py` 28), so `get_feature_manager("safety")`
  finds nothing.
- VT 10.6.5's `on_percent` getter calls the algorithm's `update_realized_power` when safety or the
  cap clamps it (`thermostat_prop.py`).

### Steps

#### I12.5 The plan and the rules ✅

This part, and `CLAUDE.md`'s rules and facts.

#### I12.6 VT 10.6.5 the oldest supported ✅

A version check refusing an older VT with a notification; the code kept only for VT 10.2–10.5
removed; the climate-state listener for a new VT API removed. The real-VT tests, locally and in
CI, on VT 10.6.5 (its sources fetched into `vendor/` by Claude, the user's consent of 2026-11-25;
the `workflow` scope for one push, the user's consent of the same day).

#### I12.7 Thermostats through the API ✅

The zone matched by its declared `entity_id`; only what is still needed, from the thermostat:
`current_temperature`, `last_temperature_measure`, `target_temperature`, `vtherm_hvac_mode`,
`hvac_action`, `is_device_active`, `hvac_off_reason` (the window only); "started" from the first
`refresh_state`; the power hook; from `entry_infos` only `used_by_controls_central_boiler`,
`thermostat_type`, `cycle_min`, the room thermometer, the window sensor and action,
`underlying_entity_ids` and VT's central boiler settings; `SAFETY_EVENT`, `WINDOW_AUTO_EVENT`;
the rooms read at each refresh and water decision; their details kept in the plugin's own store
for about 8 days. The attribute fallback and parser go.
In two parts. **I12.7a ✅** (2026-11-26): the live reads through the thermostat's members, the
first `refresh_state` and the power hook, and `entry_infos`; the duty cap is not read (VT caps
the hook's request itself, and its cap is not in the API: a room counts as fully open from 95 %
applied); the split of a room between circuits by its devices goes (VT's active devices are not
in the API). **I12.7b ✅** (2026-11-26): the rooms' history in the plugin's own store (8 days,
written 30 min after a change, at unload and at Home Assistant's stop) and "was the boiler
called" from the helper's history, which wins where both are known; the attribute parser and the
recorder reads of VT's climates go. The Boiler page still reads VT's climates: I12.12.

#### I12.8 VT decides whether to heat ✅

Decision 1: the helper setting, following its state and `CENTRAL_BOILER_EVENT`; the plugin's own
demand, VT's delay carried over and their settings removed (a repair notice for a saved power or
opening threshold); the blockers turned round; a hint for a relay VT commands today; a check that
every room is marked "used by the central boiler"; the Auto-TPI notices removed.
Done 2026-11-26, but for the check that every room is marked: it moves to I12.11, where the rooms
come from VT. The relay pre-fill from VT's commands went; the repair issue for a command that
switches anything but the helper names the relay's way out.

#### I12.9 No learning pauses, no water interface ✅

Decisions 2 and 3, with the user guide's automations for SmartPI 1.0, SmartPI 0.6.x and Auto-TPI.
Done 2026-11-26: the binary sensor "Gives no heat" (`no_heat`) with its reason; unavailable while
control is off, so SmartPI is not held back meanwhile. `tests.yml` still names SmartPI and the
deleted `water-interface.md`; it waits for a push with the `workflow` scope.

#### I12.10 Frost and the rooms' trust ✅

Decision 4 and the rooms' trust of decision 8; the "blind room" alarm removed; the critical
zone's window rule.
Done 2026-11-26, with a one-time warning at migration 24 where control was set up: frost
protection is VT's alone now. The zones form's "valves close when off" answer, used only by the
frost protection, goes with I12.11.

#### I12.11 Rooms from VT

Decision 5: no zone picker, the rooms VT marks; the first installation's "reload VT once" repair;
VT's version and "loaded" marked as Home Assistant's information; no VT central mode.

#### I12.12 The page and the analyses

Decision 6; the analyses' "was the boiler called" from the helper's history.

#### I12.13 Docs and a guard

The specification, technical description and user guide in English and Polish; a test that no
module reads VT's entities, entries or states.

#### I12.14 VT's author 🔒

Decision 9, once the user has read the issue and consented.

#### I12.15 J4 and K4 🔒

J4 over the whole on `qas`, then the review before the beta.
