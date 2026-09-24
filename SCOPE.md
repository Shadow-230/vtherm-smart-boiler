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
   (SmartPI, Auto-TPI).
5. **Safe** — the fixed safeguards of principle 11 always apply; limits and the weather-dependent
   ceiling are set by the user, with cautious defaults.
6. **Local** — nothing is sent outside.
7. **English with HA translations** — nothing user-facing hard-coded.
8. **Suggest by default** — automatic changes only within the tuning band.
9. **Weather counted once** — the heating curve is the weather channel; zone signals only
   correct it.
10. **Two kinds of users** — a regular user gets working defaults, few questions and plain
    verdicts; a power user gets every parameter, diagnostics and overrides. The level changes
    what is visible, never how the plugin behaves. When switching from advanced to simple, the
    user chooses whether to restore advanced settings to their defaults or keep them hidden;
    kept settings stay active, and the simple view shows that some advanced settings differ
    from defaults.
11. **The user decides, informed** — control choices belong to the user: write path, hand-back
    method, control mode (flow setpoint or room values), limits, curve, demand thresholds,
    anti-cycling, learning pauses, monitoring period. Each has a cautious default and a
    description of what it does and what it risks — in the config flow and in the documentation.
    Fixed safeguards, not options, for every write (flow setpoint, CH on/off, modulation cap,
    room values to the boiler): no write without fresh input data; values within hard limits; a
    rate limit, and minimum on and off times for on/off; read-back of every write, or the value
    marked unverified when the device does not echo it; hand-back on every exit with every
    override cleared; control only with a known hand-back and, for setpoint control, a source for
    the confirmed setpoint; on sensor failure a safe fallback setpoint, never zero heat (its
    value is an option), or in room-value mode the room values cleared so the boiler's own
    control carries on; the DHW-enable bit kept as it was. The values of limits, rates and times
    are options; the guards themselves are not. On/off without feedback (a relay, an override the
    device does not echo) gives no boiler data to be fresh: freshness applies to the inputs of
    the decision, the write stays marked unverified, and the on/off guards carry the safety.

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
- Control mode (from 0.2), one at a time, the user's choice: **flow setpoint** — the plugin
  decides the water temperature from its curve and writes the setpoint; **room values** — the
  plugin sends the reference room's temperature and setpoint (§5, "Reference room") and the
  boiler's own curve and room influence decide the water temperature; in this mode the plugin
  changes neither the curve nor the water temperature. Room-value mode needs a device that takes
  room values (OpenTherm ID 24 / 16 through built-in support, or entities the user picks).
- Writing (from 0.2), in this order: (1) a writable entity the user picks — any integration,
  including entities the user made; (2) built-in support for devices without such an entity —
  first OTGW, through `opentherm_gw` or its firmware over MQTT; (3) otherwise monitor only, with
  the reason shown.
- Control is enabled only with a known way to hand control back, chosen by the user: for built-in
  OTGW `CS=0` (default) or monitor mode (only with a physical thermostat, see "Gateway
  topology"); for a picked entity a value (e.g. 0), the device's own timeout, or a switch. What
  hand-back leads to depends on the topology.
- Class 2: the plugin stores the original curve parameters and restores them on every exit, and
  writes persistent parameters rarely (boiler memory wear).
- Class 3 has no feedback from the boiler: decisions rest on zone and outdoor data, writes stay
  unverified, and the on/off guards apply (minimum on and off times, a cap on switchings per
  hour). What stale inputs lead to — boiler off, or back to the previous controller — is the
  user's choice, with its risks described.
- A second circuit controlled through the boiler (e.g. OpenTherm CH2) comes later; 0.2 writes
  one circuit. The data model covers several circuits from the start.

### Gateway topology

How the gateway is set up decides what the plugin may do and what hand-back leads to. OTGW
reports its mode and whether it sees a thermostat; other gateways have similar variants (DIYLess
and ESPHome as master or pass-through; EMS-ESP with or without a controller). To verify before
0.2 (`docs/plan-0.2.md`, F3).

| Gateway mode | Thermostat | Who controls the boiler | What the plugin may do | Hand-back leads to |
|---|---|---|---|---|
| monitor | physical | the thermostat; the gateway only listens | monitor only | — |
| gateway | physical | the thermostat; the gateway may override its values | flow setpoint (override `CS`) or room values (override the thermostat's room temperature and setpoint) | overrides cleared — the thermostat takes over, heating continues |
| gateway | none | the gateway acts as master | flow setpoint; room values (injected with `AA`) if the boiler heats on its own curve without `CS` | overrides cleared — heating stops |
| monitor | none | nobody | nothing | — |
| — | virtual — a controller on the HA side (e.g. DIYLess or ESPHome as master) | that controller | through its entities: flow setpoint if it exposes one, room values if it runs its own regulator | the user's chosen method for its entities |

- The topology is part of the configuration: detected where the gateway reports it, otherwise
  declared by the user in the config flow.
- Control modes the topology does not allow are unavailable, with the reason shown.
- Hand-back stops the plugin's heating demand. Without a thermostat heating stops until the plugin
  or the user acts; the config flow states this risk. Frost protection then rests on the boiler's
  own frost protection, if it has one.
- The plugin never changes the gateway mode on its own. Monitor mode as a hand-back method is
  available only with a physical thermostat, by the user's choice, and only after checking
  whether the gateway stores the mode persistently.
- Without a thermostat, an HA outage longer than the gateway's override timeout may stop heating
  too (to verify, `docs/plan-0.2.md` F3); the config flow says so.
- An emulated OpenTherm thermostat inside the plugin stays for later (§9).

### Topology

Boiler → circuits → zones. One boiler per HA instance; the data model covers several circuits
from the start.

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
- A learning algorithm without a pause service gets an explicit warning.
- Per zone the plugin publishes two values, as entities and feature-manager properties
  (feature manager from 0.2): **hot water available** (heat is reaching the zone — no while DHW
  is active, while the flow has fallen near room temperature, or while the flow signal is stale)
  and **emitter power factor** (emitter output now versus reference, from emitter type and size,
  valve opening, water and room temperature). The factor is computed only for zones that are
  heating; otherwise the last value is held; it is unavailable, with a reason, when data is
  missing. Zone algorithms do not read these values today (§9).
- DHW charging pauses learning only in zones calling for heat (valve open); zones with a closed
  valve keep learning how the room cools. Learning resumes when the flow is back at its setpoint.
- By default the water temperature changes slowly (ramp, §7), so zone algorithms can follow it.

### Reference room

- External boiler controllers (DIYLess, ESPHome OpenTherm and similar) need one room temperature
  and setpoint. The plugin publishes a reference room: selected zone, its temperature and
  setpoint, the deficit and a status. Strategy: largest deficit (default), a chosen zone, or an
  average. Only zones taking part in heating with valid readings count; temperature and setpoint
  come from the same zone; the choice changes only on a clear difference; no invented fallback —
  "no active zone" and "no valid measurement" are explicit states.
- In room-value mode (a control mode, off by default) the reference goes to the boiler as
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
- Gas bills or the user's own heat balance give a first estimate of the building's heat loss.
- The building model is the whole house in kW — the boiler's load. It does not duplicate the
  zone algorithms' room models.

## 7. Features by stage

| Stage | Delivers | Controls the boiler |
|---|---|---|
| **Monitor** | starts per hour, burn time, condensing share, gas per degree-day, connection state; alarms with selectable reaction (info; stop and hand back from the first control release); **early warning** (flue gas, ignitions, pressure, hysteresis); **report explaining changes** (weather / DHW / settings); condensing indicator; outdoor sensor check; DHW and foreign-heat detection; **forecast recording** (FC0); **reference room** (§5); **signal check** — which optional signals are present and fresh | no |
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

Fixed safeguards (principle 11), for every write — flow setpoint, CH on/off, modulation cap and
room values:

- No write without fresh input data — the data the decision uses. Gateway connectivity is part
  of freshness; a 0 from a value outside the gateway's regular polling counts as unknown, and
  bounds fall back to safe defaults. On/off without feedback has no boiler data: its inputs are
  the zones and the outdoor temperature.
- Every value within hard limits; room values within plausible room bounds.
- Every write rate-limited; on/off keeps minimum on and off times and a cap on switchings per
  hour; persistent writes (stored in the boiler's memory) have a daily cap.
- Every write is read back; a command the boiler ignores is reported, never assumed applied. The
  state shown is the value the boiler confirmed, never the requested one; settings the device
  does not echo back are marked unverified.
- Every exit — unload, reload, error, data loss, `central_mode` "Stopped", an alarm set to hand
  back — stops every loop, hands control back and clears every override.
- Control only with a known hand-back and, for setpoint control, a source for the confirmed
  setpoint.
- Room values go to the boiler only from a valid reference room; without one they are cleared.
- A failed sensor leads to a safe fallback setpoint, not to zero heat; in room-value mode it
  clears the room values, and the boiler's own control carries on.
- The DHW-enable bit stays as it was before the plugin took over.

In room-value mode the boiler runs its own control: the curve, ramp, anti-cycling and flow limit
options do not apply; the fixed safeguards do.

Options, each with a cautious default and its risks described:

- Boiler demand from device count, total power or valve opening.
- Basic anti-cycling: minimum burn, minimum pause, starts per hour.
- Ramp: how fast the water temperature may change, so zone algorithms can follow.
- Fallback setpoint value on sensor failure.
- Values of the hard limits, rate limits, minimum on and off times and room-value bounds.
- Repeat mode for a picked write entity: on change only (default; an expiring override lapses)
  or repeated (memory wear on persistent writes). Built-in OTGW repeats `CS` every 30 s.
- Low-flow warning when all valves are closed while the pump runs — needs a pump-running or
  CH-active signal.

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
verdict stays visible and the user decides.

## 11. Open decisions

- Learning pause during long anti-cycling pauses (water near room temperature while a zone calls
  for heat) — decide on data from the first installations (before 0.3).
- Auto-TPI protection once VT's central boiler is replaced — check `central_boiler_manager.is_on`
  without a configured boiler (before 0.2).
- OTGW topologies (§5, "Gateway topology"): how the mode and a connected thermostat are
  detected; behaviour when `CS` is not repeated; hand-back effects per topology (`CS=0`, monitor
  mode `GW=0`); whether the gateway mode is stored persistently; room values with a physical
  thermostat (override) and without one (`AA` injection — does the boiler heat on its own curve
  without `CS`); firmware version that added `RT` and `BS` (before 0.2).
- Which integrations offer a writable flow-setpoint entity (ESPHome / DIYLess, EMS-ESP, newer
  OTGW firmware) (before 0.2).

**Decided**

- License: **Apache-2.0** (2026-09-24). All logic and code are written from scratch; no code is
  copied from any project, other projects are sources of ideas only. A `NOTICE` file carries
  the attribution that copies and derivatives must keep.
- Tuning band: Low / Medium / High = 3 / 8 / 15 % of the flow-over-room difference at the current
  outdoor temperature, never below 1 K; Custom for power users. Beyond the band: suggestions only.
- Clocks: decisions at the shortest VT zone cycle (default 5 min); freshness check every 30 s,
  independent of decisions; keep-alive every 30 s where the write path needs it — OTGW requires
  `CS` at least once a minute, 30 s keeps a margin.
- OTGW equipment database: not bundled. The plugin uses the boiler's MemberID and supported
  messages when the integration exposes them; boiler profiles are our own.

## 12. Release

Public from 0.2, the first release: a GitHub repository installed through HACS as a custom
repository; each release passes the test environment, then runs on the author's installation,
then goes public. Submission to the HACS default list and the VT plugin list later (HACS review
takes months). Creating the repository and every publication need the author's consent.
