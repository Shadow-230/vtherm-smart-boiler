"""Unit conversion to the units the core uses: °C, bar, kW — a boiler's electric power in W. No
Home Assistant imports, so the history importer can use it too."""

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
_FROM_CELSIUS: dict[str, Callable[[float], float]] = {
    "°C": lambda v: v,
    "C": lambda v: v,
    "°F": lambda v: v * 9.0 / 5.0 + 32.0,
    "F": lambda v: v * 9.0 / 5.0 + 32.0,
    "K": lambda v: v + 273.15,
}
# Every pressure unit Home Assistant knows (2026.9), in bar.
_PRESSURE: dict[str, float] = {
    "bar": 1.0,
    "cbar": 0.01,
    "mbar": 0.001,
    "hPa": 0.001,
    "kPa": 0.01,
    "Pa": 0.00001,
    "mPa": 0.00000001,
    "mmHg": 0.00133322387415,
    "inHg": 0.0338638866667,
    "inH₂O": 0.00249088908333,
    "psi": 0.0689475729317,
}
# Every power unit Home Assistant knows (2026.9), in kW.
_POWER: dict[str, float] = {
    "mW": 0.000001,
    "W": 0.001,
    "kW": 1.0,
    "MW": 1000.0,
    "GW": 1_000_000.0,
    "TW": 1_000_000_000.0,
    "BTU/h": 0.000293071070172,
}


def temperature_to_celsius(value: float, unit: str | None) -> float | None:
    """``None`` for an unknown unit; no unit is taken as °C."""
    convert = _TEMPERATURE.get(unit or "°C")
    return None if convert is None else convert(value)


def celsius_to(value: float, unit: str | None) -> float | None:
    """A °C value in an entity's unit, for writing; ``None`` for an unknown unit; no unit is
    taken as °C, as on reading."""
    convert = _FROM_CELSIUS.get(unit or "°C")
    return None if convert is None else convert(value)


def temperature_unit_known(unit: str | None) -> bool:
    return (unit or "°C") in _FROM_CELSIUS


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


def signal_value(
    signal: Signal, state: object, unit: str | None, *, zero_is_unknown: bool = False
) -> float | bool | None:
    """A boiler signal's value from an entity state, in core units and within the plausible
    range; ``None`` when unknown, unavailable, in an unknown unit or implausible.
    ``zero_is_unknown``: the entity is the OpenTherm Gateway's, whose pressure reads 0 after a
    reset until a real reading (P-17) — decided from the registries at setup; from any other
    source 0 bar is a reading."""
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
    elif spec.kind is SignalKind.POWER:
        kw = power_to_kw(number, unit)
        converted = None if kw is None else kw * 1000.0
    else:
        converted = number
    if converted is None or not spec.plausible(converted):
        return None
    if signal is Signal.PRESSURE and converted == 0.0 and zero_is_unknown:
        # An OpenTherm Gateway reports 0 until a real reading after each reset (L3).
        return None
    if signal is Signal.GAS_METER and converted == 0.0:
        # A cumulative meter at 0 for a moment (its value not known yet after a restart) would
        # count its whole reading again when it comes back.
        return None
    return converted
