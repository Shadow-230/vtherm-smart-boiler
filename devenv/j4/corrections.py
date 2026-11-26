"""J4's scenarios for the corrections of 2026-10-10 (G11, docs/en/development/plans/plan-0.2-g11.md), on test instance
1: the gateway path, full control, VT's zones with SmartPI in the bedroom and TPI elsewhere.

The comfort correction with its limit and the warning at its edge (repair issue
``curve_too_low_<entry>``, key ``curve_too_low`` or ``room_short_at_limit``, the rooms' entity IDs
in its ``entities`` placeholder), "is the room short" against VT's setpoint (SmartPI's learning
band went with I12.9), the curve's
room temperature in Auto (option ``room_mode``, ``room_excluded``; the control state's
``curve_room``) and the long-burn rule (binary sensor ``long_burn``, its ``reason``). The guard for
an open window without a sensor went with #64 (VT's own window detection stops a zone calling), and
Q4 with it (J4 of 2026-10-14).

Usage: HA_INSTANCE=1 scripts/env.sh python devenv/j4/corrections.py ID...
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from run import SCENARIOS, ZONES, NotRun, Run, check_written_exactly, main

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


CORRECTION_ON = {"comfort_correction": True}


async def curve_issue(r: Run) -> dict[str, Any] | None:
    """The warning at the correction's limit, if raised."""
    return next(
        (i for i in await r.ha.issues() if i["issue_id"].startswith("curve_too_low_")), None
    )


async def Q1(r: Run):
    """a curve too low with the correction on and the rooms short of their setpoints — 0.4 K
    under VT's setpoint, short by its own measure (I12.9: SmartPI's +0.5 K band no longer
    counts) — so the water rises; at the correction's limit for 3 h with a room still short,
    the warning naming it"""
    try:
        await r.options(curve=LOW_CURVE | CORRECTION_ON)
        r.ent.update(await r.ha.entities())
        await r.sim("set_outdoor", temperature=0.0)
        for zone, value in ZONES:
            await r.sim("set_room_temperature", zone=zone, temperature=value - 0.4)
        switched = time.time()
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
        if issue is not None and await r.s("alarm_correction_at_limit") == "on":
            await check_written_exactly(r, switched)
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.sim("set_outdoor", temperature=3.0)
        await r.options()


async def Q2(r: Run):
    """a curve too low with the correction off: the water stays on the curve; after 3 h of
    burning — the flame's gaps of up to 30 min kept, so a boiler cycling at its minimum counts
    (K4, F10) — with the rooms not warming, the long-burn sensor says the water is too cool —
    not the boiler's power limit (the flow holds or reaches its setpoint)"""
    try:
        await r.options(curve=LOW_CURVE)
        r.ent.update(await r.ha.entities())
        await r.sim("set_outdoor", temperature=0.0)
        await r.switch(True)
        told = await r.ha.until(lambda: _long_burn(r), 5 * 3600, 30)
        r.check(told is not None, "the long-burn sensor on within 5 h")
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


async def smartpi_bootstrap(r: Run) -> str | None:
    """The bedroom's SmartPI diagnostic state while it still learns from scratch ("bootstrap_…",
    SmartPI 0.4.0 onward; the VT climate names the sensor in ``specific_states``), else
    ``None`` — also where the sensor cannot be found."""
    states = await r.attr(SMARTPI_ZONE, "specific_states")
    sensor = states.get("regulation_diagnostics") if isinstance(states, dict) else None
    if not isinstance(sensor, str) or not sensor.startswith("sensor."):
        return None
    state = await r.s(sensor)
    return state if isinstance(state, str) and state.startswith("bootstrap") else None


async def Q5(r: Run):
    """one room short while the others hold (its setpoint out of reach): the curve must hold
    every room — the correction rises for it, and at its limit for 3 h the warning names that
    room, the radiator and the heat loss first"""
    # "The others hold" needs the bedroom's SmartPI past its bootstrap: learning from scratch it
    # runs on/off, its valve fully open down to 0.3 K under its setpoint, where its room touches
    # "short" (J4 of 2026-11-18, an instance set up a minute before: two rooms short, the curve
    # warning rightly instead). Read from SmartPI by the bench, never by the plugin (I12.9).
    learning = await smartpi_bootstrap(r)
    if learning is not None:
        raise NotRun(
            f"the bedroom's SmartPI still learns from scratch ({learning}): run Q5 once its "
            "bootstrap is over"
        )
    try:
        await r.options(curve=CORRECTION_ON)
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


SCENARIOS.update({f.__name__: f for f in (Q1, Q2, Q3, Q5)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
