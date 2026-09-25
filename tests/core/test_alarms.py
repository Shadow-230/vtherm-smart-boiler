"""Alarms with hysteresis and early warnings from window trends."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.alarms import (
    FLUE_GAS_CONDENSING_BAND,
    PRESSURE_HIGH_BAND,
    PRESSURE_LOW_BAND,
    Alarm,
    AlarmKind,
    Band,
    Level,
    Trend,
    banded_alarm,
    cold_pressure_samples,
    compare_windows,
    flue_excess_samples,
    frequent_starts,
    hysteresis_samples,
    trend_warning,
    unstable_ignition,
)
from custom_components.vtherm_smart_boiler.core.cycles import Burn, BurnKind, ClassifiedBurn
from custom_components.vtherm_smart_boiler.core.series import Series

MIN = 60.0
HOUR = 3600.0
LOW = AlarmKind.PRESSURE_LOW


def test_pressure_low_levels() -> None:
    assert banded_alarm(LOW, 1.5, PRESSURE_LOW_BAND, None) == Alarm(LOW, False, None, 1.5)
    assert banded_alarm(LOW, 0.9, PRESSURE_LOW_BAND, None) == Alarm(
        LOW, True, Level.WARNING, 0.9, 1.0
    )
    assert banded_alarm(LOW, 0.5, PRESSURE_LOW_BAND, None) == Alarm(
        LOW, True, Level.ALARM, 0.5, 0.7
    )


def test_pressure_low_clears_only_past_the_hysteresis() -> None:
    active = banded_alarm(LOW, 0.9, PRESSURE_LOW_BAND, None)
    assert banded_alarm(LOW, 1.05, PRESSURE_LOW_BAND, active).active
    assert not banded_alarm(LOW, 1.15, PRESSURE_LOW_BAND, active).active
    assert not banded_alarm(LOW, 1.05, PRESSURE_LOW_BAND, None).active


def test_rising_bands() -> None:
    high = banded_alarm(AlarmKind.PRESSURE_HIGH, 2.9, PRESSURE_HIGH_BAND, None)
    assert high.level is Level.ALARM
    flue = banded_alarm(AlarmKind.FLUE_GAS_HIGH, 90.0, FLUE_GAS_CONDENSING_BAND, None)
    assert flue.level is Level.WARNING
    still = banded_alarm(AlarmKind.FLUE_GAS_HIGH, 82.0, FLUE_GAS_CONDENSING_BAND, flue)
    assert still.active


def test_unknown_value_and_switched_off_levels() -> None:
    assert banded_alarm(LOW, None, PRESSURE_LOW_BAND, None) == Alarm(LOW, False)
    # P64: an unknown reading keeps what was known, hysteresis included.
    active = banded_alarm(LOW, 0.9, PRESSURE_LOW_BAND, None)
    held = banded_alarm(LOW, None, PRESSURE_LOW_BAND, active)
    assert held == active
    assert banded_alarm(LOW, 1.05, PRESSURE_LOW_BAND, held).active  # still within hysteresis
    off = Band(warning=None, alarm=None, rising=True, hysteresis=1.0)
    assert not banded_alarm(AlarmKind.FLUE_GAS_HIGH, 500.0, off, None).active


def burn(start_min: float, minutes: float, kind: BurnKind = BurnKind.CH) -> ClassifiedBurn:
    start = start_min * MIN
    return ClassifiedBurn(Burn(start, start + minutes * MIN, True, True), kind, 1.0)


def test_frequent_starts_in_the_last_hour() -> None:
    burns = [burn(i * 4, 2) for i in range(15)]  # a start every 4 minutes
    alarm = frequent_starts(burns, now=HOUR)
    assert alarm.active
    assert alarm.value == 15
    assert not frequent_starts(burns[:5], now=HOUR).active


def test_unstable_ignition_counts_very_short_complete_burns() -> None:
    burns = [burn(i * 10, 0.5) for i in range(12)] + [burn(200, 20)]
    alarm = unstable_ignition(burns, now=24 * HOUR)
    assert alarm.active
    assert alarm.value == 12
    assert not unstable_ignition(burns[:5], now=24 * HOUR).active


def test_trend_comparison_needs_enough_samples() -> None:
    assert compare_windows([1.0] * 5, [2.0] * 30) is None
    trend = compare_windows([1.5] * 30, [1.2] * 30)
    assert trend == Trend(1.5, 1.2)
    assert trend.change == pytest.approx(-0.3)


def test_trend_warning_direction() -> None:
    falling = trend_warning(AlarmKind.PRESSURE_FALLING, Trend(1.5, 1.2), 0.2, direction=-1)
    assert falling.active
    assert not trend_warning(AlarmKind.PRESSURE_FALLING, Trend(1.2, 1.5), 0.2, -1).active
    drift = trend_warning(AlarmKind.HYSTERESIS_DRIFT, Trend(10.0, 6.0), 3.0, direction=0)
    assert drift.active
    assert trend_warning(AlarmKind.FLUE_GAS_RISING, None, 5.0, 1) == Alarm(
        AlarmKind.FLUE_GAS_RISING, False
    )


def test_cold_pressure_samples_skip_burning_and_warm_water() -> None:
    pressure = Series([(0, 1.5)])
    flame = Series([(0, False), (HOUR, True), (2 * HOUR, False)])
    flow = Series([(0, 30.0), (HOUR, 60.0), (3 * HOUR, 30.0)])
    samples = cold_pressure_samples(pressure, flame, flow, 0, 4 * HOUR, step=HOUR)
    assert samples == [1.5, 1.5]  # at 0 h and 3 h


def test_flue_excess_during_steady_heating_burns() -> None:
    flue = Series([(0, 60.0)])
    return_temp = Series([(0, 40.0)])
    burns = [burn(0, 10), burn(20, 10, BurnKind.DHW)]
    samples = flue_excess_samples(flue, return_temp, burns)
    assert samples == [20.0] * 7  # minutes 3 to 9 of the heating burn


def test_hysteresis_samples() -> None:
    flow = Series([(0, 40.0), (10 * MIN, 55.0), (25 * MIN, 45.0), (35 * MIN, 56.0)])
    burns = [burn(0, 10), burn(25, 10), burn(50, 5, BurnKind.DHW)]
    assert hysteresis_samples(flow, burns) == [10.0]
    moving = Series([(0, 45.0), (20 * MIN, 50.0)])
    assert hysteresis_samples(flow, burns, setpoint=moving) == []


def test_an_alarm_steps_down_to_a_warning_with_hysteresis() -> None:
    """P64: between levels too — an alarm stays an alarm until the value is past its limit by
    the hysteresis."""
    alarm = banded_alarm(LOW, 0.5, PRESSURE_LOW_BAND, None)
    assert alarm.level is Level.ALARM
    assert banded_alarm(LOW, 0.75, PRESSURE_LOW_BAND, alarm).level is Level.ALARM
    assert banded_alarm(LOW, 0.85, PRESSURE_LOW_BAND, alarm).level is Level.WARNING


def test_low_flow_warning() -> None:
    from custom_components.vtherm_smart_boiler.core.alarms import LOW_FLOW_HOLD_S, low_flow
    from custom_components.vtherm_smart_boiler.core.readings import ZoneState

    def z(opening: float | None, t: float = 100.0) -> ZoneState:
        return ZoneState("z", valve_open=opening, reported_at=t)

    closed = [z(0.0), z(0.02)]
    later = 100.0 + LOW_FLOW_HOLD_S
    first = low_flow(closed, True, 100.0, 600.0)
    assert not first.active  # the pump may be running on after the burner (S28)
    assert low_flow([z(0.0, later)], True, later, 600.0, first).active
    assert not low_flow(closed, False, 100.0, 600.0).active
    assert not low_flow([z(0.0), z(0.3)], True, 100.0, 600.0).active
    for zones, pump, extra, reason in (
        (closed, None, {}, "no_pump_signal"),
        ([z(0.0), z(None)], True, {}, "zone_without_valve"),  # a relay zone may flow
        ([z(0.0, t=-5000.0)], True, {}, "no_fresh_zone"),
        (closed, True, {"dhw": True}, "hot_water"),
        (closed, True, {"bypass": True}, "bypass"),
    ):
        result = low_flow(zones, pump, 100.0, 600.0, **extra)
        assert (result.active, result.reason) == (False, reason)
