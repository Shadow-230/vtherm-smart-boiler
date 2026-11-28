"""J4: a freshly cleaned test instance set up as docs/en/testing/test-environment.md §4 says,
through Home Assistant's API (I12.28) — the pack's own, after the bench's script of 2026-11-27
(the test session's, read with the user's consent).

VT's central configuration: its central boiler on, its two commands on the helper
``input_boolean.j4_vt_central_boiler``, its safety delay 1440 min; then, after the restart below,
its device threshold at 1 (VT's thresholds are 0 by default, and 0 turns a threshold off). SmartPI
on the gateway role, whose bedroom uses it. The three VT zones, each counted by VT's central
boiler; the bath reads its window sensor (W2). The simulated gateway. Smart Boiler's entry for the
role — the gateway roles with the base the flow asks first (``base.py`` walks the rest), the relay
and entity paths in full. Each part is skipped where its entry exists.

Home Assistant then restarts once: VT's central configuration made while it runs blocks control
until it has (``vt_central_boiler_active``).

Usage: HA_INSTANCE=N scripts/env.sh python devenv/j4/setup_instance.py ROLE
ROLE: gateway | starts | relay | entity | standalone
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from options import VT_HELPER
from walk import shown

Rest = Callable[[str, str, dict[str, Any] | None], Awaitable[tuple[int, Any]]]
State = Callable[[str], Awaitable[dict[str, Any] | None]]
# ("menu", option), ("form", step_id, answers), or ("form?", step_id, answers) for a form shown
# again only where an answer revealed more of it; a form's other fields keep what it shows.
Step = tuple[Any, ...]

FLOW = "/api/config/config_entries/flow"
ENTRIES = "/api/config/config_entries/entry"
VT = "versatile_thermostat"
SMARTPI = "vtherm_smartpi"
SB = "vtherm_smart_boiler"
GW = "opentherm_gw"
ROLES = ("gateway", "starts", "relay", "entity", "standalone")
VT_CENTRAL = "Central configuration"
ZONES = ("zone_living", "zone_bedroom", "zone_bath")
BATH_WINDOW = "binary_sensor.boiler_sim_zone_bath_window"  # W2 (devenv/j4/rooms.py)
SAFETY_DELAY_MIN = 1440  # the simulator's steady rooms hold one value longer than VT's 60 min
THRESHOLD_ID = "boiler_activation_threshold"  # VT 10.6.5 ``number.py``: its device threshold
WALL_SETPOINT = "sensor.otgw_sim_thermostat_room_setpoint"

SIGNALS = {
    "flame": "binary_sensor.boiler_sim_flame",
    "flow": "sensor.boiler_sim_flow",
    "return": "sensor.boiler_sim_return",
    "modulation": "sensor.boiler_sim_modulation",
    "dhw_active": "binary_sensor.boiler_sim_dhw_active",
    "pressure": "sensor.boiler_sim_pressure",
    "outdoor": "sensor.boiler_sim_outdoor",
    "ch_active": "binary_sensor.boiler_sim_ch_active",
    "pump_running": "binary_sensor.boiler_sim_pump_running",
    # F1 and F2 need the boiler's own faults.
    "low_pressure_fault": "binary_sensor.boiler_sim_low_pressure_fault",
    "boiler_lockout": "binary_sensor.boiler_sim_boiler_lockout",
    "fault_indication": "binary_sensor.boiler_sim_fault_indication",
    "weather": "weather.boiler_sim_weather",
}
GATEWAY_READ_BACKS = {
    "ch_setpoint": "sensor.otgw_sim_boiler_control_setpoint",
    "ch_enabled": "binary_sensor.otgw_sim_boiler_master_ch_enabled",
}
# Instance 1's base as the flow first asks it (options.py BASE_GATEWAY); base.py walks the rest.
CURVE = {
    "design_outdoor": -15.0,
    "design_flow": 55.0,
    "hard_min": 20.0,
    "comfort_correction": False,
    "room_mode": "manual",
    "room": 20.0,
    "room_excluded": [],
    "offset": 0.0,
}
BEHAVIOUR = {"vt_boiler_helper": VT_HELPER, "ramp_k_per_min": 1.0, "decision_interval_min": 5.0}


class FlowError(RuntimeError):
    """A flow went elsewhere than its steps say, or refused an answer."""


def _where(d: dict[str, Any]) -> str:
    fields = [f"{f['name']}{'*' if f.get('required') else ''}" for f in d.get("data_schema") or []]
    return (
        f"{d.get('type')} {d.get('step_id')} errors={d.get('errors')} "
        f"menu={d.get('menu_options')} fields={fields} reason={d.get('reason')}"
    )


async def run_flow(
    rest: Rest, handler: str, steps: Sequence[Step], start: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A config flow walked through ``steps``; it must create its entry. A flow left half-way is
    closed."""
    _status, d = await rest(
        "POST", FLOW, {"handler": handler, "show_advanced_options": True, **(start or {})}
    )
    try:
        for step in steps:
            kind, name = step[0], step[1]
            if kind == "form?":
                if d.get("type") != "form" or d.get("step_id") != name:
                    continue
                kind = "form"
            if kind == "menu":
                if name not in (d.get("menu_options") or []):
                    raise FlowError(f"{handler}: no {name} in the menu: {_where(d)}")
                _status, d = await rest("POST", f"{FLOW}/{d['flow_id']}", {"next_step_id": name})
                continue
            if d.get("type") != "form" or d.get("step_id") != name:
                raise FlowError(f"{handler}: expected form {name}, found {_where(d)}")
            answers = dict(step[2]) if len(step) > 2 else {}
            unknown = sorted(set(answers) - {f["name"] for f in d.get("data_schema") or []})
            if unknown:
                raise FlowError(f"{handler}: form {name} has no {unknown}: {_where(d)}")
            flow_id = d["flow_id"]
            _status, d = await rest("POST", f"{FLOW}/{flow_id}", shown(d) | answers)
            if d.get("errors"):
                d.setdefault("flow_id", flow_id)
                raise FlowError(f"{handler}: form {name} refused: {_where(d)}")
        if d.get("type") != "create_entry":
            raise FlowError(f"{handler}: ended at {_where(d)}, not at the entry's creation")
        return d
    except FlowError:
        if d.get("type") in ("form", "menu") and d.get("flow_id"):
            await rest("DELETE", f"{FLOW}/{d['flow_id']}", None)
        raise


def vt_central() -> list[Step]:
    return [
        ("form", "user", {"thermostat_type": "thermostat_central_config"}),
        ("menu", "main"),
        ("form", "main", {"external_temperature_sensor_entity_id": "sensor.boiler_sim_outdoor"}),
        ("menu", "features"),
        ("form", "features", {"use_central_boiler_feature": True}),
        ("menu", "central_boiler"),
        (
            "form",
            "central_boiler",
            {
                "central_boiler_activation_service": f"{VT_HELPER}/input_boolean.turn_on",
                "central_boiler_deactivation_service": f"{VT_HELPER}/input_boolean.turn_off",
            },
        ),
        ("menu", "tpi"),
        ("form", "tpi", {}),
        ("menu", "advanced"),
        ("form", "advanced", {"safety_delay_min": SAFETY_DELAY_MIN}),
        ("menu", "finalize"),
    ]


def vt_zone(zone: str, function: str, window: str | None = None) -> list[Step]:
    """A zone counted by VT's central boiler; with ``window``, read by VT's window detection."""
    features: dict[str, Any] = {"use_window_feature": True} if window else {}
    steps: list[Step] = [
        ("form", "user", {"thermostat_type": "thermostat_over_switch"}),
        ("menu", "main"),
        (
            "form",
            "main",
            {
                "name": zone,
                "temperature_sensor_entity_id": f"sensor.boiler_sim_{zone}_temperature",
                "used_by_controls_central_boiler": True,
            },
        ),
        ("menu", "features"),
        ("form", "features", features),
        ("menu", "type"),
        (
            "form",
            "type",
            {
                "underlying_entity_ids": [f"switch.boiler_sim_{zone}_valve"],
                "proportional_function": function,
            },
        ),
    ]
    if window:
        steps += [("menu", "window"), ("form", "window", {"window_sensor_entity_id": window})]
    return [*steps, ("menu", "finalize")]


def _sb_common(connection: str, mode: str) -> list[Step]:
    return [
        ("form", "connection", {"connection": connection, "heat_source": "gas", "type": "combi"}),
        ("form", "mode", {"control_mode": mode, "condensing": True, "dhw_priority": True}),
        ("form", "name", {"name": "Smart Boiler", "level": "advanced"}),
    ]


def _sb_circuit() -> list[Step]:
    return [
        ("menu", "boiler"),
        ("form", "boiler", {}),
        ("menu", "circuit_1"),
        ("form", "circuit", {"control": "unmixed_shared"}),
        ("form?", "circuit", {}),
        ("menu", "building"),
        ("form", "building", {}),
    ]


def sb_gateway(role: str, wall_setpoint: bool) -> list[Step]:
    """The gateway roles: a stand-alone gateway, or one with an OpenTherm thermostat."""
    standalone = role == "standalone"
    interface = {"topology": "gateway_standalone" if standalone else "gateway_with_thermostat"}
    kind = {"thermostat_kind": "none" if standalone else "opentherm"}
    signals = (
        SIGNALS | GATEWAY_READ_BACKS | ({"room_setpoint": WALL_SETPOINT} if wall_setpoint else {})
    )
    return [
        *_sb_common("opentherm_gw", "full"),
        ("menu", "interface"),
        ("form", "interface", interface),
        ("form", "interface", interface | kind),  # the topology reveals the rest, shown again
        ("menu", "signals"),
        ("form", "signals", signals),
        *_sb_circuit(),
        ("menu", "monitor"),
        ("form", "monitor", {}),
        ("menu", "control_curve"),
        ("form", "control_curve", CURVE),
        ("menu", "control_behaviour"),
        ("form", "control_behaviour", BEHAVIOUR),
        ("menu", "control_alarms"),
        ("form", "control_alarms", {}),
        ("menu", "finish"),
    ]


def sb_relay() -> list[Step]:
    """The relay path (the test environment's §4: an on/off boiler on ``switch.boiler_sim_relay``)."""
    reads = {k: SIGNALS[k] for k in ("flame", "flow", "return", "outdoor", "weather")}
    return [
        *_sb_common("relay", "on_off"),
        ("menu", "interface"),
        ("form", "interface", {}),
        ("menu", "signals"),
        ("form", "signals", {"relay_reads_boiler": False, **reads}),
        *_sb_circuit(),
        ("menu", "control"),
        (
            "form",
            "control_relay",
            {
                "relay_entity": "switch.boiler_sim_relay",
                "relay_is_separate_contact": True,
                "relay_reports_state": "yes",
                "relay_power_on_state": "off",
                "relay_off_timer": "none",
                "relay_rest_state": "off",
                "own_room_controller": False,
            },
        ),
        ("menu", "monitor"),
        ("form", "monitor", {}),
        ("menu", "control_behaviour"),
        ("form", "control_behaviour", {"vt_boiler_helper": VT_HELPER}),
        ("menu", "finish"),
    ]


def sb_entity() -> list[Step]:
    """The entity path: a held flow setpoint and heating switch, as ESPHome or EMS-ESP offer them."""
    control = {
        "setpoint_entity": "number.boiler_sim_flow_setpoint",
        "write_type": "held",
        "ch_entity": "switch.boiler_sim_ch_enable",
        "hand_back": "value",
        "own_room_controller": False,
    }
    revealed = control | {
        "ch_write_type": "held",
        "hand_back_value": 0,
        "hand_back_value_effect": "own_control",
    }
    return [
        *_sb_common("other_entity", "full"),
        ("menu", "interface"),
        ("form", "interface", {"topology": "virtual"}),
        ("menu", "signals"),
        ("form", "signals", SIGNALS | {"ch_setpoint": "sensor.boiler_sim_ch_setpoint"}),
        *_sb_circuit(),
        ("menu", "monitor"),
        ("form", "monitor", {}),
        ("menu", "control"),
        ("form", "control_entity", control),
        ("form", "control_entity", revealed),  # the write types reveal the rest, shown again
        ("menu", "control_curve"),
        ("form", "control_curve", CURVE),
        ("menu", "control_behaviour"),
        ("form", "control_behaviour", {"vt_boiler_helper": VT_HELPER}),
        ("menu", "control_alarms"),
        ("form", "control_alarms", {}),
        ("menu", "finish"),
    ]


async def entries(rest: Rest, domain: str) -> list[dict[str, Any]]:
    _status, found = await rest("GET", ENTRIES, None)
    return [e for e in found if e["domain"] == domain]


async def set_up(rest: Rest, state: State, role: str) -> list[str]:
    """Every part of the role's installation that is not there yet; what was made, by name."""
    if role not in ROLES:
        raise ValueError(f"no role {role!r}: one of {ROLES}")
    made: list[str] = []
    titles = {e["title"] for e in await entries(rest, VT)}
    if VT_CENTRAL not in titles:
        await run_flow(rest, VT, vt_central())
        made.append(f"VT: {VT_CENTRAL}")
    smartpi = role == "gateway"  # the gateway's bedroom learns with SmartPI
    if smartpi and not await entries(rest, SMARTPI):
        await run_flow(rest, SMARTPI, [])
        made.append("SmartPI")
    for zone in ZONES:
        if zone in titles:
            continue
        function = "smartpi" if smartpi and zone == "zone_bedroom" else "tpi"
        window = BATH_WINDOW if zone == "zone_bath" else None
        await run_flow(rest, VT, vt_zone(zone, function, window))
        made.append(f"VT: {zone} ({function})")
    if role != "relay" and not await entries(rest, GW):
        await run_flow(rest, GW, [("form", "user", {})])
        made.append("the simulated gateway")
    if not await entries(rest, SB):
        if role == "relay":
            steps = sb_relay()
        elif role == "entity":
            steps = sb_entity()
        else:
            reading = (await state(WALL_SETPOINT) or {}).get("state")
            steps = sb_gateway(role, reading not in (None, "unknown", "unavailable"))
        await run_flow(rest, SB, steps)
        made.append(f"Smart Boiler: {role}")
    return made


async def vt_threshold(ws_cmd: Callable[[dict[str, Any]], Awaitable[Any]]) -> str | None:
    """The entity of VT's device threshold, from the entity registry; ``None`` before VT's
    central configuration has made it."""
    registry = await ws_cmd({"type": "config/entity_registry/list"})
    return next(
        (
            e["entity_id"]
            for e in registry
            if e.get("platform") == VT and e.get("unique_id") == THRESHOLD_ID
        ),
        None,
    )


async def main(argv: Sequence[str]) -> None:
    from lib import HA
    from restart import wait_running

    if len(argv) != 1 or argv[0] not in ROLES:
        raise SystemExit(__doc__)
    role = argv[0]
    async with HA() as ha:
        made = await set_up(ha.rest, ha.state, role)
        print("\n".join(made) or "everything was there")
        await ha.call("homeassistant", "restart")
    await asyncio.sleep(20)  # it answers a moment longer before it stops
    up = await wait_running()
    if up is None:
        raise SystemExit("Home Assistant did not come back")
    async with HA() as ha:
        threshold = await vt_threshold(ha.ws_cmd)
        if threshold is None:
            raise SystemExit("VT shows no device threshold")
        await ha.call("number", "set_value", entity_id=threshold, value=1)
        print(f"Home Assistant back in {round(up)} s; VT's device threshold {threshold} at 1")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
