"""Principle 13's rules 3 and 5 for the comfort correction (decision 11 of 0.2.3, SB-11)."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.comfort_rules import (
    EXTREME_RATE_K_PER_H,
    HOUR,
    OUTDOOR_SAMPLE_S,
    OUTDOOR_WINDOW_S,
    STARTS_WINDOW_S,
    StartsBaseline,
    extreme_weather,
    follow_baseline,
    follow_outdoor,
    heating_starts,
    may_rise,
    starts_rose,
)
from custom_components.vtherm_smart_boiler.core.cycles import Burn, BurnKind, ClassifiedBurn


def burn(start: float, kind: BurnKind = BurnKind.CH, seen: bool = True) -> ClassifiedBurn:
    return ClassifiedBurn(Burn(start, start + 120.0, seen, True), kind, 1.0)


def test_the_values_are_provisional_and_kept_in_one_place() -> None:
    assert STARTS_WINDOW_S == 2 * HOUR
    assert EXTREME_RATE_K_PER_H == 2.0
    assert OUTDOOR_WINDOW_S == HOUR
    assert OUTDOOR_SAMPLE_S == 300.0


# --- Rule 3: the starts ---------------------------------------------------------------------


def test_heating_starts_leave_out_hot_water_and_unseen_starts_and_count_unknown_kinds() -> None:
    now = 10 * HOUR
    burns = [
        burn(now - 3 * HOUR),  # before the window
        burn(now - 90 * 60.0),
        burn(now - 60 * 60.0, BurnKind.DHW),  # a hot-water draw
        burn(now - 30 * 60.0, BurnKind.UNKNOWN),  # either: counted in both windows alike
        burn(now - 10 * 60.0, seen=False),  # its start not seen
        burn(now + 60.0),  # after now (a clock set back)
    ]
    assert heating_starts(burns, now) == (now - 90 * 60.0, now - 30 * 60.0)
    assert heating_starts([], now) == ()


def test_the_starts_rise_against_the_same_hours_before_it_began() -> None:
    began = 10 * HOUR
    baseline = StartsBaseline(began, before=(began - 50 * 60.0, began - 20 * 60.0))
    # Half an hour after it began: the half hour before held one start (at -20 min).
    assert not starts_rose(baseline, (began + 10 * 60.0,), began + 30 * 60.0)
    assert starts_rose(baseline, (began + 10 * 60.0, began + 25 * 60.0), began + 30 * 60.0)
    # An hour after: two before, two after — not risen; a third — risen.
    after = (began + 10 * 60.0, began + 40 * 60.0)
    assert not starts_rose(baseline, after, began + HOUR)
    assert starts_rose(baseline, (*after, began + 50 * 60.0), began + HOUR)


def test_the_hours_compared_stop_growing_at_the_window() -> None:
    began = 10 * HOUR
    baseline = StartsBaseline(began, before=(began - 3 * HOUR, began - 90 * 60.0))
    now = began + 5 * HOUR
    # The last two hours against the two hours before it began (the start 3 h before is out).
    assert not starts_rose(baseline, (now - HOUR,), now)
    assert starts_rose(baseline, (now - 3 * HOUR, now - HOUR, now - 30 * 60.0), now)


def test_nothing_rises_at_the_beginning_or_before_it() -> None:
    baseline = StartsBaseline(10 * HOUR, before=())
    assert not starts_rose(baseline, (10 * HOUR,), 10 * HOUR)
    assert not starts_rose(baseline, (9 * HOUR,), 9 * HOUR)  # a clock set back


def test_it_may_rise_only_with_the_starts_known_and_not_risen() -> None:
    began = 10 * HOUR
    baseline = StartsBaseline(began, before=())
    assert may_rise(None, (), began)  # the first rise: nothing to compare yet
    assert may_rise(baseline, (), began + HOUR)
    assert not may_rise(baseline, (began + 60.0,), began + HOUR)  # risen
    # Negatives: the starts unknown, or the clock set back before its beginning.
    assert not may_rise(None, None, began)
    assert not may_rise(baseline, None, began + HOUR)
    assert not may_rise(baseline, (), began - 60.0)


def test_the_baseline_is_kept_until_the_correction_stays_at_zero_for_the_window() -> None:
    baseline = StartsBaseline(10 * HOUR, before=(9 * HOUR,))
    now = 12 * HOUR
    assert follow_baseline(None, 0.0, now) is None
    assert follow_baseline(baseline, 1.0, now) == baseline
    at_zero = follow_baseline(baseline, 0.0, now)
    assert at_zero == StartsBaseline(10 * HOUR, (9 * HOUR,), zero_since=now)
    # Rising again within the window continues it, against the same hours before it began.
    assert follow_baseline(at_zero, 0.5, now + HOUR) == baseline
    assert follow_baseline(at_zero, 0.0, now + HOUR) == at_zero
    assert follow_baseline(at_zero, 0.0, now + STARTS_WINDOW_S) is None
    # A clock set back counts from the step that sees it.
    assert follow_baseline(at_zero, 0.0, now - HOUR) == StartsBaseline(
        10 * HOUR, (9 * HOUR,), zero_since=now - HOUR
    )


# --- Rule 5: extreme weather ----------------------------------------------------------------


def readings(start: float, values: list[float]) -> tuple[tuple[float, float], ...]:
    seen: tuple[tuple[float, float], ...] = ()
    for index, value in enumerate(values):
        seen = follow_outdoor(seen, value, start + index * OUTDOOR_SAMPLE_S)
    return seen


def test_readings_are_kept_one_per_sample_for_the_hour_and_the_one_before_it() -> None:
    seen = follow_outdoor((), 5.0, 0.0)
    assert seen == ((0.0, 5.0),)
    assert follow_outdoor(seen, 6.0, 60.0) == seen  # within a sample's time: not kept
    assert follow_outdoor(seen, None, OUTDOOR_SAMPLE_S) == seen  # unknown: nothing kept
    seen = readings(0.0, [5.0] * 20)  # 95 minutes
    times = [t for t, _v in seen]
    now = times[-1]
    assert now - times[0] > OUTDOOR_WINDOW_S  # the hour covered by the one before it
    assert now - times[1] <= OUTDOOR_WINDOW_S
    # Older than two hours, or after a clock set back: dropped.
    assert follow_outdoor(seen, None, now + 3 * HOUR) == ()
    kept = (1800.0, 2100.0, 2400.0, 2700.0, 3000.0)
    assert follow_outdoor(seen, None, 3000.0) == tuple((t, 5.0) for t in kept)


def test_steady_weather_is_not_extreme_once_an_hour_is_read() -> None:
    seen = readings(0.0, [5.0] * 13)  # 0 to 60 minutes
    now = seen[-1][0]
    assert not extreme_weather(seen, 5.0, now, design_outdoor=-15.0)
    # A change of 2 K within the hour is not faster than 2 K per hour; more is.
    assert not extreme_weather(readings(0.0, [5.0 - k / 6 for k in range(13)]), 3.0, now, -15.0)
    assert extreme_weather(readings(0.0, [5.0 - k / 5 for k in range(13)]), 2.6, now, -15.0)
    # A rise counts as a fall does.
    assert extreme_weather(readings(0.0, [5.0 + k / 5 for k in range(13)]), 7.4, now, -15.0)


def test_below_the_design_outdoor_temperature_is_extreme() -> None:
    seen = readings(0.0, [-16.0] * 13)
    now = seen[-1][0]
    assert extreme_weather(seen, -16.0, now, design_outdoor=-15.0)
    assert not extreme_weather(readings(0.0, [-15.0] * 13), -15.0, now, design_outdoor=-15.0)


def test_unknown_weather_freezes() -> None:
    seen = readings(0.0, [5.0] * 13)
    now = seen[-1][0]
    assert extreme_weather(seen, None, now, -15.0)  # no reading now
    assert extreme_weather((), 5.0, now, -15.0)  # none kept
    # Less than an hour of readings: the rate cannot be judged yet.
    short = readings(0.0, [5.0] * 12)
    assert extreme_weather(short, 5.0, short[-1][0], -15.0)


@pytest.mark.parametrize("rate", [0.5, 1.9])
def test_a_slow_change_over_two_hours_is_not_extreme(rate: float) -> None:
    values = [5.0 - rate * k * OUTDOOR_SAMPLE_S / HOUR for k in range(25)]
    seen = readings(0.0, values)
    assert not extreme_weather(seen, values[-1], seen[-1][0], -15.0)


# --- Mutation testing (2026-10-12): the windows' exact bounds -------------------------------


def test_a_start_at_this_step_or_exactly_the_window_ago_is_a_heating_start() -> None:
    """Both ends of the window count: a burn seen to begin at this very step, or exactly
    ``window_s`` before it; a second older is out."""
    now = 10 * HOUR
    burns = [burn(now), burn(now - STARTS_WINDOW_S), burn(now - STARTS_WINDOW_S - 1.0)]
    assert heating_starts(burns, now) == (now - STARTS_WINDOW_S, now)


def test_the_starts_compared_include_their_edges() -> None:
    """A start at the correction's beginning or at this step counts as after it; one exactly
    the compared span before its beginning counts as before it."""
    began = 10 * HOUR
    now = began + HOUR
    empty = StartsBaseline(began, before=())
    assert starts_rose(empty, (began,), now)
    assert starts_rose(empty, (now,), now)
    edge = StartsBaseline(began, before=(began - HOUR,))
    assert not starts_rose(edge, (began + 10 * 60.0,), now)  # one before, one after


def test_a_start_within_a_second_of_the_beginning_is_compared() -> None:
    """Any time after the beginning has hours to compare, however short: a start half a second
    after it, with none before, is a rise."""
    began = 10 * HOUR
    assert starts_rose(StartsBaseline(began, before=()), (began + 0.5,), began + 1.0)


def test_it_may_rise_at_its_very_beginning() -> None:
    """The clock at the correction's beginning is not before it: nothing to compare yet, so it
    may rise."""
    began = 10 * HOUR
    assert may_rise(StartsBaseline(began, before=()), (), began)


def test_a_reading_exactly_two_hours_old_is_kept() -> None:
    """None older than two hours is kept: one exactly two hours old is not older, and with
    nothing newer before the hour it is the one that shows the hour covered."""
    seen = ((0.0, 5.0),)
    assert follow_outdoor(seen, None, 2 * OUTDOOR_WINDOW_S) == seen
    assert follow_outdoor(seen, None, 2 * OUTDOOR_WINDOW_S + 1.0) == ()


@pytest.mark.parametrize("age", [OUTDOOR_WINDOW_S, 1800.0])
def test_a_spread_within_the_hour_is_extreme_at_wall_clock_times(age: float) -> None:
    """Negative: a reading within the last hour — exactly an hour old included — counts toward
    the spread at any wall-clock time: 3 K apart within the hour is extreme."""
    now = 1_760_000_000.0
    seen = ((now - OUTDOOR_WINDOW_S - OUTDOOR_SAMPLE_S, 5.0), (now - age, 2.0))
    assert extreme_weather(seen, 5.0, now, design_outdoor=-15.0)
