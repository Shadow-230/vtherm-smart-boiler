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
    circuit_flow,
    circuit_too_hot,
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


def test_a_short_burn_ended_by_the_demand_is_no_ignition_problem() -> None:
    """A2: a short heating pulse — a TPI zone's on-time, followed at once — ends because the
    zones stop asking, not because the flame was lost; only a burn that goes out while heat is
    still asked for, or with nothing known of the demand, counts."""
    burns = [burn(i * 10, 0.5) for i in range(12)]
    pulses = Series(
        [
            (t, on)
            for i in range(12)
            for t, on in (((i * 10) * MIN, True), ((i * 10 + 0.5) * MIN, False))
        ]
    )
    assert not unstable_ignition(burns, now=24 * HOUR, demand=pulses).active
    asking = Series([(0.0, True)])  # the zones kept asking: the flame was lost
    alarm = unstable_ignition(burns, now=24 * HOUR, demand=asking)
    assert alarm.active
    assert alarm.value == 12
    assert unstable_ignition(burns, now=24 * HOUR, demand=None).value == 12


def test_a_burn_counts_only_when_heat_was_asked_for_all_through_it() -> None:
    """R6, A2: one zone's pulse ends and another's begins just before the flame goes out — the
    boiler was told to stop in between, so no flame was lost; a moment known without demand
    anywhere in the burn takes it out of the count, not only one at its end."""
    burns = [burn(i * 10, 0.5) for i in range(12)]
    handover = Series(
        [
            (t, on)
            for i in range(12)
            for t, on in (
                ((i * 10) * MIN - 5.0, True),
                ((i * 10) * MIN + 20.0, False),  # the first zone's pulse ends
                ((i * 10) * MIN + 25.0, True),  # the next one's begins
            )
        ]
    )
    assert unstable_ignition(burns, now=24 * HOUR, demand=handover).value == 0
    unknown = Series([(-5.0, None)])  # nothing known of the demand: counted, as without it
    assert unstable_ignition(burns, now=24 * HOUR, demand=unknown).value == 12


# --- X4, decision 10: the circuit too hot ------------------------------------------------------


def test_the_circuit_too_hot_alarm() -> None:
    """Maximum 40 °C, the alarm at 45 °C for 10 min: the flow at 46 for 9 min — off; 10 min —
    on, information; it clears only below 44 °C (1 K under the alarm temperature, provisional,
    K4)."""
    from custom_components.vtherm_smart_boiler.core.alarms import CIRCUIT_ALARM_HYSTERESIS_K

    assert CIRCUIT_ALARM_HYSTERESIS_K == 1.0
    alarm: Alarm | None = None
    for minute in range(10):
        alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, minute * MIN, alarm)
        assert not alarm.active, minute
    assert alarm.since == 0.0
    alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, 10 * MIN, alarm)
    assert alarm.active
    assert alarm.level is Level.WARNING
    assert (alarm.value, alarm.limit) == (46.0, 45.0)
    for flow in (45.0, 44.0):  # back under the alarm temperature, not 1 K under it
        alarm = circuit_too_hot(flow, 45.0, 10 * MIN, 11 * MIN, alarm)
        assert alarm.active, flow
    alarm = circuit_too_hot(43.9, 45.0, 10 * MIN, 12 * MIN, alarm)
    assert not alarm.active
    assert alarm.since is None


def test_the_circuit_too_hot_wait_starts_again_after_a_dip() -> None:
    alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, 0.0, None)
    alarm = circuit_too_hot(44.0, 45.0, 10 * MIN, 5 * MIN, alarm)  # back under: the wait resets
    alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, 6 * MIN, alarm)
    alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, 15 * MIN, alarm)
    assert not alarm.active
    assert circuit_too_hot(46.0, 45.0, 10 * MIN, 16 * MIN, alarm).active


def test_the_circuit_too_hot_alarm_without_a_flow_is_inactive_with_its_reason() -> None:
    """Negative: no flow reading — missing or stale — the alarm is inactive and says why, even
    one that was active; a circuit the boiler flow does not show has a reason of its own."""
    alarm = circuit_too_hot(None, 45.0, 10 * MIN, 0.0, None)
    assert not alarm.active
    assert alarm.reason == "no_flow_reading"
    active = Alarm(AlarmKind.CIRCUIT_TOO_HOT, True, Level.WARNING, 46.0, 45.0, since=0.0)
    assert not circuit_too_hot(None, 45.0, 10 * MIN, 20 * MIN, active).active
    unmeasured = circuit_too_hot(None, 45.0, 10 * MIN, 0.0, None, "circuit_not_measured")
    assert unmeasured.reason == "circuit_not_measured"
    assert not unmeasured.active


def test_a_clock_set_back_does_not_hold_up_the_circuit_alarm() -> None:
    alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, 10_000.0, None)
    alarm = circuit_too_hot(46.0, 45.0, 10 * MIN, 5_000.0, alarm)  # an hour and more back
    assert alarm.since == 5_000.0
    assert circuit_too_hot(46.0, 45.0, 10 * MIN, 5_600.0, alarm).active


def test_the_circuit_flow_comes_from_its_own_sensor_else_the_boiler_for_an_unmixed_loop() -> None:
    """The circuit's own flow entity where mapped; else the boiler flow for an unmixed circuit;
    a passive fixed or mixed circuit without its own sensor is not measured; a flow not fresh
    is no reading."""
    from custom_components.vtherm_smart_boiler.core.installation import Circuit, CircuitControl

    unmixed = Circuit("main", CircuitControl.UNMIXED_SHARED, max_flow=40.0)
    fixed = Circuit("floor", CircuitControl.PASSIVE_FIXED, 35.0, max_flow=40.0)
    mixed = Circuit("mix", CircuitControl.SEPARATE, max_flow=40.0)
    assert circuit_flow(unmixed, 46.0, None) == (46.0, None)
    assert circuit_flow(unmixed, 46.0, 38.0) == (38.0, None)
    assert circuit_flow(fixed, 46.0, None) == (None, "circuit_not_measured")
    assert circuit_flow(fixed, 46.0, 41.0) == (41.0, None)
    assert circuit_flow(mixed, 46.0, None) == (None, "circuit_not_measured")
    assert circuit_flow(unmixed, None, None) == (None, "no_flow_reading")
