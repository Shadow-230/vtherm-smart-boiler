"""Heating curve and effective outdoor temperature."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from custom_components.vtherm_smart_boiler.core.curve import (
    AUTO_ROOM_MAX,
    DEFAULT_HOLD_S,
    DEFAULT_TIME_CONSTANT_S,
    HOUR,
    UNDERFLOOR_TIME_CONSTANT_S,
    HeatingCurve,
    OutdoorSource,
    OutdoorState,
    auto_room,
    outdoor_time_constant,
    update_outdoor,
)
from custom_components.vtherm_smart_boiler.core.installation import EmitterType


def test_curve_passes_through_room_and_design_point() -> None:
    curve = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.3)
    assert curve.flow(20.0) == pytest.approx(20.0)
    assert curve.flow(25.0) == pytest.approx(20.0)  # no heat needed above the room
    assert curve.flow(-15.0) == pytest.approx(55.0)


def test_curve_is_bent_by_the_exponent() -> None:
    bent = HeatingCurve(exponent=1.3)
    straight = HeatingCurve(exponent=1.0)
    middle = 2.5  # halfway between room and design outdoor
    assert straight.flow(middle) == pytest.approx(37.5)
    assert bent.flow(middle) > straight.flow(middle)  # emitters need relatively warmer water
    assert bent.flow(middle) == pytest.approx(20.0 + 35.0 * 0.5 ** (1 / 1.3))


def test_curve_rises_monotonically_as_it_gets_colder() -> None:
    curve = HeatingCurve()
    flows = [curve.flow(t) for t in range(20, -21, -1)]
    assert all(b >= a for a, b in pairwise(flows))


def test_offset_shifts_the_whole_curve() -> None:
    assert HeatingCurve(offset=3.0).flow(0.0) == pytest.approx(HeatingCurve().flow(0.0) + 3.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"design_outdoor": 25.0},
        {"design_flow": 18.0},
        {"exponent": 0.0},
    ],
)
def test_invalid_curves_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must be"):
        HeatingCurve(**kwargs)


def test_sensor_wins_and_average_starts_at_the_first_value() -> None:
    state = update_outdoor(OutdoorState(), sensor=5.0, weather=8.0, now=0.0)
    assert state == OutdoorState(5.0, 5.0, OutdoorSource.SENSOR, 0.0, current=5.0)


def test_a_long_gap_ages_the_mean_by_its_length() -> None:
    """I12.22: a mean kept across a restart is aged by the time since its last reading, as an
    exponential mean is: after one time constant it has gone 63 % of the way to the reading."""
    kept = OutdoorState(-5.0, -5.0, OutdoorSource.SENSOR, 0.0)
    back = update_outdoor(kept, 5.0, None, 12 * HOUR, time_constant_s=12 * HOUR)
    assert back.average == pytest.approx(-5.0 + 10.0 * (1 - math.exp(-1)), rel=1e-6)
    assert back.effective == back.average  # the mean, lower than now


def test_weather_is_the_fallback_source() -> None:
    state = update_outdoor(OutdoorState(), sensor=None, weather=8.0, now=0.0)
    assert state.source is OutdoorSource.WEATHER
    assert state.effective == 8.0


def test_cold_snap_is_followed_at_once_warming_slowly() -> None:
    state = update_outdoor(OutdoorState(), 5.0, None, 0.0)
    colder = update_outdoor(state, -5.0, None, 600.0)
    assert colder.effective == -5.0  # the current value is lower than the average
    assert colder.average is not None
    assert -5.0 < colder.average < 5.0
    warmer = update_outdoor(colder, 10.0, None, 1200.0)
    assert warmer.effective == warmer.average  # the average lags behind the warm-up
    assert warmer.effective < 10.0


def test_average_follows_the_time_constant() -> None:
    state = update_outdoor(OutdoorState(), 0.0, None, 0.0)
    later = update_outdoor(state, 10.0, None, 3 * HOUR, time_constant_s=3 * HOUR)
    assert later.average == pytest.approx(10.0 * (1 - math.exp(-1)), rel=1e-6)


def test_a_clock_set_back_holds_the_outdoor_value_its_own_time_only() -> None:
    """PB-28: the wall clock set back a day — a reading "later than now" counts from now, so the
    hold lasts its three hours, not 27."""
    state = update_outdoor(OutdoorState(), 2.0, None, 86_400.0)
    held = update_outdoor(state, None, None, 0.0, hold_s=3 * HOUR)
    assert held.source is OutdoorSource.HELD
    assert held.updated_at == 0.0
    later = update_outdoor(held, None, None, 3 * HOUR - 1.0, hold_s=3 * HOUR)
    assert later.source is OutdoorSource.HELD
    gone = update_outdoor(later, None, None, 3 * HOUR + 1.0, hold_s=3 * HOUR)
    assert gone.source is OutdoorSource.NONE


def test_missing_readings_hold_the_last_value_then_give_up() -> None:
    state = update_outdoor(OutdoorState(), 2.0, None, 0.0)
    held = update_outdoor(state, None, None, 1800.0, hold_s=HOUR)
    assert held.source is OutdoorSource.HELD
    assert held.effective == 2.0
    gone = update_outdoor(held, None, None, HOUR + 1.0, hold_s=HOUR)
    assert gone.source is OutdoorSource.NONE
    assert gone.effective is None
    assert update_outdoor(OutdoorState(), None, None, 0.0).source is OutdoorSource.NONE


AUTO_CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.3)


@pytest.mark.parametrize(
    ("targets", "previous", "expected"),
    [
        ((21.5, 19.0), None, 21.5),  # the warmest room's setpoint
        ((25.0, 19.0), None, AUTO_ROOM_MAX),  # at most 23 °C
        ((), 21.0, 21.0),  # no zone that heats: the last Auto value holds
        ((), None, 20.0),  # none yet: the curve's own, the manual value
        ((12.0,), None, 15.0),  # never below the room temperature's bounds
    ],
)
def test_the_auto_room_is_the_warmest_setpoint_within_bounds(
    targets: tuple[float, ...], previous: float | None, expected: float
) -> None:
    """G11 D: Auto takes the highest setpoint among the zones that heat, at most 23 °C, within
    the room temperature's bounds; with none, the last Auto value, else the manual one."""
    assert AUTO_ROOM_MAX == 23.0
    assert auto_room(targets, AUTO_CURVE, previous) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("curve", "expected"),
    [
        (HeatingCurve(design_outdoor=-15.0, design_flow=26.0, room=20.0), 21.0),  # flow − 5 K
        (HeatingCurve(design_outdoor=9.0, design_flow=55.0, room=20.0), 19.0),  # outdoor + 10 K
    ],
)
def test_the_auto_room_keeps_the_curves_own_checks(curve: HeatingCurve, expected: float) -> None:
    """G11 D: Auto stays where the curve step's checks hold — at most the design flow − 5 K,
    at least the design outdoor temperature + 10 K — so the curve it builds is always valid."""
    room = auto_room((22.0,) if expected > 20 else (17.0,), curve, None)
    assert room == pytest.approx(expected)
    assert curve.design_outdoor < room < curve.design_flow


# --- Mutation testing (2026-10-12): the curve's own bounds and the outdoor state's memory ---

EPOCH = 1_760_000_000.0  # a wall-clock time, in seconds since the Unix epoch


@pytest.mark.parametrize(
    "kwargs",
    [
        {"design_outdoor": 20.0, "room": 20.0},  # no span: the curve would divide by zero
        {"design_flow": 20.0, "room": 20.0},  # no excess: no water above the room
    ],
)
def test_a_curve_at_its_own_bounds_is_rejected(kwargs: dict[str, float]) -> None:
    """Negative: below and above mean strictly — the design outdoor temperature or the design
    flow equal to the room temperature is refused."""
    with pytest.raises(ValueError, match="must be"):
        HeatingCurve(**kwargs)


def test_missing_readings_keep_the_average_and_when_the_last_reading_came() -> None:
    """At wall-clock times: without readings the last effective value holds for the hold time,
    then nothing is usable — both keep the moving average and when the last reading came, so a
    reading back continues the average instead of starting it again."""
    state = update_outdoor(OutdoorState(), 2.0, None, EPOCH)
    held = update_outdoor(state, None, None, EPOCH + 1800.0, hold_s=HOUR)
    assert held == OutdoorState(2.0, 2.0, OutdoorSource.HELD, EPOCH, current=2.0)
    gone = update_outdoor(held, None, None, EPOCH + HOUR + 1.0, hold_s=HOUR)
    assert gone == OutdoorState(2.0, None, OutdoorSource.NONE, EPOCH, current=2.0)
    back = update_outdoor(gone, 8.0, None, EPOCH + 2 * HOUR, time_constant_s=3 * HOUR)
    assert back.average == pytest.approx(2.0 + 6.0 * (1 - math.exp(-2 / 3)))
    assert back.effective == back.average


def test_no_time_passed_moves_no_average() -> None:
    """Negative: a second reading at the same moment, or after the wall clock was set back,
    leaves the moving average where it was — a warmer reading cannot raise the effective."""
    state = update_outdoor(OutdoorState(), 5.0, None, EPOCH)
    for now in (EPOCH, EPOCH - HOUR):
        again = update_outdoor(state, 10.0, None, now)
        assert again.average == 5.0
        assert again.effective == 5.0


@pytest.mark.parametrize(("time_constant_s", "weight"), [(0.0, 1.0), (1.0, 1 - math.exp(-1))])
def test_a_short_time_constant_weighs_by_its_own_law(time_constant_s: float, weight: float) -> None:
    """No time constant: the average is the reading itself — no division by zero, no jump past
    the reading; a one-second constant still weighs one elapsed second by its exponential."""
    state = update_outdoor(OutdoorState(), 0.0, None, EPOCH)
    later = update_outdoor(state, 10.0, None, EPOCH + 1.0, time_constant_s=time_constant_s)
    assert later.average == pytest.approx(10.0 * weight)


# --- I13.8: a slower outdoor mean for an underfloor circuit ---

R, C, U = EmitterType.RADIATOR, EmitterType.CONVECTOR, EmitterType.UNDERFLOOR


@pytest.mark.parametrize(
    ("emitters", "expected"),
    [
        ({U}, 12 * HOUR),
        ({R, U}, 12 * HOUR),  # one floor on the circuit: the water serves it too
        ({C, U}, 12 * HOUR),
        ({R}, 3 * HOUR),
        ({C}, 3 * HOUR),
        ({R, C}, 3 * HOUR),
        (set(), 3 * HOUR),  # no room known: as for radiators
    ],
    ids=["floor", "with_radiators", "with_convectors", "radiators", "convectors", "both", "none"],
)
def test_an_underfloor_circuit_takes_the_slower_outdoor_mean(
    emitters: set[EmitterType], expected: float
) -> None:
    """I13.8: a floor answers over tens of hours (Kull et al. 2017: 20–70 h), so the curve's
    circuit with an underfloor room follows a 12-hour outdoor mean; radiators and convectors keep
    3 hours (provisional, K4)."""
    assert UNDERFLOOR_TIME_CONSTANT_S == 12 * HOUR
    assert DEFAULT_TIME_CONSTANT_S == 3 * HOUR
    assert outdoor_time_constant(frozenset(emitters)) == expected


@pytest.mark.parametrize(
    ("time_constant_s", "after_an_hour"),
    [(DEFAULT_TIME_CONSTANT_S, 6.42), (UNDERFLOOR_TIME_CONSTANT_S, 5.40)],
    ids=["three_hours", "twelve_hours"],
)
def test_the_slower_mean_follows_a_mild_hour_slowly_and_a_cold_morning_at_once(
    time_constant_s: float, after_an_hour: float
) -> None:
    """I13.8: from 5 °C, an hour at 10 °C moves the effective outdoor temperature to 6.4 °C with
    3 h and to 5.4 °C with 12 h — the water stays nearer the night's; a colder reading is the
    effective at once with either: the lower of now and the mean is kept, so the water never
    follows a mild mean on a cold morning."""
    state = update_outdoor(OutdoorState(), 5.0, None, EPOCH, time_constant_s=time_constant_s)
    mild = update_outdoor(state, 10.0, None, EPOCH + HOUR, time_constant_s=time_constant_s)
    assert mild.effective == pytest.approx(after_an_hour, abs=0.005)
    cold = update_outdoor(mild, 0.0, None, EPOCH + HOUR + 60.0, time_constant_s=time_constant_s)
    assert cold.effective == 0.0
    assert cold.average is not None
    assert cold.average > 5.0  # the mean itself stays mild; the lower of the two counts


def test_after_a_short_cold_dip_the_slower_mean_reads_the_current_temperature() -> None:
    """I13.8, the other side: mild days at 10 °C, three hours at 0 °C, then 6 °C. The 3-hour mean
    fell with the dip (3.7 °C), so its curve reads less than now; the 12-hour mean kept the mild
    days (7.8 °C), so its curve reads the current 6 °C — less water than with 3 h, never less than
    the current temperature asks for."""
    effective = {}
    for time_constant_s in (DEFAULT_TIME_CONSTANT_S, UNDERFLOOR_TIME_CONSTANT_S):
        state = update_outdoor(OutdoorState(), 10.0, None, EPOCH, time_constant_s=time_constant_s)
        dip = update_outdoor(state, 0.0, None, EPOCH + 3 * HOUR, time_constant_s=time_constant_s)
        back = update_outdoor(dip, 6.0, None, EPOCH + 3 * HOUR, time_constant_s=time_constant_s)
        assert back.effective is not None
        effective[time_constant_s] = back.effective
    assert effective[DEFAULT_TIME_CONSTANT_S] == pytest.approx(3.68, abs=0.005)
    assert effective[UNDERFLOOR_TIME_CONSTANT_S] == 6.0


def test_the_slower_mean_leaves_the_three_hour_hold_as_it_is() -> None:
    """I13.8, negative: the hold of the last value when every reading is lost (decision 9) stays
    3 hours with the 12-hour mean — the two values are apart."""
    assert DEFAULT_HOLD_S == 3 * HOUR
    slow = UNDERFLOOR_TIME_CONSTANT_S
    state = update_outdoor(OutdoorState(), 2.0, None, EPOCH, time_constant_s=slow)
    held = update_outdoor(state, None, None, EPOCH + 3 * HOUR - 1.0, time_constant_s=slow)
    assert held.source is OutdoorSource.HELD
    gone = update_outdoor(held, None, None, EPOCH + 3 * HOUR + 1.0, time_constant_s=slow)
    assert gone.source is OutdoorSource.NONE


def test_a_changed_time_constant_carries_the_mean_on() -> None:
    """I13.8: the rooms VT hands over may change the circuit's emitters while control runs; the
    mean goes on from where it stood, weighed by the new constant — no restart, no jump."""
    state = update_outdoor(OutdoorState(), 0.0, None, EPOCH)
    fast = update_outdoor(state, 10.0, None, EPOCH + HOUR)
    assert fast.average is not None
    slow = update_outdoor(
        fast, 10.0, None, EPOCH + 2 * HOUR, time_constant_s=UNDERFLOOR_TIME_CONSTANT_S
    )
    expected = fast.average + (10.0 - fast.average) * (1 - math.exp(-1 / 12))
    assert slow.average == pytest.approx(expected)
