# VTherm Smart Boiler — Scope

General scope of the plugin, valid for any installation. Working rules and verified facts:
`CLAUDE.md`. Development plan: `PLAN.md`. "Decision n" and "answer X" refer to the user's
decisions of 2026-09-26/27 and answers of 2026-09-27 in `docs/plan-0.2.2.md`; S-n and P-n to the
problems of `docs/review-2026-09-26.md`. "(provisional, K4)" marks a value or rule the user
confirms or changes at the review before anything reaches a real boiler (`docs/plan-0.2.md` K4).

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
   flow. Most installations give only some of the inputs: every feature works with what it has,
   and missing data never switches heating off by itself (the missing-data rule, §7).
3. **Central water, local valves** — each circuit has one water temperature and its own curve;
   the plugin decides it centrally (flow-setpoint mode), leaves it to the boiler's own curve
   (room-value mode), or supplies a circuit that has its own controller. Zones throttle with
   their valves; information flows from the boiler to the zones. A boiler switched on and off
   by a relay (class 3) gets only heating on and off: its water temperature stays the boiler's.
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
   plugin. TPI's term is a setting; SmartPI 0.4.0 learns its own outdoor term (`u_ff1`), which
   cannot be set, and the documentation says so (S-50).
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
    boiler, a relay): no write without fresh input data — water-temperature control needs flame
    and flow known, and a relay's link is the relay itself; values within hard limits, except
    "off" and the hand-back value, which have checks of their own (§7) — the hand-back value
    still within the circuit maximum and the highest water temperature (S-21); nothing written
    to the boiler's persistent memory — control writes only to targets whose values expire or
    that the device holds (§7); a write-rate guard against a runaway loop (a repeated write waits
    at most one control step); read-back of every write, or the value marked unconfirmed when
    nothing independent of the plugin reports it — a relay's own reported state confirms the
    relay, though not that the boiler heats; a value changed from outside judged by four classes
    — a lost command is sent again, a value ignored from the start is no longer sent, a clip is
    accepted, and another controller is rewritten once, then the plugin steps aside with a full
    safe hand-back — never a fight (§7); hand-back on every exit in a safe order, with every
    override cleared, never held back by a guard, and retried until it is confirmed — except a
    target another controller takes after the hand-back, which counts as handed back; control
    only with a known hand-back and, for setpoint control, a source for the confirmed setpoint;
    on a failed outdoor sensor a safe fallback setpoint, never zero heat, or in room-value mode
    the room values cleared so the boiler's own control carries on; the DHW-enable bit kept as it
    was. The values of limits are options; the guards themselves are not, and none of them
    decides whether to heat (principle 12). A relay that reports no state of its own is
    controlled with blind repeats and shown as "controlled without confirmation"; freshness then
    applies to the inputs of the decision — the zones and the outdoor temperature.
12. **VT decides whether to heat** — the plugin replaces VT's central boiler: heating goes on
    and off with the zones' demand, at once and in both directions; the plugin decides only how
    warm the water is — the curve, the limits and the ramp. Nothing the plugin counts or times
    holds heating off, or on, against VT: an old boiler with a high minimum output cycles a lot
    on its own, and blocking it would leave the house cold. Frequent starts are information — an
    alarm with its threshold, and the verdict. (The user's decision, 2026-09-25.) The stated
    exceptions, each with its reason (§7; the user's decisions of 2026-09-26/27):
    1. Frost protection, a safety net — only for zones whose emitter can take heat (decision 4).
    2. The recognition period, at most 10 min after Home Assistant starts or VT reloads: no new
       decision, the last command kept. Reason: the zones report one by one.
    3. The grace period: a zone that becomes unknown keeps its last answer for 10 min. Reason:
       reloading one zone should neither start nor stop the boiler.
    4. No heating when every zone is unknown, or no configured demand criterion can be judged,
       after the grace, and no working thermostat is there (§7). Reason: nothing can ask for heat
       (decision 3).
    5. VT's activation delay, 0–600 s before switching on, as in VT 10.4.0. Reason: slow valves
       (decision 5).
    6. The usual "off" while the boiler reports a fault that stops it (a known "on" held 5 min,
       provisional, K4). Reason: the plugin follows the boiler's own logic.
    7. The lost boiler link: a hand-back after 5 min — stand-alone, heating stops — or, for a
       relay, an alarm and no hand-back (the decision of 2026-09-25; §5 class 3).

    A hand-back the rules require — another controller, an internal error, the plugin's own
    monitor failing for 5 min, the boiler ignoring "heating off" from the start of the session,
    an exit — is not a decision about whether to heat: it returns the boiler to its own control or
    thermostat, and stand-alone it stops heating (§5). Anti-cycling for 0.3 is to be decided
    against this principle (decision 13).
13. **Bounded learning** — every value the plugin adapts or learns by itself, now and in later
    releases, follows fixed rules that are not options: (1) a firm band around its starting
    point (the user's entry or the default), never left; (2) a limited rate of change, per hour
    and per day; (3) it moves only while every other criterion holds — comfort in every zone, no
    zone overheating, cycling not rising, every limit kept — and steps back when another one
    gets worse; (4) the aim is a "good enough" band, not an optimum: learning stops inside it;
    (5) it freezes in unusual conditions — hot water, foreign heat, data gaps, hand-back,
    extreme weather; (6) at the band's edge it informs instead of pushing on — the starting
    point is probably wrong; (7) every learned value is visible and can be reset; values of a
    session (the comfort correction) reset at hand-back and at the end of the session; learned
    properties of the boiler (the lowest water temperature, once "apply" learns it in 0.3) are
    kept, and reset when the user resets them or when an input they rest on changes; the user's
    own entry is never reset (decision 2, S-58). Pushing one quantity to its ideal can break
    another: warm one room, overheat the rest. (The user's decision, 2026-09-25.) The rule
    values — the band, the rates, the freeze conditions — are fixed; the only options are whether
    a learning feature runs (off / suggest / apply) and principle 8's tuning band (Low / Medium /
    High / Custom) (provisional, K4). Each value shows its source — class default, the user's
    entry, measured, learned; the user's entry always wins over measured and learned values, and
    "apply" (0.3) moves only within the band around it (S-58).

## 4. User levels

| Area | Regular user | Power user |
|---|---|---|
| Wizard | boiler class and profile suggestion, gateway topology and what is wired to the gateway's thermostat terminals (decision 1), control mode, circuits and zones, a few coarse choices (insulation, thermal mass, emitter type); on the entity and relay paths the tick "the boiler has its own room controller" (answers F, M); on the relay path the relay's own settings and the tick "this is a separate relay contact, not a setting stored in the boiler's memory" (answer G) | every profile field, measured values, building load from own calculation |
| Assessment | a verdict: control is worth enabling or not, and why | all metrics, per outdoor-temperature range, raw cycle data |
| Control | off by default; once enabled, control runs automatically in the chosen mode; curve changes: suggestions (default) or automatic within a preset band (Low / Medium / High) | Custom band, per-parameter overrides, manual edits of learned values, reset to profile |
| Alarms | sensible default reactions | thresholds per alarm; a reaction only where decision 7 allows one (§7) |
| Diagnostics | hidden | model parameters, confidence, sample rejection reasons, emitter power factor |
| Learning | on, within safe bounds | pause and resume, the tuning band (principle 13), learning windows, zone-algorithm protection settings |

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
| 2. Curve parameters only | BSB-LAN, ViCare | suggestions only (S-56) | later |
| 3. On/off | a relay on the boiler's room-thermostat terminals, or a boiler thermostat entity switched between heat and off | heating on and off, as VT's own central boiler, with the plugin's safeguards | 0.2.2 |
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
  first OTGW, through `opentherm_gw` or its firmware over MQTT; (3) from 0.2.2, a relay for an
  on/off boiler (class 3); (4) otherwise monitor only, with the reason shown.
- Control is enabled only with a known way to hand control back, chosen by the user: for built-in
  OTGW the safe hand-back below; for a picked entity a value, declared with its effect (the
  device's own control resumes, or heating stops) and done only once read back, the device's own
  timeout, or a switch with a declared write type (a persistent one is not used, P-40); for a
  relay its rest state. Monitor mode is not a hand-back method (S-59). What hand-back leads to
  depends on the topology.
- **The safe hand-back** (the user's decision of 2026-09-26/27), in this order, one part after
  another at once, each tried whatever the others do, waiting for no read-back and not for the
  water to cool (provisional, K4): (1) the water to the lowest water temperature set; (2) heating
  on where the boiler returns to a thermostat or its own control — on a gateway always `CH=1`,
  which only clears the plugin's own `CH=0` (stand-alone, `CS=0` still stops heating); a heating
  switch on an entity path is not turned on where the declared effect is "heating stops" (S-27);
  (3) the release — `CS=0` on a gateway, the hand-back value, the external-control switch off,
  or the timeout. A relay goes to its rest state instead. The same order is followed when the
  plugin steps aside from another controller (§7, answer H): every target is handed back, even
  one the other controller holds, each part written once.
  - Where a target is declared held (the device keeps the last value it was given: ESPHome,
    DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires within about a minute) and
    the release is not confirmed, the boiler stays at the lowest water temperature: an alarm
    rises at once, and the release is retried every minute until it is confirmed.
  - A target another controller takes after the hand-back counts as handed back, with no retry:
    the setpoint when a steady foreign value holds for 2 retries; a two-valued target (the
    heating switch, the external-control switch, a relay after a hand-back other than a step
    aside, provisional, K4) when its hand-back state was read back once and then changed without
    a trace of an outage. Before that it stays owed and is retried. This changes "retried every
    minute until it is confirmed" for that case only.
  - A missing or `unavailable` target means the hand-back failed: Home Assistant drops such a
    call without an error. An `unknown` target is written, and counts only once it is read back
    (S-28). An entity with `assumed_state`, or with no report independent of the plugin, is
    "unconfirmed" and says so (S-09).
  - A timeout hand-back is released when the read-back is back within 0.5 K of the session's
    baseline; with the baseline unknown, when it is more than 0.5 K from both the plugin's last
    value and the lowest water temperature just written. It writes no retries; `hand_back_failed`
    rises after 3 min without release, and until then it stays owed and is shown (S-20;
    provisional, K4).
  - The hand-back value is exempt only from the lowest water temperature: the circuit's maximum
    and the highest water temperature still apply (S-21). "Off" is refused within 0.5 K of a
    hand-back value declared "the device's own control resumes" (S-49).
  - An owed hand-back can be settled by hand: its repair issue is offered while it is owed, and
    the user confirms that the boiler runs on its own control again; the plugin then forgets the
    debt and stops retrying (S-45).
  - Removing the entry: Home Assistant offers no veto. The plugin makes a last attempt and, if it
    fails, raises a persistent repair issue (S-54).
- Class 2: suggestions only; the plugin writes no curve parameters, as they are persistent
  (S-56).
- Class 3 — the relay (from 0.2.2, as VT's own central boiler works; decision 13): without
  anti-cycling timers or a starts cap, which VT's central boiler does not have either.
  - The write path "relay" is a switch, or a boiler thermostat entity switched between heat and
    off; an `input_boolean` is refused, as it confirms nothing. The water-temperature parts
    (curve, limits, ramp, comfort correction) do not apply and are hidden; the activation delay
    is shown (§7).
  - The plugin cannot read the relay's own settings, so the form asks for them as the user's
    declaration (the defaults provisional, K4): the tick "this is a separate relay contact, not a
    setting stored in the boiler's memory", without which control does not start, with a blocker
    naming the reason (answer G); its state after a power cut (off / on / last / I don't know;
    default "I don't know", treated as "maybe on"); its own switch-off timer (none / its length,
    1–120 min / I don't know; default "I don't know", treated as "it may have one"); whether it
    reports its state (yes / no / I don't know; default "I don't know", treated as "no" — an
    entity with `assumed_state` always counts as "no"); the repeat interval, 10–300 s, default
    300 s.
  - Flame and flow are optional for the whole entry; water-temperature control gets a blocker
    where either is missing.
  - The link is the relay: available and, where it reports, in the commanded state. A relay out
    of reach raises the alarm "relay unreachable" and a repair issue after 5 min, and gets the
    command again when it returns; no hand-back is attempted meanwhile, as it could not arrive.
    For relays this departs from "a lost link hands back" (2026-09-25).
  - Its own reported state confirms the relay, not that the boiler heats — an exception to "a
    read-back from the written entity confirms nothing". An `assumed_state` entity confirms
    nothing. The state is checked every 5 min (provisional, K4) and the command sent again on a
    mismatch only; a relay that reports no state, or may have a switch-off timer, gets blind
    repeats every repeat interval and is shown as "controlled without confirmation". With a
    declared timer length, "on" is renewed every min(timer ÷ 2, repeat interval), and a
    switch-off at or after max(timer − 60 s, timer ÷ 2) since the "on" that started the
    on-period is the timer's lapse, answered with "on" and not counted; with "I don't know", a
    switch-off at least one repeat interval after that "on" (provisional, K4).
  - Changes seen on the relay follow §7's matrix (rows R1–R9): a relay found in another state
    after a power or link loss, or back in its declared power-cut state, is sent the command
    again (a restart); 3 such restarts within 24 h raise an information warning, and a fourth
    within 24 h counts as another controller. With the power-cut state declared "last" or "I
    don't know", a change while it stayed available is a possible restart in the same way, up to
    3 times within 24 h. Otherwise a change to another state while it stayed available — an
    automation, a person, its own button — counts as another controller: rewritten once, then
    the plugin steps aside, never fighting (answers C, D, N).
  - At hand-back the relay goes to the rest state the user chooses: "off" by default, "on" only
    when the user chose it, with its risk text; a notification rises when "off" leaves the house
    without heating while a zone calls or frost protection is active. Stepping aside sets the
    relay once to its rest state, then leaves it alone (answer L); there is no return by itself
    for relays. The hand-back never switches a relay on otherwise.
  - A planned restart of Home Assistant: the rest state at the stop, then the last command
    restored at once at the start, with no activation delay.
  - Optional proof that the boiler heats — a flow-pipe temperature, the boiler's electric power,
    the gas meter — is information only, judged within 30 min after "on" (provisional, K4);
    without it the status says "controlled without confirmation that the boiler heats".
  - Moving over from VT: the relay (where VT's commands name a switch or a boiler thermostat
    entity; otherwise the user picks it), the activation delay, the repeat interval (only where
    VT's keep-alive lies within 10–300 s) and the power threshold as VT rounded it are pre-filled
    before the user unticks VT's central boiler, since VT then deletes them; VT's device-count
    threshold only where every zone has one heating device (provisional, K4). Control waits for
    the Home Assistant restart VT needs.
  - The setup texts recommend: the relay on the boiler's room-thermostat terminals, never in its
    power supply; the old thermostat kept in parallel and set low, with the note that valves VT
    drives stay where they were while Home Assistant is down, so its heat may not reach every
    room; the relay starting "off" after a power cut; its local input set to "detached"; an
    integration that reports availability; optionally the relay's own switch-off timer, renewed
    by every "on" and set only when control starts — whether a Shelly's timer restarts on a
    repeated "on" is not documented; one test in summer.
- A second circuit controlled through the boiler (e.g. OpenTherm CH2) comes later; 0.2 writes
  one circuit: control needs exactly one configured circuit fed by the boiler flow, unmixed or
  passive fixed; with any other layout the monitor runs and a blocker says why. Radiators and
  underfloor behind a mixing valve, as one written circuit plus passive fixed circuits, come in
  0.3 (S-42). The data model covers several circuits from the start.

### Gateway topology

How the gateway is set up decides what the plugin may do and what hand-back leads to. Other
gateways have similar variants (DIYLess and ESPHome as master or pass-through; EMS-ESP with or
without a controller). F3 found that neither the OTGW's mode nor a connected thermostat can be
read reliably through Home Assistant (the mode is read only when the gateway connects; there is
no presence entity).

| Gateway mode | Thermostat | Who controls the boiler | What the plugin may do | Hand-back leads to |
|---|---|---|---|---|
| monitor | physical | the thermostat; the gateway only listens | monitor only | — |
| gateway | an OpenTherm thermostat | the thermostat; the gateway may override its values | flow setpoint (override `CS`) or room values (override the thermostat's room temperature and setpoint) | overrides cleared — the thermostat takes over, heating continues |
| gateway | an on/off contact, or "I don't know" | the contact through the gateway | monitor only — control is blocked (decision 1) | — |
| gateway | none | the gateway acts as master | flow setpoint; room values (injected with `AA`) if the boiler heats on its own curve without `CS` | overrides cleared — heating stops |
| monitor | none | nobody | nothing | — |
| — | virtual — a controller on the HA side (e.g. DIYLess or ESPHome as master) | that controller | through its entities: flow setpoint if it exposes one, room values if it runs its own regulator | the user's chosen method for its entities |
| — | relay (class 3), an optional old thermostat in parallel | the plugin, through the relay | heating on and off only | the declared rest state: "off" — heating stops unless an old thermostat in parallel heats; "on" — the boiler heats on its own dial or thermostat |

- The topology is part of the configuration, declared by the user in the config flow (F3: it
  cannot be read through Home Assistant).
- Both gateway topologies — with a thermostat and stand-alone — ask what is wired to the
  gateway's thermostat terminals: an OpenTherm thermostat, an on/off contact, nothing, or "I
  don't know" (decision 1). Control is blocked for an on/off contact and for "I don't know": the
  gateway keeps a `CH=0` through `CS=0` and the override's lapse, so after a crash while "off" an
  on/off thermostat could not heat the house. The monitor works as before. An answer that
  contradicts the topology — an OpenTherm thermostat with stand-alone, nothing with a thermostat
  — is refused in the form with a hint to pick the other topology. A gateway entry made before
  0.2.2, without this answer, keeps control stopped, with a notice asking for it (answer K).
  "Off" as a low `CS` with `CH` left alone, for such installations, waits for the user at K4
  (decision 11).
- Control modes the topology does not allow are unavailable, with the reason shown.
- Hand-back stops the plugin's heating demand. Without a thermostat heating stops until the plugin
  or the user acts; the config flow states this risk, and after a stand-alone hand-back the
  control switch says that frost protection now rests on the boiler's own, if it has one; the
  alarm "handed back in frost" rises while a watched zone reads below the frost limit, and clears
  at or above the release (S-57; provisional, K4). A lost boiler link is no exception: in every
  gateway topology it raises an alarm and control hands back — stand-alone, heating stops (the
  user's decision, 2026-09-25). A relay is the exception: an alarm, and no hand-back (§5 class
  3).
- The plugin never changes the gateway mode on its own; the gateway stores its mode
  persistently (F3). The OTGW hand-back is the safe hand-back: `CS` at the lowest water
  temperature, `CH=1`, then `CS=0`.
- **The wall thermostat on a gateway** is not synchronised in 0.2.2. The form's texts say that
  while the plugin controls, the wall thermostat's heating setting and its off switch do
  nothing (its hot-water settings still work), and that after a hand-back or a Home Assistant
  outage it heats by its own setting and program. The plugin shows the temperature the wall
  thermostat would keep after a hand-back, from the optional "wired thermostat setpoint" signal,
  and warns when that value is unknown or below 15 °C (provisional, K4). A VT zone built on the
  gateway's own thermostat entity is refused: it would call for heat whenever the flame burns.
  Synchronisation, VT leading and off by default, comes in 0.3 at the earliest.
- Without a thermostat, an HA outage longer than about a minute stops heating: `CS` lapses
  (F3); the config flow and the control switch say so.
- An emulated OpenTherm thermostat inside the plugin stays for later (§9).

### Topology

Boiler → circuits → zones. One boiler per HA instance, in a single config entry; the data model
covers several circuits from the start.

### Circuits and curves

Underfloor and radiators need different curves. Every circuit has its own curve and limits, and
takes the emitter types of its zones (S-33); the burner is shared.

| Circuit control | Example | What the plugin does |
|---|---|---|
| Unmixed, shared | radiators and underfloor on one loop, no mixing valve | one curve for the loop, capped by the most sensitive emitter (underfloor maximum flow) |
| Controlled through the boiler | OpenTherm CH2, EMS-ESP HC2, the boiler's mixing module | own curve and setpoint per circuit; boiler flow = highest circuit need + mixing margin |
| Controlled separately | external mixing controller, a mixer driven by HA, a separate weather controller | reads (or is told) the circuit's target and keeps boiler flow above it + margin; never fights that controller |
| Passive fixed | thermostatic mixing valve | declared fixed temperature; boiler flow kept at least 5 K above it (S-42; provisional, K4) |

- Each VT zone is assigned to a circuit in the wizard; zone arbitration (the critical zone) runs
  per circuit.
- Anti-cycling, DHW and the modulation cap act on the boiler (shared burner); curve tuning, the
  weather-dependent ceiling and the seasonal tune-up act per circuit.
- Condensing depends on the combined return of all circuits.

### Zone algorithms — any

- Core uses VT data only: `on_percent`, valve positions, room temperature vs target, device power.
- Detected extras: SmartPI — learning pause (its better signal and bootstrap state come later,
  §9); Auto-TPI — detected, not paused, with a repair issue (§11; S-29).
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
  valve keep learning how the room cools. Every hot-water draw pauses it, however short and on a
  combi boiler too, as the calling zones get no heat meanwhile (S-41). Learning resumes when the flow is back within a
  tolerance of its setpoint (3 K either way), and at the latest after a longest pause (1 h); a
  pause and a resume are read back from the algorithm's flag — a pause that did not take is not
  the plugin's, a resume is sent again every minute until the flag reads on — and learning the
  user switched off before a pause is never resumed. A switch-off during the plugin's own pause
  cannot be told from the pause: the flag reads off either way.
- By default the water temperature changes gradually (ramp, §7): each setpoint step stays small
  enough that the boiler does not overshoot it, and zone algorithms follow (S-47).

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
| Boiler settings (installer menu; later, §9 — S-60) | CH hysteresis, anti-cycle time, pump overrun, summer threshold, built-in curve |
| Installation | circuits, circuit control type, curve per circuit, emitter types, max underfloor flow, mixing valve, shared CH/DHW return, bypass, water volume |
| Building (whole house, in kW) | design heat load or loss coefficient, heating threshold, thermal mass, insulation class |

- Every parameter has a source and a confidence, and its source is shown: class default →
  user-entered → measured → learned. The user's entry always wins over measured and learned
  values; learning ("apply", 0.3) moves only within the band around it (principle 13, S-58). A
  mismatch between declared and measured values is a diagnostic finding.
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
| **Monitor** | starts per hour, burn time, condensing share, gas per degree-day, connection state; alarms — information, with a hand-back reaction only where decision 7 allows one (§7); **early warning** (flue gas, ignitions, pressure, hysteresis); **report explaining changes** (weather / DHW / settings); outdoor sensor check; DHW and foreign-heat detection; **forecast recording** (FC0); **reference room** (§5); **signal check** — which optional signals are present and fresh | no |
| **Advisor** | curve and anti-cycling suggestions with rationale and an "apply" button | no |
| **Curve (strategy A)** | replaces VT's on/off and user automations; curve per circuit; effective outdoor temperature; **summer/winter switch from a multi-day forecast** (FC1 — to be decided against principle 12, decision 13); ramp; keep-alive; frost protection; learning pauses (DHW, foreign heat, large changes — under control only, S-61) | yes |
| **Anti-cycling** (to be decided against principle 12, decision 13) | duty cycling at low load, starts-per-hour budget, modulation cap; **planning from the forecast** — mild hours ahead → long cycles from the start (FC2) | yes |
| **Curve tuning (strategy B)** | tuning band Low / Medium / High / Custom (3 / 8 / 15 % defaults); manual / semi-automatic / automatic; **seasonal tune-up** — a little lower each day while rooms hold comfort; per circuit | yes |
| **Forecast** | **anticipation for slow emitters** — raise water earlier before frost, lower it earlier before a warm or sunny day (FC3); lead time learned per circuit | yes |
| **DHW** (optional, storage tank only) | fast charging, schedule aligned with learning windows | yes |

**Across all stages**

- **Water-side learning:** from HA history when it covers a heating season, then live; bounded
  change per day.
- **Foreign heat:** other heaters (fireplace, stove, electric heater) — **not** the sun. Switch or
  sensor → detected in every stage; under control, learning paused in affected zones (S-61).
- **DHW** is detected in every stage; under control it pauses learning — in zones calling for
  heat (§5) and, with a shared return, the plugin's own data too (S-61).

**Control base — from the first control release**

**Missing data** (the user's rule of 2026-09-26/27). Most installations give only some of the
inputs; every feature works with what it has.

- A feature whose input is missing, unknown or unavailable is shown as inactive, and names what
  it lacks in a translated text.
- Missing data never switches heating off by itself, and never blocks the boiler by itself.
- A setting the form requires before control may start can keep control unavailable: the
  thermostat terminals (decision 1), a usable heating switch (decision 11), the relay's "separate
  contact" tick (answer G), and, for a gateway entry made before 0.2.2, the answer on its
  thermostat terminals (answer K: control stays stopped, with a notice asking for it). The
  monitor then runs and the boiler stays with its own control or thermostat — that is not heating
  switched off by missing data.
- When an input goes missing while the plugin controls, the feature that uses it becomes
  inactive, and control goes on with what remains; for example, a demand criterion that no zone
  can feed counts as having no data.
- One entity mapped to two signals: the first signal keeps it and the later one is dropped
  (inactive and named); control gets a blocker and the form refuses it — never an error that
  stops the entry, so the monitor and an owed hand-back go on.
- Two stated exceptions of principle 12 stop heating on missing data: the lost boiler link (a
  hand-back after 5 min, which stops heating stand-alone; a relay gets an alarm and no hand-back),
  and every VT zone still unknown after the grace period, or no configured demand criterion that
  can be judged, with no working thermostat (below).
- An installation that gives no confirmation at all — neither the boiler's signals nor a relay's
  own reported state — gets only the monitor. The exception is a relay that reports no state of
  its own: it is controlled with blind repeats and shown as "controlled without confirmation".

How control decides (principle 12):

- Heating goes on and off with the zones' demand at every control step (10 s), at once and in
  both directions. The decision interval (an option, default 5 min) applies only to the water
  temperature.
- Demand comes from the zones calling — VT's zones against thresholds: the number of zones
  calling, total power, valve opening — each usable alone or with the others, as in VT, and
  checked against the configured zones. VT counts heating devices where the plugin counts zones:
  a user coming from VT's central boiler sets the number of zones, and the migration pre-fills it
  only where every zone has one heating device (S-36; provisional, K4). Its source follows the VT
  type (valve opening, VT's device state, heating action) and respects VT's minimum activation
  time. Switch zones follow VT's device state, so the boiler may start once per TPI cycle (S-38).
  The power criterion, for every write path, takes a zone's mean power over its cycle, as VT
  counts it, but only while at least one calling zone has its valve open or its device active;
  a VT device power of 0 or less is no data, and a criterion no zone can feed is refused in the
  form. The opening threshold counts the calling zones only. Control needs at least one VT zone
  (S-04).
- A zone counts only while its state is known: a VT climate that is `unavailable`, or whose mode
  is unknown, is unknown — never "no demand". A zone whose mode is "off" has no demand, whatever
  `is_ready` says, once the recognition period is over (S-34). Power shedding removes a zone's
  demand. A zone in "auto" or heat_cool heats by its heating action and duty cycle.
- **The recognition period** (decision 3): after Home Assistant starts or VT reloads, until every
  configured zone has reported — VT shows it started and its mode and demand are known — at most
  10 min. No new decision is taken meanwhile. If the plugin controlled the boiler before the
  restart — a clean restart that handed it back included — its last command is kept, or restored
  at once, with its keep-alives, where the stored wish is "control on", the control switch entity
  is not disabled, no latch or internal error holds, the control options equal those the control
  was taken with, and no other blocker holds; until the write target and the boiler link are
  available nothing is written and the restore waits, and a link not yet reported never turns the
  restore into a hand-back. When a condition fails, the owed hand-back goes first; where control
  did not hold the boiler, the plugin waits. A lost or damaged store: the plugin assumes it was
  controlling and hands back first (answer K). A restored command gets no activation delay.
  Frost protection acts for zones already known (provisional, K4).
- **The grace period:** a zone that becomes unknown while VT runs keeps its last answer for
  10 min; then it drops out and the known zones decide (this changes N3 of 2026-09-25). A zone
  still unknown when the recognition period ends has no last answer and drops out at once. The
  grace also covers the "VT central boiler unknown" blocker during a VT reload, where VT's
  central boiler was known to be off just before (P-105). A zone unknown for longer than a limit
  raises an alarm, as frost protection cannot see it. So does a zone whose room sensor, as VT's
  entry names it, is gone, unavailable or unknown for as long, or whose VT `safety_state` is on
  (S-35): VT keeps the last temperature, and its demand still counts, as VT runs the zone. An
  implausible room temperature of a watched zone is unknown, with the same alarm after its limit;
  one plausibility rule serves every room reading, −30 to 45 °C (S-06; provisional, K4).
- **Every zone unknown** after that, or no configured demand criterion that can be judged:
  nothing asks for heat (decision 3). With a **working thermostat** the boiler is handed back to
  it, or to its own control. A working thermostat is a gateway with an OpenTherm thermostat
  declared on its terminals; the entity path with the tick "the boiler has its own room
  controller" (for example an EMS room controller on the bus); or the relay path with that tick
  and the rest state "on" (the relay is the boiler's heat-demand contact). Nothing else counts:
  not a relay resting "on" without the tick, not the tick with the rest state "off", not a
  hand-back value declared "the device's own control resumes" without the tick. The tick is not
  offered on a gateway (answers F, M). Without a working thermostat the plugin does not heat —
  its usual "off", for a relay the relay off, never its rest state — with no hand-back. Either
  way the alarm "no zone known" and a repair issue rise at once, with the monitor only too, and
  control resumes by itself when a zone answers again (after a hand-back: provisional, K4). This
  replaces "heat on the curve when no zone is known", whatever the outdoor temperature.
- VT's central mode (Auto, Stopped, Heat only, Cool only, Frost protection) acts through the
  zones: VT applies it only to thermostats that follow it, the plugin sees the result in each
  zone's demand, and zones outside the central mode still count. "Stopped" is not a hand-back:
  control goes on, and with every zone stopped there is no demand, so heating stays off, while
  frost protection still watches (the user's decision, 2026-09-25).
- Summer and winter come from VT: the plugin has no summer switch of its own. With VT's zones
  off it does not heat; with a zone calling it heats. The monitor keeps the building's heating
  threshold, for its degree-days.
- **Frost protection** (decision 4) heats without VT's call: when a watched zone — every zone
  (default), or one zone the user picks — falls below the frost limit, heating runs on the curve
  until the zone is back above the release temperature, but only for a cold zone whose emitter
  can take heat: VT reports an opening above 0, or an active device; the mode alone is not
  enough. A zone whose valve state cannot be read is heated as before; a per-zone option "closes
  when VT switches it off" (off by default) makes it count as closed while VT has it off. A cold
  zone VT keeps closed raises a repair issue at once and does not start the boiler: it names the
  room and its temperature, says why the plugin cannot heat it, and what to do — VT's frost
  preset instead of "off"; VT's central frost mode needs a frost temperature in every
  thermostat. The plugin never switches VT's mode. Frost heating that goes on without the zone
  warming raises an alarm; it is not stopped. Frost heating waits for the activation delay. This
  changes the decision of 2026-09-25 ("the safety net covers the whole house").
- **VT's activation delay** (decision 5), carried over as in VT 10.4.0: 0–600 s in steps of 10,
  default 0, on the relay path too. It delays switching on only. The wait starts at the first
  real call for heat, after the recognition period; a call that drops and returns during the wait
  neither cancels nor restarts it, and at its end the boiler starts only if demand is still
  there. Switching a running boiler off is immediate; a hand-back, control switched off or a
  blocker cancels a pending start. No delay where the plugin controlled the boiler before a
  restart. It is pre-filled from VT's stored value and shown for confirmation. Its risk text
  names TPI pulses shorter than the delay, and a pump that may run anyway without a heating
  switch.
- The water temperature follows the curve on the effective outdoor temperature, within the
  limits, and changes at the ramp's rate, in K per minute, at every step. The ramp is skipped
  only for installation limits — the highest water temperature, a circuit, the boiler — not for
  a falling weather ceiling (S-23).
- **The lowest water temperature** (decision 2; the key `hard_min`) bounds the curve from below,
  10–50 °C, default 20 °C (provisional, K4), set by the user like a curve setting. Its text names
  both risks: too low — the boiler stops by itself again and again in mild weather, and a
  non-condensing boiler condenses in its flue (take the value from its manual); too high — warmer
  water than the rooms need. 0.2.2 only suggests: the monitor shows its evidence of short burns
  at that temperature and a suggested value — the reference + 2 K, rounded up to 0.5 °C and kept
  below the caps (provisional, K4) — which the user enters; an "about" estimate from the boiler's
  minimum power — the curve's flow where the emitters give off that power — is shown beside it
  only where the minimum power, an entered or confidently measured design load and an entered
  curve exist, never for a non-condensing boiler (Q3.4; provisional, K4). Nothing changes by
  itself; "apply" comes in 0.3. Where the boiler's own curve sets the water temperature, the
  plugin only suggests, worded for the device that sets it, never a parallel shift of that curve;
  no suggestion while a stand-alone installation is handed back.
- **The circuit maximum** limits the setpoint; the boiler may overshoot it, and the option's text
  says so. An information alarm rises when the measured flow stays above an alarm temperature for
  a time, both the user's settings at the advanced level, pre-filled with the circuit's maximum +
  5 K and 10 min (decision 10). It needs a flow reading, and a circuit with a maximum; without
  them it is inactive.
- The outdoor temperature comes from the outdoor sensor, else from the weather entity; a sensor
  found stuck is replaced in the same way, with an alarm, and one found deviating from the
  weather entity gives way to it only while the weather entity reads colder — the colder value
  asks for more heat, which the valves throttle — and, without a weather reading, where the
  check saw it read warmer (decision 12). Without either, the last effective outdoor temperature
  holds for 3 h, then the user's fixed fallback, or the design flow, replaces it (decision 9).
- **Comfort correction** (principle 13): while a zone's valve is fully open and its room is still
  short of its setpoint, the water rises above the curve — at most +3 K, by 1 K per 30 min and
  only while heat flows: the flame when it is known, else the command (S-24); it falls twice as
  fast, and a zone without opening data does not block the fall; it counts only zones taking heat,
  and does not rise while another zone taking heat is more than 1 K over its setpoint (S-08); it
  freezes while a cap holds the setpoint, and does not rise when the clock is set back (S-25); it
  is reset at hand-back and at the end of a session; when it stays at +3 K for hours, the user is
  told. Its value is published, and a "Reset comfort correction" button resets it (answer J). The
  zones' own PI integrators (SmartPI, TPI) act in series with it; the documentation describes the
  interaction and the VT settings recommended with it.
- **"Off"** goes through the heating switch (built-in OTGW: `CH=0`, held, with `CS` of at least
  8 °C; a relay: the relay off). Control without a usable heating switch is blocked, and such
  installations get the monitor, as is decision 1's alternative (a low `CS` with `CH` left alone).
  The research of 2026-09-27 found no boiler where a low setpoint with CH enabled stops the CH
  pump (Q3.2); only the user lifts the block, at K4, whatever the research finds (decision 11,
  answer K). A boiler that ignores "heating off" from the start of the session is treated in the
  same way: control is blocked and the boiler handed back, with an alarm, and a blocker names the
  reason until the user switches control off and on after fixing it (answer O).
- **Boiler protection** follows the boiler's own logic. Two optional signals take binary sensors the
  user maps: "the boiler's own low-water-pressure fault" (simple level) and "another fault the
  boiler reports as stopping it" (advanced) — on `opentherm_gw` the boiler's "Low water pressure"
  and its other fault sensors, on ESPHome its fault binary sensors, on EMS-ESP no standard one
  (model-specific service codes) (Q3.9). On OTGW such a flag counts only while the boiler's "Fault
  indication" is on, as the gateway reads the fault details once per new fault and never again after
  it clears (provisional, K4). While either reads a known "on" for 5 min (provisional, K4), control
  sends its usual "off" — frost heating included — with no hand-back and no latch, and heats again
  by itself in the step where every mapped fault reads off, unknown or unavailable (an unknown fault
  counts as no fault). Without a mapped fault, low pressure raises only an "add water" notification,
  at a threshold the user takes from the boiler's manual — none by default. A broken or silent
  pressure sensor never stops heating. High pressure and hot flue gas inform, with a notification
  that says what to do: read the safety valve's rating on the valve itself (often 3 bar in Europe,
  about 2.1 bar in North America); let water out only with the heating off and cold. With enough
  data a warning comes earlier — "your pressure keeps falling — there is a risk of a leak" — judged
  with the water temperature taken into account, since heating the water changes the pressure.

Fixed safeguards (principle 11), for every write — flow setpoint, CH on/off, modulation cap,
room values and a relay:

- No write without fresh input data — the data the decision uses: for water-temperature control,
  flame and flow known; for a relay, the relay itself (§5 class 3). One freshness rule serves the
  monitor and control: a signal is fresh while its entity is available and, if the user set an
  age limit for it, while its last report is within the limit — each signal by its own limit, the
  flame's included, and the weather entity by an optional limit of its own. A steady reading is
  not a stale one — many sources report only on change — so age counts only with a user-set
  limit; without one, a source that freezes without going unavailable is not caught, and the
  option's description says so. Gateway connectivity is part of freshness (its entities go
  unavailable); a silent drop of the OTGW firmware's MQTT is seen through its availability topic
  within about 90 s, while a broken link between its ESP and its PIC is not seen through Home
  Assistant at all — the option's text says so (Q3.6). A 0 from a value outside the gateway's
  regular polling counts as unknown, and bounds fall back to safe defaults (0.2 reads no such
  values).
- A lost boiler link — flame or flow not fresh for 5 min within the last 10 min, so a link fresh
  one step in five is still lost — stops every write; the alarm "boiler link lost" rises whenever
  the control switch is on and the link is lost, whatever blockers or a latch show, and control
  hands back: with a thermostat, the thermostat takes over; stand-alone, heating stops. It
  resumes once the link has been fresh for 60 s without a break (provisional, K4). A relay out of
  reach instead raises its own alarm after 5 min, with no hand-back (§5 class 3). A failed
  outdoor sensor is not a lost link: it leads to the fallback setpoint, never to zero heat.
- Every value within hard limits — the lowest and the highest water temperature — with two
  exceptions that have checks of their own: "off" — a low setpoint at least 1 K below the lowest
  water temperature (P-43) and within the target's range; on OTGW `CS` is never written below
  8 °C as a setpoint, as lower values do not lapse (`CS=0` at hand-back cancels the override and
  is not a setpoint, S-59) — and the hand-back value (§5, the safe hand-back). "Off" is refused
  within 0.5 K of a hand-back value declared "the device's own control resumes" (S-49). The
  weather ceiling never falls below the lowest water temperature. Room values stay within
  plausible room bounds.
- Nothing is written to the boiler's persistent memory: control writes only to targets declared
  expiring (repeated every 30 s) or held (the device keeps the value; the plugin sends it on a
  change, after the device returns and every 5 min, with no echo required — provisional, K4 —
  which replaces "written on change only"). A setpoint target declared persistent, or of unknown
  write type, keeps control off, with the reason shown; a heating switch declared so is not used
  (the user's decision, 2026-09-25), and without a usable heating switch control is blocked
  (decision 11). The OTGW's `CH=` is held: the PIC keeps it until `CH=1` or a reset. The risks of
  "held" (S-12): a parameter the boiler keeps in its memory (for example EMS-ESP's `heatingtemp`)
  but declared held is written at every change and every 5 min — about 288 writes a day; the last
  held command, "off" included, stays while Home Assistant is down.
- Temperatures are in °C and differences in K; the form shows the unit (S-44). A value goes to an
  entity in the entity's own unit (°C, °F or K), rounded to its step inside the limits and
  compared after rounding; its range is checked in the same unit; an entity in any other unit, or
  a setpoint entity with a step above 1 K, keeps control off.
- A write-rate guard against a runaway loop: a write repeated within one control step waits for
  the next one.
- Every write is read back; a command the boiler ignores is reported, never assumed applied. The
  state shown is the value the boiler confirmed, or unknown — never the requested one. Heating
  on and off is confirmed where the device reports it, and marked unconfirmed where it does not.
  A read-back taken from the written entity itself confirms nothing and is marked unconfirmed —
  except a relay's own reported state, which confirms the relay (not that the boiler heats). An
  entity with `assumed_state`, or with no report independent of the plugin, is "unconfirmed" and
  says so (S-09). An `unknown` target is written, and counts only once it is read back (S-28). An
  OTGW read-back is confirmed by the gateway: `TSet` shows what the gateway sends, not what the
  boiler accepted.
- **Changes seen in the read-back** (decision 6, answers C, D, E, H, L, N, O) fall into four
  classes; the plugin never fights another controller. The matrix below says which is which.
- Every exit — unload, reload, error, data loss, an alarm set to hand back, the plugin's own
  monitor failing for 5 min (answer I), a step aside — stops every loop but the hand-back's own
  retry, and makes the safe hand-back (§5), clearing every override.
- A hand-back write is not a control decision: no guard holds it back — not freshness or the
  write-rate guard — and its value (e.g. `CS=0`) is not bound by the hard limits beyond §5's. A
  pending hand-back is stored, shown and retried every minute until it is confirmed (§5 for a
  target another controller takes), and it outlives restarts and option changes: a change that
  would drop it is refused, or a unit that only hands back keeps retrying, with a repair issue. A
  setup that fails sends an owed hand-back first, and reports it by a persistent issue if it is
  still owed when setup gives up.
- **The control state** — the "controlling" marker, an owed hand-back and the options it was taken
  with, the latches, the user's on/off wish, the last command given to the boiler, a SmartPI zone
  the plugin paused — is saved at once and atomically, and read cautiously. A store lost, damaged
  or unreadable for an entry that ran before means "was controlling": a full hand-back first
  (answer K). After a restart without a clean stop, a hand-back is pending until control resumes;
  after any restart the control switch comes back as the user left it, and a control switch
  entity disabled in Home Assistant means control off (answer K).
- The control switch works whatever else is broken: its availability follows the control unit,
  not the monitor. If the plugin's own monitor fails for 5 min, control hands back, and resumes by
  itself once the monitor works again, with an information note (answer I).
- Control only with a known hand-back and, for setpoint control, a source for the confirmed
  setpoint.
- Room values go to the boiler only from a valid reference room; without one they are cleared.
  In room-value mode a failed sensor clears the room values, and the boiler's own control
  carries on.
- The DHW-enable bit stays as it was before the plugin took over.

The four classes of a change seen in the read-back:

- **Lost command** — the read-back is back at the state from before the plugin (the baseline: the
  first known read-back that is not the plugin's value; with an OpenTherm thermostat, its own
  request, where the optional field for it is mapped) and there is a trace of an outage within the 5
  min before: the target, its read-back or another entity of the same device was `unavailable`,
  `unknown` or missing, or the gateway or device restarted — on `opentherm_gw` and ESPHome a restart
  shows as entities going `unavailable`; on the OTGW firmware's MQTT and EMS-ESP a quick restart may
  show nothing but a restarted uptime, which the plugin reads only where the user maps an optional
  restart indicator (Q3.7; provisional, K4). A PIC reset during bus traffic and a Data-Invalid reply
  to ID 1 leave no trace at all. A single such fall-back without a trace is a lost command too. The
  plugin sends the command again at once — both targets as one loss — with no alarm; 3 losses within
  24 h raise the information alarm "commands lost", never a hold. A second untraced fall-back within
  60 min that no send explains counts as another controller; a send explains a fall-back when it
  comes before the plugin's latest send was read back as its value, or within 120 s of a send of a
  new value (answer E).
- **Ignored from the start** — the boiler never takes the value: never read back as the plugin's
  for longer than 120 s after each of the session's first 3 sends (provisional, K4). The plugin
  stops sending it for the session and says "the boiler does not accept the command — check the
  settings"; the other target and frost heating go on; no block, no latch; tried again at the
  next session. A fall-back to the baseline without a trace after every send from the start of
  the session stays here. Except (answer O): where the heating switch's "off" is ignored
  from the start, control is blocked and the boiler handed back at once, with an alarm, and a
  blocker names the reason until the user switches control off and on after fixing it; for a
  relay, the notification says the boiler may keep heating.
- **Clipped** — one lower value, within 0.5 K, whatever the plugin sends (across at least 2 sent
  values at least 1 K apart): accepted as the boiler's own limit, information only; the plugin
  keeps sending its own value and never learns the clip as a limit (provisional, K4). A clip of a
  setpoint that stays flat cannot be told from another controller (a known limit).
- **Another controller** — a value held for 2 steps that is none of the plugin's, its previous
  one, the baseline, the thermostat's own request or a clip: rewritten once (remembered for its
  day, through a clean restart and through switching control off and on); a second change within
  24 h, or the rewrite not read back within 120 s, makes the plugin step aside — the full safe
  hand-back of every target, a relay set once to its rest state and then left alone (answers H,
  L) — with a notification and a latch, stored through reloads and restarts, until the user
  switches control off and on. An optional return by itself (off by default, described, confirmed
  twice; not for relays) starts a new session once no foreign value has been seen for 60 min. The
  reaction "information" for another controller no longer exists.

| Case | What the read-back shows | Class | Reaction |
|---|---|---|---|
| After an outage (device, gateway or broker unavailable; an ESP, PIC or EMS-ESP restart; `opentherm_gw` reloaded) | back at the baseline, with a trace | lost command | sent again at once; "commands lost" at 3 within 24 h |
| A held target back from unavailable | its restored or initial value, or unknown | lost command | every held value sent again at once; the value it came back with is not judged |
| Held values refreshed | not required | — | sent every 5 min, with no echo required; not a rewrite |
| A single fall-back without a trace | back at the baseline | lost command | as after an outage |
| A second untraced fall-back within 60 min that no send explains | back at the baseline | another controller | the day's one rewrite; the next change within 24 h → step aside |
| Refused from the start | never the plugin's value for more than 120 s after each of the first 3 sends | ignored from the start | not sent again this session; information; the heating switch's "off": blocked and handed back |
| The same lower value whatever is sent | a clip | clipped | information; the plugin keeps its own value |
| A foreign value, also while the plugin's value keeps changing or after an unknown read-back at the send | another steady value for 2 steps | another controller | rewritten once; a second change within 24 h → step aside |
| A difference in one step only | — | — | not judged until it holds 2 steps |
| Read-back unknown or unavailable while writing | unknown | — | nothing judged; "confirmation missing" after 5 min; never a hand-back by itself |
| A hand-back against another controller | its value held for 2 retries, or a two-valued target changed after its hand-back state was read back | — | counts as handed back; no retry |
| A held release not confirmed | the lowest water temperature | — | an alarm at once; the release retried every minute |
| The external-control switch turned off while available | off, with no trace | another controller | step aside at once, without a rewrite |
| The external-control switch off after a device restart | off, after unavailable or unknown | lost command | switched on again |
| A hot-water draw | a boiler-state echo goes off | — | not judged during a draw or for 2 min after it |
| The plugin's own lapse (silence over 60 s) | another value | — | sent again; not an outside change |
| Changes no read-back can see (the boiler's panel, a lockout, the maker's app) | nothing | — | not an outside change; seen only through the comfort correction at its limit or "frost not warming"; a fault the boiler reports stops heating (boiler protection) |
| The recognition period | anything | — | the last command restored under decision 3; a read-back not yet showing it is not counted |
| VT's own central boiler configured | — | — | a blocker, never an outside change |
| R1: a relay out of reach | unavailable, unknown or missing | — | nothing written while unavailable or missing; "relay unreachable" after 5 min; no hand-back |
| R2: a relay back in another state after a power or link loss | the other state, with a trace | lost command | the command again; "commands lost" at 3 within 24 h |
| R2a: a relay found in its declared power-cut state without a trace (or, with "last" or "I don't know" declared, changed while available) | that state | lost command up to 3 within 24 h; the fourth: another controller | the command again; an information warning at 3; the fourth steps aside at once |
| R3: a relay switched while it stayed available | the other state, no trace | another controller | rewritten once; a second change within 24 h → step aside to the rest state, then left alone |
| R4: the periodic check finds a mismatch | not the commanded state | by its trace, as R2, R2a or R3 | as R2, R2a or R3 |
| R5: the relay's own switch-off timer | off after its lapse time | — | "on" again, not counted |
| R6: a relay that reports no state | nothing | — | blind repeats; "controlled without confirmation"; a manual change is undone at the next repeat |
| R7: the relay never takes the command | never the commanded state for more than 120 s after each of the first 3 sends | ignored from the start | not written again this session; an alarm-level issue; its "off" ignored: control blocked |
| R8: the relay's hand-back | the rest state | — | done once read back; at a step aside written once and then left alone |
| R9: a planned restart | — | — | the rest state at the stop; the last command restored at once at the start |

How control resumes after it stopped:

| Cause | Control resumes |
|---|---|
| An alarm set to hand back (decision 7) | when the user switches control off and on — a latch: it survives a restart, shows its cause in one repair issue and never expires on its own |
| Another controller (a step aside) | when the user switches control off and on, or by itself after 60 min without a foreign value where that option is on — not for relays |
| A relay found in its declared power-cut state (or, with "last" or "I don't know", changed while available) | the command again (answer D); the fourth within 24 h is another controller: the step-aside latch until off and on (answer N) |
| An internal error | at any change of the control switch; the latch outlives a restart |
| The heating switch's "off" ignored from the start | blocked until the user switches control off and on (answer O) |
| Any other command ignored from the start | at the next session |
| A lost boiler link | on its own, once the data has been fresh for 60 s |
| A relay out of reach | the command again when it returns |
| The boiler's own fault | on its own, in the step where every mapped fault reads off, unknown or unavailable |
| Every zone unknown | on its own, when a zone answers again |
| The plugin's own monitor failing | on its own, once it works again, with an information note (answer I) |
| An alarm with a hand-back reaction already active when control is switched on | blocks control at once; the switch's text says so |
| A blocker — a missing setting, the monitoring period, VT's central boiler configured, Home Assistant starting | on its own, once the blocker is gone; "VT central boiler active" only after the Home Assistant restart its text asks for |

In room-value mode the boiler runs its own control: the curve, ramp, anti-cycling and flow limit
options do not apply; the fixed safeguards do.

Which alarms may hand back (decision 7):

- Always: an internal error; the lost boiler link after 5 min (a relay: an alarm and no
  hand-back); another controller (a step aside); the plugin's own monitor failing for 5 min,
  control resuming by itself once it works again (answer I); the heating switch's "off" ignored
  from the start of the session, with a blocker until the user switches control off and on
  (answer O).
- Optional, information by default: the boiler ignoring any other write — offered only where a
  thermostat or the boiler's own control takes over, never on the relay path.
- Every other alarm informs. Stopping heating for a boiler fault follows the boiler's own logic
  (boiler protection, above); high pressure and hot flue gas get a notification saying what to do.
- Only a known reading at the alarm level, held for 5 min, counts; unknown values never do. An
  alarm whose input is unknown or cannot be judged holds its state for 60 min, then shows
  unknown. A notification closes after 60 min back in the normal range (provisional, K4).
- An alarm with a hand-back reaction that is already active when control is switched on blocks
  control at once, and the switch's text says so.
- The allowed reactions are an allow-list in the code: a new alarm informs by default, and a
  stored reaction no longer allowed is neutralised. Every hand-back an alarm causes raises a
  repair issue, and every latch, whatever its cause, the entry's one latch issue, naming its
  cause — at alarm level where the hand-back's effect is "heating stops", else at warning level.
- A **notification** is a Home Assistant repair issue the plugin raises itself (no service
  call), with a translated text that says what happened and what to do; it closes by itself when
  its condition clears. An **alarm** is the plugin's alarm entity, at the levels warning and
  alarm; "information" is an alarm that never changes control.

Options, each with a cautious default and its risks described (temperatures in °C, differences
in K):

- Boiler demand from the number of zones calling, total power or valve opening, each criterion
  alone or with the others; per zone, "closes when VT switches it off" (off by default,
  decision 4).
- Ramp: how fast the water temperature may change, in K per minute, so the boiler does not
  overshoot a setpoint step and zone algorithms follow.
- VT's activation delay, 0–600 s (decision 5), shown at the simple level and on the relay path.
- Decision interval for the water temperature.
- A fixed fallback setpoint, replacing the curve-based one on outdoor-sensor failure.
- The lowest water temperature (decision 2), the highest water temperature, the circuit maximum
  and its alarm temperature and time (decision 10), and the room-value bounds. The write-rate
  guard and the hand-back's retry are fixed, not options.
- Write type of each picked write target — the setpoint entity, the heating switch and the
  external-control switch each declare their own: **expiring** override — repeated every 30 s so
  it does not lapse (risk, if the entity is in fact stored in the boiler's memory: each repeat
  wears it, about 2,900 writes a day); **held** — the device keeps the value; sent on a change,
  after the device returns and every 5 min (risks: see "Nothing is written to the boiler's
  persistent memory" above); **persistent**, or **unknown** (default) — not written: control
  stays off for a setpoint target, and a heating switch is left unused, which blocks control
  (decision 11). Built-in OTGW repeats `CS` every 30 s; its `CH=` is held.
- A heating on/off read-back: none by default — heating on/off is then shown unconfirmed (risk:
  another controller switching it goes unnoticed). With "gateway with thermostat", the optional
  field "the OpenTherm thermostat's requested control setpoint" tells a lost command from another
  controller; it is refused as the setpoint read-back.
- An age limit per signal (freshness), the weather entity's included: none by default (risk:
  without one a frozen source is not caught; with one shorter than the source's reporting
  interval, control stops in steady weather).
- Frost protection: its limit and release temperature, and whether it watches every zone
  (default) or one zone.
- Comfort correction on (default) or off; its bounds are fixed (principle 13).
- Learning pauses on (default) or off.
- The reactions decision 7 allows.
- The two boiler-fault signals, and the "add water" threshold (none by default).
- The return by itself after another controller (off by default, confirmed twice; not on the
  relay path).
- What is wired to a gateway's thermostat terminals (decision 1).
- "The boiler has its own room controller" (off by default), on the entity and relay paths only;
  on the relay path it counts only with the rest state "on" (answers F, M).
- The relay's settings (§5 class 3): the "separate contact" tick, its state after a power cut,
  its switch-off timer, whether it reports its state, the repeat interval, the rest state and the
  optional proof that the boiler heats.
- Low-flow warning when all valves have been closed for 15 minutes while the pump runs (the pump
  runs on after the burner) — needs a pump-running or CH-active signal; off during hot water and
  when a bypass or low-loss header is declared.

Defaults of the safety options and why (the user reviews them at K4):

| Option | Default | Why |
|---|---|---|
| Control | off; available after 7 days of monitoring | the user sees the verdict first; control is experimental |
| Heating curve | none — the design flow is entered | a wrong curve under-heats or wastes gas; no silent default |
| Emitter type | none — the user chooses | underfloor needs its own maximum flow; a wrong type hides that |
| Lowest / highest water temperature | 20 °C (provisional, K4) / 70 °C | the lowest bounds the curve from below — too low, the boiler stops by itself again and again in mild weather and a non-condensing boiler condenses in its flue (take the value from its manual); too high, warmer water than the rooms need (decision 2); 70 °C covers the usual radiator design points and stays under boilers' maximum |
| Weather ceiling | the curve + 10 K | bounds how far anything may raise the water above the curve |
| Ramp | 1 K per minute | a setpoint step small enough that the boiler does not overshoot it; zone algorithms follow, and larger swings pause SmartPI's learning (S-47) |
| Decision interval | 5 min | VT's default cycle |
| Activation delay | 0 s | as in VT 10.4.0; a delay is for slow valves (decision 5) |
| Write type of a picked target | unknown — control stays off until the user declares it expiring or held | the plugin cannot tell the type itself, and a wrong guess wears the boiler's memory |
| "Off" setpoint | 10 °C — only where "off" sends one with the heating switch (OTGW `CS`, never below 8 °C) | far below any heating value; a low setpoint alone is not "off" (decision 11) |
| Hand-back value (entity) | none — entered with its effect | 0 may mean "no heat" on one device and "own control" on another |
| Fallback setpoint | the last effective outdoor temperature for 3 h, then the design flow, or the user's fixed value (decision 9) | never zero heat; the valves keep rooms from overheating |
| Frost limit / release | 5 / 7 °C | above freezing with a margin, below any comfort setpoint |
| Frost protection | every zone, heated only where its emitter can take heat | heat for a zone VT keeps closed cannot arrive; a repair issue says what to do instead (decision 4) |
| Demand threshold | one zone calling | any zone calling heats, as with VT's central boiler |
| Comfort correction | on, up to +3 K | helps a room its emitter cannot heat on the curve, bounded so the others do not overheat |
| Learning pauses | on | keep swings the plugin causes out of SmartPI's model |
| Alarm reaction | information; the hand-backs of decision 7 always | another controller is writing — never fight; the plugin stops heating only where the boiler itself stops |
| Circuit-maximum alarm | the circuit's maximum + 5 K, for 10 min (information) | the boiler may overshoot the maximum; the user sees it (decision 10) |
| "Add water" threshold | none | the value comes from the boiler's manual; a wrong default stops nothing but misleads |
| Boiler-fault signals | none | the user maps the boiler's own fault where the integration shows it |
| Thermostat terminals (gateway) | none — required; "I don't know" blocks control | an on/off contact could not heat the house after a crash while "off" (decision 1) |
| "The boiler has its own room controller" | not ticked | without it, VT giving no answer means no heating and an alarm, never a guess (answers F, M) |
| Relay rest state | off | a relay left "on" heats without room control; the notification says when "off" leaves the house without heating |
| Relay settings | "I don't know" — its state report treated as "no" | the cautious reading of each unknown: blind repeats, "maybe on" after a power cut, "may have a timer" |
| Relay repeat interval | 300 s (10–300 s) | renews a relay that may switch itself off, without flooding it |
| Relay "separate contact" tick | not ticked — control does not start without it | a setting stored in the boiler's memory would be worn by every switching (answer G) |
| Return by itself after another controller | off | the other controller may still be there; the user checks first |
| Freshness age limit | none — availability only | many sources report only on change; a limit on such a source would stop control in steady weather |

Fixed values (S-37) — not options. "Reason to confirm" marks a value whose reason is not recorded
yet; the user reviews every provisional value at K4.

| Value | Where | Why |
|---|---|---|
| Control step 10 s | `const.py` | heating follows the zones at once |
| Keep-alive 30 s | `control_config.py` | OTGW needs `CS` at least once a minute |
| Lowest OTGW `CS` 8 °C | `transport/writers.py` | below 8 °C an override never lapses |
| Confirmation timeout 120 s; tolerance 0.5 K | `core/guards.py` | reason to confirm |
| Write interval at least 5 s | `core/guards.py` | one write per step |
| The plugin's own lapse after 60 s of silence | `core/guards.py` | an OTGW override lapses after about a minute |
| Rewrite window 24 h | `core/guards.py` | decided 2026-09-25 |
| Hand-back retry 60 s | `control.py` | existing |
| Lost link: 5 min stale within 10 min; back after 60 s fresh | `core/controller.py` | 5 min decided 2026-09-25; window and recovery provisional, K4 |
| Zone-unknown alarm 30 min | `control.py` | reason to confirm |
| Outdoor hold 3 h; outdoor time constant 3 h | `core/curve.py` | decision 9; the time constant: reason to confirm |
| Stuck sensor 12 h within 3 K; deviation 6 K over at least 2 h of overlap | `core/signal_check.py` | reason to confirm |
| Comfort correction +3 K, 30 min per K, 3 h at the edge, 1 K over stops the rise; satisfied below 70 %, short by 0.3 K | `core/controller.py` | decided 2026-09-25 |
| Frost not warming: 2 h, 0.5 K | `core/controller.py` | reason to confirm |
| A zone takes heat above 5 % open, saturated at 95 % | `core/readings.py` | existing |
| Plausible room reading −30 to 45 °C, one rule for every room reading | `core/limits.py` | a narrower range would hide a cold room from frost protection (S-06; provisional, K4) |
| Learning pauses: a swing of 5 K in 30 min, a pause of at least 10 min, resume within 3 K, longest pause 60 min, read back after 1 min | `core/learning.py` | existing |
| Low-flow warning after 15 min | `core/alarms.py` | existing |
| A short burn is under 10 min | `core/metrics.py` | reason to confirm |
| Recognition period at most 10 min; grace 10 min | control | decided (decision 3) |
| Relay out of reach 5 min | control | decided |
| Untraced fall-back window 60 min; a send explains a fall-back within 120 s of a new value | guards | decided (answer E) |
| Return by itself after 60 min without a foreign value | guards | decided |
| A relay in its declared power-cut state: warning at 3 within 24 h, the fourth steps aside | control | decided (answers D, N) |
| The plugin's own monitor failing: hand-back after 5 min | control | decided (answer I) |
| Activation delay 0–600 s in steps of 10 | options | decided (decision 5) |
| "Off" at least 1 K below the lowest water temperature; refused within 0.5 K of an "own control" hand-back value | limits | decided (P-43, S-49) |
| Relay check 5 min; blind repeats every repeat interval; timer lapse at or after max(timer − 60 s, timer ÷ 2), renewal every min(timer ÷ 2, repeat interval) | control | provisional, K4 |
| Held values resent every 5 min | control | provisional, K4 |
| "Commands lost" at 3 within 24 h, cleared after 24 h without a loss; trace window 5 min | guards | provisional, K4 |
| A difference judged after 2 steps (20 s) | guards | provisional, K4 |
| Ignored from the start: never shown for more than 120 s after each of the first 3 sends | guards | provisional, K4 |
| Clipped: one lower value within 0.5 K across at least 2 sent values at least 1 K apart | guards | provisional, K4 |
| "Confirmation missing" after 5 min | guards | provisional, K4 |
| A boiler-state echo not judged within 2 min of a draw | guards | provisional, K4 |
| A hand-back taken by another controller after 2 retries | hand-back | provisional, K4 |
| An alarm level counts once held 5 min; a notification closes after 60 min in range; an unknown input held 60 min, then unknown | alarms | provisional, K4 |
| A boiler fault stops heating after 5 min on | control | provisional, K4 |
| Wall-thermostat warning below 15 °C | monitor | provisional, K4 |
| A passive fixed circuit's margin 5 K | limits | provisional, K4 (reason to confirm) |
| A timeout hand-back released within 0.5 K of the baseline; "hand-back failed" after 3 min | hand-back | provisional, K4 (S-20) |
| A relay's proof-of-heat window 30 min after "on" | control | longer than a common 20-min restart lockout; provisional, K4 |
| "Not worth it" only with at least 2 criteria judged | verdict | provisional, K4 (S-32) |
| "Handed back in frost" below the frost limit, cleared at the release | alarms | provisional, K4 (S-57) |
| The lowest-water-temperature suggestion: the reference + 2 K, rounded up to 0.5 °C, below the caps | monitor | provisional, K4 |
| J4's starts criterion: at most the boiler's own regulation's starts per hour × 1.10 | acceptance | provisional, K4 (S-15) |
| The wait for a late report: 60 s at the start; at the stop the whole hand-back within 15 s, each write capped at 3 s, the read-back wait min(5 s, the time left) | hand-back | Home Assistant gives all shutdown jobs 20 s together (Q3.3); an ESPHome device reports within about 60 s of a start, up to about 74 s without mDNS — 90 s the alternative (Q3.5); provisional, K4 |

| The last command saved at once on a move of 1.0 K | control state (V3) | provisional, K4 (reason to confirm) |
| An OTGW release window of 60 s | hand-back (V4) | provisional, K4 (reason to confirm) |
| A held release's alarm after 10 s; taken by another after 2 checks 60 s apart (3 over 120 s with hot water unknown, none within 120 s of a draw) | hand-back (V5) | provisional, K4 (reason to confirm) |
| The monitor failing: 300 s within 600 s; control resuming after 60 s without a failed refresh | control (V6) | 300 s decided (answer I); the rest provisional, K4 |
| The "blocker stopped heating" issue after 60 s | control (V7) | provisional, K4 (reason to confirm) |
| A joint fall-back of both targets within 20 s counted as one loss; an attempt with a trace not counted toward "ignored from the start" | guards (X1) | provisional, K4 (reason to confirm) |
| The P-105 grace 600 s | VT link (X3) | provisional, K4 (reason to confirm) |
| Circuit-alarm hysteresis 1 K; its time 1–120 min; the comfort correction at most 3 K a day; the DHW resume cap 1 h after a draw | control (X4) | provisional, K4 (reason to confirm) |
| Design flow at least the room + 5 K; design outdoor at most the room − 10 K | form (X5) | provisional, K4 (reason to confirm) |
| The suggestion's evidence: 7 days, 20 burns, a share of 0.5, 1 K bands, 50 % opening, +2 K, 2 K under the caps; the wall-thermostat issue after 30 min; the 25 °C migration floor | monitor (X6) | provisional, K4 (reason to confirm) |
| VT's setup-error issue after 10 min; a 0.05 factor change | VT link (X7) | provisional, K4 (reason to confirm) |
| Relay timer tolerance 60 s; a flow rise of 5 K as proof of heat; 20 remembered contexts | control (X8) | provisional, K4 (reason to confirm) |
| Alarm holds 5 min; an unknown input held 1 h; 50 % known flame; the limit − 2; 2 K; a 10-K slope span; 0.05 bar/K; 40 °C; 0.1 bar | alarms (Y1) | provisional, K4 (reason to confirm) |
| Hot-water inference 0.35–0.65; 12 h; 6 h; 10 min; 1 h | monitor (Y2) | provisional, K4 (reason to confirm) |
| Building model: 8 K; 12 K; 2 K; 3 of 4; 2 of 3 | monitor (Y3) | provisional, K4 (reason to confirm) |
| Forecast call timeout 30 s | forecasts (Y4) | provisional, K4 (reason to confirm) |

The steps of `docs/plan-0.2.2.md` that build these values record their reasons; a value a step
finds it needs beyond this table is added with "reason to confirm at K4", as a diff for consent.

### Forecast roadmap

| Step | Use of the forecast | Stage | Release |
|---|---|---|---|
| FC0 | record forecast snapshots from day one | Monitor | 0.1 |
| FC1 | summer/winter switch from a multi-day forecast, without flip-flopping (to be decided against principle 12, decision 13) | Curve | 0.3 |
| FC2 | anti-cycling planning for mild hours ahead (to be decided against principle 12, decision 13) | Anti-cycling | 0.3 |
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
| Starts-per-hour budget instead of a fixed pause | `pwm.py` | Anti-cycling (to be decided against principle 12, decision 13) |
| Gating of learning samples (stable modulation, flow near setpoint, no duty cycling) | `minimum_setpoint.py` | Water-side learning |
| Return temperature as a correction of the minimum setpoint | `minimum_setpoint.py` | Curve tuning (condensing) |
| Bounded parameter nudges with an average of recent optima | `heating_curve.py` | Curve tuning |
| Fresh flow read right after writing a setpoint | `mqtt/opentherm.py` | Later (§9, S-60) |
| Overshoot calibration procedure | `overshoot_protection.py` | Later (§9, S-60) |
| Gas estimate from modulation | — | Monitor |

**Not taken:** its room controller, its constants (e.g. a minimum burn of about three minutes),
manufacturer files (S-59).

**Where we do better:** control handed back on unload, connectivity checked before writes,
explicit keep-alive — SAT sends the setpoint only when its loop runs.

### Google Nest

| Nest feature | Here | Stage |
|---|---|---|
| Long burns at low water (OpenTherm + True Radiant) | main strategy: low, long, rare | Curve, Anti-cycling |
| Seasonal Savings | seasonal tune-up of the **curve** (not room setpoints) | Curve tuning |
| Home Report / Energy History | report explaining changes (weather / DHW / settings) | Monitor |
| Furnace Heads-Up | early warning: flue gas, ignitions, pressure, hysteresis | Monitor |
| Leaf | condensing indicator | Later (§9, S-60) |
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

With no release yet, unless the user names one at K4 (S-60): the fresh flow read after a write;
the overshoot calibration; the boiler's MemberID and supported messages; the condensing
indicator; the boiler's installer settings; SmartPI's better signal and bootstrap state (S-29);
relay commands beyond a switch and a boiler thermostat entity (VT's free-form actions), if asked;
a separate echo entity for a relay; a wiring field for the relay (alone, parallel, series), if
asked. With a release: the "apply" mode of the lowest water temperature (0.3, once the simulator
shows it helps); the wall thermostat linked to a VT zone, VT leading and off by default (0.3 at
the earliest); radiators and underfloor behind a mixing valve as one written circuit plus passive
fixed circuits (0.3); a warning for zones the boiler does not feed — air conditioners in heat
mode, electric heaters (0.3); a recorded "heating commanded" entity and event for users leaving
VT's central boiler (0.3).

**Excluded:** heat pumps, room regulation, valve control, sending data outside.

## 10. Assess before control

The Monitor stage lets any user assess their installation before enabling control:
cycling at low load, burn times, condensing share and the building load versus the boiler's
minimum power. Regular users get a verdict with the reason; power users get the underlying
metrics. Control becomes available after a minimum monitoring period (default 7 days); the
verdict stays visible and the user decides. The period counts calendar days from the entry's
creation, so a lost store does not restart it (answer K); the user may lengthen it, up to 60
days, but not shorten it. Off-season, when the period ends without enough data, the control
switch says that control starts without a verdict (S-43).

The verdict rests on what was measured and on what the released control changes:
- "Worth enabling" comes only from problems that 0.2.2's control changes; the others are shown
  as "not changed yet" (S-22, answer K). The load criterion counts only with an entered or
  confidently measured building model (confidence at least 0.5); an estimate from rule-of-thumb
  defaults is marked as such and decides nothing (S-17). An entered design load always wins over
  a measured one, and the texts say so.
- "Not worth it" only with at least 2 criteria judged (provisional, K4); otherwise "not enough
  data" (S-32).
- Gas measured while the burner is off — other consumers on the meter — is reported apart, not
  counted as heating gas (S-31; provisional, K4).
- The building model feeds the monitor only; it is visible and resettable. Bounded learning
  (principle 13) covers what control uses.

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
- Lifting the block on control without a heating switch ("off" as a low setpoint) and on
  decision 1's low `CS` with `CH` left alone: only the user, at K4, on the research of whether a
  low setpoint stops both the boiler and its pump — even if that research is favourable
  (decision 11, answer K; L4 of `docs/plan-0.2.1.md` is closed by decision 11).
- The first published version and the repository's content (decision 16): the version after
  the independent check of 0.2.2 and at K4 — provisionally pre-release 0.2.2b1, then 0.2.2; the
  content at K5.
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
- GitHub and every publication come after 0.2.2 — 0.2.1 and 0.2.2 correct 0.2 after its reviews;
  the first pre-release is 0.2.2b1 (provisional, decision 16) and monitors first because control
  is off by default (2026-09-24, 2026-09-25, 2026-09-27).
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
  stand-alone, every fallback ends heating; monitor mode allows no control. "Every fallback
  returns control to the thermostat" holds for an OpenTherm thermostat only; an on/off contact on
  the terminals blocks control (decision 1, S-01). `CS` of 8 °C or more lapses unless repeated
  within a minute; below 8 °C it never lapses, so the plugin never writes it as a setpoint and
  writes "off" as `CS` of at least 8 °C with CH off. The gateway mode is stored in the gateway;
  the plugin never changes it and never sends `HW=` or `BW=`, so the DHW-enable bit stays as it
  was. The firmware's `TSet` echoes what the gateway sends, not what the boiler accepts.
  `CH=` is held: the gateway keeps a `CH=0` through `CS=0` and the override's lapse until `CH=1`
  or its PIC resets, and applies it to any later `CS` and to an on/off thermostat's demand, while
  `TSet` still carries `CS` with `CH=0` (PIC firmware 6.6, found by the review of 2026-09-24).
  Hand-back is the safe hand-back: `CS` at the lowest water temperature, `CH=1`, then `CS=0`.
- Auto-TPI (research F2): without VT's central boiler, Auto-TPI never learns in zones flagged
  "used by the central boiler"; the plugin raises a repair issue naming them, which states what
  its advice costs. It is detected, not paused, because `set_auto_tpi_mode` is not a pure pause;
  a pause comes in a release set at K4 (S-29).
- VT feature manager (research F4): registered once VT's API exists; a thermostat already
  running picks it up at VT's next reload, which the plugin never triggers.
- The user's decisions of 2026-09-25: VT decides whether to heat, nothing the plugin counts or
  times holds heating against VT, and what the plugin learns stays within firm bounds
  (principles 12 and 13); frost protection as an exception, for every zone or one picked zone
  (2026-09-26/27: one of principle 12's stated exceptions, heating only zones that can take
  heat); summer and winter come from VT; VT's central modes act through the zones' demand, and
  "Stopped" is not a hand-back; a lost boiler link raises an alarm and hands back in every
  topology — stand-alone, heating stops (2026-09-26/27: a relay gets an alarm and no hand-back);
  the comfort correction's bounds; nothing written to the boiler's persistent memory; a value
  never confirmed against another steady value counts as changed from outside (2026-09-26/27:
  replaced by decision 6's four classes); with some zones unknown the known ones decide, with an
  alarm (2026-09-26/27: after a grace period of 10 min, decision 3) (§7). For the monitor: the
  verdict's window, degree-days and starts per hour (§10); "hot water available" is unknown while
  the flow is (§5).
- The user's decisions of 2026-09-26/27 (`docs/plan-0.2.2.md`):
  1. Both gateway topologies ask what is wired to the thermostat terminals; control is blocked
     for an on/off contact and for "I don't know".
  2. One setting, the lowest water temperature, default 20 °C; 0.2.2 only suggests a value.
  3. A recognition period and a 10-min grace; with every zone unknown, a hand-back to a working
     thermostat, else no heating, with an alarm.
  4. Frost protection heats only zones that can take heat; a repair issue for a closed one.
  5. VT's activation delay carried over, 0–600 s, default 0.
  6. Four classes of outside change: lost command, ignored from the start, clipped, another
     controller.
  7. Only an internal error, the lost link, another controller, the monitor failing and "heating
     off" ignored from the start hand back; everything else informs.
  8. Merged into decision 6.
  9. The outdoor temperature's last value holds 3 h, then the fixed fallback or the design flow.
  10. The circuit maximum limits the setpoint; an information alarm above an alarm temperature.
  11. Control without a heating switch is blocked until the user lifts it at K4.
  12. A deviating outdoor sensor: the colder of the sensor and the weather entity.
  13. Class 3 comes into 0.2.2 without minimum times or a switching cap; anti-cycling in 0.3 is to
      be decided against principle 12.
  14. CI fetches VT 10.4.0 and SmartPI 0.4.0 from their tags on GitHub's servers.
  15. J4 provokes an unclean restart and a lost link in the test container only.
  16. The first published version after the independent check and at K4; the content at K5.
  Also: the missing-data rule, boiler protection by the boiler's own fault, the safe hand-back,
  on/off control through a relay, and the wall thermostat on a gateway (§5, §7).
- The user's answers of 2026-09-27: C, D — a relay switched while available is another
  controller, one found in its power-cut state is a restart; E — a single untraced fall-back is a
  lost command, a second within an hour that no send explains is another controller; F — without
  VT's answer the boiler goes to a working thermostat, else no heating; G — the relay's "separate
  contact" tick; H — stepping aside is the full safe hand-back; I — the plugin's own monitor
  failing for 5 min hands back and resumes by itself; J — a "Reset comfort correction" button; K —
  a lost store means "was controlling", the switch returns as the user left it, the verdict counts
  only what 0.2.2 changes, lifting blocks waits for K4, a gateway entry without the terminals
  answer stays stopped; L — a relay set once to its rest state at a step aside; M — the "own room
  controller" tick counts on the relay path only with the rest state "on", and is not offered on a
  gateway; N — a fourth relay restart within 24 h is another controller; O — "heating off" ignored
  from the start blocks control and hands back.
- Provisional control decisions (K4): control only for one circuit fed by the boiler flow and a
  boiler of the class "flow setpoint" or "on/off" (a relay); the curve's design flow is entered,
  never defaulted; control refused while VT's own central boiler is configured and during the
  monitoring period; the first setpoint of a session is the curve's value, not ramped from the
  current flow; comfort correction on by default; alarm reactions as decision 7; frost protection
  during the recognition period for zones already known; control resuming by itself after an
  every-zone-unknown hand-back.
- Provisional write decisions (K4): boiler data is there while flame and flow are known — a
  steady reading is not a stale one, as many sources report only on change; its age counts only
  with a user-set freshness limit; without the data nothing is written, and after 5 min an alarm
  is raised and control hands back (stand-alone, the gateway stops heating within a minute of the
  last keep-alive); a relay's link is the relay. A failed write is sent again at the next step;
  the setpoint goes before heating on/off, which is repeated with an expiring setpoint. Changes
  seen in the read-back follow decision 6's four classes, with no reaction to choose; another
  controller is rewritten once, and within a day never again, whatever the plugin wrote in
  between, then the plugin steps aside with the full safe hand-back (answer H) and is not retried
  against it. A lapse the plugin caused itself (silence while data was stale) is not an outside
  change. "Off" goes through the heating switch (built-in OTGW: `CH=0` with `CS` of at least
  8 °C); without one, control is blocked until the user lifts it at K4 (answer K); a boiler that
  ignores "heating off" from the start is blocked and handed back until the user switches control
  off and on (answer O). A heating switch is turned on at hand-back only where the boiler returns
  to a thermostat or its own control. A timeout hand-back needs expiring writes. A failed
  hand-back is shown and retried every minute until it is confirmed; at Home Assistant's stop the
  hand-back runs before integrations stop. Latches survive a restart; the control switch comes
  back after a restart as the user left it, the wish saved at once, and a disabled switch entity
  means control off (answer K); control waits for its blockers. The plugin's own monitor failing
  for 5 min hands back, and control resumes by itself once it works again (answer I).
- Answers to the review's questions (provisional, K4): 3 — "heat flows" is the flame when known,
  else the command; 5 — a corrupt or lost store is unreadable: a full hand-back first, and the
  monitoring period counts from the entry's creation; 6 — the switch comes back as the user left
  it, the wish saved at once; 8 — "pressure 0 = unknown" only for the gateway's sources; 9 — an
  alarm with an unknown input holds its state 60 min, then shows unknown; 10 — an options save
  that touches no control option reloads without a hand-back, and one that does says it hands
  back; 11 — bounded learning covers what control uses, while the building model feeds the
  monitor only and is visible and resettable; 12 — an entered design load always wins; 19 — the
  zone pick accepts only VT climates, checked on the server (the warning for zones the boiler does
  not feed comes in 0.3); 20 — diagnostics work for an entry in setup error.
- Learning pauses (SmartPI) only while control runs; the water-swing check follows the heating
  setpoint, not the low "off" value (K4).

## 12. Release

Public from 0.2.2 (provisional, decision 16) — 0.2 corrected after its reviews (0.2.1, 0.2.2): a
GitHub repository, created after 0.2.2 and installed through HACS as a custom repository. 0.2.2
passes the test environment, then runs on the author's installation — monitoring first, since
control is off by default — as pre-release 0.2.2b1, then as a release. Which version is published
first is decided after the independent check of 0.2.2 and at K4; whether the repository carries
`CLAUDE.md`, the plans and the reviews, and so whether it starts from a clean history, at K5. HACS installs only from public
repositories, so the repository is public from the first pre-release. The plugin needs Home
Assistant 2026.9 or later, the version it is tested on. Submission to the HACS default list and
the VT plugin list later (HACS review takes months). Creating the repository and every
publication need the author's consent.
