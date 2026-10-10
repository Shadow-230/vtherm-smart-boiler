"""Foreign heat per zone."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.foreign_heat import (
    DEFAULT_HOLD_S,
    ForeignHeatSource,
    ForeignHeatState,
    SourceKind,
    update_foreign_heat,
)

FIREPLACE = ForeignHeatSource("switch.fireplace", SourceKind.SWITCH)
HEATER = ForeignHeatSource("sensor.heater_power", SourceKind.POWER)
STOVE = ForeignHeatSource("sensor.stove_pipe", SourceKind.TEMPERATURE, threshold=50.0)


@pytest.mark.parametrize(
    ("source", "value", "expected"),
    [
        (FIREPLACE, True, True),
        (FIREPLACE, False, False),
        (FIREPLACE, 1.0, None),
        (HEATER, 1500.0, True),
        (HEATER, 20.0, False),  # standby below the default 100 W
        (HEATER, True, None),
        (STOVE, 80.0, True),
        (STOVE, 30.0, False),
        (ForeignHeatSource("t", SourceKind.TEMPERATURE), 80.0, None),  # no threshold given
        (FIREPLACE, None, None),
    ],
)
def test_source_state(source: ForeignHeatSource, value: object, expected: bool | None) -> None:
    assert source.is_active(value) is expected  # type: ignore[arg-type]


def test_active_while_a_source_heats() -> None:
    state = update_foreign_heat(None, [(FIREPLACE, True), (HEATER, 10.0)], now=100.0)
    assert state == ForeignHeatState(True, ("switch.fireplace",), (), 100.0)


def test_hold_after_the_source_stops_then_clear() -> None:
    on = update_foreign_heat(None, [(FIREPLACE, True)], now=0.0)
    holding = update_foreign_heat(on, [(FIREPLACE, False)], now=DEFAULT_HOLD_S - 1)
    assert holding.active
    assert holding.holding
    assert holding.last_active_at == 0.0
    cleared = update_foreign_heat(holding, [(FIREPLACE, False)], now=DEFAULT_HOLD_S)
    assert not cleared.active
    assert not cleared.holding


def test_a_clock_set_back_holds_foreign_heat_its_own_time_only() -> None:
    """PB-28: the wall clock set back a day — the source's last heat counts from now, so the
    hold lasts its own time, not a day more."""
    on = update_foreign_heat(None, [(FIREPLACE, True)], now=86_400.0)
    holding = update_foreign_heat(on, [(FIREPLACE, False)], now=0.0)
    assert holding.holding
    assert holding.last_active_at == 0.0
    still = update_foreign_heat(holding, [(FIREPLACE, False)], now=DEFAULT_HOLD_S - 1)
    assert still.holding
    cleared = update_foreign_heat(still, [(FIREPLACE, False)], now=DEFAULT_HOLD_S)
    assert not cleared.active


def test_unknown_sources_are_listed_but_do_not_activate() -> None:
    state = update_foreign_heat(None, [(FIREPLACE, None), (STOVE, 20.0)], now=5.0)
    assert state == ForeignHeatState(False, (), ("switch.fireplace",), None)


def test_no_sources() -> None:
    assert update_foreign_heat(None, [], now=5.0) == ForeignHeatState(False)
