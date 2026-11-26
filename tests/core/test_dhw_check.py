"""I13.5: the hot-water self-check — gas classed as hot water should not follow the weather."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.daily import DaySummary
from custom_components.vtherm_smart_boiler.core.dhw_check import (
    MIN_DAYS,
    MIN_SLOPE_SHARE,
    MIN_T,
    check_dhw_split,
)

DAY = 86400.0


def day(
    index: int, outdoor: float | None, dhw: float | None, *, observed: float = 1.0
) -> DaySummary:
    start = index * DAY
    return replace(
        DaySummary.empty(start, start + DAY),
        observed_s=observed * DAY,
        outdoor_mean=outdoor,
        dhw_gas=dhw,
    )


def month(gas: list[float] | None = None, count: int = 30) -> list[DaySummary]:
    """``count`` days over −2…14 °C (a 16 K spread), hot water 1.0 a day, each off by ±0.1 in
    turn, unless ``gas`` gives each day's."""
    temperatures = [-2.0 + 16.0 * i / (count - 1) for i in range(count)]
    amounts = gas or [1.0 + (0.1 if i % 2 else -0.1) for i in range(count)]
    return [day(i, t, g) for i, (t, g) in enumerate(zip(temperatures, amounts, strict=True))]


def test_hot_water_that_does_not_follow_the_weather_is_no_finding() -> None:
    check = check_dhw_split(month())
    assert check is not None
    assert check.days == 30
    assert not check.suspect
    assert abs(check.slope_share) < MIN_SLOPE_SHARE


def test_heating_counted_as_hot_water_shows_as_a_clear_slope() -> None:
    """Hot water of 1.0 a day plus heating burns counted with it — 0.2 a day for each kelvin
    below 14 °C: falling about 10 % of the mean per kelvin, far past 3 standard errors."""
    temperatures = [-2.0 + 16.0 * i / 29 for i in range(30)]
    gas = [1.0 + 0.2 * (14.0 - t) + (0.1 if i % 2 else -0.1) for i, t in enumerate(temperatures)]
    check = check_dhw_split(month(gas))
    assert check is not None
    assert check.suspect
    assert check.slope_share < -MIN_SLOPE_SHARE
    assert check.t < -MIN_T


def test_colder_mains_water_alone_is_no_finding() -> None:
    """Hot water a third dearer in winter than in summer (about 1.3 % per kelvin over 25 K):
    clear, but under 3 % a kelvin — the mains water, not a wrong split."""
    temperatures = [-2.0 + 16.0 * i / 29 for i in range(30)]
    gas = [1.0 * (1 - 0.013 * (t - 6.0)) for t in temperatures]
    check = check_dhw_split(month(gas))
    assert check is not None
    assert abs(check.t) > MIN_T  # clear: the days lie on the line
    assert not check.suspect


def test_a_slope_with_no_scatter_at_all_is_as_clear_as_can_be() -> None:
    """Days exactly on a falling line: no error, the slope infinitely clear — a finding."""
    days = [day(i, -2.0 + 0.5 * i, 10.0 - 0.5 * (-2.0 + 0.5 * i)) for i in range(32)]
    check = check_dhw_split(days)
    assert check is not None
    assert check.t == -math.inf
    assert check.suspect


def test_hot_water_counted_as_heating_in_the_cold_shows_too() -> None:
    """The other way round: hot water lost to heating on cold days rises with the outdoor
    temperature — as clear a finding."""
    temperatures = [-2.0 + 16.0 * i / 29 for i in range(30)]
    gas = [0.4 + 0.05 * (t + 2.0) + (0.02 if i % 2 else -0.02) for i, t in enumerate(temperatures)]
    check = check_dhw_split(month(gas))
    assert check is not None
    assert check.suspect
    assert check.slope_share > MIN_SLOPE_SHARE


@pytest.mark.parametrize(
    "days",
    [
        month(count=MIN_DAYS - 1),  # too few days
        [day(i, 5.0 + (i % 8), 1.0) for i in range(30)],  # 7 K of spread: too little
        month([0.0] * 30),  # no hot water at all
    ],
)
def test_days_that_cannot_carry_the_check_give_none(days: list[DaySummary]) -> None:
    assert check_dhw_split(days) is None


def test_only_days_known_whole_count() -> None:
    """A day without its hot-water gas or outdoor mean, mostly unseen, or with no length is
    left out — here leaving 27 days, one short."""
    days = month(count=MIN_DAYS)
    days[0] = replace(days[0], dhw_gas=None)
    days[1] = replace(days[1], outdoor_mean=None)
    days[2] = replace(days[2], observed_s=0.5 * DAY)
    days.append(replace(days[3], start=99 * DAY, end=99 * DAY))
    assert check_dhw_split(days) is None
    assert check_dhw_split(month(count=MIN_DAYS)) is not None


def test_flat_days_exactly_on_a_line_are_no_finding() -> None:
    check = check_dhw_split(month([1.0] * 30))
    assert check is not None
    assert (check.t, check.slope_share, check.suspect) == (0.0, 0.0, False)
