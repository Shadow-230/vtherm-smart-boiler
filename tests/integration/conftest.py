"""Integration tests: Home Assistant runs inside the test process (no instance, no network)."""

from __future__ import annotations

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
