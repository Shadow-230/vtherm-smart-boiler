"""Boiler signals from the entities the user mapped. Read-only: nothing here writes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..const import MQTT_DOMAIN, OPENTHERM_GW_DOMAIN
from ..core.foreign_heat import SourceKind
from ..core.hand_back import RestartKind
from ..core.limits import Grid
from ..core.readings import BoilerSnapshot, Reading
from ..core.signals import GatewayOutdoor, Signal
from ..units import (
    celsius_to,
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


def reading_from_state(
    signal: Signal, state: State | None, *, from_gateway: bool = False
) -> Reading:
    """A signal's reading from its entity's state; a missing entity is unknown.
    ``from_gateway``: the entity is the OpenTherm Gateway's — its 0 is unknown for pressure and
    measured temperatures (P-17, PB-21)."""
    if state is None:
        return Reading(None, None)
    unit = state.attributes.get("unit_of_measurement")
    value = signal_value(signal, state.state, unit, zero_is_unknown=from_gateway)
    return Reading(value, reported_at(state))


def gateway_signals(
    hass: HomeAssistant,
    mapping: Mapping[Signal, str],
    write_path: str | None = None,
    read_back: str | None = None,
) -> frozenset[Signal]:
    """The mapped signals whose entity the OpenTherm Gateway reports (P-17, Q3.9): registered by
    ``opentherm_gw``, or by ``mqtt`` on the Home Assistant device of the OTGW firmware's setpoint
    read-back where the write path is ``otgw_mqtt`` — the firmware's discovery puts a gateway's
    entities on one device (assumed, supported by its source:
    ``research/2026-09-28-y1-otgw-discovery-device.md``; provisional, K4). An entity not in the
    registry counts as none, and so does every MQTT entity on another path: its 0 bar is a
    reading. Their fault flags count only with the boiler's fault indication on — except
    ``opentherm_gw``'s boiler "Fault indication" itself (OpenTherm ID 0, in every status
    report), which is that indication and needs no gate. Read at setup, in the event loop."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    device: str | None = None
    if write_path == "otgw_mqtt" and read_back:
        found = registry.async_get(read_back)
        if found is not None and found.platform == MQTT_DOMAIN:
            device = found.device_id
    result: set[Signal] = set()
    for signal, entity_id in mapping.items():
        entry = registry.async_get(entity_id)
        if entry is None:
            continue
        if entry.platform == OPENTHERM_GW_DOMAIN:
            if not entry.unique_id.endswith(OTGW_FAULT_INDICATION):
                result.add(signal)
        elif device is not None and entry.platform == MQTT_DOMAIN and entry.device_id == device:
            result.add(signal)
    return frozenset(result)


# ``opentherm_gw``'s boiler "Fault indication": its unique ID ends so — the boiler device
# (``OpenThermDeviceIdentifier.BOILER``) and pyotgw's ``DATA_SLAVE_FAULT_IND`` (pyotgw 2.2.3,
# Home Assistant 2026.9.3).
OTGW_FAULT_INDICATION = "-boiler-slave_fault_indication"


class EntityTransport:
    """Reads the mapped boiler entities from Home Assistant's state machine. ``gateway``: the
    signals the OpenTherm Gateway reports (``gateway_signals``, read at setup): their 0 bar is
    unknown, and their fault flags count only with the boiler's fault indication on."""

    def __init__(
        self,
        hass: HomeAssistant,
        mapping: Mapping[Signal, str],
        gateway: frozenset[Signal] = frozenset(),
    ) -> None:
        self._hass = hass
        self._mapping = dict(mapping)
        self._by_entity = {entity: signal for signal, entity in self._mapping.items()}
        self.gateway = frozenset(gateway)
        # The live outdoor readings' memory for the gateway's zero rule (PB-21, M1).
        self.outdoor = GatewayOutdoor()

    def signal_of(self, entity_id: str) -> Signal | None:
        return self._by_entity.get(entity_id)

    def reading(self, signal: Signal) -> Reading:
        return self.reading_of(signal, self._hass.states.get(self._mapping[signal]))

    def reading_of(
        self, signal: Signal, state: State | None, outdoor: GatewayOutdoor | None = None
    ) -> Reading:
        """A state of the signal's entity as a reading — the live one, or a recorded one. The
        gateway's outdoor temperature goes through its zero rule (PB-21, M1), with ``outdoor``
        as the memory — recorded states in time order bring their own; the live one by
        default."""
        if signal is Signal.OUTDOOR and signal in self.gateway:
            memory = self.outdoor if outdoor is None else outdoor
            reading = reading_from_state(signal, state)
            return Reading(memory.read(reading.value), reading.reported_at)
        return reading_from_state(signal, state, from_gateway=signal in self.gateway)

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


def relay_hvac_modes(state: State | None) -> set[str] | None:
    """The modes a boiler thermostat entity offers (``hvac_modes``); ``None`` where not known —
    the entity not there, or not reporting them."""
    if state is None:
        return None
    modes = state.attributes.get("hvac_modes")
    if not isinstance(modes, list | tuple) or not modes:
        return None
    return {str(mode) for mode in modes}


def read_on_off(hass: HomeAssistant, entity_id: str) -> bool | None:
    """An on/off entity (e.g. an echo of heating on/off); anything else is unknown."""
    state = hass.states.get(entity_id)
    return None if state is None else parse_binary(state.state)


# A foreign-heat source's plausible readings (PB-43): outside them a probe's fault value or a
# meter's spike is unknown rather than an hour of foreign heat.
SOURCE_LOW, SOURCE_HIGH = -30.0, 110.0  # °C
SOURCE_KW_LOW, SOURCE_KW_HIGH = 0.0, 100.0  # kW


def read_source(hass: HomeAssistant, entity_id: str, kind: SourceKind) -> bool | float | None:
    """A foreign-heat source: on/off for switches and binary sensors, W or °C for sensors;
    unknown outside the plausible range (PB-43)."""
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
        if kw is None or not SOURCE_KW_LOW <= kw <= SOURCE_KW_HIGH:
            return None
        return kw * 1000.0
    celsius = temperature_to_celsius(number, unit)
    if celsius is None or not SOURCE_LOW <= celsius <= SOURCE_HIGH:
        return None
    return celsius


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


def read_grid(hass: HomeAssistant, entity_id: str) -> Grid | None:
    """A setpoint entity's grid in its own unit (P-15)."""
    state = hass.states.get(entity_id)
    return grid_from_state(state, step_scale(hass, state))


def step_scale(hass: HomeAssistant, state: State | None) -> float:
    """PB-42: Home Assistant shows a temperature ``number`` in the system's unit (or one the
    user picked) but keeps its ``step`` in the device's own unit (HA 2026.9.3,
    ``number/__init__.py``, ``_calculate_step``): the factor that turns that step into the
    shown unit — 1.8 for a °C device shown in °F. 1 where the units match, for any other
    domain, or where the device's unit is not known (the entity object not found: assumed
    the shown unit, as before)."""
    if state is None or state.domain != "number":
        return 1.0
    component = hass.data.get("number")
    get_entity = getattr(component, "get_entity", None)
    entity = get_entity(state.entity_id) if callable(get_entity) else None
    native = getattr(entity, "native_unit_of_measurement", None)
    shown = state.attributes.get("unit_of_measurement")
    native_k, shown_k = _kelvin_size(native), _kelvin_size(shown)
    if native is None or native_k is None or shown_k is None:
        return 1.0
    return shown_k / native_k


def _kelvin_size(unit: object) -> float | None:
    """How many of a temperature unit make one kelvin; ``None`` for a unit that is not one."""
    zero, one = celsius_to(0.0, unit), celsius_to(1.0, unit)
    return None if zero is None or one is None else one - zero


def grid_from_state(state: State | None, step_scale: float = 1.0) -> Grid | None:
    """A number or input_number entity's grid: its ``step``, counted from its ``min`` (else 0),
    within its ``min`` and ``max``, in its own unit, with that unit's conversion from °C.
    ``step_scale`` turns the ``step`` into the shown unit (PB-42, ``step_scale()``).
    ``None`` without a step above 0, or in a unit that is not a temperature."""
    if state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    zero, one = celsius_to(0.0, unit), celsius_to(1.0, unit)
    step = shown_step(state, step_scale)
    if zero is None or one is None or step is None:
        return None
    return Grid(
        step,
        parse_number(state.attributes.get("min")),
        parse_number(state.attributes.get("max")),
        scale=one - zero,
        offset=zero,
    )


def shown_step(state: State, step_scale: float = 1.0) -> float | None:
    """A number entity's ``step`` in its shown unit (PB-42); ``None`` without a step above 0."""
    step = parse_number(state.attributes.get("step"))
    return None if step is None or step <= 0 else step * step_scale


_DURATION_UNITS = frozenset({"ms", "s", "min", "h", "d", "w"})


def restart_reading(state: State | None) -> tuple[float | None, RestartKind]:
    """A restart indicator's value and what kind it is: a timestamp sensor is a boot time; a
    duration is an uptime; any other number a restart counter. ``None``: not known."""
    if state is None:
        return None, RestartKind.COUNTER
    attributes = state.attributes
    if attributes.get("device_class") == "timestamp":
        from homeassistant.util import dt as dt_util

        try:
            moment = dt_util.parse_datetime(state.state)
            boot = None if moment is None else moment.timestamp()
        except ValueError, OverflowError:
            boot = None  # a date that does not exist, or beyond the clock's range (PB-41)
        return boot, RestartKind.BOOT_TIME
    unit = attributes.get("unit_of_measurement")
    duration = attributes.get("device_class") == "duration" or (
        isinstance(unit, str) and unit in _DURATION_UNITS
    )
    kind = RestartKind.UPTIME if duration else RestartKind.COUNTER
    return parse_number(state.state), kind
