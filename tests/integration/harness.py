"""Integration-test harness: fake boiler entities, fake VT zones, canned forecasts, replay.

Everything runs inside the test's Home Assistant; nothing connects anywhere.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import entity_registry as er

from custom_components.vtherm_smart_boiler.core.history import History
from custom_components.vtherm_smart_boiler.core.signals import SIGNAL_SPECS, Signal, SignalKind

VT_PLATFORM = "versatile_thermostat"

BOILER_ENTITIES: dict[Signal, str] = {
    Signal.FLAME: "binary_sensor.fake_boiler_flame",
    Signal.FLOW: "sensor.fake_boiler_flow",
    Signal.RETURN: "sensor.fake_boiler_return",
    Signal.MODULATION: "sensor.fake_boiler_modulation",
    Signal.CH_SETPOINT: "sensor.fake_boiler_ch_setpoint",
    Signal.DHW_ACTIVE: "binary_sensor.fake_boiler_dhw",
    Signal.PRESSURE: "sensor.fake_boiler_pressure",
    Signal.FLUE_GAS: "sensor.fake_boiler_flue_gas",
    Signal.OUTDOOR: "sensor.fake_boiler_outdoor",
    Signal.ROOM_SETPOINT: "sensor.fake_thermostat_setpoint",
    Signal.ROOM_TEMPERATURE: "sensor.fake_thermostat_temperature",
    Signal.CH_ACTIVE: "binary_sensor.fake_boiler_ch",
    Signal.PUMP_RUNNING: "binary_sensor.fake_boiler_pump",
    Signal.GAS_METER: "sensor.fake_gas_meter",
}
WEATHER_ENTITY = "weather.fake_home"

_UNITS: dict[SignalKind, dict[str, str]] = {
    SignalKind.TEMPERATURE: {"unit_of_measurement": "°C", "device_class": "temperature"},
    SignalKind.PERCENT: {"unit_of_measurement": "%"},
    SignalKind.PRESSURE: {"unit_of_measurement": "bar", "device_class": "pressure"},
    SignalKind.COUNTER: {
        "unit_of_measurement": "m³",
        "device_class": "gas",
        "state_class": "total_increasing",
    },
    SignalKind.BINARY: {},
}


def state_text(signal: Signal, value: float | bool | None) -> str:
    if value is None:
        return "unavailable"
    if SIGNAL_SPECS[signal].kind is SignalKind.BINARY:
        return "on" if value else "off"
    return str(value)


class FakeBoiler:
    """Boiler signals as plain Home Assistant states with realistic units."""

    def __init__(self, hass: HomeAssistant, signals: Iterable[Signal] = tuple(BOILER_ENTITIES)):
        self.hass = hass
        self.signals = tuple(signals)

    def entity(self, signal: Signal) -> str:
        return BOILER_ENTITIES[signal]

    def set(self, signal: Signal, value: float | bool | None) -> None:
        attributes = dict(_UNITS[SIGNAL_SPECS[signal].kind])
        self.hass.states.async_set(self.entity(signal), state_text(signal, value), attributes)

    def set_many(self, values: dict[Signal, float | bool | None]) -> None:
        for signal, value in values.items():
            self.set(signal, value)

    def mapping(self) -> dict[str, str]:
        """Signal → entity, as the config flow stores it."""
        return {signal.value: self.entity(signal) for signal in self.signals}


@dataclass
class FakeZones:
    """VT climate entities: a state plus VT's top-level attributes, registered as VT's."""

    hass: HomeAssistant
    entities: dict[str, str] = field(default_factory=dict)

    def add(self, zone_id: str, **attributes: Any) -> str:
        registry = er.async_get(self.hass)
        entry = registry.async_get_or_create(
            "climate", VT_PLATFORM, f"fake_{zone_id}", suggested_object_id=f"fake_{zone_id}"
        )
        self.entities[zone_id] = entry.entity_id
        self.set(zone_id, **attributes)
        return entry.entity_id

    def set(self, zone_id: str, state: str = "heat", **attributes: Any) -> None:
        values = {
            "current_temperature": 20.0,
            "temperature": 21.0,
            "hvac_action": "idle",
            "on_percent": 0.0,
            "power_percent": 0,
        } | attributes
        self.hass.states.async_set(self.entities[zone_id], state, values)


def canned_forecast(kind: str, start: datetime, count: int, temperature: float) -> list[dict]:
    step = 3600 if kind == "hourly" else 86400
    return [
        {
            "datetime": datetime.fromtimestamp(start.timestamp() + i * step, UTC).isoformat(),
            "temperature": temperature,
            "templow": temperature - 5 if kind == "daily" else None,
            "cloud_coverage": 50,
            "wind_speed": 3.0,
            "condition": "cloudy",
        }
        for i in range(count)
    ]


@dataclass
class FakeForecasts:
    """``weather.get_forecasts`` answering with canned forecasts and recording every call."""

    hass: HomeAssistant
    temperature: float = 5.0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def register(self) -> None:
        self.hass.states.async_set(
            WEATHER_ENTITY, "cloudy", {"temperature": self.temperature, "temperature_unit": "°C"}
        )

        async def handle(call: ServiceCall) -> ServiceResponse:
            self.calls.append(dict(call.data))
            kind = call.data["type"]
            now = datetime.now(UTC)
            entities = call.data.get("entity_id") or [WEATHER_ENTITY]
            if isinstance(entities, str):
                entities = [entities]
            return {
                entity: {
                    "forecast": canned_forecast(
                        kind, now, 48 if kind == "hourly" else 7, self.temperature
                    )
                }
                for entity in entities
            }

        self.hass.services.async_register(
            "weather", "get_forecasts", handle, supports_response=SupportsResponse.ONLY
        )


def replay_events(history: History, zones: FakeZones | None = None):
    """Every change in a history as ``(t, apply)`` in time order, for replay with a frozen
    clock: each ``apply(boiler)`` sets the states of that instant."""
    events: dict[float, list] = {}
    for signal, series in history.signals.items():
        for sample in series:
            events.setdefault(sample.t, []).append(("boiler", signal, sample.value))
    if zones is not None:
        for zone_id, zone in history.zones.items():
            times = {s.t for series in zone.series() for s in series}
            for t in times:
                events.setdefault(t, []).append(("zone", zone_id, zone.state_at(t)))
    return sorted(events.items())


def apply_event(boiler: FakeBoiler, zones: FakeZones | None, changes: list) -> None:
    for kind, key, value in changes:
        if kind == "boiler":
            if key in boiler.signals:
                boiler.set(key, value)
        elif zones is not None and key in zones.entities:
            state = value
            attributes: dict[str, Any] = {
                "current_temperature": state.temperature,
                "temperature": state.target,
                "hvac_action": "heating" if state.calling else "idle",
            }
            if state.valve_open is not None:
                attributes["valve_open_percent"] = round(state.valve_open * 100)
                attributes["on_percent"] = state.valve_open
            zones.set(key, "heat" if state.heating_enabled else "off", **attributes)
