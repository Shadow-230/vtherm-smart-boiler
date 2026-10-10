"""Heating curve and effective outdoor temperature (flow-setpoint mode).

The curve gives the flow temperature an emitter needs at an outdoor temperature. It passes
through the room temperature (no heat needed) and the design point (design outdoor temperature,
design flow), bent by the emitter exponent: the heat an emitter gives grows with the water's
excess over the room to the power ``n``, and the house's need grows linearly with
``room − outdoor``, so the excess needed grows with that difference to the power ``1/n``.

The effective outdoor temperature is the lower of the current value and a moving average: a
sudden cold snap is followed at once, a quick warm-up only slowly — the cautious side.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

HOUR = 3600.0
# The curve step's own checks (X5.8, P-68; provisional, K4): the design flow at least this far
# above the curve's room temperature, the design outdoor temperature at least this far below it.
DESIGN_FLOW_OVER_ROOM_K = 5.0
DESIGN_OUTDOOR_UNDER_ROOM_K = 10.0
ROOM_BOUNDS = (15.0, 25.0)  # the curve's room temperature as the form takes it
AUTO_ROOM_MAX = 23.0  # Auto follows the warmest room no higher than this (G11 D; provisional, K4)


@dataclass(frozen=True, slots=True)
class HeatingCurve:
    """Flow temperature as a function of the effective outdoor temperature (°C)."""

    design_outdoor: float = -15.0
    design_flow: float = 55.0
    room: float = 20.0
    exponent: float = 1.3
    offset: float = 0.0  # parallel shift, K

    def __post_init__(self) -> None:
        if self.design_outdoor >= self.room:
            raise ValueError("the design outdoor temperature must be below the room temperature")
        if self.design_flow <= self.room:
            raise ValueError("the design flow temperature must be above the room temperature")
        if self.exponent <= 0:
            raise ValueError("the emitter exponent must be positive")

    def flow(self, outdoor: float) -> float:
        """Flow temperature needed at ``outdoor``; the room temperature (plus offset) above it."""
        span = self.room - self.design_outdoor
        load = max(0.0, (self.room - outdoor) / span)
        excess = (self.design_flow - self.room) * math.pow(load, 1.0 / self.exponent)
        return self.room + excess + self.offset


def auto_room(targets: Iterable[float], curve: HeatingCurve, previous: float | None) -> float:
    """The curve's room temperature in Auto (G11 D): the highest of ``targets`` — the setpoints
    of the zones that heat, as the caller picks them — at most ``AUTO_ROOM_MAX``; with none, the
    last Auto value (``previous``), else the curve's own, the manual value. Always where the
    curve step's checks hold — at least the design outdoor temperature + 10 K and the room
    bounds, at most the design flow − 5 K — so the curve it builds is valid."""
    found = list(targets)
    held = curve.room if previous is None else previous
    room = min(max(found), AUTO_ROOM_MAX) if found else held
    low = max(ROOM_BOUNDS[0], curve.design_outdoor + DESIGN_OUTDOOR_UNDER_ROOM_K)
    high = min(ROOM_BOUNDS[1], curve.design_flow - DESIGN_FLOW_OVER_ROOM_K)
    return min(max(room, low), high)


class OutdoorSource(StrEnum):
    SENSOR = "sensor"  # the boiler's outdoor sensor
    WEATHER = "weather"  # the weather entity
    HELD = "held"  # the last effective value, for a while
    NONE = "none"  # nothing usable: the fallback setpoint applies


@dataclass(frozen=True, slots=True)
class OutdoorState:
    """Moving average of the outdoor temperature and the last effective value."""

    average: float | None = None
    effective: float | None = None
    source: OutdoorSource = OutdoorSource.NONE
    updated_at: float | None = None  # when a real reading last came in


DEFAULT_TIME_CONSTANT_S = 3 * HOUR
DEFAULT_HOLD_S = 3 * HOUR  # the last effective value stands in this long, then the fallback


def update_outdoor(
    previous: OutdoorState,
    sensor: float | None,
    weather: float | None,
    now: float,
    time_constant_s: float = DEFAULT_TIME_CONSTANT_S,
    hold_s: float = DEFAULT_HOLD_S,
) -> OutdoorState:
    """The effective outdoor temperature from fresh readings (``None`` = missing or stale).

    The sensor wins over the weather entity. Without either, the last effective value holds
    for ``hold_s``; after that the state says there is nothing usable.
    """
    if sensor is not None:
        current, source = sensor, OutdoorSource.SENSOR
    elif weather is not None:
        current, source = weather, OutdoorSource.WEATHER
    else:
        # A reading "later than now" (the wall clock set back) counts from now (PB-28).
        since = None if previous.updated_at is None else min(previous.updated_at, now)
        if previous.effective is not None and since is not None and now - since <= hold_s:
            return OutdoorState(previous.average, previous.effective, OutdoorSource.HELD, since)
        return OutdoorState(previous.average, None, OutdoorSource.NONE, since)
    if previous.average is None or previous.updated_at is None:
        average = current
    else:
        elapsed = max(0.0, now - previous.updated_at)
        weight = 1.0 - math.exp(-elapsed / time_constant_s) if time_constant_s > 0 else 1.0
        average = previous.average + weight * (current - previous.average)
    return OutdoorState(average, min(current, average), source, now)
