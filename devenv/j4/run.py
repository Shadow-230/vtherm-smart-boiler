"""J4's scenarios on a test Home Assistant instance (docs/test-reports/README.md).

Usage: scripts/env.sh python devenv/j4/run.py ID... — with HA_INSTANCE set (default 1). Each
scenario starts and ends from a clean state; its result is printed and appended, with its
evidence, to research/<date>-j4-results.md (git-ignored) or the file J4_RESULTS names.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import pathlib
import sys
import time
import traceback

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import contextlib

from lib import HA, ROOT, SIGNALS

RESULTS = pathlib.Path(
    os.environ.get("J4_RESULTS")
    or ROOT / "research" / f"{dt.datetime.now(dt.UTC):%Y-%m-%d}-j4-results.md"
)
LOWEST = 20.0
SAFE = [("setpoint", LOWEST), ("ch", True), ("setpoint", 0)]
TRACE = 310
ZONES = (("zone_living", 20.5), ("zone_bedroom", 19.5), ("zone_bath", 22.0))
BASE_CONTROL = {
    "write_path": "opentherm_gw",
    "topology": "gateway_with_thermostat",
    "thermostat_kind": "opentherm",
    "confirmed_entity": "sensor.otgw_sim_boiler_control_setpoint",
    "ch_confirmed_entity": "binary_sensor.otgw_sim_boiler_master_ch_enabled",
}
BASE_CURVE = {
    "design_outdoor": -15.0,
    "design_flow": 55.0,
    "hard_min": 20.0,
    "hard_max": 70.0,
    "activation_delay_s": 0,
    "room": 20.0,
    "offset": 0.0,
    "ceiling_band": 10.0,
    "frost_limit": 5.0,
    "frost_release": 7.0,
}
BASE_BEHAVIOUR = {
    "ramp_k_per_min": 1.0,
    "decision_interval_min": 5.0,
    "off_setpoint": 10.0,
    "count_threshold": 1,
    "learning_pauses": True,
    "comfort_correction": False,
}
BASE_ALARMS = {"write_ignored": "info", "return_after_outside_change": False}


def append_result(text: str) -> None:
    with RESULTS.open("a") as f:
        f.write(text)


class Run:
    def __init__(self, ha: HA, ent: dict[str, str]) -> None:
        self.ha, self.ent = ha, ent
        self.notes: list[str] = []
        self.ok = True

    def check(self, cond: bool, what: str) -> bool:
        self.notes.append(("ok   " if cond else "FAIL ") + what)
        self.ok &= bool(cond)
        return bool(cond)

    def note(self, what: str) -> None:
        self.notes.append("     " + what)

    async def st(self, key: str) -> dict:
        return await self.ha.state(self.ent.get(key, key)) or {"state": None, "attributes": {}}

    async def s(self, key: str):
        return (await self.st(key))["state"]

    async def attr(self, key: str, name: str):
        return (await self.st(key))["attributes"].get(name)

    async def sim(self, service: str, **data):
        return await self.ha.call("boiler_sim", service, **data)

    async def switch(self, on: bool):
        return await self.ha.call(
            "switch", "turn_on" if on else "turn_off", entity_id=self.ent["control"]
        )

    async def override(self) -> bool:
        return bool(await self.attr("sensor.boiler_sim_persistent_writes", "override_active"))

    def cmds(self, t: float, kind: str | None = None):
        return [(k, v) for _t, k, v in self.ha.since(t, kind)]

    async def alarms_on(self) -> list[str]:
        st = await self.ha.states()
        return sorted(
            k
            for k, e in self.ent.items()
            if k.startswith("alarm_") and st.get(e, {}).get("state") == "on"
        )

    async def options(self, control=None, curve=None, behaviour=None, alarms=None, gateway="sim"):
        entry = await self.ha.entry("vtherm_smart_boiler")
        _s, d = await self.ha.rest(
            "POST",
            "/api/config/config_entries/options/flow",
            {"handler": entry["entry_id"], "show_advanced_options": True},
        )
        fid = d["flow_id"]
        steps = [
            {"next_step_id": "control"},
            {k: v for k, v in {**BASE_CONTROL, **(control or {})}.items() if v is not None},
        ]
        for body in steps:
            _s, d = await self.ha.rest(
                "POST", f"/api/config/config_entries/options/flow/{fid}", body
            )
            if d.get("errors") or d.get("type") == "abort":
                await self.ha.rest("DELETE", f"/api/config/config_entries/options/flow/{fid}")
                return d
        while d.get("type") == "form":
            step = d["step_id"]
            if step == "control_return_confirm":
                self.note("options: 'confirm the return by itself' ticked")
                _s, d = await self.ha.rest(
                    "POST", f"/api/config/config_entries/options/flow/{fid}", {"understood": True}
                )
                continue
            if step == "confirm_blocking":
                self.note(
                    f"options: 'this change stops control': {d.get('description_placeholders', {}).get('first')}"
                )
                _s, d = await self.ha.rest(
                    "POST", f"/api/config/config_entries/options/flow/{fid}", {"save_anyway": True}
                )
                continue
            body = {
                "control_gateway": {"gateway_id": gateway},
                "control_curve": {**BASE_CURVE, **(curve or {})},
                "control_behaviour": {**BASE_BEHAVIOUR, **(behaviour or {})},
                "control_alarms": {**BASE_ALARMS, **(alarms or {})},
            }.get(step)
            if body is None:
                return {"unexpected_step": step}
            fields = {f["name"] for f in d.get("data_schema") or []}
            body = {k: v for k, v in body.items() if v is not None and k in fields}
            _s, d = await self.ha.rest(
                "POST", f"/api/config/config_entries/options/flow/{fid}", body
            )
            if d.get("errors"):
                await self.ha.rest("DELETE", f"/api/config/config_entries/options/flow/{fid}")
                return d
        if d.get("type") != "create_entry":
            await self.ha.rest("DELETE", f"/api/config/config_entries/options/flow/{fid}")
            return {"errors": {"not_saved": str(d)[:200]}}
        await asyncio.sleep(15)  # the entry reloads
        return d

    async def zones(self, mode="heat"):
        for zone, target in ZONES:
            await self.ha.call(
                "climate", "set_hvac_mode", entity_id=f"climate.{zone}", hvac_mode=mode
            )
            if mode == "heat":
                await self.ha.call(
                    "climate", "set_temperature", entity_id=f"climate.{zone}", temperature=target
                )

    async def reset(self, options=False):
        ha = self.ha
        if await self.s("control") == "on":
            await self.switch(False)
            await ha.wait(10)
        for sig in SIGNALS:
            await self.sim("fail_signal", signal=sig, failed=False)
        for at in ("gateway", "boiler"):
            await self.sim("ignore_writes", enabled=False, at=at)
            await self.sim("clip_setpoint", at=at)
        await self.sim("refuse_id1", enabled=False)
        await self.sim("force_setpoint")
        for fault in ("low_pressure_fault", "boiler_lockout"):
            await self.sim("set_fault", fault=fault, on=False)
        await self.sim("set_outdoor", temperature=3.0)
        # A room a scenario left cold (E5) or warm warms or cools for hours: back to its target.
        for zone, target in ZONES:
            await self.sim("set_room_temperature", zone=zone, temperature=target)
        await ha.call(
            "select",
            "select_option",
            entity_id="select.central_configuration_central_mode",
            option="Auto",
        )
        await self.zones()
        if options:
            await self.options()
        await ha.wait(20)


# --- scenarios ------------------------------------------------------------------------------


async def B1(r: Run):
    """reload: hand-back, then control resumes as it was"""
    await r.switch(True)
    await r.ha.wait(60)
    r.check(await r.override(), "override held before the reload")
    entry = await r.ha.entry("vtherm_smart_boiler")
    t = time.time()
    await r.ha.rest("POST", f"/api/config/config_entries/entry/{entry['entry_id']}/reload")
    await r.ha.wait(30)
    c = r.cmds(t)
    r.note(f"commands: {c}")
    r.check(("setpoint", 0) in c, "the reload handed back (setpoint 0 sent)")
    r.check(await r.override() and await r.s("control") == "on", "control resumed after the reload")


async def B2(r: Run):
    """unload (entry disabled): hand-back, no loop left; enabled again: control as it was"""
    await r.switch(True)
    await r.ha.wait(60)
    entry = await r.ha.entry("vtherm_smart_boiler")
    t = time.time()
    await r.ha.ws_cmd(
        {"type": "config_entries/disable", "entry_id": entry["entry_id"], "disabled_by": "user"}
    )
    await r.ha.wait(15)
    c = r.cmds(t)
    r.check(("setpoint", 0) in c[-3:], f"hand-back at unload: {c}")
    r.check(not await r.override(), "override released")
    n = len(r.ha.since(t))
    await r.ha.wait(120)
    r.check(len(r.ha.since(t)) == n, "no loop left running for 2 min")
    await r.ha.ws_cmd(
        {"type": "config_entries/disable", "entry_id": entry["entry_id"], "disabled_by": None}
    )
    await r.ha.wait(60)
    r.ent.update(await r.ha.entities())
    r.note(
        f"after enabling: switch {await r.s('control')}, state {await r.s('control_state')}, override {await r.override()}"
    )
    r.check(await r.s("control") == "on" and await r.override(), "control back as the user left it")


async def B4(r: Run):
    """a thermostat heats again after a hand-back that followed "off" (CH=0 kept by the PIC)"""
    for zone, _target in ZONES:  # every room warm against its setpoint: no demand
        await r.ha.call("climate", "set_temperature", entity_id=f"climate.{zone}", temperature=15.0)
    await r.ha.wait(20)
    await r.switch(True)
    t = time.time()
    got = await r.ha.until(lambda: _last_ch_false(r, t), 420, 5)
    r.check(got is not None, f"control switched heating off (CH=0) within {got and round(got)} s")
    t2 = time.time()
    await r.switch(False)
    await r.ha.wait(30)
    c = r.cmds(t2)
    r.check(c[-3:] == SAFE, f"the full safe hand-back with CH=1: {c[-3:]}")
    r.check(not await r.override(), "override released")
    wall_calls = float(
        (await r.st("sensor.otgw_sim_thermostat_room_temperature"))["state"]
    ) < float((await r.st("sensor.otgw_sim_thermostat_room_setpoint"))["state"])
    chen = await r.s("binary_sensor.otgw_sim_boiler_master_ch_enabled")
    r.note(f"wall thermostat calling: {wall_calls}; CH enabled on the boiler: {chen}")
    r.check(chen == "on" or not wall_calls, "the thermostat's call reaches the boiler")


async def _last_ch_false(r: Run, t: float) -> bool:
    c = r.cmds(t, "ch")
    return bool(c) and c[-1][1] is False


async def B5(r: Run):
    """three reloads leave exactly one control loop"""
    await r.switch(True)
    await r.ha.wait(600)
    t = time.time()
    await r.ha.wait(300)
    one = len(r.ha.since(t))
    entry = await r.ha.entry("vtherm_smart_boiler")
    for _ in range(3):
        await r.ha.rest("POST", f"/api/config/config_entries/entry/{entry['entry_id']}/reload")
        await r.ha.wait(20)
    await r.ha.wait(300)
    t = time.time()
    await r.ha.wait(300)
    after = len(r.ha.since(t))
    r.check(
        one > 0 and after <= one + 2,
        f"commands in 5 min: one loop {one}, after three reloads {after}",
    )
    r.check(await r.override(), "control resumed")


async def C1(r: Run):
    """stale data (flow): nothing written without fresh data, then the hand-back and the alarm"""
    await r.switch(True)
    await r.ha.wait(60)
    await r.sim("fail_signal", signal="flow")
    t = time.time()
    await r.ha.wait(240)
    r.check(r.cmds(t) == [], f"nothing written for 4 min: {r.cmds(t)}")
    await r.ha.wait(90)
    sp = r.cmds(t, "setpoint")
    r.check(bool(sp) and sp[-1][1] == 0, f"handed back: {r.cmds(t)}")
    r.check(await r.s("control_state") == "handed_back", f"state {await r.s('control_state')}")
    r.check(await r.s("alarm_boiler_link_lost") == "on", "alarm boiler link lost on")


async def C2(r: Run):
    """the outdoor sensor failed: the weather instead, heating goes on"""
    await r.switch(True)
    await r.sim("fail_signal", signal="outdoor")
    await r.ha.wait(400)
    reasons = await r.attr("control_state", "reasons")
    r.check("outdoor_weather" in (reasons or []), f"reasons {reasons}")
    r.check(await r.override(), "override held")


async def C3(r: Run):
    """the gateway's whole link lost: hand-back attempted and retried, state says why"""
    await r.switch(True)
    await r.ha.wait(60)
    await r.sim("fail_signal", signal="gateway_all")
    t = time.time()
    await r.ha.wait(600)
    st = await r.st("control_state")
    r.check(st["state"] == "handed_back", f"state {st['state']}")
    r.check(
        "boiler_link_stale" in (st["attributes"].get("reasons") or []),
        f"reasons {st['attributes'].get('reasons')}",
    )
    r.check(0 in [v for k, v in r.cmds(t, "setpoint")], f"hand-back attempted: {r.cmds(t)}")
    r.check(await r.s("alarm_hand_back_failed") == "on", "hand-back failed alarm on")


async def C4(r: Run):
    """a hand-back while the gateway is away: failed, kept, retried; done once it is back"""
    await r.switch(True)
    await r.ha.wait(60)
    await r.sim("fail_signal", signal="gateway")
    await r.switch(False)
    await r.ha.wait(5)
    r.check(await r.s("alarm_hand_back_failed") == "on", "hand-back failed alarm on at once")
    await r.ha.wait(180)
    r.check(await r.s("alarm_hand_back_failed") == "on", "still on after 3 min")
    t = time.time()
    await r.sim("fail_signal", signal="gateway", failed=False)
    await r.ha.wait(70)
    c = r.cmds(t)
    r.check(c[-2:] == [("ch", True), ("setpoint", 0)], f"retried and taken: {c}")
    r.check(await r.s("alarm_hand_back_failed") == "off", "alarm cleared")
    n = len(r.ha.since(t))
    await r.ha.wait(180)
    r.check(len(r.ha.since(t)) == n, "nothing more sent")


async def C5(r: Run):
    """a gateway reset: the lost command sent again at once, no hand-back, no alarm"""
    await r.switch(True)
    await r.ha.wait(TRACE)
    t = time.time()
    await r.sim("reset_gateway")
    await r.ha.wait(25)
    sp = r.ha.since(t, "setpoint")
    r.check(
        bool(sp) and sp[0][0] - t <= 20,
        f"sent again {sp and round(sp[0][0] - t)} s after the reset",
    )
    r.check(await r.override(), "override held again")
    await r.ha.wait(60)
    r.check(0 not in [v for k, v in r.cmds(t, "setpoint")], "no hand-back")
    r.check(
        await r.s("control_state") == "heating" or await r.s("control_state") == "idle",
        f"state {await r.s('control_state')}",
    )
    r.check(await r.alarms_on() == [], f"alarms on: {await r.alarms_on()}")


async def D1(r: Run):
    """a command never taken (dropped at the gateway): ignored from the start, not fought"""
    await r.sim("ignore_writes", enabled=True, at="gateway")
    t = time.time()
    await r.switch(True)
    await r.ha.wait(240)
    r.check(await r.s("alarm_write_ignored") == "off", "no alarm before the counted sends (4 min)")
    await r.ha.wait(520)
    r.check(
        await r.s("alarm_write_ignored") == "on", "write ignored alarm after them (by 12.7 min)"
    )
    r.check(await r.s("alarm_outside_change") == "off", "never another controller")
    r.check(
        await r.s("control_state") != "handed_back",
        f"not handed back ({await r.s('control_state')})",
    )
    r.check(0 not in [v for k, v in r.cmds(t, "setpoint")], "nothing handed back")
    n = len(r.cmds(t, "setpoint"))
    await r.ha.wait(300)
    r.check(len(r.cmds(t, "setpoint")) == n, "not sent again this session")


async def D2(r: Run):
    """the boiler ignores what the gateway sends: not seen by the read-back (the real path's limit)"""
    await r.sim("ignore_writes", enabled=True, at="boiler")
    t = time.time()
    await r.switch(True)
    await r.ha.wait(900)
    r.check(bool(r.cmds(t, "setpoint")), "setpoints sent")
    r.check(
        await r.s("alarm_write_ignored") == "off" and await r.s("alarm_outside_change") == "off",
        "no alarm",
    )
    r.check(await r.s("control_state") != "handed_back", "not handed back")
    r.note(
        f"boiler's setpoint {await r.s('sensor.boiler_sim_ch_setpoint')} (its own curve at 3 °C: 42)"
    )


async def D3(r: Run):
    """another controller: rewritten once, then the safe hand-back and the latch, no fight"""
    await r.switch(True)
    await r.ha.wait(60)
    await r.sim("force_setpoint", value=62)
    await r.ha.wait(180)
    r.check(await r.s("alarm_outside_change") == "on", "outside change alarm on")
    st = await r.st("control_state")
    r.check(
        st["state"] == "handed_back",
        f"state {st['state']}, latched {st['attributes'].get('latched_by')}",
    )
    r.check(r.cmds(0)[-3:] == SAFE, f"last three: {r.cmds(0)[-3:]}")
    t = time.time()
    await r.ha.wait(120)
    r.check(r.cmds(t, "setpoint") == [], "no fight")


async def D5(r: Run):
    """overrides dropped: resent at once twice, the third within the hour steps aside"""
    await r.switch(True)
    await r.ha.wait(TRACE)
    for wait in (0, 600):
        await r.ha.wait(wait)
        t = time.time()
        await r.sim("drop_override")
        await r.ha.wait(12)
        r.check(
            bool(r.cmds(t, "setpoint")) and await r.override(), f"resent within 12 s: {r.cmds(t)}"
        )
        r.check(
            await r.s("control_state") == "heating" or await r.s("control_state") == "idle",
            f"state {await r.s('control_state')}",
        )
        r.check(await r.s("alarm_outside_change") == "off", "no outside change yet")
    await r.ha.wait(1200)
    await r.sim("drop_override")
    await r.ha.wait(25)
    st = await r.st("control_state")
    r.check(
        st["state"] == "handed_back" and st["attributes"].get("latched_by") == ["outside_change"],
        f"stepped aside: {st['state']} {st['attributes'].get('latched_by')}",
    )
    r.check(r.cmds(0)[-3:] == SAFE, f"last three: {r.cmds(0)[-3:]}")
    t = time.time()
    await r.ha.wait(600)
    r.check(r.cmds(t) == [], "no fight")


async def D6(r: Run):
    """a flat setpoint clipped at the gateway: judged another controller"""
    await r.switch(True)
    await r.ha.wait(TRACE)
    await r.sim("clip_setpoint", value=38, at="gateway")
    await r.ha.wait(300)
    st = await r.st("control_state")
    r.check(
        st["state"] == "handed_back" and st["attributes"].get("latched_by") == ["outside_change"],
        f"{st['state']} {st['attributes'].get('latched_by')}",
    )
    r.check(r.cmds(0)[-3:] == SAFE, f"last three: {r.cmds(0)[-3:]}")


async def D7(r: Run):
    """ID 1 refused: each send shown confirmed, then dropped; write ignored, not fought"""
    await r.sim("refuse_id1", enabled=True)
    t = time.time()
    await r.switch(True)
    seen = set()
    for _ in range(78):
        await r.ha.wait(10)
        v = await r.s("sensor.otgw_sim_boiler_control_setpoint")
        with contextlib.suppress(TypeError, ValueError):
            seen.add(float(v))
    sent = {float(v) for k, v in r.cmds(t, "setpoint")}
    # The gateway's acknowledgement lasts less than one simulator step, so a real Home Assistant
    # may never show it in the read-back's state (in-process the test steps both together).
    r.note(
        f"a send shown confirmed: sent {sorted(sent)}, seen {sorted(seen)} (the acknowledgement may last less than a step)"
    )
    r.check(not await r.override(), "dropped")
    r.check(await r.s("alarm_write_ignored") == "on", "write ignored alarm")
    st = await r.st("control_state")
    r.check(
        await r.s("alarm_outside_change") == "off"
        and st["state"] != "handed_back"
        and st["attributes"].get("latched_by") == [],
        f"not another controller: {st['state']}",
    )
    n = len(r.cmds(t, "setpoint"))
    await r.ha.wait(600)
    r.check(len(r.cmds(t, "setpoint")) == n, "not sent again this session")


async def D8(r: Run):
    """a hot-water draw under control: no outside change, SmartPI paused and resumed, DHW bit untouched"""
    await r.switch(True)
    await r.ha.wait(900)
    # The SmartPI zone must call — its valve open — for a draw to pause its learning (S-41).
    await r.sim("set_room_temperature", zone="zone_bedroom", temperature=17.0)
    await r.ha.wait(60)
    r.note(f"bedroom valve before the draw: {await r.s('switch.boiler_sim_zone_bedroom_valve')}")
    t = time.time()
    await r.sim("start_dhw", minutes=10)
    await r.ha.wait(60)
    r.check(await r.s("binary_sensor.boiler_sim_dhw_active") == "on", "the draw runs")
    learn = [
        (c[3].get("entity_id"), c[3].get("learning_enabled"))
        for c in r.ha.calls
        if c[0] >= t and c[2] == "set_smartpi_learning"
    ]
    r.check(learn and learn[0][1] is False, f"SmartPI learning paused: {learn}")
    await r.ha.wait(540 + 1800)
    learn = [
        (c[3].get("entity_id"), c[3].get("learning_enabled"))
        for c in r.ha.calls
        if c[0] >= t and c[2] == "set_smartpi_learning"
    ]
    r.check(learn and learn[-1][1] is True, f"resumed: {learn}")
    r.check(
        [
            a
            for a in await r.alarms_on()
            if a in ("alarm_outside_change", "alarm_write_ignored", "alarm_write_failed")
        ]
        == [],
        f"alarms {await r.alarms_on()}",
    )
    st = await r.st("control_state")
    r.check(
        st["state"] in ("heating", "idle") and st["attributes"].get("latched_by") == [],
        f"state {st['state']}",
    )
    r.check(
        r.cmds(t, "hot_water") == []
        and (await r.attr("sensor.boiler_sim_persistent_writes", "dhw_enable_writes")) == 0,
        "DHW-enable bit never written",
    )


async def F1(r: Run, fault="low_pressure_fault"):
    """the boiler's own fault: "off" after 5 min, no hand-back, no latch, repair issue; back when it clears"""
    await r.switch(True)
    await r.ha.wait(TRACE)
    t = time.time()
    await r.sim("set_fault", fault=fault)
    await r.ha.wait(240)
    r.check(("ch", False) not in r.cmds(t), f"four minutes: nothing yet ({r.cmds(t)})")
    await r.ha.wait(90)
    c = r.cmds(t)
    r.check(("ch", False) in c and ("setpoint", 0) not in c, f"CH=0, no hand-back: {c}")
    r.check(await r.override(), "the plugin keeps the boiler")
    st = await r.st("control_state")
    r.check(
        st["state"] == "boiler_fault" and st["attributes"].get("latched_by") == [],
        f"state {st['state']}",
    )
    issues = [i["issue_id"] for i in await r.ha.issues()]
    r.check(any("boiler_fault" in i for i in issues), f"repair issue: {issues}")
    t = time.time()
    await r.sim("set_fault", fault=fault, on=False)
    await r.ha.wait(40)
    r.check(
        ("ch", True) in r.cmds(t) or await r.s("control_state") in ("heating", "idle"),
        f"back: {r.cmds(t)}, {await r.s('control_state')}",
    )


async def F2(r: Run):
    """the boiler's lockout: as F1"""
    await F1(r, "boiler_lockout")


async def _refused(r: Run, label: str, d: dict) -> None:
    """Control refused for these options: by the form, or — saved — by the switch."""
    if d.get("errors"):
        r.check(True, f"{label}: refused where it is entered: {d['errors']}")
        return
    t0 = time.time()
    res = await r.switch(True)
    await r.ha.wait(60)
    r.check(
        await r.s("control") == "off" and r.cmds(t0) == [],
        f"{label}: saved, then the switch refused, nothing written; answer {res}, blockers {await r.attr('control', 'blockers')}",
    )


async def G1(r: Run):
    """control refused without a confirmed-setpoint source"""
    await _refused(r, "no confirmed setpoint", await r.options(control={"confirmed_entity": None}))
    await r.options()


async def G2(r: Run):
    """control refused in monitor mode"""
    await _refused(r, "monitor mode", await r.options(control={"topology": "monitor_mode"}))
    await r.options()


async def G3(r: Run):
    """an on/off contact or "I don't know" on the terminals: refused, nothing written, the thermostat heats"""
    for kind in ("on_off", "unknown"):
        await _refused(r, kind, await r.options(control={"thermostat_kind": kind}))
        chen = await r.s("binary_sensor.otgw_sim_boiler_master_ch_enabled")
        r.note(f"{kind}: CH enabled on the boiler (the thermostat's): {chen}")
    await r.options()


async def H1(r: Run):
    """every VT zone unavailable: the command held through recognition, then handed back to the thermostat"""
    await r.switch(True)
    await r.ha.wait(60)
    entries = [await r.ha.entry("versatile_thermostat", z) for z, _ in ZONES]
    t = time.time()
    for e in entries:
        await r.ha.ws_cmd(
            {"type": "config_entries/disable", "entry_id": e["entry_id"], "disabled_by": "user"}
        )
    await r.ha.wait(540)
    st = await r.st("control_state")
    r.check(
        st["attributes"].get("reasons") == ["zones_recognition"],
        f"held: reasons {st['attributes'].get('reasons')}, unknown {st['attributes'].get('unknown_zones')}",
    )
    r.check(await r.s("alarm_no_zone_known") == "off", "no alarm yet")
    await r.ha.wait(90)
    st = await r.st("control_state")
    r.check(
        "zones_unknown" in (st["attributes"].get("reasons") or [])
        and await r.s("alarm_no_zone_known") == "on",
        f"then: {st['state']} {st['attributes'].get('reasons')}",
    )
    sp = r.cmds(t, "setpoint")
    r.check(
        st["state"] == "handed_back" and sp and sp[-1][1] == 0,
        f"handed back to the thermostat: {r.cmds(t)}",
    )
    r.note(f"issues {[i['issue_id'] for i in await r.ha.issues()]}")
    for e in entries:
        await r.ha.ws_cmd(
            {"type": "config_entries/disable", "entry_id": e["entry_id"], "disabled_by": None}
        )
    await r.ha.wait(45)
    await r.zones()
    await r.ha.wait(30)
    r.check(
        await r.s("control_state") in ("heating", "idle")
        and await r.s("alarm_no_zone_known") == "off",
        f"back: {await r.s('control_state')}",
    )


async def E1(r: Run):
    """hard maximum in hard frost"""
    d = await r.options(curve={"hard_max": 48.0, "design_flow": 48.0})
    r.note(f"options {d.get('type')} {d.get('errors')}")
    await r.sim("set_outdoor", temperature=-25)
    t = time.time()
    await r.switch(True)
    await r.ha.wait(1800)
    sp = [v for k, v in r.cmds(t, "setpoint")]
    r.check(sp and max(sp) <= 48.0, f"max setpoint {max(sp) if sp else None}")
    r.check(
        "limit_hard_max" in (await r.attr("control_state", "reasons") or []),
        f"reasons {await r.attr('control_state', 'reasons')}",
    )
    await r.switch(False)
    await r.ha.wait(10)
    await r.options()


async def E2(r: Run):
    """a zone outside the central mode keeps heating under "Stopped" """
    entry = await r.ha.entry("versatile_thermostat", "zone_living")
    _s, d = await r.ha.rest(
        "POST",
        "/api/config/config_entries/options/flow",
        {"handler": entry["entry_id"], "show_advanced_options": True},
    )
    fid = d["flow_id"]
    await r.ha.rest(
        "POST", f"/api/config/config_entries/options/flow/{fid}", {"next_step_id": "main"}
    )
    main = {
        "name": "zone_living",
        "temperature_sensor_entity_id": "sensor.boiler_sim_zone_living_temperature",
        "cycle_min": 5,
        "device_power": 1,
        "power_unit": "w",
        "use_main_central_config": True,
        "used_by_controls_central_boiler": False,
    }
    await r.ha.rest(
        "POST",
        f"/api/config/config_entries/options/flow/{fid}",
        {**main, "use_central_mode": False},
    )
    _s, d = await r.ha.rest(
        "POST", f"/api/config/config_entries/options/flow/{fid}", {"next_step_id": "finalize"}
    )
    r.note(f"VT options: {d.get('type')}")
    await r.ha.wait(20)
    await r.zones()
    await r.switch(True)
    await r.ha.wait(60)
    t = time.time()
    await r.ha.call(
        "select",
        "select_option",
        entity_id="select.central_configuration_central_mode",
        option="Stopped",
    )
    got = await r.ha.until(lambda: _demand(r), 420, 5)
    r.note(f"zones: {[(z, await r.s('climate.' + z)) for z, _ in ZONES]}")
    r.check(
        got is not None,
        f"the living room keeps asking and the plugin heats for it (after {got and round(got)} s)",
    )
    r.check(0 not in [v for k, v in r.cmds(t, "setpoint")], "no hand-back")
    await r.ha.call(
        "select",
        "select_option",
        entity_id="select.central_configuration_central_mode",
        option="Auto",
    )
    _s, d = await r.ha.rest(
        "POST",
        "/api/config/config_entries/options/flow",
        {"handler": entry["entry_id"], "show_advanced_options": True},
    )
    fid = d["flow_id"]
    await r.ha.rest(
        "POST", f"/api/config/config_entries/options/flow/{fid}", {"next_step_id": "main"}
    )
    await r.ha.rest(
        "POST", f"/api/config/config_entries/options/flow/{fid}", {**main, "use_central_mode": True}
    )
    await r.ha.rest(
        "POST", f"/api/config/config_entries/options/flow/{fid}", {"next_step_id": "finalize"}
    )
    await r.ha.wait(20)


async def _demand(r: Run) -> bool:
    return (
        "demand" in (await r.attr("control_state", "reasons") or [])
        and await r.s("binary_sensor.otgw_sim_boiler_master_ch_enabled") == "on"
    )


async def E3(r: Run):
    """VT's activation delay of 120 s holds a start"""
    d = await r.options(curve={"activation_delay_s": 120})
    r.note(f"options {d.get('type')} {d.get('errors')}")
    await r.switch(True)
    starts = []
    for _ in range(2):
        # The rooms satisfied first, so heating goes off; then they call again.
        for zone, _target in ZONES:
            await r.ha.call(
                "climate", "set_temperature", entity_id=f"climate.{zone}", temperature=15.0
            )
        got = await r.ha.until(lambda: _ch_is(r, False), 420, 5)
        r.check(
            got is not None,
            f"heating off once the rooms are satisfied (after {got and round(got)} s)",
        )
        await r.ha.wait(30)
        # A long call: rooms 3 K below their setpoints keep a valve open well past the delay; a
        # pulse shorter than the delay would never start the boiler (VT's rule, said in the
        # option's description).
        for zone, target in ZONES:
            await r.sim("set_room_temperature", zone=zone, temperature=target - 3.0)
        await r.zones()
        opened = await r.ha.until(lambda: _any_valve_open(r), 420, 1)
        t_call = time.time()
        on = await r.ha.until(lambda: _ch_is(r, True), 300, 1)
        waited = None if on is None else round(time.time() - t_call)
        starts.append(waited)
        r.note(
            f"a valve opened {opened and round(opened)} s after the call; heating on {waited} s after it"
        )
    r.check(
        all(s is not None and s >= 115 for s in starts),
        f"each start waited at least 120 s: {starts}",
    )
    await r.switch(False)
    await r.ha.wait(10)
    await r.options()


async def _any_valve_open(r: Run) -> bool:
    return any([await r.s(f"switch.boiler_sim_{zone}_valve") == "on" for zone, _target in ZONES])


async def _ch_is(r: Run, on: bool) -> bool:
    return (await r.s("binary_sensor.otgw_sim_boiler_master_ch_enabled")) == ("on" if on else "off")


SCENARIOS = {
    f.__name__: f
    for f in (
        B1,
        B2,
        B4,
        B5,
        C1,
        C2,
        C3,
        C4,
        C5,
        D1,
        D2,
        D3,
        D5,
        D6,
        D7,
        D8,
        F1,
        F2,
        G1,
        G2,
        G3,
        H1,
        E1,
        E2,
        E3,
    )
}


async def main(ids: list[str]) -> None:
    async with HA() as ha:
        for sid in ids:
            ent = await ha.entities()
            r = Run(ha, ent)
            fn = SCENARIOS[sid]
            start = dt.datetime.now(dt.UTC)
            print(f"--- {sid} {start:%H:%M:%S} {fn.__doc__.strip()}", flush=True)
            try:
                await r.reset()
                await fn(r)
            except Exception:
                r.ok = False
                r.notes.append("FAIL exception: " + traceback.format_exc().strip().splitlines()[-1])
                traceback.print_exc()
            finally:
                try:
                    await r.reset()
                except Exception:
                    traceback.print_exc()
            verdict = "PASS" if r.ok else "FAIL"
            text = (
                f"\n### {sid} — {verdict} ({start:%H:%M}–{dt.datetime.now(dt.UTC):%H:%M} UTC)\n{fn.__doc__.strip()}\n"
                + "\n".join(f"- {n}" for n in r.notes)
                + "\n"
            )
            await asyncio.to_thread(append_result, text)
            print(text, flush=True)


# --- long scenarios -------------------------------------------------------------------------


async def D4(r: Run):
    """another controller, with "return by itself": stepped aside, back once quiet for an hour"""
    d = await r.options(alarms={"return_after_outside_change": True})
    r.note(f"options {d.get('type')}")
    await r.switch(True)
    await r.ha.wait(TRACE)
    await r.sim("force_setpoint", value=62)
    got = await r.ha.until(lambda: _handed_back(r), 300, 10)
    st = await r.st("control_state")
    r.check(
        got is not None and st["attributes"].get("latched_by") == ["outside_change"],
        f"stepped aside after {got and round(got)} s: {st['attributes'].get('latched_by')}",
    )
    r.check(r.cmds(0)[-3:] == SAFE, f"last three: {r.cmds(0)[-3:]}")
    await r.sim("force_setpoint")
    t = time.time()
    await r.ha.wait(3000)
    r.check(
        r.cmds(t) == [] and not await r.override(),
        f"quiet under an hour: no return yet ({r.cmds(t)})",
    )
    await r.ha.wait(900)
    st = await r.st("control_state")
    r.check(
        await r.override()
        and st["state"] in ("heating", "idle")
        and st["attributes"].get("latched_by") == [],
        f"a new session: {st['state']}, override {await r.override()}",
    )
    await r.switch(False)
    await r.ha.wait(10)
    await r.options()


async def _handed_back(r: Run) -> bool:
    return await r.s("control_state") == "handed_back"


async def E4(r: Run):
    """the comfort correction raises the water by 3 K at most, and says so at its edge"""
    d = await r.options(behaviour={"comfort_correction": True})
    r.note(f"options {d.get('type')}")
    r.ent.update(await r.ha.entities())
    await r.ha.call("climate", "set_temperature", entity_id="climate.zone_bath", temperature=26.0)
    t = time.time()
    await r.switch(True)
    await r.ha.wait(120)
    base = max(v for k, v in r.cmds(t, "setpoint"))
    r.note(f"curve's setpoint at the start {base}")
    seen = []
    for _ in range(30):
        await r.ha.wait(300)
        sp = [v for k, v in r.cmds(t, "setpoint")]
        seen.append(max(sp))
        if await r.s("alarm_correction_at_limit") == "on":
            break
    r.note(f"highest setpoint every 5 min: {seen}")
    r.check(max(seen) > base + 1.0, "the correction worked")
    r.check(max(seen) <= base + 3.1, "and stayed within 3 K")
    r.check(await r.s("alarm_correction_at_limit") == "on", "told at the edge")
    await r.switch(False)
    await r.ha.wait(10)
    await r.options()


async def C6(r: Run):
    """no outdoor reading at all: the last value held, then after 3 h the fallback setpoint — never zero heat"""
    await r.switch(True)
    await r.ha.wait(60)
    for sig in ("outdoor", "weather"):
        await r.sim("fail_signal", signal=sig)
    t = time.time()
    await r.ha.wait(900)
    r.check(
        "outdoor_held" in (await r.attr("control_state", "reasons") or []),
        f"held: {await r.attr('control_state', 'reasons')}",
    )
    await r.ha.wait(3 * 3600)
    reasons = await r.attr("control_state", "reasons") or []
    sp = r.cmds(t, "setpoint")
    ch = r.cmds(t, "ch")
    r.check("outdoor_unknown" in reasons, f"then unknown: {reasons}")
    r.check(
        sp and sp[-1][1] >= 20.0 and (not ch or ch[-1][1] is True) and await r.override(),
        f"heating at the fallback: last setpoint {sp[-1] if sp else None}, last CH {ch[-1] if ch else None}",
    )


SCENARIOS.update({f.__name__: f for f in (D4, E4, C6)})


# --- scenarios through the test-only fault injector (j4_faults) and set_room_temperature ----

MAIN_022 = {"monitoring_since": 0.0, "control": {}, "control_store": 1}


async def _first_after(r: Run, t: float, wait: float = 40):
    await r.ha.wait(wait)
    return r.cmds(t)


async def M1(r: Run):
    """the plugin's own monitor fails: after 5 min the safe hand-back, a blocker; works again: back by itself"""
    await r.switch(True)
    await r.ha.wait(60)
    t = time.time()
    await r.ha.call("j4_faults", "monitor", failing=True)
    await r.ha.wait(240)
    r.check(
        ("setpoint", 0) not in r.cmds(t) and await r.override(), "four minutes: control goes on"
    )
    await r.ha.wait(90)
    r.check(r.cmds(t)[-3:] == SAFE, f"then the safe hand-back: {r.cmds(t)[-3:]}")
    st = await r.st("control_state")
    r.check(
        st["state"] == "not_allowed" and st["attributes"].get("latched_by") == [],
        f"a blocker, not a latch: {st['state']}",
    )
    r.check(
        "monitor_failed" in (await r.attr("control", "blockers") or []), "blocker monitor_failed"
    )
    r.note(f"issues {[i['issue_id'] for i in await r.ha.issues()]}")
    t2 = time.time()
    await r.ha.wait(120)
    r.check(r.cmds(t2) == [], "nothing written while it fails")
    await r.ha.call("j4_faults", "monitor", failing=False)
    await r.ha.wait(30)
    r.check(not await r.override(), "not yet after 30 s (it must work for a minute)")
    await r.ha.wait(150)
    r.check(await r.override() and await r.s("control") == "on", "resumed by itself")
    r.note(f"issues {[(i['issue_id'], i.get('translation_key')) for i in await r.ha.issues()]}")


async def K1(r: Run):
    """a crashed run's stores (held, never given back): the full hand-back first, control off"""
    t = time.time()
    await r.ha.call(
        "j4_faults",
        "restart_with_stores",
        main=MAIN_022,
        control={
            "controlling": True,
            "last_command": {"heating": True, "setpoint": 55.0, "at": t - 600},
        },
    )
    c = await _first_after(r, t)
    r.ent.update(await r.ha.entities())
    r.check(c[:3] == SAFE, f"first: {c[:3]}")
    r.check(await r.s("control") == "off", f"switch {await r.s('control')}")
    n = len(r.ha.since(t))
    await r.ha.wait(180)
    r.check(len(r.ha.since(t)) == n, "nothing more")


async def K2(r: Run):
    """an entry store of another version and no control store: the full hand-back first"""
    t = time.time()
    await r.ha.call(
        "j4_faults",
        "restart_with_stores",
        main={"control": {"controlling": False}},
        main_version=99,
        control_removed=True,
    )
    c = await _first_after(r, t)
    r.check(c[:3] == SAFE, f"first: {c[:3]}")
    r.check(await r.s("control") == "off", f"switch {await r.s('control')}")


async def K3(r: Run):
    """a stored latch with a hand-back owed: the hand-back first; the latch holds until off and on"""
    t = time.time()
    await r.ha.call(
        "j4_faults",
        "restart_with_stores",
        main=MAIN_022,
        control={
            "controlling": True,
            "latched": True,
            "latched_by": ["outside_change"],
            "hand_back_pending": True,
            "last_command": {"heating": True, "setpoint": 55.0, "at": t - 600},
        },
    )
    c = await _first_after(r, t)
    r.check(c[:3] == SAFE, f"first: {c[:3]}")
    t2 = time.time()
    await r.switch(True)
    await r.ha.wait(120)
    st = await r.st("control_state")
    r.check(
        r.cmds(t2) == []
        and st["state"] == "handed_back"
        and st["attributes"].get("latched_by") == ["outside_change"],
        f"latched: {st['state']} {st['attributes'].get('latched_by')}, {r.cmds(t2)}",
    )
    await r.switch(False)
    await r.ha.wait(5)
    await r.switch(True)
    await r.ha.wait(25)
    r.check(await r.override(), "the user's off and on cleared it")


async def K4(r: Run):
    """the entry store says a control store was kept, but it is gone: the full hand-back first, control off"""
    t = time.time()
    await r.ha.call("j4_faults", "restart_with_stores", main=MAIN_022, control_removed=True)
    c = await _first_after(r, t)
    r.check(c[:3] == SAFE, f"first: {c[:3]}")
    r.check(await r.s("control") == "off", f"switch {await r.s('control')}")
    r.note(f"issues {[i['issue_id'] for i in await r.ha.issues()]}")


async def K5(r: Run):
    """a gateway entry without the answer on its thermostat terminals (made before 0.2.2): control stays stopped"""
    t = time.time()
    await r.ha.call("j4_faults", "remove_options", section="control", keys=["thermostat_kind"])
    await r.ha.wait(20)
    r.ent.update(await r.ha.entities())
    res = await r.switch(True)
    await r.ha.wait(600)
    r.check(r.cmds(t) == [], f"nothing written: {r.cmds(t)}")
    r.check(
        "thermostat_kind_unknown" in (await r.attr("control", "blockers") or []),
        f"blockers {await r.attr('control', 'blockers')}",
    )
    r.check(
        any("thermostat_kind_missing" in i["issue_id"] for i in await r.ha.issues()),
        f"issue: {[i['issue_id'] for i in await r.ha.issues()]}",
    )
    r.note(
        f"the thermostat's CH on the boiler: {await r.s('binary_sensor.otgw_sim_boiler_master_ch_enabled')}; switch answer {res}"
    )
    await r.switch(False)
    await r.ha.wait(5)
    await r.options()  # the answer given again
    r.check(
        not any("thermostat_kind_missing" in i["issue_id"] for i in await r.ha.issues()),
        "the issue goes with the answer",
    )


async def E5(r: Run):
    """VT "Stopped" and a room at 4 °C behind the valve VT keeps closed: no frost heat, a repair issue naming it"""
    await r.switch(True)
    await r.ha.wait(60)
    t = time.time()
    await r.ha.call(
        "select",
        "select_option",
        entity_id="select.central_configuration_central_mode",
        option="Stopped",
    )
    await r.ha.wait(20)
    await r.sim("set_room_temperature", zone="zone_living", temperature=4.0)
    await r.ha.wait(30)
    st = await r.st("control_state")
    ch = r.cmds(t, "ch")
    r.check(
        st["state"] == "idle" and (not ch or ch[-1][1] is False),
        f"no heat against closed valves: {st['state']}, {ch[-1:] if ch else []}",
    )
    r.check(0 not in [v for k, v in r.cmds(t, "setpoint")], "no hand-back")
    issues = [i["issue_id"] for i in await r.ha.issues()]
    r.check(any("frost_zone_closed" in i for i in issues), f"repair issue: {issues}")


SCENARIOS.update({f.__name__: f for f in (M1, K1, K2, K3, K4, K5, E5)})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
