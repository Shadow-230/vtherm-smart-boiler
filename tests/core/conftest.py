"""Core tests: layer 1 of ``PLAN.md``'s "Test environment" — plain pytest, no Home Assistant.

They run on their own, with Home Assistant's pytest plugin disabled, as the first of the two runs
(P-120): ``python -m pytest -q -p no:homeassistant ... tests/core``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_home_assistant(pytestconfig: pytest.Config) -> Iterator[None]:
    """Run on their own, the core tests import nothing of Home Assistant — neither the code
    under test nor the tests themselves. In one run with the other tests, Home Assistant's plugin
    has loaded it first, and there is nothing to check."""
    yield
    if pytestconfig.pluginmanager.has_plugin("homeassistant"):
        return
    loaded = sorted(name for name in sys.modules if name.split(".")[0] == "homeassistant")
    assert not loaded, f"the core tests imported Home Assistant: {loaded[:5]}"
