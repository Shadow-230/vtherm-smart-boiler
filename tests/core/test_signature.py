"""The energy signature (``docs/en/development/plans/plan-0.2-i10.md``, I10.7): each day's
heating gas against its mean outdoor temperature, the days the plugin only watched and the days
under control apart, each with its fitted line — by the building fit's own rules — and the two
compared where their temperatures overlap."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.daily import DaySummary
from custom_components.vtherm_smart_boiler.core.signature import (
    NoLine,
    energy_signature,
)

HOUR = 3600.0
DAY = 86400.0


def day(
    index: int,
    outdoor: float | None,
    gas: float | None,
    *,
    controlled: bool = False,
    hours: float = 24.0,
    observed: float = 1.0,
) -> DaySummary:
    start = index * DAY
    end = start + hours * HOUR
    return replace(
        DaySummary.empty(start, end),
        observed_s=observed * (end - start),
        outdoor_mean=outdoor,
        gas=gas,
        controlled_s=2 * HOUR if controlled else 0.0,
    )


def line_days(
    first: int, slope: float, intercept: float, temperatures: list[float], **kw: object
) -> list[DaySummary]:
    return [
        day(first + k, t, intercept + slope * t, **kw)  # type: ignore[arg-type]
        for k, t in enumerate(temperatures)
    ]


COLD = [-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]


def test_the_days_watched_and_under_control_are_fitted_apart() -> None:
    days = [
        *line_days(0, -0.8, 12.0, COLD),
        *line_days(20, -0.7, 10.5, COLD, controlled=True),
    ]
    signature = energy_signature(days, threshold=15.0)
    watched, control = signature.observing.line, signature.control.line
    assert watched is not None
    assert control is not None
    assert (watched.slope, watched.intercept) == (pytest.approx(-0.8), pytest.approx(12.0))
    assert (control.slope, control.intercept) == (pytest.approx(-0.7), pytest.approx(10.5))
    assert (watched.low, watched.high, watched.days) == (-6.0, 8.0, 8)
    assert watched.r_squared == pytest.approx(1.0)
    assert watched.balance == pytest.approx(15.0)  # where the heating gas reaches nothing
    assert [d.controlled for d in signature.days] == [False] * 8 + [True] * 8
    # Compared in the middle of the temperatures both share: at 1 °C.
    compared = signature.comparison
    assert compared is not None
    assert compared.outdoor == pytest.approx(1.0)
    assert (compared.observing, compared.control) == (pytest.approx(11.2), pytest.approx(9.8))
    assert compared.change == pytest.approx(9.8 / 11.2 - 1)


def test_warm_days_and_days_without_heating_gas_are_shown_not_fitted() -> None:
    days = [*line_days(0, -0.8, 12.0, COLD), day(30, 16.0, 0.4), day(31, 5.0, 0.0)]
    signature = energy_signature(days, threshold=15.0)
    assert [d.fitted for d in signature.days][-2:] == [False, False]
    assert signature.observing.line is not None
    assert signature.observing.line.days == 8


def test_a_day_needs_its_gas_its_temperature_and_most_of_it_seen() -> None:
    days = [
        day(0, 2.0, None),
        day(1, None, 5.0),
        day(2, 2.0, 5.0, observed=0.5),
        day(3, 2.0, 5.0),
        day(4, 2.0, 5.0, hours=0.0),  # a stored day with no length
    ]
    assert [d.start for d in energy_signature(days, threshold=15.0).days] == [3 * DAY]


def test_a_day_of_23_hours_counts_as_a_whole_day() -> None:
    [shown] = energy_signature([day(0, 2.0, 23.0, hours=23.0)], threshold=None).days
    assert shown.gas == pytest.approx(24.0)


@pytest.mark.parametrize(
    ("days", "reason"),
    [
        (line_days(0, -0.8, 12.0, COLD[:6]), NoLine.TOO_FEW_DAYS),
        (
            line_days(0, -0.8, 12.0, [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]),
            NoLine.TOO_LITTLE_SPREAD,
        ),
        (line_days(0, 0.3, 4.0, COLD), NoLine.NOT_HEATING),
        (
            [
                day(k, t, g)
                for k, (t, g) in enumerate(zip(COLD, [9, 2, 14, 6, 13, 3, 10, 5], strict=True))
            ],
            NoLine.TOO_SCATTERED,
        ),
    ],
)
def test_no_line_where_the_days_cannot_carry_one(days: list[DaySummary], reason: NoLine) -> None:
    fit = energy_signature(days, threshold=15.0).observing
    assert (fit.line, fit.reason) == (None, reason)


def test_no_comparison_without_both_lines_or_shared_temperatures() -> None:
    watched = line_days(0, -0.8, 12.0, COLD)
    assert energy_signature(watched, threshold=15.0).comparison is None
    warmer = [7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
    control = line_days(20, -0.7, 10.5, [t + 10 for t in COLD[:1]] + warmer[1:], controlled=True)
    apart = energy_signature(
        [*line_days(0, -0.8, 12.0, [-14.0, -13, -12, -11, -10, -9, -8, -6]), *control],
        threshold=15.0,
    )
    assert apart.observing.line is not None
    assert apart.control.line is not None
    assert apart.comparison is None


def test_no_comparison_where_the_watched_line_gives_no_gas() -> None:
    """Where the watched line, fitted over days that end near no heating, reaches zero in the
    shared temperatures, there is nothing to compare against."""
    watched = [
        (-8, 10),
        (-6, 9),
        (-4, 6),
        (-2, 5),
        (0, 2.2),
        (2, 1.0),
        (4, 0.3),
        (6, 0.05),
        (8, 0.05),
    ]
    control = [(4, 3), (5, 2.8), (6, 2.6), (7, 2.4), (8, 2.2), (9, 2.0), (10, 1.8), (12, 1.5)]
    days = [
        *(day(k, t, g) for k, (t, g) in enumerate(watched)),
        *(day(20 + k, t, g, controlled=True) for k, (t, g) in enumerate(control)),
    ]
    signature = energy_signature(days, threshold=15.0)
    assert signature.observing.line is not None
    assert signature.control.line is not None
    assert signature.observing.line.at(6.0) < 0
    assert signature.comparison is None


def test_without_a_threshold_every_day_with_heating_gas_counts() -> None:
    days = [*line_days(0, -0.8, 12.0, COLD), day(30, 14.0, 0.8)]
    fit = energy_signature(days, threshold=None).observing
    assert fit.line is not None
    assert fit.line.days == 9


# --- I13.4: the comparison's ranges ------------------------------------------------------------

TEN = [-6.0, -4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5, 6.0, 7.5]


def wavy(
    first: int,
    slope: float,
    intercept: float,
    error: float,
    *,
    warmer: float = 0.0,
    controlled: bool = False,
) -> list[DaySummary]:
    """Ten days on a line, ``warmer`` than ``TEN``, each off by ``error`` in runs of two."""
    return [
        day(
            first + k,
            t + warmer,
            intercept + slope * (t + warmer) + error * (1 if k % 4 < 2 else -1),
            controlled=controlled,
        )
        for k, t in enumerate(TEN)
    ]


def test_clean_lines_show_their_difference_with_no_range() -> None:
    """Days exactly on two lines: no error, each range is its value; the difference is
    shown."""
    signature = energy_signature(
        [*line_days(0, -0.8, 12.0, COLD), *line_days(20, -0.7, 10.5, COLD, controlled=True)],
        threshold=15.0,
    )
    compared = signature.comparison
    assert compared is not None
    assert (compared.observing_low, compared.observing_high) == (
        pytest.approx(11.2),
        pytest.approx(11.2),
    )
    assert (compared.control_low, compared.control_high) == (
        pytest.approx(9.8),
        pytest.approx(9.8),
    )
    assert compared.change_low == pytest.approx(compared.change)
    assert compared.change_high == pytest.approx(compared.change)
    assert compared.shown


def test_scattered_days_show_no_difference_where_the_ranges_overlap() -> None:
    """Days off by ±1.5 a day around lines 3 % apart: the ranges overlap — no difference
    shown, the change's range holding zero."""
    signature = energy_signature(
        [*wavy(0, -0.8, 12.0, 1.5), *wavy(20, -0.8, 11.64, 1.5, controlled=True)],
        threshold=15.0,
    )
    compared = signature.comparison
    assert compared is not None
    assert compared.change == pytest.approx(-0.03, abs=0.01)
    assert compared.observing_low < compared.observing < compared.observing_high
    assert compared.control_high > compared.observing_low
    assert not compared.shown
    assert compared.change_low is not None
    assert compared.change_high is not None
    assert compared.change_low < 0 < compared.change_high


def test_a_large_difference_is_shown_beyond_the_scatter() -> None:
    """The same scatter around lines 40 % apart: the ranges part — the difference is shown."""
    signature = energy_signature(
        [*wavy(0, -0.8, 12.0, 0.3), *wavy(20, -0.48, 7.2, 0.3, controlled=True)],
        threshold=15.0,
    )
    compared = signature.comparison
    assert compared is not None
    assert compared.change == pytest.approx(-0.4, abs=0.02)
    assert compared.shown
    assert compared.change_high is not None
    assert compared.change_high < 0


def test_a_watched_range_down_to_zero_leaves_the_change_unbounded() -> None:
    """Where the watched range reaches zero — compared at the warm end of a scattered watched
    line — the change could be anything: no range for it, and no difference shown."""
    signature = energy_signature(
        [*wavy(0, -0.8, 7.0, 2.5), *wavy(20, -0.2, 4.0, 0.3, warmer=10.0, controlled=True)],
        threshold=None,
    )
    compared = signature.comparison
    assert compared is not None
    assert compared.observing > 0
    assert compared.observing_low <= 0
    assert (compared.change_low, compared.change_high) == (None, None)
    assert not compared.shown


def test_days_apart_are_not_taken_as_correlated() -> None:
    """The same days a week apart do not follow each other: no allowance — a narrower range
    than day after day."""
    near = energy_signature(
        [*wavy(0, -0.8, 12.0, 1.0), *wavy(20, -0.7, 10.5, 1.0, controlled=True)], threshold=15.0
    )
    far = energy_signature(
        [
            *(replace(d, start=d.start * 7, end=d.start * 7 + DAY) for d in wavy(0, -0.8, 12, 1)),
            *wavy(200, -0.7, 10.5, 1.0, controlled=True),
        ],
        threshold=15.0,
    )
    assert near.comparison is not None
    assert far.comparison is not None
    near_width = near.comparison.observing_high - near.comparison.observing_low
    far_width = far.comparison.observing_high - far.comparison.observing_low
    assert far_width < near_width
