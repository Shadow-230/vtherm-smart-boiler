"""Writers: the service calls each write path makes, refused values and failures."""

from __future__ import annotations

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
from custom_components.vtherm_smart_boiler.transport.writers import (
    EntityWriter,
    OpenthermGwWriter,
    OtgwMqttWriter,
    WriteError,
    make_writer,
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
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "0"}),
    ]
    assert writer.services == {("mqtt", "publish")}


async def test_entity_writer_with_value_hand_back(hass: HomeAssistant) -> None:
    calls = record(hass, ("number", "set_value"), ("switch", "turn_on"), ("switch", "turn_off"))
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            ch_entity="switch.ch",
            hand_back="value",
            hand_back_value=0,
        ),
    )
    assert isinstance(writer, EntityWriter)
    await writer.write_setpoint(41.0)
    await writer.write_heating(True)
    await writer.hand_back()
    assert calls == [
        ("number", "set_value", {"entity_id": "number.flow", "value": 41.0}),
        ("switch", "turn_on", {"entity_id": "switch.ch"}),
        ("number", "set_value", {"entity_id": "number.flow", "value": 0.0}),
    ]
    assert writer.services == {
        ("number", "set_value"),
        ("switch", "turn_on"),
        ("switch", "turn_off"),
    }


async def test_entity_writer_switch_and_timeout_hand_back(hass: HomeAssistant) -> None:
    calls = record(
        hass,
        ("input_number", "set_value"),
        ("input_boolean", "turn_off"),
        ("input_boolean", "turn_on"),
    )
    switch = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="input_number.flow",
            hand_back="switch",
            hand_back_entity="input_boolean.external_control",
        ),
    )
    await switch.hand_back()
    assert calls == [("input_boolean", "turn_off", {"entity_id": "input_boolean.external_control"})]
    with pytest.raises(WriteError, match="no heating switch"):
        await switch.write_heating(True)
    timeout = make_writer(
        hass, options(write_path="entity", setpoint_entity="input_number.flow", hand_back="timeout")
    )
    await timeout.hand_back()
    assert len(calls) == 1  # nothing written: the device's timeout hands back


async def test_a_failing_service_is_a_write_error(hass: HomeAssistant) -> None:
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    with pytest.raises(WriteError, match="set_control_setpoint"):
        await writer.write_setpoint(45.0)  # the service does not exist


async def test_unconfigured_control_has_no_writer(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError, match="not configured"):
        make_writer(hass, options())
