# Safety

Versatile Thermostat Smart Boiler controls a home's heating. This page explains how it hands
the boiler back, how it reacts when something else changes the boiler, and how control resumes
after it stopped. Abbreviations: Versatile Thermostat (VT), OpenTherm Gateway (OTGW), Home
Assistant (HA).

Details: [`SCOPE.md`, §5](../../SCOPE.md#5-hardware-circuits-and-zone-algorithms) (the safe
hand-back) and [§7](../../SCOPE.md#7-features-by-stage) (control base).

## The safe hand-back

The plugin hands the boiler back on **every exit**, for example:

- you switch control off, or remove or reload the integration;
- an alarm set to hand back;
- Home Assistant stopping;
- the boiler link lost for 5 minutes;
- the plugin's own monitor failing for 5 minutes;
- an internal error;
- the plugin stepping aside from another controller.

The hand-back has three parts, sent one after another at once, each tried whatever the others do:

1. the water set to the lowest water temperature;
2. heating switched on where a thermostat or the boiler's own control takes over;
3. the release: on a gateway the override is cleared; on an entity, the hand-back value, the
   external-control switch off, or the device's timeout.

A relay goes to its "Relay after hand-back" state instead.

A hand-back is **retried every minute until it is confirmed**, and the plugin remembers it
through restarts. While it is owed, a repair issue says so. If you return the boiler to its own
control by hand, you can confirm that in the repair issue and the plugin stops retrying.

What the boiler does after a hand-back depends on your installation: see
[Boiler connections](boiler-connections.md#what-hand-back-means).

## Changes seen from outside

Every write is read back. The plugin shows the value the boiler confirmed, or "unknown" — never
the value it asked for. When the read-back shows something the plugin did not write, it sorts it
into one of four kinds:

- **Lost command** — the boiler is back at its value from before, after an outage or a restart.
  The plugin sends the command again. After 3 within 24 hours, an information alarm.
- **Ignored from the start** — the boiler never takes the value in the first 3 tries of a
  session. The plugin stops sending that value for this session and tells you (see below).
- **Clipped** — always the same lower value, whatever is sent. The plugin accepts it as the
  boiler's own limit; information only.
- **Another controller** — a steady value the plugin did not write. The plugin writes its value
  back once; a second change within 24 hours makes it step aside.

**The plugin never fights another controller.** When it steps aside, it makes the full safe
hand-back and stays off (a "latch") until you switch control off and on. An optional "return
by itself" (off by default, not for relays) takes the boiler back after 60 minutes without a
foreign value.

If the boiler ignores the plugin's **"heating off" or "heating on"** from the start of a session,
control is blocked and the boiler handed back, with an alarm. It stays blocked until you fix the
cause and switch control off and on.

If the read-back shows another setpoint for 5 minutes, the alarm "the boiler's confirmation is
missing" and a repair issue appear. This alone never hands the boiler back.

## A lost boiler link

The plugin writes nothing without fresh data. When the flame or flow reading is not fresh for 5
minutes within the last 10, the link is lost:

- the alarm "Control: boiler link lost" appears and the plugin hands back;
- with a thermostat, the thermostat takes over; stand-alone, heating stops;
- control resumes by itself once the data has been fresh for 60 seconds without a break.

A failed outdoor sensor is not a lost link: the plugin uses a fallback setpoint, never zero heat.

## The boiler's own fault

You may map the boiler's own fault signals: its low-water-pressure fault, and another fault that
stops it. On an OTGW a fault counts only while the boiler's "Fault indication" is on as well, and
that signal must be mapped too.

While such a fault reads "on" for 5 minutes, the plugin keeps heating off — frost heating
included — with no hand-back and no latch. It heats again by itself as soon as every mapped fault
reads off (or unknown). Read the fault on the boiler and follow its manual.

Low, high or falling water pressure and hot flue gas only inform, with a notification that says
what to do. A broken pressure sensor never stops heating.

## No sign the boiler heats

A lockout, a panel set to summer or a gas fault may leave every read-back looking right. If
heating is on while a room calls, and for 30 minutes the flame stays off (or, without a flame
signal, the flow temperature does not rise by 5 K) while the water stays below the plugin's
setpoint, the plugin raises the alarm "Control: no sign the boiler heats" and a repair issue.
This never hands back: control goes on. Both clear at the first sign of heat, or when you switch
control off.

## A relay that stops taking commands

- **Out of reach** (unavailable for 5 minutes): an alarm and a repair issue; no hand-back; the
  command is sent again when the relay returns.
- **Never takes the command** in the first 3 tries: a repair issue. If it is the "off" or "on"
  that is not taken, control is blocked and the relay handed back.
- **Stops taking commands** during a session (about 15 minutes, three checks): a repair issue.
  If "off" is not taken, control is blocked — the boiler may keep heating — and the relay is
  handed back. If "on" is not taken, the house is not heated and the plugin keeps sending "on".
- **Switched by something else** (an automation, its button, a person): written back once; a
  second change within 24 hours makes the plugin step aside.

## How control resumes

| Why control stopped | Control resumes |
|---|---|
| An alarm set to hand back | when you switch control off and on (a latch) |
| Another controller (stepped aside) | off and on, or by itself where "return by itself" is on |
| "Heating off" or "on" ignored; a relay stops taking "off" | off and on, after fixing it |
| An internal error | when you switch control off and on |
| Any other value ignored from the start | at the next session |
| Boiler link lost | by itself, after 60 seconds of fresh data |
| Relay out of reach | by itself, when the relay returns |
| The boiler's own fault | by itself, when the fault clears |
| No zone answers | by itself, when a zone answers |
| The plugin's own monitor failing | by itself, when it works again |
| A blocker: a missing setting, the monitoring period, HA starting | by itself, once it is gone |

VT's central boiler still configured is a blocker too: control waits until you untick it in VT
and restart Home Assistant.

A latch survives a restart and is named in one repair issue. An alarm with a hand-back reaction
that is already active when you switch control on blocks control at once.
