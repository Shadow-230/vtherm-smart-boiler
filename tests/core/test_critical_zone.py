"""Critical zone per circuit."""

from __future__ import annotations

from itertools import pairwise

import pytest

from custom_components.vtherm_smart_boiler.core.critical_zone import (
    BACK_K,
    READING_S,
    WARMING_K,
    WARMING_S,
    CriticalZone,
    WindowHold,
    _clearly_worse,
    critical_zone,
    follow_window,
    keep_readings,
    rise,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.zones import SelectionStatus

NOW = 1000.0
AGE = 600.0


def zone(zid: str, temp: float, target: float, demand: float | None, **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    return ZoneState(zid, temperature=temp, target=target, valve_open=demand, reported_at=NOW, **kw)


def pick(zones, previous=None) -> CriticalZone:
    return critical_zone("c", zones, NOW, AGE, previous=previous)


def test_highest_demand_wins() -> None:
    result = pick([zone("a", 20.0, 21.0, 0.4), zone("b", 20.8, 21.0, 0.9)])
    assert result == CriticalZone("c", SelectionStatus.OK, "b", 0.9, pytest.approx(0.2), False)


def test_deficit_breaks_ties_between_full_valves_and_marks_saturation() -> None:
    result = pick([zone("a", 20.0, 21.0, 1.0), zone("b", 19.0, 21.0, 1.0)])
    assert result.zone_id == "b"
    assert result.saturated


def test_fully_open_but_warm_enough_is_not_saturated() -> None:
    assert not pick([zone("a", 21.2, 21.0, 1.0)]).saturated


def test_zones_without_demand_fall_back_to_deficit() -> None:
    result = pick([zone("a", 20.0, 21.0, None), zone("b", 19.0, 21.0, None)])
    assert result.zone_id == "b"
    assert result.demand is None
    assert not result.saturated


def test_hysteresis_on_demand_and_deficit() -> None:
    first = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 20.0, 21.0, 0.7)])
    assert first.zone_id == "a"
    close = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 20.0, 21.0, 0.85)], previous=first)
    assert close.zone_id == "a"
    clear = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 20.0, 21.0, 0.95)], previous=first)
    assert clear.zone_id == "b"
    deeper = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 19.5, 21.0, 0.85)], previous=first)
    assert deeper.zone_id == "b"  # same demand band, clearly colder


def test_known_demand_beats_unknown_and_keeps_its_place() -> None:
    unknown_first = pick([zone("a", 19.0, 21.0, None)])
    result = pick([zone("a", 19.0, 21.0, None), zone("b", 20.9, 21.0, 0.3)], previous=unknown_first)
    assert result.zone_id == "b"
    back = pick([zone("a", 19.0, 21.0, None), zone("b", 20.9, 21.0, 0.3)], previous=result)
    assert back.zone_id == "b"


def test_no_zone_states() -> None:
    assert pick([]).status is SelectionStatus.NO_ACTIVE_ZONE
    off = zone("a", 20.0, 21.0, 0.5, heating_enabled=False)
    assert pick([off]).status is SelectionStatus.NO_ACTIVE_ZONE
    stale = ZoneState("a", 20.0, 21.0, heating_enabled=True, reported_at=NOW - 2 * AGE)
    assert pick([stale]) == CriticalZone("c", SelectionStatus.NO_VALID_MEASUREMENT)


def test_within_the_demand_margin_the_colder_zone_wins() -> None:
    """P61: as the docstring says — among zones with about the same demand, the one furthest
    below its setpoint."""
    result = pick([zone("a", 20.8, 21.0, 0.85), zone("b", 19.5, 21.0, 0.8)])
    assert result.zone_id == "b"


def test_a_zone_at_vts_cap_is_as_open_as_it_gets() -> None:
    """P61: one meaning of "fully open" — VT's cap on the duty cycle counts, as in control."""
    capped = ZoneState("a", 19.0, 21.0, True, on_percent=0.8, max_on_percent=0.8, reported_at=NOW)
    assert pick([capped]).saturated


def test_the_hysteresis_compares_demand_before_deficit() -> None:
    """The comparison behind the hysteresis, on its own: a candidate with a clearly lower demand,
    or with no demand beside a known one, never needs heat more, however cold its room; one with
    a known demand beside an unknown one does."""
    current = zone("a", 20.0, 21.0, 0.8)
    assert not _clearly_worse(zone("b", 15.0, 21.0, 0.5), current, 0.1, 0.3)
    assert not _clearly_worse(zone("b", 15.0, 21.0, None), current, 0.1, 0.3)
    assert _clearly_worse(zone("b", 20.0, 21.0, 0.8), zone("a", 20.0, 21.0, None), 0.1, 0.3)


def test_saturated_is_judged_against_vts_setpoint() -> None:
    """I12.9 (G11 C removed): fully open, a room 0.2 K over VT's setpoint is warm enough,
    whatever its algorithm; one 0.1 K under it is saturated."""
    over = zone("a", 21.2, 21.0, 1.0)
    assert not pick([over]).saturated
    assert pick([over]).deficit == pytest.approx(-0.2)
    assert pick([zone("a", 20.9, 21.0, 1.0)]).saturated


# --- Mutation testing (2026-10-12): demand and deficit bounds, ties by deficit, lost zone ---


def test_a_demand_exactly_one_margin_higher_is_not_clearly_worse() -> None:
    """Negative: a candidate exactly one demand margin above the current zone is still in its
    band — only a colder room could make it clearly worse."""
    current = zone("a", 20.0, 21.0, 0.5)
    assert not _clearly_worse(zone("b", 20.0, 21.0, 0.75), current, 0.25, 0.3)


def test_a_demand_exactly_one_margin_lower_still_compares_deficits() -> None:
    """A candidate exactly one demand margin below the current zone is still in its band: a
    clearly colder room makes it clearly worse."""
    current = zone("a", 21.0, 21.0, 0.5)
    assert _clearly_worse(zone("b", 19.0, 21.0, 0.25), current, 0.25, 0.3)


def test_a_deficit_exactly_one_margin_deeper_is_not_clearly_worse() -> None:
    """Negative: in the same demand band, a room exactly one deficit margin colder does not take
    the place of the current zone."""
    current = zone("a", 20.5, 21.0, 0.5)
    assert not _clearly_worse(zone("b", 20.0, 21.0, 0.5), current, 0.1, 0.5)


def test_a_zone_exactly_one_margin_below_the_top_demand_is_in_the_band() -> None:
    """The band of "about the same demand" includes its edge: the colder zone exactly one margin
    below the highest demand wins."""
    zones = [zone("a", 20.8, 21.0, 0.75), zone("b", 19.0, 21.0, 0.5)]
    assert critical_zone("c", zones, NOW, AGE, demand_margin=0.25).zone_id == "b"


@pytest.mark.parametrize("demand", [None, 0.8, 1.0])
def test_the_colder_zone_wins_whatever_its_name(demand: float | None) -> None:
    """In one demand band the deficit decides, not the order of the zone names."""
    result = pick([zone("a", 19.0, 21.0, demand), zone("b", 20.5, 21.0, demand)])
    assert result.zone_id == "a"


def test_a_previous_critical_zone_no_longer_eligible_is_replaced() -> None:
    """Negative: when the previous critical zone is gone from the eligible zones (stale, off),
    the hysteresis has nothing to keep and the best remaining zone is picked."""
    previous = CriticalZone("c", SelectionStatus.OK, "gone", 0.9, 1.0, False)
    result = pick([zone("a", 20.0, 21.0, 0.4)], previous=previous)
    assert result == CriticalZone("c", SelectionStatus.OK, "a", 0.4, pytest.approx(1.0), False)


def test_fully_open_exactly_at_the_setpoint_is_not_saturated() -> None:
    """Negative: a fully open zone exactly at its setpoint is not short of heat — no saturation."""
    result = pick([zone("a", 21.0, 21.0, 1.0)])
    assert result.zone_id == "a"
    assert not result.saturated


def test_a_room_whose_temperature_is_not_trusted_is_never_the_critical_zone() -> None:
    """I12, decision 8: VT's safety mode, its thermometer lost or no measurement since the
    plugin's start keeps the room out, however open its valve."""
    blind = zone("a", 18.0, 21.0, 1.0, room_sensor_lost=True)
    assert pick([blind, zone("b", 20.5, 21.0, 0.5)]).zone_id == "b"
    assert pick([blind]).status is SelectionStatus.NO_VALID_MEASUREMENT


# --- I12.10: the window rule (gap 1 item 4, gap 22) ---------------------------------------------


def test_the_window_rules_values() -> None:
    """The user's decision of 2026-11-25: 0.2 K in 30 minutes is warming; 0.3 K is back."""
    assert (WARMING_K, WARMING_S, BACK_K) == (0.2, 1800.0, 0.3)


def test_a_room_held_off_by_its_window_is_neither_critical_nor_saturated() -> None:
    """The fullest, coldest room has its window open: another room is picked, and none is
    saturated; with only that room, none is critical."""
    open_window = zone("a", 18.0, 21.0, 1.0)
    other = zone("b", 20.8, 21.0, 0.5)
    result = critical_zone("c", [open_window, other], NOW, AGE, held={"a"})
    assert result.zone_id == "b"
    assert not result.saturated
    alone = critical_zone("c", [open_window], NOW, AGE, held={"a"})
    assert alone == CriticalZone("c", SelectionStatus.NO_VALID_MEASUREMENT)
    kept = critical_zone("c", [open_window, other], NOW, AGE, pick([open_window]), held={"a"})
    assert kept.zone_id == "b"  # the previous critical zone is not kept while held


def test_readings_are_kept_a_minute_apart_and_for_the_rise_only() -> None:
    """A reading at most every ``READING_S``; none while unknown; the oldest kept is the newest
    at or before the span's start; one later than now (a clock set back) goes."""
    readings: tuple = ()
    for t in range(0, 2401, 30):
        readings = keep_readings(readings, float(t), 20.0 + t / 10_000)
    assert all(b[0] - a[0] >= READING_S for a, b in pairwise(readings))
    assert readings[0][0] == 600.0  # 2400 - 1800: the newest at or before the start
    assert keep_readings(readings, 2460.0, None) == readings[1:]  # unknown: none added
    assert keep_readings(((3000.0, 20.0),), 2500.0, 19.0) == ((2500.0, 19.0),)


def test_the_rise_is_the_temperature_now_against_half_an_hour_ago() -> None:
    readings = ((0.0, 18.0), (900.0, 18.5), (1800.0, 19.0))
    assert rise(readings, 2000.0, 19.4) == pytest.approx(1.4)  # against 18.0 at 0 s
    assert rise(readings, 2700.0, 19.4) == pytest.approx(0.9)  # against 18.5 at 900 s
    assert rise(readings, 1700.0, 19.4) is None  # nothing half an hour old
    assert rise(readings, 2000.0, None) is None


def warming(start: float, end: float, at: float = 15.0, per_min: float = 0.05) -> tuple:
    """A room's readings every minute from ``start`` to ``end``, warming ``per_min`` K."""
    return tuple((t, at + per_min * (t - start) / 60) for t in range(int(start), int(end) + 1, 60))


def test_the_hold_off_runs_while_open_and_after_it_closes_while_the_room_warms_back() -> None:
    """Open: held. Closed at 0 s and warming 0.05 K a minute, far below its target: held past
    half an hour; within 0.3 K of the target: released at once."""
    hold = follow_window(WindowHold(), True, -60.0, (), 15.0, 21.0)
    assert hold == WindowHold(open=True)
    hold = follow_window(hold, False, 0.0, (), 15.0, 21.0)
    assert hold == WindowHold(closed_at=0.0)
    readings = warming(-600.0, 2400.0)
    hold = follow_window(hold, False, 2400.0, readings, readings[-1][1], 21.0)
    assert hold.held  # rose 1.5 K in the last half hour
    assert follow_window(hold, False, 2460.0, readings, 20.8, 21.0) == WindowHold()


def test_the_hold_off_ends_once_the_room_stops_warming() -> None:
    """Closed at 0 s; at 40 minutes it rose 0.1 K over the last half hour: no longer warming,
    released, though still 3 K short."""
    readings = tuple((float(t), 18.0 + (0.1 if t >= 1800 else 0.0)) for t in range(0, 2401, 60))
    hold = follow_window(WindowHold(closed_at=0.0), False, 2400.0, readings, 18.1, 21.0)
    assert hold == WindowHold()
    assert not hold.held


def test_before_half_an_hour_closed_or_without_readings_the_hold_off_stays() -> None:
    """Warming cannot be told yet: closed 20 minutes, a flat room stays held; so does one whose
    readings do not reach half an hour back, or whose temperature is unknown."""
    flat = tuple((float(t), 18.0) for t in range(0, 1201, 60))
    assert follow_window(WindowHold(closed_at=0.0), False, 1200.0, flat, 18.0, 21.0).held
    recent = tuple((float(t), 18.0) for t in range(1800, 2401, 60))
    assert follow_window(WindowHold(closed_at=0.0), False, 2400.0, recent, 18.0, 21.0).held
    assert follow_window(WindowHold(closed_at=0.0), False, 2400.0, flat, None, 21.0).held


def test_no_hold_off_without_a_window_and_a_clock_set_back_counts_from_now() -> None:
    assert follow_window(WindowHold(), False, 100.0, (), 15.0, 21.0) == WindowHold()
    back = follow_window(WindowHold(closed_at=5000.0), False, 100.0, (), 15.0, 21.0)
    assert back == WindowHold(closed_at=100.0)
