# Versatile Thermostat Smart Boiler — user documentation

> **In development, not released.** The integration has not yet run on a real boiler. There is
> no release and no entry in the Home Assistant Community Store (HACS). Do not install it on a
> heating system you rely on.

Versatile Thermostat Smart Boiler is a plugin for Versatile Thermostat (VT). It watches a gas
boiler and, once you switch control on, sets the boiler's water temperature from what VT's rooms
need. These pages explain what it does in plain words.

| File | What it holds |
|---|---|
| [How it works][how] | monitoring and verdict, heating on and off, water temperature, frost |
| [Boiler connections][conn] | how it writes to the boiler, "hand-back" on each, gateway wiring |
| [Safety][safety] | the safe hand-back, outside changes, lost link, faults, how control resumes |
| [Alarms and repairs][alarms] | every alarm and repair issue: what it means, what to do |

## Cautious defaults

Every option starts at its cautious value, and its text in the form says what it does and what
it risks. Control itself is off until you switch it on, and it cannot be switched on before the
monitoring period ends.

## The full specification

These pages are a summary. The specification, with every rule and decision, is
[`SCOPE.md`](../../SCOPE.md). Where the two differ, `SCOPE.md` and the texts in the
integration's own forms are the reference. Some values in the specification are still marked
"provisional": they may change before the first release.

[how]: how-it-works.md
[conn]: boiler-connections.md
[safety]: safety.md
[alarms]: alarms-and-repairs.md
