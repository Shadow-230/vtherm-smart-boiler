"""VTherm Smart Boiler — a Versatile Thermostat plugin that optimises how a gas boiler runs.

Home Assistant is imported inside functions only, so the pure logic in ``core`` can be
imported and tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from .const import CONTROL, DOMAIN, UNREADABLE_ISSUE, has_control_section, owes_hand_back

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .config import EntryConfig
    from .control import ControlUnit
    from .coordinator import SmartBoilerCoordinator

PLATFORMS = ("sensor", "binary_sensor", "switch", "button")
# The notice asking what is wired to the gateway's thermostat terminals (answer K, X6).
KIND_ISSUE = "thermostat_kind_missing"
# An entity the options name that Home Assistant removed: one repair issue per entity (P-19).
REMOVED_ISSUE = "entity_removed"
# Y1's migration: stored alarm reactions decision 7 no longer offers were removed (a warning).
REACTIONS_REMOVED_ISSUE = "reactions_removed"
# The issues a control unit raises for a hand-back without a latch (decision 7, Y1).
HAND_BACK_ISSUES = ("hand_back_boiler_link_lost", "hand_back_control_error")


# Loaded through Home Assistant's import executor before first use: importing them in the event
# loop would read them from disk there.
_RUNTIME_MODULES = ("config", "coordinator", "control", "feature_manager", "entity")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.exceptions import ConfigEntryError
    from homeassistant.helpers.importlib import async_import_module

    for module in _RUNTIME_MODULES:
        await async_import_module(hass, f"{__package__}.{module}")

    from homeassistant.util import dt as dt_util

    from . import feature_manager
    from .config import ConfigError, EntryConfig
    from .control import ControlUnit
    from .coordinator import SmartBoilerCoordinator

    try:
        # A control section that cannot be used leaves control out, not the whole entry: the
        # monitor keeps running, and a hand-back still owed goes out.
        config = EntryConfig.from_options(entry.options, strict_control=False)
    except (ConfigError, KeyError, TypeError, ValueError) as err:
        # Options this version cannot read — an option a later check refuses, a hand edit —
        # stop the entry with a reason, and a boiler the last run held is not forgotten.
        await _async_report_owed_from_store(hass, entry)
        if isinstance(err, ConfigError):
            code, subject = err.code, err.subject or "-"
        else:
            import logging

            logging.getLogger(__name__).error("The options cannot be read: %s", err)
            code, subject = "unreadable_options", "-"
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="invalid_options",
            translation_placeholders={"code": code, "subject": subject},
        ) from err
    coordinator = SmartBoilerCoordinator(hass, entry, config)
    try:
        # What the last run left, first: a hand-back it owed is made before anything else can
        # fail, and the unit that makes it is the one that runs (P-05, C14).
        await coordinator.async_load()
        if config.control.configured:
            control = ControlUnit(hass, coordinator, config.control, raw=entry.options.get(CONTROL))
            control.restore(coordinator.stored_control)
            coordinator.control = control
        else:
            coordinator.hand_back_unit = _hand_back_unit(
                hass, coordinator, config, coordinator.stored_control
            )
            await _async_forget_control_session(coordinator)
            _forget_latch_issue(hass, entry)
        for unit in _units(coordinator):
            await unit.async_hand_back_owed(dt_util.utcnow().timestamp())
        _report_control_problem(hass, entry, config)
        _report_thermostat_kind(hass, entry, config)
        await coordinator.async_start()
        await coordinator.async_config_entry_first_refresh()
        for unit in _units(coordinator):
            await unit.async_start()
        entry.runtime_data = coordinator
        await _async_migrate_zone_unique_ids(hass, entry, config)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        feature_manager.async_attach(hass, coordinator)
        _remove_stale_entities(hass, entry, coordinator.expected_unique_ids)
        entry.async_on_unload(entry.add_update_listener(_async_options_updated))
        coordinator.async_start_background()
        # Last: renames and removals are followed only for an entry that runs (P-19).
        entry.async_on_unload(_follow_entities(hass, entry, coordinator))
    except Exception:
        await _async_setup_failed(hass, entry, coordinator)
        raise
    return True


async def _async_setup_failed(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartBoilerCoordinator
) -> None:
    """Nothing of a failed setup keeps running: the units hand back again if still owed (a
    persistent issue tells of one that did not get through), then every clock, listener and
    task stops. Home Assistant retries a setup that is not ready, which hands back first again;
    after an error, the issue stays until a reload or an options change."""
    import logging

    from . import feature_manager
    from .control import report_owed_hand_back

    logger = logging.getLogger(__name__)
    try:
        feature_manager.async_detach(hass, coordinator)
    except Exception:
        logger.exception("Could not let go of VT after a failed setup")
    for unit in _units(coordinator):
        await unit.async_stop()  # hands back again if still owed; never raises
    try:
        await coordinator.async_stop()
    except Exception:
        logger.exception("Could not stop cleanly after a failed setup")
    if not coordinator.loaded:
        # The stores could not even be read: what they owe is reported from them, cautiously.
        await _async_report_owed_from_store(hass, entry)
    elif not _units(coordinator) and owes_hand_back(coordinator.stored_control):
        # Owed with nothing to make it (the options that took the boiler are gone).
        report_owed_hand_back(hass, entry.entry_id, persistent=True)
    if hasattr(entry, "runtime_data"):
        # Not left for the options flow or a listener to take for a running entry.
        object.__delattr__(entry, "runtime_data")


def _units(coordinator: SmartBoilerCoordinator) -> list[ControlUnit]:
    return [unit for unit in (coordinator.control, coordinator.hand_back_unit) if unit is not None]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an entry stored by an earlier version to this one's options."""
    from .const import REMOVED_CONTROL_OPTIONS
    from .control_config import MIGRATED_HARD_MIN

    if entry.version > 1:
        return False  # from a newer version: nothing here can read it
    if entry.minor_version < 2:
        options = dict(entry.options)
        boiler = options.get("boiler")
        if isinstance(boiler, dict) and "shared_return" in boiler:
            options["boiler"] = {k: v for k, v in boiler.items() if k != "shared_return"}
        control = options.get(CONTROL)
        if isinstance(control, dict):
            options[CONTROL] = {
                key: value for key, value in control.items() if key not in REMOVED_CONTROL_OPTIONS
            }
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    if entry.minor_version < 3:
        # X6 (decision 2): the lowest water temperature's default became 20 °C; a control
        # section stored without one keeps 0.2.1's 25 °C, so no floor drops silently
        # (provisional, K4).
        options = dict(entry.options)
        control = options.get(CONTROL)
        if (
            has_control_section(options)
            and isinstance(control, Mapping)
            and control.get("hard_min") in (None, "")
        ):
            options[CONTROL] = {**control, "hard_min": MIGRATED_HARD_MIN}
        hass.config_entries.async_update_entry(entry, options=options, minor_version=3)
    if entry.minor_version < 4:
        _migrate_alarms(hass, entry)
    return True


def _migrate_alarms(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Y1 (minor version 4): 0.2.1's two low-pressure limits give way to the one "add water"
    threshold — none by default; a stored value other than the old default carries over — and
    the stored alarm reactions decision 7 no longer offers go; one warning issue names those
    that were set to hand back and now only inform. No version with stored options was ever
    released: this serves development entries and hand-edited options."""
    from homeassistant.helpers import issue_registry as ir

    from .config import migrated_monitor
    from .const import MONITOR
    from .control_config import migrated_reactions

    options = dict(entry.options)
    monitor = options.get(MONITOR)
    if isinstance(monitor, Mapping):
        options[MONITOR] = migrated_monitor(monitor)
    removed: list[str] = []
    control = options.get(CONTROL)
    if isinstance(control, Mapping) and "alarm_reactions" in control:
        kept, removed = migrated_reactions(control)
        options[CONTROL] = {**control, "alarm_reactions": kept}
    hass.config_entries.async_update_entry(entry, options=options, minor_version=4)
    if removed:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{REACTIONS_REMOVED_ISSUE}_{entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=REACTIONS_REMOVED_ISSUE,
            translation_placeholders={"alarms": ", ".join(removed)},
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from . import feature_manager

    coordinator = entry.runtime_data
    for unit in _units(coordinator):
        await unit.async_stop()  # hand back before anything else goes
    feature_manager.async_detach(hass, coordinator)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await coordinator.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The entry is gone: a hand-back it still owed can no longer be retried, so the user is
    told, with a repair issue that outlives the entry. A control state that cannot be read
    counts as owed wherever control was configured."""
    from pathlib import Path

    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.importlib import async_import_module

    await async_import_module(hass, f"{__package__}.coordinator")
    from .coordinator import async_read_control_state, control_store, main_store
    from .forecasts import remove_partition_files

    _delete_removed_issues(hass, entry.entry_id)
    for key in (
        "hand_back_owed",
        "hand_back_taken_by_other",
        "monitor_failed",  # the monitor's issue, or its note (V6)
        "control_stopped_heating",  # a blocker stopped heating (V7)
        "control_latched",  # the entry's one latch issue (V7)
        "no_zone_known",  # every zone unknown (decision 3, X3)
        "frost_zone_closed",  # a cold room VT keeps closed (decision 4, X4)
        KIND_ISSUE,  # the thermostat-terminals question not answered (X6)
        "wall_thermostat_fallback",  # the wall thermostat on a gateway set low (X6)
        "lowest_water_suggestion",  # the lowest water temperature's suggestion (X6)
        "control_options_invalid",
        "auto_tpi_blocked",
        "learning_not_paused",
        "vt_central_entry_not_running",  # VT's central entry not running (X7)
        UNREADABLE_ISSUE,
        # Y1: the notifications (a reload keeps them), the hand-back issues, the migration's.
        "add_water",
        "pressure_high",
        "flue_gas_high",
        "pressure_falling",
        "boiler_fault",
        *HAND_BACK_ISSUES,
        REACTIONS_REMOVED_ISSUE,
    ):
        ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry.entry_id}")
    store = main_store(hass, entry.entry_id)
    control = control_store(hass, entry.entry_id)
    read = await async_read_control_state(
        hass, entry.entry_id, entry.options, main=store, control=control
    )
    if read.owed:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"hand_back_owed_after_removal_{entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="hand_back_owed_after_removal",
        )
    # Nothing of the entry stays behind: its stores and its forecast weeks.
    await control.async_remove()
    await store.async_remove()
    await hass.async_add_executor_job(
        remove_partition_files, Path(hass.config.path(".storage")), entry.entry_id
    )


def _report_control_problem(hass: HomeAssistant, entry: ConfigEntry, config: EntryConfig) -> None:
    import logging

    from homeassistant.helpers import issue_registry as ir

    issue_id = f"control_options_invalid_{entry.entry_id}"
    if config.control_problem is None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    # The raw reason goes to the log, not into a translated text (U9).
    logging.getLogger(__name__).warning(
        "The control options cannot be used, so control is off: %s", config.control_problem
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="control_options_invalid",
    )


def _report_thermostat_kind(hass: HomeAssistant, entry: ConfigEntry, config: EntryConfig) -> None:
    """Answer K: a gateway entry without an answer to the thermostat-terminals question keeps
    control stopped (its blocker), and this repair issue asks for the answer; it goes at the
    setup after the answer is stored (every options save sets the entry up again)."""
    from homeassistant.helpers import issue_registry as ir

    from .control_config import thermostat_kind_missing

    issue_id = f"{KIND_ISSUE}_{entry.entry_id}"
    if not thermostat_kind_missing(config.control):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=KIND_ISSUE,
    )


async def _async_report_owed_from_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The options cannot be read, so no unit can hand back: if the last run left the boiler
    held — or its control state cannot be read while the options hold a control section — the
    user is told, for good, and can settle it by hand."""
    from .control import report_owed_hand_back
    from .coordinator import async_read_control_state

    try:
        read = await async_read_control_state(hass, entry.entry_id, entry.options)
    except Exception:  # an unexpected failure: the cautious answer
        import logging

        logging.getLogger(__name__).exception("Could not read the stored control state")
        owed = has_control_section(entry.options)
    else:
        owed = read.owed
    if owed:
        report_owed_hand_back(hass, entry.entry_id, persistent=True)


def _hand_back_unit(
    hass: HomeAssistant,
    coordinator: SmartBoilerCoordinator,
    config: EntryConfig,
    stored: Mapping[str, Any],
) -> ControlUnit | None:
    """Control is not in the options, but the last run left a hand-back owed (``stored``, the
    control state read at setup): a unit built from the options that took the boiler makes it,
    and does nothing else but follow the SmartPI resumes it left. With nothing owed but such
    resumes, a unit without options only follows them (C15)."""
    import logging

    from homeassistant.helpers import issue_registry as ir

    from .control import ControlUnit
    from .control_config import ControlOptions, parse_control

    if not owes_hand_back(stored):
        if not _learning_left(stored):
            return None
        unit = ControlUnit(hass, coordinator, ControlOptions(), follow_learning=True)
        unit.restore(stored)
        return unit
    taken_with = stored.get("taken_with")
    options = None
    if isinstance(taken_with, Mapping):
        try:
            options = parse_control(taken_with, config.installation, None)
        except Exception:  # whatever cannot be read: the user is asked to hand back by hand
            options = None
    if options is None or not options.configured:
        logging.getLogger(__name__).error(
            "A hand-back is owed, but the options that took the boiler are gone: return the "
            "boiler to its own control by hand"
        )
        entry_id = coordinator.config_entry.entry_id
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"hand_back_owed_{entry_id}",
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="hand_back_owed",
            data={"entry_id": entry_id},
        )
        return None
    unit = ControlUnit(hass, coordinator, options, raw=taken_with, hand_back_only=True)
    unit.restore(stored)
    return unit


async def _async_forget_control_session(coordinator: SmartBoilerCoordinator) -> None:
    """Control is not in the options: the wish and the last command the last run stored go at
    once, so control added back later starts off, with nothing to give again. A unit that only
    hands back or follows learning stores them so itself."""
    stored = coordinator.stored_control
    if not stored.get("enabled") and stored.get("last_command") is None:
        return
    coordinator.stored_control = {**stored, "enabled": False, "last_command": None}
    await coordinator.async_save_control_now()


def _forget_latch_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Control is not in the options: no control switch is left to clear the latch its issue
    tells of (V7), nor a hand-back without a latch to resume (Y1), so their issues go."""
    from homeassistant.helpers import issue_registry as ir

    for key in ("control_latched", *HAND_BACK_ISSUES):
        ir.async_delete_issue(hass, DOMAIN, f"{key}_{entry.entry_id}")


def _learning_left(stored: Mapping[str, Any]) -> bool:
    """Whether the last run left SmartPI zones paused, or resumes still to be followed."""
    return any(
        isinstance(stored.get(key), Mapping) and stored[key] for key in ("paused", "resuming")
    )


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload for a change of the options only: a reload hands control back and starts a new
    session, which a new title or preference — the options' level of detail too, which changes
    only what they show — must not cause."""
    from .const import LEVEL

    def meaningful(options: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in options.items() if key != LEVEL}

    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or meaningful(entry.options) != meaningful(coordinator.options):
        # Not running (its setup failed): whatever changed, it is set up again.
        await hass.config_entries.async_reload(entry.entry_id)


def _remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry, expected: set[str]) -> None:
    """Entities the options no longer create — a zone or circuit taken out, a signal unmapped,
    control removed — go from the registry. Disabled ones the platforms still create stay."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id not in expected:
            registry.async_remove(registered.entity_id)


async def _async_migrate_zone_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry, config: EntryConfig
) -> None:
    """Up to 0.2 a zone's entities were keyed on the thermostat's entity ID; they move to its
    registry entry, keeping their entity and history."""
    from homeassistant.core import callback
    from homeassistant.helpers import entity_registry as er

    from .entity import zone_key

    old_keys = {zone: zone_key(hass, zone) for zone in config.zone_entities}

    @callback
    def migrate(registered: er.RegistryEntry) -> dict[str, str] | None:
        for zone, key in old_keys.items():
            suffix = f"_{zone}"
            if zone != key and registered.unique_id.endswith(suffix):
                return {"new_unique_id": registered.unique_id[: -len(suffix)] + f"_{key}"}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, migrate)


def _follow_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SmartBoilerCoordinator
) -> Callable[[], None]:
    """P-19 (follow, provisional, K4): every entity the options name — and, for a unit that
    only hands back, the options the boiler was taken with — is followed in the entity registry.
    A rename is carried into the options, one reload as any options save (X5.13), and into what
    control keeps for it; a removal raises a repair issue naming the fields, and the plugin goes
    on without the entity (the missing-data rules) until it is back or the options no longer
    name it. Any other change of the registry is not the plugin's."""
    from homeassistant.core import Event, callback
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.event import async_track_entity_registry_updated_event

    named = _named_entities(entry, coordinator)
    _clear_removed_issues(hass, entry, named)
    # Renames of one batch — a device renamed renames its entities one after the other — are
    # applied together at the next turn of the event loop: the options' save starts the reload
    # at once, and its unload would stop following before the rest of the batch.
    pending: list[tuple[str, str]] = []

    @callback
    def follow_pending() -> None:
        renames = list(pending)
        pending.clear()
        _follow_renames(hass, entry, coordinator, renames)

    @callback
    def changed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        entity = data["entity_id"]
        if data["action"] == "update":
            old = data.get("old_entity_id")
            if isinstance(old, str) and old != entity:
                if not pending:
                    hass.loop.call_soon(follow_pending)
                pending.append((old, entity))
        elif data["action"] == "remove":
            fields = _named_entities(entry, coordinator).get(entity, ())
            _report_removed(hass, entry, entity, fields)
        else:  # registered again: back in Home Assistant
            ir.async_delete_issue(hass, DOMAIN, _removed_issue_id(entry.entry_id, entity))

    return async_track_entity_registry_updated_event(hass, list(named), changed)


def _named_entities(
    entry: ConfigEntry, coordinator: SmartBoilerCoordinator
) -> dict[str, tuple[str, ...]]:
    from .config import named_entities

    found = dict(named_entities(entry.options))
    for unit in _units(coordinator):
        for entity, fields in unit.named_entities().items():
            found.setdefault(entity, fields)
    return found


def _follow_renames(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: SmartBoilerCoordinator,
    renames: list[tuple[str, str]],
) -> None:
    """Entities the plugin uses got other IDs: what control keeps for them follows — stored at
    once — and so do the options, whose save reloads the entry as any options save does: one
    reload for the batch. Where only what a unit that hands back keeps named one, the entry is
    reloaded to hand back through the new ID. An entry removed meanwhile is left alone."""
    import logging

    from .config import rename_entity

    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        return
    options: dict[str, Any] = dict(entry.options)
    kept = False
    for old, new in renames:
        logging.getLogger(__name__).info("%s is now %s: the plugin follows it", old, new)
        for unit in _units(coordinator):
            kept = unit.rename_entity(old, new) or kept
        coordinator.rename_zone(old, new)
        options = rename_entity(options, old, new)
    if kept:
        coordinator.schedule_control_save()
    if options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=options)
    elif kept:
        hass.config_entries.async_schedule_reload(entry.entry_id)


def _removed_issue_id(entry_id: str, entity: str) -> str:
    return f"{REMOVED_ISSUE}_{entry_id}_{entity}"


def _report_removed(
    hass: HomeAssistant, entry: ConfigEntry, entity: str, fields: tuple[str, ...]
) -> None:
    """The repair issue of an entity the options name that Home Assistant removed: a warning,
    not fixable, kept across restarts (nothing would raise it again)."""
    import logging

    from homeassistant.helpers import issue_registry as ir

    shown = ", ".join(fields) or "-"
    logging.getLogger(__name__).warning(
        "%s is no longer in Home Assistant (%s): the plugin goes on without it", entity, shown
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        _removed_issue_id(entry.entry_id, entity),
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REMOVED_ISSUE,
        translation_placeholders={"field": shown, "entity": entity},
    )


def _clear_removed_issues(
    hass: HomeAssistant, entry: ConfigEntry, named: Mapping[str, tuple[str, ...]]
) -> None:
    """At setup: an entity's removal issue goes once the options no longer name it or it is
    back in the registry."""
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import issue_registry as ir

    prefix = _removed_issue_id(entry.entry_id, "")
    registry = er.async_get(hass)
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain != DOMAIN or not issue_id.startswith(prefix):
            continue
        entity = issue_id.removeprefix(prefix)
        if entity not in named or registry.async_get(entity) is not None:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def _delete_removed_issues(hass: HomeAssistant, entry_id: str) -> None:
    """The entry is gone: so are its removal issues."""
    from homeassistant.helpers import issue_registry as ir

    prefix = _removed_issue_id(entry_id, "")
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
