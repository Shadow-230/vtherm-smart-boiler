"""Control in Home Assistant: switching on and off, keep-alive, every hand-back path, no write
without fresh data, guard alarms, "boiler gives no heat" and the allowed service calls.

Everything runs in the test's Home Assistant; the gateway and VT are fakes that record the calls
they receive.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from unittest.mock import patch

import attr
import pytest
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import UnitOfTemperature
from homeassistant.core import Context, HomeAssistant, ServiceCall, State, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import storage as ha_storage
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_capture_events,
    async_fire_mqtt_message,
    async_fire_time_changed,
    mock_integration,
    mock_restore_cache,
)

from custom_components.vtherm_smart_boiler import control as control_module
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.control_config import (
    CONTROL_DEFAULTS,
    MIGRATED_HARD_MIN,
)
from custom_components.vtherm_smart_boiler.core.alarms import AlarmKind
from custom_components.vtherm_smart_boiler.core.boiler_call import NoHeat, NoHeatReason
from custom_components.vtherm_smart_boiler.core.controller import ControlMode
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.signal_check import Feature, FeatureStatus
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.vtherm_link import (
    register_thermostat,
)

from . import control_chain
from .harness import (
    BOILER_ENTITIES,
    VT_HELPER,
    VT_PLATFORM,
    WEATHER_ENTITY,
    FakeBoiler,
    FakeForecasts,
    FakeVtThermostat,
    FakeZones,
    ServiceSpy,
    analyse_now,
    vt_central_settings,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SIGNALS = (Signal.FLAME, Signal.FLOW, Signal.OUTDOOR, Signal.DHW_ACTIVE)
CONFIRMED = "sensor.fake_gateway_control_setpoint"
CH_ECHO = "binary_sensor.fake_gateway_central_heating"
OUTDOOR = 5.0
EXPECTED = round(HeatingCurve().flow(OUTDOOR), 1)  # the curve's setpoint at 5 °C outside
# The lowest water temperature set: a test's entry is stored as minor version 1, so the entry
# migration keeps 0.2.1's 25 °C in its control section (X6; the new default is 20 °C).
LOWEST = MIGRATED_HARD_MIN
# Options stored with the control state ("taken with") are not migrated: without the lowest water
# temperature, its default applies to their hand-back.
DEFAULT_LOWEST = float(CONTROL_DEFAULTS["hard_min"])
START = datetime(2026, 1, 12, 8, tzinfo=UTC)
# Home Assistant's own store loader, taken before the test storage mock replaces it: a test that
# needs a real file on disk (under its tmp_path) puts it back for its own body only (with
# monkeypatch, whose undo may run after the mock's, the mock would outlive the test).
REAL_STORE_LOAD = ha_storage.Store._async_load
# The store layouts an earlier run may have left (V1): 0.2.1's, and 0.2.2's control store.
LAYOUTS = ("0.2.1", "0.2.2")


@dataclass
class FakeGateway:
    """``opentherm_gw`` services; the control setpoint entity echoes the override like the
    gateway does, or the thermostat's value without one. ``forced`` plays another controller."""

    hass: HomeAssistant
    thermostat: float = 40.0
    echo: bool = True
    readable: bool = True  # False: the control setpoint entity reports nothing known
    # The control setpoint entity shows this instead of a value ("unknown", "unavailable"), or
    # is not there ("missing"), while the boiler's own signals report on.
    read_back_shown: str | None = None
    forced: float | None = None
    override: float | None = None
    ch: bool = True  # heating on/off as the boiler receives it
    forced_ch: bool | None = None  # another controller switches heating
    fail_after: bool = False  # the setpoint arrives, but the call reports a failure (a timeout)
    connected: bool = True  # False: as opentherm_gw without its gateway — every service returns
    # without an error, nothing arrives, and the gateway's entities are unavailable
    reset_shown: bool = False  # while not connected, the entities show pyotgw's reset report
    # instead: written while the connection still counted, available with no value
    lost: list[tuple[str, Any]] = field(default_factory=list)  # calls that went nowhere
    # A control setpoint's call — not the hand-back's lowest or its CS=0 — waits for this (a slow
    # gateway).
    block: asyncio.Event | None = None
    block_hand_back: asyncio.Event | None = None  # the next hand-back's first call waits for it
    hang: asyncio.Event | None = None  # every call waits for this (a gateway that hangs)
    # CS=0 arrives, and its call raises this (a bug, a task cancelled inside the integration)
    release_error: Callable[[], BaseException] | None = None
    # CS=0 arrives and the call returns, but the gateway keeps the override and nothing new is
    # reported: pyotgw after its own timeout, or a command the PIC did not take
    ignore_release: bool = False
    # Every call returns, but the gateway takes none of it and reports nothing new: pyotgw
    # after its own timeouts.
    deaf: bool = False
    watch: Callable[[str, Any], None] | None = None  # told of every call as it arrives
    calls: list[tuple[str, Any]] = field(default_factory=list)
    times: list[float] = field(default_factory=list)  # when each setpoint arrived

    def register(self) -> None:
        async def setpoint(call: ServiceCall) -> None:
            value = float(call.data["temperature"])
            if self.watch is not None:
                self.watch("setpoint", value)
            if self.hang is not None:
                await self.hang.wait()
            if not self.connected:
                self.lost.append(("setpoint", value))
                return
            self.calls.append(("setpoint", value))
            self.times.append(datetime.now(UTC).timestamp())
            if self.deaf:
                return
            if value == 0 and self.release_error is not None:
                raise self.release_error()
            if value == 0 and self.ignore_release:
                return
            self.override = None if value == 0 else value
            if value == 0 and self.echo and self.readable and self.forced is None:
                # pyotgw writes the value the gateway accepted to its status at once; the
                # boiler's next report (``publish``) shows what it gets from then on.
                self.hass.states.async_set(CONFIRMED, "0.0", {"unit_of_measurement": "°C"})
            else:
                self.publish()
            if self.fail_after:
                raise HomeAssistantError("timed out")
            if self.block is not None and value not in (0.0, LOWEST):
                await self.block.wait()

        async def heating(call: ServiceCall) -> None:
            if self.watch is not None:
                self.watch("ch", call.data["ch_override"])
            if self.hang is not None:
                await self.hang.wait()
            if not self.connected:
                self.lost.append(("ch", call.data["ch_override"]))
                return
            self.calls.append(("ch", call.data["ch_override"]))
            if self.deaf:
                return
            if self.block_hand_back is not None and call.data["ch_override"] is True:
                event, self.block_hand_back = self.block_hand_back, None
                await event.wait()  # a hand-back starts with CH=1: it hangs, once
            self.ch = bool(call.data["ch_override"])
            self.publish()
            if self.fail_after:
                raise HomeAssistantError("timed out")

        self.hass.services.async_register("opentherm_gw", "set_control_setpoint", setpoint)
        self.hass.services.async_register("opentherm_gw", "set_central_heating_ovrd", heating)
        self.publish()

    def publish(self) -> None:
        if not self.connected:
            shown = "unknown" if self.reset_shown else "unavailable"
            self.hass.states.async_set(CH_ECHO, shown)
            self.hass.states.async_set(CONFIRMED, shown)
            return
        ch = self.ch if self.forced_ch is None else self.forced_ch
        self.hass.states.async_set(CH_ECHO, "on" if ch else "off")
        if self.read_back_shown == "missing":
            self.hass.states.async_remove(CONFIRMED)
            return
        if self.read_back_shown is not None:
            self.hass.states.async_set(CONFIRMED, self.read_back_shown)
            return
        if not self.readable:
            self.hass.states.async_set(CONFIRMED, "unknown", {"unit_of_measurement": "°C"})
            return
        if self.forced is not None:
            value = self.forced
        elif self.echo and self.override is not None:
            value = self.override
        else:
            value = self.thermostat
        self.hass.states.async_set(CONFIRMED, str(value), {"unit_of_measurement": "°C"})

    def setpoints(self) -> list[float]:
        return [value for kind, value in self.calls if kind == "setpoint"]


@dataclass
class Rig:
    hass: HomeAssistant
    freezer: Any
    boiler: FakeBoiler
    zones: FakeZones
    gateway: FakeGateway
    entry: MockConfigEntry | None = None
    flow: float | None = 35.0
    dhw: bool = False
    outdoor: float = OUTDOOR
    flow_reported: bool = True  # False: the flow is not reported again (a source that reports
    # only on change, as MQTT entities do)
    outdoor_reported: bool = True  # the same for the outdoor temperature
    flame: bool | None = False  # None: the flame's entity unavailable
    flame_reported: bool = True  # the same for the flame
    storage: dict[str, Any] = field(default_factory=dict)  # the test's stores (hass_storage)
    spy: ServiceSpy | None = None  # every service call (P-118)
    # PB-39: the translation key of the error the last switching off raised (its hand-back did
    # not get through), else None.
    switch_error: str | None = None

    @property
    def services(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Every service call made in the test's Home Assistant, the test's own included."""
        assert self.spy is not None
        return self.spy.calls

    def live(self) -> None:
        """The gateway's periodic reports: fresh boiler signals and setpoint echo; without its
        connection, the gateway's entities are unavailable."""
        connected = self.gateway.connected
        values: dict[Signal, float | bool | None] = {}
        if self.flame_reported:
            values[Signal.FLAME] = self.flame if connected else None
        values[Signal.DHW_ACTIVE] = self.dhw if connected else None
        if self.outdoor_reported:
            values[Signal.OUTDOOR] = self.outdoor if connected else None
        if self.flow_reported:
            values[Signal.FLOW] = self.flow if connected else None
        self.boiler.set_many(values)
        self.gateway.publish()

    async def advance(self, seconds: float, step: float = 10.0) -> None:
        elapsed = 0.0
        while elapsed < seconds:
            self.freezer.tick(step)
            elapsed += step
            self.live()
            async_fire_time_changed(self.hass)
            # The control step runs as a background task (PB-25).
            await self.hass.async_block_till_done(wait_background_tasks=True)

    def entity(self, domain: str, key: str) -> str:
        assert self.entry is not None
        found = er.async_get(self.hass).async_get_entity_id(
            domain, DOMAIN, f"{self.entry.entry_id}_{key}"
        )
        assert found is not None, key
        return found

    def state(self, domain: str, key: str) -> State:
        state = self.hass.states.get(self.entity(domain, key))
        assert state is not None
        return state

    async def switch(self, on: bool) -> None:
        """Control switched on or off, as an automation does it (I11.2: the action, no user),
        as the test's own call: tagged, so it is not taken for the plugin's (P-118)."""
        assert self.spy is not None
        self.switch_error = None
        try:
            await self.hass.services.async_call(
                "vtherm_smart_boiler",
                "set_control",
                {"enabled": on},
                blocking=True,
                context=self.spy.own,
            )
        except HomeAssistantError as err:
            if on or isinstance(err, ServiceValidationError):
                raise
            self.switch_error = err.translation_key  # PB-39: off, its hand-back failed
        await self.hass.async_block_till_done()

    def plugin_calls(self) -> set[tuple[str, str]]:
        """Service calls made by the plugin — a switch's included (P-118); the test's own calls
        are left out by their tag, not by their domain."""
        assert self.spy is not None
        return self.spy.plugin_services()


# What is wired to the gateway's thermostat terminals, as the form asks it (decision 1): the
# answer that fits each gateway topology.
FITTING_KIND = {"gateway_with_thermostat": "opentherm", "gateway_standalone": "none"}


def options(zones: FakeZones, **control: Any) -> dict[str, Any]:
    """An entry's options with control through the gateway; a gateway topology gets the kind
    that fits it unless one is given — ``thermostat_kind=None``: no answer, as an entry from
    before 0.2.2 (answer K)."""
    control_options = {
        "write_path": "opentherm_gw",
        "gateway_id": "gw",
        "confirmed_entity": CONFIRMED,
        "topology": "gateway_with_thermostat",
        # Manual, as an entry from before G11 D runs: the curve through 20 °C (Auto's own tests
        # give the mode).
        "curve": {"design_outdoor": -15, "design_flow": 55, "room_mode": "manual"},
        # I12: the helper VT's central boiler switches (the harness's stand-in).
        "vt_boiler_helper": zones.helper,
    } | control
    if "thermostat_kind" not in control:
        kind = FITTING_KIND.get(control_options["topology"])
        if kind is not None:
            control_options["thermostat_kind"] = kind
    elif control_options["thermostat_kind"] is None:
        del control_options["thermostat_kind"]
    return {
        "signals": {s.value: BOILER_ENTITIES[s] for s in SIGNALS},
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "monitor": {"monitoring_days": 0},
        "control": control_options,
    }


@pytest.fixture
def low_setpoint_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 11 blocks control without a heating switch until the user lifts it at K4. A test
    of that path's mechanics — kept for then, and for a hand-back an earlier version left owed —
    lifts the block in its one place."""
    from custom_components.vtherm_smart_boiler import control_config

    monkeypatch.setattr(control_config, "OFF_AS_LOW_SETPOINT_ALLOWED", True)


def integrations_running(rig: Rig) -> None:
    """The gateway's and MQTT's entries shown as running, as the control forms need (P-69)."""
    for domain in ("opentherm_gw", "mqtt"):
        for entry in rig.hass.config_entries.async_entries(domain):
            entry.mock_state(rig.hass, ConfigEntryState.LOADED)


def new_rig(
    hass: HomeAssistant,
    freezer: Any,
    zones: FakeZones,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    mqtt_entry: bool = True,
) -> Rig:
    """The rig: the gateway's fakes, one zone, and a spy on every service call. ``mqtt_entry``:
    MQTT's entry marked as set up — ``False`` where Home Assistant's own MQTT integration runs
    instead (``mqtt_rig``)."""
    freezer.move_to(START)
    # The integrations the gateway paths write through, set up (X5.5): the gateway's entry and
    # MQTT's. Control needs them there and enabled.
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw"}).add_to_hass(hass)
    if mqtt_entry:
        MockConfigEntry(domain="mqtt").add_to_hass(hass)
    boiler = FakeBoiler(hass, SIGNALS)
    gateway = FakeGateway(hass)
    gateway.register()
    zones.add("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig = Rig(hass, freezer, boiler, zones, gateway, storage=hass_storage, spy=ServiceSpy(hass))
    assert rig.spy is not None
    rig.spy.install(monkeypatch)
    rig.live()
    return rig


def marks_stop_unloaded(hass: HomeAssistant, domains: tuple[str, ...]) -> None:
    """Entries only marked as set up are not running when Home Assistant stops, so it does not
    unload them."""
    for entry in hass.config_entries.async_entries():
        if entry.domain in domains and entry.state is ConfigEntryState.LOADED:
            entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
async def rig(
    hass: HomeAssistant,
    freezer,
    zones: FakeZones,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    rig = new_rig(hass, freezer, zones, hass_storage, monkeypatch)
    yield rig
    await hass.async_block_till_done()  # a reload an options flow started, done before teardown
    # PB-101: VT central entries are only marked loaded too.
    marks_stop_unloaded(hass, ("opentherm_gw", "mqtt", "versatile_thermostat"))


# The OTGW firmware's MQTT names in the tests: its top topic and its node.
OTGW_TOP, OTGW_NODE = "OTGW", "otgw-1"
# Control through the OTGW firmware over MQTT (no opentherm_gw gateway).
MQTT_PATH = {"write_path": "otgw_mqtt", "mqtt_top": OTGW_TOP, "mqtt_node": OTGW_NODE}


@dataclass
class OtgwFirmware:
    """The OTGW firmware as MQTT carries it (P-122, T-22): a command on
    ``<top>/set/<node>/<command>`` takes effect in the gateway, which then reports the control
    setpoint it sends the boiler on ``<top>/value/<node>/TSet`` — the thermostat's own value
    without an override. An MQTT sensor, made by Home Assistant's MQTT discovery, reads it.
    ``answers=False``: the firmware is offline — the broker takes every command, nothing
    answers."""

    hass: HomeAssistant
    thermostat: float = 40.0
    answers: bool = True
    override: float | None = None
    commands: list[tuple[str, str]] = field(default_factory=list)

    async def start(self) -> str:
        """Listen for commands, make the read-back entity and report once: its entity ID."""
        from homeassistant.components import mqtt

        await mqtt.async_subscribe(self.hass, f"{OTGW_TOP}/set/{OTGW_NODE}/+", self._command)
        config = {
            "name": "Control setpoint",
            "state_topic": f"{OTGW_TOP}/value/{OTGW_NODE}/TSet",
            "unique_id": f"{OTGW_NODE}-TSet",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
        }
        async_fire_mqtt_message(
            self.hass, f"homeassistant/sensor/{OTGW_NODE}/TSet/config", json.dumps(config)
        )
        await self.hass.async_block_till_done()
        self.report()
        await self.hass.async_block_till_done()
        entity = er.async_get(self.hass).async_get_entity_id("sensor", "mqtt", f"{OTGW_NODE}-TSet")
        assert entity is not None
        return entity

    @callback
    def _command(self, message: Any) -> None:
        payload = message.payload
        text = payload.decode() if isinstance(payload, bytes) else str(payload)
        command = message.topic.rsplit("/", 1)[-1]
        self.commands.append((command, text))
        if not self.answers:
            return
        if command == "ctrlsetpt":
            value = float(text)
            self.override = None if value == 0 else value
        # Reported a moment later, as the gateway does, not inside the broker's delivery.
        self.hass.loop.call_soon(self.report)

    def report(self) -> None:
        value = self.thermostat if self.override is None else self.override
        async_fire_mqtt_message(self.hass, f"{OTGW_TOP}/value/{OTGW_NODE}/TSet", f"{value:.2f}")


@pytest.fixture
async def mqtt_rig(
    hass: HomeAssistant,
    freezer,
    zones: FakeZones,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    mock_hass_config: None,
    mqtt_mock_entry: Callable[[], Any],
):
    """The rig with Home Assistant's own MQTT integration — its paho client mocked, no broker,
    no configuration.yaml — where ``rig`` marks a stand-in entry (P-122): the plugin's commands
    go through ``mqtt.publish`` and MQTT's client."""
    rig = new_rig(hass, freezer, zones, hass_storage, monkeypatch, mqtt_entry=False)
    await mqtt_mock_entry()
    yield rig
    await hass.async_block_till_done()
    marks_stop_unloaded(hass, ("opentherm_gw", "versatile_thermostat"))


def published(client: Any) -> list[tuple[str, str]]:
    """What MQTT's client was given to publish on the firmware's command topics, in order."""
    found = []
    for call in client.publish.call_args_list:
        topic, payload = call.args[0], call.args[1]
        if topic.startswith(f"{OTGW_TOP}/set/"):
            found.append((topic, payload.decode() if isinstance(payload, bytes) else str(payload)))
    return found


def mqtt_hand_back(lowest: float) -> list[tuple[str, str]]:
    """V5's safe hand-back on the firmware's topics: the lowest water temperature, CH=1, CS=0."""
    base = f"{OTGW_TOP}/set/{OTGW_NODE}"
    return [
        (f"{base}/ctrlsetpt", f"{lowest:.1f}"),
        (f"{base}/chenable", "1"),
        (f"{base}/ctrlsetpt", "0"),
    ]


def control_key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.control"


def ran_before(rig: Rig, entry: MockConfigEntry, control: dict[str, Any] | None = None) -> None:
    """The entry ran before and left its control store, by default owing nothing. Control is
    configured only in the options of an entry that ran, so one with a control section and no
    stores counts as having lost them: it hands back first (V1, R4)."""
    key = control_key(entry)
    rig.storage[key] = {"version": 1, "key": key, "data": dict(control or {})}


def add_entry(rig: Rig, entry_options: dict[str, Any]) -> MockConfigEntry:
    """An entry that ran before, owing nothing."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
    ran_before(rig, entry)
    return entry


def add_current_entry(rig: Rig, entry_options: dict[str, Any]) -> MockConfigEntry:
    """An entry stored by this version, which no migration changes: a control section's own
    read-back stays its own, as a hand edit leaves it (I8.5b)."""
    from custom_components.vtherm_smart_boiler.config_flow import SmartBoilerConfigFlow

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=entry_options,
        minor_version=SmartBoilerConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(rig.hass)
    ran_before(rig, entry)
    return entry


async def start(rig: Rig, **control: Any) -> None:
    await set_up(rig, add_entry(rig, options(rig.zones, **control)))


async def test_a_setup_that_fails_late_leaves_nothing_running(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, hass_storage: dict[str, Any]
) -> None:
    """A setup that fails after control has started — here in the platforms — stops the control
    clock and lets go of VT again: nothing of it runs, writes or stays registered. A hand-back
    owed from an earlier run is still made before it gives up."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler import feature_manager

    async def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the platforms could not be set up")

    monkeypatch.setattr(rig.hass.config_entries, "async_forward_entry_setups", fail)
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"monitoring_since": 0.0, "control": {"controlling": True}},
    }
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert feature_manager.registration(rig.hass) is None
    assert rig.gateway.calls[-3:] == HAND_BACK
    count = len(rig.gateway.calls)
    await rig.advance(300)
    assert len(rig.gateway.calls) == count  # no control clock left running


async def test_control_is_off_by_default(rig: Rig) -> None:
    await start(rig)
    assert rig.state("binary_sensor", "control").state == "off"
    await rig.advance(60)
    assert rig.gateway.calls == []


async def test_control_is_not_held_back_on_the_first_day(rig: Rig) -> None:
    """The user's decision of 2026-10-08: no monitoring period holds control back. The entry is
    created now with 7 days of data for the verdict; switching on works at once, control heats
    and writes, and the switch shows that there is no verdict yet. One entry per test of this
    single-entry integration (P-125, T11)."""
    await set_up(rig, add_entry(rig, options(rig.zones) | {"monitor": {"monitoring_days": 7}}))
    await rig.switch(True)
    await rig.advance(30)
    switch = rig.state("binary_sensor", "control")
    assert switch.state == "on"
    assert switch.attributes["blockers"] == []
    assert switch.attributes["verdict"] == "not_enough_data"
    assert rig.state("sensor", "control_state").state == "heating"
    assert rig.gateway.calls


async def test_switching_on_writes_keeps_alive_and_switching_off_hands_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    # The setpoint first: the gateway applies heating on/off only while it holds a setpoint.
    assert rig.gateway.calls[:2] == [("setpoint", EXPECTED), ("ch", True)]
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"
    assert state.attributes["heating_confirmation"] == "unverified"  # no heating echo
    setpoint = rig.state("sensor", "control_setpoint")
    assert setpoint.state == "unknown"  # never the requested value before it is confirmed
    assert setpoint.attributes["requested"] == EXPECTED
    assert setpoint.attributes["confirmation"] == "waiting"

    await rig.advance(300)
    times = [t for t, (kind, _) in enumerate(rig.gateway.calls) if kind == "setpoint"]
    assert len(times) >= 10  # a keep-alive at least every 30 s over five minutes
    assert set(rig.gateway.setpoints()) == {EXPECTED}
    setpoint = rig.state("sensor", "control_setpoint")
    assert setpoint.state == str(EXPECTED)
    assert setpoint.attributes["confirmation"] == "confirmed_by_gateway"
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"

    await rig.switch(False)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # nothing written once handed back
    assert rig.state("sensor", "control_state").state == "disabled"


async def test_keep_alive_never_lapses_between_ticks(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    moments: list[float] = []

    async def setpoint(call: ServiceCall) -> None:
        moments.append(datetime.now(UTC).timestamp())
        rig.gateway.override = float(call.data["temperature"])
        rig.gateway.publish()

    rig.hass.services.async_register("opentherm_gw", "set_control_setpoint", setpoint)
    await rig.advance(600, step=7.0)  # an uneven clock
    gaps = [b - a for a, b in pairwise(moments)]
    assert gaps
    assert max(gaps) <= 45.0  # well inside the gateway's one-minute limit


async def test_no_write_without_fresh_boiler_data(rig: Rig) -> None:
    rig.flow = None
    rig.live()
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.gateway.calls == []
    assert rig.state("sensor", "control_state").state == "waiting_data"
    rig.flow = 35.0
    await rig.advance(20)
    assert ("setpoint", EXPECTED) in rig.gateway.calls


async def test_stale_data_stops_writes_and_hands_back_after_five_minutes(rig: Rig) -> None:
    """Without the flow nothing is written; after five minutes a hand-back. Control resumes by
    itself once the flow has been back for a minute without a break (X2), not before."""
    await start(rig)
    await rig.switch(True)
    rig.flow = None
    rig.live()
    count = len(rig.gateway.calls)
    await rig.advance(240)
    assert len(rig.gateway.calls) == count  # no keep-alive: the gateway's override lapses
    assert rig.state("sensor", "control_state").state == "waiting_data"
    await rig.advance(70)
    assert rig.gateway.calls[count:] == HAND_BACK
    assert rig.state("sensor", "control_state").state == "handed_back"
    resumed = len(rig.gateway.calls)
    rig.flow = 35.0
    await rig.advance(50)
    assert rig.gateway.calls[resumed:] == []  # fresh for less than a minute: still handed back
    assert rig.state("sensor", "control_state").state == "handed_back"
    await rig.advance(20)
    assert ("setpoint", EXPECTED) in rig.gateway.calls[resumed:]  # control resumes with data


async def test_vt_stopped_acts_through_the_zones(rig: Rig) -> None:
    """VT applies "Stopped" to its zones; the plugin only sees them stop calling: heating off,
    no hand-back; back to Auto, heating follows the zones again."""
    hass = rig.hass
    select = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(select.entity_id, "Auto")
    await start(rig)
    await rig.switch(True)
    hass.states.async_set(select.entity_id, "Stopped")
    rig.zones.set("living", "off", hvac_action="off", valve_open_percent=0, on_percent=0.0)
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("ch", False)
    assert 0.0 not in rig.gateway.setpoints()
    hass.states.async_set(select.entity_id, "Auto")
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await rig.advance(10)
    assert ("ch", True) in rig.gateway.calls[-2:]


def plugin_shutdown_jobs(hass: HomeAssistant) -> list[str]:
    return sorted(j.job.name for j in hass._shutdown_jobs if (j.job.name or "").startswith(DOMAIN))


def state_trackers(hass: HomeAssistant) -> dict[str, int]:
    """How many state-change callbacks Home Assistant holds per entity."""
    data = hass.data.get("track_state_change_data")
    if data is None:
        return {}
    return {entity: len(jobs) for entity, jobs in data.callbacks.items() if jobs}


async def test_unload_and_reload_hand_back_and_leave_no_loop(rig: Rig) -> None:
    """TB-33: a control entry holding the boiler, reloaded: one plugin shutdown job and the same
    state trackers per entity as before; then unloaded: handed back, no job, no tracker of the
    plugin's, and nothing more written."""
    hass = rig.hass
    before = state_trackers(hass)
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    assert rig.entry is not None
    jobs = plugin_shutdown_jobs(hass)
    trackers = state_trackers(hass)
    assert len(jobs) == len(set(jobs)) >= 1
    assert trackers != before
    assert await hass.config_entries.async_reload(rig.entry.entry_id)
    await hass.async_block_till_done()
    await rig.advance(30)
    assert rig.state("binary_sensor", "control").state == "on"
    assert plugin_shutdown_jobs(hass) == jobs
    assert state_trackers(hass) == trackers
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert plugin_shutdown_jobs(hass) == []
    assert state_trackers(hass) == before
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count


async def test_reload_resumes_control_as_it_was(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    handed = rig.gateway.calls.index(("setpoint", 0.0))
    await rig.advance(20)
    assert rig.state("binary_sensor", "control").state == "on"
    assert ("setpoint", EXPECTED) in rig.gateway.calls[handed:]


async def test_home_assistant_stop_hands_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.hass.async_stop()  # the hand-back runs as a shutdown job, before the stop event
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)


async def test_an_internal_error_hands_back_and_blocks_until_switched_off(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(rig)
    await rig.switch(True)
    original = control_module.loop_step

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(control_module, "loop_step", broken)
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert rig.state("binary_sensor", "alarm_control_error").state == "on"
    assert "control_error" in rig.state("binary_sensor", "control").attributes["blockers"]
    count = len(rig.gateway.calls)
    monkeypatch.setattr(control_module, "loop_step", original)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # blocked until the user switches it off and on
    await rig.switch(False)
    await rig.switch(True)
    assert ("setpoint", EXPECTED) in rig.gateway.calls[count:]
    assert rig.state("binary_sensor", "alarm_control_error").state == "off"


async def test_an_outside_change_is_rewritten_once_then_handed_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    rig.gateway.forced = 60.0  # another controller writes and keeps its value
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the one rewrite
    await rig.advance(100)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    await rig.advance(40)  # the rewrite was not confirmed in time; next step hands back
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"
    rig.gateway.forced = None
    count = len(rig.gateway.calls)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # latched: no fight


async def test_the_one_rewrite_and_the_latch_are_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """C11: a crash within the store's two-minute delay would forget the one rewrite — the next
    run would fight the other controller again — and the latch."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.forced = 60.0
    await rig.advance(20)  # held two steps (M10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the one rewrite
    assert stored_control(hass_storage, rig)["rewritten_at"] is not None
    await rig.advance(140)  # not confirmed in time: an outside change, handed back, latched
    assert rig.state("sensor", "control_state").state == "handed_back"
    stored = stored_control(hass_storage, rig)
    assert stored["latched"] is True
    assert stored["latched_by"] == ["outside_change"]


@pytest.mark.parametrize("shown", ["unknown", "unavailable"])
async def test_confirmation_missing_never_hands_back(rig: Rig, shown: str) -> None:
    """M11: the read-back unknown or unavailable for ten minutes while the boiler link stays
    fresh: nothing is judged — no "write ignored", no outside change — and after five minutes
    the information alarm "confirmation missing", naming the setpoint; control goes on, never a
    hand-back by itself (the boiler link decides that, X2). It clears at the first known
    read-back. Negative: 4 minutes 50 seconds — off."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    rig.gateway.read_back_shown = shown  # the read-back drops out; the gateway still reports
    await rig.advance(290)
    missing = rig.state("binary_sensor", "alarm_confirmation_missing")
    assert missing.state == "off"
    await rig.advance(20)
    missing = rig.state("binary_sensor", "alarm_confirmation_missing")
    assert missing.state == "on"
    assert missing.attributes["targets"] == ["setpoint"]
    count = len(rig.gateway.setpoints())
    await rig.advance(280)
    assert rig.state("sensor", "control_state").state == "heating"  # information only
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert 0.0 not in rig.gateway.setpoints()[count:]  # no hand-back
    if shown == "unknown":
        assert len(rig.gateway.setpoints()) > count  # the keep-alive goes on
    assert issue(rig, "setpoint_not_shown") is None  # unknown is not "another value" (Z4R2-03)
    rig.gateway.read_back_shown = None
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_confirmation_missing").state == "off"


async def test_a_write_with_the_gateway_read_back_unavailable_fails_and_is_retried(
    rig: Rig,
) -> None:
    """TB-30: opentherm_gw's services return while its gateway is away; with the read-back
    unavailable — flame and flow still fresh — a setpoint write counts as failed: the alarm
    rises and the write is sent again; it clears once the read-back is back."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"
    rig.gateway.read_back_shown = "unavailable"
    count = len(rig.gateway.setpoints())
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"
    sent = rig.gateway.setpoints()[count:]
    assert len(sent) >= 2  # sent again
    assert 0.0 not in sent  # no hand-back
    rig.gateway.read_back_shown = None
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"


async def test_a_value_never_taken_from_the_start_is_ignored_from_the_start(rig: Rig) -> None:
    """S-48, decision 6 (replaces 0.2.1's "another controller" here): the read-back keeps the
    value from before the plugin — the thermostat's — after each of the session's first three
    sends: ignored from the start. "Write ignored" names the setpoint; no hand-back and no outside
    change; the setpoint is not written again this session, keep-alives included, while heating
    on/off goes on."""
    rig.gateway.echo = False
    await start(rig)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(250)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"  # two attempts
    await rig.advance(120)
    ignored = rig.state("binary_sensor", "alarm_write_ignored")
    assert ignored.state == "on"
    assert ignored.attributes["targets"] == ["setpoint"]
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert rig.state("sensor", "control_state").state == "heating"  # control goes on
    assert rig.state("sensor", "control_setpoint").attributes["confirmation"] == "not_confirmed"
    count = len(rig.gateway.setpoints())
    heating = rig.gateway.calls.count(("ch", True))
    await rig.advance(120)
    assert len(rig.gateway.setpoints()) == count  # not again this session
    assert rig.gateway.calls.count(("ch", True)) > heating  # the other target goes on
    await rig.switch(False)
    rig.gateway.echo = True
    await rig.switch(True)  # a new session tries it again
    assert rig.gateway.setpoints()[-1] == EXPECTED
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"


@pytest.mark.parametrize("topology", ["gateway_standalone", "gateway_with_thermostat"])
async def test_a_setpoint_ignored_from_the_start_where_nothing_else_heats_raises_an_error(
    rig: Rig, topology: str
) -> None:
    """Z4-11 (decision 6 kept): stand-alone, the boiler refuses the control setpoint from the
    start of the session — the gateway reads its own 0 again after each of the first three
    sends. Ignored from the start as before: "write ignored", no hand-back, no block, control
    goes on; and as nothing else heats the house — without the setpoint the gateway gives the
    boiler no demand — a repair issue at error level says so and what to check. It goes with the
    session. Negative: with an OpenTherm thermostat on the gateway, which heats by its own
    request meanwhile, the information alarm alone."""
    standalone = topology == "gateway_standalone"
    if standalone:
        rig.gateway.thermostat = 0.0  # without the override a stand-alone gateway reads 0
    rig.gateway.echo = False  # the override is never shown taken
    rig.gateway.publish()
    await start(rig, topology=topology)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(250)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"  # two attempts
    assert issue(rig, "write_ignored_no_heat") is None
    await rig.advance(120)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert rig.state("sensor", "control_state").state == "heating"  # no hand-back, no block
    found = issue(rig, "write_ignored_no_heat")
    if not standalone:
        assert found is None
        return
    assert found is not None
    assert found.severity is ir.IssueSeverity.ERROR
    assert not found.is_fixable
    await rig.switch(False)
    assert issue(rig, "write_ignored_no_heat") is None  # it goes with the session


@pytest.mark.parametrize("ignored", ["on", "off"])
async def test_heating_ignored_from_the_start_stand_alone_latches_with_an_error(
    rig: Rig, ignored: str
) -> None:
    """Decision 4 of 0.2.3 (SB-03), stand-alone with a heating echo, the setpoint confirmed: the
    echo never shows "on" after each of the session's first three sends of CH=1 — "heating on"
    ignored from the start, so the boiler cannot heat and nothing else heats the house: control
    is latched with ``heating_on_ignored`` and handed back, and the latch's issue is an error.
    Before: Z4-11's "house not heated" issue with control going on, not latched, the switch
    never written again. Variant: the echo never shows "off" — "heating off" ignored from the
    start: answer O's latch and its issue alike. Neither raises Z4-11's issue."""
    stays_on = ignored == "off"
    cause = f"heating_{ignored}_ignored"
    rig.gateway.thermostat = 0.0  # without the override a stand-alone gateway reads 0
    rig.gateway.forced_ch = stays_on  # the echo stays where it was before the plugin
    rig.gateway.publish()
    if stays_on:  # no zone calls: control asks "off"
        rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await start(
        rig,
        topology="gateway_standalone",
        ch_confirmed_entity=CH_ECHO,
        alarm_reactions={"write_ignored": "info"},
    )
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(350)
    assert issue(rig, "control_latched") is None  # two attempts
    await rig.advance(20)  # the third, and the step after it
    alarm = rig.state("binary_sensor", "alarm_write_ignored")
    assert alarm.state == "on"
    assert alarm.attributes["targets"] == ["heating"]
    state = rig.state("sensor", "control_state")
    assert issue(rig, "write_ignored_no_heat") is None
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == [cause]
    latched = issue(rig, "control_latched")
    assert latched is not None
    assert latched.translation_key == f"control_latched_{cause}"
    assert latched.severity is ir.IssueSeverity.ERROR  # a hand-back stops heating
    assert not latched.is_fixable


async def test_a_dropped_override_is_sent_again_not_fought(rig: Rig) -> None:
    """A boiler's Data-Invalid answer clears the gateway's override: the read-back falls back to
    the thermostat's value from before the session. In the start phase (the value never held
    120 s) each drop is sent again at once, and the third makes it ignored from the start —
    "write ignored", no outside change, control goes on. After the start phase (a new session),
    a first drop without a trace is a lost command, sent again at once; a second within the hour
    that no send explains is another controller's: the one rewrite (decision 6, answer E)."""
    await start(rig)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    for drop in range(3):
        await rig.advance(30)  # confirmed, for less than 120 s
        count = len(rig.gateway.setpoints())
        rig.gateway.override = None  # dropped
        await rig.advance(10)
        if drop < 2:
            assert rig.gateway.setpoints()[count:] == [EXPECTED]  # at once
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert rig.state("sensor", "control_state").state == "heating"

    await rig.switch(False)
    await rig.advance(10)  # the gateway reports the thermostat's value again
    await rig.switch(True)  # a new session
    await rig.advance(150)  # confirmed and held: the start phase is over
    count = len(rig.gateway.setpoints())
    rig.gateway.override = None  # dropped, with no trace
    await rig.advance(10)
    assert rig.gateway.setpoints()[count:] == [EXPECTED]  # a lost command: at once
    assert unit_of(rig)._session.loop.setpoint.rewritten_at is None
    await rig.advance(600)
    rig.gateway.override = None  # again, ten minutes later
    await rig.advance(10)
    assert unit_of(rig)._session.loop.setpoint.rewritten_at is not None  # the one rewrite
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"


@pytest.mark.parametrize(
    ("topology", "severity"),
    [
        ("gateway_standalone", ir.IssueSeverity.ERROR),
        ("gateway_with_thermostat", ir.IssueSeverity.WARNING),
    ],
)
async def test_an_outside_change_always_steps_aside(
    rig: Rig,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    topology: str,
    severity: ir.IssueSeverity,
) -> None:
    """S-11 (decision 6, the user's answer H; replaces 0.2.1's "information" test, P53): the
    reaction "information" an earlier version stored no longer counts. Another controller holds
    its value after the one rewrite: writes stop for the one step between the block and the
    latch, then the plugin steps aside — the latch and the whole safe hand-back, and the entry's
    one latch issue, an error where the hand-back stops heating, else a warning. The latch, and
    its issue, come back after a restart; off, then on, clears both."""
    await start(rig, topology=topology, alarm_reactions={"outside_change": "info"})
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    rig.gateway.forced = 60.0  # another controller writes and keeps its value
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the one rewrite
    caplog.clear()
    stopped: list[bool] = []
    for _ in range(20):  # the rewrite is not confirmed in time: an outside change
        await rig.advance(10)
        state = rig.state("sensor", "control_state")
        stopped.append(state.attributes["writes_stopped"])
        if state.state == "handed_back":
            break
    assert stopped[-2:] == [True, False]  # writes stopped, for one step only
    assert stopped.count(True) == 1
    assert rig.gateway.calls[-3:] == HAND_BACK  # the whole safe hand-back, over its 60 °C
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched"
    assert found.severity is severity
    assert not found.is_fixable
    assert not found.is_persistent
    assert _logged(caplog, logging.WARNING, "control steps aside") == 1
    stored = stored_control(hass_storage, rig)
    assert stored["latched"] is True
    assert stored["latched_by"] == ["outside_change"]
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # no fight

    # A restart: the unload leaves the issue while the latch holds; Home Assistant's own restart
    # would leave a non-persistent issue inactive, so it is gone here.
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    assert await rig.hass.config_entries.async_unload(entry_id)
    await rig.hass.async_block_till_done()
    assert issue(rig, "control_latched") is not None
    ir.async_delete_issue(rig.hass, DOMAIN, f"control_latched_{entry_id}")
    assert await rig.hass.config_entries.async_setup(entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # still latched: nothing written
    assert rig.state("binary_sensor", "control").state == "on"
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.severity is severity

    rig.gateway.forced = None
    await rig.switch(False)
    assert issue(rig, "control_latched") is None  # the latch went with the session
    await rig.switch(True)  # the user's off and on
    assert rig.gateway.setpoints()[-1] == EXPECTED
    assert issue(rig, "control_latched") is None


async def test_a_failing_write_raises_an_alarm(rig: Rig) -> None:
    await start(rig)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(True)
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"


# --- I12: VT's central boiler decides whether the boiler heats ----------------------------------


def heating_on(rig: Rig) -> bool | None:
    return rig.state("sensor", "control_state").attributes["heating_on"]


async def test_vts_helper_drives_heating_both_ways_at_once(rig: Rig) -> None:
    """I12: VT's central boiler switches its helper; heating follows it at once — a step without
    waiting for the clock (writes at least 5 s apart, MIN_WRITE_INTERVAL_S) — whatever the rooms
    show: off with a room calling ("rooms call, VT's central boiler does not"), on with none
    (VT's own thresholds count what the plugin does not see)."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(10)
    assert heating_on(rig) is True  # the room calls; the helper follows it (the harness)
    rig.freezer.tick(6)
    rig.zones.set_helper("off")
    await rig.hass.async_block_till_done(wait_background_tasks=True)  # no tick
    state = rig.state("sensor", "control_state")
    assert state.attributes["heating_on"] is False
    assert "no_demand" in state.attributes["reasons"]
    called = rig.state("binary_sensor", "boiler_called")
    assert called.state == "off"
    assert called.attributes["call_reason"] == "below_threshold"
    assert called.attributes["demand_count"] == 1
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.freezer.tick(6)
    rig.zones.set_helper("on")
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert heating_on(rig) is True
    assert rig.state("binary_sensor", "boiler_called").state == "on"
    assert rig.state("sensor", "demand_count").state == "0"


@pytest.mark.parametrize("helper", ["unknown", "unavailable"])
@pytest.mark.parametrize(
    ("topology", "effect"), [("gateway_standalone", "off"), ("gateway_with_thermostat", "back")]
)
async def test_vts_decision_unknown_is_decision_3s_end_state(
    rig: Rig, helper: str, topology: str, effect: str
) -> None:
    """Decision 3 (I12): the helper neither on nor off while the rooms are known — nothing can
    ask for heat: stand-alone the usual "off", with a thermostat on the gateway the boiler is
    handed to it; the alarm "VT's decision unknown" at once, its repair issue after ten minutes.
    Both go the step the helper reads on or off again."""
    await start(rig, topology=topology)
    await rig.switch(True)
    await rig.advance(30)
    rig.zones.set_helper(helper)
    await rig.advance(30)
    state = rig.state("sensor", "control_state")
    assert "zones_unknown" in state.attributes["reasons"]
    if effect == "off":
        assert state.state == "idle"
        assert state.attributes["heating_on"] is False
    else:
        assert state.state == "handed_back"
    assert rig.state("binary_sensor", "alarm_vt_decision_unknown").state == "on"
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"
    reason = "waiting_data" if effect == "off" else "not_controlling"
    assert rig.state("binary_sensor", "boiler_called").attributes["call_reason"] == reason
    assert issue(rig, "no_zone_known") is None
    await rig.advance(600)
    found = issue(rig, "no_zone_known")
    assert found is not None
    kind = "off" if effect == "off" else "handed_back"
    assert found.translation_key == f"vt_decision_unknown_{kind}"
    assert found.translation_placeholders == {"helper": rig.zones.helper}
    severity = ir.IssueSeverity.ERROR if effect == "off" else ir.IssueSeverity.WARNING
    assert found.severity is severity
    rig.zones.set_helper("on")
    await rig.advance(20)
    assert rig.state("binary_sensor", "alarm_vt_decision_unknown").state == "off"
    assert issue(rig, "no_zone_known") is None
    assert heating_on(rig) is True


async def test_vts_decision_unknown_with_control_off_raises_no_issue(rig: Rig) -> None:
    """Negative: with control switched off the helper unknown raises neither the alarm nor the
    issue — nothing acts on it."""
    await start(rig)
    rig.zones.set_helper("unknown")
    await rig.advance(700)
    assert rig.state("binary_sensor", "alarm_vt_decision_unknown").state == "off"
    assert issue(rig, "no_zone_known") is None


@pytest.mark.parametrize("path", ["water", "relay"])
async def test_vts_activation_delay_is_shown_from_its_event(rig: Rig, path: str) -> None:
    """I12: VT's event announcing its activation delay, the helper still off: "off", with the
    reason ``activation_delay`` and when the delay ends — on the control state, the heat-call
    sensor and the plugin's own event. It ends when the helper turns on, when VT's event says
    its command went out, or a minute after its end (VT says nothing when it cancels it)."""
    from custom_components.vtherm_smart_boiler.const import BOILER_CALL_EVENT

    if path == "relay":
        await start_relay(rig)
    else:
        await start(rig)
    events = async_capture_events(rig.hass, BOILER_CALL_EVENT)
    await rig.switch(True)
    rig.zones.set_helper("off")
    await rig.advance(20)
    sent = dt_util.utcnow().timestamp()
    rig.hass.bus.async_fire(
        "versatile_thermostat_central_boiler_event", {"delayed_activation_sec": 120}
    )
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    assert "activation_delay" in state.attributes["reasons"]
    due = datetime.fromisoformat(state.attributes["activation_at"]).timestamp()
    assert due == pytest.approx(sent + 120.0)
    called = rig.state("binary_sensor", "boiler_called")
    assert called.attributes["call_reason"] == "activation_delay"
    assert events[-1].data["call_reason"] == "activation_delay"
    assert events[-1].data["activation_at"] is not None
    rig.hass.bus.async_fire("versatile_thermostat_central_boiler_event", {"central_boiler": False})
    await rig.advance(10)
    assert rig.state("sensor", "control_state").attributes["activation_at"] is None
    rig.hass.bus.async_fire(
        "versatile_thermostat_central_boiler_event", {"delayed_activation_sec": 60}
    )
    await rig.advance(10)
    assert rig.state("sensor", "control_state").attributes["activation_at"] is not None
    await rig.advance(130)  # its end and the minute after: VT cancelled it silently
    state = rig.state("sensor", "control_state")
    assert "activation_delay" not in state.attributes["reasons"]
    assert state.attributes["activation_at"] is None
    rig.hass.bus.async_fire(
        "versatile_thermostat_central_boiler_event", {"delayed_activation_sec": 120}
    )
    await rig.advance(10)
    rig.zones.set_helper("on")
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    assert "activation_delay" not in state.attributes["reasons"]
    assert state.attributes["activation_at"] is None
    assert "demand" in state.attributes["reasons"]
    assert rig.state("binary_sensor", "boiler_called").state == "on"


@pytest.mark.parametrize(
    "data", [{}, {"delayed_activation_sec": 0}, {"delayed_activation_sec": "x"}, {"other": 1}]
)
async def test_a_vt_event_this_version_does_not_read_changes_nothing(rig: Rig, data: dict) -> None:
    """Negative: VT's event without its two keys, or with a delay that is no positive number of
    seconds, shows no delay."""
    await start(rig)
    await rig.switch(True)
    rig.zones.set_helper("off")
    await rig.advance(20)
    rig.hass.bus.async_fire("versatile_thermostat_central_boiler_event", data)
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    assert "activation_delay" not in state.attributes["reasons"]
    assert state.attributes["activation_at"] is None


@pytest.mark.parametrize("helper", [None, "switch.boiler"])
async def test_without_an_input_boolean_helper_control_is_blocked(
    rig: Rig, helper: str | None
) -> None:
    """I12: no helper picked, or one of another kind — a blocker of the configuration's, and
    switching on is refused with its text."""
    await start(rig, vt_boiler_helper=helper)
    await rig.advance(10)
    assert "no_vt_boiler_helper" in blockers(rig)
    assert "vt_command_not_helper" not in blockers(rig)  # named once a helper is picked
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_no_vt_boiler_helper"


async def test_a_helper_that_is_gone_blocks_control(rig: Rig) -> None:
    """I12: the helper picked no longer exists — blocked, handed back if control held the
    boiler; back, control resumes. Negative: with the harness's helper nothing blocks."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(10)
    assert not {b for b in blockers(rig) if "vt" in b}
    rig.zones.set_helper(None)
    await rig.advance(10)
    assert "vt_boiler_helper_missing" in blockers(rig)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # handed back
    rig.zones.set_helper("on")
    await rig.advance(20)
    assert "vt_boiler_helper_missing" not in blockers(rig)
    assert heating_on(rig) is True


@pytest.mark.parametrize(
    "changes",
    [
        {"use_central_boiler_feature": False},
        {"central_boiler_activation_service": ""},
        {"central_boiler_deactivation_service": None},
    ],
    ids=["unticked", "no_activation", "no_deactivation"],
)
async def test_vts_central_boiler_not_set_blocks_control(rig: Rig, changes: dict) -> None:
    """I12: VT's central boiler unticked, or without one of its commands — with one only, VT
    counts it as configured, but the helper would never turn back — blocks control, and
    switching on is refused with its text."""
    await start(rig)
    vt_central_boiler(rig, True, **changes)
    await rig.advance(10)
    assert "vt_central_boiler_not_set" in blockers(rig)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_vt_central_boiler_not_set"
    vt_central_boiler(rig, True)
    await rig.advance(10)
    assert "vt_central_boiler_not_set" not in blockers(rig)


@pytest.mark.parametrize(
    ("command", "named"),
    [
        ("switch.boiler_relay/switch.turn_on", "switch.boiler_relay"),
        ("climate.boiler/climate.set_hvac_mode/hvac_mode:heat", "climate.boiler"),
        (f"{VT_HELPER}/input_boolean.toggle", VT_HELPER),
        (f"{VT_HELPER}/input_boolean.turn_off", VT_HELPER),
        ("not a command", "not a command"),
    ],
    ids=["a_relay", "a_boiler_thermostat", "toggled", "reversed", "unreadable"],
)
async def test_vts_commands_on_anything_but_the_helper_block_and_name_it(
    rig: Rig, command: str, named: str
) -> None:
    """I12: VT's activation command switching anything but the helper on — two controllers —
    blocks control and raises a repair issue naming what it switches, with the way out for a
    relay; set right, both go."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(10)
    vt_central_boiler(rig, True, central_boiler_activation_service=command)
    await rig.advance(10)
    assert "vt_command_not_helper" in blockers(rig)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # handed back
    found = issue(rig, "vt_command_not_helper")
    assert found is not None
    assert found.translation_placeholders == {"entity": named, "helper": rig.zones.helper}
    assert found.severity is ir.IssueSeverity.WARNING
    vt_central_boiler(rig, True)
    await rig.advance(20)
    assert "vt_command_not_helper" not in blockers(rig)
    assert issue(rig, "vt_command_not_helper") is None


async def test_the_commands_issue_goes_with_the_unit(rig: Rig) -> None:
    """The repair issue of VT's commands goes when the entry unloads; the next run tells again
    at its first step."""
    await start(rig)
    vt_central_boiler(rig, True, central_boiler_deactivation_service="switch.x/switch.turn_off")
    await rig.advance(10)
    assert issue(rig, "vt_command_not_helper") is not None
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    await rig.hass.config_entries.async_unload(entry_id)
    await rig.hass.async_block_till_done()
    found = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"vt_command_not_helper_{entry_id}")
    assert found is None


async def test_vts_settings_not_known_yet_are_waited_for(rig: Rig) -> None:
    """I12: VT has handed no thermostat over yet — its central boiler's settings cannot be
    checked: a blocker that passes on its own; switching on is not refused but waits, and
    control takes the boiler once VT hands a thermostat over."""
    rig.zones.withdraw()
    await start(rig)
    await rig.advance(10)
    assert "vt_central_boiler_unknown" in blockers(rig)
    await rig.switch(True)  # waited for, not refused
    await rig.advance(10)
    assert ("setpoint", EXPECTED) not in rig.gateway.calls
    rig.zones.hand_over()
    await rig.advance(20)
    assert "vt_central_boiler_unknown" not in blockers(rig)
    assert ("setpoint", EXPECTED) in rig.gateway.calls


async def test_the_newest_thermostat_gives_vts_settings(rig: Rig) -> None:
    """VT's central boiler settings are read from the newest thermostat VT handed over: one
    handed over later with VT's central boiler unticked blocks; one whose ``entry_infos`` cannot
    be read is passed over."""
    await start(rig)
    await rig.advance(10)
    unreadable = FakeVtThermostat(entry_infos=None, unique_id="fake_unreadable")  # type: ignore[arg-type]
    register_thermostat(rig.hass, unreadable)
    await rig.advance(10)
    assert not {b for b in blockers(rig) if b.startswith("vt_")}
    unticked = FakeVtThermostat(
        entry_infos=vt_central_settings(rig.zones.helper, use_central_boiler_feature=False),
        unique_id="fake_unticked",
    )
    register_thermostat(rig.hass, unticked)
    await rig.advance(10)
    assert "vt_central_boiler_not_set" in blockers(rig)


async def test_a_monitor_alarm_set_to_hand_back_no_longer_hands_back(rig: Rig) -> None:
    """Decision 7 (S-30, Y1): a reaction an earlier version stored for a monitor alarm is
    neutralised — the pressure below the "add water" threshold raises its alarm after five
    minutes and informs; control keeps the boiler, nothing is handed back or latched."""
    rig.boiler = FakeBoiler(rig.hass, (*SIGNALS, Signal.PRESSURE))
    rig.boiler.set(Signal.PRESSURE, 1.5)
    rig.live()
    entry_options = options(rig.zones, alarm_reactions={"pressure_low": "hand_back"})
    entry_options["signals"][Signal.PRESSURE.value] = rig.boiler.entity(Signal.PRESSURE)
    entry_options["monitor"] = entry_options.get("monitor", {}) | {"add_water_below": 0.8}
    entry = add_entry(rig, entry_options)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.switch(True)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    rig.boiler.set(Signal.PRESSURE, 0.5)
    await rig.advance(400)
    assert rig.state("binary_sensor", "alarm_pressure_low").state == "on"
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert rig.state("sensor", "control_state").state == "heating"
    assert rig.state("binary_sensor", "control").attributes["blocked_by"] == []
    assert unit_of(rig).status.latched_by == ()


@pytest.mark.parametrize("priority", [True, False])
async def test_hot_water_without_priority_takes_no_heat_from_the_rooms(
    rig: Rig, priority: bool
) -> None:
    """I6.4 (decision 8): hot water with priority — a combi, a tank through a three-way valve —
    takes the heat from the rooms: "boiler gives no heat" is on for hot water (I12.9) and heat is
    not available to the zone. Without priority — a buffer, a tank charged in parallel — the
    rooms keep their heat: the sensor off, heat available. Nothing of SmartPI is called."""
    zone = rig.zones.entities["living"]
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    entry_options = options(rig.zones)
    entry_options["boiler"] |= {
        "connection": "opentherm_gw",
        "control_mode": "full",
        "heat_source": "gas",
        "type": "combi",
        "dhw_priority": priority,
    }
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    rig.flame = True
    rig.dhw = True
    await rig.advance(30)
    status = rig.entry.runtime_data.control.status
    assert status.mode is ControlMode.HEATING
    hot_water = NoHeat(True, NoHeatReason.HOT_WATER)
    assert status.no_heat == (hot_water if priority else NoHeat(False))
    assert not [call for call in rig.plugin_calls() if call[0] == "vtherm_smartpi"]
    # The heat the zone gets, the flame burning (I8, decision C1; the diagnostics show it).
    view = rig.entry.runtime_data.data.zones[zone]
    assert view.heat.available is not priority


async def test_a_failing_listener_does_not_stop_the_others(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-38: a listener whose state write raises is isolated — the later ones still update —
    and logged once while it keeps failing; it is logged again only after it has worked."""
    await start(rig)
    unit = unit_of(rig)
    failing = True
    seen: list[str] = []

    def broken() -> None:
        if failing:
            raise RuntimeError("a broken entity")

    unit._listeners.insert(0, broken)
    unit.async_add_listener(lambda: seen.append(unit.status.mode.value))
    await rig.switch(True)
    await rig.switch(False)
    assert len(seen) >= 2
    assert _logged(caplog, logging.ERROR, "A control listener failed") == 1
    failing = False
    await rig.switch(True)
    failing = True
    await rig.switch(False)
    assert _logged(caplog, logging.ERROR, "A control listener failed") == 2


async def test_the_entity_path_calls_only_its_configured_entities(rig: Rig) -> None:
    """TB-32: through a setpoint number, a heating switch and an expiring external-control
    switch, a session and its hand-back make only allowed calls, each to a configured entity —
    none to another entity of the same services."""
    number = FakeNumber(rig.hass)
    number.register()
    heating = FakeSwitch(rig.hass)
    heating.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    other = FakeSwitch(rig.hass, entity_id="input_boolean.someone_elses")
    other.register()
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="held",
        ch_entity=heating.entity_id,
        ch_write_type="held",
        hand_back="switch",
        hand_back_entity=external.entity_id,
        hand_back_entity_write_type="expiring",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.switch(True)
    await rig.advance(1800)
    rig.dhw = True
    await rig.advance(60)
    rig.dhw = False
    await rig.advance(60)
    await rig.switch(False)
    assert rig.entry is not None
    allowed = rig.entry.runtime_data.control.allowed_services | {("weather", "get_forecasts")}
    calls = rig.spy.plugin_calls() if rig.spy is not None else []
    assert {(domain, service) for domain, service, _ in calls} <= allowed
    configured = {number.entity_id, heating.entity_id, external.entity_id}
    targets = {data.get("entity_id") for domain, _, data in calls if domain != "weather"}
    assert targets == configured
    assert number.writes
    assert heating.writes
    assert external.writes.count(True) > 1  # renewed while it holds the boiler
    assert external.writes[-1] is False  # handed back
    assert other.writes == []


async def test_only_allowed_services_are_called(rig: Rig) -> None:
    """Only the write path's services; none of SmartPI's, even with hot water running in a
    SmartPI room (I12.9: no learning pauses)."""
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        specific_states={"smartpi_learning_enabled": True},
    )
    rig.zones.configure("living", proportional_function="smartpi")
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(30)
    await rig.switch(False)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    allowed = unit.allowed_services | {("weather", "get_forecasts")}
    assert allowed >= rig.plugin_calls()
    assert unit.allowed_services == {
        ("opentherm_gw", "set_control_setpoint"),
        ("opentherm_gw", "set_central_heating_ovrd"),
    }


async def test_control_comes_back_after_a_restart(
    hass: HomeAssistant, rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The stored wish "on" brings control back after a restart (I11.3: from the store, the
    control switch's restored state aside)."""
    await start_with_stored(rig, hass_storage, {"enabled": True}, "0.2.2")
    assert rig.state("binary_sensor", "control").state == "on"
    await rig.advance(10)
    assert ("setpoint", EXPECTED) in rig.gateway.calls


@pytest.mark.parametrize(
    ("kind", "cycle", "named"),
    [
        ("thermostat_over_switch", 5, True),  # VT's default cycle
        ("thermostat_over_switch", 9.5, True),
        ("thermostat_over_switch", 10, False),  # the gas-boiler convention: 6 cycles an hour
        ("thermostat_over_switch", 15, False),
        ("thermostat_over_valve", 5, False),  # a valve opens in proportion: no gaps
        ("thermostat_over_climate", 5, False),
        (None, 5, False),  # settings that do not say what the zone is
        ("thermostat_over_switch", None, False),  # nor its cycle
        ("thermostat_over_switch", True, False),
    ],
)
async def test_a_short_vt_cycle_is_named_while_controlling(
    rig: Rig, kind: str | None, cycle: object, named: bool
) -> None:
    """K4 (the user's decision of 2026-11-17): a zone VT switches on and off in cycles under
    10 min is named, with its cycle, in a warning while control is configured — each gap between
    its pulses stops the burner (J4's F9; the literature's 6 cycles an hour for gas boilers). Its
    type and cycle from the thermostat's ``entry_infos`` (I12.7)."""
    rig.zones.configure(
        "living", proportional_function="tpi", thermostat_type=kind, cycle_min=cycle
    )
    await start(rig)
    assert rig.entry is not None
    found = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"zone_cycle_short_{rig.entry.entry_id}")
    if not named:
        assert found is None
        return
    assert found is not None
    assert found.translation_key == "zone_cycle_short"
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_placeholders == {"zones": f"fake living ({cycle:g} min)"}


async def test_a_short_vt_cycle_is_not_named_without_control_and_goes_once_lengthened(
    rig: Rig,
) -> None:
    """K4: the warning is the boiler's, so it needs control — not in monitor mode, where the
    plugin starts nothing; and it goes once the cycle in VT is 10 min or more. While VT has not
    handed the thermostat over, its last answer stands (PB-47)."""
    rig.zones.configure("living", thermostat_type="thermostat_over_switch", cycle_min=5)
    await set_up(rig, add_entry(rig, without_control(options(rig.zones))))
    assert rig.entry is not None
    issue_id = f"zone_cycle_short_{rig.entry.entry_id}"
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, issue_id) is None
    await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = None
    await start(rig)
    assert rig.entry is not None
    issue_id = f"zone_cycle_short_{rig.entry.entry_id}"
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, issue_id) is not None
    rig.zones.stop("living")  # VT reloads the thermostat: its last answer stands
    rig.entry.runtime_data.check_zone_cycles()
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, issue_id) is not None
    rig.zones.configure("living", cycle_min=15)
    rig.zones.hand("living")
    rig.entry.runtime_data.check_zone_cycles()
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, issue_id) is None
    # I12.11: a room no longer counted by VT's central boiler is no room: nothing of it stands.
    rig.zones.configure("living", cycle_min=5)
    rig.entry.runtime_data.check_zone_cycles()
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, issue_id) is not None
    rig.zones.configure("living", used_by_controls_central_boiler=False)
    rig.entry.runtime_data.check_zone_cycles()
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, issue_id) is None


@dataclass
class FakeNumber:
    """A writable setpoint entity (like a boiler's EMS or ESPHome number) that records writes.

    Like Home Assistant, it drops a call while the entity is unavailable; ``lowest`` plays a device
    that ignores values below it and keeps its own; ``refuse``, a value its service rejects with
    an error; ``forced``, another controller holding its value over every write; ``assumed``, an
    optimistic entity (``assumed_state``) that shows whatever it was given.
    """

    hass: HomeAssistant
    entity_id: str = "input_number.fake_boiler_flow"
    writes: list[float] = field(default_factory=list)
    available: bool = True
    echo_later: bool = False  # as ESPHome or MQTT entities: the new value shows on a later tick
    lowest: float | None = None
    refuse: float | None = None
    forced: float | None = None
    assumed: bool = False
    value: float = 50.0
    unit: str = "°C"
    attributes: dict[str, Any] = field(default_factory=dict)  # min, max, step

    def register(self) -> None:
        async def set_value(call: ServiceCall) -> None:
            if not self.available:
                return  # Home Assistant skips an unavailable entity without an error
            value = float(call.data["value"])
            if value == self.refuse:
                raise HomeAssistantError("the device refused the value")
            self.writes.append(value)
            if self.lowest is None or value >= self.lowest:
                self.value = value
            if self.forced is not None:
                self.value = self.forced  # the other controller writes its value again
            if not self.echo_later:
                self.publish(self.value)

        self.hass.services.async_register("input_number", "set_value", set_value)
        self.publish(self.value)

    def publish(self, value: float) -> None:
        state = str(value) if self.available else "unavailable"
        attributes = {"unit_of_measurement": self.unit, **self.attributes}
        if self.assumed:
            attributes["assumed_state"] = True
        self.hass.states.async_set(self.entity_id, state, attributes)

    def set_available(self, available: bool) -> None:
        self.available = available
        self.publish(self.value)


@dataclass
class FakeSwitch:
    """A held heating switch (an ESPHome or EMS-ESP CH enable), or an external-control switch,
    that records its writes; like Home Assistant, it drops a call while unavailable. Several
    fakes share the ``input_boolean`` services, each answering for its own entity."""

    hass: HomeAssistant
    entity_id: str = "input_boolean.fake_ch"
    writes: list[bool] = field(default_factory=list)
    available: bool = True
    on: bool = True
    stuck_on: bool = False  # it takes "on" but will not go off
    stuck_off: bool = False  # it takes "off" but will not go on
    fail_off: bool = False  # "off" lands, then its call reports a failure (a slow integration)

    def register(self) -> None:
        fakes: dict[str, FakeSwitch] = self.hass.data.setdefault("fake_switches", {})
        fakes[self.entity_id] = self

        async def turn(call: ServiceCall, on: bool) -> None:
            fake = fakes.get(call.data["entity_id"])
            if fake is None or not fake.available:
                return
            fake.writes.append(on)
            fake.on = (on or fake.stuck_on) and not fake.stuck_off
            fake.publish()
            if not on and fake.fail_off:
                raise HomeAssistantError("timed out")

        async def turn_on(call: ServiceCall) -> None:
            await turn(call, True)

        async def turn_off(call: ServiceCall) -> None:
            await turn(call, False)

        self.hass.services.async_register("input_boolean", "turn_on", turn_on)
        self.hass.services.async_register("input_boolean", "turn_off", turn_off)
        self.publish()

    def publish(self) -> None:
        state = ("on" if self.on else "off") if self.available else "unavailable"
        self.hass.states.async_set(self.entity_id, state)

    def set_available(self, available: bool) -> None:
        self.available = available
        self.publish()


def held_entity(number: FakeNumber, **extra: Any) -> dict[str, Any]:
    """Control through a held setpoint entity with a value hand-back."""
    return {
        "write_path": "entity",
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "hand_back": "value",
        "hand_back_value": 50,
        "hand_back_value_effect": "own_control",
        "confirmed_entity": number.entity_id,
        "topology": "virtual",
    } | extra


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_held_setpoint_is_written_on_change_only(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, decision_interval_min=1, ramp_k_per_min=10))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    await rig.advance(120)
    assert number.writes == [EXPECTED]  # the device holds it: no keep-alive

    rig.outdoor = -5.0
    await rig.advance(120)
    assert number.writes[-1] > EXPECTED
    assert number.writes == sorted(number.writes)  # the ramp spreads the rise over the steps
    count = len(number.writes)
    await rig.advance(120)
    assert len(number.writes) == count  # steady: nothing more written
    await rig.switch(False)
    assert number.writes[-1] == 50.0  # the hand-back value
    assert rig.entry is not None
    assert "writes" not in rig.entry.runtime_data.control.stored()  # no daily cap to keep


async def test_ems_esp_switches_heating_off_with_setpoint_zero(rig: Rig) -> None:
    """I6 (decision 4): on EMS-ESP, with no heating switch, control is not blocked — "off" is
    the setpoint 0, EMS-ESP's own "Force Heating Off", repeated as the expiring setpoint is; a
    zone calling again gets the curve's water. Switching off hands back through EMS-ESP's
    timeout: the lowest water temperature once, then nothing more is written. Without the
    connection (an entry from before the panels) decision 11 still blocks it."""
    number = FakeNumber(rig.hass)
    number.register()
    ems_esp = {
        "write_path": "entity",
        "setpoint_entity": number.entity_id,
        "write_type": "expiring",
        "hand_back": "timeout",
        "confirmed_entity": number.entity_id,
        "topology": "virtual",
    }
    entry_options = options(rig.zones, **ems_esp)
    entry_options["boiler"] |= {"connection": "ems_esp", "control_mode": "full"}
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    assert number.writes[-1] == EXPECTED
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(60)
    assert number.writes[-1] == 0.0  # off
    count = len(number.writes)
    await rig.advance(60)
    assert len(number.writes) > count  # repeated: it lapses within about a minute
    assert set(number.writes[count:]) == {0.0}
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await rig.advance(60)
    assert number.writes[-1] == EXPECTED
    await rig.switch(False)
    handed_back = len(number.writes)
    await rig.advance(120)
    assert len(number.writes) == handed_back  # the timeout lets EMS-ESP drop it


async def test_ems_esp_off_below_the_entitys_range_blocks_and_resumes(rig: Rig) -> None:
    """P-15 (the review of 2026-10-13, A3): on EMS-ESP "off" is the setpoint 0. The setpoint
    entity's lowest value moving above 0 while control runs — an EMS-ESP update, say — would
    leave the plugin unable to switch heating off: the blocker "outside the entity's range"
    stops control at once and hands back (EMS-ESP's timeout: nothing more is written), shown on
    the control state; once the entity takes 0 again, control resumes by itself."""
    number = FakeNumber(rig.hass, attributes={"min": 0, "max": 90, "step": 0.5})
    number.register()
    ems_esp = {
        "write_path": "entity",
        "setpoint_entity": number.entity_id,
        "write_type": "expiring",
        "hand_back": "timeout",
        "confirmed_entity": number.entity_id,
        "topology": "virtual",
    }
    entry_options = options(rig.zones, **ems_esp)
    entry_options["boiler"] |= {"connection": "ems_esp", "control_mode": "full"}
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    assert number.writes
    number.attributes = {"min": 5, "max": 90, "step": 0.5}
    number.publish(number.value)
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    assert state.state == "not_allowed"
    assert "setpoint_outside_entity_range" in state.attributes["blockers"]
    count = len(number.writes)
    await rig.advance(120)
    assert len(number.writes) == count  # handed back: EMS-ESP drops the setpoint by itself
    number.attributes = {"min": 0, "max": 90, "step": 0.5}
    number.publish(number.value)
    await rig.advance(60)
    assert rig.state("sensor", "control_state").state != "not_allowed"
    assert len(number.writes) > count  # control resumed by itself


@pytest.mark.parametrize("connection", [None, "esphome"])
async def test_without_ems_esp_a_setpoint_alone_stays_blocked(
    rig: Rig, connection: str | None
) -> None:
    """Decision 11 holds wherever the connection is not EMS-ESP: no heating switch, no control."""
    number = FakeNumber(rig.hass)
    number.register()
    entry_options = options(
        rig.zones,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="expiring",
        hand_back="timeout",
        confirmed_entity=number.entity_id,
        topology="virtual",
        esphome_safe_start=True,
    )
    if connection is not None:
        entry_options["boiler"] |= {"connection": connection, "control_mode": "full"}
    await set_up(rig, add_entry(rig, entry_options))
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_no_heating_switch"
    assert number.writes == []


async def test_mqtt_path_calls_only_its_publish(mqtt_rig: Rig, mqtt_client_mock: Any) -> None:
    """P-122: through Home Assistant's own MQTT integration, its client mocked — not a service
    registered in its place: the setpoint and heating on go out on the firmware's command topics
    in that order, switching off sends the safe hand-back, and ``mqtt.publish`` is the only
    service the plugin calls."""
    rig = mqtt_rig
    firmware = OtgwFirmware(rig.hass)
    read_back = await firmware.start()
    await start(rig, **MQTT_PATH, gateway_id=None, confirmed_entity=read_back)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.hass.states.get(read_back).state == f"{EXPECTED:.2f}"  # the firmware took it
    await rig.switch(False)
    sent = published(mqtt_client_mock)
    base = f"{OTGW_TOP}/set/{OTGW_NODE}"
    assert sent[:2] == [(f"{base}/ctrlsetpt", f"{EXPECTED:.1f}"), (f"{base}/chenable", "1")]
    assert sent[-3:] == mqtt_hand_back(LOWEST)
    assert firmware.commands[-3:] == [(t.rsplit("/", 1)[-1], v) for t, v in sent[-3:]]
    assert rig.plugin_calls() == {("mqtt", "publish")}
    assert not unit_of(rig).hand_back_owed


@pytest.mark.parametrize("indication", ["off", "on"])
async def test_a_stale_fault_flag_on_mqtt_without_a_device_leaves_the_heating_on(
    mqtt_rig: Rig, mqtt_client_mock: Any, indication: str
) -> None:
    """The OTGW firmware's entities written by hand in YAML have no device. The gateway reads a
    fault's details once and never after it clears (Q3.9), so a flag left on must not stop the
    heating: it counts only while the boiler's fault indication is on too."""
    rig = mqtt_rig
    read_back = await OtgwFirmware(rig.hass).start()
    assert er.async_get(rig.hass).async_get(read_back).device_id is None
    registry = er.async_get(rig.hass)
    low, fault = (
        registry.async_get_or_create(
            "binary_sensor", "mqtt", name, suggested_object_id=name
        ).entity_id
        for name in ("otgw_low_water", "otgw_fault")
    )
    rig.hass.states.async_set(low, "off")
    rig.hass.states.async_set(fault, indication)
    entry_options = options(rig.zones, **MQTT_PATH, gateway_id=None, confirmed_entity=read_back)
    entry_options["signals"] |= {
        Signal.LOW_PRESSURE_FAULT.value: low,
        Signal.FAULT_INDICATION.value: fault,
    }
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    await rig.advance(30)
    rig.hass.states.async_set(low, "on")
    await rig.advance(6 * 60.0)
    off = (f"{OTGW_TOP}/set/{OTGW_NODE}/chenable", "0")
    assert (off in published(mqtt_client_mock)) is (indication == "on")
    assert (rig.state("sensor", "control_state").state == "boiler_fault") is (indication == "on")


@pytest.mark.parametrize("asked", ["lowest", "last_setpoint"])
async def test_an_mqtt_hand_back_is_confirmed_by_the_thermostats_own_request(
    mqtt_rig: Rig, mqtt_client_mock: Any, asked: str
) -> None:
    """PB-10: the OTGW firmware over MQTT with an OpenTherm thermostat — after ``CS=0`` its
    ``TSet`` shows the thermostat's own request, never 0. A request at the lowest water
    temperature, or at the plugin's last setpoint, never leaves them: the release shows as the
    thermostat's request where its entity is mapped — confirmed, and nothing published again."""
    rig = mqtt_rig
    firmware = OtgwFirmware(rig.hass, thermostat=LOWEST if asked == "lowest" else EXPECTED)
    read_back = await firmware.start()
    rig.hass.states.async_set(
        THERMOSTAT_REQUEST, str(firmware.thermostat), {"unit_of_measurement": "°C"}
    )
    await start(
        rig,
        **MQTT_PATH,
        gateway_id=None,
        confirmed_entity=read_back,
        thermostat_setpoint_entity=THERMOSTAT_REQUEST,
    )
    await rig.switch(True)
    await rig.advance(60)
    await rig.switch(False)
    assert published(mqtt_client_mock)[-3:] == mqtt_hand_back(LOWEST)
    await rig.advance(10)
    assert not unit_of(rig).hand_back_owed
    count = len(published(mqtt_client_mock))
    await rig.advance(300)
    assert len(published(mqtt_client_mock)) == count  # no further publishes
    assert alarm(rig) == "off"


@pytest.mark.parametrize("mapped", ["not_mapped", "unknown", "standalone"])
async def test_an_unconfirmed_mqtt_hand_back_never_publishes_the_lowest_again(
    mqtt_rig: Rig, mqtt_client_mock: Any, mapped: str
) -> None:
    """PB-10, negative: the thermostat asks for the lowest, and its request is not mapped, reads
    unknown, or counts not (a stand-alone topology): the release does not show — owed, and
    retried every minute; once the hand-back's commands went through, each retry publishes
    ``CH=1`` and ``CS=0`` only, never ``CS=<lowest>`` over the thermostat again."""
    rig = mqtt_rig
    firmware = OtgwFirmware(rig.hass, thermostat=LOWEST)
    read_back = await firmware.start()
    extra: dict[str, Any] = {}
    if mapped != "not_mapped":
        shown = "unknown" if mapped == "unknown" else str(LOWEST)
        rig.hass.states.async_set(THERMOSTAT_REQUEST, shown, {"unit_of_measurement": "°C"})
        extra["thermostat_setpoint_entity"] = THERMOSTAT_REQUEST
    if mapped == "standalone":
        extra |= {"topology": "gateway_standalone"}
    await start(rig, **MQTT_PATH, gateway_id=None, confirmed_entity=read_back, **extra)
    await rig.switch(True)
    await rig.advance(60)
    await rig.switch(False)
    count = len(published(mqtt_client_mock))
    await rig.advance(180)
    retries = published(mqtt_client_mock)[count:]
    base = f"{OTGW_TOP}/set/{OTGW_NODE}"
    assert 2 <= len(retries) <= 6  # one retry a minute, two publishes each
    assert set(retries) == {(f"{base}/chenable", "1"), (f"{base}/ctrlsetpt", "0")}
    assert unit_of(rig).hand_back_owed


async def test_an_unconfirmed_gateway_hand_back_never_sends_the_lowest_again(rig: Rig) -> None:
    """PB-10 on opentherm_gw: ``CS=0`` taken but the release not shown (the gateway keeps the
    override): each retry sends ``CH=1`` and ``CS=0``, never ``CS=<lowest>`` again. A first
    attempt that failed is retried whole."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.ignore_release = True
    await rig.switch(False)
    assert rig.gateway.calls[-3:] == HAND_BACK
    count = len(rig.gateway.calls)
    await rig.advance(130)
    retries = rig.gateway.calls[count:]
    assert retries
    assert set(retries) == {("ch", True), ("setpoint", 0.0)}
    assert unit_of(rig).hand_back_owed


@pytest.mark.parametrize(
    ("answers", "first_refused"),
    [(True, False), (False, False), (True, True)],
    ids=["released", "firmware_offline", "first_part_refused"],
)
async def test_mqtt_hand_back_is_published_before_mqtt_stops(
    mqtt_rig: Rig,
    mqtt_client_mock: Any,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    answers: bool,
    first_refused: bool,
) -> None:
    """T-22: control through the OTGW firmware over Home Assistant's own MQTT, read back from an
    MQTT entity. When Home Assistant stops, V5's safe hand-back — the lowest water temperature,
    CH=1, then CS=0, one after another at once, none waiting for a read-back — reaches MQTT's
    client before the stop event, at which MQTT stops; its release, read back, leaves no
    hand-back owed. Negatives: the firmware offline — the broker takes the commands, nothing
    answers: the same three go out, and the hand-back stays owed for the next start; MQTT's
    client refusing the first part — the other two go out all the same, each whatever the others
    do, and the whole stays owed."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    rig = mqtt_rig
    hass = rig.hass
    firmware = OtgwFirmware(hass)
    read_back = await firmware.start()
    await start(rig, **MQTT_PATH, gateway_id=None, confirmed_entity=read_back)
    await rig.switch(True)
    await rig.advance(30)
    assert unit_of(rig).holding
    order: list[tuple[str, ...]] = []
    publish = mqtt_client_mock.publish.side_effect
    refuse = [f"{LOWEST:.1f}"] if first_refused else []

    def recorded(topic: str, payload: Any, *args: Any, **kwargs: Any) -> Any:
        text = payload.decode() if isinstance(payload, bytes) else str(payload)
        order.append(("publish", topic, text))
        if refuse and text == refuse[0]:
            refuse.clear()  # the client refuses this one message: no connection for it
            return type("Refused", (), {"mid": None, "rc": 4})()
        return publish(topic, payload, *args, **kwargs)

    mqtt_client_mock.publish.side_effect = recorded
    mqtt_client_mock.disconnect.side_effect = lambda *args, **kwargs: order.append(("disconnect",))
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, lambda _event: order.append(("stop",)))
    firmware.answers = answers
    if not answers:
        # The stop's short wait for a late report ends at once: nothing is going to answer.
        monkeypatch.setattr(control_module, "STOP_REPORT_WAIT_S", 0.0)
    await hass.async_stop()
    stop = order.index(("stop",))
    before = order[:stop]
    assert before[-3:] == [("publish", topic, payload) for topic, payload in mqtt_hand_back(LOWEST)]
    assert ("disconnect",) not in before
    assert [entry for entry in order[stop:] if entry[0] == "publish"] == []  # none after it
    owed = not answers or first_refused  # a part refused: the whole goes again next start
    assert stored_control(hass_storage, rig)["hand_back_pending"] is owed
    commands = [(f"{OTGW_TOP}/set/{OTGW_NODE}/{name}", value) for name, value in firmware.commands]
    if first_refused:
        assert commands[-2:] == mqtt_hand_back(LOWEST)[1:]  # the other two arrived
    else:
        assert commands[-3:] == mqtt_hand_back(LOWEST)
    if owed:
        found = issue(rig, "hand_back_owed")
        assert found is not None
        assert found.is_persistent
    else:
        assert hass.states.get(read_back).state == f"{firmware.thermostat:.2f}"
        assert issue(rig, "hand_back_owed") is None


async def test_a_failed_hand_back_is_retried_and_stays_shown(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(False)  # the hand-back fails
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    await rig.advance(30)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"  # kept
    rig.gateway.register()  # the gateway answers again
    await rig.advance(70)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # retried until it went through
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"


async def test_a_latch_survives_a_reload(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.forced = 60.0  # another controller
    await rig.advance(180)
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    count = len(rig.gateway.setpoints())
    await rig.advance(60)
    assert rig.state("binary_sensor", "control").state == "on"
    assert len(rig.gateway.setpoints()) == count  # still handed back: no fight after reload
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    rig.gateway.forced = None
    await rig.switch(False)
    await rig.switch(True)  # the user's off and on clears the latch
    assert rig.gateway.setpoints()[-1] == EXPECTED


async def test_a_steady_reading_that_is_reported_only_on_change_is_not_stale(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.flow_reported = False  # the flow stays at its value and is not reported again
    await rig.advance(20 * 60, step=30.0)
    assert rig.state("sensor", "control_state").state == "heating"
    gaps = [b - a for a, b in pairwise(rig.gateway.times[-30:])]
    assert gaps
    assert max(gaps) <= 40.0  # keep-alives went on


async def test_a_failed_write_is_retried_at_the_next_step(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    attempts: list[float] = []
    fail = {"left": 1}

    async def flaky(call: ServiceCall) -> None:
        attempts.append(datetime.now(UTC).timestamp())
        if fail["left"]:
            fail["left"] -= 1
            raise HomeAssistantError("gateway busy")
        rig.gateway.override = float(call.data["temperature"])
        rig.gateway.publish()

    rig.hass.services.async_register("opentherm_gw", "set_control_setpoint", flaky)
    await rig.advance(60)
    assert len(attempts) >= 2
    assert attempts[1] - attempts[0] <= 10.0  # not 30 s later
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"  # cleared again


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_timeout_hand_back_needs_expiring_writes(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="held",
        hand_back="timeout",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_timeout_needs_expiring_writes"
    assert number.writes == []


async def test_the_shutdown_hand_back_lets_the_next_shutdown_job_run(rig: Rig) -> None:
    from homeassistant.core import HassJob

    await start(rig)
    await rig.switch(True)
    ran: list[str] = []

    async def other_job() -> None:
        ran.append("other")

    rig.hass.async_add_shutdown_job(HassJob(other_job, "another integration's job"))
    await rig.hass.async_stop()
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert ran == ["other"]  # removing our job while Home Assistant ran the list skipped this


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_setpoint_entity_that_rejects_a_limit_blocks_control(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    rig.hass.states.async_set(
        number.entity_id, "50", {"unit_of_measurement": "°C", "min": 20, "max": 50}
    )
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="expiring",
        hand_back="value",
        hand_back_value=30,
        hand_back_value_effect="own_control",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)  # the hard maximum of 70 °C and "off" at 10 °C fall outside
    assert err.value.translation_key == "blocked_setpoint_outside_entity_range"
    assert number.writes == []


async def test_nothing_is_handed_back_twice_without_a_write_in_between(rig: Rig) -> None:
    hass = rig.hass
    await start(rig)
    await rig.switch(True)
    await rig.switch(False)
    assert rig.gateway.setpoints().count(0.0) == 1
    assert rig.entry is not None
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert rig.gateway.setpoints().count(0.0) == 1  # already handed back, nothing written since


@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_entity_hand_back_to_an_unavailable_target_is_retried_until_confirmed(
    rig: Rig,
) -> None:
    """Home Assistant would drop the call without an error: the hand-back is not taken for done,
    is shown, and goes out again once the entity is back — done only when the entity shows it."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    number.set_available(False)
    await rig.switch(False)
    assert number.writes == [EXPECTED]  # nothing reached the device
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    control = rig.entry.runtime_data.control
    assert control.stored()["hand_back_pending"]
    await rig.advance(60)
    assert number.writes == [EXPECTED]  # still away: still owed
    number.set_available(True)
    await rig.advance(60)
    assert number.writes == [EXPECTED, LOWEST, 50.0]  # the lowest, then the hand-back value
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert not control.stored()["hand_back_pending"]


def stored_control(hass_storage: dict[str, Any], rig: Rig) -> dict[str, Any]:
    """The control store, which the entry store's copy follows."""
    assert rig.entry is not None
    return hass_storage[control_key(rig.entry)]["data"]


async def test_the_controlling_marker_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Were Home Assistant to crash now, the next start must know the boiler was held — not only
    after the store's two-minute delay: in the control store, and in the entry store's copy,
    which a change of the hold is written to at once as well (V1, R2)."""
    await start(rig)
    await rig.switch(True)
    assert rig.gateway.setpoints() == [EXPECTED]
    assert stored_control(hass_storage, rig)["controlling"] is True
    assert rig.entry is not None
    main = hass_storage[f"{DOMAIN}.{rig.entry.entry_id}"]["data"]
    assert main["control"]["controlling"] is True
    assert main["control_store"] == 1


async def test_an_unclean_restart_hands_back_when_control_does_not_resume(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The last run held the boiler and ended without a hand-back (a crash, a power cut): control
    stays off now, so the boiler is handed back in full."""
    hass_storage[f"{DOMAIN}.previous"] = {}  # nothing else in the store matters
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"monitoring_since": 0.0, "control": {"controlling": True}},
    }
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.advance(20)
    assert rig.state("binary_sensor", "control").state == "off"
    assert rig.gateway.setpoints() == [LOWEST, 0.0]  # handed back, though control is off
    await rig.advance(20)
    assert rig.gateway.setpoints() == [LOWEST, 0.0]  # once
    assert entry.runtime_data.control.stored()["controlling"] is False


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_an_unclean_restart_with_control_on_hands_back_first_then_resumes(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    """The last run held the boiler and ended without a hand-back, and control is to stay on:
    what that run left is given back in full first, then control takes the boiler afresh."""
    await start_with_stored(rig, hass_storage, {"controlling": True, "enabled": True}, layout)
    await rig.advance(20)
    calls = rig.gateway.calls
    back = calls.index(("setpoint", 0.0))
    assert calls[back - 1] == ("ch", True)  # CH=1, then CS=0
    assert rig.gateway.setpoints()[-1] == EXPECTED  # then control again
    assert rig.state("binary_sensor", "control").state == "on"


async def test_a_write_reported_failed_is_still_handed_back(rig: Rig) -> None:
    """A write that timed out may still have reached the boiler: the next hand-back is not
    skipped as if nothing had been written."""
    await start(rig)
    await rig.switch(True)
    await rig.switch(False)
    assert rig.gateway.setpoints() == [EXPECTED, LOWEST, 0.0]
    rig.gateway.fail_after = True
    await rig.switch(True)  # setpoint and heating arrive; both calls report a failure
    assert rig.gateway.setpoints() == [EXPECTED, LOWEST, 0.0, EXPECTED]
    rig.gateway.fail_after = False
    await rig.switch(False)
    assert rig.gateway.setpoints()[-1] == 0.0


def issue(rig: Rig, key: str) -> ir.IssueEntry | None:
    assert rig.entry is not None
    return ir.async_get(rig.hass).async_get_issue(DOMAIN, f"{key}_{rig.entry.entry_id}")


async def owe_a_hand_back(rig: Rig) -> FakeNumber:
    """Control through a held entity has the boiler; then the entity goes away."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    number.set_available(False)
    return number


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_hand_back_value_the_entity_no_longer_takes_stays_owed(rig: Rig) -> None:
    """PB-22 (S-21), the review's probe: the held number's minimum rises to 10 while control
    holds it. The hand-back value 0 is not moved onto 10 — the boiler would keep a 10 °C
    setpoint, its heating enabled, with no alarm: the hand-back stays owed, with its alarm and
    issue. Once the number takes 0 again, the retry gives it and the debt is settled."""
    number = FakeNumber(rig.hass, attributes={"min": 0, "max": 90, "step": 0.5})
    number.register()
    await start(rig, **held_entity(number, hand_back_value=0))
    await rig.switch(True)
    assert number.writes
    number.attributes = {"min": 10, "max": 90, "step": 0.5}
    number.publish(number.value)
    await rig.switch(False)
    await rig.advance(10)
    assert 10.0 not in number.writes
    assert number.writes[-1] == LOWEST  # the lowest went; the release did not
    assert unit_of(rig).hand_back_owed
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert issue(rig, "hand_back_owed") is not None
    number.attributes = {"min": 0, "max": 90, "step": 0.5}
    number.publish(number.value)
    await rig.advance(70)
    assert number.writes[-1] == 0.0
    await rig.advance(10)
    assert not unit_of(rig).hand_back_owed
    assert issue(rig, "hand_back_owed") is None


@pytest.mark.usefixtures("low_setpoint_off")
async def test_no_control_while_a_hand_back_is_owed_keeps_handing_back(rig: Rig) -> None:
    """Control removed from the options while its hand-back cannot get through: a unit that only
    hands back keeps retrying, with a repair issue, until the boiler has it."""
    number = await owe_a_hand_back(rig)
    assert rig.entry is not None
    options = {k: v for k, v in rig.entry.options.items() if k != "control"}
    rig.hass.config_entries.async_update_entry(rig.entry, options=options)
    await rig.hass.async_block_till_done()
    assert number.writes == [EXPECTED]  # the hand-back on unload did not get through
    assert issue(rig, "hand_back_owed") is not None
    number.set_available(True)
    await rig.advance(70)
    assert number.writes == [EXPECTED, LOWEST, 50.0]
    await rig.advance(10)
    assert issue(rig, "hand_back_owed") is None


async def test_a_broken_control_section_keeps_monitoring_and_handing_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Options that a newer check refuses do not stop the entry: the monitor runs, control is
    left out with a repair issue, and a hand-back still owed goes out."""
    number = FakeNumber(rig.hass)
    number.register()
    taken_with = held_entity(number) | {"curve": {"design_outdoor": -15, "design_flow": 55}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones, **taken_with) | {"control": {"write_path": "carrier_pigeon"}},
    )
    entry.add_to_hass(rig.hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": 0.0,
            "control": {"controlling": True, "taken_with": taken_with},
        },
    }
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    assert issue(rig, "control_options_invalid") is not None
    await rig.advance(20)
    assert number.writes == [DEFAULT_LOWEST, 50.0]  # handed back through what took the boiler
    assert issue(rig, "hand_back_owed") is None


@pytest.mark.usefixtures("low_setpoint_off")
async def test_changing_the_write_path_is_refused_while_a_hand_back_is_owed(rig: Rig) -> None:
    await owe_a_hand_back(rig)
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"write_path": "opentherm_gw"}
    )
    assert flow["errors"] == {"write_path": "hand_back_pending"}


def control_answer(answer: dict[str, Any]) -> dict[str, Any]:
    """The first control step's answer: the "Boiler interface" item's answers are its own now
    (I8, decision D2), and the read-backs boiler signals (I8.5b, D3) — stored in the rig's
    options already."""
    from custom_components.vtherm_smart_boiler.const import READ_BACK_SIGNALS
    from custom_components.vtherm_smart_boiler.control_config import INTERFACE_CONTROL_KEYS

    dropped = {*INTERFACE_CONTROL_KEYS, *READ_BACK_SIGNALS.values()}
    return {key: value for key, value in answer.items() if key not in dropped}


async def _signals_step(rig: Rig, read_backs: dict[str, Any]) -> Any:
    """I8.5b (decision D3): the read-backs, by the control options' names, answered as boiler
    signals in the options — an emptied one unmapped, every other signal as stored."""
    from custom_components.vtherm_smart_boiler.const import READ_BACK_SIGNALS

    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "signals"}
    )
    shown = {str(marker) for marker in flow["data_schema"].schema}
    stored = {**rig.entry.options["signals"], "weather": rig.entry.options.get("weather")}
    given = {key: value for key, value in stored.items() if key in shown and value}
    for signal, key in READ_BACK_SIGNALS.items():
        if key in read_backs:
            assert signal in shown, signal
            given.pop(signal, None)
            if read_backs[key]:
                given[signal] = read_backs[key]
    return await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], given)


async def _first_control_step(rig: Rig, answer: dict[str, Any]) -> Any:
    """The control device's item answered — then the next control item opens as the chain's
    next form did (I8, decision H): the curve on a gateway path."""
    assert rig.entry is not None
    options = rig.hass.config_entries.options
    flow = await options.async_init(rig.entry.entry_id)
    flow = await options.async_configure(flow["flow_id"], {"next_step_id": "control"})
    if flow.get("step_id") != "control":
        return flow  # the connection decides the path: the step asks nothing (I8.5b)
    flow = await options.async_configure(flow["flow_id"], control_answer(answer))
    return await control_chain.after(options, flow, "control")


async def _interface_step(rig: Rig, answer: dict[str, Any]) -> Any:
    """I8 (decision D2): the "Boiler interface" item answered in the options."""
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "interface"}
    )
    return await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], answer)


GATEWAY_ANSWER = {"write_path": "opentherm_gw"}


async def test_the_gateways_read_back_cannot_change_while_a_hand_back_is_owed(rig: Rig) -> None:
    """R6, H2 with C1: the gateway's read-back tells whether a hand-back through it got there.
    Re-picked while one is owed — the gateway away, its entity unavailable — the next hand-back
    would count as made with nothing arriving, and a CH=0 left in the gateway would mask the
    thermostat for good."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    # I8.5b (decision D3): the read-back is a boiler signal, guarded on that step.
    flow = await _signals_step(rig, {"confirmed_entity": other})
    assert flow["errors"] == {"ch_setpoint": "hand_back_pending"}
    assert rig.entry is not None
    assert rig.entry.options["signals"]["ch_setpoint"] == CONFIRMED
    flow = await _signals_step(rig, {"confirmed_entity": CONFIRMED})
    assert flow["type"] is FlowResultType.MENU  # the same read-back goes on
    flow = await _first_control_step(rig, GATEWAY_ANSWER)
    assert flow["step_id"] == "control_curve"  # (I8: the gateway is the interface's)


async def test_the_gateways_read_back_cannot_change_while_control_holds_the_boiler(
    rig: Rig,
) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _signals_step(rig, {"confirmed_entity": other})  # a boiler signal (I8.5b)
    assert flow["errors"] == {"ch_setpoint": "control_holds_boiler"}


@pytest.mark.usefixtures("low_setpoint_off")
@pytest.mark.parametrize("key", ["confirmed_entity", "ch_confirmed_entity"])
async def test_the_entity_paths_read_backs_cannot_change_while_a_hand_back_is_owed(
    rig: Rig, key: str
) -> None:
    """PB-09, the review's probe: a held setpoint goes away at the hand-back, which is owed.
    Another read-back — one that shows the hand-back value, say — would count the hand-back as
    made while the device got nothing: the change is refused with the reason. Negative: the
    same read-backs go on to the next step."""
    number = await owe_a_hand_back(rig)
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    if key == "confirmed_entity":
        other = "sensor.somewhere_else_temperature"
        rig.hass.states.async_set(other, "50.0", {"unit_of_measurement": "°C"})
    else:
        other = "binary_sensor.somewhere_else"
        rig.hass.states.async_set(other, "on")
    # I8.5b (decision D3): the read-backs are boiler signals, guarded on that step.
    signal = {"confirmed_entity": "ch_setpoint", "ch_confirmed_entity": "ch_enabled"}[key]
    flow = await _signals_step(rig, {key: other})
    assert flow["errors"] == {signal: "hand_back_pending"}
    assert rig.entry is not None
    assert rig.entry.options["signals"]["ch_setpoint"] == number.entity_id
    flow = await _signals_step(rig, {})
    assert flow["type"] is FlowResultType.MENU
    flow = await _first_control_step(rig, {"write_path": "entity"})
    assert flow["step_id"] == "control_entity"


ENTITY_STEP_ANSWER = {
    "write_type": "held",
    "ch_write_type": "unknown",
    "hand_back": "value",
    "hand_back_value": 50,
    "hand_back_value_effect": "own_control",
    "hand_back_entity_write_type": "unknown",
}


@pytest.mark.usefixtures("low_setpoint_off")
@pytest.mark.parametrize("owed", [True, False], ids=["owed", "holding"])
@pytest.mark.parametrize(
    ("change", "refused"),
    [
        ({"write_type": "expiring"}, True),
        ({"ch_write_type": "expiring"}, True),
        ({"hand_back_timeout_min": 30}, False),  # judges the timeout method only
        ({}, False),
    ],
    ids=["write_type", "ch_write_type", "timeout_of_another_method", "unchanged"],
)
async def test_the_write_types_cannot_change_while_a_hand_back_is_owed(
    rig: Rig, owed: bool, change: dict[str, Any], refused: bool
) -> None:
    """PB-09: the write types judge the release — a held value must show the hand-back value,
    an expiring one only leave the plugin's — so they are fixed while a hand-back is owed or
    control holds the boiler, whose hand-back the new options would make. A heating switch is
    set up, so its write type is asked (I8, decision H1)."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    await start(rig, **held_entity(number, ch_entity=switch.entity_id, ch_write_type="held"))
    await rig.switch(True)
    if owed:
        number.set_available(False)
        await rig.switch(False)
        assert unit_of(rig).hand_back_owed
    else:
        assert unit_of(rig).holding
    answer = {"write_path": "entity", "confirmed_entity": number.entity_id}
    flow = await _first_control_step(rig, answer)
    heating = {"ch_entity": switch.entity_id, "ch_write_type": "held"}
    answer = ENTITY_STEP_ANSWER | {"setpoint_entity": number.entity_id} | heating | change
    flow = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], answer)
    if refused:
        reason = "hand_back_pending" if owed else "control_holds_boiler"
        assert flow["errors"] == {"base": reason}
    else:
        assert flow["step_id"] == "control_curve"


async def test_with_control_taken_out_the_read_back_may_change(rig: Rig) -> None:
    """PB-09's negative (I8.5b): "no control" chosen first in the same edit, the read-back — a
    boiler signal — may change while control holds the boiler: the hand-back goes through what
    took it."""
    await set_up(rig, add_entry(rig, options(rig.zones) | {"level": "advanced"}))
    await rig.switch(True)
    await rig.advance(20)
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _first_control_step(rig, {"write_path": "none"})
    assert flow["type"] == "menu"
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "signals"}
    )
    assert rig.entry is not None
    shown = {str(marker) for marker in flow["data_schema"].schema}
    given = {k: v for k, v in rig.entry.options["signals"].items() if k in shown}
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], given | {"ch_setpoint": other}
    )
    assert flow["type"] == "menu"


@pytest.mark.usefixtures("low_setpoint_off")
@pytest.mark.parametrize("connection", [False, True], ids=["before_the_question", "connection"])
async def test_a_write_type_changed_before_a_hand_back_was_owed_is_refused_at_the_save(
    rig: Rig, connection: bool
) -> None:
    """P-12: the write type changed while nothing was owed; owed before the save, the save is
    refused, its reason on the first control form — the control step's where it asks the path,
    else the writable-entity step's: the connection decides the path, and the control step asks
    nothing (I8.5b). Nothing is saved."""
    number = FakeNumber(rig.hass)
    number.register()
    stored = options(rig.zones, **held_entity(number))
    if connection:
        stored["boiler"] |= {"connection": "other_entity", "control_mode": "full"}
    await set_up(rig, add_entry(rig, stored))
    flow = await _first_control_step(rig, {"write_path": "entity"})
    assert flow["step_id"] == "control_entity"
    answer = ENTITY_STEP_ANSWER | {"setpoint_entity": number.entity_id, "write_type": "expiring"}
    flow = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], answer)
    chained = control_chain.chained(rig.hass.config_entries.options)
    flow = await chained(flow["flow_id"], CURVE_ANSWER)
    if flow.get("step_id") == "control_alarms":
        flow = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], {})
    assert flow["type"] == "menu"
    await rig.switch(True)
    number.set_available(False)
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    flow = await _saved(rig, flow)
    assert flow["step_id"] == ("control_entity" if connection else "control")
    assert flow["errors"] == {"base": "hand_back_pending"}
    assert rig.entry is not None
    assert rig.entry.options["control"]["write_type"] == "held"


async def test_the_device_timeout_and_the_lowest_are_fixed_while_a_hand_back_is_owed(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """PB-09 with decision 5: a timeout hand-back is judged from the device's own timeout and
    against the lowest it wrote first — both fixed while it is owed (here an entry not running,
    its store owing it). Negative: the same values go on."""
    number = FakeNumber(rig.hass)
    number.register()
    section = held_entity(number, write_type="expiring", hand_back="timeout")
    # Without the gateway path's id, which the flow drops for the entity path.
    section |= {"hand_back_timeout_min": 5, "hard_min": LOWEST, "gateway_id": None}
    for key in ("hand_back_value", "hand_back_value_effect"):
        del section[key]
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **section)
    )
    entry.add_to_hass(rig.hass)  # never set up
    rig.entry = entry
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": 0.0,
            "control": {"hand_back_pending": True, "taken_with": dict(entry.options["control"])},
        },
    }
    configure = control_chain.chained(rig.hass.config_entries.options)
    answer = {"write_path": "entity", "confirmed_entity": number.entity_id}
    flow = await _first_control_step(rig, answer)
    step = ENTITY_STEP_ANSWER | {"setpoint_entity": number.entity_id, "write_type": "expiring"}
    step |= {"hand_back": "timeout"}
    for key in ("hand_back_value", "hand_back_value_effect"):
        del step[key]
    refused = await configure(flow["flow_id"], step | {"hand_back_timeout_min": 10})
    assert refused["errors"] == {"base": "hand_back_pending"}
    flow = await configure(flow["flow_id"], step | {"hand_back_timeout_min": 5})
    assert flow["step_id"] == "control_curve"
    refused = await configure(flow["flow_id"], CURVE_ANSWER | {"hard_min": 30})
    assert refused["errors"] == {"hard_min": "hand_back_pending"}
    flow = await configure(flow["flow_id"], CURVE_ANSWER | {"hard_min": LOWEST})
    flow = await _through_alarms(rig, flow)
    assert flow["type"] == "create_entry"  # the save finds nothing changed that judges it


async def test_the_lowest_may_change_while_control_holds_the_boiler(rig: Rig) -> None:
    """PB-09: with nothing owed, the lowest water temperature stays open while control holds
    the boiler — the hand-back made after the change writes the new lowest first and is judged
    by it."""
    integrations_running(rig)
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert unit_of(rig).holding
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": CONFIRMED})
    configure = control_chain.chained(rig.hass.config_entries.options)
    assert flow["step_id"] == "control_curve"
    flow = await configure(flow["flow_id"], CURVE_ANSWER | {"hard_min": 30})
    assert not flow.get("errors")
    flow = await _through_alarms(rig, flow)
    assert flow["type"] == "create_entry"  # the save, too, leaves it open while holding
    await rig.hass.async_block_till_done()
    assert rig.entry is not None
    assert rig.entry.options["control"]["hard_min"] == 30


async def test_a_save_refused_on_the_gateway_path_shows_on_the_curve(rig: Rig) -> None:
    """P-12 with I8 (decision H): the lowest changed while control held the boiler, then a
    hand-back owed before the save — the save is refused; the gateway's path has no device
    form, so the reason shows on the curve's, where the lowest is. Nothing is saved."""
    integrations_running(rig)
    stored = options(rig.zones)
    stored["boiler"] |= {"connection": "opentherm_gw", "control_mode": "full"}
    await set_up(rig, add_entry(rig, stored))
    await rig.switch(True)
    await rig.advance(20)
    assert rig.entry is not None
    manager = rig.hass.config_entries.options
    flow = await manager.async_init(rig.entry.entry_id)
    assert "control" not in flow["menu_options"]  # the gateway's path asks no device
    flow = await manager.async_configure(flow["flow_id"], {"next_step_id": "control_curve"})
    flow = await manager.async_configure(flow["flow_id"], CURVE_ANSWER | {"hard_min": 30})
    assert flow["type"] is FlowResultType.MENU
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    flow = await _saved(rig, flow)
    assert (flow["step_id"], flow["errors"]) == ("control_curve", {"base": "hand_back_pending"})
    assert rig.entry.options["control"].get("hard_min") != 30


@pytest.mark.parametrize(("hard_min", "refused"), [(45, True), (35, False)])
async def test_the_lowest_above_the_circuits_maximum_is_refused(
    rig: Rig, hard_min: int, refused: bool
) -> None:
    """PB-26 with I8 (decision F2): the circuit's maximum, 40 °C, is the highest water
    temperature: a lowest of 45 °C cannot pass the curve step — the hand-back would send 45
    first, and control could never give it; the design flow between the two is refused. A
    lowest below the maximum, with the design flow at it, passes."""
    integrations_running(rig)
    await set_up(rig, add_entry(rig, with_circuit(rig, {"max_flow": 40})))
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": CONFIRMED})
    configure = control_chain.chained(rig.hass.config_entries.options)
    curve = CURVE_ANSWER | {"design_flow": 40, "hard_min": hard_min}
    flow = await configure(flow["flow_id"], curve)
    if refused:
        assert flow["errors"] == {"hard_min": "hard_min_not_below_design_flow"}
    else:
        assert not flow.get("errors")


async def test_an_entry_that_is_not_running_is_guarded_by_its_store(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """R6, H2 with C1: with the entry not running — its setup failed, say — the options are
    still open, and the next start makes the hand-back the last run left owed through what they
    say then. The store tells the guard what is owed; "no control" stays possible."""
    stored = options(rig.zones)
    # As the entry's migration leaves it (I8.5b): the read-back a boiler signal.
    stored["signals"]["ch_setpoint"] = stored["control"].pop("confirmed_entity")
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=stored)
    entry.add_to_hass(rig.hass)  # never set up
    rig.entry = entry
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": 0.0,
            "control": {"hand_back_pending": True, "taken_with": dict(entry.options["control"])},
        },
    }
    number = FakeNumber(rig.hass)
    number.register()
    flow = await _first_control_step(
        rig,
        {"write_path": "entity", "confirmed_entity": number.entity_id},
    )
    assert flow["errors"] == {"write_path": "hand_back_pending"}
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _signals_step(rig, {"confirmed_entity": other})
    assert flow["errors"] == {"ch_setpoint": "hand_back_pending"}
    flow = await _first_control_step(rig, {"write_path": "none"})
    flow = await _saved(rig, flow)
    assert flow["type"] == "create_entry"


async def test_a_late_confirmation_leaves_a_session_that_has_the_boiler_alone(rig: Rig) -> None:
    """R6, C7: the user confirmed an owed hand-back by hand after control had taken the boiler
    again. The session's hold stays known — a crash must not forget that the boiler has a
    value of ours — and its own hand-back is still made at the end."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.entry is not None
    control = rig.entry.runtime_data.control
    assert control.holding
    await control.async_release_owed_hand_back()
    assert control.holding  # at once, not only after the next write sets it again
    assert control.stored()["controlling"] is True
    await rig.switch(False)
    assert rig.gateway.calls[-3:] == HAND_BACK


@pytest.mark.usefixtures("low_setpoint_off")
async def test_choosing_no_control_while_a_hand_back_is_owed_keeps_handing_back(
    rig: Rig,
) -> None:
    """In the options, "no control" is allowed with a hand-back still owed — it asks for less,
    not for another device — and the hand-back is still made once its target is back, with a
    repair issue until then."""
    number = await owe_a_hand_back(rig)
    await rig.switch(False)
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"write_path": "none"}
    )
    flow = await _saved(rig, flow)
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    # The interface's answers stay (I8, decision D2); control is taken out.
    assert "write_path" not in rig.entry.options.get("control", {})
    assert issue(rig, "hand_back_owed") is not None
    number.set_available(True)
    await rig.advance(70)
    assert number.writes[-1] == 50.0
    await rig.advance(10)
    assert issue(rig, "hand_back_owed") is None


async def test_clearing_the_heating_switch_is_refused_while_a_hand_back_is_owed(
    rig: Rig,
) -> None:
    """H2: the frontend leaves a cleared optional field out of the answer, so an owed
    hand-back's heating switch must not be dropped just because it is absent."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(
        rig.hass, "input_boolean", {"input_boolean": {"fake_ch": {}}}
    )
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, ch_entity="input_boolean.fake_ch", ch_write_type="held"))
    await rig.switch(True)
    number.set_available(False)
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"],
        {"write_path": "entity"},
    )
    assert flow["step_id"] == "control_entity"
    unchanged = {
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "ch_write_type": "held",
        "hand_back": "value",
        "hand_back_value": 50,
        "hand_back_value_effect": "own_control",
    }  # everything as it is, the heating switch cleared (left out)
    flow = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], unchanged)
    assert flow["errors"] == {"base": "hand_back_pending"}
    assert rig.entry.options["control"]["ch_entity"] == "input_boolean.fake_ch"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_owed_hand_back_can_be_settled_by_hand(rig: Rig) -> None:
    """C7: the device a hand-back is owed to is gone for good. A fixable repair issue lets the
    user say they returned the boiler to its own control by hand: retrying stops, and the
    options accept another device — deleting the entry, and a year of summaries, is no longer
    the only way out."""
    from homeassistant.components.repairs import DOMAIN as REPAIRS
    from homeassistant.setup import async_setup_component

    number = await owe_a_hand_back(rig)
    await rig.switch(False)  # the hand-back fails: the setpoint entity is unavailable
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert found.is_fixable
    assert await async_setup_component(rig.hass, REPAIRS, {})
    manager = rig.hass.data[REPAIRS]["flow_manager"]
    flow = await manager.async_init(DOMAIN, data={"issue_id": found.issue_id})
    assert flow["step_id"] == "confirm"
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    await rig.advance(70)
    assert issue(rig, "hand_back_owed") is None
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert number.writes == [EXPECTED]  # no more retries
    assert rig.entry is not None
    assert not rig.entry.runtime_data.control.hand_back_owed
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"],
        {"write_path": "opentherm_gw"},
    )
    # Another device, accepted: no hand-back holds it; only the interface's answers for the new
    # path are still to give (I8, decision D2).
    assert flow["errors"] == {"base": "interface_not_answered"}


async def test_a_session_that_retakes_the_boiler_still_owes_the_switch_it_left_off(
    rig: Rig,
) -> None:
    """C2: session one turned the held heating switch off (no demand), and its hand-back could
    not reach it. Session two takes the boiler with a setpoint, which settles the owed
    hand-back, but cannot write the switch. Its own hand-back must still turn the switch on —
    the boiler cannot heat while it is off."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    await start(rig, **held_entity(number, ch_entity=switch.entity_id, ch_write_type="held"))
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.switch(True)
    await rig.advance(20)
    assert switch.on is False  # no demand: heating off
    switch.set_available(False)
    await rig.switch(False)  # the hand-back cannot turn the switch back on
    assert rig.entry is not None
    assert rig.entry.runtime_data.control.hand_back_owed
    await rig.switch(True)  # session two: the setpoint goes through, the switch does not
    await rig.advance(20)
    switch.set_available(True)  # back — and still off
    await rig.switch(False)
    await rig.advance(10)
    assert switch.on is True


@pytest.mark.usefixtures("low_setpoint_off")
async def test_what_control_writes_to_cannot_change_while_it_holds_the_boiler(rig: Rig) -> None:
    """C2: the hand-back must go through the device that has the boiler. Changed while control
    holds it, a failed hand-back to the old device would be retried through the new one — and
    the old one never given back. Switched off first, the old device gets it."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"],
        {"write_path": "entity"},
    )
    other = {
        "setpoint_entity": "input_number.another_boiler_flow",
        "write_type": "held",
        "ch_write_type": "held",
        "hand_back": "value",
        "hand_back_value": 50,
        "hand_back_value_effect": "own_control",
    }
    rig.hass.states.async_set(other["setpoint_entity"], "50", {"unit_of_measurement": "°C"})
    result = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], other)
    assert result["errors"] == {"base": "control_holds_boiler"}
    await rig.switch(False)  # given back through the device that has it
    result = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], other)
    assert result["step_id"] == "control_curve"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_disabling_the_entry_with_a_hand_back_owed_keeps_the_issue(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """H4: the entry disabled while its hand-back cannot get through: the alarm goes with the
    entities and nothing retries, so the repair issue outlives it — and its fix settles the
    stored hand-back."""
    from homeassistant.components.repairs import DOMAIN as REPAIRS
    from homeassistant.config_entries import ConfigEntryDisabler
    from homeassistant.setup import async_setup_component

    await owe_a_hand_back(rig)
    assert rig.entry is not None
    await rig.hass.config_entries.async_set_disabled_by(
        rig.entry.entry_id, ConfigEntryDisabler.USER
    )
    await rig.hass.async_block_till_done()
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert found.is_persistent
    assert found.is_fixable
    assert stored_control(hass_storage, rig)["hand_back_pending"] is True
    assert await async_setup_component(rig.hass, REPAIRS, {})
    manager = rig.hass.data[REPAIRS]["flow_manager"]
    flow = await manager.async_init(DOMAIN, data={"issue_id": found.issue_id})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    stored = stored_control(hass_storage, rig)
    assert (stored["hand_back_pending"], stored["controlling"]) == (False, False)


async def test_options_that_cannot_be_read_still_tell_of_a_held_boiler(
    hass: HomeAssistant, hass_storage: dict[str, Any], zones: FakeZones
) -> None:
    """H5: the last run held the boiler, and the options no longer parse (a check a later
    version tightened, a hand edit): no unit can hand back, so the user is told, for good."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(zones) | {"boiler": {"class": "no such class"}},
    )
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"monitoring_since": 0.0, "control": {"controlling": True}},
    }
    assert not await hass.config_entries.async_setup(entry.entry_id)
    found = ir.async_get(hass).async_get_issue(DOMAIN, f"hand_back_owed_{entry.entry_id}")
    assert found is not None
    assert found.is_persistent


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_value_hand_back_echoed_on_a_later_tick_is_done_then(rig: Rig) -> None:
    """T6: ESPHome and MQTT entities show a new value when the device next reports. The value
    hand-back is owed until the entity shows it, and done at the tick it does — without the
    alarm, and without writing it again."""
    number = FakeNumber(rig.hass, echo_later=True)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    number.publish(number.value)
    await rig.switch(False)
    assert number.writes[-1] == 50.0  # the hand-back value, not shown yet
    assert rig.entry is not None
    assert rig.entry.runtime_data.control.hand_back_owed
    number.publish(number.value)  # the device reports
    await rig.advance(10)
    assert not rig.entry.runtime_data.control.hand_back_owed
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert number.writes.count(50.0) == 1


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_switch_that_stays_on_is_no_hand_back(rig: Rig) -> None:
    """T6: the switch hand-back counts once the switch shows "off"; one that stays on is sent
    again every minute and shown as failed."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", stuck_on=True)
    switch.register()
    control = {k: v for k, v in held_entity(number).items() if not k.startswith("hand_back")} | {
        "hand_back": "switch",
        "hand_back_entity": switch.entity_id,
        "hand_back_entity_write_type": "held",
    }
    await start(rig, **control)
    await rig.switch(True)
    await rig.switch(False)
    assert switch.writes[-1] is False  # sent...
    assert switch.on  # ...and not taken
    await rig.advance(70)
    assert switch.writes.count(False) >= 2  # sent again
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"


@pytest.mark.parametrize("unload", ["works", "raises"])
async def test_a_setup_that_fails_after_its_platforms_keeps_the_registry(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, unload: str
) -> None:
    """PB-07: a setup that fails after its platforms were set up — here telling VT of the
    plugin — unloads them: their entities go, their registry entries stay. Home Assistant's
    reload then sets them up again for the new run, and the user's names and disabled flags —
    control's state's included — are kept, not removed as stale. Negative: an unload that
    raises is logged and the setup still fails cleanly; the platforms left set up then do not
    set up again, so they say nothing is stale: the registry entries are kept all the same."""
    from custom_components.vtherm_smart_boiler import feature_manager

    await start(rig)
    assert rig.entry is not None
    entry = rig.entry
    registry = er.async_get(rig.hass)
    switch_id = rig.entity("binary_sensor", "control")
    state_id = rig.entity("sensor", "control_state")
    registry.async_update_entity(state_id, name="Boiler control")
    registry.async_update_entity(switch_id, disabled_by=er.RegistryEntryDisabler.USER)
    await rig.advance(40)  # Home Assistant reloads the entry 30 s after a disable
    attach = feature_manager.async_attach

    unload_platforms = rig.hass.config_entries.async_unload_platforms

    async def unload_fails(*_args: Any) -> bool:
        raise RuntimeError("the platforms could not be unloaded")

    def fail(*_args: Any) -> None:
        if unload == "raises":  # only the failed setup's own unload
            monkeypatch.setattr(rig.hass.config_entries, "async_unload_platforms", unload_fails)
        raise RuntimeError("VT could not be told")

    monkeypatch.setattr(feature_manager, "async_attach", fail)
    assert not await rig.hass.config_entries.async_reload(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    if unload == "raises":
        assert "Could not unload the platforms after a failed setup" in caplog.text
        monkeypatch.setattr(rig.hass.config_entries, "async_unload_platforms", unload_platforms)
    else:
        unloaded = rig.hass.states.get(state_id)
        assert unloaded is not None
        assert unloaded.attributes.get("restored") is True
    monkeypatch.setattr(feature_manager, "async_attach", attach)
    assert await rig.hass.config_entries.async_reload(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    named = registry.async_get(state_id)
    assert named is not None
    assert named.name == "Boiler control"
    switch = registry.async_get(switch_id)
    assert switch is not None
    assert switch.disabled_by is er.RegistryEntryDisabler.USER
    if unload == "raises":
        return  # the entities set up before stay as they were until a restart
    back = rig.hass.states.get(state_id)
    assert back is not None
    assert not back.attributes.get("restored")


async def test_the_control_switch_of_an_earlier_version_goes_from_the_registry(
    rig: Rig, hass_ws_client: Any
) -> None:
    """I11.3 (the test session's review of 2026-11-22): an entry updated from a version with the
    Control switch has its old registry entry — the switch domain, the same unique ID as the new
    binary sensor's. It goes as stale: the registry tells entities apart by domain, so a stale
    one is judged by its domain and unique ID together; the page finds the binary sensor."""
    from .test_websocket import connect

    entry = add_entry(rig, options(rig.zones))
    registry = er.async_get(rig.hass)
    old = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{entry.entry_id}_control",
        config_entry=entry,
        suggested_object_id="boiler_control_experimental",
    )
    await set_up(rig, entry)
    assert registry.async_get(old.entity_id) is None
    state = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_control")
    assert state is not None
    assert "blockers" in rig.state("binary_sensor", "control").attributes
    client = await connect(rig.hass, hass_ws_client)
    view = (await client.ask("installation"))["result"]
    assert view["entities"]["control"] == state


async def test_a_platform_that_fails_its_setup_keeps_its_registry_entries(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PB-07: one platform raising in its own setup — Home Assistant logs it and the entry stays
    loaded: that platform never said what is stale, so its registry entries stay; the others
    are set up as before."""
    from custom_components.vtherm_smart_boiler import switch as switch_platform

    await start(rig)
    assert rig.entry is not None
    switch_id = rig.entity("switch", "sidebar_page")

    async def fail(*_args: Any) -> None:
        raise RuntimeError("the switch could not be set up")

    monkeypatch.setattr(switch_platform, "async_setup_entry", fail)
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert rig.entry.state is ConfigEntryState.LOADED
    assert er.async_get(rig.hass).async_get(switch_id) is not None
    assert rig.state("sensor", "control_state") is not None


@pytest.mark.usefixtures("low_setpoint_off")
async def test_removing_the_entry_with_a_hand_back_owed_raises_a_repair_issue(rig: Rig) -> None:
    await owe_a_hand_back(rig)
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    await rig.hass.config_entries.async_remove(entry_id)
    await rig.hass.async_block_till_done()
    issues = ir.async_get(rig.hass)
    assert issues.async_get_issue(DOMAIN, f"hand_back_owed_after_removal_{entry_id}") is not None


async def test_an_otgw_hand_back_waits_for_the_gateway_to_be_back(rig: Rig) -> None:
    """C1: without its gateway, opentherm_gw's services return without an error and nothing
    arrives (pyotgw drops the command). A hand-back made then is not done: it is shown as
    failed, kept, and sent again once the gateway is back — a CH=0 left in the gateway would
    otherwise mask the thermostat for good."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway.override == EXPECTED
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)  # the user switches control off during the outage
    assert ("setpoint", 0.0) in rig.gateway.lost  # tried, and lost
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    await rig.advance(180)
    assert rig.gateway.override == EXPECTED  # nothing has reached the gateway
    rig.gateway.connected = True
    await rig.advance(70)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert rig.gateway.override is None
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"


async def test_an_otgw_hand_back_does_not_count_on_a_gateway_that_reported_nothing(
    rig: Rig,
) -> None:
    """R6, C1: on a lost connection pyotgw resets its status and reports it. Written while the
    connection still counted, the gateway's entities stay available with no value — then a
    hand-back must not count either: kept, shown, and sent again once the gateway reports."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.gateway.reset_shown = True
    rig.live()
    assert rig.hass.states.get(CONFIRMED).state == "unknown"
    await rig.switch(False)
    assert ("setpoint", 0.0) in rig.gateway.lost
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    rig.gateway.connected = True
    await rig.advance(70)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert rig.gateway.override is None
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"


async def test_an_otgw_hand_back_clears_the_heating_override(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(310)  # the next decision: no demand, heating off
    assert ("ch", False) in rig.gateway.calls
    await rig.switch(False)
    assert rig.gateway.calls[-3:] == HAND_BACK


async def settle(task: asyncio.Future[Any] | None = None, rounds: int = 200) -> bool:
    """Let the loop run a while without waiting on anything that may hang; whether ``task`` is
    done by then."""
    for _ in range(rounds):
        if task is not None and task.done():
            return True
        await asyncio.sleep(0)
    return task is not None and task.done()


async def test_a_stop_during_a_slow_step_hands_back_at_once(rig: Rig) -> None:
    """Home Assistant stops while a step waits on a slow gateway: the hand-back cancels the step
    rather than waiting for it."""
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    control = rig.entry.runtime_data.control
    rig.gateway.block = asyncio.Event()
    rig.freezer.tick(30)
    rig.live()
    async_fire_time_changed(rig.hass)  # the keep-alive: its call hangs
    await settle(rounds=50)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    stop = asyncio.ensure_future(control.async_stop())
    done = await settle(stop)
    rig.gateway.block.set()
    await stop
    assert done, "the hand-back waited for the slow step"
    assert rig.gateway.calls[-3:] == HAND_BACK


async def test_a_stop_that_cancels_a_hand_back_makes_its_own(rig: Rig) -> None:
    """C3: control is switched off and its hand-back hangs on a slow gateway when Home Assistant
    stops. The stop cancels that step; it must hand back itself, not take it for done."""
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    control = rig.entry.runtime_data.control
    rig.gateway.block_hand_back = asyncio.Event()
    off = asyncio.ensure_future(control.async_set_enabled(False))
    await settle(rounds=50)
    assert rig.gateway.calls[-1] == ("ch", True)  # the hand-back's first call hangs
    stop = asyncio.ensure_future(control.async_stop())
    assert await settle(stop), "the stop waited for the slow hand-back"
    await off
    assert rig.gateway.calls[-3:] == HAND_BACK


async def test_a_home_assistant_stop_waits_for_an_unloads_hand_back(rig: Rig) -> None:
    """PB-36: Home Assistant stops while an unload's hand-back hangs on a slow gateway: the
    shutdown job is still there and waits for it, so the hand-back is made before the stop goes
    on; once the unload's stop is over the job is gone."""
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    hass = rig.hass
    hanging = rig.gateway.block_hand_back = asyncio.Event()
    unload = asyncio.ensure_future(hass.config_entries.async_unload(rig.entry.entry_id))
    await settle(rounds=50)
    assert rig.gateway.calls[-1] == ("ch", True)  # the hand-back's first call hangs

    def ours() -> list[Any]:
        return [j for j in hass._shutdown_jobs if j.job.name == "vtherm_smart_boiler hand-back"]

    jobs = ours()
    assert len(jobs) == 1  # kept while the hand-back runs
    shutdown = asyncio.ensure_future(jobs[0].job.target())
    assert not await settle(shutdown), "the shutdown job waits for the hand-back"
    hanging.set()
    assert await unload
    await shutdown
    assert rig.gateway.calls[-3:] == HAND_BACK


async def test_an_unload_removes_the_shutdown_job_once_its_stop_is_over(rig: Rig) -> None:
    """PB-36's negative: without a Home Assistant stop, the unload's stop removes the job at its
    end — nothing of the entry is left in Home Assistant's list."""
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    hass = rig.hass
    name = "vtherm_smart_boiler hand-back"
    assert [j for j in hass._shutdown_jobs if j.job.name == name]
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    assert not [j for j in hass._shutdown_jobs if j.job.name == name]


async def test_a_step_waiting_behind_a_slow_one_does_not_run_before_the_stop(rig: Rig) -> None:
    """C4: a tick queued behind a slow step would run a whole step — with its writes — before
    the stop's hand-back; once the stop has begun, it does nothing."""
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    control = rig.entry.runtime_data.control
    rig.gateway.block = asyncio.Event()
    rig.freezer.tick(30)
    rig.live()
    async_fire_time_changed(rig.hass)  # the keep-alive: its call hangs
    await settle(rounds=50)
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.freezer.tick(10)
    # The next tick — heating off to write — waits behind it.
    queued = asyncio.ensure_future(control._async_timer(datetime.now(UTC)))
    await settle(rounds=20)
    assert control._tick_waiting
    before = len(rig.gateway.calls)
    stop = asyncio.ensure_future(control.async_stop())
    assert await settle(stop), "the stop waited for the queued step"
    rig.gateway.block.set()
    await queued
    await rig.hass.async_block_till_done()
    assert rig.gateway.calls[before:] == HAND_BACK  # the hand-back only


async def test_an_outer_cancellation_propagates_and_cancels_the_step(rig: Rig) -> None:
    """T-51: a step waits on a slow write service — the gateway hangs on the keep-alive — and
    the task that runs it, the control clock's, is cancelled from outside (Home Assistant cutting
    it short): the ``CancelledError`` reaches that task, and the inner step is cancelled with it,
    not left running on its own. The lock is free again and no step task is left; not being a
    stop, the unit writes again at its next step. Negative: the cancelled write is no failed
    write — nothing raises the write alarm, and nothing is handed back."""
    await start(rig)
    await rig.switch(True)
    unit = unit_of(rig)
    rig.gateway.block = asyncio.Event()
    rig.freezer.tick(30)
    rig.live()
    outer = asyncio.ensure_future(unit._async_timer(datetime.now(UTC)))
    await settle(rounds=50)
    step = unit._step_task
    assert step is not None
    assert not step.done()
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the keep-alive's call hangs
    calls = len(rig.gateway.calls)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer
    assert step.cancelled()
    assert unit._step_task is None
    assert not unit._lock.locked()
    assert not unit._tick_waiting
    assert not unit.stopping
    assert len(rig.gateway.calls) == calls  # no hand-back
    rig.gateway.block = None  # the gateway answers again
    await rig.advance(30)
    assert rig.gateway.calls[calls:] == [("setpoint", EXPECTED), ("ch", True)]
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"
    assert rig.state("binary_sensor", "control").state == "on"


def seed_stores(
    hass_storage: dict[str, Any],
    entry: MockConfigEntry,
    control: Any,
    layout: str = "0.2.1",
    **main: Any,
) -> None:
    """The stores an earlier run left. 0.2.1: the entry store alone, with the control state
    under "control" (moved to the control store at the next start). 0.2.2: the control store,
    and the entry store with its copy and the marker."""
    key = f"{DOMAIN}.{entry.entry_id}"
    data = {"monitoring_since": 0.0, "control": control} | main
    if layout == "0.2.2":
        hass_storage[control_key(entry)] = {
            "version": 1,
            "key": control_key(entry),
            "data": control,
        }
        data["control_store"] = 1
    hass_storage[key] = {"version": 1, "key": key, "data": data}


async def start_with_stored(
    rig: Rig,
    hass_storage: dict[str, Any],
    control: dict[str, Any],
    layout: str = "0.2.1",
    **extra: Any,
) -> MockConfigEntry:
    """Set up the entry over the stores left by an earlier run, in either layout."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **extra)
    )
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, control, layout)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    return entry


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_a_restored_latch_shows_its_cause_and_never_expires(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    await start_with_stored(
        rig, hass_storage, {"latched": True, "latched_by": ["pressure_low"]}, layout
    )
    await rig.advance(120)  # past the wait for the switch to restore its state
    state = rig.state("sensor", "control_state")
    assert state.attributes["latched_by"] == ["pressure_low"]
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway.calls == []  # still latched: nothing written
    assert rig.state("sensor", "control_state").state == "handed_back"
    await rig.switch(False)
    await rig.switch(True)  # the user's off and on clears it
    assert rig.gateway.setpoints() == [EXPECTED]


async def test_an_internal_error_is_cleared_by_any_switch_change(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(rig)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    original = type(unit)._async_step

    async def broken(self: Any, now: float) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(type(unit), "_async_step", broken)
    await rig.advance(40)  # the error repeats at every step while control is off
    blockers = rig.state("sensor", "control_state").attributes["blockers"]
    assert blockers.count("control_error") == 1
    monkeypatch.setattr(type(unit), "_async_step", original)
    await rig.switch(True)  # not refused: switching clears the error
    assert rig.gateway.setpoints() == [EXPECTED]
    assert "control_error" not in rig.state("sensor", "control_state").attributes["blockers"]


def guard_rewritten_at(rig: Rig) -> float | None:
    return unit_of(rig)._session.loop.setpoint.rewritten_at


async def test_the_one_rewrite_is_remembered_across_a_restart(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """An outside change was rewritten an hour before the restart: within the day another one is
    not fought, even in the new run."""
    now = START.timestamp()
    await start_with_stored(rig, hass_storage, {"rewritten_at": now - 3600.0, "enabled": True})
    await rig.advance(20)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    rig.gateway.forced = 60.0  # another controller writes its own value
    await rig.advance(20)  # held two steps (M10): judged
    assert guard_rewritten_at(rig) == now - 3600.0  # not written again
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"


async def test_a_day_after_the_one_rewrite_another_outside_change_is_rewritten(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The one rewrite is per day: more than a day after it, an outside change is rewritten
    once again before it counts as another controller."""
    now = START.timestamp()
    await start_with_stored(rig, hass_storage, {"rewritten_at": now - 25 * 3600.0, "enabled": True})
    await rig.advance(20)
    rig.gateway.forced = 60.0
    await rig.advance(20)
    assert guard_rewritten_at(rig) == now + 40.0  # rewritten once more
    assert rig.gateway.setpoints()[-1] == EXPECTED
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"


@pytest.mark.parametrize("latched_by", [["write_ignored"], ["pressure_low"]])
async def test_a_restored_write_ignored_latch_shows_its_alarm(
    rig: Rig, hass_storage: dict[str, Any], latched_by: list[str]
) -> None:
    """PB-32: a write-ignored latch restored after a restart shows its alarm, as its issue;
    negative: another latch does not."""
    await start_with_stored(rig, hass_storage, {"latched": True, "latched_by": latched_by})
    await rig.switch(True)
    await rig.advance(20)
    shown = rig.state("binary_sensor", "alarm_write_ignored").state
    assert shown == ("on" if latched_by == ["write_ignored"] else "off")


async def test_a_latch_holds_through_a_day_and_a_night(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Nothing lets a latch lapse with time: a day later, still nothing is written."""
    await start_with_stored(rig, hass_storage, {"latched": True, "latched_by": ["pressure_low"]})
    await rig.advance(120)
    await rig.switch(True)
    await rig.advance(25 * 3600, step=60.0)
    assert rig.gateway.calls == []
    control_state = rig.state("sensor", "control_state")
    assert control_state.state == "handed_back"
    assert control_state.attributes["latched_by"] == ["pressure_low"]


@pytest.mark.parametrize("topology", ["gateway_standalone", "gateway_with_thermostat"])
async def test_a_lost_boiler_link_raises_an_alarm_and_hands_back(rig: Rig, topology: str) -> None:
    """In every topology: no write without the boiler's data, an alarm, and after five minutes a
    hand-back — stand-alone, heating stops, as the switch says. Control resumes, and the alarm
    goes, once the data has been back for a minute (X2)."""
    await start(rig, topology=topology)
    await rig.switch(True)
    attributes = rig.state("binary_sensor", "control").attributes
    effect = attributes["hand_back_effect"]
    standalone = topology == "gateway_standalone"
    assert effect == ("heating_stops" if standalone else "thermostat_takes_over")
    # SB-16: stand-alone, a Home Assistant outage of more than about a minute stops heating too
    # (the gateway's CS lapses); with a thermostat, the switch says nothing of it.
    assert attributes.get("outage_effect") == ("heating_stops" if standalone else None)
    rig.flow = None
    rig.live()
    count = len(rig.gateway.calls)
    await rig.advance(310)
    assert rig.gateway.calls[count:] == HAND_BACK
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "on"
    rig.flow = 35.0
    await rig.advance(50)  # the flow back for less than a minute: the link is still lost
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "on"
    assert rig.gateway.calls[count:] == HAND_BACK
    await rig.advance(20)  # a minute of it (X2)
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "off"
    assert rig.gateway.setpoints()[-1] == EXPECTED  # control resumed


async def test_a_failed_outdoor_sensor_is_not_a_lost_link(rig: Rig) -> None:
    """Without the outdoor temperature the fallback setpoint heats; nothing is handed back."""
    await start(rig)
    await rig.switch(True)
    rig.outdoor = None  # type: ignore[assignment]
    await rig.advance(400)
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "off"
    state = rig.state("sensor", "control_state")
    assert state.state in ("heating", "fallback")  # the curve holds the last value, then falls back
    assert "outdoor_held" in state.attributes["reasons"]
    assert rig.gateway.setpoints()[-1] >= 25.0  # still heating


async def test_control_waits_while_home_assistant_is_starting(rig: Rig) -> None:
    """VT starts its thermostats only once Home Assistant has started, while `is_running` is
    already true during the start: control waits for the start to end. "Gives no heat" does not
    turn on meanwhile (I12.16): it cannot tell yet, so a zone algorithm is not held back at
    each start; once control heats, it is off."""
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    await start(rig)
    await rig.switch(True)  # not refused: the blocker passes on its own
    await rig.advance(20)
    assert rig.gateway.calls == []
    assert "ha_starting" in rig.state("sensor", "control_state").attributes["blockers"]
    assert rig.state("binary_sensor", "no_heat").state == "unavailable"
    rig.hass.set_state(CoreState.running)
    await rig.advance(10)
    assert rig.gateway.setpoints() == [EXPECTED]
    assert rig.state("binary_sensor", "no_heat").state == "off"


async def test_the_switch_says_how_off_is_sent(rig: Rig) -> None:
    """Through the heating switch (on an OpenTherm Gateway, CH=0) where there is one; else as a
    low setpoint, which may leave the CH pump running."""
    await start(rig)
    assert rig.state("binary_sensor", "control").attributes["off_by"] == "heating_switch"


async def test_without_a_heating_switch_off_is_a_low_setpoint(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    assert rig.state("binary_sensor", "control").attributes["off_by"] == "low_setpoint"


async def test_a_steady_outdoor_reading_is_not_a_stale_one(rig: Rig) -> None:
    """Many sources report only on change: without a user-set age limit the outdoor sensor keeps
    feeding the curve however old its last report."""
    await start(rig)
    await rig.switch(True)
    rig.outdoor_reported = False
    await rig.advance(3 * 3600, step=300)
    assert "outdoor_sensor" in rig.state("sensor", "control_state").attributes["reasons"]


async def test_a_stuck_outdoor_sensor_leaves_the_curve(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The monitor found the sensor stuck (or far from the weather): the curve holds its last
    value, then the fallback, and the user is told. The check needs a weather entity (Y4: its
    alarm exists only with one); it is unavailable now, so the weather cannot stand in."""
    from custom_components.vtherm_smart_boiler.core.signal_check import (
        OutdoorCheck,
        OutdoorStatus,
    )

    entry = add_entry(rig, options(rig.zones) | {"weather": "weather.fake_home"})
    rig.hass.states.async_set("weather.fake_home", "unavailable", {})
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.switch(True)
    assert rig.entry is not None
    from dataclasses import replace as replaced

    coordinator = rig.entry.runtime_data
    await rig.hass.async_block_till_done(wait_background_tasks=True)  # the first analysis
    await analyse_now(coordinator)
    real = coordinator.analysis
    assert real is not None

    async def no_analysis(*_args: Any) -> None:
        return None  # the monitor's own analysis would replace the finding meanwhile

    monkeypatch.setattr(coordinator, "async_run_analysis", no_analysis)
    coordinator.analysis = replaced(real, outdoor=OutdoorCheck(OutdoorStatus.STUCK, 0.0, 0.0))
    await rig.advance(300)  # the next water decision
    state = rig.state("sensor", "control_state")
    assert "outdoor_sensor" not in state.attributes["reasons"]
    assert "outdoor_held" in state.attributes["reasons"]
    assert rig.state("binary_sensor", "alarm_outdoor_sensor_suspect").state == "on"
    coordinator.analysis = real
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_outdoor_sensor_suspect").state == "off"


@pytest.mark.parametrize(
    ("weather", "difference", "used"),
    [
        (12.0, -7.0, "outdoor_sensor"),
        (-2.0, 7.0, "outdoor_weather"),
        # R6, A3: the weather entity is unavailable — the sensor that has been the colder one
        # carries on, the warmer one gives way to the value held from before.
        (None, -7.0, "outdoor_sensor"),
        (None, 7.0, "outdoor_held"),
    ],
)
async def test_a_deviating_outdoor_sensor_gives_way_only_to_colder_weather(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    weather: float | None,
    difference: float,
    used: str,
) -> None:
    """A3: the monitor found the sensor (5 °C) far from the weather entity. The curve takes
    the colder of the two: the sensor against a weather at 12 °C, the weather at -2 °C; without
    a weather reading, the sensor only where the check saw it read colder."""
    from dataclasses import replace as replaced

    from custom_components.vtherm_smart_boiler.core.signal_check import (
        OutdoorCheck,
        OutdoorStatus,
    )

    rig.hass.states.async_set(
        "weather.fake_home", "cloudy", {"temperature": 0.0, "temperature_unit": "°C"}
    )
    entry = add_entry(rig, options(rig.zones) | {"weather": "weather.fake_home"})
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    rig.entry = entry
    await rig.switch(True)
    coordinator = entry.runtime_data
    await analyse_now(coordinator)
    real = coordinator.analysis
    assert real is not None

    async def no_analysis(*_args: Any) -> None:
        return None

    monkeypatch.setattr(coordinator, "async_run_analysis", no_analysis)
    coordinator.analysis = replaced(
        real, outdoor=OutdoorCheck(OutdoorStatus.DEVIATES, difference, 86400.0)
    )
    if weather is None:
        rig.hass.states.async_set("weather.fake_home", "unavailable", {})
    else:
        rig.hass.states.async_set(
            "weather.fake_home", "cloudy", {"temperature": weather, "temperature_unit": "°C"}
        )
    await rig.advance(300)  # the next water decision
    assert used in rig.state("sensor", "control_state").attributes["reasons"]
    assert rig.state("binary_sensor", "alarm_outdoor_sensor_suspect").state == "on"


def left_out(rig: Rig) -> list[str]:
    """The rooms whose temperature judges nothing of the curve now (I12, decision 8)."""
    return rig.state("sensor", "control_state").attributes["room_sensor_lost_zones"]


async def test_a_room_whose_temperature_is_not_trusted_is_listed_without_an_alarm(
    rig: Rig,
) -> None:
    """I12, decision 8: the room's thermometer — the sensor VT's ``entry_infos`` names, the
    user's device — unavailable, gone or unknown; VT's safety event started; or no measurement
    by VT since the plugin started: the room is listed among those left out of the curve's
    judgement. Its demand still counts, and no alarm rises: the "blind room" alarm went. Each
    cleared, the room counts again."""
    living = rig.zones.entities["living"]
    thermostat = rig.zones.thermostats["living"]
    thermostat.measured = START  # measured before the plugin started
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert left_out(rig) == [living]
    assert rig.gateway.setpoints()  # it still calls: the boiler heats
    thermostat.measured = None  # VT measures it again
    await rig.advance(20)
    assert left_out(rig) == []
    for lost in ("unavailable", "unknown", None):
        if lost is None:
            rig.hass.states.async_remove(thermostat.thermometer)
        else:
            rig.hass.states.async_set(thermostat.thermometer, lost)
        await rig.advance(20)
        assert left_out(rig) == [living], lost
        state = rig.state("sensor", "control_state")
        assert state.attributes["unknown_zones"] == []  # its demand still counts
    rig.hass.states.async_set(thermostat.thermometer, "19.5")
    await rig.advance(20)
    assert left_out(rig) == []
    rig.zones.vt_event("living", "safety", start=True)
    await rig.advance(20)
    assert left_out(rig) == [living]
    assert rig.state("sensor", "control_state").state == "heating"
    rig.zones.vt_event("living", "safety", start=False)
    await rig.advance(20)
    assert left_out(rig) == []
    registry = er.async_get(rig.hass)
    assert rig.entry is not None
    for key in ("alarm_zone_unknown", "alarm_frost_not_warming"):
        found = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{rig.entry.entry_id}_{key}")
        assert found is None, key


async def test_a_room_in_vts_safety_mode_does_not_raise_the_correction(rig: Rig) -> None:
    """I12, decision 8: a short room VT runs in safety mode — its temperature a frozen one —
    does not make the comfort correction rise; once VT's safety mode ends it does."""
    entry = add_entry(rig, options(rig.zones, comfort_correction=True))
    await set_up(rig, entry)
    await rig.switch(True)
    short_room(rig)
    rig.zones.vt_event("living", "safety", start=True)
    await rig.advance(40 * 60, step=60)
    assert correction(rig) == 0.0
    rig.zones.vt_event("living", "safety", start=False)
    await rig.advance(40 * 60, step=60)
    assert correction(rig) > 0.0


def critical(rig: Rig) -> State:
    return rig.state("sensor", "critical_zone_main")


@pytest.mark.parametrize("source", ["sensor", "vt_event", "vt_off_reason"])
async def test_a_room_with_its_window_open_is_not_the_critical_zone(rig: Rig, source: str) -> None:
    """I12.10 (gap 1 item 4, gap 22): the fullest, coldest room has its window open — the window
    sensor VT's ``entry_infos`` names reads on, VT's automatic window detection started, or VT
    holds it off for a window: another room is the critical zone. Closed again, the room stays
    out while it warms back, and comes back once it is no longer warming — here at once, its
    temperature flat for half an hour."""
    rig.zones.add("bedroom", current_temperature=20.8, hvac_action="heating", valve_open_percent=40)
    living = rig.zones.entities["living"]
    bedroom = rig.zones.entities["bedroom"]
    cold = {"current_temperature": 18.0, "hvac_action": "heating", "valve_open_percent": 100}
    rig.zones.set("living", **cold)
    await start(rig)
    await rig.advance(60)  # the monitor's look every 30 s
    assert critical(rig).attributes["zone"] == living
    window = rig.zones.thermostats["living"].window_sensor
    if source == "sensor":
        rig.hass.states.async_set(window, "on")
    elif source == "vt_event":
        rig.zones.vt_event("living", "window_auto", start=True)
    else:
        off = {
            "hvac_action": "off",
            "specific_states": {"hvac_off_reason": "hvac_off_window_detection"},
        }
        rig.zones.set("living", "off", **(cold | off))
    await rig.advance(60)
    assert critical(rig).attributes["zone"] == bedroom
    assert not critical(rig).attributes["saturated"]
    if source == "sensor":
        rig.hass.states.async_set(window, "off")
    elif source == "vt_event":
        rig.zones.vt_event("living", "window_auto", start=False)
    else:
        rig.zones.set("living", **cold)
    await rig.advance(20 * 60, step=60)
    assert critical(rig).attributes["zone"] == bedroom  # warming cannot be told yet
    await rig.advance(11 * 60, step=60)
    assert critical(rig).attributes["zone"] == living  # flat: no longer warming


async def test_a_user_freshness_limit_stops_writes_on_a_frozen_source(rig: Rig) -> None:
    """The flow stops reporting while its entity stays available (MQTT without availability):
    with a limit of ten minutes set, nothing is written after it, and control hands back."""
    entry_options = options(rig.zones) | {"freshness": {"flow": 600.0}}
    entry = add_entry(rig, entry_options)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.switch(True)
    rig.flow_reported = False
    await rig.advance(660)
    count = len(rig.gateway.calls)
    assert rig.state("sensor", "control_state").state == "waiting_data"
    await rig.advance(300)
    assert rig.gateway.calls[count:] == HAND_BACK


async def test_heating_switched_from_outside_is_written_once_then_handed_back(rig: Rig) -> None:
    """P22, S-40 (decision 6, answers E and H): with a heating echo, heating on/off is confirmed
    by the gateway. "On" before the plugin, "on" commanded: another controller switching it off
    for two steps — away from its value from before the plugin — is written again once; the next
    time, every write stops and the plugin steps aside with the whole safe hand-back."""
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(150)  # confirmed and held: the start phase is over
    assert rig.state("sensor", "control_state").attributes["heating_confirmation"] == (
        "confirmed_by_gateway"
    )
    rig.gateway.forced_ch = False  # another controller switches heating off
    count = len(rig.gateway.calls)
    await rig.advance(20)  # held two steps
    assert ("ch", True) in rig.gateway.calls[count:]  # the one rewrite
    rig.gateway.forced_ch = None
    await rig.advance(20)  # ours again
    rig.gateway.forced_ch = False  # and switched off again
    await rig.advance(20)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    await rig.advance(10)
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.gateway.calls[-3:] == HAND_BACK  # the whole safe hand-back, the lowest first


async def test_an_optimistic_heating_echo_confirms_nothing_and_is_not_judged(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PB-34 (S-09): a heating echo carrying ``assumed_state`` shows what it was given — shown
    "unverified", never "confirmed", and a change in it is judged as none: another controller
    switching heating off in it raises nothing and makes no rewrite."""
    publish = rig.gateway.publish

    def optimistic() -> None:
        publish()
        state = rig.hass.states.get(CH_ECHO)
        assert state is not None
        rig.hass.states.async_set(CH_ECHO, state.state, {"assumed_state": True})

    monkeypatch.setattr(rig.gateway, "publish", optimistic)
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(150)
    shown = rig.state("sensor", "control_state").attributes["heating_confirmation"]
    assert shown == "unverified"
    rig.gateway.forced_ch = False
    await rig.advance(600)
    for alarm in ("outside_change", "write_ignored", "commands_lost"):
        assert rig.state("binary_sensor", f"alarm_{alarm}").state == "off"
    assert rig.state("sensor", "control_state").state != "handed_back"


async def test_a_heating_switch_that_never_shows_its_new_state_is_judged(rig: Rig) -> None:
    """Z4R2-03: OTGW with a heating echo, "on" before the plugin. The plugin switched heating off
    (read back), then on again — and the echo never shows "on" (the switch stuck, or an
    automation putting it back within a step of every CH=1). Within minutes it is judged: the
    plugin's previous state, no longer exempt 5 minutes after the send (K4.3, decided by the user
    2026-10-03), held — another controller: CH=1 written once more, then the plugin steps aside
    with the safe hand-back and the latch issue, about 7 minutes after the send, instead of
    refreshing CH=1 every 30 s for ever, unseen."""
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(150)  # "on" confirmed and held: the start phase is over
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(200)
    assert rig.gateway.ch is False  # "off" taken
    rig.gateway.forced_ch = False  # from now on the echo never shows "on"
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    for _ in range(12):
        await rig.advance(10)
        if ("ch", True) in rig.gateway.calls:
            break
    assert ("ch", True) in rig.gateway.calls  # "on" sent
    sent = dt_util.utcnow().timestamp()
    await rig.advance(290)
    assert rig.state("sensor", "control_state").state == "heating"  # within 5 minutes: not judged
    for _ in range(30):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert sent + 300 < dt_util.utcnow().timestamp() <= sent + 480  # rewrite at 5:20, 2 min
    assert state.attributes["latched_by"] == ["outside_change"]
    assert unit_of(rig)._session.loop.switch.rewritten_at is not None  # one rewrite first
    assert issue(rig, "control_latched") is not None
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # no refresh for ever: left alone


@pytest.mark.parametrize("stuck", ["off", "on"])
async def test_a_heating_switch_stuck_under_vt_pulses_is_judged(rig: Rig, stuck: str) -> None:
    """KD-01: OTGW with a heating echo, "on" before the plugin; VT pulses heating on for 90 s of
    every 5 minutes. For 20 minutes the echo follows (its delay learned from its echoes); then it
    never changes again: stuck "off" (the switch does not take "on", or an automation puts it
    back within a step) or stuck "on". The previous state's 5 minutes start again at every send,
    so it was never judged; the stuck test judges it within about 10 minutes. Stuck "off":
    another controller — CH=1 written once more, then the plugin steps aside with the safe
    hand-back and the latch. Stuck "on", the value from before the plugin: lost commands (answer
    E) — CH=0 sent again, "commands lost" raised, no step aside."""
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(150)  # "on" confirmed and held: the start phase is over
    ignored = ("ch", stuck == "off")  # the command the switch will not take
    pulsing: bool | None = None
    start_at: int | None = None
    first: float | None = None
    for step in range(6 * 65):  # 20 minutes working, then 45 stuck
        if step == 6 * 20:
            rig.gateway.forced_ch = stuck == "on"  # from now on the echo shows only this
            start_at = len(rig.gateway.calls)
        pulse = step * 10 % 300 < 90
        if pulse is not pulsing:
            pulsing = pulse
            if pulse:
                rig.zones.set(
                    "living", hvac_action="heating", valve_open_percent=60, on_percent=0.6
                )
            else:
                rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
        await rig.advance(10)
        if start_at is not None and first is None and ignored in rig.gateway.calls[start_at:]:
            first = dt_util.utcnow().timestamp()
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert first is not None
    now = dt_util.utcnow().timestamp()
    state = rig.state("sensor", "control_state")
    if stuck == "off":
        assert state.state == "handed_back"
        assert now - first <= 15 * 60  # judged and stepped aside within a quarter of an hour
        assert state.attributes["latched_by"] == ["outside_change"]
        assert unit_of(rig)._session.loop.switch.rewritten_at is not None  # one rewrite first
        assert issue(rig, "control_latched") is not None
        return
    assert state.state != "handed_back"
    assert rig.state("binary_sensor", "alarm_commands_lost").state == "on"
    assert unit_of(rig)._session.loop.switch.blocked is None


@pytest.mark.parametrize(
    ("effect", "severity", "cleared_by"),
    [
        ("own_control", ir.IssueSeverity.WARNING, "read_back"),
        ("heating_stops", ir.IssueSeverity.ERROR, "switch_off"),
    ],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_setpoint_the_boiler_does_not_show_raises_an_issue(
    rig: Rig, effect: str, severity: ir.IssueSeverity, cleared_by: str
) -> None:
    """Z4R2-03 for the setpoint: a held setpoint entity, the device keeping its old value after
    the plugin's new one (Z4R-01: never judged by itself, so a boiler's own limit stays clipped).
    After 5 minutes: "confirmation missing" names the setpoint and a repair issue says the
    boiler does not show the plugin's value — an error where a hand-back stops heating, else a
    warning — with no hand-back. Both go once the value is read back, or when control is
    switched off. Negative: 4 min 50 s — neither."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(
        rig,
        **held_entity(
            number, hand_back_value_effect=effect, decision_interval_min=1, ramp_k_per_min=""
        ),
    )
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(150)  # read back and held
    held = number.value
    number.forced = held  # the device keeps it from now on
    rig.outdoor = OUTDOOR - 10.0  # colder: one new value, no ramp
    for _ in range(12):
        await rig.advance(10)
        if number.writes[-1] != held:
            break
    assert number.writes[-1] > held
    await rig.advance(280)
    assert rig.state("binary_sensor", "alarm_confirmation_missing").state == "off"
    assert issue(rig, "setpoint_not_shown") is None
    await rig.advance(30)
    missing = rig.state("binary_sensor", "alarm_confirmation_missing")
    assert missing.state == "on"
    assert missing.attributes["targets"] == ["setpoint"]
    found = issue(rig, "setpoint_not_shown")
    assert found is not None
    assert found.severity is severity
    assert not found.is_fixable
    assert rig.state("sensor", "control_state").state != "handed_back"  # never by itself
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    if cleared_by == "switch_off":
        await rig.switch(False)
    else:
        number.forced = None  # the device takes values again
        await rig.advance(310)  # the held refresh writes it again: read back
        assert rig.state("binary_sensor", "alarm_confirmation_missing").state == "off"
    assert issue(rig, "setpoint_not_shown") is None


async def test_heating_switched_back_to_its_baseline_is_first_a_lost_command(rig: Rig) -> None:
    """S-40, answer E: "off" before the plugin (no thermostat calling), "on" commanded; the echo
    flips back to "off" while it stayed available — a fall-back without a trace: the first within
    the hour is a lost command, "on" sent again at once, no alarm; a second that no send explains
    is another controller's — the one rewrite."""
    rig.gateway.ch = False
    rig.gateway.publish()
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(150)
    rig.gateway.ch = False  # dropped: the gateway's heating override is gone
    count = len(rig.gateway.calls)
    await rig.advance(10)
    assert ("ch", True) in rig.gateway.calls[count:]  # sent again at once
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert unit_of(rig)._session.loop.switch.rewritten_at is None
    assert unit_of(rig)._session.loop.switch.fallbacks
    await rig.advance(600)
    rig.gateway.ch = False  # again within the hour, no send explains it
    await rig.advance(10)
    assert unit_of(rig)._session.loop.switch.rewritten_at is not None  # the one rewrite
    assert rig.state("sensor", "control_state").state == "heating"


async def test_keep_alives_do_not_move_the_last_change(rig: Rig) -> None:
    """P88: repeating the same value changes nothing, heating on/off included."""
    await start(rig)
    await rig.switch(True)
    first = rig.state("sensor", "control_setpoint").attributes["last_change"]
    await rig.advance(120)
    assert rig.gateway.calls.count(("ch", True)) > 1  # heating on/off was repeated
    assert rig.state("sensor", "control_setpoint").attributes["last_change"] == first


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_read_back_from_the_written_entity_confirms_nothing(rig: Rig) -> None:
    """P75: the setpoint entity read back as its own echo is shown unverified, and the plugin's
    setpoint entity stays unknown."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    await rig.advance(30)
    setpoint = rig.state("sensor", "control_setpoint")
    assert setpoint.attributes["confirmation"] == "unverified"
    assert setpoint.state == "unknown"
    assert setpoint.attributes["requested"] == EXPECTED


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_fahrenheit_setpoint_entity_gets_fahrenheit(rig: Rig) -> None:
    """P11: the entity's own unit on write and in the range check — 45 °C is not 45 °F."""
    number = FakeNumber(
        rig.hass, unit="°F", value=122.0, attributes={"min": 50, "max": 190, "step": 1}
    )
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert rig.state("binary_sensor", "control").attributes["blockers"] == []
    assert number.writes == [round(EXPECTED * 9 / 5 + 32)]  # on its 1 °F step
    await rig.advance(130)
    setpoint = rig.state("sensor", "control_setpoint")
    assert setpoint.attributes["read_back"] == pytest.approx(EXPECTED, abs=0.3)  # in °C
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_setpoint_entity_in_another_unit_blocks_control(rig: Rig) -> None:
    number = FakeNumber(rig.hass, unit="%")
    number.register()
    await start(rig, **held_entity(number))
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_setpoint_unit_not_supported"
    assert number.writes == []


def _logged(caplog: pytest.LogCaptureFixture, level: int, text: str) -> int:
    return sum(1 for r in caplog.records if r.levelno == level and text in r.getMessage())


async def test_a_lasting_write_failure_is_logged_once_and_its_recovery_once(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """P42: a write failing at every step for minutes is one warning, not one every ten
    seconds — its message without a trace, an expected failure (PB-40); its recovery is one line
    too, once it has worked for five minutes."""
    await start(rig)
    await rig.switch(True)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.advance(120)
    assert _logged(caplog, logging.WARNING, "boiler write failed") == 1
    failure = next(r for r in caplog.records if "boiler write failed" in r.getMessage())
    assert failure.exc_info is None  # no trace
    rig.gateway.register()
    await rig.advance(30)
    assert _logged(caplog, logging.INFO, "works again") == 0  # not yet
    await rig.advance(300)
    assert _logged(caplog, logging.INFO, "works again") == 1
    assert _logged(caplog, logging.WARNING, "boiler write failed") == 1


async def test_a_flapping_write_target_is_one_warning(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-40: a target that fails, works for a minute, then fails again, over and over (a Wi-Fi
    device dropping out), is one warning and no "works again" line while it keeps flapping."""
    await start(rig)
    await rig.switch(True)
    for _ in range(4):
        rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
        await rig.advance(60)
        rig.gateway.register()
        await rig.advance(60)
    assert _logged(caplog, logging.WARNING, "boiler write failed") == 1
    assert _logged(caplog, logging.INFO, "works again") == 0


async def test_a_lasting_hand_back_failure_is_logged_once(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-39 too: switching off whose hand-back fails raises a translated error (the switch
    stays off); one that gets through raises nothing."""
    await start(rig)
    await rig.switch(True)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(False)  # the hand-back fails, and is retried every minute
    assert rig.switch_error == "hand_back_failed"  # PB-39: the user is told, not success
    assert rig.state("binary_sensor", "control").state == "off"  # control is off all the same
    await rig.advance(300)
    assert _logged(caplog, logging.ERROR, "Handing control back failed") == 1
    rig.gateway.register()
    await rig.advance(70)
    assert _logged(caplog, logging.INFO, "hand-back went through") == 1
    await rig.switch(True)
    await rig.switch(False)
    assert rig.switch_error is None  # handed back


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_unreadable_control_data_still_restores_what_matters(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    """P66: one broken field no longer throws the rest away — a hand-back owed and a latch are
    kept whatever else is unreadable."""
    await start_with_stored(
        rig,
        hass_storage,
        {
            "controlling": True,
            "latched": True,
            "latched_by": ["outside_change"],
            "relay_restarts": "not a list",
            "rewritten_at": "yesterday",
            "alarms": ["no_such_alarm"],
        },
        layout,
    )
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert rig.gateway.calls[:3] == HAND_BACK  # the owed hand-back was kept (made at setup)
    stored = unit.stored()  # what a restart keeps, the cause included (T9)
    assert stored["latched"] is True
    assert stored["latched_by"] == ["outside_change"]


async def test_control_data_that_cannot_be_read_hands_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P66: when whether the plugin held the boiler cannot be read, it is taken that it did."""
    await start_with_stored(rig, hass_storage, {"controlling": "maybe"})
    assert rig.gateway.calls == HAND_BACK  # made at setup


# --- V1: the control store (P-01, P-04, P-58) ---------------------------------------------------


def main_key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}"


def without_control(entry_options: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry_options.items() if key != "control"}


def seed_main(hass_storage: dict[str, Any], entry: MockConfigEntry, **data: Any) -> None:
    """An entry store written by 0.2.2: with the marker, so its control store is expected."""
    key = main_key(entry)
    hass_storage[key] = {
        "version": 1,
        "key": key,
        "data": {"monitoring_since": 0.0, "control": {}, "control_store": 1} | data,
    }


def seed_control(hass_storage: dict[str, Any], entry: MockConfigEntry, data: Any) -> None:
    hass_storage[control_key(entry)] = {"version": 1, "key": control_key(entry), "data": data}


async def set_up(rig: Rig, entry: MockConfigEntry) -> None:
    """Set the entry up, and let the first analysis setup starts in the background finish: a
    test's own analysis asked for while it still runs would be skipped — only one runs at a
    time — and what the test then reads would depend on the machine's speed (Z1)."""
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    rig.entry = entry


# The safe hand-back on a gateway: the lowest water temperature, CH=1, then CS=0.
HAND_BACK = [("setpoint", LOWEST), ("ch", True), ("setpoint", 0.0)]


async def test_a_corrupt_store_file_hands_back_first(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T-08 (P-01): a control store file cut off mid-write — a real file, read by Home
    Assistant's own loader, which renames it and returns nothing, as for a new entry. With
    control configured the plugin takes it that it held the boiler: a full hand-back first, a
    notice, and the monitoring period still counts from the entry's creation. The file lives
    under the test's tmp_path, never in the test configuration inside .venv."""
    hass = rig.hass
    storage = tmp_path / ".storage"
    storage.mkdir()
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    real_files = patch.object(ha_storage.Store, "_async_load", REAL_STORE_LOAD)
    real_files.start()
    try:
        await _corrupt_store_file_hands_back_first(rig, storage)
    finally:
        real_files.stop()


async def _corrupt_store_file_hands_back_first(rig: Rig, storage: Path) -> None:
    hass = rig.hass
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(hass)
    main = {
        "version": 1,
        "minor_version": 1,
        "key": main_key(entry),
        "data": {
            "monitoring_since": 0.0,
            "control": {"controlling": False, "hand_back_pending": False},
            "control_store": 1,
        },
    }
    (storage / main_key(entry)).write_text(json.dumps(main), encoding="utf-8")
    whole = json.dumps(
        {
            "version": 1,
            "minor_version": 1,
            "key": control_key(entry),
            "data": {"controlling": True, "hand_back_pending": False},
        }
    )
    (storage / control_key(entry)).write_text(whole[: len(whole) // 2], encoding="utf-8")
    await set_up(rig, entry)
    await rig.advance(30)
    files = await hass.async_add_executor_job(lambda: {path.name for path in storage.iterdir()})
    assert control_key(entry) not in files
    assert any(name.startswith(f"{control_key(entry)}.corrupt.") for name in files)  # kept
    registry = ir.async_get(hass)
    assert any(
        domain == "homeassistant"
        and issue_id.startswith(f"storage_corruption_{control_key(entry)}")
        for domain, issue_id in registry.issues
    )
    assert rig.gateway.calls[:3] == HAND_BACK  # the first step hands back in full
    # The wish was in the damaged file: control stays off, the cautious side (I11.3; the
    # control switch's restored state brought it back on before).
    assert rig.gateway.calls == HAND_BACK
    assert issue(rig, "control_state_unreadable") is None  # SB-39: the hand-back confirmed
    assert entry.runtime_data.monitoring_since == entry.created_at.timestamp()


@pytest.mark.parametrize("main_left", [True, False], ids=["control_store_lost", "both_lost"])
async def test_a_missing_control_store_of_an_entry_that_ran_hands_back_first(
    rig: Rig, hass_storage: dict[str, Any], main_left: bool
) -> None:
    """The entry store has the marker, so the control store was written, and now it is gone —
    or both stores are. Control is configured, so the entry ran: a full hand-back first."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    entry.created_at = dt_util.utcnow() - timedelta(hours=1)  # it ran: no first start (I6)
    if main_left:
        seed_main(hass_storage, entry, control={"controlling": False})
    await set_up(rig, entry)
    await rig.advance(30)
    assert rig.gateway.calls == HAND_BACK
    assert issue(rig, "control_state_unreadable") is None  # SB-39: the hand-back confirmed
    stored = stored_control(hass_storage, rig)  # written afresh, the hand-back confirmed
    assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)


async def test_a_new_entry_with_control_set_up_hands_nothing_back(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """I6.6 (decision 11): control set up in the wizard — an entry made now, with neither store
    yet — has never held the boiler: its first start writes nothing and owes nothing, with no
    error and no repair issue; the switch starts off. Its stores are written as any first
    start's. The negative, an entry that ran and lost both stores, hands back first (above)."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    await set_up(rig, entry)
    await rig.advance(60)
    assert rig.gateway.calls == []
    assert issue(rig, "control_state_unreadable") is None
    assert "cannot be read (missing or damaged)" not in caplog.text
    assert rig.state("binary_sensor", "control").state == "off"
    stored = stored_control(hass_storage, rig)
    assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)


@pytest.mark.parametrize("sign", ["store_of_another_version", "entities_registered"])
async def test_a_young_entry_that_shows_it_ran_hands_back_first(
    rig: Rig, hass_storage: dict[str, Any], sign: str
) -> None:
    """Within its first half hour too, an entry that shows it ran may have held the boiler: a
    store there but unreadable (another version's), or its entities already registered (its
    stores damaged and renamed, which reads as no store at all). A full hand-back first."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    if sign == "store_of_another_version":
        key = main_key(entry)
        hass_storage[key] = {"version": 99, "key": key, "data": {"control_store": 1}}
    else:
        er.async_get(rig.hass).async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_earlier", config_entry=entry
        )
    await set_up(rig, entry)
    await rig.advance(30)
    assert rig.gateway.calls == HAND_BACK


async def test_a_lost_control_store_without_control_hands_back_what_the_copy_owes(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Control left the options while a hand-back was owed, then the control store was lost:
    the entry store's copy still owes it, and the options that took the boiler make it."""
    number = FakeNumber(rig.hass)
    number.register()
    taken_with = held_entity(number) | {"curve": {"design_outdoor": -15, "design_flow": 55}}
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=without_control(options(rig.zones))
    )
    entry.add_to_hass(rig.hass)
    seed_main(hass_storage, entry, control={"hand_back_pending": True, "taken_with": taken_with})
    await set_up(rig, entry)
    await rig.advance(20)
    assert number.writes == [DEFAULT_LOWEST, 50.0]
    assert issue(rig, "control_state_unreadable") is None  # SB-39: the hand-back confirmed


async def test_the_unreadable_notice_stays_while_its_hand_back_is_unconfirmed(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """SB-39: the control store is lost and the boiler does not show the hand-back: the notice
    stays while it is owed, and goes once the hand-back shows."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    seed_main(hass_storage, entry, control={"controlling": False})
    rig.gateway.ignore_release = True
    await set_up(rig, entry)
    await rig.advance(120)
    assert issue(rig, "control_state_unreadable") is not None
    rig.gateway.ignore_release = False
    await rig.advance(120)
    assert issue(rig, "control_state_unreadable") is None


def unit_state(**changes: Any) -> dict[str, Any]:
    """The control state as a unit stores it."""
    return {
        "controlling": False,
        "taken_with": None,
        "latched": False,
        "latched_by": [],
        "rewritten_at": None,
        "heating_rewritten_at": None,
        "failed": False,
        "alarms": [],
        "hand_back_pending": False,
    } | changes


async def test_a_0_2_1_store_moves_to_the_control_store(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The first start after 0.2.1: its entry store holds the control state without the
    marker. Nothing is owed, so nothing is handed back; the state moves to the control store
    and the entry store gets the marker, both at once."""
    control = unit_state(latched=True, latched_by=["pressure_low"], rewritten_at=1000.0)
    entry = await start_with_stored(rig, hass_storage, control)
    # With what 0.2.2 adds: the wish, off without a restored switch, stored at once (V3); the
    # setpoint a gateway's release must leave, none while nothing is owed (V4); the value a
    # timeout hand-back releases back to, and the targets another controller holds (V5);
    # whether a blocker stopped heating (V7); each guard's value from before the plugin and its
    # last fall-back without a trace (X1).
    moved = control | {
        "enabled": False,
        "last_command": None,
        "release_from": None,
        "release_baseline": None,
        "taken_by_other": [],
        "stopped_heating": False,
        "baseline": None,
        "heating_baseline": None,
        "fallback_at": None,
        "heating_fallback_at": None,
        # X8: the relay's one rewrite and the restarts it answered (answers C, N).
        "relay_rewritten_at": None,
        "relay_restarts": [],
        # Z4R2-02: the relay's own timer recognised, the switch-offs compared, and their relay.
        "relay_timer_entity": None,
        "relay_timer_seen_s": None,
        "relay_lapses": [],
        # Y1: what another controller showed when the plugin stepped aside (none here).
        "step_aside_seen": None,
        # PB-14: whether the lost link's hand-back issue was up (it was not).
        "link_lost_issue": False,
    }
    assert hass_storage[control_key(entry)]["data"] == moved
    main = hass_storage[main_key(entry)]["data"]
    assert main["control_store"] == 1
    assert main["control"] == control  # the copy follows with the delayed save
    await rig.advance(30)
    assert rig.gateway.calls == []
    assert issue(rig, "control_state_unreadable") is None


async def test_a_0_2_1_store_that_held_the_boiler_still_hands_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    await start_with_stored(rig, hass_storage, unit_state(controlling=True))
    await rig.advance(30)
    assert rig.gateway.calls == HAND_BACK
    assert issue(rig, "control_state_unreadable") is None  # it was read: no notice


@pytest.mark.parametrize(
    ("in_control_store", "in_copy"), [(False, True), (True, False)], ids=["copy", "store"]
)
async def test_a_store_written_by_0_2_1_after_a_downgrade_keeps_a_hand_back_owed(
    rig: Rig, hass_storage: dict[str, Any], in_control_store: bool, in_copy: bool
) -> None:
    """After a downgrade to 0.2.1 and back, the control store is older than 0.2.1's entry store
    (which has no marker): its copy is taken, and a hand-back either of them owes stays owed."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    seed_control(hass_storage, entry, {"controlling": in_control_store})
    hass_storage[main_key(entry)] = {
        "version": 1,
        "key": main_key(entry),
        "data": {"monitoring_since": 0.0, "control": {"controlling": in_copy}},
    }
    await set_up(rig, entry)
    await rig.advance(30)
    assert rig.gateway.calls == HAND_BACK


@pytest.mark.parametrize("confirmed", [True, False], ids=["confirmed", "unconfirmed"])
async def test_setup_failing_before_the_store_is_read_leaves_it_intact(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, confirmed: bool
) -> None:
    """T-10 (P-04), in V2's order: the stores are read first, so a setup that fails later — VT
    cannot be detected — has already sent the hand-back the last run left owed. The day
    summaries and the monitoring start are kept as they were; a hand-back still owed is
    reported by a persistent issue and made by the next good setup."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler.core.daily import DaySummary
    from custom_components.vtherm_smart_boiler.vtherm_link import VThermLink

    day_start = float(int(START.timestamp() - 3 * 86400))
    day = DaySummary(
        day_start, day_start + 86400, 86400, 12, 10, 1, 7200.0, 36000.0, 3600.0, 7200.0,
        8.5, None, 4.0, 60.0,
    )  # fmt: skip
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.created_at = START - timedelta(days=7)  # the monitoring start (V1)
    entry.add_to_hass(rig.hass)
    rig.entry = entry
    seed_stores(
        hass_storage,
        entry,
        {"controlling": True},
        "0.2.2",
        monitoring_since=START.timestamp() - 7 * 86400,
        daily={str(int(day_start)): day.to_dict()},
    )
    before = copy.deepcopy(hass_storage[main_key(entry)]["data"])
    if not confirmed:
        rig.gateway.connected = False
        rig.live()

    async def fail(_link: VThermLink) -> None:
        raise RuntimeError("the installed vtherm_api could not be read")

    with monkeypatch.context() as patched:
        patched.setattr(VThermLink, "async_detect", fail)
        assert not await rig.hass.config_entries.async_setup(entry.entry_id)
        await rig.hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_ERROR
        await rig.advance(150)  # past the delayed save
    sent = rig.gateway.calls if confirmed else rig.gateway.lost
    assert sent[:3] == HAND_BACK  # sent before the failure
    main = hass_storage[main_key(entry)]["data"]
    assert main["daily"] == before["daily"]
    assert main["monitoring_since"] == before["monitoring_since"]
    found = issue(rig, "hand_back_owed")
    stored = stored_control(hass_storage, rig)
    if confirmed:
        assert found is None
        assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)
    else:
        assert found is not None
        assert found.is_persistent
        assert stored["hand_back_pending"] is True
        rig.gateway.connected = True
        rig.live()
    calls = len(rig.gateway.calls)
    assert await rig.hass.config_entries.async_reload(entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(20)
    # The next good setup makes what is still owed, and nothing more.
    assert rig.gateway.calls[calls:] == ([] if confirmed else HAND_BACK)
    assert issue(rig, "hand_back_owed") is None


async def start_created(
    rig: Rig, hass_storage: dict[str, Any], created_at: Any, **main: Any
) -> MockConfigEntry:
    """An entry created at ``created_at`` that ran before, its verdict needing 7 days of data;
    ``main``: the entry store's fields."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones) | {"monitor": {"monitoring_days": 7}},
    )
    entry.created_at = created_at
    entry.add_to_hass(rig.hass)
    ran_before(rig, entry)
    seed_main(hass_storage, entry, **main)
    hass_storage[main_key(entry)]["data"].pop("monitoring_since")
    if "monitoring_since" in main:
        hass_storage[main_key(entry)]["data"]["monitoring_since"] = main["monitoring_since"]
    await set_up(rig, entry)
    return entry


async def test_a_lost_monitoring_start_falls_back_to_the_entry_creation(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """T-35 (P-01): the stored start is gone, the entry was created 10 days ago: monitoring
    counts from then — a lost store does not start it again."""
    created = START - timedelta(days=10)
    entry = await start_created(rig, hass_storage, created)
    assert entry.runtime_data.monitoring_since == created.timestamp()
    verdict = rig.state("sensor", "verdict")
    assert verdict.attributes["monitoring_since"] == created.isoformat()  # P-78: ISO 8601


async def test_monitoring_counts_from_the_entry_creation_even_after_a_restarted_start(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """A stored start of yesterday — 0.2.1 started it again after losing its store — does not
    move monitoring's start: the entry was created 10 days ago."""
    created = START - timedelta(days=10)
    entry = await start_created(
        rig, hass_storage, created, monitoring_since=(START - timedelta(days=1)).timestamp()
    )
    assert entry.runtime_data.monitoring_since == created.timestamp()


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ((START - timedelta(days=3)).timestamp(), (START - timedelta(days=3)).timestamp()),
        (None, START.timestamp()),
        ("long ago", START.timestamp()),
    ],
    ids=["stored", "none_stored", "unreadable"],
)
async def test_an_entry_without_a_creation_time_uses_the_stored_start(
    rig: Rig, hass_storage: dict[str, Any], stored: Any, expected: float
) -> None:
    """An entry migrated from Home Assistant's old storage has epoch 0 as its creation: the
    stored start counts, and without a readable one, now."""
    main = {} if stored is None else {"monitoring_since": stored}
    entry = await start_created(rig, hass_storage, datetime.fromtimestamp(0, UTC), **main)
    assert entry.runtime_data.monitoring_since == expected


@pytest.mark.parametrize("section", [True, False], ids=["control", "monitor_only"])
async def test_an_unreadable_store_guards_the_options_flow(
    rig: Rig, hass_storage: dict[str, Any], section: bool
) -> None:
    """P-58: the entry is not running and its control store cannot be read. With a control
    section the options flow answers as setup would — a hand-back is owed — and keeps the write
    path; a monitor-only entry owes nothing and may set control up."""
    entry_options = options(rig.zones)
    number = FakeNumber(rig.hass)
    number.register()
    # Monitor only: the interface answered for the entity path (I8, decision D2), the read-back
    # a boiler signal (I8.5b).
    monitor_only = without_control(entry_options) | {
        "control": {"topology": "virtual"},
        "signals": {**entry_options["signals"], "ch_setpoint": number.entity_id},
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=entry_options if section else monitor_only,
    )
    entry.add_to_hass(rig.hass)  # never set up
    rig.entry = entry
    seed_main(hass_storage, entry)
    seed_control(hass_storage, entry, ["not", "a", "mapping"])
    flow = await _first_control_step(
        rig,
        {"write_path": "entity", "confirmed_entity": number.entity_id},
    )
    if section:
        assert flow["errors"] == {"write_path": "hand_back_pending"}
    else:
        assert flow["step_id"] == "control_entity"


@pytest.mark.parametrize("section", [True, False], ids=["control", "monitor_only"])
async def test_removing_an_entry_with_an_unreadable_store_raises_the_issue(
    rig: Rig, hass_storage: dict[str, Any], section: bool
) -> None:
    """P-58: removal answers as setup would; both stores go with the entry."""
    entry_options = options(rig.zones)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=entry_options if section else without_control(entry_options),
    )
    entry.add_to_hass(rig.hass)
    seed_main(hass_storage, entry)
    seed_control(hass_storage, entry, "damaged")
    await rig.hass.config_entries.async_remove(entry.entry_id)
    await rig.hass.async_block_till_done()
    found = ir.async_get(rig.hass).async_get_issue(
        DOMAIN, f"hand_back_owed_after_removal_{entry.entry_id}"
    )
    assert (found is not None) is section
    if found is not None:
        assert found.is_persistent
    assert control_key(entry) not in hass_storage
    assert main_key(entry) not in hass_storage


@pytest.mark.parametrize("section", [True, False], ids=["control", "monitor_only"])
async def test_unreadable_options_and_an_unreadable_store_still_report_a_held_boiler(
    rig: Rig, hass_storage: dict[str, Any], section: bool
) -> None:
    """P-58: the options cannot be read (a control section whose write path this version does
    not know, and a boiler class it does not know) and neither can the control state: with a
    control section it is taken that the boiler was held, and the user is told, for good."""
    entry_options = options(rig.zones) | {
        "boiler": {"class": "no such class"},
        "control": {"write_path": "carrier_pigeon"},
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=entry_options if section else without_control(entry_options),
    )
    entry.add_to_hass(rig.hass)
    seed_main(hass_storage, entry)  # the marker, and no control store
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    found = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"hand_back_owed_{entry.entry_id}")
    assert (found is not None) is section
    if found is not None:
        assert found.is_persistent
    assert rig.gateway.calls == []


@pytest.mark.parametrize("readable", [True, False], ids=["readable", "unreadable"])
async def test_a_release_by_hand_writes_the_control_store(
    rig: Rig, hass_storage: dict[str, Any], readable: bool
) -> None:
    """P-58: the entry is not running and the user confirms in the repair flow that the boiler
    was returned: the control store and the entry store's copy owe nothing any more. One that
    could not be read is written afresh from what could be (the copy's latch is kept)."""
    from homeassistant.components.repairs import DOMAIN as REPAIRS
    from homeassistant.config_entries import ConfigEntryDisabler
    from homeassistant.setup import async_setup_component

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones),
        disabled_by=ConfigEntryDisabler.USER,
    )
    entry.add_to_hass(rig.hass)  # disabled: the integration runs, the entry does not
    rig.entry = entry
    owed = {"hand_back_pending": True, "controlling": True, "latched": True}
    seed_main(hass_storage, entry, control=owed)
    seed_control(hass_storage, entry, owed if readable else ["not", "a", "mapping"])
    ir.async_create_issue(
        rig.hass,
        DOMAIN,
        f"control_state_unreadable_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="control_state_unreadable",
    )
    control_module.report_owed_hand_back(rig.hass, entry.entry_id, persistent=True)
    assert await async_setup_component(rig.hass, DOMAIN, {})
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert await async_setup_component(rig.hass, REPAIRS, {})
    manager = rig.hass.data[REPAIRS]["flow_manager"]
    flow = await manager.async_init(DOMAIN, data={"issue_id": found.issue_id})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    stored = hass_storage[control_key(entry)]["data"]
    assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)
    assert stored["latched"] is True
    main = hass_storage[main_key(entry)]["data"]
    assert (main["control"]["controlling"], main["control"]["hand_back_pending"]) == (False, False)
    assert main["control_store"] == 1
    assert issue(rig, "control_state_unreadable") is None


# --- V2: a setup that fails (P-05, P-33, P-57; C14, H9) -----------------------------------------


def mark_computing(rig: Rig, monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> None:
    """Every run of the monitor's computation is marked in the record of service calls, so it
    can be ordered against the writes; ``fail``: it raises, as the first refresh then does."""
    from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

    original = SmartBoilerCoordinator._compute

    def compute(self: SmartBoilerCoordinator, now: float) -> Any:
        rig.services.append(("compute", "", {}))
        if fail:
            raise RuntimeError("the monitor cannot compute")
        return original(self, now)

    monkeypatch.setattr(SmartBoilerCoordinator, "_compute", compute)


def marks(rig: Rig) -> str:
    """The record as marks: H for a hand-back (the gateway's CS=0), C for a computation."""
    found = []
    for domain, service, data in rig.services:
        if domain == "compute":
            found.append("C")
        elif (domain, service) == ("opentherm_gw", "set_control_setpoint") and data.get(
            "temperature"
        ) == 0:
            found.append("H")
    return "".join(found)


def owed_entry(rig: Rig, hass_storage: dict[str, Any], **extra: Any) -> MockConfigEntry:
    """An entry whose last run left a hand-back owed (0.2.2's stores)."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones) | extra
    )
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, {"controlling": True, "hand_back_pending": True}, "0.2.2")
    rig.entry = entry
    return entry


@pytest.mark.parametrize("confirmed", [True, False], ids=["confirmed", "unconfirmed"])
async def test_an_owed_hand_back_is_made_before_the_first_refresh_fails(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, confirmed: bool
) -> None:
    """T-11 (P-05): the monitor's first refresh fails on every attempt. A hand-back the last run
    left owed is made before it, at each attempt while it is owed; one still owed when setup
    gives up is reported by a persistent issue; nothing keeps running."""
    from homeassistant.config_entries import ConfigEntryState

    mark_computing(rig, monkeypatch, fail=True)
    if not confirmed:
        rig.gateway.connected = False  # the gateway drops what it gets: nothing confirms
        rig.live()
    entry = owed_entry(rig, hass_storage)
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    # Setup's own attempt goes first; the failure path tries again while still owed.
    assert marks(rig) == ("HC" if confirmed else "HCH")
    await rig.advance(10)  # Home Assistant's first retry (5 s), a background task
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert marks(rig) == ("HCC" if confirmed else "HCHHCH")
    found = issue(rig, "hand_back_owed")
    stored = stored_control(hass_storage, rig)
    if confirmed:
        assert found is None
        assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)
    else:
        assert found is not None
        assert found.is_persistent
        assert stored["hand_back_pending"] is True
    assert await rig.hass.config_entries.async_unload(entry.entry_id)  # no more retries
    count = len(rig.services)
    await rig.advance(300)
    assert len(rig.services) == count  # no control clock, no refresh left running


async def test_an_unreadable_forecast_partition_does_not_fail_setup(
    rig: Rig,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    forecasts: FakeForecasts,
) -> None:
    """T-11, forecast variant (P-05): one stored forecast week cannot be read (written by a later
    version, say). It is skipped with one warning; the other weeks are loaded and the entry
    runs."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler.core.forecast import (
        PARTITION_S,
        ForecastKind,
        ForecastPoint,
        ForecastSnapshot,
        partition_of,
    )
    from custom_components.vtherm_smart_boiler.forecasts import partition_key

    entry = add_entry(rig, options(rig.zones) | {"weather": WEATHER_ENTITY})
    current = partition_of(START.timestamp())
    weeks = (current - 2, current - 1, current)
    taken = {week: week * PARTITION_S + 60.0 for week in weeks}
    for week, at in taken.items():
        snapshot = ForecastSnapshot(at, ForecastKind.DAILY, (ForecastPoint(at + 3600, 4.0),))
        key = partition_key(entry.entry_id, week)
        hass_storage[key] = {"version": 1, "key": key, "data": {"snapshots": [snapshot.to_dict()]}}
    unreadable = partition_key(entry.entry_id, current - 1)
    original = ha_storage.Store.async_load

    async def load(store: ha_storage.Store[Any]) -> Any:
        if store.key == unreadable:
            raise NotImplementedError("a later version's data")
        return await original(store)

    monkeypatch.setattr(ha_storage.Store, "async_load", load)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert await rig.hass.config_entries.async_setup(entry.entry_id)
        await rig.hass.async_block_till_done()
    rig.entry = entry
    assert entry.state is ConfigEntryState.LOADED
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and "forecast" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert "1" in warnings[0].getMessage()  # how many weeks were skipped
    recorder = entry.runtime_data.forecasts
    assert recorder is not None
    # P-23: the current week in memory, the older readable one counted, the unreadable one not.
    in_memory = recorder.store.snapshots()
    assert taken[current] in {s.taken_at for s in in_memory}
    assert recorder.store.count() - len(in_memory) == 1  # the week before last, counted


@pytest.mark.parametrize(
    "taken_with",
    [None, "not options", {"write_path": "no such path"}],
    ids=["missing", "not_a_mapping", "unparsable"],
)
async def test_an_owed_hand_back_without_its_options_raises_a_fixable_issue(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture, taken_with: Any
) -> None:
    """T-09 (P-33): a hand-back is owed, control is gone from the options, and the options that
    took the boiler are missing or cannot be read: nothing can hand back. The monitor runs; a
    fixable issue asks the user to return the boiler by hand; once confirmed, nothing is owed,
    and no issue comes back after a restart."""
    from homeassistant.components.repairs import DOMAIN as REPAIRS
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.setup import async_setup_component

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=without_control(options(rig.zones))
    )
    entry.add_to_hass(rig.hass)
    control: dict[str, Any] = {"controlling": True}
    if taken_with is not None:
        control["taken_with"] = taken_with
    seed_stores(hass_storage, entry, control, "0.2.2")
    caplog.clear()
    await set_up(rig, entry)
    assert entry.state is ConfigEntryState.LOADED
    await rig.advance(30)
    assert entry.runtime_data.last_update_success  # the monitor runs
    assert rig.state("sensor", "signal_problems").state != "unavailable"
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert found.is_fixable
    assert not found.is_persistent
    assert _logged(caplog, logging.ERROR, "the options that took the boiler are gone") == 1
    assert rig.gateway.calls == []  # nothing to hand back through
    assert await async_setup_component(rig.hass, REPAIRS, {})
    manager = rig.hass.data[REPAIRS]["flow_manager"]
    flow = await manager.async_init(DOMAIN, data={"issue_id": found.issue_id})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    stored = stored_control(hass_storage, rig)
    assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)
    assert await rig.hass.config_entries.async_reload(entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(30)
    assert issue(rig, "hand_back_owed") is None
    assert rig.gateway.calls == []


@pytest.mark.parametrize("failed", ["setup_error", "setup_retry"])
async def test_options_saved_in_setup_error_reload_the_entry(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, failed: str
) -> None:
    """H9: the entry's setup failed, so no update listener is left to reload it. Options saved
    then set it up again, with the new options."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

    if failed == "setup_error":
        original = rig.hass.config_entries.async_forward_entry_setups
        failures = [RuntimeError("the platforms could not be set up")]

        async def forward(*args: Any, **kwargs: Any) -> None:
            if failures:
                raise failures.pop()
            await original(*args, **kwargs)

        monkeypatch.setattr(rig.hass.config_entries, "async_forward_entry_setups", forward)
        expected = ConfigEntryState.SETUP_ERROR
    else:
        compute = SmartBoilerCoordinator._compute
        failures = [RuntimeError("the monitor cannot compute")]

        def once(self: SmartBoilerCoordinator, now: float) -> Any:
            if failures:
                raise failures.pop()
            return compute(self, now)

        monkeypatch.setattr(SmartBoilerCoordinator, "_compute", once)
        expected = ConfigEntryState.SETUP_RETRY
    entry = add_entry(rig, options(rig.zones))
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is expected
    assert not hasattr(entry, "runtime_data")  # nothing of the failed setup is left
    flow = await rig.hass.config_entries.options.async_init(entry.entry_id)
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "freshness"}
    )
    chained = control_chain.chained(rig.hass.config_entries.options)
    flow = await chained(flow["flow_id"], {"flow": 30})
    flow = await _saved(rig, flow)
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.options["freshness"] == {"flow": 1800.0}


async def test_options_changed_without_a_running_entry_reload_it(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H9, the listener's guard: called for an entry without its runtime data, it reloads
    rather than failing on what is not there."""
    from custom_components.vtherm_smart_boiler import _async_options_updated

    reloaded: list[str] = []

    async def reload(entry_id: str) -> bool:
        reloaded.append(entry_id)
        return True

    entry = add_entry(rig, options(rig.zones))
    monkeypatch.setattr(rig.hass.config_entries, "async_reload", reload)
    await _async_options_updated(rig.hass, entry)
    assert reloaded == [entry.entry_id]


async def test_a_failure_after_the_platforms_still_stops_everything(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, hass_storage: dict[str, Any]
) -> None:
    """P-57: the last step of setup fails, after control has started and taken the boiler: the
    failure path hands back, stops the control clock and lets go of VT; no update listener is
    left and nothing writes afterwards."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler import feature_manager
    from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

    started: list[SmartBoilerCoordinator] = []

    def fail(self: SmartBoilerCoordinator) -> None:
        started.append(self)
        raise RuntimeError("the background jobs could not start")

    monkeypatch.setattr(SmartBoilerCoordinator, "async_start_background", fail)
    entry = add_entry(rig, options(rig.zones))
    seed_stores(hass_storage, entry, {"enabled": True}, "0.2.2")  # control was on
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert rig.gateway.setpoints()[0] == EXPECTED  # control had taken the boiler
    assert rig.gateway.calls[-3:] == HAND_BACK
    (coordinator,) = started
    unit = coordinator.control
    assert unit is not None
    assert unit._unsubs == []  # no control clock
    assert unit._stop_unsub is None  # no shutdown job
    assert feature_manager.registration(rig.hass) is None
    assert entry.update_listeners == []
    assert not hasattr(entry, "runtime_data")
    count = len(rig.gateway.calls)
    await rig.advance(300)
    assert len(rig.gateway.calls) == count


async def test_an_owed_hand_back_does_not_wait_for_the_first_refresh(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C14: the hand-back the last run left owed goes out before the monitor's first
    computation, not after it."""
    mark_computing(rig, monkeypatch)
    entry = owed_entry(rig, hass_storage)
    await set_up(rig, entry)
    assert marks(rig).startswith("HC")
    assert issue(rig, "hand_back_owed") is None
    await rig.advance(10)
    stored = stored_control(hass_storage, rig)
    assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)


async def test_a_store_read_that_fails_writes_nothing_and_still_reports_the_debt(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-04 kept under the new order: reading the stores itself fails unexpectedly. Nothing is
    written over them, and as no unit could be built, a boiler the last run held is reported
    by a persistent issue."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

    async def fail(_self: SmartBoilerCoordinator) -> None:
        raise RuntimeError("the stored data could not be read")

    monkeypatch.setattr(SmartBoilerCoordinator, "async_load", fail)
    entry = owed_entry(rig, hass_storage)
    before = copy.deepcopy(
        {key: hass_storage[key] for key in (main_key(entry), control_key(entry))}
    )
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    await rig.advance(700)  # past the delayed save and the last-run record's ten minutes
    assert {key: hass_storage[key] for key in before} == before
    assert f"{DOMAIN}.{entry.entry_id}.alive" not in hass_storage  # nor that one (P-95)
    assert f"{DOMAIN}.{entry.entry_id}.rooms" not in hass_storage  # nor the rooms' (I12.7b)
    assert rig.gateway.calls == []
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert found.is_persistent


async def test_an_unexpected_failure_of_the_first_hand_back_does_not_fail_setup(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hand-back made at setup fails in a way no writer reports (a bug, say): setup goes on,
    the hand-back stays owed and shown, and the control clock retries it."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler.transport.writers import OpenthermGwWriter

    original = OpenthermGwWriter.hand_back
    failures = [RuntimeError("an unexpected failure")]

    async def hand_back(self: OpenthermGwWriter, **kwargs: Any) -> Any:
        if failures:
            raise failures.pop()
        return await original(self, **kwargs)

    monkeypatch.setattr(OpenthermGwWriter, "hand_back", hand_back)
    entry = owed_entry(rig, hass_storage)
    await set_up(rig, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.control.hand_back_owed
    assert issue(rig, "hand_back_owed") is not None
    assert rig.gateway.calls == []
    await rig.advance(70)  # the clock's retry, a minute later
    assert rig.gateway.calls[:3] == HAND_BACK
    assert not entry.runtime_data.control.hand_back_owed
    assert issue(rig, "hand_back_owed") is None


async def test_forecasts_that_cannot_be_loaded_at_all_do_not_fail_setup(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    forecasts: FakeForecasts,
) -> None:
    """P-05: loading the stored forecasts fails as a whole (the old weeks' files cannot be
    removed, say): logged, and the entry runs and records on."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.vtherm_smart_boiler.forecasts import ForecastRecorder

    async def fail(_self: ForecastRecorder, _now: float) -> None:
        raise OSError("the storage directory cannot be read")

    monkeypatch.setattr(ForecastRecorder, "async_load", fail)
    entry = add_entry(rig, options(rig.zones) | {"weather": WEATHER_ENTITY})
    caplog.clear()
    await set_up(rig, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert _logged(caplog, logging.ERROR, "Could not load the stored forecasts") == 1
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert forecasts.calls  # recording goes on


# --- V3: saved at once — last command, on/off wish, error latch ---------------------------------

SWITCH = "switch.boiler_control_experimental"


def only_saves_made_at_once(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """From now on the control store gets only what is saved at once: the delayed control save
    is dropped, so whatever the store shows was written without waiting."""
    assert rig.entry is not None
    monkeypatch.setattr(rig.entry.runtime_data, "schedule_control_save", lambda: None)


@pytest.mark.parametrize("disabled", [True, False], ids=["disabled", "enabled"])
async def test_the_stored_wish_comes_back_at_setup(
    rig: Rig, hass_storage: dict[str, Any], disabled: bool
) -> None:
    """I11.3: the setup gives the stored wish back at once, where the control switch did when
    added (T-31, answer K, was: a switch disabled in Home Assistant counted as off). Control's
    state is only shown: disabled in Home Assistant, it changes nothing. The owed hand-back goes
    at once, then control takes the boiler again."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    if disabled:
        er.async_get(rig.hass).async_get_or_create(
            "binary_sensor",
            DOMAIN,
            f"{entry.entry_id}_control",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
    seed_stores(hass_storage, entry, {"controlling": True, "enabled": True}, "0.2.2")
    await set_up(rig, entry)
    assert rig.gateway.calls[:3] == HAND_BACK  # the owed hand-back, at once
    assert entry.runtime_data.control.enabled
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED


@pytest.mark.parametrize("wish", [False, True], ids=["off", "on"])
async def test_the_switch_off_survives_an_unclean_restart(
    rig: Rig, hass_storage: dict[str, Any], wish: bool
) -> None:
    """T-39 (P-11): the user switched control off, and Home Assistant crashed before its restore
    cache was written, which still says "on". The stored wish decides: off, and nothing is
    written but the owed hand-back. Negative: a stored "on" comes back on."""
    mock_restore_cache(rig.hass, [State(SWITCH, "on")])
    await start_with_stored(rig, hass_storage, {"controlling": True, "enabled": wish}, "0.2.2")
    await rig.advance(70)
    assert rig.state("binary_sensor", "control").state == ("on" if wish else "off")
    if wish:
        assert rig.gateway.setpoints()[-1] == EXPECTED
    else:
        assert rig.gateway.calls == HAND_BACK


async def test_the_wish_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-11: switching on or off is in the control store before anything else happens, even
    when nothing is written to the boiler (here: no fresh data)."""
    rig.flow = None
    rig.live()
    await start(rig)
    only_saves_made_at_once(rig, monkeypatch)
    await rig.switch(True)
    assert rig.gateway.calls == []
    assert stored_control(hass_storage, rig)["enabled"] is True
    await rig.switch(False)
    assert stored_control(hass_storage, rig)["enabled"] is False


@pytest.mark.parametrize("restored", ["on", "off", None], ids=["on", "off", "none"])
async def test_a_start_without_a_stored_wish_is_off(
    rig: Rig, hass_storage: dict[str, Any], restored: str | None
) -> None:
    """I11.3: without a stored wish control is off — the cautious side — whatever an old
    control switch's restored state says (it decided once at 0.2.2's first start, when the
    switch still restored it)."""
    if restored is not None:
        mock_restore_cache(rig.hass, [State(SWITCH, restored)])
    await start(rig)
    assert rig.state("binary_sensor", "control").state == "off"
    await rig.advance(10)
    assert EXPECTED not in rig.gateway.setpoints()
    assert stored_control(hass_storage, rig)["enabled"] is False


@pytest.mark.parametrize("raw", ["yes", 1, [], {"on": True}])
async def test_an_unreadable_stored_wish_counts_as_off(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture, raw: Any
) -> None:
    """Negative: a wish that cannot be read is "off", not the restored switch."""
    mock_restore_cache(rig.hass, [State(SWITCH, "on")])
    await start_with_stored(rig, hass_storage, {"enabled": raw}, "0.2.2")
    await rig.advance(70)
    assert rig.state("binary_sensor", "control").state == "off"
    assert rig.gateway.calls == []
    assert _logged(caplog, logging.WARNING, "unreadable stored control data: enabled") == 1


@pytest.mark.parametrize("failed", [True, False], ids=["failed", "not_failed"])
async def test_an_internal_error_outlives_a_restart(
    rig: Rig, hass_storage: dict[str, Any], failed: bool
) -> None:
    """C10: the restore of the wish "on" does not clear an internal error: the switch shows on,
    the error blocks and nothing is written, until the user switches off and on. Negative:
    without a stored error control runs at once."""
    stored = {"enabled": True, "failed": failed, "alarms": ["control_error"] if failed else []}
    await start_with_stored(rig, hass_storage, stored, "0.2.2")
    await rig.advance(30)
    assert rig.state("binary_sensor", "control").state == "on"
    if not failed:
        assert rig.gateway.setpoints()[-1] == EXPECTED
        return
    assert "control_error" in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.state("binary_sensor", "alarm_control_error").state == "on"
    assert rig.gateway.calls == []
    assert stored_control(hass_storage, rig)["failed"] is True
    await rig.switch(False)
    await rig.switch(True)
    assert rig.gateway.setpoints() == [EXPECTED]
    assert rig.state("binary_sensor", "alarm_control_error").state == "off"


@pytest.mark.parametrize("on", [True, False], ids=["controlling", "off"])
async def test_an_internal_error_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, on: bool
) -> None:
    """C10: an internal error, and the alarm that explains it, are in the control store at once,
    with control on or off."""
    await start(rig)
    if on:
        await rig.switch(True)
    only_saves_made_at_once(rig, monkeypatch)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert not stored_control(hass_storage, rig).get("failed")

    async def broken(self: Any, now: float) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(type(unit), "_async_step", broken)
    await rig.advance(10)
    stored = stored_control(hass_storage, rig)
    assert stored["failed"] is True
    assert stored["alarms"] == ["control_error"]
    assert stored["last_command"] is None


def last_command(hass_storage: dict[str, Any], rig: Rig) -> Any:
    return stored_control(hass_storage, rig)["last_command"]


async def test_the_last_command_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 3 needs the last command after a crash: the first one, and every change of
    heating on/off, are stored at once; a setpoint step below a kelvin waits for the next save,
    and one that adds up to a kelvin is stored at once."""
    await start(rig, decision_interval_min=1, ramp_k_per_min=None)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    only_saves_made_at_once(rig, monkeypatch)
    at = datetime.now(UTC).timestamp()
    await rig.switch(True)
    first = last_command(hass_storage, rig)
    # The setpoint as control gave it to the writer, in °C (the gateway gets it rounded).
    assert first == {"heating": True, "setpoint": pytest.approx(EXPECTED, abs=0.05), "at": at}

    # Colder outside: the outdoor average, and with it the setpoint, rises by small steps.
    rig.outdoor = OUTDOOR - 10.0
    small_steps = 0
    for _ in range(60):
        await rig.advance(60)
        written = unit.stored()["last_command"]["setpoint"]
        if written - first["setpoint"] >= 1.0:
            break  # a kelvin from the one stored: stored at once
        if written != first["setpoint"]:
            small_steps += 1
            assert last_command(hass_storage, rig) == first  # below a kelvin: not yet
    else:
        pytest.fail("the setpoint never rose by a kelvin")
    assert small_steps > 0
    stored = last_command(hass_storage, rig)["setpoint"]
    assert stored - first["setpoint"] >= 1.0  # stored at once when it got that far
    assert abs(written - stored) < 1.0  # any step since is below a kelvin from it
    assert rig.gateway.setpoints()[-1] == pytest.approx(written, abs=0.05)

    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("ch", False)
    assert last_command(hass_storage, rig)["heating"] is False


async def test_an_unreadable_last_command_is_ignored(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Negative: a last command that cannot be read is none, with a warning; the rest of the
    stored state is restored as it was."""
    stored = {"last_command": "garbage", "latched": True, "latched_by": ["pressure_low"]}
    await start_with_stored(rig, hass_storage, stored, "0.2.2")
    assert rig.entry is not None
    kept = rig.entry.runtime_data.control.stored()
    assert kept["last_command"] is None
    assert (kept["latched"], kept["latched_by"]) == (True, ["pressure_low"])
    assert _logged(caplog, logging.WARNING, "unreadable stored control data: last_command") == 1


ENDINGS = ("ha_stop", "unload", "switch_off", "latch", "internal_error", "blocker", "stale_link")


@pytest.mark.parametrize("ending", ENDINGS)
async def test_the_last_command_survives_only_the_stops_hand_back(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """The hand-back made by a stop (Home Assistant stopping, an unload or reload) keeps the last
    command for the next start; a session that ends for any other reason forgets it."""
    hass = rig.hass
    rig.boiler = FakeBoiler(hass, (*SIGNALS, Signal.PRESSURE))
    rig.boiler.set(Signal.PRESSURE, 1.5)
    rig.live()
    entry_options = options(rig.zones, alarm_reactions={"pressure_low": "hand_back"})
    entry_options["signals"][Signal.PRESSURE.value] = rig.boiler.entity(Signal.PRESSURE)
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert last_command(hass_storage, rig) is not None
    if ending == "ha_stop":
        await hass.async_stop()
    elif ending == "unload":
        assert await hass.config_entries.async_unload(rig.entry.entry_id)
    elif ending == "switch_off":
        await rig.switch(False)
    elif ending == "latch":
        # Y1: a monitor alarm no longer latches (decision 7); another controller does.
        await rig.advance(30)
        rig.gateway.forced = 60.0
        await rig.advance(160)
    elif ending == "internal_error":

        async def broken(self: Any, now: float) -> None:
            raise RuntimeError("a bug")

        monkeypatch.setattr(type(unit), "_async_step", broken)
        await rig.advance(10)
    elif ending == "blocker":
        vt_central_boiler(rig, False)  # VT's central boiler unticked: blocked (I12)
        await rig.advance(10)
    else:
        rig.flow = None
        rig.live()
        await rig.advance(310)
    await hass.async_block_till_done()
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # handed back
    kept = ending in ("ha_stop", "unload")
    stored = last_command(hass_storage, rig)
    assert (stored is not None) is kept
    if kept:
        assert stored["heating"] is True
        assert stored["setpoint"] == pytest.approx(EXPECTED, abs=0.05)


async def test_control_added_back_after_removal_starts_off(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Control left the options while on: the stored wish and last command go, so control
    added back later starts off, with no command to give again; nothing owed, no unit runs
    (I12.9: none follows SmartPI resumes any more)."""
    hass = rig.hass
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    entry = rig.entry
    with_control = dict(entry.options)
    hass.config_entries.async_update_entry(entry, options=without_control(with_control))
    await hass.async_block_till_done()
    assert entry.runtime_data.hand_back_unit is None
    await rig.advance(10)
    stored = stored_control(hass_storage, rig)
    assert (stored["enabled"], stored["last_command"]) == (False, None)
    count = len(rig.gateway.calls)
    hass.config_entries.async_update_entry(entry, options=with_control)
    await hass.async_block_till_done()
    await rig.advance(70)
    assert rig.state("binary_sensor", "control").state == "off"
    assert len(rig.gateway.calls) == count


# --- V4: the hand-back's bookkeeping (P-12, P-42, P-49, P-50, P-51, P-52; Open after R6 #8) -----

CURVE_ANSWER = {"design_outdoor": -15, "design_flow": 55, "hard_min": 25}


async def _through_alarms(rig: Rig, flow: Any) -> Any:
    """Y1 (decision 7): where a thermostat or the boiler's own control takes over, the alarm
    step — the reaction to an ignored write — follows the curve at every level; its default
    answer ends the control section, and the options are saved."""
    if flow.get("step_id") == "control_alarms":
        flow = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], {})
    return await _saved(rig, flow)


async def _saved(rig: Rig, flow: Any) -> Any:
    """I7: a section ends at the menu; "Save and finish" saves."""
    if flow.get("type") != "menu":
        return flow
    return await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], {"next_step_id": "save"}
    )


def unit_of(rig: Rig) -> Any:
    assert rig.entry is not None
    return rig.entry.runtime_data.control


def alarm(rig: Rig) -> str:
    return rig.state("binary_sensor", "alarm_hand_back_failed").state


def errors_logged(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The plugin's own records at ERROR or above."""
    return [
        record
        for record in caplog.records
        if record.levelno >= logging.ERROR and record.name.startswith("custom_components")
    ]


@pytest.mark.parametrize("raised", ["cancelled", "runtime_error"])
async def test_a_hand_back_cut_by_a_foreign_cancel_stays_owed(
    rig: Rig, hass_storage: dict[str, Any], raised: str
) -> None:
    """T-05 (P-42, R1): while control hands back, the gateway's service raises CancelledError —
    a task inside its integration cancelled under the call, not a stop — or RuntimeError. The
    hand-back is owed and stored, shown as failed, and sent again a minute later; once the
    service works it goes through."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    rig.gateway.release_error = (
        asyncio.CancelledError
        if raised == "cancelled"
        else lambda: RuntimeError("a bug in the gateway's integration")
    )
    await rig.switch(False)  # the step decides to hand back; CS=0 raises
    assert unit.hand_back_owed
    assert stored_control(hass_storage, rig)["hand_back_pending"] is True
    assert alarm(rig) == "on"
    sent = rig.gateway.setpoints().count(0.0)
    await rig.advance(50)
    assert rig.gateway.setpoints().count(0.0) == sent  # not before a minute
    await rig.advance(20)
    assert rig.gateway.setpoints().count(0.0) == sent + 1  # sent again after a minute
    assert unit.hand_back_owed
    rig.gateway.release_error = None
    await rig.advance(60)
    assert not unit.hand_back_owed
    assert alarm(rig) == "off"


async def test_a_real_cancel_of_a_hand_back_keeps_it_owed_and_stored(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1, negative: the step that hands back is itself cancelled. The cancel passes — it is no
    failed attempt — and the debt, stored at once before the first write, stays owed; the
    next attempt comes a minute later and goes through."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    only_saves_made_at_once(rig, monkeypatch)
    rig.gateway.block_hand_back = asyncio.Event()
    off = asyncio.ensure_future(unit.async_set_enabled(False))
    await settle(rounds=50)
    assert rig.gateway.calls[-1] == ("ch", True)  # hanging in the hand-back's first call
    assert stored_control(hass_storage, rig)["hand_back_pending"] is True  # stored before it
    step = unit._step_task
    assert step is not None
    step.cancel()
    await off  # switching off returns: the cancel ended the step, nothing else failed
    assert step.cancelled()
    assert unit.hand_back_owed
    assert alarm(rig) == "off"  # no failed attempt
    await rig.advance(70)
    assert rig.gateway.calls[-3:] == HAND_BACK  # the next attempt
    assert not unit.hand_back_owed


@pytest.mark.parametrize("ending", ["unload", "reload", "step_error"])
async def test_stop_never_raises_when_the_hand_back_raises_unexpectedly(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """T-06 (P-42, R1): ``writer.hand_back`` raises what no writer reports (a bug). Nothing
    escapes; the debt stays owed and stored — with the persistent issue when the entry unloads,
    and the issue shown with ``control_error`` after a failed step — and the next start makes a
    full hand-back after the failed step. After an unload or reload, control on and nothing else
    in the way, decision 3 gives the last command again at once instead (X3): the debt is folded
    into it, with no hand-back first. Every attempt made while the debt exists is full (P-49);
    the first, made for the session's end, is not."""
    from custom_components.vtherm_smart_boiler.transport.writers import OpenthermGwWriter

    hass = rig.hass
    original = OpenthermGwWriter.hand_back
    skipped: list[set[str]] = []
    # The attempts that fail: the stop's, and after a failed step the step's too.
    failures = 2 if ending == "step_error" else 1

    async def hand_back(self: OpenthermGwWriter, **kwargs: Any) -> Any:
        nonlocal failures
        skipped.append(set(kwargs["skip"]))
        if failures:
            failures -= 1
            raise RuntimeError("a bug in the writer")
        return await original(self, **kwargs)

    monkeypatch.setattr(OpenthermGwWriter, "hand_back", hand_back)
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    entry = rig.entry
    assert entry is not None
    if ending == "step_error":
        step = type(unit)._async_step

        async def broken(self: Any, now: float) -> None:
            raise RuntimeError("a bug in the step")

        monkeypatch.setattr(type(unit), "_async_step", broken)
        await rig.advance(10)
        assert unit.hand_back_owed
        found = issue(rig, "hand_back_owed")
        assert found is not None
        assert not found.is_persistent  # shown while the entry runs
        assert rig.state("binary_sensor", "alarm_control_error").state == "on"
        assert alarm(rig) == "on"
        assert stored_control(hass_storage, rig)["hand_back_pending"] is True
        monkeypatch.setattr(type(unit), "_async_step", step)
    if ending == "reload":
        assert await hass.config_entries.async_reload(entry.entry_id)  # the stop's attempt raises
        await hass.async_block_till_done()
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)  # its hand-back raises
        await hass.async_block_till_done()
        found = issue(rig, "hand_back_owed")
        assert found is not None
        assert found.is_persistent
        assert stored_control(hass_storage, rig)["hand_back_pending"] is True
        count = len(rig.gateway.calls)
        await set_up(rig, entry)  # the next start
        if ending == "step_error":  # an internal error stored: the hand-back first
            assert rig.gateway.calls[count:][:3] == HAND_BACK
        else:
            assert rig.gateway.calls[count:][:2] == [("setpoint", EXPECTED), ("ch", True)]
    # Every attempt is the whole safe hand-back: nothing is left out (P-49, V5).
    assert skipped == [set()] * (3 if ending == "step_error" else 1)
    assert not unit_of(rig).hand_back_owed
    assert issue(rig, "hand_back_owed") is None


@pytest.mark.parametrize("older_debt", [True, False], ids=["older_debt", "no_debt"])
async def test_an_end_of_session_hand_back_is_full_while_an_older_debt_exists(
    rig: Rig, hass_storage: dict[str, Any], older_debt: bool
) -> None:
    """P-49 (R2), as V5 decides it: the last run left a hand-back owed, with its held heating
    switch left off, and this session's writes all fail (both targets away). The older debt is
    folded into the session at its first write attempt (PB-13): the session holds the boiler.
    Switched off, the session's hand-back is the whole safe hand-back: the heating switch goes
    back on, though this session never switched it. Without an older debt the same: the heating
    part follows the hand-back's effect (S-27), not what the session touched."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass, on=False)
    switch.register()
    number.set_available(False)
    switch.set_available(False)
    control = held_entity(number, ch_entity=switch.entity_id, ch_write_type="held")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **control)
    )
    entry.add_to_hass(rig.hass)
    owed = {"controlling": True, "hand_back_pending": True} if older_debt else {}
    seed_stores(hass_storage, entry, owed, "0.2.2")
    await set_up(rig, entry)
    await rig.switch(True)  # a session whose writes all fail
    await rig.advance(20)
    assert number.writes == []
    assert switch.writes == []
    unit = unit_of(rig)
    assert unit.holding
    assert not unit.hand_back_owed  # folded into the session, which holds the boiler
    switch.set_available(True)  # back, and still off
    await rig.switch(False)
    assert switch.on  # "own control": the boiler heats under its own control again


async def test_a_release_by_hand_waits_for_a_running_attempt(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P-51 (R3): the user confirms in the repair flow that the boiler was returned while a
    hand-back attempt hangs in a slow gateway. The release waits for the attempt; afterwards
    nothing is owed — the attempt, which did not see its release, did not set the debt again —
    and nothing is retried."""
    from custom_components.vtherm_smart_boiler import repairs

    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    assert rig.entry is not None
    hanging = asyncio.Event()
    rig.gateway.block_hand_back = hanging
    rig.gateway.ignore_release = True  # the attempt will not see its release
    off = asyncio.ensure_future(unit.async_set_enabled(False))
    await settle(rounds=50)
    assert rig.gateway.calls[-1] == ("ch", True)  # the attempt hangs in its first call
    assert unit.hand_back_owed
    release = asyncio.ensure_future(repairs.async_release(rig.hass, rig.entry.entry_id))
    assert not await settle(release, rounds=50), "the release did not wait for the attempt"
    hanging.set()
    await off
    await release
    await rig.hass.async_block_till_done()
    assert not unit.hand_back_owed
    assert not unit.holding
    assert stored_control(hass_storage, rig)["hand_back_pending"] is False
    assert issue(rig, "hand_back_owed") is None
    count = len(rig.gateway.calls)
    await rig.advance(130)
    assert len(rig.gateway.calls) == count  # nothing retried


INTERFACE_GATEWAY = {"topology": "gateway_with_thermostat", "thermostat_kind": "opentherm"}


def stored_topics(rig: Rig) -> dict[str, Any]:
    """The firmware's topics as control reads them: the connection's, one copy (I8.4b)."""
    from custom_components.vtherm_smart_boiler.control_config import with_interface_topics

    assert rig.entry is not None
    return dict(
        with_interface_topics(rig.entry.options["control"], rig.entry.options.get("boiler"))
    )


async def test_gateway_id_cannot_change_while_a_hand_back_is_owed(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """T-13 (P-12, R4): two gateways. The "Boiler interface" item passes with nothing owed and
    picks gw2 (I8, decision D2); before the save, the unit starts owing a hand-back through gw1.
    The save goes back to the interface with the reason, the options stay, and the hand-back
    goes on through gw1. Negative: with nothing owed at the save, gw2 is saved."""
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw2"}).add_to_hass(rig.hass)
    integrations_running(rig)
    await start(rig)
    assert rig.entry is not None
    configure = control_chain.chained(rig.hass.config_entries.options)
    flow = await _interface_step(rig, INTERFACE_GATEWAY | {"gateway_id": "gw2"})
    assert flow["type"] == "menu"
    # Before the save: control takes the boiler, the gateway drops, control is switched off.
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    flow = await configure(flow["flow_id"], {"next_step_id": "save"})
    assert flow["step_id"] == "interface"
    assert flow["errors"] == {"base": "hand_back_pending"}
    await rig.hass.async_block_till_done()
    assert rig.entry.options["control"]["gateway_id"] == "gw"
    rig.gateway.connected = True
    await rig.advance(70)
    assert not unit_of(rig).hand_back_owed  # through gw1
    released = {
        data["gateway_id"]
        for domain, service, data in rig.services
        if (domain, service) == ("opentherm_gw", "set_control_setpoint")
        and data["temperature"] == 0
    }
    assert released == {"gw"}
    flow = await _interface_step(rig, INTERFACE_GATEWAY | {"gateway_id": "gw2"})
    flow = await configure(flow["flow_id"], {"next_step_id": "save"})
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    assert rig.entry.options["control"]["gateway_id"] == "gw2"


@pytest.mark.parametrize(
    ("node", "saved"), [("otgw-2", False), ("  otgw-1 ", True)], ids=["changed", "spaces"]
)
async def test_mqtt_topics_cannot_change_while_control_holds_the_boiler(
    rig: Rig, node: str, saved: bool
) -> None:
    """T-14 (P-12, R4): the "Boiler interface" item passes while control is off; before the
    save control takes the boiler. A changed node is refused at the save, back at the interface,
    the options kept; the same node with spaces around it passes."""

    async def publish(call: ServiceCall) -> None:
        if call.data["topic"].endswith("/ctrlsetpt"):
            value = float(call.data["payload"])
            rig.gateway.override = None if value == 0 else value
            rig.gateway.publish()

    rig.hass.services.async_register("mqtt", "publish", publish)
    integrations_running(rig)
    # Without the opentherm_gw path's gateway: the flow drops what another path left.
    await start(rig, write_path="otgw_mqtt", mqtt_top="OTGW", mqtt_node="otgw-1", gateway_id=None)
    assert rig.entry is not None
    flow = await _interface_step(rig, INTERFACE_GATEWAY | {"mqtt_top": "OTGW", "mqtt_node": node})
    assert flow["type"] == "menu"
    await rig.switch(True)  # control takes the boiler before the save
    await rig.advance(20)
    assert unit_of(rig).holding
    configure = control_chain.chained(rig.hass.config_entries.options)
    flow = await configure(flow["flow_id"], {"next_step_id": "save"})
    if saved:
        assert flow["type"] == "create_entry"
    else:
        assert flow["step_id"] == "interface"
        assert flow["errors"] == {"base": "control_holds_boiler"}
    await rig.hass.async_block_till_done()
    assert stored_topics(rig)["mqtt_node"] == "otgw-1"


async def test_the_interface_refuses_another_gateway_while_control_holds_the_boiler(
    rig: Rig,
) -> None:
    """P-34 (T-13 at its own step): control holds the boiler through gw when the options reach
    the "Boiler interface" item — another gateway is refused there, with the reason; the same
    gateway passes on to the menu. Negative: control off, holding nothing — gw2 passes."""
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw2"}).add_to_hass(rig.hass)
    integrations_running(rig)
    await start(rig)
    assert rig.entry is not None
    await rig.switch(True)
    await rig.advance(20)
    assert unit_of(rig).holding
    configure = control_chain.chained(rig.hass.config_entries.options)
    refused = await _interface_step(rig, INTERFACE_GATEWAY | {"gateway_id": "gw2"})
    assert (refused["step_id"], refused["errors"]) == (
        "interface",
        {"base": "control_holds_boiler"},
    )
    passed = await configure(refused["flow_id"], INTERFACE_GATEWAY | {"gateway_id": "gw"})
    assert passed["type"] == "menu"
    await rig.switch(False)
    passed = await _interface_step(rig, INTERFACE_GATEWAY | {"gateway_id": "gw2"})
    assert passed["type"] == "menu"
    assert rig.entry.options["control"]["gateway_id"] == "gw"  # nothing saved by the steps


async def test_the_interface_refuses_other_topics_while_a_hand_back_is_owed(rig: Rig) -> None:
    """P-34 (T-14 at its own step): a hand-back owed through the firmware's topics when the
    options reach the "Boiler interface" item — another node is refused there, with the reason;
    the same topics, spaces around them dropped, pass on to the menu."""

    async def publish(call: ServiceCall) -> None:
        if call.data["topic"].endswith("/ctrlsetpt"):
            value = float(call.data["payload"])
            rig.gateway.override = None if value == 0 else value
            rig.gateway.publish()

    rig.hass.services.async_register("mqtt", "publish", publish)
    integrations_running(rig)
    await start(rig, **MQTT_PATH, gateway_id=None)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False  # the release will not show: the hand-back stays owed
    rig.live()
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    configure = control_chain.chained(rig.hass.config_entries.options)
    refused = await _interface_step(
        rig, INTERFACE_GATEWAY | {"mqtt_top": OTGW_TOP, "mqtt_node": "otgw-2"}
    )
    assert (refused["step_id"], refused["errors"]) == (
        "interface",
        {"base": "hand_back_pending"},
    )
    passed = await configure(
        refused["flow_id"], INTERFACE_GATEWAY | {"mqtt_top": OTGW_TOP, "mqtt_node": " otgw-1 "}
    )
    assert passed["type"] == "menu"


async def test_the_gateways_read_back_cannot_change_at_the_save(rig: Rig) -> None:
    """R4: the gateway's read-back, which judges its release, re-picked while nothing was owed;
    owed before the save: refused there, on the signals step — a boiler signal now (I8.5b).
    Negative, a missing control section: "no control" stays possible at the save, the hand-back
    going through what took the boiler."""
    integrations_running(rig)
    await start(rig)
    assert rig.entry is not None
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _signals_step(rig, {"confirmed_entity": other})
    assert flow["type"] is FlowResultType.MENU  # nothing owed yet: taken, not saved
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    flow = await _saved(rig, flow)
    assert flow["step_id"] == "signals"
    assert flow["errors"] == {"base": "hand_back_pending"}
    assert rig.entry.options["signals"]["ch_setpoint"] == CONFIRMED
    rig.hass.config_entries.options.async_abort(flow["flow_id"])
    flow = await _first_control_step(rig, {"write_path": "none"})
    flow = await _saved(rig, flow)
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    # Control taken out; the interface's answers stay (I8, decision D2).
    assert "write_path" not in rig.entry.options.get("control", {})


async def test_a_stop_during_the_save_leaves_no_unawaited_write(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    """P-52 (R5): the store save made before a write is slow, and the unit stops meanwhile. The
    write's coroutine is made only once the save is done, so the stop leaves none behind
    unawaited; only the stop's own hand-back is written."""
    import gc

    await start(rig)
    unit = unit_of(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    original = coordinator.async_save_control_now
    gate = asyncio.Event()

    async def slow() -> None:
        if unit.holding and not unit._stopping:
            await gate.wait()  # the save before the first write
        await original()

    monkeypatch.setattr(coordinator, "async_save_control_now", slow)
    on = asyncio.ensure_future(unit.async_set_enabled(True))
    await settle(rounds=50)
    assert unit.holding
    assert rig.gateway.calls == []  # waiting in the save
    await unit.async_stop()
    gate.set()
    await on
    await rig.hass.async_block_till_done()
    gc.collect()
    assert not [w for w in recwarn if "was never awaited" in str(w.message)]
    assert rig.gateway.calls == HAND_BACK


@pytest.mark.parametrize(
    ("after_s", "shown", "done"),
    [(3.0, "value", True), (8.0, "value", False), (3.0, "unknown", False)],
    ids=["within_the_wait", "after_it", "unknown"],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_late_echo_at_stop_counts_within_the_wait(
    rig: Rig, hass_storage: dict[str, Any], after_s: float, shown: str, done: bool
) -> None:
    """P-50 (R6, Open after R6 #8): a held entity shows a new value only when its device reports
    again (ESPHome, MQTT). Home Assistant stops: after the hand-back's writes the stop waits up
    to 5 s for the report. Within it the hand-back counts, with no persistent issue; after it,
    or with a report of no value, the hand-back stays owed, with the persistent issue."""
    number = FakeNumber(rig.hass, echo_later=True)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    number.publish(number.value)
    stop = asyncio.ensure_future(rig.hass.async_stop())
    await settle(rounds=100)
    assert number.writes[-1] == 50.0  # written, not shown yet
    assert not stop.done()  # waiting for the report
    rig.freezer.tick(after_s)
    if shown == "unknown":
        rig.hass.states.async_set(number.entity_id, "unknown", {"unit_of_measurement": "°C"})
    elif after_s < 5.0:
        number.publish(number.value)
    await settle(rounds=100)
    if after_s >= 5.0:
        number.publish(number.value)  # too late
    rig.freezer.tick(10.0)
    await stop
    found = issue(rig, "hand_back_owed")
    stored = stored_control(hass_storage, rig)
    if done:
        assert found is None
        assert stored["hand_back_pending"] is False
    else:
        assert found is not None
        assert found.is_persistent
        assert stored["hand_back_pending"] is True


def owed_with_command(rig: Rig, hass_storage: dict[str, Any], **extra: Any) -> MockConfigEntry:
    """An entry whose last run held the boiler with a known last command, and left the
    hand-back owed — as a stop that could not get it through leaves it."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **extra)
    )
    entry.add_to_hass(rig.hass)
    command = {"heating": True, "setpoint": EXPECTED, "at": START.timestamp() - 600.0}
    seed_stores(
        hass_storage,
        entry,
        {"controlling": True, "hand_back_pending": True, "last_command": command},
        "0.2.2",
    )
    return entry


@pytest.mark.parametrize(("away_s", "alarmed"), [(40, False), (70, True)])
async def test_the_first_hand_back_after_start_raises_no_alarm_within_the_grace(
    rig: Rig,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    away_s: int,
    alarmed: bool,
) -> None:
    """P-50 (R6): a hand-back the last run left owed, and the gateway away for a while after the
    start. Within the first minute: no ``hand_back_failed``, no ERROR, and the persistent issue
    the last stop left stays as it was; the hand-back is sent at each step and goes through
    once the gateway is back. Negative: away for 70 s, the alarm rises once the minute is over."""
    rig.gateway.connected = False
    rig.live()
    entry = owed_with_command(rig, hass_storage)
    control_module.report_owed_hand_back(rig.hass, entry.entry_id, persistent=True)
    caplog.clear()
    await set_up(rig, entry)
    unit = unit_of(rig)
    for elapsed in range(10, away_s + 1, 10):
        await rig.advance(10)
        if elapsed < 60:
            assert alarm(rig) == "off", elapsed
            found = issue(rig, "hand_back_owed")
            assert found is not None
            assert found.is_persistent  # neither deleted nor raised again
    assert unit.hand_back_owed
    assert len(rig.gateway.lost) >= 2 * (away_s // 10)  # sent at each step
    if alarmed:
        assert alarm(rig) == "on"
        assert len(errors_logged(caplog)) == 1
        return
    assert errors_logged(caplog) == []
    rig.gateway.connected = True
    await rig.advance(10)
    assert rig.gateway.calls[:3] == HAND_BACK
    assert not unit.hand_back_owed
    assert alarm(rig) == "off"
    assert issue(rig, "hand_back_owed") is None
    assert errors_logged(caplog) == []


@pytest.mark.parametrize("read_back", ["the_plugins_value", "unknown"])
async def test_an_otgw_hand_back_the_gateway_did_not_take_stays_owed(
    rig: Rig, read_back: str
) -> None:
    """Open after R6 #8 (R7): the gateway is connected and its service returns normally, but CS=0
    did not take (pyotgw's own timeout, say): the read-back stays at the plugin's value. The
    hand-back stays owed, is sent again every minute and shown as failed after a minute; it is
    done as soon as the read-back leaves the plugin's value. Negative: a read-back without a
    value never counts."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    rig.gateway.ignore_release = True
    await rig.switch(False)
    assert rig.gateway.calls[-3:] == HAND_BACK  # sent, and the service returned
    assert unit.hand_back_owed
    assert alarm(rig) == "off"  # not yet a minute
    if read_back == "unknown":
        rig.gateway.override = None  # it lapsed, but nothing tells
        rig.gateway.readable = False
    await rig.advance(50)
    assert unit.hand_back_owed
    assert rig.gateway.setpoints().count(0.0) == 1
    await rig.advance(20)
    assert rig.gateway.setpoints().count(0.0) == 2  # sent again after a minute
    assert alarm(rig) == "on"
    await rig.advance(60)
    assert rig.gateway.setpoints().count(0.0) == 3  # and every minute
    assert unit.hand_back_owed
    rig.gateway.override = None  # the override lapses: the thermostat's value shows
    rig.gateway.readable = True
    # Seen at the next step; after a read-back without a value the attempt failed (C1), and
    # the next one comes a minute later.
    await rig.advance(10 if read_back == "the_plugins_value" else 60)
    assert not unit.hand_back_owed
    assert alarm(rig) == "off"


@pytest.mark.parametrize("reported", [True, False], ids=["reported", "nothing_new"])
async def test_an_otgw_hand_back_without_a_known_value_needs_a_report_after_it(
    rig: Rig, hass_storage: dict[str, Any], reported: bool
) -> None:
    """R7: neither a setpoint of this session nor a stored one is known (a store from 0.2.1):
    the release counts once the read-back reports a value after the command — pyotgw writes the
    accepted 0 at once. Negative: a read-back with nothing new since keeps it owed."""
    entry = owed_entry(rig, hass_storage)  # no last command stored
    if not reported:
        rig.gateway.ignore_release = True
    await set_up(rig, entry)
    assert rig.gateway.calls[:3] == HAND_BACK
    assert unit_of(rig).hand_back_owed is not reported


@pytest.mark.parametrize("stored", ["kept", "unreadable"])
async def test_the_value_a_release_must_leave_outlives_a_restart(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture, stored: str
) -> None:
    """R7: switched off with the gateway away, then a restart. The session and its last command
    are gone, but the setpoint the release must leave is stored: once the gateway is back, its
    steady read-back — the thermostat's value — counts at once. Negative: a stored value that
    cannot be read is ignored, with a warning, and the steady read-back does not count."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    assert rig.entry is not None
    entry = rig.entry
    assert await rig.hass.config_entries.async_unload(entry.entry_id)
    await rig.hass.async_block_till_done()
    kept = stored_control(hass_storage, rig)
    assert kept["hand_back_pending"] is True
    assert kept["release_from"] == pytest.approx(EXPECTED, abs=0.05)
    assert kept["last_command"] is None  # forgotten when the session ended (V3)
    if stored == "unreadable":
        kept["release_from"] = "garbage"
    rig.gateway.connected = True
    rig.gateway.override = None  # it lapsed while Home Assistant was down
    rig.gateway.deaf = True  # the hand-back adds no report: only the value tells
    rig.live()
    caplog.clear()
    await set_up(rig, entry)
    assert unit_of(rig).hand_back_owed is (stored == "unreadable")
    warned = _logged(caplog, logging.WARNING, "unreadable stored control data: release_from")
    assert warned == (1 if stored == "unreadable" else 0)


async def test_a_lagging_read_back_away_from_ours_is_no_release(rig: Rig) -> None:
    """PB-30: a read-back one ramp step behind the plugin's last value, not reported again after
    the hand-back's command, does not confirm it: the hand-back stays owed. Once the gateway
    reports after the command, a value away from ours does."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    rig.hass.states.async_set(CONFIRMED, str(EXPECTED - 2.0), {"unit_of_measurement": "°C"})
    rig.gateway.deaf = True  # nothing new is reported after the command
    await rig.switch(False)
    assert unit.hand_back_owed
    rig.gateway.deaf = False
    rig.gateway.override = None  # the override lapsed
    rig.gateway.thermostat = EXPECTED - 3.0
    rig.gateway.publish()  # the gateway's report after the command: the thermostat's value
    await rig.advance(10)
    assert not unit.hand_back_owed


async def test_a_clock_set_back_does_not_hold_up_the_owed_retry(rig: Rig) -> None:
    """R8 (C9): a hand-back failed and is due again in a minute; then the wall clock is set back
    an hour. The retry comes at the next step, not once the clock has caught up. Negative:
    without the set back, a step ten seconds later does not retry."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    rig.gateway.release_error = lambda: HomeAssistantError("the gateway is busy")
    await rig.switch(False)
    assert unit.hand_back_owed
    assert rig.gateway.setpoints().count(0.0) == 1
    rig.freezer.tick(10)
    await unit._async_timer(datetime.now(UTC))
    assert rig.gateway.setpoints().count(0.0) == 1  # due in a minute
    rig.gateway.release_error = None
    rig.freezer.move_to(datetime.now(UTC) - timedelta(hours=1))
    rig.live()
    await unit._async_timer(datetime.now(UTC))
    assert rig.gateway.setpoints().count(0.0) == 2  # at once
    assert not unit.hand_back_owed


@pytest.mark.parametrize("attempt", ["switch_off", "step_error", "stop"])
async def test_the_owed_marker_is_stored_before_every_hand_back_write(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, attempt: str
) -> None:
    """R1 (P-42, Q3.3): at the moment a hand-back's first write goes out, the control store
    already says one is owed — saved at once, not with the delayed save — so a crash, or a kill
    during a stop (Docker's 10 s), still leaves it owed."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    only_saves_made_at_once(rig, monkeypatch)
    assert stored_control(hass_storage, rig)["hand_back_pending"] is False
    seen: list[bool] = []

    def watch(kind: str, value: Any) -> None:
        if (kind, value) == ("ch", True):
            seen.append(stored_control(hass_storage, rig)["hand_back_pending"])

    rig.gateway.watch = watch
    if attempt == "switch_off":
        await rig.switch(False)
    elif attempt == "step_error":

        async def broken(self: Any, now: float) -> None:
            raise RuntimeError("a bug in the step")

        monkeypatch.setattr(type(unit), "_async_step", broken)
        await rig.advance(10)
    else:
        await unit.async_stop()
    assert seen == [True]


async def test_a_store_that_cannot_be_written_does_not_hold_up_a_hand_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R1, negative: the store cannot be written before the hand-back (a full disk): logged, and
    the hand-back still goes out and counts as its read-back says."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    assert rig.entry is not None

    async def fail() -> None:
        raise OSError("no space left on the device")

    monkeypatch.setattr(rig.entry.runtime_data, "async_save_control_now", fail)
    await unit.async_stop()
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert not unit.hand_back_owed
    assert _logged(caplog, logging.ERROR, "Could not store the owed hand-back") == 1


@pytest.mark.parametrize("case", ["writes_capped", "budget_cut"])
async def test_the_stop_hand_back_fits_home_assistants_budget(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """R6 (Q3.3): Home Assistant gives all shutdown jobs together 20 s, then cancels them. At a
    stop each hand-back write is capped at 3 s — the safe hand-back's three writes take 9 s at
    most, the wait for a late report 5 s more — and the whole ends within 15 s: a gateway that
    hangs leaves the hand-back owed, with the persistent issue, before Home Assistant cuts
    it."""
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await start(rig)
    await rig.switch(True)
    unit = unit_of(rig)
    rig.gateway.hang = asyncio.Event()  # every call hangs
    if case == "budget_cut":
        monkeypatch.setattr(control_module, "STOP_BUDGET_S", 4.0)
    stop = asyncio.ensure_future(unit.async_stop())
    await settle(rounds=50)
    assert not stop.done()
    rig.freezer.tick(1.9)
    await settle(rounds=50)
    assert not stop.done()
    if case == "writes_capped":
        rig.freezer.tick(1.2)  # 3.1 s: the first write gave up, the second hangs
        await settle(rounds=50)
        assert not stop.done()
        rig.freezer.tick(3.1)  # 6.2 s: the second gave up too, the third hangs
        await settle(rounds=50)
        assert not stop.done()
        rig.freezer.tick(3.1)  # 9.3 s: the third gave up: 9 s of writes, within the 15 s
    else:
        rig.freezer.tick(2.2)  # 4.1 s: past the budget (2 s or 4 s)
    assert await settle(stop, rounds=100), "the stop outlasted its budget"
    await stop
    assert unit.hand_back_owed
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert found.is_persistent
    ran_out = _logged(caplog, logging.ERROR, "ran out of time")
    assert ran_out == (1 if case == "budget_cut" else 0)


async def test_a_cancel_raised_by_the_writer_itself_is_a_failed_attempt(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 (P-42): a CancelledError that leaves the writer itself, while the step is not being
    cancelled — not through a service call, which makes it a failed write — counts as a failed
    attempt: owed, stored, shown, and sent again a minute later."""
    from custom_components.vtherm_smart_boiler.transport.writers import OpenthermGwWriter

    original = OpenthermGwWriter.hand_back
    failures = 1

    async def hand_back(self: OpenthermGwWriter, **kwargs: Any) -> Any:
        nonlocal failures
        if failures:
            failures -= 1
            raise asyncio.CancelledError
        return await original(self, **kwargs)

    monkeypatch.setattr(OpenthermGwWriter, "hand_back", hand_back)
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    await rig.switch(False)
    assert unit.hand_back_owed
    assert stored_control(hass_storage, rig)["hand_back_pending"] is True
    assert alarm(rig) == "on"
    await rig.advance(70)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert not unit.hand_back_owed


async def test_an_unconfirmed_hand_back_raises_no_alarm_within_the_grace(
    rig: Rig,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P-50 (R6): the hand-back the last run left is sent but not shown — the gateway kept the
    override. With a grace longer than the minute such a hand-back gets (a value K4 may pick), it
    is sent again after each minute without an alarm or an ERROR; once the grace is over, it is
    shown as failed."""
    monkeypatch.setattr(control_module, "START_GRACE_S", 150.0)
    entry = owed_with_command(rig, hass_storage)
    rig.gateway.override = EXPECTED  # still in force: a quick restart
    rig.gateway.ignore_release = True
    rig.live()
    caplog.clear()
    await set_up(rig, entry)
    unit = unit_of(rig)
    assert unit.hand_back_owed
    await rig.advance(130)
    assert rig.gateway.setpoints().count(0.0) == 3  # at the start, then after each minute
    assert alarm(rig) == "off"
    assert errors_logged(caplog) == []
    await rig.advance(60)
    assert alarm(rig) == "on"
    assert len(errors_logged(caplog)) == 1


# --- V5: the safe hand-back and what confirms it ----------------------------------------------


def hand_back_shown(rig: Rig) -> Any:
    return rig.state("sensor", "control_state").attributes["hand_back_confirmation"]


def mqtt_gateway(rig: Rig) -> None:
    """The gateway's firmware over MQTT: its commands reach the fake gateway."""

    async def publish(call: ServiceCall) -> None:
        topic, payload = call.data["topic"], call.data["payload"]
        if topic.endswith("/ctrlsetpt"):
            value = float(payload)
            rig.gateway.override = None if value == 0 else value
        elif topic.endswith("/chenable"):
            rig.gateway.ch = payload == "1"
        rig.gateway.calls.append(("setpoint" if "ctrlsetpt" in topic else "ch", float(payload)))
        rig.gateway.publish()

    rig.hass.services.async_register("mqtt", "publish", publish)


GATEWAY_PATHS = {
    "opentherm_gw": {},
    "otgw_mqtt": {"write_path": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw-1"},
}


@pytest.mark.parametrize("path", list(GATEWAY_PATHS))
@pytest.mark.parametrize("shown", ["unknown", "unavailable", "missing"])
async def test_otgw_control_waits_until_the_gateway_has_reported(
    rig: Rig, path: str, shown: str
) -> None:
    """P-21: the gateway's read-back holds no value since the start — pyotgw's report after a
    reset, an entity not reporting, or none at all — while the boiler's own signals are fresh.
    A boiler taken now could never be seen handed back: nothing is written, control waits for
    data; once the read-back holds a value, control takes the boiler."""
    if path == "otgw_mqtt":
        mqtt_gateway(rig)
    rig.gateway.read_back_shown = shown
    rig.live()
    await start(rig, **GATEWAY_PATHS[path])
    await rig.switch(True)
    await rig.advance(60)
    assert rig.gateway.calls == []
    assert rig.plugin_calls() <= {("weather", "get_forecasts")}  # nothing written at all
    state = rig.state("sensor", "control_state")
    assert state.state == "waiting_data"
    assert state.attributes["reasons"] == ["read_back_unknown"]
    rig.gateway.read_back_shown = None
    await rig.advance(10)
    assert rig.gateway.setpoints()[0] == EXPECTED  # control takes the boiler
    assert rig.state("sensor", "control_state").state == "heating"


@pytest.mark.parametrize("shown", ["unknown", "missing"])
@pytest.mark.parametrize(
    ("topology", "severity"),
    [
        ("gateway_standalone", ir.IssueSeverity.ERROR),
        ("gateway_with_thermostat", ir.IssueSeverity.WARNING),
    ],
)
async def test_control_waiting_for_the_gateways_read_back_raises_an_issue(
    rig: Rig, topology: str, severity: ir.IssueSeverity, shown: str
) -> None:
    """Z4-10 (P-21): control is switched on, but the gateway's setpoint read-back has no value —
    unknown, or the entity missing — while the boiler's own signals are fresh: control does not
    take the boiler, as a hand-back could never be seen to get through. Once that wait has
    lasted 5 minutes, a repair issue says so and what to check: an error where a hand-back stops
    heating (stand-alone: nothing heats meanwhile), else a warning. It goes when control is
    switched off, and once the read-back has a value. Negatives: control off — none, however
    long; 4 min 50 s of waiting — none."""
    rig.gateway.read_back_shown = shown
    rig.live()
    await start(rig, topology=topology)
    await rig.advance(600)  # control off: nothing waits
    assert issue(rig, "read_back_waiting") is None
    await rig.switch(True)
    await rig.advance(290)
    assert rig.state("sensor", "control_state").attributes["reasons"] == ["read_back_unknown"]
    assert issue(rig, "read_back_waiting") is None
    await rig.advance(20)
    found = issue(rig, "read_back_waiting")
    assert found is not None
    assert found.severity is severity
    assert not found.is_fixable
    assert rig.gateway.calls == []  # nothing written meanwhile
    await rig.switch(False)
    assert issue(rig, "read_back_waiting") is None
    await rig.switch(True)
    await rig.advance(310)  # waiting again
    assert issue(rig, "read_back_waiting") is not None
    rig.gateway.read_back_shown = None  # the read-back reports
    await rig.advance(10)
    assert issue(rig, "read_back_waiting") is None
    assert rig.gateway.setpoints()[0] == EXPECTED  # control takes the boiler


async def test_an_unknown_gateway_read_back_while_controlling_is_not_a_hand_back_by_itself(
    rig: Rig,
) -> None:
    """P-21, the other half: controlling, the read-back turns unknown while the flame and the
    flow stay fresh — no hand-back by itself, control and its keep-alive go on (X1 adds the
    information alarm ``confirmation_missing`` after 5 min). The boiler link decides: flame and
    flow gone stale, X2's stale-link hand-back comes after five minutes."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.read_back_shown = "unknown"
    count = len(rig.gateway.calls)
    await rig.advance(600)
    assert 0.0 not in rig.gateway.setpoints()[count:]  # no hand-back
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the keep-alive goes on
    assert rig.state("sensor", "control_state").state == "heating"
    rig.flow = None  # the boiler link goes stale
    await rig.advance(310)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert rig.state("sensor", "control_state").state == "handed_back"


@pytest.mark.parametrize("read_back", ["the_entity", "a_separate_one"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_optimistic_setpoint_entity_does_not_confirm_a_hand_back(
    rig: Rig, read_back: str
) -> None:
    """T-30 (S-09): a setpoint entity with ``assumed_state`` shows whatever it was given, the
    device receiving or not. Switched off, the hand-back is done once written — nothing could
    tell more — shown "unverified", and not sent again. Variant: an optimistic separate
    read-back, the same."""
    number = FakeNumber(rig.hass, assumed=True)  # the device is not receiving: no one can tell
    number.register()
    confirmed = number.entity_id
    if read_back == "a_separate_one":
        confirmed = "sensor.fake_boiler_flow_setpoint"
        rig.hass.states.async_set(
            confirmed, str(EXPECTED), {"unit_of_measurement": "°C", "assumed_state": True}
        )
    await start(rig, **held_entity(number, confirmed_entity=confirmed))
    await rig.switch(True)
    await rig.switch(False)
    assert number.writes == [EXPECTED, LOWEST, 50.0]
    unit = unit_of(rig)
    assert not unit.hand_back_owed
    assert hand_back_shown(rig) == "unverified"
    await rig.advance(130)
    assert number.writes == [EXPECTED, LOWEST, 50.0]  # no retry
    assert alarm(rig) == "off"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_optimistic_entity_away_at_the_hand_back_is_retried(rig: Rig) -> None:
    """T-30, negative: an optimistic target counts once written — a write to it while it is
    away fails, so the hand-back stays owed, is shown and sent again; once it is back and
    written, it is done."""
    number = FakeNumber(rig.hass, assumed=True)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    number.set_available(False)
    await rig.switch(False)
    unit = unit_of(rig)
    assert unit.hand_back_owed
    assert alarm(rig) == "on"
    assert hand_back_shown(rig) == "not_confirmed"
    number.set_available(True)
    await rig.advance(60)
    assert number.writes == [EXPECTED, LOWEST, 50.0]
    assert not unit.hand_back_owed
    assert alarm(rig) == "off"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_held_release_not_confirmed_raises_the_alarm_at_once(rig: Rig) -> None:
    """The decision "Safe hand-back": a device that keeps its last value (declared held) refuses
    the release — its write fails. The boiler is left at the lowest water temperature the
    hand-back wrote first: ``hand_back_failed`` at once, the release sent again every minute,
    the device holding the lowest meanwhile, until it goes through."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, hand_back_value=15))
    await rig.switch(True)
    number.refuse = 15.0
    await rig.switch(False)
    assert number.value == LOWEST  # the device holds the lowest
    assert alarm(rig) == "on"  # at once
    assert hand_back_shown(rig) == "not_confirmed"
    sent = number.writes.count(LOWEST)
    await rig.advance(50)
    assert number.writes.count(LOWEST) == sent  # not before a minute
    await rig.advance(10)
    assert number.writes.count(LOWEST) == sent + 1  # the lowest, then the release, again
    assert number.value == LOWEST
    number.refuse = None
    await rig.advance(60)
    assert number.value == 15.0
    assert not unit_of(rig).hand_back_owed
    assert alarm(rig) == "off"


@pytest.mark.parametrize(
    ("write_type", "alarm_at_s"), [("held", 10), ("expiring", 60)], ids=["held", "expiring"]
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_unconfirmed_release_leaves_the_lowest_water_temperature_and_alarms(
    rig: Rig, write_type: str, alarm_at_s: int
) -> None:
    """Q1 M13: the release written but not taken — the device keeps the lowest the hand-back
    wrote first. Declared held, the alarm rises a step later (10 s); sent again every minute
    until it is read back. Negative: an expiring target lapses to the device's own value by
    itself, so it alarms only once unconfirmed at the minute's retry, as before."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, hand_back_value=15, write_type=write_type))
    await rig.switch(True)
    number.lowest = 20.0  # the device ignores 15 and keeps what it was given before
    await rig.switch(False)
    assert number.writes[-2:] == [LOWEST, 15.0]
    assert number.value == LOWEST
    assert alarm(rig) == "off"
    await rig.advance(alarm_at_s - 10)
    assert alarm(rig) == "off"
    await rig.advance(10)
    assert alarm(rig) == "on"
    assert unit_of(rig).hand_back_owed
    number.lowest = None
    await rig.advance(70)  # sent again at the minute, and read back
    assert number.value == 15.0
    assert alarm(rig) == "off"
    assert not unit_of(rig).hand_back_owed


async def test_a_held_release_raises_no_alarm_within_the_start_grace(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The held rule's negative: the hand-back the last run left owed, its target not showing
    it at once — within V4's start grace no alarm, only once the grace is over."""
    number = FakeNumber(rig.hass, lowest=20.0)
    number.register()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones, **held_entity(number, hand_back_value=15)),
    )
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, {"controlling": True, "hand_back_pending": True}, "0.2.2")
    await set_up(rig, entry)
    assert number.writes == [LOWEST, 15.0]
    await rig.advance(50)
    assert alarm(rig) == "off"  # within the grace
    await rig.advance(20)
    assert alarm(rig) == "on"


TIMEOUT_PATH = {"write_path": "entity", "write_type": "expiring", "hand_back": "timeout"}


@pytest.mark.parametrize("baseline", [45.0, None], ids=["baseline_known", "baseline_unknown"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_timeout_hand_back_is_confirmed_when_the_read_back_returns_to_the_baseline(
    rig: Rig, hass_storage: dict[str, Any], baseline: float | None
) -> None:
    """S-20: a timeout hand-back writes the lowest water temperature, then nothing: released once
    the read-back is back within 0.5 K of the value from before the session; that value unknown,
    once it is more than 0.5 K from both the plugin's last value and the lowest. Never written
    again meanwhile — each write would arm the device's timer anew."""
    number = FakeNumber(rig.hass, value=45.0)
    number.register()
    if baseline is None:  # the device had reported nothing before the session
        rig.hass.states.async_set(number.entity_id, "unknown", {"unit_of_measurement": "°C"})
    await start(
        rig,
        **TIMEOUT_PATH,
        setpoint_entity=number.entity_id,
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.switch(True)
    await rig.advance(30)
    await rig.switch(False)
    assert number.writes[-1] == LOWEST  # the lowest, then silence
    unit = unit_of(rig)
    assert unit.hand_back_owed
    assert stored_control(hass_storage, rig)["release_baseline"] == baseline
    count = len(number.writes)
    await rig.advance(90)
    assert len(number.writes) == count  # no rewrite
    assert alarm(rig) == "off"  # not before three minutes
    assert hand_back_shown(rig) == "waiting"
    number.publish(45.0 if baseline is not None else 47.0)  # its timer ran out: its own value
    await rig.advance(10)
    assert not unit.hand_back_owed
    assert hand_back_shown(rig) == "unverified"  # only the written entity shows it
    assert len(number.writes) == count


@pytest.mark.parametrize(
    ("timeout_min", "shown"),
    [(None, None), (5, None), (5, "unknown"), (5, "unavailable")],
    ids=["timeout_not_stored", "lowest_kept", "read_back_unknown", "read_back_unavailable"],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_timeout_hand_back_not_released_alarms_three_minutes_after_the_devices_timeout(
    rig: Rig, timeout_min: int | None, shown: str | None
) -> None:
    """S-20 and decision 5, negative: the read-back stays at the lowest — the device's timer did
    not release — or shows nothing (unknown, unavailable). No rewrite retries; ``hand_back_failed``
    rises three minutes after the device's own timeout from the form (an entry from before the
    field: 1 min), and the hand-back stays owed and shown until the release."""
    number = FakeNumber(rig.hass, value=45.0)
    number.register()
    timeout = {} if timeout_min is None else {"hand_back_timeout_min": timeout_min}
    await start(
        rig,
        **TIMEOUT_PATH,
        **timeout,
        setpoint_entity=number.entity_id,
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.switch(True)
    await rig.advance(30)
    await rig.switch(False)
    count = len(number.writes)
    if shown is not None:
        rig.hass.states.async_set(number.entity_id, shown, {"unit_of_measurement": "°C"})
    late = 60 * (timeout_min or 1) + 180
    await rig.advance(late - 10)
    assert alarm(rig) == "off"
    await rig.advance(10)
    assert alarm(rig) == "on"
    assert hand_back_shown(rig) == "not_confirmed"
    await rig.advance(300)
    assert len(number.writes) == count  # never written again
    assert unit_of(rig).hand_back_owed


@pytest.mark.parametrize("baseline", [52.0, None], ids=["baseline_known", "baseline_unknown"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_timeout_hand_back_is_released_once_the_devices_own_value_moves(
    rig: Rig, baseline: float | None
) -> None:
    """SB-04 (decision 5): a device whose own value moves — an EMS boiler under its own controller
    or curve — never shows the value from before the session again: the hand-back counts once
    its read-back has left both the plugin's last value and the lowest. Judged from the device's
    own timeout given in the form (5 min): not before it — the device holds the lowest until
    then, whatever its read-back shows — and not failed three minutes after the hand-back (the
    fixed time before). Never written again."""
    number = FakeNumber(rig.hass, value=52.0)
    number.register()
    if baseline is None:  # the device had reported nothing before the session
        rig.hass.states.async_set(number.entity_id, "unknown", {"unit_of_measurement": "°C"})
    await start(
        rig,
        **TIMEOUT_PATH,
        hand_back_timeout_min=5,
        setpoint_entity=number.entity_id,
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.switch(True)
    await rig.advance(30)
    await rig.switch(False)
    assert number.writes[-1] == LOWEST
    count = len(number.writes)
    unit = unit_of(rig)
    await rig.advance(120)
    number.publish(47.0)  # away from ours before the device's timeout: not judged yet
    await rig.advance(60)
    assert unit.hand_back_owed
    assert alarm(rig) == "off"
    assert hand_back_shown(rig) == "waiting"
    await rig.advance(130)  # the device's own timeout has run, its value still its own
    assert not unit.hand_back_owed
    assert alarm(rig) == "off"
    assert hand_back_shown(rig) == "unverified"  # only the written entity shows it
    assert len(number.writes) == count


@pytest.mark.parametrize(
    ("effect", "severity"),
    [("own_control", ir.IssueSeverity.WARNING), ("heating_stops", ir.IssueSeverity.ERROR)],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_target_another_controller_holds_counts_as_handed_back(
    rig: Rig, caplog: pytest.LogCaptureFixture, effect: str, severity: ir.IssueSeverity
) -> None:
    """W3 (Q1 M12): after the hand-back another controller holds a held target at 60 °C —
    neither the plugin's value, nor the lowest, nor the hand-back value — at two retry checks a
    minute apart, with no hot water. The hand-back counts as done there and is not sent again:
    shown ``taken_by_other``, one WARNING, and the repair issue — an error where the hand-back
    stops heating, else a warning; not fixable, not persistent. Control taking the boiler
    again deletes it."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, hand_back_value_effect=effect))
    await rig.switch(True)
    number.forced = 60.0  # another controller writes its value over every other
    caplog.clear()
    await rig.switch(False)
    assert number.writes[-2:] == [LOWEST, 50.0]  # the whole safe hand-back, over its value
    assert number.value == 60.0
    unit = unit_of(rig)
    await rig.advance(60)  # the first retry check: judged, the write held back
    assert number.writes[-2:] == [LOWEST, 50.0]
    assert number.writes.count(LOWEST) == 1
    assert unit.hand_back_owed
    await rig.advance(60)  # the second, a minute later: another controller holds it
    assert not unit.hand_back_owed
    count = len(number.writes)
    await rig.advance(180)
    assert len(number.writes) == count  # never sent again
    assert hand_back_shown(rig) == "taken_by_other"
    assert alarm(rig) == "off"
    found = issue(rig, "hand_back_taken_by_other")
    assert found is not None
    assert found.severity is severity
    assert not found.is_fixable
    assert not found.is_persistent
    assert found.translation_placeholders == {"target": number.entity_id}
    assert _logged(caplog, logging.WARNING, "another controller holds") == 1
    number.forced = None
    await rig.switch(True)  # control takes the boiler again
    assert issue(rig, "hand_back_taken_by_other") is None


@pytest.mark.parametrize("hot_water", ["draw", "unknown"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_third_value_during_hot_water_is_judged_later(rig: Rig, hot_water: str) -> None:
    """W6, negatives: during a hot-water draw, and for 120 s after it, the boiler's read-back
    may show another value — no judgement, and the retry write is held back while it is shown.
    With hot water unknown it takes three checks over 120 s."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    number.forced = 60.0
    rig.dhw = True if hot_water == "draw" else None
    rig.live()
    await rig.switch(False)
    unit = unit_of(rig)
    await rig.advance(120)  # two retry checks
    assert unit.hand_back_owed
    assert number.writes.count(LOWEST) == 1  # held back while the third value shows
    if hot_water == "unknown":
        await rig.advance(60)  # the third check, 120 s after the first
        assert not unit.hand_back_owed
        return
    rig.dhw = False  # the draw ends after the second check
    await rig.advance(180)  # checks at 60 s and 120 s after the draw: none judges yet
    assert unit.hand_back_owed
    await rig.advance(60)  # then two checks a minute apart
    assert not unit.hand_back_owed


@pytest.mark.parametrize("case", ["no_trace", "never_on", "trace"])
async def test_a_heating_switch_read_back_on_then_switched_off_is_taken_by_another(
    rig: Rig, case: str
) -> None:
    """Q1 M12, two-valued targets: the heating switch read back "on" once after the hand-back,
    then "off" with no trace of an outage, is another controller's: done there, never sent
    again, with the repair issue. Never read back "on": owed, and sent again every minute.
    "Off" after the switch was unavailable within the five minutes before: a lost command —
    "on" is written again at once."""
    number = FakeNumber(rig.hass, lowest=20.0)  # keeps the value target owed: 15 is ignored
    number.register()
    switch = FakeSwitch(rig.hass, stuck_off=case == "never_on")
    switch.register()
    control = held_entity(
        number, hand_back_value=15, ch_entity=switch.entity_id, ch_write_type="held"
    )
    await start(rig, **control)
    await rig.switch(True)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(False)
    unit = unit_of(rig)
    assert unit.hand_back_owed
    if case == "never_on":
        assert not switch.on
        sent = switch.writes.count(True)
        await rig.advance(60)
        assert switch.writes.count(True) == sent + 1  # sent again every minute
        assert issue(rig, "hand_back_taken_by_other") is None
        return
    assert switch.on  # read back "on" once
    if case == "trace":
        switch.set_available(False)  # the device restarts...
        switch.on = False
        switch.set_available(True)  # ...and comes back off
        await rig.advance(10)
        assert switch.writes[-1] is True  # a lost command: "on" written again at once
        assert switch.on
        assert issue(rig, "hand_back_taken_by_other") is None
        return
    switch.on = False  # an automation switches heating off
    switch.publish()
    await rig.hass.async_block_till_done()
    found = issue(rig, "hand_back_taken_by_other")
    assert found is not None
    assert found.translation_placeholders == {"target": switch.entity_id}
    count = switch.writes.count(True)
    await rig.advance(130)
    assert switch.writes.count(True) == count  # not sent again
    assert not switch.on
    assert unit.hand_back_owed  # the value target is still owed, and sent again
    number.lowest = None
    await rig.advance(60)
    assert not unit.hand_back_owed  # every target done
    assert hand_back_shown(rig) == "taken_by_other"


@pytest.mark.parametrize("trace", [False, True], ids=["no_trace", "trace"])
async def test_an_external_switch_turned_back_on_after_the_hand_back_is_taken_by_another(
    rig: Rig, trace: bool
) -> None:
    """Q1 M12 for the external-control switch, whose hand-back state is "off": read back "off"
    once, then "on" with no trace of an outage — another controller's; with a trace, a lost
    command, written "off" again. The heating switch, away, keeps the hand-back owed."""
    number = FakeNumber(rig.hass)
    number.register()
    heating = FakeSwitch(rig.hass)
    heating.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="held",
        ch_entity=heating.entity_id,
        ch_write_type="held",
        hand_back="switch",
        hand_back_entity=external.entity_id,
        hand_back_entity_write_type="held",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.switch(True)
    assert external.on  # control took the boiler
    await rig.advance(310)
    heating.set_available(False)  # its part cannot go out: the hand-back stays owed
    await rig.switch(False)
    assert not external.on  # released: read back "off"
    assert number.value == LOWEST  # the lowest came first
    unit = unit_of(rig)
    assert unit.hand_back_owed
    if trace:
        external.set_available(False)
        external.on = True
        external.set_available(True)  # back from an outage, on again
        await rig.advance(10)
        assert external.writes[-1] is False  # a lost command: "off" written again
        assert issue(rig, "hand_back_taken_by_other") is None
        return
    external.on = True  # another controller takes external control
    external.publish()
    await rig.hass.async_block_till_done()
    assert issue(rig, "hand_back_taken_by_other") is not None
    count = len(external.writes)
    await rig.advance(130)
    assert len(external.writes) == count  # not sent again


async def test_no_taken_issue_beside_the_step_aside_issue(rig: Rig) -> None:
    """While V7's ``control_latched`` issue for another controller is up, it says so already:
    a target judged held by another controller after the step-aside — here the heating switch,
    read back on and then switched off with no trace of an outage — raises no
    ``hand_back_taken_by_other``. (Before V7 the test raised the latch issue by hand; now a
    switch-off ends the latch and its issue, so the step-aside itself raises it.)"""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    await start(rig, **held_entity(number, ch_entity=switch.entity_id, ch_write_type="held"))
    await rig.switch(True)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    number.forced = 60.0  # another controller writes its value, and again over every write
    number.value = 60.0
    number.publish(60.0)
    for _ in range(20):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert issue(rig, "control_latched") is not None
    assert switch.on  # the step-aside switched heating on: the device's own control resumes
    switch.on = False  # the other controller switches heating off, with no outage
    switch.publish()
    await rig.advance(180)
    assert not unit_of(rig).hand_back_owed  # judged taken all the same
    assert hand_back_shown(rig) == "taken_by_other"
    assert issue(rig, "hand_back_taken_by_other") is None


async def test_the_hand_back_does_not_wait_between_its_parts_on_a_gateway(rig: Rig) -> None:
    """The parts follow one another at once: a gateway whose read-back never shows the lowest
    water temperature gets CH=1 and CS=0 in the same moment, not after a read-back or a wait."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.echo = False  # the read-back shows the thermostat's value, never the lowest
    before = len(rig.gateway.times)
    await rig.switch(False)
    assert rig.gateway.calls[-3:] == HAND_BACK
    moments = rig.gateway.times[before:]
    assert len(moments) == 2  # CS=<lowest> and CS=0
    assert moments[1] - moments[0] < 1.0


# --- P-40, S-21, S-49: the options ---------------------------------------------------------


def switch_method(number: FakeNumber, external: str, write_type: str | None) -> dict[str, Any]:
    control = {
        "write_path": "entity",
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "hand_back": "switch",
        "hand_back_entity": external,
        "confirmed_entity": number.entity_id,
        "topology": "virtual",
    }
    if write_type is not None:
        control["hand_back_entity_write_type"] = write_type
    return control


@pytest.mark.parametrize("write_type", [None, "unknown", "persistent"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_external_switch_of_unknown_write_type_blocks_control(
    rig: Rig, write_type: str | None
) -> None:
    """P-40: the external-control switch is turned on at every take and off at every hand-back,
    so one the boiler may store would be worn: control is blocked with it — an entry saved
    before the option existed too, until the user declares it — and the form refuses it."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    await start(rig, **switch_method(number, external.entity_id, write_type))
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_hand_back_switch_not_writable"
    assert number.writes == []
    assert external.writes == []
    flow = await _first_control_step(
        rig, {"write_path": "entity", "confirmed_entity": number.entity_id}
    )
    answer = {
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "hand_back": "switch",
        "hand_back_entity": external.entity_id,
        "hand_back_entity_write_type": write_type or "unknown",
    }
    flow = await control_chain.chained(rig.hass.config_entries.options)(flow["flow_id"], answer)
    assert flow["errors"] == {
        "hand_back_entity_write_type": "hand_back_entity_write_type_not_supported"
    }
    flow = await control_chain.chained(rig.hass.config_entries.options)(
        flow["flow_id"], answer | {"hand_back_entity_write_type": "held"}
    )
    assert flow["step_id"] == "control_curve"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_expiring_external_switch_is_turned_on_every_keep_alive(rig: Rig) -> None:
    """P-40: declared expiring, the external-control switch lapses unless repeated: turned on
    again every 30 s while control holds the boiler — a held setpoint written once meanwhile —
    and off at the hand-back, then left alone."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    await start(rig, **switch_method(number, external.entity_id, "expiring"))
    await rig.switch(True)
    assert external.writes == [True]
    await rig.advance(95)
    assert external.writes == [True] * 4  # at the take, then every 30 s
    assert number.writes == [EXPECTED]  # the held setpoint: written once
    await rig.switch(False)
    assert external.writes[-1] is False
    count = len(external.writes)
    await rig.advance(60)
    assert len(external.writes) == count  # nothing after the hand-back


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_held_external_switch_is_turned_on_once_per_take(rig: Rig) -> None:
    """P-40: declared held, the device keeps the external-control switch's state: turned on once
    each time control takes the boiler, off at each hand-back."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    await start(rig, **switch_method(number, external.entity_id, "held"))
    await rig.switch(True)
    await rig.advance(120)
    assert external.writes == [True]
    await rig.switch(False)
    assert external.writes == [True, False]
    await rig.switch(True)
    assert external.writes == [True, False, True]


ENTITY_ANSWER = {"write_path": "entity", "topology": "virtual"}


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_hand_back_value_above_the_maximum_is_refused(rig: Rig) -> None:
    """S-21: the hand-back value is exempt only from the lowest water temperature. Above the
    highest the plugin may write it is refused at the step, and at the save when a later step
    lowered a maximum; options edited by hand get the blocker. It is never clamped."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, hand_back_value=75))  # edited by hand: 75 > 70
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_hand_back_value_above_max"
    assert number.writes == []
    assert rig.entry is not None
    assert rig.entry.options["control"]["hand_back_value"] == 75  # never clamped
    flow = await _first_control_step(rig, ENTITY_ANSWER | {"confirmed_entity": number.entity_id})
    answer = {
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "hand_back": "value",
        "hand_back_value_effect": "own_control",
    }
    configure = control_chain.chained(rig.hass.config_entries.options)
    flow = await configure(flow["flow_id"], answer | {"hand_back_value": 75})
    assert flow["errors"] == {"hand_back_value": "hand_back_value_above_max"}
    flow = await configure(flow["flow_id"], answer | {"hand_back_value": 60})
    assert flow["step_id"] == "control_curve"
    flow = await configure(flow["flow_id"], CURVE_ANSWER)
    if flow.get("step_id") == "control_alarms":
        flow = await configure(flow["flow_id"], {})
    # A later step lowers the maximum: the circuit's highest water temperature (I8, F2).
    flow = await configure(flow["flow_id"], {"next_step_id": "circuit_1"})
    flow = await configure(flow["flow_id"], {"control": "unmixed_shared", "max_flow": 55})
    flow = await _saved(rig, flow)
    assert flow["step_id"] == "control_entity"  # the save found the lowered maximum
    assert flow["errors"] == {"base": "hand_back_value_above_max"}
    flow = await configure(flow["flow_id"], answer | {"hand_back_value": 50})
    flow = await configure(flow["flow_id"], CURVE_ANSWER)
    flow = await _through_alarms(rig, flow)
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    assert rig.entry.options["control"]["hand_back_value"] == 50


@pytest.mark.parametrize(
    ("changes", "blocked"),
    [
        ({}, True),
        ({"hand_back_value_effect": "heating_stops"}, False),
        ({"ch_entity": "input_boolean.fake_ch", "ch_write_type": "held"}, False),
    ],
    ids=["own_control", "heating_stops", "heating_switch"],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_off_near_an_own_control_hand_back_value_is_refused(
    rig: Rig, changes: dict[str, Any], blocked: bool
) -> None:
    """S-49: "off" sent as a low setpoint within 0.5 K of a hand-back value that returns the
    boiler to its own control would hand it back instead of stopping heating: the blocker, and
    the form at the save (back to the behaviour step). Allowed with a heating switch, which
    sends "off" itself, and where the hand-back value stops heating."""
    number = FakeNumber(rig.hass)
    number.register()
    FakeSwitch(rig.hass).register()
    await start(rig, **held_entity(number, hand_back_value=10.3) | changes)  # "off" is 10 °C
    if blocked:
        with pytest.raises(ServiceValidationError) as err:
            await rig.switch(True)
        assert err.value.translation_key == "blocked_off_setpoint_near_hand_back_value"
        assert number.writes == []
    else:
        await rig.switch(True)
        assert number.writes == [EXPECTED]
        return
    flow = await _first_control_step(rig, ENTITY_ANSWER | {"confirmed_entity": number.entity_id})
    answer = {
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "hand_back": "value",
        "hand_back_value": 10.3,
        "hand_back_value_effect": "own_control",
    }
    manager = rig.hass.config_entries.options
    configure = control_chain.chained(manager)
    flow = await configure(flow["flow_id"], answer)
    # The curve saved to the menu without a look at the behaviour, then the save: back to the
    # behaviour item, "off" shown there at the simple level while it is refused (I8.9a).
    flow = await manager.async_configure(flow["flow_id"], CURVE_ANSWER)
    flow = await _saved(rig, flow)
    assert flow["step_id"] == "control_behaviour"
    assert flow["errors"] == {"base": "off_setpoint_near_hand_back_value"}
    assert "off_setpoint" in {str(marker) for marker in flow["data_schema"].schema}
    helper = {"vt_boiler_helper": rig.zones.helper}
    flow = await configure(flow["flow_id"], helper | {"off_setpoint": 10.5})
    assert flow["errors"] == {"off_setpoint": "off_setpoint_near_hand_back_value"}
    flow = await configure(flow["flow_id"], helper | {"off_setpoint": 5})
    assert flow["step_id"] == "control_alarms"
    flow = await _through_alarms(rig, flow)
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()  # the entry reloads with the options


@pytest.mark.parametrize("stored", ["kept", "unreadable"])
async def test_a_target_another_controller_holds_stays_so_after_a_restart(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture, stored: str
) -> None:
    """The targets judged held by another controller are stored with the owed hand-back: after
    a restart the setup's attempt writes the rest, not them — no fight at every start. Negative:
    a stored list that cannot be read counts as none — every target is handed back again, with
    a warning."""
    number = FakeNumber(rig.hass, value=60.0)
    number.register()
    switch = FakeSwitch(rig.hass, on=False)
    switch.register()
    control = held_entity(number, ch_entity=switch.entity_id, ch_write_type="held")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **control)
    )
    entry.add_to_hass(rig.hass)
    taken: Any = [number.entity_id] if stored == "kept" else "garbage"
    seed_stores(
        hass_storage,
        entry,
        {"controlling": True, "hand_back_pending": True, "taken_by_other": taken},
        "0.2.2",
    )
    caplog.clear()
    await set_up(rig, entry)
    assert switch.writes == [True]  # the heating part goes out either way
    if stored == "kept":
        assert number.writes == []  # another controller holds it: left alone
        assert not unit_of(rig).hand_back_owed
    else:
        assert number.writes == [LOWEST, 50.0]
        warned = _logged(caplog, logging.WARNING, "unreadable stored control data: taken_by_other")
        assert warned == 1


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_failed_lowest_does_not_keep_a_shown_release_owed(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """The parts are tried whatever the others do: the device refuses the lowest water
    temperature, the release still goes out and is read back — the hand-back is done, with a
    warning, not owed and retried for a part that no longer matters."""
    number = FakeNumber(rig.hass, refuse=LOWEST)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    caplog.clear()
    await rig.switch(False)
    assert number.writes == [EXPECTED, 50.0]  # the lowest refused, the release through
    assert not unit_of(rig).hand_back_owed
    assert alarm(rig) == "off"
    assert _logged(caplog, logging.WARNING, "Part of the hand-back failed") == 1


@pytest.mark.parametrize("same_device", [True, False], ids=["same_device", "other_device"])
async def test_an_outage_of_another_entity_of_the_same_device_is_a_trace(
    rig: Rig, same_device: bool
) -> None:
    """X1's trace, as V5 needs it for two-valued targets: the heating switch changes with no
    outage of its own, but another entity of the same device the plugin uses — the setpoint —
    was unavailable within five minutes before: a lost command, written again, not another
    controller. Negative: the setpoint on another device is no trace for the switch."""
    from homeassistant.helpers import device_registry as dr

    number = FakeNumber(rig.hass, lowest=20.0)  # keeps the value target owed: 15 is ignored
    switch = FakeSwitch(rig.hass)
    esp = MockConfigEntry(domain="esphome", data={})
    esp.add_to_hass(rig.hass)
    device = dr.async_get(rig.hass).async_get_or_create(
        config_entry_id=esp.entry_id, identifiers={("esphome", "opentherm")}
    )
    other = dr.async_get(rig.hass).async_get_or_create(
        config_entry_id=esp.entry_id, identifiers={("esphome", "another")}
    )
    for entity_id in (switch.entity_id, number.entity_id):  # registered before their states
        domain, object_id = entity_id.split(".")
        on = device if same_device or entity_id == switch.entity_id else other
        entry = er.async_get(rig.hass).async_get_or_create(
            domain, "esphome", object_id, suggested_object_id=object_id, device_id=on.id
        )
        assert entry.entity_id == entity_id
    number.register()
    switch.register()
    control = held_entity(
        number, hand_back_value=15, ch_entity=switch.entity_id, ch_write_type="held"
    )
    await start(rig, **control)
    await rig.switch(True)
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(False)
    assert switch.on
    # The session's "on", its five-minute refresh (a held value, X1), the hand-back's.
    assert switch.writes == [True, True, True]
    number.set_available(False)  # the device restarts: its setpoint entity drops out...
    number.set_available(True)
    switch.on = False  # ...and its heating switch comes back off, never seen unavailable
    switch.publish()
    await rig.advance(10)
    if same_device:
        assert switch.writes[-1] is True  # a lost command: "on" written again
        assert switch.on
        assert issue(rig, "hand_back_taken_by_other") is None
    else:
        assert switch.writes.count(True) == 3  # the session's two and the hand-back's only
        assert issue(rig, "hand_back_taken_by_other") is not None


# --- V6: the stop button (P-02, P-24; T-15, T-54; the user's answer I) ---------------------------


@dataclass
class Breaker:
    """The monitor's refresh, made to fail on demand: while ``failing``, its computation — or the
    feature manager's check before it — raises. ``runs``: when each refresh ran, and whether it
    failed."""

    failing: bool = False
    runs: list[tuple[float, bool]] = field(default_factory=list)


def break_monitor(monkeypatch: pytest.MonkeyPatch, where: str = "compute") -> Breaker:
    from custom_components.vtherm_smart_boiler import feature_manager
    from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

    breaker = Breaker()
    if where == "compute":
        compute = SmartBoilerCoordinator._compute

        def broken(self: SmartBoilerCoordinator, now: float) -> Any:
            breaker.runs.append((now, breaker.failing))
            if breaker.failing:
                raise RuntimeError("the monitor cannot compute")
            return compute(self, now)

        monkeypatch.setattr(SmartBoilerCoordinator, "_compute", broken)
        return breaker
    check = feature_manager.async_check

    def broken_check(hass: HomeAssistant, coordinator: Any) -> None:
        breaker.runs.append((dt_util.utcnow().timestamp(), breaker.failing))
        if breaker.failing:
            raise RuntimeError("the feature manager's check fails")
        check(hass, coordinator)

    monkeypatch.setattr(feature_manager, "async_check", broken_check)
    return breaker


async def refresh(rig: Rig) -> None:
    """A refresh of the monitor now, as its clock or a state change makes one."""
    assert rig.entry is not None
    await rig.entry.runtime_data.async_refresh()
    await rig.hass.async_block_till_done()


def control_entities() -> list[tuple[str, str]]:
    """Control (its state, the switch's place since I11.3), control's state and setpoint, the
    "Reset comfort correction" button and
    every control alarm the rig has: the gateway path's — the relay's exist on the relay path
    only (X8, R15) — without the outdoor sensor's, whose check needs a weather entity the rig
    does not have (the missing-data rule, Y4)."""
    return [
        ("binary_sensor", "control"),
        ("sensor", "control_state"),
        ("sensor", "control_setpoint"),
        ("button", "reset_comfort_correction"),
        *(
            ("binary_sensor", f"alarm_{kind.value}")
            for kind in control_module.ControlAlarm
            if kind not in control_module.RELAY_ONLY_ALARMS
            and kind is not control_module.ControlAlarm.OUTDOOR_SENSOR_SUSPECT
        ),
    ]


def blockers(rig: Rig) -> list[str]:
    return list(rig.state("binary_sensor", "control").attributes["blockers"])


def local_minute(t: float) -> str:
    """A moment as the monitor's note shows it: local time, to the minute."""
    return dt_util.as_local(dt_util.utc_from_timestamp(t)).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("where", ["compute", "feature_manager"])
async def test_control_switch_stays_usable_when_the_monitor_refresh_fails(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """T-15 (P-02): the monitor's refresh fails at every run — its computation, or the feature
    manager's check before it. The monitor's own entities go unavailable; the control switch,
    control's state and its alarms do not, so switching control off still hands back at once."""
    await start(rig, comfort_correction=True)  # off by default since K4.1
    await rig.switch(True)
    await rig.advance(30)
    breaker = break_monitor(monkeypatch, where)
    breaker.failing = True
    await refresh(rig)
    await rig.advance(60)
    assert [failed for _, failed in breaker.runs] == [True] * len(breaker.runs)
    assert len(breaker.runs) >= 2
    assert rig.state("binary_sensor", "connection").state == "unavailable"  # the monitor's own
    for domain, key in control_entities():
        assert rig.state(domain, key).state != "unavailable", key
    count = len(rig.gateway.calls)
    await rig.switch(False)
    assert rig.gateway.calls[count:] == HAND_BACK
    assert rig.state("binary_sensor", "control").state == "off"
    for domain, key in control_entities():
        assert rig.state(domain, key).state != "unavailable", key


async def test_control_entities_go_unavailable_only_once_control_stops(rig: Rig) -> None:
    """Negative for T-15: control's entities follow the control unit — unavailable once it stops
    (an unload, Home Assistant stopping), and not before."""
    from homeassistant.helpers.entity_component import DATA_INSTANCES

    await start(rig, comfort_correction=True)  # off by default since K4.1
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    entities = [
        rig.hass.data[DATA_INSTANCES][domain].get_entity(rig.entity(domain, key))
        for domain, key in control_entities()
    ]
    assert all(entity is not None and entity.available for entity in entities)
    await unit.async_stop()
    assert not any(entity is not None and entity.available for entity in entities)


@pytest.mark.parametrize("on", [False, True], ids=["monitor_only", "controlling"])
async def test_a_lasting_fast_path_error_is_logged_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, on: bool
) -> None:
    """T-54 (P-24): the monitor's computation fails for ten minutes, then works. One ERROR with
    its trace from the plugin and at most one without (Home Assistant's "Error fetching …"); the
    recovery is one INFO from the plugin — Home Assistant adds its own "recovered" line, once.
    With control on, its hand-back and its resume are one line each."""
    await start(rig)
    if on:
        await rig.switch(True)
    breaker = break_monitor(monkeypatch)
    caplog.clear()
    breaker.failing = True
    await rig.advance(600)
    breaker.failing = False
    await rig.advance(120)
    assert sum(failed for _, failed in breaker.runs) >= 14  # every refresh of ten minutes
    ours = [r for r in caplog.records if r.name.startswith("custom_components.vtherm_smart_boiler")]
    errors = [r for r in ours if r.levelno >= logging.ERROR]
    assert len([r for r in errors if r.exc_info]) == 1
    assert len([r for r in errors if not r.exc_info]) <= 1
    assert _logged(caplog, logging.INFO, "monitor refresh works again") == 1
    assert _logged(caplog, logging.INFO, "data recovered") <= 1  # Home Assistant's own line
    handed_back = _logged(caplog, logging.WARNING, "monitor has failed")
    resumed = _logged(caplog, logging.INFO, "control has resumed")
    assert (handed_back, resumed) == ((1, 1) if on else (0, 0))
    if on:
        assert rig.gateway.setpoints()[-1] == EXPECTED  # control resumed


@pytest.mark.parametrize(
    ("topology", "severity"),
    [
        ("gateway_standalone", ir.IssueSeverity.ERROR),
        ("gateway_with_thermostat", ir.IssueSeverity.WARNING),
    ],
)
async def test_control_hands_back_when_the_monitor_keeps_failing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, topology: str, severity: ir.IssueSeverity
) -> None:
    """The user's answer I: the monitor failing for five minutes is a blocker — a hand-back, its
    alarm, and a repair issue (an error where the hand-back stops heating). A single good refresh
    does not resume; a minute of them without a failure does, on its own, and the issue becomes
    the information note, from the first failure to the first good refresh."""
    await start(rig, topology=topology)
    await rig.switch(True)
    await rig.advance(30)
    breaker = break_monitor(monkeypatch)
    breaker.failing = True
    await refresh(rig)  # the first failure, now
    first = dt_util.utcnow().timestamp()
    count = len(rig.gateway.calls)
    await rig.advance(290)
    assert ("setpoint", 0.0) not in rig.gateway.calls[count:]
    assert rig.gateway.setpoints()[-1] == EXPECTED  # still controlling: keep-alives go on
    assert "monitor_failed" not in blockers(rig)
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "off"
    since = rig.state("sensor", "control_state").attributes["monitor_failed_since"]
    assert since == dt_util.utc_from_timestamp(first).isoformat()
    assert issue(rig, "monitor_failed") is None
    count = len(rig.gateway.calls)
    await rig.advance(10)  # five minutes of failed refreshes
    assert rig.gateway.calls[count:] == HAND_BACK
    assert "monitor_failed" in blockers(rig)
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "on"
    assert rig.state("sensor", "control_state").state == "not_allowed"
    found = issue(rig, "monitor_failed")
    assert found is not None
    assert found.translation_key == "monitor_failed"
    assert found.severity is severity
    assert not found.is_persistent
    assert not found.is_fixable
    handed = len(rig.gateway.calls)
    breaker.failing = False
    await refresh(rig)  # a single good refresh...
    breaker.failing = True
    await rig.advance(120)
    assert len(rig.gateway.calls) == handed  # ...does not resume
    assert "monitor_failed" in blockers(rig)
    breaker.failing = False
    await refresh(rig)  # works again from now
    back = dt_util.utcnow().timestamp()
    await rig.advance(50)
    assert len(rig.gateway.calls) == handed  # not a minute yet
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # control resumed on its own
    assert "monitor_failed" not in blockers(rig)
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "off"
    assert rig.state("sensor", "control_state").attributes["monitor_failed_since"] is None
    note = issue(rig, "monitor_failed")
    assert note is not None
    assert note.translation_key == "monitor_recovered"
    assert note.severity is ir.IssueSeverity.WARNING
    assert note.translation_placeholders == {
        "since": local_minute(first),
        "until": local_minute(back),
    }


@pytest.mark.parametrize("when", ["switched_on_while_failing", "controlling"])
async def test_stale_monitor_alarms_do_not_hand_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    """Decision 7 (Y1): no monitor alarm hands back — a reaction an earlier version stored for
    one is neutralised — neither while the monitor fails, its last data stale, nor once it works
    again and the alarm is known: control keeps the boiler, nothing latches."""
    rig.boiler = FakeBoiler(rig.hass, (*SIGNALS, Signal.PRESSURE))
    rig.boiler.set(Signal.PRESSURE, 0.5 if when == "switched_on_while_failing" else 1.5)
    rig.live()
    entry_options = options(rig.zones, alarm_reactions={"pressure_low": "hand_back"})
    entry_options["signals"][Signal.PRESSURE.value] = rig.boiler.entity(Signal.PRESSURE)
    entry_options["monitor"] = entry_options.get("monitor", {}) | {"add_water_below": 0.8}
    entry = add_entry(rig, entry_options)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    coordinator = entry.runtime_data
    breaker = break_monitor(monkeypatch)
    if when == "controlling":
        await rig.switch(True)
        await rig.advance(30)
        rig.boiler.set(Signal.PRESSURE, 0.5)
    await rig.advance(310)  # five minutes below the threshold: the alarm level
    await refresh(rig)
    assert coordinator.data.alarms[AlarmKind.PRESSURE_LOW].active
    breaker.failing = True
    await refresh(rig)  # the monitor fails, its last data holding the alarm
    if when == "switched_on_while_failing":
        await rig.switch(True)
    await rig.advance(200)
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert rig.gateway.setpoints()[-1] == EXPECTED  # still controlling
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"
    assert state.attributes["latched_by"] == []
    breaker.failing = False
    await refresh(rig)  # the monitor works again: the alarm is known
    await rig.advance(10)
    assert ("setpoint", 0.0) not in rig.gateway.calls  # it only informs
    assert rig.state("sensor", "control_state").attributes["latched_by"] == []


async def test_a_lasting_control_step_error_is_logged_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """P-24: the control step failing at every step for five minutes is one ERROR with its trace
    (then DEBUG), and the first step without the error one INFO. A new failure after that is a
    new streak: logged again."""
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    original = type(unit)._async_step

    async def broken(self: Any, now: float) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(type(unit), "_async_step", broken)
    await rig.advance(300)
    assert _logged(caplog, logging.ERROR, "control step failed") == 1
    failure = next(r for r in caplog.records if "control step failed" in r.getMessage())
    assert failure.exc_info is not None  # with the trace
    monkeypatch.setattr(type(unit), "_async_step", original)
    await rig.advance(30)
    assert _logged(caplog, logging.INFO, "control step works again") == 1
    assert _logged(caplog, logging.ERROR, "control step failed") == 1
    monkeypatch.setattr(type(unit), "_async_step", broken)
    await rig.advance(30)
    assert _logged(caplog, logging.ERROR, "control step failed") == 2


async def test_a_short_monitor_failure_changes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative: 290 s of failed refreshes, then the monitor works — no blocker, no alarm, no
    issue and no hand-back; control keeps writing."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    breaker = break_monitor(monkeypatch)
    breaker.failing = True
    await refresh(rig)
    count = len(rig.gateway.calls)
    await rig.advance(290)
    breaker.failing = False
    await refresh(rig)  # 290 s of failures
    await rig.advance(600)
    assert ("setpoint", 0.0) not in rig.gateway.calls[count:]
    assert rig.gateway.setpoints()[-1] == EXPECTED
    assert "monitor_failed" not in blockers(rig)
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "off"
    assert issue(rig, "monitor_failed") is None


async def test_a_flapping_monitor_still_hands_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nine refreshes in ten fail, one every 20 s: no run of failures lasts five minutes (180 s
    here), yet together they cover five minutes within ten, and control hands back then — not
    earlier."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    breaker = break_monitor(monkeypatch)
    first = dt_util.utcnow().timestamp()
    for i in range(30):
        breaker.failing = i % 10 != 9
        await refresh(rig)
        await rig.advance(20)
        if 0.0 in rig.gateway.setpoints():
            break
    assert 0.0 in rig.gateway.setpoints()
    handed_at = rig.gateway.times[rig.gateway.setpoints().index(0.0)]
    assert handed_at == first + 320  # 180 s, 20 s good, then 120 s more
    longest = run = 0.0
    for (t, failed), (t_next, _) in pairwise(breaker.runs):
        run = run + (t_next - t) if failed else 0.0
        longest = max(longest, run)
    assert longest < 300
    assert "monitor_failed" in blockers(rig)


async def test_one_failed_refresh_every_five_minutes_never_hands_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative for a flapping monitor: a single failed refresh every five minutes, for half an
    hour, never adds up to five minutes within ten."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    breaker = break_monitor(monkeypatch)
    count = len(rig.gateway.calls)
    for _ in range(6):
        # The clock's analysis runs in the background and ends with a refresh of its own: let
        # one still running finish first, so the one failed refresh is the test's alone — none
        # can start before the clock moves again (Z1).
        await rig.hass.async_block_till_done(wait_background_tasks=True)
        breaker.failing = True
        await refresh(rig)
        breaker.failing = False
        await rig.advance(300)
    assert sum(failed for _, failed in breaker.runs) == 6
    assert ("setpoint", 0.0) not in rig.gateway.calls[count:]
    assert "monitor_failed" not in blockers(rig)
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "off"


async def test_the_monitor_recovered_note_goes_when_control_is_switched_off(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answer I's information note stays through a reload of the entry, and goes when the user
    switches control off."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    breaker = break_monitor(monkeypatch)
    breaker.failing = True
    await refresh(rig)
    await rig.advance(300)
    breaker.failing = False
    await refresh(rig)
    await rig.advance(60)
    note = issue(rig, "monitor_failed")
    assert note is not None
    assert note.translation_key == "monitor_recovered"
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(20)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # control runs again after the reload
    kept = issue(rig, "monitor_failed")
    assert kept is not None
    assert kept.translation_key == "monitor_recovered"
    await rig.switch(False)
    assert issue(rig, "monitor_failed") is None


async def test_a_monitor_failing_before_control_holds_the_boiler_raises_no_issue(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing was handed back, so no repair issue: the alarm and the blocker show it. Switching
    control on waits for the monitor instead of being refused, writes nothing meanwhile, and
    control takes the boiler once the monitor works again — with no note either."""
    await start(rig)
    breaker = break_monitor(monkeypatch)
    breaker.failing = True
    await refresh(rig)
    await rig.advance(300)
    assert "monitor_failed" in blockers(rig)
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "on"
    await rig.switch(True)  # not refused: the blocker passes on its own
    await rig.advance(60)
    assert rig.state("binary_sensor", "control").state == "on"
    assert rig.gateway.calls == []
    assert issue(rig, "monitor_failed") is None
    breaker.failing = False
    await refresh(rig)
    await rig.advance(60)
    assert rig.gateway.setpoints() == [EXPECTED]
    assert rig.state("binary_sensor", "alarm_monitor_failed").state == "off"
    assert issue(rig, "monitor_failed") is None


@pytest.mark.parametrize(
    "data", [{"since": 1768197600.0}, {"since": "not a time"}, None], ids=["known", "bad", "none"]
)
async def test_a_monitor_issue_left_by_the_last_run_becomes_the_note_when_control_resumes(
    rig: Rig, data: dict[str, Any] | None
) -> None:
    """A reload keeps the monitor's issue: once the new run's control holds the boiler, it becomes
    the note, from the failure's start the issue kept — unknown or unreadable, from when the
    issue was raised — to when the new run's monitor first worked."""
    entry = add_entry(rig, options(rig.zones))
    ir.async_create_issue(
        rig.hass,
        DOMAIN,
        f"monitor_failed_{entry.entry_id}",
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="monitor_failed",
        data=data,
    )
    raised = dt_util.utcnow().timestamp()
    await rig.advance(120)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    worked = dt_util.utcnow().timestamp()
    left = issue(rig, "monitor_failed")
    assert left is not None
    assert left.translation_key == "monitor_failed"  # control does not hold the boiler yet
    await rig.switch(True)
    note = issue(rig, "monitor_failed")
    assert note is not None
    assert note.translation_key == "monitor_recovered"
    since = 1768197600.0 if data == {"since": 1768197600.0} else raised
    assert note.translation_placeholders == {
        "since": local_minute(since),
        "until": local_minute(worked),
    }


async def test_removing_the_entry_deletes_the_monitor_issue(rig: Rig) -> None:
    await start(rig)
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    ir.async_create_issue(
        rig.hass,
        DOMAIN,
        f"monitor_failed_{entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="monitor_recovered",
        translation_placeholders={"since": "-", "until": "-"},
    )
    await rig.hass.config_entries.async_remove(entry_id)
    await rig.hass.async_block_till_done()
    assert ir.async_get(rig.hass).async_get_issue(DOMAIN, f"monitor_failed_{entry_id}") is None


# --- V7: stopping with an alarm (S-10, S-57, S-11; the user's answer H) --------------------------


def vt_central_boiler(rig: Rig, configured: bool, **changes: Any) -> None:
    """VT's central boiler as the thermostats VT handed over carry its settings (I12): set up
    with its commands on the helper, or not (unticked) — then it blocks control
    (``vt_central_boiler_not_set``); ``changes``: other settings."""
    settings = vt_central_settings(rig.zones.helper, use_central_boiler_feature=configured)
    rig.zones.stand_in.entry_infos = settings | changes


def vt_central_boiler_gone(rig: Rig) -> None:
    """The blocker of ``vt_central_boiler`` gone: VT's central boiler set up again. For tests
    about a blocker's end, where which blocker it was does not matter."""
    vt_central_boiler(rig, True)


def stopped_heating(rig: Rig) -> ir.IssueEntry | None:
    return issue(rig, "control_stopped_heating")


async def start_stopping_heating(rig: Rig, installation: str) -> FakeNumber:
    """Control on, where a hand-back stops heating: a stand-alone gateway, or a setpoint entity
    whose hand-back value is declared to stop heating."""
    number = FakeNumber(rig.hass)
    number.register()
    if installation == "standalone":
        await start(rig, topology="gateway_standalone")
    else:
        await start(rig, **held_entity(number, hand_back_value_effect="heating_stops"))
    await rig.switch(True)
    await rig.advance(30)
    return number


@pytest.mark.parametrize("installation", ["standalone", "value_stops_heating"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_blocker_that_stops_a_stand_alone_session_raises_an_issue(
    rig: Rig, caplog: pytest.LogCaptureFixture, installation: str
) -> None:
    """S-10: a hand-back stops heating here. A blocker that ends a session holding the boiler
    hands it back at once; still there a minute later, it raises the repair issue — an error,
    neither fixable nor persistent — once. Control resuming once the blocker is gone deletes
    it."""
    number = await start_stopping_heating(rig, installation)
    writes = len(number.writes)
    count = len(rig.gateway.calls)
    caplog.clear()
    vt_central_boiler(rig, False)
    await rig.advance(10)
    if installation == "standalone":
        assert rig.gateway.calls[count:] == HAND_BACK
    else:
        assert number.writes[writes:] == [LOWEST, 50.0]
    assert "vt_central_boiler_not_set" in blockers(rig)
    await rig.advance(50)
    assert stopped_heating(rig) is None  # not a minute yet
    await rig.advance(10)
    found = stopped_heating(rig)
    assert found is not None
    assert found.translation_key == "control_stopped_heating"
    assert found.severity is ir.IssueSeverity.ERROR
    assert not found.is_fixable
    assert not found.is_persistent
    await rig.advance(120)
    assert _logged(caplog, logging.WARNING, "stays stopped by vt_central_boiler_not_set") == 1
    vt_central_boiler_gone(rig)
    await rig.advance(10)
    assert rig.state("sensor", "control_state").state == "heating"  # control resumed
    assert stopped_heating(rig) is None


@pytest.mark.parametrize(
    "case",
    [
        "ha_starting",
        "control_error",
        "monitor_failed",
        "thermostat_takes_over",
        "device_decides",
        "cleared_within_a_minute",
    ],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_no_stopped_heating_issue_where_the_blocker_has_its_own_or_heating_goes_on(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """S-10, negatives: Home Assistant starting, an internal error (its own alarm) and the
    monitor failing (V6's own issue) raise no such issue; nor does any blocker where a
    thermostat or the device's own control takes over, nor one gone within the minute."""
    from homeassistant.core import CoreState

    number = FakeNumber(rig.hass)
    number.register()
    if case == "thermostat_takes_over":
        await start(rig, topology="gateway_with_thermostat")
    elif case == "device_decides":
        await start(rig, **held_entity(number))
    else:
        await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    await rig.advance(30)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    if case == "ha_starting":
        rig.hass.set_state(CoreState.starting)
        await rig.advance(10)
        assert blockers(rig) == ["ha_starting"]
    elif case == "control_error":
        original = control_module.loop_step

        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(control_module, "loop_step", broken)
        await rig.advance(10)
        monkeypatch.setattr(control_module, "loop_step", original)
    elif case == "monitor_failed":
        breaker = break_monitor(monkeypatch)
        breaker.failing = True
        await refresh(rig)
        await rig.advance(300)
        assert issue(rig, "monitor_failed") is not None  # V6's own
    else:
        vt_central_boiler(rig, False)
        await rig.advance(10)
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] != "vt"  # handed
    if case == "cleared_within_a_minute":
        await rig.advance(40)
        assert stopped_heating(rig) is None
        vt_central_boiler_gone(rig)  # gone within the minute
    await rig.advance(120)
    assert stopped_heating(rig) is None
    assert not unit.stored()["stopped_heating"]
    if case == "cleared_within_a_minute":
        assert rig.state("sensor", "control_state").state == "heating"  # control resumed
    if case == "ha_starting":
        rig.hass.set_state(CoreState.running)


@pytest.mark.parametrize("how", ["switched_off", "unloaded"])
async def test_the_stopped_heating_issue_goes_when_control_is_switched_off_or_unloaded(
    rig: Rig, how: str
) -> None:
    """S-10: the user switching control off clears it for good — nothing comes back while the
    blocker holds; the unit stopping takes the issue with it."""
    await start_stopping_heating(rig, "standalone")
    vt_central_boiler(rig, False)
    await rig.advance(70)
    assert stopped_heating(rig) is not None
    assert rig.entry is not None
    if how == "unloaded":
        assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
        await rig.hass.async_block_till_done()
        assert stopped_heating(rig) is None
        return
    await rig.switch(False)
    assert stopped_heating(rig) is None
    assert not rig.entry.runtime_data.control.stored()["stopped_heating"]
    await rig.advance(120)
    assert stopped_heating(rig) is None


@pytest.mark.parametrize("wish", ["on", "switched_off"])
async def test_the_stopped_heating_issue_comes_back_after_a_restart_while_the_blocker_holds(
    rig: Rig, hass_storage: dict[str, Any], wish: str
) -> None:
    """S-10 (the cautious reading, V7's report): the issue goes with the unit, but whether a
    blocker stopped heating is stored at once. The next run raises the issue again once a
    blocker has held for a minute; once control resumes, it is gone for good. Negative: after
    the user switched control off, nothing comes back."""
    await start_stopping_heating(rig, "standalone")
    vt_central_boiler(rig, False)
    await rig.advance(10)
    assert stored_control(hass_storage, rig)["stopped_heating"] is True
    if wish == "switched_off":
        await rig.switch(False)
        assert stored_control(hass_storage, rig)["stopped_heating"] is False
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert stopped_heating(rig) is None
    await rig.advance(40)
    assert stopped_heating(rig) is None  # not a minute yet
    await rig.advance(30)
    if wish == "switched_off":
        assert stopped_heating(rig) is None
        return
    assert stopped_heating(rig) is not None
    vt_central_boiler_gone(rig)
    await rig.advance(10)
    assert rig.state("sensor", "control_state").state == "heating"
    assert stopped_heating(rig) is None
    assert unit_of(rig).stored()["stopped_heating"] is False  # the next save stores it


@pytest.mark.parametrize("stored", [True, "unreadable", False, None])
async def test_a_stored_stopped_heating_is_read_cautiously(
    rig: Rig, hass_storage: dict[str, Any], stored: Any
) -> None:
    """Missing data: a stored flag that cannot be read counts as set — the issue then only
    follows while a blocker holds and the wish is on; none stored, none raised."""
    control: dict[str, Any] = {"enabled": True}
    if stored is not None:
        control["stopped_heating"] = stored
    vt_central_boiler(rig, False)
    await start_with_stored(rig, hass_storage, control, "0.2.2", topology="gateway_standalone")
    await rig.advance(70)
    assert rig.gateway.calls == []
    raised = stored in (True, "unreadable")
    assert (stopped_heating(rig) is not None) is raised


async def test_the_switch_says_vt_keeps_frost_protection_only_while_control_holds_the_boiler(
    rig: Rig,
) -> None:
    """S-57, stand-alone: VT, through the plugin, while its session controls (I12.10); after the
    hand-back — and before control ever took the boiler — the boiler's own, if it has one."""
    await start(rig, topology="gateway_standalone")
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == "boiler"
    await rig.switch(True)
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == "vt"
    await rig.advance(20)
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == "vt"
    await rig.switch(False)
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == "boiler"


@pytest.mark.parametrize(
    ("installation", "handed_back"),
    [
        ("gateway_standalone", "boiler"),
        ("gateway_with_thermostat", "thermostat"),
        ("own_control", "device"),  # a value declared to return the device's own control
        ("heating_stops", "boiler"),  # a value declared to stop heating
        ("timeout", "device"),  # the virtual topology: the device decides
    ],
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_the_switch_says_who_keeps_frost_protection(
    rig: Rig, installation: str, handed_back: str
) -> None:
    """S-57: ``frost_protection_by`` is ``vt`` while the session controls, and otherwise
    follows the hand-back's effect: ``thermostat``, ``boiler`` where it stops heating, or
    ``device`` where the device decides (and, once Y1 adds it, its own control resuming)."""
    number = FakeNumber(rig.hass)
    number.register()
    if installation.startswith("gateway"):
        await start(rig, topology=installation)
    elif installation == "timeout":
        await start(rig, **held_entity(number, write_type="expiring", hand_back="timeout"))
    else:
        await start(rig, **held_entity(number, hand_back_value_effect=installation))
    shown = rig.state("binary_sensor", "control").attributes
    assert shown["frost_protection_by"] == handed_back  # control has not taken the boiler
    await rig.switch(True)
    await rig.advance(10)
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == "vt"
    await rig.switch(False)
    await rig.advance(10)
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == handed_back


def room(rig: Rig, temperature: float | None, zone: str = "living") -> None:
    """VT reports the room at this temperature, not calling for heat."""
    rig.zones.set(zone, current_temperature=temperature, hvac_action="idle")


def in_frost(rig: Rig) -> str:
    return rig.state("binary_sensor", "alarm_handed_back_in_frost").state


async def test_handed_back_in_frost_raises_an_alarm(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """S-57: stand-alone with control off, nothing heats: a watched room below the frost limit
    raises the alarm at the next step; it holds below the release and goes at or above it. It
    is information only: nothing is written to the boiler."""
    await start(rig, topology="gateway_standalone")
    await rig.advance(10)
    assert in_frost(rig) == "off"
    room(rig, 4.0)
    await rig.advance(10)
    assert in_frost(rig) == "on"
    assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] == "boiler"
    assert _logged(caplog, logging.WARNING, "near freezing") == 1
    room(rig, 6.0)  # above the limit, below the release
    await rig.advance(10)
    assert in_frost(rig) == "on"
    room(rig, 7.5)
    await rig.advance(10)
    assert in_frost(rig) == "off"
    assert rig.gateway.calls == []  # it never starts heating
    room(rig, 6.0)
    await rig.advance(30)
    assert in_frost(rig) == "off"  # not raised again until below the limit


@pytest.mark.parametrize(
    "case", ["unknown", "lost_after", "thermostat", "no_topology", "controlling"]
)
async def test_handed_back_in_frost_negatives(rig: Rig, case: str) -> None:
    """S-57, negatives: a room whose temperature is not known is not counted — with none known
    the alarm cannot be judged: unknown at once where nothing was known before, a raised one
    held for an hour, then unknown (Y1, S-16); with a thermostat it never rises, nor where the
    hand-back's effect is not known (no topology: control is blocked anyway); while control
    holds the boiler it is off — and it rises once a switch-off hands the boiler back."""
    topology = {"thermostat": "gateway_with_thermostat", "no_topology": ""}.get(
        case, "gateway_standalone"
    )
    await start(rig, topology=topology)
    if case == "controlling":
        await rig.switch(True)
    room(rig, None if case == "unknown" else 4.0)
    if case == "controlling":
        # VT's frost preset makes the room call: the plugin heats for VT (I12.10).
        rig.zones.set(
            "living", current_temperature=4.0, hvac_action="heating", valve_open_percent=60
        )
    await rig.advance(30)
    if case == "lost_after":
        assert in_frost(rig) == "on"
        # The zone drops out: no watched room is known, so the alarm holds for an hour, then
        # shows unknown (S-16); control's state names the zone it cannot see.
        rig.zones.set("living", "unavailable", current_temperature=None)
        await rig.advance(10)
        assert in_frost(rig) == "on"
        living = rig.zones.entities["living"]
        assert rig.state("sensor", "control_state").attributes["unknown_zones"] == [living]
        await rig.advance(3600, step=300)
        assert in_frost(rig) == "unknown"
        return
    if case == "unknown":
        assert in_frost(rig) == "unknown"  # nothing known from the start: unknown at once
        return
    assert in_frost(rig) == "off"
    if case == "controlling":
        assert rig.state("sensor", "control_state").state == "heating"  # VT's call heats
        await rig.switch(False)
        await rig.advance(10)
        assert in_frost(rig) == "on"
    elif case in ("thermostat", "no_topology"):
        await rig.advance(120)
        assert in_frost(rig) == "off"
    if case == "no_topology":
        assert "no_topology" in blockers(rig)
        assert rig.state("binary_sensor", "control").attributes["frost_protection_by"] is None


@pytest.mark.parametrize("latched_by", [["outside_change"], ["pressure_low"], None])
async def test_a_stored_step_aside_raises_its_issue_at_start(
    rig: Rig, hass_storage: dict[str, Any], latched_by: list[str] | None
) -> None:
    """V7: while a stored latch from stepping aside holds, each start raises the entry's latch
    issue again. A latch an earlier version stored for an alarm that now only informs holds
    all the same, and gets the entry's one latch issue naming it (decision 7, Y1: every latch,
    whatever its cause). Negative: with no latch, an issue an earlier run left is deleted."""
    stored: dict[str, Any] = {}
    if latched_by is not None:
        stored = {"latched": True, "latched_by": latched_by}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones, topology="gateway_standalone"),
    )
    entry.add_to_hass(rig.hass)
    ir.async_create_issue(  # left by an earlier run
        rig.hass,
        DOMAIN,
        f"control_latched_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="control_latched",
    )
    seed_stores(hass_storage, entry, stored, "0.2.2")
    await set_up(rig, entry)
    found = issue(rig, "control_latched")
    if latched_by == ["outside_change"]:
        assert found is not None
        assert found.severity is ir.IssueSeverity.ERROR  # stand-alone: heating stops
        assert found.translation_key == "control_latched"
        assert found.translation_placeholders == {"target": "-", "value": "-"}  # not stored
    elif latched_by == ["pressure_low"]:
        assert found is not None
        assert found.translation_key == "control_latched_other"
        assert found.translation_placeholders == {"alarm": "pressure_low"}
        assert found.severity is ir.IssueSeverity.ERROR
    else:
        assert found is None


async def test_removing_control_from_the_options_deletes_the_latch_issue(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Without control in the options no switch is left to clear the latch: its issue goes."""
    entry_options = options(rig.zones)
    del entry_options["control"]
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
    ir.async_create_issue(
        rig.hass,
        DOMAIN,
        f"control_latched_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="control_latched",
    )
    seed_stores(hass_storage, entry, {"latched": True, "latched_by": ["outside_change"]}, "0.2.2")
    await set_up(rig, entry)
    assert issue(rig, "control_latched") is None


@pytest.mark.parametrize("effect", ["own_control", "heating_stops"])
async def test_stepping_aside_makes_the_whole_safe_hand_back(
    rig: Rig, caplog: pytest.LogCaptureFixture, effect: str
) -> None:
    """The user's answer H: at the step-aside the held setpoint entity gets the lowest water
    temperature over the other controller's 60 °C, the heating switch goes on where the effect
    allows (left as it is where the hand-back stops heating), then the release. The other
    controller writes its 60 °C again: V5 judges the target taken by another controller — no
    retry every minute — and raises no ``hand_back_taken_by_other`` beside the latch issue."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    control = held_entity(
        number, hand_back_value_effect=effect, ch_entity=switch.entity_id, ch_write_type="held"
    )
    await start(rig, **control)
    await rig.switch(True)
    await rig.advance(30)
    assert number.writes == [EXPECTED]
    number.forced = 60.0  # another controller writes its value, and again over every write
    number.value = 60.0
    number.publish(60.0)
    await rig.advance(20)  # held two steps (M10)
    assert number.writes == [EXPECTED, EXPECTED]  # the one rewrite
    switch_writes = len(switch.writes)
    start_at = len(rig.services)
    for _ in range(20):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    parts = [
        (service, data.get("value"))
        for domain, service, data in rig.services[start_at:]
        if domain in ("input_number", "input_boolean")
    ]
    if effect == "own_control":
        assert parts == [("set_value", LOWEST), ("turn_on", None), ("set_value", 50.0)]
        assert switch.writes[switch_writes:] == [True]
    else:
        assert parts == [("set_value", LOWEST), ("set_value", 50.0)]  # heating left as it is
        assert switch.writes[switch_writes:] == []
    assert number.value == 60.0  # the other controller's value again
    writes = len(number.writes)
    unit = unit_of(rig)
    await rig.advance(60)  # the first retry check: a third value, the write held back
    assert len(number.writes) == writes
    await rig.advance(60)  # the second, a minute later: another controller holds it
    assert not unit.hand_back_owed
    await rig.advance(180)
    assert len(number.writes) == writes  # never written again
    assert hand_back_shown(rig) == "taken_by_other"
    assert issue(rig, "hand_back_taken_by_other") is None
    found = issue(rig, "control_latched")
    assert found is not None
    stops = effect == "heating_stops"
    assert found.severity is (ir.IssueSeverity.ERROR if stops else ir.IssueSeverity.WARNING)


async def test_stepping_aside_on_a_gateway_makes_the_whole_safe_hand_back(rig: Rig) -> None:
    """The user's answer H on a gateway: CS=<lowest>, CH=1, CS=0 over the other controller's
    60 °C; its value read back afterwards shows the release (the override is gone), so nothing
    is retried."""
    await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.forced = 60.0
    for _ in range(20):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert rig.gateway.calls[-3:] == HAND_BACK
    await rig.advance(10)  # the gateway's next report after the command shows it (PB-30)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert not unit_of(rig).hand_back_owed
    count = len(rig.gateway.calls)
    await rig.advance(180)
    assert len(rig.gateway.calls) == count
    assert issue(rig, "control_latched") is not None
    assert issue(rig, "hand_back_taken_by_other") is None


async def test_removing_the_entry_deletes_the_v7_issues(rig: Rig) -> None:
    await start(rig)
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    for key in ("control_stopped_heating", "control_latched"):
        ir.async_create_issue(
            rig.hass,
            DOMAIN,
            f"{key}_{entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=key,
        )
    await rig.hass.config_entries.async_remove(entry_id)
    await rig.hass.async_block_till_done()
    registry = ir.async_get(rig.hass)
    for key in ("control_stopped_heating", "control_latched"):
        assert registry.async_get_issue(DOMAIN, f"{key}_{entry_id}") is None


# --- X1: the guards' memory, decision 6's classes, answer O, the external switch, the return ---


async def test_the_one_rewrite_is_remembered_across_a_clean_reload(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P-06, T-01 (integration half), M20: one rewrite; the entry reloads cleanly — the stop's
    own hand-back keeps the guards' memory — and another controller writes again within the day:
    no second rewrite; the plugin steps aside with the whole safe hand-back, the latch and the
    entry's one latch issue."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    rig.gateway.forced = 60.0
    await rig.advance(20)  # held two steps: the one rewrite
    rewritten = unit_of(rig)._session.loop.setpoint.rewritten_at
    assert rewritten is not None
    rig.gateway.forced = None
    await rig.advance(20)  # ours again
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert stored_control(hass_storage, rig)["rewritten_at"] == rewritten  # after the stop
    await rig.advance(20)  # control resumes
    assert unit_of(rig)._session.loop.setpoint.rewritten_at == rewritten
    rig.gateway.forced = 60.0  # the other controller again, the same day
    for _ in range(10):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert unit_of(rig)._session.loop.setpoint.rewritten_at == rewritten  # no second rewrite
    assert rig.gateway.calls[-3:] == HAND_BACK  # the whole safe hand-back
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    assert issue(rig, "control_latched") is not None


@pytest.mark.parametrize("ignored", ["off", "on"])
async def test_an_ignored_heating_switch_raises_write_ignored(
    rig: Rig, hass_storage: dict[str, Any], ignored: str
) -> None:
    """T-04 (P-09) with answer O and decision 4 of 0.2.3 (SB-03): OTGW with a heating echo and a
    thermostat, the setpoint confirmed. The echo never follows CH=0 — "on" before the plugin and
    after each of the session's first three sends of "off" — or never follows CH=1 — "off"
    throughout, the boiler or its echo not taking "heating on": "write ignored" names the
    heating switch and, at the next step, control is blocked and the boiler handed back
    (CS=<lowest>, CH=1, CS=0) whatever alarm reaction is stored; the latch names
    ``heating_off_ignored`` or ``heating_on_ignored``, and so do the entry's latch issue — a
    warning where "off" was refused, as the thermostat takes over; an error where "on" was, as
    the plugin cannot make the boiler heat — and a blocker. Nothing is written after the
    hand-back, VT's next command the other way included (before, for "on": no latch, the switch
    never written again, so VT's later "off" never reached the boiler). The latch survives a
    reload and clears only when control is switched off and on."""
    stays_on = ignored == "off"
    cause = f"heating_{ignored}_ignored"
    rig.gateway.forced_ch = stays_on  # the echo stays where it was before the plugin
    rig.gateway.publish()
    if stays_on:  # no zone calls: control asks "off"
        rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await start(rig, ch_confirmed_entity=CH_ECHO, alarm_reactions={"write_ignored": "info"})
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(350)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"  # two attempts
    await rig.advance(10)  # the third, 360 s after the first send
    alarm = rig.state("binary_sensor", "alarm_write_ignored")
    assert alarm.state == "on"
    assert alarm.attributes["targets"] == ["heating"]
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    blockers = rig.state("binary_sensor", "control").attributes["blockers"]
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == [cause]
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert cause in blockers
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == f"control_latched_{cause}"
    severity = ir.IssueSeverity.WARNING if stays_on else ir.IssueSeverity.ERROR
    assert found.severity is severity
    assert issue(rig, "write_ignored_no_heat") is None  # the latch's issue says it
    assert stored_control(hass_storage, rig)["latched_by"] == [cause]
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    count = len(rig.gateway.calls)
    if stays_on:  # VT's next command, the other way
        rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    else:
        rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # nothing written but the hand-back
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(30)
    assert rig.state("sensor", "control_state").attributes["latched_by"] == [cause]
    assert cause in rig.state("binary_sensor", "control").attributes["blockers"]
    assert issue(rig, "control_latched") is not None
    alarm = rig.state("binary_sensor", "alarm_write_ignored")
    assert alarm.state == "on"  # the alarm with the latch, through the reload
    assert alarm.attributes["targets"] == ["heating"]
    count = len(rig.gateway.calls)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # nothing written
    await rig.switch(False)
    assert issue(rig, "control_latched") is None
    await rig.switch(True)  # the user's off and on: a new session tries the switch again
    assert cause not in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.state("sensor", "control_state").attributes["latched_by"] == []


@pytest.mark.parametrize("heating_target", [True, False], ids=["heating", "setpoint_only"])
async def test_write_ignored_clears_per_guard(rig: Rig, heating_target: bool) -> None:
    """P-09: "write ignored" follows each guard. The heating switch's "on" ignored from the
    start (the switch stays off) and the setpoint confirmed: the alarm names the heating switch —
    the setpoint's confirmation does not clear it — and stays on with the latch that follows
    (decision 4 of 0.2.3); a new session (off, then on) with the heating value taken clears
    it. Negative: a path without a heating target — the setpoint alone decides."""
    if heating_target:
        rig.gateway.forced_ch = False
        rig.gateway.publish()
        await start(rig, ch_confirmed_entity=CH_ECHO)
    else:
        rig.gateway.echo = False  # the setpoint is never taken
        await start(rig)
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(360 if heating_target else 370)
    alarm = rig.state("binary_sensor", "alarm_write_ignored")
    assert alarm.state == "on"
    assert alarm.attributes["targets"] == (["heating"] if heating_target else ["setpoint"])
    if heating_target:
        setpoint = rig.state("sensor", "control_setpoint")
        assert setpoint.attributes["confirmation"] == "confirmed_by_gateway"
        await rig.advance(10)
        state = rig.state("sensor", "control_state")
        assert state.attributes["latched_by"] == ["heating_on_ignored"]
        await rig.advance(300)
        assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
        rig.gateway.forced_ch = None
    else:
        rig.gateway.echo = True
    await rig.switch(False)
    await rig.advance(10)
    await rig.switch(True)
    await rig.advance(130)  # the value held 120 s
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"


@pytest.mark.parametrize("case", ["ignored", "outage", "unknown", "once_taken"])
async def test_heating_off_ignored_from_the_start_blocks_and_hands_back(
    rig: Rig, case: str
) -> None:
    """Answer O on the entity path, with a held heating switch as its own read-back: it stays on
    after each of the session's first three sends of "off" — blocked and handed back, with the
    blocker; switching control off and on clears it and a new session tries the switch again.
    Negatives: the switch unavailable within an attempt (a trace: that attempt does not count,
    the block comes later); a read-back unknown throughout (nothing judged, no blocker); the
    switch refusing "off" after it once took "off" in this session (not "from the start")."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass, stuck_on=case != "once_taken")  # takes "on", not "off"
    switch.register()
    echo = switch.entity_id
    if case == "unknown":
        echo = "input_boolean.fake_ch_echo"
        rig.hass.states.async_set(echo, "unknown")
    control = held_entity(
        number, ch_entity=switch.entity_id, ch_write_type="held", ch_confirmed_entity=echo
    )
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await start(rig, **control)
    await rig.advance(310)
    await rig.switch(True)
    if case == "outage":
        await rig.advance(50)
        switch.set_available(False)
        await rig.advance(10)
        switch.set_available(True)
    if case == "once_taken":
        await rig.advance(150)  # "off" taken and held: the start phase is over
        assert not switch.on
        rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
        await rig.advance(20)
        switch.stuck_on = True  # from now on it will not go off
        rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(400)
    blockers = rig.state("binary_sensor", "control").attributes["blockers"]
    if case == "ignored":
        assert rig.state("sensor", "control_state").state == "handed_back"
        assert "heating_off_ignored" in blockers
        assert switch.on  # the hand-back left heating on: the device's own control resumes
        await rig.switch(False)
        await rig.switch(True)
        assert (
            "heating_off_ignored"
            not in rig.state("binary_sensor", "control").attributes["blockers"]
        )
        assert switch.writes[-1] is False  # tried again
        return
    assert "heating_off_ignored" not in blockers
    assert rig.state("sensor", "control_state").state == "idle"
    if case == "outage":
        await rig.advance(400)  # three counted attempts after the trace
        assert rig.state("sensor", "control_state").state == "handed_back"
        assert "heating_off_ignored" in rig.state("binary_sensor", "control").attributes["blockers"]


@pytest.mark.parametrize("case", ["frozen", "unknown", "unavailable", "once_taken"])
async def test_heating_on_ignored_from_the_start_blocks_and_hands_back(rig: Rig, case: str) -> None:
    """Decision 4 of 0.2.3 (SB-03) on the entity path: a held heating switch that takes every
    command, its read-back — a status entity picked for it — frozen at "off": "on" is never read
    back after each of the session's first three sends — blocked and handed back, with the
    blocker and the latch's error-level issue; VT's later "off" is not written but through the
    hand-back (before: the switch never written again, so heating stayed enabled for the session,
    with no latch); switching control off and on clears it. Negatives: the read-back unknown or
    unavailable throughout (nothing judged: no blocker, VT's "off" still written); "on" taken and
    held once, then not shown (a lost command, not "from the start": no such blocker)."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass, on=False)
    switch.register()
    echo = switch.entity_id
    if case != "once_taken":
        echo = "input_boolean.fake_ch_echo"
        rig.hass.states.async_set(echo, "off" if case == "frozen" else case)
    control = held_entity(
        number, ch_entity=switch.entity_id, ch_write_type="held", ch_confirmed_entity=echo
    )
    await start(rig, **control)
    await rig.advance(310)
    await rig.switch(True)
    if case == "once_taken":
        await rig.advance(150)  # "on" taken and held: the start phase is over
        assert switch.on
        switch.stuck_off = True  # from now on it will not go on
        switch.on = False
        switch.publish()
    await rig.advance(400)
    state = rig.state("sensor", "control_state")
    blockers = rig.state("binary_sensor", "control").attributes["blockers"]
    if case != "frozen":
        assert "heating_on_ignored" not in blockers
        assert "heating_on_ignored" not in state.attributes["latched_by"]
        if case == "once_taken":
            return
        assert state.state == "heating"
        rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
        await rig.advance(20)
        assert switch.writes[-1] is False  # VT's "off" written
        return
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["heating_on_ignored"]
    assert "heating_on_ignored" in blockers
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_heating_on_ignored"
    assert found.severity is ir.IssueSeverity.ERROR  # though the device's own control takes over
    count = len(switch.writes)
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(120)
    assert len(switch.writes) == count  # VT's "off": nothing written but the hand-back
    await rig.switch(False)
    await rig.switch(True)
    assert "heating_on_ignored" not in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.state("sensor", "control_state").attributes["latched_by"] == []


@pytest.mark.parametrize("release", ["shown", "refused"])
async def test_heating_on_ignored_writes_the_heating_switch_once_in_the_hand_back(
    rig: Rig, release: str
) -> None:
    """Decision 4 of 0.2.3 (SB-03; finding 1 of the part-1 check D) on the entity path: a held
    heating switch that will not go on and is its own read-back, a hand-back that gives the
    boiler its own control back. "On" ignored from the start latches and hands back; the
    hand-back writes the switch "on" once — its rest state, as a relay steps aside — and leaves
    it out of the debt: never written again, and no owed issue for it. Before: "on" every
    minute for good, with an error-level owed issue beside the latch's. Negative (``refused``):
    the setpoint's release, refused by the device, is still sent again every minute, with the
    owed issue, until it shows; the switch is not written again meanwhile."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass, on=False, stuck_off=True)
    switch.register()
    control = held_entity(
        number,
        ch_entity=switch.entity_id,
        ch_write_type="held",
        ch_confirmed_entity=switch.entity_id,
    )
    await start(rig, **control)
    await rig.advance(310)
    await rig.switch(True)
    assert EXPECTED != 50.0  # the hand-back value, which the device may refuse below
    number.refuse = 50.0 if release == "refused" else None
    for _ in range(60):
        before = len(switch.writes)
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    else:
        pytest.fail("not handed back")
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["heating_on_ignored"]
    assert switch.writes[before:] == [True]  # the hand-back's "on", once
    written, lowest = len(switch.writes), len(number.writes)
    await rig.advance(1800)
    assert len(switch.writes) == written  # never again
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_heating_on_ignored"
    unit = unit_of(rig)
    if release == "shown":
        assert not unit.hand_back_owed
        assert issue(rig, "hand_back_owed") is None
        return
    assert unit.hand_back_owed
    assert issue(rig, "hand_back_owed") is not None
    assert len(number.writes) - lowest >= 29  # the lowest, written with each retry of the release
    number.refuse = None
    await rig.advance(60)
    assert number.value == 50.0
    assert not unit.hand_back_owed
    assert issue(rig, "hand_back_owed") is None
    assert len(switch.writes) == written


@dataclass
class EchoedSwitch(FakeSwitch):
    """A held heating switch with a status entity of its own that follows it — an ESPHome
    master's CH enable and its "CH active" status, say."""

    echo: str = "binary_sensor.fake_ch_echo"

    def publish(self) -> None:
        super().publish()
        shown = ("on" if self.on else "off") if self.available else "unavailable"
        self.hass.states.async_set(self.echo, shown)


@dataclass
class LateEchoedSwitch(EchoedSwitch):
    """A held heating switch whose status entity reports each change ``lag_s`` late, in order —
    a scripted or cloud-backed switch (Z4R3-01)."""

    lag_s: float = 90.0
    pending: list[Callable[[], None]] = field(default_factory=list)

    def publish(self) -> None:
        FakeSwitch.publish(self)
        shown = ("on" if self.on else "off") if self.available else "unavailable"
        if self.lag_s <= 0.0 or self.hass.states.get(self.echo) is None:
            self.hass.states.async_set(self.echo, shown)
            return

        @callback
        def show(_now: datetime) -> None:
            self.pending.pop(0)
            self.hass.states.async_set(self.echo, shown)

        self.pending.append(async_call_later(self.hass, self.lag_s, show))

    def stop(self) -> None:
        """The test is over: the reports still on their way are dropped, later ones prompt."""
        for cancel in self.pending:
            cancel()
        self.pending.clear()
        self.lag_s = 0.0


@pytest.mark.parametrize("lag_s", [90.0, 115.0])
async def test_a_late_heating_echo_beside_short_vt_pulses_is_never_judged(
    rig: Rig, lag_s: float
) -> None:
    """K4.3 (Z4R3-01): entity path, a held heating switch, off before the plugin, whose status
    reports each change 90 or 115 s late, in order, while VT pulses heating on for 60 s every 5
    minutes — and from the second hour a second zone's pulse 40 s after the first — for four
    hours. The plugin's own late echo is never judged: a report older than a send, or one that
    may still be the echo of an earlier send, is not its read-back. No rewrite, no step aside,
    no latch, no lost command (before: another controller within the first hour)."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = LateEchoedSwitch(rig.hass, on=False, lag_s=lag_s)
    switch.register()
    await start(
        rig,
        **held_entity(
            number,
            ch_entity=switch.entity_id,
            ch_write_type="held",
            ch_confirmed_entity=switch.echo,
        ),
    )
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    pulsing: bool | None = None
    for step in range(4 * 360):
        phase = step * 10 % 300
        pulse = phase < 60 or (step >= 360 and 100 <= phase < 160)
        if pulse is not pulsing:
            pulsing = pulse
            if pulse:
                rig.zones.set(
                    "living", hvac_action="heating", valve_open_percent=60, on_percent=0.6
                )
            else:
                rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
        await rig.advance(10)
        assert rig.state("sensor", "control_state").state != "handed_back", step
    switch.stop()
    assert switch.writes.count(True) > 40  # pulsed all along
    switch_guard = unit_of(rig)._session.loop.switch
    assert switch_guard.baseline == 0.0  # "off" before the plugin
    assert switch_guard.rewritten_at is None
    assert switch_guard.blocked is None
    assert issue(rig, "control_latched") is None
    assert rig.state("binary_sensor", "alarm_commands_lost").state == "off"


async def test_each_guard_is_told_when_its_read_back_last_changed(rig: Rig) -> None:
    """Z4R3-01 (K4.3): each guard gets its read-back's last change, as Home Assistant shows it —
    the setpoint's and heating on/off's — so a report older than a send is never taken for that
    send's read-back. A read-back not there: not known."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = EchoedSwitch(rig.hass)
    switch.register()
    await start(
        rig,
        **held_entity(
            number,
            ch_entity=switch.entity_id,
            ch_write_type="held",
            ch_confirmed_entity=switch.echo,
        ),
    )
    await rig.advance(30)
    now = dt_util.utcnow().timestamp()
    setpoint, heating = unit_of(rig)._contexts(now, None)
    for context, entity in ((setpoint, number.entity_id), (heating, switch.echo)):
        state = rig.hass.states.get(entity)
        assert state is not None
        assert context.reported_at == state.last_changed.timestamp()
        assert context.reported_at < now
    rig.hass.states.async_remove(switch.echo)
    _setpoint, heating = unit_of(rig)._contexts(now, None)
    assert heating.reported_at is None


async def test_heating_switched_by_hand_after_the_plugin_toggled_it_steps_aside(
    rig: Rig,
) -> None:
    """Z4-01 (decision 6, answer E): entity path, a held heating switch with its own echo. The
    plugin has switched heating both ways in the session and commands "on", the state from
    before it. A person switches heating off more than 120 s after the plugin's last change:
    held two steps, another controller — "on" written once again; switched off again the same
    day, the plugin steps aside with the safe hand-back, the latch and its issue. The heating
    confirmation is never shown confirmed while the echo shows "off"."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = EchoedSwitch(rig.hass)
    switch.register()
    await start(
        rig,
        **held_entity(
            number,
            ch_entity=switch.entity_id,
            ch_write_type="held",
            ch_confirmed_entity=switch.echo,
        ),
    )
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(150)  # "on" confirmed and held: the start phase is over
    assert switch.on
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(200)
    assert not switch.on  # the plugin switched heating off ...
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    for _ in range(6):
        await rig.advance(10)
        if switch.on:
            break
    assert switch.on  # ... and on again: its previous state is now "off"
    await rig.advance(150)  # more than 120 s after that change
    state = rig.state("sensor", "control_state")
    assert state.attributes["heating_confirmation"] == "confirmed"
    switch_guard = unit_of(rig)._session.loop.switch
    assert switch_guard.baseline == 1.0  # "on" before the plugin
    assert switch_guard.rewritten_at is None

    def shown_while_off() -> list[str]:
        echo = rig.hass.states.get(switch.echo)
        assert echo is not None
        if echo.state != "off":
            return []
        return [rig.state("sensor", "control_state").attributes["heating_confirmation"]]

    switch.on = False  # a person switches heating off for maintenance
    switch.publish()
    ons = switch.writes.count(True)
    shown: list[str] = []
    for _ in range(2):
        await rig.advance(10)
        shown += shown_while_off()
    assert switch.writes.count(True) == ons + 1  # held two steps: the one rewrite
    assert switch.on
    assert unit_of(rig)._session.loop.switch.rewritten_at is not None
    assert rig.state("sensor", "control_state").state != "handed_back"
    await rig.advance(60)
    switch.on = False  # switched off again the same day
    switch.publish()
    ons = switch.writes.count(True)
    for _ in range(4):
        await rig.advance(10)
        shown += shown_while_off()
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["outside_change"]
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert issue(rig, "control_latched") is not None
    assert "confirmed" not in shown
    assert switch.writes.count(True) <= ons + 1  # at most the hand-back's "heating on", once


async def _external_switch_rig(rig: Rig) -> tuple[FakeNumber, FakeSwitch]:
    """Control through a held setpoint entity, given back by switching off an external-control
    switch declared held; past the five minutes the unit's own start counts as a trace."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="held",
        hand_back="switch",
        hand_back_entity=external.entity_id,
        hand_back_entity_write_type="held",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.advance(310)
    await rig.switch(True)
    assert external.on  # control took the boiler
    await rig.advance(30)
    return number, external


@pytest.mark.usefixtures("low_setpoint_off")
async def test_the_external_control_switch_switched_off_steps_aside_without_a_rewrite(
    rig: Rig,
) -> None:
    """M14: the external-control switch goes off while it stayed available (no trace within
    five minutes): another controller — no "on" written back, at once the whole safe hand-back
    (its release counts as done: the switch is already off), the latch and the entry's one
    latch issue; left alone afterwards."""
    number, external = await _external_switch_rig(rig)
    ons = external.writes.count(True)
    external.on = False  # a person, an automation or its own button
    external.publish()
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["outside_change"]
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert external.writes.count(True) == ons  # no fight
    assert number.writes[-1] == LOWEST  # the lowest water temperature, first
    assert not unit_of(rig).hand_back_owed  # the switch, off, shows the release
    found = issue(rig, "control_latched")
    assert found is not None
    # PB-76: a switch's own text, with no raw "on"/"off" state in a translated sentence.
    assert found.translation_key == "control_latched_switch"
    assert found.translation_placeholders == {"target": external.entity_id}
    await rig.advance(180)
    assert external.writes.count(True) == ons


@pytest.mark.parametrize("minutes", [4, 6])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_the_external_control_switch_off_after_its_device_restart_is_switched_on_again(
    rig: Rig, minutes: int
) -> None:
    """M15: the switch was unavailable within the five minutes before it reads off — its device
    restarted: switched on again at the next step, counted as a lost command, no alarm.
    Negative: unavailable six minutes before — another controller: the plugin steps aside."""
    _number, external = await _external_switch_rig(rig)
    external.set_available(False)
    await rig.advance(10)
    external.set_available(True)  # back on
    await rig.advance(minutes * 60 - 10)
    ons = external.writes.count(True)
    external.on = False
    external.publish()
    await rig.advance(10)
    if minutes == 4:
        assert external.writes.count(True) == ons + 1  # switched on again
        assert external.on
        assert rig.state("sensor", "control_state").state != "handed_back"
        assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
        assert [who for _t, who in unit_of(rig)._session.loop.losses] == ["external"]
    else:
        assert external.writes.count(True) == ons
        assert rig.state("sensor", "control_state").state == "handed_back"
        assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]


@pytest.mark.parametrize("write_type", ["expiring", "held"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_external_switch_never_shown_on_is_judged_after_the_timeout(
    rig: Rig, write_type: str
) -> None:
    """Z4R2-03 for the external-control switch: control turns it on, and it never shows "on"
    (it does not take it, or something puts it back within a step). Within 5 minutes nothing is
    judged (K4.3, decided by the user 2026-10-03: the same window as heating on/off's previous
    state); after them, it reads off with no trace of an outage — another controller, as M14
    says: the plugin steps aside, no fight, instead of turning it on again every keep-alive for
    ever, unseen."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(
        rig.hass, entity_id="input_boolean.fake_external", on=False, stuck_off=True
    )
    external.register()
    await start(rig, **switch_method(number, external.entity_id, write_type))
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    assert external.writes == [True]  # turned on, but it stays off
    await rig.advance(290)
    assert rig.state("sensor", "control_state").state != "handed_back"  # within 5 minutes
    await rig.advance(30)
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["outside_change"]
    ons = external.writes.count(True)
    await rig.advance(120)
    assert external.writes.count(True) == ons  # left alone


@pytest.mark.parametrize("silent", [True, False], ids=["plugin_silent", "kept_alive"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_an_expiring_external_switch_lapsing_in_the_plugins_silence_is_turned_on_again(
    rig: Rig, silent: bool
) -> None:
    """Z4-09 (M17 for the external-control switch): declared expiring, it lapses unless the plugin
    renews it. The boiler link goes stale short of a loss — its flow from a device of its own —
    so nothing is written, the switch's renewal included; the switch lapses with no trace after
    more than two keep-alives of that silence: the plugin's own lapse — turned on again once
    control writes, not counted, no outside change, no latch. Negative: switched off while the
    plugin keeps renewing it — another controller: the plugin steps aside."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    external.register()
    await start(rig, **switch_method(number, external.entity_id, "expiring"))
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(60)
    assert external.on
    if silent:
        rig.flow = None  # stale, short of a loss: nothing is written
        await rig.advance(90)  # no renewal for more than two keep-alives
    ons = external.writes.count(True)
    external.on = False  # its own lapse — or, kept alive, a person
    external.publish()
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    if not silent:
        assert state.state == "handed_back"
        assert state.attributes["latched_by"] == ["outside_change"]
        assert external.writes.count(True) == ons  # no fight
        return
    assert state.state != "handed_back"
    await rig.advance(60)  # still stale: nothing written yet
    assert external.writes.count(True) == ons
    rig.flow = 35.0  # the link is back: control writes
    await rig.advance(20)
    assert external.writes.count(True) == ons + 1  # turned on again
    assert external.on
    assert rig.state("sensor", "control_state").state != "handed_back"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert unit_of(rig)._session.loop.losses == ()  # its own lapse: not counted
    assert issue(rig, "control_latched") is None


@pytest.mark.parametrize("case", ["returns", "option_off", "unknown"])
async def test_the_return_by_itself_after_an_hour_without_a_foreign_value(
    rig: Rig, case: str
) -> None:
    """Decision 6's optional return: the plugin stepped aside from another controller; the
    read-back then shows only the hand-back state (stand-alone: the released override, 0) for an
    hour — control resumes as a new session, the latch and its issue go, the one rewrite stays.
    With the option off it stays aside after two hours. Negative: the read-back unknown for the
    hour — no return."""
    rig.gateway.thermostat = 0.0  # stand-alone: without the override the gateway reads 0
    rig.gateway.publish()
    await start(
        rig, topology="gateway_standalone", return_after_outside_change=case != "option_off"
    )
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.forced = 60.0
    for _ in range(30):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    rewritten = unit_of(rig)._session.loop.setpoint.rewritten_at
    assert rewritten is not None
    assert issue(rig, "control_latched") is not None
    rig.gateway.forced = None  # the other controller is gone
    if case == "unknown":
        rig.gateway.read_back_shown = "unknown"
    await rig.advance(3540, step=60.0)
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    await rig.advance(120, step=60.0)
    if case == "returns":
        state = rig.state("sensor", "control_state")
        assert state.attributes["latched_by"] == []
        assert state.state == "heating"
        assert issue(rig, "control_latched") is None
        assert unit_of(rig)._session.loop.setpoint.rewritten_at == rewritten
        assert rig.gateway.setpoints()[-1] == EXPECTED  # control takes the boiler again
        return
    await rig.advance(3600, step=60.0)
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    assert issue(rig, "control_latched") is not None


@pytest.mark.usefixtures("low_setpoint_off")
async def test_setpoint_step_over_1k_is_refused_or_compared_after_rounding(rig: Rig) -> None:
    """T-55 (P-15, P-98): a setpoint entity with a step of 0.5 from 0.25 and the hard maximum
    70: 70 is sent as 69.75, read back as 69.75 it confirms — no false "ignored" — and the
    hand-back value goes on the grid too, and is checked after rounding. The step raised to 5
    after setup: the runtime blocker ``setpoint_step_too_coarse``. A °F entity with a step of
    2 °F (1.1 K) is refused the same way."""
    number = FakeNumber(rig.hass, attributes={"min": 0.25, "max": 90, "step": 0.5})
    number.register()
    rig.outdoor = -30.0
    rig.live()
    # At −30 °C the curve asks for more than its 70 °C design flow: the hard maximum cuts it
    # (a design flow above the maximum itself is refused, P-68).
    control = held_entity(number, curve={"design_outdoor": -15, "design_flow": 70})
    await start(rig, **control)
    await rig.switch(True)
    assert number.writes == [69.75]
    await rig.advance(150)
    setpoint = rig.state("sensor", "control_setpoint")
    assert setpoint.attributes["requested"] == 69.8  # shown rounded to a tenth
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"
    await rig.switch(False)
    assert number.writes[-2:] == [25.25, 50.25]  # the lowest and the hand-back value, on grid
    assert not unit_of(rig).hand_back_owed  # 50.25 read back: the release
    number.attributes["step"] = 5
    number.publish(number.value)
    blockers = unit_of(rig).blockers(dt_util.utcnow().timestamp())
    assert "setpoint_step_too_coarse" in blockers
    number.attributes.update({"step": 2, "min": 50, "max": 190})
    number.unit = "°F"
    number.publish(number.value)
    blockers = unit_of(rig).blockers(dt_util.utcnow().timestamp())
    assert "setpoint_step_too_coarse" in blockers
    number.attributes["step"] = 1
    number.publish(number.value)
    blockers = unit_of(rig).blockers(dt_util.utcnow().timestamp())
    assert "setpoint_step_too_coarse" not in blockers


@pytest.mark.parametrize("indicator", ["uptime", "counter", "unavailable", "none"])
async def test_a_restart_the_indicator_shows_is_a_trace(rig: Rig, indicator: str) -> None:
    """Q3.7: the optional restart indicator — an uptime that falls, a restart counter that goes
    up, or the indicator itself unavailable — is a trace of an outage: the gateway's override
    falling back just after it is a lost command with a trace, which primes nothing, so a
    fall-back without a trace later in the hour is only the first such (sent again). Negative:
    without the indicator the first counts as one without a trace, and the second within the
    hour that no send explains is another controller's — the one rewrite."""
    entity = "sensor.gateway_uptime"
    attributes = (
        {"unit_of_measurement": "s", "device_class": "duration"} if indicator == "uptime" else {}
    )
    before = "5000" if indicator == "uptime" else "3"
    rig.hass.states.async_set(entity, before, attributes)
    extra = {} if indicator == "none" else {"restart_entity": entity}
    await start(rig, **extra)
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(150)  # held: the start phase is over
    if indicator == "uptime":
        rig.hass.states.async_set(entity, "12", attributes)  # restarted: counting again
    elif indicator == "counter":
        rig.hass.states.async_set(entity, "4", attributes)  # one more restart
    elif indicator == "unavailable":
        rig.hass.states.async_set(entity, "unavailable", attributes)
        rig.hass.states.async_set(entity, "3", attributes)
    rig.gateway.override = None  # the restart lost the override
    count = len(rig.gateway.setpoints())
    await rig.advance(10)
    assert rig.gateway.setpoints()[count:] == [EXPECTED]  # sent again at once
    guard = unit_of(rig)._session.loop.setpoint
    assert (guard.fallbacks == ()) is (indicator != "none")
    await rig.advance(600)
    rig.gateway.override = None  # again, now with no trace
    await rig.advance(10)
    rewritten = unit_of(rig)._session.loop.setpoint.rewritten_at
    assert (rewritten is not None) is (indicator == "none")


async def test_frequent_lost_commands_raise_commands_lost_never_a_hold(rig: Rig) -> None:
    """M1: three lost commands within a day — the gateway restarting three times, its restart
    counter going up and its override lost each time — raise the information alarm "commands
    lost"; the command is sent again each time, control goes on and nothing is handed back. It
    clears after a day without a loss."""
    entity = "sensor.gateway_reboot_count"
    rig.hass.states.async_set(entity, "3")
    await start(rig, restart_entity=entity)
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(150)
    for restarts in (4, 5, 6):
        assert rig.state("binary_sensor", "alarm_commands_lost").state == "off"
        rig.hass.states.async_set(entity, str(restarts))
        rig.gateway.override = None
        count = len(rig.gateway.setpoints())
        await rig.advance(10)
        assert rig.gateway.setpoints()[count:] == [EXPECTED]  # sent again at once
        await rig.advance(600)
    assert rig.state("binary_sensor", "alarm_commands_lost").state == "on"
    assert rig.state("sensor", "control_state").state == "heating"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert 0.0 not in rig.gateway.setpoints()  # never a hold, never a hand-back
    await rig.advance(24 * 3600, step=300.0)
    assert rig.state("binary_sensor", "alarm_commands_lost").state == "off"


THERMOSTAT_REQUEST = "sensor.fake_thermostat_control_setpoint"


@pytest.mark.parametrize("case", ["returns", "unknown", "third_value"])
@pytest.mark.parametrize(
    "path", ["value", "thermostat", "thermostat_unmapped", "timeout", "switch"]
)
@pytest.mark.usefixtures("low_setpoint_off")
async def test_the_return_by_itself_comes_only_while_each_paths_hand_back_state_shows(
    rig: Rig, path: str, case: str
) -> None:
    """TB-13, decision 6's return by itself on each path, after the plugin stepped aside from
    another controller: quiet for an hour while the read-back shows only the hand-back state — a
    held setpoint entity its hand-back value; a gateway with an OpenTherm thermostat the
    thermostat's own request, where the optional field is mapped; the timeout hand-back the value
    from before the session (45 °C); the external-control switch off — then a new session starts
    and the latch issue goes. Negative: the read-back unknown, or a third value (the switch on),
    within the hour — no return. PB-33: the thermostat's field not mapped, the value from before
    the session (its request then, 40 °C) counts as the hand-back state."""
    number = FakeNumber(rig.hass, value=45.0)
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    if path == "thermostat":
        rig.hass.states.async_set(THERMOSTAT_REQUEST, "40.0", {"unit_of_measurement": "°C"})
        await start(
            rig, thermostat_setpoint_entity=THERMOSTAT_REQUEST, return_after_outside_change=True
        )
    elif path == "thermostat_unmapped":
        await start(rig, return_after_outside_change=True)
    else:
        number.register()
        control = {
            "value": held_entity(number),
            "timeout": held_entity(number, **TIMEOUT_PATH),
            "switch": switch_method(number, external.entity_id, "held"),
        }[path]
        if path == "switch":
            external.register()
            control["return_after_switch_hand_back"] = True  # SB-36: its own option
        await start(rig, **control, return_after_outside_change=True)
    await rig.switch(True)
    await rig.advance(30)
    if path.startswith("thermostat"):
        rig.gateway.forced = 60.0
    else:
        number.forced = number.value = 60.0
        number.publish(60.0)
    for _ in range(30):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    assert issue(rig, "control_latched") is not None
    # The other controller is gone; the read-back shows the hand-back state.
    if path.startswith("thermostat"):
        rig.gateway.forced = None  # the gateway shows the thermostat's request (40)
    else:
        number.forced = None
        number.value = {"value": 50.0, "timeout": 45.0, "switch": 47.0}[path]
        number.publish(number.value)
    if path == "switch":
        assert not external.on  # handed back at the step aside
    await rig.advance(1800, step=60.0)
    if case == "unknown":
        if path.startswith("thermostat"):
            rig.gateway.read_back_shown = "unknown"
            rig.gateway.publish()
        elif path == "switch":
            rig.hass.states.async_set(external.entity_id, "unknown")
        else:
            rig.hass.states.async_set(number.entity_id, "unknown", {"unit_of_measurement": "°C"})
    elif case == "third_value":
        if path.startswith("thermostat"):
            rig.gateway.forced = 33.0
            rig.gateway.publish()
        elif path == "switch":
            external.on = True
            external.publish()
        else:
            number.publish(38.0)
    await rig.advance(60, step=60.0)
    if case != "returns":  # the hour broken: it starts again once the hand-back state is back
        if path.startswith("thermostat"):
            rig.gateway.read_back_shown = None
            rig.gateway.forced = None
            rig.gateway.publish()
        elif path == "switch":
            external.on = False
            external.publish()
        else:
            number.publish(number.value)
    await rig.advance(1800, step=60.0)
    returned = rig.state("sensor", "control_state").attributes["latched_by"] == []
    assert returned is (case == "returns")
    assert (issue(rig, "control_latched") is None) is (case == "returns")


@pytest.mark.parametrize("own_option", [False, None, "yes"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_the_switch_hand_back_returns_by_itself_only_with_its_own_option(
    rig: Rig, own_option: bool | str | None
) -> None:
    """SB-36 (decision 10): after a hand-back through the external-control switch, the return by
    itself needs its own option, off by default — the switch also reads "off" when a person
    switched external control off on purpose. With only the general return on (its own option
    off, missing or not a clear true) control stays aside for hours of a quiet hand-back state,
    as with relays; with it on, it returns (the test above)."""
    number = FakeNumber(rig.hass, value=45.0)
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    number.register()
    external.register()
    control = switch_method(number, external.entity_id, "held")
    if own_option is not None:
        control["return_after_switch_hand_back"] = own_option
    await start(rig, **control, return_after_outside_change=True)
    await rig.switch(True)
    await rig.advance(30)
    number.forced = number.value = 60.0
    number.publish(60.0)
    for _ in range(30):
        await rig.advance(10)
        if rig.state("sensor", "control_state").state == "handed_back":
            break
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    number.forced = None
    number.value = 47.0
    number.publish(number.value)
    assert not external.on
    await rig.advance(3 * 3600, step=60.0)
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["outside_change"]
    assert issue(rig, "control_latched") is not None
    assert not external.on  # never taken back


# --- X2: the boiler link and freshness (P-08, P-41; T-03; Open after R6 #8) --------------------


def link_alarm(rig: Rig) -> str:
    return rig.state("binary_sensor", "alarm_boiler_link_lost").state


@pytest.mark.parametrize("lost", ["flow", "gateway"])
async def test_a_lost_link_after_a_restart_raises_boiler_link_lost(
    rig: Rig, hass_storage: dict[str, Any], lost: str
) -> None:
    """T-03 (P-08; the review's Appendix B, first row): stand-alone, the last run held the boiler
    and control is to stay on; Home Assistant restarts with the boiler link still lost — the flow
    gone, or the whole gateway. The owed hand-back goes first (it reaches a gateway that is
    there); the link's samples start empty, so the alarm rises 300 s after the start, and ten
    minutes on it is still on, the state showing the wait: a restart no longer clears it."""
    if lost == "flow":
        rig.flow = None
    else:
        rig.gateway.connected = False
    rig.live()
    await start_with_stored(
        rig,
        hass_storage,
        {"controlling": True, "enabled": True},
        "0.2.2",
        topology="gateway_standalone",
    )
    assert rig.state("binary_sensor", "control").state == "on"
    await rig.advance(290)
    assert link_alarm(rig) == "off"
    await rig.advance(20)
    assert link_alarm(rig) == "on"
    await rig.advance(300)  # ten minutes after the start
    assert link_alarm(rig) == "on"
    state = rig.state("sensor", "control_state")
    assert state.state in ("handed_back", "waiting_data")
    assert "boiler_link_stale" in state.attributes["reasons"]
    assert rig.gateway.calls == ([] if lost == "gateway" else HAND_BACK)  # nothing more


async def test_boiler_link_lost_rises_while_a_latch_holds(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P-08: the switch on while a latch holds control; the link down for six minutes raises
    the alarm all the same, with nothing written, and the alarm goes once the link has been back
    for a minute. (The monitoring period no longer holds control: 2026-10-08.)"""
    stored: dict[str, Any] = {"enabled": True, "latched": True, "latched_by": ["pressure_low"]}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, stored, "0.2.2")
    await set_up(rig, entry)
    assert rig.state("binary_sensor", "control").state == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"
    rig.flow = None
    await rig.advance(290)
    assert link_alarm(rig) == "off"
    await rig.advance(70)  # six minutes
    assert link_alarm(rig) == "on"
    rig.flow = 35.0
    await rig.advance(80)
    assert link_alarm(rig) == "off"
    assert rig.gateway.calls == []  # held back throughout


async def test_switching_on_with_the_link_down_raises_the_alarm(rig: Rig) -> None:
    """P-08: switched on while the flow is gone: nothing is written, the state says control waits
    for data, and 300 s later the alarm rises — though control never held the boiler."""
    await start(rig)
    rig.flow = None
    rig.live()
    await rig.switch(True)
    await rig.advance(290)
    assert link_alarm(rig) == "off"
    assert rig.state("sensor", "control_state").state == "waiting_data"
    await rig.advance(20)
    assert link_alarm(rig) == "on"
    assert rig.gateway.calls == []


async def test_the_link_alarm_is_off_while_control_is_switched_off(rig: Rig) -> None:
    """Negative: with control switched off the alarm stays off however long the link is lost,
    and nothing is written. Switched on with the link lost for long, the alarm is on at once —
    switching does not make a lost link fresh; switched off, it goes at once."""
    await start(rig)
    rig.flow = None
    await rig.advance(900)
    assert link_alarm(rig) == "off"
    await rig.switch(True)
    assert link_alarm(rig) == "on"
    await rig.switch(False)
    assert link_alarm(rig) == "off"
    await rig.advance(300)
    assert link_alarm(rig) == "off"
    await rig.switch(True)  # a new session: the link's window is kept
    assert link_alarm(rig) == "on"
    assert rig.gateway.calls == []


async def test_a_flapping_flow_still_hands_back(rig: Rig) -> None:
    """P-08 in Home Assistant: the flow reported for one step in five — never five minutes stale
    in a row — hands back once its stale steps cover five minutes within ten; control stays
    handed back, the alarm on, while it keeps flapping."""
    await start(rig)
    await rig.switch(True)
    for i in range(120):  # twenty minutes, fresh at every fifth step
        rig.flow = 35.0 if i % 5 == 4 else None
        await rig.advance(10)
    assert rig.gateway.setpoints().count(0.0) == 1  # handed back once
    assert rig.gateway.calls[-3:] == HAND_BACK  # nothing written since
    assert link_alarm(rig) == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"


@pytest.mark.parametrize("limit", [600.0, None], ids=["flame_limit", "no_limit"])
async def test_a_stale_flame_counts_by_its_own_limit(rig: Rig, limit: float | None) -> None:
    """P-41: the flame stops reporting while its entity stays available (MQTT without
    availability); the flow reports on. With the flame's own limit of ten minutes nothing is
    written once it has passed, and the hand-back follows the window rule five minutes later,
    with the alarm. Negative: without a limit a steady flame is not a stale one — control goes
    on, its keep-alives with it."""
    freshness = {} if limit is None else {"flame": limit}
    entry = add_entry(rig, options(rig.zones) | {"freshness": freshness})
    await set_up(rig, entry)
    await rig.switch(True)
    rig.flame_reported = False  # its last report: now
    await rig.advance(600)  # the limit reached, not passed
    assert rig.state("sensor", "control_state").state == "heating"
    count = len(rig.gateway.calls)
    await rig.advance(290)
    if limit is None:
        assert ("setpoint", EXPECTED) in rig.gateway.calls[count:]  # keep-alives went on
        await rig.advance(600)
        assert rig.state("sensor", "control_state").state == "heating"
        assert link_alarm(rig) == "off"
        assert 0.0 not in rig.gateway.setpoints()
        return
    assert rig.gateway.calls[count:] == []  # nothing written after the flame's limit
    assert rig.state("sensor", "control_state").state == "waiting_data"
    assert link_alarm(rig) == "off"
    await rig.advance(30)
    assert rig.gateway.calls[count:] == HAND_BACK
    assert link_alarm(rig) == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"


async def test_a_missing_flame_is_a_lost_link_like_a_missing_flow(rig: Rig) -> None:
    """P-41, missing input: the flame's entity unavailable while the flow reports on — nothing is
    written, and after five minutes the hand-back and the alarm, as for the flow; the flame back
    for a minute, control resumes and the alarm goes."""
    await start(rig)
    await rig.switch(True)
    rig.flame = None
    rig.live()
    count = len(rig.gateway.calls)
    await rig.advance(290)
    assert rig.gateway.calls[count:] == []
    assert link_alarm(rig) == "off"
    await rig.advance(20)
    assert rig.gateway.calls[count:] == HAND_BACK
    assert link_alarm(rig) == "on"
    rig.flame = False
    await rig.advance(70)
    assert link_alarm(rig) == "off"
    assert rig.gateway.setpoints()[-1] == EXPECTED


@pytest.mark.parametrize(
    ("weather", "limit", "early", "late"),
    [
        ("cloudy", None, "outdoor_weather", "outdoor_weather"),
        ("cloudy", 1800.0, "outdoor_weather", "outdoor_held"),
        ("unavailable", None, "outdoor_held", "outdoor_held"),
    ],
    ids=["no_weather_limit", "weather_limit", "weather_unavailable"],
)
async def test_the_weather_entity_uses_its_own_age_limit(
    rig: Rig, weather: str, limit: float | None, early: str, late: str
) -> None:
    """P-41: the outdoor sensor has a limit of ten minutes and stops reporting; the weather entity
    reported once, at the start. Without a limit of its own it still feeds the curve after the
    sensor's limit — the sensor's limit is not its; with its own limit of 30 minutes it is left
    out after them, and the curve holds the last value. Missing input: an unavailable weather
    entity is never used."""
    attributes = {"temperature": 0.0, "temperature_unit": "°C"} if weather == "cloudy" else {}
    rig.hass.states.async_set(WEATHER_ENTITY, weather, attributes)
    freshness = {"outdoor": 600.0} | ({} if limit is None else {"weather": limit})
    entry = add_entry(rig, options(rig.zones) | {"weather": WEATHER_ENTITY, "freshness": freshness})
    await set_up(rig, entry)
    await rig.switch(True)
    rig.outdoor_reported = False
    await rig.advance(20 * 60, step=60.0)  # the sensor stale for ten minutes
    assert early in rig.state("sensor", "control_state").attributes["reasons"]
    await rig.advance(20 * 60, step=60.0)  # the weather's report 40 minutes old
    reasons = rig.state("sensor", "control_state").attributes["reasons"]
    assert late in reasons
    assert "outdoor_sensor" not in reasons


@pytest.mark.parametrize("limits", [True, False], ids=["limits", "no_limits"])
async def test_hot_water_flags_count_by_their_own_limits(rig: Rig, limits: bool) -> None:
    """X2, one freshness rule for the monitor and control: the flags hot water is read from —
    its own, else the flame on with heating off — each count by their own age limit; a stale
    one is unknown, as an unavailable one is. Negative: without limits a steady flag counts,
    however old its report."""
    from custom_components.vtherm_smart_boiler.core.readings import BoilerSnapshot, Reading

    freshness = {"dhw_active": 600.0, "flame": 600.0, "ch_active": 600.0} if limits else {}
    base = options(rig.zones)
    # I8 (decision D7): a limit belongs to a mapped signal — heating active mapped too.
    signals = base["signals"] | {"ch_active": BOILER_ENTITIES[Signal.CH_ACTIVE]}
    entry = add_entry(rig, base | {"signals": signals, "freshness": freshness})
    await set_up(rig, entry)
    coordinator = entry.runtime_data
    now = START.timestamp()
    old, new = now - 700.0, now - 10.0

    def dhw(**flags: tuple[bool | None, float | None]) -> bool | None:
        readings = {Signal(key): Reading(*reading) for key, reading in flags.items()}
        return coordinator.dhw_now(BoilerSnapshot(now, readings))

    stale = None if limits else True
    assert dhw(dhw_active=(True, new)) is True
    assert dhw(dhw_active=(True, old)) is stale
    assert dhw(dhw_active=(None, new)) is None  # unavailable: unknown
    inferred = {"flame": (True, new), "ch_active": (False, new)}
    assert dhw(dhw_active=(None, new), **inferred) is True  # the flame on, heating off
    assert dhw(dhw_active=(True, old), **inferred) is True
    assert dhw(flame=(True, old), ch_active=(False, new)) is stale
    assert dhw(flame=(True, new), ch_active=(False, old)) is stale


# --- X3: demand, zones, decision 3 ---------------------------------------------------------------

RESTORED = 45.0  # the last command a run stored: heating on at 45 °C


def taken_with(rig: Rig, **control: Any) -> dict[str, Any]:
    """The control options a run took the boiler with, as the entry holds them after its
    migration — which keeps the lowest water temperature (X6)."""
    return options(rig.zones, **control)["control"] | {"hard_min": LOWEST}


def restorable(rig: Rig, **changes: Any) -> dict[str, Any]:
    """The control store a run that held the boiler left — a crash, by default — with its last
    command, the user's wish on, and the options the boiler was taken with."""
    return {
        "enabled": True,
        "controlling": True,
        "last_command": {"heating": True, "setpoint": RESTORED, "at": START.timestamp()},
        "taken_with": taken_with(rig),
    } | changes


def not_started(rig: Rig, zone_id: str = "living") -> None:
    """What VT shows before it has started a thermostat: "off", without its own attributes."""
    rig.zones.set(zone_id, "off", is_ready=None, specific_states=None)


def started(rig: Rig, zone_id: str = "living") -> None:
    rig.zones.set(zone_id, hvac_action="heating", valve_open_percent=60, on_percent=0.6)


async def test_a_renamed_entity_carries_what_control_stored_for_it(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P-19: a VT climate — a room the only circuit lists with convectors — renamed while
    control runs: the options follow it, and the options the boiler was taken with stay in the
    store as control runs them."""
    hass = rig.hass
    living = rig.zones.entities["living"]
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    registry = er.async_get(hass)
    stored = restorable(rig, controlling=False, taken_with=taken_with(rig))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=with_circuit(rig, {"convectors": [living]}),
    )
    entry.add_to_hass(hass)
    seed_stores(hass_storage, entry, stored, "0.2.2")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    rig.entry = entry
    await rig.advance(10)
    assert rig.gateway.setpoints()  # control holds the boiler: what it was taken with is kept
    rig.gateway.calls.clear()
    registry.async_update_entity(living, new_entity_id="climate.lounge")
    await hass.async_block_till_done()
    assert rig.entry is not None
    # I12.11: the only circuit lists no room — only its emitter lists, which follow the rename.
    assert rig.entry.options["circuits"][0]["convectors"] == ["climate.lounge"]
    control = rig.entry.options["control"]
    kept = stored_control(hass_storage, rig)
    # The curve as control runs it: with the building's design outdoor temperature (I6).
    design_outdoor = rig.entry.options["parameters"]["design_outdoor"]
    curve = control["curve"] | {"design_outdoor": design_outdoor}
    # And the read-back, a boiler signal now (I8.5b).
    read_back = rig.entry.options["signals"]["ch_setpoint"]
    assert kept["taken_with"] == control | {"curve": curve, "confirmed_entity": read_back}


async def test_control_renamed_while_controlling_keeps_control(rig: Rig) -> None:
    """The user renames the entity ID of control's state while control holds the boiler: Home
    Assistant 2026.11 onward changes it in place (the plugin opts in; the only way from
    2027.11), older versions remove the entity and add it again. Either way control stays on and
    holds the boiler, the state shows under its new ID only, and control still switches off
    (I11.3: the state was the control switch)."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(10)
    assert rig.gateway.setpoints()
    old = rig.entity("binary_sensor", "control")
    new = "binary_sensor.renamed_boiler_control"
    er.async_get(rig.hass).async_update_entity(old, new_entity_id=new)
    await rig.hass.async_block_till_done()
    rig.gateway.calls.clear()
    await rig.advance(60)
    assert rig.entity("binary_sensor", "control") == new
    assert rig.hass.states.get(old) is None
    assert rig.state("binary_sensor", "control").state == "on"
    assert rig.gateway.setpoints()  # still controlling: the setpoint is repeated
    await rig.switch(False)
    assert rig.state("binary_sensor", "control").state == "off"


@pytest.mark.parametrize("home_assistant_has_it", [True, False])
async def test_the_rename_hook_passes_on_to_home_assistants_own(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, home_assistant_has_it: bool
) -> None:
    """The control entities' ``async_entity_id_changed`` passes the rename on to Home
    Assistant's own where the running version has one (2026.11 onward), and does nothing else
    where it has none."""
    from homeassistant.helpers.entity import Entity

    await start(rig)
    calls: list[tuple[str, str]] = []
    if home_assistant_has_it:

        def own(self: Entity, old_entity_id: str) -> None:
            calls.append((self.entity_id, old_entity_id))

        monkeypatch.setattr(Entity, "async_entity_id_changed", own, raising=False)
    else:
        monkeypatch.delattr(Entity, "async_entity_id_changed", raising=False)
    state_id = rig.entity("binary_sensor", "control")
    state = rig.hass.data["binary_sensor"].get_entity(state_id)
    assert state is not None
    state.async_entity_id_changed("binary_sensor.before")
    assert calls == ([(state_id, "binary_sensor.before")] if home_assistant_has_it else [])


def no_zone_issue(rig: Rig) -> ir.IssueEntry | None:
    return issue(rig, "no_zone_known")


@pytest.mark.parametrize("stop", ["crash", "clean"])
async def test_the_last_command_is_restored_at_once_after_a_restart(
    rig: Rig, hass_storage: dict[str, Any], stop: str
) -> None:
    """Decision 3: the store of a run that held the boiler — a crash, or a clean stop whose
    hand-back went through — its last command (on, 45 °C), the wish on and the options the
    boiler was taken with: while Home Assistant starts and VT's zones are not there yet, the
    first write is 45 with heating on — no hand-back first — kept with its keep-alives until
    the recognition period ends; then control decides anew. The owed hand-back is folded in."""
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    not_started(rig)
    changes = {} if stop == "crash" else {"controlling": False}
    await start_with_stored(rig, hass_storage, restorable(rig, **changes), "0.2.2")
    await rig.advance(10)
    assert rig.gateway.calls[:2] == [("setpoint", RESTORED), ("ch", True)]
    assert rig.state("binary_sensor", "control").state == "on"
    attributes = rig.state("sensor", "control_state").attributes
    assert attributes["reasons"] == ["zones_recognition"]
    assert "ha_starting" in attributes["blockers"]
    await rig.advance(60)
    assert set(rig.gateway.setpoints()) == {RESTORED}  # kept alive, nothing new decided
    assert ("setpoint", 0.0) not in rig.gateway.calls  # never handed back first
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert not unit.hand_back_owed
    rig.hass.set_state(CoreState.running)
    started(rig)
    await rig.advance(10)
    attributes = rig.state("sensor", "control_state").attributes
    assert "demand" in attributes["reasons"]  # decided anew: the curve, reached by the ramp
    assert attributes["target"] == EXPECTED
    await rig.advance(600)
    assert rig.gateway.setpoints()[-1] == pytest.approx(EXPECTED, abs=0.5)
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert issue(rig, OWED) is None


@pytest.mark.parametrize("circuit_max", [40.0, None], ids=["lowered", "none"])
async def test_a_restored_command_goes_out_within_the_limits_as_they_are_now(
    rig: Rig, hass_storage: dict[str, Any], circuit_max: float | None
) -> None:
    """PB-11: the last command a run stored (on, 45 °C), the circuit's maximum lowered to 40 °C
    in the options since — the control section unchanged, so the command is given again. On the
    gateway, which has no entity grid to put it on, through the recognition period with a zone
    not reporting: nothing above 40 °C goes out. Negative: without a maximum, 45 °C as stored."""
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    not_started(rig)
    circuit = {} if circuit_max is None else {"max_flow": circuit_max}
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=with_circuit(rig, circuit)
    )
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, restorable(rig), "0.2.2")
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.advance(600, step=30)
    written = rig.gateway.setpoints()
    assert written
    assert ("setpoint", 0.0) not in rig.gateway.calls  # given again, not handed back first
    assert set(written) == {RESTORED if circuit_max is None else circuit_max}


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_restored_off_is_not_raised_into_the_limits(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """PB-11's negative: on a path without heating writes "off" is a low setpoint below the
    lowest water temperature. Given again after a restart it stays "off" — written from its
    own option, its target not raised to the lowest — never turned into heating."""
    from homeassistant.core import CoreState

    from custom_components.vtherm_smart_boiler.core.loop import DEFAULT_OFF_SETPOINT

    rig.hass.set_state(CoreState.starting)
    not_started(rig)
    number = FakeNumber(rig.hass)
    number.register()
    section = held_entity(number)
    command = {"heating": False, "setpoint": DEFAULT_OFF_SETPOINT, "at": START.timestamp()}
    stored = restorable(rig, last_command=command, taken_with=taken_with(rig, **section))
    await start_with_stored(rig, hass_storage, stored, "0.2.2", **section)
    await rig.advance(60)
    assert number.writes == [DEFAULT_OFF_SETPOINT]
    assert rig.state("sensor", "control_state").attributes["target"] == DEFAULT_OFF_SETPOINT


OWED = "hand_back_owed"


@pytest.mark.parametrize(
    "case",
    [
        "no_command",
        "no_setpoint",
        "no_options_stored",
        "wish_off",
        "latch",
        "internal_error",
        "options_differ",
        "design_outdoor_differs",
        "blocker",
        "thermostat_kind_missing",
        "store_lost",
    ],
)
async def test_a_restore_whose_conditions_fail_hands_back_first(
    rig: Rig, hass_storage: dict[str, Any], case: str
) -> None:
    """Negatives, each: the owed hand-back comes first, as before — no stored command (or one
    without a setpoint), the wish off, a stored latch
    or internal error, options other than those the boiler was taken with, a blocker other than
    Home Assistant starting — VT's central boiler, or the thermostat-terminals question not
    answered by an entry from before 0.2.2 (X6, answer K) — a store that could not be read
    (answer K)."""
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    not_started(rig)
    changes: dict[str, Any] = {
        "no_command": {"last_command": None},
        "no_setpoint": {"last_command": {"heating": True, "setpoint": None, "at": 0.0}},
        "no_options_stored": {"taken_with": None},  # an earlier store: they cannot be compared
        "wish_off": {"enabled": False},
        "latch": {"latched": True, "latched_by": ["pressure_low"]},
        "internal_error": {"failed": True},
        "options_differ": {"taken_with": options(rig.zones, topology="gateway_standalone")},
        # I6: the design outdoor temperature, now the building's, still counts as the curve's.
        "design_outdoor_differs": {
            "taken_with": taken_with(rig, curve={"design_outdoor": -20, "design_flow": 55})
        },
        # Taken with these very options, stored before the question existed.
        "thermostat_kind_missing": {"taken_with": taken_with(rig, thermostat_kind=None)},
    }.get(case, {})
    kind = {"thermostat_kind": None} if case == "thermostat_kind_missing" else {}
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **kind)
    )
    entry.add_to_hass(rig.hass)
    if case == "store_lost":
        seed_main(hass_storage, entry)  # the entry store, its control store gone
    else:
        seed_stores(hass_storage, entry, restorable(rig, **changes), "0.2.2")
    if case == "blocker":
        vt_central_boiler(rig, False)
    await set_up(rig, entry)
    await rig.advance(10)
    calls = rig.gateway.calls
    assert calls[:3] == [("setpoint", LOWEST), ("ch", True), ("setpoint", 0.0)]
    assert ("setpoint", RESTORED) not in calls
    if case == "thermostat_kind_missing":
        blockers = rig.state("sensor", "control_state").attributes["blockers"]
        assert "thermostat_kind_unknown" in blockers


async def test_a_link_not_yet_reported_does_not_turn_a_restore_into_a_hand_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The gateway's link reports three minutes after the start: nothing is written meanwhile,
    no loss is declared, then the restore — no hand-back first."""
    not_started(rig)
    rig.flow = None
    rig.live()
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(170)
    assert rig.gateway.calls == []
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "off"
    rig.flow = 35.0
    await rig.advance(10)
    assert rig.gateway.calls[:2] == [("setpoint", RESTORED), ("ch", True)]
    await rig.advance(400)
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "off"


async def test_a_link_still_silent_when_the_recognition_ends_gives_way_to_the_hand_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Negative: the link still silent at the end of the recognition period (ten minutes): the
    owed hand-back is made, and the link, silent since the start, is lost at once (X2)."""
    not_started(rig)
    rig.flow = None
    rig.live()
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(590)
    assert rig.gateway.calls == []
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "off"
    await rig.advance(20)
    assert rig.gateway.calls[:3] == [("setpoint", LOWEST), ("ch", True), ("setpoint", 0.0)]
    assert ("setpoint", RESTORED) not in rig.gateway.calls
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "on"


async def test_a_restore_goes_out_while_vts_settings_are_not_known_yet(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """I12, decision 3 after a restart: VT hands its thermostats — and with them its central
    boiler's settings — over only once it starts them. The restorable store's command goes out
    at once meanwhile and is kept through the recognition period; once VT has handed them over,
    control goes on, nothing handed back."""
    rig.zones.withdraw()
    not_started(rig)
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(10)
    assert rig.gateway.calls[:2] == [("setpoint", RESTORED), ("ch", True)]
    assert "vt_central_boiler_unknown" in blockers(rig)
    rig.zones.hand_over()
    started(rig)
    await rig.advance(30)
    assert "vt_central_boiler_unknown" not in blockers(rig)
    assert ("setpoint", 0.0) not in rig.gateway.calls


async def test_a_restore_at_a_start_waits_for_neither_the_helper_nor_vts_settings(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """I12, decision 3 at a real start: Home Assistant starting, its helpers not set up yet and
    VT's thermostats not handed over — the restore goes out at once all the same, no hand-back
    first; once Home Assistant runs, the helper is there and VT has handed its thermostats
    over, control decides anew."""
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    rig.zones.withdraw()
    rig.zones.set_helper(None)
    not_started(rig)
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(10)
    assert rig.gateway.calls[:2] == [("setpoint", RESTORED), ("ch", True)]
    assert {"ha_starting", "vt_central_boiler_unknown"} <= set(blockers(rig))
    assert "vt_boiler_helper_missing" not in blockers(rig)
    rig.hass.set_state(CoreState.running)
    rig.zones.set_helper("off", follow=True)
    rig.zones.hand_over()
    started(rig)
    await rig.advance(10)
    assert not {b for b in blockers(rig) if b.startswith("vt_") or b == "ha_starting"}
    assert "demand" in rig.state("sensor", "control_state").attributes["reasons"]
    assert ("setpoint", 0.0) not in rig.gateway.calls


async def test_vts_settings_still_unknown_after_the_recognition_hand_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Negative: VT's settings still not known — its thermostats' ``entry_infos`` cannot be
    read, so no room is known either (I12.11: a room is a thermostat VT's central boiler counts,
    as its ``entry_infos`` say) — the blocker counts once the recognition period is over, its
    ten minutes: the restored session hands back, and control waits for VT."""
    from custom_components.vtherm_smart_boiler.core.zone_watch import RECOGNITION_S

    rig.zones.stand_in.entry_infos = None  # type: ignore[assignment]
    not_started(rig)
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(10)
    assert rig.gateway.calls[:2] == [("setpoint", RESTORED), ("ch", True)]
    started(rig)
    await rig.advance(30)
    assert rig.gateway.setpoints()[-1] == RESTORED  # kept through the recognition period
    await rig.advance(RECOGNITION_S, step=30.0)
    assert "vt_central_boiler_unknown" in blockers(rig)
    assert rig.gateway.setpoints()[-1] == 0.0


@pytest.mark.parametrize("installation", ["standalone", "value_stops_heating"])
async def test_a_clean_restart_with_a_blocker_at_the_start_raises_the_stopped_heating_issue(
    rig: Rig, hass_storage: dict[str, Any], installation: str
) -> None:
    """Open after 0.2.2 #15 (V7's S-10 across a restart): the last run controlled and stopped
    cleanly; at the next start a blocker keeps the restore from happening, where a hand-back
    stops heating — the session carried over was ended by a blocker: the issue after a minute.
    Negative: without a last command (the run did not control) there is no such issue."""
    number = FakeNumber(rig.hass)
    number.register()
    extra = (
        {"topology": "gateway_standalone"}
        if installation == "standalone"
        else held_entity(number, hand_back_value_effect="heating_stops")
    )
    vt_central_boiler(rig, False)
    stored = restorable(rig, controlling=False, taken_with=taken_with(rig, **extra))
    await start_with_stored(rig, hass_storage, stored, "0.2.2", **extra)
    await rig.advance(50)
    assert stopped_heating(rig) is None
    await rig.advance(20)
    found = stopped_heating(rig)
    assert found is not None
    assert found.severity is ir.IssueSeverity.ERROR


async def test_a_run_that_never_controlled_raises_no_stopped_heating_issue(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    vt_central_boiler(rig, False)
    stored = restorable(rig, controlling=False, last_command=None)
    stored["taken_with"] = taken_with(rig, topology="gateway_standalone")
    await start_with_stored(rig, hass_storage, stored, "0.2.2", topology="gateway_standalone")
    await rig.advance(120)
    assert stopped_heating(rig) is None


async def test_no_zone_known_raises_an_alarm_and_a_repair_issue(rig: Rig) -> None:
    """Control on, every zone unavailable from the start: after the recognition period (ten
    minutes) nothing can ask for heat — the alarm and the repair issue, both at once; with the
    thermostat on the gateway the boiler is its (it was never taken). Both go the step a zone
    answers again."""
    rig.zones.set("living", "unavailable")
    await start(rig)
    await rig.switch(True)
    await rig.advance(590)
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"
    assert no_zone_issue(rig) is None
    assert rig.state("sensor", "control_state").attributes["reasons"] == ["zones_recognition"]
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "on"
    found = no_zone_issue(rig)
    assert found is not None
    assert found.translation_key == "no_zone_known_handed_back"
    assert found.severity is ir.IssueSeverity.WARNING
    zone = rig.hass.states.get(rig.zones.entities["living"])
    assert zone is not None
    assert found.translation_placeholders == {"zones": zone.name}
    state = rig.state("sensor", "control_state")
    assert (state.state, state.attributes["reasons"]) == ("handed_back", ["zones_unknown"])
    assert rig.gateway.calls == []  # never taken: nothing to hand back
    started(rig)
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"
    assert no_zone_issue(rig) is None
    assert rig.gateway.setpoints() == [EXPECTED]  # control resumes by itself


async def test_no_zone_known_without_a_thermostat_keeps_heating_off(rig: Rig) -> None:
    """Stand-alone: the usual "off" — heating off, no hand-back — with the issue as an error.
    It goes when the entry unloads."""
    await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway.calls[-1] == ("ch", True)
    rig.zones.set("living", "unavailable")
    await rig.advance(590)
    assert rig.gateway.calls[-1] == ("ch", True)  # the recognition period keeps the command
    await rig.advance(30)
    assert rig.gateway.calls[-1] == ("ch", False)
    assert ("setpoint", 0.0) not in rig.gateway.calls
    found = no_zone_issue(rig)
    assert found is not None
    assert found.translation_key == "no_zone_known_off"
    assert found.severity is ir.IssueSeverity.ERROR
    assert rig.state("sensor", "control_state").state == "idle"
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert no_zone_issue(rig) is None


async def test_no_zone_known_raises_the_repair_issue_with_the_monitor_only(rig: Rig) -> None:
    """No control configured: the monitor raises it after ten minutes of every zone unknown, as
    a warning, and drops it when a zone answers; with control switched off, the unit says the
    same. Negative: no zone configured, no issue."""
    rig.zones.set("living", "unavailable")
    entry = add_entry(rig, without_control(options(rig.zones)))
    await set_up(rig, entry)
    await rig.advance(570, step=30.0)
    assert no_zone_issue(rig) is None
    await rig.advance(60, step=30.0)
    found = no_zone_issue(rig)
    assert found is not None
    assert found.translation_key == "no_zone_known_monitor"
    assert found.severity is ir.IssueSeverity.WARNING
    started(rig)
    await rig.advance(30, step=30.0)
    assert no_zone_issue(rig) is None


async def test_no_zone_known_does_not_rise_while_home_assistant_starts(rig: Rig) -> None:
    """PB-53: the monitor's clock for the issue starts with Home Assistant running — VT starts
    its thermostats only then, so a slow start raises no issue."""
    from homeassistant.core import CoreState

    rig.zones.set("living", "unavailable")
    rig.hass.set_state(CoreState.starting)
    entry = add_entry(rig, without_control(options(rig.zones)))
    await set_up(rig, entry)
    await rig.advance(900, step=30.0)
    assert no_zone_issue(rig) is None
    rig.hass.set_state(CoreState.running)
    await rig.advance(570, step=30.0)
    assert no_zone_issue(rig) is None
    await rig.advance(60, step=30.0)
    assert no_zone_issue(rig) is not None


async def test_no_zone_known_with_control_switched_off_is_the_monitors_issue(rig: Rig) -> None:
    rig.zones.set("living", "unavailable")
    await start(rig)
    await rig.advance(610)
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"  # switched off
    found = no_zone_issue(rig)
    assert found is not None
    assert found.translation_key == "no_zone_known_monitor"


async def test_no_room_vt_counts_raises_the_information_issue_and_heats_nothing(
    rig: Rig,
) -> None:
    """I12.11: the rooms are the thermostats VT's central boiler counts. With none ticked "used
    by central boiler" in VT, control is not blocked by the options — the S-04 blocker went —
    but nothing can ask for heat, whatever VT's helper shows (decision 3); nothing is unknown, so
    no "no zone known" issue (TB-29); the information issue names the thermostats VT hands over
    and does not count. Ticking one in VT makes it a room, and the issue goes."""
    for zone_id in rig.zones.entities:
        rig.zones.configure(zone_id, used_by_controls_central_boiler=False)
    rig.zones.set_helper("on")
    await start(rig)
    await rig.switch(True)
    await rig.advance(700, step=30.0)
    assert "no_zones" not in blockers(rig)
    assert no_zone_issue(rig) is None
    assert rig.state("sensor", "control_state").attributes["reasons"] == ["zones_unknown"]
    assert ("ch", True) not in rig.gateway.calls
    counted = issue(rig, "vt_thermostats_not_counted")
    assert counted is not None
    assert counted.translation_key == "vt_thermostats_not_counted"
    assert "fake living" in counted.translation_placeholders["zones"]
    for zone_id in rig.zones.entities:
        rig.zones.configure(zone_id, used_by_controls_central_boiler=True)
    rig.zones.stand_in.entry_infos |= {"used_by_controls_central_boiler": True}
    await rig.advance(60, step=30.0)
    assert issue(rig, "vt_thermostats_not_counted") is None
    assert "demand" in rig.state("sensor", "control_state").attributes["reasons"]


async def test_a_transient_loss_of_every_zone_does_not_start_the_boiler(rig: Rig) -> None:
    """T-28 (S-03): summer, the only zone off; VT reloads it — unavailable for three steps,
    then its placeholder, then off again: heating never goes on, nothing is handed back."""
    rig.outdoor = 25.0
    rig.zones.set("living", "off", hvac_action="off", valve_open_percent=0, on_percent=0.0)
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.zones.set("living", "unavailable")
    await rig.advance(30)
    not_started(rig)
    await rig.advance(10)
    rig.zones.set("living", "off", hvac_action="off", valve_open_percent=0, on_percent=0.0)
    await rig.advance(30)
    assert ("ch", True) not in rig.gateway.calls
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert rig.state("sensor", "control_state").state == "idle"


async def test_the_vt_issue_without_control_configured(rig: Rig) -> None:
    """Negative: monitoring only — no helper is read, no issue raised."""
    rig.zones.set_helper("unknown")
    entry = add_entry(rig, without_control(options(rig.zones)))
    await set_up(rig, entry)
    await rig.advance(11 * 60, step=30.0)
    assert no_zone_issue(rig) is None


async def test_the_vt_issue_gives_way_to_every_zone_unknown(rig: Rig) -> None:
    """VT's decision unknown, then the zone lost for good: the recognition period that follows
    (every zone stopped answering at once) leaves the issue as it is; at its end every zone is
    unknown, and the issue says that instead — the zones named."""
    await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    rig.zones.set_helper("unknown")
    await rig.advance(11 * 60)
    assert no_zone_issue(rig).translation_key == "vt_decision_unknown_off"
    rig.zones.set("living", "unavailable")
    await rig.advance(9 * 60)
    assert no_zone_issue(rig).translation_key == "vt_decision_unknown_off"  # recognition
    await rig.advance(2 * 60)
    found = no_zone_issue(rig)
    assert found.translation_key == "no_zone_known_off"
    assert set(found.translation_placeholders) == {"zones"}
    assert rig.state("binary_sensor", "alarm_vt_decision_unknown").state == "off"
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "on"


# Check C's F2 and F3: a switch zone whose calls start and stop with VT's cycle.
CYCLE_ON = {
    "hvac_action": "heating",
    "valve_open_percent": 60,
    "specific_states": {"is_device_active": True},
    "on_percent": 0.4,
}
CYCLE_OFF = CYCLE_ON | {
    "hvac_action": "idle",
    "valve_open_percent": 0,
    "specific_states": {"is_device_active": False},
}


@pytest.mark.parametrize(
    ("topology", "kind"),
    [("gateway_with_thermostat", "handed_back"), ("gateway_standalone", "off")],
)
async def test_vt_unknown_holds_while_calls_start_and_stop(
    rig: Rig, topology: str, kind: str
) -> None:
    """Check C's F2 and F3 with VT deciding: the helper unknown while the zone's calls follow
    VT's 5-minute cycle (2 minutes on) for 40 minutes. Decision 3's end state holds: the
    thermostat on the gateway keeps the boiler — nothing taken at a call's end and handed back
    at the next start — and stand-alone heating stays off; the alarm never flickers, and the
    repair issue rises after ten minutes."""
    rig.zones.set("living", **CYCLE_ON)
    rig.zones.set_helper("unknown")
    await start(rig, topology=topology)
    await rig.switch(True)
    await rig.advance(20)
    seen = len(rig.gateway.calls)
    for cycle in range(8):
        for attributes, seconds in ((CYCLE_ON, 120), (CYCLE_OFF, 180)):
            rig.zones.set("living", **attributes)
            await rig.advance(seconds)
            state = rig.state("sensor", "control_state")
            assert state.state == ("handed_back" if kind == "handed_back" else "idle")
            assert "zones_unknown" in state.attributes["reasons"]
            assert "no_demand" not in state.attributes["reasons"]
            assert rig.state("binary_sensor", "alarm_vt_decision_unknown").state == "on"
            found = no_zone_issue(rig)
            if cycle >= 2:  # 15 minutes on
                assert found is not None
                assert found.translation_key == f"vt_decision_unknown_{kind}"
    calls = rig.gateway.calls[seen:]
    assert ("ch", True) not in calls  # heating never switched on without VT's word
    if kind == "handed_back":
        assert calls == []  # nothing taken, nothing handed back again
    else:
        assert len({call for call in calls if call[0] == "setpoint"}) <= 1


async def test_a_relay_with_its_own_control_is_not_switched_at_each_call_edge(
    rig: Rig, relay: FakeRelay
) -> None:
    """Check C's F2 on the relay path: the boiler's own room controller behind the relay (the
    tick, rest "on"), VT's decision unknown, and the zone's calls starting and stopping every
    30 s. The relay is handed back and stays so — never switched at each edge."""
    rig.zones.set("living", **CYCLE_OFF)
    rig.zones.set_helper("unknown")
    await start_relay(rig, relay_rest_state="on", own_room_controller=True)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    seen = len(relay.calls)
    for _ in range(6):
        for attributes in (CYCLE_ON, CYCLE_OFF):
            rig.zones.set("living", **attributes)
            await rig.advance(30)
            assert rig.state("sensor", "control_state").state == "handed_back"
    assert relay.calls[seen:] == []


async def test_vt_off_and_every_zone_off_is_no_demand_without_an_alarm_or_an_issue(
    rig: Rig,
) -> None:
    """Summer, negative: the only zone "off", VT's helper off — no demand: no end state, no
    alarm, no repair issue."""
    rig.zones.set("living", "off", **(CYCLE_OFF | {"hvac_action": "off"}))
    await start(rig)
    await rig.switch(True)
    await rig.advance(11 * 60)
    state = rig.state("sensor", "control_state")
    assert state.state == "idle"
    assert "no_demand" in state.attributes["reasons"]
    assert "zones_unknown" not in state.attributes["reasons"]
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"
    assert rig.state("binary_sensor", "alarm_vt_decision_unknown").state == "off"
    assert no_zone_issue(rig) is None


async def test_the_switch_shows_the_boilers_own_room_controller(rig: Rig) -> None:
    """Answer F: with the tick on the entity path, every hand-back goes to the boiler's own
    control, and the switch says so."""
    number = FakeNumber(rig.hass)
    number.register()
    control = held_entity(number, hand_back="timeout", write_type="expiring")
    await start(rig, **control, own_room_controller=True)
    attributes = rig.state("binary_sensor", "control").attributes
    assert attributes["hand_back_effect"] == "own_control_resumes"
    assert attributes["frost_protection_by"] == "device"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_restore_waits_for_its_setpoint_entity(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The entity path: the setpoint entity not there yet after the restart — nothing is
    written, the restore waits; once it is there, the last command goes out, no hand-back
    first."""
    number = FakeNumber(rig.hass)
    number.register()
    number.set_available(False)
    not_started(rig)
    control = held_entity(number)
    stored = restorable(rig, taken_with=taken_with(rig, **control))
    await start_with_stored(rig, hass_storage, stored, "0.2.2", **control)
    await rig.advance(60)
    assert number.writes == []
    number.set_available(True)
    await rig.advance(10)
    assert number.writes == [RESTORED]
    assert rig.state("sensor", "control_state").attributes["reasons"] == ["zones_recognition"]


async def test_a_restored_command_not_yet_through_still_holds_the_boiler(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The restored command is given, but its write reports a failure: the owed hand-back is
    folded into the session at that first attempt (PB-13) — the session holds the boiler, as
    stored, so a crash still hands back first and the session's own hand-back is whole — and the
    command is sent again until it goes through, with no hand-back first."""
    rig.gateway.fail_after = True
    not_started(rig)
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(20)
    assert ("setpoint", RESTORED) in rig.gateway.calls
    unit = unit_of(rig)
    assert not unit.hand_back_owed
    assert unit.holding
    assert stored_control(hass_storage, rig)["controlling"] is True
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"
    rig.gateway.fail_after = False
    await rig.advance(40)
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"
    assert not unit.hand_back_owed
    assert ("setpoint", 0.0) not in rig.gateway.calls


async def test_a_blocker_while_the_restore_waits_hands_back_and_tells_where_heating_stops(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Stand-alone: the restore waits for the boiler link; meanwhile VT's own central boiler is
    configured — a blocker: the restore gives way to the owed hand-back, and as a hand-back stops
    heating here, the issue follows once the blocker has held a minute (S-10)."""
    extra = {"topology": "gateway_standalone"}
    stored = restorable(rig, taken_with=taken_with(rig, **extra))
    not_started(rig)
    rig.flow = None
    rig.live()
    await start_with_stored(rig, hass_storage, stored, "0.2.2", **extra)
    await rig.advance(30)
    assert rig.gateway.calls == []
    vt_central_boiler(rig, False)
    await rig.advance(10)
    assert rig.gateway.calls[:3] == [("setpoint", LOWEST), ("ch", True), ("setpoint", 0.0)]
    rig.flow = 35.0
    await rig.advance(70)
    found = stopped_heating(rig)
    assert found is not None


# --- X4: the comfort correction published and reset (P-38, answer J); VT's activation delay
# (decision 5); the circuit alarm (decision 10) --------------------------------------------------


def satisfied_room(rig: Rig, zone: str = "living") -> None:
    rig.zones.set(
        zone,
        hvac_action="idle",
        valve_open_percent=0,
        on_percent=0.0,
        specific_states={"is_device_active": False},
    )


def heating(rig: Rig) -> bool:
    """Heating on/off as last written to the gateway."""
    return [value for kind, value in rig.gateway.calls if kind == "ch"][-1]


def short_room(rig: Rig) -> None:
    """A room short of its setpoint with its valve fully open, the burner on: the comfort
    correction rises 1 K per 30 minutes of heat flow."""
    rig.zones.set(
        "living",
        current_temperature=19.0,
        temperature=21.0,
        hvac_action="heating",
        valve_open_percent=100,
        on_percent=1.0,
    )
    rig.flame = True


def correction(rig: Rig) -> float:
    return float(rig.state("sensor", "control_state").attributes["comfort_correction"])


async def test_the_comfort_correction_is_published(rig: Rig) -> None:
    """P-38: the correction shows as the attribute ``comfort_correction`` of the control state,
    and in diagnostics."""
    from custom_components.vtherm_smart_boiler.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    short_room(rig)
    await start(rig, comfort_correction=True)  # off by default since K4.1
    await rig.advance(3600, step=60)  # an hour of outdoor readings first (rule 5)
    await rig.switch(True)
    assert correction(rig) == 0.0
    await rig.advance(3600, step=60)
    shown = correction(rig)
    assert 1.5 <= shown <= 2.0
    assert rig.entry is not None
    result = await async_get_config_entry_diagnostics(rig.hass, rig.entry)
    assert result["control"]["comfort_correction"] == pytest.approx(shown, abs=0.01)
    assert result["control"]["status"]["correction"] == pytest.approx(shown, abs=0.01)


async def press_reset(rig: Rig) -> None:
    await rig.hass.services.async_call(
        "button",
        "press",
        {"entity_id": rig.entity("button", "reset_comfort_correction")},
        blocking=True,
    )
    await rig.hass.async_block_till_done()


async def test_the_reset_button_resets_the_comfort_correction(rig: Rig) -> None:
    """P-38, answer J: correction 2 K → press → 0 at once in the running control unit, shown at
    once; no hand-back, no reload, no option saved. The rise may start again under its rules —
    what is left of the day's 3 K."""
    short_room(rig)
    await start(rig, comfort_correction=True)  # off by default since K4.1
    await rig.advance(3600, step=60)  # an hour of outdoor readings first (rule 5)
    await rig.switch(True)
    await rig.advance(3600, step=60)
    assert correction(rig) >= 1.5
    assert rig.entry is not None
    entry = rig.entry
    coordinator, options_before = entry.runtime_data, dict(entry.options)
    unit = coordinator.control
    count = len(rig.gateway.calls)
    await press_reset(rig)
    assert correction(rig) == 0.0  # at once, before any step
    assert unit.status.correction == 0.0
    assert unit.enabled
    assert entry.runtime_data is coordinator  # not reloaded
    assert dict(entry.options) == options_before  # nothing saved
    await rig.advance(10)
    assert 0.0 not in rig.gateway.setpoints()[count:]  # nothing handed back
    assert rig.state("sensor", "control_state").state == "heating"
    await rig.advance(3600, step=60)
    assert 0.5 <= correction(rig) <= 1.5  # rising again, within the day's 3 K


async def test_one_room_short_at_the_limit_is_named_with_its_radiator_and_heat_loss_first(
    rig: Rig,
) -> None:
    """G11 B, additions 2 and 3: one room short while the others reach their setpoints counts
    like any other — the correction rises for it, within its limit — and at the limit for three
    hours the warning names that room, its entity ID among the placeholders (J4's Q5), with the
    radiator and the heat loss first among the causes, then the curve."""
    rig.zones.add("bedroom")
    short_room(rig)
    rig.zones.set("bedroom", current_temperature=21.0, temperature=21.0, valve_open_percent=30)
    await start(rig, comfort_correction=True, comfort_correction_max_k=1.0)
    await rig.advance(3600, step=60)  # an hour of outdoor readings first (rule 5)
    await rig.switch(True)
    await rig.advance(1800 + 3 * 3600 + 300, step=60)
    assert correction(rig) == pytest.approx(1.0)  # risen for one room, held at the limit
    found = issue(rig, "curve_too_low")
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_key == "room_short_at_limit"
    assert found.translation_placeholders is not None
    assert found.translation_placeholders["entities"] == rig.zones.entities["living"]


async def test_a_curve_too_low_for_a_room_is_named_at_the_correction_limit(rig: Rig) -> None:
    """G11 B: the correction at the user's limit (1 K here) for three hours with the room still
    short — the information alarm, and a warning repair issue naming the room: the curve is too
    low for it. It goes once the room is no longer short; switching control off takes it too."""
    short_room(rig)
    await start(rig, comfort_correction=True, comfort_correction_max_k=1.0)
    await rig.advance(3600, step=60)  # an hour of outdoor readings first (rule 5)
    await rig.switch(True)
    await rig.advance(1800 + 3 * 3600 - 300, step=60)
    assert correction(rig) == pytest.approx(1.0)  # the user's limit
    assert issue(rig, "curve_too_low") is None  # not three hours at it yet
    await rig.advance(600, step=60)
    found = issue(rig, "curve_too_low")
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_key == "curve_too_low"  # the only room: most of them — the curve first
    assert found.translation_placeholders == {
        "zones": rig.hass.states.get(rig.zones.entities["living"]).name,
        "entities": rig.zones.entities["living"],
        "limit": "1",
    }
    assert rig.state("binary_sensor", "alarm_correction_at_limit").state == "on"
    rig.zones.set("living", current_temperature=21.0, temperature=21.0, valve_open_percent=40)
    await rig.advance(60)
    assert issue(rig, "curve_too_low") is None
    # Short again by a setpoint raised, not by a fall — a sudden fall would read as a window
    # probably open (G11 F).
    rig.zones.set(
        "living",
        current_temperature=21.0,
        temperature=23.0,
        hvac_action="heating",
        valve_open_percent=100,
        on_percent=1.0,
    )
    await rig.advance(60)
    assert issue(rig, "curve_too_low") is not None  # still at the limit, short again
    await rig.switch(False)
    assert issue(rig, "curve_too_low") is None


AUTO_CURVE = {"design_outdoor": -15, "design_flow": 55, "room_mode": "auto"}


def heated(rig: Rig, zone_id: str, target: float) -> None:
    """A room heating towards ``target``, half a kelvin short, its valve half open."""
    rig.zones.set(
        zone_id,
        current_temperature=target - 0.5,
        temperature=target,
        hvac_action="heating",
        valve_open_percent=50,
        on_percent=0.5,
    )


def curve_room(rig: Rig) -> float | None:
    return rig.state("sensor", "control_state").attributes["curve_room"]


async def test_the_auto_curve_room_follows_the_warmest_room(rig: Rig) -> None:
    """G11 D: in Auto the curve passes through the warmest setpoint among the zones that heat,
    shown on the control state: a preset lowering it (eco at night) moves it at the next water
    decision, and one set above 23 °C is capped there."""
    rig.zones.add("bedroom")
    heated(rig, "living", 21.5)
    heated(rig, "bedroom", 19.0)
    await start(rig, curve=AUTO_CURVE)
    await rig.advance(60)
    await rig.switch(True)
    await rig.advance(60)
    assert curve_room(rig) == 21.5
    heated(rig, "living", 18.0)  # eco
    await rig.advance(6 * 60, step=60)  # the next water decision
    assert curve_room(rig) == 19.0
    heated(rig, "bedroom", 25.0)
    await rig.advance(6 * 60, step=60)
    assert curve_room(rig) == 23.0


async def test_the_control_state_shows_the_outdoor_temperature_of_the_curve(rig: Rig) -> None:
    """I10.3c: beside the curve's room temperature, the outdoor temperature the water was decided
    with — the lower of the current and the averaged, as the curve reads it — so the Boiler page
    puts "where we are" on the curve itself; none before a water decision."""
    heated(rig, "living", 21.0)
    await start(rig, curve=AUTO_CURVE)
    await rig.advance(60)
    assert rig.state("sensor", "control_state").attributes["curve_outdoor"] is None
    await rig.switch(True)
    await rig.advance(60)
    assert rig.state("sensor", "control_state").attributes["curve_outdoor"] == round(OUTDOOR, 1)
    rig.outdoor = OUTDOOR - 6.0  # a cold snap is followed at once
    await rig.advance(6 * 60, step=60)  # the next water decision
    assert rig.state("sensor", "control_state").attributes["curve_outdoor"] == round(
        OUTDOOR - 6.0, 1
    )


@pytest.mark.parametrize(
    ("curve", "room"),
    [
        (AUTO_CURVE, 23.0),
        (AUTO_CURVE | {"room_excluded": ["climate.fake_bedroom"]}, 21.5),
        ({"design_outdoor": -15, "design_flow": 55, "room_mode": "manual", "room": 20.5}, 20.5),
    ],
    ids=["auto", "left_out", "manual"],
)
async def test_a_room_left_out_of_auto_or_manual_does_not_move_the_curve(
    rig: Rig, curve: dict[str, Any], room: float
) -> None:
    """G11 D: a zone the user left out — a bathroom kept warmer — is not followed; Manual keeps
    the value entered whatever the rooms ask."""
    rig.zones.add("bedroom")
    heated(rig, "living", 21.5)
    heated(rig, "bedroom", 24.0)
    await start(rig, curve=curve)
    await rig.advance(60)
    await rig.switch(True)
    await rig.advance(60)
    assert curve_room(rig) == room


async def test_the_reset_button_exists_only_with_control_configured(rig: Rig) -> None:
    """Without control, no button; with control switched off (the correction already 0) a
    press changes nothing and raises no error."""
    monitor_only = options(rig.zones)
    del monitor_only["control"]
    entry = add_entry(rig, monitor_only)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    registry = er.async_get(rig.hass)
    key = f"{entry.entry_id}_reset_comfort_correction"
    assert registry.async_get_entity_id("button", DOMAIN, key) is None
    assert await rig.hass.config_entries.async_unload(entry.entry_id)
    await rig.hass.async_block_till_done()


async def test_a_press_with_control_off_changes_nothing(rig: Rig) -> None:
    await start(rig, comfort_correction=True)  # off by default since K4.1
    await press_reset(rig)
    assert correction(rig) == 0.0
    assert rig.gateway.calls == []
    assert rig.state("binary_sensor", "control").state == "off"


def with_circuit(rig: Rig, circuit: dict[str, Any]) -> dict[str, Any]:
    main = {"id": "main", "control": "unmixed_shared"} | circuit
    return options(rig.zones) | {"circuits": [main]}


async def test_the_circuit_too_hot_alarm_is_information_on_the_measured_flow(rig: Rig) -> None:
    """Decision 10: the maximum 40 °C, its alarm pre-filled at 45 °C for 10 minutes: the flow at
    46 °C rises the information alarm after 10 minutes — control goes on, whatever reaction an
    edited option names; it goes below 44 °C. Without a flow reading its state is held for an
    hour, then it is unknown with its reason (Y1, S-16)."""
    entry_options = with_circuit(rig, {"max_flow": 40})
    entry_options["control"]["alarm_reactions"] = {"circuit_too_hot": "hand_back"}
    entry = add_entry(rig, entry_options)
    await set_up(rig, entry)
    await rig.switch(True)
    rig.flow = 46.0
    await rig.advance(540, step=30)
    assert rig.state("binary_sensor", "alarm_circuit_too_hot").state == "off"
    await rig.advance(90, step=30)
    alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
    assert alarm.state == "on"
    assert alarm.attributes["limit"] == 45.0
    assert entry.runtime_data.data.alarms[AlarmKind.CIRCUIT_TOO_HOT].value == 46.0  # P-72
    assert 0.0 not in rig.gateway.setpoints()  # information only: no hand-back
    assert rig.state("binary_sensor", "control").state == "on"
    rig.flow = 44.0
    await rig.advance(60, step=30)
    assert rig.state("binary_sensor", "alarm_circuit_too_hot").state == "on"
    rig.flow = 43.5
    await rig.advance(60, step=30)
    assert rig.state("binary_sensor", "alarm_circuit_too_hot").state == "off"
    rig.flow = None
    await rig.advance(60, step=30)
    alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
    assert alarm.state == "off"  # Y1 (S-16): held an hour without a flow reading...
    assert alarm.attributes["reason"] == "held"
    await rig.advance(3600, step=300)
    alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
    assert alarm.state == "unknown"  # ...then unknown, with its reason
    assert alarm.attributes["reason"] == "no_flow_reading"


@pytest.mark.parametrize("priority", [True, False], ids=["priority", "no_priority"])
async def test_the_circuit_too_hot_alarm_skips_hot_water_on_a_straight_circuit(
    rig: Rig, priority: bool
) -> None:
    """The user's decision of 2026-10-12: a circuit fed straight from the boiler, measured by
    the boiler's flow — 9 minutes at 46 °C, then 20 minutes of hot water at 75 °C, then 46 °C
    again: where hot water has priority the circuit gets none of it, so the alarm does not count
    those minutes and comes on only 10 minutes after the hot water; without priority the rooms
    keep the boiler's water, so the hot water counts and the alarm comes on during it."""
    entry_options = with_circuit(rig, {"max_flow": 40})
    entry_options["boiler"] = entry_options["boiler"] | {"dhw_priority": priority}
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    rig.flow = 46.0
    await rig.advance(540, step=30)
    rig.dhw = True
    rig.flow = 75.0
    await rig.advance(1200, step=30)
    alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
    assert alarm.state == ("off" if priority else "on")
    rig.dhw = False
    rig.flow = 46.0
    if not priority:
        return
    assert alarm.attributes["reason"] == "held"  # the state known before the hot water, kept
    await rig.advance(540, step=30)
    assert rig.state("binary_sensor", "alarm_circuit_too_hot").state == "off"
    await rig.advance(90, step=30)
    alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
    assert alarm.state == "on"
    assert alarm.attributes.get("reason") is None


async def test_no_circuit_alarm_without_a_circuit_maximum(rig: Rig) -> None:
    await start(rig)
    assert rig.entry is not None
    key = f"{rig.entry.entry_id}_alarm_circuit_too_hot"
    assert er.async_get(rig.hass).async_get_entity_id("binary_sensor", DOMAIN, key) is None


@pytest.mark.parametrize("own_sensor", [True, False], ids=["own_sensor", "not_measured"])
async def test_a_fixed_circuit_is_judged_by_its_own_flow_sensor(rig: Rig, own_sensor: bool) -> None:
    """Decision 10: the circuit's own flow sensor where mapped — here 46 °C behind a
    thermostatic valve while the boiler's flow reads 35 °C; without one, a passive fixed circuit
    is not measured: the alarm's feature is inactive and its entity not created (SB-32) — never
    "OK" for a circuit no reading can show."""
    circuit: dict[str, Any] = {"control": "passive_fixed", "fixed_temperature": 35, "max_flow": 40}
    if own_sensor:
        circuit["flow_entity"] = "sensor.floor_flow"
        rig.hass.states.async_set(
            "sensor.floor_flow",
            "46.0",
            {"unit_of_measurement": "°C", "device_class": "temperature"},
        )
    entry = add_entry(rig, with_circuit(rig, circuit))
    await set_up(rig, entry)
    await rig.advance(660, step=30)
    if own_sensor:
        alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
        assert alarm.state == "on"
        assert entry.runtime_data.data.alarms[AlarmKind.CIRCUIT_TOO_HOT].value == 46.0
    else:
        found = er.async_get(rig.hass).async_get_entity_id(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_alarm_circuit_too_hot"
        )
        assert found is None
        feature = entry.runtime_data.data.features[Feature.CIRCUIT_OVERSHOOT_ALARM]
        assert feature.status is FeatureStatus.INACTIVE
        assert feature.missing == ("flow",)


FLOOR_ASKS = "input_boolean.floor_asks"


async def test_a_circuit_run_by_other_automation_asks_through_its_entity(rig: Rig) -> None:
    """I8.8 (decisions F3, F6): the living room fed straight from the boiler, idle; a circuit
    whose mixer another automation runs asks through its entity: heating goes on for it, and
    the water holds its need, 60 °C, nothing added (2026-10-14). Its entity unavailable: it does
    not ask, and the control state says why (the user's answer of 2026-10-12). The analyses
    count its asking as a call for heating, though VT's helper is off (I12.18)."""
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.hass.states.async_set(FLOOR_ASKS, "on")
    floor = {
        "id": "floor",
        "control": "separate",
        "max_flow": 45,
        "request_entity": FLOOR_ASKS,
        "needed_temperature": 60,
    }
    entry_options = with_circuit(rig, {}) | {
        "zones": [{"entity_id": rig.zones.entities["living"], "circuit": "main"}]
    }
    entry_options["circuits"].append(floor)
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    await rig.advance(30)
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"
    assert "circuit_asks" in state.attributes["reasons"]
    assert ("ch", True) in rig.gateway.calls
    assert rig.gateway.setpoints()[-1] == 60.0 > EXPECTED
    history = rig.entry.runtime_data.history
    asks, called = history.circuits_asking[FLOOR_ASKS].last, history.vt_called.last
    assert asks is not None
    assert asks.value is True
    assert called is not None
    assert called.value is False  # VT's helper off: no room calls
    demand = history.zone_demand(asks.t, asks.t + 60.0)
    assert demand is not None
    assert demand.value_at(asks.t + 30.0) is True
    rig.hass.states.async_set(FLOOR_ASKS, "unavailable")
    await rig.advance(30)
    state = rig.state("sensor", "control_state")
    assert state.state == "idle"
    assert "circuit_request_unknown" in state.attributes["reasons"]
    unknown = history.circuits_asking[FLOOR_ASKS].last
    assert unknown is not None
    assert unknown.value is None
    assert [call for call in rig.gateway.calls if call[0] == "ch"][-1] == ("ch", False)


async def test_a_circuit_asking_while_control_runs_rises_to_its_need_exactly(rig: Rig) -> None:
    """F14 (J4 of 2026-10-14, E7): control on and idle, then a circuit run by other automation
    asks — the water rises at the ramp's 1 K/min from the idle setpoint and ends on its need
    itself, the last step within the read-back's tolerance written too."""
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.hass.states.async_set(FLOOR_ASKS, "off")
    heater = {
        "id": "heater",
        "control": "separate",
        "request_entity": FLOOR_ASKS,
        "needed_temperature": 50,
    }
    entry_options = with_circuit(rig, {}) | {
        "zones": [{"entity_id": rig.zones.entities["living"], "circuit": "main"}]
    }
    entry_options["circuits"].append(heater)
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    await rig.advance(60)
    assert rig.state("sensor", "control_state").state == "idle"
    rig.hass.states.async_set(FLOOR_ASKS, "on")
    await rig.advance(20 * 60)  # from the curve's ~38 °C at 1 K/min, with room to spare
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"
    assert "ramp" not in state.attributes["reasons"]
    assert rig.gateway.setpoints()[-1] == 50.0


async def test_a_reset_once_the_unit_stops_does_nothing(rig: Rig) -> None:
    short_room(rig)
    await start(rig, comfort_correction=True)  # off by default since K4.1
    await rig.advance(3600, step=60)  # an hour of outdoor readings first (rule 5)
    await rig.switch(True)
    await rig.advance(1860, step=60)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    before = unit.status.correction
    assert before > 0.0
    await unit.async_stop()
    await unit.async_reset_correction()  # no error, and nothing to do
    assert unit.status.correction == before


# --- X5: configuration refused among the blockers (run time) ------------------------------------


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_a_boiler_ignoring_heating_off_shows_the_blocker_until_off_and_on(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    """X5.21 (answer O, with decision 11): X1's latch with its cause ``heating_off_ignored``,
    as a restart finds it stored: the blocker names it, and switching on while control is on is
    refused with its text; switching control off and on clears it and control runs again. With
    control off, switching on is the second half of that off and on — never refused for it, so
    the user cannot be left unable to clear it."""
    stored = {"latched": True, "latched_by": ["heating_off_ignored"], "enabled": True}
    await start_with_stored(rig, hass_storage, stored, layout)
    await rig.advance(120)
    assert "heating_off_ignored" in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.state("sensor", "control_state").attributes["latched_by"] == ["heating_off_ignored"]
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)  # on already: refused, with the reason
    assert err.value.translation_key == "blocked_heating_off_ignored"
    assert str(err.value).startswith("From the start of the session the boiler did not take")
    assert rig.gateway.setpoints() == []  # nothing written
    await rig.switch(False)
    await rig.switch(True)
    assert "heating_off_ignored" not in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.gateway.setpoints() == [EXPECTED]


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_a_latch_stored_with_control_off_can_still_be_cleared(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    """The latch stored with the wish "off" (the switch was disabled, say): switching on is not
    refused for it; the latch holds, nothing is written, and the next off and on clears it."""
    stored = {"latched": True, "latched_by": ["heating_off_ignored"], "enabled": False}
    await start_with_stored(rig, hass_storage, stored, layout)
    await rig.advance(120)
    assert rig.state("binary_sensor", "control").state == "off"
    await rig.switch(True)  # not refused
    await rig.advance(20)
    assert "heating_off_ignored" in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.gateway.setpoints() == []
    await rig.switch(False)
    await rig.switch(True)
    assert rig.gateway.setpoints() == [EXPECTED]


@pytest.mark.parametrize("latched_by", [None, [], ["pressure_low"]], ids=["none", "empty", "other"])
async def test_a_stored_latch_without_its_cause_is_no_heating_off_blocker(
    rig: Rig, hass_storage: dict[str, Any], latched_by: list[str] | None
) -> None:
    """Negative (X5.21): a stored latch without the cause ``heating_off_ignored`` is read as
    today's latch — control stays handed back until off and on — never as this blocker."""
    stored: dict[str, Any] = {"latched": True, "enabled": True}
    if latched_by is not None:
        stored["latched_by"] = latched_by
    await start_with_stored(rig, hass_storage, stored, "0.2.2")
    await rig.advance(120)
    assert "heating_off_ignored" not in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.gateway.setpoints() == []
    await rig.switch(False)
    await rig.switch(True)
    assert rig.gateway.setpoints() == [EXPECTED]


async def test_a_zone_reconfigured_onto_the_boilers_thermostat_blocks_control(rig: Rig) -> None:
    """X5.19 at run time: VT is reconfigured — the plugin's options unchanged — so the zone is
    built on the gateway's own thermostat climate (its thermostat's ``entry_infos``, I12.7): at
    the next step the blocker ``zone_on_boiler_thermostat`` stops control with the safe
    hand-back; VT set back, control resumes by itself. Negative: the zone's thermostat not handed
    over (VT stopped it: its settings cannot be read) — no blocker."""
    registry = er.async_get(rig.hass)
    thermostat = registry.async_get_or_create(
        "climate", "opentherm_gw", "gw-thermostat", suggested_object_id="gateway_thermostat"
    ).entity_id
    rig.zones.configure("living", underlying_entity_ids=["switch.living_valve"])
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway.setpoints() == [EXPECTED]
    rig.zones.configure("living", underlying_entity_ids=[thermostat])
    await rig.advance(20)
    assert (
        "zone_on_boiler_thermostat" in rig.state("binary_sensor", "control").attributes["blockers"]
    )
    assert rig.gateway.calls[-3:] == HAND_BACK
    count = len(rig.gateway.calls)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # nothing written while it holds
    rig.zones.configure("living", underlying_entity_ids=[])
    await rig.advance(20)
    assert (
        "zone_on_boiler_thermostat"
        not in rig.state("binary_sensor", "control").attributes["blockers"]
    )
    assert rig.gateway.setpoints()[-1] == EXPECTED  # resumed by itself
    rig.zones.configure("living", underlying_entity_ids=[thermostat])
    rig.zones.stop("living")
    await rig.advance(20)
    assert (
        "zone_on_boiler_thermostat"
        not in rig.state("binary_sensor", "control").attributes["blockers"]
    )


async def test_a_hand_edited_room_of_another_kind_is_no_room(rig: Rig) -> None:
    """X5.7, I12.11: the rooms are the thermostats VT hands over — a climate of another
    integration a circuit lists (a hand edit) is never a room nor read, and blocks nothing; the
    rooms on the circuit are those VT counts."""
    other = (
        er.async_get(rig.hass)
        .async_get_or_create("climate", "generic_thermostat", "hall", suggested_object_id="hall")
        .entity_id
    )
    rig.hass.states.async_set(other, "heat")
    living = rig.zones.entities["living"]
    floor = {"id": "floor", "control": "separate", "zones": [other]}
    entry_options = with_circuit(rig, {"zones": [living]})
    entry_options["circuits"].append(floor)
    await set_up(rig, add_entry(rig, entry_options))
    await rig.advance(10)
    assert "zone_not_vt" not in blockers(rig)
    assert other not in rig.entry.runtime_data.link.rooms()
    assert set(rig.entry.runtime_data.data.zones) == set(rig.zones.entities.values())
    assert rig.entry.runtime_data.data.zones[living].circuit_ids == ("main",)


async def test_a_vt_older_than_the_oldest_supported_blocks_control(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I12.6: VT older than 10.6.5 — whose manifest says 10.6.4 — blocks control
    (``vt_too_old``) and switching on is refused. Negative: 10.6.5 read as 10.6.4, and a version
    not known."""
    from custom_components.vtherm_smart_boiler import vtherm_link

    version: dict[str, str | None] = {"now": "10.6.3"}
    monkeypatch.setattr(vtherm_link, "vt_version", lambda _hass: version["now"])
    await start(rig)
    await rig.advance(10)
    assert "vt_too_old" in rig.state("binary_sensor", "control").attributes["blockers"]
    with pytest.raises(ServiceValidationError):
        await rig.switch(True)
    for supported in ("10.6.4", None):
        version["now"] = supported
        await rig.advance(10)
        assert "vt_too_old" not in rig.state("binary_sensor", "control").attributes["blockers"]


async def test_a_gateway_entry_removed_or_disabled_blocks_control(rig: Rig) -> None:
    """X5.5 at run time: the ``opentherm_gw`` entry of the gateway picked disabled while control
    runs — the blocker ``gateway_not_set_up`` hands back; enabled again, control resumes by
    itself. Missing from the start: the blocker too. Negative: an entry only not loaded is Home
    Assistant starting's case, no blocker of its own."""
    from homeassistant.config_entries import ConfigEntryDisabler

    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway.setpoints() == [EXPECTED]
    gateway = rig.hass.config_entries.async_entries("opentherm_gw")[0]
    assert gateway.state is ConfigEntryState.NOT_LOADED  # not running: no blocker
    assert "gateway_not_set_up" not in rig.state("binary_sensor", "control").attributes["blockers"]
    await rig.hass.config_entries.async_set_disabled_by(gateway.entry_id, ConfigEntryDisabler.USER)
    await rig.advance(20)
    assert "gateway_not_set_up" in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.gateway.calls[-3:] == HAND_BACK
    await rig.hass.config_entries.async_set_disabled_by(gateway.entry_id, None)
    await rig.advance(20)
    assert "gateway_not_set_up" not in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.gateway.setpoints()[-1] == EXPECTED
    assert rig.entry is not None
    control = dict(rig.entry.options["control"]) | {"gateway_id": "another_gw"}
    rig.hass.config_entries.async_update_entry(
        rig.entry, options=dict(rig.entry.options) | {"control": control}
    )
    await rig.hass.async_block_till_done()
    await rig.advance(10)
    assert "gateway_not_set_up" in rig.state("binary_sensor", "control").attributes["blockers"]


@pytest.mark.parametrize("mqtt", ["missing", "disabled", "set_up"])
async def test_the_mqtt_path_needs_the_mqtt_integration(rig: Rig, mqtt: str) -> None:
    """X5.5 at run time: the OTGW firmware's path with no MQTT entry, or a disabled one, is
    blocked (``mqtt_not_set_up``); with one, not."""
    from homeassistant.config_entries import ConfigEntryDisabler

    for entry in rig.hass.config_entries.async_entries("mqtt"):
        await rig.hass.config_entries.async_remove(entry.entry_id)
    if mqtt == "disabled":
        MockConfigEntry(domain="mqtt", disabled_by=ConfigEntryDisabler.USER).add_to_hass(rig.hass)
    elif mqtt == "set_up":
        MockConfigEntry(domain="mqtt").add_to_hass(rig.hass)
    await start(rig, write_path="otgw_mqtt", mqtt_top="OTGW", mqtt_node="otgw-1", gateway_id=None)
    await rig.advance(10)
    blockers = rig.state("binary_sensor", "control").attributes["blockers"]
    assert ("mqtt_not_set_up" in blockers) is (mqtt != "set_up")


async def test_an_entity_writer_refuses_one_switch_in_two_roles(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """X5.1 (P-03): options where the heating switch is also the external-control switch — a
    hand edit, or left from an earlier version — while a hand-back is owed: the hand-back fails
    at once, stays owed and is shown for the user to settle, and the switch is not toggled every
    minute. Control itself is blocked (``hand_back_switch_is_heating_switch``)."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    control = held_entity(
        number,
        ch_entity=switch.entity_id,
        ch_write_type="held",
        hand_back="switch",
        hand_back_entity=switch.entity_id,
        hand_back_entity_write_type="held",
    )
    entry = owed_entry(rig, hass_storage, control=options(rig.zones, **control)["control"])
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(300)
    assert switch.writes == []  # never switched on and off
    assert number.writes == []
    assert unit_of(rig).hand_back_owed
    assert issue(rig, "hand_back_owed") is not None
    assert (
        "hand_back_switch_is_heating_switch"
        in (rig.state("binary_sensor", "control").attributes["blockers"])
    )


# --- X6: the thermostat terminals, the OTGW's CH= held, the wall thermostat, the lowest water
# temperature's suggestion ----------------------------------------------------------------------

KIND_ISSUE = "thermostat_kind_missing"


@pytest.mark.parametrize("topology", ["gateway_with_thermostat", "gateway_standalone"])
async def test_a_gateway_entry_without_a_kind_is_blocked_and_told(
    rig: Rig, hass_storage: dict[str, Any], topology: str
) -> None:
    """Answer K: stored gateway options without an answer to the thermostat-terminals question
    (an entry from before 0.2.2) — at the start, the hand-back the last run left owed is still
    made first (V5's safe hand-back: ``CS=<lowest>``, ``CH=1``, ``CS=0``); then control stays
    stopped with the blocker ``thermostat_kind_unknown`` and switching on is refused; the repair
    issue ``thermostat_kind_missing`` (an error, not fixable) asks for the answer, and goes once
    it is stored."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones, topology=topology, thermostat_kind=None),
    )
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, {"controlling": True, "hand_back_pending": True}, "0.2.2")
    await set_up(rig, entry)
    await rig.advance(10)
    assert rig.gateway.calls[:3] == HAND_BACK
    assert "thermostat_kind_unknown" in rig.state("binary_sensor", "control").attributes["blockers"]
    found = issue(rig, KIND_ISSUE)
    assert found is not None
    assert found.severity is ir.IssueSeverity.ERROR
    assert not found.is_fixable
    assert found.translation_key == KIND_ISSUE
    with pytest.raises(ServiceValidationError):
        await rig.switch(True)
    await rig.advance(120)
    assert rig.gateway.setpoints() == [LOWEST, 0.0]  # nothing more written
    answered = options(rig.zones, topology=topology)  # the kind that fits the topology
    rig.hass.config_entries.async_update_entry(entry, options=answered)
    await rig.hass.async_block_till_done()
    assert issue(rig, KIND_ISSUE) is None
    await rig.switch(True)
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # control runs


@pytest.mark.parametrize(
    ("changes", "raised"),
    [
        ({"thermostat_kind": "unknown"}, False),  # "I don't know" is an answer: blocked, no issue
        ({"thermostat_kind": "on_off"}, False),
        ({"thermostat_kind": "opentherm"}, False),
        ({"topology": "virtual", "thermostat_kind": None}, False),  # no terminals to ask about
        ({"thermostat_kind": "a kind this version does not know"}, True),  # answer it again
    ],
)
async def test_the_kind_issue_is_raised_only_for_a_gateway_without_an_answer(
    rig: Rig, changes: dict[str, Any], raised: bool
) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    extra = held_entity(number, ch_entity="switch.ch", ch_write_type="held", **changes)
    if changes.get("topology") != "virtual":
        extra = changes
    await start(rig, **extra)
    await rig.advance(10)
    assert (issue(rig, KIND_ISSUE) is not None) is raised
    blockers = rig.state("binary_sensor", "control").attributes["blockers"]
    blocked = {"unknown": "thermostat_kind_dont_know", "on_off": "thermostat_on_off"}.get(
        str(changes.get("thermostat_kind"))
    )
    if blocked is not None:
        assert blocked in blockers


def no_demand(rig: Rig) -> None:
    """The zone stops asking for heat: control commands "off"."""
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)


@pytest.mark.parametrize("path", ["opentherm_gw", "otgw_mqtt"])
async def test_on_the_gateway_heating_off_goes_out_with_every_keep_alive(
    rig: Rig, path: str
) -> None:
    """Follow-up to X6 (provisional, K4): the PIC keeps ``CH=`` in its RAM until ``CH=1`` or a
    reset — held, sent at once when the gateway comes back — and, as a reset nothing traces
    would lose it, on both OTGW paths it goes out again with every ``CS`` keep-alive, every
    30 s: with "off" commanded, ``CH=0`` each time."""
    published: list[tuple[str, str]] = []
    if path == "otgw_mqtt":

        async def publish(call: ServiceCall) -> None:
            published.append((call.data["topic"], call.data["payload"]))
            if call.data["topic"].endswith("/ctrlsetpt"):
                value = float(call.data["payload"])
                rig.gateway.override = None if value == 0 else value
                rig.gateway.publish()

        rig.hass.services.async_register("mqtt", "publish", publish)
        await start(rig, write_path="otgw_mqtt", mqtt_top="OTGW", mqtt_node="otgw-1")
    else:
        await start(rig)

    def sent() -> list[tuple[str, object]]:
        """Setpoints and heating on/off as the gateway got them, in order."""
        if path == "opentherm_gw":
            return list(rig.gateway.calls)
        commands = {"ctrlsetpt": "setpoint", "chenable": "ch"}
        return [
            (commands[topic.rsplit("/", 1)[1]], float(value) if "ctrl" in topic else value == "1")
            for topic, value in published
        ]

    await rig.switch(True)
    assert sent()[:2] == [("setpoint", EXPECTED), ("ch", True)]
    no_demand(rig)
    await rig.advance(10)
    assert sent()[-1] == ("ch", False)  # "off" commanded
    count = len(sent())
    await rig.advance(300)
    later = sent()[count:]
    keep_alives = [c for c in later if c[0] == "setpoint"]
    offs = [c for c in later if c == ("ch", False)]
    assert len(keep_alives) >= 9  # CS every 30 s
    assert len(offs) >= len(keep_alives)  # CH=0 with every one of them
    assert ("ch", True) not in later
    if path == "opentherm_gw":
        before = rig.gateway.calls.count(("ch", False))
        rig.gateway.connected = False  # the gateway drops: its entities unavailable
        await rig.advance(20)
        rig.gateway.connected = True
        await rig.advance(10)
        assert rig.gateway.calls[-1] == ("ch", False)  # held: sent again once it is back
        assert rig.gateway.calls.count(("ch", False)) > before


async def test_an_entity_paths_held_switch_still_refreshes_every_5_minutes(rig: Rig) -> None:
    """Negative: on the entity path a heating switch declared held keeps X1's refresh — every
    5 minutes, not with the setpoint entity's 30-s keep-alive."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    control = held_entity(
        number, write_type="expiring", ch_entity=switch.entity_id, ch_write_type="held"
    )
    await start(rig, **control)
    await rig.switch(True)
    assert switch.writes == [True]
    await rig.advance(290)
    assert len(number.writes) >= 9  # the setpoint kept alive every 30 s
    assert switch.writes == [True]  # the held switch: not with them
    await rig.advance(10)
    assert switch.writes == [True, True]  # its 5-minute refresh


# The wall thermostat on a gateway: its setpoint as the thermostat device shows it.
ROOM_SETPOINT = "sensor.fake_thermostat_setpoint"
WALL_ISSUE = "wall_thermostat_fallback"


def with_room_setpoint(rig: Rig, **control: Any) -> dict[str, Any]:
    entry_options = options(rig.zones, **control)
    entry_options["signals"] = entry_options["signals"] | {"room_setpoint": ROOM_SETPOINT}
    return entry_options


def wall_setpoint(rig: Rig, value: float | None) -> None:
    shown = "unavailable" if value is None else str(value)
    rig.hass.states.async_set(
        ROOM_SETPOINT, shown, {"unit_of_measurement": "°C", "device_class": "temperature"}
    )


async def test_the_switch_shows_the_wall_thermostat_fallback(rig: Rig) -> None:
    """With an OpenTherm thermostat on the gateway, the control switch shows the temperature the
    wall thermostat keeps after a hand-back, from the optional signal, and warns when it is
    below 15 °C or unknown; a repair issue follows after 30 minutes of either (a warning, not
    fixable), and goes once the value is fine."""
    wall_setpoint(rig, 20.0)
    entry = add_entry(rig, with_room_setpoint(rig))
    await set_up(rig, entry)
    await rig.advance(10)
    attributes = rig.state("binary_sensor", "control").attributes
    assert attributes["wall_thermostat_setpoint"] == 20.0
    assert attributes["wall_thermostat_warning"] is None
    wall_setpoint(rig, 12.0)
    await rig.advance(30)
    attributes = rig.state("binary_sensor", "control").attributes
    assert attributes["wall_thermostat_setpoint"] == 12.0
    assert attributes["wall_thermostat_warning"] == "low"
    await rig.advance(29 * 60)
    assert issue(rig, WALL_ISSUE) is None  # not yet 30 minutes
    await rig.advance(60)
    found = issue(rig, WALL_ISSUE)
    assert found is not None
    assert found.translation_key == "wall_thermostat_fallback"
    assert found.translation_placeholders == {"value": "12.0"}
    assert found.severity is ir.IssueSeverity.WARNING
    assert not found.is_fixable
    wall_setpoint(rig, None)  # low, then unknown: one stretch
    await rig.advance(30)
    attributes = rig.state("binary_sensor", "control").attributes
    assert attributes["wall_thermostat_setpoint"] is None
    assert attributes["wall_thermostat_warning"] == "unknown"
    found = issue(rig, WALL_ISSUE)
    assert found is not None
    assert found.translation_key == "wall_thermostat_fallback_unknown"
    wall_setpoint(rig, 21.0)
    await rig.advance(30)
    assert issue(rig, WALL_ISSUE) is None
    assert rig.state("binary_sensor", "control").attributes["wall_thermostat_warning"] is None


async def test_an_unmapped_wall_thermostat_is_shown_as_not_known_without_an_issue(
    rig: Rig,
) -> None:
    """The missing-data rule: the signal not mapped — control's state says so, and no issue is
    raised, however long (nothing is known to warn about)."""
    await start(rig)
    await rig.advance(31 * 60)
    attributes = rig.state("binary_sensor", "control").attributes
    assert attributes["wall_thermostat_setpoint"] is None
    assert attributes["wall_thermostat_warning"] == "not_mapped"
    assert issue(rig, WALL_ISSUE) is None
    from custom_components.vtherm_smart_boiler.binary_sensor import ControlStateSensor

    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    data, coordinator.data = coordinator.data, None  # no monitor data yet: nothing known
    try:
        shown = ControlStateSensor(coordinator).extra_state_attributes
    finally:
        coordinator.data = data
    assert shown["wall_thermostat_setpoint"] is None
    assert shown["wall_thermostat_warning"] is None


@pytest.mark.parametrize(
    "control",
    [
        {"topology": "gateway_standalone"},
        {"thermostat_kind": "on_off"},
        {"thermostat_kind": None},
        "virtual",
    ],
    ids=["standalone", "on_off", "no_answer", "virtual"],
)
async def test_no_wall_thermostat_is_shown_without_an_opentherm_one(
    rig: Rig, control: dict[str, Any] | str
) -> None:
    """Stand-alone, the virtual topology, or another answer about the terminals: no wall
    thermostat to show, nor an issue — whatever the signal holds."""
    if control == "virtual":
        number = FakeNumber(rig.hass)
        number.register()
        control = held_entity(number, ch_entity="switch.ch", ch_write_type="held")
    assert isinstance(control, dict)
    wall_setpoint(rig, 8.0)
    entry = add_entry(rig, with_room_setpoint(rig, **control))
    await set_up(rig, entry)
    await rig.advance(31 * 60)
    attributes = rig.state("binary_sensor", "control").attributes
    assert "wall_thermostat_setpoint" not in attributes
    assert "wall_thermostat_warning" not in attributes
    assert issue(rig, WALL_ISSUE) is None


SUGGESTION_ISSUE = "lowest_water_suggestion"


def short_burns(coordinator: Any, now: float, setpoint: float, *, read_back: bool) -> None:
    """Thirty 3-minute heating burns at ``setpoint`` over the last hours, each ended because the
    water was warm enough while the room still called — put into the coordinator's history."""
    from custom_components.vtherm_smart_boiler.core.series import Series

    history = coordinator.history
    flame: Series[bool] = Series([(now - 7 * 3600.0, False)])
    flow: Series[float] = Series([(now - 7 * 3600.0, setpoint - 8.0)])
    setpoints: Series[float] = Series([(now - 7 * 3600.0, setpoint)])
    t = now - 6 * 3600.0
    for _ in range(30):
        flame.append(t, True)
        flow.append(t + 170.0, setpoint + 0.5)
        flame.append(t + 180.0, False)
        flow.append(t + 240.0, setpoint - 8.0)
        t += 600.0
    history.signals[Signal.FLAME] = flame
    history.signals[Signal.FLOW] = flow
    if read_back:
        history.setpoint_read_back = setpoints
    else:
        history.signals[Signal.CH_SETPOINT] = setpoints
    zone = next(iter(history.zones.values()))
    zone.calling = Series([(now - 7 * 3600.0, True)])
    zone.valve_open = Series([(now - 7 * 3600.0, 1.0)])


def suggestion_sensor(rig: Rig) -> State:
    return rig.state("sensor", "lowest_water_suggestion")


@pytest.mark.parametrize("own", [False, True], ids=["signal", "section_own"])
async def test_under_control_the_suggestion_is_the_settings_own(rig: Rig, own: bool) -> None:
    """While the plugin sets the water: the reference is the lowest water temperature set, the
    source the setpoint the boiler received, recorded into the history as control writes —
    the CH setpoint signal, which the read-back is (I8.5b, decision D3), or a control section's
    own read-back (a hand edit) where the signal is not mapped; thirty short burns at it suggest
    it + 2 K, with the issue worded for the plugin's option. Nothing is written for it."""
    if own:
        stored = options(rig.zones)
        stored["control"] = taken_with(rig)  # as its migrations left it (X6)
        await set_up(rig, add_current_entry(rig, stored))
    else:
        await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    history = coordinator.history
    series = history.setpoint_read_back if own else history.signals[Signal.CH_SETPOINT]
    assert EXPECTED in [s.value for s in series]  # the read-back, recorded live
    written = list(rig.gateway.calls)
    now = dt_util.utcnow().timestamp()
    short_burns(coordinator, now, LOWEST, read_back=own)
    await analyse_now(coordinator)
    state = suggestion_sensor(rig)
    assert float(state.state) == LOWEST + 2.0
    attributes = state.attributes
    assert attributes["state"] == "suggestion"
    assert attributes["source"] == ("read_back" if own else "ch_setpoint")
    assert attributes["reference"] == LOWEST
    assert attributes["counted_burns"] == 30
    assert attributes["short_share"] == 100.0
    assert attributes["window_days"] == 7
    assert attributes["missing"] == []
    found = issue(rig, SUGGESTION_ISSUE)
    assert found is not None
    assert found.translation_key == SUGGESTION_ISSUE
    assert found.severity is ir.IssueSeverity.WARNING
    assert not found.is_fixable
    assert found.translation_placeholders == {
        "days": "7",
        "short": "30",
        "burns": "30",
        "reference": f"{LOWEST:.1f}",
        "limit": "10",
        "value": f"{LOWEST + 2.0:.1f}",
    }
    assert rig.gateway.calls == written  # the suggestion writes nothing
    assert rig.entry.options["control"]["hard_min"] == LOWEST  # nor changes the setting


async def test_with_control_off_the_read_back_is_no_source(rig: Rig) -> None:
    """Control off: the boiler's own curve or its thermostat sets the water, and a control
    section's own read-back (a hand edit, I8.5b) counts only while the plugin sets it — without
    the CH setpoint signal the suggestion is inactive, naming it, and nothing is told."""
    await set_up(rig, add_current_entry(rig, options(rig.zones)))
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    short_burns(coordinator, dt_util.utcnow().timestamp(), 30.0, read_back=True)
    await analyse_now(coordinator)
    state = suggestion_sensor(rig)
    assert state.state == "unknown"
    assert state.attributes["state"] == "inactive"
    assert state.attributes["missing"] == ["ch_setpoint"]
    assert issue(rig, SUGGESTION_ISSUE) is None


async def test_with_control_off_the_suggestion_is_worded_for_the_device(rig: Rig) -> None:
    """Control off, the CH setpoint signal mapped: the reference is the lowest setpoint the
    boiler showed, and the issue is worded for the device that sets the water — never the
    plugin's option, never a parallel shift of its curve."""
    entry_options = options(rig.zones)
    entry_options["signals"] = entry_options["signals"] | {
        "ch_setpoint": BOILER_ENTITIES[Signal.CH_SETPOINT]
    }
    await set_up(rig, add_entry(rig, entry_options))
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    short_burns(coordinator, dt_util.utcnow().timestamp(), 30.0, read_back=False)
    await analyse_now(coordinator)
    state = suggestion_sensor(rig)
    assert float(state.state) == 32.0
    assert state.attributes["source"] == "ch_setpoint"
    assert state.attributes["reference"] == 30.0
    found = issue(rig, SUGGESTION_ISSUE)
    assert found is not None
    assert found.translation_key == "lowest_water_suggestion_boiler"
    assert found.translation_placeholders is not None
    assert found.translation_placeholders["value"] == "32.0"


async def test_no_suggestion_while_a_standalone_gateway_is_handed_back(rig: Rig) -> None:
    """Stand-alone and handed back, nothing heats: no suggestion, no issue."""
    await start(rig, topology="gateway_standalone")
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    short_burns(coordinator, dt_util.utcnow().timestamp(), 30.0, read_back=False)
    await analyse_now(coordinator)
    state = suggestion_sensor(rig)
    assert state.state == "unknown"
    assert state.attributes["state"] == "not_applicable"
    assert issue(rig, SUGGESTION_ISSUE) is None


async def test_a_failing_evaluation_keeps_the_last_suggestion_and_the_analysis(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The evidence's evaluation failing (a bug): the last suggestion is kept, the analysis is
    published all the same, the failure is logged once — and nothing is written."""
    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    await start(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    short_burns(coordinator, dt_util.utcnow().timestamp(), 30.0, read_back=False)
    await analyse_now(coordinator)
    before = coordinator.lowest_water
    assert before is not None
    written = list(rig.gateway.calls)

    def broken(*_args: Any) -> None:
        raise RuntimeError("a bug in the evaluation")

    monkeypatch.setattr(coordinator_module, "suggest_lowest_water", broken)
    coordinator.analysis = None
    await analyse_now(coordinator)
    await analyse_now(coordinator)
    assert coordinator.lowest_water is before
    assert coordinator.analysis is not None  # the analysis itself went on
    failures = [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING and "lowest water temperature's evidence" in r.message
    ]
    assert len(failures) == 1  # logged once, not at every run
    assert rig.gateway.calls == written


# --- X8: on/off control through a relay (class 3) ---------------------------------------------

RELAY = "switch.fake_boiler_relay"
START_TRACE_S = 310.0  # past the five minutes a unit's start counts as a trace of an outage


class _RelayEntity(SwitchEntity):
    """The relay's switch entity, as its integration would add it."""

    _attr_should_poll = False
    _attr_name = "Fake boiler relay"
    _attr_unique_id = "fake_boiler_relay"

    def __init__(self, relay: FakeRelay) -> None:
        self.entity_id = relay.entity_id
        self._relay = relay

    @property
    def is_on(self) -> bool:
        return self._relay.on

    @property
    def available(self) -> bool:
        return self._relay.available

    @property
    def assumed_state(self) -> bool:
        return self._relay.assumed

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._relay.turned(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._relay.turned(False)


@dataclass
class FakeRelay:
    """A relay on the boiler's room-thermostat terminals as Home Assistant shows it — a Shelly,
    Tasmota or Zigbee relay: a real switch entity, switched by the plugin's calls, which it may
    not take (``takes``), or by something else; out of reach, back in another state after a
    power cut, or an optimistic entity (``assumed``). Home Assistant calls no unavailable
    entity."""

    hass: HomeAssistant
    entity_id: str = RELAY
    on: bool = False
    available: bool = True
    takes: bool = True
    assumed: bool = False
    calls: list[bool] = field(default_factory=list)
    entity: _RelayEntity | None = None
    # An old automation that puts the relay back a second after every call of the plugin's that
    # changed it (PB-01): the test's clock, to move that second on. ``reverts_itself``: the
    # relay's own logic does it (an "inching" mode, a script on the device), so Home Assistant
    # files the change under the caller's context, as it does for a few seconds after a call.
    reverts: Any = None
    reverts_itself: bool = False

    def turned(self, on: bool) -> None:
        """A call reached it — with the caller's context, which Home Assistant keeps."""
        self.calls.append(on)
        before = self.on
        if self.takes:
            self.on = on
        assert self.entity is not None
        self.entity.async_write_ha_state()
        if self.reverts is not None and self.on != before:
            self.reverts.tick(1)  # a second later, before any step looks again
            if self.reverts_itself:
                self.on = before
                self.entity.async_write_ha_state()
            else:
                self.switch(before)

    def publish(self) -> None:
        """A report of its own, with a context of its own (not the plugin's)."""
        assert self.entity is not None
        self.entity.async_set_context(Context())
        self.entity.async_write_ha_state()

    def switch(self, on: bool) -> None:
        """Something else — an automation, its own button — switches it while it stays up."""
        self.on = on
        self.publish()

    def away(self) -> None:
        self.available = False
        self.publish()

    def back(self, on: bool) -> None:
        """Back after a power or link loss, in ``on``."""
        self.available = True
        self.on = on
        self.publish()


@pytest.fixture
async def relay(rig: Rig) -> FakeRelay:
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import setup_test_component_platform

    fake = FakeRelay(rig.hass)
    fake.entity = _RelayEntity(fake)
    setup_test_component_platform(rig.hass, "switch", [fake.entity])
    assert await async_setup_component(rig.hass, "switch", {"switch": {"platform": "test"}})
    await rig.hass.async_block_till_done()
    return fake


def relay_options(
    zones: FakeZones, signals: tuple[Signal, ...] = SIGNALS, **control: Any
) -> dict[str, Any]:
    """An on/off boiler switched through a relay that reports its state, starts off after a power
    cut and has no timer — the separate-contact tick given (answer G)."""
    return {
        "signals": {s.value: BOILER_ENTITIES[s] for s in signals},
        "boiler": {"class": "on_off", "dhw": "combi"},
        "monitor": {"monitoring_days": 0},
        "control": {
            "write_path": "relay",
            "relay_entity": RELAY,
            "relay_is_separate_contact": True,
            "relay_reports_state": "yes",
            "relay_power_on_state": "off",
            "relay_off_timer": "none",
            "vt_boiler_helper": zones.helper,  # I12
        }
        | control,
    }


async def start_relay(rig: Rig, signals: tuple[Signal, ...] = SIGNALS, **control: Any) -> None:
    entry = add_entry(rig, relay_options(rig.zones, signals, **control))
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry


def calling(rig: Rig, on: bool = True) -> None:
    if on:
        rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    else:
        rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)


def control_alarm(rig: Rig, kind: str) -> str:
    return rig.state("binary_sensor", f"alarm_{kind}").state


def name_of(rig: Rig, entity_id: str) -> str:
    state = rig.hass.states.get(entity_id)
    assert state is not None
    return state.name


async def test_relay_control_follows_vt_both_ways(rig: Rig, relay: FakeRelay) -> None:
    """The relay goes on and off with the zones, at once; written on a mismatch only — no
    repeats for a relay that reports its state and has no timer; switched off, control hands
    back to the rest state, "off"."""
    await start_relay(rig)
    await rig.switch(True)
    assert relay.calls == [True]
    calling(rig, False)
    await rig.advance(10)
    assert relay.calls == [True, False]
    calling(rig)
    await rig.advance(10)
    assert relay.calls == [True, False, True]
    await rig.advance(3600)
    assert relay.calls == [True, False, True]
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"
    assert state.attributes["relay_state"] == "on"
    assert state.attributes["relay_check"] == "confirmed"
    switch = rig.state("binary_sensor", "control")
    assert switch.attributes["off_by"] == "relay"
    assert switch.attributes["hand_back_effect"] == "relay_rests_off"
    assert switch.attributes["confirmation"] is None
    assert rig.entry is not None
    registry = er.async_get(rig.hass)
    setpoint = f"{rig.entry.entry_id}_control_setpoint"
    assert registry.async_get_entity_id("sensor", DOMAIN, setpoint) is None  # R15
    link = f"{rig.entry.entry_id}_alarm_boiler_link_lost"
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, link) is None
    await rig.switch(False)
    assert relay.calls[-1] is False
    assert not relay.on
    assert rig.state("sensor", "control_state").attributes["hand_back_confirmation"] == "confirmed"


async def test_a_relay_out_of_reach_alarms_and_never_hands_back(rig: Rig, relay: FakeRelay) -> None:
    """R6: nothing is written while the relay is out of reach, and nothing handed back — it
    could not arrive; after five minutes the alarm and its repair issue; back after a power cut,
    it gets the command at once."""
    await start_relay(rig)
    await rig.switch(True)
    relay.away()
    await rig.advance(290)
    assert control_alarm(rig, "relay_unreachable") == "off"
    assert issue(rig, "relay_unreachable") is None
    await rig.advance(20)
    assert control_alarm(rig, "relay_unreachable") == "on"
    found = issue(rig, "relay_unreachable")
    assert found is not None
    assert found.translation_key == "relay_unreachable_off"
    assert found.translation_placeholders == {"relay": name_of(rig, RELAY)}
    assert relay.calls == [True]  # no write, no rest state
    assert rig.state("sensor", "control_state").state == "heating"  # control keeps deciding
    assert control_alarm(rig, "hand_back_failed") == "off"
    relay.back(False)
    await rig.advance(10)
    assert relay.calls == [True, True]
    assert relay.on
    assert control_alarm(rig, "relay_unreachable") == "off"
    assert issue(rig, "relay_unreachable") is None
    # Flame and flow never gate a relay: the boiler's signals lost, control goes on.
    rig.flow = None
    rig.flame = None
    await rig.advance(600)
    assert rig.state("sensor", "control_state").state == "heating"
    assert relay.calls == [True, True]


async def test_a_relay_restart_gets_the_command_again(rig: Rig, relay: FakeRelay) -> None:
    """Answer C: back from a power cut in another state — the command at once, counted; the
    third within a day raises "commands lost", information only."""
    await start_relay(rig)
    await rig.switch(True)
    for n in (1, 2, 3):
        await rig.advance(130)  # past the last send's confirmation window
        relay.away()
        await rig.advance(30)
        relay.back(False)
        await rig.advance(10)
        assert relay.calls[-1] is True, n
        assert relay.on
        assert control_alarm(rig, "commands_lost") == ("on" if n == 3 else "off"), n
    assert control_alarm(rig, "outside_change") == "off"
    assert rig.state("sensor", "control_state").state == "heating"


@pytest.mark.parametrize(("rest", "severity"), [("off", "error"), ("on", "warning")])
async def test_a_relay_switched_by_an_automation_is_rewritten_once_then_handed_back(
    rig: Rig, relay: FakeRelay, rest: str, severity: str
) -> None:
    """Answers C, H and L: commanded off, switched on by an automation while it stayed
    available — written back once; the second time within a day the plugin steps aside: the
    rest state written once (unless the relay reads it already), then nothing, even when the
    automation switches the relay again at once. The latch and its repair issue survive a
    restart; switching control off and on clears them."""
    calling(rig, False)
    await start_relay(rig, relay_rest_state=rest)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    relay.switch(True)
    await rig.advance(10)
    assert relay.calls == [False]  # rewritten once
    assert not relay.on
    await rig.advance(130)  # past the rewrite's own confirmation window
    relay.switch(True)
    await rig.advance(20)
    expected = [False, False] if rest == "off" else [False]  # "on" is read already
    assert relay.calls == expected
    relay.switch(not relay.on)  # the automation again, at once
    await rig.advance(600)
    assert relay.calls == expected  # left alone
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.state("sensor", "control_state").attributes["relay_check"] is not None
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == f"control_latched_relay_{rest}"
    assert found.severity.value == severity
    assert found.translation_placeholders == {"relay": name_of(rig, RELAY)}
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(60)
    assert relay.calls == expected
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert issue(rig, "control_latched") is not None
    await rig.switch(False)
    await rig.switch(True)
    assert issue(rig, "control_latched") is None
    assert rig.state("sensor", "control_state").state == "idle"


async def test_a_relay_rest_state_changed_after_the_hand_back_is_left(
    rig: Rig, relay: FakeRelay
) -> None:
    """R9 (V5's two-valued rule): control switched off — the rest state read back once, the
    hand-back is done; changed afterwards with no trace, it is left to whoever changed it. Never
    read back, the hand-back stays owed and is sent again every minute."""
    await start_relay(rig)
    await rig.switch(True)
    await rig.switch(False)
    assert relay.calls == [True, False]
    relay.switch(True)
    await rig.advance(600)
    assert relay.calls == [True, False]  # not retried
    relay.switch(False)
    relay.takes = False  # a relay that does not take "off": never read back
    await rig.switch(True)
    assert relay.calls[-1] is True
    relay.on = True
    relay.publish()
    await rig.switch(False)
    await rig.advance(60)
    offs = [call for call in relay.calls[3:] if call is False]
    assert len(offs) >= 2  # owed, and sent again after a minute
    assert rig.entry is not None
    assert rig.entry.runtime_data.control.hand_back_owed


@pytest.mark.parametrize("power_on", ["off", "unknown"])
async def test_a_relay_that_keeps_restarting_steps_aside_on_the_fourth_time(
    rig: Rig, relay: FakeRelay, power_on: str
) -> None:
    """Answer N: found off — its declared state after a power cut — with no trace while it
    stayed available (or, with "I don't know", any change): a restart the relay did not report,
    answered three times within a day; the fourth steps aside with the rest state once (here the
    relay reads "off" already), and the latch survives a restart."""
    await start_relay(rig, relay_power_on_state=power_on)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    for n in (1, 2, 3):
        relay.switch(False)
        await rig.advance(10)
        assert relay.calls[-1] is True, n
        assert relay.on
        await rig.advance(600)
    count = len(relay.calls)
    relay.switch(False)
    await rig.advance(20)
    assert relay.calls[count:] == []  # stepping aside: no rewrite, the rest state read already
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert issue(rig, "control_latched") is not None
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(60)
    assert relay.calls[count:] == []
    assert rig.state("sensor", "control_state").state == "handed_back"


async def test_a_planned_restart_rests_then_restores_at_once(rig: Rig, relay: FakeRelay) -> None:
    """R11: a planned stop sets the rest state; the next start gives the stored command at its
    first step."""
    await start_relay(rig)
    await rig.switch(True)
    await rig.advance(120)
    assert relay.calls == [True]
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert relay.calls == [True, False]  # the rest state at the stop
    assert await rig.hass.config_entries.async_setup(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert relay.calls == [True, False, True]  # at once: no hand-back first
    await rig.advance(600)
    assert relay.calls == [True, False, True]


def relay_restorable(rig: Rig, **changes: Any) -> dict[str, Any]:
    """The control store a run that held the relay left — a crash, by default."""
    return {
        "enabled": True,
        "controlling": True,
        "last_command": {"heating": True, "setpoint": None, "at": START.timestamp()},
        # As the entry holds them after its migration, which keeps the lowest water temperature.
        "taken_with": relay_options(rig.zones)["control"] | {"hard_min": LOWEST},
    } | changes


async def start_relay_with_stored(
    rig: Rig, hass_storage: dict[str, Any], control: dict[str, Any] | None
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=relay_options(rig.zones)
    )
    entry.add_to_hass(rig.hass)
    if control is None:
        seed_main(hass_storage, entry)  # the control store lost: it counts as holding (answer K)
    else:
        seed_stores(hass_storage, entry, control, "0.2.2")
    await set_up(rig, entry)


async def test_a_crash_restores_without_a_hand_back_first(
    rig: Rig, relay: FakeRelay, hass_storage: dict[str, Any]
) -> None:
    """R11: after a crash the relay gets the stored command at once — no rest state first."""
    await start_relay_with_stored(rig, hass_storage, relay_restorable(rig))
    await rig.advance(20)
    assert relay.calls == [True]
    assert rig.entry is not None
    assert not rig.entry.runtime_data.control.hand_back_owed


async def test_an_unreadable_store_hands_a_relay_back_first(
    rig: Rig, relay: FakeRelay, hass_storage: dict[str, Any]
) -> None:
    """Answer K: a lost control store means "was controlling": the rest state first."""
    relay.on = True
    relay.publish()
    await start_relay_with_stored(rig, hass_storage, None)
    await rig.advance(20)
    assert relay.calls[0] is False


@pytest.mark.parametrize("case", ["wish_off", "latched", "blocked", "options_differ", "no_command"])
async def test_no_restore_when_the_wish_was_off_or_latched_or_blocked(
    rig: Rig, relay: FakeRelay, hass_storage: dict[str, Any], case: str
) -> None:
    """R11's negatives: the relay is not given the stored command — it goes to its rest state,
    the owed hand-back."""
    relay.on = True
    relay.publish()
    changes: dict[str, Any] = {
        "wish_off": {"enabled": False},
        "latched": {"latched": True, "latched_by": ["outside_change"]},
        "options_differ": {
            "taken_with": relay_options(rig.zones, relay_repeat_s=60)["control"]
            | {"hard_min": LOWEST}
        },
        "no_command": {"last_command": None},
    }.get(case, {})
    if case == "blocked":
        vt_central_boiler(rig, False)
    await start_relay_with_stored(rig, hass_storage, relay_restorable(rig, **changes))
    await rig.advance(20)
    assert relay.calls[:1] == [False]  # the rest state, never the stored "on" first


async def test_an_owed_relay_hand_back_is_folded_when_control_resumes(
    rig: Rig, relay: FakeRelay
) -> None:
    """R9: a hand-back owed (the relay was away) and control on again as the relay returns in
    the commanded state: only the command — nothing written, as it shows it — no off-then-on."""
    await start_relay(rig)
    await rig.switch(True)
    relay.away()
    await rig.switch(False)  # the rest state cannot reach it: owed
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert unit.hand_back_owed
    relay.back(True)
    await rig.switch(True)
    assert relay.calls == [True]
    assert not unit.hand_back_owed
    await rig.advance(120)
    assert relay.calls == [True]
    await rig.switch(False)
    assert relay.calls == [True, False]  # the session's own hand-back at its end


async def test_the_rest_state_notice_when_a_zone_calls(rig: Rig, relay: FakeRelay) -> None:
    """R10: control not holding a relay resting "off", a zone calling: a repair issue naming it;
    not for a room near freezing that does not call (frost protection is VT's, I12.10); it goes
    once control takes the relay, or the relay is on (another controller took it)."""
    await start_relay(rig)
    await rig.switch(True)
    await rig.switch(False)  # control held the relay and handed it back
    await rig.advance(10)
    found = issue(rig, "relay_rests_off")
    assert found is not None
    zone = name_of(rig, rig.zones.entities["living"])
    assert found.translation_placeholders == {"zones": zone}
    relay.switch(True)  # someone switched it on: the boiler may heat
    await rig.advance(10)
    assert issue(rig, "relay_rests_off") is None
    relay.switch(False)
    calling(rig, False)
    await rig.advance(10)
    assert issue(rig, "relay_rests_off") is None
    rig.zones.set("living", "off", current_temperature=4.0, valve_open_percent=10)
    await rig.advance(10)
    assert issue(rig, "relay_rests_off") is None  # near freezing, but VT does not call
    calling(rig)
    await rig.advance(10)
    assert issue(rig, "relay_rests_off") is not None
    await rig.switch(True)
    await rig.advance(10)
    assert issue(rig, "relay_rests_off") is None


@pytest.mark.parametrize("vt_heats", [False, True])
async def test_no_rest_state_notice_before_control_held_the_relay(
    rig: Rig, relay: FakeRelay, vt_heats: bool
) -> None:
    """PB-15: control never held the relay in this run — before it was ever switched on, or in
    the migration's monitoring week while VT's central boiler still drives the relay: no notice
    that the boiler does not heat while control is off."""
    if vt_heats:
        vt_central_boiler(rig, False)
    await start_relay(rig)  # control cannot be switched on while VT's central boiler is
    await rig.advance(30)
    assert issue(rig, "relay_rests_off") is None


async def test_no_rest_state_notice_for_a_relay_resting_on(rig: Rig, relay: FakeRelay) -> None:
    await start_relay(rig, relay_rest_state="on")
    await rig.advance(10)
    assert issue(rig, "relay_rests_off") is None


@pytest.mark.parametrize(
    ("reports", "assumed", "signals", "shown"),
    [
        ("no", False, SIGNALS, "controlled_without_confirmation"),
        ("unknown", False, SIGNALS, "controlled_without_confirmation"),
        ("yes", True, SIGNALS, "controlled_without_confirmation"),
        ("yes", False, (Signal.OUTDOOR,), "without_heat_confirmation"),
        ("yes", False, SIGNALS, None),
    ],
)
async def test_controlled_without_confirmation_is_shown(
    rig: Rig,
    relay: FakeRelay,
    reports: str,
    assumed: bool,
    signals: tuple[Signal, ...],
    shown: str | None,
) -> None:
    relay.assumed = assumed
    relay.publish()
    await start_relay(rig, signals, relay_reports_state=reports)
    await rig.switch(True)
    assert rig.state("binary_sensor", "control").attributes["confirmation"] == shown
    check = rig.state("sensor", "control_state").attributes["relay_check"]
    assert (check == "unverified") is (shown == "controlled_without_confirmation")


async def test_boiler_not_responding_after_thirty_minutes(rig: Rig, relay: FakeRelay) -> None:
    """R12: 30 minutes of the relay on, a proof input known and no sign of heat — the
    information alarm; it clears on any proof. Without a proof input: never, and the status
    says so."""
    await start_relay(rig)
    await rig.switch(True)
    await rig.advance(1790)
    assert control_alarm(rig, "boiler_not_responding") == "off"
    await rig.advance(20)
    assert control_alarm(rig, "boiler_not_responding") == "on"
    assert rig.state("sensor", "control_state").attributes["boiler_heats"] == "not_seen"
    assert issue(rig, NO_HEAT_SIGN) is None  # the water paths' issue (decision 2 of 0.2.3)
    rig.flame = True
    await rig.advance(10)
    assert control_alarm(rig, "boiler_not_responding") == "off"
    assert rig.state("sensor", "control_state").attributes["boiler_heats"] == "heats"
    assert rig.state("sensor", "control_state").state == "heating"  # information only


async def test_no_heat_alarm_without_a_proof_input(rig: Rig, relay: FakeRelay) -> None:
    """Without a proof input the proof is inactive (the missing-data rule, Y4): no alarm entity,
    the boiler's heat shown unverified, and control "without heat confirmation"."""
    await start_relay(rig, (Signal.OUTDOOR,))
    await rig.switch(True)
    await rig.advance(2100)
    assert rig.entry is not None
    key = f"{rig.entry.entry_id}_alarm_boiler_not_responding"
    assert er.async_get(rig.hass).async_get_entity_id("binary_sensor", DOMAIN, key) is None
    assert rig.state("sensor", "control_state").attributes["boiler_heats"] == "unverified"
    switch = rig.state("binary_sensor", "control")
    assert switch.attributes["confirmation"] == "without_heat_confirmation"


NO_HEAT_SIGN = "no_sign_boiler_heats"


def no_heat_sign(rig: Rig) -> tuple[str, ir.IssueEntry | None]:
    """The water paths' "no sign the boiler heats": its alarm and its repair issue."""
    return control_alarm(rig, "boiler_not_responding"), issue(rig, NO_HEAT_SIGN)


async def test_no_sign_the_boiler_heats_on_a_water_path(rig: Rig) -> None:
    """Decision 2 of 0.2.3 (SB-01), the review's test: the gateway path, a calling zone, heating
    on and the flame off — nothing at 29 minutes; at 31 the information alarm and a warning
    repair issue, control still writing, no hand-back; the flame on clears both."""
    await start(rig)
    await rig.switch(True)
    assert rig.flow is not None
    assert rig.flow < rig.gateway.setpoints()[-1]
    await rig.advance(29 * 60)
    assert no_heat_sign(rig) == ("off", None)
    await rig.advance(2 * 60)
    alarm, found = no_heat_sign(rig)
    assert alarm == "on"
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_placeholders == {"minutes": "30"}
    calls = len(rig.gateway.calls)
    await rig.advance(60)
    assert rig.gateway.calls[calls:]  # control goes on writing
    state = rig.state("sensor", "control_state")
    assert (state.state, state.attributes["latched_by"]) == ("heating", [])
    rig.flame = True
    await rig.advance(10)
    assert no_heat_sign(rig) == ("off", None)


async def test_no_sign_the_boiler_heats_waits_for_water_below_the_setpoint(rig: Rig) -> None:
    """The water at the setpoint the plugin wrote (the gateway's value, on its 0.1-K step): a
    boiler resting as asked is not judged."""
    await start(rig)
    await rig.switch(True)
    rig.flow = rig.gateway.setpoints()[-1] + 0.1
    await rig.advance(40 * 60)
    assert no_heat_sign(rig) == ("off", None)


@pytest.mark.parametrize("pause", ["zone", "hot_water"])
async def test_no_sign_the_boiler_heats_counts_again_after_a_pause(rig: Rig, pause: str) -> None:
    """The zone that stops calling, or a hot-water draw (and two minutes after it), starts the
    count again."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20 * 60)
    if pause == "zone":
        rig.zones.set("living", valve_open_percent=0)
    else:
        rig.dhw = True
    await rig.advance(60)
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig.dhw = False
    await rig.advance(27 * 60)
    assert no_heat_sign(rig) == ("off", None)  # 48 minutes, at most 27 of them counted
    await rig.advance(6 * 60)
    assert no_heat_sign(rig)[0] == "on"


async def test_no_sign_the_boiler_heats_needs_heating_commanded_and_a_sign_known(
    rig: Rig,
) -> None:
    """Control switched off — the boiler handed back — clears the alarm and its issue, and
    counts nothing; neither the flame nor the flow known judges nothing (the boiler link is
    lost, and control hands back)."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(31 * 60)
    assert no_heat_sign(rig)[0] == "on"
    await rig.switch(False)
    assert no_heat_sign(rig) == ("off", None)
    await rig.advance(40 * 60)
    assert no_heat_sign(rig) == ("off", None)
    await rig.switch(True)
    rig.flame = None
    rig.flow = None
    await rig.advance(40 * 60)
    assert no_heat_sign(rig) == ("off", None)


async def test_only_the_relays_services_are_called(rig: Rig, relay: FakeRelay) -> None:
    await start_relay(rig)
    await rig.switch(True)
    calling(rig, False)
    await rig.advance(30)
    await rig.switch(False)
    made = {
        (domain, service)
        for domain, service, _data in rig.services
        if (domain, service) != ("vtherm_smart_boiler", "set_control")  # the test's own
    }
    assert made == {("switch", "turn_on"), ("switch", "turn_off")}
    allowed = rig.state("binary_sensor", "control").attributes["allowed_services"]
    assert set(allowed) <= {"switch.turn_on", "switch.turn_off"}


@pytest.mark.parametrize("command", [True, False])
async def test_a_relay_that_never_takes_the_command_raises_relay_ignored(
    rig: Rig, relay: FakeRelay, command: bool
) -> None:
    """R7: never the commanded state for 120 s after each of the session's first three sends —
    not written again this session; "write ignored" names the relay and a repair issue (an
    error) says so. Where it is "off" it ignores, control is blocked (answer O): the boiler may
    keep heating; where it is "on", alike (decision 4 of 0.2.3, SB-03): the house is not heated.
    Either way the relay is handed back to its rest state, written once, with the latch's
    error-level issue (before, for "on": no block, no hand-back)."""
    relay.on = not command
    relay.takes = False
    relay.publish()
    calling(rig, command)
    # The rest state the relay does not read: the hand-back writes it.
    await start_relay(rig, relay_rest_state="on" if command else "off")
    # Past the unit's start, a trace of an outage: sends within it are lost commands, not the
    # start phase's attempts (X1's rule).
    await rig.advance(START_TRACE_S)
    await rig.switch(True)
    await rig.advance(720)
    sends = [call for call in relay.calls if call is command]
    assert len(sends) == 3
    write_ignored = rig.state("binary_sensor", "alarm_write_ignored")
    assert write_ignored.state == "on"
    assert write_ignored.attributes["targets"] == ["relay"]
    found = issue(rig, "relay_ignored")
    assert found is not None
    assert found.severity.value == "error"
    assert found.translation_key == ("relay_ignored" if command else "relay_ignored_off")
    await rig.advance(1200)
    # Not written again this session, repeats included; the rest state is written once at the
    # hand-back, though it cannot be relied on (answer O; decision 4 of 0.2.3).
    assert relay.calls == [command] * 4
    cause = "heating_on_ignored" if command else "heating_off_ignored"
    assert cause in rig.state("binary_sensor", "control").attributes["blockers"]
    assert rig.state("sensor", "control_state").attributes["latched_by"] == [cause]
    latch = issue(rig, "control_latched")
    assert latch is not None
    assert latch.translation_key == f"control_latched_relay_{cause}"
    assert latch.severity is ir.IssueSeverity.ERROR


def relay_memory(rig: Rig) -> Any:
    assert rig.entry is not None
    return rig.entry.runtime_data.control._session.loop.relay


async def test_a_controller_reverting_the_relay_at_once_makes_the_plugin_step_aside(
    rig: Rig, relay: FakeRelay
) -> None:
    """PB-01 (answers C, N): an old automation switches the relay off, and puts it back a second
    after every "on" of the plugin's, so no step ever sees the plugin's state — Home Assistant
    shows it for that second. With the power-cut state "I don't know", each such switch-off is
    a possible restart: three answered, the fourth makes the plugin step aside — within minutes,
    the rest state ("off", read already) not written, then nothing more. Before: "on" resent
    every 5 min for good — a burner start every 5 min — with an information alarm only."""
    calling(rig)
    await start_relay(rig, relay_power_on_state="unknown")
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    assert relay.calls == [True]
    relay.reverts = rig.freezer
    relay.switch(False)  # the automation
    await rig.advance(600)
    assert relay.calls == [True, True, True, True]  # three restarts answered, each put back
    assert rig.state("sensor", "control_state").state == "handed_back"
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_relay_off"
    assert len(relay_memory(rig).restarts) == 3
    assert issue(rig, "relay_not_taking") is None  # it took every command: no relay fault
    await rig.advance(1800, step=30.0)
    assert relay.calls == [True, True, True, True]  # left alone


async def test_a_relay_that_puts_itself_back_at_once_raises_the_not_taking_issue(
    rig: Rig, relay: FakeRelay
) -> None:
    """PB-01's other side, in Home Assistant: the relay puts itself back a second after every
    "on" by its own logic, so the change carries the plugin's own context. Never judged another
    controller, nor left unjudged with "on" resent every 5 min for good: "not confirmed", then
    after three checks the error-level issue that it does not take commands — "on" still sent at
    every check, no step aside."""
    calling(rig, False)
    await start_relay(rig, relay_power_on_state="unknown")
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    relay.reverts = rig.freezer
    relay.reverts_itself = True
    calling(rig)
    await rig.advance(10)
    assert relay.calls == [True]
    assert not relay.on  # back at once
    await rig.advance(880)
    assert issue(rig, "relay_not_taking") is None
    assert rig.state("sensor", "control_state").attributes["relay_check"] == "not_confirmed"
    await rig.advance(20)
    found = issue(rig, "relay_not_taking")
    assert found is not None
    assert found.translation_key == "relay_not_taking"
    assert rig.state("sensor", "control_state").state == "heating"
    assert issue(rig, "control_latched") is None
    assert relay_memory(rig).restarts == ()
    assert relay.calls == [True] * 4  # at each check


async def test_a_relay_rewrite_that_fails_once_still_steps_aside(
    rig: Rig, relay: FakeRelay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PB-01 (answer C): commanded off, the relay is switched on by another controller that then
    holds it; the one rewrite's service call fails once and goes again at the next step — still
    as the rewrite, so 120 s after it was decided, not read back, the plugin steps aside with the
    rest state once. Before: the retry went as a plain resend that forgot the rewrite, and "off"
    was resent every 5 min for good."""
    failing = {"off": True}
    original = _RelayEntity.async_turn_off

    async def turn_off(self: Any, **kwargs: Any) -> None:
        if failing["off"]:
            failing["off"] = False
            raise HomeAssistantError("the relay did not answer")
        await original(self, **kwargs)

    calling(rig, False)
    await start_relay(rig)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    assert relay.calls == []  # it reads "off" already
    monkeypatch.setattr(_RelayEntity, "async_turn_off", turn_off)
    relay.takes = False
    relay.switch(True)  # another controller, holding it on
    await rig.advance(10)
    assert relay.calls == []  # the rewrite's call failed
    assert control_alarm(rig, "write_failed") == "on"
    await rig.advance(10)
    assert relay.calls == [False]  # the rewrite again
    await rig.advance(100)
    assert rig.state("sensor", "control_state").state == "idle"
    await rig.advance(20)
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert relay.calls == [False, False]  # the rest state, once
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_relay_off"
    await rig.advance(1800, step=30.0)
    assert relay.calls == [False, False]


@pytest.mark.parametrize("rest", ["off", "on"])
async def test_late_switch_offs_with_a_declared_relay_timer_make_the_plugin_step_aside(
    rig: Rig, relay: FakeRelay, rest: str
) -> None:
    """SB-05 (decision 6 of 0.2.3): a declared 10-min timer. A switch-off 10 min into an
    on-period is its lapse — "on" again, not counted. An automation switching the relay off 15
    min into each on-period is not: each is a change seen on the relay — here, in its declared
    power-cut state "off", a restart the relay did not report — three answered, the fourth steps
    aside: the rest state written once (unless the relay reads it already), then nothing more.
    Before: every switch-off from 9 min on was the timer's, answered for good."""
    calling(rig)
    await start_relay(rig, relay_off_timer="minutes", relay_off_timer_min=10, relay_rest_state=rest)
    await rig.switch(True)
    assert relay.calls == [True]  # the on-period begins
    await rig.advance(600)
    relay.switch(False)  # the timer's own lapse, 10 min in
    await rig.advance(10)
    assert relay.on  # "on" again at once
    assert relay_memory(rig).restarts == ()  # not counted
    for n in (1, 2, 3):
        await rig.advance(900 - 10)
        relay.switch(False)  # the automation, 15 min into the on-period
        await rig.advance(10)
        assert relay.on, n  # answered
        assert len(relay_memory(rig).restarts) == n
    await rig.advance(900 - 10)
    count = len(relay.calls)
    relay.switch(False)  # the fourth within a day
    await rig.advance(20)
    assert rig.state("sensor", "control_state").state == "handed_back"
    # No rewrite; the rest state once — "off" is read already.
    assert relay.calls[count:] == ([] if rest == "off" else [True])
    assert relay.on is (rest == "on")
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == f"control_latched_relay_{rest}"
    relay.switch(rest == "off")  # the automation again
    await rig.advance(1800, step=30.0)
    assert relay.calls[count:] == ([] if rest == "off" else [True])  # left alone


async def test_a_relay_that_stops_taking_off_mid_session_blocks_control(
    rig: Rig, relay: FakeRelay
) -> None:
    """SB-06 (decision 6 of 0.2.3): a relay that took "on" — the start phase over — then stops
    taking commands (a link that delivers its reports but not the commands, a stuck contact) and
    does not show "off" over three checks: an error-level issue says the boiler may keep
    heating; control is blocked and the relay handed back — its rest state written once — with
    the latch issue and a blocker until control is switched off and on, as answer O. Before:
    "not confirmed", the information alarm only, "off" resent every 5 min for good."""
    calling(rig)
    await start_relay(rig)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    assert relay.on
    relay.takes = False
    calling(rig, False)
    await rig.advance(10)
    assert relay.calls == [True, False]  # "off", not taken
    await rig.advance(880)
    assert issue(rig, "relay_not_taking") is None
    assert relay.calls == [True, False, False, False]  # sent again at two checks
    assert rig.state("sensor", "control_state").attributes["relay_check"] == "not_confirmed"
    await rig.advance(20)
    found = issue(rig, "relay_not_taking")
    assert found is not None
    assert found.translation_key == "relay_not_taking_off"
    assert found.severity is ir.IssueSeverity.ERROR
    assert found.translation_placeholders == {"relay": name_of(rig, RELAY)}
    assert relay.calls == [True, False, False, False]  # no more "off": the next step hands back
    await rig.advance(10)
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["relay_off_not_taken"]
    assert state.attributes["relay_check"] == "not_taken"
    assert relay.calls == [True, False, False, False, False]  # the rest state, once
    assert relay.on  # the boiler may keep heating
    blockers = rig.state("binary_sensor", "control").attributes["blockers"]
    assert "relay_off_not_taken" in blockers
    latch = issue(rig, "control_latched")
    assert latch is not None
    assert latch.translation_key == "control_latched_relay_off_not_taken"
    assert latch.severity is ir.IssueSeverity.ERROR
    write_ignored = rig.state("binary_sensor", "alarm_write_ignored")
    assert write_ignored.state == "on"
    assert write_ignored.attributes["targets"] == ["relay"]
    await rig.advance(1800, step=30.0)
    assert len(relay.calls) == 5  # left alone
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(60)
    assert len(relay.calls) == 5  # the latch outlives a restart
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert "relay_off_not_taken" in rig.state("binary_sensor", "control").attributes["blockers"]
    latch = issue(rig, "control_latched")
    assert latch is not None
    assert latch.translation_key == "control_latched_relay_off_not_taken"
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)  # refused while control is on: off and on clears it
    assert err.value.translation_key == "blocked_relay_off_not_taken"
    relay.takes = True
    await rig.switch(False)
    await rig.switch(True)
    assert issue(rig, "control_latched") is None
    assert issue(rig, "relay_not_taking") is None
    assert "relay_off_not_taken" not in rig.state("binary_sensor", "control").attributes["blockers"]


@pytest.mark.parametrize("outage", [False, True], ids=["reachable", "out_of_reach_meanwhile"])
async def test_a_relay_that_stops_taking_on_mid_session_raises_an_issue_and_keeps_sending(
    rig: Rig, relay: FakeRelay, outage: bool
) -> None:
    """SB-06 (decision 6 of 0.2.3): a relay that took "off" — the start phase over — then does
    not show "on" over three checks: an error-level issue says the house is not heated; control
    keeps heating and sends "on" again at every check; the issue goes once the relay shows "on".
    Negative: out of reach in the middle of the checks — the run starts again once it is back,
    so no issue 15 min after the first send."""
    calling(rig, False)
    await start_relay(rig)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    relay.takes = False
    calling(rig)
    await rig.advance(10)
    assert relay.calls == [True]  # "on", not taken
    if outage:
        await rig.advance(200)
        relay.away()
        await rig.advance(400)
        relay.back(False)
        await rig.advance(290)
        assert issue(rig, "relay_not_taking") is None
        assert rig.state("sensor", "control_state").attributes["relay_check"] != "not_taken"
        return
    await rig.advance(880)
    assert issue(rig, "relay_not_taking") is None
    await rig.advance(20)
    found = issue(rig, "relay_not_taking")
    assert found is not None
    assert found.translation_key == "relay_not_taking"
    assert found.severity is ir.IssueSeverity.ERROR
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"  # control keeps the relay
    assert state.attributes["relay_check"] == "not_taken"
    assert relay.calls == [True] * 4  # at each check
    await rig.advance(300)
    assert relay.calls == [True] * 5
    relay.takes = True
    await rig.advance(300)
    assert relay.on  # taken at the next check
    assert issue(rig, "relay_not_taking") is not None
    await rig.advance(10)  # and shown at the step after it
    assert issue(rig, "relay_not_taking") is None
    assert rig.state("sensor", "control_state").attributes["relay_check"] != "not_taken"


@pytest.mark.parametrize("assumed", [False, True], ids=["declared_no", "assumed_state"])
async def test_a_relay_without_a_state_gets_its_command_at_once_when_it_returns(
    rig: Rig, relay: FakeRelay, assumed: bool
) -> None:
    """PB-44 (R6): a relay that reports no state — declared so, or an entity with
    ``assumed_state`` — gets its command at once when it comes back within reach, as the
    "relay unreachable" texts say, not at the next blind repeat (before: up to the repeat
    interval, 5 min, later); a blip between two steps counts too. Nothing is written while it
    is away. Bounded (M1 of the part-1 check): back again within 5 min of that send, it waits
    for the regular repeat; each return while commanded on counts toward "commands lost"."""
    relay.assumed = assumed
    calling(rig)
    await start_relay(rig, relay_reports_state="yes" if assumed else "no")
    await rig.switch(True)
    assert relay.calls == [True]
    await rig.advance(60)
    relay.away()
    await rig.advance(60)
    assert relay.calls == [True]  # nothing while it is away
    relay.back(False)  # its state after a power cut
    await rig.advance(10)
    assert relay.calls == [True, True]  # at once
    assert relay.on
    await rig.advance(60)
    relay.away()
    relay.back(False)  # gone and back between two steps, a minute after the last send
    await rig.advance(10)
    assert relay.calls == [True, True]  # waits for the repeat
    assert not relay.on
    await rig.advance(230)  # the repeat, 5 min after the last write
    assert relay.calls == [True, True, True]
    assert relay.on
    assert control_alarm(rig, "commands_lost") == "off"  # two returns lost
    await rig.advance(130)
    relay.away()
    relay.back(False)  # over 5 min after the last return's send, 2 min after the repeat
    await rig.advance(10)
    assert relay.calls == [True] * 4  # at once again
    assert relay.on
    assert control_alarm(rig, "commands_lost") == "on"  # the third within a day


async def test_a_relay_a_vt_zone_drives_blocks_control(rig: Rig, relay: FakeRelay) -> None:
    """R2 at run time: VT can be reconfigured without the options changing — a relay a VT
    thermostat drives for a room blocks control; it is handed back, nothing more is written."""
    await start_relay(rig)
    await rig.switch(True)
    assert relay.calls == [True]
    rig.zones.configure("living", underlying_entity_ids=[RELAY])  # its ``entry_infos`` (I12.7)
    await rig.advance(10)
    assert "relay_used_by_zone" in blockers(rig)
    assert relay.calls == [True, False]  # handed back: the rest state
    await rig.advance(600)
    assert relay.calls == [True, False]


@pytest.mark.parametrize("platform", ["opentherm_gw", "versatile_thermostat"])
async def test_a_relay_of_the_gateway_or_of_vt_blocks_control(
    rig: Rig, relay: FakeRelay, platform: str
) -> None:
    """R2 at run time (TB-20): a relay whose registry entry turns out to belong to the boiler's
    gateway integration or to VT — a setting of the boiler interface, not a relay contact —
    blocks control; it is handed back, nothing more is written."""
    await start_relay(rig)
    await rig.switch(True)
    assert relay.calls == [True]
    assert "relay_of_boiler_interface" not in blockers(rig)
    registry = er.async_get(rig.hass)
    registered = registry.async_get(RELAY)
    assert registered is not None
    registry.entities[RELAY] = attr.evolve(registered, platform=platform)
    await rig.advance(10)
    assert "relay_of_boiler_interface" in blockers(rig)
    assert relay.calls == [True, False]  # handed back: the rest state
    await rig.advance(600)
    assert relay.calls == [True, False]


async def test_a_heating_switch_a_vt_zone_drives_blocks_control(rig: Rig) -> None:
    """PB-54 at run time: VT can be reconfigured without the options changing — a heating
    switch a VT thermostat drives for a room blocks control on the entity path, as the relay
    does. Negative: the same switch no zone drives does not."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    await start(rig, **held_entity(number, ch_entity=switch.entity_id, ch_write_type="held"))
    await rig.advance(10)
    assert "entity_used_by_zone" not in blockers(rig)
    rig.zones.configure("living", underlying_entity_ids=[switch.entity_id])
    await rig.advance(10)
    assert "entity_used_by_zone" in blockers(rig)


@pytest.mark.parametrize("target", ["setpoint", "heating", "hand_back"])
@pytest.mark.parametrize(("iot_class", "blocked"), [("cloud_polling", True), ("local_push", False)])
async def test_a_write_target_through_a_cloud_blocks_control(
    rig: Rig, target: str, iot_class: str, blocked: bool
) -> None:
    """A maker's cloud cannot carry this control: it limits the calls, and with no internet the
    boiler could not be handed back. A setpoint, heating switch or external-control switch whose
    integration says it works through a cloud blocks control, and nothing is written. Negative:
    the same entity of a local integration."""
    mock_integration(rig.hass, MockModule("maker", partial_manifest={"iot_class": iot_class}))
    number = FakeNumber(rig.hass)
    heating = FakeSwitch(rig.hass)
    external = FakeSwitch(rig.hass, entity_id="input_boolean.fake_external", on=False)
    entity_id = {"setpoint": number, "heating": heating, "hand_back": external}[target].entity_id
    domain, object_id = entity_id.split(".", 1)
    er.async_get(rig.hass).async_get_or_create(
        domain, "maker", object_id, suggested_object_id=object_id
    )
    for fake in (number, heating, external):
        fake.register()
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="held",
        ch_entity=heating.entity_id,
        ch_write_type="held",
        hand_back="switch",
        hand_back_entity=external.entity_id,
        hand_back_entity_write_type="expiring",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.advance(10)
    assert ("write_through_cloud" in blockers(rig)) is blocked
    if not blocked:
        await rig.switch(True)
        await rig.advance(30)
        assert number.writes
        return
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_write_through_cloud"
    await rig.advance(60)
    assert (number.writes, heating.writes, external.writes) == ([], [], [])


async def test_a_relay_through_a_cloud_blocks_control(rig: Rig, relay: FakeRelay) -> None:
    """The relay too: found at run time, it is handed back and nothing more is written."""
    mock_integration(rig.hass, MockModule("maker", partial_manifest={"iot_class": "cloud_push"}))
    await start_relay(rig)
    await rig.switch(True)
    assert relay.calls == [True]
    registry = er.async_get(rig.hass)
    registered = registry.async_get(RELAY)
    assert registered is not None
    registry.entities[RELAY] = attr.evolve(registered, platform="maker")
    await rig.advance(10)
    assert "write_through_cloud" in blockers(rig)
    assert relay.calls == [True, False]  # handed back: the rest state
    await rig.advance(600)
    assert relay.calls == [True, False]


async def test_a_relay_boiler_thermostat_without_both_modes_blocks_control(
    rig: Rig, relay: FakeRelay
) -> None:
    rig.hass.states.async_set("climate.boiler", "off", {"hvac_modes": ["off", "auto"]})
    await start_relay(rig, relay_entity="climate.boiler")
    await rig.advance(10)
    assert "relay_climate_modes" in blockers(rig)
    rig.hass.states.async_set("climate.boiler", "off", {"hvac_modes": ["off", "heat"]})
    await rig.advance(10)
    assert "relay_climate_modes" not in blockers(rig)


CLIMATE_RELAY = "climate.fake_boiler_thermostat"


class _ClimateRelay(ClimateEntity):
    """A boiler thermostat entity as the relay — a real climate entity with the modes off and
    heat that reports its state; ``calls``: the modes the plugin's calls set."""

    _attr_should_poll = False
    _attr_name = "Fake boiler thermostat"
    _attr_unique_id = "fake_boiler_thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON

    def __init__(self) -> None:
        self.entity_id = CLIMATE_RELAY
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_hvac_mode = HVACMode.OFF
        self.calls: list[str] = []

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.calls.append(hvac_mode.value)
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    def person(self, mode: HVACMode) -> None:
        """A person sets it on the device itself: a report with a context of its own."""
        self._attr_hvac_mode = mode
        self.async_set_context(Context())
        self.async_write_ha_state()


async def test_a_boiler_thermostat_relay_follows_vt_and_judges_only_a_persons_change(
    rig: Rig,
) -> None:
    """TB-11: a real climate entity on the test platform (modes off and heat, reporting its
    state) as the relay. Control follows a zone that calls and stops with
    ``climate.set_hvac_mode`` heat and off; an hour of the plugin's own changes is never judged
    an outside change. Commanded off, a person sets it to heat: written back once; the second
    time within a day the plugin steps aside — the rest state "off" written once (answer C)."""
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.common import setup_test_component_platform

    hass = rig.hass
    relay = _ClimateRelay()
    setup_test_component_platform(hass, "climate", [relay])
    assert await async_setup_component(hass, "climate", {"climate": {"platform": "test"}})
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE_RELAY).state == "off"
    rig.zones.set("living")  # not calling
    await start_relay(rig, relay_entity=CLIMATE_RELAY)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    assert relay.calls == []  # it reads "off" already
    for _ in range(6):  # an hour: the zone calls and stops every five minutes
        for zone_calls in (True, False):
            if zone_calls:
                calling(rig)
            else:
                rig.zones.set("living")
            await rig.advance(300)
            state = rig.state("sensor", "control_state")
            assert state.state == ("heating" if zone_calls else "idle")
            assert state.attributes["relay_state"] == ("on" if zone_calls else "off")
            assert state.attributes["relay_check"] == "confirmed"
            assert state.attributes["latched_by"] == []
            for kind in ("outside_change", "write_ignored", "write_failed", "commands_lost"):
                assert control_alarm(rig, kind) == "off", kind
    assert relay.calls == ["heat", "off"] * 6  # each change once, never repeated
    assert hass.states.get(CLIMATE_RELAY).state == "off"
    assert issue(rig, "control_latched") is None
    written = len(relay.calls)
    relay.person(HVACMode.HEAT)
    await rig.advance(10)
    assert relay.calls[written:] == ["off"]  # rewritten once
    await rig.advance(130)  # past the rewrite's own confirmation window
    relay.person(HVACMode.HEAT)
    await rig.advance(20)
    assert relay.calls[written:] == ["off", "off"]  # the rest state, once
    relay.person(HVACMode.HEAT)
    await rig.advance(600)
    assert relay.calls[written:] == ["off", "off"]  # left alone
    assert rig.state("sensor", "control_state").state == "handed_back"
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_relay_off"


async def test_the_relay_path_needs_no_boiler_signal_but_the_water_path_does(
    rig: Rig, relay: FakeRelay
) -> None:
    """R4: flame and flow optional for the entry; water-temperature control gets blockers where
    either is missing — the relay path none."""
    await start_relay(rig, (Signal.OUTDOOR,))
    await rig.switch(True)
    assert relay.calls == [True]
    assert "no_flame_signal" not in blockers(rig)
    assert "no_flow_signal" not in blockers(rig)


async def test_water_temperature_control_is_blocked_without_flame_and_flow(rig: Rig) -> None:
    entry_options = options(rig.zones) | {
        "signals": {Signal.OUTDOOR.value: BOILER_ENTITIES[Signal.OUTDOOR]}
    }
    entry = add_entry(rig, entry_options)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.advance(10)
    found = blockers(rig)
    assert "no_flame_signal" in found
    assert "no_flow_signal" in found
    await rig.advance(30)
    assert rig.gateway.calls == []


async def test_a_relay_not_yet_reported_never_turns_the_restore_into_a_hand_back(
    rig: Rig, relay: FakeRelay, hass_storage: dict[str, Any]
) -> None:
    """R11: the relay out of reach from the start and the zones not reported: the restore
    waits; when the recognition period ends it gives way without a hand-back — nothing could
    reach the relay — and the relay gets the command as soon as it is back, never "off"
    first."""
    from custom_components.vtherm_smart_boiler.core.zone_watch import RECOGNITION_S

    relay.away()
    not_started(rig)
    await start_relay_with_stored(rig, hass_storage, relay_restorable(rig))
    await rig.advance(RECOGNITION_S + 30)
    assert relay.calls == []
    assert control_alarm(rig, "hand_back_failed") == "off"
    assert issue(rig, OWED) is None
    started(rig)
    relay.back(False)
    await rig.advance(10)
    assert relay.calls == [True]


async def test_the_relay_restore_goes_out_before_the_switch_restores(
    rig: Rig, relay: FakeRelay, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11: V3 knows the wish from the store — the stored command is written at the first
    step, before the wish is restored (by the setup since I11.3; here held back)."""

    async def not_restored(self: Any, _on: bool) -> None:
        return None

    monkeypatch.setattr(control_module.ControlUnit, "async_restore_enabled", not_restored)
    await start_relay_with_stored(rig, hass_storage, relay_restorable(rig))
    assert relay.calls == []
    await rig.advance(10)
    assert relay.calls == [True]


async def test_an_owed_relay_hand_back_waits_for_the_relay_while_control_commands_it(
    rig: Rig, relay: FakeRelay
) -> None:
    """R6, R9: control on again while the relay is still out of reach — the owed hand-back is
    not tried against it, and once it is back only the command goes out, folding the debt."""
    await start_relay(rig)
    await rig.switch(True)
    relay.away()
    await rig.switch(False)
    await rig.switch(True)
    await rig.advance(180)
    assert relay.calls == [True]  # nothing reached it meanwhile
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert unit.hand_back_owed
    relay.back(False)
    await rig.advance(10)
    assert relay.calls == [True, True]  # the command, never "off" first
    assert not unit.hand_back_owed
    assert control_alarm(rig, "hand_back_failed") == "off"


async def test_a_failed_relay_write_is_sent_again_at_the_next_step(
    rig: Rig, relay: FakeRelay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relay write that fails — the service raises — raises "write failed" and goes again at
    the next step."""
    failing = {"on": True}

    async def turn_on(self: Any, **kwargs: Any) -> None:
        if failing["on"]:
            raise HomeAssistantError("the relay did not answer")
        self._relay.turned(True)

    monkeypatch.setattr(_RelayEntity, "async_turn_on", turn_on)
    await start_relay(rig)
    await rig.switch(True)
    assert relay.calls == []
    assert control_alarm(rig, "write_failed") == "on"
    failing["on"] = False
    await rig.advance(10)
    assert relay.calls == [True]
    assert control_alarm(rig, "write_failed") == "off"


async def test_unreadable_relay_memory_in_the_store_is_skipped(
    rig: Rig, relay: FakeRelay, hass_storage: dict[str, Any]
) -> None:
    """A stored restart list or rewrite of another shape is skipped, logged, and the rest of
    the store restored."""
    stored = relay_restorable(rig, relay_restarts="yesterday", relay_rewritten_at="noon")
    await start_relay_with_stored(rig, hass_storage, stored)
    await rig.advance(20)
    assert relay.calls == [True]  # the restore goes on
    assert rig.entry is not None
    loop = rig.entry.runtime_data.control._session.loop
    assert loop.relay.restarts == ()
    assert loop.relay.rewritten_at is None


@pytest.mark.parametrize(
    "case",
    [
        "kept",
        "unreadable",
        "not_a_list",
        "not_a_pair",
        "another_relay",
        "declared",
        "too_short",
        "a_minute_short",
    ],
)
async def test_the_relays_own_timer_is_stored_and_read_cautiously(
    rig: Rig,
    relay: FakeRelay,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    case: str,
) -> None:
    """Z4R2-02: the relay's own timer recognised while its timer is "I don't know", and the
    switch-offs compared with it, are stored with the relay and read back at the next run — a
    restart or an options save forgets neither. Read cautiously: a value of another shape is
    skipped and logged, the rest restored; another relay's, or one kept from before the timer
    was declared, are dropped — and a timer seen shorter than 9 min, which an earlier build could
    store, is never the relay's own (K4.2): dropped and logged, its switch-offs kept; one a minute
    short of 10 min is (KD-02): kept."""
    at = START.timestamp()
    stored = relay_restorable(
        rig,
        relay_timer_entity=RELAY,
        relay_timer_seen_s=1620.0,
        relay_lapses=[[at, 1620.0]],
    )
    if case == "unreadable":
        stored |= {"relay_timer_seen_s": "long", "relay_lapses": [[at, -5.0]]}
    if case == "not_a_list":
        stored |= {"relay_timer_seen_s": -60.0, "relay_lapses": "yesterday"}
    if case == "not_a_pair":
        stored |= {"relay_lapses": [[at]]}
    if case == "another_relay":
        stored |= {"relay_timer_entity": "switch.another_relay"}
    if case == "too_short":
        stored |= {"relay_timer_seen_s": 120.0, "relay_lapses": [[at, 120.0]]}
    if case == "a_minute_short":
        stored |= {"relay_timer_seen_s": 545.0, "relay_lapses": [[at, 545.0]]}
    timer = (
        {"relay_off_timer": "minutes", "relay_off_timer_min": 27}
        if case == "declared"
        else {"relay_off_timer": "unknown"}
    )
    stored["taken_with"] = stored["taken_with"] | timer
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=relay_options(rig.zones, **timer)
    )
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, stored, "0.2.2")
    await set_up(rig, entry)
    await rig.advance(20)
    assert relay.calls == [True]  # the restore goes on whatever the case
    memory = entry.runtime_data.control._session.loop.relay
    if case == "not_a_pair":  # the timer seen restored, the switch-offs skipped
        assert memory.timer_seen_s == 1620.0
        assert memory.lapses == ()
    elif case == "too_short":  # never the relay's own; its switch-offs still count
        assert memory.timer_seen_s is None
        assert memory.lapses == ((at, 120.0),)
        assert _logged(caplog, logging.WARNING, "shorter than 9 min") == 1
    elif case == "a_minute_short":  # a 10-min timer measured short: the relay's own (KD-02)
        assert memory.timer_seen_s == 545.0
        assert memory.lapses == ((at, 545.0),)
        assert _logged(caplog, logging.WARNING, "shorter than") == 0
    elif case == "kept":
        assert memory.timer_seen_s == 1620.0
        assert memory.lapses == ((at, 1620.0),)
        stored_now = entry.runtime_data.control.stored()
        assert stored_now["relay_timer_seen_s"] == 1620.0
        assert stored_now["relay_timer_entity"] == RELAY
    else:
        assert memory.timer_seen_s is None
        assert memory.lapses == ()
    if case in ("unreadable", "not_a_list"):
        for key in ("relay_timer_seen_s", "relay_lapses"):
            assert _logged(caplog, logging.WARNING, f"unreadable stored control data: {key}") == 1


# --- Y2: the days under control (P-96, A12) --------------------------------------------------


async def test_the_time_under_control_is_recorded_for_the_verdict(rig: Rig) -> None:
    """P-96 (A12): the control state goes into the history from the unit itself, as its
    control-state sensor shows it — from the first start on, before the sensor is in the
    registry. A day with an hour of control or more is left out of the verdict, and the verdict
    says how many days it left out."""
    await start(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    assert [s.value for s in coordinator.history.control_state] == ["disabled"]
    await analyse_now(coordinator)
    assert rig.state("sensor", "verdict").attributes["days_left_out"] == 0
    await rig.switch(True)
    await rig.advance(3700, step=60.0)
    modes = {s.value for s in coordinator.history.control_state}
    assert modes & {"heating", "idle"}
    await analyse_now(coordinator)
    # Today — under control for more than an hour — is left out.
    assert rig.state("sensor", "verdict").attributes["days_left_out"] == 1


async def test_days_under_control_are_read_back_from_the_control_state_sensor(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-96: after a restart the rolling history is read back from the recorder with the
    plugin's own control-state sensor, as the registry names it: a past day is tagged with the
    time under control it had before the restart."""
    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    now = dt_util.utcnow()
    asked: list[list[str]] = []

    def significant_states(hass, start_time, *, end_time=None, entity_ids=None, **_kwargs):
        asked.append(list(entity_ids))
        if end_time is not None:
            return {}  # older days: the recorder reaches no further back
        flame = BOILER_ENTITIES[Signal.FLAME]
        rows: dict[str, list[State]] = {
            flame: [State(flame, "off", {}, last_updated=now - timedelta(days=3))]
        }
        for entity in entity_ids:
            if entity.endswith("control_state"):
                rows[entity] = [
                    State(entity, "disabled", {}, last_updated=now - timedelta(days=3)),
                    State(entity, "heating", {}, last_updated=now - timedelta(hours=30)),
                    State(entity, "unavailable", {}, last_updated=now - timedelta(hours=28)),
                    State(entity, "idle", {}, last_updated=now - timedelta(hours=27, minutes=30)),
                    State(entity, "handed_back", {}, last_updated=now - timedelta(hours=26)),
                ]
        return rows

    class Recorder:
        async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
            return await rig.hass.async_add_executor_job(target, *args)

    monkeypatch.setattr(coordinator_module, "_recorder", lambda hass: Recorder())
    monkeypatch.setattr(coordinator_module, "_significant_states", lambda: significant_states)
    rig.hass.config.components.add("recorder")
    await start(rig)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    sensor = rig.entity("sensor", "control_state")
    assert sensor in asked[0]
    series = coordinator.history.control_state
    moment = (now - timedelta(hours=29)).timestamp()
    assert series.value_at(moment) == "heating"
    assert series.value_at((now - timedelta(hours=27, minutes=45)).timestamp()) is None
    [day] = [
        d for d in coordinator.daily.values() if d.start <= moment < d.end
    ]  # the day before yesterday
    assert day.controlled_s == pytest.approx(2 * 3600.0 + 1.5 * 3600.0)
    assert day.under_control


async def test_vts_helper_is_read_back_and_followed_as_vts_call(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I12.7b: where a helper is set, the recorder's history of it — the rolling eight days and
    the older days the day summaries are built from — is VT's call in the history, before what
    is recorded live; each change of it is followed live. No query asks for VT's climates."""
    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    now = dt_util.utcnow()
    helper = rig.zones.helper
    living = rig.zones.entities["living"]
    asked: list[tuple[bool, list[str]]] = []

    def significant_states(hass, start_time, *, end_time=None, entity_ids=None, **_kwargs):
        asked.append((end_time is None, list(entity_ids)))
        if start_time < now - timedelta(days=12):
            return {}  # the recorder reaches no further back
        flame = BOILER_ENTITIES[Signal.FLAME]
        return {
            flame: [State(flame, "off", {}, last_updated=start_time)],
            helper: [
                State(helper, "on", {}, last_updated=start_time),
                State(helper, "unavailable", {}, last_updated=start_time + timedelta(hours=1)),
                State(helper, "off", {}, last_updated=start_time + timedelta(hours=2)),
            ],
        }

    class Recorder:
        async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
            return await rig.hass.async_add_executor_job(target, *args)

    monkeypatch.setattr(coordinator_module, "_recorder", lambda hass: Recorder())
    monkeypatch.setattr(coordinator_module, "_significant_states", lambda: significant_states)
    rig.hass.config.components.add("recorder")
    await start(rig)
    assert rig.entry is not None
    assert {rolling for rolling, _ids in asked} == {True, False}
    assert all(helper in ids and living not in ids for _rolling, ids in asked)
    called = rig.entry.runtime_data.history.vt_called
    begin = (now - timedelta(days=8)).timestamp()
    assert [called.value_at(begin + hours * 3600.0) for hours in (0.5, 1.5, 2.5)] == [
        True,
        None,
        False,
    ]
    live = rig.hass.states.get(helper)
    assert live is not None
    assert called.value_at(now.timestamp()) is {"on": True, "off": False}[live.state]
    rig.freezer.tick(60)
    rig.zones.set_helper("on")
    await rig.hass.async_block_till_done()
    assert called.last is not None
    assert called.last.value is True
    rig.zones.set_helper("unknown")
    await rig.hass.async_block_till_done()
    assert called.last.value is None


# --- Y4: the coded lists' texts (P-39) and the switch's refusal (P-74) -------------------------

EN_TEXTS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "custom_components/vtherm_smart_boiler/translations/en.json"
    ).read_text(encoding="utf-8")
)


def _attribute_text(platform: str, key: str, attribute: str, code: str) -> str:
    entity = EN_TEXTS["entity"][platform][key]
    return entity["state_attributes"][attribute]["state"][code]


async def test_blocked_switch_error_counts_the_others(rig: Rig) -> None:
    """P-74: switching on with two blockers is refused with the first blocker's own text and
    the count of the others — no raw code in the message; both are named, translated, on the
    switch and on the control state."""
    await start(rig, curve={}, vt_boiler_helper=None)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_curve_not_entered"
    assert err.value.translation_placeholders == {"count": "1"}
    await rig.advance(10)  # the next step shows them
    switch = rig.state("binary_sensor", "control")
    assert switch.attributes["blockers"] == ["curve_not_entered", "no_vt_boiler_helper"]
    expected = ", ".join(
        _attribute_text("binary_sensor", "control", "blockers", code)
        for code in ("curve_not_entered", "no_vt_boiler_helper")
    )
    assert switch.attributes["blockers_text"] == expected
    state = rig.state("sensor", "control_state")
    assert state.attributes["blockers_text"] == ", ".join(
        _attribute_text("sensor", "control_state", "blockers", code)
        for code in ("curve_not_entered", "no_vt_boiler_helper")
    )


async def test_one_blocker_alone_counts_no_others(rig: Rig) -> None:
    """Negative: a single blocker gives a count of 0."""
    await start(rig, curve={})
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_placeholders == {"count": "0"}


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_coded_lists_come_with_their_text(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    """P-39: the codes stay, for automations, and each list has its text in Home Assistant's
    language beside it — control's reasons and latch here; a code without a text (a latch an
    earlier version stored for an alarm this one does not have) is shown as itself."""
    await start_with_stored(
        rig,
        hass_storage,
        {"latched": True, "latched_by": ["outside_change", "pressure_low"]},
        layout,
    )
    await rig.advance(120)
    state = rig.state("sensor", "control_state")
    assert state.attributes["latched_by"] == ["outside_change", "pressure_low"]
    outside = _attribute_text("sensor", "control_state", "latched_by", "outside_change")
    assert state.attributes["latched_by_text"] == f"{outside}, pressure_low"
    reasons = state.attributes["reasons"]
    assert reasons
    assert state.attributes["reasons_text"] == ", ".join(
        _attribute_text("sensor", "control_state", "reasons", code) for code in reasons
    )
    assert state.attributes["blockers_text"] == ""  # nothing blocks: an empty text


async def test_the_verdict_reasons_come_with_their_text(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-39 and the Y3 carry-over: each verdict reason with its text; low condensing where
    control does not set the water temperature says so, not "anti-cycling is planned"."""
    from dataclasses import replace

    from custom_components.vtherm_smart_boiler.core.verdict import (
        WATER_NOT_CONTROLLED,
        Reason,
        ReasonCode,
        ReasonKind,
        Verdict,
        VerdictResult,
    )

    await start(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    await rig.hass.async_block_till_done(wait_background_tasks=True)  # the first analysis
    await analyse_now(coordinator)
    analysis = coordinator.analysis
    assert analysis is not None

    async def no_analysis(*_args: Any) -> None:
        return None  # the monitor's own analysis would replace the verdict meanwhile

    monkeypatch.setattr(coordinator, "async_run_analysis", no_analysis)
    reasons = (
        Reason(ReasonCode.FREQUENT_STARTS, ReasonKind.PROBLEM, 4.0, 3.0, changed_by_control=False),
        Reason(
            ReasonCode.LOW_CONDENSING,
            ReasonKind.PROBLEM,
            0.2,
            0.5,
            changed_by_control=False,
            detail=WATER_NOT_CONTROLLED,
        ),
    )
    coordinator.analysis = replace(analysis, verdict=VerdictResult(Verdict.NOT_WORTH_IT, reasons))
    await coordinator.async_refresh()
    await rig.hass.async_block_till_done()
    text = rig.state("sensor", "verdict").attributes["reasons_text"]
    starts = _attribute_text("sensor", "verdict", "reasons", "frequent_starts")
    not_yet = _attribute_text("sensor", "verdict", "changed_by_control", "false")
    low = _attribute_text("sensor", "verdict", "reasons", "low_condensing")
    water = _attribute_text("sensor", "verdict", "detail", WATER_NOT_CONTROLLED)
    assert text == f"{starts} ({not_yet}), {low} ({water})"
    assert "anti-cycling" not in text.split(", ", 1)[1]


# --- P-115: the precedence of a control step, as a table -----------------------------------------
# What ``_async_step`` does first when several things are due at once: the last command restored
# before an owed hand-back (decision 3); an owed hand-back before the step's own command; the
# switch not yet restored deciding nothing (answer K); a unit left only to hand back doing
# nothing else; a hand-back decided in a step writing nothing else in it. The table the split of
# ``_async_step`` must keep green: the gateway's calls, and the control state shown.


async def _restorable_first(rig: Rig, hass_storage: dict[str, Any]) -> None:
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    not_started(rig)
    await start_with_stored(rig, hass_storage, restorable(rig), "0.2.2")
    await rig.advance(30)


async def _owed_then_command(rig: Rig, hass_storage: dict[str, Any]) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, {"controlling": True, "enabled": True}, "0.2.2")
    await set_up(rig, entry)
    await rig.advance(10)


async def _wish_never_restored(rig: Rig, hass_storage: dict[str, Any]) -> None:
    """The wish never given back — the setup gives it since I11.3; held back here: the unit's
    own guard decides nothing for a minute, then counts control as off."""
    from unittest.mock import patch

    async def not_restored(self: Any, _on: bool) -> None:
        return None

    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, {"controlling": True, "enabled": True}, "0.2.2")
    with patch.object(control_module.ControlUnit, "async_restore_enabled", not_restored):
        await set_up(rig, entry)
        await rig.advance(120)


async def _hand_back_only(rig: Rig, hass_storage: dict[str, Any]) -> None:
    """Control taken out of the options while the boiler was held: the unit that remains only
    hands back."""
    entry_options = options(rig.zones)
    stored = {"controlling": True, "enabled": True, "taken_with": entry_options["control"]}
    del entry_options["control"]
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, stored, "0.2.2")
    await set_up(rig, entry)
    await rig.advance(120)


async def _switched_off(rig: Rig, hass_storage: dict[str, Any]) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.calls.clear()
    await rig.switch(False)
    await rig.advance(30)


async def _latched_by_another_controller(rig: Rig, hass_storage: dict[str, Any]) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.calls.clear()
    rig.gateway.forced = 60.0  # another controller holds the setpoint
    await rig.advance(180)


STEP_PRECEDENCE = [
    (
        "the last command restored before the owed hand-back",
        _restorable_first,
        [("setpoint", RESTORED), ("ch", True), ("setpoint", RESTORED), ("ch", True)],
        "heating",
    ),
    (
        "the owed hand-back before the step's own command",
        _owed_then_command,
        [*HAND_BACK, ("setpoint", EXPECTED), ("ch", True)],
        "heating",
    ),
    (
        "the wish never restored: nothing decided, then off",
        _wish_never_restored,
        HAND_BACK,
        "disabled",
    ),
    (
        "a unit left only to hand back does nothing else",
        _hand_back_only,
        # The options it was taken with are not migrated: the lowest water temperature's default.
        [("setpoint", DEFAULT_LOWEST), ("ch", True), ("setpoint", 0.0)],
        None,
    ),
    ("switched off: the hand-back and nothing else", _switched_off, HAND_BACK, "disabled"),
    (
        "another controller: the hand-back and nothing else",
        _latched_by_another_controller,
        None,
        "handed_back",
    ),
]


@pytest.mark.parametrize(
    ("scenario", "calls", "shown"),
    [row[1:] for row in STEP_PRECEDENCE],
    ids=[row[0] for row in STEP_PRECEDENCE],
)
async def test_the_precedence_of_a_control_step(
    rig: Rig,
    hass_storage: dict[str, Any],
    scenario: Callable[[Rig, dict[str, Any]], Any],
    calls: list[tuple[str, Any]] | None,
    shown: str | None,
) -> None:
    """P-115: the gateway's calls, in order, and the control state shown, for each set of
    things due at once. ``calls`` ``None``: whatever the latch's one rewrite sent, it ends with
    the hand-back and nothing after it."""
    await scenario(rig, hass_storage)
    if calls is None:
        assert rig.gateway.calls[-3:] == HAND_BACK
        assert ("setpoint", EXPECTED) not in rig.gateway.calls[
            rig.gateway.calls.index(HAND_BACK[0]) :
        ]
    else:
        assert rig.gateway.calls[: len(calls)] == calls
        if shown != "heating":
            assert rig.gateway.calls == calls  # nothing else
    assert rig.entry is not None
    control_state = er.async_get(rig.hass).async_get_entity_id(
        "sensor", DOMAIN, f"{rig.entry.entry_id}_control_state"
    )
    if shown is None:  # no control configured: no control state to show
        assert control_state is None
    else:
        assert rig.state("sensor", "control_state").state == shown


# --- The heat call and the rooms calling (2026-10-14; I12) -----------------------------------


async def test_the_boiler_called_sensor_shows_the_call_and_why_not(rig: Rig) -> None:
    """The user's decisions of 2026-10-14: on while the plugin calls the boiler; off with the
    reason while it controls and does not (a room calling, VT's central boiler not — its count
    of two not reached, I12); unknown while control is off. The rooms calling beside it, on the
    control state too, and the plugin's event when the call changes."""
    from custom_components.vtherm_smart_boiler.const import BOILER_CALL_EVENT

    events = async_capture_events(rig.hass, BOILER_CALL_EVENT)
    rig.zones.add("bedroom", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.zones.set_helper("off")  # VT's count of two: one room calls
    await start(rig)
    await rig.advance(20)
    called = rig.state("binary_sensor", "boiler_called")
    assert (called.state, called.attributes["call_reason"]) == ("unknown", "not_controlling")
    await rig.switch(True)
    await rig.advance(20)
    called = rig.state("binary_sensor", "boiler_called")
    assert (called.state, called.attributes["call_reason"]) == ("off", "below_threshold")
    assert called.attributes["demand_count"] == 1
    assert "count_threshold" not in called.attributes
    state = rig.state("sensor", "control_state")
    assert (state.attributes["boiler_called"], state.attributes["call_reason"]) == (
        False,
        "below_threshold",
    )
    rig.zones.set("bedroom", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig.zones.set_helper("on")
    await rig.advance(20)
    called = rig.state("binary_sensor", "boiler_called")
    assert (called.state, called.attributes["call_reason"]) == ("on", None)
    assert [event.data["boiler_called"] for event in events] == [False, True]
    assert rig.entry is not None
    assert {event.data["entry_id"] for event in events} == {rig.entry.entry_id}


async def test_the_rooms_calling_are_counted_and_named(rig: Rig) -> None:
    """The rooms calling now, counted and named — a room with two heads open counts once; no
    power sensor and no device list any more (I12: VT's central boiler counts its own)."""
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        on_percent=0.6,
        specific_states={"is_device_active": True, "device_actives": ["switch.a", "switch.b"]},
    )
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    count = rig.state("sensor", "demand_count")
    assert count.state == "1"
    assert count.attributes["calling_zones"] == [rig.zones.entities["living"]]
    assert count.attributes["calling_circuits"] == ["main"]
    assert "active_devices" not in count.attributes
    assert rig.hass.states.get("sensor.boiler_demand_power") is None
    assert rig.state("binary_sensor", "boiler_called").state == "on"


async def test_the_circuits_of_the_rooms_calling_are_named(rig: Rig) -> None:
    """I12.12: the circuits the rooms calling are on — what the Boiler page draws taking water,
    with no room read — recorded, so its last 24 h replay them; the rooms are not recorded. A
    circuit whose rooms do not call is not named; none while no room calls."""
    rig.zones.add("bedroom", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    living, bedroom = rig.zones.entities["living"], rig.zones.entities["bedroom"]
    floor = {"id": "floor", "control": "passive_fixed", "fixed_temperature": 35}
    entry_options = with_circuit(rig, {"zones": [living]})
    entry_options["circuits"].append(floor | {"zones": [bedroom], "underfloor": [bedroom]})
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    await rig.advance(20)
    count = rig.state("sensor", "demand_count")
    assert (count.state, count.attributes["calling_circuits"]) == ("1", ["main"])
    rig.zones.set("bedroom", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await rig.advance(20)
    count = rig.state("sensor", "demand_count")
    assert (count.state, count.attributes["calling_circuits"]) == ("2", ["main", "floor"])
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.zones.set("bedroom", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(20)
    count = rig.state("sensor", "demand_count")
    assert (count.state, count.attributes["calling_circuits"]) == ("0", [])
    from custom_components.vtherm_smart_boiler.sensor import DemandCountSensor

    assert DemandCountSensor._unrecorded_attributes == frozenset({"calling_zones"})


async def test_gives_no_heat_follows_vts_decision(rig: Rig) -> None:
    """I12.9: the house-wide "boiler gives no heat" sensor — unavailable while control is off
    (an "on" would hold SmartPI's learning for as long as control stays off); on, "VT not
    calling", while a room calls and VT's central boiler does not; off once VT calls and the
    plugin heats. Nothing of the water interface is left: no zone values for VT."""
    from custom_components.vtherm_smart_boiler import feature_manager

    rig.zones.add("bedroom", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    rig.zones.set_helper("off")  # VT's count of two: one room calls
    await start(rig)
    await rig.advance(20)
    assert rig.state("binary_sensor", "no_heat").state == "unavailable"
    await rig.switch(True)
    await rig.advance(20)
    state = rig.state("binary_sensor", "no_heat")
    assert (state.state, state.attributes["reason"]) == ("on", "vt_not_calling")
    rig.zones.set("bedroom", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig.zones.set_helper("on")
    await rig.advance(20)
    state = rig.state("binary_sensor", "no_heat")
    assert (state.state, state.attributes["reason"]) == ("off", None)
    assert "device_class" not in state.attributes  # a signal for automations, not a problem
    await rig.switch(False)
    await rig.advance(20)
    assert rig.state("binary_sensor", "no_heat").state == "unavailable"
    assert not hasattr(feature_manager, "zone_values")


async def test_gives_no_heat_exists_only_with_control(rig: Rig) -> None:
    """I12.9: without a control section the plugin drives no boiler: no "gives no heat"
    sensor."""
    await set_up(rig, add_entry(rig, without_control(options(rig.zones))))
    assert rig.entry is not None
    assert (
        er.async_get(rig.hass).async_get_entity_id(
            "binary_sensor", DOMAIN, f"{rig.entry.entry_id}_no_heat"
        )
        is None
    )
