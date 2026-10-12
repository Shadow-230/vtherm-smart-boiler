"""Report explaining changes between two periods."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.report import (
    Cause,
    PeriodSummary,
    explain_change,
)


def test_colder_week_is_explained_by_weather() -> None:
    previous = PeriodSummary(heating=100.0, dhw=20.0, degree_days=50.0, heating_days=7.0)
    current = PeriodSummary(heating=130.0, dhw=20.0, degree_days=65.0, heating_days=7.0)
    report = explain_change(previous, current)
    assert report.change == pytest.approx(30.0)
    assert report.relative_change == pytest.approx(0.25)
    assert report.amount(Cause.WEATHER) == pytest.approx(30.0)
    assert report.amount(Cause.DHW) == 0.0
    assert report.amount(Cause.OTHER) == pytest.approx(0.0)
    assert report.unexplained == (Cause.SETTINGS,)


def test_dhw_and_settings_and_rest() -> None:
    previous = PeriodSummary(100.0, 20.0, 50.0, 7.0, mean_target=20.0)
    current = PeriodSummary(115.0, 30.0, 50.0, 7.0, mean_target=20.5)
    report = explain_change(previous, current)
    assert report.amount(Cause.WEATHER) == pytest.approx(0.0)
    assert report.amount(Cause.DHW) == pytest.approx(10.0)
    # 2 per degree-day, 0.5 K more on 7 heating days = 3.5 extra degree-days
    assert report.amount(Cause.SETTINGS) == pytest.approx(7.0)
    assert report.amount(Cause.OTHER) == pytest.approx(8.0)
    assert report.unexplained == ()


def test_parts_always_add_up_to_the_change() -> None:
    previous = PeriodSummary(80.0, 15.0, 40.0, 6.0, 21.0)
    current = PeriodSummary(60.0, 25.0, 30.0, 5.0, 20.0)
    report = explain_change(previous, current)
    assert sum(c.amount for c in report.contributions) == pytest.approx(report.change)


def test_warm_previous_period_uses_the_current_ones_rate() -> None:
    previous = PeriodSummary(heating=0.0, dhw=10.0, degree_days=0.0, heating_days=0.0)
    current = PeriodSummary(heating=40.0, dhw=10.0, degree_days=20.0, heating_days=5.0)
    report = explain_change(previous, current)
    assert report.amount(Cause.WEATHER) == pytest.approx(40.0)
    assert report.relative_change == pytest.approx(4.0)


def test_no_heating_at_all_leaves_weather_unexplained() -> None:
    previous = PeriodSummary(0.0, 10.0, 0.0, 0.0)
    current = PeriodSummary(0.0, 14.0, 0.2, 0.0)
    report = explain_change(previous, current)
    assert set(report.unexplained) == {Cause.WEATHER, Cause.SETTINGS}
    assert report.amount(Cause.DHW) == pytest.approx(4.0)
    assert report.amount(Cause.OTHER) == pytest.approx(0.0)


def test_relative_change_without_previous_use() -> None:
    report = explain_change(PeriodSummary(0.0, 0.0, 0.0, 0.0), PeriodSummary(1.0, 0.0, 0.0, 0.0))
    assert report.relative_change is None


# --- Mutation testing (2026-10-12): the rate's bounds and settings without what they need ---


def test_a_period_with_exactly_the_minimum_degree_days_gives_the_rate() -> None:
    """The minimum of degree-days is enough: the previous period's rate (10 per degree-day)
    explains the weather, not the current period's."""
    previous = PeriodSummary(heating=5.0, dhw=0.0, degree_days=0.5, heating_days=1.0)
    current = PeriodSummary(heating=10.0, dhw=0.0, degree_days=2.5, heating_days=1.0)
    assert explain_change(previous, current).amount(Cause.WEATHER) == pytest.approx(20.0)


def test_a_small_heating_use_still_gives_a_rate() -> None:
    """Any heating use above zero gives a rate, however small in the periods' unit."""
    previous = PeriodSummary(heating=0.5, dhw=0.0, degree_days=10.0, heating_days=2.0)
    current = PeriodSummary(heating=1.0, dhw=0.0, degree_days=20.0, heating_days=4.0)
    report = explain_change(previous, current)
    assert report.amount(Cause.WEATHER) == pytest.approx(0.5)
    assert report.unexplained == (Cause.SETTINGS,)


def test_degree_days_without_heating_use_give_no_rate() -> None:
    """Negative: a period with degree-days but no heating use gives no rate — weather stays
    unexplained instead of being judged at zero use per degree-day."""
    previous = PeriodSummary(heating=0.0, dhw=10.0, degree_days=10.0, heating_days=3.0)
    current = PeriodSummary(heating=0.0, dhw=10.0, degree_days=0.2, heating_days=0.0)
    report = explain_change(previous, current)
    assert set(report.unexplained) == {Cause.WEATHER, Cause.SETTINGS}


@pytest.mark.parametrize(("before", "after"), [(None, 21.0), (21.0, None)])
def test_settings_need_both_mean_setpoints(before: float | None, after: float | None) -> None:
    """Negative: with one period's mean setpoint unknown, settings are not judged."""
    previous = PeriodSummary(100.0, 20.0, 50.0, 7.0, mean_target=before)
    current = PeriodSummary(115.0, 20.0, 50.0, 7.0, mean_target=after)
    report = explain_change(previous, current)
    assert report.amount(Cause.SETTINGS) == 0.0
    assert report.unexplained == (Cause.SETTINGS,)
    assert report.amount(Cause.OTHER) == pytest.approx(15.0)


def test_settings_need_a_rate_even_with_both_mean_setpoints() -> None:
    """Negative: without a rate (no degree-days), a changed mean setpoint is not judged either."""
    previous = PeriodSummary(0.0, 10.0, 0.0, 0.0, mean_target=20.0)
    current = PeriodSummary(0.0, 10.0, 0.2, 0.0, mean_target=21.0)
    report = explain_change(previous, current)
    assert report.amount(Cause.SETTINGS) == 0.0
    assert set(report.unexplained) == {Cause.WEATHER, Cause.SETTINGS}
