"""The periodic analysis on a simulated installation."""

from __future__ import annotations

from typing import Any

import pytest
from custom_components.boiler_sim.profiles import BOILERS, HOUSES, radiator_zones

from custom_components.vtherm_smart_boiler.core.alarms import AlarmKind
from custom_components.vtherm_smart_boiler.core.analysis import ReportUnit, analyse
from custom_components.vtherm_smart_boiler.core.history import History
from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.report import Cause
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signal_check import OutdoorStatus
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.core.verdict import Verdict
from sim.simulator import DAY, DhwSchedule, Scenario, daily_cycle, entered_parameters, simulate

MEANS = [8.0, 6.0, 4.0, 2.0, 5.0, 7.0, 3.0, 1.0, 0.0]
# Pressure is compared only on cold water, which a cold day does not have: the trends are
# judged on a mild week.
MILD = [12.0, 11.0, 12.0, 13.0, 12.0, 11.0, 12.0, 13.0, 12.0]
TRENDS = (AlarmKind.PRESSURE_FALLING, AlarmKind.FLUE_GAS_RISING, AlarmKind.HYSTERESIS_DRIFT)


def simulated_week(
    means: list[float] = MEANS,
) -> tuple[History, ParameterSet, float, list[tuple[float, float]]]:
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
    return history, params, now, days


def shifted(series: Series[Any], after: float, delta: float) -> Series[Any]:
    """The series with ``delta`` added from ``after`` on: a fault developing."""
    return Series(
        (s.t, s.value + delta if s.t >= after and s.value is not None else s.value) for s in series
    )


def test_analysis_of_a_simulated_week() -> None:
    history, params, now, days = simulated_week()
    result = analyse(history, params, MonitorOptions(), now, days)
    assert result.at == now
    assert result.week.observed_s == pytest.approx(7 * DAY)
    assert result.day.observed_s == pytest.approx(DAY)
    assert result.verdict.verdict is not Verdict.NOT_ENOUGH_DATA
    assert set(TRENDS) <= set(result.trends)
    assert not any(alarm.active for alarm in result.trends.values())
    assert result.report is not None
    assert result.report_unit is ReportUnit.KWH
    # the last day was colder than the one before: weather explains most of the change
    assert result.report.amount(Cause.WEATHER) > 0
    assert result.outdoor is not None
    assert result.outdoor.status is OutdoorStatus.OK
    assert result.fit is not None
    assert result.fit.loss.value == pytest.approx(0.25, rel=0.3)


def test_a_healthy_boiler_passes_every_trend_it_is_judged_on() -> None:
    """Not a pass for want of data (P102): each trend was judged, and none warns."""
    history, params, now, days = simulated_week(MILD)
    result = analyse(history, params, MonitorOptions(), now, days)
    for kind in TRENDS:
        alarm = result.trends[kind]
        assert alarm.value is not None, kind
        assert not alarm.active, kind


@pytest.mark.parametrize(
    ("signal", "delta", "kind"),
    [
        (Signal.PRESSURE, -0.4, AlarmKind.PRESSURE_FALLING),  # a leak
        (Signal.FLUE_GAS, 15.0, AlarmKind.FLUE_GAS_RISING),  # a fouling heat exchanger
    ],
)
def test_a_developing_fault_is_warned_about(signal: Signal, delta: float, kind: AlarmKind) -> None:
    """The trends the healthy week passes do catch a fault of the last day."""
    history, params, now, days = simulated_week(MILD)
    history.signals[signal] = shifted(history.signal(signal), now - DAY, delta)
    result = analyse(history, params, MonitorOptions(), now, days)
    assert result.trends[kind].active


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
