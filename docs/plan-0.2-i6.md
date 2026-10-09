# Plan 0.2, step I6 — The setup starts with how the boiler is connected

Goal: the setup wizard and the options open with the few choices that shape everything after
them — how the boiler is connected, the control mode, the heat source and the boiler type — and the
later steps show only what fits those answers. Step I6 of `docs/plan-0.2.md`, widened by the user's
decisions of 2026-10-08 and 2026-10-09 below. Control stays off by default: no answer switches
anything on.
Scope: `SCOPE.md`; overview: `PLAN.md`; the release plan: `docs/plan-0.2.md`.

Status on 2026-10-09: approved by the user (I6.0); I6.1 to I6.6a done; next I6.6b. The corrections from the test report
that the user put first (F1, F2, F5) are done as pull requests #32, #34 and #35.

## How to read this plan

- "Decision n" refers to the numbered list below.
- 🔒 marks a step that needs the user's consent or answer; ✅ marks a finished step.
- Every step is one pull request into `dev`, with its "J4 impact": the J4 scenarios to run again in
  the test Home Assistant once it is deployed. After each step the main session reports to the user
  in Polish (the user's rule of 2026-10-08).
- An entry made before I6 has none of the new answers. It works exactly as today: no new blocker,
  no field hidden, the control step offering the paths by boiler class as before. Nothing is
  guessed for it; the options offer the new panels, pre-filled where the stored write path says it
  (decision 12).

## Decisions of 2026-10-08 and 2026-10-09 (the user)

1. **The first panel asks how the boiler is connected** — the very first panel of the setup; the
   name and the level of detail follow it. The answers:
   - the OpenTherm Gateway through Home Assistant's integration (`opentherm_gw`);
   - the OTGW firmware over MQTT;
   - ESPHome OpenTherm;
   - EMS-ESP;
   - a relay (an on/off boiler);
   - the boiler's own Wi-Fi module or the manufacturer's integration;
   - another writable entity — always offered, labelled advanced;
   - another integration, read only (replacing "monitoring only", which became a control mode,
     decision 6).
2. **What the connection sets** (provisional, K4) — the write path, the write types, the hand-back,
   whether a heating switch is required, the boiler class (what the connection can do, not what the
   user wants: the verdict "worth enabling" needs the flow-setpoint class), the entities suggested,
   and the text of what happens to the boiler when Home Assistant stops:

   | Connection | Write path | Write types | Hand-back | Heating switch | Class | When Home Assistant stops |
   |---|---|---|---|---|---|---|
   | OTGW (integration) | `opentherm_gw` | fixed (`CS` expiring, `CH=` held) | the safe hand-back | built in | flow setpoint | the gateway drops the setpoint within a minute; with a thermostat it takes over, stand-alone heating stops |
   | OTGW over MQTT | `otgw_mqtt` | as above | as above | built in | flow setpoint | as above |
   | ESPHome OpenTherm | entity, topology virtual | held, held | a value (suggested) | required | flow setpoint | the ESP keeps the last setpoint and CH enable until it restarts (API `reboot_timeout`, 15 min by default), then its configured start values |
   | EMS-ESP | entity, topology virtual | setpoint expiring | the device's timeout, 1 min | not needed (decision 4) | flow setpoint | the setpoint lapses within about a minute; the boiler returns to its own setting |
   | Relay | relay | — | its rest state | — | on/off | the relay stays as it was |
   | Wi-Fi module or manufacturer | entity | unknown (not written) | — | required | read only (suggested) | depends on the device; writes usually go to its memory or through a cloud |
   | Another writable entity | entity | declared by the user | chosen by the user | required | flow setpoint | depends on the device |
   | Another integration, read only | none | — | — | — | read only | nothing is written |

   Entities suggested: on the OTGW integration, where exactly one gateway is set up, its boiler
   device's entities are filled in (by the integration's unique IDs `<gateway>-boiler-<key>`:
   `slave_flame_on`, `ch_water_temp`, `return_water_temp`, `relative_mod_level`, `slave_dhw_active`,
   `ch_water_pressure`, `slave_low_water_pressure`, `slave_fault_indication`; the read-backs
   `control_setpoint` and `master_ch_enabled`), shown for the user to check; for the others the
   signals step names what to pick (ESPHome's `flame_on`, `t_boiler`, `t_ret`, `rel_mod_level`,
   `ch_pressure`, `dhw_active`, `fault_indication`, `low_water_pressure`; EMS-ESP's `burngas`,
   `curflowtemp`, `rettemp`, `curburnpow`, `syspress`, `selflowtemp`). No entity ID is ever written
   into code, defaults, tests or docs: the suggestion comes from the integration's own identifiers.
3. **ESPHome:** control needs the user's tick "on the ESP I have set safe start values and a short
   API `reboot_timeout`", as the relay needs its separate-contact tick; without it, a blocker. The
   user guide gives a sample configuration (`api: reboot_timeout` of a few minutes; the `t_set`
   number with `restore_value: false` and an `initial_value`; the `ch_enable` switch starting off;
   `force_update: true` on the sensors) and the alternative of a moderate start temperature with its
   risk.
4. **EMS-ESP: "off" is setpoint 0** (the user, 2026-10-08; EMS-ESP's own documented way to keep
   heating off, "Force Heating Off"): written as an expiring value every 30 s like every setpoint on
   this path, with no heating switch — decision 11 of `docs/plan-0.2.2.md` lifted for EMS-ESP only,
   and only with the setpoint declared expiring, so that a stopped Home Assistant leaves the boiler
   on its own control within about a minute. "Off" is fixed at 0 there (no "off" field). The read-back
   is `selflowtemp` itself, which EMS-ESP fills from the boiler's own report. A 0 the boiler ignores
   from the start blocks control and hands back, as answer O does for a heating switch (a change in
   `core/loop.py`, with its test first). What the pump does at 0 is not known: the texts say so.
5. **The boiler's Wi-Fi module or the manufacturer's integration:** monitoring by default; control
   only with a write type that is known and not persistent (the existing rule).
6. **The control mode, on the second panel, with no default** — it is one of the first choices and
   is made on purpose: full control (the curve, the water temperature); on/off (the relay); room
   temperature only — "from version 0.3", the monitor only until then, with the reason shown;
   monitoring only. Only the modes the connection allows are offered.
7. **The heat source:** gas (natural or LPG), oil, electric, other. Pellet and biomass are left out
   for now. The source decides which fields, signals and alarms are shown: electric — no flame,
   flue gas, condensing or gas: the flame signal reads "heating on", the gas meter an energy meter;
   oil — no gas meter or gas rates; "other" and an entry without an answer — everything, as today.
8. **The boiler type, by its standard names:** single-function without hot water; single-function
   with a hot-water tank; combi (instantaneous hot water); combi with a built-in tank. Then
   condensing or conventional (gas and oil only), and the hot-water priority — with priority
   (default, as today) or without — for every boiler that heats hot water: a combi may share heat
   (a time-limited priority, a buffer, a tank charged in parallel). Without priority, hot water
   neither pauses SmartPI's learning nor marks heat unavailable to the zones; telling hot-water
   burns from heating stays as it is. An optional hint: a boiler that often reports heating active
   together with hot water active may have no priority — information only. The stored values
   `none`, `storage`, `combi` keep their meaning; a combi with a built-in tank is a new value.
9. **Freshness limits get sensible defaults, with forced updates for every connection** (the user,
   2026-10-09). Where Home Assistant writes only changes, "data flowing" is known in two layers:
   - the device's availability (its MQTT online/offline, ESPHome's API link), which turns its
     entities unavailable — already read; it does not see a device that is online while the
     boiler's data stop (a link inside an OTGW, say);
   - the device's own repeats: the OTGW firmware publishes every value at least every 60 s, EMS-ESP
     at its publish interval, and Home Assistant drops the unchanged ones. The plugin listens to
     the device's MQTT messages itself, reading only, and takes the time of the last message as the
     signals' report time: on the OTGW firmware from its topics (top and node, asked with the
     connection, not only with control), on EMS-ESP from its base topic (a field, `ems-esp` by
     default). The defaults follow the device's rhythm (5 min for the OTGW firmware's 60 s; EMS-ESP's
     from its interval, to be checked at I6.5).
   On ESPHome the repeats are forced on the ESP (`force_update: true` on its sensors, in the sample
   configuration); the plugin checks that a sensor re-reports and warns where it does not. On the
   OTGW integration, which rewrites every entity on each report: 10 min. The weather entity: 3 h.
   Another MQTT device whose topics are not known: availability, and a limit the user may set.
10. **The highest water temperature:** its three fields stay (the boiler's, the circuit's, control's);
    the curve step shows which one applies and where it comes from; merging them waits for K4. An
    installation may have the boiler's control and a separate controller for an underfloor mixer:
    the stored layout of the new answers allows a second control configuration, per circuit;
    controlling two circuits at once stays in 0.3, as `SCOPE.md` §5 has it (the user, 2026-10-09).
11. **Control in the wizard:** with full control or on/off chosen, the control steps follow in the
    setup; the control switch still starts off.
12. **Existing entries** keep working as they are, with no automatic migration (an entity path may
    be ESPHome, EMS-ESP or another device); the options offer the new panels, pre-filled from the
    stored write path where it says the connection (`opentherm_gw`, `otgw_mqtt`, `relay`). A stored
    answer this version does not know leaves control out at setup, the monitor running, and is shown
    on its panel at the next save (P-70).
13. **The test report's F1, F2 and F5 first** — done: #32, #34, #35.
14. **This plan is kept in this file.**

## Facts found for this plan

- ESPHome (docs and source, `research/2026-10-08-i6-esphome-docs-check.md`): the API
  `reboot_timeout` defaults to 15 min and `0s` disables it; CH enable goes to the boiler only with the
  hub flag, the `ch_enable` switch on and a setpoint above 0; the OpenTherm number takes
  `initial_value` and `restore_value`.
- Reporting (`research/2026-10-08-i6-reporting-behaviour.md`): Home Assistant's ESPHome and MQTT
  integrations write a state only when it changes (unless the source forces an update); the OTGW
  firmware publishes on change with a 60 s heartbeat its discovery does not force; the OTGW
  integration rewrites every entity on each report. A freshness limit on an on-change source
  measures the time since the value last changed — a limit on a flame that stays off for hours
  would stop control and hand back, and could leave a house unheated with nothing ever changing.
- The flows (`research/2026-10-08-i6-flow-map.md`): control is set up only in the options today;
  the boiler class decides whether the verdict can say "worth enabling"; storage and combi are not
  told apart anywhere (only "has hot water"); the hot-water learning pause does not read the
  boiler type; an electric boiler has no flame, so most of the monitor is off and water-temperature
  control is blocked; "condensing" defaults to ticked and the flue-gas limits are asked for any
  boiler; the design outdoor temperature is entered twice (building, curve) and only pre-filled once;
  the "add water" and high-pressure limits are advanced only, and "restore defaults" drops them
  though they come from the boiler's manual.
- Kept in mind at I6.6a: `has_control_section` assumed control is set up only in the options of an
  entry that has run, so a control section without a stored state was taken as a held boiler. An
  entry made by the wizard with control set up has never held the boiler: an entry created less
  than 30 minutes ago, with neither store there and none of its entities registered, owes nothing
  at its first start. A store there but unreadable, or registered entities (an entry that ran,
  its stores damaged), still hand back first; so does an older entry that lost its stores.

## Steps

| Step | Work | J4 impact |
|---|---|---|
| I6.0 ✅ | the user approves this plan, and answers decisions 9 and 10 (2026-10-09) | — |
| I6.1 ✅ | the first panels: the connection (decision 1), the control mode (6), the heat source (7), the boiler type with condensing and hot-water priority (8), then the name and level; the answers stored as their own keys; the boiler class from the connection, no longer asked; "room temperature only" gives the monitor with its reason; the options menu opens with the same panels; an entry without the answers as today (12); translations EN and PL; tests | the setup and the options' first steps: G1–G3 |
| I6.2 ✅ | what the connection sets (decision 2) in the control steps: the paths offered, the write types, the hand-back, the topology; the ESPHome tick and its blocker (3); EMS-ESP's "off" at 0 and its answer-O latch (4, `core/` first); the blockers "connection does not fit the write path" and "topology does not fit the connection"; the entities suggested; translations, tests | every control scenario on the OTGW integration still passes unchanged; G1–G3 again |
| I6.3 ✅ | the heat source (decision 7): fields, signals and alarms shown or hidden; the electric boiler's "heating on"; the defaults for condensing by source | the monitor's scenarios with the sim's gas boiler: none expected; F1, F2 |
| I6.4 ✅ | the hot-water priority (decision 8): the learning pause and heat availability follow it (`core/` first); the optional hint deferred — how boilers report heating and hot water at once is not known, and a wrong hint would mislead (`docs/plan-0.2-i6.md`, Open after I6) | D8 (the SmartPI pause on a draw) |
| I6.5 ✅ | freshness (decision 9): the plugin listening to the OTGW firmware's and EMS-ESP's MQTT messages for the report times; ESPHome's re-report check and warning; translations, tests. Built more cautiously than planned: a source earns its automatic limit only once seen repeating an unchanged value (a report with nothing changed since, by its own change time) at least twice in the run — five times its median heartbeat gap, 10 to 30 min for the boiler's signals (not 5 min), 3 to 12 h for the weather; a change-only source never gets one. In the form, empty is automatic, 0 none. It applies to every entry, one made before the panels included, as it can only add a limit a source has shown it keeps to | C1–C5 (stale data, link lost) |
| I6.6a ✅ | control in the wizard (decision 11): the control steps follow the panels when the mode is full or on/off, with the same checks and blockers as in the options; monitoring only skips them. A new entry's first start never hands back a boiler it never held: an entry created less than 30 minutes ago, with neither store there and none of its entities registered, owes nothing | G1–G3, also on a fresh entry set up with control in the wizard; K1–K4 to confirm |
| I6.6b | the tidy-up: the design outdoor temperature in one place; the pressure limits in the boiler step at both levels and kept by "restore defaults"; the curve step naming the limit that applies (decision 10) | G1–G3 |
| I6.7 | the user guides EN and PL (the connection table, the ESPHome sample, EMS-ESP), `SCOPE.md` §4, §5 and §11, `CLAUDE.md`'s verified facts (EMS-ESP's "Force Heating Off"; how ESPHome and MQTT report), and I6 marked ✅ in `docs/plan-0.2.md` | none |

## Open after I6

- Merging the three highest-water-temperature fields into one (K4).
- Pellet and biomass as heat sources.
- Controlling two circuits at once (decision 10; 0.3).
- Room-temperature mode itself (0.3).
- The hint that a boiler may have no hot-water priority (decision 8): deferred until how boilers report
  heating and hot water at once is known.
