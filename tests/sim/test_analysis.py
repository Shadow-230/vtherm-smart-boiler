"""The periodic analysis on a simulated installation."""

from __future__ import annotations

import pytest
from custom_components.boiler_sim.profiles import BOILERS, HOUSES, radiator_zones

from custom_components.vtherm_smart_boiler.core.alarms import AlarmKind
from custom_components.vtherm_smart_boiler.core.analysis import ReportUnit, analyse
from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions
from custom_components.vtherm_smart_boiler.core.parameters import Estimate, ParameterKey, Source
from custom_components.vtherm_smart_boiler.core.report import Cause
from custom_components.vtherm_smart_boiler.core.signal_check import OutdoorStatus
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.core.verdict import Verdict
from sim.simulator import DAY, DhwSchedule, Scenario, daily_cycle, entered_parameters, simulate


def test_analysis_of_a_simulated_week() -> None:
    means = [8.0, 6.0, 4.0, 2.0, 5.0, 7.0, 3.0, 1.0, 0.0]
    boiler = BOILERS["condensing_large"]
    scenario = Scenario(
        boiler,
        HOUSES["average"],
        radiator_zones(),
        daily_cycle(means),
        days=len(means),
        dhw=DhwSchedule(),
    )
    history = simulate(scenario).history
    params = entered_parameters(boiler, heating_threshold=18.0).with_estimate(
        ParameterKey.LOSS_COEFFICIENT, Estimate(0.25, Source.ENTERED)
    )
    now = len(means) * DAY
    days = [(d * DAY, (d + 1) * DAY) for d in range(1, len(means))]
    result = analyse(history, params, MonitorOptions(), now, days)
    assert result.at == now
    assert result.week.observed_s == pytest.approx(7 * DAY)
    assert result.day.observed_s == pytest.approx(DAY)
    assert result.verdict.verdict is not Verdict.NOT_ENOUGH_DATA
    assert {
        AlarmKind.PRESSURE_FALLING,
        AlarmKind.FLUE_GAS_RISING,
        AlarmKind.HYSTERESIS_DRIFT,
    } <= set(result.trends)
    assert not any(alarm.active for alarm in result.trends.values())  # a healthy boiler
    assert result.report is not None
    assert result.report_unit is ReportUnit.KWH
    # the last day was colder than the one before: weather explains most of the change
    assert result.report.amount(Cause.WEATHER) > 0
    assert result.outdoor is not None
    assert result.outdoor.status is OutdoorStatus.OK
    assert result.fit is not None
    assert result.fit.loss.value == pytest.approx(0.25, rel=0.3)


def test_analysis_with_minimal_signals() -> None:
    boiler = BOILERS["condensing_small"]
    scenario = Scenario(
        boiler,
        HOUSES["well_insulated"],
        radiator_zones(),
        daily_cycle([5.0, 5.0]),
        days=2,
        signals=frozenset({Signal.FLAME, Signal.FLOW}),
    )
    history = simulate(scenario).history
    result = analyse(history, entered_parameters(boiler), MonitorOptions(), 2 * DAY)
    assert result.verdict.verdict is Verdict.NOT_ENOUGH_DATA
    assert AlarmKind.PRESSURE_FALLING not in result.trends
    assert result.outdoor is None
    assert result.fit is None
