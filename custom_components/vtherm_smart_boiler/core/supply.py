"""Water temperature reaching a circuit's emitters, from the boiler flow and the circuit type."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .installation import Circuit, CircuitControl


class SupplyReason(StrEnum):
    FLOW_UNKNOWN = "flow_unknown"
    FLOW_STALE = "flow_stale"
    CIRCUIT_NOT_MEASURED = "circuit_not_measured"


@dataclass(frozen=True, slots=True)
class Supply:
    """Supply temperature of a circuit, or ``None`` with the reason it is not known."""

    temperature: float | None
    reason: SupplyReason | None = None


def circuit_supply(
    circuit: Circuit,
    boiler_flow: float | None,
    flow_fresh: bool,
    circuit_flow: float | None = None,
) -> Supply:
    """What the circuit's emitters receive.

    A measured circuit flow wins. Otherwise an unmixed circuit gets the boiler flow, a passive
    fixed circuit at most its declared temperature; a mixed circuit without its own sensor is
    not known — the boiler flow says nothing about it.
    """
    if circuit_flow is not None:
        return Supply(circuit_flow)
    if circuit.control in (CircuitControl.THROUGH_BOILER, CircuitControl.SEPARATE):
        return Supply(None, SupplyReason.CIRCUIT_NOT_MEASURED)
    if boiler_flow is None:
        return Supply(None, SupplyReason.FLOW_UNKNOWN)
    if not flow_fresh:
        return Supply(None, SupplyReason.FLOW_STALE)
    if circuit.control is CircuitControl.PASSIVE_FIXED and circuit.fixed_temperature is not None:
        return Supply(min(boiler_flow, circuit.fixed_temperature))
    return Supply(boiler_flow)
