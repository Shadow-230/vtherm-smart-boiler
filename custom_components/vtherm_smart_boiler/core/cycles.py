"""Burner cycles: burns and pauses from the flame signal, and whether a burn heated DHW.

A burn is a stretch with the flame on. Its start (or end) is *seen* only when the flame was
known to be off right before (or after) it; an edge hidden by unknown data or cut by the window
is not a start. DHW is taken from its own signal when mapped, else from a CH-active signal, else
inferred from flow temperature against the CH setpoint and from zone demand, with a confidence.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .series import Series, duration_where, known_duration


@dataclass(frozen=True, slots=True)
class Burn:
    start: float
    end: float
    start_seen: bool  # the flame was seen going on
    end_seen: bool  # the flame was seen going off

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def complete(self) -> bool:
        return self.start_seen and self.end_seen


@dataclass(frozen=True, slots=True)
class Pause:
    """Flame off between two burns, both edges seen."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def find_burns(flame: Series[bool], start: float, end: float) -> list[Burn]:
    """Flame-on stretches in ``[start, end)``."""
    segments = list(flame.segments(start, end))
    burns: list[Burn] = []
    for index, segment in enumerate(segments):
        if segment.value is not True:
            continue
        before = segments[index - 1].value if index > 0 else None
        after = segments[index + 1].value if index + 1 < len(segments) else None
        burns.append(Burn(segment.start, segment.end, before is False, after is False))
    return burns


def find_pauses(flame: Series[bool], start: float, end: float) -> list[Pause]:
    """Flame-off stretches in ``[start, end)`` with a seen burn on both sides."""
    segments = list(flame.segments(start, end))
    return [
        Pause(segment.start, segment.end)
        for index, segment in enumerate(segments)
        if segment.value is False
        and 0 < index < len(segments) - 1
        and segments[index - 1].value is True
        and segments[index + 1].value is True
    ]


class BurnKind(StrEnum):
    CH = "ch"
    DHW = "dhw"
    UNKNOWN = "unknown"


class Evidence(StrEnum):
    DHW_SIGNAL = "dhw_signal"
    CH_SIGNAL = "ch_signal"
    FLOW_ABOVE_SETPOINT = "flow_above_setpoint"
    FLOW_ABOVE_MAX_CH = "flow_above_max_ch"
    NO_ZONE_DEMAND = "no_zone_demand"
    ZONE_DEMAND = "zone_demand"
    FLOW_WITHIN_SETPOINT = "flow_within_setpoint"


# How strongly each inferred observation points to DHW (> 0.5) or to CH (< 0.5).
_DHW_PROBABILITY: dict[Evidence, float] = {
    Evidence.FLOW_ABOVE_MAX_CH: 0.9,
    Evidence.FLOW_ABOVE_SETPOINT: 0.7,
    Evidence.NO_ZONE_DEMAND: 0.6,
    Evidence.ZONE_DEMAND: 0.4,
    Evidence.FLOW_WITHIN_SETPOINT: 0.45,
}
SIGNAL_COVERAGE = 0.5  # a signal decides when known for at least half of the burn
CH_SIGNAL_CONFIDENCE = 0.9


@dataclass(frozen=True, slots=True)
class DhwInputs:
    """Signals that help tell DHW from CH; any may be missing.

    ``zone_demand`` is true while any zone on the boiler calls for heat.
    """

    dhw_active: Series[bool] | None = None
    ch_active: Series[bool] | None = None
    flow: Series[float] | None = None
    ch_setpoint: Series[float] | None = None
    max_ch_setpoint: float | None = None
    zone_demand: Series[bool] | None = None
    setpoint_margin: float = 5.0  # K the flow must exceed a setpoint by


@dataclass(frozen=True, slots=True)
class ClassifiedBurn:
    burn: Burn
    kind: BurnKind
    confidence: float  # 0 to 1 that ``kind`` is right
    evidence: tuple[Evidence, ...] = ()

    @property
    def is_dhw(self) -> bool:
        return self.kind is BurnKind.DHW


def classify_burn(burn: Burn, inputs: DhwInputs) -> ClassifiedBurn:
    """Decide whether a burn heated DHW or CH."""
    if burn.duration <= 0:
        return ClassifiedBurn(burn, BurnKind.UNKNOWN, 0.0)
    for signal, evidence, dhw_when, weight in (
        (inputs.dhw_active, Evidence.DHW_SIGNAL, True, 1.0),
        (inputs.ch_active, Evidence.CH_SIGNAL, False, CH_SIGNAL_CONFIDENCE),
    ):
        if signal is None:
            continue
        coverage = known_duration(signal, burn.start, burn.end) / burn.duration
        if coverage < SIGNAL_COVERAGE:
            continue
        dhw_time = duration_where(signal, burn.start, burn.end, lambda v, w=dhw_when: v is w)
        dhw_share = dhw_time / (coverage * burn.duration)
        kind = BurnKind.DHW if dhw_share >= 0.5 else BurnKind.CH
        share = dhw_share if kind is BurnKind.DHW else 1.0 - dhw_share
        return ClassifiedBurn(burn, kind, weight * coverage * share, (evidence,))
    return _infer(burn, inputs)


def classify_burns(burns: Sequence[Burn], inputs: DhwInputs) -> list[ClassifiedBurn]:
    return [classify_burn(burn, inputs) for burn in burns]


def _infer(burn: Burn, inputs: DhwInputs) -> ClassifiedBurn:
    found: list[Evidence] = []
    flow = inputs.flow
    if flow is not None and inputs.max_ch_setpoint is not None:
        ceiling = inputs.max_ch_setpoint + inputs.setpoint_margin
        if duration_where(flow, burn.start, burn.end, lambda v: v > ceiling) > 0:
            found.append(Evidence.FLOW_ABOVE_MAX_CH)
    if flow is not None and inputs.ch_setpoint is not None:
        above = _share_over_time(burn, flow, inputs.ch_setpoint, inputs.setpoint_margin)
        if above is not None:
            found.append(
                Evidence.FLOW_ABOVE_SETPOINT if above >= 0.5 else Evidence.FLOW_WITHIN_SETPOINT
            )
    if inputs.zone_demand is not None:
        known = known_duration(inputs.zone_demand, burn.start, burn.end)
        if known >= SIGNAL_COVERAGE * burn.duration:
            demand = duration_where(inputs.zone_demand, burn.start, burn.end, bool)
            found.append(Evidence.ZONE_DEMAND if demand > 0 else Evidence.NO_ZONE_DEMAND)
    if not found:
        return ClassifiedBurn(burn, BurnKind.UNKNOWN, 0.0)
    # Independent observations add up in log-odds from an even prior.
    log_odds = sum(math.log(p / (1.0 - p)) for p in (_DHW_PROBABILITY[e] for e in found))
    probability = 1.0 / (1.0 + math.exp(-log_odds))
    if probability > 0.5:
        return ClassifiedBurn(burn, BurnKind.DHW, probability, tuple(found))
    return ClassifiedBurn(burn, BurnKind.CH, 1.0 - probability, tuple(found))


def _share_over_time(
    burn: Burn, flow: Series[float], setpoint: Series[float], margin: float
) -> float | None:
    """Share of the burn, where both are known, with flow above setpoint plus margin."""
    known = 0.0
    above = 0.0
    for segment in flow.segments(burn.start, burn.end):
        if segment.value is None:
            continue
        for part in setpoint.segments(segment.start, segment.end):
            if part.value is None:
                continue
            known += part.duration
            if segment.value > part.value + margin:
                above += part.duration
    if known < SIGNAL_COVERAGE * burn.duration:
        return None
    return above / known
