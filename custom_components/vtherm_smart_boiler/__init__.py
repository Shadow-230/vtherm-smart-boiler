"""VTherm Smart Boiler — a Versatile Thermostat plugin that optimises how a gas boiler runs.

Home Assistant is imported inside functions only, so the pure logic in ``core`` can be
imported and tested on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import SmartBoilerCoordinator

PLATFORMS = ("sensor", "binary_sensor", "switch")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.exceptions import ConfigEntryError

    from . import feature_manager
    from .config import ConfigError, EntryConfig
    from .control import ControlUnit
    from .coordinator import SmartBoilerCoordinator

    try:
        config = EntryConfig.from_options(entry.options)
    except ConfigError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="invalid_options",
            translation_placeholders={"code": err.code, "subject": err.subject or "-"},
        ) from err
    coordinator = SmartBoilerCoordinator(hass, entry, config)
    try:
        await coordinator.async_start()
        await coordinator.async_config_entry_first_refresh()
        if config.control.configured:
            control = ControlUnit(hass, coordinator, config.control)
            control.restore(coordinator.stored_control)
            coordinator.control = control
            await control.async_start()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await _async_stop(coordinator)
        raise
    feature_manager.async_attach(hass, coordinator)
    if not config.control.configured:
        _remove_control_entities(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    coordinator.async_start_background()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from . import feature_manager

    coordinator = entry.runtime_data
    if coordinator.control is not None:
        await coordinator.control.async_stop()  # hand back before anything else goes
    feature_manager.async_detach(hass, coordinator)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await coordinator.async_stop()
    return unloaded


async def _async_stop(coordinator: SmartBoilerCoordinator) -> None:
    if coordinator.control is not None:
        await coordinator.control.async_stop()
    await coordinator.async_stop()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_control_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Control was removed from the options: its entities go from the registry too."""
    from homeassistant.helpers import entity_registry as er

    from .control import ControlAlarm

    keys = [
        ("switch", "control"),
        ("sensor", "control_state"),
        ("sensor", "control_setpoint"),
        *(("binary_sensor", f"alarm_{kind.value}") for kind in ControlAlarm),
    ]
    registry = er.async_get(hass)
    for domain, key in keys:
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
        if entity_id is not None:
            registry.async_remove(entity_id)
