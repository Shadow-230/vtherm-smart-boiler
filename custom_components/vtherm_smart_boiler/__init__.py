"""VTherm Smart Boiler — a Versatile Thermostat plugin that optimises how a gas boiler runs.

Home Assistant is imported inside functions only, so the pure logic in ``core`` can be
imported and tested on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import CONTROL, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .config import EntryConfig
    from .control import ControlUnit
    from .coordinator import SmartBoilerCoordinator

PLATFORMS = ("sensor", "binary_sensor", "switch")


# Loaded through Home Assistant's import executor before first use: importing them in the event
# loop would read them from disk there.
_RUNTIME_MODULES = ("config", "coordinator", "control", "feature_manager")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.exceptions import ConfigEntryError
    from homeassistant.helpers.importlib import async_import_module

    for module in _RUNTIME_MODULES:
        await async_import_module(hass, f"{__package__}.{module}")

    from . import feature_manager
    from .config import ConfigError, EntryConfig
    from .control import ControlUnit
    from .coordinator import SmartBoilerCoordinator

    try:
        # A control section that cannot be used leaves control out, not the whole entry: the
        # monitor keeps running, and a hand-back still owed goes out.
        config = EntryConfig.from_options(entry.options, strict_control=False)
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
        _report_control_problem(hass, entry, config)
        if config.control.configured:
            control = ControlUnit(
                hass, coordinator, config.control, raw=entry.options.get(CONTROL)
            )
            control.restore(coordinator.stored_control)
            coordinator.control = control
            await control.async_start()
        else:
            coordinator.hand_back_unit = _hand_back_unit(hass, coordinator, config)
            if coordinator.hand_back_unit is not None:
                await coordinator.hand_back_unit.async_start()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        feature_manager.async_attach(hass, coordinator)
        if not config.control.configured:
            _remove_control_entities(hass, entry)
    except Exception:
        feature_manager.async_detach(hass, coordinator)
        await _async_stop(coordinator)  # no control clock is left running
        raise
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    coordinator.async_start_background()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from . import feature_manager

    coordinator = entry.runtime_data
    for unit in (coordinator.control, coordinator.hand_back_unit):
        if unit is not None:
            await unit.async_stop()  # hand back before anything else goes
    feature_manager.async_detach(hass, coordinator)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await coordinator.async_stop()
    return unloaded


async def _async_stop(coordinator: SmartBoilerCoordinator) -> None:
    for unit in (coordinator.control, coordinator.hand_back_unit):
        if unit is not None:
            await unit.async_stop()
    await coordinator.async_stop()


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The entry is gone: a hand-back it still owed can no longer be retried, so the user is
    told, with a repair issue that outlives the entry."""
    from pathlib import Path

    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.storage import Store

    from .coordinator import STORAGE_VERSION
    from .forecasts import remove_partition_files

    for key in (
        "hand_back_owed",
        "control_options_invalid",
        "auto_tpi_blocked",
        "learning_not_paused",
    ):
        ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry.entry_id}")
    store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    data = await store.async_load() or {}
    control = data.get("control")
    owed = isinstance(control, dict) and (
        control.get("hand_back_pending") or control.get("controlling")
    )
    if owed:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"hand_back_owed_after_removal_{entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="hand_back_owed_after_removal",
        )
    # Nothing of the entry stays behind: its store and its forecast weeks.
    await store.async_remove()
    await hass.async_add_executor_job(
        remove_partition_files, Path(hass.config.path(".storage")), entry.entry_id
    )


def _report_control_problem(hass: HomeAssistant, entry: ConfigEntry, config: EntryConfig) -> None:
    from homeassistant.helpers import issue_registry as ir

    issue_id = f"control_options_invalid_{entry.entry_id}"
    if config.control_problem is None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="control_options_invalid",
        translation_placeholders={"problem": config.control_problem},
    )


def _hand_back_unit(
    hass: HomeAssistant, coordinator: SmartBoilerCoordinator, config: EntryConfig
) -> ControlUnit | None:
    """Control is not in the options, but the last run left a hand-back owed: a unit built from
    the options that took the boiler makes it, and does nothing else."""
    import logging

    from homeassistant.helpers import issue_registry as ir

    from .control import ControlUnit
    from .control_config import parse_control

    stored = coordinator.stored_control
    owed = stored.get("hand_back_pending") or stored.get("controlling")
    if not owed:
        return None
    taken_with = stored.get("taken_with")
    try:
        options = parse_control(taken_with, config.installation, None)
    except (KeyError, TypeError, ValueError):
        options = None
    if options is None or not options.configured:
        logging.getLogger(__name__).error(
            "A hand-back is owed, but the options that took the boiler are gone: return the "
            "boiler to its own control by hand"
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"hand_back_owed_{coordinator.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="hand_back_owed",
        )
        return None
    unit = ControlUnit(hass, coordinator, options, raw=taken_with, hand_back_only=True)
    unit.restore(stored)
    return unit


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload for a change of the options only: a reload hands control back and starts a new
    session, which a new title or preference must not cause."""
    if dict(entry.options) != entry.runtime_data.options:
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
