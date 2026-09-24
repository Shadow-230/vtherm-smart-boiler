"""Boiler signals the user maps to entities, with their kind, plausible range and freshness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MINUTE = 60.0
HOUR = 3600.0


class SignalKind(StrEnum):
    """What a signal's value means."""

    BINARY = "binary"
    TEMPERATURE = "temperature"
    PERCENT = "percent"
    PRESSURE = "pressure"
    COUNTER = "counter"


class Signal(StrEnum):
    """A boiler-side signal; each one comes from an entity the user picks."""

    FLAME = "flame"
    FLOW = "flow"
    RETURN = "return"
    MODULATION = "modulation"
    CH_SETPOINT = "ch_setpoint"
    DHW_ACTIVE = "dhw_active"
    PRESSURE = "pressure"
    FLUE_GAS = "flue_gas"
    OUTDOOR = "outdoor"
    ROOM_SETPOINT = "room_setpoint"
    ROOM_TEMPERATURE = "room_temperature"
    CH_ACTIVE = "ch_active"
    PUMP_RUNNING = "pump_running"
    GAS_METER = "gas_meter"


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """Static facts about a signal.

    ``max_age_s`` is the default freshness limit: a value not reported for longer is stale.
    ``None`` means only availability counts — a flame that stays off for hours is normal.
    ``low`` and ``high`` bound a plausible value; anything outside is treated as unknown.
    """

    kind: SignalKind
    required: bool = False
    max_age_s: float | None = None
    low: float | None = None
    high: float | None = None

    def plausible(self, value: float) -> bool:
        """Whether a numeric value lies inside the plausible range."""
        if self.low is not None and value < self.low:
            return False
        return self.high is None or value <= self.high


SIGNAL_SPECS: dict[Signal, SignalSpec] = {
    Signal.FLAME: SignalSpec(SignalKind.BINARY, required=True),
    Signal.FLOW: SignalSpec(
        SignalKind.TEMPERATURE, required=True, max_age_s=30 * MINUTE, low=-20.0, high=110.0
    ),
    Signal.RETURN: SignalSpec(SignalKind.TEMPERATURE, max_age_s=30 * MINUTE, low=-20.0, high=110.0),
    Signal.MODULATION: SignalSpec(SignalKind.PERCENT, max_age_s=30 * MINUTE, low=0.0, high=100.0),
    Signal.CH_SETPOINT: SignalSpec(
        SignalKind.TEMPERATURE, max_age_s=30 * MINUTE, low=0.0, high=100.0
    ),
    Signal.DHW_ACTIVE: SignalSpec(SignalKind.BINARY),
    Signal.PRESSURE: SignalSpec(SignalKind.PRESSURE, max_age_s=6 * HOUR, low=0.0, high=6.0),
    Signal.FLUE_GAS: SignalSpec(
        SignalKind.TEMPERATURE, max_age_s=30 * MINUTE, low=-20.0, high=300.0
    ),
    Signal.OUTDOOR: SignalSpec(SignalKind.TEMPERATURE, max_age_s=2 * HOUR, low=-60.0, high=60.0),
    Signal.ROOM_SETPOINT: SignalSpec(
        SignalKind.TEMPERATURE, max_age_s=2 * HOUR, low=0.0, high=40.0
    ),
    Signal.ROOM_TEMPERATURE: SignalSpec(
        SignalKind.TEMPERATURE, max_age_s=2 * HOUR, low=-10.0, high=50.0
    ),
    Signal.CH_ACTIVE: SignalSpec(SignalKind.BINARY),
    Signal.PUMP_RUNNING: SignalSpec(SignalKind.BINARY),
    Signal.GAS_METER: SignalSpec(SignalKind.COUNTER, low=0.0),
}

REQUIRED_SIGNALS: frozenset[Signal] = frozenset(
    signal for signal, spec in SIGNAL_SPECS.items() if spec.required
)
