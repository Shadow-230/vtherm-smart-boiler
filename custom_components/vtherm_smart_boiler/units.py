"""Unit conversion to the units the core uses: °C, bar, kW. No Home Assistant imports, so the
history importer can use it too."""

from __future__ import annotations

from collections.abc import Callable

from .core.signals import SIGNAL_SPECS, Signal, SignalKind

_TEMPERATURE: dict[str, Callable[[float], float]] = {
    "°C": lambda v: v,
    "C": lambda v: v,
    "°F": lambda v: (v - 32.0) * 5.0 / 9.0,
    "F": lambda v: (v - 32.0) * 5.0 / 9.0,
    "K": lambda v: v - 273.15,
}
_PRESSURE: dict[str, float] = {
    "bar": 1.0,
    "mbar": 0.001,
    "hPa": 0.001,
    "kPa": 0.01,
    "Pa": 0.00001,
    "psi": 0.0689476,
}
_POWER: dict[str, float] = {"W": 0.001, "kW": 1.0, "MW": 1000.0}


def temperature_to_celsius(value: float, unit: str | None) -> float | None:
    """``None`` for an unknown unit; no unit is taken as °C."""
    convert = _TEMPERATURE.get(unit or "°C")
    return None if convert is None else convert(value)


def pressure_to_bar(value: float, unit: str | None) -> float | None:
    factor = _PRESSURE.get(unit or "bar")
    return None if factor is None else value * factor


def power_to_kw(value: float, unit: str | None) -> float | None:
    factor = _POWER.get(unit or "W")
    return None if factor is None else value * factor


def parse_number(state: object) -> float | None:
    """A finite number from a state or attribute; ``None`` for 'unavailable', text or NaN."""
    if isinstance(state, bool):
        return None
    if isinstance(state, int | float):
        number = float(state)
    elif isinstance(state, str):
        try:
            number = float(state)
        except ValueError:
            return None
    else:
        return None
    return number if number == number and abs(number) != float("inf") else None


def parse_binary(state: object) -> bool | None:
    """'on' / 'off' (or a bool) to a bool; anything else is unknown."""
    if isinstance(state, bool):
        return state
    if state == "on":
        return True
    if state == "off":
        return False
    return None


def signal_value(signal: Signal, state: object, unit: str | None) -> float | bool | None:
    """A boiler signal's value from an entity state, in core units and within the plausible
    range; ``None`` when unknown, unavailable, in an unknown unit or implausible."""
    spec = SIGNAL_SPECS[signal]
    if spec.kind is SignalKind.BINARY:
        return parse_binary(state)
    number = parse_number(state)
    if number is None:
        return None
    if spec.kind is SignalKind.TEMPERATURE:
        converted = temperature_to_celsius(number, unit)
    elif spec.kind is SignalKind.PRESSURE:
        converted = pressure_to_bar(number, unit)
    else:
        converted = number
    if converted is None or not spec.plausible(converted):
        return None
    return converted
