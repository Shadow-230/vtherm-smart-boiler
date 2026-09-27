"""Control in Home Assistant: switching on and off, keep-alive, every hand-back path, no write
without fresh data, guard alarms, learning pauses and the allowed service calls.

Everything runs in the test's Home Assistant; the gateway, VT and SmartPI are fakes that record
the calls they receive.
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

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import storage as ha_storage
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.vtherm_smart_boiler import control as control_module
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import (
    BOILER_ENTITIES,
    VT_PLATFORM,
    WEATHER_ENTITY,
    FakeBoiler,
    FakeForecasts,
    FakeZones,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SIGNALS = (Signal.FLAME, Signal.FLOW, Signal.OUTDOOR, Signal.DHW_ACTIVE)
CONFIRMED = "sensor.fake_gateway_control_setpoint"
CH_ECHO = "binary_sensor.fake_gateway_central_heating"
OUTDOOR = 5.0
EXPECTED = round(HeatingCurve().flow(OUTDOOR), 1)  # the curve's setpoint at 5 °C outside
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
    block: asyncio.Event | None = None  # a heating setpoint's call waits for this (a slow gateway)
    block_hand_back: asyncio.Event | None = None  # the next hand-back's first call waits for it
    hang: asyncio.Event | None = None  # every call waits for this (a gateway that hangs)
    # CS=0 arrives, and its call raises this (a bug, a task cancelled inside the integration)
    release_error: Callable[[], BaseException] | None = None
    # CS=0 arrives and the call returns, but the gateway keeps the override and nothing new is
    # reported: pyotgw after its own timeout, or a command the PIC did not take
    ignore_release: bool = False
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
            if self.block is not None and value != 0:
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
    services: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    storage: dict[str, Any] = field(default_factory=dict)  # the test's stores (hass_storage)

    def live(self) -> None:
        """The gateway's periodic reports: fresh boiler signals and setpoint echo; without its
        connection, the gateway's entities are unavailable."""
        connected = self.gateway.connected
        values: dict[Signal, float | bool | None] = {
            Signal.FLAME: False if connected else None,
            Signal.DHW_ACTIVE: self.dhw if connected else None,
        }
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
            await self.hass.async_block_till_done()

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
        await self.hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": self.entity("switch", "control")},
            blocking=True,
        )
        await self.hass.async_block_till_done()

    def plugin_calls(self) -> set[tuple[str, str]]:
        """Service calls made by the plugin (the test's own switch calls left out)."""
        return {(domain, service) for domain, service, _ in self.services if domain != "switch"}


def options(zones: FakeZones, **control: Any) -> dict[str, Any]:
    control_options = {
        "write_path": "opentherm_gw",
        "gateway_id": "gw",
        "confirmed_entity": CONFIRMED,
        "topology": "gateway_with_thermostat",
        "curve": {"design_outdoor": -15, "design_flow": 55},
    } | control
    return {
        "signals": {s.value: BOILER_ENTITIES[s] for s in SIGNALS},
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "zones": [{"entity_id": e} for e in zones.entities.values()],
        "monitor": {"monitoring_days": 0},
        "control": control_options,
    }


@pytest.fixture
async def rig(hass: HomeAssistant, freezer, zones: FakeZones, hass_storage: dict[str, Any]) -> Rig:
    freezer.move_to(START)
    boiler = FakeBoiler(hass, SIGNALS)
    gateway = FakeGateway(hass)
    gateway.register()
    zones.add("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig = Rig(hass, freezer, boiler, zones, gateway, storage=hass_storage)
    rig.live()

    def record(event: Event) -> None:
        data = event.data
        rig.services.append((data["domain"], data["service"], dict(data["service_data"])))

    hass.bus.async_listen(EVENT_CALL_SERVICE, record)
    return rig


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


async def start(rig: Rig, **control: Any) -> None:
    entry = add_entry(rig, options(rig.zones, **control))
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry


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
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]
    count = len(rig.gateway.calls)
    await rig.advance(300)
    assert len(rig.gateway.calls) == count  # no control clock left running


async def test_control_is_off_by_default_and_refused_during_monitoring(rig: Rig) -> None:
    await start(rig)
    assert rig.state("switch", "control").state == "off"
    await rig.advance(60)
    assert rig.gateway.calls == []
    hass = rig.hass
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        data={},
        options=options(rig.zones) | {"monitor": {"monitoring_days": 7}},
    )
    entry.add_to_hass(hass)
    ran_before(rig, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_control")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert err.value.translation_key == "blocked_monitoring_period"
    assert hass.states.get(switch).state == "off"
    assert rig.gateway.calls == []


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
    await start(rig)
    await rig.switch(True)
    rig.flow = None
    rig.live()
    count = len(rig.gateway.calls)
    await rig.advance(240)
    assert len(rig.gateway.calls) == count  # no keep-alive: the gateway's override lapses
    assert rig.state("sensor", "control_state").state == "waiting_data"
    await rig.advance(70)
    assert rig.gateway.calls[count:] == [("ch", True), ("setpoint", 0.0)]
    assert rig.state("sensor", "control_state").state == "handed_back"
    resumed = len(rig.gateway.calls)
    rig.flow = 35.0
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


async def test_unload_and_reload_hand_back_and_leave_no_loop(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
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
    assert rig.state("switch", "control").state == "on"
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
    assert "control_error" in rig.state("switch", "control").attributes["blockers"]
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
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the one rewrite
    assert stored_control(hass_storage, rig)["rewritten_at"] is not None
    await rig.advance(140)  # not confirmed in time: an outside change, handed back, latched
    assert rig.state("sensor", "control_state").state == "handed_back"
    stored = stored_control(hass_storage, rig)
    assert stored["latched"] is True
    assert stored["latched_by"] == ["outside_change"]


async def test_an_unconfirmed_write_is_reported_and_writing_goes_on(rig: Rig) -> None:
    rig.gateway.readable = False  # nothing says whether the value arrived
    await start(rig)
    await rig.switch(True)
    await rig.advance(90)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("sensor", "control_state").state == "heating"  # information only
    count = len(rig.gateway.setpoints())
    await rig.advance(60)
    assert len(rig.gateway.setpoints()) > count  # the keep-alive goes on


async def test_a_value_never_taken_from_the_start_is_an_outside_change(rig: Rig) -> None:
    """The user's decision: the read-back keeps another steady value — the thermostat's — from
    the start, so ours is never confirmed: one rewrite, then an outside change, which hands
    back by default."""
    rig.gateway.echo = False
    await start(rig)
    await rig.switch(True)
    await rig.advance(130)
    assert rig.gateway.calls.count(("setpoint", EXPECTED)) >= 2  # the first write and the rewrite
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    await rig.advance(140)  # the rewrite not confirmed in time; the next step hands back
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)


async def test_a_dropped_override_is_sent_again_not_fought(rig: Rig) -> None:
    """A boiler's Data-Invalid answer clears the gateway's override: the read-back falls back
    to the thermostat's value from before the session. Sent again at once, no outside change;
    when it keeps falling back, the write is reported as ignored."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    count = len(rig.gateway.setpoints())
    rig.gateway.override = None  # dropped
    await rig.advance(10)
    assert rig.gateway.setpoints()[count:] == [EXPECTED]  # at once, not at the keep-alive
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    for _ in range(3):  # it keeps falling back
        await rig.advance(10)
        rig.gateway.override = None
        await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert rig.state("sensor", "control_state").state == "heating"


async def test_an_outside_change_set_to_information_stops_every_write(rig: Rig) -> None:
    """P53: another controller has the boiler. With the alarm set to information, control stays
    on, but nothing is written — heating on/off included."""
    await start(rig, alarm_reactions={"outside_change": "info"})
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    rig.gateway.forced = 60.0
    await rig.advance(180)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    state = rig.state("sensor", "control_state")
    assert state.attributes["writes_stopped"] is True
    assert state.state == "heating"  # the decision goes on; nothing is sent
    count = len(rig.gateway.calls)
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # no heating off, no keep-alive


async def test_a_failing_write_raises_an_alarm(rig: Rig) -> None:
    await start(rig)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(True)
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"


async def test_vt_central_boiler_blocks_control(rig: Rig) -> None:
    hass = rig.hass
    await start(rig)
    await rig.switch(True)
    boiler = er.async_get(hass).async_get_or_create(
        "binary_sensor", VT_PLATFORM, "central_boiler_state"
    )
    hass.states.async_set(boiler.entity_id, "off", {"is_central_boiler_configured": True})
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    blockers = rig.state("switch", "control").attributes["blockers"]
    assert "vt_central_boiler_active" in blockers
    await rig.switch(False)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_vt_central_boiler_active"


async def test_a_monitor_alarm_set_to_hand_back_hands_back(rig: Rig) -> None:
    rig.boiler = FakeBoiler(rig.hass, (*SIGNALS, Signal.PRESSURE))
    rig.boiler.set(Signal.PRESSURE, 1.5)
    rig.live()
    entry_options = options(rig.zones, alarm_reactions={"pressure_low": "hand_back"})
    entry_options["signals"][Signal.PRESSURE.value] = rig.boiler.entity(Signal.PRESSURE)
    entry = add_entry(rig, entry_options)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.switch(True)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    rig.boiler.set(Signal.PRESSURE, 0.5)
    await rig.advance(40)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert rig.state("sensor", "control_state").state == "handed_back"


async def test_learning_is_paused_during_hot_water_and_released_on_switch_off(
    rig: Rig,
) -> None:
    hass = rig.hass
    learning: list[tuple[str, bool]] = []

    async def set_learning(call: ServiceCall) -> None:
        learning.append((call.data["entity_id"], call.data["learning_enabled"]))

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    zone = rig.zones.entities["living"]
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        on_percent=0.6,
        configuration={"proportional_function": "smartpi"},
        specific_states={"smartpi_learning_enabled": True},
    )
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(10)
    assert learning == [(zone, False)]
    assert rig.state("sensor", "control_state").attributes["learning_paused"] == [zone]
    await rig.switch(False)
    assert learning[-1] == (zone, True)


async def test_only_allowed_services_are_called(rig: Rig) -> None:
    hass = rig.hass

    async def set_learning(call: ServiceCall) -> None:
        return None

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        configuration={"proportional_function": "smartpi"},
        specific_states={"smartpi_learning_enabled": True},
    )
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(30)
    await rig.switch(False)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    allowed = unit.allowed_services | {("weather", "get_forecasts")}
    assert allowed >= rig.plugin_calls()
    assert ("vtherm_smartpi", "set_smartpi_learning") in rig.plugin_calls()
    assert unit.allowed_services == {
        ("opentherm_gw", "set_control_setpoint"),
        ("opentherm_gw", "set_central_heating_ovrd"),
        ("vtherm_smartpi", "set_smartpi_learning"),
    }


async def test_the_switch_comes_back_after_a_restart(hass: HomeAssistant, rig: Rig) -> None:
    mock_restore_cache(hass, [State("switch.boiler_boiler_control_experimental", "on")])
    await start(rig)
    assert rig.state("switch", "control").state == "on"
    await rig.advance(10)
    assert ("setpoint", EXPECTED) in rig.gateway.calls


async def test_auto_tpi_zones_that_cannot_learn_raise_a_repair_issue(rig: Rig) -> None:
    rig.zones.set(
        "living",
        configuration={"proportional_function": "tpi", "is_used_by_central_boiler": True},
        specific_states={"auto_tpi_state": "on"},
    )
    await start(rig)
    assert rig.entry is not None
    issue = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"auto_tpi_blocked_{rig.entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "auto_tpi_blocked"
    # Blocked from learning: not also reported as learning without pauses.
    assert (
        ir.async_get(rig.hass).async_get_issue(DOMAIN, f"learning_not_paused_{rig.entry.entry_id}")
        is None
    )


@pytest.mark.parametrize(
    ("configuration", "specific_states"),
    [
        ({"proportional_function": "tpi"}, {"auto_tpi_state": "on"}),  # Auto-TPI learning
        ({"proportional_function": "smartpi"}, {}),  # SmartPI without its learning flag
    ],
)
async def test_learning_the_plugin_cannot_pause_raises_a_repair_issue(
    rig: Rig, configuration: dict[str, Any], specific_states: dict[str, Any]
) -> None:
    """S19: a learning algorithm without a pause service gets an explicit warning."""
    rig.zones.set("living", configuration=configuration, specific_states=specific_states)
    await start(rig)
    assert rig.entry is not None
    issue = ir.async_get(rig.hass).async_get_issue(
        DOMAIN, f"learning_not_paused_{rig.entry.entry_id}"
    )
    assert issue is not None
    await start(rig, learning_pauses=False)  # a second entry, without pauses: nothing promised
    assert (
        ir.async_get(rig.hass).async_get_issue(DOMAIN, f"learning_not_paused_{rig.entry.entry_id}")
        is None
    )


@dataclass
class FakeNumber:
    """A writable setpoint entity (like a boiler's EMS or ESPHome number) that records writes.

    Like Home Assistant, it drops a call while the entity is unavailable; ``lowest`` plays a device
    that ignores values below it and keeps its own.
    """

    hass: HomeAssistant
    entity_id: str = "input_number.fake_boiler_flow"
    writes: list[float] = field(default_factory=list)
    available: bool = True
    echo_later: bool = False  # as ESPHome or MQTT entities: the new value shows on a later tick
    lowest: float | None = None
    value: float = 50.0
    unit: str = "°C"
    attributes: dict[str, Any] = field(default_factory=dict)  # min, max, step

    def register(self) -> None:
        async def set_value(call: ServiceCall) -> None:
            if not self.available:
                return  # Home Assistant skips an unavailable entity without an error
            value = float(call.data["value"])
            self.writes.append(value)
            if self.lowest is None or value >= self.lowest:
                self.value = value
            if not self.echo_later:
                self.publish(self.value)

        self.hass.services.async_register("input_number", "set_value", set_value)
        self.publish(self.value)

    def publish(self, value: float) -> None:
        state = str(value) if self.available else "unavailable"
        attributes = {"unit_of_measurement": self.unit, **self.attributes}
        self.hass.states.async_set(self.entity_id, state, attributes)

    def set_available(self, available: bool) -> None:
        self.available = available
        self.publish(self.value)


@dataclass
class FakeSwitch:
    """A held heating switch (an ESPHome or EMS-ESP CH enable) that records its writes; like
    Home Assistant, it drops a call while unavailable."""

    hass: HomeAssistant
    entity_id: str = "input_boolean.fake_ch"
    writes: list[bool] = field(default_factory=list)
    available: bool = True
    on: bool = True
    stuck_on: bool = False  # it takes "on" but will not go off

    def register(self) -> None:
        async def turn(call: ServiceCall, on: bool) -> None:
            if not self.available:
                return
            self.writes.append(on)
            self.on = on or self.stuck_on
            self.publish()

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


async def test_mqtt_path_calls_only_its_publish(rig: Rig) -> None:
    published: list[tuple[str, str]] = []

    async def publish(call: ServiceCall) -> None:
        published.append((call.data["topic"], call.data["payload"]))
        if call.data["topic"].endswith("/ctrlsetpt"):
            value = float(call.data["payload"])
            rig.gateway.override = None if value == 0 else value
            rig.gateway.publish()

    rig.hass.services.async_register("mqtt", "publish", publish)
    await start(rig, write_path="otgw_mqtt", mqtt_top="OTGW", mqtt_node="otgw-1")
    await rig.switch(True)
    await rig.advance(60)
    await rig.switch(False)
    assert published[0] == ("OTGW/set/otgw-1/ctrlsetpt", f"{EXPECTED:.1f}")
    assert published[1] == ("OTGW/set/otgw-1/chenable", "1")
    assert published[-1] == ("OTGW/set/otgw-1/ctrlsetpt", "0")
    assert rig.plugin_calls() <= {("mqtt", "publish"), ("weather", "get_forecasts")}


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
    assert rig.state("switch", "control").state == "on"
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
    assert number.writes == [EXPECTED, 50.0]
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert not control.stored()["hand_back_pending"]


async def test_a_value_hand_back_the_device_does_not_take_stays_owed(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, hand_back_value=10))
    await rig.switch(True)
    number.lowest = 20.0  # the device keeps its value: the hand-back does not reach the boiler
    await rig.switch(False)
    assert number.writes == [EXPECTED, 10.0]
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"  # not yet due
    await rig.advance(60)
    assert number.writes == [EXPECTED, 10.0, 10.0]  # sent again
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    assert rig.entry.runtime_data.control.stored()["hand_back_pending"]
    number.lowest = None
    await rig.advance(70)
    assert number.writes[-1] == 10.0
    assert number.value == 10.0
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert not rig.entry.runtime_data.control.stored()["hand_back_pending"]


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
    assert rig.state("switch", "control").state == "off"
    assert rig.gateway.setpoints() == [0.0]  # handed back, though control is off
    await rig.advance(20)
    assert rig.gateway.setpoints() == [0.0]  # once
    assert entry.runtime_data.control.stored()["controlling"] is False


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_an_unclean_restart_with_control_on_hands_back_first_then_resumes(
    rig: Rig, hass_storage: dict[str, Any], layout: str
) -> None:
    """The last run held the boiler and ended without a hand-back, and control is to stay on:
    what that run left is given back in full first, then control takes the boiler afresh."""
    mock_restore_cache(rig.hass, [State("switch.boiler_boiler_control_experimental", "on")])
    await start_with_stored(rig, hass_storage, {"controlling": True}, layout)
    await rig.advance(20)
    calls = rig.gateway.calls
    back = calls.index(("setpoint", 0.0))
    assert calls[back - 1] == ("ch", True)  # CH=1, then CS=0
    assert rig.gateway.setpoints()[-1] == EXPECTED  # then control again
    assert rig.state("switch", "control").state == "on"


async def test_a_write_reported_failed_is_still_handed_back(rig: Rig) -> None:
    """A write that timed out may still have reached the boiler: the next hand-back is not
    skipped as if nothing had been written."""
    await start(rig)
    await rig.switch(True)
    await rig.switch(False)
    assert rig.gateway.setpoints() == [EXPECTED, 0.0]
    rig.gateway.fail_after = True
    await rig.switch(True)  # setpoint and heating arrive; both calls report a failure
    assert rig.gateway.setpoints() == [EXPECTED, 0.0, EXPECTED]
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
    assert number.writes == [EXPECTED, 50.0]
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
    assert number.writes == [50.0]  # handed back through what took the boiler
    assert issue(rig, "hand_back_owed") is None


async def test_changing_the_write_path_is_refused_while_a_hand_back_is_owed(rig: Rig) -> None:
    await owe_a_hand_back(rig)
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "confirmed_entity": CONFIRMED,
        },
    )
    assert flow["errors"] == {"write_path": "hand_back_pending"}


async def _first_control_step(rig: Rig, answer: dict[str, Any]) -> Any:
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    return await rig.hass.config_entries.options.async_configure(flow["flow_id"], answer)


GATEWAY_ANSWER = {"write_path": "opentherm_gw", "topology": "gateway_with_thermostat"}


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
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": other})
    assert flow["errors"] == {"confirmed_entity": "hand_back_pending"}
    assert rig.entry is not None
    assert rig.entry.options["control"]["confirmed_entity"] == CONFIRMED
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": CONFIRMED})
    assert flow["step_id"] == "control_gateway"  # the same read-back goes on


async def test_the_gateways_read_back_cannot_change_while_control_holds_the_boiler(
    rig: Rig,
) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": other})
    assert flow["errors"] == {"confirmed_entity": "control_holds_boiler"}


async def test_an_entry_that_is_not_running_is_guarded_by_its_store(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """R6, H2 with C1: with the entry not running — its setup failed, say — the options are
    still open, and the next start makes the hand-back the last run left owed through what they
    say then. The store tells the guard what is owed; "no control" stays possible."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
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
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": number.entity_id},
    )
    assert flow["errors"] == {"write_path": "hand_back_pending"}
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": other})
    assert flow["errors"] == {"confirmed_entity": "hand_back_pending"}
    flow = await _first_control_step(rig, {"write_path": "none"})
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
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]


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
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"write_path": "none"}
    )
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    assert "control" not in rig.entry.options
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
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": number.entity_id},
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
    flow = await rig.hass.config_entries.options.async_configure(flow["flow_id"], unchanged)
    assert flow["errors"] == {"base": "hand_back_pending"}
    assert rig.entry.options["control"]["ch_entity"] == "input_boolean.fake_ch"


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
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "confirmed_entity": CONFIRMED,
        },
    )
    assert flow["step_id"] == "control_gateway"  # another device, accepted


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
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": number.entity_id},
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
    result = await rig.hass.config_entries.options.async_configure(flow["flow_id"], other)
    assert result["errors"] == {"base": "control_holds_boiler"}
    await rig.switch(False)  # given back through the device that has it
    result = await rig.hass.config_entries.options.async_configure(flow["flow_id"], other)
    assert result["step_id"] == "control_curve"


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
    }
    await start(rig, **control)
    await rig.switch(True)
    await rig.switch(False)
    assert switch.writes[-1] is False  # sent...
    assert switch.on  # ...and not taken
    await rig.advance(70)
    assert switch.writes.count(False) >= 2  # sent again
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"


async def test_while_vt_reloads_its_central_entry_control_waits(rig: Rig) -> None:
    """T6: VT's central boiler switched off, its sensor a stand-in. While VT sets its central
    entry up again, its own central boiler cannot be ruled out: control gives the boiler back
    and says why, then takes it again once VT is back without it."""
    from homeassistant.config_entries import ConfigEntryState

    from .harness import VT_PLATFORM

    central = MockConfigEntry(
        domain="versatile_thermostat",
        data={"use_central_boiler_feature": False},
        state=ConfigEntryState.LOADED,
    )
    central.add_to_hass(rig.hass)
    registry = er.async_get(rig.hass)
    sensor = registry.async_get_or_create(
        "binary_sensor", VT_PLATFORM, "central_boiler_state", config_entry=central
    )
    registry.async_get(sensor.entity_id).write_unavailable_state(rig.hass)
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    central.mock_state(rig.hass, ConfigEntryState.SETUP_IN_PROGRESS)
    await rig.advance(20)
    attributes = rig.state("sensor", "control_state").attributes
    assert "vt_central_boiler_unknown" in attributes["blockers"]
    assert rig.gateway.setpoints()[-1] == 0.0
    central.mock_state(rig.hass, ConfigEntryState.LOADED)
    await rig.advance(20)
    assert (
        "vt_central_boiler_unknown"
        not in rig.state("sensor", "control_state").attributes["blockers"]
    )
    assert rig.gateway.setpoints()[-1] == EXPECTED


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
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]
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
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]
    assert rig.gateway.override is None
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"


async def test_an_otgw_hand_back_clears_the_heating_override(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.zones.set("living", hvac_action="idle", valve_open_percent=0, on_percent=0.0)
    await rig.advance(310)  # the next decision: no demand, heating off
    assert ("ch", False) in rig.gateway.calls
    await rig.switch(False)
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]


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
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]


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
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]


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
    assert rig.gateway.calls[before:] == [("ch", True), ("setpoint", 0.0)]  # the hand-back only


async def test_a_slow_smartpi_call_does_not_hold_up_control(rig: Rig) -> None:
    hass = rig.hass
    learning: list[tuple[str, bool]] = []
    slow = asyncio.Event()

    async def set_learning(call: ServiceCall) -> None:
        learning.append((call.data["entity_id"], call.data["learning_enabled"]))
        if not call.data["learning_enabled"]:
            await slow.wait()

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        on_percent=0.6,
        configuration={"proportional_function": "smartpi"},
        specific_states={"smartpi_learning_enabled": True},
    )
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    rig.freezer.tick(10)
    rig.live()
    async_fire_time_changed(hass)  # the step pauses learning; SmartPI hangs
    await settle(rounds=50)
    assert learning == [(rig.zones.entities["living"], False)]
    off = asyncio.ensure_future(
        hass.services.async_call(
            "switch", "turn_off", {"entity_id": rig.entity("switch", "control")}, blocking=True
        )
    )
    done = await settle(off)
    slow.set()
    await off
    await hass.async_block_till_done()
    assert done, "switching control off waited for SmartPI"
    assert ("setpoint", 0.0) in rig.gateway.calls


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


async def test_the_one_rewrite_is_remembered_across_a_restart(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """An outside change was rewritten an hour before the restart: within the day another one is
    not fought, even in the new run."""
    now = START.timestamp()
    mock_restore_cache(rig.hass, [State("switch.boiler_boiler_control_experimental", "on")])
    await start_with_stored(rig, hass_storage, {"rewritten_at": now - 3600.0})
    await rig.advance(20)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    rig.gateway.forced = 60.0  # another controller writes its own value
    await rig.advance(20)
    assert rig.gateway.setpoints().count(EXPECTED) == 1  # not written again
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"


async def test_a_day_after_the_one_rewrite_another_outside_change_is_rewritten(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The one rewrite is per day: more than a day after it, an outside change is rewritten
    once again before it counts as another controller."""
    now = START.timestamp()
    mock_restore_cache(rig.hass, [State("switch.boiler_boiler_control_experimental", "on")])
    await start_with_stored(rig, hass_storage, {"rewritten_at": now - 25 * 3600.0})
    await rig.advance(20)
    rig.gateway.forced = 60.0
    await rig.advance(20)
    assert rig.gateway.setpoints().count(EXPECTED) == 2  # rewritten once more


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
    hand-back — stand-alone, heating stops, as the switch says. Control resumes with the data."""
    await start(rig, topology=topology)
    await rig.switch(True)
    effect = rig.state("switch", "control").attributes["hand_back_effect"]
    standalone = topology == "gateway_standalone"
    assert effect == ("heating_stops" if standalone else "thermostat_takes_over")
    rig.flow = None
    rig.live()
    count = len(rig.gateway.calls)
    await rig.advance(310)
    assert rig.gateway.calls[count:] == [("ch", True), ("setpoint", 0.0)]
    assert rig.state("binary_sensor", "alarm_boiler_link_lost").state == "on"
    rig.flow = 35.0
    await rig.advance(20)
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
    already true during the start: control waits for the start to end."""
    from homeassistant.core import CoreState

    rig.hass.set_state(CoreState.starting)
    await start(rig)
    await rig.switch(True)  # not refused: the blocker passes on its own
    await rig.advance(20)
    assert rig.gateway.calls == []
    assert "ha_starting" in rig.state("sensor", "control_state").attributes["blockers"]
    rig.hass.set_state(CoreState.running)
    await rig.advance(10)
    assert rig.gateway.setpoints() == [EXPECTED]


async def test_a_zone_unknown_for_long_raises_an_alarm(rig: Rig) -> None:
    """The known zones decide meanwhile; frost protection cannot see the unknown one, so after a
    while the user is told."""
    await start(rig)
    await rig.switch(True)
    rig.zones.set("living", "unavailable")
    await rig.advance(20 * 60)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "off"
    await rig.advance(11 * 60)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "on"
    state = rig.state("sensor", "control_state")
    assert state.attributes["unknown_zones"] == [rig.zones.entities["living"]]
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "off"


async def test_frost_heating_that_does_not_warm_the_room_raises_an_alarm(rig: Rig) -> None:
    """Frost protection is never stopped; heating that leaves the room as cold for two hours is
    reported."""

    async def cold_for(seconds: int) -> None:
        for _ in range(seconds // 60):  # VT keeps reporting the room, as cold as it was
            rig.zones.set("living", "off", current_temperature=3.0, hvac_action="off")
            await rig.advance(60, step=60)

    rig.zones.set("living", "off", current_temperature=3.0, hvac_action="off")
    await start(rig)
    await rig.switch(True)
    await cold_for(3600)
    assert rig.state("sensor", "control_state").state == "frost"
    assert rig.state("binary_sensor", "alarm_frost_not_warming").state == "off"
    await cold_for(3660)
    assert rig.state("binary_sensor", "alarm_frost_not_warming").state == "on"
    assert rig.gateway.calls[-1] != ("setpoint", 0.0)  # still heating
    rig.zones.set("living", "off", current_temperature=8.0, hvac_action="off")
    await rig.advance(60, step=60)
    assert rig.state("binary_sensor", "alarm_frost_not_warming").state == "off"


async def test_the_switch_says_how_off_is_sent(rig: Rig) -> None:
    """Through the heating switch (on an OpenTherm Gateway, CH=0) where there is one; else as a
    low setpoint, which may leave the CH pump running."""
    await start(rig)
    assert rig.state("switch", "control").attributes["off_by"] == "heating_switch"


async def test_without_a_heating_switch_off_is_a_low_setpoint(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    assert rig.state("switch", "control").attributes["off_by"] == "low_setpoint"


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
    value, then the fallback, and the user is told."""
    from custom_components.vtherm_smart_boiler.core.signal_check import (
        OutdoorCheck,
        OutdoorStatus,
    )

    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    from dataclasses import replace as replaced

    coordinator = rig.entry.runtime_data
    await rig.hass.async_block_till_done(wait_background_tasks=True)  # the first analysis
    await coordinator.async_run_analysis()
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
    await coordinator.async_run_analysis()
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


async def test_a_zone_whose_room_sensor_is_lost_raises_the_alarm(rig: Rig) -> None:
    """R6, T2: the room sensor VT reads goes away. VT keeps the last temperature — with the
    zone off its safety check sleeps — so frost protection cannot see the room: after the
    limit the user is told, as for a zone whose state is unknown. The zone's demand still
    counts, VT runs it; the sensor back, the alarm clears."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    living = rig.zones.entities["living"]
    vt = MockConfigEntry(
        domain="versatile_thermostat", data={"temperature_sensor_entity_id": "sensor.room"}
    )
    vt.add_to_hass(rig.hass)
    er.async_get(rig.hass).async_update_entity(living, config_entry_id=vt.entry_id)
    rig.hass.states.async_set("sensor.room", "20.0")
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "off"
    rig.hass.states.async_set("sensor.room", "unavailable")
    await rig.advance(20 * 60)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "off"  # not yet
    state = rig.state("sensor", "control_state")
    assert state.attributes["room_sensor_lost_zones"] == [living]
    assert state.attributes["unknown_zones"] == []  # its demand still counts
    await rig.advance(11 * 60)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "on"
    rig.hass.states.async_set("sensor.room", "19.5")
    await rig.advance(20)
    assert rig.state("binary_sensor", "alarm_zone_unknown").state == "off"
    assert rig.state("sensor", "control_state").attributes["room_sensor_lost_zones"] == []


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
    assert rig.gateway.calls[count:] == [("ch", True), ("setpoint", 0.0)]


async def test_heating_switched_from_outside_is_written_once_then_handed_back(rig: Rig) -> None:
    """P22: with a heating echo, heating on/off is confirmed by the gateway, and another
    controller switching it is written again once; the next time, every write stops."""
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.switch(True)
    await rig.advance(30)
    assert rig.state("sensor", "control_state").attributes["heating_confirmation"] == (
        "confirmed_by_gateway"
    )
    rig.gateway.forced_ch = False  # another controller switches heating off
    count = len(rig.gateway.calls)
    await rig.advance(10)
    assert ("ch", True) in rig.gateway.calls[count:]  # the one rewrite
    rig.gateway.forced_ch = None
    await rig.advance(20)  # ours again
    rig.gateway.forced_ch = False  # and switched off again
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    await rig.advance(10)
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.gateway.calls[-2:] == [("ch", True), ("setpoint", 0.0)]  # the hand-back


async def test_keep_alives_do_not_move_the_last_change(rig: Rig) -> None:
    """P88: repeating the same value changes nothing, heating on/off included."""
    await start(rig)
    await rig.switch(True)
    first = rig.state("sensor", "control_setpoint").attributes["last_change"]
    await rig.advance(120)
    assert rig.gateway.calls.count(("ch", True)) > 1  # heating on/off was repeated
    assert rig.state("sensor", "control_setpoint").attributes["last_change"] == first


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


async def test_a_fahrenheit_setpoint_entity_gets_fahrenheit(rig: Rig) -> None:
    """P11: the entity's own unit on write and in the range check — 45 °C is not 45 °F."""
    number = FakeNumber(
        rig.hass, unit="°F", value=122.0, attributes={"min": 50, "max": 190, "step": 1}
    )
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert rig.state("switch", "control").attributes["blockers"] == []
    assert number.writes == [round(EXPECTED * 9 / 5 + 32)]  # on its 1 °F step
    await rig.advance(130)
    setpoint = rig.state("sensor", "control_setpoint")
    assert setpoint.attributes["read_back"] == pytest.approx(EXPECTED, abs=0.3)  # in °C
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"


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
    """P42: a write failing at every step for minutes is one warning, with its trace, not one
    every ten seconds; its recovery is one line too."""
    await start(rig)
    await rig.switch(True)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.advance(120)
    assert _logged(caplog, logging.WARNING, "boiler write failed") == 1
    failure = next(r for r in caplog.records if "boiler write failed" in r.getMessage())
    assert failure.exc_info is not None  # with the trace
    rig.gateway.register()
    await rig.advance(30)
    assert _logged(caplog, logging.INFO, "works again") == 1
    assert _logged(caplog, logging.WARNING, "boiler write failed") == 1


async def test_a_lasting_hand_back_failure_is_logged_once(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    await start(rig)
    await rig.switch(True)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(False)  # the hand-back fails, and is retried every minute
    await rig.advance(300)
    assert _logged(caplog, logging.ERROR, "Handing control back failed") == 1
    rig.gateway.register()
    await rig.advance(70)
    assert _logged(caplog, logging.INFO, "hand-back went through") == 1


async def test_a_lasting_learning_failure_is_logged_once_per_zone(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    hass = rig.hass
    attempts: list[bool] = []

    def smartpi(learning: bool) -> None:
        rig.zones.set(
            "living",
            hvac_action="heating",
            valve_open_percent=60,
            on_percent=0.6,
            configuration={"proportional_function": "smartpi"},
            specific_states={"smartpi_learning_enabled": learning},
        )

    async def set_learning(call: ServiceCall) -> None:
        attempts.append(call.data["learning_enabled"])
        if call.data["learning_enabled"]:
            raise HomeAssistantError("SmartPI is not ready")
        smartpi(False)  # the pause goes through

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    smartpi(True)
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(10)  # paused
    await rig.switch(False)  # its release fails, and is sent again every minute
    for _ in range(5):
        await rig.advance(60)
        smartpi(False)  # the zone reports again, still paused
    assert attempts.count(True) >= 3
    assert _logged(caplog, logging.WARNING, "SmartPI learning") == 1


async def test_a_resume_smartpi_skipped_is_sent_again_until_it_reads_on(rig: Rig) -> None:
    """P41: SmartPI skips a thermostat it cannot find without an error, and keeps its flag for
    good: a resume counts only once the flag reads on, and is sent again every minute."""
    hass = rig.hass
    calls: list[bool] = []
    skipping = True

    def smartpi(learning: bool) -> None:
        rig.zones.set(
            "living",
            hvac_action="heating",
            valve_open_percent=60,
            on_percent=0.6,
            configuration={"proportional_function": "smartpi"},
            specific_states={"smartpi_learning_enabled": learning},
        )

    async def set_learning(call: ServiceCall) -> None:
        enabled = call.data["learning_enabled"]
        calls.append(enabled)
        if not enabled or not skipping:
            smartpi(enabled)

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    smartpi(True)
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(10)
    assert calls == [False]
    await rig.switch(False)  # released: the resume is skipped without an error
    assert calls == [False, True]
    await rig.advance(130)
    assert calls.count(True) >= 3  # sent again every minute while the flag reads off
    skipping = False
    await rig.advance(60)
    count = len(calls)
    await rig.advance(180)
    assert len(calls) == count  # read back on: done
    assert (
        rig.hass.states.get(rig.zones.entities["living"]).attributes["specific_states"][
            "smartpi_learning_enabled"
        ]
        is True
    )


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
            "paused": "not a mapping",
            "rewritten_at": "yesterday",
            "alarms": ["no_such_alarm"],
        },
        layout,
    )
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert rig.gateway.calls[:2] == HAND_BACK  # the owed hand-back was kept (made at setup)
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
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry


HAND_BACK = [("ch", True), ("setpoint", 0.0)]  # CH=1, then CS=0 (the order changes in V5)


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
    mock_restore_cache(hass, [State("switch.boiler_boiler_control_experimental", "on")])
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
    assert rig.gateway.calls[:2] == HAND_BACK  # the first step hands back in full
    assert rig.gateway.setpoints()[-1] == EXPECTED  # then control takes the boiler afresh
    assert issue(rig, "control_state_unreadable") is not None
    assert entry.runtime_data.monitoring_since == entry.created_at.timestamp()


@pytest.mark.parametrize("main_left", [True, False], ids=["control_store_lost", "both_lost"])
async def test_a_missing_control_store_of_an_entry_that_ran_hands_back_first(
    rig: Rig, hass_storage: dict[str, Any], main_left: bool
) -> None:
    """The entry store has the marker, so the control store was written, and now it is gone —
    or both stores are. Control is configured, so the entry ran: a full hand-back first."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    if main_left:
        seed_main(hass_storage, entry, control={"controlling": False})
    await set_up(rig, entry)
    await rig.advance(30)
    assert rig.gateway.calls == HAND_BACK
    assert issue(rig, "control_state_unreadable") is not None
    stored = stored_control(hass_storage, rig)  # written afresh, the hand-back confirmed
    assert (stored["controlling"], stored["hand_back_pending"]) == (False, False)


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
    assert number.writes == [50.0]
    assert issue(rig, "control_state_unreadable") is not None


def unit_state(**changes: Any) -> dict[str, Any]:
    """The control state as a unit stores it."""
    return {
        "controlling": False,
        "taken_with": None,
        "paused": {},
        "resuming": {},
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
    # With what 0.2.2 adds: the wish, off without a restored switch, stored at once (V3), and
    # the setpoint a gateway's release must leave, none while nothing is owed (V4).
    moved = control | {
        "enabled": False,
        "last_command": None,
        "resume_since": {},
        "release_from": None,
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
        0.0, 0.0, False, 8.5, None, 4.0, 60.0,
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
    assert sent[:2] == HAND_BACK  # sent before the failure
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
    """An entry created at ``created_at`` that ran before, with a monitoring period of 7 days;
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


def monitoring_blocked(rig: Rig) -> bool:
    assert rig.entry is not None
    return "monitoring_period" in rig.entry.runtime_data.control.blockers(START.timestamp())


async def test_a_lost_monitoring_start_falls_back_to_the_entry_creation(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """T-35 (P-01): the stored start is gone, the entry was created 10 days ago: the 7-day
    monitoring period is over — a lost store does not start it again."""
    created = START - timedelta(days=10)
    await start_created(rig, hass_storage, created)
    assert not monitoring_blocked(rig)
    verdict = rig.state("sensor", "verdict")
    assert verdict.attributes["monitoring_since"] == created.timestamp()


async def test_monitoring_counts_from_the_entry_creation_even_after_a_restarted_start(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """A stored start of yesterday — 0.2.1 started it again after losing its store — does not
    hold control back: the entry was created 10 days ago."""
    created = START - timedelta(days=10)
    entry = await start_created(
        rig, hass_storage, created, monitoring_since=(START - timedelta(days=1)).timestamp()
    )
    assert not monitoring_blocked(rig)
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
    assert monitoring_blocked(rig)


@pytest.mark.parametrize("section", [True, False], ids=["control", "monitor_only"])
async def test_an_unreadable_store_guards_the_options_flow(
    rig: Rig, hass_storage: dict[str, Any], section: bool
) -> None:
    """P-58: the entry is not running and its control store cannot be read. With a control
    section the options flow answers as setup would — a hand-back is owed — and keeps the write
    path; a monitor-only entry owes nothing and may set control up."""
    entry_options = options(rig.zones)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=entry_options if section else without_control(entry_options),
    )
    entry.add_to_hass(rig.hass)  # never set up
    rig.entry = entry
    seed_main(hass_storage, entry)
    seed_control(hass_storage, entry, ["not", "a", "mapping"])
    number = FakeNumber(rig.hass)
    number.register()
    flow = await _first_control_step(
        rig,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": number.entity_id},
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
    loaded = {s.taken_at for s in recorder.store.snapshots()}
    assert taken[current - 2] in loaded
    assert taken[current] in loaded
    assert taken[current - 1] not in loaded


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
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "freshness"}
    )
    flow = await rig.hass.config_entries.options.async_configure(flow["flow_id"], {"flow": 30})
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
    rig: Rig, monkeypatch: pytest.MonkeyPatch
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
    mock_restore_cache(rig.hass, [State("switch.boiler_boiler_control_experimental", "on")])
    entry = add_entry(rig, options(rig.zones))
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert rig.gateway.setpoints()[0] == EXPECTED  # control had taken the boiler
    assert rig.gateway.calls[-2:] == HAND_BACK
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
    await rig.advance(150)  # past the delayed save
    assert {key: hass_storage[key] for key in before} == before
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

    async def hand_back(self: OpenthermGwWriter, full: bool = False, **kwargs: Any) -> Any:
        if failures:
            raise failures.pop()
        return await original(self, full, **kwargs)

    monkeypatch.setattr(OpenthermGwWriter, "hand_back", hand_back)
    entry = owed_entry(rig, hass_storage)
    await set_up(rig, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.control.hand_back_owed
    assert issue(rig, "hand_back_owed") is not None
    assert rig.gateway.calls == []
    await rig.advance(70)  # the clock's retry, a minute later
    assert rig.gateway.calls[:2] == HAND_BACK
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


# --- V3: saved at once — last command, SmartPI pause, on/off wish, error latch ------------------

SWITCH = "switch.boiler_boiler_control_experimental"


def only_saves_made_at_once(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """From now on the control store gets only what is saved at once: the delayed control save
    is dropped, so whatever the store shows was written without waiting."""
    assert rig.entry is not None
    monkeypatch.setattr(rig.entry.runtime_data, "schedule_control_save", lambda: None)


def smartpi_zone(rig: Rig, learning: bool) -> None:
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        on_percent=0.6,
        configuration={"proportional_function": "smartpi"},
        specific_states={"smartpi_learning_enabled": learning},
    )


@pytest.mark.parametrize("stored_pause", [True, False], ids=["stored", "not_stored"])
async def test_a_smartpi_pause_is_stored_before_the_call(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, stored_pause: bool
) -> None:
    """T-29 (P-10): the pause is in the control store before SmartPI is asked, so a crash right
    after the call still knows the zone is the plugin's to resume. Negative: a store without the
    pause resumes nothing."""
    hass = rig.hass
    zone = rig.zones.entities["living"]
    calls: list[tuple[bool, dict[str, Any]]] = []

    async def set_learning(call: ServiceCall) -> None:
        stored = copy.deepcopy(stored_control(hass_storage, rig))
        calls.append((call.data["learning_enabled"], stored))
        smartpi_zone(rig, call.data["learning_enabled"])

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    smartpi_zone(rig, True)
    await start(rig)
    only_saves_made_at_once(rig, monkeypatch)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(10)
    assert [enabled for enabled, _ in calls] == [False]
    left = calls[0][1]  # what a crash at the call would leave
    assert zone in left["paused"]

    # The crash: the next start finds that store, and SmartPI still paused.
    assert rig.entry is not None
    entry = rig.entry
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    if not stored_pause:
        left = {**left, "paused": {}}
    seed_stores(hass_storage, entry, left, "0.2.2")
    smartpi_zone(rig, False)
    rig.dhw = False
    calls.clear()
    await set_up(rig, entry)
    await rig.switch(False)  # control off: what the plugin paused is resumed
    resumed = [enabled for enabled, _ in calls]
    assert resumed == ([True] if stored_pause else [])


@pytest.mark.parametrize("disabled", [True, False], ids=["disabled", "enabled"])
async def test_control_waits_for_the_switch_to_restore_then_counts_as_off(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, disabled: bool
) -> None:
    """T-31 (answer K): a control switch disabled in Home Assistant is never added, so it cannot
    restore the wish. The owed hand-back goes at once; nothing is decided for a minute; then
    control counts as off, whatever the stored wish, and nothing more is written. Negative: the
    same switch enabled restores the wish "on"."""
    steps = 0
    original = control_module.loop_step

    def counted(*args: Any, **kwargs: Any) -> Any:
        nonlocal steps
        steps += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(control_module, "loop_step", counted)
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    if disabled:
        er.async_get(rig.hass).async_get_or_create(
            "switch",
            DOMAIN,
            f"{entry.entry_id}_control",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
    seed_stores(hass_storage, entry, {"controlling": True, "enabled": True}, "0.2.2")
    await set_up(rig, entry)
    assert rig.gateway.calls[:2] == HAND_BACK  # the owed hand-back, at once
    unit = entry.runtime_data.control
    if not disabled:
        assert unit.enabled
        await rig.advance(10)
        assert rig.gateway.setpoints()[-1] == EXPECTED
        return
    await rig.advance(50)
    assert steps == 0  # no decision while the switch may still restore
    assert not unit.enabled
    await rig.advance(20)
    assert steps > 0
    assert not unit.enabled  # counts as off
    assert rig.gateway.calls == HAND_BACK  # nothing more written
    assert stored_control(hass_storage, rig)["enabled"] is False
    await rig.advance(60)
    assert rig.gateway.calls == HAND_BACK


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
    assert rig.state("switch", "control").state == ("on" if wish else "off")
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
async def test_a_first_start_without_a_stored_wish_uses_the_restored_switch(
    rig: Rig, hass_storage: dict[str, Any], restored: str | None
) -> None:
    """The first start of 0.2.2 has no stored wish: the switch's restored state decides once,
    and is stored from then on. Negative: without a restored state control is off."""
    if restored is not None:
        mock_restore_cache(rig.hass, [State(SWITCH, restored)])
    await start(rig)
    on = restored == "on"
    assert rig.state("switch", "control").state == ("on" if on else "off")
    await rig.advance(10)
    assert (EXPECTED in rig.gateway.setpoints()) is on
    assert stored_control(hass_storage, rig)["enabled"] is on


@pytest.mark.parametrize("raw", ["yes", 1, [], {"on": True}])
async def test_an_unreadable_stored_wish_counts_as_off(
    rig: Rig, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture, raw: Any
) -> None:
    """Negative: a wish that cannot be read is "off", not the restored switch."""
    mock_restore_cache(rig.hass, [State(SWITCH, "on")])
    await start_with_stored(rig, hass_storage, {"enabled": raw}, "0.2.2")
    await rig.advance(70)
    assert rig.state("switch", "control").state == "off"
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
    assert rig.state("switch", "control").state == "on"
    if not failed:
        assert rig.gateway.setpoints()[-1] == EXPECTED
        return
    assert "control_error" in rig.state("switch", "control").attributes["blockers"]
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
        rig.boiler.set(Signal.PRESSURE, 0.5)
        await rig.advance(40)
    elif ending == "internal_error":

        async def broken(self: Any, now: float) -> None:
            raise RuntimeError("a bug")

        monkeypatch.setattr(type(unit), "_async_step", broken)
        await rig.advance(10)
    elif ending == "blocker":
        boiler = er.async_get(hass).async_get_or_create(
            "binary_sensor", VT_PLATFORM, "central_boiler_state"
        )
        hass.states.async_set(boiler.entity_id, "off", {"is_central_boiler_configured": True})
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


@pytest.mark.parametrize("outcome", ["takes", "never_takes", "nothing_paused"])
async def test_a_resume_that_did_not_take_is_followed_after_control_leaves_the_options(
    rig: Rig, hass_storage: dict[str, Any], outcome: str
) -> None:
    """C15: control leaves the options while a SmartPI zone is paused, and the resume made on
    the way out does not take. After the reload a unit that only follows learning sends it again
    every minute until the flag reads on, and gives up a day after the first resume. Negative:
    with nothing paused, no such unit is built."""
    hass = rig.hass
    zone = rig.zones.entities["living"]
    calls: list[bool] = []
    skipping = True

    async def set_learning(call: ServiceCall) -> None:
        enabled = call.data["learning_enabled"]
        calls.append(enabled)
        if not enabled or not skipping:
            smartpi_zone(rig, enabled)

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    smartpi_zone(rig, True)
    await start(rig)
    await rig.switch(True)
    if outcome != "nothing_paused":
        rig.dhw = True
        await rig.advance(10)
        assert calls == [False]
    assert rig.entry is not None
    entry = rig.entry
    hass.config_entries.async_update_entry(entry, options=without_control(dict(entry.options)))
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.control is None
    if outcome == "nothing_paused":
        assert coordinator.hand_back_unit is None
        assert calls == []
        return
    unit = coordinator.hand_back_unit
    assert unit is not None
    assert ("vtherm_smartpi", "set_smartpi_learning") in unit.allowed_services
    assert calls == [False, True]  # resumed on the way out, and skipped
    assert zone in stored_control(hass_storage, rig)["resuming"]
    await rig.advance(130)
    assert calls.count(True) >= 3  # sent again every minute
    if outcome == "takes":
        skipping = False
        await rig.advance(60)
        count = len(calls)
        await rig.advance(180)
        assert len(calls) == count  # read back on: done
        assert stored_control(hass_storage, rig)["resuming"] == {}
        return
    await rig.advance(86400, step=600.0)
    count = len(calls)
    await rig.advance(1800, step=600.0)
    assert len(calls) == count  # given up a day after the first resume
    assert stored_control(hass_storage, rig)["resuming"] == {}
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # nothing but the hand-back written


@pytest.mark.parametrize("paused", [False, True], ids=["no_unit", "learning_unit"])
async def test_control_added_back_after_removal_starts_off(
    rig: Rig, hass_storage: dict[str, Any], paused: bool
) -> None:
    """Control left the options while on: the stored wish and last command go, so control
    added back later starts off, with no command to give again — whether a unit still follows
    SmartPI resumes or none runs."""
    hass = rig.hass

    async def set_learning(call: ServiceCall) -> None:
        if not call.data["learning_enabled"]:
            smartpi_zone(rig, False)  # a pause takes; a resume never does

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    smartpi_zone(rig, True)
    await start(rig)
    await rig.switch(True)
    if paused:
        rig.dhw = True
        await rig.advance(10)
    assert rig.entry is not None
    entry = rig.entry
    with_control = dict(entry.options)
    hass.config_entries.async_update_entry(entry, options=without_control(with_control))
    await hass.async_block_till_done()
    assert (entry.runtime_data.hand_back_unit is not None) is paused
    await rig.advance(10)
    stored = stored_control(hass_storage, rig)
    assert (stored["enabled"], stored["last_command"]) == (False, None)
    count = len(rig.gateway.calls)
    hass.config_entries.async_update_entry(entry, options=with_control)
    await hass.async_block_till_done()
    await rig.advance(70)
    assert rig.state("switch", "control").state == "off"
    assert len(rig.gateway.calls) == count


# --- V4: the hand-back's bookkeeping (P-12, P-42, P-49, P-50, P-51, P-52; Open after R6 #8) -----

CURVE_ANSWER = {"design_outdoor": -15, "design_flow": 55, "hard_min": 25, "hard_max": 70}


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
    assert rig.gateway.calls[-2:] == HAND_BACK  # the next attempt
    assert not unit.hand_back_owed


@pytest.mark.parametrize("ending", ["unload", "reload", "step_error"])
async def test_stop_never_raises_when_the_hand_back_raises_unexpectedly(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    """T-06 (P-42, R1): ``writer.hand_back`` raises what no writer reports (a bug). Nothing
    escapes; the debt stays owed and stored — with the persistent issue when the entry unloads,
    and the issue shown with ``control_error`` after a failed step — and the next start makes a
    full hand-back. Every attempt made while the debt exists is full (P-49); the first, made for
    the session's end, is not."""
    from custom_components.vtherm_smart_boiler.transport.writers import OpenthermGwWriter

    hass = rig.hass
    original = OpenthermGwWriter.hand_back
    fulls: list[bool] = []
    # The attempts that fail: the stop's, and after a failed step the step's too.
    failures = 2 if ending == "step_error" else 1

    async def hand_back(self: OpenthermGwWriter, full: bool = False, **kwargs: Any) -> Any:
        nonlocal failures
        fulls.append(full)
        if failures:
            failures -= 1
            raise RuntimeError("a bug in the writer")
        return await original(self, full, **kwargs)

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
        assert rig.gateway.calls[count:][:2] == HAND_BACK
    # The session's own hand-back is not full; every later one is, a debt existing (P-49).
    assert fulls == [False] + [True] * (2 if ending == "step_error" else 1)
    assert not unit_of(rig).hand_back_owed
    assert issue(rig, "hand_back_owed") is None


@pytest.mark.parametrize("older_debt", [True, False], ids=["older_debt", "no_debt"])
async def test_an_end_of_session_hand_back_is_full_while_an_older_debt_exists(
    rig: Rig, hass_storage: dict[str, Any], older_debt: bool
) -> None:
    """P-49 (R2): the last run left a hand-back owed, with its held heating switch left off, and
    this session's writes all fail (both targets away). Switched off, the session's hand-back is
    full: the heating switch goes back on, though this session never switched it — its success
    would clear the older debt too. Negative: without an older debt it is not full, and a switch
    this session never touched is left as it is (V5 decides that anew)."""
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
    assert unit.hand_back_owed is older_debt
    switch.set_available(True)  # back, and still off
    await rig.switch(False)
    assert switch.on is older_debt


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


async def test_gateway_id_cannot_change_while_a_hand_back_is_owed(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """T-13 (P-12, R4): two gateways. The control steps pass with nothing owed and pick gw2;
    before the save, the unit starts owing a hand-back through gw1. The save goes back to the
    control step with the reason, the options stay, and the hand-back goes on through gw1.
    Negative: with nothing owed at the save, gw2 is saved."""
    for gateway in ("gw", "gw2"):
        MockConfigEntry(domain="opentherm_gw", data={"id": gateway}).add_to_hass(rig.hass)
    await start(rig)
    assert rig.entry is not None
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": CONFIRMED})
    assert flow["step_id"] == "control_gateway"
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"gateway_id": "gw2"}
    )
    assert flow["step_id"] == "control_curve"
    # Before the save: control takes the boiler, the gateway drops, control is switched off.
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    flow = await rig.hass.config_entries.options.async_configure(flow["flow_id"], CURVE_ANSWER)
    assert flow["step_id"] == "control"
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
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": CONFIRMED})
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"gateway_id": "gw2"}
    )
    flow = await rig.hass.config_entries.options.async_configure(flow["flow_id"], CURVE_ANSWER)
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    assert rig.entry.options["control"]["gateway_id"] == "gw2"


@pytest.mark.parametrize(
    ("node", "saved"), [("otgw-2", False), ("  otgw-1 ", True)], ids=["changed", "spaces"]
)
async def test_mqtt_topics_cannot_change_while_control_holds_the_boiler(
    rig: Rig, node: str, saved: bool
) -> None:
    """T-14 (P-12, R4): the MQTT step passes while control is off; before the save control takes
    the boiler. A changed node is refused at the save, back at the control step, the options
    kept; the same node with spaces around it passes."""

    async def publish(call: ServiceCall) -> None:
        if call.data["topic"].endswith("/ctrlsetpt"):
            value = float(call.data["payload"])
            rig.gateway.override = None if value == 0 else value
            rig.gateway.publish()

    rig.hass.services.async_register("mqtt", "publish", publish)
    # Without the opentherm_gw path's gateway: the flow drops what another path left.
    await start(rig, write_path="otgw_mqtt", mqtt_top="OTGW", mqtt_node="otgw-1", gateway_id=None)
    assert rig.entry is not None
    flow = await _first_control_step(
        rig,
        {"write_path": "otgw_mqtt", "topology": "gateway_with_thermostat"}
        | {"confirmed_entity": CONFIRMED},
    )
    assert flow["step_id"] == "control_mqtt"
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"mqtt_top": "OTGW", "mqtt_node": node}
    )
    assert flow["step_id"] == "control_curve"
    await rig.switch(True)  # control takes the boiler before the save
    await rig.advance(20)
    assert unit_of(rig).holding
    flow = await rig.hass.config_entries.options.async_configure(flow["flow_id"], CURVE_ANSWER)
    if saved:
        assert flow["type"] == "create_entry"
    else:
        assert flow["step_id"] == "control"
        assert flow["errors"] == {"base": "control_holds_boiler"}
    await rig.hass.async_block_till_done()
    assert rig.entry.options["control"]["mqtt_node"] == "otgw-1"


async def test_the_gateways_read_back_cannot_change_at_the_save(rig: Rig) -> None:
    """R4: the gateway's read-back, which judges its release, re-picked while nothing was owed;
    owed before the save: refused there. Negative, a missing control section: "no control"
    stays possible at the save, the hand-back going through what took the boiler."""
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw"}).add_to_hass(rig.hass)
    await start(rig)
    assert rig.entry is not None
    other = "sensor.somewhere_else_temperature"
    rig.hass.states.async_set(other, "20.0", {"unit_of_measurement": "°C"})
    flow = await _first_control_step(rig, GATEWAY_ANSWER | {"confirmed_entity": other})
    assert flow["step_id"] == "control_gateway"
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"gateway_id": "gw"}
    )
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    await rig.switch(False)
    flow = await rig.hass.config_entries.options.async_configure(flow["flow_id"], CURVE_ANSWER)
    assert flow["errors"] == {"base": "hand_back_pending"}
    assert rig.entry.options["control"]["confirmed_entity"] == CONFIRMED
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"write_path": "none"}
    )
    assert flow["type"] == "create_entry"
    await rig.hass.async_block_till_done()
    assert "control" not in rig.entry.options


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
    assert rig.gateway.calls[:2] == HAND_BACK
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
    assert rig.gateway.calls[-2:] == HAND_BACK  # sent, and the service returned
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
    assert rig.gateway.calls[:2] == HAND_BACK
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
    rig.gateway.ignore_release = True  # the release adds no report: only the value tells
    rig.live()
    caplog.clear()
    await set_up(rig, entry)
    assert unit_of(rig).hand_back_owed is (stored == "unreadable")
    warned = _logged(caplog, logging.WARNING, "unreadable stored control data: release_from")
    assert warned == (1 if stored == "unreadable" else 0)


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
    assert rig.gateway.calls[-2:] == HAND_BACK
    assert not unit.hand_back_owed
    assert _logged(caplog, logging.ERROR, "Could not store the owed hand-back") == 1


@pytest.mark.parametrize(
    "case", ["writes_capped", "budget_cut", "smartpi_in_budget", "no_time_for_smartpi"]
)
async def test_the_stop_hand_back_fits_home_assistants_budget(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    """R6 (Q3.3): Home Assistant gives all shutdown jobs together 20 s, then cancels them. At a
    stop each hand-back write is capped at 3 s, and the whole — writes, the wait for a late
    report and SmartPI's calls — ends within 15 s: a gateway that hangs leaves the hand-back
    owed, with the persistent issue, before Home Assistant cuts it."""
    hass = rig.hass
    learning: list[bool] = []
    smartpi_hangs = asyncio.Event()

    async def set_learning(call: ServiceCall) -> None:
        learning.append(call.data["learning_enabled"])
        if call.data["learning_enabled"]:
            await smartpi_hangs.wait()
        smartpi_zone(rig, call.data["learning_enabled"])

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    smartpi_zone(rig, True)
    await start(rig)
    await rig.switch(True)
    unit = unit_of(rig)
    if case in ("smartpi_in_budget", "no_time_for_smartpi"):
        rig.dhw = True
        await rig.advance(10)  # SmartPI paused; its resume at the stop will hang
        assert learning == [False]
        monkeypatch.setattr(control_module, "STOP_BUDGET_S", 2.0)
        if case == "no_time_for_smartpi":
            rig.gateway.ignore_release = True  # unconfirmed: the wait takes what is left
    else:
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
        rig.freezer.tick(3.1)  # 6.2 s: the second gave up too
    else:
        rig.freezer.tick(2.2)  # 4.1 s: past the budget (2 s or 4 s)
    assert await settle(stop, rounds=100), "the stop outlasted its budget"
    await stop
    if case == "smartpi_in_budget":
        assert learning == [False, True]  # the resume was tried, and given up at the budget
        assert rig.gateway.calls[-2:] == HAND_BACK
        assert not unit.hand_back_owed
        return
    if case == "no_time_for_smartpi":
        assert learning == [False]  # no time left for the resume: not made now...
        assert rig.zones.entities["living"] in unit.stored()["resuming"]  # ...but at next start
    assert unit.hand_back_owed
    found = issue(rig, "hand_back_owed")
    assert found is not None
    assert found.is_persistent
    ran_out = _logged(caplog, logging.ERROR, "ran out of time")
    if case != "no_time_for_smartpi":  # there the wait and the budget end together
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

    async def hand_back(self: OpenthermGwWriter, full: bool = False, **kwargs: Any) -> Any:
        nonlocal failures
        if failures:
            failures -= 1
            raise asyncio.CancelledError
        return await original(self, full, **kwargs)

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
    assert rig.gateway.calls[-2:] == HAND_BACK
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
