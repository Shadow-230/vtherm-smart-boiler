# Smart Boiler's water data for zone algorithms — integration specification

[Polska wersja: dokumentacja techniczna, rozdział 8](../pl/technical.md#8-dane-o-wodzie-dla-algorytmów-stref)

Status: agreed with the owner on 2026-10-12; the requirements are closed. Smart Boiler's side is
built (step I9 of `docs/plan-0.2.md`, `docs/plan-0.2-i9.md`, 2026-10-12); a contract test
(`tests/test_water_interface.py`) pins every name and value below. Extended on 2026-10-14, at
SmartPI's request and with the owner's agreement, with whether the boiler is called for heat
(§4, §4.3) — an addition under §8.

The normative part (sections 1–10) says what Smart Boiler exposes, under which names, with which
values, what it reads from a zone algorithm and which service it calls. What a consumer does with
the data is the consumer's own specification; the owner's agreements about SmartPI's use are kept
in Annex A for context.

## 1. Purpose

A zone algorithm's room model assumes that a unit of command always brings the same heat. With a
weather-compensated boiler, a mixer, burner cycling or hot water with priority, that is false.
Smart Boiler knows the water each zone's circuit receives; it exposes it, so a zone algorithm can
account for it. The first consumer is SmartPI.

A zone may also call while the boiler is not fired at all: the demand criteria not met (too few
devices or zones calling, too little power), VT's activation delay running, the boiler's own
fault. Smart Boiler decides that, so it says it (`boiler_called`, §4.3) — apart from the burner's
own pauses, which `heat_available` follows.

## 2. Principles

- **Optional.** Smart Boiler works without any consumer, and a consumer without Smart Boiler. Any
  value missing means "no data", and a consumer then behaves as it would without the interface.
- **One direction.** Smart Boiler exposes what the water is now. A consumer never sets or asks
  for a water temperature: the water usually cannot be set per zone, and choosing it stays Smart
  Boiler's (its curve, circuits and critical zone).
- **Single source.** Every boiler-side sensor is mapped in Smart Boiler, which passes the data on
  in every control mode, monitoring only included.
- **One heat source per VT thermostat.** VT runs one control per zone: underfloor heating and
  radiators are separate VT thermostats, possibly with a master zone over both.
- **No version number.** A consumer detects what exists (a property, a key, a function); changes
  only add; a change of meaning gets a new name, the old one kept for a transition. A contract
  test in Smart Boiler pins every name, type and allowed value of this specification, so nothing
  changes without a failing check.

## 3. Where the data is

### 3.1 The feature manager

Smart Boiler registers a VT feature manager named `vtherm_smart_boiler` on each VT thermostat. It
has the fields of section 4 as read-only properties. A consumer reaches it through
`thermostat.get_feature_manager("vtherm_smart_boiler")` where VT offers that method (VT
10.5.0.beta1 and later). VT gives a thermostat its managers when the thermostat starts, so one
that started before Smart Boiler registered has none until VT's next reload.

### 3.2 The public API

While Smart Boiler runs, `hass.data["vtherm_smart_boiler_api"]` holds an object with named
functions; it is removed when Smart Boiler stops. Today it has one:

- `zone_water(entity_id: str) -> Mapping[str, Any] | None` — for a VT climate's entity ID, a
  read-only mapping with the fields of section 4; `None` when the thermostat is not one of Smart
  Boiler's zones, or its data cannot be read.

It works with every VT version Smart Boiler supports (10.2.0 and later; 10.5.1 tested) and before
VT's reload. A consumer imports nothing of Smart Boiler's; it checks that the key and the
function exist. A later addition is a new function on the same object. Smart Boiler's other keys
in `hass.data` are internal and not part of this interface.

### 3.3 The attribute on VT's thermostat

The `smart_boiler` attribute on each VT climate Smart Boiler serves is a mapping:

| Key | Type | Value | Published |
|---|---|---|---|
| `heat_available` | `bool \| None` | as in section 4 | on every change |
| `supply_temperature` | `int \| None`, °C | section 4's value rounded to 1 °C | on a change of at least 1 K, or to or from `None` |

For display only: VT records its thermostats' attributes, so the attribute changes rarely. A
consumer reads the live values (3.1, 3.2).

### 3.4 What Smart Boiler reads from a consumer

Smart Boiler reads, per VT thermostat, a key the consumer writes into the thermostat's
`specific_states` (VT does not record that part of its attributes). Its presence means "this
thermostat's algorithm uses the water data". The key's name is set by the consumer's
specification; for SmartPI the proposal is `water_factor`. Smart Boiler reads it as it reads VT's
other zone data.

### 3.5 Which service Smart Boiler calls

Smart Boiler pauses and resumes SmartPI's learning through
`vtherm_smartpi.set_smartpi_learning` (`entity_id`, `learning_enabled`), on conditions it
defines:

| Condition | Paused |
|---|---|
| Hot water with priority runs (a tank charged through a three-way valve, a combi boiler) | the zones calling for heat (valve open); a zone not calling keeps learning how it cools |
| The boiler's own fault, for which control switches heating off | the zones calling for heat |
| A large swing of the water temperature the plugin causes | only thermostats without the key of 3.4: for one with it, the water data explain the swing |

Resuming, the read-back of the learning flag and the one-hour cap work as today (`SCOPE.md` §5).

## 4. The fields

Per VT thermostat that is one of Smart Boiler's zones.

| Field | Type, unit | Values | `None` when | Purpose |
|---|---|---|---|---|
| `supply_temperature` | `float`, °C | the water reaching this thermostat's circuit, as measured: not rounded, not averaged; −20 to 110 °C (a reading outside is unknown) | not known; the reason is `supply_reason` | how warm the water in the zone's emitters is |
| `supply_reason` | `str` | one of 4.1 | `supply_temperature` is known | why the water is not known, and whether lastingly |
| `supply_measured_at` | `datetime`, UTC | when the underlying reading was taken | `supply_temperature` is `None` | information only: a source that reports only on a change keeps an old time while its value is right (section 6) |
| `heat_available` | `bool` | `True`: the flame burns (where a flame signal is mapped) and the supply is more than 2 K above the return — more than 3 K above the room where no return is known; once `True`, it stays so down to 1 K and 2 K (hysteresis). `False`: the flame is out, hot water with priority takes the heat, or the supply is not above the return or the room by that | it cannot be told | whether heat reaches the zone now — it follows the burner, so it changes every burner cycle |
| `heat_reason` | `str` | one of 4.2 | `heat_available` is `True` | why heat does not reach the zone, or why it cannot be told |
| `boiler_called` | `bool` | `True`: Smart Boiler asks the boiler for space heating now, frost protection included. `False`: it does not, while it controls the boiler | Smart Boiler does not control the boiler now, or cannot tell yet | whether heat is asked of the boiler, apart from the burner's own cycling |
| `call_reason` | `str` | one of 4.3 | `boiler_called` is `True` | why the boiler is not called, or why it cannot be told |
| `demand_count` | `int` | the devices — or zones, as `count_by` says — calling now | no zone is known | diagnostics: the demand against its threshold |
| `count_threshold` | `int` | the count that starts the boiler | the count criterion is off (0) | diagnostics |
| `count_by` | `str` | `devices` (VT's heads, valves and switches, as VT's central boiler counts them) or `zones` | the count criterion is off | diagnostics |
| `demand_power_kw` | `float`, kW | the zones' mean power over their cycles, summed, as VT's central boiler shows it; it counts toward its threshold only while a calling zone's valve is open or its device on | no zone gives a power | diagnostics |
| `power_threshold_kw` | `float`, kW | the power that starts the boiler | the power criterion is not set | diagnostics |
| `demand_opening` | `float`, 0 to 1 | the widest opening among the calling zones — a valve's opening, else the zone's duty cycle | no calling zone publishes one | diagnostics |
| `opening_threshold` | `float`, 0 to 1 | the opening that starts the boiler | the opening criterion is not set | diagnostics |

`boiler_called`, `call_reason` and the demand fields are the installation's: the same for each of
its zones. `True` means Smart Boiler commands heating, not proof that the boiler obeys (a write
ignored or a relay not confirmed has its own alarm); a burner pause or hot water with priority
stay in `heat_available` / `heat_reason`.

Which water is "the water reaching this thermostat's circuit":

- the circuit's own flow sensor, where one is mapped and its reading is fresh;
- otherwise, for a circuit fed straight from the boiler, the boiler's flow;
- for a passive circuit behind a fixed valve, the lower of the boiler's flow and the valve's
  declared temperature;
- for a mixed circuit (its own mixer, another automation, or through the boiler) without its own
  sensor: not known (`circuit_not_measured`).

### 4.1 `supply_reason`

| Value | Meaning | Lasting? |
|---|---|---|
| `not_mapped` | no water sensor is mapped for this circuit: no boiler flow, and no circuit sensor | lasting — until the configuration changes |
| `circuit_not_measured` | a mixed circuit without its own sensor: the boiler's flow says nothing about it | lasting |
| `several_circuits` | the thermostat's devices are in more than one circuit, and their waters differ or one is unknown (a fallback: section 2 expects one source per thermostat); circuits with the same water give it | lasting |
| `flow_unknown` | the sensor is mapped but reads nothing usable now: unavailable, unknown, not a number, or outside −20 to 110 °C | momentary |
| `flow_stale` | the sensor's last reading is older than its age limit (section 6) | momentary |

### 4.2 `heat_reason`

| Value | Meaning |
|---|---|
| `dhw_active` | hot water with priority takes the boiler's heat; never on a boiler without hot water or without priority |
| `flame_off` | the flame is out |
| `flame_unknown` | a mapped flame signal is unknown or stale |
| `flow_near_return` | the supply is not clearly above the return |
| `flow_near_room` | no return known: the supply is not clearly above the room |
| `flow_unknown`, `flow_stale`, `circuit_not_measured` | the water is not known now — as in 4.1 |
| `not_mapped` | no water sensor for this circuit — as in 4.1 |
| `room_unknown` | neither a return nor the room's temperature is known to judge against |

### 4.3 `call_reason`

| Value | Meaning | `boiler_called` |
|---|---|---|
| `below_threshold` | zones call, but the demand criteria (count, power, opening) are not met | `False` |
| `no_demand` | nothing calls — no zone, and no circuit run by other automation | `False` |
| `activation_delay` | the criteria are met; the start waits for VT's activation delay | `False` |
| `boiler_fault` | the boiler reports its own fault; control keeps heating off | `False` |
| `not_controlling` | Smart Boiler does not control the boiler now: control off, not allowed, handed back, monitoring only | `None` |
| `waiting_data` | Smart Boiler controls but cannot tell yet: the boiler link stale, the read-back unknown, the recognition period after a start holding "off", every zone unknown | `None` |

When several apply: `boiler_fault`, then `activation_delay`, then `below_threshold`, then
`no_demand`. Heating, frost protection and the fallback setpoint (heating without an outdoor
temperature) are called, as is the heating command the recognition period holds. The on/off path
(a relay) has the same states.

## 5. When values are missing

### 5.1 By what is mapped (normative)

In every row, `heat_available` is `False` with `dhw_active` while hot water with priority runs,
and with `flame_off` while a mapped flame signal says the flame is out (section 4); the table
shows the rest.

| Situation | `supply_temperature` | `heat_available` |
|---|---|---|
| No water sensor for the circuit (no boiler flow, no circuit sensor) | `None`, `not_mapped` | `None`, `not_mapped` |
| Sensor mapped, unavailable or implausible now | `None`, `flow_unknown` | `None`, `flow_unknown` |
| Sensor mapped, reading past its age limit | `None`, `flow_stale` | `None`, `flow_stale` |
| Mixed circuit without its own sensor | `None`, `circuit_not_measured` | `None`, `circuit_not_measured` |
| No flame signal mapped | as above | judged by the water alone (no `flame_*` reasons) |
| Flame signal mapped but unknown or stale | as above | `None`, `flame_unknown` |
| No return mapped (or a mixed circuit, whose water does not return to the boiler) | as above | judged against the room |
| No return and the room's temperature unknown | as above | `None`, `room_unknown` |
| Hot-water signal not mapped, or unknown | as above | not blocked: only a known draw gives `dhw_active` |
| Boiler without hot water, or hot water without priority | as above | never `dhw_active` |
| The thermostat is not one of Smart Boiler's zones (in no circuit) | no data: `zone_water` gives `None`, the manager's properties `None` | no data |
| Smart Boiler not running, starting or reloading | no data: no API key, or `None` | no data |

The call (§4.3) does not depend on what is mapped: it follows control. Without control
(monitoring only), or while control stops, `boiler_called` is `None` with `not_controlling`, and
the demand fields are `None`.

### 5.2 By installation (examples, not normative)

What a consumer gets follows from what is mapped (5.1), not from the connection. Typically:

| Installation | What it usually gives |
|---|---|
| OpenTherm Gateway, ESPHome OpenTherm, EMS-ESP | boiler flow, return, flame, hot water active: every field |
| An on/off boiler on a relay | nothing, unless a pipe sensor is mapped as the flow; a flame or hot-water signal only where the boiler exposes one. The relay's own state is not the flame |
| The boiler's Wi-Fi module, a manufacturer's integration | what that integration shows, often polled every one to several minutes and rounded; the automatic age limits follow its rhythm |
| Another read-only integration | what it shows |
| Monitoring only (any connection) | the same as with control: the data does not depend on control |
| A circuit with its own mixer and a sensor after it | that sensor's water |

## 6. Freshness and updates

- Smart Boiler judges each signal's freshness by its own age limit (automatic by default: none
  until the source repeats an unchanged value twice, then five times its rhythm, 10 to 30 min;
  settable per signal). Past it, `flow_stale`.
- A consumer trusts `None` and its reason. It applies no age limit of its own to
  `supply_measured_at`: MQTT and ESPHome sources report only on a change and keep an old time
  while their value is right.
- The values are recomputed at every Smart Boiler update — at each change of a signal it reads,
  and at least every 30 s — and read live; no throttling. The call and the demand (§4.3) follow
  control's step, every 10 s, and are read live.

## 7. Units and formats

- Temperatures in °C, whatever the sensor's unit (Smart Boiler converts; a sensor without a unit
  is taken as °C), also on a Home Assistant in °F.
- Times as timezone-aware UTC `datetime`.
- Power in kW; openings as fractions from 0 to 1.
- Reasons as the strings of 4.1, 4.2 and 4.3.

## 8. Changes

- Only additions: a new field, a new reason value, a new API function.
- A consumer must take an unknown reason value as "no data" for that moment.
- A change of meaning gets a new name; the old name stays until consumers have moved.
- The contract test (section 2) fails on any change to a name, a type or an allowed value; that
  failure is the reminder to update this specification and to tell the consumers.

## 9. Not in the interface

A consumer publishes no water temperature it would need, and Smart Boiler takes none: it would
need a large rebuild, and the water usually cannot be set per zone. Smart Boiler reads from a
consumer only the key of 3.4.

## 10. Built

Smart Boiler's side: step I9 (2026-10-12) — the fields (with the reasons `not_mapped` and
`several_circuits`), the manager's properties (3.1), the API (3.2), the attribute (3.3), the read
of the consumer's key (3.4), the pause conditions (3.5) and the contract test (section 2).
2026-10-14: the boiler's call and the demand against its thresholds (§4, §4.3), at SmartPI's
request (SmartPI's `specs/2026-10-14-smart-boiler-boiler-call.md`), with the reason
`below_threshold` and the corrected mapping agreed then; no learning pause added for it (3.5
unchanged). The consumer's side is the consumer's: for SmartPI, Annex A.

## Annex A — SmartPI's use (agreed on 2026-10-12; belongs to SmartPI's own specification)

Kept here until SmartPI's specification holds it; informative for Smart Boiler.

1. **Heating type.** Each SmartPI thermostat has a heating type: water radiator, water floor,
   electric mat, fast electric. A water type gives the emitter exponent `n` and a reference water
   `T_ref`; provisional values: radiator 1.3 and 60 °C, floor 1.1 and 45 °C. Electric types
   ignore the water data.
2. **The emitter power factor.** `φ = (max(T_supply − T_room, 0) / (T_ref − 20)) ** n`, with the
   supply averaged over about 15 minutes, as burner cycling makes the raw value jump.
3. **Use.** Demand as power at the reference water; the command to the emitter is that power
   divided by `φ`, before the valve curve; learning uses command × `φ`; the zone model and its
   brake use the same factor.
4. **The cooling is always learned.** No learning gate of SmartPI's own: an input of command ×
   `φ` = 0 (burner off, hot water, closed valve) teaches the losses. Pauses come only from Smart
   Boiler (3.5).
5. **Hot water with priority.** While `heat_reason` is `dhw_active`, `φ = 0` for the thermostat's
   circuit: the boiler's flow then shows the water heating the tank. The integral does not grow
   and the command is held.
6. **No heat otherwise.** With `φ` near 0, the integral does not grow (anti-windup).
7. **Missing data.** A momentary reason (4.1): the factor's long-term average, so the learned model
   keeps its units. A lasting reason, or no data since start: `φ = 1`, as without the interface.
8. **Data appearing or disappearing for good** (a lasting reason appears or goes): the learned
   model's units change; SmartPI rescales the learned power by the average factor, or offers its
   model reset.
9. **The key of 3.4.** SmartPI writes `water_factor` (the factor it applies, or `None`) into
   `specific_states` for each thermostat of a water type that uses the data.
10. **The boiler's call** (requested 2026-10-14). While `boiler_called` is `False` and the zone's
    command is above 0, and for a settling time after each change, SmartPI pauses its learning
    of the zone's model and dead times and freezes its feed-forward trim; its regulation is
    unchanged. `None`: not known from Smart Boiler — SmartPI then reads VT's central boiler
    where VT counts the thermostat for it, else behaves as before. Smart Boiler adds no pause
    for this case.
