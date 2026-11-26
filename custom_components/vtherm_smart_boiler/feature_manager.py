"""A VT feature manager: the channel through which VT hands each of its thermostats to the plugin
(``vtherm_api``). It publishes nothing on VT's thermostats (I12.9, the user's decision of
2026-11-25: the water interface went, nobody read it) and never controls.

VT picks up external feature managers from the ``vtherm_api`` registry when a thermostat starts
(research F4): a thermostat already running sees the manager only after VT's next reload, which
the plugin never triggers itself. The factory is registered only while VT is loaded — asking
``vtherm_api`` for its API before VT sets it up would leave VT a bare one — and again whenever VT
has created a new API (VT up to 10.6.4 drops it with its last entry; 10.6.5 keeps it while a
plugin is registered, ``vtherm_central_api.py`` ``remove_entry``). Every method of the manager
catches its own errors, and every call the plugin makes on VT's API is inside ``try``, so no
error of the plugin's ever reaches VT (T-53).

Whether the manager works is shown: a repair issue when VT cannot load feature managers — an API
without them, or a VT older than the first version that creates them, whatever its API offers
(P-60) — and one listing the zones VT shows running whose thermostat VT has not handed over some
time after the registration: it started before it and needs VT's reload (P-59).
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from . import vtherm_link
from .const import DOMAIN, VT_DOMAIN

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
MANAGER_NAME = DOMAIN
DATA_KEY = f"{DOMAIN}_feature_manager"
UNSUPPORTED_ISSUE = "vt_feature_manager_unsupported"
RELOAD_GRACE_S = 15 * 60  # a started thermostat is handed over within this, else needs a reload


class RegistrationState(StrEnum):
    WAITING = "waiting"  # VT is not loaded, or has no API yet
    UNSUPPORTED = "unsupported"  # VT's API has no feature managers (an older vtherm_api)
    REGISTERED = "registered"


class SmartBoilerFeatureManager:
    """One per VT thermostat: keeps the thermostat VT handed over, for the plugin to read through
    ``vtherm_api``; publishes nothing, never controls."""

    def __init__(self, hass: HomeAssistant, thermostat: Any) -> None:
        self._hass = hass
        self._thermostat = thermostat
        try:  # the zone's values are read from it through ``vtherm_api`` (``vtherm_link``)
            vtherm_link.register_thermostat(hass, thermostat)
        except Exception:  # never into VT
            _LOGGER.debug("Could not keep a VT thermostat", exc_info=True)

    def post_init(self, entry_infos: Any) -> None:
        return None

    async def start_listening(self, force: bool = False) -> None:
        return None

    def stop_listening(self) -> bool | None:
        try:  # VT removes the thermostat: its values come from nowhere else now
            vtherm_link.unregister_thermostat(self._hass, self._thermostat)
        except Exception:  # never into VT
            _LOGGER.debug("Could not forget a VT thermostat", exc_info=True)
        return None

    async def refresh_state(self) -> bool:
        return False  # nothing of the manager's own to refresh

    def restore_state(self, old_state: Any) -> None:
        return None

    def add_listener(self, func: CALLBACK_TYPE) -> None:
        return None  # nothing here changes on its own

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def is_detected(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return MANAGER_NAME

    @property
    def hass(self) -> HomeAssistant:
        return self._hass


class SmartBoilerFeatureFactory:
    """The factory VT asks for a manager per thermostat."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def name(self) -> str:
        return MANAGER_NAME

    def supports(self, thermostat: Any) -> bool:
        return True  # every thermostat; the plugin reads only its zones'

    def create(self, thermostat: Any) -> SmartBoilerFeatureManager:
        return SmartBoilerFeatureManager(self._hass, thermostat)


def _api_name() -> str:
    try:
        from vtherm_api.const import VTHERM_API_NAME
    except ImportError:
        return "vtherm_api"  # the name in vtherm_api 0.5.0
    return str(VTHERM_API_NAME)


def _stored_api(hass: HomeAssistant) -> Any | None:
    """The API instance VT keeps, without creating one."""
    data = hass.data.get(VT_DOMAIN)
    return data.get(_api_name()) if isinstance(data, dict) else None


def _api(hass: HomeAssistant) -> tuple[Any | None, RegistrationState]:
    """VT's API once VT has created it, with what it allows. ``get_vtherm_api`` is called only
    when the instance exists, as it would create a bare one otherwise. A VT older than the oldest
    the plugin supports is unsupported whatever its API offers (I12.6; P-60: VT 10.0 and 10.1 take
    a registration and never create a manager); its version unknown, the API's capability
    decides."""
    if VT_DOMAIN not in hass.config.components:
        return None, RegistrationState.WAITING
    if vtherm_link.vt_supported(vtherm_link.vt_version(hass)) is False:
        return None, RegistrationState.UNSUPPORTED
    try:
        from vtherm_api.vtherm_api import VThermAPI
    except ImportError:
        return None, RegistrationState.UNSUPPORTED
    if _stored_api(hass) is None:
        return None, RegistrationState.WAITING
    try:
        api = VThermAPI.get_vtherm_api(hass)
    except Exception:
        _LOGGER.debug("VT's API is not available", exc_info=True)
        return None, RegistrationState.WAITING
    if api is None:
        return None, RegistrationState.WAITING
    try:
        supported = callable(getattr(api, "register_feature_manager", None))
    except Exception:  # an API that cannot even say: as without the method
        _LOGGER.debug("VT's API could not be asked for feature managers", exc_info=True)
        supported = False
    if not supported:
        return None, RegistrationState.UNSUPPORTED
    return api, RegistrationState.REGISTERED


class FeatureRegistration:
    """Registers the factory once for all installations, as soon as VT is loaded, and again
    on each API VT creates later."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._factory = SmartBoilerFeatureFactory(hass)
        self._api: Any | None = None
        # PB-46: the API object that refused the factory is not asked again; only the first
        # refusal is logged with its trace.
        self._refused: Any | None = None
        self._refusal_logged = False
        self._unsub: CALLBACK_TYPE | None = None
        self._unsub_entries: CALLBACK_TYPE | None = None
        self.state = RegistrationState.WAITING
        self.registered_at: float | None = None  # when the current API got the factory

    def start(self) -> None:
        # VT 10.6.5 keeps its API while a plugin is registered; a real 10.6.4, which the floor
        # lets through (``vtherm_link.VT_OLDEST``), drops it with its last entry and creates a new
        # one when an entry is set up again. Home Assistant's own signal for a VT entry being set
        # up gives the new API the factory before VT builds the entry's thermostats, as SmartPI
        # does — no state of VT's read.
        self._unsub_entries = async_dispatcher_connect(
            self._hass, SIGNAL_CONFIG_ENTRY_CHANGED, self._on_entry_changed
        )
        if not self.check():
            self._unsub = self._hass.bus.async_listen(EVENT_COMPONENT_LOADED, self._on_loaded)

    @callback
    def _on_entry_changed(self, _change: ConfigEntryChange, entry: ConfigEntry) -> None:
        if entry.domain == VT_DOMAIN and entry.state in (
            ConfigEntryState.SETUP_IN_PROGRESS,
            ConfigEntryState.LOADED,
        ):
            self.check()

    @callback
    def _on_loaded(self, event: Event) -> None:
        if event.data.get("component") == VT_DOMAIN and self.check() and self._unsub:
            self._unsub()
            self._unsub = None

    def check(self) -> bool:
        """Registered with VT's current API — again, if VT has created a new one. Never raises
        (T-53): an unexpected error leaves it waiting, to be checked again at the next update."""
        try:
            return self._check()
        except Exception:
            _LOGGER.warning("Could not check the VT feature manager's registration", exc_info=True)
            self._api = None
            self.registered_at = None
            self._set_state(RegistrationState.WAITING)
            return False

    def _check(self) -> bool:
        api, state = _api(self._hass)
        if api is not None and api is self._refused:
            state = RegistrationState.UNSUPPORTED  # refused before: not asked again (PB-46)
        elif api is not None and api is not self._api:
            try:
                api.register_feature_manager(self._factory)
            except Exception:
                log = _LOGGER.debug if self._refusal_logged else _LOGGER.warning
                log("Could not register the VT feature manager", exc_info=True)
                self._refusal_logged = True
                self._refused = api
                api, state = None, RegistrationState.UNSUPPORTED
            else:
                self._api = api
                self.registered_at = dt_util.utcnow().timestamp()
        elif api is None:
            self._api = None
            self.registered_at = None
        self._set_state(state)
        return self._api is not None

    def _set_state(self, state: RegistrationState) -> None:
        """The issue rises while unsupported and goes only once registered — not while VT is
        not known yet (Home Assistant starting) nor at an unload, so the user's "ignore" sticks
        (PB-50); it goes with the entry (``async_remove_issue``)."""
        self.state = state
        if state is RegistrationState.UNSUPPORTED:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                UNSUPPORTED_ISSUE,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=UNSUPPORTED_ISSUE,
                translation_placeholders={"version": vtherm_link.VT_OLDEST_SHOWN},
            )
        elif state is RegistrationState.REGISTERED:
            ir.async_delete_issue(self._hass, DOMAIN, UNSUPPORTED_ISSUE)

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_entries is not None:
            self._unsub_entries()
            self._unsub_entries = None
        api, self._api = self._api, None
        if api is None:
            return
        try:  # the instance it was registered with, even if VT has since dropped it
            unregister = getattr(api, "unregister_feature_manager", None)
            if callable(unregister):
                unregister(MANAGER_NAME)
        except Exception:
            _LOGGER.debug("Could not unregister the VT feature manager", exc_info=True)


def async_remove_issue(hass: HomeAssistant) -> None:
    """The entry is removed: the issue goes with it (PB-50)."""
    ir.async_delete_issue(hass, DOMAIN, UNSUPPORTED_ISSUE)


def registration(hass: HomeAssistant) -> FeatureRegistration | None:
    shared = hass.data.get(DATA_KEY)
    return None if shared is None else shared.get("registration")


def async_attach(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> None:
    """Add an installation; the first one registers the factory."""
    shared: dict[str, Any] = hass.data.setdefault(DATA_KEY, {"coordinators": []})
    shared["coordinators"].append(coordinator)
    if "registration" not in shared:
        shared["registration"] = FeatureRegistration(hass)
        shared["registration"].start()


def async_check(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> None:
    """At each update: registered with VT's current API, and the zones whose thermostat VT has
    still not handed over some time after the registration reported — they started before it and
    pick the manager up only at VT's next reload. Only a zone VT shows running is listed:
    reported and ready, its mode known (P-59); one away, unavailable or still starting would not
    be handed over yet anyway."""
    current = registration(hass)
    if current is not None:
        current.check()
    issue_id = f"vt_reload_needed_{coordinator.config_entry.entry_id}"
    missing: list[str] = []
    data = coordinator.data
    if (
        current is not None
        and current.registered_at is not None
        and dt_util.utcnow().timestamp() - current.registered_at >= RELOAD_GRACE_S
        and data is not None
    ):
        link = coordinator.link
        for zone_id in coordinator.config.zone_entities:
            if zone_id not in data.zones:
                continue
            zone = link.zone(zone_id)
            running = zone.started and zone.ready is not False and zone.heating_enabled is not None
            if running and vtherm_link.vt_thermostat(hass, zone_id) is None:
                missing.append(link.zone_name(zone_id))
    if missing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="vt_reload_needed",
            translation_placeholders={"zones": ", ".join(missing)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def async_detach(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> None:
    """Remove an installation; the last one unregisters the factory."""
    ir.async_delete_issue(hass, DOMAIN, f"vt_reload_needed_{coordinator.config_entry.entry_id}")
    shared = hass.data.get(DATA_KEY)
    if shared is None:
        return
    if coordinator in shared["coordinators"]:
        shared["coordinators"].remove(coordinator)
    if not shared["coordinators"]:
        current: FeatureRegistration | None = shared.get("registration")
        if current is not None:
            current.stop()
        hass.data.pop(DATA_KEY, None)
