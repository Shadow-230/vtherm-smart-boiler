"""A wall thermostat on a gateway's thermostat terminals (X6; Z3 rule 9).

One setting with a day program — 21 °C from 06:00 to 22:00 and 17 °C otherwise, on the
simulator's clock (UTC); test-only values — which a person may change by hand until the next
program switch. It measures one room, the first zone's, and calls for heat with a switching
differential around its setting. It sends its demand to the gateway:

- an OpenTherm thermostat sends its own CH bit and water setpoint (the boiler's own curve while
  it calls, ``IDLE_WATER`` otherwise — assumed, a generic thermostat), and its room setpoint and
  room temperature; the gateway's ``CH=0`` does not mask its own CH bit once no override holds
  (PIC 6.6);
- an on/off contact only opens and closes: the gateway turns a closed contact into a demand at
  the boiler's maximum water temperature, and its ``CH=0`` masks it (PIC 6.6).

While a control setpoint is overridden at the gateway, nothing it sends reaches the boiler's
heating; once the override is released or has lapsed, it takes over at the next step — within a
minute.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .plant import Request

DAY_SETPOINT = 21.0
NIGHT_SETPOINT = 17.0
DAY_FROM_H = 6.0
DAY_TO_H = 22.0
DIFFERENTIAL_K = 0.5  # calls below the setting − 0.25 K, stops above it + 0.25 K (test-only)
IDLE_WATER = 10.0  # the water setpoint an OpenTherm thermostat sends while it does not call
HOUR = 3600.0
DAY = 86400.0


class WallKind(StrEnum):
    OPENTHERM = "opentherm"
    ON_OFF = "on_off"


def program(t: float) -> float:
    hour = (t % DAY) / HOUR
    return DAY_SETPOINT if DAY_FROM_H <= hour < DAY_TO_H else NIGHT_SETPOINT


def period(t: float) -> int:
    """The program period ``t`` falls in; a manual setting lasts until it ends."""
    hour = (t % DAY) / HOUR
    day = int(t // DAY)
    if hour < DAY_FROM_H:
        return 3 * day
    if hour < DAY_TO_H:
        return 3 * day + 1
    return 3 * day + 2


@dataclass
class WallThermostat:
    kind: WallKind
    zone: int = 0  # the room it measures: the first zone's
    manual: float | None = None
    manual_period: int | None = None
    calling: bool = False
    room: float | None = None  # the room temperature it measured last

    def setpoint(self, t: float) -> float:
        if self.manual is not None and self.manual_period == period(t):
            return self.manual
        self.manual = self.manual_period = None
        return program(t)

    def set_manual(self, t: float, value: float) -> None:
        """Its setting changed by hand: it holds until the next program switch."""
        self.manual = value
        self.manual_period = period(t)

    def update(self, t: float, room: float) -> None:
        self.room = room
        setting = self.setpoint(t)
        if room < setting - DIFFERENTIAL_K / 2.0:
            self.calling = True
        elif room > setting + DIFFERENTIAL_K / 2.0:
            self.calling = False

    def request(self, curve: float, maximum: float) -> Request:
        """What it asks of the boiler now; ``curve``: the boiler's own curve's water
        temperature, ``maximum``: the boiler's highest."""
        if self.kind is WallKind.OPENTHERM:
            water = curve if self.calling else IDLE_WATER
            return Request(self.calling, water, masked=False)
        return Request(self.calling, maximum if self.calling else 0.0, masked=True)
