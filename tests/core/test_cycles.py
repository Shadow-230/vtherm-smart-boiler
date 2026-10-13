"""Burner cycles: burns, pauses, seen edges and DHW classification."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.cycles import (
    Burn,
    BurnKind,
    ClassifiedBurn,
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


# --- Mutation testing (2026-10-12): edges, boundaries and the burn kept in every result ---


def test_a_burn_cut_by_the_window_start_has_no_seen_start() -> None:
    """Negative: a burn already on when the window opens has no seen start, even when the
    flame is off at the window's end — the last stretch is not the one before the first."""
    series = flame((0, True), (10, False))
    assert find_burns(series, 0, 20 * MIN) == [Burn(0, 10 * MIN, False, True)]


@pytest.mark.parametrize(
    "inputs",
    [
        DhwInputs(dhw_active=Series([(0, True)])),
        DhwInputs(),
    ],
)
def test_a_zero_length_burn_is_unknown_with_no_confidence(inputs: DhwInputs) -> None:
    """Negative: a burn of no length decides nothing, whatever the signals say; it is still the
    burn the result is about."""
    zero = Burn(5.0, 5.0, True, True)
    assert classify_burn(zero, inputs) == ClassifiedBurn(zero, BurnKind.UNKNOWN, 0.0)


def test_a_burn_of_one_second_is_classified() -> None:
    """Any burn longer than zero is classified from its signals."""
    short = Burn(0, 1.0, True, True)
    result = classify_burn(short, DhwInputs(dhw_active=Series([(0, True)])))
    assert (result.burn, result.kind) == (short, BurnKind.DHW)


def test_a_signal_known_for_exactly_half_the_burn_decides() -> None:
    """A DHW signal known for half the burn is enough, its confidence scaled by that coverage;
    known for 80 %, the confidence is 0.8."""
    half = classify_burn(BURN, DhwInputs(dhw_active=Series([(0, None), (5 * MIN, True)])))
    assert (half.kind, half.evidence) == (BurnKind.DHW, (Evidence.DHW_SIGNAL,))
    assert half.confidence == pytest.approx(0.5)
    most = classify_burn(BURN, DhwInputs(dhw_active=Series([(0, None), (2 * MIN, True)])))
    assert most.confidence == pytest.approx(0.8)


def test_a_poorly_known_dhw_signal_leaves_the_ch_signal_to_decide() -> None:
    """Negative: a DHW signal known for too little of the burn is skipped, and the CH signal
    still decides."""
    inputs = DhwInputs(
        dhw_active=Series([(0, None), (8 * MIN, True)]), ch_active=Series([(0, True)])
    )
    result = classify_burn(BURN, inputs)
    assert (result.kind, result.evidence) == (BurnKind.CH, (Evidence.CH_SIGNAL,))
    assert result.confidence == pytest.approx(0.9)


def test_a_dhw_signal_on_for_exactly_half_the_burn_is_hot_water() -> None:
    """A tie on the DHW signal counts as hot water, at half confidence."""
    result = classify_burn(BURN, DhwInputs(dhw_active=Series([(0, True), (5 * MIN, False)])))
    assert (result.kind, result.confidence) == (BurnKind.DHW, pytest.approx(0.5))


@pytest.mark.parametrize("flow", [67.0, 70.0])
def test_flow_within_the_margin_above_max_ch_is_no_evidence(flow: float) -> None:
    """Negative: the flow above the maximum CH setpoint but not beyond it plus the margin —
    up to and including it — is no sign of hot water."""
    inputs = DhwInputs(flow=Series([(0, flow)]), max_ch_setpoint=65.0)
    result = classify_burn(BURN, inputs)
    assert (result.kind, result.evidence) == (BurnKind.UNKNOWN, ())


@pytest.mark.parametrize(
    ("flow", "kind"),
    [
        (Series([(0, None), (5 * MIN, 78.0)]), BurnKind.DHW),  # known for half: decides
        (Series([(0, None), (9 * MIN, 78.0)]), BurnKind.UNKNOWN),  # known for a tenth: not
    ],
)
def test_flow_above_max_ch_needs_half_the_burn_known(flow: Series[float], kind: BurnKind) -> None:
    """Negative: the flow above the maximum CH setpoint counts only when the flow is known for
    at least half the burn."""
    result = classify_burn(BURN, DhwInputs(flow=flow, max_ch_setpoint=65.0))
    assert result.kind is kind
    assert result.burn == BURN


@pytest.mark.parametrize(
    ("demand", "kind"),
    [
        (Series([(0, None), (5 * MIN, False)]), BurnKind.DHW),  # known for half: no demand
        (Series([(0, None), (9 * MIN, False)]), BurnKind.UNKNOWN),  # known for a tenth: none
        (Series([(0, False), (MIN, True), (MIN + 1, False)]), BurnKind.CH),  # a second of it
    ],
)
def test_zone_demand_needs_half_the_burn_known_and_any_demand_counts(
    demand: Series[bool], kind: BurnKind
) -> None:
    """Negative: the zones' demand is evidence only when known for at least half the burn; a
    zone asking for a single second of it is demand."""
    assert classify_burn(BURN, DhwInputs(zone_demand=demand)).kind is kind


def test_conflicting_evidence_is_unknown_with_no_confidence() -> None:
    """Negative (P-28): a conflict that decides nothing has confidence 0, and keeps the burn
    and its evidence."""
    inputs = DhwInputs(
        flow=Series([(0, 44.0)]),
        ch_setpoint=Series([(0, 45.0)]),
        zone_demand=Series([(0, False)]),
    )
    expected = (Evidence.FLOW_WITHIN_SETPOINT, Evidence.NO_ZONE_DEMAND)
    assert classify_burn(BURN, inputs) == ClassifiedBurn(BURN, BurnKind.UNKNOWN, 0.0, expected)


def test_inferred_results_keep_their_burn() -> None:
    """An inferred hot-water or heating result is about the burn it classified."""
    dhw = classify_burn(BURN, DhwInputs(zone_demand=Series([(0, False)])))
    ch = classify_burn(BURN, DhwInputs(zone_demand=Series([(0, True)])))
    assert (dhw.burn, dhw.kind) == (BURN, BurnKind.DHW)
    assert (ch.burn, ch.kind, ch.confidence) == (BURN, BurnKind.CH, pytest.approx(0.6))


SETPOINT = Series([(0, 45.0)])


@pytest.mark.parametrize(
    ("flow", "setpoint", "evidence"),
    [
        # Exactly at setpoint plus margin is within it.
        (Series([(0, 50.0)]), SETPOINT, Evidence.FLOW_WITHIN_SETPOINT),
        # Above for exactly half the burn: above; a second less: within.
        (Series([(0, 70.0), (5 * MIN, 44.0)]), SETPOINT, Evidence.FLOW_ABOVE_SETPOINT),
        (Series([(0, 70.0), (5 * MIN - 1, 44.0)]), SETPOINT, Evidence.FLOW_WITHIN_SETPOINT),
        # Above for a minute only: within.
        (Series([(0, 70.0), (MIN, 44.0)]), SETPOINT, Evidence.FLOW_WITHIN_SETPOINT),
        # Above in two stretches that make most of the burn together.
        (
            Series([(0, 70.0), (3 * MIN, 71.0), (6 * MIN, 44.0)]),
            SETPOINT,
            Evidence.FLOW_ABOVE_SETPOINT,
        ),
        # The flow unknown at first, then known and above.
        (Series([(0, None), (2 * MIN, 70.0)]), SETPOINT, Evidence.FLOW_ABOVE_SETPOINT),
        # Known for exactly half the burn: decides.
        (Series([(0, None), (5 * MIN, 70.0)]), SETPOINT, Evidence.FLOW_ABOVE_SETPOINT),
        # The setpoint unknown at first, then known.
        (Series([(0, 70.0)]), Series([(0, None), (2 * MIN, 45.0)]), Evidence.FLOW_ABOVE_SETPOINT),
        # The setpoint changing within the burn: every part counts.
        (Series([(0, 70.0)]), Series([(0, 45.0), (8 * MIN, 46.0)]), Evidence.FLOW_ABOVE_SETPOINT),
    ],
)
def test_flow_against_setpoint_over_the_burn(
    flow: Series[float], setpoint: Series[float], evidence: Evidence
) -> None:
    """The share of the burn with the flow above the CH setpoint plus the margin, over the time
    both are known: half or more is above, less is within."""
    result = classify_burn(BURN, DhwInputs(flow=flow, ch_setpoint=setpoint))
    assert result.evidence == (evidence,)
