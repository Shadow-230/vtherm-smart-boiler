# Plan 0.2 — Control base and first release

Goal: the first release with control — the 0.1 monitor (`docs/plan-0.1.md`) plus minimal, safe
control in flow-setpoint mode: the plugin decides the water temperature. Room-value mode (the
boiler's own curve decides it) moves to 0.3. Control is opt-in, marked experimental, and
available from the first day; the monitor's verdict comes after 7 days of data (`SCOPE.md` §10;
the user's decision of 2026-10-08 replaced the monitoring period that held control back). On/off-only boilers
(relay) come later (0.2.2: on/off boilers through a relay, `docs/plan-0.2.2.md` X8). GitHub and
every publication come at the end of 0.2 (the user's decision, 2026-09-24).
Scope: `SCOPE.md`; overview: `PLAN.md`.

Phases run in order: F, G, H, I, J, K — the build first, then the test HA with the user (J2, J4),
the review and the release. S3 can happen at any time.

Status on 2026-10-10: built through 0.2.3 (`docs/plan-0.2.3.md`, done). The repository is public
on GitHub since 2026-10-07 (K5's first half, below), with its checks green; J2 done (2026-10-08);
I6 done (2026-10-09; `docs/plan-0.2-i6.md`); G11 done (2026-10-10; `docs/plan-0.2-g11.md`); I7
next (`docs/plan-0.2-i7.md`); J4 running (the scenarios I6, G11 and I7 touch run again, each pull
request names them);
then the rest of K1, K4, then K5's
pre-release (provisionally 0.2.3b1, `docs/plan-0.2.2.md` decision 16), K6 and K7. S3 stays
optional.

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
    research/diy/      sources of DIY boiler interfaces, read for interface facts (git-ignored;
                       `research/diy/INDEX.md`)
    .github/workflows/ tests, ruff, Hassfest, HACS
    LICENSE NOTICE README.md CHANGELOG.md hacs.json

## Start

| Step | Work |
|---|---|
| S1 ✅ | this plan written and `CLAUDE.md` updated: code and delegation rules (2026-09-24) |
| S2 ✅ | review of the 0.1 monitor laws — moved to K4 (the user's decision, 2026-09-24) |
| S3 🔒 | optional, at any time once there is heating data: the user copies their recorder database to `data/`; the importer's results are compared with what the user sees (starts, DHW runs on a shared return) |

## Phase F — checks before control code

Reads over the network and of local sources, for facts only; results in `research/`; the user
decides where a choice is needed.

| Step | Question |
|---|---|
| F1 ✅ | Writable entities for a flow setpoint (and optionally a modulation cap and CH enable): ESPHome / DIYLess, EMS-ESP, newer OTGW firmware (none in `opentherm_gw` or firmware 1.7.4 over MQTT, `research/2026-09-24-otgw-write-paths.md`). For every write path: a volatile override that expires (needs repeating), a persistent write (memory wear, must stay rare), or a value the gateway holds and keeps sending (neither) — which may need a third write type |
| F2 ✅ | Auto-TPI once VT's central boiler is replaced: `central_boiler_manager.is_on` without a configured boiler — whether Auto-TPI would stop learning |
| F3 ✅ | OTGW topologies for flow-setpoint control (`SCOPE.md` §5, "Gateway topology"): detection of the gateway mode and of a connected thermostat; behaviour when `CS` is not repeated; hand-back effects per topology (`CS=0`, monitor mode `GW=0`); whether the gateway mode is stored persistently; what the boiler does during an HA outage in each topology |
| F4 ✅ | The feature-manager contract of `vtherm_api` 0.5.0 and VT 10.4.0: what VT calls, when, and what happens on an exception |
| F5 ✅ | `opentherm_gw` in Home Assistant 2026.9.3: service fields, the gateway ID, and the entities that echo the confirmed control setpoint, modulation cap and CH enable |
| F6 ✅ | OTGW firmware over MQTT: command topics, the echo of each command, values after a gateway reset |
| F7 ✅ | The DHW-enable bit when the gateway is master: how it is set and how the plugin keeps it as it was |

Done when: answers recorded and `SCOPE.md` §11 updated. Open choices — among them the default
hand-back method per topology and a possible third write type — get the most cautious option as
a provisional decision; the user confirms them at K4.

Answers (2026-09-24): `research/2026-09-24-write-paths-f1-f6.md`,
`research/2026-09-24-vt-otgw-interfaces-f2-f4-f5.md`, `research/2026-09-24-otgw-topologies-f3-f7.md`;
the decisions they led to are in `SCOPE.md` §11.

## Phase G — control core (test first)

Flow-setpoint mode; 0.2 writes one circuit, a second circuit through the boiler (CH2) comes later.

| Step | Work |
|---|---|
| G0 ✅ | control model: a state machine — monitor, heating, idle, summer, frost protection, fallback setpoint, handed back — every decision with its reason (0.2.1: no summer state; summer and winter come from VT) |
| G1 ✅ | heating curve (one for the written circuit; per circuit with CH2, `SCOPE.md` §5) (entered; taking it from the boiler's parameters is left for later); effective outdoor temperature, smoothed, with the weather entity as the fallback source |
| G2 ✅ | limits: hard minimum and maximum, weather-dependent ceiling, underfloor maximum capping a shared unmixed circuit, frost protection |
| G3 ✅ | summer/winter threshold with hysteresis (0.2.1: summer and winter come from VT; the threshold stays in the monitor only) |
| G4 ✅ | boiler demand from device count, total power or valve opening |
| G5 ✅ | basic anti-cycling: minimum burn, minimum pause, starts per hour (removed in 0.2.1: VT decides whether to heat, and nothing counted or timed holds heating against it) |
| G6 ✅ | failure rules: stale data → no write; failed sensor → safe fallback setpoint (value is an option); low-flow warning when all valves are closed while the pump runs (needs a pump-running or CH-active signal; otherwise unavailable with the reason) |
| G7 ✅ | decision clock for the water temperature, an option (default 5 min, VT's default cycle); keep-alive every 30 s where the write path needs it; heating on/off follows the zones at every 10 s step (0.2.1) |
| G8 ✅ | ramp: the water temperature changes at a limited rate (option, cautious default); with a persistent write type, steps of at least the minimum change (0.2.1: K per minute at every step; nothing persistent is written) |
| G9 ✅ | write guards for every write: rate limits; minimum on and off times and a cap on switchings per hour for CH on/off; for persistent writes (declared persistent or unknown) a minimum change (default 1 K) and a daily cap — once reached, the last value held and an alarm raised, or hand-back, the user's choice; a value changed from outside written again at most once, then an alarm, no fight (keep-alive repeats of an expiring override are not rewrites); a hand-back write held back by no guard and not bound by the hard limits (values are options, the guards are fixed; since 0.2.2 the hard limits bind the hand-back value, `docs/plan-0.2.2.md` V5, S-21). 0.2.1: a write-rate guard replaces the rate limits; the minimum on and off times, the switching cap, the minimum change and the daily cap go, as nothing is written to the boiler's persistent memory |
| G10 ✅ | closed-loop tests against the simulator extended with a controllable boiler (an expiring setpoint override like OTGW's, CH enable, modulation cap, DHW-enable bit): rooms hold their setpoints, hard limits are never exceeded, starts stay within the budget (no budget from 0.2.1), after hand-back the boiler returns to its own control, no write without fresh data (0.2.2: starts under control compared with the boiler's own regulation, S-15, T-24 — `docs/plan-0.2.2.md` Z3) |
| G11 ✅ | the corrections of 2026-10-10 (from J4 and the review of the "curve too low" case): the comfort correction on by default in full control, within the user's limit, with a warning repair issue when the curve is too low for a room; SmartPI's learning phase in "is the room short"; the curve's room temperature Auto or Manual; a long burn without warming and a window probably open told to the user; planned step by step in `docs/plan-0.2-g11.md`. Done on 2026-10-10 (pull requests #51 to #57) |

Done when: every law has unit tests, including limits, stale data and sensor failure, and the
closed-loop tests pass.

Review: the control laws, the write guards and the proposed defaults (limits, fallback setpoint,
ramp, minimum times), each with its reason, go to the user's review at K4 — before anything
reaches a real boiler.

## Phase H — write path and VT integration

| Step | Work |
|---|---|
| H0 ✅ | writers in a separate module, created only while control is enabled; the read transport keeps no write method (0.2.1: a writer lives through hand-backs inside a session; a unit that only hands back may exist, M4) |
| H1 ✅ | write transport: (1) user-picked entity; (2) built-in OTGW through `opentherm_gw` services or firmware MQTT commands. Repetition by write type: built-in OTGW `CS` every 30 s; a picked entity by its declared write type — expiring: repeated every 30 s; persistent or unknown (default): on change only, within the persistent-write guards (G9) — from 0.2.1 never written, control stays off; state from the value the boiler confirmed, never the requested one, read from the mapped confirmed-setpoint entity (required); on/off overrides the device does not echo (e.g. CH enable) stay marked unverified and rely on the write guards; ignored command reported; DHW-enable bit kept as it was; a 0 from rarely polled values treated as unknown |
| H2 ✅ | hand-back on unload, reload, error, data loss, `central_mode` "Stopped" (0.2.1: "Stopped" acts through the zones' demand, not a hand-back; the OTGW hand-back sends CH=1 before CS=0) and an alarm set to hand back, with every override cleared (setpoint, CH on/off, modulation cap) — the user's chosen method: for built-in OTGW `CS=0` (default) or monitor mode (only with a physical thermostat, if F3 allows it), for an entity a value, the device's timeout or a switch; control cannot be enabled without one; what hand-back leads to depends on the topology (the thermostat takes over, or heating stops) and is shown to the user; reload leaves no loop running (0.2.1: monitor mode is not offered as a hand-back method; 0.2.2: the safe hand-back — the lowest water temperature, `CH=1`, then the release, `docs/plan-0.2.2.md` V5) |
| H3 ✅ | replaces VT's central boiler; a warning when both are active; obeys `central_mode` (0.2.1: through the zones' demand, as VT applies it per zone; 0.2.2: a blocker, cleared only after the Home Assistant restart VT needs, `docs/plan-0.2.2.md` X7) |
| H4 ✅ | VT feature manager with the two zone values; every exception caught so VT's loop never breaks |
| H5 ✅ | learning pauses (options, on by default): SmartPI (`set_smartpi_learning`) during DHW in zones calling for heat, in zones with foreign heat on, and during large water temperature changes; Auto-TPI resumed only with `reinitialise: false` (built: Auto-TPI is not paused, as `set_auto_tpi_mode` is not a pure pause; a repair issue names the zones) |
| H6 ✅ | gateway topology: detected where the gateway reports it, otherwise declared (built: declared, as F3 found it cannot be read); control is unavailable, with the reason shown, where the topology does not allow it; the plugin never changes the gateway mode on its own |
| H7 ✅ | the allowed service calls follow from the configuration; a test checks them, and that monitor mode still calls only `weather.get_forecasts` |

## Phase I — config flow and entities

| Step | Work |
|---|---|
| I1 ✅ | control switch: off by default, available after the monitoring period (default 7 days, user may change it), marked experimental; cannot be enabled without a hand-back method and a confirmed-setpoint entity (the relay path has its own conditions since 0.2.2, `docs/plan-0.2.2.md` X8); the verdict stays visible |
| I2 ✅ | fields: writable entity or built-in device, write type for a picked entity (expiring, persistent, or unknown — counted as persistent) and the reaction to a reached daily cap (hold and alarm, or hand back), gateway topology (detected or declared) with the hand-back effect stated, hand-back method, limits and curve (one curve for the written circuit until CH2), demand thresholds, anti-cycling, learning pauses, write-guard values (0.2.1: anti-cycling, the write-guard values, the persistent write type and the cap reaction go), alarm reactions per alarm type (built: info or hand back, no separate stop); each with a cautious default, a description and its risks; simple and advanced levels |
| I3 ✅ | control-state entities: current setpoint and its reason, last write and read-back, hand-back state, anti-cycling state (0.2.1: no anti-cycling state in 0.2) |
| I4 ✅ | translations EN and PL; key-parity test |
| I5 ✅ | alarm thresholds as advanced options (open from 0.1) |
| I6 ✅ | the first panel of the setup asks how the boiler is connected (the user's decisions of 2026-10-08): the OpenTherm Gateway through Home Assistant's integration; the OTGW firmware over MQTT; ESPHome OpenTherm; EMS-ESP; a relay (an on/off boiler); the boiler's own Wi-Fi module or the manufacturer's integration; another writable entity (advanced); monitoring only. The choice sets the write path, the write types, the hand-back and whether a heating switch is required, suggests the signal entities, and says what happens to the boiler when Home Assistant stops — the OTGW: its override lapses within a minute and the thermostat takes over (stand-alone, heating stops); EMS-ESP: its setpoint lapses within about a minute, so the plugin repeats it; ESPHome: it holds the last setpoint and CH enable until it restarts (its API `reboot_timeout`, 15 min by default), then its configured initial values — control needs the user's tick that a safe initial value and a short `reboot_timeout` are set on the ESP, as the relay needs its separate-contact tick, with a sample ESPHome configuration in the user guide; the boiler's Wi-Fi module or the manufacturer's integration: writes usually go to the boiler's memory or through a cloud, so monitoring, and control only where the write type is known and not persistent. Control stays off by default: the choice switches nothing on. The config and options flows, translations (EN, PL), tests, the user guides and `SCOPE.md` §4. Widened by the user's decisions of 2026-10-08 and 2026-10-09 — the control mode, the heat source, the boiler type and hot-water priority, freshness defaults, control in the wizard — and planned step by step in `docs/plan-0.2-i6.md`. Done on 2026-10-09 (pull requests #36 to #48 and I6.7's) |
| I7 | the setup and the options move through a menu of sections, as in Versatile Thermostat (the user's decisions of 2026-10-10): a section returns to the menu, nothing is saved until "Save and finish" (in the setup "Create", offered once every section shown has been confirmed and the whole passes the check), which runs every check of the save and reloads once; sections that do not apply are not shown; the menu names the unsaved changes, and closing the window discards them; the pressure and flue-gas limits shown only with their sensor. Planned step by step in `docs/plan-0.2-i7.md` |

Done when: integration tests cover enabling and disabling control, every hand-back path, the
"no write without fresh data" rule and the list of allowed service calls.

## Phase J — test environment and acceptance

| Step | Work |
|---|---|
| J1 ✅ | `devenv/`: `compose.yaml` (pinned image, config volume, plugin, VT and SmartPI mounted read-only, port), `configuration.yaml` with a fake boiler from helpers, rooms and weather; `scripts/deploy_test.sh` syncs files to the test LXC with rsync over SSH and restarts Home Assistant; setup guide for the user (0.2.1 R4: one tar stream over SSH, no rsync; the simulator component instead of helpers) |
| J2 ✅ | done by the user on 2026-10-08: the test LXC, Debian 13, 4 cores, 8 GB, 28 GB; Docker; the firewall on the Proxmox host; T-25 passed from the LXC and from a container, again after the LXC's reboot, and repeated by Claude from each Home Assistant instance; the project's SSH key for the deploy user; up to five instances, one login copied from the first (`devenv/README.md`, section 6). The step as planned: user, at any time: a new LXC for the tests alone (unprivileged Debian 13, `nesting=1`, `keyctl=1`, a static IPv4 address, IPv6 off), Docker, and a firewall on the Proxmox host at the LXC's network device — out of reach from inside the LXC, Claude's SSH reaching the LXC alone — letting the LXC reach the internet but no device on the home network, the production HA, its broker and the gateway among them (`devenv/README.md`; S-19; the user's decision, 2026-10-08, in place of the rules inside the LXC); a long-lived token for Claude; address, token and SSH key in `devenv/local.env` and `devenv/ssh/` (git-ignored). Check T-25: from a container and from the LXC itself, TCP to the production HA, its broker, the gateway and one more home device must time out — a refusal means the packet reached the target; over IPv6, "no route" passes too — checked with a positive control and again after the LXC's reboot (`devenv/README.md`); run by the user at J2, after the user has consented to `devenv/README.md`'s updated setup guide (the gateway stub, the thermostat-terminals answer, the stub's read-back, the relay steps; `research/2026-10-02-z3-readme-proposal.md`), which J2 and J4 follow; Claude repeats it over SSH only after the user has said to start J4 |
| J3 ✅ | physics simulator of our own as a test-only component in the test HA: writable setpoint entities (expiring and persistent, with a write counter) and an OTGW-like command path, burner with minimum power and hysteresis, water volume, house as one mass, zones; topologies: gateway or monitor mode, with a physical thermostat, without one, or with a virtual one |
| J4 🔒 | acceptance scenarios, first automated in-process against the simulator (no Home Assistant instance; done: `tests/integration/test_acceptance.py`), then the same run by Claude in the test HA through its API once the user says to start: hand-back on every exit, confirmed, and retried while its target is unavailable; a restart without a clean stop handing back; keep-alive loss; hard limits; stale data and a lost boiler link (an alarm, then hand-back); outdoor-sensor failure (the fallback setpoint, never zero heat); reload; DHW-enable bit kept; ignored command detected; heating on and off following VT's zones at once, both ways, with no hold — a short-cycling boiler included; `central_mode` "Stopped" giving no demand rather than a hand-back; zones `unavailable`, in "auto" or of the over_climate type; frost protection; the comfort correction within +3 K; control refused without a hand-back, without a confirmed-setpoint source, or with a persistent or unknown write target; an alarm handing back; every topology allowing control only where it may and handing back as described; a value changed from outside, or never confirmed, rewritten at most once and then an alarm; a hand-back write passing every guard (the list as changed by 0.2.1); plus the monitor on fake entities. 0.2.2 revises these to the decisions of 2026-09-26/27 (`docs/plan-0.2.2.md`) and adds, in the simulator only (nothing reaches a real boiler before K4): one scenario per class of decision 6 — a lost command with a trace; a single untraced fall-back; a second within an hour, and one a send explains (answer E); ignored from the start; clipped; another controller, with the full safe hand-back (answer H), the latch and the return by itself; a held device that restarts (S-13, T-47); the lost link, and for a relay an alarm, the command again on its return and no hand-back; the recognition period, the grace period and "every zone unknown", with and without the "own room controller" tick (answer F), and on the relay path with the tick and each rest state (answer M); frost heating only for zones that can take heat, and a repair issue for a closed one; only decision 7's alarms handing back — the plugin's own monitor failing for 5 min hands back, then control resumes by itself (answer I), and the boiler's own fault gives the usual "off" after 5 min; the safe hand-back, its parts at once one after the other, and at a step aside written once even over the other controller's value, a target it then takes counting as done (answer H); control refused for an on/off contact or "I don't know" on the thermostat terminals, without a heating switch, for a boiler that ignores "heating off" from the start of the session (blocked and handed back until control is switched off and on, answer O), for a gateway entry with no answer on its thermostat terminals (answer K) and for a relay without the "separate contact" tick (answer G) — the simulator's PIC `CH=0` flag with an on/off thermostat shows why (T-07); a lost or damaged store handing back first (answer K); the activation delay, on the relay path too; a relay that restarts (seen unavailable, or found in its declared power-cut state without that, answer D; the fourth such restart within 24 h, and a relay declared "last" or "I don't know" changing while available, stepping aside, answer N), loses Wi-Fi, is switched by an automation or its own button (the step aside setting the rest state once, then leaving the relay alone, answer L), has a switch-off timer, or goes through a planned restart; starts under control against the boiler's own regulation in the same simulated house, under the conditions of `SCOPE.md`'s fixed-values row (decision 8 of `docs/plan-0.2.3.md`: comfort parity, a ±3 K daily outdoor swing at +8 °C and at −5 °C), the ratio reported for K4 (S-15, T-24); the wall thermostat after a hand-back; an unclean restart with `docker kill ha-test` over SSH and a lost link provoked by a means Z3 prepares, both in the test container only, after the user says to start (decision 15); the report records the `vtherm_api` version the test HA installed (`devenv/README.md`) |

Done when: every scenario passes in the test HA.

## Phase K — release

| Step | Work |
|---|---|
| K1 🔒 | release files — done on 2026-10-07: `LICENSE` (the official Apache-2.0 text, fetched with the user's consent), no `NOTICE` (as the other Apache-2.0 Home Assistant projects; the user's decision), the brand (`brand/` icon and logo in the Versatile Thermostat family's style, the name "Smart Boiler for Versatile Thermostat" — the user's choice), a first `README.md` and `README.pl.md` (status, roadmap, links) and the guides `documentation/en|pl/` (user guide, technical documentation); still to do: `CHANGELOG.md` and the full `README.md` (a high-level description, use cases and automation examples, as Home Assistant's quality-scale documentation rules ask; installation, what each entity means, what stays local, a section "Options and risks", a section "Versatile Thermostat settings with the plugin" (TPI's `tpi_coef_ext` beside the curve, and SmartPI 0.4.0's own outdoor term `u_ff1`, which cannot be switched off — principle 9, S-50), what hand-back does on each write path, a template for the user's manual fallback; removal; how often data update — the 30 s tick, the 10 s control step, the 5-min analysis, forecasts every 30 min; troubleshooting; known limitations, among them changes no read-back can see and a clip of a flat setpoint judged as another controller; supported devices; the relay setup recommendations, with the Shelly timer "not documented" until K6; the wall-thermostat texts — S-52), `CHANGELOG.md`, `hacs.json`; `manifest.json` code owners, documentation and issue tracker once the repository exists (K5); the README states the minimum VT version (10.2.0 loads external feature managers; 10.4.0 is the version tested) |
| K2 ✅ | workflows: tests, ruff, Hassfest, HACS action — written; its ✅ withdrawn until the validation passes (`docs/plan-0.2.1.md`, R1). Passing on GitHub since 2026-10-07: the two required test checks (the supported and the oldest supported Home Assistant), hassfest and HACS; the early warnings weekly and before `qas` and `main`; the tests on every CPU; a documentation-only pull request skips the tests (`CONTRIBUTING.md`, "Checks") |
| K3 ✅ | local git since 2026-09-24; `.gitignore` written before the first commit: `.tools/`, `.venv/`, `.tmp/`, `data/`, `vendor/`, `research/`, `home-assessment.md`, `devenv/local.env`, `devenv/ssh/` |
| K4 🔒 | the user reviews the 0.1 monitor laws, the control laws, the write guards and the defaults, and confirms the provisional decisions — before anything reaches a real boiler (the user's decisions, 2026-09-24). The agenda adds `docs/plan-0.2.2-details.md` Q4's list: the first published version (decision 16); the default of 20 °C and every "(provisional, K4)" value of `SCOPE.md`'s fixed-values table; the plan's answers to review questions 3, 5, 6, 8–12, 19 and 20; whether to lift the block on "off" as a low setpoint and on decision 1's low `CS` (decision 11, answer K); every item marked K4 in "Open after 0.2.2" and "Open after 0.2.3" (`docs/plan-0.2.2.md`, `docs/plan-0.2.3.md`), with J4's acceptable starts ratio (decision 8 of `docs/plan-0.2.3.md`; 0.2.2's #24 and #27); and the 0.2.1 change log read together with `docs/review-2026-09-26-vs-0.2.md` |
| K5 🔒 | first half done on 2026-10-07 — the repository `Shadow-230/vtherm-smart-boiler`, created by the user, public, with its description, topics, the history kept and the documents included (the user's choice); the branches working branch → `dev` → `qas` → `main`, protected by rulesets (`.github/rulesets/`, `CONTRIBUTING.md`); Claude works as `Shadow-230-bot` (`CLAUDE.md`); `main` holds the documentation until the first release. Still to do: the pre-release. GitHub repository (created by the user, or by Claude with the user's consent), public — HACS installs only from public repositories — with the description, topics and issues the HACS action checks; the manifest's code owners, documentation and issue tracker filled in; a pre-release — `docs/plan-0.2.2.md` Z2 sets the manifest and `tests/test_release.py` to 0.2.2b1 (step 4.3 of `docs/plan-0.2.3.md`: 0.2.3b1), and K5 publishes it or sets both to the version decision 16 picks at K4; K5 also decides the repository's content (whether it carries `CLAUDE.md`, the plans and the reviews, and so whether it starts from a clean history) |
| K6 🔒 | the user installs the pre-release on their installation through HACS; control is off by default, so it monitors first: 7 days; before control is enabled, a written manual fallback (how to return the boiler to its own control) is ready; control starts under supervision in mild weather; several days without errors; redacted diagnostics the user places in `data/` can be analysed. Where the user has a Shelly relay of their own, they check whether its switch-off timer restarts on a repeated "on" (`docs/plan-0.2.2.md` Q3.10); the result is kept in `research/`. It is never done at J4, which uses the simulator only |
| K7 🔒 | release — the manifest and `tests/test_release.py` set to the release version (decided at K4 and K5; provisionally 0.2.3, decision 16); the version's test report complete, `docs/test-reports/unreleased.md` renamed to `docs/test-reports/<version>.md`, with the pull request from `dev` to `qas` (the user's decision, 2026-10-08; `docs/test-reports/README.md`) |

## Done for 0.2

All tests and `ruff` pass; every acceptance scenario passes in the test HA; the author's
installation has monitored for 7 days and then run control without errors; the user has reviewed
0.1 and 0.2; published as the first release (its version decided at K4 and K5; provisionally
0.2.3b1).

## Open for 0.2

- J4 🔒, started by the user on 2026-10-08 in the test HA: instance 1 runs the scenarios one after
  another, instances 2 to 5 the starts criterion's four runs of 24 h (until 2026-10-10). No
  monitoring period holds control back there either (the user's decision, 2026-10-08).
- J4's results go into the version's test report as its batches end (`docs/test-reports/`;
  the user's decision, 2026-10-08); the runner is `devenv/j4/`.
- I6: the first panel — how the boiler is connected — after J4's scenarios on instance 1 and
  before K4; the J4 scenarios the changed flows touch run again in the test HA.
- K1 🔒: `CHANGELOG.md` and the full `README.md` (the license text is in, 2026-10-07).
- K4: the user's decision of 2026-10-08 — no monitoring period holds control back; control may be
  switched on from the first day, and the option is the verdict's days of data (`SCOPE.md` §10) —
  reviewed with the other provisional decisions.
- For the review (K4), besides the provisional decisions in `SCOPE.md` §11 — what the
  independent reviews of the control code (2026-09-24) leave for the user to decide (the
  decisions of 2026-09-25 settle several: a lost link raises an alarm, nothing persistent is
  written, the comfort correction stays within +3 K — `docs/plan-0.2.1.md`):
  - Stand-alone gateway: with the boiler's data lost, or an alarm set to hand back, the boiler
    does not heat until the data returns or the user acts. (0.2.2: decision 7 narrows the alarm
    hand-backs, and a relay out of reach gets an alarm and no hand-back.)
  - Two gateway disturbances in a day (reset, power blip) count as two outside changes: control
    hands back and stays latched until switched off and on. (0.2.2: moot, decision 6 — a lost
    command is sent again.)
  - A source that freezes without going unavailable (MQTT without availability) is not caught
    unless a freshness limit is set; control then runs on the curve without seeing the boiler.
  - Near the daily cap of wearing writes "off" is no longer written, so the boiler may heat
    without demand until the day's window frees up. (Removed, 0.2.1 M0.)
  - Comfort correction is on by default (up to 10 K above the curve; +3 K, 0.2.1 N5; off by default
    and at the advanced level only since K4.1; on again by default in full control since G11, at
    both levels, within the user's limit); a session's first setpoint
    is the curve's value, not ramped; Auto-TPI is not paused (a repair issue only); an OTGW
    read-back confirms what the gateway sent, not what the boiler took; the control switch comes
    back after a restart as it was.
  - Built differently from the steps above: alarm reactions are information or hand-back (no
    separate "stop", I2); the gateway topology is declared, not detected, as F3 found it cannot
    be read (H6); Auto-TPI is not paused, so no `reinitialise` handling (H5); 0.2 reads no rarely
    polled gateway values, so "a 0 counts as unknown" has nothing to act on yet (H1); the curve
    is entered, not taken from the boiler; the test HA's boiler, rooms and weather come from the
    simulator component rather than helpers (J1); the simulator models the gateway with and
    without a thermostat and a virtual controller (the entity path), not monitor mode, where the
    plugin refuses control anyway (J3).

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
