"""A VT feature manager that shows on each VT thermostat whether the boiler's heat is reaching
its zone now — the plugin's one zone value (I8, decision C1).

VT picks up external feature managers from the ``vtherm_api`` registry when a thermostat starts
(research F4): a thermostat already running sees the manager only after VT's next reload, which
the plugin never triggers itself. The factory is registered only while VT is loaded — asking
``vtherm_api`` for its API before VT sets it up would leave VT a bare one — and again whenever VT
has created a new API (VT drops it with its last entry). Every method of the manager catches its
own errors, and every call the plugin makes on VT's API is inside ``try``, so no error of the
plugin's ever reaches VT (T-53).

The managers reach the plugin's data through a stable access point, not through the installation
that created them: after the plugin reloads (an options change), the managers VT already holds
show the value again at once; while no installation runs, they publish nothing. VT records its
thermostats' attributes, so a manager replaces what it published only when it changes (P-63).
Whether the manager works is shown: a repair issue when VT cannot load feature managers — an API
without them, or a VT older than the first version that creates them, whatever its API offers
(P-60) — and one listing the zones VT shows running whose thermostat started before the
registration and needs VT's reload (P-59).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_COMPONENT_LOADED, EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from . import vtherm_link
from .const import DOMAIN, VT_DOMAIN
from .core.boiler_call import CallReason

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
MANAGER_NAME = DOMAIN
ATTRIBUTE = "smart_boiler"
DATA_KEY = f"{DOMAIN}_feature_manager"
UNSUPPORTED_ISSUE = "vt_feature_manager_unsupported"
RELOAD_GRACE_S = 15 * 60  # a started thermostat shows the value within this, else needs a reload
# The public name of "heat reaches the zone now" (P-61; "hot water" is the boiler's domestic hot
# water).
HEAT_AVAILABLE = "heat_available"
# The water interface (I9; docs/en/specification/water-interface.md): its fields, in its order, and
# the public API's key in ``hass.data``.
SUPPLY_TEMPERATURE = "supply_temperature"
SUPPLY_REASON = "supply_reason"
SUPPLY_MEASURED_AT = "supply_measured_at"
HEAT_REASON = "heat_reason"
# Whether the boiler is called for heat and why not, and the demand against its thresholds (§4,
# §4.3; SmartPI's request, the user's decisions of 2026-10-14): the installation's, the same for
# each of its zones, read live from control.
BOILER_CALLED = "boiler_called"
CALL_REASON = "call_reason"
DEMAND_FIELDS = (
    "demand_count",
    "count_threshold",
    "count_by",
    "demand_power_kw",
    "power_threshold_kw",
    "demand_opening",
    "opening_threshold",
)
WATER_FIELDS = (
    SUPPLY_TEMPERATURE,
    SUPPLY_REASON,
    SUPPLY_MEASURED_AT,
    HEAT_AVAILABLE,
    HEAT_REASON,
    BOILER_CALLED,
    CALL_REASON,
    *DEMAND_FIELDS,
)
API_KEY = f"{DOMAIN}_api"
# The attribute shows the water rounded, changed only once it has moved this far (§3.3, P-63).
ATTRIBUTE_STEP_K = 1.0

type Lookup = Callable[[str], dict[str, Any] | None]


class RegistrationState(StrEnum):
    WAITING = "waiting"  # VT is not loaded, or has no API yet
    UNSUPPORTED = "unsupported"  # VT's API has no feature managers (an older vtherm_api)
    REGISTERED = "registered"


def zone_values(
    coordinators: list[SmartBoilerCoordinator], entity_id: str
) -> dict[str, Any] | None:
    """The zone's water and whether heat reaches it now (§4), from the first installation that
    has the zone and whose last refresh worked; ``None`` when none has it."""
    for coordinator in coordinators:
        if not coordinator.last_update_success:
            continue  # its entities are unavailable: no stale values on VT's either (PB-48)
        data = coordinator.data
        view = data.zones.get(entity_id) if data is not None else None
        if view is None:
            continue
        water = view.water
        measured = water.supply_measured_at
        return {
            SUPPLY_TEMPERATURE: water.supply_temperature,
            SUPPLY_REASON: None if water.supply_reason is None else water.supply_reason.value,
            SUPPLY_MEASURED_AT: None if measured is None else dt_util.utc_from_timestamp(measured),
            HEAT_AVAILABLE: water.heat_available,
            HEAT_REASON: None if water.heat_reason is None else water.heat_reason.value,
            **boiler_call_values(coordinator),
        }
    return None


def boiler_call_values(coordinator: SmartBoilerCoordinator) -> dict[str, Any]:
    """§4, §4.3: whether the boiler is called and why not, and the demand against its
    thresholds, as control shows them now — without control (monitoring only), or while it
    stops, the boiler is not the plugin's: not called by it, nothing to tell."""
    control = coordinator.control
    if control is None or control.stopping:
        return {
            BOILER_CALLED: None,
            CALL_REASON: CallReason.NOT_CONTROLLING.value,
            **dict.fromkeys(DEMAND_FIELDS),
        }
    status = control.status
    return {
        BOILER_CALLED: status.boiler_called,
        CALL_REASON: status.call_reason,
        "demand_count": status.demand_count,
        "count_threshold": status.count_threshold,
        "count_by": status.count_by,
        "demand_power_kw": status.demand_power_kw,
        "power_threshold_kw": status.power_threshold_kw,
        "demand_opening": status.demand_opening,
        "opening_threshold": status.opening_threshold,
    }


class SmartBoilerApi:
    """What other integrations read, under ``hass.data[API_KEY]`` while an installation runs
    (I9; water-interface.md §3.2): named functions, a later one added beside these."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def zone_water(self, entity_id: str) -> Mapping[str, Any] | None:
        """A VT climate's water data (§4) as a read-only mapping; ``None`` when it is not a
        zone of a running installation, or anything goes wrong — never an exception."""
        try:
            values = zone_values(_running(self._hass), entity_id)
        except Exception:
            _LOGGER.debug("Could not read the water data of %s", entity_id, exc_info=True)
            return None
        return None if values is None else MappingProxyType(values)


def _running(hass: HomeAssistant) -> list[SmartBoilerCoordinator]:
    """The installations running now: the stable access point every manager reads through."""
    shared = hass.data.get(DATA_KEY)
    return list(shared["coordinators"]) if shared else []


class SmartBoilerFeatureManager:
    """One per VT thermostat; publishes, never controls. Other plugins read the value as the
    property ``heat_available``, as it is now; the attribute on VT's thermostat keeps what was
    last published until it changes (P-63)."""

    def __init__(self, hass: HomeAssistant, thermostat: Any, lookup: Lookup) -> None:
        self._hass = hass
        self._thermostat = thermostat
        self._lookup = lookup
        self._failing = False  # a lasting failure is logged once, with its trace
        self._published: dict[str, Any] | None = None  # what VT's thermostat shows
        self._published_water: float | None = None  # the unrounded water it was shown from

    def post_init(self, entry_infos: Any) -> None:
        return None

    async def start_listening(self, force: bool = False) -> None:
        return None

    def stop_listening(self) -> bool | None:
        return None

    async def refresh_state(self) -> bool:
        return False  # the value comes from the plugin's own coordinator

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
        value = self._field(HEAT_AVAILABLE)
        return value if isinstance(value, bool) else None

    @property
    def heat_reason(self) -> str | None:
        """Why heat does not reach the zone, or why it cannot be told (§4.2)."""
        value = self._field(HEAT_REASON)
        return value if isinstance(value, str) else None

    @property
    def supply_temperature(self) -> float | None:
        """The water reaching the zone's circuit now, °C, as measured (§4)."""
        value = self._field(SUPPLY_TEMPERATURE)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    @property
    def supply_reason(self) -> str | None:
        """Why the water is not known, lastingly or for now (§4.1)."""
        value = self._field(SUPPLY_REASON)
        return value if isinstance(value, str) else None

    @property
    def supply_measured_at(self) -> datetime | None:
        """When the reading of the water was taken, UTC — information only (§6)."""
        value = self._field(SUPPLY_MEASURED_AT)
        return value if isinstance(value, datetime) else None

    @property
    def boiler_called(self) -> bool | None:
        """The boiler is called for space heating now, frost protection included (§4); ``None``
        while the plugin does not control it, or cannot tell yet."""
        value = self._field(BOILER_CALLED)
        return value if isinstance(value, bool) else None

    @property
    def call_reason(self) -> str | None:
        """Why the boiler is not called, or why it cannot be told (§4.3)."""
        value = self._field(CALL_REASON)
        return value if isinstance(value, str) else None

    @property
    def demand_count(self) -> int | None:
        """The devices — or zones, as ``count_by`` says — calling now (§4)."""
        return self._whole(self._field("demand_count"))

    @property
    def count_threshold(self) -> int | None:
        """The count that starts the boiler; ``None`` with the count off (§4)."""
        return self._whole(self._field("count_threshold"))

    @property
    def count_by(self) -> str | None:
        """What the count counts: ``devices`` or ``zones``; ``None`` with the count off (§4)."""
        value = self._field("count_by")
        return value if isinstance(value, str) else None

    @property
    def demand_power_kw(self) -> float | None:
        """The zones' mean power summed, kW, as VT's central boiler shows it (§4)."""
        return self._number(self._field("demand_power_kw"))

    @property
    def power_threshold_kw(self) -> float | None:
        """The power that starts the boiler, kW; ``None`` where not set (§4)."""
        return self._number(self._field("power_threshold_kw"))

    @property
    def demand_opening(self) -> float | None:
        """The widest opening among the calling zones, 0 to 1 (§4)."""
        return self._number(self._field("demand_opening"))

    @property
    def opening_threshold(self) -> float | None:
        """The opening that starts the boiler, 0 to 1; ``None`` where not set (§4)."""
        return self._number(self._field("opening_threshold"))

    @staticmethod
    def _whole(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _number(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    def _field(self, name: str) -> Any:
        values = self._values()
        return None if values is None else values.get(name)

    def _values(self) -> dict[str, Any] | None:
        entity_id = getattr(self._thermostat, "entity_id", None)
        return self._lookup(entity_id) if isinstance(entity_id, str) else None

    def add_custom_attributes(self, attributes: dict[str, Any]) -> None:
        try:
            values = self._values()
            if values is None:
                self._published = None
                self._published_water = None
                attributes.pop(ATTRIBUTE, None)
            else:
                attributes[ATTRIBUTE] = dict(self._shown(values))
        except Exception:  # VT's attribute update must never fail because of the plugin
            if self._failing:
                _LOGGER.debug("Could not add the plugin's zone value", exc_info=True)
            else:
                _LOGGER.exception("Could not add the plugin's zone value to a VT thermostat")
                self._failing = True
        else:
            self._failing = False

    def _shown(self, values: dict[str, Any]) -> dict[str, Any]:
        """The attribute (§3.3): the heat on every change, the water rounded to 1 °C and
        replaced only once it has moved ``ATTRIBUTE_STEP_K`` from what it was shown from, or to
        or from ``None`` — VT records it (P-63)."""
        water = values[SUPPLY_TEMPERATURE]
        last = self._published_water
        moved = (water is None) != (last is None) or (
            water is not None and last is not None and abs(water - last) >= ATTRIBUTE_STEP_K
        )
        if self._published is None or moved:
            self._published_water = water
        shown_water = self._published_water
        shown = {
            HEAT_AVAILABLE: values[HEAT_AVAILABLE],
            SUPPLY_TEMPERATURE: None if shown_water is None else round(shown_water),
        }
        if self._published != shown:
            self._published = shown
        return self._published


class SmartBoilerFeatureFactory:
    """The factory VT asks for a manager per thermostat."""

    def __init__(self, hass: HomeAssistant, lookup: Lookup) -> None:
        self._hass = hass
        self._lookup = lookup

    @property
    def name(self) -> str:
        return MANAGER_NAME

    def supports(self, thermostat: Any) -> bool:
        return True  # every thermostat; the value appears only for the plugin's zones

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
        # PB-46: the API object that refused the factory is not asked again; only the first
        # refusal is logged with its trace.
        self._refused: Any | None = None
        self._refusal_logged = False
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
        if stored is not None and stored is not self._api and stored is not self._refused:
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
                translation_placeholders={"version": vtherm_link.VT_FEATURE_MANAGERS_FROM},
            )
        elif state is RegistrationState.REGISTERED:
            ir.async_delete_issue(self._hass, DOMAIN, UNSUPPORTED_ISSUE)

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_states is not None:
            self._unsub_states()
            self._unsub_states = None
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
    hass.data.setdefault(API_KEY, SmartBoilerApi(hass))  # the public API (I9, §3.2)


def async_check(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> None:
    """At each update: registered with VT's current API, and the zones whose thermostat still
    shows nothing of the plugin some time after the registration reported — they started before
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
        hass.data.pop(API_KEY, None)
