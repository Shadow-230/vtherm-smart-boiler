"""Lags of the gateway's CH enable behind 'any zone valve open', from recorder history."""

from __future__ import annotations

import datetime as dt


async def lags(ha, start_ts: float):
    start = dt.datetime.fromtimestamp(start_ts, dt.UTC).isoformat()
    ents = [
        "switch.boiler_sim_zone_living_valve",
        "switch.boiler_sim_zone_bedroom_valve",
        "switch.boiler_sim_zone_bath_valve",
        "binary_sensor.otgw_sim_boiler_master_ch_enabled",
    ]
    _s, h = await ha.rest(
        "GET",
        f"/api/history/period/{start}?filter_entity_id={','.join(ents)}&minimal_response&no_attributes",
    )
    events = []
    for series in h:
        eid = None
        for s in series:
            eid = s.get("entity_id", eid)
            events.append((dt.datetime.fromisoformat(s["last_changed"]), eid, s["state"]))
    events.sort()
    valves, any_open, ch, last, first_call, out = {}, None, None, None, None, []
    for t, eid, state in events:
        if eid.startswith("switch."):
            valves[eid] = state == "on"
            now = any(valves.values())
            if now != any_open:
                any_open = now
                last = (t, now)
                if now and ch is False and first_call is None:
                    first_call = t  # the first call since heating went off
        else:
            on = state == "on"
            if on != ch:
                if ch is not None and last and last[1] == on:
                    out.append(("on" if on else "off", round((t - last[0]).total_seconds())))
                if on and first_call is not None:
                    out.append(("on_first", round((t - first_call).total_seconds())))
                if not on:
                    first_call = None
                ch = on
    return out
