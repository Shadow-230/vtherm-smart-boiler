"""Integration tests: Home Assistant runs inside the test process (no instance, no network)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

VENDOR_COMPONENTS = Path(__file__).resolve().parents[2] / "vendor" / "custom_components"

requires_vendor = pytest.mark.skipif(
    not (VENDOR_COMPONENTS / "versatile_thermostat").is_dir(),
    reason="vendor/ is not set up (docs/plan-0.1.md, A5)",
)


@pytest.fixture(autouse=True)
def _one_entry_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """P-125, T11: the integration allows one entry (``single_config_entry``), so a test never
    sets one up beside another that runs — Home Assistant's own flow would refuse it, and what
    only ever meets one entry would pass untested."""
    from homeassistant.config_entries import ConfigEntries, ConfigEntryState

    from custom_components.vtherm_smart_boiler.const import DOMAIN

    original = ConfigEntries.async_setup

    async def async_setup(entries: ConfigEntries, entry_id: str, *args: Any, **kwargs: Any) -> bool:
        entry = entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            running = [
                other.entry_id
                for other in entries.async_entries(DOMAIN)
                if other.entry_id != entry_id and other.state is ConfigEntryState.LOADED
            ]
            assert not running, f"a second entry of a single-entry integration beside {running}"
        return await original(entries, entry_id, *args, **kwargs)

    monkeypatch.setattr(ConfigEntries, "async_setup", async_setup)


@pytest.fixture(autouse=True)
def _monitoring_period_skippable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The integration tests start control at once with ``monitoring_days: 0``, which the form
    never stores and the parser refuses (PB-24): the bound is lowered in its one place for them,
    as ``low_setpoint_off`` lifts decision 11's block; ``tests/test_config.py`` keeps it."""
    from custom_components.vtherm_smart_boiler import config

    monkeypatch.setattr(config, "MONITORING_DAYS_BOUNDS", (0.0, config.MONITORING_DAYS_BOUNDS[1]))


@pytest.fixture
def hass_config_dir(tmp_path: Path) -> str:
    """Home Assistant's configuration directory: a fresh, empty one for each test under its
    ``tmp_path`` (inside ``.tmp/``). A file a test or the plugin writes there — a forecast week,
    a store — never lands in the shared test configuration inside ``.venv``, and nothing an
    earlier test left there is seen (Z1)."""
    config = tmp_path / "config"
    config.mkdir()
    return str(config)


@pytest.fixture
def boiler(hass):
    from .harness import FakeBoiler

    return FakeBoiler(hass)


@pytest.fixture
def zones(hass):
    from .harness import FakeZones

    return FakeZones(hass)


@pytest.fixture
def forecasts(hass):
    from .harness import FakeForecasts

    fake = FakeForecasts(hass)
    fake.register()
    return fake


@pytest.fixture
def blocking_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """TB-22: Home Assistant's blocking-call detection, enabled as in production — with the
    calls it skips in tests (``open``, ``listdir``, ``scandir``, ``import_module``, ...) — and
    every blocking call it catches in the event loop collected, whether it would raise or only
    log: the plugin may catch the error, so the test reads the list."""
    import traceback

    from homeassistant import block_async_io
    from homeassistant.util import loop

    found: list[str] = []
    original = loop.raise_for_blocking_call

    def collect(func: Any, check_allowed: Any = None, **kwargs: Any) -> None:
        if check_allowed is None or not check_allowed(kwargs):
            found.append(
                f"{func.__name__}{kwargs.get('args')}\n{''.join(traceback.format_stack())}"
            )
        original(func, check_allowed, **kwargs)

    monkeypatch.setattr(block_async_io, "_IN_TESTS", False)
    monkeypatch.setattr(loop, "_PREVIOUSLY_REPORTED", set())
    monkeypatch.setattr(loop, "raise_for_blocking_call", collect)
    assert not block_async_io._BLOCKED_CALLS.calls
    block_async_io.enable()
    try:
        yield found
    finally:
        for call in block_async_io._BLOCKED_CALLS.calls:
            setattr(call.object, call.function, call.original_func)
        block_async_io._BLOCKED_CALLS.calls.clear()
