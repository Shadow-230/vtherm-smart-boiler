"""What the Boiler page reads (``docs/en/development/plans/plan-0.2-i10.md``, I10.2): the
installation, the curve's points with the settings' checks — for the settings in use or for draft
values, nothing saved — and the daily summaries; each from the running entry only."""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.daily import DaySummary
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits, limit_flow
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.websocket_api import async_setup_websocket

from .harness import FakeBoiler
from .test_control import (  # the rig fixture comes with them
    Rig,
    rig,  # noqa: F401
    start,
)
from .test_setup import entity_id, entry_for, setup

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

DAY = 86400.0


class Client:
    """A signed-in user's WebSocket connection, one command at a time."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.next_id = 1

    async def ask(self, command: str, **fields: Any) -> dict[str, Any]:
        self.next_id += 1
        await self.ws.send_json({"id": self.next_id, "type": f"{DOMAIN}/{command}", **fields})
        reply = await self.ws.receive_json()
        assert reply["id"] == self.next_id
        return reply


async def connect(hass: HomeAssistant, hass_ws_client: Any) -> Client:
    assert await async_setup_component(hass, "websocket_api", {})
    return Client(await hass_ws_client(hass))


async def monitoring(hass: HomeAssistant):
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    return boiler, entry


async def test_nothing_running_answers_not_running(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    async_setup_websocket(hass)
    async_setup_websocket(hass)  # once per run: a second call changes nothing
    client = await connect(hass, hass_ws_client)
    for command in ("installation", "curve", "days"):
        reply = await client.ask(command)
        assert reply["success"] is False, command
        assert reply["error"]["code"] == "not_running"


async def test_the_installation_of_a_monitor_only_entry(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    boiler, entry = await monitoring(hass)
    client = await connect(hass, hass_ws_client)

    reply = await client.ask("installation")
    assert reply["success"] is True
    view = reply["result"]
    assert view["entry_id"] == entry.entry_id
    assert view["title"] == "Boiler"
    assert view["signals"] == {
        Signal.FLAME.value: boiler.entity(Signal.FLAME),
        Signal.FLOW.value: boiler.entity(Signal.FLOW),
    }
    assert view["entities"]["sidebar_page"] == entity_id(hass, entry, "switch", "sidebar_page")
    assert set(view["boiler"]) == {"type", "dhw", "condensing"}
    assert view["curve"] is None  # monitoring only: control sets no water
    for circuit in view["circuits"]:
        assert set(circuit) == {
            "id", "name", "control", "fixed_temperature", "max_flow", "needed", "zones",
        }  # fmt: skip

    reply = await client.ask("curve")
    assert reply["success"] is False
    assert reply["error"]["code"] == "no_curve"


async def test_the_days_oldest_first_and_from_a_moment(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    _boiler, entry = await monitoring(hass)
    client = await connect(hass, hass_ws_client)
    coordinator = entry.runtime_data
    coordinator.daily = {
        start: DaySummary.empty(start, start + DAY) for start in (3 * DAY, 1 * DAY, 2 * DAY)
    }

    reply = await client.ask("days")
    assert [day["start"] for day in reply["result"]["days"]] == [DAY, 2 * DAY, 3 * DAY]
    assert reply["result"]["days"][0] == DaySummary.empty(DAY, 2 * DAY).to_dict()
    reply = await client.ask("days", since=2 * DAY)
    assert [day["start"] for day in reply["result"]["days"]] == [2 * DAY, 3 * DAY]


async def test_the_curve_as_control_decides_it(rig: Rig, hass_ws_client: Any) -> None:
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    loop = rig.entry.runtime_data.config.control.loop.control

    view = (await client.ask("installation"))["result"]
    curve = view["curve"]
    assert curve is not None
    assert (curve["design_outdoor"], curve["design_flow"]) == (-15, 55)
    assert curve["entered"] is True
    assert (curve["hard_min"], curve["hard_max"]) == (loop.limits.hard_min, loop.limits.hard_max)
    assert curve["room_auto"] is loop.room_auto

    reply = await client.ask("curve", outdoor_from=-20, outdoor_to=20, step=1)
    assert reply["success"] is True
    points = reply["result"]["points"]
    assert len(points) == 41
    for outdoor, water in points:
        assert water == pytest.approx(
            limit_flow(
                loop.curve.flow(outdoor), loop.limits, loop.circuit_max, loop.boiler_max
            ).value
        )
    assert reply["result"]["problems"] == []


async def test_a_draft_is_checked_as_the_settings_check_it(rig: Rig, hass_ws_client: Any) -> None:
    """A preview: draft values give their points and the settings' own problems, by their
    translation keys; nothing is saved."""
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    options = dict(rig.entry.options)

    reply = await client.ask("curve", design_flow=24, room=21, step=5)
    assert reply["result"]["problems"] == ["design_flow_too_low", "hard_min_not_below_design_flow"]
    draft = HeatingCurve(design_outdoor=-15, design_flow=60, room=22, offset=2)
    reply = await client.ask("curve", design_flow=60, room=22, offset=2, step=5)
    points = dict(reply["result"]["points"])
    limits = rig.entry.runtime_data.config.control.loop.control.limits
    assert points[-10] == pytest.approx(limit_flow(draft.flow(-10), limits).value)
    assert reply["result"]["problems"] == []
    assert dict(rig.entry.options) == options  # nothing saved


@pytest.mark.parametrize(
    "fields",
    [{"exponent": 0}, {"hard_min": 60, "hard_max": 50}, {"design_outdoor": 25, "room": 21}],
)
async def test_values_that_make_no_curve_are_named(
    rig: Rig, hass_ws_client: Any, fields: dict[str, float]
) -> None:
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    reply = await client.ask("curve", **fields)
    assert reply["success"] is True
    assert reply["result"] == {"points": [], "problems": ["invalid_curve"]}


async def test_the_lowest_water_above_a_cap_is_named(rig: Rig, hass_ws_client: Any) -> None:
    """PB-26 as the settings name it: the lowest water above a circuit's highest."""
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    coordinator = rig.entry.runtime_data
    config = coordinator.config
    loop = replace(
        config.control.loop, control=replace(config.control.loop.control, circuit_max=40.0)
    )
    coordinator.config = replace(config, control=replace(config.control, loop=loop))
    reply = await client.ask("curve", hard_min=45, step=5)
    assert "hard_min_above_max" in reply["result"]["problems"]
    assert {water for _o, water in reply["result"]["points"]} == {40.0}  # the cap wins


async def test_a_backwards_range_is_refused(rig: Rig, hass_ws_client: Any) -> None:
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    reply = await client.ask("curve", outdoor_from=10, outdoor_to=-10)
    assert reply["success"] is False
    assert reply["error"]["code"] == "invalid_range"
    reply = await client.ask("curve", step=0)  # the schema's own bounds
    assert reply["success"] is False


def test_flow_limits_refuse_what_the_command_names_invalid() -> None:
    """The command's ``invalid_curve`` stands on these refusals."""
    with pytest.raises(ValueError, match="hard limits"):
        FlowLimits(hard_min=60, hard_max=50)
    with pytest.raises(ValueError, match="exponent"):
        HeatingCurve(exponent=0)
