"""Writers: the service calls each write path makes, refused values and failures."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.vtherm_smart_boiler.control_config import parse_control
from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    Installation,
)
from custom_components.vtherm_smart_boiler.transport import writers
from custom_components.vtherm_smart_boiler.transport.writers import (
    EntityWriter,
    HandBackCheck,
    OpenthermGwWriter,
    OtgwMqttWriter,
    WriteError,
    make_writer,
    writer_services,
)

INSTALLATION = Installation(Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),))


def record(
    hass: HomeAssistant, *services: tuple[str, str]
) -> list[tuple[str, str, dict[str, Any]]]:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    for domain, service in services:

        async def handle(call: ServiceCall, domain=domain, service=service) -> None:
            calls.append((domain, service, dict(call.data)))

        hass.services.async_register(domain, service, handle)
    return calls


def options(**data: Any):
    return parse_control(data, INSTALLATION, None)


def present(hass: HomeAssistant, *entities: str) -> None:
    """The targets exist and are available, as a device's entities are while it is online."""
    for entity in entities:
        on_off = entity.split(".", 1)[0] in ("switch", "input_boolean")
        hass.states.async_set(entity, "on" if on_off else "40")


async def test_opentherm_gw_writer(hass: HomeAssistant) -> None:
    calls = record(
        hass, ("opentherm_gw", "set_control_setpoint"), ("opentherm_gw", "set_central_heating_ovrd")
    )
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    assert isinstance(writer, OpenthermGwWriter)
    await writer.write_setpoint(45.04)
    await writer.write_heating(False)
    await writer.hand_back()
    assert calls == [
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 45.0}),
        ("opentherm_gw", "set_central_heating_ovrd", {"gateway_id": "gw1", "ch_override": False}),
        # The gateway keeps a CH=0 through CS=0 (PIC 6.6): CH=1 first, then the setpoint.
        ("opentherm_gw", "set_central_heating_ovrd", {"gateway_id": "gw1", "ch_override": True}),
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 0}),
    ]
    assert writer.services == {
        ("opentherm_gw", "set_control_setpoint"),
        ("opentherm_gw", "set_central_heating_ovrd"),
    }


@pytest.mark.parametrize("value", [5.0, 0.5, 7.9, 95.0, float("nan")])
async def test_otgw_refuses_setpoints_that_never_lapse_or_are_implausible(
    hass: HomeAssistant, value: float
) -> None:
    calls = record(hass, ("opentherm_gw", "set_control_setpoint"))
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    with pytest.raises(WriteError):
        await writer.write_setpoint(value)
    assert calls == []


async def test_mqtt_writer(hass: HomeAssistant) -> None:
    calls = record(hass, ("mqtt", "publish"))
    writer = make_writer(
        hass, options(write_path="otgw_mqtt", mqtt_top="OTGW/", mqtt_node="otgw-1")
    )
    assert isinstance(writer, OtgwMqttWriter)
    await writer.write_setpoint(38.26)
    await writer.write_heating(True)
    await writer.hand_back()
    assert calls == [
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "38.3"}),
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/chenable", "payload": "1"}),
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/chenable", "payload": "1"}),
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "0"}),
    ]
    assert writer.services == {("mqtt", "publish")}


async def test_entity_writer_with_value_hand_back(hass: HomeAssistant) -> None:
    calls = record(hass, ("number", "set_value"), ("switch", "turn_on"), ("switch", "turn_off"))
    present(hass, "number.flow", "switch.ch")
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            ch_entity="switch.ch",
            write_type="expiring",
            ch_write_type="expiring",
            hand_back="value",
            hand_back_value=0,
            hand_back_value_effect="own_control",
        ),
    )
    assert isinstance(writer, EntityWriter)
    await writer.write_setpoint(41.0)
    await writer.write_heating(False)
    checks = await writer.hand_back()
    # Done only once each target shows it: the switch on, the setpoint at the hand-back value.
    assert checks == (HandBackCheck("switch.ch", "on"), HandBackCheck("number.flow", 0.0))
    ch = {"entity_id": "switch.ch"}
    assert calls == [
        ("number", "set_value", {"entity_id": "number.flow", "value": 41.0}),
        ("switch", "turn_off", ch),
        ("switch", "turn_on", ch),  # the heating override is cleared: the boiler heats itself
        ("number", "set_value", {"entity_id": "number.flow", "value": 0.0}),
    ]
    assert writer.services == {
        ("number", "set_value"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
    }
    calls.clear()
    await writer.write_setpoint(42.0)
    await writer.hand_back()  # the switch was not touched this session: left alone
    assert ("switch", "turn_on", ch) not in calls


@pytest.mark.parametrize("ch_write_type", ["persistent", "unknown"])
async def test_a_heating_switch_the_boiler_may_store_is_left_alone(
    hass: HomeAssistant, ch_write_type: str
) -> None:
    data = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "ch_entity": "switch.ch",
        "write_type": "expiring",
        "ch_write_type": ch_write_type,
        "hand_back": "value",
        "hand_back_value": 0,
    }
    assert writer_services(options(**data)) == {("number", "set_value")}


async def test_entity_writer_switch_and_timeout_hand_back(hass: HomeAssistant) -> None:
    calls = record(
        hass,
        ("input_number", "set_value"),
        ("input_boolean", "turn_off"),
        ("input_boolean", "turn_on"),
    )
    present(hass, "input_number.flow", "input_boolean.external_control")
    switch = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="input_number.flow",
            hand_back="switch",
            hand_back_entity="input_boolean.external_control",
        ),
    )
    external = {"entity_id": "input_boolean.external_control"}
    await switch.write_setpoint(40.0)
    await switch.write_setpoint(41.0)
    assert await switch.hand_back() == (HandBackCheck("input_boolean.external_control", "off"),)
    await switch.write_setpoint(42.0)
    assert calls == [
        ("input_boolean", "turn_on", external),  # control is taken once per session
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": 40.0}),
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": 41.0}),
        ("input_boolean", "turn_off", external),
        ("input_boolean", "turn_on", external),
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": 42.0}),
    ]
    assert switch.services == {
        ("input_number", "set_value"),
        ("input_boolean", "turn_on"),
        ("input_boolean", "turn_off"),
    }
    with pytest.raises(WriteError, match="no heating switch"):
        await switch.write_heating(True)
    calls.clear()
    timeout = make_writer(
        hass, options(write_path="entity", setpoint_entity="input_number.flow", hand_back="timeout")
    )
    assert await timeout.hand_back() == ()
    assert calls == []  # nothing written: the device's timeout hands back
    assert timeout.services == {("input_number", "set_value")}


async def test_a_value_hand_back_ignores_a_hand_back_switch(hass: HomeAssistant) -> None:
    services = writer_services(
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            hand_back="value",
            hand_back_entity="switch.unused",
        )
    )
    assert services == {("number", "set_value")}


async def test_a_hanging_service_times_out(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang(call: ServiceCall) -> None:
        await asyncio.sleep(3600)

    hass.services.async_register("opentherm_gw", "set_control_setpoint", hang)
    monkeypatch.setattr(writers, "WRITE_TIMEOUT_S", 0.05)
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    with pytest.raises(WriteError, match="set_control_setpoint"):
        await writer.write_setpoint(45.0)


async def test_a_failing_service_is_a_write_error(hass: HomeAssistant) -> None:
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    with pytest.raises(WriteError, match="set_control_setpoint"):
        await writer.write_setpoint(45.0)  # the service does not exist


async def test_unconfigured_control_has_no_writer(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError, match="not configured"):
        make_writer(hass, options())
    assert writer_services(options()) == frozenset()


async def test_each_hand_back_step_is_tried_whatever_the_others_do(hass: HomeAssistant) -> None:
    calls = record(hass, ("number", "set_value"))  # the heating switch's service is missing
    present(hass, "number.flow", "switch.ch")
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            ch_entity="switch.ch",
            write_type="expiring",
            ch_write_type="expiring",
            hand_back="value",
            hand_back_value=0,
        ),
    )
    with pytest.raises(WriteError, match=r"switch\.turn_on"):
        await writer.hand_back(full=True)
    assert calls == [("number", "set_value", {"entity_id": "number.flow", "value": 0.0})]


@pytest.mark.parametrize("state", [None, "unavailable", "unknown"])
async def test_a_missing_or_unavailable_target_is_a_failure(
    hass: HomeAssistant, state: str | None
) -> None:
    """Home Assistant skips an unavailable entity without an error, and a missing one with a log
    line only: the writer must not take such a call for a write that went through."""
    calls = record(hass, ("number", "set_value"), ("switch", "turn_on"), ("switch", "turn_off"))
    present(hass, "switch.ch")
    if state is not None:
        hass.states.async_set("number.flow", state)
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            ch_entity="switch.ch",
            write_type="held",
            ch_write_type="held",
            hand_back="value",
            hand_back_value=0,
            hand_back_value_effect="own_control",
        ),
    )
    with pytest.raises(WriteError, match=r"number\.flow"):
        await writer.write_setpoint(41.0)
    await writer.write_heating(True)  # the switch is there
    with pytest.raises(WriteError, match=r"number\.flow"):
        await writer.hand_back()
    assert ("number", "set_value") not in {(d, s) for d, s, _ in calls}
    hass.states.async_set("switch.ch", "unavailable")
    with pytest.raises(WriteError, match=r"switch\.ch"):
        await writer.write_heating(False)


async def test_an_otgw_hand_back_tries_both_steps(hass: HomeAssistant) -> None:
    """CH=1 and CS=0 are each tried whatever the other does; a failure is raised at the end."""
    calls = record(hass, ("opentherm_gw", "set_control_setpoint"))  # CH's service is missing
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    with pytest.raises(WriteError, match="set_central_heating_ovrd"):
        await writer.hand_back()
    assert calls == [
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 0})
    ]


@pytest.mark.parametrize(
    ("attributes", "written"),
    [
        ({"unit_of_measurement": "°F", "step": 1, "min": 50, "max": 190}, 113.0),
        ({"unit_of_measurement": "°C", "step": 1, "min": 20, "max": 80}, 46.0),
        ({"unit_of_measurement": "°C", "step": 0.5, "min": 20, "max": 80}, 45.5),
        ({"unit_of_measurement": "°C"}, 45.6),
    ],
)
async def test_the_setpoint_goes_in_the_entitys_unit_and_step(
    hass: HomeAssistant, attributes: dict[str, Any], written: float
) -> None:
    """P11, P87: a number takes its value in its own unit, rounded to its step — else 45 °C
    would reach a °F boiler as 7 °C, and an unrounded value would read back as ignored."""
    calls = record(hass, ("number", "set_value"))
    hass.states.async_set("number.flow", "40", attributes)
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            write_type="held",
            hand_back="value",
            hand_back_value=0,
            hand_back_value_effect="own_control",
        ),
    )
    await writer.write_setpoint(45.6 if written != 113.0 else 45.0)
    assert calls[-1][2]["value"] == pytest.approx(written)


async def test_a_setpoint_entity_in_an_unknown_unit_is_not_written(hass: HomeAssistant) -> None:
    calls = record(hass, ("number", "set_value"))
    hass.states.async_set("number.flow", "40", {"unit_of_measurement": "furlong"})
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            write_type="held",
            hand_back="value",
            hand_back_value=0,
            hand_back_value_effect="own_control",
        ),
    )
    with pytest.raises(WriteError, match="unit"):
        await writer.write_setpoint(45.0)
    assert calls == []


async def test_the_hand_back_value_goes_in_the_entitys_unit(hass: HomeAssistant) -> None:
    calls = record(hass, ("number", "set_value"))
    hass.states.async_set("number.flow", "104", {"unit_of_measurement": "°F", "step": 1})
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            write_type="held",
            hand_back="value",
            hand_back_value=40,
            hand_back_value_effect="own_control",
        ),
    )
    checks = await writer.hand_back()
    assert calls[-1][2]["value"] == pytest.approx(104.0)
    assert checks == (HandBackCheck("number.flow", 40.0),)  # read back in °C
