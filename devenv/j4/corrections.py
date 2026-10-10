"""J4's scenarios for the corrections decided on 2026-10-10 (test instance 1: the gateway path,
full control, VT's zones with SmartPI in the bedroom and TPI elsewhere).

They test the behaviour decided before it is built — run them once the corrections are merged:
the comfort correction with a user limit and a warning at its edge, SmartPI's learning band in
"is the room short", the curve's room temperature in Auto, the long-run rule and the guard for
an open window without a sensor. The new notices' names are the code's to choose, so these
scenarios look for any new repair issue or alarm and note what they find; once the names exist,
tighten the checks to them.

Usage: HA_INSTANCE=1 scripts/env.sh python devenv/j4/corrections.py ID...
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from paths import options_walk
from run import SCENARIOS, ZONES, Run, main

FLAME = "binary_sensor.boiler_sim_flame"
SMARTPI_ZONE = "climate.zone_bedroom"
LOW_CURVE = {"design_flow": 38.0}  # well below what the simulated house needs


async def notices(r: Run) -> dict[str, dict[str, Any]]:
    """The plugin's repair issues and its alarms that are on, by id."""
    out: dict[str, dict[str, Any]] = {}
    for issue in await r.ha.issues():
        out[f"issue:{issue['issue_id']}"] = {
            "severity": issue.get("severity"),
            "key": issue.get("translation_key"),
            "placeholders": issue.get("translation_placeholders") or {},
        }
    for alarm in await r.alarms_on():
        out[f"alarm:{alarm}"] = {"severity": None, "key": alarm, "placeholders": {}}
    return out


def new_since(before: dict[str, Any], now: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in now.items() if k not in before}


async def correction_on(r: Run) -> bool:
    return "comfort_correction" in (await r.attr("control_state", "reasons") or [])


async def target(r: Run) -> float | None:
    value = await r.attr("control_state", "target")
    return float(value) if isinstance(value, (int, float)) else None


async def room(r: Run, zone: str) -> float | None:
    with contextlib.suppress(TypeError, ValueError):
        return float(await r.s(f"sensor.boiler_sim_{zone}_temperature"))
    return None


async def curve_fields(r: Run, step: str = "control_curve") -> list[dict[str, Any]]:
    """The fields of one control options step as the form shows them now (the flow is left
    unsaved)."""
    ha = r.ha
    entry = await ha.entry("vtherm_smart_boiler")
    _s, d = await ha.rest(
        "POST",
        "/api/config/config_entries/options/flow",
        {"handler": entry["entry_id"], "show_advanced_options": True},
    )
    path = f"/api/config/config_entries/options/flow/{d['flow_id']}"
    _s, d = await ha.rest("POST", path, {"next_step_id": "control"})
    try:
        while d.get("type") == "form":
            if d["step_id"] == step:
                return list(d.get("data_schema") or [])
            body = {
                f["name"]: v
                for f in d.get("data_schema") or []
                if (v := (f.get("description") or {}).get("suggested_value", f.get("default")))
                is not None
            }
            _s, d = await ha.rest("POST", path, body)
        return []
    finally:
        await ha.rest("DELETE", path)


def _options_of(field: dict[str, Any]) -> list[str]:
    options = ((field.get("selector") or {}).get("select") or {}).get("options") or []
    return [o["value"] if isinstance(o, dict) else str(o) for o in options]


async def room_mode_field(r: Run) -> tuple[str | None, str | None]:
    """The curve's room temperature mode (a choice with "auto" and "manual") and the field
    that leaves zones out of Auto, as the form names them; ``None`` where not found."""
    fields = await curve_fields(r)
    mode = next((f["name"] for f in fields if {"auto", "manual"} <= set(_options_of(f))), None)
    exclude = next((f["name"] for f in fields if "exclu" in f["name"]), None)
    return mode, exclude


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


async def Q1(r: Run):
    """a curve too low with the correction on, the bedroom's SmartPI in its learning phase and
    the rooms just under their setpoints: SmartPI's band (+0.5 K) counts, so the water rises; at
    the correction's limit for 3 h with a room still short, a warning"""
    try:
        await r.options(curve=LOW_CURVE, behaviour={"comfort_correction": True})
        r.ent.update(await r.ha.entities())
        await r.sim("set_outdoor", temperature=0.0)
        await r.ha.call("vtherm_smartpi", "reset_smartpi_learning", entity_id=SMARTPI_ZONE)
        for zone, value in ZONES:
            await r.sim("set_room_temperature", zone=zone, temperature=value - 0.2)
        before = await notices(r)
        await r.switch(True)
        await r.ha.wait(300)
        start = await target(r)
        rose = await r.ha.until(lambda: correction_on(r), 7200, 60)
        r.check(rose is not None, f"the correction started ({rose and round(rose / 60)} min)")
        t = time.time()
        warned: dict[str, Any] = {}
        while time.time() - t < 6 * 3600 and not warned:
            await r.ha.wait(300)
            warned = {
                k: v
                for k, v in new_since(before, await notices(r)).items()
                if v["severity"] == "warning"
            }
        r.note(
            f"target {start} → {await target(r)}; bedroom {await room(r, 'zone_bedroom')} °C; new {new_since(before, await notices(r))}"
        )
        r.check(bool(warned), f"a warning at the limit with a room short: {warned}")
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.sim("set_outdoor", temperature=3.0)
        await r.options()


async def Q2(r: Run):
    """a curve too low with the correction off: the water stays on the curve; after 3 h of the
    flame on with the rooms not warming, information that the water is too cool"""
    try:
        await r.options(curve=LOW_CURVE, behaviour={"comfort_correction": False})
        await r.sim("set_outdoor", temperature=0.0)
        before = await notices(r)
        rooms0 = {z: await room(r, z) for z, _v in ZONES}
        await r.switch(True)
        burned = await flame_on_for(r, 3 * 3600, 5 * 3600)
        r.check(burned is not None, f"the flame on for 3 h ({burned and round(burned / 60)} min)")
        await r.ha.wait(600)
        rooms1 = {z: await room(r, z) for z, _v in ZONES}
        new = new_since(before, await notices(r))
        r.note(f"rooms {rooms0} → {rooms1}; new {new}")
        r.check(not await correction_on(r), "no correction: off")
        r.check(bool(new), f"told the water is too cool: {new}")
        r.check(
            not any("power" in str(v["key"]) for v in new.values()),
            "not taken for the boiler's power limit (the flow holds its setpoint)",
        )
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.sim("set_outdoor", temperature=3.0)
        await r.options()


async def Q3(r: Run):
    """the curve's room temperature in Auto: the warmest heating room's setpoint, at most
    23 °C, a zone left out ignored; Manual back after"""
    mode, exclude = await room_mode_field(r)
    if mode is None:
        r.check(False, "no Auto/Manual choice for the curve's room temperature in the form")
        return
    try:
        d = await options_walk(r, {"control_curve": {mode: "auto"}})
        r.check(not d.get("errors"), f"Auto saved: {d.get('errors')}")
        await r.switch(True)
        await r.ha.wait(420)
        base = await target(r)  # the bath, 22 °C, is the warmest
        await set_targets(r, {"zone_bath": 23.0})
        await r.ha.wait(420)
        up = await target(r)
        await set_targets(r, {"zone_bath": 25.0})
        await r.ha.wait(420)
        capped = await target(r)
        await set_targets(r, {"zone_bath": 22.0, "zone_living": 21.0})
        await r.ha.wait(420)
        other = await target(r)
        r.note(f"targets: base {base}, bath 23 → {up}, bath 25 → {capped}, living 21 → {other}")
        r.check(base is not None and up is not None and up > base + 0.3, "follows the warmest room")
        r.check(capped is not None and up is not None and abs(capped - up) < 0.3, "at most 23 °C")
        r.check(
            other is not None and base is not None and abs(other - base) < 0.3,
            "a room that is not the warmest changes nothing",
        )
        if exclude is not None:
            d = await options_walk(r, {"control_curve": {exclude: ["climate.zone_bath"]}})
            await r.ha.wait(420)
            left = await target(r)
            r.check(
                left is not None and base is not None and left < base - 0.3,
                f"the bath left out: {left} (the living room, 21 °C, is the warmest now)",
            )
        else:
            r.note("no field to leave zones out found in the form")
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        answers: dict[str, Any] = {mode: "manual", "room": 20.0}
        if exclude is not None:
            answers[exclude] = []
        await options_walk(r, {"control_curve": answers})
        await r.zones()


async def Q4(r: Run):
    """a window opened in one room without a sensor (its temperature falls 1.5 K at once): no
    correction for it for at least 30 min, and information that a window is probably open"""
    try:
        await r.options(behaviour={"comfort_correction": True})
        await r.switch(True)
        await r.ha.wait(900)
        before = await notices(r)
        base = await target(r)
        await r.sim("set_room_temperature", zone="zone_living", temperature=ZONES[0][1] - 1.5)
        rose_at = None
        t = time.time()
        while time.time() - t < 1800:
            await r.ha.wait(60)
            if rose_at is None and await correction_on(r):
                rose_at = round((time.time() - t) / 60)
        new = new_since(before, await notices(r))
        r.note(f"target {base} → {await target(r)}; new {new}")
        r.check(rose_at is None, f"no correction for 30 min (rose at {rose_at} min)")
        r.check(bool(new), f"told a window is probably open: {new}")
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.options()


async def Q5(r: Run):
    """one room short while the others hold (its setpoint out of reach): the curve must hold every
    room — the correction raises the water for it, and at its limit for 3 h the warning names
    that room"""
    try:
        await r.options(behaviour={"comfort_correction": True})
        before = await notices(r)
        await set_targets(r, {"zone_living": 28.0})
        await r.switch(True)
        rose = await r.ha.until(lambda: correction_on(r), 7200, 60)
        r.check(
            rose is not None, f"the correction rises for one room ({rose and round(rose / 60)} min)"
        )
        t = time.time()
        named: list[dict[str, Any]] = []
        while time.time() - t < 6 * 3600 and not named:
            await r.ha.wait(300)
            named = [
                v
                for v in new_since(before, await notices(r)).values()
                if v["severity"] == "warning" and "living" in str(v["placeholders"])
            ]
        r.note(
            f"after {round((time.time() - t) / 3600, 1)} h: new {new_since(before, await notices(r))}"
        )
        r.check(bool(named), f"a warning naming the living room: {named}")
    finally:
        await r.switch(False)
        await r.ha.wait(10)
        await r.options()
        await r.zones()


SCENARIOS.update({f.__name__: f for f in (Q1, Q2, Q3, Q4, Q5)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
