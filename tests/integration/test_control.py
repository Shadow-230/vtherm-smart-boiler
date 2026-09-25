"""Control in Home Assistant: switching on and off, keep-alive, every hand-back path, no write
without fresh data, guard alarms, learning pauses and the allowed service calls.

Everything runs in the test's Home Assistant; the gateway, VT and SmartPI are fakes that record
the calls they receive.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.vtherm_smart_boiler import control as control_module
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import BOILER_ENTITIES, VT_PLATFORM, FakeBoiler, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SIGNALS = (Signal.FLAME, Signal.FLOW, Signal.OUTDOOR, Signal.DHW_ACTIVE)
CONFIRMED = "sensor.fake_gateway_control_setpoint"
CH_ECHO = "binary_sensor.fake_gateway_central_heating"
OUTDOOR = 5.0
EXPECTED = round(HeatingCurve().flow(OUTDOOR), 1)  # the curve's setpoint at 5 °C outside
START = datetime(2026, 1, 12, 8, tzinfo=UTC)


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
    block: asyncio.Event | None = None  # a heating setpoint's call waits for this (a slow gateway)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    times: list[float] = field(default_factory=list)  # when each setpoint arrived

    def register(self) -> None:
        async def setpoint(call: ServiceCall) -> None:
            value = float(call.data["temperature"])
            self.calls.append(("setpoint", value))
            self.times.append(datetime.now(UTC).timestamp())
            self.override = None if value == 0 else value
            self.publish()
            if self.fail_after:
                raise HomeAssistantError("timed out")
            if self.block is not None and value != 0:
                await self.block.wait()

        async def heating(call: ServiceCall) -> None:
            self.calls.append(("ch", call.data["ch_override"]))
            self.ch = bool(call.data["ch_override"])
            self.publish()
            if self.fail_after:
                raise HomeAssistantError("timed out")

        self.hass.services.async_register("opentherm_gw", "set_control_setpoint", setpoint)
        self.hass.services.async_register("opentherm_gw", "set_central_heating_ovrd", heating)
        self.publish()

    def publish(self) -> None:
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

    def live(self) -> None:
        """The gateway's periodic reports: fresh boiler signals and setpoint echo."""
        values: dict[Signal, float | bool | None] = {
            Signal.FLAME: False,
            Signal.DHW_ACTIVE: self.dhw,
        }
        if self.outdoor_reported:
            values[Signal.OUTDOOR] = self.outdoor
        if self.flow_reported:
            values[Signal.FLOW] = self.flow
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
async def rig(hass: HomeAssistant, freezer, zones: FakeZones) -> Rig:
    freezer.move_to(START)
    boiler = FakeBoiler(hass, SIGNALS)
    gateway = FakeGateway(hass)
    gateway.register()
    zones.add("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig = Rig(hass, freezer, boiler, zones, gateway)
    rig.live()

    def record(event: Event) -> None:
        data = event.data
        rig.services.append((data["domain"], data["service"], dict(data["service_data"])))

    hass.bus.async_listen(EVENT_CALL_SERVICE, record)
    return rig


async def start(rig: Rig, **control: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **control)
    )
    entry.add_to_hass(rig.hass)
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
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
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
    assert rig.entry is not None
    return hass_storage[f"{DOMAIN}.{rig.entry.entry_id}"]["data"]["control"]


async def test_the_controlling_marker_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Were Home Assistant to crash now, the next start must know the boiler was held — not only
    after the store's two-minute delay."""
    await start(rig)
    await rig.switch(True)
    assert rig.gateway.setpoints() == [EXPECTED]
    assert stored_control(hass_storage, rig)["controlling"] is True


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


async def test_an_unclean_restart_with_control_on_hands_back_first_then_resumes(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The last run held the boiler and ended without a hand-back, and control is to stay on:
    what that run left is given back in full first, then control takes the boiler afresh."""
    mock_restore_cache(rig.hass, [State("switch.boiler_boiler_control_experimental", "on")])
    await start_with_stored(rig, hass_storage, {"controlling": True})
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


async def test_removing_the_entry_with_a_hand_back_owed_raises_a_repair_issue(rig: Rig) -> None:
    await owe_a_hand_back(rig)
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    await rig.hass.config_entries.async_remove(entry_id)
    await rig.hass.async_block_till_done()
    issues = ir.async_get(rig.hass)
    assert issues.async_get_issue(DOMAIN, f"hand_back_owed_after_removal_{entry_id}") is not None


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


async def start_with_stored(
    rig: Rig, hass_storage: dict[str, Any], control: dict[str, Any], **extra: Any
) -> MockConfigEntry:
    """Set up the entry over a store left by an earlier run."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **extra)
    )
    entry.add_to_hass(rig.hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"monitoring_since": 0.0, "control": control},
    }
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    return entry


async def test_a_restored_latch_shows_its_cause_and_never_expires(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    await start_with_stored(rig, hass_storage, {"latched": True, "latched_by": ["pressure_low"]})
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


async def test_a_user_freshness_limit_stops_writes_on_a_frozen_source(rig: Rig) -> None:
    """The flow stops reporting while its entity stays available (MQTT without availability):
    with a limit of ten minutes set, nothing is written after it, and control hands back."""
    entry_options = options(rig.zones) | {"freshness": {"flow": 600.0}}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
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


async def test_unreadable_control_data_still_restores_what_matters(
    rig: Rig, hass_storage: dict[str, Any]
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
    )
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    assert unit.hand_back_owed
    assert unit.status.latched_by == ("outside_change",) or unit._session.loop.control.latched


async def test_control_data_that_cannot_be_read_hands_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P66: when whether the plugin held the boiler cannot be read, it is taken that it did."""
    await start_with_stored(rig, hass_storage, {"controlling": "maybe"})
    assert rig.entry is not None
    assert rig.entry.runtime_data.control.hand_back_owed
