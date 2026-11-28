"""J4's scenarios for VT's central boiler deciding whether the boiler heats (I12.8, I12.27,
docs/en/development/plans/plan-0.2-i12.md), on the gateway instance.

VT's central boiler switches the helper ``input_boolean.j4_vt_central_boiler`` once enough rooms
call — its device threshold, a number entity of VT's central configuration found by its unique
ID — and the plugin follows the helper. "Gives no heat" (binary sensor ``no_heat``) is on while a
room calls and the boiler gives none, with its ``reason``, and off while no room calls (I13.1).
VT's settings are changed through VT's own options flow, as a user changes them (``walk.py``
``set_vt_fields``), and put back after each scenario. The blockers ``no_vt_boiler_helper`` and
``vt_boiler_helper_missing`` cannot be brought about here — the plugin's form takes only a helper
that exists — nor ``vt_central_boiler_not_set``, which VT's form saves only with its commands:
they stay checks by hand, as an entry from before I12 does.

Usage: HA_INSTANCE=1 scripts/env.sh python devenv/j4/vt_boiler.py ID...
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from options import VT_HELPER
from run import SCENARIOS, ZONES, NotRun, Run, main
from walk import set_vt_fields

THRESHOLD_ID = "boiler_activation_threshold"  # VT 10.6.5 ``number.py``: its device threshold
ABOVE_ANY_COUNT = 9  # VT's highest device threshold: three rooms never reach it
DELAY = "central_boiler_activation_delay_sec"  # VT 10.6.5 ``const.py``, its "central_boiler" form
DELAY_S = 120
ON_COMMAND = "central_boiler_activation_service"
USED_BY = "used_by_controls_central_boiler"  # a thermostat's "main" form
ELSEWHERE = "input_boolean.j4_not_the_helper/input_boolean.turn_on"  # an entity that is not there


async def vt_threshold(r: Run) -> str:
    """The entity of VT's device threshold, from the entity registry."""
    registry = await r.ha.ws_cmd({"type": "config/entity_registry/list"})
    found = [
        e["entity_id"]
        for e in registry
        if e.get("platform") == "versatile_thermostat" and e.get("unique_id") == THRESHOLD_ID
    ]
    if not found:
        raise NotRun("VT's central boiler shows no device threshold (test-environment.md §4)")
    return found[0]


async def rooms(r: Run, calling: bool) -> None:
    """Every room calling (3 K below its setpoint) or satisfied (its setpoint at 15 °C)."""
    for zone, target in ZONES:
        if calling:
            await r.sim("set_room_temperature", zone=zone, temperature=target - 3.0)
        await r.ha.call(
            "climate",
            "set_temperature",
            entity_id=f"climate.{zone}",
            temperature=target if calling else 15.0,
        )


async def V2(r: Run):
    """ "Gives no heat" and VT's threshold (I13.1, I12.8): off with every room satisfied; on with
    ``vt_not_calling`` while the rooms call below VT's threshold, VT's helper off; off again once
    the threshold is back and VT calls"""
    threshold = await vt_threshold(r)
    before = (await r.ha.state(threshold) or {}).get("state")
    r.note(f"VT's threshold {threshold}: {before}")

    async def no_heat(reason: str | None) -> bool:
        shown = await r.st("no_heat")
        if reason is None:
            return shown["state"] == "off"
        return shown["state"] == "on" and shown["attributes"].get("reason") == reason

    try:
        await rooms(r, calling=False)
        await r.switch(True)
        off = await r.ha.until(lambda: no_heat(None), 420, 10)  # VT's cycle ends the pulses
        r.check(off is not None, f"no room calls: gives no heat off ({await r.s('no_heat')})")
        await r.ha.call("number", "set_value", entity_id=threshold, value=ABOVE_ANY_COUNT)
        await rooms(r, calling=True)
        on = await r.ha.until(lambda: no_heat("vt_not_calling"), 420, 10)
        shown = await r.st("no_heat")
        r.check(
            on is not None,
            f"the rooms call below VT's threshold: {shown['state']} {shown['attributes'].get('reason')}",
        )
        helper = (await r.ha.state(VT_HELPER) or {}).get("state")
        r.check(helper == "off", f"VT's helper off: {helper}")
        await r.ha.call("number", "set_value", entity_id=threshold, value=float(before or 1))
        back = await r.ha.until(lambda: no_heat(None), 600, 10)
        r.check(back is not None, f"VT calls again: gives no heat off ({await r.s('no_heat')})")
    finally:
        with contextlib.suppress(Exception):
            await r.ha.call("number", "set_value", entity_id=threshold, value=float(before or 1))
        await r.switch(False)
        await r.zones()


async def vt_entries(r: Run) -> tuple[dict, list[dict]]:
    """VT's central configuration and its three zones' entries, by their titles."""
    _s, entries = await r.ha.rest("GET", "/api/config/config_entries/entry")
    titles = {zone for zone, _t in ZONES}
    vt = [e for e in entries if e["domain"] == "versatile_thermostat"]
    zones = [e for e in vt if e["title"] in titles]
    central = [e for e in vt if e["title"] not in titles]
    if len(central) != 1 or len(zones) != len(titles):
        raise NotRun(f"VT's entries are not one central configuration and the three zones: {vt}")
    return central[0], zones


async def helper_is(r: Run, state: str) -> bool:
    return (await r.ha.state(VT_HELPER) or {}).get("state") == state


async def V3(r: Run):
    """VT's own activation delay (I12.8), set at 120 s in VT's central configuration: the rooms
    calling wait it — the control state's reason and "Gives no heat" say ``activation_delay``,
    VT's helper off — then the boiler heats; put back to 0"""
    central, _zones = await vt_entries(r)

    async def reasons() -> list[str]:
        return list(await r.attr("control_state", "reasons") or [])

    async def waiting() -> bool:
        return "activation_delay" in await reasons()

    async def heating() -> bool:
        return await r.s("control_state") == "heating"

    try:
        await rooms(r, calling=False)
        await r.switch(True)
        await r.ha.until(lambda: helper_is(r, "off"), 420, 10)
        if not await set_vt_fields(
            r.ha.rest, central["entry_id"], "central_boiler", {DELAY: DELAY_S}
        ):
            raise NotRun("VT's central configuration offers no central boiler form")
        await r.ha.wait(90)  # VT reloads every thermostat
        await rooms(r, calling=True)  # a full call: the valves stay open, VT's delay runs through
        got = await r.ha.until(waiting, 420, 5)
        shown = await r.st("no_heat")
        r.check(got is not None, f"VT's delay shown: {await reasons()}")
        r.check(
            shown["state"] == "on" and shown["attributes"].get("reason") == "activation_delay",
            f"gives no heat for VT's delay: {shown['state']} {shown['attributes'].get('reason')}",
        )
        r.check(await helper_is(r, "off"), "VT's helper off while its delay runs")
        t = time.time()
        heats = await r.ha.until(heating, DELAY_S + 180, 5)
        r.check(heats is not None, f"then the boiler heats ({heats and round(heats)} s after)")
        r.note(f"waited {round(time.time() - t)} s after the delay was first shown")
    finally:
        with contextlib.suppress(Exception):
            await set_vt_fields(r.ha.rest, central["entry_id"], "central_boiler", {DELAY: 0})
        await r.ha.wait(60)
        await r.switch(False)
        await r.zones()


async def V4(r: Run):
    """VT's settings the plugin tells about (I12.11, I12.8): the bath not counted by VT's central
    boiler — the information issue ``vt_thermostats_not_counted`` naming it; VT's "on" command on
    another entity — the blocker ``vt_command_not_helper``; each gone once VT's setting is put
    back"""
    central, zones = await vt_entries(r)
    bath = next(zone for zone in zones if zone["title"] == "zone_bath")

    async def not_counted(present: bool) -> bool:
        issues = [i["issue_id"] for i in await r.ha.issues()]
        return any(i.startswith("vt_thermostats_not_counted") for i in issues) is present

    async def blockers() -> list[str]:
        return list(await r.attr("control", "blockers") or [])

    async def blocked(present: bool) -> bool:
        return ("vt_command_not_helper" in await blockers()) is present

    on_command = f"{VT_HELPER}/input_boolean.turn_on"
    try:
        await r.switch(True)
        await set_vt_fields(r.ha.rest, bath["entry_id"], "main", {USED_BY: False})
        got = await r.ha.until(lambda: not_counted(True), 300, 10)
        r.check(got is not None, f"the bath not counted: the issue ({got and round(got)} s)")
        await set_vt_fields(r.ha.rest, bath["entry_id"], "main", {USED_BY: True})
        gone = await r.ha.until(lambda: not_counted(False), 300, 10)
        r.check(gone is not None, f"counted again: the issue gone ({gone and round(gone)} s)")
        await set_vt_fields(
            r.ha.rest, central["entry_id"], "central_boiler", {ON_COMMAND: ELSEWHERE}
        )
        got = await r.ha.until(lambda: blocked(True), 300, 10)
        r.check(got is not None, f"VT's command elsewhere: {await blockers()}")
        await set_vt_fields(
            r.ha.rest, central["entry_id"], "central_boiler", {ON_COMMAND: on_command}
        )
        gone = await r.ha.until(lambda: blocked(False), 300, 10)
        r.check(gone is not None, f"VT's command on the helper again: {await blockers()}")
    finally:
        with contextlib.suppress(Exception):
            await set_vt_fields(r.ha.rest, bath["entry_id"], "main", {USED_BY: True})
            await set_vt_fields(
                r.ha.rest, central["entry_id"], "central_boiler", {ON_COMMAND: on_command}
            )
        await r.ha.wait(60)
        await r.switch(False)
        await r.zones()


async def V5(r: Run):
    """VT's decision unknown (I12, decision 3): VT's helper made unavailable in Home Assistant's
    state machine with the rooms known — the reason ``vt_decision_unknown``, the boiler handed
    back to the wall thermostat at once; the helper back, control takes the boiler again"""
    before = (await r.ha.state(VT_HELPER) or {}).get("state")

    async def handed_back() -> bool:
        st = await r.st("control_state")
        return st["state"] == "handed_back" and "vt_decision_unknown" in (
            st["attributes"].get("reasons") or []
        )

    async def taken() -> bool:
        return await r.s("control_state") in ("heating", "idle")

    try:
        await r.zones()
        await r.switch(True)
        await r.ha.wait(60)
        await r.ha.rest("POST", f"/api/states/{VT_HELPER}", {"state": "unavailable"})
        got = await r.ha.until(handed_back, 120, 5)
        st = await r.st("control_state")
        r.check(
            got is not None,
            f"VT's decision unknown: {st['state']} {st['attributes'].get('reasons')}",
        )
        r.check("zones_unknown" not in (st["attributes"].get("reasons") or []), "the rooms known")
    finally:
        await r.ha.rest("POST", f"/api/states/{VT_HELPER}", {"state": before or "off"})
    back = await r.ha.until(taken, 300, 5)
    r.check(
        back is not None, f"the helper back: control takes the boiler ({back and round(back)} s)"
    )
    await r.switch(False)


SCENARIOS.update({f.__name__: f for f in (V2, V3, V4, V5)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
