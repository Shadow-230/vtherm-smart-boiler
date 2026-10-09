# Plan 0.2, step I6 — The setup starts with how the boiler is connected

Goal: the setup wizard and the options open with the few choices that shape everything after
them — how the boiler is connected, the control mode, the heat source and the boiler type — and the
later steps show only what fits those answers. Step I6 of `docs/plan-0.2.md`, widened by the user's
decisions of 2026-10-08 and 2026-10-09 below. Control stays off by default: no answer switches
anything on.
Scope: `SCOPE.md`; overview: `PLAN.md`; the release plan: `docs/plan-0.2.md`.

Status on 2026-10-09: planned. The corrections from the test report that the user put first (F1,
F2, F5) are done as pull requests #32, #34 and #35. I6.1 starts once the user has approved this
plan; two of its questions are open (decisions 9 and 10).

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
   2026-10-09). 🔒 Open: how forced updates are had where Home Assistant writes only changes (see
   I6.5). The defaults known safe today: 10 min for the boiler signals on the OTGW integration (it
   rewrites every entity on each report), 3 h for the weather entity.
10. **The highest water temperature:** its three fields stay (the boiler's, the circuit's, control's);
    the curve step shows which one applies and where it comes from; merging them waits for K4. An
    installation may have the boiler's control and a separate controller for an underfloor mixer:
    the stored layout of the new answers allows a second control configuration, per circuit. 🔒 Open:
    whether controlling two circuits at once stays in 0.3, as `SCOPE.md` §5 has it.
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
- To keep in mind at I6.6: `has_control_section` assumes control is set up only in the options of an
  entry that has run, so a control section without a stored state is taken as a held boiler. An
  entry made by the wizard with control set up has never held the boiler: its first start must not
  hand back a boiler it never took.

## Steps

| Step | Work | J4 impact |
|---|---|---|
| I6.0 🔒 | the user approves this plan, and answers decisions 9 and 10 | — |
| I6.1 | the first panels: the connection (decision 1), the control mode (6), the heat source (7), the boiler type with condensing and hot-water priority (8), then the name and level; the answers stored as their own keys; the boiler class from the connection, no longer asked; "room temperature only" gives the monitor with its reason; the options menu opens with the same panels; an entry without the answers as today (12); translations EN and PL; tests | the setup and the options' first steps: G1–G3 |
| I6.2 | what the connection sets (decision 2) in the control steps: the paths offered, the write types, the hand-back, the topology; the ESPHome tick and its blocker (3); EMS-ESP's "off" at 0 and its answer-O latch (4, `core/` first); the blockers "connection does not fit the write path" and "topology does not fit the connection"; the entities suggested; translations, tests | every control scenario on the OTGW integration still passes unchanged; G1–G3 again |
| I6.3 | the heat source (decision 7): fields, signals and alarms shown or hidden; the electric boiler's "heating on"; the defaults for condensing by source | the monitor's scenarios with the sim's gas boiler: none expected; F1, F2 |
| I6.4 | the hot-water priority (decision 8): the learning pause and heat availability follow it (`core/` first); the optional hint | D8 (the SmartPI pause on a draw) |
| I6.5 🔒 | freshness: the defaults and forced updates for every connection (decision 9), as the user answers | C1–C5 (stale data, link lost) |
| I6.6 | control in the wizard (decision 11), with a new entry's first start never handing back a boiler it never held; the tidy-up: the design outdoor temperature in one place; the pressure limits in the boiler step at both levels and kept by "restore defaults"; the curve step naming the limit that applies (decision 10) | the setup with control; A1, B1 |
| I6.7 | the user guides EN and PL (the connection table, the ESPHome sample, EMS-ESP), `SCOPE.md` §4, §5 and §11, `CLAUDE.md`'s verified facts (EMS-ESP's "Force Heating Off"; how ESPHome and MQTT report), and I6 marked ✅ in `docs/plan-0.2.md` | none |

## Open after I6

- Merging the three highest-water-temperature fields into one (K4).
- Pellet and biomass as heat sources.
- Controlling two circuits at once (decision 10; 0.3 in `SCOPE.md` §5 unless the user decides
  otherwise).
- Room-temperature mode itself (0.3).
