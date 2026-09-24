# Plan 0.1 — Monitor (read-only)

Goal: the read-only monitor that any user configures by picking entities — the first part of
0.2, not released on its own. Testing in the test HA and on the author's installation happens
with 0.2 (`docs/plan-0.2.md`). Scope: `SCOPE.md`; overview: `PLAN.md`.

## Starting point (2026-09-24)

- The development machine is a Debian 12 LXC on Proxmox with system Python 3.11 only; no `uv`,
  Docker or Podman. Claude does not use `sudo`.
- No code; local git since 2026-09-24. Documents: `CLAUDE.md`, `SCOPE.md`, `PLAN.md`, this plan,
  `docs/plan-0.2.md`, `research/`.
- Decided on 2026-09-24: domain `vtherm_smart_boiler`; consent for every step of this plan
  (after A1–A5 and A7, the user accepted all steps needed to build 0.1); Claude's own code, test
  and tool files may be changed without asking; 0.1 and 0.2 are built in one go, in order, and
  0.2 is the first release.

## Rules that shape this step

- Universal: every input is a config-flow entity field; no installation-specific data anywhere.
- Read-only by construction: the transport interface has no write method in 0.1; a test proves
  the plugin calls no service except `weather.get_forecasts`.
- Everything inside the project: `.tools/`, `.venv/`, `.tmp/`; commands run as
  `scripts/env.sh <command>`; no `sudo`.
- Claude connects only to the test HA.
- Local git: a commit after every completed step; no remote without the user's consent.
- 🔒 marks steps that need the user's consent or action; ✓ marks consent already given; ✅
  marks a finished step.
- Working mode: phases run in order without waiting; each phase ends with all tests and `ruff`
  passing and a short summary for the user; work stops at every 🔒 step and at the review stop
  after phase B.

## Layout

    custom_components/vtherm_smart_boiler/   the plugin
      core/            pure logic, no Home Assistant imports
      transport/       boiler signals from mapped entities, read-only
      vtherm_link.py   the only module reading VT zones
      __init__.py manifest.json config_flow.py coordinator.py
      sensor.py binary_sensor.py diagnostics.py translations/{en,pl}.json
    sim/               minimal simulator, not shipped
    tools/             history importer, not shipped
    tests/core/ tests/integration/
    devenv/            test HA: compose file, configuration, setup guide;
                       local.env and ssh/ git-ignored
    vendor/            VT and SmartPI at pinned versions, git-ignored
    data/              user exports and entity mappings, git-ignored
    scripts/env.sh scripts/deploy_test.sh
    docs/

## Phase A — prerequisites

Run order: A4, A1, A2, A5, A3, A6, A7 — `scripts/env.sh` comes first, so no tool writes outside
the project.

| Step | Work | Done when |
|---|---|---|
| A4 ✓ ✅ | `scripts/env.sh <command>`: sets `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `UV_PYTHON_BIN_DIR=.tools/bin`, `PIP_CACHE_DIR`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME` (all under `.tools/`), `TMPDIR=.tmp`, `PATH`, then runs the command | written before any install |
| A1 ✓ ✅ | through `scripts/env.sh`: `.tools/bootstrap` venv from system Python, `uv` installed into it. Done without a venv: the system Python has no `ensurepip` or `pip`, so the `uv` wheel from PyPI (0.12.18) was unpacked into `.tools/bootstrap/bin/` after its SHA-256 matched PyPI | `uv --version` |
| A2 ✓ ✅ | through `scripts/env.sh`: Python 3.14 into `.tools/python/` without shims outside the project (`--no-bin` or `UV_PYTHON_BIN_DIR` — check against the installed uv version first). Done: Python 3.14.7 with `--no-bin`, `UV_PYTHON_BIN_DIR` kept as a safety net | Python ≥ 3.14.2; `uv cache dir`, `uv python dir` and `uv python dir --bin` all point inside the project |
| A5 ✓ ✅ | VT 10.4.0 and SmartPI 0.4.0 sources from their release tags in `vendor/` (git-ignored); newer VT features (e.g. `get_feature_manager` from 10.5) are tested with fakes. Done: tag archives streamed from GitHub (no archive kept), commits checked (VT `78090166e88a`, SmartPI `51db763bb0db`), images left out; `vendor/custom_components/` links the two integrations, so only `vendor/` joins `sys.path` | loadable in tests and the test HA |
| A3 ✓ ✅ | `.venv` with `pytest-homeassistant-custom-component==0.13.366` (pins Home Assistant 2026.9.3), `vtherm-api==0.5.0`, `ruff`, plus the requirements in the VT and SmartPI manifests from `vendor/` (e.g. `numpy`, `scipy` for VT), at the versions those manifests allow, constrained by Home Assistant's `package_constraints.txt` so the versions match a real Home Assistant (to verify: the file ships in the `homeassistant` package); pins change only deliberately. Done: the file ships in the package; `numpy` 2.3.2 (as pinned by Home Assistant), `scipy` 1.18.1, `ruff` 0.16.8; pins recorded in `pyproject.toml` (`test` group) | imports succeed; VT loads in a test |
| A6 🔒 ✅ | system packages for the test dependencies, only if one fails to build — installed by the user. Not needed: every package installed from a wheel | — |
| A7 ✓ ✅ | layout, `pyproject.toml` (pytest `--basetemp=.tmp/pytest`, ruff `py314`). Done: `tests/conftest.py` imports `custom_components` as a namespace package before Home Assistant's loader would take the one in its test configuration directory | `pytest -q` and `ruff check .` pass on an empty suite |

## Phase B — core (test first)

`core/` stays free of Home Assistant: a test parses every module in `core/` and fails on any
`homeassistant` import; the integration's `__init__.py` imports Home Assistant inside functions,
so `core` can be imported on its own; `core` tests import it directly.

| Step | Work |
|---|---|
| B1 ✅ | data format: boiler state (flame, flow, return, modulation, setpoint, DHW, pressure, flue gas), zone state (on_percent, valve, temperature, target, active, power), weather |
| B2 ✅ | installation model (boiler → circuits of four control types → zones); parameters with source and confidence; declared-versus-measured findings |
| B3 ✅ | building load estimate: coarse answers (insulation, thermal mass) or an entered design heat load or loss coefficient; refined from measured data |
| B4 ✅ | burn-cycle detection; DHW from its signal, inference from a shared return with a confidence |
| B5 ✅ | metrics: starts per hour, burn times, condensing share (return threshold as a parameter, default 55 °C), degree-days, gas per degree-day from a mapped gas meter, else estimated from modulation when consumption data exist; binned by outdoor temperature |
| B6 ✅ | emitter power factor (EN 442 exponent by emitter type — defaults: radiator 1.3, underfloor 1.1, convector 1.4, advanced override), heating zones only, last value held, unavailable with a reason |
| B7 ✅ | hot water available per zone: no while DHW is active, while the flow has fallen near room temperature, or while the flow signal is stale |
| B8 ✅ | reference room: strategies, selection hysteresis, explicit "no active zone" and "no valid measurement" |
| B9 | critical zone per circuit |
| B10 | signal check: which optional signals are present and fresh; outdoor sensor plausibility against the weather entity |
| B11 | foreign heat from user-mapped switches or sensors, per zone |
| B12 | verdict — worth it / not worth it / not enough data (minimum 7 days), always with reasons; compares the building load with the boiler's minimum power |
| B13 | alarms and early warning (flue gas, ignitions, pressure, hysteresis drift), information only |
| B14 | report explaining changes (weather, DHW, settings) |
| B15 | forecast snapshot model (FC0) |

Done when: every law has unit tests, including missing and stale data.

**Review stop 🔒:** the user reviews the core laws and the model before phase C starts.
Covered by the consent to every 0.1 step (2026-09-24): work continues without waiting, and the
core is reviewed together with the rest of 0.1.

## Phase C — simulator and test harness

| Step | Work |
|---|---|
| C1 | `sim/`: boiler (minimum and maximum power, hysteresis, water volume), house as one mass, one circuit, zones; generic profiles per boiler class and circuit type |
| C2 | `tools/`: importer for a copy of an HA database (read-only) with a user-written entity mapping kept in `data/` |
| C3 | integration-test harness: `enable_custom_integrations`, fake boiler entities, VT zones (from `vendor/` or fakes), time control |

Done when: simulator output and an imported history pass through the core and give sensible
metrics. The test HA (`devenv/`, test LXC) is built with 0.2 (`docs/plan-0.2.md`, phase J).

## Phase D — Home Assistant integration

| Step | Work |
|---|---|
| D1 | `manifest.json`: `vtherm-api>=0.4.0`, config flow, local; newer VT features detected at runtime |
| D2 | config flow, simple and advanced: boiler class and power, optional gas consumption at minimum and maximum power, entity fields per signal (required: flame, flow temperature), circuits, VT zones per circuit with emitter type and size, foreign-heat switches or sensors per zone, building (coarse answers or heat loss), weather entity, reference-room strategy; options flow; every option with a cautious default and a description of what it does and what it risks |
| D3 | transport from mapped entities: freshness per signal, capabilities from filled fields |
| D4 | `vtherm_link.py`: VT zones, `central_mode`, device power; capability detection |
| D5 | coordinator: state events plus a 30 s tick; bounded rolling history in HA storage |
| D6 | entities: boiler metrics, connection, signal check, per-zone hot water available and emitter power factor, critical zone, reference room, verdict, alarms; advanced entities hidden by default |
| D7 | FC0: `weather.get_forecasts` (hourly and daily) every 30 min, 90-day retention |
| D8 | diagnostics download, redacted |
| D9 | translations EN and PL, key-parity test |
| D10 | "no writes" test |

Config-flow signal fields — entity pickers filtered by domain and device class, as in VT:

| Signal | Required | Entity |
|---|---|---|
| flame | yes | `binary_sensor` |
| flow temperature | yes | `sensor`, temperature |
| return temperature | no | `sensor`, temperature |
| modulation | no | `sensor`, % |
| CH setpoint | no | `sensor` or `number`, temperature |
| DHW active | no | `binary_sensor` |
| water pressure | no | `sensor`, pressure |
| flue gas temperature | no | `sensor`, temperature |
| outdoor temperature | no | `sensor`, temperature |
| thermostat room setpoint | no | `sensor`, temperature |
| thermostat room temperature | no | `sensor`, temperature |
| CH active | no | `binary_sensor` |
| pump running | no | `binary_sensor` |
| gas meter | no | `sensor`, gas or energy |
| weather | no | `weather` |
| foreign heat, per zone | no | `switch`, `binary_sensor` or `sensor` |

The VT feature manager is registered in 0.2, not here: its code runs inside VT's loop.

Done when: integration tests pass for setup, unload, reload, missing entities, stale data and
replayed history.

## Done for 0.1

All unit and integration tests and `ruff` pass. 0.1 is not released on its own: work continues
with `docs/plan-0.2.md`, and the release steps are there (phase K).

## Open for 0.1

None at the start. New questions go to the user; answers are recorded here.
