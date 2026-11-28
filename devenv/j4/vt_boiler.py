"""J4's scenarios for VT's central boiler deciding whether the boiler heats (I12.8, I12.27,
docs/en/development/plans/plan-0.2-i12.md), on the gateway instance.

VT's central boiler switches the helper ``input_boolean.j4_vt_central_boiler`` once enough rooms
call — its device threshold, a number entity of VT's central configuration found by its unique
ID — and the plugin follows the helper. "Gives no heat" (binary sensor ``no_heat``) is on while a
room calls and the boiler gives none, with its ``reason``, and off while no room calls (I13.1).

Usage: HA_INSTANCE=1 scripts/env.sh python devenv/j4/vt_boiler.py ID...
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from options import VT_HELPER
from run import SCENARIOS, ZONES, NotRun, Run, main

THRESHOLD_ID = "boiler_activation_threshold"  # VT 10.6.5 ``number.py``: its device threshold
ABOVE_ANY_COUNT = 9  # VT's highest device threshold: three rooms never reach it


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


SCENARIOS.update({f.__name__: f for f in (V2,)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
