[Polska wersja](README.pl.md)

[![Status][status-shield]](#status)
[![Release][release-shield]][releases]
[![Commit activity on dev][commits-shield]][commits]
[![License][license-shield]][license]
[![HACS][hacs-shield]](#installation)
[![Buy me a coffee][bmc-shield]][bmc]

# Smart Boiler for Versatile Thermostat

<p align="center">
  <img src="docs/images/logo.png" alt="Smart Boiler for Versatile Thermostat logo" width="280" />
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
- **Heating on and off follow VT's zones** — by devices (or zones) calling, total power or valve
  opening, as VT's central boiler does — and VT's central modes act through the zones.
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

# Requirements

| Requirement | Version |
|---|---|
| Home Assistant | 2026.9 or later |
| Versatile Thermostat | 10.2.0 or later (it loads external feature managers from 10.2.0); 10.5.1 is the version tested — provisional until the first release |
| `vtherm_api` | 0.5.0 or later, installed with the plugin |
| SmartPI, Auto-TPI | optional; any VT zone algorithm works |

Any boiler whose signals Home Assistant shows as entities can be monitored. To control it, the
plugin writes through the OpenTherm Gateway (Home Assistant's `opentherm_gw` or its firmware over
MQTT), ESPHome OpenTherm, EMS-ESP, a relay for an on/off boiler, or another writable entity you
pick. Nothing is written that the boiler would store in its permanent memory. Tested so far
against a simulated boiler only. What each connection writes and what it does after a hand-back:
[user guide, section 5][guide-connect].

# Installation

There is **no release yet**. Once there is one, it installs through HACS as a custom repository,
or by hand: [user guide, section 2][guide-install]. Then the [quick start][guide-start] takes you
through the setup.

# Documentation

Everything a user needs is in the **user guide** — 🇬🇧 [User guide][guide] ·
🇵🇱 [Przewodnik użytkownika][guide-pl]:

| What you want to know | Where in the guide |
|---|---|
| What you need, how to install, the first setup | [1–3][guide] |
| How it works: the verdict, heating on and off, the water temperature, frost, circuits, the zone algorithms | [4][guide-how] |
| How the boiler is connected, and what a hand-back does on each connection | [5][guide-connect] |
| Safety: the hand-back, other controllers, a lost link, fresh data | [6][guide-safety] |
| What each alarm and repair issue means | [7][guide-alarms] |
| The entities | [9][guide-entities] |
| How often data updates, and what stays local | [10, 11][guide-updates] |
| The options and what each one risks | [12][guide-options] |
| Automation examples | [13][guide-automations] |
| Troubleshooting | [14][guide-troubleshooting] |
| Known limitations | [15][guide-limitations] |
| Removal | [16][guide-removal] |

The specification, the technical documentation, the plans and the test reports are listed in
the [documentation map][docs-map].

`main` holds these documents; the code under development lives on the [`dev`][dev] branch and
reaches `main` with the first release.

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
[`docs/en/development/plan.md`][plan].

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
[plan]: docs/en/development/plan.md
[contributing]: CONTRIBUTING.md
[license]: LICENSE
[releases]: https://github.com/Shadow-230/vtherm-smart-boiler/releases
[commits]: https://github.com/Shadow-230/vtherm-smart-boiler/commits/dev
[bmc]: https://buymeacoffee.com/shadow23
[guide]: docs/en/user-guide/user-guide.md
[guide-install]: docs/en/user-guide/user-guide.md#2-installation
[guide-start]: docs/en/user-guide/user-guide.md#3-quick-start
[guide-how]: docs/en/user-guide/user-guide.md#4-how-it-works
[guide-connect]: docs/en/user-guide/user-guide.md#5-connecting-the-boiler
[guide-safety]: docs/en/user-guide/user-guide.md#6-safety-and-hand-back
[guide-alarms]: docs/en/user-guide/user-guide.md#7-alarms-and-repair-issues
[guide-entities]: docs/en/user-guide/user-guide.md#9-entities
[guide-updates]: docs/en/user-guide/user-guide.md#10-how-often-data-updates
[guide-options]: docs/en/user-guide/user-guide.md#12-options-and-risks
[guide-automations]: docs/en/user-guide/user-guide.md#13-automation-examples
[guide-troubleshooting]: docs/en/user-guide/user-guide.md#14-troubleshooting
[guide-limitations]: docs/en/user-guide/user-guide.md#15-known-limitations
[guide-removal]: docs/en/user-guide/user-guide.md#16-removal
[guide-pl]: docs/pl/user-guide/user-guide.md
[docs-map]: docs/en/README.md
[status-shield]: https://img.shields.io/badge/status-in%20development-orange.svg?style=for-the-badge
[release-shield]: https://img.shields.io/badge/release-none%20yet-lightgrey.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/m/Shadow-230/vtherm-smart-boiler/dev.svg?style=for-the-badge
[license-shield]: https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-not%20yet-lightgrey.svg?style=for-the-badge
[bmc-shield]: https://img.shields.io/badge/buy%20me%20a%20coffee-shadow23-ffdd00.svg?style=for-the-badge&logo=buymeacoffee&logoColor=black
