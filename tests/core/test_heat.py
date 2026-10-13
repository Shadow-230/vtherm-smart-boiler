"""Heat available per zone (I8, decision C1): the flame and the flow against the return."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.heat import (
    Against,
    Heat,
    HeatReason,
    heat_available,
    heat_through_any,
)
from custom_components.vtherm_smart_boiler.core.supply import Supply, SupplyReason


def test_available_while_the_flame_burns_and_the_flow_is_above_the_return() -> None:
    result = heat_available(Supply(45.0), True, 38.0, 20.0, False)
    assert result == Heat(True, None, 7.0, Against.RETURN)


def test_the_return_decides_where_it_is_known_not_the_room() -> None:
    """Water well above the room but no warmer than the return: the emitters take no heat."""
    result = heat_available(Supply(40.0), True, 39.0, 20.0, False)
    assert result == Heat(False, HeatReason.FLOW_NEAR_RETURN, 1.0, Against.RETURN)


def test_against_the_room_only_without_a_return() -> None:
    assert heat_available(Supply(45.0), True, None, 20.0, False) == Heat(
        True, None, 25.0, Against.ROOM
    )
    near = heat_available(Supply(22.5), True, None, 20.0, False)
    assert near == Heat(False, HeatReason.FLOW_NEAR_ROOM, 2.5, Against.ROOM)


def test_the_flame_out_is_no_heat() -> None:
    """Hot water still in the pipes after the flame went out is not heat the boiler gives."""
    result = heat_available(Supply(60.0), False, 40.0, 20.0, False)
    assert result == Heat(False, HeatReason.FLAME_OFF)


@pytest.mark.parametrize("flame", [True, None])
def test_a_hot_water_draw_with_priority_is_no_heat(flame: bool | None) -> None:
    result = heat_available(Supply(70.0), flame, 40.0, 20.0, True)
    assert result == Heat(False, HeatReason.DHW_ACTIVE)


def test_an_unknown_hot_water_state_does_not_block() -> None:
    assert heat_available(Supply(45.0), True, 38.0, 20.0, None).available is True


def test_an_unknown_or_stale_flame_cannot_be_told() -> None:
    result = heat_available(Supply(45.0), None, 38.0, 20.0, False)
    assert result == Heat(None, HeatReason.FLAME_UNKNOWN)


def test_without_a_flame_signal_the_flow_alone_decides() -> None:
    """The missing-data rule: an installation that maps no flame is judged on the water."""
    on = heat_available(Supply(45.0), None, 38.0, 20.0, False, flame_mapped=False)
    assert on == Heat(True, None, 7.0, Against.RETURN)
    off = heat_available(Supply(39.0), None, 38.0, 20.0, False, flame_mapped=False)
    assert off.available is False


@pytest.mark.parametrize(
    ("supply", "expected"),
    [
        # The user's decision: unknown while the flow is unknown or stale, not "no".
        (Supply(None, SupplyReason.FLOW_STALE), Heat(None, HeatReason.FLOW_STALE)),
        (Supply(None, SupplyReason.FLOW_UNKNOWN), Heat(None, HeatReason.FLOW_UNKNOWN)),
        (Supply(None), Heat(None, HeatReason.FLOW_UNKNOWN)),
        (
            Supply(None, SupplyReason.CIRCUIT_NOT_MEASURED),
            Heat(None, HeatReason.CIRCUIT_NOT_MEASURED),
        ),
    ],
)
def test_supply_problems(supply: Supply, expected: Heat) -> None:
    assert heat_available(supply, True, 38.0, 20.0, False) == expected


def test_no_return_and_an_unknown_room() -> None:
    result = heat_available(Supply(45.0), True, None, None, False)
    assert result == Heat(None, HeatReason.ROOM_UNKNOWN)


def test_against_the_return_with_hysteresis() -> None:
    assert heat_available(Supply(41.5), True, 40.0, 20.0, False).available is False
    assert heat_available(Supply(42.5), True, 40.0, 20.0, False).available is True
    # Once available it stays so until the difference falls below margin minus hysteresis.
    assert heat_available(Supply(41.5), True, 40.0, 20.0, False, True).available is True
    near = heat_available(Supply(40.5), True, 40.0, 20.0, False, True)
    assert near == Heat(False, HeatReason.FLOW_NEAR_RETURN, 0.5, Against.RETURN)


def test_against_the_room_with_hysteresis() -> None:
    assert heat_available(Supply(22.5), True, None, 20.0, False).available is False
    assert heat_available(Supply(23.5), True, None, 20.0, False).available is True
    assert heat_available(Supply(22.5), True, None, 20.0, False, True).available is True
    near = heat_available(Supply(21.5), True, None, 20.0, False, True)
    assert near == Heat(False, HeatReason.FLOW_NEAR_ROOM, 1.5, Against.ROOM)


def test_a_zone_split_between_circuits_has_heat_through_either() -> None:
    """I8.8b: a zone fed by two circuits through its devices takes heat while either circuit
    brings it; neither, what cannot be told comes before a no; the first no otherwise."""
    yes = Heat(True, None, 7.0, Against.RETURN)
    unknown = Heat(None, HeatReason.CIRCUIT_NOT_MEASURED)
    no = Heat(False, HeatReason.FLAME_OFF)
    assert heat_through_any([no, yes]) == yes
    assert heat_through_any([no, unknown]) == unknown
    assert heat_through_any([no, Heat(False, HeatReason.DHW_ACTIVE)]) == no
    assert heat_through_any([yes]) == yes


def test_no_water_sensor_cannot_tell_but_a_known_no_comes_first() -> None:
    """I9.1: no water sensor at all — `not_mapped`, unknown; hot water with priority and a flame
    known out still say no (water-interface.md §4, §5.1)."""
    none = Supply(None, SupplyReason.NOT_MAPPED)
    assert heat_available(none, True, 38.0, 20.0, False) == Heat(None, HeatReason.NOT_MAPPED)
    assert heat_available(none, None, None, 20.0, None, flame_mapped=False) == Heat(
        None, HeatReason.NOT_MAPPED
    )
    assert heat_available(none, False, 38.0, 20.0, False) == Heat(False, HeatReason.FLAME_OFF)
    assert heat_available(none, True, 38.0, 20.0, True) == Heat(False, HeatReason.DHW_ACTIVE)


# --- Mutation testing (2026-10-12): "clearly above" excludes the margin itself ---


@pytest.mark.parametrize(
    ("flow", "return_temp", "room", "previous", "expected"),
    [
        (42.0, 40.0, 20.0, None, Heat(False, HeatReason.FLOW_NEAR_RETURN, 2.0, Against.RETURN)),
        (41.0, 40.0, 20.0, True, Heat(False, HeatReason.FLOW_NEAR_RETURN, 1.0, Against.RETURN)),
        (23.0, None, 20.0, None, Heat(False, HeatReason.FLOW_NEAR_ROOM, 3.0, Against.ROOM)),
    ],
)
def test_a_flow_exactly_at_its_threshold_is_no_heat(
    flow: float, return_temp: float | None, room: float, previous: bool | None, expected: Heat
) -> None:
    """Negative: the flow exactly at the margin (or, once available, at the margin minus the
    hysteresis) is not clearly above what it is judged against — no heat."""
    assert heat_available(Supply(flow), True, return_temp, room, False, previous) == expected
