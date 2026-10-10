"""The entry's device and entities as Home Assistant registers them (TB-23), and no blocking call in
the event loop through setup, reload and removal (TB-22)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.vtherm_smart_boiler import PLATFORMS
from custom_components.vtherm_smart_boiler.const import DOMAIN

from .harness import FakeForecasts, FakeZones
from .test_features import _setup

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# Each platform's limit on parallel updates: the coordinator's readers none, an action at a time.
PARALLEL = {"sensor": 0, "binary_sensor": 0, "switch": 1, "button": 1}
DIAGNOSTIC = ("connection", "features", "signal_problems", "forecast_snapshots")
CONFIG = ("reset_comfort_correction",)
DEVICE_CLASSES = {
    "connection": BinarySensorDeviceClass.CONNECTIVITY,
    "alarm_flue_gas_high": BinarySensorDeviceClass.PROBLEM,
    "alarm_frequent_starts": BinarySensorDeviceClass.PROBLEM,
    "outdoor_sensor_problem": BinarySensorDeviceClass.PROBLEM,
    "verdict": SensorDeviceClass.ENUM,
    "control_state": SensorDeviceClass.ENUM,
    "control_setpoint": SensorDeviceClass.TEMPERATURE,
    "median_burn": SensorDeviceClass.DURATION,
    "burner_hours": SensorDeviceClass.DURATION,
    "heating_threshold": SensorDeviceClass.TEMPERATURE,
}


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_platform_limits_its_parallel_updates(platform: str) -> None:
    module = importlib.import_module(f"custom_components.vtherm_smart_boiler.{platform}")
    assert module.PARALLEL_UPDATES == PARALLEL[platform]


async def test_one_service_device_holds_every_entity(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    """TB-23: one device per entry, identified by the entry, a service named by the entry's
    title; the diagnostic entities in the diagnostic category, the reset button among the
    configuration ones, and the device classes as designed."""
    entry = await _setup(hass, zones, "water", lambda options: None)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    (device,) = devices
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.name == entry.title
    registry = er.async_get(hass)
    entities = {
        e.unique_id.removeprefix(f"{entry.entry_id}_"): e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert {e.device_id for e in entities.values()} == {device.id}
    for key in DIAGNOSTIC:
        assert entities[key].entity_category is EntityCategory.DIAGNOSTIC, key
    factors = [e for k, e in entities.items() if k.startswith("emitter_power_factor_")]
    assert factors
    assert all(e.entity_category is EntityCategory.DIAGNOSTIC for e in factors)
    for key in CONFIG:
        assert entities[key].entity_category is EntityCategory.CONFIG, key
    for key, device_class in DEVICE_CLASSES.items():
        assert entities[key].original_device_class == device_class, key
    for key, entity in entities.items():
        if key.startswith(("hot_water_", "foreign_heat_")):
            assert entity.original_device_class == BinarySensorDeviceClass.HEAT, key
        elif key.startswith("alarm_"):
            assert entity.original_device_class == BinarySensorDeviceClass.PROBLEM, key
        if entity.entity_category is None:
            assert key not in DIAGNOSTIC


async def test_no_blocking_call_in_the_event_loop(
    hass: HomeAssistant,
    zones: FakeZones,
    forecasts: FakeForecasts,
    blocking_calls: list[str],
) -> None:
    """TB-22: with Home Assistant's blocking-call detection on, as outside tests, an entry with
    control is set up, reloaded and removed — the forecast weeks' files among what it reads and
    removes — and no blocking call is caught."""
    storage = Path(hass.config.path(".storage"))
    await hass.async_add_executor_job(lambda: storage.mkdir(parents=True, exist_ok=True))
    entry = await _setup(hass, zones, "water", lambda options: None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert blocking_calls == []
