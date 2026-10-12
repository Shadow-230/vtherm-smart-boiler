"""J4 restarts on test instance 1: B3 a clean Home Assistant restart, B6 docker kill (decision 15)."""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import time
import traceback

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from lib import CONTAINER, HA, ssh
from run import Run, append_result


async def wait_running(limit: float = 300) -> float | None:
    start = time.time()
    while time.time() - start < limit:
        try:
            async with HA() as ha:
                _s, c = await ha.rest("GET", "/api/config")
                if isinstance(c, dict) and c.get("state") == "RUNNING":
                    return time.time() - start
        except Exception:
            pass
        await asyncio.sleep(5)
    return None


async def B3(notes):
    async with HA() as ha:
        r = Run(ha, await ha.entities())
        await r.reset()
        await r.switch(True)
        await ha.wait(60)
        held = await r.override()
        t = time.time()
        await ha.call("homeassistant", "restart")
        await asyncio.sleep(20)
        captured = r.cmds(t)
    since = dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    up = await wait_running()
    log = ssh(
        f"docker logs --since {since} {CONTAINER} 2>&1 | grep -i -E 'vtherm_smart_boiler' | grep -i -E 'hand|stop|shut' | head -8"
    )
    async with HA() as ha:
        r = Run(ha, await ha.entities())
        await ha.wait(60)
        ok = [held, ("setpoint", 0) in captured, await r.s("control") == "on", await r.override()]
        notes += [
            f"override held before: {held}",
            f"captured before the connection closed: {captured}",
            f"log: {log.strip()[:600]}",
            f"up again in {up and round(up)} s; switch {await r.s('control')}, state {await r.s('control_state')}, override {await r.override()}",
        ]
        await r.reset()
    return all(ok[2:]) and (ok[1] or "hand" in log.lower())


async def B6(notes):
    async with HA() as ha:
        r = Run(ha, await ha.entities())
        await r.reset()
        await r.switch(True)
        await ha.wait(60)
        held = await r.override()
    t = time.time()
    since = dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    out = ssh(
        f"docker kill {CONTAINER}; sleep 5; cd /opt/ha-test && docker compose start homeassistant 2>&1 | tail -1"
    )
    up = await wait_running()
    async with HA() as ha:
        r = Run(ha, await ha.entities())
        await ha.wait(45)
        p = (await r.st("sensor.boiler_sim_persistent_writes"))["attributes"]
        log = ssh(
            f"docker logs --since {since} {CONTAINER} 2>&1 | grep -i 'vtherm_smart_boiler' | grep -i -E 'hand|owed|controll|crash|clean' | head -8"
        )
        sw, state, ovr = await r.s("control"), await r.s("control_state"), await r.override()
        notes += [
            f"override held before the kill: {held}; kill/start: {out.strip()}",
            f"up again in {up and round(up)} s",
            f"after start: switch {sw}, state {state}, override {ovr}, simulator's gateway commands since its start {p.get('gateway_commands')}, CH writes {p.get('ch_writes')}",
            f"log: {log.strip()[:800]}",
        ]
        # SCOPE.md §7: after a restart without a clean stop a hand-back is pending until
        # control resumes, and the control switch comes back as the user left it — on.
        ok = held and sw == "on" and ovr and state in ("heating", "idle")
        await r.reset()
    return ok


async def main(ids):
    for sid in ids:
        notes: list[str] = []
        start = dt.datetime.now(dt.UTC)
        doc = {
            "B3": "a clean Home Assistant restart: hand-back at the stop, control back as left",
            "B6": "Home Assistant killed (docker kill, decision 15): the switch back as left, control resumed",
        }[sid]
        print(f"--- {sid} {start:%H:%M:%S} {doc}", flush=True)
        try:
            ok = await {"B3": B3, "B6": B6}[sid](notes)
        except Exception:
            ok = False
            notes.append("exception: " + traceback.format_exc().strip().splitlines()[-1])
            traceback.print_exc()
        text = (
            f"\n### {sid} — {'PASS' if ok else 'FAIL'} ({start:%H:%M}–{dt.datetime.now(dt.UTC):%H:%M} UTC)\n{doc}\n"
            + "\n".join(f"- {n}" for n in notes)
            + "\n"
        )
        await asyncio.to_thread(append_result, text)
        print(text, flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
