"""Physical parameters with a source and a confidence for every value.

A parameter can have one estimate per source. The effective value is the user's entry when there
is one — manual entry always wins — else the most refined estimate that is confident enough:
learned, then measured, then the class default. A value read from the boiler's integration is
only a suggestion until the user confirms it. A declared value that disagrees with a measured
one is a diagnostic finding.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType


class Source(StrEnum):
    DEFAULT = "default"  # generic value for the boiler or building class
    SUGGESTED = "suggested"  # read from the integration, waiting for confirmation
    ENTERED = "entered"  # typed or confirmed by the user
    MEASURED = "measured"  # derived once from recorded data
    LEARNED = "learned"  # adapted continuously from live data


# Order in which estimates become effective (after ENTERED, which always wins).
_REFINED = (Source.LEARNED, Source.MEASURED)


class ParameterKey(StrEnum):
    BOILER_MIN_POWER = "boiler_min_power"
    BOILER_MAX_POWER = "boiler_max_power"
    MAX_CH_SETPOINT = "max_ch_setpoint"
    GAS_AT_MIN_POWER = "gas_at_min_power"
    GAS_AT_MAX_POWER = "gas_at_max_power"
    CH_HYSTERESIS = "ch_hysteresis"
    WATER_VOLUME = "water_volume"
    LOSS_COEFFICIENT = "loss_coefficient"
    HEATING_THRESHOLD = "heating_threshold"
    THERMAL_TIME_CONSTANT = "thermal_time_constant"
    DESIGN_OUTDOOR = "design_outdoor"
    INDOOR_REFERENCE = "indoor_reference"


@dataclass(frozen=True, slots=True)
class ParameterDef:
    """Unit, plausible range, generic default and mismatch tolerance of a parameter.

    A declared and a measured value mismatch when they differ by more than both
    ``tolerance_abs`` and ``tolerance_rel`` times the declared value.
    """

    unit: str
    low: float
    high: float
    default: float | None = None
    tolerance_abs: float = 0.0
    tolerance_rel: float = 0.0

    def plausible(self, value: float) -> bool:
        return self.low <= value <= self.high


PARAMETER_DEFS: Mapping[ParameterKey, ParameterDef] = MappingProxyType(
    {
        ParameterKey.BOILER_MIN_POWER: ParameterDef("kW", 0.3, 200.0, tolerance_rel=0.2),
        ParameterKey.BOILER_MAX_POWER: ParameterDef("kW", 1.0, 500.0, tolerance_rel=0.2),
        ParameterKey.MAX_CH_SETPOINT: ParameterDef("°C", 20.0, 95.0, tolerance_abs=3.0),
        # Gas per hour at minimum and maximum power, in the gas meter's unit (m³ or kWh).
        ParameterKey.GAS_AT_MIN_POWER: ParameterDef("gas/h", 0.0, 200.0, tolerance_rel=0.2),
        ParameterKey.GAS_AT_MAX_POWER: ParameterDef("gas/h", 0.0, 500.0, tolerance_rel=0.2),
        ParameterKey.CH_HYSTERESIS: ParameterDef("K", 0.5, 30.0, tolerance_abs=2.0),
        ParameterKey.WATER_VOLUME: ParameterDef("l", 5.0, 5000.0, tolerance_rel=0.3),
        ParameterKey.LOSS_COEFFICIENT: ParameterDef("kW/K", 0.01, 5.0, tolerance_rel=0.25),
        ParameterKey.HEATING_THRESHOLD: ParameterDef(
            "°C", 5.0, 22.0, default=15.0, tolerance_abs=2.0
        ),
        ParameterKey.THERMAL_TIME_CONSTANT: ParameterDef("h", 1.0, 1000.0, tolerance_rel=0.5),
        ParameterKey.DESIGN_OUTDOOR: ParameterDef("°C", -45.0, 10.0, default=-15.0),
        ParameterKey.INDOOR_REFERENCE: ParameterDef("°C", 10.0, 30.0, default=20.0),
    }
)

DEFAULT_CONFIDENCE = 0.2
MIN_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class Estimate:
    value: float
    source: Source
    confidence: float = 1.0  # 0 to 1
    at: float | None = None  # seconds since the Unix epoch


@dataclass(frozen=True, slots=True)
class Mismatch:
    """A declared value that disagrees with a measured or learned one."""

    key: ParameterKey
    declared: float
    observed: Estimate


@dataclass(frozen=True, slots=True)
class Parameter:
    key: ParameterKey
    estimates: Mapping[Source, Estimate] = field(default_factory=dict)

    @property
    def definition(self) -> ParameterDef:
        return PARAMETER_DEFS[self.key]

    def estimate(self, source: Source) -> Estimate | None:
        found = self.estimates.get(source)
        if found is None and source is Source.DEFAULT and self.definition.default is not None:
            return Estimate(self.definition.default, Source.DEFAULT, DEFAULT_CONFIDENCE)
        return found

    def effective(self, min_confidence: float = MIN_CONFIDENCE) -> Estimate | None:
        """The value to use now; ``None`` when nothing usable is known."""
        entered = self.estimates.get(Source.ENTERED)
        if entered is not None:
            return entered
        for source in _REFINED:
            candidate = self.estimates.get(source)
            if candidate is not None and candidate.confidence >= min_confidence:
                return candidate
        return self.estimate(Source.DEFAULT)

    def mismatch(self, min_confidence: float = MIN_CONFIDENCE) -> Mismatch | None:
        """A finding when the user's value disagrees with a confident observation."""
        entered = self.estimates.get(Source.ENTERED)
        if entered is None:
            return None
        definition = self.definition
        for source in _REFINED:
            observed = self.estimates.get(source)
            if observed is None or observed.confidence < min_confidence:
                continue
            difference = abs(observed.value - entered.value)
            if (
                difference > definition.tolerance_abs
                and difference > definition.tolerance_rel * abs(entered.value)
            ):
                return Mismatch(self.key, entered.value, observed)
            return None
        return None


class ParameterSet:
    """Every parameter of an installation; immutable, changes return a new set."""

    __slots__ = ("_parameters",)

    def __init__(self, parameters: Mapping[ParameterKey, Parameter] | None = None) -> None:
        self._parameters: dict[ParameterKey, Parameter] = dict(parameters or {})

    def get(self, key: ParameterKey) -> Parameter:
        return self._parameters.get(key, Parameter(key))

    def value(self, key: ParameterKey, min_confidence: float = MIN_CONFIDENCE) -> float | None:
        effective = self.get(key).effective(min_confidence)
        return None if effective is None else effective.value

    def with_estimate(self, key: ParameterKey, estimate: Estimate) -> ParameterSet:
        """A copy with ``estimate`` replacing the one from the same source."""
        definition = PARAMETER_DEFS[key]
        if not definition.plausible(estimate.value):
            raise ValueError(
                f"{key}: {estimate.value} {definition.unit} is outside "
                f"{definition.low} to {definition.high}"
            )
        if not 0.0 <= estimate.confidence <= 1.0:
            raise ValueError(f"{key}: confidence {estimate.confidence} is outside 0 to 1")
        parameter = self.get(key)
        updated = replace(parameter, estimates={**parameter.estimates, estimate.source: estimate})
        return ParameterSet({**self._parameters, key: updated})

    def without(self, key: ParameterKey, source: Source) -> ParameterSet:
        """A copy without the estimate from ``source``."""
        parameter = self.get(key)
        estimates = {s: e for s, e in parameter.estimates.items() if s is not source}
        return ParameterSet({**self._parameters, key: replace(parameter, estimates=estimates)})

    def confirm_suggestion(self, key: ParameterKey, at: float | None = None) -> ParameterSet:
        """Turn the integration's suggestion into the user's entry."""
        suggestion = self.get(key).estimates.get(Source.SUGGESTED)
        if suggestion is None:
            raise KeyError(f"{key}: no suggestion to confirm")
        entered = Estimate(suggestion.value, Source.ENTERED, 1.0, at)
        return self.with_estimate(key, entered).without(key, Source.SUGGESTED)

    def mismatches(self, min_confidence: float = MIN_CONFIDENCE) -> list[Mismatch]:
        found = (self.get(key).mismatch(min_confidence) for key in ParameterKey)
        return [m for m in found if m is not None]
