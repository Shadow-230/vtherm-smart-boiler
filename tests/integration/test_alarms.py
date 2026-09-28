"""Y1 in Home Assistant: alarms that cannot judge (S-16), pressure 0.0 only from the gateway
unknown (P-17), the notifications, the boiler's own fault (boiler protection), decision 7's
repair issue for every hand-back or latch, and hot-water draws with the named heating echo
(T-21's integration part).

The rig — the gateway, VT's zones and the boiler signals as fakes — is the control tests'.
"""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import BOILER_ENTITIES, FakeBoiler
from .test_control import (  # the rig fixture comes with them
    CH_ECHO,
    CONFIRMED,
    EXPECTED,
    HAND_BACK,
    SIGNALS,
    Rig,
    add_entry,
    blockers,
    issue,
    options,
    rig,  # noqa: F401
    set_up,
    start,
    unit_of,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

PRESSURE = BOILER_ENTITIES[Signal.PRESSURE]
FLUE_GAS = BOILER_ENTITIES[Signal.FLUE_GAS]
LOW_WATER = "binary_sensor.fake_boiler_low_water_pressure"
FAULT_INDICATION = "binary_sensor.fake_boiler_fault_indication"
MINUTE = 60.0


def register(
    rig: Rig,
    entity_id: str,
    platform: str,
    device_id: str | None = None,
    unique_id: str | None = None,
) -> None:
    """The entity in Home Assistant's entity registry, as ``platform`` registers it — its
    state, if it has one already, kept."""
    domain, object_id = entity_id.split(".", 1)
    state = rig.hass.states.get(entity_id)
    if state is not None:
        rig.hass.states.async_remove(entity_id)  # its ID is free to register
    entry = er.async_get(rig.hass).async_get_or_create(
        domain,
        platform,
        unique_id or f"test_{object_id}",
        suggested_object_id=object_id,
        device_id=device_id,
    )
    assert entry.entity_id == entity_id
    if state is not None:
        rig.hass.states.async_set(entity_id, state.state, state.attributes)


def mqtt_device(rig: Rig, name: str) -> str:
    """A device of MQTT's entry: the OTGW firmware's, or an EMS-ESP's."""
    mqtt = rig.hass.config_entries.async_entries("mqtt")[0]
    device = dr.async_get(rig.hass).async_get_or_create(
        config_entry_id=mqtt.entry_id, identifiers={("mqtt", name)}
    )
    return device.id


def with_pressure(rig: Rig, value: float | None, **monitor: Any) -> dict[str, Any]:
    """Options with the water pressure mapped, reading ``value``; ``monitor``: its options."""
    rig.boiler = FakeBoiler(rig.hass, (*SIGNALS, Signal.PRESSURE))
    set_pressure(rig, value)
    rig.live()
    entry_options = options(rig.zones)
    entry_options["signals"][Signal.PRESSURE.value] = PRESSURE
    entry_options["monitor"] = entry_options["monitor"] | monitor
    return entry_options


def set_pressure(rig: Rig, value: float | None) -> None:
    shown = "unavailable" if value is None else str(value)
    rig.hass.states.async_set(PRESSURE, shown, {"unit_of_measurement": "bar"})


def alarm_state(rig: Rig, kind: str) -> str:
    return rig.state("binary_sensor", f"alarm_{kind}").state


# --- P-17, question 8: 0.0 bar unknown only from the gateway ----------------------------------


@pytest.mark.parametrize("source", ["zigbee", "ems_esp_over_mqtt"])
async def test_zero_pressure_from_a_non_gateway_sensor_raises_add_water(
    rig: Rig, source: str
) -> None:
    """T-33 (P-17): a threshold of 0.8 bar entered; the pressure entity registered by a platform
    other than ``opentherm_gw``, or by ``mqtt`` on a device that is not the OTGW firmware's
    (an EMS-ESP sensor, the write path being ``otgw_mqtt``). The value goes 1.5 → 0.0 and stays
    five minutes: a reading — "add water" is on, and its repair issue names the value and the
    threshold."""
    control: dict[str, Any] = {}
    if source == "zigbee":
        register(rig, PRESSURE, "zha")
    else:
        control = {"write_path": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw-1"}
        register(rig, CONFIRMED, "mqtt", mqtt_device(rig, "otgw-1"))
        register(rig, PRESSURE, "mqtt", mqtt_device(rig, "ems-esp"))
    entry_options = with_pressure(rig, 1.5, add_water_below=0.8)
    entry_options["control"] |= control
    await set_up(rig, add_entry(rig, entry_options))
    await rig.advance(60)
    assert alarm_state(rig, "pressure_low") == "off"
    set_pressure(rig, 0.0)
    await rig.advance(240)
    assert alarm_state(rig, "pressure_low") == "off"  # four minutes: not yet
    await rig.advance(90)
    low = rig.state("binary_sensor", "alarm_pressure_low")
    assert low.state == "on"
    assert low.attributes["level"] == "alarm"
    assert low.attributes["value"] == 0.0
    found = issue(rig, "add_water")
    assert found is not None
    assert found.translation_placeholders == {"value": "0.00", "threshold": "0.8"}
    assert found.severity is ir.IssueSeverity.WARNING
    assert not found.is_fixable
    assert unit_of(rig).status.alarms == frozenset()  # it changes nothing in control


@pytest.mark.parametrize("source", ["opentherm_gw", "otgw_firmware_over_mqtt"])
async def test_zero_pressure_from_the_gateway_is_unknown(rig: Rig, source: str) -> None:
    """P-17: the OpenTherm Gateway reports 0 bar after a reset until a real reading — from its
    entity (registered by ``opentherm_gw``, or by ``mqtt`` on the device of the ``otgw_mqtt``
    path's read-back) 0.0 is unknown: the alarm holds its state an hour, then shows unknown;
    never "add water"."""
    control: dict[str, Any] = {}
    if source == "opentherm_gw":
        register(rig, PRESSURE, "opentherm_gw")
    else:
        device = mqtt_device(rig, "otgw-1")
        control = {"write_path": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw-1"}
        register(rig, CONFIRMED, "mqtt", device)
        register(rig, PRESSURE, "mqtt", device)
    entry_options = with_pressure(rig, 1.5, add_water_below=0.8)
    entry_options["control"] |= control
    await set_up(rig, add_entry(rig, entry_options))
    await rig.advance(60)
    set_pressure(rig, 0.0)
    await rig.advance(600, step=30.0)
    low = rig.state("binary_sensor", "alarm_pressure_low")
    assert low.state == "off"  # held: the last known state
    assert low.attributes["reason"] == "held"
    assert issue(rig, "add_water") is None
    await rig.advance(3600, step=60.0)
    assert alarm_state(rig, "pressure_low") == "unknown"
    assert issue(rig, "add_water") is None


# --- S-16, question 9: unknown inputs -----------------------------------------------------------


async def test_the_pressure_alarm_is_unknown_while_pressure_is_unknown(rig: Rig) -> None:
    """T-34 (S-16): the pressure entity unavailable from the start — the alarms show unknown,
    never "OK". After a reading, unavailable for 59 minutes: held; for 61: unknown."""
    await set_up(rig, add_entry(rig, with_pressure(rig, None, add_water_below=0.8)))
    await rig.advance(60)
    assert alarm_state(rig, "pressure_high") == "unknown"
    assert alarm_state(rig, "pressure_low") == "unknown"
    reason = rig.state("binary_sensor", "alarm_pressure_high").attributes["reason"]
    assert reason == "unknown_input"
    set_pressure(rig, 1.5)
    await rig.advance(60)
    assert alarm_state(rig, "pressure_high") == "off"
    set_pressure(rig, None)
    await rig.advance(58 * MINUTE, step=60.0)
    high = rig.state("binary_sensor", "alarm_pressure_high")
    assert high.state == "off"
    assert high.attributes["reason"] == "held"
    await rig.advance(3 * MINUTE, step=60.0)
    assert alarm_state(rig, "pressure_high") == "unknown"
    assert alarm_state(rig, "pressure_low") == "unknown"


# --- the notifications (decision 7) --------------------------------------------------------------


async def test_notifications_open_after_five_minutes_and_close_after_an_hour_in_range(
    rig: Rig,
) -> None:
    """2.9 bar for five minutes: the issue ``pressure_high``, saying what to do. Back at 2.3 bar
    it is still open at 58 minutes and gone after an hour; the alarm itself clears at once.
    Negative: an unknown value keeps an open one open, however long."""
    await set_up(rig, add_entry(rig, with_pressure(rig, 1.5)))
    await rig.advance(60)
    set_pressure(rig, 2.9)
    await rig.advance(4 * MINUTE)
    assert issue(rig, "pressure_high") is None  # the warning at once, not the notification
    assert rig.state("binary_sensor", "alarm_pressure_high").attributes["level"] == "warning"
    await rig.advance(90)
    found = issue(rig, "pressure_high")
    assert found is not None
    assert found.translation_placeholders == {"value": "2.90", "limit": "2.8"}
    assert found.severity is ir.IssueSeverity.WARNING
    set_pressure(rig, 2.3)
    await rig.advance(58 * MINUTE, step=60.0)
    assert alarm_state(rig, "pressure_high") == "off"
    open_ = issue(rig, "pressure_high")
    assert open_ is not None  # still open, and what it says is what raised it
    assert open_.translation_placeholders == {"value": "2.90", "limit": "2.8"}
    await rig.advance(3 * MINUTE, step=60.0)
    assert issue(rig, "pressure_high") is None
    set_pressure(rig, 2.9)
    await rig.advance(6 * MINUTE)
    assert issue(rig, "pressure_high") is not None
    set_pressure(rig, None)
    await rig.advance(3 * 3600, step=300.0)
    assert issue(rig, "pressure_high") is not None  # unknown keeps it open


async def test_a_reload_keeps_an_open_notification_and_its_rule(rig: Rig) -> None:
    """A reload does not remove a notification; the new run closes it by its rule."""
    await set_up(rig, add_entry(rig, with_pressure(rig, 2.9)))
    await rig.advance(6 * MINUTE)
    assert issue(rig, "pressure_high") is not None
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert issue(rig, "pressure_high") is not None
    set_pressure(rig, 2.0)
    await rig.advance(62 * MINUTE, step=60.0)
    assert issue(rig, "pressure_high") is None


async def test_flue_gas_notification_counts_during_hot_water(rig: Rig) -> None:
    """Hot flue gas informs with its notification, hot-water draws included (no hot-water
    filter): 105 °C for five minutes while hot water runs."""
    rig.boiler = FakeBoiler(rig.hass, (*SIGNALS, Signal.FLUE_GAS))
    rig.hass.states.async_set(FLUE_GAS, "60", {"unit_of_measurement": "°C"})
    entry_options = options(rig.zones)
    entry_options["signals"][Signal.FLUE_GAS.value] = FLUE_GAS
    await set_up(rig, add_entry(rig, entry_options))
    await rig.advance(60)
    rig.dhw = True
    rig.hass.states.async_set(FLUE_GAS, "105", {"unit_of_measurement": "°C"})
    await rig.advance(6 * MINUTE)
    found = issue(rig, "flue_gas_high")
    assert found is not None
    assert found.translation_placeholders == {"value": "105", "limit": "100"}
    assert unit_of(rig).status.alarms == frozenset()


async def test_without_a_threshold_there_is_no_add_water(rig: Rig) -> None:
    """Negative: without the "add water" threshold no low-pressure alarm exists, however low the
    pressure, and no notification opens; the feature names what it lacks."""
    await set_up(rig, add_entry(rig, with_pressure(rig, 0.3)))
    await rig.advance(10 * MINUTE)
    assert rig.entry is not None
    key = f"{rig.entry.entry_id}_alarm_pressure_low"
    assert er.async_get(rig.hass).async_get_entity_id("binary_sensor", DOMAIN, key) is None
    assert issue(rig, "add_water") is None
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature

    state = rig.entry.runtime_data.data.features[Feature.ADD_WATER]
    assert state.reason == "no_threshold"


# --- boiler protection: the boiler's own fault -------------------------------------------------


def with_fault(rig: Rig, **extra: Any) -> dict[str, Any]:
    """Options with the boiler's own low-water-pressure fault mapped (``extra``: more signals);
    the fault reads off."""
    rig.hass.states.async_set(LOW_WATER, "off")
    entry_options = options(rig.zones)
    entry_options["signals"][Signal.LOW_PRESSURE_FAULT.value] = LOW_WATER
    entry_options["signals"] |= extra
    return entry_options


async def test_a_boiler_fault_switches_heating_off_without_a_hand_back(rig: Rig) -> None:
    """The boiler reports its low-water-pressure fault for five minutes: control sends its usual
    "off" (the gateway's CH=0), with no hand-back and no latch, and the notification names the
    fault. The fault gone unavailable: heating on again in the same step, the notification
    gone."""
    await set_up(rig, add_entry(rig, with_fault(rig)))
    await rig.switch(True)
    await rig.advance(30)
    assert rig.gateway.calls[-1] == ("ch", True) or rig.gateway.setpoints()[-1] == EXPECTED
    rig.hass.states.async_set(LOW_WATER, "on")
    await rig.advance(4 * MINUTE)
    assert ("ch", False) not in rig.gateway.calls  # four minutes: nothing yet
    await rig.advance(90)
    assert ("ch", False) in rig.gateway.calls
    assert ("setpoint", 0.0) not in rig.gateway.calls  # no hand-back
    state = rig.state("sensor", "control_state")
    assert state.state == "boiler_fault"
    assert state.attributes["latched_by"] == []
    found = issue(rig, "boiler_fault")
    assert found is not None
    assert LOW_WATER in found.translation_placeholders["entity"]
    count = len(rig.gateway.calls)
    rig.hass.states.async_set(LOW_WATER, "unavailable")  # unknown counts as no fault
    await rig.advance(10)
    assert ("ch", True) in rig.gateway.calls[count:]
    assert rig.state("sensor", "control_state").state == "heating"
    await rig.advance(30)
    assert issue(rig, "boiler_fault") is None


@pytest.mark.parametrize("gate", [None, "off", "unknown", "on"])
async def test_a_gateway_fault_flag_counts_only_with_the_fault_indication_on(
    rig: Rig, gate: str | None
) -> None:
    """Q3.9: the gateway's "Low water pressure" (registered by ``opentherm_gw``) may be stale —
    the gateway reads it once per new fault and never after it clears. It counts only while the
    boiler's fault indication reads a known "on": without that signal mapped, off or unknown,
    heating goes on."""
    register(rig, LOW_WATER, "opentherm_gw")
    extra: dict[str, str] = {}
    if gate is not None:
        register(rig, FAULT_INDICATION, "opentherm_gw")
        rig.hass.states.async_set(FAULT_INDICATION, gate)
        extra[Signal.FAULT_INDICATION.value] = FAULT_INDICATION
    await set_up(rig, add_entry(rig, with_fault(rig, **extra)))
    await rig.switch(True)
    await rig.advance(30)
    rig.hass.states.async_set(LOW_WATER, "on")
    await rig.advance(6 * MINUTE)
    stopped = ("ch", False) in rig.gateway.calls
    assert stopped is (gate == "on")
    assert ("setpoint", 0.0) not in rig.gateway.calls
    assert (issue(rig, "boiler_fault") is not None) is (gate == "on")


async def test_the_gateways_fault_indication_picked_as_the_lockout_counts_alone(
    rig: Rig,
) -> None:
    """The user picked the gateway's boiler "Fault indication" (OpenTherm ID 0, fresh in every
    status report) as the lockout: it is the indication itself and counts without a gate."""
    register(rig, FAULT_INDICATION, "opentherm_gw", unique_id="gw-boiler-slave_fault_indication")
    rig.hass.states.async_set(FAULT_INDICATION, "off")
    entry_options = options(rig.zones)
    entry_options["signals"][Signal.BOILER_LOCKOUT.value] = FAULT_INDICATION
    await set_up(rig, add_entry(rig, entry_options))
    await rig.switch(True)
    await rig.advance(30)
    rig.hass.states.async_set(FAULT_INDICATION, "on")
    await rig.advance(6 * MINUTE)
    assert ("ch", False) in rig.gateway.calls
    assert rig.state("sensor", "control_state").state == "boiler_fault"


async def test_the_fault_notification_opens_without_control(rig: Rig) -> None:
    """Without control configured nothing is written, but the notification still opens."""
    entry_options = with_fault(rig)
    del entry_options["control"]
    await set_up(rig, add_entry(rig, entry_options))
    rig.hass.states.async_set(LOW_WATER, "on")
    await rig.advance(6 * MINUTE)
    assert issue(rig, "boiler_fault") is not None
    assert rig.gateway.calls == []
    rig.hass.states.async_set(LOW_WATER, "off")
    await rig.advance(60)
    assert issue(rig, "boiler_fault") is None


# --- decision 7: a repair issue for every hand-back or latch -----------------------------------


def hand_back_issues(rig: Rig) -> set[str]:
    """This entry's issues about control stopping: the latch, the hand-backs, the blockers."""
    assert rig.entry is not None
    suffix = f"_{rig.entry.entry_id}"
    found = set()
    for domain, issue_id in ir.async_get(rig.hass).issues:
        if domain != DOMAIN or not issue_id.endswith(suffix):
            continue
        key = issue_id.removesuffix(suffix)
        if key.startswith(("control_latched", "hand_back_", "monitor_", "control_stopped")):
            found.add(key)
    return found


@pytest.mark.parametrize(
    ("topology", "severity"),
    [
        ("gateway_standalone", ir.IssueSeverity.ERROR),
        ("gateway_with_thermostat", ir.IssueSeverity.WARNING),
    ],
)
async def test_a_step_aside_names_the_target_and_the_value_seen(
    rig: Rig, topology: str, severity: ir.IssueSeverity
) -> None:
    """A latch by another controller raises the entry's one latch issue, naming the target
    whose read-back showed the other value and that value (Q1's matrix, M8) — an error where
    the hand-back stops heating, else a warning — and no other issue for the same cause."""
    await start(rig, topology=topology)
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.forced = 60.0
    await rig.advance(200)
    assert rig.state("sensor", "control_state").state == "handed_back"
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched"
    assert found.translation_placeholders == {"target": CONFIRMED, "value": "60.0 °C"}
    assert found.severity is severity
    assert hand_back_issues(rig) == {"control_latched"}


async def test_an_ignored_write_set_to_hand_back_latches_with_its_issue(rig: Rig) -> None:
    """Decision 7's one optional reaction: with a thermostat to take over and the reaction set
    to hand back, a setpoint the boiler never takes latches control — the latch issue names the
    ignored write, a warning (the thermostat heats). Negative: stand-alone the same stored
    reaction only informs — control goes on, no issue."""
    rig.gateway.echo = False
    await start(rig, alarm_reactions={"write_ignored": "hand_back"})
    await rig.advance(310)  # past the five minutes the unit's own start counts as a trace
    await rig.switch(True)
    await rig.advance(400)
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["write_ignored"]
    found = issue(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_write_ignored"
    assert found.severity is ir.IssueSeverity.WARNING
    assert hand_back_issues(rig) == {"control_latched"}
    await rig.switch(False)
    assert issue(rig, "control_latched") is None  # the latch clears with off, then on


async def test_an_ignored_write_stand_alone_only_informs(rig: Rig) -> None:
    rig.gateway.echo = False
    await start(rig, topology="gateway_standalone", alarm_reactions={"write_ignored": "hand_back"})
    await rig.advance(310)
    await rig.switch(True)
    await rig.advance(400)
    assert alarm_state(rig, "write_ignored") == "on"
    assert rig.state("sensor", "control_state").state == "heating"
    assert issue(rig, "control_latched") is None


async def test_a_lost_link_hand_back_raises_its_issue_until_control_resumes(rig: Rig) -> None:
    """The lost boiler link hands back without a latch: its issue, ``hand_back_boiler_link_lost``
    — an error stand-alone — and it goes once control resumes by itself."""
    await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    await rig.advance(30)
    rig.flow = None
    await rig.advance(310)
    assert rig.gateway.calls[-3:] == HAND_BACK
    found = issue(rig, "hand_back_boiler_link_lost")
    assert found is not None
    assert found.severity is ir.IssueSeverity.ERROR
    assert hand_back_issues(rig) == {"hand_back_boiler_link_lost"}
    rig.flow = 35.0
    await rig.advance(80)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # control resumed by itself
    assert issue(rig, "hand_back_boiler_link_lost") is None


async def test_an_internal_error_raises_its_issue_until_switched_off_and_on(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An internal error hands back: its issue ``hand_back_control_error``, a warning where the
    thermostat takes over; it goes when the user switches control off."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    original = type(unit)._async_step

    async def broken(self: Any, now: float) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(type(unit), "_async_step", broken)
    await rig.advance(10)
    found = issue(rig, "hand_back_control_error")
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING
    assert hand_back_issues(rig) == {"hand_back_control_error"}
    monkeypatch.setattr(type(unit), "_async_step", original)
    await rig.switch(False)
    assert issue(rig, "hand_back_control_error") is None


async def test_the_monitor_failing_raises_only_its_own_issue(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The monitor failing for five minutes hands back with V6's issue alone — never a second
    one for the same cause."""
    from .test_control import break_monitor

    await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    await rig.advance(20)
    breaker = break_monitor(monkeypatch)
    breaker.failing = True
    await rig.advance(330)
    assert "monitor_failed" in blockers(rig)
    assert hand_back_issues(rig) == {"monitor_failed"}


async def test_an_allow_listed_alarm_active_at_switch_on_blocks_control_at_once(
    rig: Rig,
) -> None:
    """Decision 7 (X2's alarm, Y1's text): switched on while the boiler link is lost, control
    does not start writing — handed back at once, with no latch, and the switch names the alarm
    (``blocked_by``); it takes the boiler by itself once the link has been fresh for a minute."""
    await start(rig)
    rig.flow = None
    await rig.advance(320)
    await rig.switch(True)
    await rig.advance(10)
    assert rig.gateway.calls == []
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == []
    switch = rig.state("switch", "control")
    assert switch.attributes["blocked_by"] == ["boiler_link_lost"]
    assert alarm_state(rig, "boiler_link_lost") == "on"
    rig.flow = 35.0
    await rig.advance(80)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    assert rig.state("switch", "control").attributes["blocked_by"] == []


# --- T-21 (P-22): hot-water draws with the named heating echo ----------------------------------


async def test_hot_water_draws_with_the_named_ch_echo_raise_no_outside_change(rig: Rig) -> None:
    """T-21's integration part: the heating echo taken from the boiler device's "Central
    heating 1" that shows what the gateway sends (On/Off) stays on through hot-water draws —
    two ten-minute draws raise no outside change, no ignored write and no latch."""
    await start(rig, ch_confirmed_entity=CH_ECHO)
    await rig.switch(True)
    await rig.advance(60)
    for _ in range(2):
        rig.dhw = True
        await rig.advance(600)
        rig.dhw = False
        await rig.advance(300)
    assert alarm_state(rig, "outside_change") == "off"
    assert alarm_state(rig, "write_ignored") == "off"
    state = rig.state("sensor", "control_state")
    assert state.attributes["latched_by"] == []
    assert state.state == "heating"
    assert ("setpoint", 0.0) not in rig.gateway.calls
