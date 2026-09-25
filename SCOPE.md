# VTherm Smart Boiler — Scope

General scope of the plugin, valid for any installation. Working rules and verified facts:
`CLAUDE.md`. Development plan: `PLAN.md`.

## 1. What it is

A **native Versatile Thermostat (VT) plugin that optimises how a gas boiler runs**: fewer and
longer burns, more condensing, less gas per degree-day — while room comfort stays the same and
the zone algorithms' room models are not damaged.

Its edge over the boiler alone: it knows from VT what the rooms actually need.

**What it is not:** a room controller (rooms belong to VT and its zone algorithms), valve control,
a heat pump controller (excluded), or anything that sends data outside.

## 2. Why a plugin

- VT's central boiler feature is on/off only.
- The VT author declined boiler water control (issues #660, #451) and directs new features to
  plugins (#2010).
- No boiler or OpenTherm plugin exists in the VT ecosystem (checked 2026-09-24).
  `vtherm_pellet_stove` (2026-09-22) drives a central pellet stove — a reference for how a
  plugin controls a heat source.

## 3. Principles

1. **Native** — HACS install and config flow; the user needs no automations, scripts, blueprints,
   helpers or YAML (the test HA may use them).
2. **Universal** — boilers, circuits, zones and zone algorithms described by profiles, wizard
   answers and detected capabilities, never by constants. A missing capability switches the
   feature off with a visible reason. Entities that expose the plugin's data are created by the
   plugin; entities it needs — inputs and write targets — are picked by the user in the config
   flow.
3. **Central water, local valves** — each circuit has one water temperature and its own curve;
   the plugin decides it centrally (flow-setpoint mode), leaves it to the boiler's own curve
   (room-value mode), or supplies a circuit that has its own controller. Zones throttle with
   their valves; information flows from the boiler to the zones.
4. **Do not damage other models** — pause zone-algorithm learning through their public services
   (SmartPI; Auto-TPI only once its service can pause without losing what it learned, §11).
5. **Safe** — the fixed safeguards of principle 11 always apply; limits and the weather-dependent
   ceiling are set by the user, with cautious defaults.
6. **Local** — nothing is sent outside.
7. **English with HA translations** — nothing user-facing hard-coded.
8. **Suggest by default** — automatic changes only within the tuning band.
9. **Weather counted once** — the heating curve is the weather channel; zone signals only
   correct it. A zone algorithm with an outdoor term of its own (TPI's `tpi_coef_ext`, SmartPI's
   `u_ff1`) counts weather a second time; the documentation says how to set it alongside the
   plugin.
10. **Two kinds of users** — a regular user gets working defaults, few questions and plain
    verdicts; a power user gets every parameter, diagnostics and overrides. The level changes
    what is visible, never how the plugin behaves. When switching from advanced to simple, the
    user chooses whether to restore advanced settings to their defaults or keep them hidden;
    kept settings stay active, and the simple view shows that some advanced settings differ
    from defaults.
11. **The user decides, informed** — control choices belong to the user: write path, hand-back
    method, control mode (flow setpoint or room values), limits, curve, demand thresholds,
    learning pauses, monitoring period. Each has a cautious default and a description of what it
    does and what it risks — in the config flow and in the documentation. Fixed safeguards, not
    options, for every write (flow setpoint, CH on/off, modulation cap, room values to the
    boiler): no write without fresh input data; values within hard limits, except "off" and the
    hand-back value, which have checks of their own (§7); nothing written to the boiler's
    persistent memory — control writes only to targets whose values expire or that the device
    holds (§7); a write-rate guard against a runaway loop (a repeated write waits at most one
    control step); read-back of every write, or the value marked unverified when the device does
    not echo it; a value changed from outside written again at most once, then an alarm, never a
    fight; hand-back on every exit with every override cleared, never held back by a guard, and
    retried until it is confirmed; control only with a known hand-back and, for setpoint control,
    a source for the confirmed setpoint; on a failed outdoor sensor a safe fallback setpoint,
    never zero heat, or in room-value mode the room values cleared so the boiler's own control
    carries on; the DHW-enable bit kept as it was. The values of limits are options; the guards
    themselves are not, and none of them decides whether to heat (principle 12). On/off without
    feedback (a relay, an override the device does not echo) gives no boiler data to be fresh:
    freshness applies to the inputs of the decision, and the write stays marked unverified.
12. **VT decides whether to heat** — the plugin replaces VT's central boiler: heating goes on
    and off with the zones' demand, at once and in both directions; the plugin decides only how
    warm the water is — the curve, the limits and the ramp. Frost protection is the one
    exception, a safety net (§7). Nothing the plugin counts or times holds heating off, or on,
    against VT: an old boiler with a high minimum output cycles a lot on its own, and blocking it
    would leave the house cold. Frequent starts are information — an alarm with its threshold,
    and the verdict. (The user's decision, 2026-09-25.)
13. **Bounded learning** — every value the plugin adapts or learns by itself, now and in later
    releases, follows fixed rules that are not options: (1) a firm band around its starting
    point (the user's entry or the default), never left; (2) a limited rate of change, per hour
    and per day; (3) it moves only while every other criterion holds — comfort in every zone, no
    zone overheating, cycling not rising, every limit kept — and steps back when another one
    gets worse; (4) the aim is a "good enough" band, not an optimum: learning stops inside it;
    (5) it freezes in unusual conditions — hot water, foreign heat, data gaps, hand-back,
    extreme weather; (6) at the band's edge it informs instead of pushing on — the starting
    point is probably wrong; (7) every learned value is visible and can be reset, and hand-back
    resets it. Pushing one quantity to its ideal can break another: warm one room, overheat the
    rest. (The user's decision, 2026-09-25.)

## 4. User levels

| Area | Regular user | Power user |
|---|---|---|
| Wizard | boiler class and profile suggestion, gateway topology, control mode, circuits and zones, a few coarse choices (insulation, thermal mass, emitter type) | every profile field, measured values, building load from own calculation |
| Assessment | a verdict: control is worth enabling or not, and why | all metrics, per outdoor-temperature range, raw cycle data |
| Control | off by default; once enabled, control runs automatically in the chosen mode; curve changes: suggestions (default) or automatic within a preset band (Low / Medium / High) | Custom band, per-parameter overrides, manual edits of learned values, reset to profile |
| Alarms | sensible default reactions | reaction and thresholds per alarm type |
| Diagnostics | hidden | model parameters, confidence, sample rejection reasons, emitter power factor |
| Learning | on, within safe bounds | pause and resume, change-per-day limit, learning windows, zone-algorithm protection settings |

Switching advanced → simple offers "restore advanced settings to defaults" (unchecked by
default). It never touches learned values; those have their own "restore profile defaults"
button.

Boiler profiles — with "reset to profile" and "restore profile defaults" — come later; until
then the boiler class gives the defaults.

## 5. Hardware, circuits and zone algorithms

### Boilers — any boiler that talks to HA

What the plugin can do depends on what the integration can write:

| Class | Examples | Scope | From release |
|---|---|---|---|
| 1. Flow setpoint (+ modulation cap) | OpenTherm (OTGW, DIYLess, ESPHome), EMS-ESP, some ebusd | full | 0.2 |
| 2. Curve parameters only | BSB-LAN, ViCare | curve tuning, summer/winter; limited anti-cycling | later |
| 3. On/off | relay | minimal | later |
| 4. Read-only | any | monitor | 0.2 (built as 0.1) |

- Reading works with any integration: the user maps each signal to an entity in the config flow;
  capabilities follow from the filled fields.
- Control mode, one at a time, the user's choice: **flow setpoint** (from 0.2) — the plugin
  decides the water temperature from its curve and writes the setpoint; **room values** (from
  0.3) — the plugin sends the reference room's temperature and setpoint (§5, "Reference room")
  and the boiler's own curve and room influence decide the water temperature; in this mode the
  plugin changes neither the curve nor the water temperature. Room-value mode needs a device that
  takes room values (OpenTherm ID 24 / 16 through built-in support, or entities the user picks).
- Writing (from 0.2), in this order: (1) a writable entity the user picks — any integration,
  including entities the user made; (2) built-in support for devices without such an entity —
  first OTGW, through `opentherm_gw` or its firmware over MQTT; (3) otherwise monitor only, with
  the reason shown.
- Control is enabled only with a known way to hand control back, chosen by the user: for built-in
  OTGW `CH=1`, then `CS=0` (default) — the gateway keeps a `CH=0` through `CS=0` — or monitor
  mode (only with a physical thermostat, see "Gateway topology"); for a picked entity a value,
  declared with its effect (the device's own control resumes, or heating stops) and done only
  once read back, the device's own timeout, or a switch. A hand-back to a target that is
  missing, `unavailable` or `unknown` has failed: Home Assistant drops such a call without an
  error. What hand-back leads to depends on the topology.
- Class 2: the plugin stores the original curve parameters and restores them on every exit, and
  writes persistent parameters rarely (boiler memory wear).
- Class 3 has no feedback from the boiler: decisions rest on zone and outdoor data, writes stay
  unverified, and the on/off guards apply (minimum on and off times, a cap on switchings per
  hour). What stale inputs lead to — boiler off, or back to the previous controller — is the
  user's choice, with its risks described.
- A second circuit controlled through the boiler (e.g. OpenTherm CH2) comes later; 0.2 writes
  one circuit: control needs exactly one configured circuit fed by the boiler flow, unmixed or
  passive fixed; with any other layout the monitor runs and a blocker says why. The data model
  covers several circuits from the start.

### Gateway topology

How the gateway is set up decides what the plugin may do and what hand-back leads to. Other
gateways have similar variants (DIYLess and ESPHome as master or pass-through; EMS-ESP with or
without a controller). F3 found that neither the OTGW's mode nor a connected thermostat can be
read reliably through Home Assistant (the mode is read only when the gateway connects; there is
no presence entity).

| Gateway mode | Thermostat | Who controls the boiler | What the plugin may do | Hand-back leads to |
|---|---|---|---|---|
| monitor | physical | the thermostat; the gateway only listens | monitor only | — |
| gateway | physical | the thermostat; the gateway may override its values | flow setpoint (override `CS`) or room values (override the thermostat's room temperature and setpoint) | overrides cleared — the thermostat takes over, heating continues |
| gateway | none | the gateway acts as master | flow setpoint; room values (injected with `AA`) if the boiler heats on its own curve without `CS` | overrides cleared — heating stops |
| monitor | none | nobody | nothing | — |
| — | virtual — a controller on the HA side (e.g. DIYLess or ESPHome as master) | that controller | through its entities: flow setpoint if it exposes one, room values if it runs its own regulator | the user's chosen method for its entities |

- The topology is part of the configuration, declared by the user in the config flow (F3: it
  cannot be read through Home Assistant).
- Control modes the topology does not allow are unavailable, with the reason shown.
- Hand-back stops the plugin's heating demand. Without a thermostat heating stops until the plugin
  or the user acts; the config flow states this risk. Frost protection then rests on the boiler's
  own frost protection, if it has one. A lost boiler link is no exception: in every topology it
  raises an alarm and control hands back — stand-alone, heating stops (the user's decision,
  2026-09-25).
- The plugin never changes the gateway mode on its own; the gateway stores its mode
  persistently (F3). 0.2 hands back with `CH=1`, then `CS=0`; monitor mode as a hand-back method
  is not offered.
- Without a thermostat, an HA outage longer than about a minute stops heating: `CS` lapses
  (F3); the config flow and the control switch say so.
- An emulated OpenTherm thermostat inside the plugin stays for later (§9).

### Topology

Boiler → circuits → zones. One boiler per HA instance, in a single config entry; the data model
covers several circuits from the start.

### Circuits and curves

Underfloor and radiators need different curves. Every circuit has its own curve, limits and
emitter type; the burner is shared.

| Circuit control | Example | What the plugin does |
|---|---|---|
| Unmixed, shared | radiators and underfloor on one loop, no mixing valve | one curve for the loop, capped by the most sensitive emitter (underfloor maximum flow) |
| Controlled through the boiler | OpenTherm CH2, EMS-ESP HC2, the boiler's mixing module | own curve and setpoint per circuit; boiler flow = highest circuit need + mixing margin |
| Controlled separately | external mixing controller, a mixer driven by HA, a separate weather controller | reads (or is told) the circuit's target and keeps boiler flow above it + margin; never fights that controller |
| Passive fixed | thermostatic mixing valve | declared fixed temperature; boiler flow kept above it |

- Each VT zone is assigned to a circuit in the wizard; zone arbitration (the critical zone) runs
  per circuit.
- Anti-cycling, DHW and the modulation cap act on the boiler (shared burner); curve tuning, the
  weather-dependent ceiling and the seasonal tune-up act per circuit.
- Condensing depends on the combined return of all circuits.

### Zone algorithms — any

- Core uses VT data only: `on_percent`, valve positions, room temperature vs target, device power.
- Detected extras: SmartPI (better signal, bootstrap state, learning pause), Auto-TPI (learning
  pause).
- A learning algorithm without a pause service gets an explicit warning, which states what its
  advice costs.
- Per zone the plugin publishes two values, as entities and feature-manager properties
  (feature manager from 0.2): **hot water available** (heat is reaching the zone — no while DHW
  is active or while the flow has fallen near room temperature; unknown while the flow signal is
  unknown or stale)
  and **emitter power factor** (emitter output now versus reference, from emitter type and size,
  valve opening, water and room temperature). The factor is computed only for zones that are
  heating; otherwise the last value is held; it is unavailable, with a reason, when data is
  missing. Zone algorithms do not read these values today (§9).
- DHW charging pauses learning only in zones calling for heat (valve open); zones with a closed
  valve keep learning how the room cools. Learning resumes when the flow is back within a
  tolerance of its setpoint (3 K either way), and at the latest after a longest pause (1 h); a
  pause and a resume are read back from the algorithm's flag — a pause that did not take is not
  the plugin's, a resume is sent again every minute until the flag reads on — and learning the
  user switched off before a pause is never resumed. A switch-off during the plugin's own pause
  cannot be told from the pause: the flag reads off either way.
- By default the water temperature changes slowly (ramp, §7), so zone algorithms can follow it.

### Reference room

- External boiler controllers (DIYLess, ESPHome OpenTherm and similar) need one room temperature
  and setpoint. The plugin publishes a reference room: selected zone, its temperature and
  setpoint, the deficit and a status. Strategy: largest deficit (default), a chosen zone, or an
  average. Only zones taking part in heating with valid readings count; temperature and setpoint
  come from the same zone — for the average, from the same set of zones; the choice changes only
  on a clear difference; no invented fallback —
  "no active zone" and "no valid measurement" are explicit states.
- In room-value mode (a control mode from 0.3, off by default) the reference goes to the boiler as
  OpenTherm room temperature (ID 24) and room setpoint (ID 16) through built-in support, or to
  entities the user picked. Safeguards: sent only from a valid reference room and within
  plausible room bounds; rate-limited; cleared — never frozen at the last value — when no valid
  reference exists; cleared on hand-back. Only a boiler with room influence enabled acts on
  these values, and then it changes its flow temperature with them — which is why they are
  guarded.

## 6. Data and its sources

| Group | Examples |
|---|---|
| Boiler specification | type, min/max power, modulation range, max CH setpoint, condensing, DHW type (storage / combi), gas consumption min/max |
| Boiler settings (installer menu) | CH hysteresis, anti-cycle time, pump overrun, summer threshold, built-in curve |
| Installation | circuits, circuit control type, curve per circuit, emitter types, max underfloor flow, mixing valve, shared CH/DHW return, bypass, water volume |
| Building (whole house, in kW) | design heat load or loss coefficient, heating threshold, thermal mass, insulation class |

- Every parameter has a source and a confidence: class default → user-entered → measured →
  learned. A mismatch between declared and measured values is a diagnostic finding.
- Regular users answer a few coarse questions; power users can fill every field (§4). Manual
  entry always wins; boiler data read from the integration only suggests and waits for
  confirmation.
- The user's own heat balance gives a first estimate of the building's heat loss; an estimate
  from gas bills comes later.
- The building model is the whole house in kW — the boiler's load. It does not duplicate the
  zone algorithms' room models.

## 7. Features by stage

| Stage | Delivers | Controls the boiler |
|---|---|---|
| **Monitor** | starts per hour, burn time, condensing share, gas per degree-day, connection state; alarms with selectable reaction (info; hand back from the first control release); **early warning** (flue gas, ignitions, pressure, hysteresis); **report explaining changes** (weather / DHW / settings); condensing indicator (later); outdoor sensor check; DHW and foreign-heat detection; **forecast recording** (FC0); **reference room** (§5); **signal check** — which optional signals are present and fresh | no |
| **Advisor** | curve and anti-cycling suggestions with rationale and an "apply" button | no |
| **Curve (strategy A)** | replaces VT's on/off and user automations; curve per circuit; effective outdoor temperature; **summer/winter switch from a multi-day forecast** (FC1); ramp; keep-alive; frost protection; learning pauses (DHW, foreign heat, large changes) | yes |
| **Anti-cycling** | duty cycling at low load, starts-per-hour budget, modulation cap; **planning from the forecast** — mild hours ahead → long cycles from the start (FC2) | yes |
| **Curve tuning (strategy B)** | tuning band Low / Medium / High / Custom (3 / 8 / 15 % defaults); manual / semi-automatic / automatic; **seasonal tune-up** — a little lower each day while rooms hold comfort; per circuit | yes |
| **Forecast** | **anticipation for slow emitters** — raise water earlier before frost, lower it earlier before a warm or sunny day (FC3); lead time learned per circuit | yes |
| **DHW** (optional, storage tank only) | fast charging, schedule aligned with learning windows | yes |

**Across all stages**

- **Water-side learning:** from HA history when it covers a heating season, then live; bounded
  change per day.
- **Foreign heat:** other heaters (fireplace, stove, electric heater) — **not** the sun. Switch or
  sensor → learning paused in affected zones.
- **DHW pauses learning** — in zones calling for heat (§5) and, with a shared return, the
  plugin's own data too.

**Control base — from the first control release**

How control decides (principle 12):

- Heating goes on and off with the zones' demand at every control step (10 s), at once and in
  both directions. The decision interval (an option, default 5 min) applies only to the water
  temperature.
- Demand comes from VT's zones against thresholds — number of zones, total power, valve
  opening — each usable alone or with the others, as in VT, and checked against the configured
  zones. Its source follows the VT type (valve opening, duty cycle, heating action) and respects
  VT's minimum activation time. A zone counts only while its state is known: a VT climate that
  is `unavailable`, or whose mode is unknown, is unknown — never "no demand". With no zone known,
  heating runs on the curve; with some zones unknown, the decision rests on the known ones, and
  a zone unknown for longer than a limit raises an alarm, as frost protection cannot see it. A
  zone in "auto" or heat_cool heats by its heating action and duty cycle.
- VT's central mode (Auto, Stopped, Heat only, Cool only, Frost protection) acts through the
  zones: VT applies it only to thermostats that follow it, the plugin sees the result in each
  zone's demand, and zones outside the central mode still count. "Stopped" is not a hand-back:
  control goes on, and with every zone stopped there is no demand, so heating stays off, while
  frost protection still watches (the user's decision, 2026-09-25).
- Summer and winter come from VT: the plugin has no summer switch of its own. With VT's zones
  off it does not heat; with a zone calling it heats. The monitor keeps the building's heating
  threshold, for its degree-days.
- Frost protection is the one case where the plugin heats without VT's call: when a watched zone
  — every zone (default), or one zone the user picks — falls below the frost limit, heating runs
  on the curve until the zone is back above the release temperature. Implausible temperatures
  are rejected. Frost heating that goes on without the zone warming raises an alarm; it is not
  stopped.
- The water temperature follows the curve on the effective outdoor temperature, within the
  limits, and changes at the ramp's rate, in K per minute, at every step.
- The outdoor temperature comes from the outdoor sensor, else from the weather entity; a sensor
  found stuck or deviating is replaced in the same way, with an alarm. Without either, the
  fallback setpoint applies: the curve at the last effective outdoor temperature for a limited
  time, then at the design outdoor temperature; a fixed fallback value the user sets replaces
  both.
- Comfort correction (principle 13): while a zone's valve is fully open and its room is still
  short of its setpoint, the water rises above the curve — at most +3 K, by 1 K per 30 min and
  only while heat flows; it falls twice as fast, and a zone without opening data does not block
  the fall; it does not rise while another zone is more than 1 K over its setpoint; it is reset
  at hand-back and at the end of a session; when it stays at +3 K for hours, the user is told.
  The zones' own PI integrators (SmartPI, TPI) act in series with it; the documentation
  describes the interaction and the VT settings recommended with it.
- "Off" goes through the heating switch where one is configured, else as a low setpoint
  (provisional, §11).

Fixed safeguards (principle 11), for every write — flow setpoint, CH on/off, modulation cap and
room values:

- No write without fresh input data — the data the decision uses: for the boiler, flame and flow
  known. One freshness rule serves the monitor and control: a signal is fresh while its entity is
  available and, if the user set an age limit for it, while its last report is within the limit.
  A steady reading is not a stale one — many sources report only on change — so age counts only
  with a user-set limit; without one, a source that freezes without going unavailable is not
  caught, and the option's description says so. Gateway connectivity is part of freshness (its
  entities go unavailable). A 0 from a value outside the gateway's regular polling counts as
  unknown, and bounds fall back to safe defaults (0.2 reads no such values). On/off without
  feedback has no boiler data: its inputs are the zones and the outdoor temperature.
- A lost boiler link — flame or flow not fresh — stops every write; after 5 min an alarm is
  raised and control hands back: with a thermostat, the thermostat takes over; stand-alone,
  heating stops. A failed outdoor sensor is not a lost link: it leads to the fallback setpoint,
  never to zero heat.
- Every value within hard limits, with two exceptions that have checks of their own: "off" — a
  low setpoint below the hard minimum and within the target's range, on OTGW never below 8 °C,
  as lower values do not lapse — and the hand-back value. The weather ceiling never falls below
  the hard minimum. Room values stay within plausible room bounds.
- Nothing is written to the boiler's persistent memory: control writes only to targets declared
  expiring (repeated every 30 s) or held (the device keeps the value and repeats it itself;
  written on change). A setpoint target declared persistent, or of unknown write type, keeps
  control off, with the reason shown; a heating switch declared so is not used, and "off" goes as
  a low setpoint instead (the user's decision, 2026-09-25).
- A value goes to an entity in the entity's own unit (°C, °F or K), rounded to its step, and its
  range is checked in the same unit; an entity in any other unit keeps control off.
- A write-rate guard against a runaway loop: a write repeated within one control step waits for
  the next one.
- Every write is read back; a command the boiler ignores is reported, never assumed applied. The
  state shown is the value the boiler confirmed, or unknown — never the requested one. Heating
  on and off is confirmed where the device echoes it, and marked unverified where it does not. A
  read-back taken from the written entity itself confirms nothing and is marked unverified. An
  OTGW read-back is confirmed by the gateway: `TSet` shows what the gateway sends, not what the
  boiler accepted.
- A value changed from outside is written again at most once; then an alarm is raised and every
  write stops, heating on and off included, whatever the alarm's reaction — the plugin never
  fights another controller. A value never confirmed, because the read-back shows another steady
  value from the start of the session, counts as changed from outside (the user's decision,
  2026-09-25); a read-back still showing the plugin's previous value only means ignored.
  Keep-alive repeats of an expiring override are not rewrites. A read-back that falls back to its
  value from before the session is the plugin's override dropped — a boiler's Data-Invalid answer
  clears an OTGW's override, a gateway reset loses it — not another controller: it is sent again
  at once, and reported as ignored when it keeps falling back.
- Every exit — unload, reload, error, data loss, an alarm set to hand back — stops every loop but
  the hand-back's own retry, hands control back and clears every override.
- A hand-back write is not a control decision: no guard holds it back — not freshness or the
  write-rate guard — and its value (e.g. `CS=0`) is not bound by the hard limits. It is checked:
  a missing, `unavailable` or `unknown` target means it failed, and a value hand-back is done
  only once read back. A pending hand-back is stored, shown and retried every minute until it is
  confirmed, and it outlives restarts and option changes: a change that would drop it is
  refused, or a unit that only hands back keeps retrying, with a repair issue.
- When the plugin takes the boiler, it stores a "controlling" marker at once; after a restart
  without a clean stop, a hand-back is pending until control resumes.
- Control only with a known hand-back and, for setpoint control, a source for the confirmed
  setpoint.
- Room values go to the boiler only from a valid reference room; without one they are cleared.
  In room-value mode a failed sensor clears the room values, and the boiler's own control
  carries on.
- The DHW-enable bit stays as it was before the plugin took over.

How control resumes after it stopped:

| Cause | Control resumes |
|---|---|
| An alarm set to hand back, an outside change included | when the user switches control off and on — a latch: it survives a restart, shows its cause and never expires on its own |
| An internal error | at any change of the control switch |
| A lost boiler link | on its own, once the data is fresh again |
| A blocker — a missing setting, the monitoring period, VT's central boiler configured, Home Assistant starting | on its own, once the blocker is gone |

In room-value mode the boiler runs its own control: the curve, ramp, anti-cycling and flow limit
options do not apply; the fixed safeguards do.

Options, each with a cautious default and its risks described:

- Boiler demand from device count, total power or valve opening, each criterion alone or with
  the others.
- Ramp: how fast the water temperature may change, in K per minute, so zone algorithms can
  follow.
- Decision interval for the water temperature.
- A fixed fallback setpoint, replacing the curve-based one on outdoor-sensor failure.
- Values of the hard limits and room-value bounds. The write-rate guard and the hand-back's
  retry are fixed, not options.
- The "off" setpoint, where "off" is a low setpoint.
- Write type of each picked write target — the setpoint entity and the heating switch each
  declare their own: **expiring** override — repeated every 30 s so it does not lapse (risk, if
  the entity is in fact stored in the boiler's memory: each repeat wears it, about 2,900 writes
  a day); **held** — the device keeps the value and sends it on itself (e.g. an ESPHome
  OpenTherm master), written on change only; **persistent**, or **unknown** (default) — not
  written: control stays off for a setpoint target, and a heating switch is left unused.
  Built-in OTGW repeats `CS` every 30 s.
- A heating on/off read-back: none by default — heating on/off is then shown unverified (risk:
  another controller switching it goes unnoticed; picking the thermostat's request instead of
  what the boiler receives stops control as an outside change).
- An age limit per signal (freshness): none by default (risk: without one a frozen source is not
  caught; with one shorter than the source's reporting interval, control stops in steady
  weather).
- Frost protection: its limit and release temperature, and whether it watches every zone
  (default) or one zone.
- Comfort correction on (default) or off; its bounds are fixed (principle 13).
- Learning pauses on (default) or off.
- The reaction to each alarm: information, or hand control back.
- Low-flow warning when all valves are closed while the pump runs — needs a pump-running or
  CH-active signal.

Defaults of the safety options and why (the user reviews them at K4):

| Option | Default | Why |
|---|---|---|
| Control | off; available after 7 days of monitoring | the user sees the verdict first; control is experimental |
| Heating curve | none — the design flow is entered | a wrong curve under-heats or wastes gas; no silent default |
| Emitter type | none — the user chooses | underfloor needs its own maximum flow; a wrong type hides that |
| Hard minimum / maximum | 25 / 70 °C | below 25 °C a radiator gives little heat; 70 °C covers the usual radiator design points and stays under boilers' maximum |
| Weather ceiling | the curve + 10 K | bounds how far anything may raise the water above the curve |
| Ramp | 1 K per minute | zone algorithms follow gradual changes; larger swings pause SmartPI's learning |
| Decision interval | 5 min | VT's default cycle |
| Write type of a picked target | unknown — control stays off until the user declares it expiring or held | the plugin cannot tell the type itself, and a wrong guess wears the boiler's memory |
| "Off" setpoint | 10 °C | far below any heating value; on OTGW never below 8 °C |
| Hand-back value (entity) | none — entered with its effect | 0 may mean "no heat" on one device and "own control" on another |
| Fallback setpoint | the curve at the last effective outdoor temperature, then at the design outdoor temperature | never zero heat; the valves keep rooms from overheating |
| Frost limit / release | 5 / 7 °C | above freezing with a margin, below any comfort setpoint |
| Frost protection | every zone | the safety net covers the whole house |
| Demand threshold | one zone | any zone calling heats, as with VT's central boiler |
| Comfort correction | on, up to +3 K | helps a room its emitter cannot heat on the curve, bounded so the others do not overheat |
| Learning pauses | on | keep swings the plugin causes out of SmartPI's model |
| Alarm reaction | information; an outside change hands back | another controller is writing — never fight |
| Freshness age limit | none — availability only | many sources report only on change; a limit on such a source would stop control in steady weather |

### Forecast roadmap

| Step | Use of the forecast | Stage | Release |
|---|---|---|---|
| FC0 | record forecast snapshots from day one | Monitor | 0.1 |
| FC1 | summer/winter switch from a multi-day forecast, without flip-flopping | Curve | 0.3 |
| FC2 | anti-cycling planning for mild hours ahead | Anti-cycling | 0.3 |
| FC3 | anticipation for slow emitters (underfloor) | Forecast | 0.5 |
| FC4 | wind and sun correction of the curve | later | later |

FC0 comes first because the recorder does not keep forecasts: HA provides them only through the
`weather.get_forecasts` service, not as entity attributes (verified 2026-09-24). The plugin
stores snapshots itself to measure forecast error per horizon and learn the lead time — FC3 has
nothing to learn from without them. Forecasts are read from HA weather entities; the plugin
itself never goes online.

Source: any HA weather entity the user picks. An hourly forecast enables FC2 and FC3; a daily-only
source switches them off with a visible reason.

## 8. Prior art — what we take

### SAT (Smart Autotune Thermostat)

Ideas only — re-implemented from scratch. No SAT code is copied, so SAT's GPL-3.0 does not apply
to this plugin.

| Idea | SAT module | Where here |
|---|---|---|
| Duty cycle from overshoot: `(requested − reference) / (actual flow − reference)` | `pwm.py` | Anti-cycling |
| Starts-per-hour budget instead of a fixed pause | `pwm.py` | Anti-cycling |
| Gating of learning samples (stable modulation, flow near setpoint, no duty cycling) | `minimum_setpoint.py` | Water-side learning |
| Return temperature as a correction of the minimum setpoint | `minimum_setpoint.py` | Curve tuning (condensing) |
| Bounded parameter nudges with an average of recent optima | `heating_curve.py` | Curve tuning |
| Fresh flow read right after writing a setpoint | `mqtt/opentherm.py` | Built-in OTGW support |
| Overshoot calibration procedure | `overshoot_protection.py` | Assessment (history first, calibration only without data) |
| Gas estimate from modulation | — | Monitor |

**Not taken:** its room controller, the curve as the main mechanism, its constants (e.g. a
minimum burn of about three minutes), manufacturer files.

**Where we do better:** control handed back on unload, connectivity checked before writes,
explicit keep-alive — SAT sends the setpoint only when its loop runs.

### Google Nest

| Nest feature | Here | Stage |
|---|---|---|
| Long burns at low water (OpenTherm + True Radiant) | main strategy: low, long, rare | Curve, Anti-cycling |
| Seasonal Savings | seasonal tune-up of the **curve** (not room setpoints) | Curve tuning |
| Home Report / Energy History | report explaining changes (weather / DHW / settings) | Monitor |
| Furnace Heads-Up | early warning: flue gas, ignitions, pressure, hysteresis | Monitor |
| Leaf | condensing indicator | Monitor |
| Current weather and a forecast of the next hours | effective outdoor temperature, then the forecast roadmap | Curve, Forecast |
| True Radiant early switch-off for slow systems | earlier water reduction for underfloor | Forecast |
| DHW control over OpenTherm | fast charging, schedule | DHW |

**Not taken:** Auto-Schedule, Home/Away, Early-On, Sunblock, time-to-temperature (room and
occupancy layer — VT's job); Rush Hour Rewards (not relevant to gas).

## 9. Later / excluded

**Later (out of current scope):** load-based setpoint (strategy C); wind and sun correction of the
curve (FC4); gas-usage modes (eco / balanced / comfort); emulated OpenTherm thermostat; built-in
support for more devices without writable entities (EMS-ESP, ebusd, BSB-LAN, as needed);
proposal to the SmartPI and adaptive TPI authors to read the two zone values (a fork only for
tests).

**Excluded:** heat pumps, room regulation, valve control, sending data outside.

## 10. Assess before control

The Monitor stage lets any user assess their installation before enabling control:
cycling at low load, burn times, condensing share and the building load versus the boiler's
minimum power. Regular users get a verdict with the reason; power users get the underlying
metrics. Control becomes available after a minimum monitoring period (default 7 days); the
verdict stays visible and the user decides. The period counts calendar days from the first
setup; the user may lengthen it, up to 60 days, but not shorten it.

The verdict covers a window the user may set — by default every day with data. It is built
from daily summaries the plugin keeps for up to a year, filled at start from the recorder as far
back as the recorder reaches, so it does not depend on the recorder's settings. Degree-days are
the hourly integral of how far the outdoor temperature is below the building's heating
threshold; gas per degree-day leaves out the gas for hot water where hot-water heating is known.
Starts per hour count the hours with heating.

## 11. Open decisions

- Learning pause during long anti-cycling pauses (water near room temperature while a zone calls
  for heat) — decide on data from the first installations (before 0.3).
- Room values with an OTGW (0.3): with a physical thermostat (override) and without one (`AA`
  injection — does the boiler heat on its own curve without `CS`); firmware version that added
  `RT` and `BS` (before 0.3).
- How "off" is sent without a heating switch (provisional, below): the user decides it after the
  research on the devices — whether a low setpoint stops the CH pump (`docs/plan-0.2.1.md`, L4).
- The provisional decisions below, marked (K4), are confirmed or changed by the user at the
  review before anything reaches a real boiler (`docs/plan-0.2.md`, K4).

**Decided**

- License: **Apache-2.0** (2026-09-24). All logic and code are written from scratch; no code is
  copied from any project, other projects are sources of ideas only. A `NOTICE` file carries
  the attribution that copies and derivatives must keep.
- Tuning band: Low / Medium / High = 3 / 8 / 15 % of the flow-over-room difference at the current
  outdoor temperature, never below 1 K; Custom for power users. Beyond the band: suggestions only.
- Clocks: a control step every 10 s, which checks freshness and switches heating on and off with
  the zones' demand; the water temperature is decided every decision interval (an option,
  default 5 min, VT's default cycle — the plugin does not read the zones' cycles); keep-alive
  every 30 s where the write path needs it — OTGW requires `CS` at least once a minute, 30 s
  keeps a margin.
- OTGW equipment database: not bundled. The plugin uses the boiler's MemberID and supported
  messages when the integration exposes them; boiler profiles are our own.
- 0.2 controls in flow-setpoint mode only; room-value mode comes in 0.3 (2026-09-24).
- 0.2 supports every write path, for any installation: a writable entity the user picks, and
  built-in OTGW through `opentherm_gw` or its firmware over MQTT (2026-09-24).
- GitHub and every publication come at the end of 0.2; the first pre-release is 0.2.1b1 — 0.2.1
  corrects 0.2 after its review — and monitors first because control is off by default
  (2026-09-24, 2026-09-25).
- Writable flow-setpoint entities (research F1, 2026-09-24): ESPHome `opentherm` (`number`, held
  by the ESP, which repeats it itself), DIYLess (ESPHome, or its own `climate`), EMS-ESP
  (`selflowtemp` expiring — repeated within a minute; `heatingtemp` persistent). OTGW firmware up
  to 2.0.0-alpha has none; its MQTT commands are the path. All three kinds occur, so a picked
  entity has a declared write type: expiring, persistent, held, or unknown. Control writes only
  to expiring or held targets; a persistent or unknown one is never written (the user's decision,
  2026-09-25).
- OTGW (research F3, F5–F7): the topology is declared in the config flow — the gateway's mode
  and a connected thermostat cannot be read reliably through Home Assistant. With a thermostat,
  every fallback (`CS=0`, expiry, Home Assistant stopping) returns control to the thermostat;
  stand-alone, every fallback ends heating; monitor mode allows no control. `CS` of 8 °C or more
  lapses unless repeated within a minute; below 8 °C it never lapses, so the plugin never writes
  it and writes "off" as `CS` of at least 8 °C with CH off. The gateway mode is stored in the
  gateway; the plugin never changes it and never sends `HW=` or `BW=`, so the DHW-enable bit
  stays as it was. The firmware's `TSet` echoes what the gateway sends, not what the boiler
  accepts. Hand-back sends `CH=1`, then `CS=0`: the gateway keeps a `CH=0` through `CS=0` until
  its PIC resets and applies it to any later `CS` and to an on/off thermostat's demand, while
  `TSet` still carries `CS` with `CH=0` (PIC firmware 6.6, found by the review of 2026-09-24).
- Auto-TPI (research F2): without VT's central boiler, Auto-TPI never learns in zones flagged
  "used by the central boiler"; the plugin raises a repair issue naming them, which states what
  its advice costs. It does not pause Auto-TPI in 0.2, because `set_auto_tpi_mode` is not a pure
  pause (K4).
- VT feature manager (research F4): registered once VT's API exists; a thermostat already
  running picks it up at VT's next reload, which the plugin never triggers.
- The user's decisions of 2026-09-25: VT decides whether to heat, nothing the plugin counts or
  times holds heating against VT, and what the plugin learns stays within firm bounds
  (principles 12 and 13); frost protection stays as the one exception, for every zone or one
  picked zone; summer and winter come from VT; VT's central modes act through the zones' demand,
  and "Stopped" is not a hand-back; a lost boiler link raises an alarm and hands back in every
  topology — stand-alone, heating stops; the comfort correction's bounds; nothing written to the
  boiler's persistent memory; a value never confirmed against another steady value counts as
  changed from outside; with some zones unknown the known ones decide, with an alarm (§7). For
  the monitor: the verdict's window, degree-days and starts per hour (§10); "hot water
  available" is unknown while the flow is (§5).
- Provisional control decisions (K4): control only for one circuit fed by the boiler flow and a
  boiler of the class "flow setpoint"; the curve's design flow is entered, never defaulted;
  control refused while VT's own central boiler is configured and during the monitoring period;
  the first setpoint of a session is the curve's value, not ramped from the current flow;
  comfort correction on by default; alarm reactions information or hand-back.
- Provisional write decisions (K4): boiler data is there while flame and flow are known — a
  steady reading is not a stale one, as many sources report only on change; its age counts only
  with a user-set freshness limit; without the data nothing is written, and after 5 min an alarm
  is raised and control hands back (stand-alone, the gateway stops heating within a minute of the
  last keep-alive). A failed write is sent again at the next step; the setpoint goes before
  heating on/off, which is repeated with an expiring setpoint. An outside change is rewritten
  once, and within a day never again, whatever the plugin wrote in between; the default reaction
  is hand-back. A lapse the plugin caused itself (silence while data was stale) is not an
  outside change. "Off" goes through the heating switch where one is configured (built-in OTGW:
  `CH=0` with `CS` of at least 8 °C), else as a low setpoint, whose effect on the CH pump the
  research on the devices settles. A heating switch is turned back on at hand-back. A timeout
  hand-back needs expiring writes. A failed hand-back is shown and retried every minute until it
  is confirmed; at Home Assistant's stop the hand-back runs before integrations stop. Latches
  survive a restart; the control switch comes back as it was and control waits for its
  blockers.
- Learning pauses (SmartPI) only while control runs; the water-swing check follows the heating
  setpoint, not the low "off" value (K4).

## 12. Release

Public from 0.2.1, the first release — 0.2 corrected after its review: a GitHub repository,
created at the end of 0.2.1 and installed through HACS as a custom repository. 0.2.1 passes the
test environment, then runs on the author's installation — monitoring first, since control is
off by default — as a pre-release, then as a release. HACS installs only from public
repositories, so the repository is public from the first pre-release. The plugin needs Home
Assistant 2026.9 or later, the version it is tested on. Submission to the HACS default list and
the VT plugin list later (HACS review takes months). Creating the repository and every
publication need the author's consent.
