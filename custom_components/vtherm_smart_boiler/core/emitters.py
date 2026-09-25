"""Emitter power factor: how much an emitter gives now compared with its reference condition.

EN 442 relation: ``P = P_ref · (ΔT / ΔT_ref)^n`` with ``ΔT`` the mean excess of the water over
the room. The factor says what the water temperature does to a zone's heat; the valve opening
only decides whether the zone is heating, so an algorithm whose input is the opening can scale
its gain by the factor without counting the opening twice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .installation import EmitterType, Zone
from .readings import ZONE_OPEN, ZoneState
from .supply import Supply, SupplyReason


@dataclass(frozen=True, slots=True)
class EmitterReference:
    """Reference condition of an emitter type: flow, return and room temperature, exponent."""

    flow: float
    return_: float
    room: float
    exponent: float

    @property
    def excess(self) -> float:
        return mean_excess(self.flow, self.return_, self.room)

    @property
    def nominal_drop(self) -> float:
        return self.flow - self.return_


EMITTER_REFERENCE: dict[EmitterType, EmitterReference] = {
    EmitterType.RADIATOR: EmitterReference(75.0, 65.0, 20.0, 1.3),  # EN 442 nominal
    EmitterType.CONVECTOR: EmitterReference(75.0, 65.0, 20.0, 1.4),
    EmitterType.UNDERFLOOR: EmitterReference(35.0, 30.0, 20.0, 1.1),
}


# Below this ratio of return excess to flow excess the logarithmic mean falls towards zero,
# which a radiator whose top is hot does not: from here down to a return at room temperature,
# the mean runs straight to half the flow excess — no jump where the return reaches the room.
LOG_MEAN_FROM = 0.5


def mean_excess(flow: float, return_: float, room: float) -> float:
    """Mean excess of the water over the room, in K; zero when the water is not warmer.

    Logarithmic mean for a return well above the room; arithmetic mean when the return is not
    below the flow; half the flow excess when the return is not above the room; in between, a
    straight line from there to the logarithmic mean, so the mean is continuous (P62).
    """
    flow_excess = flow - room
    if flow_excess <= 0:
        return 0.0
    return_excess = return_ - room
    if return_ >= flow:
        return (flow_excess + return_excess) / 2.0
    ratio = max(0.0, return_excess / flow_excess)
    if ratio >= LOG_MEAN_FROM:
        return (flow - return_) / math.log(flow_excess / return_excess)
    edge = (1.0 - LOG_MEAN_FROM) / math.log(1.0 / LOG_MEAN_FROM)  # log mean at the edge, / ΔT
    share = 0.5 + (edge - 0.5) * ratio / LOG_MEAN_FROM
    return flow_excess * share


def power_factor(
    emitter: EmitterType,
    supply: float,
    return_: float | None,
    room: float,
    exponent: float | None = None,
) -> float:
    """Output now relative to the reference output of this emitter type."""
    reference = EMITTER_REFERENCE[emitter]
    if return_ is None:
        # Without a return, the drop is taken to scale with the water's excess over the room.
        share = 1.0 - reference.nominal_drop / (2.0 * (reference.flow - reference.room))
        excess = max(0.0, (supply - room) * share)
    else:
        excess = mean_excess(supply, return_, room)
    return (excess / reference.excess) ** (exponent if exponent is not None else reference.exponent)


class FactorStatus(StrEnum):
    COMPUTED = "computed"
    HELD = "held"
    UNAVAILABLE = "unavailable"


class FactorReason(StrEnum):
    FLOW_UNKNOWN = "flow_unknown"
    FLOW_STALE = "flow_stale"
    CIRCUIT_NOT_MEASURED = "circuit_not_measured"
    ROOM_UNKNOWN = "room_unknown"
    ZONE_UNKNOWN = "zone_unknown"
    NOT_HEATING_YET = "not_heating_yet"


_SUPPLY_TO_FACTOR = {
    SupplyReason.FLOW_UNKNOWN: FactorReason.FLOW_UNKNOWN,
    SupplyReason.FLOW_STALE: FactorReason.FLOW_STALE,
    SupplyReason.CIRCUIT_NOT_MEASURED: FactorReason.CIRCUIT_NOT_MEASURED,
}


@dataclass(frozen=True, slots=True)
class FactorResult:
    value: float | None
    status: FactorStatus
    reason: FactorReason | None = None
    at: float | None = None  # when the value was computed
    output_w: float | None = None  # estimated output when the emitter size is known


def is_heating(zone: ZoneState) -> bool | None:
    """Whether a zone takes heat now: its valve or duty cycle is open, or it calls for heat."""
    demand = zone.demand
    if demand is not None:
        return demand > ZONE_OPEN
    return zone.calling


def update_factor(
    previous: FactorResult | None,
    zone_config: Zone,
    zone: ZoneState,
    supply: Supply,
    return_: float | None,
    now: float,
    dhw: bool | None = None,
) -> FactorResult:
    """The factor for a zone: computed while heating, else held; unavailable without data.
    While the boiler heats hot water no heat reaches the zone: the last value is held."""
    heating = is_heating(zone)
    if heating is None:
        return FactorResult(None, FactorStatus.UNAVAILABLE, FactorReason.ZONE_UNKNOWN)
    if not heating or dhw is True:
        if previous is not None and previous.value is not None:
            return FactorResult(
                previous.value, FactorStatus.HELD, None, previous.at, previous.output_w
            )
        return FactorResult(None, FactorStatus.UNAVAILABLE, FactorReason.NOT_HEATING_YET)
    if supply.temperature is None:
        reason = _SUPPLY_TO_FACTOR[supply.reason or SupplyReason.FLOW_UNKNOWN]
        return FactorResult(None, FactorStatus.UNAVAILABLE, reason)
    if zone.temperature is None:
        return FactorResult(None, FactorStatus.UNAVAILABLE, FactorReason.ROOM_UNKNOWN)
    factor = power_factor(
        zone_config.emitter, supply.temperature, return_, zone.temperature, zone_config.exponent
    )
    output = (
        zone_config.reference_output_w * factor
        if zone_config.reference_output_w is not None
        else None
    )
    return FactorResult(factor, FactorStatus.COMPUTED, None, now, output)
