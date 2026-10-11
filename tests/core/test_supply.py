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
