"""J4's scenarios for the corrections of 2026-10-10 (G11, docs/plan-0.2-g11.md), on test instance
1: the gateway path, full control, VT's zones with SmartPI in the bedroom and TPI elsewhere.

The comfort correction with its limit and the warning at its edge (repair issue
``curve_too_low_<entry>``, key ``curve_too_low`` or ``room_short_at_limit``, the rooms' entity IDs
in its ``entities`` placeholder), SmartPI's learning band in "is the room short", the curve's
room temperature in Auto (option ``room_mode``, ``room_excluded``; the control state's
``curve_room``), the long-burn rule (binary sensor ``long_burn``, its ``reason``) and the guard
for an open window without a sensor (binary sensor ``window_probably_open``).

Usage: HA_INSTANCE=1 scripts/env.sh python devenv/j4/corrections.py ID...
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from run import SCENARIOS, ZONES, Run, main

FLAME = "binary_sensor.boiler_sim_flame"
SMARTPI_ZONE = "climate.zone_bedroom"
LOW_CURVE = {"design_flow": 38.0}  # well below what the simulated house needs


async def correction_on(r: Run) -> bool:
    return "comfort_correction" in (await r.attr("control_state", "reasons") or [])


async def target(r: Run) -> float | None:
    value = await r.attr("control_state", "target")
    return float(value) if isinstance(value, (int, float)) else None


async def room(r: Run, zone: str) -> float | None:
    with contextlib.suppress(TypeError, ValueError):
        return float(await r.s(f"sensor.boiler_sim_{zone}_temperature"))
    return None


async def set_targets(r: Run, targets: dict[str, float]) -> None:
    for zone, value in targets.items():
        await r.ha.call(
            "climate", "set_temperature", entity_id=f"climate.{zone}", temperature=value
        )


async def flame_on_for(r: Run, seconds: float, within: float) -> float | None:
    """Seconds until the flame has been on without a break for ``seconds``; ``None`` if that
    never happened within ``within``."""
    start = time.time()
    since: float | None = None
    while time.time() - start < within:
        if await r.s(FLAME) == "on":
            since = since or time.time()
            if time.time() - since >= seconds:
                return time.time() - start
        else:
            since = None
        await r.ha.wait(30)
    return None


CORRECTION_ON = {"comfort_correction": True}


async def curve_issue(r: Run) -> dict[str, Any] | None:
    """The warning at the correction's limit, if raised."""
    return next(
        (i for i in await r.ha.issues() if i["issue_id"].startswith("curve_too_low_")), None
    )


async def Q1(r: Run):
    """a curve too low with the correction on, the bedroom's SmartPI in its learning phase and
    the rooms just under their setpoints: SmartPI's band (+0.5 K) counts, so the water rises; at
    the correction's limit for 3 h with a room still short, the warning naming it"""
    try:
        await r.options(curve=LOW_CURVE, behaviour=CORRECTION_ON)
        r.ent.update(await r.ha.entities())
        await r.sim("set_outdoor", temperature=0.0)
        await r.ha.call("vtherm_smartpi", "reset_smartpi_learning", entity_id=SMARTPI_ZONE)
        for zone, value in ZONES:
            await r.sim("set_room_temperature", zone=zone, temperature=value - 0.2)
        await r.switch(True)
        await r.ha.wait(300)
        start = await target(r)
        rose = await r.ha.until(lambda: correction_on(r), 7200, 60)
        r.check(rose is not None, f"the correction started ({rose and round(rose / 60)} min)")
        issue = None
        t = time.time()
        while time.time() - t < 6 * 3600 and issue is None:
            await r.ha.wait(300)
            issue = await curve_issue(r)
        r.note(
            f"target {start} → {await target(r)}; bedroom {await room(r, 'zone_bedroom')} °C; issue {issue and (issue.get('translation_key'), issue.get('translation_placeholders'))}"
        )
        r.check(
            issue is not None and issue.get("severity") == "warning",
            "the warning at the limit with a room short",
        )
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.sim("set_outdoor", temperature=3.0)
        await r.options()


async def Q2(r: Run):
    """a curve too low with the correction off: the water stays on the curve; after 3 h of the
    flame on with the rooms not warming, the long-burn sensor says the water is too cool — not
    the boiler's power limit (the flow holds its setpoint)"""
    try:
        await r.options(curve=LOW_CURVE)
        r.ent.update(await r.ha.entities())
        await r.sim("set_outdoor", temperature=0.0)
        await r.switch(True)
        burned = await flame_on_for(r, 3 * 3600, 5 * 3600)
        r.check(burned is not None, f"the flame on for 3 h ({burned and round(burned / 60)} min)")
        told = await r.ha.until(lambda: _long_burn(r), 1800, 30)
        st = await r.st("long_burn")
        r.note(f"long burn: {st['state']} {st['attributes']}")
        r.check(not await correction_on(r), "no correction: off")
        r.check(
            told is not None and st["attributes"].get("reason") == "water_too_cool",
            f"the water too cool: {st['attributes'].get('reason')}",
        )
        r.check(
            not any(i["issue_id"].startswith("boiler_power_limit") for i in await r.ha.issues()),
            "no power-limit warning",
        )
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.sim("set_outdoor", temperature=3.0)
        await r.options()


async def _long_burn(r: Run) -> bool:
    return await r.s("long_burn") == "on"


async def _curve_room(r: Run) -> float | None:
    value = await r.attr("control_state", "curve_room")
    return float(value) if isinstance(value, (int, float)) else None


async def Q3(r: Run):
    """the curve's room temperature in Auto: the warmest heating room's setpoint, at most
    23 °C, a zone left out ignored; Manual back after"""
    try:
        await r.options(curve={"room_mode": "auto"})
        await r.switch(True)
        steps = []
        for targets in (
            {},
            {"zone_bath": 23.0},
            {"zone_bath": 25.0},
            {"zone_bath": 22.0, "zone_living": 21.0},
        ):
            await set_targets(r, targets)
            await r.ha.wait(420)
            steps.append(await _curve_room(r))
        r.note(f"curve room: base, bath 23, bath 25, living 21 → {steps}")
        r.check(steps[0] == 22.0, f"the warmest room, the bath at 22 °C: {steps[0]}")
        r.check(steps[1] == 23.0, f"follows the bath to 23 °C: {steps[1]}")
        r.check(steps[2] == 23.0, f"at most 23 °C: {steps[2]}")
        r.check(steps[3] == 22.0, f"a room that is not the warmest changes nothing: {steps[3]}")
        await r.options(curve={"room_mode": "auto", "room_excluded": ["climate.zone_bath"]})
        await r.switch(True)
        await r.ha.wait(420)
        left = await _curve_room(r)
        r.check(left == 21.0, f"the bath left out: the living room's 21 °C: {left}")
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.options()
        await r.zones()


async def Q4(r: Run):
    """a window opened in one room without a sensor (its temperature falls 1.5 K at once): the
    window sensor on, no correction for it for at least 30 min"""
    try:
        await r.options(behaviour=CORRECTION_ON)
        r.ent.update(await r.ha.entities())
        await r.switch(True)
        await r.ha.wait(900)
        base = await target(r)
        await r.sim("set_room_temperature", zone="zone_living", temperature=ZONES[0][1] - 1.5)
        seen = await r.ha.until(lambda: _window(r), 600, 10)
        st = await r.st("window_probably_open")
        r.check(
            seen is not None,
            f"window probably open {seen and round(seen)} s after: {st['attributes']}",
        )
        rose_at = None
        t = time.time()
        while time.time() - t < 1800:
            await r.ha.wait(60)
            if rose_at is None and await correction_on(r):
                rose_at = round((time.time() - t) / 60)
        r.note(f"target {base} → {await target(r)}")
        r.check(rose_at is None, f"no correction for 30 min (rose at {rose_at} min)")
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.options()


async def _window(r: Run) -> bool:
    return await r.s("window_probably_open") == "on"


async def Q5(r: Run):
    """one room short while the others hold (its setpoint out of reach): the curve must hold
    every room — the correction rises for it, and at its limit for 3 h the warning names that
    room, the radiator and the heat loss first"""
    try:
        await r.options(behaviour=CORRECTION_ON)
        await set_targets(r, {"zone_living": 28.0})
        await r.switch(True)
        rose = await r.ha.until(lambda: correction_on(r), 7200, 60)
        r.check(
            rose is not None, f"the correction rises for one room ({rose and round(rose / 60)} min)"
        )
        issue = None
        t = time.time()
        while time.time() - t < 6 * 3600 and issue is None:
            await r.ha.wait(300)
            issue = await curve_issue(r)
        placeholders = (issue or {}).get("translation_placeholders") or {}
        r.note(
            f"after {round((time.time() - t) / 3600, 1)} h: {issue and (issue.get('translation_key'), placeholders)}"
        )
        r.check(
            issue is not None
            and issue.get("translation_key") == "room_short_at_limit"
            and "climate.zone_living" in placeholders.get("entities", ""),
            "the warning names the living room, one room short",
        )
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.options()
        await r.zones()


SCENARIOS.update({f.__name__: f for f in (Q1, Q2, Q3, Q4, Q5)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
