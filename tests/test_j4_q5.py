"""J4's Q5 checks its precondition before it starts (L15, ``devenv/j4/corrections.py``): with the
bedroom's SmartPI still learning from scratch its room counts as short, so the scenario reads
NOT RUN with the reason instead of failing after hours; once SmartPI has learned it starts; and
where the diagnostic sensor cannot be found — the bedroom not on SmartPI, or a SmartPI that
names none — it starts too, as intended: nothing says a learning band is in the way.

The runner's ``lib.py`` reads the test instances' access data when imported, so a stand-in takes
its place here: nothing connects anywhere."""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

J4 = Path(__file__).resolve().parents[1] / "devenv" / "j4"
BEDROOM = "climate.zone_bedroom"
DIAGNOSTICS = "sensor.zone_bedroom_smartpi_diagnostics"


class Started(Exception):
    """Q5 went past its precondition: its first step, the options, was asked."""


def _stand_in_lib() -> types.ModuleType:
    lib = types.ModuleType("lib")
    lib.__dict__.update(
        CONTAINER="ha-test",
        HA=object,
        ROLE_ENTITY="input_text.j4_role",
        ROOT=J4.parents[1],
        SIGNALS=(),
        ssh=None,
    )
    return lib


@pytest.fixture
def j4(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    """The runner's ``run`` and ``corrections`` modules, loaded from ``devenv/j4`` with the
    stand-in ``lib``; sys.path and sys.modules as they were afterwards."""
    monkeypatch.syspath_prepend(str(J4))
    before = set(sys.modules)
    monkeypatch.setitem(sys.modules, "lib", _stand_in_lib())
    corrections = importlib.import_module("corrections")
    yield sys.modules["run"], corrections
    for name in set(sys.modules) - before:
        del sys.modules[name]


class FakeHA:
    """The states the scenario reads; anything else it asks is a step past the precondition."""

    def __init__(self, states: dict[str, dict[str, Any]]) -> None:
        self.states = states

    async def state(self, entity_id: str) -> dict[str, Any] | None:
        return self.states.get(entity_id)

    async def wait(self, seconds: float) -> None:
        return None

    async def call(self, *args: Any, **data: Any) -> None:
        raise Started


def _states(specific: dict[str, Any] | None, diagnostic: str | None) -> dict[str, dict]:
    attributes = {} if specific is None else {"specific_states": specific}
    states = {BEDROOM: {"state": "heat", "attributes": attributes}}
    if diagnostic is not None:
        states[DIAGNOSTICS] = {"state": diagnostic, "attributes": {}}
    return states


def _learning(state: str | None) -> dict[str, dict]:
    return _states({"regulation_diagnostics": DIAGNOSTICS}, state)


def _run(run: Any, states: dict[str, dict]) -> Any:
    """A ``Run`` on the fake states whose options, switch and zones are only recorded; the
    options the scenario starts with raise ``Started``."""

    class Recorded(run.Run):
        asked: list[tuple[str, Any]]

        async def options(self, **changes: Any) -> dict:
            self.asked.append(("options", changes))
            if changes:
                raise Started
            return {}

        async def switch(self, on: bool, refusal_ok: bool = False) -> dict:
            self.asked.append(("switch", on))
            return {}

        async def zones(self, mode: str = "heat") -> None:
            self.asked.append(("zones", mode))

    r = Recorded(FakeHA(states), {})
    r.asked = []
    return r


async def test_q5_is_not_run_while_the_bedrooms_smartpi_learns_from_scratch(j4) -> None:
    """SmartPI in its learning phase: the reason names its state, and nothing is changed."""
    run, corrections = j4
    r = _run(run, _learning("bootstrap_hysteresis"))
    assert await corrections.smartpi_bootstrap(r) == "bootstrap_hysteresis"
    with pytest.raises(run.NotRun, match="bootstrap_hysteresis"):
        await corrections.Q5(r)
    assert r.asked == []


@pytest.mark.parametrize("state", ["stable", "calibration"])
async def test_q5_starts_once_smartpi_has_learned(j4, state: str) -> None:
    """Past its learning from scratch, SmartPI is no reason to wait: Q5 starts — the comfort
    correction switched on first — and puts the options and zones back after."""
    run, corrections = j4
    r = _run(run, _learning(state))
    assert await corrections.smartpi_bootstrap(r) is None
    with pytest.raises(Started):
        await corrections.Q5(r)
    assert r.asked[0] == ("options", {"curve": corrections.CORRECTION_ON})
    assert r.asked[1:] == [("switch", False), ("options", {}), ("zones", "heat")]


@pytest.mark.parametrize(
    "states",
    [
        pytest.param(_states(None, None), id="no_specific_states"),
        pytest.param(_states({}, None), id="no_diagnostics_named"),
        pytest.param(_states({"regulation_diagnostics": None}, None), id="named_none"),
        pytest.param(_states({"regulation_diagnostics": "climate.x"}, None), id="not_a_sensor"),
        pytest.param({}, id="no_bedroom"),
    ],
)
async def test_q5_starts_where_no_diagnostic_sensor_is_found(j4, states: dict) -> None:
    """Intended (L15): without a diagnostic sensor — the bedroom on TPI, a SmartPI that names
    none — there is no learning band to wait for, and Q5 starts."""
    run, corrections = j4
    r = _run(run, states)
    assert await corrections.smartpi_bootstrap(r) is None
    with pytest.raises(Started):
        await corrections.Q5(r)


async def test_the_runner_reports_q5_not_run_with_its_reason(
    j4, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The result J4 writes: "NOT RUN" and the reason, not a failure."""
    run, _corrections = j4
    states = _learning("bootstrap_hysteresis")

    class Connected(FakeHA):
        async def __aenter__(self) -> Connected:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def entities(self) -> dict[str, str]:
            return {}

    async def no_problem(r: Any, sid: str) -> None:
        return None

    async def nothing(self: Any) -> None:
        return None

    written: list[str] = []
    monkeypatch.setattr(run, "HA", lambda: Connected(states))
    monkeypatch.setattr(run, "base_problem", no_problem)
    monkeypatch.setattr(run.Run, "reset", nothing)
    monkeypatch.setattr(run.Run, "zones_enabled", nothing)
    monkeypatch.setattr(run, "append_result", written.append)
    await run.main(["Q5"])
    (text,) = written
    assert "### Q5 — NOT RUN" in text
    reason = "the bedroom's SmartPI still learns from scratch (bootstrap_hysteresis)"
    assert f"NOT RUN — {reason}" in text
