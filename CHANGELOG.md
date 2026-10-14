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
- A verdict on whether control is worth enabling, after 7 days of data by default.
- Signal health, and each feature active only with its data: the sensor **Features** says why
  one is not.
- Alarms and early warnings: water pressure low, high or falling; flue gas; frequent starts;
  unstable ignition; heating hysteresis drifting; low flow; a circuit's water too hot; an outdoor
  sensor stuck or deviating; a long burn without warming. Notifications as repair issues.
- A suggested lowest water temperature, never applied.
- Forecasts recorded from a weather entity, for later releases.

**Control (experimental, opt-in)**

- The water temperature on a heating curve, bounded by the lowest and highest water temperature
  and each circuit's maximum; up to four circuits at the advanced level, among them circuits run
  by other automation and circuits behind a fixed valve. A circuit run by other automation holds
  the water at its need while it asks, nothing added; a fixed valve sets no lower bound — the
  boiler follows its curve, the valve standing open at or below its setting.
- Heating on and off following VT's zones — devices calling as VT counts them (or zones), total
  power or valve opening — and VT's central modes; VT's activation delay. What VT's central
  boiler showed: **Heat call** with the reason it is not, the devices calling and their
  power against the thresholds, and an event when the call changes.
- Write paths: the OpenTherm Gateway (`opentherm_gw`, or its firmware over MQTT), ESPHome
  OpenTherm, EMS-ESP, another writable entity, and a relay for an on/off boiler; how the boiler is
  connected is the setup's first question.
- Frost protection; a fallback setpoint when no outdoor temperature is known; the comfort
  correction; SmartPI's learning paused while hot water or large swings disturb the rooms.
- On each VT thermostat the plugin serves, the attribute `smart_boiler`: `heat_available` and
  the water reaching the zone, rounded.
- The water data for zone algorithms (`docs/en/specification/water-interface.md`): per VT thermostat,
  the water reaching its circuit, why it is missing (lasting or momentary), when it was measured,
  and whether heat reaches the zone — through the feature manager and a function in
  `hass.data`. A zone algorithm that uses it says so, and is then not paused for water swings.

**Safety**

- Every write read back; changes from outside sorted into lost commands, values ignored from the
  start, the boiler's own limit and another controller — never fought.
- The safe hand-back on every exit, read back and retried until confirmed: control switched off,
  an alarm, a lost boiler link, Home Assistant stopping, and after a restart without a clean stop.
- Nothing written to the boiler's permanent memory: a target declared persistent, or of unknown
  type, is never written.
- Control refused where it could leave the house without heat: an on/off thermostat on the
  gateway's terminals, no heating switch, a relay not confirmed as a separate contact.
- Removing the integration hands the boiler back, and a repair issue stays if it cannot confirm
  it.

### Requirements

- Home Assistant 2026.9 or later; Versatile Thermostat 10.2.0 or later (10.5.1 tested; 10.5 or
  later for zones whose valve may not close fully); `vtherm_api` 0.5.0 or later.
- Translations: English and Polish.
