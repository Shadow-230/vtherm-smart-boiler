# VTherm Smart Boiler

Working rules, code conventions and verified facts for Claude. **Where to continue:** the first
step without ✅ in [`docs/plan-0.1.md`](docs/plan-0.1.md), then in
[`docs/plan-0.2.md`](docs/plan-0.2.md); phases run in order. 0.1 and 0.2 are built in one go;
0.2 is the first release.

- **Scope** (general, any installation): [`SCOPE.md`](SCOPE.md)
- **Development plan:** [`PLAN.md`](PLAN.md); plans per release:
  [`docs/plan-0.1.md`](docs/plan-0.1.md), [`docs/plan-0.2.md`](docs/plan-0.2.md)
- **Research** (network reads, dated): `research/`
- **Author's own assessment**, private — never a source of values for code, defaults, tests or
  docs: [`home-assessment.md`](home-assessment.md)

Each topic lives only in its file; do not copy it here.

## Working rules

- The user converses in Polish; everything written into the repository is in English, except
  translation files for other languages (e.g. `translations/pl.json`).
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
  and SmartPI 0.4.0 sources in `vendor/` (A5). The official license text only with the user's
  consent at that step (`docs/plan-0.2.md` K1).
- Nothing is created without the user's consent: no files or directories (temporary ones
  included), repositories, installs, environments, issues or pull requests.
  Exceptions: files and directories in the agreed layout (the "Layout" sections of
  `docs/plan-0.1.md` and `docs/plan-0.2.md`) are created without asking; results of network
  reads may be kept in `research/` in the working directory (git-ignored).
- These rules bind subagents too: every delegated task states them.
- Tools, Python, package caches and temporary files live inside the project (`.tools/`, `.venv/`,
  `.tmp/`, git-ignored); every command runs as `scripts/env.sh <command>`, which sets the
  variables and runs the command. No `sudo`; no changes to the home directory, shell profile or
  global git config.
- Git is local only (since 2026-09-24): commit after every completed step with a descriptive
  message; never add a remote or push without the user's consent. Code, test and
  tool-configuration files may be changed without asking — history keeps every change.
  Documents (`*.md`) and the user's files still need a shown diff and consent. Anything not
  tracked by git is shown and confirmed before it is deleted or overwritten.
- Autonomous work: phases run in order without waiting; work stops at every 🔒 step and at the
  review stops after phases B and G (`docs/plan-0.1.md`, `docs/plan-0.2.md`); each finished step
  is marked ✅ in its plan and committed, so the next session knows where to continue; a step
  found unnecessary is marked ✅ with the reason.
  Subagents may be used and are bound by these rules; a multi-agent workflow only when the user
  asks for one.
- **Never touch the production Home Assistant instance** (location in Claude's memory): no
  deploys, no writes. The plugin reaches it only as a HACS release.
- **Neither Claude nor subagents connect to any Home Assistant instance** — by any means (REST,
  WebSocket, MQTT, SSH, UI, add-ons). Sole exception: the dedicated test HA in its own Proxmox
  LXC. Its address and access data live only in the git-ignored `devenv/local.env`; never
  connect to an address that is not listed there.
- Use the Explore subagent for repository searches.
- Read large files in parts (offset and limit, `sed -n`): the harness saves oversized tool
  output outside the project.
- Once code exists: start changes in `core/` with a test; before a commit run
  `python -m pytest -q` and `ruff check .` through `scripts/env.sh`.

## Code conventions (for when code starts)

- Reference: [KipK/vtherm_hysteresis](https://github.com/KipK/vtherm_hysteresis) shows how a VT
  plugin registers — read, not copied. It registers a proportional algorithm; we register a
  feature manager (`register_feature_manager`).
- **Never copy code from any project** — ideas only, re-implemented from scratch.
- Python 3.14 (HA requires ≥ 3.14.2 since 2026.3), `from __future__ import annotations`, types
  everywhere.
- `core/` is pure logic with zero Home Assistant imports, enforced by a test that parses its
  imports; control and learning laws are pure functions with unit tests.
- Zone data only through one module (`vtherm_link.py`); no `hass.states.get(...)` by entity name
  elsewhere.
- Detect capabilities (`hasattr`, import in `try`); VT, `vtherm_api` and SmartPI change fast and
  older versions must work.
- `translations/en.json` is the source; every user-visible string via translation keys; a test
  checks key parity across languages.
- Every user option has a cautious default and a translated description of what it does and what
  it risks (`SCOPE.md` §3, principle 11).
- Test layers: `PLAN.md`, section "Test environment".

## Verified facts

- **`vtherm_api`**: class `VThermAPI`, `VThermAPI.get_vtherm_api(hass)`; `register_feature_manager`,
  `get_feature_manager_factories`, `list_feature_managers`, `register_prop_algorithm`,
  `PluginClimate`. No central hook — hence the plugin replaces VT's central boiler itself.
  A feature manager can add attributes to the VT climate (`add_custom_attributes`); its
  `refresh_state()` runs after the algorithm (one-cycle lag). The thermostat method
  `get_feature_manager(name)` exists from VT 10.5.0.beta1, not in 10.4.0.
- **VT central configuration**: `select.central_mode` (Auto, Stopped, Heat only, Cool only, Frost
  protection) — the plugin obeys it. Central boiler: binary sensor on device count or total power
  thresholds, calls on/off actions — the plugin replaces it.
- **VT** uses current outdoor temperature only; forecast is on its "future improvements" list.
  Auto-TPI learns in sessions (≥ 50 cycles). `set_auto_tpi_mode`: disabling pauses (cycles and
  coefficients kept); re-enabling with the default `reinitialise: true` wipes them — always send
  `reinitialise: false`. Auto-TPI skips learning while power shedding is active or VT's central
  boiler is off.
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
- **Related plugins (no overlap)**: `vtherm_heating_failure_detection` (rooms),
  `vtherm_heating_optimizer` (chooses pellet/AC/electric source), `vtherm_adaptive_tpi`.
  `vtherm_pellet_stove` (MIT) drives a central heat source — a reference. No license, ideas
  only: `Virtual-VTherm-Simulator`, both `heating-simulator` repos (caiusseverus, Juans77).
  OTGW-firmware is GPL-3.0; the OTGW equipment matrix (tclcode.com) has no license.
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
  `research/2026-09-24-otgw-write-paths.md`.
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
