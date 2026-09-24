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
(boiler → circuits → zones, curve per circuit) is part of the core from 0.1.

## Tracks

| Track | Content | Runs on |
|---|---|---|
| A. Core | burn-cycle detection, metrics (starts, burns, condensing, gas, degree-days), DHW detection, circuit model, parameter model with source and confidence, building estimate, control and learning laws | Python 3.14 |
| B. Data | common format, history importer, forecast snapshot store, assessment verdict from live and exported data | Python 3.14 |
| C. Simulator | boiler (minimum power, hysteresis, water volume), house as one mass, circuits (direct, mixed, separately controlled), zones; generic profiles per boiler class and circuit type | Python 3.14 |
| D. HA integration | own scaffold (`vtherm_hysteresis` as a reference), config flow with simple/advanced levels, entities, translations, `vtherm_api` registration, entity-based transport (read; write from 0.2), built-in OTGW support, learning pauses | test environment |
| E. Release | docs, license, HACS, VT plugin list submission | — |

## Test environment

Three layers:

1. `core/` tests — plain pytest, no Home Assistant.
2. Integration tests — `pytest-homeassistant-custom-component`: Home Assistant runs inside the
   test process; no instance, no network.
3. Test HA — a dedicated Proxmox LXC running the official Home Assistant container at a pinned
   version, set up by the user. The plugin, VT and SmartPI come from this project; fake boiler
   from core helpers (`input_number`, `input_boolean`, `template`), rooms from
   `generic_thermostat`, weather from a template weather entity with forecasts; a physics
   simulator of our own arrives with 0.2. The test LXC has no access to the production HA, its
   MQTT broker or the real gateway. Claude connects only to this instance (`CLAUDE.md`).

Control is tested only against the simulator. Details: `docs/plan-0.2.md`, phase J.

## Releases

0.1 and 0.2 are built in one go, in order; 0.2 is the first release and is tested as a whole.
After that, release early and in small steps: every release collects data for the next one.

| Release | Content | Done when | Target |
|---|---|---|---|
| Step 0 | Python 3.14 and tools inside the project (`.tools/`, `.venv/`, `.tmp/`, `scripts/env.sh`), repo layout; local git (since 2026-09-24) | — | now |
| 0.1 Monitor (read-only) — internal step, not released | core: common format, circuit model, parameter model, building load estimate, burn-cycle and DHW detection, metrics; config flow (simple / advanced) with entity fields — the user picks which entity provides each signal, as in VT; read-only; capabilities follow from the filled fields; zone data through VT; entities: metrics, connection, per-zone hot water available and emitter power factor, critical zone, reference room (`SCOPE.md` §5), verdict; signal check; foreign heat; alarms, early warning, report explaining changes; FC0; HA diagnostics download; EN + PL translations; minimal simulator, history importer, integration tests | all tests and `ruff` pass; work continues with 0.2 | October |
| 0.2 Control base — first release | the 0.1 monitor plus control: opt-in, marked experimental, available after the monitoring period (default 7 days); every option with a cautious default and its risks described; replaces VT's central boiler, obeys `central_mode`; boiler demand from device count, total power or valve opening; fixed curve per circuit (entered or taken from the boiler); hard limits, weather ceiling, frost protection; writes to a user-picked entity or through built-in OTGW support; control only with a known hand-back; setpoint repeated every 30 s where the override expires (built-in OTGW, a picked entity declared expiring); a picked entity declared persistent, or of unknown write type, written only on a minimum change and within a daily cap; no writes without fresh data; read-back of every write; hand-back on every exit; clean reload; safe fallback setpoint on sensor failure, or room values cleared in room-value mode; DHW-enable bit kept as it was; basic anti-cycling (minimum burn, minimum pause, starts per hour); write guards (rate limits, minimum on and off times, plausible room values, minimum change and daily cap for persistent writes, at most one rewrite of a value changed from outside; hand-back never held back); alarm reactions (info, stop, hand back); in flow-setpoint mode control only with a confirmed-setpoint source; one written circuit (CH2 later); low-flow warning; summer/winter threshold; ramp of the water temperature; learning pauses (`SCOPE.md` §5); gateway topology (mode and thermostat) decides the allowed control modes and what hand-back leads to; control mode: flow setpoint, or room values (ID 24 / 16 or picked entities) where the boiler's own curve decides the water temperature; VT feature manager with the two zone values; release files (`LICENSE`, `NOTICE`, README, `hacs.json`, HACS action, Hassfest); **test environment**: test HA in its LXC, own physics simulator, acceptance scenarios | every acceptance scenario passes in the test HA; the author's installation monitors for 7 days, then runs control without errors; published | second half of November |
| 0.3 Anti-cycling | duty cycling, modulation cap, summer/winter from forecast (FC1), forecast planning (FC2) | fewer starts, same comfort | December–January |
| 0.4 Learning and tuning | water-side learning, advisor suggestions, tuning band, seasonal tune-up | lower return, less gas per degree-day | January–February |
| 0.5 Forecast | anticipation for slow emitters (FC3), lead time from recorded forecasts | better comfort on weather changes without extra gas | late winter or next season |
| Later | DHW charging; HACS default list and VT plugin list submission; proposal to SmartPI and adaptive TPI authors; built-in support for more devices; on/off-only boilers (relay) | — | spring 2027 onward |

Targets are aims, not commitments. The simulator stays minimal: enough to accept 0.2 before it
reaches a real boiler.
No release reaches a real boiler before it passes in the test environment. Automated tests run
in-process; Claude connects only to the test HA.

## Before 0.2

Checks before control code: `docs/plan-0.2.md`, phase F.

## Before 0.3

- Decision gate after 2–4 weeks of heating data from 0.2: full scope, slimmed scope, or
  stop after 0.2.

## Release plans

- 0.1 — `docs/plan-0.1.md`
- 0.2 — `docs/plan-0.2.md`
