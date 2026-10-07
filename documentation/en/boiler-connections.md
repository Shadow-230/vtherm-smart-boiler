# Boiler connections

Versatile Thermostat Smart Boiler reads the boiler through entities you pick in its forms. To
control the boiler it also needs a way to **write** to it — a "write path" — and a way to give
the boiler back to its own control — the **hand-back**. This page explains both.

Details: [`SCOPE.md`, §5](../../SCOPE.md#5-hardware-circuits-and-zone-algorithms) and
[Gateway topology](../../SCOPE.md#gateway-topology).

## The write paths

You choose one in the control options ("Write path"). The default is "No control": the plugin
only monitors.

- **Writable entity** — a boiler interface that offers writable entities, for example EMS-ESP
  or an ESPHome OpenTherm controller. The plugin writes the flow setpoint, and heating on and off
  through a switch.
- **OpenTherm Gateway (OTGW)**, through Home Assistant's `opentherm_gw` integration. The plugin
  writes the control setpoint and heating on and off through the gateway.
- **OTGW firmware over MQTT** (Message Queuing Telemetry Transport) — the same, sent as the
  firmware's MQTT commands.
- **Relay (on/off boiler)** — for a boiler with only room-thermostat terminals. Heating on and
  off only.

A heating on/off switch is **required** for water-temperature control in this version. Without
it, control stays blocked and the monitor runs.

### A writable entity

You pick the setpoint entity and the heating on/off switch, and declare how each keeps its
value ("Write type"):

| Write type | Meaning | What the plugin does |
|---|---|---|
| Expiring | the device drops the value unless it is repeated | repeats it every 30 seconds |
| Held by the device | the device keeps the last value | sends it on a change and every 5 minutes |
| Persistent | the value is stored in the boiler's memory | not written: control stays off |
| Unknown (default) | — | not written: control stays off |

You also pick the **hand-back method**:

- **Write a value** — a setpoint written on hand-back. You declare what it does: "Its own control
  resumes" or "Heating stops". The same number means different things on different devices, so
  there is no default.
- **Device timeout** — the device returns to its own control when the plugin stops writing. You
  enter the device's timeout (default 1 minute, 1 to 60).
- **Turn off a switch** — an "external control" switch that hands control back to the device.

### The OpenTherm Gateway

The plugin sends the control setpoint and repeats it every 30 seconds, as the gateway drops it
otherwise. "Heating off" is the gateway's heating-enable switched off, held, and sent again with
every repeat. The plugin never changes the gateway's mode.

## What hand-back means

On every exit — control switched off, an alarm set to hand back, Home Assistant stopping, a lost
boiler link, an error — the plugin hands the boiler back (see [Safety](safety.md)). What happens
next depends on your installation:

| Installation | After hand-back |
|---|---|
| Gateway with an OpenTherm thermostat | the thermostat takes over; heating continues |
| Gateway without a thermostat (stand-alone) | heating **stops** until control resumes or you act |
| Writable entity, value "Its own control resumes" | the boiler's own control heats |
| Writable entity, value "Heating stops" | heating **stops** until control resumes |
| Relay, "Relay after hand-back" = off (default) | no heat, unless a thermostat in parallel calls |
| Relay, "Relay after hand-back" = on | the boiler heats on its own dial or thermostat |

After a hand-back, or while Home Assistant is down, the boiler's (or the wall thermostat's) own
maximum water temperature applies, not the plugin's. Set an unmixed underfloor circuit's limit
there too.

The control switch shows what a hand-back does in your installation ("On hand-back").

## The gateway topology

You declare how the gateway is wired ("Gateway connection"); Home Assistant cannot read it.

| Gateway connection | What the plugin may do |
|---|---|
| Gateway with a thermostat | control; hand-back returns the boiler to the thermostat |
| Gateway without a thermostat (stand-alone) | control; hand-back stops heating |
| Gateway in monitor mode | monitor only |
| Virtual: a controller on the Home Assistant side | control through that controller's entities |

For a gateway, the form also asks **what is wired to the gateway's thermostat terminals**:

| Answer | Control |
|---|---|
| OpenTherm thermostat | allowed (with "Gateway with a thermostat") |
| Nothing | allowed (with stand-alone) |
| On/off contact (two wires) | **blocked**: monitor only |
| I don't know | **blocked** until you check |

Why an on/off contact blocks control: the gateway keeps the plugin's "heating off" even after the
override ends. If Home Assistant crashed while heating was off, an on/off thermostat on the
gateway could then not heat the house. An OpenTherm thermostat is not affected.

Things to know with a gateway:

- **Stand-alone:** if Home Assistant stops for more than about a minute, the setpoint lapses and
  the boiler stops heating. After a stand-alone hand-back, frost protection rests on the boiler's
  own, if it has one.
- **With a thermostat:** while the plugin controls, the wall thermostat's heating setting and its
  off switch do nothing (its hot-water settings still work). After a hand-back it heats by its own
  setting and program, so keep them at what the house should get. The plugin warns when the wall
  thermostat's setpoint is unknown or below 15 °C (if you map that signal).
- A VT zone built on the gateway's own thermostat entity is refused.

## The relay (on/off boiler)

The relay is a switch, or a boiler thermostat entity switched between heat and off. An
`input_boolean` (a Home Assistant helper) is refused, because it confirms nothing. The plugin
switches heating on and off only; it does not set a water temperature.

The plugin cannot read the relay's own settings, so the form asks you:

- the tick "this is a separate relay contact, not a setting stored in the boiler's memory" —
  control does not start without it;
- its state after a power cut, its own switch-off timer, and whether it reports its real state
  (each defaults to "I don't know", treated cautiously);
- the repeat interval (10 to 300 seconds, default 300);
- "Relay after hand-back": off (default) or on.

The form's texts recommend: the relay on the boiler's room-thermostat terminals, never in its
power supply; the old thermostat kept in parallel and set low; the relay starting "off" after a
power cut; one test in summer.

A relay out of reach raises an alarm after 5 minutes. There is no hand-back then, since nothing
could reach the relay; the command is sent again when it returns.

## The tick "The boiler has its own room controller"

Tick it only if the boiler has a room controller of its own that asks for heat by itself once the
plugin lets go — for example a room unit on the boiler's bus. It is off by default.

- On a writable entity: when VT gives no answer at all, the boiler is handed back to that
  controller, and every other hand-back goes to it too.
- On a relay: it counts only with "Relay after hand-back" = on.
- On a gateway it is not offered: the thermostat terminals answer decides.

Without the tick, when VT gives no answer the boiler does not heat, and an alarm and a repair
issue tell you why.

## Nothing goes to the boiler's permanent memory

The plugin writes only values that expire or that the device holds in working memory. A target
declared persistent, or of unknown type, is never written: control stays off and says why. Curve
parameters stored in the boiler are never written. The plugin also leaves the boiler's hot-water
enable as it was.
