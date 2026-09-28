"""A VT feature manager that shows two of the plugin's zone values on each VT thermostat.

VT picks up external feature managers from the ``vtherm_api`` registry when a thermostat starts
(research F4): a thermostat already running sees the manager only after VT's next reload, which
the plugin never triggers itself. The factory is registered only while VT is loaded — asking
``vtherm_api`` for its API before VT sets it up would leave VT a bare one — and again whenever VT
has created a new API (VT drops it with its last entry). Every method of the manager catches its
own errors, and every call the plugin makes on VT's API is inside ``try``, so no error of the
plugin's ever reaches VT (T-53).

The managers reach the plugin's data through a stable access point, not through the installation
that created them: after the plugin reloads (an options change), the managers VT already holds
show the values again at once; while no installation runs, they publish nothing. VT records its
thermostats' attributes, so a manager replaces what it published only on a real change (P-63).
Whether the manager works is shown: a repair issue when VT cannot load feature managers — an API
without them, or a VT older than the first version that creates them, whatever its API offers
(P-60) — and one listing the zones VT shows running whose thermostat started before the
registration and needs VT's reload (P-59).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_COMPONENT_LOADED, EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from . import vtherm_link
from .const import DOMAIN, VT_DOMAIN

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
MANAGER_NAME = DOMAIN
ATTRIBUTE = "smart_boiler"
DATA_KEY = f"{DOMAIN}_feature_manager"
UNSUPPORTED_ISSUE = "vt_feature_manager_unsupported"
RELOAD_GRACE_S = 15 * 60  # a started thermostat shows the values within this, else needs a reload
# The public name of "heat reaches the zone now" (P-61; "hot water" is the boiler's domestic hot
# water), and the zone's emitter power factor.
HEAT_AVAILABLE = "heat_available"
EMITTER_POWER_FACTOR = "emitter_power_factor"
# The factor published again only once it has moved this far from what VT shows (P-63;
# provisional, K4).
FACTOR_STEP = 0.05

type Lookup = Callable[[str], dict[str, Any] | None]


class RegistrationState(StrEnum):
    WAITING = "waiting"  # VT is not loaded, or has no API yet
    UNSUPPORTED = "unsupported"  # VT's API has no feature managers (an older vtherm_api)
    REGISTERED = "registered"


def zone_values(
    coordinators: list[SmartBoilerCoordinator], entity_id: str
) -> dict[str, Any] | None:
    """Whether heat reaches the zone now, and its emitter power factor, from the first
    installation that has the zone; ``None`` when none has it."""
    for coordinator in coordinators:
        data = coordinator.data
        view = data.zones.get(entity_id) if data is not None else None
        if view is None:
            continue
        factor = view.factor.value
        return {
            HEAT_AVAILABLE: view.hot_water.available,
            EMITTER_POWER_FACTOR: None if factor is None else round(factor, 3),
        }
    return None


def _real_change(published: dict[str, Any], values: dict[str, Any]) -> bool:
    """P-63: heat availability changed, the factor came or went, or it moved by at least
    ``FACTOR_STEP`` from what was published."""
    if published.get(HEAT_AVAILABLE) != values.get(HEAT_AVAILABLE):
        return True
    before, now = published.get(EMITTER_POWER_FACTOR), values.get(EMITTER_POWER_FACTOR)
    if before is None or now is None:
        return (before is None) != (now is None)
    return bool(abs(float(now) - float(before)) >= FACTOR_STEP)


def _running(hass: HomeAssistant) -> list[SmartBoilerCoordinator]:
    """The installations running now: the stable access point every manager reads through."""
    shared = hass.data.get(DATA_KEY)
    return list(shared["coordinators"]) if shared else []


class SmartBoilerFeatureManager:
    """One per VT thermostat; publishes, never controls. Other plugins read the values as the
    properties ``heat_available`` and ``emitter_power_factor``, as they are now; the attribute
    on VT's thermostat keeps what was last published until a real change (P-63)."""

    def __init__(self, hass: HomeAssistant, thermostat: Any, lookup: Lookup) -> None:
        self._hass = hass
        self._thermostat = thermostat
        self._lookup = lookup
        self._failing = False  # a lasting failure is logged once, with its trace
        self._published: dict[str, Any] | None = None  # what VT's thermostat shows

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
    def heat_available(self) -> bool | None:
        """Heat is reaching the zone now; ``None`` when unknown or not the plugin's zone."""
        values = self._values()
        return None if values is None else values[HEAT_AVAILABLE]

    @property
    def emitter_power_factor(self) -> float | None:
        """The zone's emitter output now versus its reference; ``None`` when unknown."""
        values = self._values()
        return None if values is None else values[EMITTER_POWER_FACTOR]

    def _values(self) -> dict[str, Any] | None:
        entity_id = getattr(self._thermostat, "entity_id", None)
        return self._lookup(entity_id) if isinstance(entity_id, str) else None

    def add_custom_attributes(self, attributes: dict[str, Any]) -> None:
        try:
            values = self._values()
            if values is None:
                self._published = None
                attributes.pop(ATTRIBUTE, None)
            else:
                if self._published is None or _real_change(self._published, values):
                    self._published = dict(values)
                attributes[ATTRIBUTE] = dict(self._published)
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


@callback
def _is_climate(data: EventStateChangedData) -> bool:
    return data["entity_id"].startswith("climate.")


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
    when the instance exists, as it would create a bare one otherwise. A VT older than the first
    version that creates outside feature managers is unsupported whatever its API offers: the
    ``vtherm_api`` shared with the plugin has the method all the same (P-60); its version
    unknown, the API's capability decides."""
    if VT_DOMAIN not in hass.config.components:
        return None, RegistrationState.WAITING
    if vtherm_link.vt_loads_feature_managers(vtherm_link.vt_version(hass)) is False:
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
        self._factory = SmartBoilerFeatureFactory(
            hass, lambda entity_id: zone_values(_running(hass), entity_id)
        )
        self._api: Any | None = None
        self._unsub: CALLBACK_TYPE | None = None
        self._unsub_states: CALLBACK_TYPE | None = None
        self.state = RegistrationState.WAITING
        self.registered_at: float | None = None  # when the current API got the factory

    def start(self) -> None:
        # VT drops its API with its last entry and creates a new one when set up again; a
        # thermostat it then builds writes its first state before it starts and asks for
        # feature managers, so the new API is given the factory right then.
        self._unsub_states = self._hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._on_climate_state, event_filter=_is_climate
        )
        if not self.check():
            self._unsub = self._hass.bus.async_listen(EVENT_COMPONENT_LOADED, self._on_loaded)

    @callback
    def _on_climate_state(self, _event: Event[EventStateChangedData]) -> None:
        try:
            stored = _stored_api(self._hass)
        except Exception:  # never into VT's state writes
            _LOGGER.debug("VT's API could not be looked up", exc_info=True)
            return
        if stored is not None and stored is not self._api:
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
                translation_placeholders={"version": vtherm_link.VT_FEATURE_MANAGERS_FROM},
            )
        else:
            ir.async_delete_issue(self._hass, DOMAIN, UNSUPPORTED_ISSUE)

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_states is not None:
            self._unsub_states()
            self._unsub_states = None
        ir.async_delete_issue(self._hass, DOMAIN, UNSUPPORTED_ISSUE)
        api, self._api = self._api, None
        if api is None:
            return
        try:  # the instance it was registered with, even if VT has since dropped it
            unregister = getattr(api, "unregister_feature_manager", None)
            if callable(unregister):
                unregister(MANAGER_NAME)
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
    it and pick the manager up only at VT's next reload. Only a zone VT shows running is listed:
    reported and ready, its mode known (P-59); one away, unavailable or still starting would
    show nothing anyway."""
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
            if running and link.shows_attribute(zone_id, ATTRIBUTE) is False:
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
