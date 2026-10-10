"""J4's scenarios on the relay path, the entity path and a stand-alone gateway (test instances
deployed with ``--config relay``, ``entity`` and ``standalone``; docs/test-reports/README.md).

Usage: HA_INSTANCE=N scripts/env.sh python devenv/j4/paths.py ID... — the same runner as
run.py (its clean state, its results file), with the commands to the relay and the entities
captured from Home Assistant's service calls as run.py captures the gateway's.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from datetime import UTC, datetime
from itertools import pairwise
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


async def options_walk(r: Run, answers: dict[str, Any], menu: str = "control") -> dict[str, Any]:
    """A section of the plugin's options — control by default — saved again, each step with its
    current values and the given changes (a list for a step met more than once, such as each
    zone's: one change each, in order); the confirmation steps ticked. Returns the last answer
    of the flow."""
    ha = r.ha
    entry = await ha.entry("vtherm_smart_boiler")
    _s, d = await ha.rest(
        "POST",
        "/api/config/config_entries/options/flow",
        {"handler": entry["entry_id"], "show_advanced_options": True},
    )
    fid = d["flow_id"]
    path = f"/api/config/config_entries/options/flow/{fid}"
    _s, d = await ha.rest("POST", path, {"next_step_id": menu})
    met: dict[str, int] = {}
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
        change = answers.get(step, {})
        if isinstance(change, list):
            n = met.get(step, 0)
            met[step] = n + 1
            change = change[n] if n < len(change) else {}
        body |= change
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


# --- the relay's own settings (instance 6, the simulator's relay_setup and set_lockout) --------

PROFILE_LOCKOUT_S = 180.0  # condensing_small's restart lockout (sim/…/profiles.py)


async def fresh_control(r: Run) -> None:
    """The plugin's control memory wiped — the day's one rewrite and the untraced restarts it
    keeps across sessions — so a scenario does not inherit an earlier one's (as for D5)."""
    if await r.s("control") == "on":
        await r.switch(False)
        await r.ha.wait(10)
    await r.ha.call(
        "j4_faults",
        "restart_with_stores",
        main={"monitoring_since": 0.0, "control": {}, "control_store": 1},
        control={},
    )
    await r.ha.wait(30)
    r.ent.update(await r.ha.entities())


async def relay_setup(r: Run, declared: dict[str, Any], **relay: Any) -> None:
    """The simulated relay given its own settings, and the plugin's relay options declaring
    ``declared``; the control memory fresh."""
    await r.sim("relay_setup", **relay)
    d = await options_walk(r, {"control_relay": declared})
    if d.get("errors"):
        raise RuntimeError(f"relay options not saved: {d['errors']}")
    await fresh_control(r)


async def relay_defaults(r: Run) -> None:
    """Back to instance 6's relay: no timer, off after a power cut, its state reported."""
    if await r.s("control") == "on":
        await r.switch(False)
        await r.ha.wait(10)
    await r.sim(
        "relay_setup",
        start_up="off",
        off_timer_min=0,
        timer_restarts_on_repeat=True,
        assumed_state=False,
    )
    await r.sim("set_lockout", seconds=PROFILE_LOCKOUT_S)
    await options_walk(
        r,
        {
            "control_relay": {
                "relay_power_on_state": "off",
                "relay_off_timer": "none",
                "relay_repeat_s": None,
            }
        },
    )


async def relay_offs(r: Run, since: float) -> int:
    """How often the relay went from on to off since ``since``, as the recorder kept it."""
    start = datetime.fromtimestamp(since, UTC).isoformat()
    _s, h = await r.ha.rest(
        "GET",
        f"/api/history/period/{start}?filter_entity_id={RELAY}&minimal_response&no_attributes",
    )
    states = [x["state"] for x in (h[0] if h else [])]
    return sum(1 for a, b in pairwise(states) if a == "on" and b == "off")


async def relay_on_under_control(r: Run) -> None:
    await rooms_call(r, True)
    await r.switch(True)
    # VT opens the valves at its next cycle — up to its cycle length, 5 min — after the call;
    # a cycle that began before it may still give a short pulse. A whole cycle later the rooms,
    # 3 K below their setpoints, keep the valves open: the relay is on for good.
    for _ in range(2):
        on = await r.ha.until(lambda: relay_is(r, True), 400, 1)
        if on is None:
            raise RuntimeError("the relay did not come on under control")
        await r.ha.wait(330)
    if not await relay_is(r, True):
        raise RuntimeError("the relay did not stay on under control")


async def _issue(r: Run, key: str) -> dict[str, Any] | None:
    return next(
        (i for i in await r.ha.issues() if i["issue_id"].startswith(key)),
        None,
    )


async def R9(r: Run):
    """a declared 10-min switch-off timer that an "on" restarts (Tasmota): renewed, never lapses"""
    try:
        await relay_setup(
            r,
            {"relay_off_timer": "minutes", "relay_off_timer_min": 10},
            off_timer_min=10,
            timer_restarts_on_repeat=True,
        )
        await relay_on_under_control(r)
        t = time.time()
        await r.ha.wait(1800)
        c = relay_cmds(r, t)
        offs = await relay_offs(r, t)
        r.check(c.count(False) == 0 and c.count(True) >= 5, f"renewed, never off: {c}")
        r.check(offs == 0, f"its timer never lapsed ({offs} switch-offs)")
        r.check(await r.alarms_on() == [], f"alarms {await r.alarms_on()}")
        r.check(await r.s("control_state") == "heating", f"state {await r.s('control_state')}")
        r.check(await _issue(r, "relay_timer_seen") is None, "declared: nothing to ask")
    finally:
        await relay_defaults(r)


async def R10(r: Run):
    """a declared 11-min timer that runs from the first "on" (a Shelly's auto-off): each lapse
    answered at once, never counted. 11, not 10: a lapse at a multiple of the 5-min renewal
    comes with one, and the renewal hides it from Home Assistant (PB-25)"""
    try:
        await relay_setup(
            r,
            {"relay_off_timer": "minutes", "relay_off_timer_min": 11},
            off_timer_min=11,
            timer_restarts_on_repeat=False,
        )
        await relay_on_under_control(r)
        t = time.time()
        await r.ha.wait(1800)
        offs = await relay_offs(r, t)
        r.check(offs >= 2, f"its timer lapsed {offs} times in 30 min")
        r.check(await relay_is(r, True), "on, each lapse answered")
        r.check(await r.alarms_on() == [], f"alarms {await r.alarms_on()}")
        r.check(await r.s("control_state") == "heating", f"state {await r.s('control_state')}")
        r.note(f"commands {relay_cmds(r, t)}")
    finally:
        await relay_defaults(r)


async def R11(r: Run):
    """the timer declared "I don't know", the relay's own 10-min timer restarted by "on": kept on
    by the repeats; "off" not repeated"""
    try:
        await relay_setup(
            r, {"relay_off_timer": "unknown"}, off_timer_min=10, timer_restarts_on_repeat=True
        )
        await relay_on_under_control(r)
        t = time.time()
        await r.ha.wait(1800)
        offs = await relay_offs(r, t)
        times = [
            x
            for x, domain, service, data in r.ha.calls
            if x >= t and service == "turn_on" and RELAY in _targets(data)
        ]
        gaps = [round(b - a) for a, b in pairwise(times)]
        r.check(offs == 0, f"never lapsed ({offs} switch-offs); repeats {gaps} s apart")
        r.check(bool(gaps) and max(gaps) <= 310, "repeated at least every 5 min")
        await rooms_call(r, False)
        t2 = time.time()
        await r.ha.wait(1200)
        c = relay_cmds(r, t2)
        r.check(c.count(False) == 1 and c[-1:] == [False], f"off once, not repeated: {c}")
    finally:
        await relay_defaults(r)


async def R12(r: Run):
    """the relay's state after a power cut (seen 10 s unavailable): the command again where it
    differs, nothing where it matches"""
    try:
        for start_up, commanded, sent in (
            ("off", True, [True]),
            ("on", False, [False]),
            ("last", True, []),
            ("last", False, []),
        ):
            await relay_setup(r, {"relay_power_on_state": "unknown"}, start_up=start_up)
            await rooms_call(r, commanded)
            await r.switch(True)
            await r.ha.until(lambda c=commanded: relay_is(r, c), 400, 1)
            await r.ha.wait(PAST_CONFIRM_S)
            t = time.time()
            await r.sim("relay_restart", reported=True)
            await r.ha.wait(40)
            c = relay_cmds(r, t)
            r.check(
                c == sent and await relay_is(r, commanded),
                f"{start_up}, commanded {'on' if commanded else 'off'}: sent {c}, relay {await r.s(RELAY)}",
            )
            await r.switch(False)
            await r.ha.wait(10)
    finally:
        await relay_defaults(r)


async def R13(r: Run):
    """an optimistic relay entity (assumed_state): controlled without confirmation, the command
    repeated blindly, an unseen restart undone within the repeat"""
    try:
        await relay_setup(r, {}, assumed_state=True)
        await relay_on_under_control(r)
        await r.ha.wait(20)
        conf = await r.attr("control", "confirmation")
        check = await r.attr("control_state", "relay_check")
        r.check(
            conf == "controlled_without_confirmation" and check == "unverified",
            f"shown: {conf}, relay check {check}",
        )
        t = time.time()
        await r.sim("relay_restart", reported=False)
        back = await r.ha.until(lambda: relay_is(r, True), 330, 2)
        r.check(
            back is not None,
            f"the blind repeat put it back ({back and round(back)} s): {relay_cmds(r, t)}",
        )
        await rooms_call(r, False)
        t2 = time.time()
        await r.ha.wait(660)
        c = relay_cmds(r, t2)
        r.check(c[-3:] == [False, False, False], f'"off" repeated too: {c}')
        r.check(await r.s("alarm_outside_change") == "off", "no outside change")
    finally:
        await relay_defaults(r)


async def R14(r: Run):
    """a 20-min restart lockout against the 30-min proof of heat: the burner waits it out, no
    "boiler not responding" alarm"""
    try:
        await r.sim("set_lockout", seconds=1200)
        await fresh_control(r)
        await relay_on_under_control(r)
        fired = await r.ha.until(lambda: _flame(r, True), 600, 5)
        r.check(fired is not None, f"the burner fires under control ({fired and round(fired)} s)")
        await rooms_call(r, False)
        await r.ha.until(lambda: relay_is(r, False), 600, 2)
        await r.ha.until(lambda: _flame(r, False), 120, 2)
        await r.ha.wait(60)
        await rooms_call(r, True)
        await r.ha.until(lambda: relay_is(r, True), 600, 2)
        t = time.time()
        alarm_seen = False
        fired_after = None
        while time.time() - t < 1800:
            if fired_after is None and await _flame(r, True):
                fired_after = time.time() - t
            if await r.s("alarm_boiler_not_responding") == "on":
                alarm_seen = True
            await r.ha.wait(10)
        r.check(
            fired_after is not None,
            f"fired {fired_after and round(fired_after / 60, 1)} min after the relay",
        )
        r.check(not alarm_seen, "no 'boiler not responding' within the 30 min")
        r.check(
            await r.attr("control_state", "boiler_heats") == "heats",
            f"boiler heats: {await r.attr('control_state', 'boiler_heats')}",
        )
    finally:
        await relay_defaults(r)


async def _flame(r: Run, on: bool) -> bool:
    return await r.s("binary_sensor.boiler_sim_flame") == ("on" if on else "off")


async def R15(r: Run):
    """an "inching" relay switching itself off 2 min after each "on", the timer "I don't know":
    each counted, the fourth steps aside, the latch issue names it"""
    try:
        await relay_setup(
            r,
            {"relay_off_timer": "unknown", "relay_rest_state": "off"},
            off_timer_min=2,
            timer_restarts_on_repeat=False,
        )
        # Not relay_on_under_control: this relay never stays on — it is the point.
        await rooms_call(r, True)
        await r.switch(True)
        on = await r.ha.until(lambda: relay_is(r, True), 400, 1)
        r.check(on is not None, f"the relay on under control ({on and round(on)} s)")
        aside = await r.ha.until(lambda: _control_state(r, "handed_back"), 1500, 5)
        r.check(
            aside is not None, f"stepped aside {aside and round(aside / 60, 1)} min into control"
        )
        await r.ha.wait(30)
        found = await _issue(r, "control_latched")
        r.check(
            found is not None
            and found.get("translation_key") == "control_latched_relay_short_timer_off"
            and (found.get("translation_placeholders") or {}).get("minutes") == "2",
            f"the latch issue: {found and (found.get('translation_key'), found.get('translation_placeholders'))}",
        )
        t = time.time()
        await r.ha.wait(600)
        r.check(relay_cmds(r, t) == [], f"left alone: {relay_cmds(r, t)}")
    finally:
        await relay_defaults(r)


async def R16(r: Run):
    """an undeclared 11-min timer that runs from the first "on": recognised at its second lapse,
    heating goes on, a warning asks to declare it"""
    try:
        await relay_setup(
            r, {"relay_off_timer": "unknown"}, off_timer_min=11, timer_restarts_on_repeat=False
        )
        await relay_on_under_control(r)
        t = time.time()
        found = None
        while time.time() - t < 2700 and found is None:
            await r.ha.wait(60)
            found = await _issue(r, "relay_timer_seen")
        offs = await relay_offs(r, t)
        r.check(
            found is not None
            and found.get("severity") == "warning"
            and (found.get("translation_placeholders") or {}).get("minutes") == "11",
            f"recognised after {offs} lapses: {found and (found.get('severity'), found.get('translation_placeholders'))}",
        )
        await r.ha.wait(900)
        r.check(
            await r.s("control_state") == "heating",
            f"heating goes on: {await r.s('control_state')}",
        )
        r.check(await r.s("alarm_outside_change") == "off", "no outside change")
    finally:
        await relay_defaults(r)


async def R17(r: Run):
    """every zone unknown on the relay path with the own-room-controller tick: the rest state
    "on" hands the boiler back to its own controller, "off" switches heating off"""
    try:
        for rest, back in (("on", True), ("off", False)):
            await relay_setup(r, {"relay_rest_state": rest, "own_room_controller": True})
            await relay_on_under_control(r)
            entries = await _zones_unknown(r, 11.5)
            st = await r.st("control_state")
            issue = await _issue(r, "no_zone_known")
            r.check(
                st["state"] == ("handed_back" if back else "idle")
                and await relay_is(r, back)
                and issue is not None
                and issue.get("translation_key")
                == ("no_zone_known_handed_back" if back else "no_zone_known_off"),
                f"rest {rest}: {st['state']}, relay {await r.s(RELAY)}, issue {issue and issue.get('translation_key')}",
            )
            await _zones_back(r, entries)
            await r.switch(False)
            await r.ha.wait(10)
    finally:
        await options_walk(
            r, {"control_relay": {"relay_rest_state": "off", "own_room_controller": False}}
        )
        await relay_defaults(r)


async def R18(r: Run):
    """VT's activation delay of 120 s on the relay path: a start waits for it"""
    try:
        d = await options_walk(r, {"control_relay_behaviour": {"activation_delay_s": 120}})
        if d.get("errors"):
            raise RuntimeError(f"options not saved: {d['errors']}")
        await r.switch(True)
        waits = []
        for _ in range(2):
            await rooms_call(r, False)
            await r.ha.until(lambda: relay_is(r, False), 420, 5)
            # Past the delay since any earlier pulse: a wait it started runs on through a drop
            # (VT's rule), and would shorten the one measured here.
            await r.ha.wait(150)
            await rooms_call(r, True)
            await r.ha.until(lambda: _any_valve(r), 420, 1)
            t_call = time.time()
            on = await r.ha.until(lambda: relay_is(r, True), 300, 1)
            waits.append(None if on is None else round(time.time() - t_call))
        r.check(
            all(w is not None and w >= 115 for w in waits),
            f"each start waited at least 120 s: {waits}",
        )
    finally:
        if await r.s("control") == "on":
            await r.switch(False)
            await r.ha.wait(10)
        await options_walk(r, {"control_relay_behaviour": {"activation_delay_s": 0}})


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


async def N7(r: Run):
    """a switch that enables external control as the hand-back: on with control, off at the
    hand-back, on again with control"""
    try:
        d = await options_walk(
            r,
            {
                "control_entity": {
                    "hand_back": "switch",
                    "hand_back_entity": EXTERNAL,
                    "hand_back_entity_write_type": "held",
                }
            },
        )
        if d.get("errors"):
            raise RuntimeError(f"options not saved: {d['errors']}")
        await rooms_call(r, True)
        t = time.time()
        await r.switch(True)
        on = await r.ha.until(lambda: _is(r, EXTERNAL, "on"), 90, 1)
        r.check(on is not None, f"external control on with control ({on and round(on)} s)")
        await r.ha.wait(30)
        await r.switch(False)
        off = await r.ha.until(lambda: _is(r, EXTERNAL, "off"), 60, 1)
        r.check(off is not None, f"off at the hand-back ({off and round(off)} s)")
        await r.ha.wait(30)
        r.check(await r.s("alarm_hand_back_failed") == "off", "the hand-back confirmed")
        r.note(f"writes {entity_cmds(r, t)}")
        await r.switch(True)
        again = await r.ha.until(lambda: _is(r, EXTERNAL, "on"), 60, 1)
        r.check(again is not None, f"on again with control ({again and round(again)} s)")
    finally:
        if await r.s("control") == "on":
            await r.switch(False)
            await r.ha.wait(10)
        await options_walk(r, {"control_entity": {"hand_back": "value", "hand_back_value": 0}})
        await r.ha.call("switch", "turn_on", entity_id=EXTERNAL)


async def _is(r: Run, entity_id: str, state: str) -> bool:
    return await r.s(entity_id) == state


async def N8(r: Run):
    """a timeout hand-back on an expiring setpoint: the lowest, then nothing — the device's own
    timeout releases it; a device that keeps the value after all: the alarm"""
    try:
        await r.sim("set_write_type", write_type="expiring")
        d = await options_walk(
            r,
            {"control_entity": {"write_type": "expiring", "hand_back": "timeout"}},
        )
        if d.get("errors"):
            raise RuntimeError(f"options not saved: {d['errors']}")
        await rooms_call(r, True)
        await r.switch(True)
        await r.ha.wait(120)
        t = time.time()
        await r.ha.wait(60)
        kept = [v for k, v in entity_cmds(r, t) if k == "setpoint"]
        r.check(len(kept) >= 1, f"kept alive while controlling: {kept}")
        t = time.time()
        await r.switch(False)
        await r.ha.wait(300)
        sp = [v for k, v in entity_cmds(r, t) if k == "setpoint"]
        r.check(sp == [20.0], f"the lowest, then nothing: {sp}")
        r.check(await r.s("alarm_hand_back_failed") == "off", "released by its timeout: no alarm")
        r.note(f"control state {await r.s('control_state')}")
        # The device keeps the value after all (declared expiring, held in fact).
        await r.sim("set_write_type", write_type="held")
        await r.switch(True)
        await r.ha.wait(120)
        t = time.time()
        await r.switch(False)
        alarm = await r.ha.until(lambda: _is(r, "alarm_hand_back_failed", "on"), 420, 5)
        r.check(
            alarm is not None and 200 <= alarm <= 330,
            f"not released: the alarm {alarm and round(alarm)} s after the hand-back (its timeout + 3 min)",
        )
        sp = [v for k, v in entity_cmds(r, t) if k == "setpoint"]
        r.check(sp == [20.0], f"nothing written again: {sp}")
    finally:
        if await r.s("control") == "on":
            await r.switch(False)
            await r.ha.wait(10)
        await r.sim("set_write_type", write_type="held")
        await options_walk(
            r,
            {"control_entity": {"write_type": "held", "hand_back": "value", "hand_back_value": 0}},
        )


async def U1(r: Run, outdoor: float = -5.0, emitters: tuple[str, ...] = ("underfloor",) * 3):
    """underfloor heating on an unmixed loop, the circuit's maximum 40 °C below what the curve
    asks at −5 °C: every setpoint held at the maximum, said so; the measured flow over it by
    the boiler's stop hysteresis at most; the too-hot alarm (45 °C, pre-filled) stays off"""
    try:
        d = await options_walk(r, {"circuit": {"max_flow": 40}}, menu="circuit")
        if d.get("errors"):
            raise RuntimeError(f"circuit not saved: {d['errors']}")
        d = await options_walk(r, {"zone": [{"emitter": e} for e in emitters]}, menu="zones")
        if d.get("errors"):
            raise RuntimeError(f"zones not saved: {d['errors']}")
        await r.sim("set_outdoor", temperature=outdoor)
        await rooms_call(r, True)
        await r.switch(True)
        t = time.time()
        flows: list[float] = []
        capped = False
        while time.time() - t < 6000:  # 100 min
            await r.ha.wait(300)
            flow = await r.s("sensor.boiler_sim_flow")
            with contextlib.suppress(TypeError, ValueError):
                flows.append(float(flow))
            capped = capped or "limit_circuit_max" in (
                await r.attr("control_state", "reasons") or []
            )
        sp = [v for k, v in entity_cmds(r, t) if k == "setpoint"]
        alarm = await r.st("alarm_circuit_too_hot")
        r.check(
            bool(sp) and max(sp) <= 40.0,
            f"setpoints within the maximum: max {max(sp, default=None)}",
        )
        r.check(capped is (outdoor < 0), f"the maximum said so: {capped}")
        r.check(
            bool(flows) and max(flows) <= 45.0,
            f"measured flow at most 45: max {max(flows, default=None)}",
        )
        r.check(
            alarm["state"] == "off"
            and alarm["attributes"].get("limit") == 45.0
            and alarm["attributes"].get("reason") is None,
            f"too-hot alarm off, judged: {alarm['state']}, limit {alarm['attributes'].get('limit')}, reason {alarm['attributes'].get('reason')}",
        )
    finally:
        if await r.s("control") == "on":
            await r.switch(False)
            await r.ha.wait(10)
        await r.sim("set_outdoor", temperature=3.0)
        await options_walk(r, {"zone": [{"emitter": "radiator"}] * 3}, menu="zones")
        await options_walk(
            r,
            {"circuit": {"max_flow": None, "max_flow_alarm": None, "max_flow_alarm_min": None}},
            menu="circuit",
        )


async def U2(r: Run):
    """underfloor sharing the unmixed loop with a radiator at +5 °C: the curve below the
    maximum, nothing held back; the flow and the alarm as in U1"""
    await U1(r, outdoor=5.0, emitters=("underfloor", "underfloor", "radiator"))


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
    {
        f.__name__: f
        for f in (
            *(R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15, R16, R17, R18),
            *(N1, N2, N3, N4, N5, N6, N7, N8, U1, U2),
            *(S1, S2),
        )
    }
)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
