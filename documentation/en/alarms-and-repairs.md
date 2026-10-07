# Alarms and repairs

Versatile Thermostat Smart Boiler tells you about problems in two ways:

- **Alarms** are binary sensors of the integration's device. Most only inform. Only the few named
  in [Safety](safety.md) change control.
- **Repair issues** appear in Home Assistant (HA) under Settings → System → Repairs. Each says
  what happened and what to do, and closes by itself when its cause is gone.

An alarm whose input is unknown keeps its last state for 60 minutes, then shows "unknown". An
unknown value never raises an alarm. Some alarms exist only when the signals they need are
mapped. Abbreviations: Versatile Thermostat (VT), OpenTherm Gateway (OTGW).

The names below are the ones shown in Home Assistant in English.

## Boiler and water

Alarms from the monitor. They inform; the plugin keeps heating.

| Alarm | Meaning | What to do |
|---|---|---|
| Water pressure low | below the "add water" level you set | add water as the manual says |
| Water pressure high | above the limit you set | see the repair issue below |
| Water pressure falling | falling over days, water temperature allowed for | look for a leak |
| Flue gas too hot | above the limit you set | book a boiler service |
| Flue gas rising above return | flue gas hotter above the return than before | book a service |
| Frequent starts | more starts in the last hour than the limit | check the curve and limits |
| Unstable ignition | many burns lost soon after ignition in a day | have it checked |
| Heating hysteresis drifting | the boiler's on/off band drifts over time | have it checked |
| Low flow: all valves closed while the pump runs | no path for the water | check valves or bypass |
| Circuit water too hot | flow above the circuit's alarm temperature | check its maximum |

Repair issues:

| Repair issue | Meaning and what to do |
|---|---|
| Heating water pressure is low — add water | add water with the filling tap, watching the gauge |
| Heating water pressure is high | check the filling tap is closed; let water out only when cold |
| Heating water pressure keeps falling | risk of a leak: look for drips, or have it checked |
| Flue gas too hot | book a service: heat exchanger, flue, condensate pipe |
| The boiler reports a fault that stops it | heating is kept off until it clears; see the manual |
| The boiler keeps stopping at the lowest water temperature | consider raising that limit |
| The boiler keeps stopping at its lowest water temperature | the same, on the device's own curve |

For pressure, your alarm limit must be below the safety valve's rating, printed on the valve.

## Control

Control alarms are named "Control: …".

| Alarm | Meaning |
|---|---|
| Control: write failed | a write did not go through; it is sent again every step |
| Control: the boiler does not accept a command — check the settings | a value was never taken |
| Control: changed by another controller | something else wrote to the boiler |
| Control: hand-back failed | the hand-back has not been confirmed |
| Control: internal error | an error in the plugin stopped control |
| Control: comfort correction at its limit | at +3 K for 3 hours: the curve is likely too low |
| Control: the boiler's confirmation is missing | a setpoint not shown back for 5 minutes |
| Control: commands often lost | 3 lost commands within 24 hours (information) |
| Control: no sign the boiler heats | heating on for 30 minutes with no flame or rise |
| Control: the monitor keeps failing | the plugin's monitor failed for 5 minutes; handed back |

Repair issues about control:

| Repair issue | Meaning and what to do |
|---|---|
| Handing the boiler back has not got through | retried every minute; confirm by hand once done |
| After the hand-back another controller holds the boiler | counted as handed back |
| Control stepped aside: another controller writes to the boiler | switch control off and on |
| Control stepped aside: another controller switches the boiler | switch control off and on |
| Control stopped: the boiler does not take "heating off" | fix it, then switch off and on |
| Control stopped: the boiler does not take "heating on" | fix it, then switch off and on |
| Control handed back: the boiler ignores a value the plugin writes | your reaction setting |
| Control stays handed back after an earlier alarm | switch control off and on |
| Control stopped after an internal error | see the log; switch control off and on |
| Control stopped and the boiler does not heat | a blocker stopped control; heating is off |
| The boiler does not accept the command: the house is not heated | check the setpoint entity |
| The boiler does not show the plugin's water temperature | check the boiler's limits |
| No sign the boiler heats | check for a lockout, summer mode or gas |
| Control waits for the gateway's confirmation | the setpoint read-back has no value |
| The control options cannot be used | open the options and set control up again |
| Alarm reactions no longer offered | those alarms now only inform |

## Zones

| Alarm | Meaning |
|---|---|
| Control: a zone's state is unknown | unknown for 30 minutes; frost protection cannot see it |
| Control: frost heating does not warm the room | frost heating for 2 hours without warming |
| Control: handed back while a room is near freezing | frost protection rests on the boiler |
| Control: no zone answers | no zone known: nothing can ask for heat |
| Control: a demand criterion has no data | a calling zone feeds none of the criteria |

| Repair issue | Meaning and what to do |
|---|---|
| Versatile Thermostat gives no answer (3 variants) | check that VT runs, thermostats on |
| No demand criterion can be judged (3 variants) | set VT's device power, or another one |
| A room below the frost limit cannot get heat (5 variants) | VT keeps it closed; see text |
| A heating circuit has no rooms | add its rooms, or remove the circuit |
| Underfloor heating without a water limit | enter the circuit's maximum flow temperature |
| Auto-TPI cannot learn in some zones | clear "used by the central boiler" in VT |
| The plugin cannot pause learning in some zones | information |
| The plugin could not switch learning back on in some zones | switch SmartPI learning on |
| VT's thermostats cannot show the plugin's zone values | update VT; nothing else depends on it |
| Some VT thermostats need a reload to show the plugin's values | reload VT |

"3 variants": the boiler is not heating, or it is back on its thermostat, or the plugin only
monitors.

## Connection

When "Signals" is off, its attributes name the signal with the problem.

| Alarm | Meaning |
|---|---|
| Signals | on (connected) while flame and flow, or the relay, are known and fresh |
| Control: boiler link lost | flame or flow not fresh for 5 minutes within 10; handed back |
| Control: relay out of reach | the relay unavailable for 5 minutes; no hand-back |
| Outdoor sensor problem | the outdoor sensor is stuck or far from the weather entity |
| Control: outdoor sensor left out | control uses the weather entity or a fallback instead |

| Repair issue | Meaning and what to do |
|---|---|
| Control handed the boiler back: its data is lost | check the boiler interface |
| The relay cannot be reached | check the relay and its connection |
| The relay does not accept the command — check it | check the relay and the entity |
| The relay has stopped taking commands (two variants) | check it; "off" not taken blocks control |
| Control stepped aside: something else switches the relay | find what switches it |
| Control stepped aside: the relay switches itself off every few minutes | lengthen its timer |
| Control stopped: the relay does not take "off" / "on" | check it, then switch off and on |
| Control stopped: the relay stopped taking "off" | check it, then switch off and on |
| The relay keeps switching off a fixed time after "on" | declare its timer |
| The boiler does not heat while control is off | the relay rests off while rooms call |
| Say what is wired to the gateway's thermostat terminals | answer it in the control options |
| The wall thermostat would keep the house cool after a hand-back | raise its setting |
| The wall thermostat reports no setpoint | check its setting and the signal |
| An entity the plugin uses is gone | pick another one in the options |
| Versatile Thermostat's central configuration is not running | fix VT's central configuration |

## Monitor and the plugin itself

| Repair issue | Meaning and what to do |
|---|---|
| Control handed the boiler back: the plugin's monitor keeps failing | resumes by itself |
| The plugin's monitor failed for a while; control has resumed | report it if it recurs |
| The plugin did not start: the house is not heated | see the log; heat by other means |
| The plugin did not start: the house may not be heated | see the log; check the boiler |
| The plugin's memory of the boiler could not be read | it handed back to be safe |
| The plugin cannot save its memory of the boiler | full disk or read-only storage |
| The boiler may still hold a value from Versatile Thermostat Smart Boiler | hand back by hand |
| SmartPI's learning may still be off in some zones | switch SmartPI learning on |

The last two appear after the integration was removed before it could finish its cleanup.
