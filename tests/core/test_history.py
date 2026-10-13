"""The history's own rules: the plugin's downtime is unknown time (P-95, A11)."""

from __future__ import annotations

from itertools import islice

import pytest

from custom_components.vtherm_smart_boiler.core.daily import summarize_day
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries, with_downtime
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.readings import ZONE_OPEN, ZoneState
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
    the plugin's, say nothing of how long they held before the plugin's start — the latest of
    them is the state at that start, known from then on (PB-65). A state at the very moment of
    the stop is hidden too."""
    rows = [(0.0, False), (HOUR, True), (1.5 * HOUR, False), (3 * HOUR, True), (4 * HOUR, False)]
    marked = list(with_downtime(rows, [(HOUR, 3.5 * HOUR)], 0.0, DAY))
    assert marked == [(0.0, False), (HOUR, None), (3.5 * HOUR, True), (4 * HOUR, False)]
    # Two downtimes, one without any row inside, one reaching past the window's end.
    marked = list(with_downtime(rows, [(0.5 * HOUR, 0.7 * HOUR), (3.5 * HOUR, 2 * DAY)], 0.0, DAY))
    assert marked == [(0.0, False), (0.5 * HOUR, None), (HOUR, True), (1.5 * HOUR, False),
                      (3 * HOUR, True), (3.5 * HOUR, None)]  # fmt: skip


def test_a_steady_signal_is_known_again_from_the_plugins_setup() -> None:
    """PB-65: the flame off for hours; Home Assistant down 10:00–16:00, its start writing the
    flame off at 15:59, the plugin set up at 16:00 — the flame is known off from 16:00, not
    unknown until its next change. Negatives: no row inside (a sub-second gap the recorder
    wrote nothing in) leaves it unknown until the next row; a row at ``to`` itself is used as
    it is; the window-start state of a downtime begun before the window is not the state at
    ``to``; a downtime past the window's end gives nothing at its end."""
    rows = [(0.0, False), (15 * HOUR + 59 * MIN, False)]
    marked = list(with_downtime(rows, [(10 * HOUR, 16 * HOUR)], 0.0, DAY))
    assert marked == [(0.0, False), (10 * HOUR, None), (16 * HOUR, False)]
    assert list(with_downtime([(0.0, False)], [(HOUR, 2 * HOUR)], 0.0, DAY)) == [
        (0.0, False),
        (HOUR, None),
    ]
    at_to = [(0.0, False), (1.5 * HOUR, True), (2 * HOUR, False)]
    assert list(with_downtime(at_to, [(HOUR, 2 * HOUR)], 0.0, DAY)) == [
        (0.0, False),
        (HOUR, None),
        (2 * HOUR, False),
    ]
    assert list(with_downtime([(0.0, True)], [(-HOUR, HOUR)], 0.0, DAY)) == [(0.0, None)]
    # Two overlapping downtimes are one: known again at the later end.
    merged = list(with_downtime(rows, [(10 * HOUR, 15 * HOUR), (12 * HOUR, 16 * HOUR)], 0.0, DAY))
    assert merged == [(0.0, False), (10 * HOUR, None), (16 * HOUR, False)]
    assert list(with_downtime(rows, [(10 * HOUR, 2 * DAY)], 0.0, DAY)) == [
        (0.0, False),
        (10 * HOUR, None),
    ]


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


def test_overlapping_downtimes_are_one() -> None:
    """TB-28: downtimes (1 h, 3 h) and (2 h, 4 h), a row every half hour: one ``None`` at 1 h,
    the rows inside dropped, known again from the row at 4 h on."""
    rows = [(k * 0.5 * HOUR, float(k)) for k in range(13)]
    marked = list(with_downtime(rows, [(HOUR, 3 * HOUR), (2 * HOUR, 4 * HOUR)], 0.0, DAY))
    assert marked == [
        (0.0, 0.0),
        (0.5 * HOUR, 1.0),
        (HOUR, None),
        *[(k * 0.5 * HOUR, float(k)) for k in range(8, 13)],
    ]


# --- Mutation testing (2026-10-12): zone states, copies, cuts and downtime edges ---------------


def _full_zone(zone_id: str) -> ZoneSeries:
    """A zone with every series known from 10 s on."""
    zone = ZoneSeries(zone_id)
    for series, value in zip(zone.series(), (20.5, 21.0, True, True, 0.4, 0.6, 1.5), strict=True):
        series.append(10.0, value)
    return zone


def test_a_zones_state_holds_every_series_value_at_the_moment() -> None:
    """A zone's state at a moment carries its id and every series' value then; before its first
    samples everything but the id and the moment is unknown."""
    zone = _full_zone("a")
    assert zone.state_at(20.0) == ZoneState(
        "a",
        temperature=20.5,
        target=21.0,
        heating_enabled=True,
        calling=True,
        on_percent=0.4,
        valve_open=0.6,
        power=1.5,
        reported_at=20.0,
    )
    assert zone.state_at(5.0) == ZoneState("a", reported_at=5.0)


@pytest.mark.parametrize(
    ("opening", "wanted"), [(ZONE_OPEN, False), (ZONE_OPEN + 0.01, True)], ids=["at", "above"]
)
def test_a_zone_with_only_its_valve_opening_is_judged_by_it(opening: float, wanted: bool) -> None:
    """Negative: a zone with nothing but its valve opening still counts; an opening of exactly
    ``ZONE_OPEN`` is no demand, only above it — whether its flag is unknown or missing."""
    zone = ZoneSeries("a", valve_open=Series([(0.0, opening)]))
    history = History(zones={"a": zone})
    demand = history.zone_demand(0.0, HOUR)
    calling = history.zone_calling(0.0, HOUR)
    assert demand is not None
    assert calling is not None
    assert demand.value_at(0.0) is wanted
    assert calling.value_at(0.0) is wanted


def test_a_copied_window_keeps_every_series_and_the_zone_ids() -> None:
    """The copy handed to another thread holds the window of every series — the weather, the
    setpoint read-back, the control state and each zone under its own id — not empty ones."""
    history = History(
        signals={Signal.FLOW: Series([(0.0, 40.0), (20.0, 45.0)])},
        zones={"a": _full_zone("a")},
        weather=Series([(0.0, 5.0), (20.0, 4.0)]),
        setpoint_read_back=Series([(0.0, 50.0), (20.0, 55.0)]),
        control_state=Series([(0.0, "watching"), (20.0, "controlling")]),
    )
    copy = history.copy_window(15.0, 30.0)
    assert _samples(copy.signals[Signal.FLOW]) == [(15.0, 40.0), (20.0, 45.0)]
    assert _samples(copy.weather) == [(15.0, 5.0), (20.0, 4.0)]
    assert _samples(copy.setpoint_read_back) == [(15.0, 50.0), (20.0, 55.0)]
    assert _samples(copy.control_state) == [(15.0, "watching"), (20.0, "controlling")]
    assert copy.zones["a"].zone_id == "a"
    assert copy.zones["a"].state_at(15.0) == _full_zone("a").state_at(15.0)


def test_dropping_old_samples_keeps_the_value_holding_at_the_cut_everywhere() -> None:
    """The rolling history forgets what lies before the cut in every series — signals, zones,
    weather, setpoint read-back, control state — and keeps the value holding at the cut."""
    zone = ZoneSeries("a", temperature=Series([(0.0, 19.0), (20.0, 20.0), (40.0, 21.0)]))
    history = History(
        signals={Signal.FLOW: Series([(0.0, 40.0), (20.0, 45.0), (40.0, 50.0)])},
        zones={"a": zone},
        weather=Series([(0.0, 5.0), (20.0, 4.0), (40.0, 3.0)]),
        setpoint_read_back=Series([(0.0, 50.0), (20.0, 55.0), (40.0, 60.0)]),
        control_state=Series([(0.0, "off"), (20.0, "watching"), (40.0, "controlling")]),
    )
    history.drop_before(30.0)
    assert _samples(history.signals[Signal.FLOW]) == [(20.0, 45.0), (40.0, 50.0)]
    assert _samples(history.zones["a"].temperature) == [(20.0, 20.0), (40.0, 21.0)]
    assert _samples(history.weather) == [(20.0, 4.0), (40.0, 3.0)]
    assert _samples(history.setpoint_read_back) == [(20.0, 55.0), (40.0, 60.0)]
    assert _samples(history.control_state) == [(20.0, "watching"), (40.0, "controlling")]


@pytest.mark.parametrize(
    "down", [[(HOUR, HOUR)], [(-HOUR, 0.0)]], ids=["empty", "ends_at_the_window_start"]
)
def test_a_downtime_with_no_time_in_the_window_marks_nothing(down: list) -> None:
    """Negative: an empty downtime, or one that ends exactly at the window's start, covers none
    of ``[start, end)``: the rows come back as they are."""
    rows = [(0.0, False), (2 * HOUR, True)]
    assert list(with_downtime(rows, down, 0.0, DAY)) == rows


@pytest.mark.parametrize(
    "down",
    [[(HOUR, 2 * HOUR), (2 * HOUR, 3 * HOUR)], [(HOUR, 3 * HOUR), (1.5 * HOUR, 2 * HOUR)]],
    ids=["touching", "nested"],
)
def test_touching_or_nested_downtimes_are_one_until_the_latest_end(down: list) -> None:
    """Two downtimes that touch, or one inside another, are one downtime: one ``None`` at its
    start, known again only at the latest end."""
    rows = [(0.0, False), (1.2 * HOUR, True), (2.5 * HOUR, False), (4 * HOUR, True)]
    assert list(with_downtime(rows, down, 0.0, DAY)) == [
        (0.0, False),
        (HOUR, None),
        (3 * HOUR, False),
        (4 * HOUR, True),
    ]


def test_a_downtime_from_the_window_start_takes_its_row_as_the_state_at_the_end() -> None:
    """A downtime that begins exactly at the window's start did not begin before it: the row at
    the start is a state inside the downtime, the state at its end.
    This test pins current behaviour that the review of 2026-10-13 questions (A8,
    research/2026-10-13-mutation-tests-review.md): a fix of it changes this test."""
    assert list(with_downtime([(0.0, True)], [(0.0, HOUR)], 0.0, DAY)) == [
        (0.0, None),
        (HOUR, True),
    ]


def test_a_row_inside_a_downtime_begun_before_the_window_is_the_state_at_its_end() -> None:
    """Only the window-start row of a downtime begun before the window says nothing of its end; a
    row recorded inside it after the start is the state at its end (PB-65)."""
    rows = [(0.0, True), (0.5 * HOUR, False), (2 * HOUR, True)]
    assert list(with_downtime(rows, [(-HOUR, HOUR)], 0.0, DAY)) == [
        (0.0, None),
        (HOUR, False),
        (2 * HOUR, True),
    ]


def test_separate_downtimes_are_each_unknown() -> None:
    """Two separate downtimes, each with a row inside: each starts unknown and is known again at
    its own end — also when both lie after the last row (the generator ends)."""
    rows = [(0.0, False), (1.5 * HOUR, True), (2.5 * HOUR, False), (3.5 * HOUR, True)]
    down = [(HOUR, 2 * HOUR), (3 * HOUR, 4 * HOUR)]
    later = [*rows, (5 * HOUR, False)]
    assert list(islice(with_downtime(later, down, 0.0, DAY), 20)) == [
        (0.0, False),
        (HOUR, None),
        (2 * HOUR, True),
        (2.5 * HOUR, False),
        (3 * HOUR, None),
        (4 * HOUR, True),
        (5 * HOUR, False),
    ]
    assert list(islice(with_downtime(rows[:2], down, 0.0, DAY), 20)) == [
        (0.0, False),
        (HOUR, None),
        (2 * HOUR, True),
        (3 * HOUR, None),
    ]
