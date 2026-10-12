"""G11 E: a long burn that does not reach the rooms — information and a warning, never control."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.long_run import (
    AVERAGE_S,
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
    for an hour is too hot; averages over 30 min, room samples every 5 min."""
    assert (LONG_RUN_S, NOT_RISING_K, HOLDING_K, HIGH_MODULATION) == (3 * HOUR, 0.2, 1.0, 90.0)
    assert (TOO_HOT_K, TOO_HOT_S, AVERAGE_S, SAMPLE_S) == (0.3, HOUR, 30 * MIN, 5 * MIN)


def short_rooms(_now: float) -> list[RoomLook]:
    return [look("a", 20.0, short=True), look("b", 21.0)]


def test_a_room_short_with_the_water_holding_its_setpoint_has_water_too_cool() -> None:
    """Three hours of flame, a room short and not warming, the flow at its setpoint: the water is
    too cool for it — one room counts like any other (addition 2)."""
    state = burn(3.1, short_rooms)
    assert state.found is LongRunClass.WATER_TOO_COOL
    assert state.rooms_named == ("a",)


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


def test_the_flame_off_or_unknown_ends_the_run() -> None:
    state = burn(3.1, short_rooms)
    assert state.found is LongRunClass.WATER_TOO_COOL
    off = follow_long_run(state, 3.2 * HOUR, False, 45.0, 45.0, 60.0, short_rooms(0.0))
    assert off == LongRun()
    unknown = follow_long_run(state, 3.2 * HOUR, None, 45.0, 45.0, 60.0, short_rooms(0.0))
    assert unknown == LongRun()


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
