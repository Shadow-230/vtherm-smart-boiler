"""Read-only by construction: the monitor calls no service except weather.get_forecasts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import WEATHER_ENTITY, FakeBoiler, FakeForecasts, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ALLOWED = {("weather", "get_forecasts")}


async def test_only_forecasts_are_requested(
    hass: HomeAssistant, freezer, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    calls: list[tuple[str, str]] = []

    def record(event: Event) -> None:
        calls.append((event.data["domain"], event.data["service"]))

    hass.bus.async_listen(EVENT_CALL_SERVICE, record)
    freezer.move_to(datetime(2026, 1, 10, 6, tzinfo=UTC))
    boiler = FakeBoiler(hass)
    boiler.set_many(
        dict.fromkeys(
            (
                Signal.FLOW,
                Signal.RETURN,
                Signal.MODULATION,
                Signal.PRESSURE,
                Signal.FLUE_GAS,
                Signal.OUTDOOR,
            ),
            1.0,
        )
    )
    boiler.set_many(
        {
            Signal.FLAME: True,
            Signal.DHW_ACTIVE: False,
            Signal.CH_ACTIVE: True,
            Signal.PUMP_RUNNING: True,
            Signal.GAS_METER: 10.0,
        }
    )
    hass.states.async_set("switch.fireplace", "on")
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": boiler.mapping(),
            "weather": WEATHER_ENTITY,
            "zones": [
                {
                    "entity_id": living,
                    "foreign_heat": [{"entity_id": "switch.fireplace", "kind": "switch"}],
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for minute in range(0, 90, 5):
        freezer.tick(timedelta(minutes=5))
        boiler.set(Signal.FLAME, minute % 10 == 0)
        boiler.set(Signal.FLOW, 40.0 + minute % 7)
        zones.set("living", hvac_action="heating", valve_open_percent=50 + minute % 3)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    await entry.runtime_data.async_run_analysis()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert forecasts.calls  # the one allowed service was used
    assert set(calls) <= ALLOWED, set(calls) - ALLOWED
