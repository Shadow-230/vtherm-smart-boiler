[Polska wersja](README.pl.md)

[![Status][status-shield]](#status)
[![Release][release-shield]][releases]
[![Commit activity on dev][commits-shield]][commits]
[![License][license-shield]][license]
[![HACS][hacs-shield]](#installation)
[![Buy me a coffee][bmc-shield]][bmc]

# Smart Boiler for Versatile Thermostat

<p align="center">
  <img src="documentation/images/logo.png" alt="Smart Boiler for Versatile Thermostat logo" width="280" />
</p>

<p align="center"><b>
Runs a central heating boiler from what Versatile Thermostat's rooms need, and always hands it
back safely.
</b></p>

> **Not released yet — do not install it on a heating system you rely on.**
> The integration is being built and has not run on a real boiler. There is no release and no
> entry in the Home Assistant Community Store (HACS); the first pre-release follows the tests on a
> test Home Assistant and a review.
> Where it stands: [Status](#status) · what comes next: [Roadmap](#roadmap).

**Smart Boiler for Versatile Thermostat** is a plugin for [Versatile Thermostat][vt] (VT) — not part
of VT and not made by its authors — that runs a central heating boiler — gas, oil, electric or
another fuel, any boiler Home Assistant can talk to, not a heat pump — from what the rooms actually
need: fewer and longer burns, more condensing where the boiler condenses, less fuel per degree-day —
with the same room comfort, and without disturbing the zone algorithms' own room models. It replaces
VT's on/off central boiler with control of the boiler's water temperature, and always knows how to
hand the boiler back to its own control.

It is **not** a room controller (rooms stay with VT and its algorithms), it does not drive
valves or heat pumps, and it sends no data outside your Home Assistant.

# What it does

- **Monitor, and control when you choose.** It watches the boiler — burns and their length,
  condensing, hot-water draws, gas per degree-day, signal problems — and after 7 days of data
  gives a verdict on whether control is worth it. Until you switch control on, the boiler runs as
  before; you may switch it on from the first day.
- **Weather-compensated water temperature** on a curve you enter, bounded by the lowest and
  highest water temperature and each circuit's maximum.
- **Heating on and off follow VT's zones** — by zones calling, total power or valve opening, as
  VT's central boiler does — and VT's central modes act through the zones.
- **Writes through what you have:** an entity you pick, the OpenTherm Gateway (Home Assistant's
  `opentherm_gw` or its firmware over MQTT), or a relay for an on/off boiler.
- **Safety first:** frost protection, protection against short cycling, read-back of every
  write, never fighting another controller, nothing written to the boiler's permanent memory,
  and a safe hand-back to the boiler's own control on every exit — retried until confirmed.
- Every option has a cautious default and a text that says what it does and what it risks.

# Use cases

- **Is my boiler short-cycling?** Map the boiler's signals and leave control off: the monitor
  counts starts per hour, burn lengths, the condensing share and gas per degree-day, and its
  verdict says whether control is worth enabling. Nothing is written to the boiler.
- **An OpenTherm boiler with VT in every room.** The plugin sets the water temperature from the
  outdoor temperature and switches heating on and off from VT's zones, through the OpenTherm
  Gateway, ESPHome OpenTherm or EMS-ESP. With a wall thermostat on the gateway, the boiler goes
  back to it on every hand-back.
- **An on/off boiler.** A relay on the boiler's room-thermostat terminals follows VT's zones in
  place of VT's central boiler; the plugin checks the relay or repeats its command, and hands
  back to the relay's rest state.
- **Underfloor heating on a loop without a mixer.** The circuit's highest water temperature caps
  every setpoint, and an alarm tells you when the measured flow stays above it.

# Integration with Versatile Thermostat

1. Set up VT's thermostats for the rooms the boiler heats. If VT's central boiler is configured,
   untick it in VT's central configuration and restart Home Assistant: the plugin takes its place.
2. Add one **Smart Boiler for Versatile Thermostat** entry and pick the VT zones this boiler heats.
3. Pick the entity that provides each boiler signal — at least flame and flow temperature for
   control.
4. Let it monitor; its verdict comes after 7 days of data (by default).
5. Whenever you choose — from the first day, or after reading the verdict — set up control in the
   options and switch **Control (experimental)** on.

Step by step: the [user guide][guide].

## Beside VT's zone algorithms

The plugin reads VT's zones and never changes their settings or algorithms. Each zone's
thermostat gets one attribute, `smart_boiler`: `heat_available` — whether the boiler's heat
reaches the zone now — and `supply_temperature`, the water reaching it, rounded. A zone
algorithm can read the full water data ([water interface][water]); SmartPI 0.4.0 does not.
Nothing in VT depends on it.

The heating curve already raises the water temperature as it gets colder outside. Some zone
algorithms count the outdoor temperature as well, so the weather then acts twice:

- **TPI** (VT's time-proportional algorithm) adds `tpi_coef_ext` × (target − outdoor) to each
  zone's heating time. With the plugin's curve, colder weather brings both warmer water and longer
  heating times. The term is VT's setting, per zone; the plugin does not change it.
- **SmartPI** (0.4.0) learns an outdoor term of its own (`u_ff1`, a learned factor ×
  (target − outdoor)). It cannot be set or switched off; it learns with the water the plugin
  sends.

How a zone behaves with both depends on its room and its algorithm; the plugin describes this and
gives no advice on these settings. While hot water or a large change of the water temperature
disturbs the rooms, the plugin pauses SmartPI's learning (on by default), so the swings it causes
stay out of SmartPI's model.

# Supported devices

| Requirement | Version |
|---|---|
| Home Assistant | 2026.9 or later |
| Versatile Thermostat | 10.2.0 or later (it loads external feature managers from 10.2.0); 10.5.1 is the version tested — provisional until the first release |
| `vtherm_api` | 0.5.0 or later, installed with the plugin |
| SmartPI, Auto-TPI | optional; any VT zone algorithm works |

Any boiler whose signals Home Assistant shows as entities can be monitored. To control it, the
plugin writes through:

| Connection | What the plugin writes |
|---|---|
| OpenTherm Gateway, through Home Assistant's `opentherm_gw` | the control setpoint, repeated every 30 s, and heating enable |
| OpenTherm Gateway firmware over MQTT | the same, as the firmware's MQTT commands |
| ESPHome OpenTherm | its setpoint number and heating switch, held by the ESP |
| EMS-ESP | its flow setpoint, repeated every 30 s; setpoint 0 for "heating off" |
| A relay on the room-thermostat terminals (on/off boiler) | heating on and off only |
| Another writable entity (advanced) | what you pick, with the write type you declare |
| The boiler's Wi-Fi module, the manufacturer's integration, another read-only integration | nothing by default: monitoring |

Nothing is written that the boiler would store in its permanent memory: a target declared
persistent, or whose type is unknown, is never written. Tested so far against a simulated boiler
only. Details: [user guide, section 5][guide-connect].

# Installation

There is **no release yet**. Once there is one:

1. In HACS, open the menu → **Custom repositories**, add
   `https://github.com/Shadow-230/vtherm-smart-boiler` with the type **Integration**.
2. Find **Smart Boiler for Versatile Thermostat** in HACS and download it.
3. Restart Home Assistant, then add the integration under Settings → Devices & services.

Manual installation: copy `custom_components/vtherm_smart_boiler/` from the release into the
`custom_components/` folder of your Home Assistant configuration and restart Home Assistant.

Only one entry can exist: it runs one boiler.

# Entities

All belong to one device, named as you named the entry ("Boiler" by default). A monitor entity
exists only while the signals it needs are mapped; the sensor **Features** says which are
inactive and why. Some are hidden by default (marked *hidden*); **Forecast snapshots** is
disabled by default.

**Monitor**

| Entity | What it shows |
|---|---|
| Heating starts per hour | burner starts for heating, per hour over the last 24 h; burns that may have been hot water apart |
| Median heating burn | the typical length of a heating burn |
| Heating burner hours (24 h) *hidden* | burner hours for heating in the last 24 h |
| Short heating burns *hidden* | the share of heating burns shorter than the short-burn length (10 min by default) |
| Condensing share | the share of heating burn time with the return below 55 °C |
| Degree-days (7 days) *hidden* | the week's degree-days, from the heating threshold |
| Gas per degree-day | gas per degree-day, measured with a gas meter you map, else estimated |
| Use against yesterday *hidden* | the change in use against the day before, split into weather, hot water, settings and the rest |
| Control verdict | worth enabling, not worth enabling, or not enough data yet — with its reasons |
| Signal problems | how many mapped signals have a problem; each one's health in the attributes |
| Features | how many features are inactive now, and why |
| Building loss coefficient, Building heating threshold *hidden* | the building values in use — yours, measured or the default — with their source |
| Suggested lowest water temperature | a suggestion only, never applied |
| Forecast snapshots *disabled* | how many recorded forecasts are kept, for later releases |
| Critical zone, circuit … | per circuit, the zone whose own controller works hardest now |
| Signals | on while flame and flow (and a relay) are known and fresh |
| Outdoor sensor problem | the boiler's outdoor sensor is stuck or disagrees with the weather entity |
| Long burn without warming | the flame on for 3 h without the rooms warming, with the likely reason |
| Alarms (binary sensors, on = problem) | one per check: water pressure, flue gas, starts, ignition, low flow, a circuit's water too hot and the others — the [user guide's table][guide-alarms] |

**Control**

| Entity | What it shows or does |
|---|---|
| Control (experimental) | switches control on and off; its attributes say what blocks it and what a hand-back does in your installation |
| Control state | off, not allowed, handed back, waiting for data, heating, idle, frost protection, fallback setpoint or boiler fault — with its reasons |
| Control flow setpoint | the setpoint as the boiler confirms it; unknown otherwise, never the value asked for |
| Control: … (binary sensors) | the control alarms: write failed or ignored, another controller, hand-back failed, boiler link lost, a zone unknown, frost not warming and the others |
| Reset comfort correction | sets the comfort correction back to 0 |
| Reset measured heat loss, Reset measured heating threshold | forget the measured building values |

Problems that need you also show as repair issues under Settings → Repairs.

# How often data updates

- Boiler signals and zones are read when they change, and at least every **30 s**.
- Control takes a step every **10 s**; an expiring setpoint is repeated every **30 s**, a held one
  on a change and every 5 minutes.
- The monitor's metrics and verdict are computed every **5 minutes**.
- With a weather entity, forecasts are recorded every **30 minutes** (kept for later releases;
  nothing uses them for control yet).
- A signal counts as stale past its age limit: automatic by default, settable per signal
  ([Fresh data][guide-fresh]).

# What stays local

Everything. The plugin talks to no cloud service and sends nothing outside Home Assistant. It
reads entities, writes only to the targets you pick, keeps its state and recorded forecasts in
Home Assistant's own storage (`.storage`), and its sensors go to Home Assistant's recorder like
any other. A diagnostics download (the integration's device → Download diagnostics) replaces
entity IDs and the gateway's identifiers before you share it.

# Options and risks

Every option has a cautious default, and its text in the form says what it does and what it
risks. The main ones — described, not advised:

| Option | Default | What it does, and what it risks |
|---|---|---|
| Control (switch) | off | on, the plugin writes to the boiler; off, the boiler runs as before |
| Heating curve | the design flow has no default — you enter it | too high wastes gas and makes the burner cycle; too low leaves rooms cold |
| Lowest water temperature | 20 °C (provisional) | too low: in mild weather the boiler stops by itself again and again, and a non-condensing boiler condenses in its flue (its manual gives the value) |
| A circuit's highest water temperature | 70 °C where empty | caps every setpoint on circuits fed straight from the boiler; the boiler may overshoot it by its own hysteresis |
| Its too-hot alarm | the maximum + 5 K, for 10 min | information only; too high lets a real overshoot pass unreported |
| Comfort correction | on, up to 3 K (at most 10 K), rising at most 3 K a day | raises the water for a room that stays short of its target; with TPI zones it can hold the water higher and multiply the burner's starts |
| Activation delay | 0 s | waits before heating starts, for slow valves; meanwhile the rooms get no heat |
| Write type of a picked target | unknown — not written | expiring or held must be declared; a wrong declaration wears the boiler's memory or lets a value lapse |
| Hand-back value | none — entered with its effect | the same number means "own control" on one device and "no heat" on another |
| Frost protection | 5 °C on, 7 °C off, every zone | heats only zones whose emitters can take heat; a zone VT keeps closed gets a repair issue |
| Alarm reactions | information — a few alarms always hand back | an alarm set to hand back stops control until you switch it off and on |
| Return by itself after another controller | off | on, control returns 60 minutes after the last foreign value, while the other controller may still be there |
| Learning pauses (SmartPI) | on | off, the swings the plugin causes enter SmartPI's model |

Every default and the reason for it: the defaults table in [`SCOPE.md`, section 7][scope-defaults]. Values marked
provisional are reviewed before the first release.

# Hand-back

On every exit — control switched off, an alarm set to hand back, Home Assistant stopping, a lost
boiler link, an error — the plugin hands the boiler back, reads it back and retries until it is
confirmed ([the safe hand-back][guide-hand-back]). What follows depends on the write path:

| Write path | After hand-back |
|---|---|
| Gateway with an OpenTherm thermostat | the thermostat takes over; heating continues |
| Gateway without a thermostat (stand-alone) | heating **stops** until control resumes or you act |
| ESPHome OpenTherm, a writable entity | the value you declared: "its own control resumes", or "heating stops" |
| EMS-ESP | the setpoint lapses within about a minute; the boiler returns to its own setting |
| Relay | its rest state: off (default) — no heat unless a thermostat wired to the boiler calls; on — the boiler heats by its own setting |

After a hand-back the boiler's (or the wall thermostat's) own maximum water temperature applies,
not the plugin's.

**If Home Assistant is down.** Nothing of the plugin runs, so plan your manual way back:

- **Gateway:** the setpoint lapses within a minute — a thermostat on the gateway takes over;
  stand-alone, heating stops until Home Assistant runs again.
- **ESPHome OpenTherm:** the ESP keeps the last setpoint and heating until it restarts (by
  default after 15 minutes without Home Assistant), then takes its start values.
- **EMS-ESP:** the setpoint lapses within about a minute; the boiler heats on its own setting.
- **Relay:** stays as it was; switch it by hand in its own app or web page. A relay with its own
  switch-off timer switches heating off by itself.
- **Another writable entity:** up to the device.

# The wall thermostat

On a gateway with an OpenTherm thermostat, while the plugin controls, the wall thermostat's
heating setting and its off switch do nothing; its hot-water settings still work. After a
hand-back it heats again by its own setting and program. If you map its setpoint, the plugin
warns when it is unknown or below 15 °C: after a hand-back the house would be heated only to
that. An on/off thermostat (two wires) on the gateway's thermostat terminals blocks control:
the gateway would keep the plugin's "heating off" after a crash, and that thermostat could not
heat the house.

# The relay's settings

The plugin cannot read a relay's own settings, so its form asks for them; "I don't know" is the
default for each and is treated cautiously:

- **Separate contact** (tick) — the relay is a contact of its own, not a setting stored in the
  boiler's memory. Control does not start without it.
- **Reports its real state** — yes: the plugin writes only on a difference and checks the relay;
  no or I don't know: it repeats its command, unconfirmed.
- **State after a power cut** — off: the boiler waits for Home Assistant; on, last or I don't
  know: after a power cut the boiler may heat without control until Home Assistant is back.
- **Own switch-off timer** — none, a length (10–120 min; "on" is repeated at half of it), or I
  don't know. Whether a Shelly restarts its auto-off timer on a repeated "on" is not documented.
- **Repeat interval** — 10–300 s, 300 s by default.
- **Relay after hand-back** — off (default) or on.

More: [user guide, the relay][guide-relay].

# Automation examples

The entity IDs below are for an entry named "Boiler"; find yours on the integration's device.

Tell me when control hands the boiler back and cannot confirm it:

```yaml
automation:
  - alias: "Boiler hand-back failed"
    triggers:
      - trigger: state
        entity_id: binary_sensor.boiler_control_hand_back_failed
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: "The boiler's hand-back has not got through — check Settings → Repairs."
```

Tell me when the verdict is ready:

```yaml
automation:
  - alias: "Boiler control verdict"
    triggers:
      - trigger: state
        entity_id: sensor.boiler_control_verdict
        to:
          - "worth_it"
          - "not_worth_it"
    actions:
      - action: notify.notify
        data:
          message: "Control verdict: {{ states('sensor.boiler_control_verdict') }}"
```

Hand the boiler back before a service visit — switching control off does it:

```yaml
action: switch.turn_off
target:
  entity_id: switch.boiler_control_experimental
```

# Troubleshooting

- **Control does not switch on, or the control state says "Not allowed".** The switch's
  attributes (`blockers_text`, `blocked_by_text`) say what is missing; a repair issue usually says
  what to do.
- **The control state stays "Handed back".** The plugin stepped aside — another controller, the
  boiler ignoring "heating off", an alarm set to hand back. Fix the cause, then switch control off
  and on.
- **The verdict says "Not enough data yet", or a sensor is missing.** The sensors **Features** and
  **Signal problems** name the missing or stale signals.
- **"Signals" is off.** Flame or flow is stale or unknown: check the boiler's integration, or the
  signal's age limit ([Fresh data][guide-fresh]).
- **An alarm is on.** The [alarm table][guide-alarms] says what each means and what to do.
- **Logs.** Debug logging:

  ```yaml
  logger:
    logs:
      custom_components.vtherm_smart_boiler: debug
  ```

  With a problem report, attach the diagnostics download.

# Known limitations

- Not released, and not yet run on a real boiler: tested against a simulated boiler and on a
  test Home Assistant.
- **Changes no read-back can see:** heating switched off or summer mode on the boiler's panel, a
  lockout, the maker's app, another controller's modulation limit, the hot-water enable, a boiler
  that clamps the setpoint behind a gateway — the gateway still shows the plugin's value. They
  show only through their effects: the comfort correction at its limit (after about 4.5 h), or
  frost heating that does not warm a room (after 2 h).
- **A boiler that clips a steady setpoint** looks like another controller: a lower value is
  recognised as the boiler's own limit only once the plugin has sent values at least 1 K apart.
  With one steady value it is written back once, and a second change within 24 h makes the plugin
  step aside.
- One boiler per Home Assistant (one entry). No heat pumps, no valves, no hot-water control.
- Water-temperature control needs a heating on/off switch (except EMS-ESP); a gateway with an
  on/off thermostat on its terminals is monitor only.
- VT's own central boiler must be off, and Home Assistant restarted once.
- Forecasts are recorded, not used for control yet.
- On a Home Assistant install outside its container or OS image, Home Assistant installs the
  client libraries of the MQTT and OpenTherm Gateway integrations with the plugin, even if you use
  neither; without network access then, the plugin does not set up.
- Many values are provisional until the review before the first release.

# Removal

1. Optionally switch **Control (experimental)** off first and check the boiler is back under its
   own control.
2. Delete the entry: Settings → Devices & services → Smart Boiler for Versatile Thermostat →
   Delete. The plugin hands the boiler back, resumes SmartPI learning it had paused, and deletes
   its stored state and forecasts. If the hand-back could not be confirmed, a repair issue stays
   after removal: hand the boiler back by hand.
3. Remove it in HACS (or delete its folder) and restart Home Assistant.
4. To return to VT's own central boiler, tick it again in VT's central configuration.

# Status

| Stage | State |
|---|---|
| 0.1 Monitor (read-only) | built, published together with 0.2 |
| 0.2 Control base | built; corrected after three full reviews (0.2.1, 0.2.2, 0.2.3) |
| Tests on a test Home Assistant | running |
| Review before a real boiler | after those tests |
| First pre-release (provisionally 0.2.3b1) | after the review |

# Roadmap

| Release | Content |
|---|---|
| 0.2 Control base | the monitor plus control of the water temperature, the safe hand-back, frost protection |
| 0.3 Anti-cycling and the thermostat-like mode | duty cycling, a modulation cap, forecast planning, the thermostat-like mode, underfloor behind a mixing valve |
| 0.4 Learning and tuning | water-side learning, suggestions, seasonal tune-up |
| 0.5 Forecast | anticipation for slow emitters from recorded forecasts |
| Later | hot-water charging, the HACS default list, more devices |

Targets are aims, not commitments; each release collects data for the next. Details:
[`PLAN.md`][plan].

# Documentation

| Document | What it holds |
|---|---|
| [`SCOPE.md`][scope] | the specification: what the plugin does, its principles and every decision |
| [`PLAN.md`][plan] | the development plan, releases and the test environment |
| [`docs/`][docs] | the plan of each release and the reviews of the code |
| 🇬🇧 [User guide][guide] · 🇵🇱 [Przewodnik użytkownika][guide-pl] | prerequisites, installation, quick start, how it works, boiler connections, safety, alarms |
| 🇬🇧 [Technical documentation][technical] · 🇵🇱 [Dokumentacja techniczna][technical-pl] | the integration's parts, one control step, lifecycle, stored state, tests |
| [Water data for zone algorithms][water] | the interface that gives SmartPI and other zone algorithms the water reaching each zone |
| [`CHANGELOG.md`][changelog] | what each release changes |
| [`CONTRIBUTING.md`][contributing] | how to contribute: branches, tests, rules |
| [`LICENSE`][license] | Apache License 2.0 |

`main` holds these documents; the code under development lives on the [`dev`][dev] branch and
reaches `main` with the first release.

# Contributing

Contributions are welcome — open pull requests against `dev`. Read
[`CONTRIBUTING.md`][contributing] first: this integration controls a home's heating, so every
change is small, tested and reviewed. Which automatic checks run, and when, is in its section
[Checks](CONTRIBUTING.md#checks).

# ☕ Support

If Smart Boiler for Versatile Thermostat is useful to you, you can support its development here:

<a href="https://buymeacoffee.com/shadow23"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy me a coffee" height="50"></a>

# Authors

[@Shadow-230](https://github.com/Shadow-230)

# License

[Apache License 2.0][license].

[vt]: https://github.com/jmcollin78/versatile_thermostat
[dev]: https://github.com/Shadow-230/vtherm-smart-boiler/tree/dev
[scope]: SCOPE.md
[scope-defaults]: SCOPE.md#7-features-by-stage
[plan]: PLAN.md
[docs]: docs/
[guide]: documentation/en/user-guide.md
[guide-connect]: documentation/en/user-guide.md#5-connecting-the-boiler
[guide-hand-back]: documentation/en/user-guide.md#61-the-safe-hand-back
[guide-relay]: documentation/en/user-guide.md#54-the-relay-onoff-boiler
[guide-fresh]: documentation/en/user-guide.md#68-fresh-data
[guide-alarms]: documentation/en/user-guide.md#7-alarms-and-repair-issues
[guide-pl]: documentation/pl/user-guide.md
[technical]: documentation/en/technical.md
[technical-pl]: documentation/pl/technical.md
[water]: documentation/en/water-interface.md
[changelog]: CHANGELOG.md
[contributing]: CONTRIBUTING.md
[license]: LICENSE
[releases]: https://github.com/Shadow-230/vtherm-smart-boiler/releases
[commits]: https://github.com/Shadow-230/vtherm-smart-boiler/commits/dev
[status-shield]: https://img.shields.io/badge/status-in%20development-orange.svg?style=for-the-badge
[release-shield]: https://img.shields.io/badge/release-none%20yet-lightgrey.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/m/Shadow-230/vtherm-smart-boiler/dev.svg?style=for-the-badge
[license-shield]: https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-not%20yet-lightgrey.svg?style=for-the-badge
[bmc]: https://buymeacoffee.com/shadow23
[bmc-shield]: https://img.shields.io/badge/buy%20me%20a%20coffee-shadow23-ffdd00.svg?style=for-the-badge&logo=buymeacoffee&logoColor=black
