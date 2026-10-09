"""J4's scenarios on the relay path, the entity path and a stand-alone gateway (test instances
deployed with ``--config relay``, ``entity`` and ``standalone``; docs/test-reports/README.md).

Usage: HA_INSTANCE=N scripts/env.sh python devenv/j4/paths.py ID... — the same runner as
run.py (its clean state, its results file), with the commands to the relay and the entities
captured from Home Assistant's service calls as run.py captures the gateway's.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from run import SCENARIOS, ZONES, Run, main

RELAY = "switch.boiler_sim_relay"
SETPOINT = "number.boiler_sim_flow_setpoint"
CH_SWITCH = "switch.boiler_sim_ch_enable"
EXTERNAL = "switch.boiler_sim_external_control"
# The relay rule judges no other state within its confirmation window (RELAY_CONFIRM_S, 120 s) of
# a send — a resend, a rewrite included — so an event comes this long after the last send, as in
# the in-process tests.
PAST_CONFIRM_S = 130


def _targets(data: dict[str, Any]) -> list[str]:
    target = data.get("entity_id") or []
    return [target] if isinstance(target, str) else list(target)


def relay_cmds(r: Run, since: float) -> list[bool]:
    """Every on/off the plugin sent the relay since ``since``."""
    return [
        service == "turn_on"
        for t, domain, service, data in r.ha.calls
        if t >= since
        and domain == "switch"
        and service in ("turn_on", "turn_off")
        and RELAY in _targets(data)
    ]


def entity_cmds(r: Run, since: float) -> list[tuple[str, object]]:
    """Every write to the setpoint entity, the heating switch and the external-control switch."""
    out: list[tuple[str, object]] = []
    for t, domain, service, data in r.ha.calls:
        if t < since:
            continue
        targets = _targets(data)
        if domain == "number" and service == "set_value" and SETPOINT in targets:
            out.append(("setpoint", float(data.get("value"))))
        elif domain == "switch" and service in ("turn_on", "turn_off"):
            if CH_SWITCH in targets:
                out.append(("ch", service == "turn_on"))
            elif EXTERNAL in targets:
                out.append(("external", service == "turn_on"))
    return out


async def options_walk(r: Run, answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The plugin's control options saved again, each step with its current values and the
    given changes; the confirmation steps ticked. Returns the last answer of the flow."""
    ha = r.ha
    entry = await ha.entry("vtherm_smart_boiler")
    _s, d = await ha.rest(
        "POST",
        "/api/config/config_entries/options/flow",
        {"handler": entry["entry_id"], "show_advanced_options": True},
    )
    fid = d["flow_id"]
    path = f"/api/config/config_entries/options/flow/{fid}"
    _s, d = await ha.rest("POST", path, {"next_step_id": "control"})
    while d.get("type") == "form":
        step = d["step_id"]
        if step == "confirm_blocking":
            r.note(f"options: 'this change stops control': {d.get('description_placeholders')}")
            _s, d = await ha.rest("POST", path, {"save_anyway": True})
            continue
        if step == "control_return_confirm":
            _s, d = await ha.rest("POST", path, {"understood": True})
            continue
        body: dict[str, Any] = {}
        for field in d.get("data_schema") or []:
            name = field["name"]
            value = (field.get("description") or {}).get("suggested_value", field.get("default"))
            if value is not None:
                body[name] = value
        body |= answers.get(step, {})
        body = {k: v for k, v in body.items() if v is not None}
        _s, d = await ha.rest("POST", path, body)
        if d.get("errors"):
            await ha.rest("DELETE", path)
            return d
    if d.get("type") != "create_entry":
        await ha.rest("DELETE", path)
        return {"errors": {"not_saved": str(d)[:200]}}
    await asyncio.sleep(15)  # the entry reloads
    r.ent.update(await ha.entities())
    return d


async def rooms_call(r: Run, call: bool) -> None:
    """The rooms all calling (3 K below their setpoints) or all satisfied (setpoints lowered)."""
    for zone, target in ZONES:
        if call:
            await r.sim("set_room_temperature", zone=zone, temperature=target - 3.0)
            await r.ha.call(
                "climate", "set_temperature", entity_id=f"climate.{zone}", temperature=target
            )
        else:
            await r.ha.call(
                "climate", "set_temperature", entity_id=f"climate.{zone}", temperature=15.0
            )


async def relay_is(r: Run, on: bool) -> bool:
    return await r.s(RELAY) == ("on" if on else "off")


# --- the relay path (instance 6, --config relay) ----------------------------------------------


async def R1(r: Run):
    """the relay follows VT's zones at once, both ways"""
    await rooms_call(r, True)
    await r.switch(True)
    on = await r.ha.until(lambda: relay_is(r, True), 120, 1)
    r.check(on is not None, f"relay on with the rooms calling ({on and round(on)} s)")
    await rooms_call(r, False)
    t = time.time()
    off = await r.ha.until(lambda: relay_is(r, False), 400, 1)
    r.check(
        off is not None,
        f"relay off once the rooms are satisfied ({off and round(off)} s; VT's cycle decides when the valves close)",
    )
    await rooms_call(r, True)
    on = await r.ha.until(lambda: relay_is(r, True), 400, 1)
    r.check(on is not None, f"relay on again with the call ({on and round(on)} s)")
    r.note(f"relay commands: {relay_cmds(r, t)}")


async def R2(r: Run):
    """the relay restarts, seen unavailable: the command again at once, counted, no alarm"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.until(lambda: relay_is(r, True), 120, 1)
    await r.ha.wait(PAST_CONFIRM_S)
    t = time.time()
    await r.sim("relay_restart", reported=True)
    back = await r.ha.until(lambda: relay_is(r, True), 90, 1)
    r.check(back is not None, f"on again {back and round(back)} s after the restart")
    r.check(True in relay_cmds(r, t), f"sent again: {relay_cmds(r, t)}")
    r.check(await r.alarms_on() == [], f"alarms {await r.alarms_on()}")
    r.check(await r.s("control_state") != "handed_back", f"state {await r.s('control_state')}")


async def R3(r: Run):
    """the relay restarts unseen, found off while commanded on: the command again"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.until(lambda: relay_is(r, True), 120, 1)
    await r.ha.wait(PAST_CONFIRM_S)
    t = time.time()
    await r.sim("relay_restart", reported=False)
    back = await r.ha.until(lambda: relay_is(r, True), 90, 1)
    r.check(
        back is not None and True in relay_cmds(r, t),
        f"on again {back and round(back)} s after: {relay_cmds(r, t)}",
    )
    r.check(await r.s("control_state") != "handed_back", f"state {await r.s('control_state')}")


async def R4(r: Run):
    """the relay switched by an automation while available: written back once, then the plugin steps aside"""
    await rooms_call(r, False)
    await r.switch(True)
    await r.ha.until(lambda: relay_is(r, False), 400, 1)
    await r.ha.wait(30)
    t = time.time()
    await r.sim("relay_switch", on=True)
    back = await r.ha.until(lambda: relay_is(r, False), 60, 1)
    r.check(
        back is not None, f"written back off {back and round(back)} s after: {relay_cmds(r, t)}"
    )
    await r.ha.wait(PAST_CONFIRM_S)
    t2 = time.time()
    await r.sim("relay_switch", on=True)
    aside = await r.ha.until(lambda: _control_state(r, "handed_back"), 60, 1)
    st = await r.st("control_state")
    r.note(
        f"after the second: {st['state']}, latched {st['attributes'].get('latched_by')}, commands {relay_cmds(r, t2)}, relay {await r.s(RELAY)}"
    )
    r.check(aside is not None, f"stepped aside {aside and round(aside)} s after the second")
    r.check(relay_cmds(r, t2) == [False], f"the rest state written once: {relay_cmds(r, t2)}")
    await r.sim("relay_switch", on=True)  # the automation again
    await r.ha.wait(120)
    r.check(relay_cmds(r, t2) == [False], "the relay left alone after the step aside")
    r.check(await relay_is(r, True), "the automation's value kept")


async def _control_state(r: Run, state: str) -> bool:
    return await r.s("control_state") == state


async def R5(r: Run):
    """the relay loses its Wi-Fi for 8 min: nothing written meanwhile, an alarm after 5 min, the command again on return"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.until(lambda: relay_is(r, True), 120, 1)
    await r.ha.wait(30)
    t = time.time()
    await r.sim("relay_wifi_loss", minutes=8)
    await rooms_call(r, False)
    await r.ha.wait(240)
    r.check(await r.alarms_on() == [], f"no alarm in 4 min: {await r.alarms_on()}")
    await r.ha.wait(90)
    alarms = await r.alarms_on()
    r.check(bool(alarms), f"an alarm after 5 min: {alarms}")
    r.note(f"issues {[i['issue_id'] for i in await r.ha.issues()]}")
    r.check(
        await r.s("control_state") != "handed_back",
        f"not handed back: {await r.s('control_state')}",
    )
    await r.ha.wait(200)
    off = await r.ha.until(lambda: relay_is(r, False), 120, 1)
    r.check(off is not None, f"back: the command (off) at once — {relay_cmds(r, t)}")


async def R6(r: Run):
    """VT's activation delay of 120 s on the relay path"""
    d = await options_walk(r, {"control_relay_behaviour": {"activation_delay_s": 120}})
    r.note(f"options {d.get('type')} {d.get('errors')}")
    await rooms_call(r, False)
    await r.switch(True)
    await r.ha.until(lambda: relay_is(r, False), 400, 1)
    await r.ha.wait(20)
    await rooms_call(r, True)
    opened = await r.ha.until(lambda: _any_valve(r), 400, 1)
    t = time.time()
    on = await r.ha.until(lambda: relay_is(r, True), 300, 1)
    waited = None if on is None else round(time.time() - t)
    r.check(
        waited is not None and waited >= 115,
        f"the relay on {waited} s after the first valve opened ({opened and round(opened)} s after the call)",
    )
    await r.switch(False)
    await r.ha.wait(10)
    await options_walk(r, {"control_relay_behaviour": {"activation_delay_s": 0}})


async def _any_valve(r: Run) -> bool:
    return any([await r.s(f"switch.boiler_sim_{zone}_valve") == "on" for zone, _t in ZONES])


async def R7(r: Run):
    """a planned restart (the entry reloaded): the rest state at the stop, the last command again at once"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.until(lambda: relay_is(r, True), 120, 1)
    await r.ha.wait(30)
    entry = await r.ha.entry("vtherm_smart_boiler")
    t = time.time()
    await r.ha.rest("POST", f"/api/config/config_entries/entry/{entry['entry_id']}/reload")
    await r.ha.wait(30)
    c = relay_cmds(r, t)
    r.check(c[:1] == [False] and True in c, f"off at the stop, then on again: {c}")
    r.check(await relay_is(r, True), "on")


async def R8(r: Run):
    """the relay path without the separate-contact tick: control blocked, nothing reaches the relay"""
    d = await options_walk(r, {"control_relay": {"relay_is_separate_contact": False}})
    if d.get("errors"):
        r.check(True, f"refused where it is entered: {d['errors']}")
    else:
        t = time.time()
        res = await r.switch(True)
        await r.ha.wait(60)
        r.check(
            await r.s("control") == "off" and relay_cmds(r, t) == [],
            f"refused, nothing to the relay; {res}, blockers {await r.attr('control', 'blockers')}",
        )
    await options_walk(r, {"control_relay": {"relay_is_separate_contact": True}})


# --- the entity path (instance 7, --config entity) ---------------------------------------------


async def N1(r: Run):
    """a held device restarts (out of reach 20 s, its values lost): sent again once back, no alarm"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.wait(120)
    t = time.time()
    await r.sim("restart_device", seconds=20)
    await r.ha.wait(60)
    c = entity_cmds(r, t)
    r.check(
        any(k == "setpoint" for k, _v in c) and any(k == "ch" for k, _v in c),
        f"setpoint and heating switch sent again: {c}",
    )
    r.check(
        [a for a in await r.alarms_on() if a in ("alarm_outside_change", "alarm_write_ignored")]
        == [],
        f"alarms {await r.alarms_on()}",
    )
    r.check(await r.s("control_state") != "handed_back", f"state {await r.s('control_state')}")


async def N2(r: Run):
    """the device restarting at a hand-back (its entities away 90 s): shown failed, kept, made once it is back"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.wait(120)
    await r.sim("restart_device", seconds=90)
    await r.ha.wait(5)
    t = time.time()
    await r.switch(False)
    await r.ha.wait(10)
    r.check(
        await r.s("alarm_hand_back_failed") == "on",
        "hand-back failed alarm while the device is away",
    )
    await r.ha.wait(140)
    c = entity_cmds(r, t)
    r.check(("setpoint", 0.0) in c, f"the hand-back made once back: {c}")
    r.check(await r.s("alarm_hand_back_failed") == "off", "alarm cleared")


async def N6(r: Run):
    """the setpoint entity alone away at a hand-back, the device holding its value (the
    in-process test's case): shown failed, kept, the lowest and the hand-back value once it is back"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.wait(120)
    await r.sim("fail_signal", signal="flow_setpoint")
    await r.ha.wait(5)
    t = time.time()
    await r.switch(False)
    await r.ha.wait(10)
    r.check(
        await r.s("alarm_hand_back_failed") == "on",
        "hand-back failed alarm while the entity is away",
    )
    await r.ha.wait(120)
    r.check(("setpoint", 0.0) not in entity_cmds(r, t), "nothing written to it meanwhile")
    await r.sim("fail_signal", signal="flow_setpoint", failed=False)
    t2 = time.time()
    await r.ha.wait(80)
    sp = [v for k, v in entity_cmds(r, t2) if k == "setpoint"]
    r.check(sp[-1:] == [0.0], f"the hand-back made once back: {entity_cmds(r, t2)}")
    await r.ha.wait(130)
    r.note(
        f"after the retry checks: alarm {await r.s('alarm_hand_back_failed')}, confirmation {await r.attr('control_state', 'hand_back_confirmation')}"
    )
    r.check(await r.s("alarm_hand_back_failed") == "off", "alarm cleared")


async def N3(r: Run):
    """a setpoint the boiler stores, or might (persistent, unknown): control never writes it"""
    for write_type in ("persistent", "unknown"):
        d = await options_walk(r, {"control_entity": {"write_type": write_type}})
        if d.get("errors"):
            r.check(True, f"{write_type}: refused where it is entered: {d['errors']}")
            continue
        t = time.time()
        res = await r.switch(True)
        await r.ha.wait(60)
        r.check(
            await r.s("control") == "off"
            and not [c for c in entity_cmds(r, t) if c[0] == "setpoint"],
            f"{write_type}: refused, never written; {res}, blockers {await r.attr('control', 'blockers')}",
        )
    await options_walk(r, {"control_entity": {"write_type": "held"}})


async def N4(r: Run):
    """without a heating switch control is refused (a low setpoint is not "off")"""
    d = await options_walk(r, {"control_entity": {"ch_entity": None, "ch_write_type": "unknown"}})
    if d.get("errors"):
        r.check(True, f"refused where it is entered: {d['errors']}")
    else:
        t = time.time()
        res = await r.switch(True)
        await r.ha.wait(60)
        r.check(
            await r.s("control") == "off" and entity_cmds(r, t) == [],
            f"refused, nothing written; {res}, blockers {await r.attr('control', 'blockers')}",
        )
    await options_walk(r, {"control_entity": {"ch_entity": CH_SWITCH, "ch_write_type": "held"}})


async def _zones_unknown(r: Run, minutes: float) -> list[dict[str, Any]]:
    entries = [await r.ha.entry("versatile_thermostat", z) for z, _t in ZONES]
    for e in entries:
        await r.ha.ws_cmd(
            {"type": "config_entries/disable", "entry_id": e["entry_id"], "disabled_by": "user"}
        )
    await r.ha.wait(minutes * 60)
    return entries


async def _zones_back(r: Run, entries: list[dict[str, Any]]) -> None:
    for e in entries:
        await r.ha.ws_cmd(
            {"type": "config_entries/disable", "entry_id": e["entry_id"], "disabled_by": None}
        )
    await r.ha.wait(45)
    await r.zones()


async def N5(r: Run):
    """every zone unknown on the entity path, with and without the own-room-controller tick"""
    for tick in (True, False):
        await options_walk(r, {"control_entity": {"own_room_controller": tick}})
        await rooms_call(r, True)
        await r.switch(True)
        await r.ha.wait(60)
        t = time.time()
        entries = await _zones_unknown(r, 11.5)
        st = await r.st("control_state")
        c = entity_cmds(r, t)
        r.note(f"tick {tick}: {st['state']} {st['attributes'].get('reasons')}, writes {c[-4:]}")
        if tick:
            r.check(
                st["state"] == "handed_back" and ("setpoint", 0.0) in c,
                "with the tick: handed back to the boiler's own controller",
            )
        else:
            r.check(
                st["state"] != "handed_back" and ("setpoint", 0.0) not in c,
                "without it: no hand-back, heating off",
            )
        await _zones_back(r, entries)
        await r.switch(False)
        await r.ha.wait(10)
    await options_walk(r, {"control_entity": {"own_room_controller": False}})


# --- a stand-alone gateway (instance 8, --config standalone) -----------------------------------


async def S1(r: Run):
    """a stand-alone gateway: the hand-back stops heating, as the control switch says"""
    r.check(
        await r.attr("control", "hand_back_effect") == "heating_stops",
        f"the switch says: {await r.attr('control', 'hand_back_effect')}",
    )
    await rooms_call(r, True)
    await r.switch(True)
    got = await r.ha.until(lambda: _ch_active(r, True), 300, 2)
    r.check(got is not None, f"the boiler heats under control ({got and round(got)} s)")
    await r.switch(False)
    stopped = await r.ha.until(lambda: _ch_active(r, False), 60, 1)
    r.check(
        stopped is not None, f"heating stops after the hand-back ({stopped and round(stopped)} s)"
    )


async def _ch_active(r: Run, on: bool) -> bool:
    return await r.s("binary_sensor.boiler_sim_ch_active") == ("on" if on else "off")


async def S2(r: Run):
    """every zone unknown with a stand-alone gateway: held through recognition, then heating off, no hand-back"""
    await rooms_call(r, True)
    await r.switch(True)
    await r.ha.wait(60)
    t = time.time()
    entries = await _zones_unknown(r, 11.5)
    st = await r.st("control_state")
    sp = r.cmds(t, "setpoint")
    ch = r.cmds(t, "ch")
    r.check(
        st["state"] == "idle" and ch and ch[-1][1] is False,
        f"heating off: {st['state']}, CH {ch[-1:]}",
    )
    r.check(0 not in [v for _k, v in sp], f"no hand-back: {sp[-3:]}")
    await _zones_back(r, entries)


SCENARIOS.update(
    {f.__name__: f for f in (R1, R2, R3, R4, R5, R6, R7, R8, N1, N2, N3, N4, N5, N6, S1, S2)}
)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
