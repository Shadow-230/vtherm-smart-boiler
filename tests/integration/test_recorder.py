"""The history rebuilt from Home Assistant's own recorder, not a stand-in for it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import FakeBoiler

# The recorder is set up before Home Assistant's test instance, which it needs to be.
pytestmark = pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations")


async def test_the_history_is_rebuilt_from_home_assistants_own_recorder(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Home Assistant's recorder itself, not a stand-in for it: three days of burns, the flow
    unavailable for an hour among them, are read back at setup, in order and with the gap, and
    the analysis counts the burns."""
    start = datetime(2026, 1, 10, tzinfo=UTC)
    freezer.move_to(start)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    # The recorder takes each state change as it is set; waiting for it once, at the end,
    # keeps the test quick.
    for step in range(3 * 24 * 2):  # every half hour: ten minutes burning, twenty off
        boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
        freezer.tick(timedelta(minutes=10))
        boiler.set_many({Signal.FLAME: False, Signal.FLOW: 35.0})
        if step == 60:
            boiler.set(Signal.FLOW, None)  # unavailable for an hour
            freezer.tick(timedelta(hours=1))
            boiler.set(Signal.FLOW, 35.0)
        freezer.tick(timedelta(minutes=20))
    await async_wait_recording_done(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={
            "signals": boiler.mapping(),
            "parameters": {"boiler_min_power": 4.0, "boiler_max_power": 25.0},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    flame = coordinator.history.signals[Signal.FLAME]
    flow = coordinator.history.signals[Signal.FLOW]
    assert next(iter(flame)).t == pytest.approx(start.timestamp(), abs=60)
    ons = [s.t for s in flame if s.value is True]
    assert len(ons) == 3 * 24 * 2
    assert [s.value for s in flow].count(None) == 1  # the hour without a reading
    await coordinator.async_run_analysis()
    day = coordinator.data.analysis.day
    burns = day.heating.starts + day.unknown.starts + day.dhw.starts
    assert burns == pytest.approx(48, abs=1)
