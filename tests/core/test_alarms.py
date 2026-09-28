"""Alarms with hysteresis and early warnings from window trends."""

from __future__ import annotations

import math

import pytest

from custom_components.vtherm_smart_boiler.core.alarms import (
    ALARM_HOLD_S,
    FLUE_GAS_CONDENSING_BAND,
    HELD,
    HOT_WATER_UNKNOWN,
    NO_ZONE_DATA,
    PRESSURE_HIGH_BAND,
    UNKNOWN_HOLD_S,
    UNKNOWN_INPUT,
    Alarm,
    AlarmKind,
    Band,
    Level,
    Trend,
    add_water_band,
    banded_alarm,
    circuit_flow,
    circuit_too_hot,
    compare_windows,
    flue_excess_samples,
    frequent_starts,
    hysteresis_samples,
    pressure_alarms,
    pressure_samples,
    pressure_trend,
    settle,
    trend_warning,
    unstable_ignition,
)
from custom_components.vtherm_smart_boiler.core.cycles import Burn, BurnKind, ClassifiedBurn
from custom_components.vtherm_smart_boiler.core.series import Series

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0
LOW = AlarmKind.PRESSURE_LOW
HIGH = AlarmKind.PRESSURE_HIGH
ADD_WATER = add_water_band(0.8)  # a threshold the user entered from the boiler's manual


def settled(kind: AlarmKind, values: list[float | None], band: Band, step: float = MIN) -> Alarm:
    """The alarm after ``values``, one reading every ``step`` seconds from 0."""
    alarm: Alarm | None = None
    for index, value in enumerate(values):
        alarm = banded_alarm(kind, value, band, alarm, index * step)
    assert alarm is not None
    return alarm


def test_the_add_water_band_has_one_level_and_no_default() -> None:
    """Y1: the 1.0 / 0.7 bar band is gone; one optional threshold from the boiler's manual gives
    one level, the alarm level, with 0.1 bar of hysteresis."""
    assert ADD_WATER == Band(warning=None, alarm=0.8, rising=False, hysteresis=0.1)
    from custom_components.vtherm_smart_boiler.core import alarms

    assert not hasattr(alarms, "PRESSURE_LOW_BAND")


def test_levels_at_once_and_after_five_minutes() -> None:
    """The warning level shows at once; the alarm level only once the value has stayed beyond
    the alarm limit for five minutes of known readings (decision 7)."""
    assert ALARM_HOLD_S == 300.0
    ok = banded_alarm(HIGH, 2.0, PRESSURE_HIGH_BAND, None, 0.0)
    assert (ok.active, ok.level, ok.value, ok.known_at) == (False, None, 2.0, 0.0)
    warning = banded_alarm(HIGH, 2.6, PRESSURE_HIGH_BAND, None, 0.0)
    assert (warning.active, warning.level, warning.limit) == (True, Level.WARNING, 2.5)
    early = banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, None, 0.0)
    assert (early.active, early.level) == (True, Level.WARNING)  # not five minutes yet
    flue = settled(AlarmKind.FLUE_GAS_HIGH, [105.0] * 6, FLUE_GAS_CONDENSING_BAND)
    assert (flue.level, flue.limit) == (Level.ALARM, 100.0)


def test_the_alarm_level_needs_five_minutes_of_known_readings() -> None:
    """2.9 bar known: a warning for 4 min 59 s, the alarm at 5 min. A ``None`` in between
    restarts the count."""
    alarm = banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, None, 0.0)
    assert alarm.level is Level.WARNING
    before = banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, alarm, 299.0)
    assert before.level is Level.WARNING
    assert banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, before, 300.0).level is Level.ALARM
    gap = banded_alarm(HIGH, None, PRESSURE_HIGH_BAND, alarm, 120.0)
    assert (gap.active, gap.reason) == (True, HELD)
    again = banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, gap, 180.0)
    assert banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, again, 479.0).level is Level.WARNING
    assert banded_alarm(HIGH, 2.9, PRESSURE_HIGH_BAND, again, 480.0).level is Level.ALARM


def test_an_unknown_input_holds_the_alarm_one_hour_then_is_unknown() -> None:
    """S-16, question 9: pressure_high active at 2.9 bar; the value unknown for 59 min — still
    active, reason ``held``; for 61 min — unknown (``active is None``), and it stays unknown
    until a known reading comes. An inactive alarm is held alike: off for the hour, then
    unknown, never "OK" for good."""
    assert UNKNOWN_HOLD_S == 3600.0
    active = settled(HIGH, [2.9] * 6, PRESSURE_HIGH_BAND)
    known = active.known_at
    assert known == 5 * MIN
    held = banded_alarm(HIGH, None, PRESSURE_HIGH_BAND, active, known + 59 * MIN)
    assert (held.active, held.reason, held.level) == (True, HELD, Level.ALARM)
    gone = banded_alarm(HIGH, None, PRESSURE_HIGH_BAND, held, known + 61 * MIN)
    assert gone.active is None
    assert gone.reason == UNKNOWN_INPUT
    later = banded_alarm(HIGH, None, PRESSURE_HIGH_BAND, gone, known + 5 * HOUR)
    assert later.active is None
    back = banded_alarm(HIGH, 2.0, PRESSURE_HIGH_BAND, later, known + 6 * HOUR)
    assert (back.active, back.reason) == (False, None)
    ok = banded_alarm(HIGH, 2.0, PRESSURE_HIGH_BAND, None, 0.0)
    held_ok = banded_alarm(HIGH, None, PRESSURE_HIGH_BAND, ok, 59 * MIN)
    assert (held_ok.active, held_ok.reason) == (False, HELD)
    assert banded_alarm(HIGH, None, PRESSURE_HIGH_BAND, held_ok, 61 * MIN).active is None


def test_an_input_unknown_from_the_start_is_unknown_at_once() -> None:
    """Negative: no reading ever — unknown at once, never "OK"; for a count or a trend too."""
    for kind, band in ((HIGH, PRESSURE_HIGH_BAND), (LOW, ADD_WATER)):
        alarm = banded_alarm(kind, None, band, None, 0.0)
        assert alarm.active is None
        assert alarm.reason == UNKNOWN_INPUT
    assert frequent_starts([], HOUR, known_s=0.0).active is None
    assert unstable_ignition([], DAY, known_s=0.0).active is None
    assert (
        settle(trend_warning(AlarmKind.PRESSURE_FALLING, None, 0.2, -1), None, 0.0).active is None
    )


def test_a_level_clears_only_past_the_hysteresis() -> None:
    """P64: an active level clears only once the value is back past its limit by the
    hysteresis — from the alarm to the warning as from the warning to none."""
    alarm = settled(HIGH, [2.9] * 6, PRESSURE_HIGH_BAND)
    assert alarm.level is Level.ALARM
    assert banded_alarm(HIGH, 2.75, PRESSURE_HIGH_BAND, alarm, 6 * MIN).level is Level.ALARM
    warning = banded_alarm(HIGH, 2.65, PRESSURE_HIGH_BAND, alarm, 6 * MIN)
    assert warning.level is Level.WARNING
    assert banded_alarm(HIGH, 2.45, PRESSURE_HIGH_BAND, warning, 7 * MIN).active
    assert not banded_alarm(HIGH, 2.35, PRESSURE_HIGH_BAND, warning, 7 * MIN).active
    assert not banded_alarm(HIGH, 2.45, PRESSURE_HIGH_BAND, None, 0.0).active
    off = Band(warning=None, alarm=None, rising=True, hysteresis=1.0)
    assert not banded_alarm(AlarmKind.FLUE_GAS_HIGH, 500.0, off, None, 0.0).active


def test_low_pressure_has_no_default_threshold() -> None:
    """Y1: without an "add water" threshold no low-pressure alarm is computed at all, however
    low the pressure; the high-pressure alarm still is."""
    alarms = pressure_alarms(0.3, None, PRESSURE_HIGH_BAND, {}, 0.0)
    assert LOW not in alarms
    assert alarms[HIGH].active is False


def test_add_water_after_five_minutes_below_the_threshold() -> None:
    """A threshold of 0.8 bar: 0.75 bar for 4 min — still off; for 5 min — on, at the alarm
    level. It clears only above the threshold + 0.1 bar."""
    alarms: dict[AlarmKind, Alarm] = {}
    for minute in range(5):
        alarms = pressure_alarms(0.75, 0.8, PRESSURE_HIGH_BAND, alarms, minute * MIN)
        assert alarms[LOW].active is False, minute
    alarms = pressure_alarms(0.75, 0.8, PRESSURE_HIGH_BAND, alarms, 5 * MIN)
    low = alarms[LOW]
    assert (low.active, low.level, low.value, low.limit) == (True, Level.ALARM, 0.75, 0.8)
    alarms = pressure_alarms(0.85, 0.8, PRESSURE_HIGH_BAND, alarms, 6 * MIN)
    assert alarms[LOW].active
    alarms = pressure_alarms(0.95, 0.8, PRESSURE_HIGH_BAND, alarms, 7 * MIN)
    assert alarms[LOW].active is False


def test_zero_bar_is_a_reading_below_any_threshold() -> None:
    """P-17: 0.0 bar reaches the core as a reading where the source is not the gateway's — a
    failed or empty system shows, after the five minutes."""
    alarm = settled(LOW, [1.5, *[0.0] * 6], ADD_WATER)
    assert (alarm.active, alarm.level, alarm.value) == (True, Level.ALARM, 0.0)


def burn(start_min: float, minutes: float, kind: BurnKind = BurnKind.CH) -> ClassifiedBurn:
    start = start_min * MIN
    return ClassifiedBurn(Burn(start, start + minutes * MIN, True, True), kind, 1.0)


def starts(count: int) -> list[ClassifiedBurn]:
    """``count`` complete heating burns started within the hour before ``HOUR``."""
    return [burn(60 - (i + 1) * 4, 1) for i in range(count)]


def short_burns(count: int) -> list[ClassifiedBurn]:
    """``count`` burns of 30 s within the day before ``DAY``."""
    return [burn(i * 10, 0.5) for i in range(count)]


def test_frequent_starts_in_the_last_hour() -> None:
    burns = [burn(i * 4, 2) for i in range(15)]  # a start every 4 minutes
    alarm = frequent_starts(burns, now=HOUR)
    assert alarm.active
    assert alarm.value == 15
    assert alarm.known_at == HOUR
    assert not frequent_starts(burns[:5], now=HOUR).active


def test_frequent_starts_clears_two_below_its_limit() -> None:
    """P-82: limit 12 — 13, then 12, 11, then 10 starts an hour: on, on, on, off; 12 without it
    on before does not raise it."""
    alarm: Alarm | None = None
    shown = []
    for count in (13, 12, 11, 10):
        alarm = frequent_starts(starts(count), HOUR, 12, alarm)
        shown.append(alarm.active)
    assert shown == [True, True, True, False]
    assert frequent_starts(starts(12), HOUR, 12, None).active is False


def test_unstable_ignition_counts_very_short_complete_burns() -> None:
    burns = [*short_burns(12), burn(200, 20)]
    alarm = unstable_ignition(burns, now=DAY)
    assert alarm.active
    assert alarm.value == 12
    assert not unstable_ignition(burns[:5], now=DAY).active


def test_unstable_ignition_clears_two_below_its_limit() -> None:
    """P-82: limit 10 — 11, then 10, 9, then 8 short burns a day: on, on, on, off."""
    alarm: Alarm | None = None
    shown = []
    for count in (11, 10, 9, 8):
        alarm = unstable_ignition(short_burns(count), DAY, limit=10, previous=alarm)
        shown.append(alarm.active)
    assert shown == [True, True, True, False]
    assert unstable_ignition(short_burns(10), DAY, limit=10).active is False


def test_a_short_burn_ending_at_its_setpoint_is_not_unstable() -> None:
    """P-81: a 40 s burn that ends with the flow within 2 K of the CH setpoint then in force
    ended on the boiler's own hysteresis — not counted; one ending 10 K below lost its flame.
    Flow or setpoint mapped but unknown at the burn's end: not counted."""
    burns = [ClassifiedBurn(Burn(0.0, 40.0, True, True), BurnKind.CH, 1.0)]
    setpoint = Series([(-HOUR, 50.0)])
    reached = Series([(-HOUR, 30.0), (30.0, 48.0)])  # 48 >= 50 - 2 at its end
    assert unstable_ignition(burns, DAY, flow=reached, setpoint=setpoint).value == 0
    short = Series([(-HOUR, 30.0), (30.0, 40.0)])  # 10 K below
    assert unstable_ignition(burns, DAY, flow=short, setpoint=setpoint).value == 1
    unknown = Series([(-HOUR, 30.0), (30.0, None)])
    assert unstable_ignition(burns, DAY, flow=unknown, setpoint=setpoint).value == 0
    no_setpoint = Series([(-HOUR, None)])
    assert unstable_ignition(burns, DAY, flow=short, setpoint=no_setpoint).value == 0


def test_unstable_ignition_without_flow_or_setpoint_counts_as_before() -> None:
    """Negative: flow and CH setpoint not mapped — every short burn counts, as before Y1, and
    the feature is degraded, naming what is missing."""
    from custom_components.vtherm_smart_boiler.core.signal_check import (
        Feature,
        FeatureStatus,
        features,
    )
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    burns = short_burns(12)
    assert unstable_ignition(burns, DAY).value == 12
    short = Series([(-HOUR, 30.0)])
    assert unstable_ignition(burns, DAY, flow=short).value == 12  # the setpoint not mapped
    state = features(frozenset({Signal.FLAME}), False, False)[Feature.UNSTABLE_IGNITION]
    assert state.status is FeatureStatus.DEGRADED
    assert state.missing == (Signal.FLOW, Signal.CH_SETPOINT)
    full = features(frozenset({Signal.FLAME, Signal.FLOW, Signal.CH_SETPOINT}), False, False)
    assert full[Feature.UNSTABLE_IGNITION].status is FeatureStatus.AVAILABLE
    none = features(frozenset(), False, False)[Feature.UNSTABLE_IGNITION]
    assert (none.status, none.missing) == (FeatureStatus.UNAVAILABLE, (Signal.FLAME,))


def test_counting_alarms_need_the_flame_known_for_half_their_window() -> None:
    """Y1: the flame known for less than half the hour (the day) — the count cannot be judged:
    its last state is held for an hour, then unknown."""
    active = frequent_starts(starts(13), HOUR, 12, None, known_s=HOUR)
    assert active.active
    half = frequent_starts(starts(13), HOUR + MIN, 12, active, known_s=0.5 * HOUR)
    assert half.active  # half known: judged
    assert half.reason is None
    held = frequent_starts([], HOUR + 2 * MIN, 12, half, known_s=0.49 * HOUR)
    assert (held.active, held.reason) == (True, HELD)
    gone = frequent_starts([], HOUR + 2 * MIN + HOUR, 12, held, known_s=0.0)
    assert (gone.active, gone.reason) == (None, UNKNOWN_INPUT)
    day = unstable_ignition(short_burns(12), DAY, known_s=0.4 * DAY)
    assert (day.active, day.reason) == (None, UNKNOWN_INPUT)


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
    unknown = trend_warning(AlarmKind.FLUE_GAS_RISING, None, 5.0, 1)
    assert (unknown.active, unknown.reason) == (None, UNKNOWN_INPUT)  # never "OK" (S-16)


def test_a_trend_that_cannot_be_judged_is_held_then_unknown() -> None:
    """S-16 for the trends: a trend known active, then without enough samples — held an hour,
    then unknown."""
    kind = AlarmKind.PRESSURE_FALLING
    known = settle(trend_warning(kind, Trend(1.5, 1.2), 0.2, -1), None, 0.0)
    assert (known.active, known.known_at) == (True, 0.0)
    held = settle(trend_warning(kind, None, 0.2, -1), known, 30 * MIN)
    assert (held.active, held.reason) == (True, HELD)
    gone = settle(trend_warning(kind, None, 0.2, -1), held, HOUR)
    assert (gone.active, gone.reason) == (None, UNKNOWN_INPUT)


def quiet_series(start: float, end: float, flow_at, pressure_at, step: float = 10 * MIN):
    """Flame known off throughout; flow and pressure given every ``step`` from ``start``."""
    times = [start + i * step for i in range(math.ceil((end - start) / step))]
    flame = Series([(start - HOUR, False)])
    flow = Series([(t, flow_at(t)) for t in times])
    pressure = Series([(t, pressure_at(t, flow_at(t))) for t in times])
    return pressure, flame, flow


NOW = 8 * DAY
BASELINE = (0.0, NOW - 4 * DAY)
RECENT = (NOW - DAY, NOW)


def warm_flow(t: float) -> float:
    """Heating water that never drops below 35 °C: 35 to 60 °C over a 6-hour cycle."""
    return 47.5 + 12.5 * math.sin(2 * math.pi * t / (6 * HOUR))


def test_pressure_samples_need_the_flame_off_for_ten_minutes() -> None:
    """Samples every 10 min where the flame has been known off for the 10 min before, and
    pressure and flow are known."""
    flame = Series([(-HOUR, False), (HOUR, True), (HOUR + 30 * MIN, False)])
    flow = Series([(-HOUR, 40.0)])
    pressure = Series([(-HOUR, 1.5), (3 * HOUR, None)])
    samples = pressure_samples(pressure, flame, flow, 0.0, 4 * HOUR)
    times = [s.t for s in samples]
    assert 0.0 in times
    assert HOUR not in times  # the flame came on at that moment
    assert HOUR + 30 * MIN not in times  # off only just now
    assert HOUR + 40 * MIN in times  # off for the ten minutes before
    assert all(t < 3 * HOUR for t in times)  # the pressure unknown from 3 h
    unknown_flame = Series([(-HOUR, None)])
    assert pressure_samples(pressure, unknown_flame, flow, 0.0, 4 * HOUR) == []


def test_the_pressure_trend_sees_a_leak_with_warm_water() -> None:
    """Open after R6 #5: 8 days where the flow never drops below 35 °C, the pressure following
    0.01 bar/K; a real loss of 0.3 bar between the windows raises "pressure falling". Without
    the loss it stays off — the water temperature is taken into account."""

    def leaking(t: float, flow: float) -> float:
        loss = 0.3 if t >= NOW - 3 * DAY else 0.0
        return 1.5 + 0.01 * (flow - 40.0) - loss

    alarm = pressure_trend(*quiet_series(0.0, NOW, warm_flow, leaking), BASELINE, RECENT)
    assert alarm.active is True
    assert alarm.value == pytest.approx(-0.3, abs=0.02)
    steady = pressure_trend(
        *quiet_series(0.0, NOW, warm_flow, lambda _t, flow: 1.5 + 0.01 * (flow - 40.0)),
        BASELINE,
        RECENT,
    )
    assert steady.active is False
    assert steady.value == pytest.approx(0.0, abs=0.02)


def test_the_pressure_trend_without_a_slope_falls_back_to_cold_samples() -> None:
    """The flow spans less than 10 K: no slope — only cold samples (flow below 35 °C) count,
    as before; with fewer than 20 per window the trend is unknown."""

    def leaking(t: float, _flow: float) -> float:
        return 1.2 if t >= NOW - 3 * DAY else 1.5

    cold = pressure_trend(*quiet_series(0.0, NOW, lambda _t: 30.0, leaking), BASELINE, RECENT)
    assert cold.active is True
    warm = pressure_trend(*quiet_series(0.0, NOW, lambda _t: 45.0, leaking), BASELINE, RECENT)
    assert (warm.active, warm.reason) == (None, UNKNOWN_INPUT)  # no cold sample at all

    def sparse(t: float, _flow: float) -> float | None:
        if t >= NOW - DAY:  # the last day: known for its first two hours only
            return 1.2 if t < NOW - DAY + 2 * HOUR else None
        return 1.5

    few = pressure_trend(*quiet_series(0.0, NOW, lambda _t: 30.0, sparse), BASELINE, RECENT)
    assert few.active is None  # 12 samples in the last day: not enough

    def steep(t: float, flow: float) -> float:  # 0.08 bar/K: no system swells that much
        return 1.5 + 0.08 * (flow - 40.0) - (0.3 if t >= NOW - 3 * DAY else 0.0)

    out_of_range = pressure_trend(*quiet_series(0.0, NOW, warm_flow, steep), BASELINE, RECENT)
    assert out_of_range.active is None  # the slope is not used, and no sample is cold


def test_the_pressure_trend_is_unknown_without_flow_or_flame() -> None:
    """Negative: without flow readings, or with the flame never known, no sample — unknown."""
    pressure, flame, flow = quiet_series(0.0, NOW, warm_flow, lambda _t, _f: 1.5)
    no_flow = pressure_trend(pressure, flame, Series(), BASELINE, RECENT)
    assert (no_flow.active, no_flow.reason) == (None, UNKNOWN_INPUT)
    no_flame = pressure_trend(pressure, Series(), flow, BASELINE, RECENT)
    assert no_flame.active is None


def test_flue_excess_during_steady_heating_burns() -> None:
    flue = Series([(0, 60.0)])
    return_temp = Series([(0, 40.0)])
    burns = [burn(0, 10), burn(20, 10, BurnKind.DHW)]
    samples = flue_excess_samples(flue, return_temp, burns)
    assert samples == [20.0] * 7  # minutes 3 to 9 of the heating burn


def test_hysteresis_samples() -> None:
    flow = Series([(0, 40.0), (10 * MIN, 55.0), (25 * MIN, 45.0), (35 * MIN, 56.0)])
    burns = [burn(0, 10), burn(25, 10), burn(50, 5, BurnKind.DHW)]
    asking = Series([(0.0, True)])
    assert hysteresis_samples(flow, burns, None, demand=asking) == [10.0]
    moving = Series([(0, 45.0), (20 * MIN, 50.0)])
    assert hysteresis_samples(flow, burns, moving, demand=asking) == []


def test_hysteresis_samples_only_from_pauses_with_demand_throughout() -> None:
    """P-29: a pause during which the zones' demand turned off comes from no demand, not the
    burner's hysteresis — no sample. Negative: demand unknown during the pause, or no zone data
    at all — no sample."""
    flow = Series([(0, 40.0), (10 * MIN, 55.0), (25 * MIN, 45.0), (35 * MIN, 56.0)])
    burns = [burn(0, 10), burn(25, 10)]
    dropped = Series([(0.0, True), (15 * MIN, False), (20 * MIN, True)])
    assert hysteresis_samples(flow, burns, None, demand=dropped) == []
    unknown = Series([(0.0, True), (15 * MIN, None), (20 * MIN, True)])
    assert hysteresis_samples(flow, burns, None, demand=unknown) == []
    assert hysteresis_samples(flow, burns, None, demand=None) == []
    assert NO_ZONE_DATA == "no_zone_data"


def test_low_flow_warning() -> None:
    from custom_components.vtherm_smart_boiler.core.alarms import LOW_FLOW_HOLD_S, low_flow
    from custom_components.vtherm_smart_boiler.core.readings import ZoneState

    def z(opening: float | None, t: float = 100.0) -> ZoneState:
        return ZoneState("z", valve_open=opening, reported_at=t)

    closed = [z(0.0), z(0.02)]
    later = 100.0 + LOW_FLOW_HOLD_S
    first = low_flow(closed, True, 100.0, 600.0, dhw=False)
    assert first.active is False  # the pump may be running on after the burner (S28)
    assert low_flow([z(0.0, later)], True, later, 600.0, first, dhw=False).active
    assert low_flow(closed, False, 100.0, 600.0, dhw=False).active is False
    assert low_flow([z(0.0), z(0.3)], True, 100.0, 600.0, dhw=False).active is False
    bypass = low_flow(closed, True, 100.0, 600.0, dhw=False, bypass=True)
    assert (bypass.active, bypass.reason) == (False, "bypass")  # does not apply: known
    for zones, pump, extra, reason in (
        (closed, None, {}, "no_pump_signal"),
        ([z(0.0), z(None)], True, {}, "zone_without_valve"),  # a relay zone may flow
        ([z(0.0, t=-5000.0)], True, {}, "no_fresh_zone"),
        (closed, True, {"dhw": True}, "hot_water"),
    ):
        extra = {"dhw": False, **extra}
        result = low_flow(zones, pump, 100.0, 600.0, **extra)
        # Not judged, and nothing known before: unknown at once (S-16), with its reason.
        assert (result.active, result.reason) == (None, reason)
        held = low_flow(zones, pump, 160.0, 600.0, first, **extra)
        assert (held.active, held.reason) == (False, HELD)


def test_low_flow_is_not_judged_with_hot_water_unknown() -> None:
    """P-27: a boiler with hot water whose hot water is unknown — not judged (storage charging
    with the valves closed is no low flow): held, then unknown. A boiler declared without hot
    water is judged."""
    from custom_components.vtherm_smart_boiler.core.alarms import low_flow
    from custom_components.vtherm_smart_boiler.core.readings import ZoneState

    def closed(t: float) -> list[ZoneState]:
        return [ZoneState("z", valve_open=0.0, reported_at=t)]

    judged = low_flow(closed(0.0), True, 0.0, None, None, dhw=False)
    assert judged.active is False
    held = low_flow(closed(60.0), True, 60.0, None, judged, dhw=None, has_dhw=True)
    assert (held.active, held.reason) == (False, HELD)
    gone = low_flow(closed(3700.0), True, 3700.0, None, held, dhw=None, has_dhw=True)
    assert (gone.active, gone.reason) == (None, HOT_WATER_UNKNOWN)
    at_once = low_flow(closed(0.0), True, 0.0, None, None, dhw=None)
    assert (at_once.active, at_once.reason) == (None, HOT_WATER_UNKNOWN)
    none = low_flow(closed(0.0), True, 0.0, None, None, dhw=None, has_dhw=False)
    assert (none.active, none.reason) == (False, None)


def test_the_low_flow_wait_starts_again_after_a_gap() -> None:
    """A gap it cannot judge — hot water, say — restarts the fifteen minutes' wait, as a
    ``None`` restarts the alarm level's count."""
    from custom_components.vtherm_smart_boiler.core.alarms import LOW_FLOW_HOLD_S, low_flow
    from custom_components.vtherm_smart_boiler.core.readings import ZoneState

    def closed(t: float) -> list[ZoneState]:
        return [ZoneState("z", valve_open=0.0, reported_at=t)]

    alarm = low_flow(closed(0.0), True, 0.0, None, None, dhw=False)
    alarm = low_flow(closed(600.0), True, 600.0, None, alarm, dhw=True)  # a draw
    alarm = low_flow(closed(660.0), True, 660.0, None, alarm, dhw=False)
    assert (
        low_flow(closed(LOW_FLOW_HOLD_S), True, LOW_FLOW_HOLD_S, None, alarm, dhw=False).active
        is False
    )
    due = 660.0 + LOW_FLOW_HOLD_S
    assert low_flow(closed(due), True, due, None, alarm, dhw=False).active


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


def test_the_circuit_too_hot_alarm_without_a_flow_is_held_then_unknown() -> None:
    """Negative: no flow reading — missing or stale — the alarm cannot judge: unknown at once
    without a state known before; one known is held for an hour (S-16, Y1), then unknown, with
    its reason. A circuit the boiler flow does not show and no sensor measures is inactive with a
    reason of its own: the alarm does not apply to it."""
    alarm = circuit_too_hot(None, 45.0, 10 * MIN, 0.0, None)
    assert (alarm.active, alarm.reason) == (None, "no_flow_reading")
    active = Alarm(
        AlarmKind.CIRCUIT_TOO_HOT, True, Level.WARNING, 46.0, 45.0, since=0.0, known_at=20 * MIN
    )
    held = circuit_too_hot(None, 45.0, 10 * MIN, 30 * MIN, active)
    assert (held.active, held.reason) == (True, HELD)
    gone = circuit_too_hot(None, 45.0, 10 * MIN, 20 * MIN + HOUR, held)
    assert (gone.active, gone.reason) == (None, "no_flow_reading")
    unmeasured = circuit_too_hot(None, 45.0, 10 * MIN, 0.0, None, "circuit_not_measured")
    assert unmeasured.reason == "circuit_not_measured"
    assert unmeasured.active is False


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


# --- Y1: the notifications -----------------------------------------------------------------------


def test_a_notification_opens_at_its_level_and_closes_after_an_hour_in_range() -> None:
    """Decision 7: open while its alarm level holds; closed after an hour of known readings in
    the normal range — still open at 59 min, gone at 60. A reading outside the range, or an
    unknown one, keeps it open and starts the hour again."""
    from custom_components.vtherm_smart_boiler.core.alarms import (
        NOTICE_CLOSE_S,
        Notice,
        follow_notice,
    )

    assert NOTICE_CLOSE_S == HOUR
    assert follow_notice(Notice(), False, True, 0.0) == Notice()  # never raised: closed
    assert follow_notice(Notice(), False, None, 0.0) == Notice()
    notice = follow_notice(Notice(), True, False, 0.0)
    assert notice.open
    notice = follow_notice(notice, False, True, 10 * MIN)
    assert follow_notice(notice, False, True, 10 * MIN + 59 * MIN).open
    assert not follow_notice(notice, False, True, 10 * MIN + 60 * MIN).open
    unknown = follow_notice(notice, False, None, 40 * MIN)  # an unknown reading
    assert unknown == Notice(True)
    again = follow_notice(unknown, False, True, 50 * MIN)
    assert follow_notice(again, False, True, 50 * MIN + 59 * MIN).open
    outside = follow_notice(again, False, False, 60 * MIN)
    assert outside == Notice(True)
    raised_again = follow_notice(again, True, False, 70 * MIN)
    assert raised_again == Notice(True)
