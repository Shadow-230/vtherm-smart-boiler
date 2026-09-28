"""History container and the monitor pipeline on small synthetic histories."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import pytest

from custom_components.vtherm_smart_boiler.core.cycles import BurnKind
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries, combine
from custom_components.vtherm_smart_boiler.core.metrics import ModulationScale
from custom_components.vtherm_smart_boiler.core.monitor import (
    GasSource,
    MonitorOptions,
    summarize,
    verdict,
)
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.core.verdict import Verdict

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0


def params(**values: float) -> ParameterSet:
    result = ParameterSet()
    for name, value in values.items():
        result = result.with_estimate(ParameterKey(name), Estimate(value, Source.ENTERED))
    return result


def test_zone_demand_prefers_openings_over_the_calling_flag() -> None:
    relay = ZoneSeries(
        "relay",
        on_percent=Series([(0, 0.4), (30, 0.0)]),
        calling=Series([(0, True), (5, False), (10, True)]),  # flips within the cycle
    )
    demand = History(zones={"relay": relay}).zone_demand(0, 40)
    assert demand is not None
    assert [(s.t, s.value) for s in demand] == [(0, True), (30, False)]


def test_zone_calling_prefers_the_calling_flag_over_openings() -> None:
    """R6, A2: a TPI zone's duty cycle stays the same through its cycle while its relay pulses;
    whether it asks for heat at a given moment is its calling flag, the opening only where the
    flag is not known."""
    relay = ZoneSeries(
        "relay",
        on_percent=Series([(0, 0.4), (30, 0.0)]),
        calling=Series([(0, True), (5, False), (10, True), (20, None)]),
    )
    valve = ZoneSeries("valve", valve_open=Series([(0, 0.0), (25, 0.5)]))
    calling = History(zones={"relay": relay}).zone_calling(0, 40)
    assert calling is not None
    assert [(s.t, s.value) for s in calling] == [(0, True), (5, False), (10, True), (30, False)]
    both = History(zones={"relay": relay, "valve": valve}).zone_calling(0, 40)
    assert both is not None
    assert [(s.t, s.value) for s in both] == [(0, True), (5, False), (10, True)]
    assert both.value_at(35) is True  # the relay is off by then, the valve open
    assert History().zone_calling(0, 40) is None


def test_combine_and_zone_demand() -> None:
    a = ZoneSeries("a", calling=Series([(0, False), (10, True), (20, False)]))
    b = ZoneSeries("b", calling=Series([(0, None), (15, False)]))
    history = History(zones={"a": a, "b": b})
    demand = history.zone_demand(0, 30)
    assert demand is not None
    # P63: an unknown zone may be calling — "no demand" only once every zone says so.
    assert [(s.t, s.value) for s in demand] == [(0, None), (10, True), (20, False)]
    assert History().zone_demand(0, 30) is None
    unknown = combine([Series([(0, None)])], 0, 10, lambda values: values[0])
    assert unknown.value_at(5) is None


def test_zone_state_at_and_outdoor_fallback() -> None:
    zone = ZoneSeries(
        "a",
        temperature=Series([(0, 20.0)]),
        target=Series([(0, 21.0)]),
        heating_enabled=Series([(0, True)]),
    )
    state = zone.state_at(5.0)
    assert state.deficit == pytest.approx(1.0)
    assert state.is_fresh(5.0, 1.0)
    weather = Series([(0, 3.0)])
    assert History(weather=weather).outdoor() is weather
    sensor = Series([(0, 4.0)])
    outdoor = History(signals={Signal.OUTDOOR: sensor}, weather=weather).outdoor()
    assert outdoor.value_at(5.0) == 4.0  # the sensor wins where it is known


def cycling_history(days: int = 8, outdoor: float = 8.0) -> History:
    """A boiler burning 10 minutes every 30 minutes at 50 % modulation, with a DHW signal."""
    flame = Series[bool]([(0, False)])
    for k in range(int(days * DAY // (30 * MIN))):
        t = k * 30 * MIN
        flame.append(t + 5 * MIN, True)
        flame.append(t + 15 * MIN, False)
    return History(
        signals={
            Signal.FLAME: flame,
            Signal.RETURN: Series([(0, 45.0)]),
            Signal.MODULATION: Series([(0, 50.0)]),
            Signal.DHW_ACTIVE: Series([(0, False)]),
        },
        weather=Series([(0, outdoor)]),
    )


def test_summary_of_a_cycling_boiler() -> None:
    history = cycling_history()
    parameters = params(
        boiler_min_power=4.0,
        boiler_max_power=24.0,
        gas_at_min_power=0.4,
        gas_at_max_power=2.4,
        loss_coefficient=0.2,
        heating_threshold=15.0,  # both entered: a model the load criterion trusts (S-17)
    )
    summary = summarize(history, parameters, 0, 8 * DAY)
    assert summary.heating.starts_per_hour == pytest.approx(2.0)
    assert summary.heating.median_burn_s == 10 * MIN
    assert summary.dhw.starts == 0
    assert all(b.kind is BurnKind.CH for b in summary.burns)
    assert summary.condensing is not None
    assert summary.condensing.value == pytest.approx(1.0)
    assert summary.degree_days is not None
    assert summary.degree_days.value == pytest.approx(8 * 7.0)  # base 15 °C, outdoor 8 °C
    assert summary.gas_source is GasSource.MODULATION
    assert summary.gas is not None
    # a third of the time burning: 8 h a day at 1.4 per hour
    assert summary.gas.amount == pytest.approx(8 * 8 * 1.4)
    assert summary.gas_per_degree_day == pytest.approx(summary.gas.amount / 56.0)
    assert summary.heat_output_kwh is not None
    assert summary.heat_output_kwh.amount == pytest.approx(8 * 8 * 14.0)
    assert summary.dhw_output_kwh is not None
    assert summary.dhw_output_kwh.amount == 0.0
    # load 1.4 kW at 8 °C, below the 4 kW minimum all the time
    assert summary.load_below_min is not None
    assert summary.load_below_min.value == pytest.approx(1.0)
    assert set(summary.by_outdoor) == {5.0}
    result = verdict(summary)
    # The load below the minimum power is a problem 0.2.2's control does not change (answer K).
    assert result.verdict is Verdict.NOT_WORTH_IT
    [load] = [r for r in result.reasons if r.code.value == "load_often_below_min_power"]
    assert load.changed_by_control is False


def test_summary_with_minimal_mapping() -> None:
    history = History(signals={Signal.FLAME: Series([(0, False), (HOUR, True), (2 * HOUR, False)])})
    summary = summarize(history, ParameterSet(), 0, 3 * HOUR)
    assert summary.unknown.starts == 1  # nothing tells heating from hot water
    assert summary.condensing is None
    assert summary.degree_days is None
    assert summary.gas is None
    assert summary.gas_source is None
    assert summary.heat_output_kwh is None
    assert summary.load_below_min is None
    assert summary.by_outdoor == {}
    assert verdict(summary).verdict is Verdict.NOT_ENOUGH_DATA


def test_meter_wins_over_the_modulation_estimate() -> None:
    history = cycling_history(days=1)
    history.signals[Signal.GAS_METER] = Series([(0, 100.0), (12 * HOUR, 103.0), (DAY, 106.0)])
    parameters = params(gas_at_min_power=0.4, gas_at_max_power=2.4)
    summary = summarize(history, parameters, 0, DAY + 1)
    assert summary.gas_source is GasSource.METER
    assert summary.gas is not None
    assert summary.gas.amount == pytest.approx(6.0)


def test_capacity_scale_changes_the_estimate() -> None:
    history = cycling_history(days=1)
    parameters = params(boiler_min_power=4.0, boiler_max_power=24.0)
    options = MonitorOptions(modulation_scale=ModulationScale.CAPACITY)
    summary = summarize(history, parameters, 0, DAY, options)
    assert summary.heat_output_kwh is not None
    assert summary.heat_output_kwh.amount == pytest.approx(8 * 12.0)


def test_fit_points_need_known_outdoor_and_output() -> None:
    """The building fit's days come from the day summaries (P-93: one path, 23- and 25-hour
    days normalised), each with its outdoor temperature and heat output known."""
    from custom_components.vtherm_smart_boiler.core.daily import fit_points, summarize_day

    history = cycling_history(days=3)
    parameters = params(boiler_min_power=4.0, boiler_max_power=24.0)
    days = [(d * DAY, (d + 1) * DAY) for d in range(3)]
    points = fit_points([summarize_day(history, parameters, a, b) for a, b in days])
    assert len(points) == 3
    assert points[0].outdoor_mean == pytest.approx(8.0)
    assert points[0].energy_kwh == pytest.approx(8 * 14.0)
    assert fit_points([summarize_day(history, ParameterSet(), a, b) for a, b in days]) == []


def test_copy_window_is_independent() -> None:
    zone = ZoneSeries("a", temperature=Series([(0, 20.0), (50, 21.0)]))
    history = History(signals={Signal.FLOW: Series([(0, 40.0), (50, 45.0)])}, zones={"a": zone})
    copy = history.copy_window(10, 100)
    history.signals[Signal.FLOW].append(200, 50.0)
    assert [(s.t, s.value) for s in copy.signal(Signal.FLOW)] == [(10, 40.0), (50, 45.0)]
    assert copy.zones["a"].temperature.value_at(60) == 21.0
    assert copy.zones["a"].target.value_at(60) is None


def test_gas_per_degree_day_leaves_hot_water_out() -> None:
    """Where a burn is known as hot water, its gas is not heating gas."""
    history = cycling_history(days=1)
    history.signals[Signal.DHW_ACTIVE] = Series([(0, False), (5 * MIN, True), (15 * MIN, False)])
    parameters = params(gas_at_min_power=0.4, gas_at_max_power=2.4)
    summary = summarize(history, parameters, 0, DAY)
    assert summary.gas is not None
    assert summary.gas.amount == pytest.approx(8 * 1.4 - 1.4 / 6)  # the first burn left out
    history.signals[Signal.GAS_METER] = Series(
        [(0, 100.0), (5 * MIN, 100.0), (15 * MIN, 100.5), (DAY, 110.0)]
    )
    metered = summarize(history, parameters, 0, DAY + 1)
    assert metered.gas_source is GasSource.METER
    assert metered.gas is not None
    assert metered.gas.amount == pytest.approx(9.5)  # 10 on the meter, 0.5 of it hot water


def test_the_summary_counts_burns_of_unknown_kind_apart() -> None:
    history = History(signals={Signal.FLAME: Series([(0, False), (HOUR, True), (2 * HOUR, False)])})
    summary = summarize(history, ParameterSet(), 0, 3 * HOUR)
    assert summary.heating.starts == 0
    assert summary.unknown.starts == 1
    no_dhw = summarize(history, ParameterSet(), 0, 3 * HOUR, MonitorOptions(has_dhw=False))
    assert no_dhw.heating.starts == 1


def test_the_weather_stands_in_where_the_outdoor_sensor_is_unknown() -> None:
    """P46: a mapped outdoor sensor that is unavailable no longer blocks the weather entity."""
    sensor = Series([(0, 4.0), (10, None), (20, 6.0)])
    history = History(signals={Signal.OUTDOOR: sensor}, weather=Series([(0, 9.0)]))
    outdoor = history.outdoor()
    assert [outdoor.value_at(t) for t in (5, 15, 25)] == [4.0, 9.0, 6.0]


def test_gas_per_degree_day_needs_the_gas_of_the_whole_window() -> None:
    """P46: gas known for half the window over degree-days for all of it would halve it."""
    history = cycling_history(days=1)
    history.signals[Signal.GAS_METER] = Series([(12 * HOUR, 100.0), (DAY, 106.0)])
    summary = summarize(history, params(), 0, DAY + 1)
    assert summary.gas is not None
    assert not summary.gas.complete
    assert summary.gas_per_degree_day is None


def test_a_coarse_meter_leaves_hot_water_out_by_burner_time() -> None:
    """A7: a meter that reports once an hour shows no rise within a short hot-water draw, so
    reading it at the burn's start and end left nothing out. Each rise is split by the burner
    time between its two readings — hot water's share left out."""
    flame = Series(
        [(0.0, False), (1.0, True), (50 * MIN, False), (50 * MIN + 30, True), (HOUR, False)]
    )
    history = History(
        signals={
            Signal.FLAME: flame,
            Signal.DHW_ACTIVE: Series([(0.0, False), (50 * MIN, True), (HOUR + 1, False)]),
            Signal.GAS_METER: Series([(0.0, 100.0), (HOUR, 101.0)]),  # one reading an hour
        }
    )
    summary = summarize(history, ParameterSet(), 0.0, HOUR + 1)
    assert summary.gas is not None
    heating_s = 50 * MIN - 1.0
    dhw_s = 10 * MIN - 30
    assert summary.gas.amount == pytest.approx(1.0 * heating_s / (heating_s + dhw_s))


def test_gas_from_modulation_survives_a_moment_without_the_flame() -> None:
    """A8: every Home Assistant restart leaves seconds without a flame reading; the gas from
    modulation became incomplete for the whole week, and gas per degree-day vanished. It is
    counted burn by burn, and complete while the flame is known nearly all the time."""
    history = cycling_history(days=7)
    flame = history.signals[Signal.FLAME]
    gap = Series([(s.t, s.value) for s in flame if s.t < 3 * DAY])
    gap.append(3 * DAY, None)  # a restart: five seconds unknown
    gap.append(3 * DAY + 5, False)
    for sample in flame:
        if sample.t > 3 * DAY + 5:
            gap.append(sample.t, sample.value)
    history.signals[Signal.FLAME] = gap
    parameters = params(gas_at_min_power=0.4, gas_at_max_power=2.4, heating_threshold=18.0)
    summary = summarize(history, parameters, 0, 7 * DAY)
    assert summary.gas is not None
    assert summary.gas.complete
    assert summary.gas_per_degree_day is not None


def _metered_history(days: int = 2) -> tuple[History, int, int]:
    """A burn of 10 minutes every 30 (every third one hot water), a meter reporting every
    7 minutes that counts only while the burner burns; returns it with the number of meter
    readings and burns."""
    flame = Series[bool]([(0, False)])
    dhw = Series[bool]([(0, False)])
    burns = int(days * DAY // (30 * MIN))
    for k in range(burns):
        t = k * 30 * MIN
        flame.append(t + 5 * MIN, True)
        flame.append(t + 15 * MIN, False)
        if k % 3 == 0:
            dhw.append(t + 5 * MIN, True)
            dhw.append(t + 15 * MIN, False)
    meter = Series[float]()
    readings = 0
    t = 0.0
    while t < days * DAY:
        burnt = sum(
            max(0.0, min(k * 30 * MIN + 15 * MIN, t) - (k * 30 * MIN + 5 * MIN))
            for k in range(burns)
        )
        meter.append(t, 1000.0 + burnt / HOUR)
        readings += 1
        t += 7 * MIN
    signals = {Signal.FLAME: flame, Signal.DHW_ACTIVE: dhw, Signal.GAS_METER: meter}
    return History(signals=signals), readings, burns


def _split_as_before(history: History, start: float, end: float) -> float:
    """0.2.1's split, pair by pair against every burn: the hot water's share of each rise by
    the burner time between its readings."""
    summary = summarize(history, ParameterSet(), start, end)
    meter = history.signal(Signal.GAS_METER)
    readings = [(s.start, s.value) for s in meter.segments(start, end) if s.value is not None]
    dhw = 0.0
    for (since, before), (at, after) in pairwise(readings):
        rise = after - before
        parts = [
            (b, max(0.0, min(b.burn.end, at) - max(b.burn.start, since))) for b in summary.burns
        ]
        total = sum(s for _b, s in parts)
        if rise > 0 and total > 0:
            dhw += rise * sum(s for b, s in parts if b.kind is BurnKind.DHW) / total
    return dhw


def test_metered_gas_is_split_in_one_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """P-84: the hot water's part of a meter's gas was found pair of readings by pair against
    every burn — readings times burns. It is one walk over both, in time order: the same
    result, with work that grows with readings plus burns."""
    from custom_components.vtherm_smart_boiler.core import monitor

    history, readings, burns = _metered_history()
    end = 2 * DAY
    summary = summarize(history, ParameterSet(), 0, end)
    total = summary.gas
    assert total is not None
    heating_before = (history.signal(Signal.GAS_METER).value_at(end - 1) - 1000.0) - (
        _split_as_before(history, 0, end)
    )
    assert total.amount == pytest.approx(heating_before)
    assert summary.other_gas == 0.0  # the meter counts only while the burner burns
    visits = 0
    overlap = monitor._overlap

    def counted(*args: Any) -> float:
        nonlocal visits
        visits += 1
        return overlap(*args)

    monkeypatch.setattr(monitor, "_overlap", counted)
    summarize(history, ParameterSet(), 0, end)
    assert 0 < visits <= 2 * (readings + burns)
    assert readings * burns > 50 * (readings + burns)  # the old walk would be far above


def test_a_meter_bounce_counts_once() -> None:
    """P-97: readings 100.0, 99.9, 100.0, 100.2 — a small step back and forth, as a meter's
    rounding or a correction gives — are a rise of 0.2, not 0.3: a rise counts only above the
    highest reading so far, in the consumption and in the split alike."""
    from custom_components.vtherm_smart_boiler.core.metrics import meter_consumption

    meter = Series([(0.0, 100.0), (10 * MIN, 99.9), (20 * MIN, 100.0), (30 * MIN, 100.2)])
    consumption = meter_consumption(meter, 0, 40 * MIN)
    assert consumption is not None
    assert consumption.amount == pytest.approx(0.2)
    flame = Series([(0.0, True)])  # burning throughout: every rise is the burner's
    history = History(
        signals={
            Signal.FLAME: flame,
            Signal.DHW_ACTIVE: Series([(0.0, False)]),
            Signal.GAS_METER: meter,
        }
    )
    summary = summarize(history, ParameterSet(), 0, 40 * MIN)
    assert summary.gas is not None
    assert summary.gas.amount == pytest.approx(0.2)
    assert summary.other_gas == pytest.approx(0.0)


def test_gas_without_burner_is_reported_apart() -> None:
    """S-31: a rise over an interval with the flame known off throughout is another consumer's
    gas (a cooker): left out of heating gas and shown apart, never silently subtracted. A rise
    over an interval with burner time is split as before — another consumer's gas during a
    burn cannot be told apart and counts as heating."""
    flame = Series([(0.0, False), (HOUR, True), (HOUR + 10 * MIN, False)])
    meter = Series([(0.0, 100.0), (30 * MIN, 100.3), (80 * MIN, 100.8)])
    history = History(
        signals={
            Signal.FLAME: flame,
            Signal.DHW_ACTIVE: Series([(0.0, False)]),
            Signal.GAS_METER: meter,
        }
    )
    summary = summarize(history, ParameterSet(), 0, 2 * HOUR)
    assert summary.gas is not None
    assert summary.gas.amount == pytest.approx(0.5)
    assert summary.other_gas == pytest.approx(0.3)


def test_gas_with_the_flame_unknown_counts_as_before() -> None:
    """S-31's negative: with the flame unknown over an interval, its rise cannot be told to be
    another consumer's — it is split as before (heating, without burner time); without a gas
    meter there is no other gas to show."""
    flame = Series([(0.0, None), (30 * MIN, False), (HOUR, True), (HOUR + 10 * MIN, False)])
    meter = Series([(0.0, 100.0), (30 * MIN, 100.3), (80 * MIN, 100.8)])
    history = History(
        signals={
            Signal.FLAME: flame,
            Signal.DHW_ACTIVE: Series([(0.0, False)]),
            Signal.GAS_METER: meter,
        }
    )
    summary = summarize(history, ParameterSet(), 0, 2 * HOUR)
    assert summary.gas is not None
    assert summary.gas.amount == pytest.approx(0.8)
    assert summary.other_gas == pytest.approx(0.0)
    del history.signals[Signal.GAS_METER]
    history.signals[Signal.MODULATION] = Series([(0.0, 50.0)])
    rates = params(gas_at_min_power=0.4, gas_at_max_power=2.4)
    estimated = summarize(history, rates, 0, 2 * HOUR)
    assert estimated.gas_source is GasSource.MODULATION
    assert estimated.other_gas is None
