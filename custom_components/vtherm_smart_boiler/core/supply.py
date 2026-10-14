"""Water temperature reaching a circuit's emitters, from the boiler flow and the circuit type."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .installation import Circuit, CircuitControl


class SupplyReason(StrEnum):
    """Why a circuit's water is not known (docs/en/specification/water-interface.md, §4.1): lasting
    — nothing to measure it with, or a zone in circuits with different water — or momentary."""

    NOT_MAPPED = "not_mapped"  # lasting: no boiler flow mapped and no circuit sensor
    CIRCUIT_NOT_MEASURED = "circuit_not_measured"  # lasting: a mixed circuit without its sensor
    SEVERAL_CIRCUITS = "several_circuits"  # lasting: a zone's circuits differ, or one is unknown
    FLOW_UNKNOWN = "flow_unknown"  # momentary: the sensor reads nothing usable now
    FLOW_STALE = "flow_stale"  # momentary: its last reading is past its age limit


@dataclass(frozen=True, slots=True)
class Supply:
    """Supply temperature of a circuit, or ``None`` with the reason it is not known."""

    temperature: float | None
    reason: SupplyReason | None = None
    measured_at: float | None = None  # when the reading used was taken; only with a temperature


def circuit_return(circuit: Circuit, boiler_return: float | None) -> float | None:
    """The return of a circuit's emitters: the boiler's return only for a circuit fed straight
    from the boiler — a mixed circuit's water goes back through its own mixing."""
    return boiler_return if circuit.control is CircuitControl.UNMIXED_SHARED else None


def circuit_supply(
    circuit: Circuit,
    boiler_flow: float | None,
    flow_fresh: bool,
    circuit_flow: float | None = None,
    *,
    flow_mapped: bool = True,
    own_mapped: bool = False,
    own_stale: bool = False,
    flow_at: float | None = None,
    own_at: float | None = None,
) -> Supply:
    """What the circuit's emitters receive.

    A measured circuit flow (``circuit_flow``: its own sensor's fresh value) wins. Otherwise an
    unmixed circuit gets the boiler flow, a passive fixed circuit at most its declared
    temperature; a mixed circuit is not known — the boiler flow says nothing about it. Why not
    known, lasting or momentary (I9): no water sensor at all (``flow_mapped`` false and no
    ``own_mapped``) is ``not_mapped``; a circuit's own sensor that is mapped but gives nothing
    now is ``flow_unknown``, or ``flow_stale`` (``own_stale``) — a straight circuit then takes the
    boiler's flow. ``flow_at`` and ``own_at``: when each reading was taken.
    """
    if circuit_flow is not None:
        return Supply(circuit_flow, measured_at=own_at)
    lost = None
    if own_mapped:
        lost = SupplyReason.FLOW_STALE if own_stale else SupplyReason.FLOW_UNKNOWN
    if circuit.control in (CircuitControl.THROUGH_BOILER, CircuitControl.SEPARATE):
        return Supply(None, lost or SupplyReason.CIRCUIT_NOT_MEASURED)
    if boiler_flow is None:
        if not flow_mapped:
            return Supply(None, lost or SupplyReason.NOT_MAPPED)
        return Supply(None, SupplyReason.FLOW_UNKNOWN)
    if not flow_fresh:
        return Supply(None, SupplyReason.FLOW_STALE)
    if circuit.control is CircuitControl.PASSIVE_FIXED and circuit.fixed_temperature is not None:
        return Supply(min(boiler_flow, circuit.fixed_temperature), measured_at=flow_at)
    return Supply(boiler_flow, measured_at=flow_at)
