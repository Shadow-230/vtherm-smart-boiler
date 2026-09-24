"""Unit conversion and state parsing shared by the integration and the importer."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.units import (
    parse_binary,
    parse_number,
    power_to_kw,
    pressure_to_bar,
    signal_value,
    temperature_to_celsius,
)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(20.0, "°C", 20.0), (68.0, "°F", 20.0), (293.15, "K", 20.0), (20.0, None, 20.0)],
)
def test_temperature(value: float, unit: str | None, expected: float) -> None:
    assert temperature_to_celsius(value, unit) == pytest.approx(expected)


def test_unknown_units_give_none() -> None:
    assert temperature_to_celsius(20.0, "furlong") is None
    assert pressure_to_bar(1.0, "atm-ish") is None
    assert power_to_kw(1.0, "hp") is None


def test_pressure_and_power() -> None:
    assert pressure_to_bar(150.0, "kPa") == pytest.approx(1.5)
    assert pressure_to_bar(21.75, "psi") == pytest.approx(1.4996, rel=1e-3)
    assert pressure_to_bar(1.5, None) == 1.5
    assert power_to_kw(1500.0, "W") == pytest.approx(1.5)
    assert power_to_kw(1500.0, None) == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("state", "expected"),
    [("21.5", 21.5), (3, 3.0), ("unavailable", None), ("nan", None), ("inf", None), (True, None)],
)
def test_parse_number(state: object, expected: float | None) -> None:
    assert parse_number(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [("on", True), ("off", False), (True, True), ("unknown", None), (1, None)],
)
def test_parse_binary(state: object, expected: bool | None) -> None:
    assert parse_binary(state) is expected


@pytest.mark.parametrize(
    ("signal", "state", "unit", "expected"),
    [
        (Signal.FLAME, "on", None, True),
        (Signal.FLOW, "113.0", "°F", pytest.approx(45.0)),
        (Signal.FLOW, "45", "furlong", None),
        (Signal.FLOW, "150", "°C", None),  # implausible
        (Signal.PRESSURE, "150", "kPa", pytest.approx(1.5)),
        (Signal.MODULATION, "37", "%", 37.0),
        (Signal.GAS_METER, "1234.5", "m³", 1234.5),
        (Signal.RETURN, "unavailable", "°C", None),
    ],
)
def test_signal_value(signal: Signal, state: str, unit: str | None, expected: object) -> None:
    assert signal_value(signal, state, unit) == expected
