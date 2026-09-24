# Plan 0.2 — Control base and first release

Goal: the first release — the 0.1 monitor (`docs/plan-0.1.md`) plus minimal, safe control in one
of two modes chosen by the user: flow setpoint (the plugin decides the water temperature) or room
values (the boiler's own curve decides it; the plugin changes neither curve nor water
temperature). Control is opt-in, marked experimental, and available after the
monitoring period (default 7 days, `SCOPE.md` §10). On/off-only boilers (relay) come later.
Scope: `SCOPE.md`; overview: `PLAN.md`.

Work starts when `docs/plan-0.1.md` is done; phases run in order.

## Rules that shape this release

- Everything in `docs/plan-0.1.md` "Rules" still applies.
- The fixed safeguards (`SCOPE.md` §3 principle 11, §7) cover every write — flow setpoint, CH
  on/off, modulation cap, room values — and are not options.
- Boiler writes go to a writable entity the user picked, or through built-in support for a
  device without one (first OTGW); otherwise monitor only (`SCOPE.md` §5). The plugin's own data
  is exposed through entities the plugin creates.
- Other service calls are limited to learning pauses (VT, SmartPI) and weather forecasts; a test
  lists every service the plugin may call.
- Control choices are the user's (`SCOPE.md` §3, principle 11): each option has a cautious
  default and a description of what it does and what it risks, in the config flow and the README.
- Nothing reaches a real boiler before every acceptance scenario passes in the test HA.
- 🔒 marks steps that need the user's consent or action; ✅ marks a finished step.
- Working mode as in `docs/plan-0.1.md`; the review stop in this release comes after phase G.

## Layout additions

    custom_components/vtherm_smart_boiler/
      core/            + control laws and write guards
      transport/       + writes: user-picked entity; built-in OTGW (`opentherm_gw` services,
                         firmware MQTT commands)
      switch.py        control switch
    sim/               + physics simulator as a test-only component for the test HA

## Phase F — checks before control code 🔒

Network reads; results in `research/`; the user decides where a choice is needed.

| Step | Question |
|---|---|
| F1 | Which integrations offer writable entities for a flow setpoint (and optionally a modulation cap and CH enable). Done for OTGW: none in `opentherm_gw` or firmware 1.7.4 over MQTT (`research/2026-09-24-otgw-write-paths.md`) — hence built-in support. Still to check: ESPHome / DIYLess, EMS-ESP, newer OTGW firmware. For every write path: is it a volatile override that expires (needs repeating) or a persistent write (memory wear, must stay rare) |
| F2 | Auto-TPI once VT's central boiler is replaced: `central_boiler_manager.is_on` without a configured boiler |
| F3 | OTGW topologies (`SCOPE.md` §5, "Gateway topology"): detection of the gateway mode and of a connected thermostat; behaviour when `CS` is not repeated; hand-back effects per topology (`CS=0`, monitor mode `GW=0`); whether the gateway mode is stored persistently; room-value mode with a physical thermostat (override) and without one (does the boiler heat on its own curve with only `RT` / `BS` and CH enable, no `CS`); what the boiler does during an HA outage in each topology, once `CS` is no longer repeated |
| F4 | OTGW firmware version that added `RT` and `BS` |

Done when: answers recorded, `SCOPE.md` §11 updated, the user has decided the open choices.

## Phase G — control core (test first)

G1–G3, G5 and G8 apply to flow-setpoint mode; in room-value mode the boiler runs its own control.
0.2 writes one circuit; a second circuit through the boiler (CH2) comes later.

| Step | Work |
|---|---|
| G1 | heating curve per circuit (entered, or taken from the boiler's parameters); effective outdoor temperature |
| G2 | limits: hard minimum and maximum, weather-dependent ceiling, underfloor maximum capping a shared unmixed circuit, frost protection |
| G3 | summer/winter threshold with hysteresis |
| G4 | boiler demand from device count, total power or valve opening |
| G5 | basic anti-cycling: minimum burn, minimum pause, starts per hour |
| G6 | failure rules: stale data → no write; failed sensor → safe fallback setpoint (value is an option), or in room-value mode the room values cleared; low-flow warning when all valves are closed while the pump runs (needs a pump-running or CH-active signal; otherwise unavailable with the reason) |
| G7 | decision clock at the shortest VT zone cycle (default 5 min); keep-alive clock every 30 s |
| G8 | ramp: the water temperature changes at a limited rate (option, cautious default); with a persistent write type, steps of at least the minimum change |
| G9 | write guards for every write: rate limits; minimum on and off times and a cap on switchings per hour for CH on/off; plausible bounds for room values; for persistent writes (declared persistent or unknown) a minimum change (default 1 K) and a daily cap — once reached, the last value held and an alarm raised, or hand-back, the user's choice; a value changed from outside written again at most once, then an alarm, no fight (keep-alive repeats of an expiring override are not rewrites); a hand-back write held back by no guard and not bound by the hard limits (values are options, the guards are fixed) |

Done when: every law has unit tests, including limits, stale data and sensor failure.

**Review stop 🔒:** the user reviews the control laws and write guards before phase H starts.

## Phase H — write path and VT integration

| Step | Work |
|---|---|
| H1 | write transport: (1) user-picked entity; (2) built-in OTGW through `opentherm_gw` services or firmware MQTT commands. Repetition by write type: built-in OTGW `CS` every 30 s; a picked entity by its declared write type — expiring: repeated every 30 s; persistent or unknown (default): on change only, within the persistent-write guards (G9); state from the value the boiler confirmed, never the requested one, read from the mapped confirmed-setpoint entity (required in flow-setpoint mode); on/off overrides the device does not echo (e.g. CH enable) stay marked unverified and rely on the write guards; ignored command reported; DHW-enable bit kept as it was; a 0 from rarely polled values treated as unknown |
| H2 | hand-back on unload, reload, error, data loss, `central_mode` "Stopped" and an alarm set to hand back, with every override cleared (setpoint, CH on/off, modulation cap, room values) — the user's chosen method: for built-in OTGW `CS=0` (default) or monitor mode (only with a physical thermostat, if F3 allows it), for an entity a value, the device's timeout or a switch; control cannot be enabled without one; what hand-back leads to depends on the topology (the thermostat takes over, or heating stops) and is shown to the user; reload leaves no loop running |
| H3 | replaces VT's central boiler; a warning when both are active; obeys `central_mode` |
| H4 | VT feature manager with the two zone values; every exception caught so VT's loop never breaks |
| H5 | learning pauses (options, on by default): SmartPI (`set_smartpi_learning`) during DHW in zones calling for heat, in zones with foreign heat on, and during large water temperature changes; Auto-TPI resumed only with `reinitialise: false` |
| H6 | room-value mode (alternative to flow-setpoint mode, off by default): sends the reference room's temperature and setpoint — built-in OTGW (`RT` / `BS` — overriding a physical thermostat's values, or injected with `AA` when there is none) or picked entities; never writes the flow setpoint or the curve; only from a valid reference room, within plausible bounds, rate-limited, cleared when no valid reference exists and on hand-back |
| H7 | gateway topology: detected where the gateway reports it, otherwise declared; control modes it does not allow are unavailable with the reason shown; the plugin never changes the gateway mode on its own |

## Phase I — config flow and entities

| Step | Work |
|---|---|
| I1 | control switch: off by default, available after the monitoring period (default 7 days, user may change it), marked experimental; cannot be enabled without a hand-back method and, in flow-setpoint mode, a confirmed-setpoint entity; the verdict stays visible |
| I2 | fields: writable entity or built-in device, write type for a picked entity (expiring, persistent, or unknown — counted as persistent) and the reaction to a reached daily cap (hold and alarm, or hand back), gateway topology (detected or declared) with the hand-back effect stated, hand-back method, limits and curve per circuit, demand thresholds, anti-cycling, learning pauses, control mode (flow setpoint or room values), write-guard values, alarm reactions per alarm type (info, stop, hand back); each with a cautious default, a description and its risks; simple and advanced levels |
| I3 | control-state entities: current setpoint and its reason (in room-value mode: the room values sent), last write and read-back, hand-back state, anti-cycling state |
| I4 | translations EN and PL; key-parity test |

Done when: integration tests cover enabling and disabling control, every hand-back path, the
"no write without fresh data" rule and the list of allowed service calls.

## Phase J — test environment and acceptance

| Step | Work |
|---|---|
| J1 | `devenv/`: `compose.yaml` (pinned image, config volume, plugin, VT and SmartPI mounted read-only, port), `configuration.yaml` with a fake boiler from helpers, rooms and weather; `scripts/deploy_test.sh` syncs files to the test LXC with rsync over SSH and restarts Home Assistant; setup guide for the user |
| J2 🔒 | user: LXC (Debian 12, `nesting=1`, `keyctl=1` if unprivileged), Docker, firewall blocking the production HA, its broker and the gateway; a long-lived token for Claude; address, token and SSH key in `devenv/local.env` and `devenv/ssh/` (git-ignored) |
| J3 | physics simulator of our own as a test-only component in the test HA: writable setpoint entities (expiring and persistent, with a write counter) and an OTGW-like command path, burner with minimum power and hysteresis, water volume, house as one mass, zones; topologies: gateway or monitor mode, with a physical thermostat, without one, or with a virtual one |
| J4 | acceptance scenarios, run by Claude through the test HA's API: hand-back on every exit, keep-alive loss, hard limits, stale data, sensor failure, reload, DHW-enable bit kept, ignored command detected, minimum burn and pause, `central_mode` "Stopped", frost protection, control refused without a hand-back, or in flow-setpoint mode without a confirmed-setpoint source, an alarm handing back, room values cleared when the reference room is lost, room-value mode never writing the flow setpoint, every topology allowing only its control modes and handing back as described, CH on/off respecting minimum on and off times, persistent writes only on the minimum change and stopped at the daily cap with the last value held, a value changed from outside rewritten at most once and then an alarm, a hand-back write passing every guard; plus the 0.1 monitor on fake entities |

Done when: every scenario passes.

## Phase K — release

| Step | Work |
|---|---|
| K1 🔒 | `LICENSE` (official Apache-2.0 text), `NOTICE`, `README.md` marked early with safety notes and a section "Options and risks", `CHANGELOG.md`, `hacs.json` |
| K2 | workflows: tests, ruff, Hassfest, HACS action |
| K3 ✅ | local git since 2026-09-24; `.gitignore` written before the first commit: `.tools/`, `.venv/`, `.tmp/`, `data/`, `vendor/`, `research/`, `home-assessment.md`, `devenv/local.env`, `devenv/ssh/` |
| K4 🔒 | GitHub repository and a pre-release 0.2.0b1 (private if HACS can install from a private repository — to verify; otherwise public, marked pre-release) |
| K5 🔒 | the user installs the pre-release on their installation through HACS; 7 days of monitoring; before control is enabled, a written manual fallback (how to return the boiler to its own control) is ready; control starts under supervision in mild weather; several days without errors |
| K6 🔒 | release 0.2.0, repository public |

## Done for 0.2

All tests and `ruff` pass; every acceptance scenario passes in the test HA; the author's
installation has monitored for 7 days and then run control without errors; release 0.2.0 is
published.

## Open for 0.2

- Phase F questions.

Decided: 0.2 writes one circuit; CH2 later (2026-09-24).
