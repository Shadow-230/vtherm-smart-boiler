"""Integration-test harness: fake boiler entities, fake VT zones and VT's central boiler, canned
forecasts, replay.

Everything runs inside the test's Home Assistant; nothing connects anywhere.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.core import (
    Context,
    HomeAssistant,
    ServiceCall,
    ServiceRegistry,
    ServiceResponse,
    SupportsResponse,
)
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
# I12: the helper VT's central boiler switches, as the user creates it and picks it in the plugin.
VT_HELPER = "input_boolean.fake_vt_central_boiler"


def vt_central_settings(helper: str = VT_HELPER, **changes: Any) -> dict[str, Any]:
    """VT's central boiler settings as a thermostat's ``entry_infos`` carries them (VT 10.6.5):
    ticked, its commands turning ``helper`` on and off."""
    return {
        "use_central_boiler_feature": True,
        "central_boiler_activation_service": f"{helper}/input_boolean.turn_on",
        "central_boiler_deactivation_service": f"{helper}/input_boolean.turn_off",
        "central_boiler_activation_delay_sec": 0,
    } | changes


@dataclass
class FakeVtThermostat:
    """A thermostat VT handed to the plugin's feature manager, as ``vtherm_api`` declares it —
    its entity, name, unique ID and ``entry_infos`` — standing in for VT's central boiler
    settings; its unique ID matches no zone, so no zone is read through it."""

    entry_infos: dict[str, Any] = field(default_factory=vt_central_settings)
    entity_id: str = "climate.fake_vt_stand_in"
    name: str = "VT stand-in"
    unique_id: str = "fake_vt_stand_in"


@dataclass
class FakeZoneThermostat:
    """A zone's thermostat as VT hands it over (I12.10): VT's central boiler settings as the
    stand-in carries them, merged with the room's thermometer and window sensor — the user's
    devices, in ``entry_infos`` — and VT's clock of its last measurement, ``vtherm_api``'s
    ``last_temperature_measure``: by default a thermometer that measures all the time, so a room
    counts once time has moved past the plugin's start; ``measured`` sets it."""

    stand_in: FakeVtThermostat
    entity_id: str
    unique_id: str
    thermometer: str
    window_sensor: str
    name: str = "zone"
    measured: datetime | None = None

    @property
    def entry_infos(self) -> Any:
        infos = self.stand_in.entry_infos
        if not isinstance(infos, dict):
            return infos
        return infos | {
            "temperature_sensor_entity_id": self.thermometer,
            "window_sensor_entity_id": self.window_sensor,
        }

    @property
    def last_temperature_measure(self) -> datetime:
        from homeassistant.util import dt as dt_util

        return self.measured or dt_util.utcnow()


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
    """VT climate entities: a state plus VT's top-level attributes, registered as VT's — and
    VT's central boiler (I12): a thermostat handed over whose ``entry_infos`` say VT's central
    boiler is on with its commands on the helper, and the helper itself, which follows the zones
    as VT's count of 1 would — on while a known zone calls, off otherwise — each time a zone is
    set, until a test takes it over (``set_helper``). Each zone's thermostat is handed over too
    (``FakeZoneThermostat``), with its thermometer and window sensor as states: the thermometer
    follows the zone's temperature, the window sensor reads "off"."""

    hass: HomeAssistant
    entities: dict[str, str] = field(default_factory=dict)
    helper: str = VT_HELPER
    follow: bool = True
    stand_in: FakeVtThermostat = field(default_factory=FakeVtThermostat)
    thermostats: dict[str, FakeZoneThermostat] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from custom_components.vtherm_smart_boiler.vtherm_link import register_thermostat

        register_thermostat(self.hass, self.stand_in)
        self.hass.states.async_set(self.helper, "off")

    def set_helper(self, state: str | None, *, follow: bool = False) -> None:
        """The helper as VT's central boiler leaves it: "on", "off", any other state, or
        ``None`` — removed. The test takes it over unless ``follow``."""
        self.follow = follow
        if state is None:
            self.hass.states.async_remove(self.helper)
            return
        now = self.hass.states.get(self.helper)
        if now is None or now.state != state:
            self.hass.states.async_set(self.helper, state)

    def withdraw(self) -> None:
        """VT has handed no thermostat over (as at every start, until VT starts them): the
        stand-in and every zone's thermostat taken back."""
        from custom_components.vtherm_smart_boiler.vtherm_link import unregister_thermostat

        for thermostat in (self.stand_in, *self.thermostats.values()):
            unregister_thermostat(self.hass, thermostat)

    def hand_over(self) -> None:
        """VT hands its thermostats over again: the stand-in and every zone's."""
        from custom_components.vtherm_smart_boiler.vtherm_link import register_thermostat

        for thermostat in (self.stand_in, *self.thermostats.values()):
            register_thermostat(self.hass, thermostat)

    def vt_event(self, zone_id: str, kind: str, start: bool) -> None:
        """VT's safety (``kind`` "safety") or automatic window (``kind`` "window_auto") event
        for a zone, starting or ending, as VT 10.6.5 fires it."""
        self.hass.bus.async_fire(
            f"versatile_thermostat_{kind}_event",
            {"type": "start" if start else "end", "entity_id": self.entities[zone_id]},
        )

    def follow_zones(self) -> None:
        """VT's count of 1: the helper on while a known zone calls, as the plugin reads them."""
        from homeassistant.util import dt as dt_util

        from custom_components.vtherm_smart_boiler.core.demand import zone_wants_heat
        from custom_components.vtherm_smart_boiler.vtherm_link import VThermLink

        now = dt_util.utcnow().timestamp()
        zones = VThermLink(self.hass, list(self.entities.values())).zones()
        calling = any(z.is_known(now, None) and zone_wants_heat(z) for z in zones)
        self.set_helper("on" if calling else "off", follow=True)

    def add(self, zone_id: str, *, handed_over: bool = True, **attributes: Any) -> str:
        """A VT climate, registered as VT's, and — unless ``handed_over`` is false: a thermostat
        VT started before the plugin registered — its thermostat handed over."""
        registry = er.async_get(self.hass)
        entry = registry.async_get_or_create(
            "climate", VT_PLATFORM, f"fake_{zone_id}", suggested_object_id=f"fake_{zone_id}"
        )
        self.entities[zone_id] = entry.entity_id
        from custom_components.vtherm_smart_boiler.vtherm_link import register_thermostat

        thermostat = FakeZoneThermostat(
            self.stand_in,
            entry.entity_id,
            f"fake_{zone_id}",
            f"sensor.fake_{zone_id}_temperature",
            f"binary_sensor.fake_{zone_id}_window",
            name=zone_id,
        )
        self.thermostats[zone_id] = thermostat
        if handed_over:
            register_thermostat(self.hass, thermostat)
        self.hass.states.async_set(thermostat.window_sensor, "off")
        self.set(zone_id, **attributes)
        return entry.entity_id

    def set(self, zone_id: str, state: str = "heat", **attributes: Any) -> None:
        """A VT climate's state. In a mode, it shows what VT 10.4.0 shows once it has started
        the thermostat — ``is_ready`` true and its ``specific_states``; a test sets a zone VT
        has not started explicitly (``is_ready=False``), or gives ``None`` to leave either out,
        as VT does before its first refresh."""
        values: dict[str, Any] = {
            "current_temperature": 20.0,
            "temperature": 21.0,
            "hvac_action": "idle",
            "on_percent": 0.0,
            "power_percent": 0,
        }
        if state not in ("unavailable", "unknown"):
            values |= {"is_ready": True, "specific_states": {}}
        values |= attributes
        for key in ("is_ready", "specific_states"):
            if values.get(key, False) is None:
                del values[key]
        thermostat = self.thermostats.get(zone_id)
        if thermostat is not None and values.get("current_temperature") is not None:
            self.hass.states.async_set(
                thermostat.thermometer,
                str(values["current_temperature"]),
                {"unit_of_measurement": "°C", "device_class": "temperature"},
            )
        self.hass.states.async_set(self.entities[zone_id], state, values)
        if self.follow:
            self.follow_zones()


async def analysis_idle(coordinator: Any) -> None:
    """Until no analysis runs. Setup's first analysis and the clock's periodic one run as
    background tasks, which ``async_block_till_done`` does not wait for — nor can a test that
    holds another background task on purpose wait for them all (Z1)."""
    for _ in range(10_000_000):
        if not coordinator._analysing:
            return
        await asyncio.sleep(0)  # the loop's clock may be frozen: never a timed sleep
    raise AssertionError("an analysis never finished")


async def analyse_now(coordinator: Any) -> None:
    """The analysis a test asks for, once any analysis already running has finished: a call
    while one runs is skipped — only one runs at a time — so without the wait a test would
    depend on the machine's speed (Z1)."""
    await analysis_idle(coordinator)
    await coordinator.async_run_analysis()


_ASYNC_CALL = inspect.signature(ServiceRegistry.async_call)


@dataclass
class ServiceSpy:
    """Every service call made in the test's Home Assistant, as ``(domain, service, data)``,
    whether a service of that name is registered or not (P-118): Home Assistant fires
    ``EVENT_CALL_SERVICE`` only for services that exist, so a listener on it would miss a call
    that went nowhere. ``ServiceRegistry.async_call`` is patched for the test with a wrapper that
    records, then calls the real one. The test's own calls carry ``own`` as their context and
    are left out of ``plugin_calls``."""

    hass: HomeAssistant
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    contexts: list[Context | None] = field(default_factory=list)
    own: Context = field(default_factory=Context)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = ServiceRegistry.async_call
        spy = self

        async def async_call(registry: ServiceRegistry, *args: Any, **kwargs: Any) -> Any:
            if registry is spy.hass.services:
                bound = _ASYNC_CALL.bind(registry, *args, **kwargs)
                bound.apply_defaults()
                given = bound.arguments
                data = given["service_data"]
                spy.calls.append((given["domain"], given["service"], dict(data or {})))
                spy.contexts.append(given["context"])
            return await original(registry, *args, **kwargs)

        monkeypatch.setattr(ServiceRegistry, "async_call", async_call)

    def plugin_calls(self) -> list[tuple[str, str, dict[str, Any]]]:
        """The calls not made by the test itself."""
        return [
            call
            for call, context in zip(self.calls, self.contexts, strict=True)
            if context is not self.own
        ]

    def plugin_services(self) -> set[tuple[str, str]]:
        return {(domain, service) for domain, service, _ in self.plugin_calls()}


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


async def left_control_store(hass: Any, entry: Any) -> None:
    """PB-100: the entry ran before and left its control store, owing nothing. Control is
    configured only in the options of an entry that ran, so one with a control section and no
    store has lost it — it is taken as holding the boiler and hands back first (V1, R4), which
    a test of something else must not set off."""
    from custom_components.vtherm_smart_boiler.coordinator import control_store

    await control_store(hass, entry.entry_id).async_save({})
