"""G11 E: a long burn that does not reach the rooms — told on a monitor-only entry too."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import FakeBoiler, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SIGNALS = (Signal.FLAME, Signal.FLOW, Signal.CH_SETPOINT, Signal.MODULATION)
STEP = 300.0  # a look every five minutes


async def set_up(hass: HomeAssistant, boiler: FakeBoiler, zones: FakeZones) -> MockConfigEntry:
    options = {
        "signals": boiler.mapping(),
        "zones": [{"entity_id": entity} for entity in zones.entities.values()],
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def rooms(zones: FakeZones, living: float, bedroom: float, living_valve: int = 100) -> None:
    """Both rooms heating to 21 °C; the bedroom's valve part open, the living room's as given."""
    zones.set(
        "living",
        current_temperature=living,
        temperature=21.0,
        hvac_action="heating",
        valve_open_percent=living_valve,
        on_percent=living_valve / 100.0,
    )
    zones.set(
        "bedroom",
        current_temperature=bedroom,
        temperature=21.0,
        hvac_action="heating",
        valve_open_percent=30,
        on_percent=0.3,
    )


async def burn(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: Any,
    boiler: FakeBoiler,
    zones: FakeZones,
    hours: float,
    water: dict[Signal, float],
    living: Any = 19.0,
    bedroom: float = 21.0,
) -> None:
    """The flame on for ``hours``, a look every five minutes; ``living`` a temperature or a
    function of the hours burnt."""
    for i in range(round(hours * 3600 / STEP) + 1):
        temperature = living(i * STEP / 3600) if callable(living) else living
        rooms(zones, temperature, bedroom)
        boiler.set_many({Signal.FLAME: True, **water})
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        freezer.tick(STEP)


@pytest.fixture
async def rig(hass: HomeAssistant, zones: FakeZones):
    zones.add("living")
    zones.add("bedroom")
    # The living room cool from the start: a sudden fall while it heats would read as a window
    # probably open (G11 F), and leave it out.
    rooms(zones, 19.0, 21.0)
    boiler = FakeBoiler(hass, SIGNALS)
    boiler.set_many(
        {Signal.FLAME: False, Signal.FLOW: 40.0, Signal.CH_SETPOINT: 45.0, Signal.MODULATION: 0.0}
    )
    entry = await set_up(hass, boiler, zones)
    return entry, boiler


HOLDING = {Signal.FLOW: 45.0, Signal.CH_SETPOINT: 45.0, Signal.MODULATION: 60.0}


def sensor(hass: HomeAssistant) -> Any:
    found = [
        state
        for state in hass.states.async_all("binary_sensor")
        if state.entity_id.endswith("long_burn_without_warming")
    ]
    assert len(found) == 1
    return found[0]


async def test_a_room_short_for_three_hours_with_the_water_at_its_setpoint(
    hass: HomeAssistant, zones: FakeZones, freezer: Any, rig: Any
) -> None:
    """Three hours of flame, the living room short and not warming, the flow at its setpoint:
    the water is too cool for it — one room counts like any other (addition 2). Information
    only: no repair issue. Before three hours, nothing."""
    entry, boiler = rig
    await burn(hass, entry, freezer, boiler, zones, 2.75, HOLDING)
    assert sensor(hass).state == "off"
    await burn(hass, entry, freezer, boiler, zones, 0.5, HOLDING)
    state = sensor(hass)
    assert state.state == "on"
    assert state.attributes["reason"] == "water_too_cool"
    assert state.attributes["zones"] == [zones.entities["living"]]
    assert state.attributes["kept"]["water_too_cool_runs"] == 1
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"boiler_power_limit_{entry.entry_id}") is None
    )


async def test_the_boiler_at_its_power_limit_is_a_warning(
    hass: HomeAssistant, zones: FakeZones, freezer: Any, rig: Any
) -> None:
    """The room short, the flow 3 K below its setpoint at 95 % modulation: the boiler can give
    no more — the sensor says so, and a warning repair issue names the room; it goes with the
    flame."""
    entry, boiler = rig
    water = {Signal.FLOW: 42.0, Signal.CH_SETPOINT: 45.0, Signal.MODULATION: 95.0}
    await burn(hass, entry, freezer, boiler, zones, 3.25, water)
    assert sensor(hass).attributes["reason"] == "power_limit"
    issue_id = f"boiler_power_limit_{entry.entry_id}"
    found = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_placeholders["entities"] == zones.entities["living"]
    boiler.set(Signal.FLAME, False)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert sensor(hass).state == "off"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_rooms_over_their_setpoints_have_the_water_too_hot(
    hass: HomeAssistant, zones: FakeZones, freezer: Any, rig: Any
) -> None:
    entry, boiler = rig
    await burn(hass, entry, freezer, boiler, zones, 3.25, HOLDING, living=21.5, bedroom=21.4)
    assert sensor(hass).attributes["reason"] == "water_too_hot"


async def test_a_room_that_warms_is_no_case(
    hass: HomeAssistant, zones: FakeZones, freezer: Any, rig: Any
) -> None:
    """The living room short but rising 0.6 K over the three hours: it gets there — nothing."""
    entry, boiler = rig
    await burn(hass, entry, freezer, boiler, zones, 3.25, HOLDING, living=lambda h: 19.0 + 0.2 * h)
    assert sensor(hass).state == "off"
