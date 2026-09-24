"""The installation: one boiler, its circuits and the VT zones on each circuit."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum


class BoilerClass(StrEnum):
    """What the plugin can do with the boiler, from what its integration can write."""

    FLOW_SETPOINT = "flow_setpoint"
    CURVE_ONLY = "curve_only"
    ON_OFF = "on_off"
    READ_ONLY = "read_only"


class DhwType(StrEnum):
    NONE = "none"
    STORAGE = "storage"
    COMBI = "combi"


class CircuitControl(StrEnum):
    """Who sets a circuit's water temperature."""

    UNMIXED_SHARED = "unmixed_shared"  # one loop straight from the boiler
    THROUGH_BOILER = "through_boiler"  # e.g. OpenTherm CH2 or the boiler's mixing module
    SEPARATE = "separate"  # an external mixing controller
    PASSIVE_FIXED = "passive_fixed"  # a thermostatic mixing valve at a fixed temperature


class EmitterType(StrEnum):
    RADIATOR = "radiator"
    UNDERFLOOR = "underfloor"
    CONVECTOR = "convector"


@dataclass(frozen=True, slots=True)
class Boiler:
    boiler_class: BoilerClass
    dhw: DhwType = DhwType.NONE
    condensing: bool = True
    shared_return: bool = False  # CH and DHW share the return sensor


@dataclass(frozen=True, slots=True)
class Circuit:
    """A heating circuit.

    ``fixed_temperature`` is the declared water temperature of a passive fixed circuit.
    ``max_flow`` caps the water temperature this circuit may receive (e.g. underfloor).
    """

    circuit_id: str
    control: CircuitControl = CircuitControl.UNMIXED_SHARED
    fixed_temperature: float | None = None
    max_flow: float | None = None


@dataclass(frozen=True, slots=True)
class Zone:
    """A VT thermostat assigned to a circuit.

    ``reference_output_w`` is the emitter size: its output at the emitter type's reference
    condition, when the user knows it. ``exponent`` overrides the emitter type's EN 442 exponent
    (advanced).
    """

    zone_id: str
    circuit_id: str
    emitter: EmitterType = EmitterType.RADIATOR
    reference_output_w: float | None = None
    exponent: float | None = None


class IssueCode(StrEnum):
    NO_CIRCUIT = "no_circuit"
    DUPLICATE_CIRCUIT = "duplicate_circuit"
    DUPLICATE_ZONE = "duplicate_zone"
    UNKNOWN_CIRCUIT = "unknown_circuit"
    FIXED_TEMPERATURE_MISSING = "fixed_temperature_missing"
    EMPTY_CIRCUIT = "empty_circuit"
    UNDERFLOOR_WITHOUT_MAX_FLOW = "underfloor_without_max_flow"


class Severity(StrEnum):
    ERROR = "error"  # the configuration cannot be used
    WARNING = "warning"  # usable, but the user should know


@dataclass(frozen=True, slots=True)
class Issue:
    code: IssueCode
    severity: Severity
    subject: str | None = None  # the circuit or zone concerned


@dataclass(frozen=True, slots=True)
class Installation:
    boiler: Boiler
    circuits: tuple[Circuit, ...]
    zones: tuple[Zone, ...] = ()

    def circuit(self, circuit_id: str) -> Circuit | None:
        return next((c for c in self.circuits if c.circuit_id == circuit_id), None)

    def zone(self, zone_id: str) -> Zone | None:
        return next((z for z in self.zones if z.zone_id == zone_id), None)

    def zones_in(self, circuit_id: str) -> tuple[Zone, ...]:
        return tuple(z for z in self.zones if z.circuit_id == circuit_id)

    def emitters_in(self, circuit_id: str) -> frozenset[EmitterType]:
        return frozenset(z.emitter for z in self.zones_in(circuit_id))

    def issues(self) -> list[Issue]:
        """Problems with the configuration; any ``ERROR`` makes it unusable."""
        found: list[Issue] = []
        if not self.circuits:
            found.append(Issue(IssueCode.NO_CIRCUIT, Severity.ERROR))
        circuit_counts = Counter(c.circuit_id for c in self.circuits)
        found.extend(
            Issue(IssueCode.DUPLICATE_CIRCUIT, Severity.ERROR, cid)
            for cid, count in circuit_counts.items()
            if count > 1
        )
        zone_counts = Counter(z.zone_id for z in self.zones)
        found.extend(
            Issue(IssueCode.DUPLICATE_ZONE, Severity.ERROR, zid)
            for zid, count in zone_counts.items()
            if count > 1
        )
        found.extend(
            Issue(IssueCode.UNKNOWN_CIRCUIT, Severity.ERROR, z.zone_id)
            for z in self.zones
            if z.circuit_id not in circuit_counts
        )
        for circuit in self.circuits:
            cid = circuit.circuit_id
            if (
                circuit.control is CircuitControl.PASSIVE_FIXED
                and circuit.fixed_temperature is None
            ):
                found.append(Issue(IssueCode.FIXED_TEMPERATURE_MISSING, Severity.ERROR, cid))
            emitters = self.emitters_in(cid)
            if not emitters:
                found.append(Issue(IssueCode.EMPTY_CIRCUIT, Severity.WARNING, cid))
            if (
                circuit.control is CircuitControl.UNMIXED_SHARED
                and EmitterType.UNDERFLOOR in emitters
                and circuit.max_flow is None
            ):
                found.append(Issue(IssueCode.UNDERFLOOR_WITHOUT_MAX_FLOW, Severity.WARNING, cid))
        return found

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues())
