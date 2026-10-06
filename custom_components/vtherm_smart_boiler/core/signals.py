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
    POWER = "power"  # W


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
    # The boiler's electric power, e.g. from a plug that measures it: only a relay's proof that
    # the boiler heats (X8).
    BOILER_POWER = "boiler_power"
    # Boiler protection (Y1): the boiler's own low-water-pressure fault, and another fault the
    # boiler reports as stopping it (a lockout) — each optional, a binary sensor the user picks;
    # while either reads a known "on" for five minutes, control sends its usual "off". The
    # boiler's general fault indication gates both where they come from the OpenTherm Gateway,
    # which reads the fault details once per new fault and never after it clears (Q3.9).
    LOW_PRESSURE_FAULT = "low_pressure_fault"
    BOILER_LOCKOUT = "boiler_lockout"
    FAULT_INDICATION = "fault_indication"


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """Static facts about a signal.

    ``low`` and ``high`` bound a plausible value; anything outside is treated as unknown. There is
    no age limit here: one freshness rule serves the monitor and control — a value is fresh while
    its entity is available and, if the user set an age limit for it, reported within it. A
    steady reading is not a stale one; many sources report only on change.

    ``link``: the signal is part of the boiler link — the connection sensor, and the link of
    water-temperature control, which needs it mapped (X8: no signal is required for the entry;
    a home with only a relay is monitored too).

    ``gateway_zero_unknown``: from an OpenTherm Gateway a 0 is unknown — it shows 0 after a
    reset until a real reading, and for good where the boiler never answers the ID (P-17,
    PB-21). Measured values only; a setpoint's 0 is a value.
    """

    kind: SignalKind
    link: bool = False
    low: float | None = None
    high: float | None = None
    gateway_zero_unknown: bool = False

    def plausible(self, value: float) -> bool:
        """Whether a numeric value lies inside the plausible range."""
        if self.low is not None and value < self.low:
            return False
        return self.high is None or value <= self.high


SIGNAL_SPECS: dict[Signal, SignalSpec] = {
    Signal.FLAME: SignalSpec(SignalKind.BINARY, link=True),
    # Water below 0 °C is a broken sensor, not a heating circuit (PB-21).
    Signal.FLOW: SignalSpec(
        SignalKind.TEMPERATURE, link=True, low=0.0, high=110.0, gateway_zero_unknown=True
    ),
    Signal.RETURN: SignalSpec(
        SignalKind.TEMPERATURE, low=0.0, high=110.0, gateway_zero_unknown=True
    ),
    Signal.MODULATION: SignalSpec(SignalKind.PERCENT, low=0.0, high=100.0),
    Signal.CH_SETPOINT: SignalSpec(SignalKind.TEMPERATURE, low=0.0, high=100.0),
    Signal.DHW_ACTIVE: SignalSpec(SignalKind.BINARY),
    Signal.PRESSURE: SignalSpec(SignalKind.PRESSURE, low=0.0, high=6.0, gateway_zero_unknown=True),
    Signal.FLUE_GAS: SignalSpec(
        SignalKind.TEMPERATURE, low=-20.0, high=300.0, gateway_zero_unknown=True
    ),
    Signal.OUTDOOR: SignalSpec(
        SignalKind.TEMPERATURE, low=-60.0, high=60.0, gateway_zero_unknown=True
    ),
    Signal.ROOM_SETPOINT: SignalSpec(SignalKind.TEMPERATURE, low=0.0, high=40.0),
    Signal.ROOM_TEMPERATURE: SignalSpec(
        SignalKind.TEMPERATURE, low=-10.0, high=50.0, gateway_zero_unknown=True
    ),
    Signal.CH_ACTIVE: SignalSpec(SignalKind.BINARY),
    Signal.PUMP_RUNNING: SignalSpec(SignalKind.BINARY),
    Signal.GAS_METER: SignalSpec(SignalKind.COUNTER, low=0.0),
    Signal.BOILER_POWER: SignalSpec(SignalKind.POWER, low=0.0, high=100000.0),
    # Not part of the boiler link (X2): a fault signal gone or stale is no fault.
    Signal.LOW_PRESSURE_FAULT: SignalSpec(SignalKind.BINARY),
    Signal.BOILER_LOCKOUT: SignalSpec(SignalKind.BINARY),
    Signal.FAULT_INDICATION: SignalSpec(SignalKind.BINARY),
}

# The boiler link's signals: water-temperature control needs them mapped (``no_flame_signal``,
# ``no_flow_signal``), the connection sensor judges them. Optional for the entry (X8).
LINK_SIGNALS: frozenset[Signal] = frozenset(
    signal for signal, spec in SIGNAL_SPECS.items() if spec.link
)

# The order the form asks for the signals in, which is also their precedence: one entity feeds
# one signal only (X5.2, P-16; which pairs may share one is empty in 0.2.2 — provisional, K4),
# and where stored options map one entity to several, the first here keeps it and the later ones
# are dropped. A shared entity would otherwise, e.g., never let hot water be told apart from
# heating ("flame on, heating off").
SIGNAL_PRECEDENCE: tuple[Signal, ...] = (
    Signal.FLAME,
    Signal.FLOW,
    Signal.RETURN,
    Signal.MODULATION,
    Signal.DHW_ACTIVE,
    Signal.PRESSURE,
    Signal.OUTDOOR,
    Signal.CH_SETPOINT,
    Signal.CH_ACTIVE,
    Signal.PUMP_RUNNING,
    Signal.FLUE_GAS,
    Signal.GAS_METER,
    Signal.BOILER_POWER,
    Signal.ROOM_SETPOINT,
    Signal.ROOM_TEMPERATURE,
    # Y1: the low-pressure fault before the lockout; one entity for both keeps the first.
    Signal.LOW_PRESSURE_FAULT,
    Signal.BOILER_LOCKOUT,
    Signal.FAULT_INDICATION,
)

# How near 0 °C the gateway's last outdoor reading must be for its next 0.0 to be a reading
# (PB-21, M1; provisional, K4).
GATEWAY_OUTDOOR_ZERO_NEAR_K = 2.0


@dataclass
class GatewayOutdoor:
    """The OpenTherm Gateway's outdoor temperature through its zero rule (PB-21, M1). The
    gateway shows 0 after a reset and for good where the boiler never answers the ID, but a
    boiler reporting whole or half degrees also reads exactly 0 for hours at freezing. A 0.0
    is a reading only right after a known reading within ``GATEWAY_OUTDOOR_ZERO_NEAR_K`` of 0
    (an accepted 0 included); with no reading yet in this run, after one farther away, or
    after an unknown state (unavailable, missing, implausible — the trace of an outage or a
    reset) it is unknown. A gateway reset whose entity never goes unknown is not traced: its 0
    after a reading near 0 counts, at most that margin off. ``last``: the last value read."""

    last: float | None = None

    def read(self, value: float | None) -> float | None:
        """The reading for ``value`` (the entity's parsed value, its 0 kept as 0)."""
        if value == 0.0 and (self.last is None or abs(self.last) > GATEWAY_OUTDOOR_ZERO_NEAR_K):
            value = None
        self.last = value
        return value
