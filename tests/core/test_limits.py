"""Flow limits and the alarm "handed back in frost"."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.limits import (
    FROST_ALARM_LIMIT,
    FROST_ALARM_RELEASE,
    FlowLimits,
    Grid,
    LimitCode,
    Limited,
    handed_back_in_frost,
    install_cap,
    is_on_grid,
    limit_flow,
    on_grid,
    room_temperatures,
    within_write_bounds,
    write_bounds,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

LIMITS = FlowLimits(hard_min=25.0, hard_max=70.0)


def test_within_limits_is_unchanged() -> None:
    assert limit_flow(45.0, LIMITS) == Limited(45.0)


def test_hard_minimum_and_maximum() -> None:
    assert limit_flow(20.0, LIMITS) == Limited(25.0, (LimitCode.HARD_MIN,))
    assert limit_flow(90.0, LIMITS) == Limited(70.0, (LimitCode.HARD_MAX,))


def test_no_weather_ceiling_of_its_own() -> None:
    """I8 (decision B6): the "correction range" is gone — above the curve only the comfort
    correction goes, bounded by its own limit; here the installation's caps alone hold."""
    assert limit_flow(60.0, LIMITS) == Limited(60.0)  # 20 K above a 40 °C curve: not held
    assert not hasattr(FlowLimits(), "ceiling_band")
    assert "CEILING" not in LimitCode.__members__


def test_the_lowest_cap_wins() -> None:
    result = limit_flow(60.0, LIMITS, circuit_max=45.0, boiler_max=65.0)
    assert result == Limited(45.0, (LimitCode.CIRCUIT_MAX,))
    boiler = limit_flow(60.0, LIMITS, circuit_max=None, boiler_max=55.0)
    assert boiler == Limited(55.0, (LimitCode.BOILER_MAX,))


def test_caps_that_protect_the_installation_win_over_the_hard_minimum() -> None:
    limits = FlowLimits(hard_min=30.0, hard_max=70.0)
    result = limit_flow(20.0, limits, circuit_max=28.0)
    assert result == Limited(28.0, (LimitCode.HARD_MIN, LimitCode.CIRCUIT_MAX))


def test_a_circuit_asking_holds_the_water_at_its_need() -> None:
    """I8.8 (decision F6): a circuit run by other automation that asks holds the water at its
    need, given here; the caps still win. A thermostatic mixing valve sets no lower bound (the
    user's decision of 2026-10-14): the boiler follows its curve."""
    assert limit_flow(32.0, LIMITS, need=45.0) == Limited(45.0, (LimitCode.CIRCUIT_NEED,))
    assert limit_flow(50.0, LIMITS, need=45.0) == Limited(50.0)  # the curve above it
    assert limit_flow(32.0, LIMITS, need=60.0, circuit_max=55.0) == Limited(
        55.0, (LimitCode.CIRCUIT_NEED, LimitCode.CIRCUIT_MAX)
    )


def test_a_value_goes_on_the_entitys_grid_inside_the_limits() -> None:
    """P-98: rounding to the entity's step stays inside the limits — the grid value just inside
    where the nearest falls outside; none without one."""
    assert on_grid(70.0, 0.5, 0.25, 25.0, 70.0) == 69.75  # a tie, the nearest above is outside
    assert on_grid(45.3, 0.5, 0.0, 25.0, 70.0) == 45.5
    assert on_grid(24.9, 1.0, 0.0, 25.0, 70.0) == 25.0  # the nearest (25) is inside
    assert on_grid(25.2, 5.0, 0.0, 25.2, 70.0) == 30.0  # just inside from below
    assert on_grid(40.0, 5.0, 0.0, 41.0, 44.0) is None  # no grid value inside
    assert on_grid(45.37, 0.0, 0.0, 25.0, 70.0) == 45.37  # no step: no grid
    assert on_grid(80.0, 0.0, 0.0, None, 70.0) is None
    assert is_on_grid(69.75, 0.5, 0.25)
    assert not is_on_grid(70.0, 0.5, 0.25)
    assert is_on_grid(45.123, 0.0, 0.0)


def test_a_grid_in_another_unit_is_applied_in_that_unit() -> None:
    """P-15: a °F entity's grid is applied in °F and the value returned in °C; its step as a
    temperature difference decides whether it is too coarse (above 1 K)."""
    fahrenheit = Grid(step=1.0, minimum=50.0, maximum=190.0, scale=1.8, offset=32.0)
    value = fahrenheit.put(45.3, 25.0, 70.0)
    assert value is not None
    assert fahrenheit.to_unit(value) == pytest.approx(114.0)
    assert not fahrenheit.too_coarse  # 0.56 K
    assert Grid(step=2.0, scale=1.8, offset=32.0).too_coarse  # 1.1 K
    assert Grid(step=1.0).step_k == 1.0
    assert not Grid(step=1.0).too_coarse
    assert Grid(step=5.0).too_coarse
    assert Grid(step=0.5, minimum=30.0, maximum=60.0).put(20.0, 25.0, 70.0) == 30.0
    assert Grid(step=0.5, minimum=30.0, maximum=60.0).put(20.0, None, 25.0) is None


def test_the_bounds_a_written_value_keeps() -> None:
    limits = FlowLimits(hard_min=25.0, hard_max=70.0)
    assert write_bounds(limits) == (25.0, 70.0)
    assert write_bounds(limits, circuit_max=45.0, boiler_max=80.0) == (25.0, 45.0)
    assert write_bounds(limits, circuit_max=20.0) == (20.0, 20.0)


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        (45.0, {"circuit_max": 40.0}, 40.0),  # PB-11: a maximum lowered since it was written
        (45.0, {"boiler_max": 42.0, "circuit_max": 44.0}, 42.0),
        (75.0, {}, 70.0),  # the hard maximum
        (20.0, {}, 25.0),  # the lowest water temperature raised since
        (45.0, {"circuit_max": 20.0}, 20.0),  # a cap below the hard minimum wins over it
        (45.0, {"circuit_max": 50.0}, 45.0),  # inside: unchanged
    ],
)
def test_a_value_is_moved_inside_the_bounds_a_written_value_keeps(
    value: float, kwargs: dict[str, float], expected: float
) -> None:
    limits = FlowLimits(hard_min=25.0, hard_max=70.0)
    assert within_write_bounds(value, limits, **kwargs) == expected


@pytest.mark.parametrize(
    "kwargs",
    [{"hard_min": 50.0, "hard_max": 40.0}, {"hard_max": 99.0}],
)
def test_invalid_limits(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        FlowLimits(**kwargs)


def zone(temp: float | None, reported: float | None = 100.0, zid: str = "z") -> ZoneState:
    return ZoneState(zid, temperature=temp, reported_at=reported)


def test_the_room_temperatures_are_the_fresh_plausible_ones() -> None:
    """Every room's fresh, plausible temperature; a stale, unknown or broken one is left out."""
    rooms = [zone(4.0), zone(None), zone(2.0, reported=-10_000.0), zone(-127.0), zone(20.0)]
    assert room_temperatures(rooms, 100.0, 600.0) == [4.0, 20.0]


# --- V7, S-57: handed back while a room is near freezing ----------------------------------------


def in_frost(
    zones: list[ZoneState],
    active: bool = False,
    heating_stops: bool = True,
    controlling: bool = False,
) -> bool | None:
    return handed_back_in_frost(
        zones,
        100.0,
        600.0,
        heating_stops=heating_stops,
        controlling=controlling,
        active=active,
    )


def test_the_alarm_keeps_the_frost_options_old_defaults() -> None:
    """I12.10 (decision 4): frost protection is VT's, so the alarm's limit and release are no
    options; they keep the values the options had by default."""
    assert (FROST_ALARM_LIMIT, FROST_ALARM_RELEASE) == (5.0, 7.0)


def test_handed_back_in_frost_rises_below_the_limit_and_clears_at_the_release() -> None:
    """S-57: where a hand-back stops heating and control does not hold the boiler, a room below
    5 °C raises the alarm; it holds until every room with a known temperature is at or above
    7 °C."""
    assert in_frost([zone(4.0), zone(20.0)])
    assert not in_frost([zone(6.0)])  # between the limit and the release: not raised
    assert in_frost([zone(6.0)], active=True)  # once raised, it holds below the release
    assert in_frost([zone(7.5), zone(6.9)], active=True)
    assert not in_frost([zone(7.5)], active=True)
    assert not in_frost([zone(7.0)], active=True)  # at the release: off
    assert not in_frost([zone(5.0)])  # at the limit: not below it


def test_handed_back_in_frost_never_while_controlling_or_where_something_else_heats() -> None:
    """Negatives: while control holds the boiler VT's frost protection reaches it; with a
    thermostat or a device's own control after the hand-back, frost protection rests on it."""
    assert not in_frost([zone(3.0)], controlling=True)
    assert not in_frost([zone(3.0)], active=True, controlling=True)
    assert not in_frost([zone(3.0)], heating_stops=False)
    assert not in_frost([zone(3.0)], active=True, heating_stops=False)


def test_handed_back_in_frost_ignores_unknown_stale_and_implausible_rooms() -> None:
    """Missing data: a room with no temperature, a stale one or a broken sensor is not counted;
    with no room known the alarm cannot be judged (``None``) — the control unit holds its last
    state for an hour, then shows it unknown (S-16, Y1). One known room judges."""
    assert in_frost([zone(None)]) is None
    assert in_frost([zone(None)], active=True) is None
    assert in_frost([zone(2.0, reported=None)]) is None
    assert in_frost([zone(2.0, reported=-10_000.0)]) is None
    assert in_frost([zone(-127.0)]) is None
    assert in_frost([]) is None
    assert in_frost([], active=True) is None
    assert in_frost([zone(None), zone(20.0)]) is False
    assert in_frost([zone(None)], controlling=True) is False  # does not apply: known off


def test_handed_back_in_frost_watches_every_room_closed_or_not() -> None:
    """S-57 tells of a room near freezing while nothing heats, whether or not VT keeps it
    closed: the hand-back leaves it cold either way."""
    closed = ZoneState(
        "garage", 4.0, heating_enabled=False, valve_open=0.0, device_active=False, reported_at=100
    )
    assert in_frost([closed, zone(20.0, zid="living")])


def test_the_installation_cap_is_the_lowest_of_the_hard_circuit_and_boiler_maximum() -> None:
    """S-23: the ramp is skipped only above this cap — never for the weather ceiling."""
    assert install_cap(LIMITS) == 70.0
    assert install_cap(LIMITS, circuit_max=45.0) == 45.0
    assert install_cap(LIMITS, circuit_max=45.0, boiler_max=40.0) == 40.0
    assert install_cap(LIMITS, boiler_max=80.0) == 70.0


# --- Mutation testing (2026-10-12): bounds, ties and the grid's tolerance -----------------------


def test_the_hard_limits_take_10_and_95_and_refuse_beyond_or_equal() -> None:
    """The bounds of the form are inclusive: 10 °C as the lowest and 95 °C as the highest are
    taken. Negative: below 10, above 95, or a lowest equal to the highest are refused."""
    assert FlowLimits(hard_min=10.0, hard_max=50.0).hard_min == 10.0
    assert FlowLimits(hard_min=25.0, hard_max=95.0).hard_max == 95.0
    for kwargs in (
        {"hard_min": 9.9, "hard_max": 50.0},
        {"hard_min": 25.0, "hard_max": 95.5},
        {"hard_min": 50.0, "hard_max": 50.0},
    ):
        with pytest.raises(ValueError, match="must"):
            FlowLimits(**kwargs)


def test_a_request_exactly_at_a_limit_is_unchanged_and_names_no_limit() -> None:
    """A setpoint at the hard maximum or minimum is inside: nothing changed it, so no limit is
    named (a limit named where none acted would show a false reason)."""
    assert limit_flow(70.0, LIMITS) == Limited(70.0)
    assert limit_flow(25.0, LIMITS) == Limited(25.0)
    assert limit_flow(40.0, LIMITS, need=40.0) == Limited(40.0)
    assert limit_flow(45.0, LIMITS, circuit_max=45.0) == Limited(45.0)


def test_on_a_tie_the_limit_named_first_stands() -> None:
    """Equal limits: the hard maximum before a circuit's, the hard minimum before a circuit's
    need at the same value, and a lower bound equal to the cap is met without naming the cap."""
    assert limit_flow(80.0, LIMITS, circuit_max=70.0) == Limited(70.0, (LimitCode.HARD_MAX,))
    assert limit_flow(20.0, LIMITS, need=25.0) == Limited(25.0, (LimitCode.HARD_MIN,))
    limits = FlowLimits(hard_min=30.0, hard_max=70.0)
    assert limit_flow(20.0, limits, circuit_max=30.0) == Limited(30.0, (LimitCode.HARD_MIN,))


def test_without_a_grid_a_value_at_a_bound_is_inside() -> None:
    assert on_grid(25.0, 0.0, 0.0, 25.0, 70.0) == 25.0
    assert on_grid(70.0, 0.0, 0.0, 25.0, 70.0) == 70.0
    assert on_grid(24.9, 0.0, 0.0, 25.0, 70.0) is None


def test_a_value_on_a_coarse_grid_stays_where_it_is() -> None:
    """A value already on a grid of 2 K inside the bounds is not moved."""
    assert on_grid(30.0, 2.0, 0.0, 25.0, 70.0) == 30.0
    assert on_grid(45.0, 2.0, 1.0, 25.0, 70.0) == 45.0


def test_a_value_above_the_highest_comes_down_to_the_highest_on_the_grid() -> None:
    """The highest on the grid itself is the value given; one step lower would waste heat the
    limits allow."""
    assert on_grid(80.0, 0.5, 0.0, 25.0, 70.0) == 70.0
    assert on_grid(70.0, 0.5, 0.0, 25.0, 70.0) == 70.0


def test_a_grid_with_one_bound_or_none() -> None:
    """Missing bounds: a grid value is found without the highest, without the lowest, or with
    neither."""
    assert on_grid(80.0, 0.5, 0.0, 25.0, None) == 80.0
    assert on_grid(10.0, 0.5, 0.0, None, 70.0) == 10.0
    assert on_grid(45.3, 0.5, 0.0, None, None) == 45.5


def test_the_grids_tolerance_is_a_millionth_of_a_step() -> None:
    """A bound a fraction of a millionth of a step off a grid value counts as on it; one
    further off does not — the next grid value inside is taken, or none."""
    assert on_grid(10.0, 0.5, 0.0, 10.0000002, 70.0) == 10.0
    assert on_grid(10.0, 0.5, 0.0, 10.000001, 70.0) == 10.5
    assert on_grid(10.0, 0.5, 0.0, 0.0, 9.9999998) == 10.0
    assert on_grid(10.0, 0.5, 0.0, 0.0, 9.999999) == 9.5
    assert on_grid(10.0, 5.0, 0.0, 0.0, 9.999999) == 10.0  # 2e-7 of a 5 K step
    # Negative: the only grid value near [10.0000008, 10.2] lies more than the tolerance below.
    assert on_grid(10.0, 0.5, 0.0, 10.0000008, 10.2) is None


def test_on_the_grid_counts_from_its_base_with_a_relative_tolerance() -> None:
    """The grid starts at its base; the tolerance grows with the grid index (a millionth of it),
    and near zero it is a millionth of a step."""
    assert is_on_grid(20.1, 0.5, 0.1)
    assert not is_on_grid(20.2, 0.5, 0.1)
    assert is_on_grid(45.00001, 0.5, 0.0)
    assert not is_on_grid(45.001, 0.5, 0.0)
    assert not is_on_grid(0.0000015, 1.0, 0.0)


def test_a_grid_puts_a_value_inside_the_bounds_given_in_celsius() -> None:
    """The lower bound in °C lifts a value even where the entity's own minimum is lower; a bound
    not given leaves the entity's own range, or none."""
    assert Grid(step=0.5, minimum=10.0, maximum=60.0).put(20.0, 25.0, 70.0) == 25.0
    assert Grid(step=0.5, minimum=30.0, maximum=60.0).put(45.3, 25.0, None) == 45.5
    assert Grid(step=0.5, minimum=30.0, maximum=60.0).put(80.0, 25.0, None) == 60.0
    assert Grid(step=0.5).put(45.3) == 45.5


def test_the_plausible_room_range_is_inclusive() -> None:
    """−30 °C and 45 °C are rooms; a reading beyond them is a broken sensor (not counted, so
    alone it cannot be judged)."""
    assert in_frost([zone(-30.0)]) is True
    assert in_frost([zone(-30.1)]) is None
    assert in_frost([zone(45.0)]) is False
    assert in_frost([zone(45.1)]) is None


def test_handed_back_in_frost_ignores_a_stale_cold_room_beside_a_fresh_warm_one() -> None:
    """Negative (stale data): a stale reading of 2 °C is not counted once another room is known
    at 20 °C — the alarm is judged on fresh readings only."""
    assert in_frost([zone(2.0, reported=-10_000.0), zone(20.0)]) is False
