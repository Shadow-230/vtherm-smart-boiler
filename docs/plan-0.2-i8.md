# Plan 0.2, step I8 — A boiler plugin, one form per menu item

Goal: the corrections the user decided on 2026-10-10 after trying I7 on a test instance. The
plugin does one thing — control the boiler and watch how it runs; what belongs to rooms, windows
and zones is VT's and goes. The options become a menu of single forms with no sub-menus, each
field shown only where it can work, each text short and plain. Step I8 of `docs/plan-0.2.md`.
Control stays off by default; nothing here makes the plugin write anything new to the boiler.
Scope: `SCOPE.md`; overview: `PLAN.md`; the release plan: `docs/plan-0.2.md`. The decisions as
collected in chat: `research/2026-10-10-options-review-decisions.md`.

Status on 2026-10-11: the plan approved by the user; I8.0 to I8.3 done; I8.4 next.

## How to read this plan

- "Decision X" refers to the lettered list below.
- ✅ marks a finished step. Every step is one pull request into `dev`, with its "J4 impact": the
  J4 scenarios to run again once it is deployed in the test Home Assistant, and what the runner
  (`devenv/j4/`, the testing session's) must change. After each step the main session reports to
  the user in Polish.
- Every step updates, in the same pull request, every document and text its change touches —
  the list is in the step ("Documents"). The last step (I8.10) checks them all against the code
  once more.
- Every step that changes stored options migrates them (a new `MINOR_VERSION`, a migration in
  `async_migrate_entry`, tests that an entry from before reads the same where nothing was meant
  to change).
- "Claude's call" marks a choice the user left open: written here with its reason, provisional
  until K4 like every value of this release.

## Facts (checked in the code and the vendored sources, 2026-10-10)

Details: `research/2026-10-10-control-section-duplicates.md`,
`research/2026-10-10-room-values-mode-sources.md`, `research/2026-10-10-i7-vt-menu-facts.md`.

- Each connection writes through exactly one path (`control_config.CONNECTION_PATH`; read only:
  none) and offers its own modes (`CONNECTION_MODES`; on/off only with the relay). The control
  step's write path repeats the connection and the mode.
- The MQTT topics are stored twice (the boiler section for the repeats, the control section for
  the writes); the OTGW gateway is picked on a control step while the signals' suggestions use
  "the one loaded gateway" only; the topology and the thermostat's wiring are facts of the
  gateway; the gateway's "monitor mode" topology means no control, as the mode "monitoring only".
- The setpoint read-back is read "as the CH setpoint signal would be" (`coordinator.py`); on the
  OTGW both are the boiler device's "Control setpoint 1". The CH-enabled read-back (On/Off) is
  not the "CH active" signal (Running).
- The design outdoor temperature is one stored value shown in two forms; the curve's hard
  maximum and each circuit's maximum cap the same written setpoint.
- The weather ceiling (curve + "correction range", 10 K) binds only above the curve, where only
  the comfort correction goes (`core/controller.py` water decision, `core/limits.limit_flow`);
  the correction has its own limit (3 K by default).
- The reference room is published (three sensors, diagnostics) and read by no control decision.
- The thermal mass is stored as a time constant no function reads; the floor area and insulation
  give only a coarse heat-loss estimate shown until recorded days replace it — the lowest-water
  estimate and the verdict use only an entered, measured or learned loss.
- With a gas meter the gas rates are not read; the maximum power and the modulation scale are
  read only with a modulation signal.
- "Heat reaches the zone" (`core/hot_water.py`, the flow against the room) feeds a per-zone binary
  sensor, the VT feature manager and diagnostics, and no control decision. The VT feature
  manager exists only to show it and the emitter power factor on each VT thermostat.
- Foreign heat freezes the comfort correction (`core/controller.py`), pauses SmartPI's learning
  (`core/learning.py`), is left out by the long-run rule, and has a hold time in the monitor.
- The window guard (G11 F) feeds a binary sensor and leaves rooms out of the comfort correction
  and the long-run rule; VT itself detects windows and turns the zone off, frost or eco.
- On the relay path flame and flow never gate control (`control.py`).
- VT 10.4.0 publishes each thermostat's devices (`underlying_entities`) and the active ones
  (`specific_states.device_actives`, `is_device_active`); it has no outdoor-based season switch.
- SmartPI 0.4.0 publishes its phase, its learning-phase heating state and its working setpoint
  (`filtered_setpoint`), which never includes the learning band (+0.5 °C, `HYST_UPPER_C`).
- Home Assistant's menu takes a mapping of step to a literal label (core's `elmax` flow), so a
  menu can name items built at run time; each item needs its own `async_step_<id>`.

## Decisions of 2026-10-10 (the user)

### A. Scope

1. The plugin is for the boiler: its control and watching how it runs. Room, window and zone
   topics belong to VT. Functions and plans beyond that are removed (B).
2. No sub-menus: every menu item is one form that returns to the menu. Confirmation dialogs stay
   ("this change stops control", the second confirmation of a risky option). A form may show
   itself again with the fields its answer revealed (decisions E3, H1).
3. A field shows only where it can work — its signal mapped, its mode and connection — and a
   hidden value is kept.
4. Texts are short and plain: a section about 40 words, a field about 30, a safety note up to
   50; what it does, its default, its main risk. Details go to the user guide, also plain. They
   describe functions, not recommendations; facts about safety consequences stay, worded
   neutrally ("a relay that cuts the boiler's power also stops its frost protection and pump
   overrun"). No sample ESPHome configuration in the guide: it says what the ESPHome tick
   confirms.

### B. Removed

1. The reference room: its section, its logic (`core/reference_room.py`), its three sensors, its
   diagnostics and its stored settings.
2. Window handling: the plugin's "window probably open" guess (G11 F) and every use of windows —
   VT decides; a zone VT turns off or to eco or frost for a window no longer asks or looks short.
3. Foreign heat entirely: its sources and thresholds, the hold time, the SmartPI pause for it,
   the comfort correction's freeze for it, the long-run rule's exclusion.
4. Per-zone entities: the emitter power factor, "heat reaches the zone", foreign heat; with them
   the zones' rated output and exponent and the monitor's "near room temperature".
5. Building fields: floor area, insulation, thermal mass and the loss coefficient (an entered
   loss coefficient becomes the design load it gives).
6. The curve's "correction range" (the comfort correction's own limit stays the only one).
7. The control step's write path field (it follows the connection and the mode; kept only for an
   entry made before the connection question) and the gateway topology "monitor mode".
8. Summer/winter switching of any kind.
9. Plans struck: FC1 (summer/winter from the forecast), the warning for zones the boiler does not
   feed, the proposal to the SmartPI and adaptive TPI authors.

### C. Kept and changed

1. The VT feature manager stays, showing one value: "heat available", redefined — the flame
   burning and the flow clearly above the return where the return is known (the flow against
   the room, with a fixed margin, only without a return).
2. The control mode "room temperature only" leaves the panel until it works (0.3); an entry with
   it reads as "monitoring only", which is what it does today.
3. "Relay after hand-back" stays off by default; its text says what each answer means without a
   thermostat.
4. The relay's texts no longer advise wiring a thermostat in parallel, anywhere: they say what
   happens without Home Assistant and the manual way back through the relay's own app or page.

### D. Connection, interface, signals, freshness

1. "Connection and boiler type" and "Control mode" are two menu items. A connection change that
   makes the stored mode impossible opens "Control mode" at once.
2. "Boiler interface", where there is something to ask, its form following the connection: the
   OTGW gateway (one loaded gateway picked automatically), the MQTT topics (one copy, for the
   repeats and the writes), what is on the gateway's thermostat terminals and the thermostat's
   own water setpoint, the restart indicator. The hand-back guards that fix these fields while a
   hand-back is owed (PB-09) move with them.
3. "Boiler signals" holds every read input: the "CH setpoint" signal is the setpoint read-back;
   the CH-enabled read-back becomes a signal field.
4. The relay asks "Do you also read the boiler through another integration?" — No by default,
   Yes by default where such a signal is already mapped. No: flame, flow, return, the boiler's
   electric power, gas meter, outdoor sensor and weather only; the other boiler signals mapped
   before are removed at the save. Yes: the full list.
5. The wired thermostat's setpoint and temperature stay for every connection but the relay with
   No, described as "a thermostat connected to the boiler or its interface".
6. Outdoor temperature: any outdoor sensor — renamed, new text; kept for the relay.
7. Freshness: a limit only for a mapped signal; removing a signal removes its limit; the text
   follows the connection (the relay: the limits judge the monitor only).

### E. Boiler, building, monitor thresholds

1. Boiler: the minimum power always; the maximum power and the modulation scale only with a
   modulation signal; the boiler's maximum CH setpoint (advanced) hidden for the relay; the gas
   rates only with modulation and no gas meter, with "m³/h" shown and a plain text (the boiler
   manual's technical data; kg/h for LPG); the pressure limits only with a pressure sensor (as
   I7.2); the bypass only where the low-flow warning can work.
2. Building (advanced, hidden when empty): the design load; the heating threshold, renamed
   "Heating threshold (for statistics)", its text saying it switches no heating; the design
   outdoor temperature only where there is no curve.
3. The design outdoor temperature lives in the curve: "Outdoor temperature at the hardest frost
   (curve point)"; the guide says where to find it (the heating design, the national standard
   for the place, the frost of a few days a year).
4. Monitor thresholds (advanced): the condensing return only for a condensing boiler with a
   return signal; short burn, frequent starts and unstable ignition only with flame; the
   monitoring days and the verdict window always.

### F. Circuits and zones

1. No list inside: each circuit is its own menu item ("Circuit: <name>") plus "Add circuit"; at
   most 4; removed by a tick in its form (never the only one); one circuit, no list, at the
   simple level.
2. A circuit's form: its name (suggestions from Home Assistant's areas and the VT zones' names,
   or free text; the internal ID stays and is never shown); "Circuit type" (the field once called
   "Control"); the VT zones it feeds — whole zones, single devices of a zone, or an area as a
   shortcut filled in at the save; of them, those with underfloor and those with convectors (the
   rest radiators — a zone in two circuits has an emitter in each); the highest water
   temperature (one field: the curve's hard maximum merged in); the too-hot alarm and its time
   (advanced, with a flow reading); the circuit's own flow sensor (mixed or fixed-valve circuits
   only); the fixed temperature (fixed valve only, the form showing itself again).
3. A circuit "controlled by other automation (mixer, pump)" — the type once called "mixed by a
   separate controller" — gets two optional fields: "Circuit asks for heat" (a binary entity: the
   boiler heats for it as for a VT zone asking) and "Water temperature needed" (a value or an
   entity: while the circuit asks, the boiler's water stays at or above it plus a margin). The
   plugin never drives a mixer or a pump.
4. Zone assignment is only on the circuit's side; the zone's form no longer asks a circuit. The
   watched zones are those in a circuit.
5. "VT zones" is one form: "valves close when the zone is off", a list of the watched zones.
6. The boiler's water is the highest need of the circuits asking for heat — the direct circuit's
   curve, a fixed valve's setting plus its margin, another automation's need plus its margin —
   under the safety caps. Each circuit has its own curve, its own comfort correction and, from
   0.4, its own learning, from its own zones only.

### G. The thermostat-like mode (0.3; plan only here)

The control mode "room temperature only" returns in 0.3 as "Like a room thermostat": on and off
follow the zones' demand; only zones asking for heat now count; the largest deficit wins, its
target the highest known (the VT setpoint; +0.5 K while SmartPI's learning phase heats; SmartPI's
published setpoint); while a zone asks, at least a minimum deficit is sent; two kinds —
"temperature and setpoint" (two entities, or the OTGW's own support) or "difference" (one
entity); 0.1 °C or the target entity's step, the deficit rounded up, the temperature down, the
setpoint their sum, never no deficit while a zone asks; a margin before the zone changes; sent
on a change only and not too often; cleared without valid data. What ESPHome OpenTherm and EMS-ESP
take is checked before it is planned.

### H. Control tabs

Shown only with control, each one form:
1. "Control device": the setpoint entity, the heating switch, the hand-back method — the form
   showing itself again with that method's own fields —, the write types only where the
   connection does not fix them, the boiler's own room controller, the ESPHome tick; or the relay
   and its settings: the timer's length only with a timer, the repeat interval only without
   state reports or with a timer, "boiler heats above (W)" only with the boiler's power mapped.
2. "Heating curve" (full control): the curve's points, the lowest water temperature, the curve's
   room Auto or Manual with the rooms left out, the exponent and offset (advanced), the fallback
   setpoint (advanced), the comfort correction and its limit in one place at both levels.
3. "Control behaviour": the activation delay, the demand criteria, the learning pauses; with full
   control the ramp and the decision interval (advanced) and the "off" setpoint only where "off"
   is written as a low setpoint.
4. "Frost protection".
5. "Alarm reactions", where any applies.

### I. Plans

1. The wall thermostat linked to a VT zone (0.3 at the earliest) stays, reworded as a fallback for
   Home Assistant failing: one way, VT → thermostat, off by default; the user picks the
   thermostat's setpoint entity and the zone; rounded to its step; never stored in the
   thermostat's or the gateway's permanent memory; nothing sent in the recognition period.
2. 0.4: curve learning and tuning per circuit — also the need of a circuit run by other
   automation where no value is given.
3. Later: estimating gas from the boiler's power where no gas rates are given.
4. Kept as planned: FC0, FC2, FC3, FC4, anti-cycling, the heating-commanded entity, the lowest
   water "apply" mode, DHW charging, gas modes, more devices.

## Claude's calls

- **Order:** removals first (less to restructure), then the feature manager, the menu, the
  circuits (model before control), the control tabs, the texts; the documents follow every step
  and are checked once more at the end.
- **Migrations, one per step that changes stored options**, each cautious: nothing a user set
  is lost without the user's decision; a value merged from two takes the cautious one (the
  highest water temperature: the lower of the two); an entered loss coefficient becomes the
  design load it gives at the stored design outdoor temperature and the 20 °C indoor reference;
  the read-back and the "CH setpoint" signal: where both are set and differ, the read-back's
  entity (what control was judged with); the MQTT topics: where the two copies differ, the
  control section's (what the writes used); the topology "monitor mode": the mode becomes
  "monitoring only", the control section kept; zones' circuits become the circuits' zone lists,
  their emitters the circuit's emitter lists.
- **Where stored options keep their keys** (the topology, the thermostat's wiring, the gateway)
  while their field moves to another tab, the storage stays: fewer migrations, the same reading.
- **The device-level assignment** (a zone's single devices in a circuit) counts a device as
  asking when VT lists it in `device_actives`; a zone in two circuits asks in each through its
  own devices there. Valve opening stays a zone's value (VT gives no per-device opening).
- **Circuit limit 4:** CH1 and CH2 the boiler can serve, two more watched behind mixers.
- **The hand-back method's own fields** show after the method is picked: the form shows itself
  again, as the fixed temperature does (decision A2).

## Other plans and specifications

Collated on 2026-10-10 with every plan of the project. A finished plan is history: its text is not
rewritten; where I8 changes what a finished step built, a note in parentheses is added to that
step, as earlier plans did ("(0.2.1: …)"), in the I8 step that changes it.

| File | What I8 changes there | Step |
|---|---|---|
| `PLAN.md` | the 0.2 row's content (no reference room, windows, foreign heat or per-zone values; one value for VT; circuits run by other automation; single-form options); the 0.3 row (FC1 struck; room values become the thermostat-like mode, G; the wall thermostat as a fallback, I1; the zones-not-fed warning struck); the 0.4 row (learning per circuit, I2); "Later" (the proposal to the authors struck; gas from power, I3) | I8.0 |
| `SCOPE.md` | plans: §5's control modes and the topology table's room-values column, the safety lines on room values (§3, §7 control safety), "Reference room", the forecast roadmap (FC1), §7's stages, §9 (struck items, the relay wiring field struck, the wall thermostat reworded, gas from power), §11's open decisions on room values; behaviour: each section as its step changes it, and the fixed-values table (the reference room's switch margin, "near room temperature", the weather ceiling's 10 K, the foreign-heat hold, the window guard's values leave it, and so leave K4's review) | I8.0 (plans), each step (behaviour) |
| `docs/plan-0.2.md` | the status line and step I8; "Moved to 0.3" rewritten as decision G; K1's README list without recommendation sections (the relay setup recommendations, "VT settings with the plugin" become descriptions of what the plugin does); notes on H4 (one value, I8.2), H5 (no foreign-heat pause, I8.1), G11 (F withdrawn, I8.1), I2 and I6 (no write path field or "monitor mode" topology; "room temperature only" hidden, I8.4), I7 (the menu's items, I8.4, I8.7, I8.9) | I8.0, I8.1, I8.2, I8.4, I8.7, I8.9 |
| `docs/plan-0.2-g11.md` | F withdrawn; E's exclusions of windows and foreign heat removed; B's freeze for foreign heat removed | I8.1 |
| `docs/plan-0.2-i6.md` | decision 6 (room values hidden until 0.3), decision 9 (the MQTT topics, one copy), decision 2 (no write path field) — notes | I8.4 |
| `docs/plan-0.2-i7.md` | notes: the reference room's filter gone; control's items shown by the mode (and for an entry from before the mode, or one still holding a control section); circuits and the control chain as items | I8.4, I8.7, I8.9 |
| `docs/plan-0.2.3.md` | "Open after 0.2.3" item 52 (the circuit "controlled separately") built as F3 — a note | I8.8 |
| `docs/plan-0.2.2.md` | decision 13: its summer/winter part withdrawn (FC1 struck), anti-cycling stays; "Open after 0.2.2" item 11 (a wiring field for the relay: alone, parallel, series) struck — the plugin describes no wiring (C4) | I8.0 |
| `docs/plan-0.1.md`, `docs/plan-0.2.1.md`, `docs/plan-0.2.2-details.md`, the reviews | history; not changed. What I8 removes of 0.1's monitor (the reference room, foreign heat, the coarse building estimate's inputs, the emitter factor) is listed in B | — |
| `CLAUDE.md` | "Where to continue" and the plan list (I8.0); the verified facts touched by I8.2 (the manager's one value) | I8.0, I8.2 |

Found while collating, outside I8: `docs/plan-0.2.1.md` R2 🔒 (the integration's icon) is still
open though K1 records the brand as done on 2026-10-07 — for the user to close.

## Steps

Each step: code and tests (a core change starts with a test), translations EN and PL, the
documents named, the full checks of `CLAUDE.md`, a pull request with its J4 impact.

### I8.0 ✅ The plan

This file; step I8 in `docs/plan-0.2.md` with its status line; `CLAUDE.md`'s "Where to
continue" and plan list; `PLAN.md`'s plan list. The plans' future, as decided (B8, B9, C2, G, I)
and as the table above names for I8.0: `PLAN.md`'s 0.2, 0.3, 0.4 and "Later" rows; `SCOPE.md`'s
plan parts (the room-values texts rewritten as decision G, the forecast roadmap, §7's stages, §9,
§11); `docs/plan-0.2.md`'s "Moved to 0.3" and K1's README list; `docs/plan-0.2.2.md`'s decision 13
and "Open after 0.2.2" item 11. J4 impact: none.

### I8.1 Out of scope: rooms, windows, foreign heat (B1–B4)

Claude's call: built as four pull requests, each easy to review and to undo — I8.1a the
reference room, I8.1b windows, I8.1c foreign heat, I8.1d the per-zone entities and fields with
"near room temperature". Each takes its own share of the code, migration, documents and J4
impact below.

- I8.1a ✅ the reference room (minor version 9 drops its settings; its three sensors leave the
  registry as entities the options no longer create; the setup's and the options' "Reference
  room" items, the problem codes `reference_zone_unknown` and `invalid_reference`, the level's
  "restore defaults" text; `SCOPE.md` §5 and §7, both user guides, `docs/plan-0.2-i7.md`). Done
  on 2026-10-10.
- I8.1b ✅ windows (the window guard and its binary sensor, VT's window state no longer read, the
  comfort correction's and the long-run rule's window exclusions, the feature and its texts; no
  stored option, no migration; `SCOPE.md` §7, both user guides' 4.9, `docs/plan-0.2-g11.md` E and
  F, `docs/plan-0.2.md` G11). Done on 2026-10-10.
- I8.1c ✅ foreign heat (`core/foreign_heat.py`, the zones' sources and thresholds, the monitor's
  hold time, the source reader, the per-zone binary sensor, the SmartPI pause cause — a stored
  "foreign_heat" cause reads as unknown, so as hot water, the cautious rule —, the comfort
  correction's freeze, the long-run exclusion; minor version 10 drops the stored sources and hold
  time; `SCOPE.md` §3 and §7, `docs/plan-0.2.md` H5, `docs/plan-0.2-g11.md` B and E; the
  learning-pause and comfort-correction texts). Done on 2026-10-10.
- I8.1d ✅ the per-zone entities and fields (the "heat reaches the zone" binary sensor and the
  emitter power factor sensor, both one per zone; the zones' emitter output and exponent; the
  monitor's "near room temperature", its default kept by the rule; minor version 11 drops them,
  and the entities leave the registry at the next setup as entities the options no longer
  create; with no zone entity left, the entities' zone key and the move of the zones' unique IDs
  from 0.2 go too; `SCOPE.md` §5). The coordinator still computes both values for the feature
  manager until I8.2. Done on 2026-10-10.

- Code: remove the reference room (section, `core/reference_room.py`, sensors, diagnostics,
  options key), the window guard and every use of windows (`core/window_guard.py`, the window
  readings in `vtherm_link.py` and `vtherm_attributes.py`, the binary sensor, the comfort
  correction's and the long-run rule's exclusions), foreign heat (`core/foreign_heat.py`, the
  zone fields and thresholds, the hold time, the learning pause cause, the correction's freeze,
  the long-run exclusion, the binary sensors), the per-zone emitter power factor sensor, the
  per-zone "heat reaches the zone" binary sensor, the zones' rated output and exponent, the
  monitor's "near room temperature". The feature manager keeps "heat available" until I8.2.
- The level step's "restore defaults" text no longer names the reference room.
- Migration: the removed keys go.
- Documents: `SCOPE.md` §5 (reference room, zone algorithms), §6, §7 (the monitor row: windows,
  reference room, foreign heat), §10–§11 where they name them; `docs/plan-0.2-g11.md` (F marked
  withdrawn by I8, with the date); the user guides EN and PL (4.9 "Open windows", every mention
  of the reference room, foreign heat, windows, the zone sensors; the entity tables); the
  technical documents EN and PL (components, the control step); `README.md`, `README.pl.md`;
  `CLAUDE.md`'s verified facts that described these as plugin behaviour (VT's own window facts
  stay).
- J4 impact: the scenarios that look at the comfort correction, the long-run rule, windows or
  foreign heat, and every scenario reading the removed entities; the runner's entity names.

### I8.2 ✅ The feature manager's one value (C1)

Done on 2026-10-11: `core/heat.py` replaces `core/hot_water.py` and `core/emitters.py`. Claude's
calls, provisional (K4, in `SCOPE.md`'s fixed values): "clearly above" is 2 K over the return
and 3 K over the room, with 1 K hysteresis, as the old "near room temperature" had; hot water
with priority still makes it "no" (I6, decision 8); without a flame signal the water alone
decides and the feature is degraded, naming the flame (the missing-data rule), as it is without
a return, naming the return; the feature on the "Features" sensor is renamed `heat_available`
(it was `hot_water`), and `emitter_factor` goes; the stored emitter factors are no longer
loaded or written; the boiler simulator keeps its own EN 442 table. `CLAUDE.md`'s facts name no
zone value, so they stay.

- "Heat available" redefined (the flame and the flow against the return; against the room
  without a return); the emitter power factor leaves the manager; tests with an unknown, missing
  and stale input.
- Documents: `SCOPE.md` (the VT integration), the technical documents (feature manager), the
  user guides (what VT's thermostats show), `CLAUDE.md`'s fact about the manager.
- J4 impact: the scenarios that check VT's thermostat attributes.

### I8.3 Building, curve point, correction range (B5, B6, E2, E3)

Claude's call: two pull requests — I8.3a the correction range, I8.3b the building and the curve
point.

- I8.3a ✅ the correction range (2026-10-11): `limit_flow` has no weather ceiling of its own and
  no curve argument; the field, its defaults, bounds and texts, the "held at the curve plus its
  room for correction" reason go; minor version 12 drops the stored range — one narrower than
  the correction's limit becomes the limit, one under 0.5 K (no correction could pass) switches
  the correction off, so control runs as it did; a session taken with a range compares as
  migrated after the update (`section_as_migrated`); `SCOPE.md` (§3, §5, §7 and the defaults
  table), the user guides' limits, the READMEs, notes on `docs/plan-0.2.md` G2 and
  `docs/plan-0.2-g11.md` B.
- I8.3b ✅ the building and the curve point (2026-10-11): floor area, insulation, thermal mass
  and the entered loss coefficient go — with them the rules of thumb (`core/building.py`) and
  the thermal time constant no function read; the parser takes the heat loss from the design
  load only (a stored loss coefficient, a hand edit, is logged and left out); the building is
  the advanced level's only, its heating threshold "for statistics" and saying it switches no
  heating; the outdoor temperature at the hardest frost is the curve's point, asked in the
  curve step, and in the building only without a curve (full control decides, or for an entry
  from before the mode a section that writes the water); still stored in the parameters
  (Claude's call: the storage stays). Minor version 13 drops the coarse answers and turns an
  entered loss coefficient into the design load it gives at the stored design outdoor and
  indoor reference temperatures (to 0.1 kW, within the form's 0.5 to 200 kW, logged where it
  replaces a stored design load or is brought into range). The building step's own "too warm
  for the curve" check went with the field. `SCOPE.md` §4 and §6, both user guides (the setup
  and the curve, with where to find the hardest frost); the technical documents name no
  building parameter, so they stay.

- Code: the building fields go (the loss coefficient converted); the heating threshold renamed;
  the design outdoor temperature in the curve only (in the building only without a curve),
  renamed; the "correction range" goes (the ceiling then the curve plus the correction's limit).
- Migration as in Claude's calls.
- Documents: `SCOPE.md` (building, curve, limits), the user guides (building, curve, limits; where
  to find the design outdoor temperature), the technical documents (parameters).
- J4 impact: the scenarios that set the curve or the correction's limit; the runner's curve
  answers (`design_outdoor` leaves the building step's answers, `ceiling_band` goes).

### I8.4 Connection, mode, interface (B7, C2, D1, D2)

- Code: two menu items for connection and mode; the mode step opened after a connection change
  that leaves the mode impossible; "room temperature only" hidden; the "Boiler interface" item
  (gateway, MQTT topics as one copy, the thermostat's wiring and setpoint, the restart
  indicator, the hand-back guards with them); the control step's write path and the "monitor
  mode" topology go.
- Migration as in Claude's calls (topics, monitor mode, room values).
- Documents: `SCOPE.md` §4–§5 (the setup, the topologies), the user guides (quick start, the
  connections, the gateway topology), the technical documents (config flow).
- J4 impact: every scenario that walks the options or the setup — the runner's menu items
  (`connection`, `mode`, the new interface item) and its control walk (no `write_path` answer, no
  gateway or MQTT control step).

### I8.5 Signals and freshness (D3–D7)

- Code: the read-backs in the signals; the relay's question and its short list; the wired
  thermostat's fields; the outdoor sensor; freshness limits only for mapped signals, removed
  with them, their text by connection.
- Migration: read-back and CH setpoint as in Claude's calls; a relay entry answers Yes where a
  boiler signal is mapped.
- Documents: `SCOPE.md` §6 (data and sources), the user guides (signals, freshness), the
  technical documents.
- J4 impact: the scenarios on the relay and on freshness; the runner's signal answers.

### I8.6 Boiler and monitor thresholds (E1, E4)

- Code: the visibility rules; the gas rates' unit and text.
- Documents: the user guides (boiler, monitor), `SCOPE.md` where it lists the fields.
- J4 impact: none unless a scenario sets a hidden field.

### I8.7 Circuits and zones: the model (F1, F2, F4, F5)

- Code: circuits as menu items (up to 4, add, remove, names), the circuit's zones and devices and
  emitters, the merged highest water temperature, the circuit type renamed, the zone form
  reduced to "valves close when off", VT's devices read through `vtherm_link.py`.
- Migration as in Claude's calls (zones' circuits and emitters, the merged maximum).
- Documents: `SCOPE.md` §5 (circuits and curves, zone algorithms), the user guides (circuits,
  zones), the technical documents (installation model, `vtherm_link`).
- J4 impact: every scenario that sets circuits or zones; the runner's circuit and zone answers.

### I8.8 Circuits in control (F3, F6)

- Core first, with tests: the boiler's water as the highest need of the circuits asking; the
  floor of a circuit run by other automation; its heat request in the demand (both modes); the
  comfort correction, the curve's room and the critical zone per circuit from its own zones;
  a device-level zone asking in each of its circuits.
- Documents: `SCOPE.md` (control, circuits), the user guides (how heating goes on and off, the
  water temperature), the technical documents (one control step and its diagram), both
  diagrams of the user guides (the control state: "zones or circuits ask").
- J4 impact: the scenarios on demand, the water temperature and the comfort correction; a new
  scenario for a circuit run by other automation, for the testing session.

### I8.9 Control tabs (H)

- Code: the control chain split into the five items; the hand-back method's fields shown after
  it is picked; the write types only where not fixed; the relay's conditional fields; the
  comfort correction in one place; the "off" setpoint where it applies.
- Documents: the user guides (setting up control), the technical documents (config flow).
- J4 impact: every scenario that walks the control options — the runner's `Run.options` and
  `options_walk` choose the items instead of walking a chain.

### I8.10 Texts and documents (A4, C3, C4) — the final check

- Every panel text shortened to the limits of A4, plain, functions not recommendations, EN
  source and PL; the relay's texts (C3, C4); the gas rates, the design outdoor temperature, the
  heating threshold, the outdoor sensor, the wired thermostat.
- The user guides EN and PL rewritten plain: functions, not recommendations; the neutral safety
  facts kept; the ESPHome sample configuration replaced by what its tick confirms; the
  "Changing settings later" and quick-start texts for the new menu.
- The check, against the code, of every document: `README.md`, `README.pl.md`, both user guides
  (with the control state diagram and the entity tables), both technical documents (with the
  control step diagram, the components, the persistent state), `SCOPE.md`, `PLAN.md`,
  `docs/plan-0.2.md` (K1's README list: no recommendation sections), `CLAUDE.md`, the
  translations (key parity and the unused-key test), the diagnostics' fields; a search for every
  removed name (reference room, window, foreign heat, thermal mass, floor area, insulation, loss
  coefficient entered, near room, emitter power, correction range, monitor mode, parallel
  thermostat, summer/winter). The result in `research/`.
- J4 impact: none beyond the texts; the testing session may read the new guides.
