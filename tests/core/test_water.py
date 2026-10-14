"""I9.1: what the plugin exposes about a zone's water (docs/en/specification/water-interface.md,
§4)."""

from __future__ import annotations

from custom_components.vtherm_smart_boiler.core.heat import Heat, HeatReason
from custom_components.vtherm_smart_boiler.core.supply import Supply, SupplyReason
from custom_components.vtherm_smart_boiler.core.water import ZoneWater, zone_water

HEAT = Heat(True)
NO_HEAT = Heat(False, HeatReason.FLAME_OFF)


def test_a_zone_in_one_circuit_shows_its_supply_and_heat() -> None:
    assert zone_water([Supply(45.0, measured_at=100.0)], HEAT) == ZoneWater(
        45.0, None, 100.0, True, None
    )
    assert zone_water([Supply(45.0, measured_at=100.0)], NO_HEAT) == ZoneWater(
        45.0, None, 100.0, False, HeatReason.FLAME_OFF
    )


def test_a_missing_supply_keeps_its_reason_and_has_no_time() -> None:
    """Negative: the supply unknown — `None` with its reason, and no time."""
    for reason in (
        SupplyReason.NOT_MAPPED,
        SupplyReason.FLOW_UNKNOWN,
        SupplyReason.FLOW_STALE,
        SupplyReason.CIRCUIT_NOT_MEASURED,
    ):
        water = zone_water(
            [Supply(None, reason, measured_at=100.0)], Heat(None, HeatReason.ROOM_UNKNOWN)
        )
        assert water == ZoneWater(None, reason, None, None, HeatReason.ROOM_UNKNOWN), reason


def test_a_zone_in_several_circuits_with_the_same_water_gives_it() -> None:
    """Circuits giving the same water — the boiler's flow to two straight circuits — give it,
    with the latest reading's time."""
    supplies = [Supply(45.0, measured_at=100.0), Supply(45.0, measured_at=120.0)]
    assert zone_water(supplies, HEAT) == ZoneWater(45.0, None, 120.0, True, None)


def test_a_zone_in_several_circuits_with_different_water_is_not_known() -> None:
    """Negative: different waters, or one unknown — `several_circuits`, a lasting fallback (one
    heat source per VT thermostat is expected); the heat through either still shows."""
    differ = [Supply(45.0, measured_at=100.0), Supply(32.0, measured_at=100.0)]
    one_unknown = [Supply(45.0, measured_at=100.0), Supply(None, SupplyReason.FLOW_STALE)]
    for supplies in (differ, one_unknown):
        assert zone_water(supplies, HEAT) == ZoneWater(
            None, SupplyReason.SEVERAL_CIRCUITS, None, True, None
        )


def test_the_reasons_are_the_specified_strings() -> None:
    """The values a consumer reads (water-interface.md §4.1, §4.2)."""
    assert {r.value for r in SupplyReason} == {
        "not_mapped",
        "circuit_not_measured",
        "several_circuits",
        "flow_unknown",
        "flow_stale",
    }
    assert {r.value for r in HeatReason} == {
        "dhw_active",
        "flame_off",
        "flame_unknown",
        "flow_near_return",
        "flow_near_room",
        "flow_unknown",
        "flow_stale",
        "circuit_not_measured",
        "not_mapped",
        "room_unknown",
    }
