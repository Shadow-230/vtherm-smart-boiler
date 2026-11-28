"""J4's scenarios for a room's own devices (I12.26, docs/en/development/plans/plan-0.2-i12.md), on
the gateway instance: a room's thermometer failing and a room's window opening, through the
simulator's ``fail_room_sensor`` and ``set_window``.

The plugin trusts a room only on sound readings (I12.10): a room whose thermometer is unavailable
is listed in the control state's ``room_sensor_lost_zones`` and judges nothing of the curve. A
room VT holds off for a window, or whose window sensor VT reads is on, is left out of the
circuit's critical zone while open, and after it closes while it is still warming back (the
critical zone's window rule). W2 needs VT's bath zone to read its window sensor
(``docs/en/testing/test-environment.md`` §4 item 2); without it, it is not run.

Usage: HA_INSTANCE=1 scripts/env.sh python devenv/j4/rooms.py ID...
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from run import SCENARIOS, NotRun, Run, main

BEDROOM = "zone_bedroom"
BATH = "zone_bath"
BATH_WINDOW = f"binary_sensor.boiler_sim_{BATH}_window"
BATH_SHORT = 24.0  # the bath's setpoint while W2 runs: 2 K above its base, so it is the shortest


async def lost_rooms(r: Run) -> set[str]:
    return set(await r.attr("control_state", "room_sensor_lost_zones") or [])


async def T2(r: Run):
    """a room's thermometer fails (I12.10): that room alone is no longer trusted while control
    goes on; trusted again once its sensor reports"""
    bedroom = f"climate.{BEDROOM}"
    await r.zones()
    await r.switch(True)
    await r.ha.wait(60)
    # After a restart a room stays untrusted until VT measures it again (I12.10): the rooms
    # already untrusted are noted, and only the bedroom's change is judged.
    before = await lost_rooms(r)
    r.note(f"untrusted before: {sorted(before)}")
    try:
        await r.sim("fail_room_sensor", zone=BEDROOM)

        async def lost() -> bool:
            return bedroom in await lost_rooms(r)

        got = await r.ha.until(lost, 120, 5)
        now = await lost_rooms(r)
        r.check(
            got is not None and now - before == {bedroom},
            f"the bedroom alone untrusted after {got and round(got)} s: {sorted(now)}",
        )
        state = await r.s("control_state")
        r.check(state in ("heating", "idle"), f"control goes on: {state}")
        r.check(await r.s("alarm_no_zone_known") == "off", "no alarm for the other rooms")
    finally:
        await r.sim("fail_room_sensor", zone=BEDROOM, failed=False)

    async def trusted() -> bool:
        return bedroom not in await lost_rooms(r)

    back = await r.ha.until(trusted, 600, 10)
    r.check(back is not None, f"the bedroom trusted again ({back and round(back)} s)")


async def vt_window(r: Run) -> dict:
    """VT's window state of the bath zone, as its climate shows it (VT 10.6.5
    ``feature_window_manager.py``): empty where VT reads no window for it."""
    attributes = (await r.ha.state(f"climate.{BATH}") or {}).get("attributes") or {}
    return attributes.get("window_manager") or {}


async def W2(r: Run):
    """a window opens in the critical room (I12.10): VT sees it, and the room is no longer the
    circuit's critical zone while it is open; closed again, it is the critical zone again once it
    warms back"""
    bath = f"climate.{BATH}"
    if (await vt_window(r)).get("window_sensor_entity_id") != BATH_WINDOW:
        raise NotRun(
            f"VT's bath zone reads no window sensor {BATH_WINDOW} (test-environment.md §4 item 2)"
        )

    async def critical() -> str | None:
        return await r.attr("critical_zone", "zone")

    async def bath_critical() -> bool:
        return await critical() == bath

    async def bath_not_critical() -> bool:
        return await critical() != bath

    async def vt_sees_it() -> bool:
        return (await vt_window(r)).get("window_state") == "on"

    await r.zones()
    try:  # the bath's setpoint put back whatever happens
        await r.ha.call("climate", "set_temperature", entity_id=bath, temperature=BATH_SHORT)
        await r.switch(True)
        got = await r.ha.until(bath_critical, 900, 15)
        r.check(got is not None, f"the bath, set {BATH_SHORT} °C, critical: {await critical()}")
        try:
            await r.sim("set_window", zone=BATH)
            moved = await r.ha.until(bath_not_critical, 120, 5)
            r.check(
                moved is not None,
                f"window open: the bath not critical after {moved and round(moved)} s ({await critical()})",
            )
            seen = await r.ha.until(vt_sees_it, 120, 5)  # VT's window delay, 30 s by default
            r.check(seen is not None, f"VT sees the window: {await vt_window(r)}")
            await r.ha.wait(300)
            r.check(await bath_not_critical(), f"still not critical while open: {await critical()}")
        finally:
            await r.sim("set_window", zone=BATH, open=False)
        back = await r.ha.until(bath_critical, 3600, 30)
        r.check(
            back is not None,
            f"closed: the bath critical again once it warms back ({back and round(back / 60)} min)",
        )
    finally:
        await r.zones()


SCENARIOS.update({f.__name__: f for f in (T2, W2)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
