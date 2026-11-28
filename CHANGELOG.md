# Changelog

Every change that reaches a release is listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are `MAJOR.MINOR.PATCH`, with
`bN` for a pre-release (as `0.2.3b1`).

## [Unreleased] — the first pre-release, provisionally 0.2.3b1

Nothing has been released yet. The first pre-release holds the monitor (0.1) and the control base
(0.2), once the tests on a test Home Assistant and the review before a real boiler are done. Its
version is decided then.

### Added

**Monitor (read-only)**

- Burner metrics: heating starts per hour, the median burn, burner hours, short burns and the
  condensing share, with hot-water draws told apart.
- Degree-days and gas per degree-day — measured with a gas meter you map, else estimated — and the
  change in use against the day before, split into weather, hot water, settings and the rest.
- A verdict on whether control is worth enabling, after 7 days of data by default. Frequent
  short burns name a large boiler as a common cause, never "the main cause", and the boiler's
  lowest and highest output are shown against the house's design load.
- The building's heat loss with its range, taken from the fit with an allowance for days that
  follow each other (never narrower than ±15 %); the heating threshold found from the days once
  there are days on both sides of it; the energy signature with and without control compared
  with their ranges ("no difference shown" where they overlap).
- Gas per degree-day week by week, shown from 14 degree-days a week, with a band from the house's
  own day-to-day scatter; burns under 3 minutes counted beside those under 10; a check that gas
  classed as hot water does not follow the outdoor temperature, with a notice where it does.
- The past from the boiler's signals in the recorder; whether the boiler was called for heat from
  the helper VT's central boiler switches, its recorder history included, or a circuit run by
  other automation asking; the rooms' details from
  the plugin's own reads, kept 8 days in its own storage — nothing is read back from VT's
  thermostats in the recorder, so room details start from the installation.
- Signal health, and each feature active only with its data: the sensor **Features** says why
  one is not.
- Alarms and early warnings: water pressure low, high or falling; flue gas; frequent starts;
  unstable ignition; heating hysteresis drifting, fast or over weeks; low flow; a circuit's water
  too hot; an outdoor
  sensor stuck or deviating; a long burn without warming. Notifications as repair issues.
- A suggested lowest water temperature, never applied.
- Forecasts recorded from a weather entity, for later releases.

**Control (experimental, opt-in)**

- Switched on and off only by an administrator in the plugin's settings ("Control mode",
  "Control on"), as a feature in VT's, and by automations with the action
  `vtherm_smart_boiler.set_control`; a person calling the action is refused. The entity
  **Control (experimental)** shows whether control is on, with what blocks it; it switches
  nothing. After a restart control comes back as the user left it.
- The water temperature on a heating curve, bounded by the lowest and highest water temperature
  and each circuit's maximum; up to four circuits at the advanced level, among them circuits run
  by other automation and circuits behind a fixed valve. A circuit run by other automation holds
  the water at its need while it asks, nothing added; a fixed valve sets no lower bound — the
  boiler follows its curve, the valve standing open at or below its setting.
- Heating on and off as VT's central boiler decides: with its own thresholds and activation
  delay, it switches an on/off helper (`input_boolean`) that the plugin follows — "on" at once,
  "off" once it has lasted 30 seconds: VT turns the helper off for a few seconds between its
  cycles, as one room's valve closes just before another's opens, and following that stopped the
  burner for nothing. **Heat call** shows the plugin's call with the reason when it is off,
  **Calling for heat** the rooms that call, and an event follows each change of the call.
- Write paths: the OpenTherm Gateway (`opentherm_gw`, or its firmware over MQTT), ESPHome
  OpenTherm, EMS-ESP, another writable entity, and a relay for an on/off boiler; how the boiler is
  connected is the setup's first question. Control never writes through a cloud service.
- The curve reads the lower of the outdoor temperature now and its mean over 3 hours, over
  12 hours for a circuit with underfloor heating. The mean is kept through a restart and a change
  of settings; **Curve outdoor temperature** shows the value the curve uses, with the mean, the
  last reading, where it came from and the hours the mean covers. A fallback setpoint when no
  outdoor temperature is known.
- The comfort correction (off by default): it counts a room short only after it has been fully
  open and short for two of its cycles and an hour, rises at most 1 K per four cycles of the
  slowest room it reads, waits while a room warms back after its setpoint was raised, and trims
  the water below the curve — at most 3 K, slowly — while every room is well under open.
- A modulation cap, opt-in and off by default, on the paths that can set it: never below the
  boiler's minimum, released during hot water, at every hand-back and when it is switched off,
  lifted for 3 hours when the house is not getting enough heat.
- A room's temperature judges the curve only while it is trusted: not while VT runs it in safety
  mode, its thermometer is unavailable, or VT has not measured it since the plugin started. A
  room with its window open, or still warming back after it closes, is not the critical zone.
- **Gives no heat**: one binary sensor, on while a room calls for heat and the boiler gives none —
  VT's central boiler not calling, its activation delay, hot water, a boiler fault, or the plugin
  unable to vouch for heat — with the reason; off while no room calls, so a zone algorithm can
  learn from the rest. Pick it in SmartPI 1.0's "heating unavailable" setting, or use it in an
  automation.

**Versatile Thermostat through `vtherm_api`** (step I12)

- The plugin takes from VT only what `vtherm_api` gives. The rooms are the thermostats VT hands
  to the plugin and counts for its central boiler ("Used by central boiler" ticked in VT): the
  plugin keeps no list of rooms, and reads no state of VT's climates, none of the settings in
  VT's config entries, and no history of them. VT 10.6.5 is the oldest supported. At a first installation while VT runs, reload VT
  once; a repair issue reminds you.
- Set at least one of the thresholds of VT's central boiler above 0: both are 0 by default, and a
  threshold of 0 is off, so VT would never switch the helper. VT's central boiler counts as set up
  once it has both its commands. The control state tells VT's decision not known — its helper
  unknown or unavailable — apart from no room known.
- What stays VT's: when to heat and the activation delay, frost protection (VT's frost preset and
  central mode), and the zone algorithms' learning — the plugin pauses none and publishes nothing
  on VT's thermostats.
- An entry from an earlier test build moves over by itself: the plugin's own demand thresholds,
  activation delay, frost protection and learning pauses go with their settings. A repair notice
  lists the values that were set, to set them in VT, and a one-time warning says that frost
  protection is VT's alone.

**Safety**

- Every write read back; changes from outside sorted into lost commands, values ignored from the
  start, the boiler's own limit and another controller — never fought.
- The safe hand-back on every exit, read back and retried until confirmed: control switched off,
  an alarm, a lost boiler link, Home Assistant stopping, and after a restart without a clean stop.
- A boiler link lost again within an hour is taken back only after 10 minutes of fresh data, so a
  link that keeps dropping does not hand the boiler back and take it again every few minutes. A
  signal earns its freshness limit after four unchanged repeats, never shorter than twice its
  second-longest pause.
- Nothing written to the boiler's permanent memory: a target declared persistent, or of unknown
  type, is never written.
- Control refused where it could leave the house without heat: an on/off thermostat on the
  gateway's terminals, no heating switch, a relay not confirmed as a separate contact.
- Removing the integration hands the boiler back, and a repair issue stays if it cannot confirm
  it.

**The Boiler page (being built)**

- A page "Boiler" in Home Assistant's sidebar, for every user, in Home Assistant's language; the
  switch **Page in the sidebar** (on by default) takes it away and puts it back (the user guide,
  section 4.12). Its overview shows the status with its reasons, whether **Control** is on — with
  "Change in settings" for an administrator — and tiles for the water asked and confirmed, flow, return, outdoor, flame and
  how many rooms call for heat, as the plugin counts them, with a link to Versatile Thermostat's
  page for an administrator; and the schematic of the installation, drawn from the settings — the
  boiler, its tank or its own hot water, each circuit with its valve, pump and radiators or
  underfloor loop — with the water moving where it flows now, into the circuits whose rooms call,
  and the measured temperatures. The page reads nothing of VT and lists no rooms; and
  the heating curve as control decides the water, with "where we are" on it, the last 7 days'
  decisions and a preview of changes — drag the point at the hardest frost, shift the curve — that
  the plugin checks as the settings do, and that an administrator can save after confirming —
  through the plugin's own settings, their checks and their save; and the last 24 h from the
  recorder — the water the plugin asked, flow, return and the burns — whose scrubber and play show
  any moment of the day in every part of the page. A tab
  **Burner**: the burner's metrics, the monitor's own burns of the last 24 h, and how long the
  heating burns lasted, the short ones marked by the monitor's short-burn length. A tab **Use**:
  gas per degree-day and the degree-days, the last 12 weeks' gas per degree-day, and the change
  against yesterday cause by cause — weather, hot water, settings and the rest; a value not known
  says why. A tab **Status
  and alarms**: the control verdict with its reasons, every alarm with the active ones first, the
  signals' health, the building values with their source — an administrator forgets a measured
  one there, after confirming — and the suggested lowest water temperature with its evidence. A
  tab **Journal**: what the plugin decided and why over the last 14 days — its starts and stops,
  control taking the boiler and handing it back, the heat call, the water setpoint written, a
  circuit's need, the alarms and each settings save, from the page or the settings — as lanes
  that zoom by dragging and as a filtered list. The plugin keeps the journal in a store of its
  own, 14 days and 2,000 entries at most; it only watches and changes nothing. A tab
  **Analyses**: the energy signature — each day's heating gas against its mean outdoor
  temperature, the days only watched and the days under control apart, each with the line the
  plugin fits, and the two compared at the same temperature — and the burner's heating starts by
  hour over the last 4 weeks. Each daily summary now keeps its heating starts hour by hour; days
  kept before show without them.
- **Cards** for your own dashboards, in the card picker while the plugin runs: "Boiler: status"
  (the status, whether control is on and the tiles), "Boiler: schematic" (the installation and the
  circuits taking heat), "Boiler: heating curve" and "Boiler: last 24 h" — the page's own parts, with no
  settings, the same rules for changes.
- The control state's attribute **Curve's outdoor temperature**: the outdoor temperature the
  water was decided with, as the curve reads it; and **Calling for heat**'s **Circuits calling**,
  the circuits the rooms calling are on, kept in the recorder for the page's last 24 h.

### Requirements

- Home Assistant 2026.10.4 or later, tested on 2026.10.4 and 2026.11.3; Versatile Thermostat
  10.6.5 or later (it shows itself as 10.6.4 in Home Assistant); `vtherm_api` 0.9.0 or later.
- Translations: English and Polish.
