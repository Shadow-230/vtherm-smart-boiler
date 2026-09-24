"""Hot water available per zone."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.hot_water import (
    HotWater,
    HotWaterReason,
    hot_water_available,
)
from custom_components.vtherm_smart_boiler.core.supply import Supply, SupplyReason


def test_available_when_supply_well_above_room() -> None:
    assert hot_water_available(Supply(45.0), 20.0, False) == HotWater(True, None, 25.0)


def test_dhw_run_blocks() -> None:
    result = hot_water_available(Supply(70.0), 20.0, True)
    assert result == HotWater(False, HotWaterReason.DHW_ACTIVE)


def test_unknown_dhw_state_does_not_block() -> None:
    assert hot_water_available(Supply(45.0), 20.0, None).available is True


@pytest.mark.parametrize(
    ("supply", "expected"),
    [
        (Supply(None, SupplyReason.FLOW_STALE), HotWater(False, HotWaterReason.FLOW_STALE)),
        (Supply(None, SupplyReason.FLOW_UNKNOWN), HotWater(False, HotWaterReason.FLOW_UNKNOWN)),
        (Supply(None), HotWater(False, HotWaterReason.FLOW_UNKNOWN)),
        (
            Supply(None, SupplyReason.CIRCUIT_NOT_MEASURED),
            HotWater(None, HotWaterReason.CIRCUIT_NOT_MEASURED),
        ),
    ],
)
def test_supply_problems(supply: Supply, expected: HotWater) -> None:
    assert hot_water_available(supply, 20.0, False) == expected


def test_unknown_room() -> None:
    result = hot_water_available(Supply(45.0), None, False)
    assert result == HotWater(None, HotWaterReason.ROOM_UNKNOWN)


def test_flow_near_room_with_hysteresis() -> None:
    assert hot_water_available(Supply(22.5), 20.0, False).available is False
    assert hot_water_available(Supply(23.5), 20.0, False).available is True
    # Once available it stays so until the excess falls below margin minus hysteresis.
    assert hot_water_available(Supply(22.5), 20.0, False, previous=True).available is True
    near = hot_water_available(Supply(21.5), 20.0, False, previous=True)
    assert near == HotWater(False, HotWaterReason.FLOW_NEAR_ROOM, 1.5)
