"""J4's scenario P2 reads the Boiler page's commands on a test Home Assistant
(``devenv/j4/page_checks.py``): its checks hold against the plugin's real answers here, and each
one finds what it is there to find — so a change to the commands fails here first."""

# The fixtures ``rig`` and ``j4`` are imported by name: each test's parameter of that name is the
# fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from custom_components.vtherm_smart_boiler.const import DOMAIN
from tests.test_j4_q5 import j4  # noqa: F401

from .test_control import Rig, rig, start  # noqa: F401
from .test_websocket import Client, connect

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

J4 = Path(__file__).resolve().parents[2] / "devenv" / "j4"


def _checks() -> ModuleType:
    spec = importlib.util.spec_from_file_location("j4_page_checks", J4 / "page_checks.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checks = _checks()


def _zones(installation: dict[str, Any]) -> list[str]:
    return [z["entity_id"] for c in installation["circuits"] for z in c["zones"]]


class OverWebSocket:
    """The runner's ``HA``, on the plugin's real commands."""

    def __init__(self, client: Client) -> None:
        self.client = client
        self.asked: list[str] = []

    async def ws_cmd(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = {k: v for k, v in payload.items() if k != "type"}
        command = payload["type"].removeprefix(f"{DOMAIN}/")
        self.asked.append(command)
        reply = await self.client.ask(command, **fields)
        if not reply.get("success"):
            raise RuntimeError(f"{command}: {reply.get('error')}")
        return reply["result"]


async def test_p2_passes_on_the_plugins_real_answers(
    rig: Rig, hass_ws_client: Any, j4: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario itself, through the real commands: every check passes, the commands the
    page uses are each asked, and the draft leaves the stored options as they were."""
    run, _corrections = j4
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    zones = _zones((await client.ask("installation"))["result"])
    monkeypatch.setattr(run, "ZONES", tuple((z.removeprefix("climate."), 20.0) for z in zones))
    assert rig.entry is not None
    stored = copy.deepcopy(dict(rig.entry.options))
    ha = OverWebSocket(client)
    r = run.Run(ha, {})
    await run.SCENARIOS["P2"](r)
    assert r.ok, r.notes
    assert set(ha.asked) == {"installation", "curve", "days", "burns"}
    assert dict(rig.entry.options) == stored


async def test_p2_fails_when_a_command_is_refused(rig: Rig, hass_ws_client: Any, j4: Any) -> None:
    """A command the page needs and cannot get does not pass: the scenario stops with its
    error, which the runner reports as a failure."""
    run, _corrections = j4
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)

    class Refusing(OverWebSocket):
        async def ws_cmd(self, payload: dict[str, Any]) -> dict[str, Any]:
            if payload["type"].endswith("/days"):
                raise RuntimeError("days: not_running")
            return await super().ws_cmd(payload)

    r = run.Run(Refusing(client), {})
    with pytest.raises(RuntimeError, match="days"):
        await run.SCENARIOS["P2"](r)


INSTALLATION: dict[str, Any] = {
    "circuits": [{"zones": [{"entity_id": "climate.a"}]}],
    "signals": {"flame": "binary_sensor.flame", "flow": "sensor.flow"},
    "entities": {"control": "binary_sensor.control", "control_state": "sensor.control_state"},
    "curve": {"design_flow": 55.0},
}


@pytest.mark.parametrize(
    ("change", "found"),
    [
        ({"circuits": []}, "no circuit"),
        ({"circuits": [{"zones": [{"entity_id": "climate.b"}]}]}, "zones"),
        ({"signals": {"flow": "sensor.flow"}}, "no signal flame"),
        ({"entities": {"control": "switch.control", "control_state": "sensor.s"}}, "control is"),
        ({"entities": {"control": "binary_sensor.c"}}, "control state is"),
        ({"curve": None}, "no curve"),
    ],
)
def test_the_installation_check_finds(change: dict[str, Any], found: str) -> None:
    assert checks.installation_problems(INSTALLATION, ["climate.a"]) == []
    problems = checks.installation_problems(INSTALLATION | change, ["climate.a"])
    assert any(found in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("answer", "found"),
    [
        ({"points": [[0, 40]], "problems": []}, "1 points"),
        ({"points": [[0, 40], [0]], "problems": []}, "not (outdoor"),
        ({"points": [[1, 40], [0, 39]], "problems": []}, "does not rise"),
        ({"points": [[0, 40], [1, 41]], "problems": []}, "water rises"),
        ({"points": [[0, 40], [1, 39]], "problems": ["hard_min"]}, "problems named"),
    ],
)
def test_the_curve_check_finds(answer: dict[str, Any], found: str) -> None:
    assert checks.curve_problems({"points": [[0, 40], [1, 39]], "problems": []}) == []
    assert any(found in problem for problem in checks.curve_problems(answer))


@pytest.mark.parametrize(
    ("draft", "found"),
    [
        ([[0, 40]], "points against"),
        ([[0, 39], [1, 40]], "cooler"),
        ([[0, 40], [1, 39]], "changes nothing"),
    ],
)
def test_the_draft_check_finds(draft: list[list[float]], found: str) -> None:
    saved = {"points": [[0, 40], [1, 39]]}
    assert checks.draft_problems(saved, {"points": [[0, 41], [1, 39]]}) == []
    assert any(found in p for p in checks.draft_problems(saved, {"points": draft}))


DAYS: dict[str, Any] = {
    "days": [{"start": 1.0}, {"start": 2.0}],
    "weeks": [dict.fromkeys(checks.WEEK_KEYS)],
    "signature": dict.fromkeys(checks.SIGNATURE_KEYS),
    "gas_unit": None,
}


@pytest.mark.parametrize(
    ("change", "found"),
    [
        ({"days": [{"start": 2.0}, {"start": 1.0}]}, "oldest first"),
        ({"weeks": [{}] * 13}, "weeks"),
        ({"weeks": [{"start": 0}]}, "a week lacks"),
        ({"signature": {"days": []}}, "signature"),
    ],
)
def test_the_days_check_finds(change: dict[str, Any], found: str) -> None:
    assert checks.days_problems(DAYS) == []
    assert any(found in problem for problem in checks.days_problems(DAYS | change))
    assert "no gas unit" in checks.days_problems({k: v for k, v in DAYS.items() if k != "gas_unit"})


BURN = {"start": 1.0, "end": 2.0, "kind": "ch", "start_seen": True, "end_seen": False}


@pytest.mark.parametrize(
    ("answer", "found"),
    [
        ({"at": None, "burns": [BURN]}, "before any analysis"),
        ({"at": "soon", "burns": []}, "analysed at"),
        ({"at": 5.0, "burns": None}, "burns:"),
        ({"at": 5.0, "burns": [BURN | {"end": 0.5}]}, "ends before"),
        ({"at": 5.0, "burns": [BURN | {"start": None}]}, "times"),
        ({"at": 5.0, "burns": [BURN | {"kind": "heat"}]}, "kind"),
        ({"at": 5.0, "burns": [BURN | {"end_seen": 1}]}, "edges"),
    ],
)
def test_the_burns_check_finds(answer: dict[str, Any], found: str) -> None:
    assert checks.burns_problems({"at": None, "burns": []}) == []
    assert checks.burns_problems({"at": 5.0, "burns": [BURN]}) == []
    assert any(found in problem for problem in checks.burns_problems(answer))
