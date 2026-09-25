"""A VT feature manager that shows two of the plugin's zone values on each VT thermostat.

VT picks up external feature managers from the ``vtherm_api`` registry when a thermostat starts
(research F4): a thermostat already running sees the manager only after VT's next reload, which
the plugin never triggers itself. The factory is registered only while VT is loaded — asking
``vtherm_api`` for its API before VT sets it up would leave VT a bare one — and again whenever VT
has created a new API (VT drops it with its last entry). Every method of the manager catches its
own errors, so VT's loop never breaks because of the plugin.

The managers reach the plugin's data through a stable access point, not through the installation
that created them: after the plugin reloads (an options change), the managers VT already holds
show the values again at once; while no installation runs, they publish nothing. Whether the
manager works is shown: a repair issue when VT's API has no feature managers, and one listing
the zones whose thermostat started before the registration and needs VT's reload.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN, VT_DOMAIN

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
MANAGER_NAME = DOMAIN
ATTRIBUTE = "smart_boiler"
DATA_KEY = f"{DOMAIN}_feature_manager"
UNSUPPORTED_ISSUE = "vt_feature_manager_unsupported"
RELOAD_GRACE_S = 15 * 60  # a started thermostat shows the values within this, else needs a reload

type Lookup = Callable[[str], dict[str, Any] | None]


class RegistrationState(StrEnum):
    WAITING = "waiting"  # VT is not loaded, or has no API yet
    UNSUPPORTED = "unsupported"  # VT's API has no feature managers (an older vtherm_api)
    REGISTERED = "registered"


def zone_values(
    coordinators: list[SmartBoilerCoordinator], entity_id: str
) -> dict[str, Any] | None:
    """The zone's hot water availability and emitter power factor, from the first installation
    that has the zone; ``None`` when none has it."""
    for coordinator in coordinators:
        data = coordinator.data
        view = data.zones.get(entity_id) if data is not None else None
        if view is None:
            continue
        factor = view.factor.value
        return {
            "hot_water": view.hot_water.available,
            "emitter_power_factor": None if factor is None else round(factor, 3),
        }
    return None


def _running(hass: HomeAssistant) -> list[SmartBoilerCoordinator]:
    """The installations running now: the stable access point every manager reads through."""
    shared = hass.data.get(DATA_KEY)
    return list(shared["coordinators"]) if shared else []


class SmartBoilerFeatureManager:
    """One per VT thermostat; publishes, never controls. Other plugins read the values as the
    properties ``hot_water`` and ``emitter_power_factor``."""

    def __init__(self, hass: HomeAssistant, thermostat: Any, lookup: Lookup) -> None:
        self._hass = hass
        self._thermostat = thermostat
        self._lookup = lookup
        self._failing = False  # a lasting failure is logged once, with its trace

    def post_init(self, entry_infos: Any) -> None:
        return None

    async def start_listening(self, force: bool = False) -> None:
        return None

    def stop_listening(self) -> bool | None:
        return None

    async def refresh_state(self) -> bool:
        return False  # the values come from the plugin's own coordinator

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

    @property
    def hot_water(self) -> bool | None:
        """Heat is reaching the zone now; ``None`` when unknown or not the plugin's zone."""
        values = self._values()
        return None if values is None else values["hot_water"]

    @property
    def emitter_power_factor(self) -> float | None:
        """The zone's emitter output now versus its reference; ``None`` when unknown."""
        values = self._values()
        return None if values is None else values["emitter_power_factor"]

    def _values(self) -> dict[str, Any] | None:
        entity_id = getattr(self._thermostat, "entity_id", None)
        return self._lookup(entity_id) if isinstance(entity_id, str) else None

    def add_custom_attributes(self, attributes: dict[str, Any]) -> None:
        try:
            values = self._values()
            if values is None:
                attributes.pop(ATTRIBUTE, None)
            else:
                attributes[ATTRIBUTE] = values
        except Exception:  # VT's attribute update must never fail because of the plugin
            if self._failing:
                _LOGGER.debug("Could not add the plugin's zone values", exc_info=True)
            else:
                _LOGGER.exception("Could not add the plugin's zone values to a VT thermostat")
                self._failing = True
        else:
            self._failing = False


class SmartBoilerFeatureFactory:
    """The factory VT asks for a manager per thermostat."""

    def __init__(self, hass: HomeAssistant, lookup: Lookup) -> None:
        self._hass = hass
        self._lookup = lookup

    @property
    def name(self) -> str:
        return MANAGER_NAME

    def supports(self, thermostat: Any) -> bool:
        return True  # every thermostat; values appear only for the plugin's zones

    def create(self, thermostat: Any) -> SmartBoilerFeatureManager:
        return SmartBoilerFeatureManager(self._hass, thermostat, self._lookup)


def _api(hass: HomeAssistant) -> tuple[Any | None, RegistrationState]:
    """VT's API once VT has created it, with what it allows. ``get_vtherm_api`` is called only
    when the instance exists, as it would create a bare one otherwise."""
    if VT_DOMAIN not in hass.config.components:
        return None, RegistrationState.WAITING
    try:
        from vtherm_api.vtherm_api import VThermAPI
    except ImportError:
        return None, RegistrationState.UNSUPPORTED
    try:
        from vtherm_api.const import VTHERM_API_NAME
    except ImportError:
        VTHERM_API_NAME = "vtherm_api"  # the name in vtherm_api 0.5.0
    data = hass.data.get(VT_DOMAIN)
    if not isinstance(data, dict) or data.get(VTHERM_API_NAME) is None:
        return None, RegistrationState.WAITING
    try:
        api = VThermAPI.get_vtherm_api(hass)
    except Exception:
        _LOGGER.debug("VT's API is not available", exc_info=True)
        return None, RegistrationState.WAITING
    if api is None:
        return None, RegistrationState.WAITING
    if not hasattr(api, "register_feature_manager"):
        return None, RegistrationState.UNSUPPORTED
    return api, RegistrationState.REGISTERED


class FeatureRegistration:
    """Registers the factory once for all installations, as soon as VT is loaded, and again
    on each API VT creates later."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._factory = SmartBoilerFeatureFactory(
            hass, lambda entity_id: zone_values(_running(hass), entity_id)
        )
        self._api: Any | None = None
        self._unsub: CALLBACK_TYPE | None = None
        self.state = RegistrationState.WAITING
        self.registered_at: float | None = None  # when the current API got the factory

    @property
    def registered(self) -> bool:
        return self._api is not None

    def start(self) -> None:
        if not self.check():
            self._unsub = self._hass.bus.async_listen(EVENT_COMPONENT_LOADED, self._on_loaded)

    @callback
    def _on_loaded(self, event: Event) -> None:
        if event.data.get("component") == VT_DOMAIN and self.check() and self._unsub:
            self._unsub()
            self._unsub = None

    def check(self) -> bool:
        """Registered with VT's current API — again, if VT has created a new one."""
        api, state = _api(self._hass)
        if api is not None and api is not self._api:
            try:
                api.register_feature_manager(self._factory)
            except Exception:
                _LOGGER.warning("Could not register the VT feature manager", exc_info=True)
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
        self.state = state
        if state is RegistrationState.UNSUPPORTED:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                UNSUPPORTED_ISSUE,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=UNSUPPORTED_ISSUE,
            )
        else:
            ir.async_delete_issue(self._hass, DOMAIN, UNSUPPORTED_ISSUE)

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        ir.async_delete_issue(self._hass, DOMAIN, UNSUPPORTED_ISSUE)
        api, self._api = self._api, None
        if api is None or not hasattr(api, "unregister_feature_manager"):
            return
        try:  # the instance it was registered with, even if VT has since dropped it
            api.unregister_feature_manager(MANAGER_NAME)
        except Exception:
            _LOGGER.debug("Could not unregister the VT feature manager", exc_info=True)


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
    """At each update: registered with VT's current API, and the zones whose thermostat still
    shows none of the values some time after the registration reported — they started before
    it and pick the manager up only at VT's next reload."""
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
        for zone_id in coordinator.config.zone_entities:
            state = hass.states.get(zone_id)
            if zone_id in data.zones and state is not None and ATTRIBUTE not in state.attributes:
                missing.append(coordinator.link.zone_name(zone_id))
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
