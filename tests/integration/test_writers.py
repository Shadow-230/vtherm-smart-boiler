"""Writers: the service calls each write path makes, refused values and failures."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.vtherm_smart_boiler.control_config import parse_control
from custom_components.vtherm_smart_boiler.core.hand_back import CheckKind, CheckSource
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
    HandBackFailed,
    OpenthermGwWriter,
    OtgwMqttWriter,
    WriteError,
    make_writer,
    writer_services,
)

INSTALLATION = Installation(Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),))
READ_BACK = "sensor.gw_control_setpoint"
LOWEST = 20.0  # the lowest water temperature set: its default (decision 2)
GATEWAYS = {
    "opentherm_gw": {"write_path": "opentherm_gw", "gateway_id": "gw1"},
    "otgw_mqtt": {"write_path": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw-1"},
}
GATEWAY_SERVICES = (
    ("opentherm_gw", "set_control_setpoint"),
    ("opentherm_gw", "set_central_heating_ovrd"),
    ("mqtt", "publish"),
)


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
    hass.states.async_set(READ_BACK, "45.0", {"unit_of_measurement": "°C"})
    writer = make_writer(
        hass, options(write_path="opentherm_gw", gateway_id="gw1", confirmed_entity=READ_BACK)
    )
    assert isinstance(writer, OpenthermGwWriter)
    await writer.write_setpoint(45.04)
    await writer.write_heating(False)
    await writer.hand_back()
    assert calls == [
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 45.0}),
        ("opentherm_gw", "set_central_heating_ovrd", {"gateway_id": "gw1", "ch_override": False}),
        # The safe hand-back: the lowest water temperature, then CH=1 — the gateway keeps a
        # CH=0 through CS=0 (PIC 6.6) — then the release.
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": LOWEST}),
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
    hass.states.async_set(READ_BACK, "38.3", {"unit_of_measurement": "°C"})
    writer = make_writer(
        hass,
        options(
            write_path="otgw_mqtt",
            mqtt_top="OTGW/",
            mqtt_node="otgw-1",
            confirmed_entity=READ_BACK,
        ),
    )
    assert isinstance(writer, OtgwMqttWriter)
    await writer.write_setpoint(38.26)
    await writer.write_heating(True)
    await writer.hand_back()
    assert calls == [
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "38.3"}),
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/chenable", "payload": "1"}),
        ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "20.0"}),
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
    checks = await writer.hand_back(release_from=41.0)
    # Done only once each target shows it: the switch on, the setpoint at the hand-back value
    # or — expiring — away from the plugin's value and the lowest. No read-back but the
    # written entities themselves: unverified.
    assert checks == (
        HandBackCheck("switch.ch", "on", CheckKind.SWITCH, CheckSource.SELF),
        HandBackCheck(
            "number.flow",
            0.0,
            CheckKind.LEAVES_VALUE,
            CheckSource.SELF,
            release_from=41.0,
            lowest=LOWEST,
        ),
    )
    ch = {"entity_id": "switch.ch"}
    assert calls == [
        ("number", "set_value", {"entity_id": "number.flow", "value": 41.0}),
        ("switch", "turn_off", ch),
        ("number", "set_value", {"entity_id": "number.flow", "value": LOWEST}),  # the lowest
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
    await writer.hand_back()  # untouched this session: on all the same, as the effect says (S-27)
    assert ("switch", "turn_on", ch) in calls


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
    assert await switch.hand_back() == (
        HandBackCheck("input_boolean.external_control", "off", CheckKind.SWITCH, CheckSource.SELF),
    )
    await switch.write_setpoint(42.0)
    assert calls == [
        ("input_boolean", "turn_on", external),  # control is taken once per session
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": 40.0}),
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": 41.0}),
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": LOWEST}),
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
    [check] = await timeout.hand_back(baseline=45.0)
    assert check.kind is CheckKind.BACK_TO_BASELINE
    assert check.baseline == 45.0
    # Only the lowest: the device's own timeout hands back.
    assert calls == [
        ("input_number", "set_value", {"entity_id": "input_number.flow", "value": LOWEST})
    ]
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
        await writer.hand_back()
    assert calls == [
        ("number", "set_value", {"entity_id": "number.flow", "value": LOWEST}),
        ("number", "set_value", {"entity_id": "number.flow", "value": 0.0}),
    ]


@pytest.mark.parametrize("state", [None, "unavailable"])
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


async def test_a_target_without_a_value_yet_is_written(hass: HomeAssistant) -> None:
    """An entity whose state is unknown is available, only without a value (never written, or
    its device not heard yet): Home Assistant calls it, so the writer does too — and a
    hand-back is never held back for it. Whether it took the value is the read-back's job."""
    calls = record(hass, ("number", "set_value"), ("switch", "turn_on"), ("switch", "turn_off"))
    hass.states.async_set("number.flow", "unknown", {"unit_of_measurement": "°C", "step": 0.5})
    hass.states.async_set("switch.ch", "unknown")
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
    await writer.write_setpoint(41.0)
    await writer.write_heating(True)
    await writer.hand_back()
    assert ("number", "set_value", {"entity_id": "number.flow", "value": 41.0}) in calls
    assert ("switch", "turn_on", {"entity_id": "switch.ch"}) in calls
    assert ("number", "set_value", {"entity_id": "number.flow", "value": 0.0}) in calls


async def test_an_otgw_hand_back_tries_every_part(hass: HomeAssistant) -> None:
    """CS=<lowest>, CH=1 and CS=0 are each tried whatever the others do; a failure is raised
    at the end."""
    calls = record(hass, ("opentherm_gw", "set_control_setpoint"))  # CH's service is missing
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    with pytest.raises(WriteError, match="set_central_heating_ovrd"):
        await writer.hand_back()
    assert calls == [
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": LOWEST}),
        ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 0}),
    ]


@pytest.mark.parametrize(
    ("attributes", "value", "written"),
    [
        ({"unit_of_measurement": "°F", "step": 1, "min": 50, "max": 190}, 45.0, 113.0),
        ({"unit_of_measurement": "°F", "step": 1, "min": 50, "max": 190}, (114 - 32) / 1.8, 114.0),
        ({"unit_of_measurement": "°C", "step": 1, "min": 20, "max": 80}, 46.0, 46.0),
        ({"unit_of_measurement": "°C", "step": 0.5, "min": 0.25, "max": 80}, 69.75, 69.75),
        ({"unit_of_measurement": "°C"}, 45.6, 45.6),
    ],
)
async def test_the_setpoint_goes_in_the_entitys_unit_and_step(
    hass: HomeAssistant, attributes: dict[str, Any], value: float, written: float
) -> None:
    """P11, P87, P-15: a number takes its value in its own unit — else 45 °C would reach a °F
    boiler as 7 °C — on its grid, where the loop put it inside the limits; the writer no longer
    rounds, so what the guard compares is what the device gets."""
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
    await writer.write_setpoint(value)
    assert calls[-1][2]["value"] == pytest.approx(written)


@pytest.mark.parametrize(
    ("attributes", "value"),
    [
        ({"unit_of_measurement": "°C", "step": 1, "min": 20, "max": 80}, 45.6),  # off its grid
        ({"unit_of_measurement": "°C", "step": 0.5, "min": 0.25, "max": 80}, 70.0),
        ({"unit_of_measurement": "°C", "step": 0.5, "min": 20, "max": 60}, 65.0),  # above max
        ({"unit_of_measurement": "°C", "min": 30}, 25.0),  # below min
    ],
)
async def test_a_value_off_the_entitys_grid_or_range_is_refused(
    hass: HomeAssistant, attributes: dict[str, Any], value: float
) -> None:
    """P-15, P-98: a value not on the entity's grid, or outside its ``min`` and ``max``, is a
    failed write — sent again at the next step, never rounded past the limits here."""
    calls = record(hass, ("number", "set_value"))
    hass.states.async_set("number.flow", "40", attributes)
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
    with pytest.raises(WriteError):
        await writer.write_setpoint(value)
    assert calls == []


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
    [check] = await writer.hand_back()
    # The lowest water temperature (20 °C = 68 °F), then the hand-back value (40 °C = 104 °F).
    assert [call[2]["value"] for call in calls] == [pytest.approx(68.0), pytest.approx(104.0)]
    assert check.expected == 40.0  # read back in °C
    assert check.kind is CheckKind.VALUE  # held


# --- V4: a gateway's hand-back is judged by its read-back; cancels and caps -------------------


@pytest.mark.parametrize("path", list(GATEWAYS))
@pytest.mark.parametrize("release_from", [45.0, None], ids=["known", "unknown"])
async def test_a_gateway_hand_back_is_judged_by_its_read_back(
    hass: HomeAssistant, path: str, release_from: float | None
) -> None:
    """R7 (Open after R6 #8): a service's normal return proves nothing — pyotgw returns after a
    timeout, and an MQTT publish once written to the socket. The hand-back returns a check on
    the gateway's setpoint read-back: released once it leaves the value the plugin wrote (the
    caller's; unknown: a value reported after the command, judged from the state before it)."""
    calls = record(hass, *GATEWAY_SERVICES)
    hass.states.async_set(READ_BACK, "45.0", {"unit_of_measurement": "°C"})
    before = hass.states.get(READ_BACK)
    writer = make_writer(hass, options(**GATEWAYS[path], confirmed_entity=READ_BACK))
    checks = await writer.hand_back(release_from=release_from)
    assert checks == (
        HandBackCheck(
            READ_BACK,
            0.0,  # CS=0 read back
            CheckKind.LEAVES_VALUE,
            CheckSource.SEPARATE,
            release_from=release_from,
            lowest=LOWEST,
        ),
    )
    assert checks[0].before is before  # the read-back as it stood before the writes
    assert len(calls) == 3  # every part written first


@pytest.mark.parametrize("path", list(GATEWAYS))
async def test_a_gateway_hand_back_without_a_read_back_cannot_count(
    hass: HomeAssistant, path: str
) -> None:
    """Negative: without a read-back the release cannot be seen, so the hand-back fails after
    its writes, and stays owed."""
    calls = record(hass, *GATEWAY_SERVICES)
    writer = make_writer(hass, options(**GATEWAYS[path]))
    with pytest.raises(WriteError, match="read-back"):
        await writer.hand_back(release_from=45.0)
    assert len(calls) == 3  # written all the same


async def test_a_cancel_inside_a_service_is_a_failed_write(hass: HomeAssistant) -> None:
    """P-42: a service that raises CancelledError while the caller is not being cancelled (a
    task inside the integration cancelled under it) is a failed write, like any other error:
    the hand-back's other part is still tried."""
    calls: list[float] = []

    async def cancelled(call: ServiceCall) -> None:
        calls.append(call.data["temperature"])
        raise asyncio.CancelledError

    async def heating(call: ServiceCall) -> None:
        return None

    hass.services.async_register("opentherm_gw", "set_control_setpoint", cancelled)
    hass.services.async_register("opentherm_gw", "set_central_heating_ovrd", heating)
    hass.states.async_set(READ_BACK, "45.0", {"unit_of_measurement": "°C"})
    writer = make_writer(
        hass, options(write_path="opentherm_gw", gateway_id="gw1", confirmed_entity=READ_BACK)
    )
    with pytest.raises(WriteError, match="cancelled inside the service"):
        await writer.write_setpoint(45.0)
    with pytest.raises(WriteError, match="cancelled inside the service"):
        await writer.hand_back()
    assert calls == [45.0, LOWEST, 0]


async def test_a_real_cancel_passes_through_the_writer(hass: HomeAssistant) -> None:
    """Negative: the caller itself being cancelled (a stop) is not a failed write: it passes."""
    started = asyncio.Event()

    async def hang(call: ServiceCall) -> None:
        started.set()
        await asyncio.sleep(3600)

    hass.services.async_register("opentherm_gw", "set_control_setpoint", hang)
    writer = make_writer(hass, options(write_path="opentherm_gw", gateway_id="gw1"))
    task = asyncio.ensure_future(writer.write_setpoint(45.0))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("path", ["entity", *GATEWAYS])
async def test_a_hand_back_write_can_be_capped(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """R6: at a stop each hand-back write gets the cap it is given, not the usual 10 s."""

    async def hang(call: ServiceCall) -> None:
        await asyncio.sleep(3600)

    for domain, service in (*GATEWAY_SERVICES, ("number", "set_value")):
        hass.services.async_register(domain, service, hang)
    monkeypatch.setattr(writers, "WRITE_TIMEOUT_S", 3600.0)
    hass.states.async_set(READ_BACK, "45.0", {"unit_of_measurement": "°C"})
    present(hass, "number.flow")
    data = GATEWAYS.get(path) or {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": "held",
        "hand_back": "value",
        "hand_back_value": 30,
        "hand_back_value_effect": "own_control",
    }
    writer = make_writer(hass, options(**data, confirmed_entity=READ_BACK))
    async with asyncio.timeout(5.0):  # well below the usual cap, set to an hour here
        with pytest.raises(WriteError):
            await writer.hand_back(write_timeout_s=0.05)


# --- V5: the safe hand-back ---------------------------------------------------------------------

NUMBER_SERVICES = (("number", "set_value"), ("switch", "turn_on"), ("switch", "turn_off"))
ENTITY_PATH = {
    "write_path": "entity",
    "setpoint_entity": "number.flow",
    "write_type": "held",
    "ch_entity": "switch.ch",
    "ch_write_type": "held",
    "confirmed_entity": "sensor.flow_setpoint",
    "hard_min": 22.0,
}
ORDERS = {
    "opentherm_gw": (
        GATEWAYS["opentherm_gw"],
        [
            ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 22.0}),
            (
                "opentherm_gw",
                "set_central_heating_ovrd",
                {"gateway_id": "gw1", "ch_override": True},
            ),
            ("opentherm_gw", "set_control_setpoint", {"gateway_id": "gw1", "temperature": 0}),
        ],
    ),
    "otgw_mqtt": (
        GATEWAYS["otgw_mqtt"],
        [
            ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "22.0"}),
            ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/chenable", "payload": "1"}),
            ("mqtt", "publish", {"topic": "OTGW/set/otgw-1/ctrlsetpt", "payload": "0"}),
        ],
    ),
    "value_own_control": (
        ENTITY_PATH
        | {"hand_back": "value", "hand_back_value": 50, "hand_back_value_effect": "own_control"},
        [
            ("number", "set_value", {"entity_id": "number.flow", "value": 22.0}),
            ("switch", "turn_on", {"entity_id": "switch.ch"}),
            ("number", "set_value", {"entity_id": "number.flow", "value": 50.0}),
        ],
    ),
    "value_heating_stops": (
        ENTITY_PATH
        | {"hand_back": "value", "hand_back_value": 10, "hand_back_value_effect": "heating_stops"},
        [
            ("number", "set_value", {"entity_id": "number.flow", "value": 22.0}),
            ("number", "set_value", {"entity_id": "number.flow", "value": 10.0}),
        ],  # the heating switch left as it is (S-27)
    ),
    "timeout": (
        ENTITY_PATH | {"hand_back": "timeout", "write_type": "expiring", "topology": "virtual"},
        [
            ("number", "set_value", {"entity_id": "number.flow", "value": 22.0}),
            ("switch", "turn_on", {"entity_id": "switch.ch"}),
        ],  # then silence: the device's own timeout releases
    ),
    "switch": (
        ENTITY_PATH
        | {
            "hand_back": "switch",
            "hand_back_entity": "switch.external",
            "hand_back_entity_write_type": "held",
            "topology": "virtual",
        },
        [
            ("number", "set_value", {"entity_id": "number.flow", "value": 22.0}),
            ("switch", "turn_on", {"entity_id": "switch.ch"}),
            ("switch", "turn_off", {"entity_id": "switch.external"}),
        ],
    ),
}


@pytest.mark.parametrize("path", list(ORDERS))
async def test_the_hand_back_order_per_path(hass: HomeAssistant, path: str) -> None:
    """The safe hand-back (the user's decision of 2026-09-26/27): the lowest water temperature,
    heating on where the boiler returns to a thermostat or its own control (on a gateway always
    CH=1), then the release — the hand-back value, the external switch off, nothing more for
    the timeout, CS=0 on a gateway."""
    calls = record(hass, *GATEWAY_SERVICES, *NUMBER_SERVICES)
    hass.states.async_set(READ_BACK, "45.0", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.flow_setpoint", "45.0", {"unit_of_measurement": "°C"})
    present(hass, "number.flow", "switch.ch", "switch.external")
    data, order = ORDERS[path]
    writer = make_writer(hass, options(**{"confirmed_entity": READ_BACK} | data | {"hard_min": 22}))
    await writer.hand_back(release_from=45.0)
    assert calls == order


@pytest.mark.parametrize("path", list(GATEWAYS))
async def test_a_stand_alone_gateway_still_gets_ch_1_at_hand_back(
    hass: HomeAssistant, path: str
) -> None:
    """CH=1 only clears the plugin's own CH=0 flag, which the gateway would keep through CS=0 and
    mask any later demand: it is not the "heating on" a stopping hand-back leaves out (S-27).
    Stand-alone, CS=0 still leaves the boiler without demand."""
    calls = record(hass, *GATEWAY_SERVICES)
    hass.states.async_set(READ_BACK, "45.0", {"unit_of_measurement": "°C"})
    data = GATEWAYS[path] | {"topology": "gateway_standalone", "confirmed_entity": READ_BACK}
    await make_writer(hass, options(**data)).hand_back(release_from=45.0)
    heating = [c for c in calls if c[1] == "set_central_heating_ovrd" or "chenable" in str(c)]
    assert len(heating) == 1
    assert calls.index(heating[0]) == 1  # between the lowest and the release


@pytest.mark.parametrize("lowest_fails", [False, True], ids=["not_shown", "write_fails"])
async def test_the_hand_back_does_not_wait_between_its_parts(
    hass: HomeAssistant, lowest_fails: bool
) -> None:
    """The parts follow one another at once: a read-back that never shows the lowest water
    temperature — or a write of it that fails — holds up neither the heating part nor the
    release, which go out in the same attempt; the failure is raised at the end, with what the
    targets must show all the same."""
    moments: list[float] = []
    loop = asyncio.get_running_loop()

    async def handle(call: ServiceCall) -> None:
        moments.append(loop.time())
        if lowest_fails and call.data.get("value") == 22.0:
            raise HomeAssistantError("the device refused it")

    for domain, service in NUMBER_SERVICES:
        hass.services.async_register(domain, service, handle)
    hass.states.async_set("sensor.flow_setpoint", "60.0", {"unit_of_measurement": "°C"})
    present(hass, "number.flow", "switch.ch")
    data, _order = ORDERS["value_own_control"]
    writer = make_writer(hass, options(**data))
    if lowest_fails:
        with pytest.raises(HandBackFailed, match="refused") as failed:
            await writer.hand_back(release_from=60.0)
        checks = failed.value.checks
    else:
        checks = await writer.hand_back(release_from=60.0)
    assert len(moments) == 3  # the lowest, the heating switch, the release
    assert moments[-1] - moments[0] < 1.0  # no wait between them
    assert [check.key for check in checks] == ["switch.ch", "number.flow"]
    value = checks[1]
    assert value.entity_id == "sensor.flow_setpoint"  # the separate read-back judges it
    assert value.written is not lowest_fails  # every part of the release target, or not


@pytest.mark.parametrize(
    ("confirmed", "assumed", "source"),
    [
        ("sensor.flow_setpoint", None, CheckSource.SEPARATE),
        ("number.flow", None, CheckSource.SELF),
        (None, None, CheckSource.SELF),
        ("number.flow", "number.flow", CheckSource.ASSUMED),
        ("sensor.flow_setpoint", "sensor.flow_setpoint", CheckSource.ASSUMED),
        ("sensor.flow_setpoint", "number.flow", CheckSource.SEPARATE),
    ],
)
async def test_what_confirms_a_release(
    hass: HomeAssistant, confirmed: str | None, assumed: str | None, source: CheckSource
) -> None:
    """S-09: a separate read-back without ``assumed_state`` confirms; the written entity itself
    is the same check, unverified; an optimistic entity is no check at all."""
    record(hass, *NUMBER_SERVICES)
    for entity in ("number.flow", "sensor.flow_setpoint", "switch.ch"):
        attributes: dict[str, Any] = {"unit_of_measurement": "°C"}
        if entity == assumed:
            attributes["assumed_state"] = True
        hass.states.async_set(entity, "on" if entity == "switch.ch" else "45", attributes)
    data, _order = ORDERS["value_own_control"]
    writer = make_writer(hass, options(**data | {"confirmed_entity": confirmed}))
    heating, value = await writer.hand_back()
    assert value.source is source
    assert value.held  # the setpoint is declared held
    assert value.key == "number.flow"
    assert heating.source is CheckSource.SELF  # a switch has no separate report


async def test_no_lowest_is_left_without_a_release(hass: HomeAssistant) -> None:
    """Negative: without a hand-back method there is no release to follow the lowest water
    temperature, which a device that keeps its values would hold for good: nothing is written.
    (Control is blocked without one; this guards a unit built from options that lost it.)"""
    calls = record(hass, *NUMBER_SERVICES)
    present(hass, "number.flow")
    writer = make_writer(hass, options(write_path="entity", setpoint_entity="number.flow"))
    assert await writer.hand_back(release_from=45.0) == ()
    assert calls == []


async def test_an_expiring_external_switch_is_due_again_every_keep_alive(
    hass: HomeAssistant, freezer: Any
) -> None:
    """P-40: an expiring external-control switch is turned on at the take, again once a
    keep-alive has passed — a clock set back counts as passed — and never before; a held one
    only at the take; after the hand-back, not at all."""
    from datetime import timedelta

    calls = record(hass, *NUMBER_SERVICES)
    present(hass, "number.flow", "switch.external")
    base = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": "held",
        "hand_back": "switch",
        "hand_back_entity": "switch.external",
    }
    on = ("switch", "turn_on", {"entity_id": "switch.external"})
    expiring = make_writer(hass, options(**base, hand_back_entity_write_type="expiring"))
    await expiring.keep_alive()
    assert calls == []  # nothing taken yet: nothing to keep alive
    await expiring.write_setpoint(40.0)
    await expiring.keep_alive()
    assert calls.count(on) == 1  # not before a keep-alive has passed
    freezer.tick(timedelta(seconds=30))
    await expiring.keep_alive()
    assert calls.count(on) == 2
    freezer.move_to(datetime.now(UTC) - timedelta(hours=1))  # the clock set back
    await expiring.keep_alive()
    assert calls.count(on) == 3
    await expiring.hand_back()
    freezer.tick(timedelta(seconds=60))
    await expiring.keep_alive()
    assert calls.count(on) == 3  # handed back: nothing kept alive
    calls.clear()
    held = make_writer(hass, options(**base, hand_back_entity_write_type="held"))
    await held.write_setpoint(40.0)
    freezer.tick(timedelta(seconds=90))
    await held.keep_alive()
    await held.write_setpoint(41.0)
    assert calls.count(on) == 1  # once per take — and, since X1, refreshed:
    freezer.tick(timedelta(seconds=210))
    await held.keep_alive()
    assert calls.count(on) == 2  # every five minutes, with no echo required
    await held.keep_alive(returned=True)
    assert calls.count(on) == 3  # at once when it came back from unavailable
    await held.keep_alive()
    assert calls.count(on) == 3
    await held.renew_external()
    assert calls.count(on) == 4  # found off after an outage of its device (M15)


async def test_the_hand_back_puts_its_values_on_the_entitys_grid(hass: HomeAssistant) -> None:
    """P-15, P-98: the lowest water temperature and the hand-back value go on the setpoint
    entity's grid — the lowest never below itself, the hand-back value never above the highest
    water temperature — and the release is checked against the value on the grid."""
    calls = record(hass, ("number", "set_value"))
    hass.states.async_set(
        "number.flow", "40", {"unit_of_measurement": "°C", "step": 0.5, "min": 0.25, "max": 90}
    )
    writer = make_writer(
        hass,
        options(
            write_path="entity",
            setpoint_entity="number.flow",
            write_type="held",
            hand_back="value",
            hand_back_value=50,
            hand_back_value_effect="own_control",
        ),
    )
    checks = await writer.hand_back()
    assert [call[2]["value"] for call in calls] == [20.25, 50.25]
    (check,) = checks
    assert check.expected == pytest.approx(50.25)
    assert check.lowest == pytest.approx(20.25)


@pytest.mark.parametrize(
    "roles",
    [
        {"ch_entity": "switch.ch", "hand_back": "switch", "hand_back_entity": "switch.ch"},
        {"hand_back": "switch", "hand_back_entity": "number.flow"},
        {"ch_entity": "number.flow"},
    ],
    ids=["heating_and_external", "setpoint_and_external", "setpoint_and_heating"],
)
async def test_an_entity_writer_refuses_one_entity_in_two_roles(
    hass: HomeAssistant, roles: dict[str, Any]
) -> None:
    """X5.1 (P-03): each hand-back would switch such an entity on and off for ever — the writer
    is not built, so a hand-back through such options fails and stays owed. Negative: every role
    its own entity, or one left empty, builds."""
    base = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": "held",
        "ch_write_type": "held",
        "hand_back_entity_write_type": "held",
        "hand_back": "value",
        "hand_back_value": 30,
        "hand_back_value_effect": "own_control",
    }
    with pytest.raises(ValueError, match="two roles"):
        make_writer(hass, options(**base | roles))
    make_writer(hass, options(**base | {"ch_entity": "switch.ch"}))
    make_writer(
        hass,
        options(
            **base
            | {"ch_entity": "switch.ch", "hand_back": "switch", "hand_back_entity": "switch.ext"}
        ),
    )
    make_writer(
        hass,
        options(**base | {"ch_entity": "", "hand_back": "switch", "hand_back_entity": "switch.ch"}),
    )
