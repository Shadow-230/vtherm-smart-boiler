[Polska wersja](../../pl/development/plan.md)

# Development plan

Status: current.

Scope: `docs/en/specification/scope.md`. The author's own assessment of their installation: `home-assessment.md`
(private) — never a source of values for code, defaults, tests or docs.

## Approach — one core, three data sources

Pure logic in `core/` works on one time-series format (flame, flow, return, modulation, DHW,
weather, forecast snapshots, circuits, zones). The same code is fed by:

1. exported history — replay in tests,
2. the simulator — testing control laws,
3. live HA — through the integration layer.

Assessment, monitor and control are one code base, not three projects. The circuit model
(boiler → circuits → zones) is part of the core from 0.1; in 0.2 one curve serves the one written
circuit, and per-circuit curves come with CH2 (`docs/en/specification/scope.md` §5).

## Tracks

| Track | Content | Runs on |
|---|---|---|
| A. Core | burn-cycle detection, metrics (starts, burns, condensing, gas, degree-days), DHW detection, circuit model, parameter model with source and confidence, building estimate, control and learning laws | Python 3.14 |
| B. Data | common format, history importer, forecast snapshot store, assessment verdict from live and exported data | Python 3.14 |
| C. Simulator | boiler (minimum power, hysteresis, water volume), house as one mass, one unmixed loop (`sim/custom_components/boiler_sim/profiles.py`), zones; generic profiles per boiler class; mixed and separately controlled circuits with 0.3 | Python 3.14 |
| D. HA integration | own scaffold (`vtherm_hysteresis` as a reference), config flow with simple/advanced levels, entities, translations, `vtherm_api` registration, entity-based transport (read; write from 0.2), built-in OTGW support | test environment |
| E. Release | docs, license, HACS (the Marketplace from Home Assistant 2026.11), VT plugin list submission | — |

## Test environment

Three layers:

1. `core/` tests — plain pytest, no Home Assistant.
2. Integration tests — `pytest-homeassistant-custom-component`: Home Assistant runs inside the
   test process; no instance, no network.
3. Test HA — a dedicated Proxmox LXC running the official Home Assistant container at a pinned
   version, set up by the user (`devenv/`). The plugin, VT and SmartPI come from this project;
   boiler, rooms and weather come from our own physics simulator, a test-only component
   (`sim/custom_components/boiler_sim`), with real VT thermostats driving its zone valves. The
   test LXC reaches no device on the home network — the production HA, its MQTT broker and the
   real gateway among them: a firewall on the Proxmox host, out of reach from inside the LXC,
   blocks it (2026-10-08). Claude connects only to this instance (`CLAUDE.md`).

Control is tested only against the simulator: acceptance scenarios run first in-process, then in
the test HA. Details: `docs/en/development/plans/plan-0.2.md`, phase J. CI fetches VT 10.5.1 and SmartPI 0.4.0 from
their tags on GitHub's servers, so the real-VT tests run on every change; nothing is downloaded
locally (`docs/en/development/plans/plan-0.2.2.md`, decision 14).

## Releases

0.1 is published with 0.2 — the first release, its version decided at K4 and K5 (provisionally
0.2.3b1, `docs/en/development/plans/plan-0.2.2.md` decision 16), with control, tested as a whole; 0.2.1, 0.2.2 and
0.2.3 correct 0.2 after its reviews (`docs/en/development/plans/plan-0.2.1.md`, `docs/en/development/plans/plan-0.2.2.md`,
`docs/en/development/plans/plan-0.2.3.md`).
After that, release early and in small steps: every release collects data for the next one.

| Release | Content | Done when | Target |
|---|---|---|---|
| Step 0 | Python 3.14 and tools inside the project (`.tools/`, `.venv/`, `.tmp/`, `scripts/env.sh`), repo layout; local git (since 2026-09-24) | — | now |
| 0.1 Monitor (read-only) — done 2026-09-24, published with 0.2 | core: common format, circuit model, parameter model, building load estimate, burn-cycle and DHW detection, metrics; config flow (simple / advanced) with entity fields — the user picks which entity provides each signal, as in VT; read-only; capabilities follow from the filled fields; zone data through VT; entities: metrics, connection, per-zone hot water available and emitter power factor, critical zone, reference room (`docs/en/specification/scope.md` §5), verdict; signal check; foreign heat (the reference room, the per-zone entities and foreign heat removed in I8); alarms, early warning, report explaining changes; FC0; HA diagnostics download; EN + PL translations; minimal simulator, history importer, integration tests | all tests and `ruff` pass ✅ | September |
| 0.2 Control base — the first release (its version decided at K4 and K5; provisionally 0.2.3b1) | the 0.1 monitor plus control: opt-in, marked experimental, available from the first day — no monitoring period holds it (the user's decision, 2026-10-08), the verdict after 7 days of data; every option with a cautious default and its risks described; heating on and off as VT's central boiler decides, through a helper the plugin follows at once, nothing counted or timed holding heating against VT (I12); fixed curve (entered; one for the written circuit, per circuit with CH2); the lowest and highest water temperature; the recognition and grace periods (principle 12's stated exceptions); frost protection left to VT (I12); comfort correction within firm bounds (on by default in full control since G11); writes through every path: a user-picked entity, built-in OTGW through `opentherm_gw` or its firmware over MQTT, or a relay for an on/off boiler (class 3, 0.2.2); control only with a known hand-back; setpoint repeated every 30 s where the override expires (built-in OTGW, a picked entity declared expiring); one the device holds (declared held) sent on a change, after the device returns and every 5 min; nothing written to the boiler's persistent memory (a target declared persistent, or of unknown write type, keeps control off); no writes without fresh data; read-back of every write; the safe hand-back on every exit, retried until confirmed; clean reload; safe fallback setpoint on outdoor-sensor failure; DHW-enable bit kept as it was; write guards (a write-rate guard against a runaway loop; changes seen in the read-back judged by four classes — lost command, ignored from the start, clipped, another controller; hand-back never held back); alarm reactions as decision 7; the missing-data rule; in flow-setpoint mode control only with a confirmed-setpoint source; one circuit fed straight from the boiler, with circuits behind a fixed valve or run by other automation beside it (CH2 later); low-flow warning; summer and winter from VT; ramp of the water temperature; a "gives no heat" sensor for zone algorithms (I12); gateway topology (mode, and what is wired to the thermostat terminals) decides whether control is allowed and what hand-back leads to; the "own room controller" tick; control in flow-setpoint mode (the thermostat-like mode in 0.3); VT feature manager as the channel VT hands its thermostats through (I12); the comfort correction on by default in full control, within the user's limit, with a warning when the curve is too low for a room; the curve's room temperature Auto (the warmest zone's setpoint) or Manual; a long burn without warming told to the user (step G11, `docs/en/development/plans/plan-0.2-g11.md`); circuits as the boiler sees them — each with its zones, its highest water temperature and its own curve and correction, a circuit run by other automation asking for heat and setting a water floor, the boiler's water serving the most demanding circuit asking; the options as single forms with no sub-menus, each field shown only where it can work, texts short and plain (step I8, `docs/en/development/plans/plan-0.2-i8.md`, which also removes what belongs to rooms and zones: the reference room, window handling, foreign heat, the per-zone entities); the Boiler page in the sidebar and the same parts as cards — status, tiles, the hydraulic schematic with the circuits taking water, the curve with its preview and saving by an administrator, the last 24 h, the burner, use, analyses, the journal of decisions, status and alarms (step I10, `docs/en/development/plans/plan-0.2-i10.md`; the user's decisions of 2026-11-18); release files (`LICENSE`, README, `hacs.json`, HACS action, Hassfest); **test environment**: test HA in its LXC, own physics simulator, acceptance scenarios (first in-process, then in the test HA) | every acceptance scenario passes in the test HA; the author's installation monitors for 7 days, then runs control without errors; the user has reviewed 0.1 and 0.2; published | second half of November |
| 0.3 Anti-cycling and the thermostat-like mode | duty cycling — to be decided against principle 12 (`docs/en/development/plans/plan-0.2.2.md` decision 13), with the restart pause and the heat call's hysteresis (K4, 2026-11-17); the comfort correction in proportion to the shortfall, from at least two rooms at full demand, 1–2 K at most; the modulation cap, presented as a way to lengthen burns; a slower fall of the water near its floor, tested in the simulator; forecast planning (FC2) parked — no evidence found; the thermostat-like mode — the boiler gets the temperature and setpoint, or the difference, of the zone asking for heat that lacks most, and sets its own water (ID 24 / 16 or picked entities; `docs/en/development/plans/plan-0.2-i8.md` G) — off by default, only for a boiler shown to react to IDs 16/24; the wall thermostat as a fallback for Home Assistant failing — one way, VT to the thermostat, off by default (at the earliest; `docs/en/development/plans/plan-0.2-i8.md` I1); the "apply" mode of the lowest water temperature; radiators and underfloor behind a mixing valve (one written circuit plus passive fixed circuits) | fewer starts, same comfort | December–January |
| 0.4 Learning and tuning | water-side learning — the curve's shift first, its slope only once outdoor temperatures vary; advisor suggestions, "suggest" by default, the measured effect of each change shown; tuning band (High only by explicit choice); seasonal tune-up stopping at the cycling edge, heat-up time after a setback as a comfort check; the heating threshold by regression — each per circuit, also the water a circuit run by other automation needs where no value is given | lower return, less gas per degree-day | January–February |
| 0.5 Forecast | anticipation for slow emitters (FC3) kept simple: a bounded look-ahead outdoor temperature for slow circuits only, the sun only lowering the water; the lead time from the circuit's response, the forecasts' records giving how far they can be trusted; a building time constant from heating-off periods (K4, 2026-11-17) | better comfort on weather changes without extra gas | late winter or next season |
| Later | DHW charging; the Marketplace's default list (`hacs/default`) and VT plugin list submission; built-in support for more devices; the gas estimated from the boiler's power where no gas rates are given; relay commands beyond a switch and a boiler thermostat entity (VT's free-form actions), if asked | — | spring 2027 onward |

Targets are aims, not commitments. The simulator stays minimal: enough to accept 0.2 before it
reaches a real boiler.
No release reaches a real boiler before it passes in the test environment. Automated tests run
in-process; Claude connects only to the test HA.

## Before 0.2

Checks before control code: `docs/en/development/plans/plan-0.2.md`, phase F (done 2026-09-24; answers in `docs/en/specification/scope.md` §11).

## Before the first release — open for the review (K4)

Added on 2026-11-16, after a check against the newest Home Assistant and VT and a review of
published research (the notes `research/2026-11-16-*`, not in the repository). Each point waits
for the user's decision at K4.

**How the plugin is published.** From Home Assistant 2026.11, HACS is part of Home Assistant,
named the Marketplace. A repository that is not on its list can still be added from its link.

- The code goes to `main` (from `qas`) before the release: today `main` holds only the
  documents, and the Marketplace may install from it.
- The first release is either a GitHub pre-release or a regular release that its notes call a
  beta. A pre-release is hidden until the user switches pre-releases on for this repository, and
  while there is no regular release, the Marketplace installs the default branch instead.
- After installing, Home Assistant is restarted or VT reloaded: VT finds the plugin only when its
  thermostats start.
- Once the kind of release is chosen, the user guide (§2) and the README describe both ways to
  install: HACS up to Home Assistant 2026.10, the Marketplace from 2026.11.
- The Marketplace's default list (`hacs/default`) needs a release, passing checks and an
  open-source licence (Apache-2.0 passes); its queue takes months. VT's list of plugins is a
  form on VT's website.

**Versions.** The tests move to the newest versions; the plugin's code must work with them (the
user's decision, 2026-11-16). VT 10.6.5 and `vtherm_api` 0.9.0 came with I12.6; SmartPI left the
tests with I12.9, as the plugin reads nothing of it. Home Assistant 2026.11 is a step of its own,
after the corrections that follow I12 (the user, 2026-11-26). The oldest Home Assistant supported
follows the newest VT: 2026.10.4, as VT 10.6.5 needs (the user, 2026-11-17; `hacs.json`, CI's two
harness pins).

**Home Assistant 2027.11** removes five old interfaces. The plugin used one — the old way an
entity's ID is renamed — and is ready for the new one (#147, 2026-11-16). VT 10.6.5 still uses the old
temperature properties of thermostats, which stop working in 2027.11; the plugin's zones depend
on VT changing them. Watched at each early-warning run; not raised with VT (the user's decision,
2026-11-16).

**From the research.** Proposals; each changes a default or a rule. **Decided by the user on
2026-11-17** (`research/2026-11-17-k4-literature-proposals.md`): 1 to 6 and the verdict's text
built — 1 in #149, 2 in #150 (the warning on VT's cycle; J4's criterion: at most ×1.10 the
boiler's own starts, or at most 6 an hour with a median burn of 10 min), 3 in #151, 4 in #152,
5 and 6 with the oversizing text in #153 (gas per degree-day was already over 7 days); 7 to 10
in their releases (below, "Releases" and "Before 0.3"); the restart pause of 7 is decided
before 0.3. Kept as built where the research agrees, and the provisional values it says
nothing on (ignition and flue-gas limits, frost, the ramp, the timings).

1. The comfort correction off by default, at least where the zones run VT's TPI, and offered by
   the advisor instead. In the research it is a shift of the curve from one reference room
   without a radiator valve, in proportion to the room's shortfall — not a correction that
   climbs to its limit over rooms VT throttles. J4's ×1.30 to ×4.42 starts (F8) agree. This
   reverses the decision of 2026-10-10 (G11).
2. Advise a TPI cycle of at least 10 minutes for zones that call a boiler (VT's default is 5).
   The extra starts at −5 °C (F9) come from the gaps between VT's pulses, at a load where a
   modulating boiler would seldom stop. UK practice for gas boilers is 6 cycles an hour.
3. Frequent starts in two steps: information above about 6 an hour for some hours, the alarm
   above 12 (today 12 only).
4. The building's heat loss counted as known only after about 3 weeks of heating, and shown with
   a range.
5. Gas per degree-day over 7 days; the change against the day before with a band for noise.
6. The verdict's text names an oversized boiler as the main cause of short burns.
7. For 0.3: a short pause before the burner starts again (3 to 5 minutes), cut short by a large
   shortfall or hot water, and never delaying a stop. It goes against
   principle 12 (heating follows VT at once), so it is the user's to decide. With it, the
   correction in proportion to the shortfall: only from rooms at full demand for whole cycles,
   past a dead band, from at least two rooms, 1 to 2 K at most.
8. For 0.4: learn the curve's shift first and its slope only once outdoor temperatures vary;
   "suggest" as the default; stop lowering the water when starts rise or burns get shorter; show
   the measured effect of each change.
9. For 0.5: anticipation kept simple — a limited look-ahead outdoor temperature for slow circuits
   only; the sun only lowers the water, and only a little. The research finds little gain from
   forecasts where rooms already have their own control.
10. Later: the mean return temperature, or the share below about 45 °C, beside the share below
    55 °C.

The research agrees with what is built: the curve's shape, the circuit's highest water
temperature, the most demanding circuit setting the water, short burns counted under
10 minutes, hot water told from the boiler's own signals. It has nothing on: forecast-based
anti-cycling (FC2), ignition and flue-gas limits, the tuning band's 3 / 8 / 15 %, and whether real
boilers use OpenTherm IDs 16 and 24 (the thermostat-like mode).

## Before 0.3

- Decision gate after 2–4 weeks of heating data from 0.2: full scope, slimmed scope, or
  stop after 0.2.
- At that gate (K4, 2026-11-17): a restart pause of 3–5 min after a heating stop — cut short by
  a large shortfall or hot water, never delaying a stop (Siemens LMS14,
  Vaillant's anti-cycle time; about 0.04 K at −5 °C) — and hysteresis on the heat call
  (ASHRAE Guideline 36). Both go against principle 12 (heating follows VT at once): the user's
  decision.
- **Device templates** (the user's decisions of 2026-11-22): what differs between boiler
  connections moves into one YAML file per device, in three layers: protocol, behaviour and the
  routes to the device. After the first release, before the work on 0.3:
  [`plan-device-templates.md`](plans/plan-device-templates.md); the fields and today's cards are in
  [`device-connections.md`](../specification/device-connections.md).
- **Ideas from `vtherm_api`** (read on 2026-11-22), none needed for the beta:
  - *The zones' pulses known ahead.* VT tells a feature manager when each zone's cycle starts and
    how long it heats (`async_on_underlying_power`, since `vtherm_api` 0.9.0). The plugin could tell
    a short gap between two zones from a real end of demand, the gap that stops the burner with
    VT's 5-minute cycle. This goes against principle 12, so it is the user's decision, and its gain
    is measured in the simulator first.
  - *A warning before VT's safety mode.* VT's freshness clocks (`vtherm_api` 0.12.0, not released)
    would let the plugin say a sensor has been quiet for most of VT's safety delay.
  - *One signal for every zone algorithm: "this zone gets heat now".* SmartPI's author suggested
    an interface at this level on 2026-11-22. It would be a small optional contract in
    `vtherm_api`, talked over with VT's and SmartPI's authors first, with the working plugin as the
    evidence, and no pull request before they agree.

## Release plans

- 0.1 — `docs/en/development/plans/plan-0.1.md`
- 0.2 — `docs/en/development/plans/plan-0.2.md`
- 0.2.1 — `docs/en/development/plans/plan-0.2.1.md`: the corrections after the review of 2026-09-24 and the user's
  decisions of 2026-09-25, before the test HA
- 0.2.2 — `docs/en/development/plans/plan-0.2.2.md` (details: `docs/en/development/plans/plan-0.2.2-details.md`): the corrections after the
  review of 2026-09-26 and the user's decisions of 2026-09-26/27; the first version to be
  published (provisional)
- 0.2, step I6 — `docs/en/development/plans/plan-0.2-i6.md`: the setup opens with how the boiler is connected, the
  control mode, the heat source and the boiler type (the user's decisions of 2026-10-08 and
  2026-10-09)
- 0.2, step G11 — `docs/en/development/plans/plan-0.2-g11.md`: the comfort correction on by default, the curve's
  room temperature Auto or Manual, the long-run rule and the window guard (the user's decisions
  of 2026-10-10)
- 0.2, step I7 — `docs/en/development/plans/plan-0.2-i7.md`: the setup and the options move through a menu of
  sections, saved once at the end, as in Versatile Thermostat (the user's decisions of
  2026-10-10)
- 0.2, step I8 — `docs/en/development/plans/plan-0.2-i8.md`: a boiler plugin, one form per menu item — what belongs
  to rooms and zones goes, circuits and the control chain become menu items, texts short and
  plain (the user's decisions of 2026-10-10)
- 0.2, step I10 — `docs/en/development/plans/plan-0.2-i10.md`: the Boiler page in the sidebar and
  the same parts as cards, changing the curve from the page with the settings' checks (the user's
  decisions of 2026-11-18)
- 0.2, step I11 — `docs/en/development/plans/plan-0.2-i11.md`: control switched on and off only
  by an administrator in the plugin's settings, and by automations; the Control switch becomes a
  state shown (the user's decisions of 2026-11-22, after J4's F19)
- 0.2, step I12 — `docs/en/development/plans/plan-0.2-i12.md`: VT integration only through
  `vtherm_api`; VT's central boiler decides whether to heat, through a helper the plugin follows;
  no learning pauses, water interface or frost protection of the plugin's; the rooms from VT; VT
  10.6.5 the oldest supported (the user's decisions of 2026-11-24 and 2026-11-25)
- 0.2, step I13 — `docs/en/development/plans/plan-0.2-i13.md`: the corrections from the
  literature — "Gives no heat" only while a room is withheld heat, the boiler link without
  chatter, the comfort correction's pace, the building's range and the verdict, the monitor's
  figures, a restart pause (off by default), the modulation cap (opt-in), a longer outdoor mean
  for heavy houses, the documents (the user's decision of 2026-11-26); the sources in
  `literature/`
- Device templates — `docs/en/development/plans/plan-device-templates.md`: one parameter file per
  boiler device, after the first release (the user's decisions of 2026-11-22)
