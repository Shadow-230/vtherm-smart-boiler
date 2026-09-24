"""Boiler signals from the entities the user mapped. Read-only: nothing here writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..core.readings import BoilerSnapshot, Reading
from ..core.signals import Signal
from ..units import signal_value

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
