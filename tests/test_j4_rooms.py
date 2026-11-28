"""J4's W2 checks its precondition before it starts (I12.26, ``devenv/j4/rooms.py``): where VT's
bath zone reads no window sensor — or another one — the scenario reads NOT RUN with the reason,
changing nothing; where it reads the simulator's bath window, it starts.

The runner's ``lib.py`` reads the test instances' access data when imported, so a stand-in takes
its place here, as in ``tests/test_j4_q5.py``: nothing connects anywhere."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

J4 = Path(__file__).resolve().parents[1] / "devenv" / "j4"
BATH = "climate.zone_bath"
WINDOW = "binary_sensor.boiler_sim_zone_bath_window"


class Started(Exception):
    """W2 went past its precondition: it asked Home Assistant to change something."""


@pytest.fixture
def j4(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    """The runner's ``run`` and ``rooms`` modules, loaded with a stand-in ``lib``."""
    lib = types.ModuleType("lib")
    lib.__dict__.update(
        CONTAINER="ha-test",
        HA=object,
        ROLE_ENTITY="input_text.j4_role",
        ROOT=J4.parents[1],
        SIGNALS=(),
        ssh=None,
    )
    monkeypatch.syspath_prepend(str(J4))
    before = set(sys.modules)
    monkeypatch.setitem(sys.modules, "lib", lib)
    rooms = importlib.import_module("rooms")
    yield sys.modules["run"], rooms
    for name in set(sys.modules) - before:
        del sys.modules[name]


class FakeHA:
    def __init__(self, states: dict[str, dict[str, Any]]) -> None:
        self.states = states

    async def state(self, entity_id: str) -> dict[str, Any] | None:
        return self.states.get(entity_id)

    async def call(self, *args: Any, **data: Any) -> None:
        raise Started


def _run(run: Any, window_manager: dict[str, Any] | None) -> Any:
    class Recorded(run.Run):
        asked: list[str]

        async def zones(self, mode: str = "heat") -> None:
            self.asked.append("zones")

        async def switch(self, on: bool, refusal_ok: bool = False) -> dict:
            self.asked.append("switch")
            return {}

    attributes = {} if window_manager is None else {"window_manager": window_manager}
    r = Recorded(FakeHA({BATH: {"state": "heat", "attributes": attributes}}), {})
    r.asked = []
    return r


@pytest.mark.parametrize(
    "window_manager",
    [
        pytest.param(None, id="no_window_configured"),
        pytest.param({"window_sensor_entity_id": None}, id="automatic_only"),
        pytest.param({"window_sensor_entity_id": "binary_sensor.other"}, id="another_sensor"),
    ],
)
async def test_w2_is_not_run_without_the_bath_window_in_vt(
    j4, window_manager: dict[str, Any] | None
) -> None:
    run, rooms = j4
    r = _run(run, window_manager)
    with pytest.raises(run.NotRun, match=WINDOW):
        await rooms.W2(r)
    assert r.asked == []


async def test_w2_starts_with_the_bath_window_in_vt(j4) -> None:
    run, rooms = j4
    r = _run(run, {"window_sensor_entity_id": WINDOW, "window_state": "off"})
    with pytest.raises(Started):
        await rooms.W2(r)
    assert r.asked == ["zones", "zones"]  # the zones set, then put back after the stop


def test_the_room_scenarios_are_registered(j4) -> None:
    run, rooms = j4
    assert run.SCENARIOS["T2"] is rooms.T2
    assert run.SCENARIOS["W2"] is rooms.W2
    assert run.scenario_roles("T2") == run.scenario_roles("W2") == {"gateway"}
