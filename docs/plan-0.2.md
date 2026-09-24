# Plan 0.2 — Control base and first release

Goal: the first release with control — the 0.1 monitor (`docs/plan-0.1.md`) plus minimal, safe
control in flow-setpoint mode: the plugin decides the water temperature. Room-value mode (the
boiler's own curve decides it) moves to 0.3. Control is opt-in, marked experimental, and
available after the monitoring period (default 7 days, `SCOPE.md` §10). On/off-only boilers
(relay) come later. GitHub and every publication come at the end of 0.2 (the user's decision,
2026-09-24).
Scope: `SCOPE.md`; overview: `PLAN.md`.

Phases run in order: F, G, H, I, J, K — the build first, then the test HA with the user (J2, J4),
the review and the release. S3 can happen at any time.

## Rules that shape this release

- Everything in `docs/plan-0.1.md` "Rules" still applies.
- No code of another application is used — VT and SAT in particular: nothing copied, adapted or
  translated. All code is written from descriptions of functionality (`SCOPE.md`, research
  notes). Another project's code is read only to verify facts about its interfaces; SAT's code is
  not read at all.
- Every delegated task includes, in full, every rule of `CLAUDE.md` and every restriction the user
  has given.
- No Home Assistant instance but the dedicated test HA, and that one only after the user says to
  start (J4). The author's installation is the user's alone (K6).
- The fixed safeguards (`SCOPE.md` §3 principle 11, §7) cover every write — flow setpoint, CH
  on/off, modulation cap — and are not options.
- Every write path, for any installation: a writable entity the user picked, and built-in OTGW
  through `opentherm_gw` services or its firmware over MQTT; otherwise monitor only
  (`SCOPE.md` §5). The plugin's own data is exposed through entities the plugin creates.
- The services the plugin may call follow from its configuration: in monitor mode only
  `weather.get_forecasts`; with control, the configured write path's services and the learning
  pauses (VT, SmartPI). A test checks the list.
- Control choices are the user's (`SCOPE.md` §3, principle 11): each option has a cautious
  default and a description of what it does and what it risks, in the config flow and the README.
- Nothing reaches a real boiler before every acceptance scenario passes in the test HA.
- 🔒 marks steps that need the user's consent or action; ✅ marks a finished step.
- Working mode as in `docs/plan-0.1.md`. The build runs to the end without the review stop after
  phase G: the user reviews everything before anything reaches a real boiler (K4; the user's
  decision, 2026-09-24). Choices phase F leaves open get the most cautious option as a
  provisional decision, confirmed at K4.

## Layout additions

    custom_components/vtherm_smart_boiler/
      core/            + control laws and write guards
      transport/       + writers, present only while control is enabled: user-picked entity;
                         built-in OTGW (`opentherm_gw` services, firmware MQTT commands)
      switch.py        control switch
    sim/               + controllable boiler; physics simulator as a test-only component
    .github/workflows/ tests, ruff, Hassfest, HACS
    LICENSE NOTICE README.md CHANGELOG.md hacs.json

## Start

| Step | Work |
|---|---|
| S1 ✅ | this plan written and `CLAUDE.md` updated: code and delegation rules (2026-09-24) |
| S2 | review of the 0.1 monitor laws — moved to K4 (the user's decision, 2026-09-24) |
| S3 🔒 | optional, at any time once there is heating data: the user copies their recorder database to `data/`; the importer's results are compared with what the user sees (starts, DHW runs on a shared return) |

## Phase F — checks before control code

Reads over the network and of local sources, for facts only; results in `research/`; the user
decides where a choice is needed.

| Step | Question |
|---|---|
| F1 | Writable entities for a flow setpoint (and optionally a modulation cap and CH enable): ESPHome / DIYLess, EMS-ESP, newer OTGW firmware (none in `opentherm_gw` or firmware 1.7.4 over MQTT, `research/2026-09-24-otgw-write-paths.md`). For every write path: a volatile override that expires (needs repeating), a persistent write (memory wear, must stay rare), or a value the gateway holds and keeps sending (neither) — which may need a third write type |
| F2 | Auto-TPI once VT's central boiler is replaced: `central_boiler_manager.is_on` without a configured boiler — whether Auto-TPI would stop learning |
| F3 | OTGW topologies for flow-setpoint control (`SCOPE.md` §5, "Gateway topology"): detection of the gateway mode and of a connected thermostat; behaviour when `CS` is not repeated; hand-back effects per topology (`CS=0`, monitor mode `GW=0`); whether the gateway mode is stored persistently; what the boiler does during an HA outage in each topology |
| F4 | The feature-manager contract of `vtherm_api` 0.5.0 and VT 10.4.0: what VT calls, when, and what happens on an exception |
| F5 | `opentherm_gw` in Home Assistant 2026.9.3: service fields, the gateway ID, and the entities that echo the confirmed control setpoint, modulation cap and CH enable |
| F6 | OTGW firmware over MQTT: command topics, the echo of each command, values after a gateway reset |
| F7 | The DHW-enable bit when the gateway is master: how it is set and how the plugin keeps it as it was |

Done when: answers recorded and `SCOPE.md` §11 updated. Open choices — among them the default
hand-back method per topology and a possible third write type — get the most cautious option as
a provisional decision; the user confirms them at K4.

## Phase G — control core (test first)

Flow-setpoint mode; 0.2 writes one circuit, a second circuit through the boiler (CH2) comes later.

| Step | Work |
|---|---|
| G0 ✅ | control model: a state machine — monitor, heating, idle, summer, frost protection, fallback setpoint, handed back — every decision with its reason |
| G1 ✅ | heating curve per circuit (entered, or taken from the boiler's parameters); effective outdoor temperature, smoothed, with the weather entity as the fallback source |
| G2 ✅ | limits: hard minimum and maximum, weather-dependent ceiling, underfloor maximum capping a shared unmixed circuit, frost protection |
| G3 ✅ | summer/winter threshold with hysteresis |
| G4 ✅ | boiler demand from device count, total power or valve opening |
| G5 ✅ | basic anti-cycling: minimum burn, minimum pause, starts per hour |
| G6 ✅ | failure rules: stale data → no write; failed sensor → safe fallback setpoint (value is an option); low-flow warning when all valves are closed while the pump runs (needs a pump-running or CH-active signal; otherwise unavailable with the reason) |
| G7 ✅ | decision clock at the shortest VT zone cycle (default 5 min); keep-alive clock every 30 s |
| G8 ✅ | ramp: the water temperature changes at a limited rate (option, cautious default); with a persistent write type, steps of at least the minimum change |
| G9 ✅ | write guards for every write: rate limits; minimum on and off times and a cap on switchings per hour for CH on/off; for persistent writes (declared persistent or unknown) a minimum change (default 1 K) and a daily cap — once reached, the last value held and an alarm raised, or hand-back, the user's choice; a value changed from outside written again at most once, then an alarm, no fight (keep-alive repeats of an expiring override are not rewrites); a hand-back write held back by no guard and not bound by the hard limits (values are options, the guards are fixed) |
| G10 | closed-loop tests against the simulator extended with a controllable boiler (an expiring setpoint override like OTGW's, CH enable, modulation cap, DHW-enable bit): rooms hold their setpoints, hard limits are never exceeded, starts stay within the budget, after hand-back the boiler returns to its own control, no write without fresh data |

Done when: every law has unit tests, including limits, stale data and sensor failure, and the
closed-loop tests pass.

Review: the control laws, the write guards and the proposed defaults (limits, fallback setpoint,
ramp, minimum times), each with its reason, go to the user's review at K4 — before anything
reaches a real boiler.

## Phase H — write path and VT integration

| Step | Work |
|---|---|
| H0 | writers in a separate module, created only while control is enabled; the read transport keeps no write method |
| H1 | write transport: (1) user-picked entity; (2) built-in OTGW through `opentherm_gw` services or firmware MQTT commands. Repetition by write type: built-in OTGW `CS` every 30 s; a picked entity by its declared write type — expiring: repeated every 30 s; persistent or unknown (default): on change only, within the persistent-write guards (G9); state from the value the boiler confirmed, never the requested one, read from the mapped confirmed-setpoint entity (required); on/off overrides the device does not echo (e.g. CH enable) stay marked unverified and rely on the write guards; ignored command reported; DHW-enable bit kept as it was; a 0 from rarely polled values treated as unknown |
| H2 | hand-back on unload, reload, error, data loss, `central_mode` "Stopped" and an alarm set to hand back, with every override cleared (setpoint, CH on/off, modulation cap) — the user's chosen method: for built-in OTGW `CS=0` (default) or monitor mode (only with a physical thermostat, if F3 allows it), for an entity a value, the device's timeout or a switch; control cannot be enabled without one; what hand-back leads to depends on the topology (the thermostat takes over, or heating stops) and is shown to the user; reload leaves no loop running |
| H3 | replaces VT's central boiler; a warning when both are active; obeys `central_mode` |
| H4 | VT feature manager with the two zone values; every exception caught so VT's loop never breaks |
| H5 | learning pauses (options, on by default): SmartPI (`set_smartpi_learning`) during DHW in zones calling for heat, in zones with foreign heat on, and during large water temperature changes; Auto-TPI resumed only with `reinitialise: false` |
| H6 | gateway topology: detected where the gateway reports it, otherwise declared; control is unavailable, with the reason shown, where the topology does not allow it; the plugin never changes the gateway mode on its own |
| H7 | the allowed service calls follow from the configuration; a test checks them, and that monitor mode still calls only `weather.get_forecasts` |

## Phase I — config flow and entities

| Step | Work |
|---|---|
| I1 | control switch: off by default, available after the monitoring period (default 7 days, user may change it), marked experimental; cannot be enabled without a hand-back method and a confirmed-setpoint entity; the verdict stays visible |
| I2 | fields: writable entity or built-in device, write type for a picked entity (expiring, persistent, or unknown — counted as persistent) and the reaction to a reached daily cap (hold and alarm, or hand back), gateway topology (detected or declared) with the hand-back effect stated, hand-back method, limits and curve per circuit, demand thresholds, anti-cycling, learning pauses, write-guard values, alarm reactions per alarm type (info, stop, hand back); each with a cautious default, a description and its risks; simple and advanced levels |
| I3 | control-state entities: current setpoint and its reason, last write and read-back, hand-back state, anti-cycling state |
| I4 | translations EN and PL; key-parity test |
| I5 | alarm thresholds as advanced options (open from 0.1) |

Done when: integration tests cover enabling and disabling control, every hand-back path, the
"no write without fresh data" rule and the list of allowed service calls.

## Phase J — test environment and acceptance

| Step | Work |
|---|---|
| J1 | `devenv/`: `compose.yaml` (pinned image, config volume, plugin, VT and SmartPI mounted read-only, port), `configuration.yaml` with a fake boiler from helpers, rooms and weather; `scripts/deploy_test.sh` syncs files to the test LXC with rsync over SSH and restarts Home Assistant; setup guide for the user |
| J2 🔒 | user, at any time: LXC (Debian 12, `nesting=1`, `keyctl=1` if unprivileged), Docker, firewall blocking the production HA, its broker and the gateway; a long-lived token for Claude; address, token and SSH key in `devenv/local.env` and `devenv/ssh/` (git-ignored) |
| J3 | physics simulator of our own as a test-only component in the test HA: writable setpoint entities (expiring and persistent, with a write counter) and an OTGW-like command path, burner with minimum power and hysteresis, water volume, house as one mass, zones; topologies: gateway or monitor mode, with a physical thermostat, without one, or with a virtual one |
| J4 🔒 | acceptance scenarios, first automated in-process against the simulator (no Home Assistant instance), then the same run by Claude in the test HA through its API once the user says to start: hand-back on every exit, keep-alive loss, hard limits, stale data, sensor failure, reload, DHW-enable bit kept, ignored command detected, minimum burn and pause, `central_mode` "Stopped", frost protection, control refused without a hand-back or without a confirmed-setpoint source, an alarm handing back, every topology allowing control only where it may and handing back as described, CH on/off respecting minimum on and off times, persistent writes only on the minimum change and stopped at the daily cap with the last value held, a value changed from outside rewritten at most once and then an alarm, a hand-back write passing every guard; plus the monitor on fake entities |

Done when: every scenario passes in the test HA.

## Phase K — release

| Step | Work |
|---|---|
| K1 🔒 | release files: `LICENSE` (official Apache-2.0 text, fetched with the user's consent at this step), `NOTICE`, `README.md` (installation, what each entity means, what stays local, a section "Options and risks", what hand-back does on each write path, a template for the user's manual fallback), `CHANGELOG.md`, `hacs.json`; `manifest.json` code owners, documentation and issue tracker once the repository name is known |
| K2 | workflows: tests, ruff, Hassfest, HACS action |
| K3 ✅ | local git since 2026-09-24; `.gitignore` written before the first commit: `.tools/`, `.venv/`, `.tmp/`, `data/`, `vendor/`, `research/`, `home-assessment.md`, `devenv/local.env`, `devenv/ssh/` |
| K4 🔒 | the user reviews the 0.1 monitor laws, the control laws, the write guards and the defaults, and confirms the provisional decisions — before anything reaches a real boiler (the user's decisions, 2026-09-24) |
| K5 🔒 | GitHub repository (created by the user, or by Claude with the user's consent) and a pre-release `0.2.0b1` — private if HACS can install from a private repository (to verify), otherwise public, marked pre-release |
| K6 🔒 | the user installs the pre-release on their installation through HACS; control is off by default, so it monitors first: 7 days; before control is enabled, a written manual fallback (how to return the boiler to its own control) is ready; control starts under supervision in mild weather; several days without errors; redacted diagnostics the user places in `data/` can be analysed |
| K7 🔒 | release 0.2.0, repository public |

## Done for 0.2

All tests and `ruff` pass; every acceptance scenario passes in the test HA; the author's
installation has monitored for 7 days and then run control without errors; the user has reviewed
0.1 and 0.2; release 0.2.0 is published.

## Open for 0.2

- Phase F questions.

Decided on 2026-09-24: 0.2 writes one circuit, CH2 later; room-value mode moves to 0.3; 0.2
supports every write path, for any installation; GitHub and every publication come at the end of
0.2, so the monitor pre-release (phase E) is folded into K; the build runs to the end and one
review — the 0.1 laws, the control laws and the defaults — comes before anything reaches a real
boiler (K4).

## Moved to 0.3

Room-value mode: the plugin sends the reference room's temperature and setpoint to the boiler —
built-in OTGW (`RT` / `BS`, overriding a physical thermostat's values, or injected with `AA` when
there is none) or picked entities; it never writes the flow setpoint or the curve; only from a
valid reference room, within plausible room bounds, rate-limited, cleared when no valid reference
exists and on hand-back. Its checks: room values with a physical thermostat (override) and
without one (does the boiler heat on its own curve with only `RT` / `BS` and CH enable, no `CS`);
the OTGW firmware version that added `RT` and `BS`. Its acceptance scenarios: room values cleared
when the reference room is lost; room-value mode never writing the flow setpoint.
