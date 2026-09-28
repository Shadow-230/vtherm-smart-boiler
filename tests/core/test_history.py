"""The history's own rules: the plugin's downtime is unknown time (P-95, A11)."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.daily import summarize_day
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries, with_downtime
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0
POWER = (
    ParameterSet()
    .with_estimate(ParameterKey.BOILER_MIN_POWER, Estimate(4.0, Source.ENTERED))
    .with_estimate(ParameterKey.BOILER_MAX_POWER, Estimate(24.0, Source.ENTERED))
)
DOWN = [(10 * HOUR, 16 * HOUR)]  # stored as 10:00–16:00


def rebuilt(rows: dict[Signal, list[tuple[float, object]]], down: list) -> History:
    """A history read back as the recorder gives it — each entity's rows in time order, only
    changes kept — with the downtime marked."""
    history = History()
    for signal, entity_rows in rows.items():
        series: Series = Series()
        for t, value in with_downtime(entity_rows, down, 0, DAY):
            series.append(t, value)
        history.signals[signal] = series
    return history


# The flame last on before the stop; Home Assistant's first states after the start at 16:00:30,
# the burner still (or again) on — the recorder keeps that row, a change from the gap.
ROWS: dict[Signal, list[tuple[float, object]]] = {
    Signal.FLAME: [(0.0, False), (9 * HOUR + 50 * MIN, True), (16 * HOUR + 30, True),
                   (16 * HOUR + 10 * MIN, False)],
    Signal.MODULATION: [(0.0, 50.0), (16 * HOUR + 30, 50.0)],
    Signal.DHW_ACTIVE: [(0.0, False), (16 * HOUR + 30, False)],
}  # fmt: skip


def test_downtime_is_unknown() -> None:
    """P-95 (A11): the time Home Assistant (or the plugin) was down, stored as 10:00–16:00, is
    unknown: a burn that was on when it stopped does not burn through it — no burn time and no
    heat in it — and the day's observed time leaves it out."""
    day = summarize_day(rebuilt(ROWS, DOWN), POWER, 0, DAY, known_until=DAY)
    gap = 6 * HOUR + 30  # 10:00 to the first state after the start
    assert day.observed_s == pytest.approx(DAY - gap)
    assert day.burn_s == pytest.approx(10 * MIN + 10 * MIN - 30)  # 09:50–10:00, 16:00:30–16:10
    assert day.heat_kwh == pytest.approx(14.0 * day.burn_s / HOUR)  # 14 kW at 50 %
    assert day.starts == 1  # the one seen going on; the one after the gap is not a start
    assert day.complete_burns == 0  # neither was seen from start to end


def test_without_a_downtime_record_nothing_is_marked() -> None:
    """The negative: no stored record (a first run, a lost store) marks nothing — the flame
    that was on is taken to burn on, as before; a downtime outside the window marks nothing."""
    unmarked = summarize_day(rebuilt(ROWS, []), POWER, 0, DAY, known_until=DAY)
    assert unmarked.observed_s == pytest.approx(DAY)
    assert unmarked.burn_s == pytest.approx(6 * HOUR + 20 * MIN)
    assert (
        list(with_downtime(ROWS[Signal.FLAME], [(DAY, DAY + HOUR)], 0, DAY)) == ROWS[Signal.FLAME]
    )


def test_a_downtime_across_the_window_start_starts_it_unknown() -> None:
    """A downtime that began before the window and ends inside it: the value the recorder gives
    for the window's start is the one from before the stop — unknown, not held."""
    rows = [(0.0, True), (2 * HOUR, False)]  # the state at the window's start, then a change
    marked = list(with_downtime(rows, [(-HOUR, HOUR)], 0.0, DAY))
    assert marked == [(0.0, None), (2 * HOUR, False)]
    series: Series = Series()
    for t, value in marked:
        series.append(t, value)
    assert series.value_at(HOUR) is None
    assert series.value_at(2 * HOUR) is False


def test_states_inside_a_downtime_do_not_hold() -> None:
    """After a crash the downtime starts at the last sign of life, up to minutes before the
    crash: a state recorded between the two, and one Home Assistant wrote at its start before
    the plugin's, say nothing of how long they held — the first state from the plugin's start
    on makes it known again. A state at the very moment of the stop is hidden too."""
    rows = [(0.0, False), (HOUR, True), (1.5 * HOUR, False), (3 * HOUR, True), (4 * HOUR, False)]
    marked = list(with_downtime(rows, [(HOUR, 3.5 * HOUR)], 0.0, DAY))
    assert marked == [(0.0, False), (HOUR, None), (4 * HOUR, False)]
    # Two downtimes, one without any row inside, one reaching past the window's end.
    marked = list(with_downtime(rows, [(0.5 * HOUR, 0.7 * HOUR), (3.5 * HOUR, 2 * DAY)], 0.0, DAY))
    assert marked == [(0.0, False), (0.5 * HOUR, None), (HOUR, True), (1.5 * HOUR, False),
                      (3 * HOUR, True), (3.5 * HOUR, None)]  # fmt: skip


# --- the backfill (P-117) ----------------------------------------------------------------------


def _samples(series: Series) -> list[tuple[float, object]]:
    return [(s.t, s.value) for s in series]


def test_a_backfill_puts_each_zones_older_states_before_its_live_ones() -> None:
    """P-117: the recorder's history goes before what was recorded live since setup, zone by zone
    and series by series, as for the boiler's signals: only what is older than a series' first
    live sample. A zone the older history lacks keeps what it has; a zone only the older history
    has — no longer configured — is not added."""
    live = History(
        signals={Signal.FLOW: Series([(100.0, 45.0)])},
        zones={"a": ZoneSeries("a"), "b": ZoneSeries("b")},
    )
    live.zones["a"].temperature.append(100.0, 20.0)
    live.zones["a"].calling.append(100.0, True)
    live.zones["b"].valve_open.append(100.0, 0.3)
    older = History(
        signals={Signal.FLOW: Series([(0.0, 30.0), (150.0, 99.0)])},
        zones={"a": ZoneSeries("a"), "c": ZoneSeries("c")},
    )
    for t, value in ((0.0, 18.0), (50.0, 19.0), (150.0, 99.0)):
        older.zones["a"].temperature.append(t, value)
    older.zones["a"].calling.append(0.0, False)
    older.zones["a"].valve_open.append(10.0, 0.6)  # a series with nothing live yet
    older.zones["c"].temperature.append(0.0, 17.0)

    live.prepend(older)

    zone = live.zones["a"]
    assert _samples(zone.temperature) == [(0.0, 18.0), (50.0, 19.0), (100.0, 20.0)]
    assert _samples(zone.calling) == [(0.0, False), (100.0, True)]
    assert _samples(zone.valve_open) == [(10.0, 0.6)]
    assert _samples(zone.target) == []
    assert _samples(live.zones["b"].valve_open) == [(100.0, 0.3)]
    assert set(live.zones) == {"a", "b"}
    assert _samples(live.signals[Signal.FLOW]) == [(0.0, 30.0), (100.0, 45.0)]


def test_an_empty_backfill_changes_no_zone() -> None:
    """Negative: nothing recorded (the recorder reaches no further back): every zone's series
    stays as it was."""
    live = History(zones={"a": ZoneSeries("a")})
    live.zones["a"].temperature.append(100.0, 20.0)
    live.prepend(History(zones={"a": ZoneSeries("a")}))
    live.prepend(History())
    assert _samples(live.zones["a"].temperature) == [(100.0, 20.0)]
    assert all(not len(series) for series in live.zones["a"].series()[1:])
