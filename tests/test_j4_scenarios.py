"""J4's scenarios added after the run on qas 01ef0a6 (I12.27): registered for the gateway role,
and V2 not run where VT's central boiler shows no device threshold, changing nothing.

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


@pytest.fixture
def j4(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    """The runner's ``run`` and ``vt_boiler`` modules, loaded with a stand-in ``lib``."""
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
    vt_boiler = importlib.import_module("vt_boiler")
    yield sys.modules["run"], vt_boiler
    for name in set(sys.modules) - before:
        del sys.modules[name]


class FakeHA:
    def __init__(self, registry: list[dict[str, Any]]) -> None:
        self.registry = registry
        self.calls: list[tuple[Any, ...]] = []

    async def ws_cmd(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        assert payload == {"type": "config/entity_registry/list"}
        return self.registry

    async def call(self, *args: Any, **data: Any) -> None:
        self.calls.append(args)


def test_the_new_scenarios_are_registered_for_the_gateway(j4) -> None:
    run, vt_boiler = j4
    assert run.SCENARIOS["V2"] is vt_boiler.V2
    for sid in ("C7", "M2", "V2"):
        assert sid in run.SCENARIOS
        assert run.scenario_roles(sid) == {"gateway"}


@pytest.mark.parametrize(
    "registry",
    [
        pytest.param([], id="empty"),
        pytest.param(
            [{"platform": "versatile_thermostat", "unique_id": "other", "entity_id": "number.x"}],
            id="another_number",
        ),
        pytest.param(
            [{"platform": "other", "unique_id": "boiler_activation_threshold", "entity_id": "n.y"}],
            id="another_platform",
        ),
    ],
)
async def test_v2_is_not_run_without_vts_device_threshold(j4, registry: list[dict]) -> None:
    run, vt_boiler = j4
    ha = FakeHA(registry)
    with pytest.raises(run.NotRun, match="device threshold"):
        await vt_boiler.V2(run.Run(ha, {}))
    assert ha.calls == []


async def test_v2_finds_vts_device_threshold_by_its_unique_id(j4) -> None:
    run, vt_boiler = j4
    registry = [
        {
            "platform": "versatile_thermostat",
            "unique_id": "boiler_activation_threshold",
            "entity_id": "number.central_configuration_number_activation_threshold",
        }
    ]
    found = await vt_boiler.vt_threshold(run.Run(FakeHA(registry), {}))
    assert found == "number.central_configuration_number_activation_threshold"
