# Smart Boiler for Versatile Thermostat

Working rules, code conventions and verified facts for Claude. **Where to continue:** the first
step without ✅ (optional ones aside) in [`docs/plan-0.1.md`](docs/plan-0.1.md), then in
[`docs/plan-0.2.1.md`](docs/plan-0.2.1.md) (corrections that come before the rest of 0.2), then
in [`docs/plan-0.2.2.md`](docs/plan-0.2.2.md) (corrections after the review of 2026-09-26; the
details of each step are in [`docs/plan-0.2.2-details.md`](docs/plan-0.2.2-details.md), which opens
with "Start here"), then in [`docs/plan-0.2.3.md`](docs/plan-0.2.3.md) (corrections after the
review of 2026-10-04, in four parts, each ending with a stop where the user decides whether the
next starts), then in [`docs/plan-0.2.md`](docs/plan-0.2.md), whose status line says where the
build stands; phases run in order. A 🔒 step whose plan says it holds nothing up is noted in the
report and passed; work goes on with the next step. 0.1 and 0.2 are built in one go; the first
published version is decided at K4 and K5 (`docs/plan-0.2.2.md`, decision 16; provisionally
0.2.3b1).

- **Scope** (general, any installation): [`SCOPE.md`](SCOPE.md)
- **Development plan:** [`PLAN.md`](PLAN.md); plans per release:
  [`docs/plan-0.1.md`](docs/plan-0.1.md), [`docs/plan-0.2.md`](docs/plan-0.2.md),
  [`docs/plan-0.2.1.md`](docs/plan-0.2.1.md), [`docs/plan-0.2.2.md`](docs/plan-0.2.2.md) with
  [`docs/plan-0.2.2-details.md`](docs/plan-0.2.2-details.md),
  [`docs/plan-0.2.3.md`](docs/plan-0.2.3.md)
- **Research** (network reads, and the notes and raw results of every analysis and check, dated):
  `research/`
- **Author's own assessment**, private — never a source of values for code, defaults, tests or
  docs: [`home-assessment.md`](home-assessment.md)

Each topic lives only in its file; do not copy it here.

## Working rules

- The user converses in Polish; everything written into the repository is in English, except
  translation files for other languages (e.g. `translations/pl.json`). Replies to the user are in
  plain, less technical Polish: what was done, what it means for the house and the boiler, and
  what needs the user's answer (the user's rule, 2026-09-26/27).
- **We build a universal plugin, not a custom project for the author's HA.** Never write
  installation-specific data — entity IDs, device names, the author's boiler, house or zone
  values — into code, defaults, tests or docs. Every input comes from a config-flow field where
  the user picks the entity, as in VT; the author's installation is configured like any other.
  Entities that expose the plugin's data are created by the plugin; entities the plugin needs —
  inputs and write targets — are picked by the user.
- **This will control a home's heating.** A bug means a cold house or a boiler cycling every
  minute, not a red test. When in doubt, choose the more cautious option.
- Verify facts in the code or docs of VT, `vtherm_api` and SmartPI before relying on them; mark
  what is assumed.
- Stay inside the working directory. Reading or writing anything outside it — including the
  production HA directory and Claude's memory directory — requires the user's explicit consent
  for that specific access.
- External sources (VT, `vtherm_api`, SmartPI, HA, anything else) are read over the network
  only: no clones, downloads or copies on disk, temporary directories included. Exceptions,
  consented 2026-09-24: `uv` from PyPI into `.tools/bootstrap/` (`docs/plan-0.1.md` A1); Python
  3.14 through `uv` into `.tools/python/` (A2); packages from PyPI into `.venv/` (A3); VT 10.4.0
  and SmartPI 0.4.0 sources in `vendor/` (A5). Sources and documents of typical DIY boiler
  interfaces (OTGW, ESPHome, EMS-ESP, DIYLess and the like) are downloaded on purpose into the
  git-ignored `research/diy/` — one folder per solution, every file listed with its source, date
  and license in `research/diy/INDEX.md` — rather than left by a tool outside the project; read
  for interface facts only (the user's decision, 2026-09-24). The official license text only
  with the user's consent at that step (`docs/plan-0.2.md` K1). CI on GitHub's servers fetches VT
  10.4.0 and SmartPI 0.4.0 from their tags for the real-VT tests; nothing is downloaded locally
  (`docs/plan-0.2.2.md`, decision 14).
- Nothing is created without the user's consent: no files or directories (temporary ones
  included), repositories, installs, environments, issues or pull requests.
  Exceptions: files and directories in the agreed layout (the "Layout" sections of
  `docs/plan-0.1.md` and `docs/plan-0.2.md`) are created without asking; results of network
  reads, and every finding and result of an analysis or check, are kept in `research/` in the
  working directory (git-ignored) — the user's rule, 2026-09-27: all findings and results are
  saved there.
- These rules bind subagents too: every delegated task includes, in full, every rule of this
  file and every restriction the user has given — not a summary.
- Tools, Python, package caches and temporary files live inside the project (`.tools/`, `.venv/`,
  `.tmp/`, git-ignored); every command runs as `scripts/env.sh <command>`, which sets the
  variables and runs the command. No `sudo`; no changes to the home directory, shell profile or
  global git config.
- Git: commit after every completed step with a descriptive message. The repository is public on
  GitHub, `Shadow-230/vtherm-smart-boiler` (since 2026-10-07); Claude works there as the
  collaborator account `Shadow-230-bot`. Flow: a working branch → `dev` → `qas` → `main` (release).
  Claude pushes only to its own working branches (`claude/<topic>`, from `dev`), opens a pull
  request from it to `dev` and merges it itself once the checks pass, deleting the working branch
  on GitHub and locally as it merges (`gh pr merge --delete-branch`; the user's rule,
  2026-10-08); it never pushes to `dev`,
  `qas` or `main` directly (the one exception: their first creation on 2026-10-07, before the
  rulesets), never force-pushes or deletes them, never makes a tag or a GitHub release, and never
  merges anyone else's pull request. A pull request from `dev` to `qas`, or from `qas` to `main`, is
  opened only when the user says so; the user approves and merges both and makes releases
  (`CONTRIBUTING.md`; `.github/CODEOWNERS`; the rulesets in `.github/rulesets/`). An issue or a
  comment on GitHub is published only with the user's consent.
  The bot's token has no `workflow` scope: a push that changes `.github/workflows/` waits until
  the user grants it for that one push (`gh auth refresh -h github.com -s workflow`) and takes it
  back at once (`gh auth refresh -h github.com --remove-scopes workflow`); Claude checks
  `gh auth status` after, and never keeps or asks for the scope otherwise.
- Autonomous work: phases run in order without waiting; work stops at every 🔒 step; the user
  reviews before anything reaches a real boiler (`docs/plan-0.2.md`, K4); each finished step
  is marked ✅ in its plan and committed, so the next session knows where to continue; a step
  found unnecessary is marked ✅ with the reason.
  Subagents may be used and are bound by these rules; a multi-agent workflow only when the user
  asks for one.
- Tokens (the user's rule, 2026-10-05/06): work is cut into small pieces — a subagent gets a few
  problems at a time, told to read only what it needs and to keep its report short — and every
  stop reports the tokens the subagents used.
- Consent (the user's rule, 2026-10-07): a message that asks a question or reports a state is not
  consent to change anything. Before acting, say what will change; act only on the user's
  explicit go-ahead.
- **Never touch the production Home Assistant instance** (location in Claude's memory): no
  deploys, no writes. The plugin reaches it only as a HACS release.
- **Neither Claude nor subagents connect to any Home Assistant instance** — by any means (REST,
  WebSocket, MQTT, SSH, UI, add-ons). Sole exception: the dedicated test HA in its own Proxmox
  LXC. Its address and access data live only in the git-ignored `devenv/local.env`; never
  connect to an address that is not listed there, and connect only after the user has said to
  start (`docs/plan-0.2.md`, J4). J4 may provoke an unclean restart (`docker kill` over SSH) and a
  lost link in the test HA's own container only, after that start (`docs/plan-0.2.2.md`,
  decision 15).
- Use the Explore subagent for repository searches.
- Read large files in parts (offset and limit, `sed -n`): the harness saves oversized tool
  output outside the project.
- Once code exists: start changes in `core/` with a test; before a commit run through
  `scripts/env.sh`, as CI does: the core tests without Home Assistant
  (`python -m pytest -q -p no:homeassistant --disable-socket --allow-unix-socket tests/core`),
  then the others (`python -m pytest -q --ignore=tests/core`), `ruff check .`,
  `ruff format --check .` and `mypy`.

## Code conventions (for when code starts)

- Reference: [KipK/vtherm_hysteresis](https://github.com/KipK/vtherm_hysteresis) shows how a VT
  plugin registers — read, not copied. It registers a proportional algorithm; we register a
  feature manager (`register_feature_manager`).
- **Never use code from another application** — VT and SAT in particular: nothing copied,
  adapted or translated. Code is written from descriptions of functionality. Another project's
  code may be read only to verify facts about its interfaces (names, attributes, services,
  behaviour); SAT's code is not read at all.
- Python 3.14 (HA requires ≥ 3.14.2 since 2026.3), `from __future__ import annotations`, types
  everywhere.
- `core/` is pure logic with zero Home Assistant imports, enforced by a test that parses its
  imports; control and learning laws are pure functions with unit tests.
- Zone data only through one module (`vtherm_link.py`); no `hass.states.get(...)` by entity name
  elsewhere.
- Detect capabilities (`hasattr`, import in `try`); VT, `vtherm_api` and SmartPI change fast and
  older versions must work.
- `translations/en.json` is the source; every user-visible string via translation keys; a test
  checks key parity across languages. The language is the Home Assistant instance's: the plugin
  has no language setting of its own (the user's rule, 2026-09-24).
- Every user option has a cautious default and a translated description of what it does and what
  it risks (`SCOPE.md` §3, principle 11).
- Test layers: `PLAN.md`, section "Test environment".

## Verified facts

- **`vtherm_api`**: class `VThermAPI`, `VThermAPI.get_vtherm_api(hass)`; `register_feature_manager`,
  `get_feature_manager_factories`, `list_feature_managers`, `register_prop_algorithm`,
  `PluginClimate`. No central hook — hence the plugin replaces VT's central boiler itself.
  A feature manager can add attributes to the VT climate (`add_custom_attributes`); its
  `refresh_state()` runs after the algorithm (one-cycle lag). The thermostat method
  `get_feature_manager(name)` exists from VT 10.5.0.beta1, not in 10.4.0. `get_vtherm_api`
  creates a bare API when VT has none yet — call it only once VT's instance exists. A factory is
  picked up when a thermostat starts; a running one sees it only after VT's reload. VT loads
  external feature managers from 10.2.0 (with `vtherm_api` 0.4.0's factory registry); VT 10.0 and
  10.1 depend on `vtherm_api` for control algorithms only, so there a registration succeeds and no
  manager is ever created (Q3.1, `research/2026-09-27-q3-1-vt-feature-manager-version.md`).
- **VT central configuration**: `select.central_mode` (Auto, Stopped, Heat only, Cool only, Frost
  protection); VT applies it only to thermostats that follow the central mode
  (`is_controlled_by_central_mode`, VT 10.4.0 `base_thermostat.py`), so the plugin sees it
  through the zones' demand. Central boiler: binary sensor on device count or total power
  thresholds, calls on/off actions — the plugin replaces it. VT starts its thermostats at
  `EVENT_HOMEASSISTANT_STARTED` (at the end of an entry's setup once Home Assistant runs), while
  `hass.is_running` is already true during start-up; each VT climate has `is_ready`. Reloading the
  central entry makes the central-boiler binary sensor unavailable, then `off` until VT's boiler
  state next changes; `select.central_mode` restores its last value (L3,
  `research/2026-09-25-l3-device-facts.md`). VT 10.4.0's central boiler (`vendor/`,
  `config_schema.py`, `const.py`, `feature_central_boiler_manager.py`): activation delay 0–600 s
  in steps of 10, default 0 — a drop during the wait does not cancel it, and demand is checked
  again at its end; repeat interval `keep_alive_boiler_delay_sec` 0–3600 s, default 0; its
  commands are free-form actions; its power criterion uses each zone's `mean_cycle_power`
  (`sensor.py`); it counts heating devices, not zones. Unticking it deletes its two commands
  (`config_flow.py`); that its keep-alive keeps resending the old command until Home Assistant
  restarts is inferred from the code, not seen.
- **VT** uses current outdoor temperature only; forecast is on its "future improvements" list.
  Auto-TPI learns in sessions (≥ 50 cycles). `set_auto_tpi_mode` is not a pure pause: the
  `reinitialise` default is true (wipes the learning), the allow-flags are overwritten on every
  call, configured coefficients return after a restart while learning is off, and enabling may
  rewrite and reload the VT entry — the plugin does not call it (0.2). Auto-TPI skips learning
  while power shedding is active or VT's central boiler is off; without a central boiler it
  never learns in zones flagged `is_used_by_central_boiler`. VT 10.4.0 publishes
  `auto_tpi_state` and `auto_tpi_continuous_kext` ("on"/"off") for every TPI zone; only "on"
  means Auto-TPI learns.
- **Zones are modelled alone**: no VT, SmartPI or TPI model uses another zone's data; the only
  house-wide signals are power shedding and central boiler off, used only to skip learning.
- **SmartPI**: 1R1C room model, no water/boiler input. Services `set_smartpi_learning`
  (`learning_enabled`), `force_smartpi_calibration`, `reset_smartpi_learning`,
  `reset_smartpi_integral` (per thermostat). Publishes `on_percent`, `u_pi`, `u_ff`, `u_ff1`,
  `u_ff2`, `u_ff_final`, `bootstrap_state`, drift states, `deadtime_heat_s`. `u_ff1` contains
  outdoor temperature. Reads no external input (no entity option, no plugin lookup, no boiler
  concept); power shedding freezes its learning. `set_smartpi_learning` pauses without losing
  the model.
- **HA forecasts**: only through `weather.get_forecasts`, not in entity state — the recorder
  does not keep them. HACS inclusion has no license requirement.
- **Home Assistant 2026.9.3**: shutdown jobs (`hass.async_add_shutdown_job`) run before
  `EVENT_HOMEASSISTANT_STOP` — the plugin hands back in one, and a job must not remove itself
  while they run (Home Assistant would skip the next one). All shutdown jobs run side by side
  under one shared 20 s limit; at 20 s Home Assistant cancels those still running and goes on
  (`core.py`). At the stop event MQTT stops reconnecting but keeps its connection until the
  process ends (Q3.3, `research/2026-09-27-q3-3-hand-back-vs-ha-stop.md`). MQTT
  entities write their state only when a value changes (unless `force_update`), so a steady MQTT
  source keeps an old `last_reported`; `opentherm_gw` rewrites every entity on each report.
- **Related plugins (no overlap)**: `vtherm_heating_failure_detection` (rooms),
  `vtherm_heating_optimizer` (chooses pellet/AC/electric source), `vtherm_adaptive_tpi`.
  `vtherm_pellet_stove` (MIT) drives a central heat source — a reference. No license, ideas
  only: `Virtual-VTherm-Simulator`, both `heating-simulator` repos (caiusseverus, Juans77).
  OTGW-firmware v1.7.5 is MIT (its LICENSE file and headers; earlier notes said GPL-3.0); the
  OTGW PIC firmware source is under Schelte Bron's own license (no redistribution without
  permission, Q3.8); the OTGW equipment matrix (tclcode.com) has no license.
- **OTGW** (firmware reference, otgw.tclcode.com): `CS` / `C2` must be repeated at least once a
  minute or the gateway falls back to the thermostat's value — the plugin repeats every 30 s.
  `RT=` (ID 24) and `BS=` (ID 16) set room temperature and setpoint; without a thermostat they
  also need `AA=24` / `AA=16`. Its author: boilers do not need room temperature and setpoint.
  No writable entity for the flow setpoint or the modulation cap: `opentherm_gw` (HA 2026.9.3)
  has no `number` — services `set_control_setpoint`, `set_max_modulation`,
  `send_transparent_command`; firmware 1.7.4 over MQTT neither — commands on
  `<top>/set/<node>/<command>` (`ctrlsetpt`, `maxmodulation`, `chenable`, `command`). Reported
  from the author's installation, to confirm: `SW` does not expire; values outside the gateway's
  regular polling (e.g. ID 48 bounds) read 0 after a gateway reset.
  `research/2026-09-24-otgw-write-paths.md`. Firmware MQTT: commands resent after 5 s, up to 5
  times; `TSet` echoes what the gateway sends, not the boiler's acceptance; `CS`, `MM` and `CH`
  are lost at a PIC reset (`research/2026-09-24-write-paths-f1-f6.md`). PIC 6.6 source (L3,
  `research/2026-09-24-otgw-topologies-f3-f7.md`): `CH=0` sets a flag kept through `CS=0` and the
  override's lapse until `CH=1` or a reset — it masks CH enable under any later `CS` and an
  on/off thermostat's demand, while an OpenTherm thermostat's own CH bit passes again after
  `CS=0`; `TSet` carries `CS` whatever `CH`; a Data-Invalid or Unknown-DataID reply to ID 1
  clears the `CS` override without a message; stand-alone the PIC polls ID 18 itself, and a reset
  zeroes its stored values, so `opentherm_gw` shows water pressure 0.0 until a real reading.
  `opentherm_gw` (HA 2026.9.3, `binary_sensor.py`, `sensor.py`, `__init__.py`): the boiler device
  has "Low water pressure", "Gas fault", "Air pressure fault" and "Water overtemperature" problem
  sensors and two "Central heating 1" entities (CH active, running; CH enabled); the thermostat
  device has its own "Control setpoint 1"; it sends `CS=0` in its cleanup when it unloads.
  pyotgw 2.2.3 passes on only ACK and DATA frames, so Data-Invalid and Unknown-DataID replies
  are skipped (`research/diy/pyotgw/2.2.3/messageprocessor.py`). The OTGW firmware resets the PIC
  when its ESP boots (`research/diy/otgw-firmware/v1.7.5/OTGW-firmware.ino`).
- **DIY masters** (L3, `research/2026-09-25-l3-device-facts.md`): ESPHome `opentherm` sends CH
  enable only with `t_set` > 0 and its `ch_enable` switch on — a low setpoint leaves CH enabled,
  and its docs require the switch to turn heating off; the ESP resends its values itself (held)
  and by default reboots after 15 min without a Home Assistant API client, coming back with
  `t_set` at its initial value. DIYLess stock firmware idles at 10 °C with CH enabled; users
  report the pump running. EMS-ESP `selflowtemp` and `selburnpow` expire within about a minute
  and EMS-ESP never resends them; it holds `heatingoff` itself; `heatingactivated`, `heatingtemp`
  and the other parameter telegrams stay in the boiler — whether in EEPROM is not documented. No
  report found of a boiler showing CH off with the flame on, or of flame flicker.
- **User needs** (VT and SAT issues, 2026-09-24, details in `research/`): short-cycling is the
  top complaint in both; boilers silently ignore some commands; a gateway acting as master lost
  the DHW-enable bit (Immergas); a reload left old loops toggling the boiler; a failed outdoor
  sensor stopped all heating. SAT never sends ID 24 / 16. VT users feed external OpenTherm
  controllers a reference room (spec: VT discussion #2068). VT's author adds no more to the
  central boiler and sends new features to plugins.
- **SAT** sources consulted for ideas: `pwm.py`, `minimum_setpoint.py`, `heating_curve.py`,
  `overshoot_protection.py`, `mqtt/opentherm.py`; SAT sends the setpoint only when its loop runs
  (no watchdog). What we take: `SCOPE.md` §8.
- **Nest** sources: Google Nest Help pages on OpenTherm, True Radiant and Seasonal Savings. What we
  take: `SCOPE.md` §8.
- **Licenses**: VT, `vtherm_api` MIT; `vtherm_hysteresis`, SmartPI Apache-2.0; SAT GPL-3.0.
  This plugin: Apache-2.0.
