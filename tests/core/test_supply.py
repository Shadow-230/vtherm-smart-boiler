"""The water reaching a circuit's emitters, and the return they give back."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.installation import Circuit, CircuitControl
from custom_components.vtherm_smart_boiler.core.supply import (
    Supply,
    SupplyReason,
    circuit_return,
    circuit_supply,
)

SHARED = Circuit("main")
FIXED = Circuit("floor", CircuitControl.PASSIVE_FIXED, fixed_temperature=35.0)


def test_an_unmixed_circuit_gets_the_boiler_flow() -> None:
    assert circuit_supply(SHARED, 45.0, True) == Supply(45.0)


def test_a_measured_circuit_flow_wins() -> None:
    mixed = Circuit("mixed", CircuitControl.SEPARATE)
    assert circuit_supply(mixed, 60.0, True, 32.0) == Supply(32.0)
    assert circuit_supply(SHARED, None, False, 40.0) == Supply(40.0)


@pytest.mark.parametrize("control", [CircuitControl.THROUGH_BOILER, CircuitControl.SEPARATE])
def test_a_mixed_circuit_without_its_own_sensor_is_not_known(control: CircuitControl) -> None:
    result = circuit_supply(Circuit("mixed", control), 60.0, True)
    assert result == Supply(None, SupplyReason.CIRCUIT_NOT_MEASURED)


def test_an_unknown_or_stale_boiler_flow() -> None:
    assert circuit_supply(SHARED, None, True) == Supply(None, SupplyReason.FLOW_UNKNOWN)
    assert circuit_supply(SHARED, 45.0, False) == Supply(None, SupplyReason.FLOW_STALE)


def test_a_passive_fixed_circuit_gets_at_most_its_temperature() -> None:
    assert circuit_supply(FIXED, 60.0, True) == Supply(35.0)
    assert circuit_supply(FIXED, 30.0, True) == Supply(30.0)
    undeclared = Circuit("floor", CircuitControl.PASSIVE_FIXED)
    assert circuit_supply(undeclared, 60.0, True) == Supply(60.0)


def test_only_an_unmixed_circuit_gives_back_the_boiler_return() -> None:
    assert circuit_return(SHARED, 38.0) == 38.0
    for control in (
        CircuitControl.THROUGH_BOILER,
        CircuitControl.SEPARATE,
        CircuitControl.PASSIVE_FIXED,
    ):
        assert circuit_return(Circuit("c", control), 38.0) is None


# --- I9.1: lasting and momentary reasons, and the time of the reading (water-interface.md §4.1) --


def test_no_water_sensor_at_all_is_not_mapped() -> None:
    """No boiler flow mapped and no circuit sensor: lasting, `not_mapped` — not the momentary
    `flow_unknown` a mapped flow without a value gives."""
    assert circuit_supply(SHARED, None, False, flow_mapped=False) == Supply(
        None, SupplyReason.NOT_MAPPED
    )
    assert circuit_supply(FIXED, None, False, flow_mapped=False) == Supply(
        None, SupplyReason.NOT_MAPPED
    )
    assert circuit_supply(SHARED, None, True) == Supply(None, SupplyReason.FLOW_UNKNOWN)


@pytest.mark.parametrize("control", [CircuitControl.THROUGH_BOILER, CircuitControl.SEPARATE])
def test_a_mixed_circuit_s_own_sensor_lost_for_now_is_momentary(control: CircuitControl) -> None:
    """A mixed circuit whose own sensor is mapped but reads nothing usable, or nothing fresh,
    now: momentary (`flow_unknown`, `flow_stale`), not the lasting `circuit_not_measured`; the
    boiler's flow says nothing about it either way."""
    mixed = Circuit("mixed", control)
    assert circuit_supply(mixed, 60.0, True, own_mapped=True) == Supply(
        None, SupplyReason.FLOW_UNKNOWN
    )
    assert circuit_supply(mixed, 60.0, True, own_mapped=True, own_stale=True) == Supply(
        None, SupplyReason.FLOW_STALE
    )
    assert circuit_supply(mixed, None, False, flow_mapped=False) == Supply(
        None, SupplyReason.CIRCUIT_NOT_MEASURED
    )


def test_a_straight_circuit_falls_back_to_the_boiler_flow() -> None:
    """A circuit fed straight from the boiler whose own sensor is lost for now takes the
    boiler's flow; without the boiler's flow mapped, its own sensor's reason."""
    assert circuit_supply(SHARED, 45.0, True, own_mapped=True, flow_at=100.0) == Supply(
        45.0, measured_at=100.0
    )
    assert circuit_supply(
        SHARED, None, False, flow_mapped=False, own_mapped=True, own_stale=True
    ) == Supply(None, SupplyReason.FLOW_STALE)


def test_the_supply_carries_the_time_of_the_reading_it_uses() -> None:
    mixed = Circuit("mixed", CircuitControl.SEPARATE)
    assert circuit_supply(mixed, 60.0, True, 32.0, flow_at=100.0, own_at=90.0) == Supply(
        32.0, measured_at=90.0
    )
    assert circuit_supply(SHARED, 45.0, True, flow_at=100.0) == Supply(45.0, measured_at=100.0)
    assert circuit_supply(FIXED, 60.0, True, flow_at=100.0) == Supply(35.0, measured_at=100.0)
    assert circuit_supply(SHARED, 45.0, False, flow_at=100.0).measured_at is None
