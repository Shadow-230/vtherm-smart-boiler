"""G11 E: a long burn that does not reach the rooms — information and a warning, never control."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.long_run import (
    AVERAGE_S,
    GAP_S,
    HIGH_MODULATION,
    HOLDING_K,
    LONG_RUN_S,
    NOT_RISING_K,
    SAMPLE_S,
    TOO_HOT_K,
    TOO_HOT_S,
    LongRun,
    LongRunClass,
    RoomLook,
    follow_long_run,
    tally,
)

MIN = 60.0
HOUR = 3600.0


def look(zone_id: str, temperature: float, target: float = 21.0, short: bool = False) -> RoomLook:
    return RoomLook(zone_id, temperature, target, short)


def burn(
    hours: float,
    rooms,
    flow: float | None = 45.0,
    setpoint: float | None = 45.0,
    modulation: float | None = 60.0,
    flame: bool | None = True,
    start: float = 0.0,
    state: LongRun | None = None,
) -> LongRun:
    """A look a minute for ``hours``; ``rooms`` gives the rooms at each moment."""
    state = state or LongRun()
    steps = round(hours * HOUR / MIN)
    for i in range(steps + 1):
        now = start + i * MIN
        state = follow_long_run(state, now, flame, flow, setpoint, modulation, rooms(now))
    return state


def test_the_rules_values() -> None:
    """Provisional (K4), each with its reason in the plan: 3 h of burning, a room rising less
    than 0.2 K is not warming, 1 K is holding the setpoint, 90 % is high modulation, 0.3 K over
    for an hour is too hot; averages over 30 min, room samples every 5 min; a flame gap of 30 min
    ends a run (K4, 2026-11-17)."""
    assert (LONG_RUN_S, NOT_RISING_K, HOLDING_K, HIGH_MODULATION) == (3 * HOUR, 0.2, 1.0, 90.0)
    assert (TOO_HOT_K, TOO_HOT_S, AVERAGE_S, SAMPLE_S) == (0.3, HOUR, 30 * MIN, 5 * MIN)
    assert GAP_S == 30 * MIN


def short_rooms(_now: float) -> list[RoomLook]:
    return [look("a", 20.0, short=True), look("b", 21.0)]


def test_a_room_short_with_the_water_holding_its_setpoint_has_water_too_cool() -> None:
    """Three hours of flame, a room short and not warming, the flow at its setpoint: the water is
    too cool for it — one room counts like any other (addition 2)."""
    state = burn(3.1, short_rooms)
    assert state.found is LongRunClass.WATER_TOO_COOL
    assert state.rooms_named == ("a",)


def test_water_above_its_setpoint_with_the_flame_on_throughout_has_water_too_cool() -> None:
    """J4's F15 (Q2): a curve too low, the boiler burning at its minimum without a break, its
    water above the setpoint it cannot go down to (34 °C for 31.7 °C, modulation 0), a room
    short and not warming: the water reached what was asked and is too cool for the room."""
    state = burn(3.1, short_rooms, flow=34.0, setpoint=31.7, modulation=0.0)
    assert state.found is LongRunClass.WATER_TOO_COOL
    assert state.rooms_named == ("a",)


def swinging(
    hours: float,
    rooms,
    flow,
    setpoint: float = 45.0,
    modulation: float | None = 60.0,
) -> LongRun:
    """``burn`` with the flame on throughout and the flow given at each moment."""
    state = LongRun()
    for i in range(round(hours * HOUR / MIN) + 1):
        now = i * MIN
        state = follow_long_run(state, now, True, flow(now), setpoint, modulation, rooms(now))
    return state


def test_a_flow_that_swings_or_lags_but_reaches_its_setpoint_has_water_too_cool() -> None:
    """The user's note of 2026-11-22: the boiler's own hysteresis and its delays keep the flow
    from holding its setpoint within a kelvin. Reaching it — at most ``HOLDING_K`` under it, or
    above — once in the last ``AVERAGE_S`` is enough: here 3 K under most of the time, at the
    setpoint one minute in twenty."""

    def flow(now: float) -> float:
        return 45.0 if round(now / MIN) % 20 == 0 else 42.0

    state = swinging(3.1, short_rooms, flow)
    assert state.found is LongRunClass.WATER_TOO_COOL


def test_the_power_limit_comes_first_even_if_the_flow_once_reached_its_setpoint() -> None:
    """On average below its setpoint by more than ``HOLDING_K`` at the burner's top, with the
    flame on throughout: the power limit, though the flow touched its setpoint once."""

    def flow(now: float) -> float:
        return 45.0 if round(now / MIN) % 20 == 0 else 42.0

    state = swinging(3.1, short_rooms, flow, modulation=95.0)
    assert state.found is LongRunClass.POWER_LIMIT


def test_nothing_before_three_hours_of_flame() -> None:
    assert burn(2.9, short_rooms).found is None


def test_a_room_that_warms_is_no_case() -> None:
    """The room short but rising 0.5 K over the three hours: it gets there — nothing."""

    def warming(now: float) -> list[RoomLook]:
        return [look("a", 20.0 + 0.5 * now / LONG_RUN_S, short=True)]

    assert burn(3.1, warming).found is None


def test_short_rooms_below_the_setpoint_at_high_modulation_are_the_boilers_power_limit() -> None:
    state = burn(3.1, short_rooms, flow=42.0, setpoint=45.0, modulation=95.0)
    assert state.found is LongRunClass.POWER_LIMIT
    assert state.rooms_named == ("a",)


@pytest.mark.parametrize(
    ("flow", "setpoint", "modulation"),
    [(42.0, 45.0, 70.0), (42.0, 45.0, None), (45.0, None, 95.0), (None, 45.0, 95.0)],
    ids=["moderate_modulation", "modulation_unknown", "setpoint_unknown", "flow_unknown"],
)
def test_below_the_setpoint_without_high_modulation_or_data_is_not_judged(
    flow: float | None, setpoint: float | None, modulation: float | None
) -> None:
    """Below its setpoint but not at the burner's top, or without the data to say: neither the
    power limit nor water too cool."""
    assert burn(3.1, short_rooms, flow=flow, setpoint=setpoint, modulation=modulation).found is None


def test_rooms_over_their_setpoints_for_an_hour_have_water_too_hot() -> None:
    def warm(_now: float) -> list[RoomLook]:
        return [look("a", 21.5), look("b", 21.4)]

    state = burn(3.1, warm)
    assert state.found is LongRunClass.WATER_TOO_HOT
    assert state.rooms_named == ("a", "b")


def test_rooms_at_their_setpoints_are_the_ideal_state() -> None:
    def at(_now: float) -> list[RoomLook]:
        return [look("a", 21.1), look("b", 20.9)]

    assert burn(3.5, at).found is None


def test_the_flame_off_past_the_gap_or_unknown_ends_the_run() -> None:
    """K4 (F10): a gap in the flame of up to ``GAP_S`` keeps the run — a boiler cycling burns in
    one; longer, or the flame unknown, ends it."""
    state = burn(3.1, short_rooms)
    assert state.found is LongRunClass.WATER_TOO_COOL
    last = state.water[-1][0]
    gap = follow_long_run(state, last + GAP_S, False, 40.0, 45.0, None, short_rooms(0.0))
    assert gap.burning_since == 0.0
    assert gap.found is LongRunClass.WATER_TOO_COOL  # it reached its setpoint, then stopped
    off = follow_long_run(gap, last + GAP_S + 1.0, False, 40.0, 45.0, None, short_rooms(0.0))
    assert off == LongRun()
    unknown = follow_long_run(state, last + MIN, None, 45.0, 45.0, 60.0, short_rooms(0.0))
    assert unknown == LongRun()
    assert follow_long_run(LongRun(), 0.0, False, 40.0, 45.0, None, short_rooms(0.0)) == LongRun()


def cycling(
    hours: float,
    rooms,
    peak: float = 45.0,
    setpoint: float = 45.0,
    modulation: float | None = 30.0,
    on_min: int = 10,
    off_min: int = 5,
) -> LongRun:
    """A boiler cycling at its minimum: ``on_min`` minutes of flame with the flow rising to
    ``peak``, then ``off_min`` minutes off with it falling 5 K, a look a minute."""
    state = LongRun()
    period = on_min + off_min
    for i in range(round(hours * HOUR / MIN) + 1):
        phase = i % period
        on = phase < on_min
        flow = (
            peak - 5.0 + 5.0 * phase / (on_min - 1)
            if on
            else peak - 5.0 * (phase - on_min + 1) / off_min
        )
        state = follow_long_run(
            state, i * MIN, on, flow, setpoint, modulation if on else None, rooms(i * MIN)
        )
    return state


def test_a_cycling_boiler_reaching_its_setpoint_with_rooms_short_has_water_too_cool() -> None:
    """K4 (F10): the boiler cycles at its minimum — the flow reaches its setpoint, the burner
    stops, and again — for three hours while a room stays short and does not warm: the water is
    too cool for it, as with the flame on throughout (Salford: cycling and lost comfort at a low
    flow; Bennett: cycling from the minimum output against the demand)."""
    state = cycling(3.1, short_rooms)
    assert state.found is LongRunClass.WATER_TOO_COOL
    assert state.rooms_named == ("a",)
    assert state.burning_since == 0.0
    assert state.burning_s == pytest.approx(3.1 * HOUR)


def test_a_cycling_boiler_short_of_its_setpoint_is_not_judged() -> None:
    """Negative: cycling with the flow never within ``HOLDING_K`` of its setpoint — the boiler
    stops for another reason — is neither water too cool nor, without its flame on throughout,
    the power limit, even at the burner's top."""
    assert cycling(3.1, short_rooms, peak=43.5).found is None
    assert cycling(3.1, short_rooms, peak=42.0, modulation=95.0).found is None


def test_the_power_limit_needs_three_hours_of_flame_without_a_break() -> None:
    """The power limit — a warning — keeps its bar: the flame on throughout the run's last three
    hours; a run whose flame came back within ``GAP_S`` an hour ago is not it yet."""
    first = burn(1.0, short_rooms, flow=42.0, setpoint=45.0, modulation=95.0)
    last = first.water[-1][0]
    state = follow_long_run(first, last + 20 * MIN, False, 40.0, 45.0, None, short_rooms(0.0))
    state = burn(
        2.2,
        short_rooms,
        flow=42.0,
        setpoint=45.0,
        modulation=95.0,
        start=last + 21 * MIN,
        state=state,
    )
    assert state.burning_since == 0.0
    assert state.found is None
    state = burn(
        3.0,
        short_rooms,
        flow=42.0,
        setpoint=45.0,
        modulation=95.0,
        start=state.water[-1][0] + MIN,
        state=state,
    )
    assert state.found is LongRunClass.POWER_LIMIT


def test_a_clock_set_back_starts_the_run_again() -> None:
    state = burn(3.1, short_rooms, start=10 * HOUR)
    again = follow_long_run(state, 5 * HOUR, True, 45.0, 45.0, 60.0, short_rooms(0.0))
    assert again.burning_since == 5 * HOUR
    assert again.found is None


def test_the_tally_counts_each_run_once_and_its_hours() -> None:
    """For 0.4's tuning: each class's runs, counted once as one begins, and its hours."""
    totals = tally({}, None, LongRunClass.WATER_TOO_COOL, 60.0)
    totals = tally(totals, LongRunClass.WATER_TOO_COOL, LongRunClass.WATER_TOO_COOL, 3600.0)
    totals = tally(totals, LongRunClass.WATER_TOO_COOL, None, 60.0)
    assert totals == {"water_too_cool_runs": 1, "water_too_cool_hours": pytest.approx(61 / 60)}


# --- Mutation testing (2026-10-12): exact boundaries, partial room data and the tally ----------


def warm_rooms(_now: float) -> list[RoomLook]:
    return [look("a", 21.5), look("b", 21.4)]


def test_a_second_look_at_the_same_moment_keeps_the_run() -> None:
    """Negative: only a moment before the last look starts the run again — a look at the same
    moment does not."""
    state = burn(3.1, short_rooms)
    again = follow_long_run(state, state.water[-1][0], True, 45.0, 45.0, 60.0, short_rooms(0.0))
    assert again.burning_since == 0.0
    assert again.found is LongRunClass.WATER_TOO_COOL


def test_a_look_exactly_the_average_span_old_still_counts() -> None:
    """The water is averaged over the last ``AVERAGE_S``, its ends included: the flow 1.5 K below
    its setpoint now, at its setpoint exactly ``AVERAGE_S`` ago, holds it on average."""
    state = burn(3.1, short_rooms)
    now = state.water[-1][0] + AVERAGE_S
    later = follow_long_run(state, now, True, 43.5, 45.0, 60.0, short_rooms(now))
    assert [w[0] for w in later.water] == [now - AVERAGE_S, now]
    assert later.found is LongRunClass.WATER_TOO_COOL


@pytest.mark.parametrize(
    ("hours", "found", "named"),
    [(2.9, None, ()), (3.0, LongRunClass.WATER_TOO_HOT, ("a", "b"))],
    ids=["before", "exactly"],
)
def test_a_run_is_judged_from_exactly_three_hours_of_flame(
    hours: float, found: LongRunClass | None, named: tuple[str, ...]
) -> None:
    """Negative: a run that began at any moment (not only at 0) is not judged before
    ``LONG_RUN_S`` of flame, and names no room; from exactly ``LONG_RUN_S`` on it is."""
    state = burn(hours, warm_rooms, start=10 * HOUR)
    assert state.found is found
    assert state.rooms_named == named


def test_a_rooms_temperature_is_kept_every_five_minutes_and_unknown_is_not_kept() -> None:
    """A room's temperature is sampled every ``SAMPLE_S`` exactly, not at every look; an unknown
    temperature adds no sample."""
    state = burn(0.5, lambda _now: [look("a", 20.0)])
    assert state.rooms == (("a", tuple((k * SAMPLE_S, 20.0) for k in range(7))),)
    unknown = follow_long_run(
        LongRun(), 0.0, True, 45.0, 45.0, 60.0, [RoomLook("a", None, 21.0, True)]
    )
    assert unknown.rooms == (("a", ()),)


def test_the_oldest_sample_exactly_a_run_and_a_sample_old_still_counts() -> None:
    """A room 1 K cooler only at the run's very start has warmed: its first sample, exactly
    ``LONG_RUN_S + SAMPLE_S`` old, is still kept and compared — no case."""

    def warmed(now: float) -> list[RoomLook]:
        return [look("a", 19.0 if now < SAMPLE_S else 20.0, short=True)]

    state = burn((LONG_RUN_S + SAMPLE_S) / HOUR, warmed)
    assert state.rooms[0][1][0] == (0.0, 19.0)
    assert state.found is None


@pytest.mark.parametrize(
    ("known_from", "found"),
    [(SAMPLE_S, LongRunClass.WATER_TOO_COOL), (HOUR, None)],
    ids=["from_exactly_three_hours_back", "only_the_last_two_hours"],
)
def test_a_room_known_only_for_part_of_the_run(
    known_from: float, found: LongRunClass | None
) -> None:
    """Negative: a room's warming is judged only against a sample at least
    ``LONG_RUN_S - SAMPLE_S`` old — one exactly that old counts; a room known only for the
    run's last two hours is not judged."""

    def late(now: float) -> list[RoomLook]:
        return [RoomLook("a", 20.0 if now >= known_from else None, 21.0, True)]

    assert burn(LONG_RUN_S / HOUR, late).found is found


@pytest.mark.parametrize(
    ("flow", "modulation", "found"),
    [(44.0, 95.0, LongRunClass.WATER_TOO_COOL), (42.0, 90.0, LongRunClass.POWER_LIMIT)],
    ids=["gap_exactly_holding", "modulation_exactly_high"],
)
def test_the_water_classes_at_their_exact_bounds(
    flow: float, modulation: float, found: LongRunClass
) -> None:
    """The flow exactly ``HOLDING_K`` below its setpoint still holds it (not the power limit,
    even at the burner's top); a modulation of exactly ``HIGH_MODULATION`` is high."""
    state = burn(3.1, short_rooms, flow=flow, setpoint=45.0, modulation=modulation)
    assert state.found is found


@pytest.mark.parametrize(
    ("warm_from", "found"),
    [(126 * MIN, LongRunClass.WATER_TOO_HOT), (156 * MIN, None)],
    ids=["exactly_an_hour", "half_an_hour"],
)
def test_rooms_too_warm_from_exactly_an_hour(warm_from: float, found: LongRunClass | None) -> None:
    """Negative: every room over its setpoint for half an hour is not yet the water too hot;
    for exactly ``TOO_HOT_S`` it is."""

    def rooms(now: float) -> list[RoomLook]:
        return warm_rooms(now) if now >= warm_from else [look("a", 21.0), look("b", 21.0)]

    assert burn(3.1, rooms).found is found


def test_the_tally_adds_to_the_kept_counts_and_no_hours_for_no_time() -> None:
    """A class that begins adds one run to the kept count — even for a single look — and a step
    of no time (the first look) adds no hours; a change of class is a run of the new one."""
    totals = tally({"water_too_cool_runs": 2}, None, LongRunClass.WATER_TOO_COOL, 0.0)
    assert totals == {"water_too_cool_runs": 3, "water_too_cool_hours": 0.0}
    totals = tally(totals, LongRunClass.WATER_TOO_COOL, LongRunClass.POWER_LIMIT, 60.0)
    assert totals["power_limit_runs"] == 1
    assert totals["power_limit_hours"] == pytest.approx(1 / 60)
