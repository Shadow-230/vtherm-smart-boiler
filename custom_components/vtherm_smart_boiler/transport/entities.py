"""Boiler signals from the entities the user mapped. Read-only: nothing here writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..core.foreign_heat import SourceKind
from ..core.readings import BoilerSnapshot, Reading
from ..core.signals import Signal
from ..units import (
    parse_binary,
    parse_number,
    power_to_kw,
    signal_value,
    temperature_to_celsius,
    temperature_unit_known,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State


def reported_at(state: State) -> float:
    """When the source last reported, changed or not (``last_reported`` since HA 2024.3)."""
    moment = getattr(state, "last_reported", None) or state.last_updated
    return moment.timestamp()


def reading_from_state(signal: Signal, state: State | None) -> Reading:
    """A signal's reading from its entity's state; a missing entity is unknown."""
    if state is None:
        return Reading(None, None)
    unit = state.attributes.get("unit_of_measurement")
    return Reading(signal_value(signal, state.state, unit), reported_at(state))


class EntityTransport:
    """Reads the mapped boiler entities from Home Assistant's state machine."""

    def __init__(self, hass: HomeAssistant, mapping: Mapping[Signal, str]) -> None:
        self._hass = hass
        self._mapping = dict(mapping)
        self._by_entity = {entity: signal for signal, entity in self._mapping.items()}

    @property
    def mapping(self) -> dict[Signal, str]:
        return dict(self._mapping)

    @property
    def entity_ids(self) -> tuple[str, ...]:
        return tuple(self._mapping.values())

    def signal_of(self, entity_id: str) -> Signal | None:
        return self._by_entity.get(entity_id)

    def reading(self, signal: Signal) -> Reading:
        return reading_from_state(signal, self._hass.states.get(self._mapping[signal]))

    def snapshot(self, now: float) -> BoilerSnapshot:
        """Every mapped signal at ``now``; an unmapped signal is absent."""
        return BoilerSnapshot(now, {signal: self.reading(signal) for signal in self._mapping})


FLOW_LOW, FLOW_HIGH = -20.0, 110.0


def read_temperature(hass: HomeAssistant, entity_id: str) -> Reading:
    """A water temperature entity (e.g. a mixed circuit's flow) in °C, plausibility-checked."""
    return temperature_from_state(hass.states.get(entity_id))


def temperature_from_state(state: State | None) -> Reading:
    if state is None:
        return Reading(None, None)
    number = parse_number(state.state)
    value = (
        None
        if number is None
        else temperature_to_celsius(number, state.attributes.get("unit_of_measurement"))
    )
    if value is not None and not FLOW_LOW <= value <= FLOW_HIGH:
        value = None
    return Reading(value, reported_at(state))


def read_on_off(hass: HomeAssistant, entity_id: str) -> bool | None:
    """An on/off entity (e.g. an echo of heating on/off); anything else is unknown."""
    state = hass.states.get(entity_id)
    return None if state is None else parse_binary(state.state)


def read_source(hass: HomeAssistant, entity_id: str, kind: SourceKind) -> bool | float | None:
    """A foreign-heat source: on/off for switches and binary sensors, W or °C for sensors."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    if kind in (SourceKind.SWITCH, SourceKind.BINARY):
        return parse_binary(state.state)
    number = parse_number(state.state)
    if number is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if kind is SourceKind.POWER:
        kw = power_to_kw(number, unit)
        return None if kw is None else kw * 1000.0
    return temperature_to_celsius(number, unit)


def read_weather_temperature(hass: HomeAssistant, entity_id: str) -> Reading:
    """The current temperature of a weather entity, in °C."""
    return weather_from_state(hass.states.get(entity_id))


def weather_from_state(state: State | None) -> Reading:
    if state is None:
        return Reading(None, None)
    number = parse_number(state.attributes.get("temperature"))
    value = (
        None
        if number is None
        else temperature_to_celsius(number, state.attributes.get("temperature_unit"))
    )
    if value is not None and not -60.0 <= value <= 60.0:
        value = None
    return Reading(value, reported_at(state))


def read_bounds(hass: HomeAssistant, entity_id: str) -> tuple[float | None, float | None]:
    """The ``min`` and ``max`` a number or input_number entity accepts, in °C; ``None`` where
    unknown — also in a unit that is not a temperature."""
    return bounds_from_state(hass.states.get(entity_id))


def bounds_from_state(state: State | None) -> tuple[float | None, float | None]:
    if state is None:
        return None, None
    unit = state.attributes.get("unit_of_measurement")
    unit = unit if isinstance(unit, str) else None

    def celsius(key: str) -> float | None:
        number = parse_number(state.attributes.get(key))
        return None if number is None else temperature_to_celsius(number, unit)

    return celsius("min"), celsius("max")


def temperature_unit_of(hass: HomeAssistant, entity_id: str) -> bool | None:
    """Whether an entity's unit is a temperature unit (none counts as °C); ``None`` when the
    entity is missing."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    return temperature_unit_known(unit if isinstance(unit, str) else None)
