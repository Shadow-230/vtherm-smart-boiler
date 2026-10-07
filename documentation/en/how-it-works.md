# How it works

Versatile Thermostat Smart Boiler is a plugin for Versatile Thermostat (VT), a Home Assistant
integration that runs the rooms of a house. VT decides how much heat each room needs. This plugin
decides when the boiler heats and how warm its water is. It does not control rooms or valves.

The details of every rule are in the specification:
[`SCOPE.md`, §7](../../SCOPE.md#7-features-by-stage) and
[§10](../../SCOPE.md#10-assess-before-control).

## 1. Monitoring first

After you add the integration, it only watches the boiler. It writes nothing. It records, for
example:

- burns and how long they last, and how often the boiler starts;
- how much of the time the boiler condenses (if you map the signals it needs);
- hot-water draws, and gas per degree-day (measured with a gas meter you map, else estimated);
- problems with the signals it reads.

The **monitoring period** is 7 days by default. You may make it longer (up to 60 days), but not
shorter. It counts calendar days from the day you created the entry.

At the end, the sensor **Control verdict** shows one of:

| Verdict | Meaning |
|---|---|
| Worth enabling | the plugin saw problems that its control changes, for example short burns |
| Not worth enabling | enough was measured, and control would change little |
| Not enough data yet | too little was measured to judge |

The verdict is advice. You decide. Outside the heating season the period may end without enough
data; the control switch then says that control starts without a verdict.

## 2. Control is opt-in

Control is **off by default**. It is the switch **Control (experimental)**. You can switch it on
only after the monitoring period, and only when every required setting is filled in, for example:

- a way to write to the boiler and a way to hand it back (see
  [Boiler connections](boiler-connections.md));
- the heating curve's design flow temperature (it has no default);
- exactly one heating circuit fed straight from the boiler (or through a fixed thermostatic
  mixing valve);
- VT's own central boiler switched off in VT, followed by a Home Assistant restart, so that two
  controllers never drive the same boiler.

When something is missing, the control switch says what. The monitor keeps running, and the
boiler stays with its own control or its thermostat.

## 3. When heating goes on and off

The plugin replaces VT's central boiler. It decides heating on or off from VT's zones, in the
same way VT's central boiler does. You choose one or more of these criteria:

| Criterion | Heating is on when |
|---|---|
| Zones calling | at least the set number of zones call for heat (default 1) |
| Total power | the zones' power together reaches the set threshold |
| Valve opening | the calling zones' valve opening reaches the set threshold |

- The decision is checked every 10 seconds and acts at once, in both directions.
- VT counts heating devices; this plugin counts **zones**. If you move over from VT's central
  boiler, check the number.
- A zone counts only while VT reports it clearly. A zone that is unavailable, or that VT has not
  started yet, is "unknown" — never "no demand".
- VT's central mode (Auto, Stopped, Heat only, Cool only, Frost protection) acts through the
  zones. With every zone stopped, nothing calls for heat, so the boiler stays off. "Stopped" in
  VT does not hand the boiler back; frost protection still watches.
- There is no summer switch in the plugin. If VT's zones are off, the boiler does not heat.

## 4. The water temperature

While heating is on, the plugin sets the boiler's water (flow) temperature:

1. **The heating curve** — you enter it: the design outdoor temperature (default −15 °C), the
   design flow temperature (required, no default), the curve's room temperature (default 20 °C)
   and an optional offset. The curve gives a water temperature for each outdoor temperature.
2. **Lowest water temperature** — the curve never goes below it. Default 20 °C (provisional).
   Too low, and the boiler may stop by itself again and again in mild weather; a boiler that does
   not condense may condense in its flue. Take the value from the boiler's manual. The monitor
   may suggest a higher value if it sees many short burns; nothing changes by itself.
3. **Highest water temperature** — never above it. Default 70 °C.
4. **Weather ceiling** (shown as "Room for correction") — how far anything may raise the water
   above the curve. Default 10 K (kelvin, a temperature difference).
5. **Circuit maximum** — each circuit's "Maximum flow temperature", for example for underfloor
   heating. The plugin never asks for more. The boiler itself may overshoot it a little; an
   optional alarm tells you when the measured flow stays too high.

The water temperature changes slowly (the ramp, default 1 K per minute). It is re-decided every
5 minutes by default (the decision interval).

If the outdoor temperature is lost, the plugin uses the weather entity, then keeps the last
known value for 3 hours, then uses your fallback setpoint or the curve's design point. A failed
outdoor sensor never means zero heat.

**Comfort correction** — **off by default**. When switched on, and a room stays short of its
setpoint with its valve fully open, the water may rise up to 3 K above the curve, slowly. It
does not rise when the boiler starts more often than before. Its text in the form explains the
risk with VT's TPI zones (more burner starts). Switch it on only where a room stays cold with its
valve open, and watch the starts. A "Reset comfort correction" button sets it back to zero.

## 5. Frost protection

Frost protection heats even when no zone calls for heat:

- It watches every zone (default) or one zone you pick.
- When a watched zone falls below **5 °C** (default), heating runs on the curve until every
  watched zone is above **7 °C** (default).
- It heats only a room whose heat can reach it: VT reports the valve open or the device on. If
  VT keeps a cold room closed (thermostat off, open window, central mode "Stopped"), the plugin
  does not start the boiler for it. It raises a repair issue that names the room and says what
  to do — for example, use VT's frost preset instead of "off".
- If frost heating runs for about 2 hours without the room warming, an alarm tells you. Heating
  is not stopped for that.

## 6. VT's activation delay

The plugin keeps VT's activation delay: 0 to 600 seconds, default 0. It is for slow valves
(for example thermoelectric heads on underfloor heating), so they open before the boiler and its
pump start.

- It delays **switching on** only. Switching off is never delayed.
- The wait starts at the first real call for heat. If the call drops and returns during the
  wait, the wait goes on; at its end the boiler starts only if demand is still there.
- Frost heating waits for it too.
- When you move over from VT, the value is pre-filled from VT's setting for you to confirm.

## 7. After a restart

**Recognition period.** After Home Assistant starts or VT reloads, the plugin waits until every
zone has reported, for at most 10 minutes. It takes no new decision meanwhile. If it was
controlling the boiler before the restart, and nothing has changed that forbids it, it keeps or
restores its last command at once (with no activation delay). If something has changed, it hands
the boiler back first.

**Grace period.** If a zone becomes unknown while VT runs, its last answer is kept for 10
minutes. After that it drops out and the other zones decide. A zone unknown for 30 minutes
raises an alarm, because frost protection cannot see it.

**No zone answers.** If every zone is unknown after these periods, or none of your demand
criteria gets any data, nothing can ask for heat:

| Your installation | What happens |
|---|---|
| A working thermostat or room controller (see below) | the boiler is handed back to it |
| No working thermostat | the plugin keeps heating off; it does **not** hand back |

In both cases an alarm ("Control: no zone answers") and a repair issue appear at once. Control
resumes by itself when a zone answers again.

A **working thermostat** is one of:

- an OpenTherm thermostat wired to the gateway's thermostat terminals;
- on an entity path, the tick "The boiler has its own room controller";
- on a relay, that tick together with the relay's state after hand-back set to "on".

**A thermostat VT has not started** counts as unknown, even after the recognition period. VT may
show such a thermostat as "off" until it starts. The plugin does not read that "off" as "no
demand".
