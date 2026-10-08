# Development plan

Scope: `SCOPE.md`. The author's own assessment of their installation: `home-assessment.md`
(private) — never a source of values for code, defaults, tests or docs.

## Approach — one core, three data sources

Pure logic in `core/` works on one time-series format (flame, flow, return, modulation, DHW,
weather, forecast snapshots, circuits, zones). The same code is fed by:

1. exported history — replay in tests,
2. the simulator — testing control laws,
3. live HA — through the integration layer.

Assessment, monitor and control are one code base, not three projects. The circuit model
(boiler → circuits → zones) is part of the core from 0.1; in 0.2 one curve serves the one written
circuit, and per-circuit curves come with CH2 (`SCOPE.md` §5).

## Tracks

| Track | Content | Runs on |
|---|---|---|
| A. Core | burn-cycle detection, metrics (starts, burns, condensing, gas, degree-days), DHW detection, circuit model, parameter model with source and confidence, building estimate, control and learning laws | Python 3.14 |
| B. Data | common format, history importer, forecast snapshot store, assessment verdict from live and exported data | Python 3.14 |
| C. Simulator | boiler (minimum power, hysteresis, water volume), house as one mass, one unmixed loop (`sim/custom_components/boiler_sim/profiles.py`), zones; generic profiles per boiler class; mixed and separately controlled circuits with 0.3 | Python 3.14 |
| D. HA integration | own scaffold (`vtherm_hysteresis` as a reference), config flow with simple/advanced levels, entities, translations, `vtherm_api` registration, entity-based transport (read; write from 0.2), built-in OTGW support, learning pauses | test environment |
| E. Release | docs, license, HACS, VT plugin list submission | — |

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
the test HA. Details: `docs/plan-0.2.md`, phase J. CI fetches VT 10.4.0 and SmartPI 0.4.0 from
their tags on GitHub's servers, so the real-VT tests run on every change; nothing is downloaded
locally (`docs/plan-0.2.2.md`, decision 14).

## Releases

0.1 is published with 0.2 — the first release, its version decided at K4 and K5 (provisionally
0.2.3b1, `docs/plan-0.2.2.md` decision 16), with control, tested as a whole; 0.2.1, 0.2.2 and
0.2.3 correct 0.2 after its reviews (`docs/plan-0.2.1.md`, `docs/plan-0.2.2.md`,
`docs/plan-0.2.3.md`).
After that, release early and in small steps: every release collects data for the next one.

| Release | Content | Done when | Target |
|---|---|---|---|
| Step 0 | Python 3.14 and tools inside the project (`.tools/`, `.venv/`, `.tmp/`, `scripts/env.sh`), repo layout; local git (since 2026-09-24) | — | now |
| 0.1 Monitor (read-only) — done 2026-09-24, published with 0.2 | core: common format, circuit model, parameter model, building load estimate, burn-cycle and DHW detection, metrics; config flow (simple / advanced) with entity fields — the user picks which entity provides each signal, as in VT; read-only; capabilities follow from the filled fields; zone data through VT; entities: metrics, connection, per-zone hot water available and emitter power factor, critical zone, reference room (`SCOPE.md` §5), verdict; signal check; foreign heat; alarms, early warning, report explaining changes; FC0; HA diagnostics download; EN + PL translations; minimal simulator, history importer, integration tests | all tests and `ruff` pass ✅ | September |
| 0.2 Control base — the first release (its version decided at K4 and K5; provisionally 0.2.3b1) | the 0.1 monitor plus control: opt-in, marked experimental, available from the first day — no monitoring period holds it (the user's decision, 2026-10-08), the verdict after 7 days of data; every option with a cautious default and its risks described; replaces VT's central boiler: heating on and off follow VT's zones at once, VT's central modes through the zones' demand, nothing counted or timed holding heating against VT; boiler demand from zones calling, total power or valve opening; fixed curve (entered; one for the written circuit, per circuit with CH2); the lowest and highest water temperature, weather ceiling, frost protection (one of principle 12's stated exceptions, with the recognition and grace periods and VT's activation delay); comfort correction within firm bounds; writes through every path: a user-picked entity, built-in OTGW through `opentherm_gw` or its firmware over MQTT, or a relay for an on/off boiler (class 3, 0.2.2); control only with a known hand-back; setpoint repeated every 30 s where the override expires (built-in OTGW, a picked entity declared expiring); one the device holds (declared held) sent on a change, after the device returns and every 5 min; nothing written to the boiler's persistent memory (a target declared persistent, or of unknown write type, keeps control off); no writes without fresh data; read-back of every write; the safe hand-back on every exit, retried until confirmed; clean reload; safe fallback setpoint on outdoor-sensor failure; DHW-enable bit kept as it was; write guards (a write-rate guard against a runaway loop; changes seen in the read-back judged by four classes — lost command, ignored from the start, clipped, another controller; hand-back never held back); alarm reactions as decision 7; the missing-data rule; in flow-setpoint mode control only with a confirmed-setpoint source; one written circuit (CH2 later); low-flow warning; summer and winter from VT; ramp of the water temperature; learning pauses (`SCOPE.md` §5); gateway topology (mode, and what is wired to the thermostat terminals) decides whether control is allowed and what hand-back leads to; the "own room controller" tick; control in flow-setpoint mode (room values in 0.3); VT feature manager with the two zone values; release files (`LICENSE`, `NOTICE`, README, `hacs.json`, HACS action, Hassfest); **test environment**: test HA in its LXC, own physics simulator, acceptance scenarios (first in-process, then in the test HA) | every acceptance scenario passes in the test HA; the author's installation monitors for 7 days, then runs control without errors; the user has reviewed 0.1 and 0.2; published | second half of November |
| 0.3 Anti-cycling and room values | duty cycling and summer/winter from forecast (FC1) — both to be decided against principle 12 (`docs/plan-0.2.2.md` decision 13); modulation cap, forecast planning (FC2); room-value mode (ID 24 / 16 or picked entities, moved from 0.2); the wall thermostat linked to a VT zone, VT leading and off by default (at the earliest); the "apply" mode of the lowest water temperature; radiators and underfloor behind a mixing valve (one written circuit plus passive fixed circuits) | fewer starts, same comfort | December–January |
| 0.4 Learning and tuning | water-side learning, advisor suggestions, tuning band, seasonal tune-up | lower return, less gas per degree-day | January–February |
| 0.5 Forecast | anticipation for slow emitters (FC3), lead time from recorded forecasts | better comfort on weather changes without extra gas | late winter or next season |
| Later | DHW charging; HACS default list and VT plugin list submission; proposal to SmartPI and adaptive TPI authors; built-in support for more devices; relay commands beyond a switch and a boiler thermostat entity (VT's free-form actions), if asked | — | spring 2027 onward |

Targets are aims, not commitments. The simulator stays minimal: enough to accept 0.2 before it
reaches a real boiler.
No release reaches a real boiler before it passes in the test environment. Automated tests run
in-process; Claude connects only to the test HA.

## Before 0.2

Checks before control code: `docs/plan-0.2.md`, phase F (done 2026-09-24; answers in `SCOPE.md` §11).

## Before 0.3

- Decision gate after 2–4 weeks of heating data from 0.2: full scope, slimmed scope, or
  stop after 0.2.

## Release plans

- 0.1 — `docs/plan-0.1.md`
- 0.2 — `docs/plan-0.2.md`
- 0.2.1 — `docs/plan-0.2.1.md`: the corrections after the review of 2026-09-24 and the user's
  decisions of 2026-09-25, before the test HA
- 0.2.2 — `docs/plan-0.2.2.md` (details: `docs/plan-0.2.2-details.md`): the corrections after the
  review of 2026-09-26 and the user's decisions of 2026-09-26/27; the first version to be
  published (provisional)
