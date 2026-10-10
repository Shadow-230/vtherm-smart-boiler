"""Read-only by construction: the monitor calls no service except weather.get_forecasts.

Every service call is seen — a switch's included, and one to a service nobody registered — by a
spy on ``hass.services.async_call`` itself (P-118), not by a listener on the call event, which
Home Assistant fires only for a service that exists."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotFound
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import WEATHER_ENTITY, FakeBoiler, FakeForecasts, FakeZones, ServiceSpy, analyse_now

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ALLOWED = {("weather", "get_forecasts")}


@pytest.fixture
def spy(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> ServiceSpy:
    found = ServiceSpy(hass)
    found.install(monkeypatch)
    return found


async def test_the_spy_sees_a_call_to_a_service_nobody_registered(
    hass: HomeAssistant, spy: ServiceSpy
) -> None:
    """P-118: a call to a service that does not exist — here a switch, with no switch
    integration loaded — fails, and the check still sees it; the test's own calls are left
    out."""
    with pytest.raises(ServiceNotFound):
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.boiler"})
    with pytest.raises(ServiceNotFound):
        await hass.services.async_call("switch", "turn_on", {}, context=spy.own)
    assert spy.calls == [
        ("switch", "turn_off", {"entity_id": "switch.boiler"}),
        ("switch", "turn_on", {}),
    ]
    assert spy.plugin_services() == {("switch", "turn_off")}
    assert not spy.plugin_services() <= ALLOWED


async def test_only_forecasts_are_requested(
    hass: HomeAssistant, freezer, zones: FakeZones, forecasts: FakeForecasts, spy: ServiceSpy
) -> None:
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
    # The first analysis, started in the background at setup, done: one that is still running
    # when the test asks for its own would make the test skip it (Z1).
    await hass.async_block_till_done(wait_background_tasks=True)
    for minute in range(0, 90, 5):
        freezer.tick(timedelta(minutes=5))
        boiler.set(Signal.FLAME, minute % 10 == 0)
        boiler.set(Signal.FLOW, 40.0 + minute % 7)
        zones.set("living", hvac_action="heating", valve_open_percent=50 + minute % 3)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    await analyse_now(entry.runtime_data)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert forecasts.calls  # the one allowed service was used
    assert spy.plugin_services() == ALLOWED, spy.plugin_services() - ALLOWED


async def test_the_suggestion_calls_no_service(
    hass: HomeAssistant, freezer, zones: FakeZones, spy: ServiceSpy
) -> None:
    """X6 (decision 2, S-56): the monitor's evidence of short burns at the lowest water
    temperature and the value it suggests — here where the boiler's own curve sets the water —
    reach the user as a sensor and a repair issue only: no service is called, nothing written,
    no setting changed."""
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import issue_registry as ir

    freezer.move_to(datetime(2026, 1, 10, 6, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.CH_SETPOINT))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 22.0, Signal.CH_SETPOINT: 30.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=100)
    options = {
        "signals": boiler.mapping(),
        "boiler": {"class": "read_only", "dhw": "none"},
        "zones": [{"entity_id": living}],
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    # The first analysis, started in the background at setup, done: one that is still running
    # when the test asks for its own would make the test skip it (Z1).
    await hass.async_block_till_done(wait_background_tasks=True)
    for _ in range(30):  # 3-minute burns, each ended because the water reached its setpoint
        freezer.tick(timedelta(minutes=5))
        boiler.set(Signal.FLAME, True)
        freezer.tick(timedelta(minutes=3) - timedelta(seconds=10))
        boiler.set(Signal.FLOW, 30.5)
        freezer.tick(timedelta(seconds=10))
        boiler.set(Signal.FLAME, False)
        await hass.async_block_till_done()
        boiler.set(Signal.FLOW, 22.0)
    await hass.async_block_till_done()
    await analyse_now(entry.runtime_data)
    await hass.async_block_till_done()
    sensor = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_lowest_water_suggestion"
    )
    assert sensor is not None
    state = hass.states.get(sensor)
    assert state is not None
    assert float(state.state) == 32.0
    assert state.attributes["state"] == "suggestion"
    assert state.attributes["source"] == "ch_setpoint"
    found = ir.async_get(hass).async_get_issue(DOMAIN, f"lowest_water_suggestion_{entry.entry_id}")
    assert found is not None
    assert found.translation_key == "lowest_water_suggestion_boiler"
    assert entry.options == options  # no setting changed
    assert spy.plugin_calls() == []  # no weather entity: not even a forecast
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"lowest_water_suggestion_{entry.entry_id}")
        is None
    )  # it goes with the entry's run
