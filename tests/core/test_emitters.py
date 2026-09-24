"""Circuit supply temperature and the emitter power factor."""

from __future__ import annotations

import math

import pytest

from custom_components.vtherm_smart_boiler.core.emitters import (
    EMITTER_REFERENCE,
    FactorReason,
    FactorResult,
    FactorStatus,
    is_heating,
    mean_excess,
    power_factor,
    update_factor,
)
from custom_components.vtherm_smart_boiler.core.installation import (
    Circuit,
    CircuitControl,
    EmitterType,
    Zone,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.supply import Supply, SupplyReason, circuit_supply

# --- supply -------------------------------------------------------------------------------


def test_unmixed_circuit_gets_the_boiler_flow() -> None:
    assert circuit_supply(Circuit("c"), 55.0, flow_fresh=True) == Supply(55.0)


def test_supply_without_fresh_flow() -> None:
    assert circuit_supply(Circuit("c"), None, True) == Supply(None, SupplyReason.FLOW_UNKNOWN)
    assert circuit_supply(Circuit("c"), 55.0, False) == Supply(None, SupplyReason.FLOW_STALE)


def test_passive_fixed_circuit_is_capped() -> None:
    circuit = Circuit("tmv", CircuitControl.PASSIVE_FIXED, fixed_temperature=35.0)
    assert circuit_supply(circuit, 55.0, True) == Supply(35.0)
    assert circuit_supply(circuit, 30.0, True) == Supply(30.0)


@pytest.mark.parametrize("control", [CircuitControl.THROUGH_BOILER, CircuitControl.SEPARATE])
def test_mixed_circuit_needs_its_own_sensor(control: CircuitControl) -> None:
    circuit = Circuit("mix", control)
    assert circuit_supply(circuit, 55.0, True) == Supply(None, SupplyReason.CIRCUIT_NOT_MEASURED)
    assert circuit_supply(circuit, None, False, circuit_flow=32.0) == Supply(32.0)


# --- factor ---------------------------------------------------------------------------------


def test_mean_excess_cases() -> None:
    assert mean_excess(75.0, 65.0, 20.0) == pytest.approx(10 / math.log(55 / 45))
    assert mean_excess(40.0, 40.0, 20.0) == pytest.approx(20.0)  # return not below flow
    assert mean_excess(40.0, 18.0, 20.0) == pytest.approx(10.0)  # return below room
    assert mean_excess(19.0, 18.0, 20.0) == 0.0  # water colder than the room


def test_factor_is_one_at_the_reference_condition() -> None:
    for emitter, ref in EMITTER_REFERENCE.items():
        assert power_factor(emitter, ref.flow, ref.return_, ref.room) == pytest.approx(1.0)
        assert power_factor(emitter, ref.flow, None, ref.room) == pytest.approx(1.0, rel=0.02)


def test_factor_follows_en442_exponent() -> None:
    low = power_factor(EmitterType.RADIATOR, 45.0, 40.0, 20.0)
    excess = mean_excess(45.0, 40.0, 20.0) / EMITTER_REFERENCE[EmitterType.RADIATOR].excess
    assert low == pytest.approx(excess**1.3)
    assert power_factor(EmitterType.RADIATOR, 45.0, 40.0, 20.0, exponent=1.0) == pytest.approx(
        excess
    )


def test_factor_is_zero_when_water_is_not_warmer_than_the_room() -> None:
    assert power_factor(EmitterType.UNDERFLOOR, 19.0, None, 21.0) == 0.0
    assert power_factor(EmitterType.RADIATOR, 20.0, 20.0, 21.0) == 0.0


@pytest.mark.parametrize(
    ("zone", "expected"),
    [
        (ZoneState("z", valve_open=0.5), True),
        (ZoneState("z", valve_open=0.0, calling=True), False),  # the opening decides
        (ZoneState("z", on_percent=0.3), True),
        (ZoneState("z", calling=True), True),
        (ZoneState("z", calling=False), False),
        (ZoneState("z"), None),
    ],
)
def test_is_heating(zone: ZoneState, expected: bool | None) -> None:
    assert is_heating(zone) is expected


ZONE = Zone("z", "c", EmitterType.RADIATOR, reference_output_w=1000.0)
HEATING = ZoneState("z", temperature=20.0, valve_open=0.8)
IDLE = ZoneState("z", temperature=20.0, valve_open=0.0)


def test_update_computes_while_heating() -> None:
    result = update_factor(None, ZONE, HEATING, Supply(75.0), 65.0, now=10.0)
    assert result.status is FactorStatus.COMPUTED
    assert result.value == pytest.approx(1.0)
    assert result.output_w == pytest.approx(1000.0)
    assert result.at == 10.0


def test_update_holds_the_last_value_when_not_heating() -> None:
    computed = update_factor(None, ZONE, HEATING, Supply(55.0), 45.0, now=10.0)
    held = update_factor(computed, ZONE, IDLE, Supply(None, SupplyReason.FLOW_STALE), None, 99.0)
    assert held == FactorResult(computed.value, FactorStatus.HELD, None, 10.0, computed.output_w)


def test_update_without_previous_value_when_not_heating() -> None:
    result = update_factor(None, ZONE, IDLE, Supply(55.0), None, now=1.0)
    assert result == FactorResult(None, FactorStatus.UNAVAILABLE, FactorReason.NOT_HEATING_YET)


@pytest.mark.parametrize(
    ("zone", "supply", "reason"),
    [
        (HEATING, Supply(None, SupplyReason.FLOW_STALE), FactorReason.FLOW_STALE),
        (HEATING, Supply(None, SupplyReason.FLOW_UNKNOWN), FactorReason.FLOW_UNKNOWN),
        (
            HEATING,
            Supply(None, SupplyReason.CIRCUIT_NOT_MEASURED),
            FactorReason.CIRCUIT_NOT_MEASURED,
        ),
        (ZoneState("z", valve_open=0.8), Supply(55.0), FactorReason.ROOM_UNKNOWN),
        (ZoneState("z", temperature=20.0), Supply(55.0), FactorReason.ZONE_UNKNOWN),
    ],
)
def test_update_unavailable_with_a_reason(
    zone: ZoneState, supply: Supply, reason: FactorReason
) -> None:
    previous = FactorResult(0.5, FactorStatus.COMPUTED, at=1.0)
    result = update_factor(previous, ZONE, zone, supply, None, now=2.0)
    assert result.status is FactorStatus.UNAVAILABLE
    assert result.reason is reason
    assert result.value is None


def test_zone_exponent_override_and_unknown_size() -> None:
    zone = Zone("z", "c", EmitterType.RADIATOR, exponent=1.0)
    result = update_factor(None, zone, HEATING, Supply(45.0), 40.0, now=1.0)
    expected = mean_excess(45.0, 40.0, 20.0) / EMITTER_REFERENCE[EmitterType.RADIATOR].excess
    assert result.value == pytest.approx(expected)
    assert result.output_w is None
