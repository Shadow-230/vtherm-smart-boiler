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
