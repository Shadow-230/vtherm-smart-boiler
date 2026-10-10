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
