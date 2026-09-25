"""Metrics: cycle statistics, condensing share, degree-days, gas and outdoor bins."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.cycles import (
    Burn,
    BurnKind,
    ClassifiedBurn,
    DhwInputs,
    classify_burns,
    find_burns,
)
from custom_components.vtherm_smart_boiler.core.metrics import (
    DHW_KINDS,
    Consumption,
    DegreeDays,
    ModulationScale,
    binned_cycle_stats,
    condensing_share,
    cycle_stats,
    degree_days,
    integrate_rate,
    meter_consumption,
    outdoor_bins,
    per_degree_day,
    rate_at,
)
from custom_components.vtherm_smart_boiler.core.series import Series, known_duration

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0


def ch(start_min: float, end_min: float, seen: bool = True) -> ClassifiedBurn:
    return ClassifiedBurn(Burn(start_min * MIN, end_min * MIN, seen, seen), BurnKind.CH, 1.0)


def dhw(start_min: float, end_min: float) -> ClassifiedBurn:
    return ClassifiedBurn(Burn(start_min * MIN, end_min * MIN, True, True), BurnKind.DHW, 1.0)


def test_cycle_stats_for_heating() -> None:
    burns = [ch(0, 5), ch(20, 40), ch(60, 68), dhw(80, 100), ch(110, 120, seen=False)]
    stats = cycle_stats(burns, observed_s=2 * HOUR)
    assert stats.starts == 3
    assert stats.starts_per_hour == pytest.approx(1.5)
    assert stats.complete_burns == 3
    assert stats.median_burn_s == 8 * MIN
    assert stats.p10_burn_s == 5 * MIN
    assert stats.p90_burn_s == 20 * MIN
    assert stats.short_burns == 2
    assert stats.short_burn_share == pytest.approx(2 / 3)
    assert stats.burn_s == 43 * MIN


def test_cycle_stats_for_dhw_and_empty() -> None:
    burns = [ch(0, 5), dhw(80, 100)]
    assert cycle_stats(burns, HOUR, kinds=DHW_KINDS).starts == 1
    empty = cycle_stats([], 0.0)
    assert empty.starts_per_hour is None
    assert empty.median_burn_s is None
    assert empty.short_burn_share is None


def test_unknown_burns_count_as_heating() -> None:
    unknown = ClassifiedBurn(Burn(0, 20 * MIN, True, True), BurnKind.UNKNOWN, 0.0)
    assert cycle_stats([unknown], HOUR).starts == 1


def test_condensing_share_uses_known_return_during_heating_burns() -> None:
    return_temp = Series([(0, 40.0), (5 * MIN, 58.0), (10 * MIN, None)])
    burns = [ch(0, 20), dhw(0, 20)]
    share = condensing_share(return_temp, burns)
    assert share.basis_s == 10 * MIN
    assert share.value == pytest.approx(0.5)
    assert condensing_share(Series[float](), burns).value is None


def test_degree_days_integrate_over_known_time() -> None:
    outdoor = Series([(0, 5.0), (DAY / 2, 25.0), (DAY, None)])
    days = degree_days(outdoor, base=15.0, start=0.0, end=2 * DAY)
    assert days.value == pytest.approx(5.0)  # 10 K for half a day, nothing above the base
    assert days.coverage == pytest.approx(0.5)
    assert days.estimated_total() is None  # too little coverage
    assert days.estimated_total(min_coverage=0.5) == pytest.approx(10.0)


def test_meter_consumption_with_reset_and_gap() -> None:
    meter = Series([(0, 100.0), (10, 102.5), (20, None), (30, 104.0), (40, 1.0), (50, 1.5)])
    assert meter_consumption(meter, 0, 60) == Consumption(pytest.approx(5.5), True)


def test_meter_consumption_completeness() -> None:
    meter = Series([(10, 100.0), (20, 101.0)])
    assert meter_consumption(meter, 0, 30) == Consumption(1.0, False)  # unknown at start
    tail_gap = Series([(0, 100.0), (20, None)])
    assert meter_consumption(tail_gap, 0, 30) == Consumption(0.0, False)
    assert meter_consumption(Series([(0, None)]), 0, 30) is None


@pytest.mark.parametrize(
    ("modulation", "scale", "expected"),
    [
        (0.0, ModulationScale.RANGE, 1.0),
        (50.0, ModulationScale.RANGE, 2.0),
        (100.0, ModulationScale.RANGE, 3.0),
        (150.0, ModulationScale.RANGE, 3.0),
        (10.0, ModulationScale.CAPACITY, 1.0),
        (50.0, ModulationScale.CAPACITY, 1.5),
    ],
)
def test_rate_at(modulation: float, scale: ModulationScale, expected: float) -> None:
    assert rate_at(modulation, at_min=1.0, at_max=3.0, scale=scale) == pytest.approx(expected)


def test_integrate_rate_while_burning() -> None:
    flame = Series([(0, True), (HOUR, False), (2 * HOUR, True), (3 * HOUR, False)])
    modulation = Series([(0, 0.0), (2 * HOUR, 100.0)])
    result = integrate_rate(flame, modulation, 1.0, 3.0, ModulationScale.RANGE, 0, 4 * HOUR)
    assert result == Consumption(pytest.approx(4.0), True)


def test_integrate_rate_marks_unknown_modulation() -> None:
    flame = Series([(0, True), (HOUR, False)])
    modulation = Series([(0, 50.0), (HOUR / 2, None)])
    result = integrate_rate(flame, modulation, 1.0, 3.0, ModulationScale.RANGE, 0, HOUR)
    assert result == Consumption(pytest.approx(1.0), False)


def test_per_degree_day() -> None:
    full = DegreeDays(10.0, DAY, DAY)
    assert per_degree_day(25.0, full) == pytest.approx(2.5)
    assert per_degree_day(25.0, DegreeDays(0.1, DAY, DAY)) is None
    assert per_degree_day(25.0, DegreeDays(10.0, DAY / 4, DAY)) is None


def test_outdoor_bins() -> None:
    outdoor = Series([(0, -3.0), (10, 2.0), (20, None), (30, -1.0)])
    bins = outdoor_bins(outdoor, 0, 40, width=5.0)
    assert [(b.low, b.intervals) for b in bins] == [(-5.0, ((0, 10), (30, 40))), (0.0, ((10, 20),))]


def test_binned_cycle_stats_attribute_burns_by_start() -> None:
    flame = Series(
        [(0, False), (10 * MIN, True), (15 * MIN, False), (70 * MIN, True), (100 * MIN, False)]
    )
    outdoor = Series([(0, 8.0), (HOUR, -2.0)])
    burns = classify_burns(
        find_burns(flame, 0, 2 * HOUR), DhwInputs(dhw_active=Series([(0, False)]))
    )
    stats = binned_cycle_stats(burns, flame, outdoor, 0, 2 * HOUR)
    assert set(stats) == {5.0, -5.0}
    assert stats[5.0].starts == 1
    assert stats[5.0].median_burn_s == 5 * MIN
    assert stats[5.0].observed_s == known_duration(flame, 0, HOUR)
    assert stats[-5.0].starts == 1
    assert stats[-5.0].median_burn_s == 30 * MIN


def test_starts_per_hour_count_the_hours_with_heating() -> None:
    """P49: four starts within one hour of an otherwise quiet day are four an hour, not a
    sixth of one."""
    burns = [ch(600 + 15 * k, 600 + 15 * k + 5) for k in range(4)]
    stats = cycle_stats(burns, observed_s=DAY)
    assert stats.active_s == HOUR
    assert stats.starts_per_hour == pytest.approx(4.0)
    assert cycle_stats([], observed_s=DAY).starts_per_hour is None
