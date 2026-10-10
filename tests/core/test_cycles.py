"""Burner cycles: burns, pauses, seen edges and DHW classification."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.cycles import (
    Burn,
    BurnKind,
    DhwInputs,
    Evidence,
    classify_burn,
    classify_burns,
    find_burns,
)
from custom_components.vtherm_smart_boiler.core.series import Series

MIN = 60.0


def flame(*points: tuple[float, bool | None]) -> Series[bool]:
    return Series([(t * MIN, v) for t, v in points])


def test_burns_with_seen_edges() -> None:
    series = flame((0, False), (10, True), (20, False), (30, True), (45, False))
    assert find_burns(series, 0, 60 * MIN) == [
        Burn(10 * MIN, 20 * MIN, True, True),
        Burn(30 * MIN, 45 * MIN, True, True),
    ]


def test_edges_cut_by_the_window_are_not_seen() -> None:
    series = flame((0, True), (10, False), (20, True))
    burns = find_burns(series, 0, 30 * MIN)
    assert burns == [Burn(0, 10 * MIN, False, True), Burn(20 * MIN, 30 * MIN, True, False)]
    assert not any(b.complete for b in burns)


def test_edges_hidden_by_unknown_are_not_seen() -> None:
    series = flame((0, False), (10, True), (15, None), (20, True), (25, False))
    burns = find_burns(series, 0, 30 * MIN)
    assert burns == [Burn(10 * MIN, 15 * MIN, True, False), Burn(20 * MIN, 25 * MIN, False, True)]


def test_no_flame_data_gives_no_burns() -> None:
    assert find_burns(Series[bool](), 0, 60 * MIN) == []
    assert find_burns(flame((0, None)), 0, 60 * MIN) == []


BURN = Burn(0, 10 * MIN, True, True)


def test_dhw_signal_decides() -> None:
    dhw = Series([(0, True)])
    result = classify_burn(BURN, DhwInputs(dhw_active=dhw))
    assert result.kind is BurnKind.DHW
    assert result.confidence == pytest.approx(1.0)
    assert result.evidence == (Evidence.DHW_SIGNAL,)
    assert result.is_dhw


def test_dhw_signal_majority_on_mixed_burn() -> None:
    dhw = Series([(0, True), (3 * MIN, False)])
    result = classify_burn(BURN, DhwInputs(dhw_active=dhw))
    assert result.kind is BurnKind.CH
    assert result.confidence == pytest.approx(0.7)


def test_dhw_signal_with_poor_coverage_is_ignored() -> None:
    dhw = Series([(0, None), (8 * MIN, True)])
    flow = Series([(0, 75.0)])
    result = classify_burn(BURN, DhwInputs(dhw_active=dhw, flow=flow, max_ch_setpoint=65.0))
    assert Evidence.DHW_SIGNAL not in result.evidence
    assert result.kind is BurnKind.DHW  # inferred from flow above max CH setpoint


def test_ch_signal_decides_when_no_dhw_signal() -> None:
    result = classify_burn(BURN, DhwInputs(ch_active=Series([(0, True)])))
    assert result.kind is BurnKind.CH
    assert result.confidence == pytest.approx(0.9)
    off = classify_burn(BURN, DhwInputs(ch_active=Series([(0, False)])))
    assert off.kind is BurnKind.DHW


def test_nothing_known_is_unknown() -> None:
    result = classify_burn(BURN, DhwInputs())
    assert result.kind is BurnKind.UNKNOWN
    assert result.confidence == 0.0


def test_flow_far_above_setpoint_points_to_dhw() -> None:
    inputs = DhwInputs(flow=Series([(0, 70.0)]), ch_setpoint=Series([(0, 45.0)]))
    result = classify_burn(BURN, inputs)
    assert result.kind is BurnKind.DHW
    assert result.confidence == pytest.approx(0.7)
    assert result.evidence == (Evidence.FLOW_ABOVE_SETPOINT,)


def test_flow_within_setpoint_and_zone_demand_point_to_ch() -> None:
    inputs = DhwInputs(
        flow=Series([(0, 44.0)]),
        ch_setpoint=Series([(0, 45.0)]),
        zone_demand=Series([(0, True)]),
    )
    result = classify_burn(BURN, inputs)
    assert result.kind is BurnKind.CH
    assert result.confidence > 0.6
    assert set(result.evidence) == {Evidence.FLOW_WITHIN_SETPOINT, Evidence.ZONE_DEMAND}


def test_no_zone_demand_alone_is_weak_dhw_evidence() -> None:
    result = classify_burn(BURN, DhwInputs(zone_demand=Series([(0, False)])))
    assert result.kind is BurnKind.DHW
    assert result.confidence == pytest.approx(0.6)


def test_flow_above_max_ch_outweighs_zone_demand() -> None:
    inputs = DhwInputs(
        flow=Series([(0, 50.0), (5 * MIN, 78.0)]),
        max_ch_setpoint=65.0,
        zone_demand=Series([(0, True)]),
    )
    result = classify_burn(BURN, inputs)
    assert result.kind is BurnKind.DHW
    assert result.confidence > 0.8


def test_setpoint_evidence_needs_overlapping_known_data() -> None:
    inputs = DhwInputs(flow=Series([(0, 70.0)]), ch_setpoint=Series([(9 * MIN, 45.0)]))
    assert classify_burn(BURN, inputs).kind is BurnKind.UNKNOWN


def test_zero_length_burn_is_unknown_and_batch_classification() -> None:
    zero = Burn(5.0, 5.0, True, True)
    results = classify_burns([zero, BURN], DhwInputs(dhw_active=Series([(0, False)])))
    assert [r.kind for r in results] == [BurnKind.UNKNOWN, BurnKind.CH]


def test_a_heating_overshoot_is_not_hot_water() -> None:
    """P47: the flow passing the maximum heating setpoint for a moment — an overshoot at low
    load — is no sign of hot water; most of the burn above it is."""
    inputs = DhwInputs(
        flow=Series([(0, 50.0), (8 * MIN, 72.0), (9 * MIN, 50.0)]),
        max_ch_setpoint=65.0,
        zone_demand=Series([(0, True)]),
    )
    assert classify_burn(BURN, inputs).kind is BurnKind.CH


def test_a_boiler_without_hot_water_burns_for_heating() -> None:
    """The declared hot-water type is used: without hot water every burn heats."""
    inputs = DhwInputs(zone_demand=Series([(0, False)]), has_dhw=False)
    result = classify_burn(BURN, inputs)
    assert (result.kind, result.confidence) == (BurnKind.CH, 1.0)


def test_conflicting_inferred_evidence_is_unknown() -> None:
    """P-28: without a DHW or CH signal, a heating burn with no zone demand at that moment and
    the flow within the setpoint scored as hot water (0.6 against 0.45) and left the cycling
    statistics. Evidence that points both ways with a combined probability within 0.35–0.65
    decides nothing: the burn is of unknown kind, counted apart."""
    inputs = DhwInputs(
        flow=Series([(0, 44.0)]),
        ch_setpoint=Series([(0, 45.0)]),
        zone_demand=Series([(0, False)]),
    )
    result = classify_burn(BURN, inputs)
    assert result.kind is BurnKind.UNKNOWN
    assert set(result.evidence) == {Evidence.NO_ZONE_DEMAND, Evidence.FLOW_WITHIN_SETPOINT}
    # Flow above the setpoint while a zone asks: 0.7 against 0.4, about 0.61 — no decision.
    above = DhwInputs(
        flow=Series([(0, 70.0)]),
        ch_setpoint=Series([(0, 45.0)]),
        zone_demand=Series([(0, True)]),
    )
    assert classify_burn(BURN, above).kind is BurnKind.UNKNOWN
    # A conflict whose combined evidence is strong still decides (flow above the maximum).
    strong = DhwInputs(
        flow=Series([(0, 78.0)]), max_ch_setpoint=65.0, zone_demand=Series([(0, True)])
    )
    assert classify_burn(BURN, strong).kind is BurnKind.DHW


def test_single_inferred_evidence_is_unchanged() -> None:
    """P-28's rule needs evidence both ways: one observation decides as before, and one that
    is unknown over the burn is no evidence at all."""
    no_demand = classify_burn(BURN, DhwInputs(zone_demand=Series([(0, False)])))
    assert (no_demand.kind, no_demand.confidence) == (BurnKind.DHW, pytest.approx(0.6))
    flow_only = DhwInputs(flow=Series([(0, 44.0)]), ch_setpoint=Series([(0, 45.0)]))
    within = classify_burn(BURN, flow_only)
    assert (within.kind, within.confidence) == (BurnKind.CH, pytest.approx(0.55))
    # The zones' demand unknown over the burn: only the flow counts, and it decides.
    unknown_demand = DhwInputs(
        flow=Series([(0, 44.0)]),
        ch_setpoint=Series([(0, 45.0)]),
        zone_demand=Series([(0, None)]),
    )
    result = classify_burn(BURN, unknown_demand)
    assert (result.kind, result.evidence) == (BurnKind.CH, (Evidence.FLOW_WITHIN_SETPOINT,))
    # Evidence the same way twice is no conflict: heating.
    both = DhwInputs(
        flow=Series([(0, 44.0)]), ch_setpoint=Series([(0, 45.0)]), zone_demand=Series([(0, True)])
    )
    assert classify_burn(BURN, both).kind is BurnKind.CH
    assert classify_burn(BURN, DhwInputs(zone_demand=None)).kind is BurnKind.UNKNOWN
