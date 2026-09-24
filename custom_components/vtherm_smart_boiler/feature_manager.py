"""A VT feature manager that shows two of the plugin's zone values on each VT thermostat.

VT picks up external feature managers from the ``vtherm_api`` registry when a thermostat starts
(research F4): a thermostat already running sees the manager only after VT's next reload, which
the plugin never triggers itself. The factory is registered only while VT is loaded — asking
``vtherm_api`` for its API before VT sets it up would leave VT a bare one. Every method of the
manager catches its own errors, so VT's loop never breaks because of the plugin; after the plugin
unloads, managers VT already created stay attached and simply publish nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .const import DOMAIN, VT_DOMAIN

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
MANAGER_NAME = DOMAIN
ATTRIBUTE = "smart_boiler"
DATA_KEY = f"{DOMAIN}_feature_manager"

type Lookup = Callable[[str], dict[str, Any] | None]


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


class SmartBoilerFeatureManager:
    """One per VT thermostat; publishes, never controls."""

    def __init__(self, hass: HomeAssistant, thermostat: Any, lookup: Lookup) -> None:
        self._hass = hass
        self._thermostat = thermostat
        self._lookup = lookup

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

    def add_custom_attributes(self, attributes: dict[str, Any]) -> None:
        try:
            entity_id = getattr(self._thermostat, "entity_id", None)
            values = self._lookup(entity_id) if isinstance(entity_id, str) else None
            if values is None:
                attributes.pop(ATTRIBUTE, None)
            else:
                attributes[ATTRIBUTE] = values
        except Exception:  # VT's attribute update must never fail because of the plugin
            _LOGGER.debug("Could not add the plugin's zone values", exc_info=True)


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


def _api(hass: HomeAssistant) -> Any | None:
    """VT's API once VT has created it; ``None`` otherwise, or when vtherm_api or the feature is
    missing. ``get_vtherm_api`` is called only when the instance exists, as it would create a
    bare one otherwise."""
    if VT_DOMAIN not in hass.config.components:
        return None
    try:
        from vtherm_api.vtherm_api import VThermAPI
    except ImportError:
        return None
    try:
        from vtherm_api.const import VTHERM_API_NAME
    except ImportError:
        VTHERM_API_NAME = "vtherm_api"  # the name in vtherm_api 0.5.0
    data = hass.data.get(VT_DOMAIN)
    if not isinstance(data, dict) or data.get(VTHERM_API_NAME) is None:
        return None
    try:
        api = VThermAPI.get_vtherm_api(hass)
    except Exception:
        _LOGGER.debug("VT's API is not available", exc_info=True)
        return None
    if api is None or not hasattr(api, "register_feature_manager"):
        return None
    return api


class FeatureRegistration:
    """Registers the factory once for all installations, as soon as VT is loaded."""

    def __init__(self, hass: HomeAssistant, lookup: Lookup) -> None:
        self._hass = hass
        self._factory = SmartBoilerFeatureFactory(hass, lookup)
        self._api: Any | None = None
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def registered(self) -> bool:
        return self._api is not None

    def start(self) -> None:
        if not self._register():
            self._unsub = self._hass.bus.async_listen(EVENT_COMPONENT_LOADED, self._on_loaded)

    @callback
    def _on_loaded(self, event: Event) -> None:
        if event.data.get("component") == VT_DOMAIN and self._register() and self._unsub:
            self._unsub()
            self._unsub = None

    def _register(self) -> bool:
        api = _api(self._hass)
        if api is None:
            return False
        try:
            api.register_feature_manager(self._factory)
        except Exception:
            _LOGGER.warning("Could not register the VT feature manager", exc_info=True)
            return False
        self._api = api
        return True

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        api, self._api = self._api, None
        if api is None or not hasattr(api, "unregister_feature_manager"):
            return
        try:  # the instance it was registered with, even if VT has since dropped it
            api.unregister_feature_manager(MANAGER_NAME)
        except Exception:
            _LOGGER.debug("Could not unregister the VT feature manager", exc_info=True)


def async_attach(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> None:
    """Add an installation; the first one registers the factory."""
    shared: dict[str, Any] = hass.data.setdefault(DATA_KEY, {"coordinators": []})
    shared["coordinators"].append(coordinator)
    if "registration" not in shared:
        registration = FeatureRegistration(
            hass, lambda entity_id: zone_values(shared["coordinators"], entity_id)
        )
        shared["registration"] = registration
        registration.start()


def async_detach(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> None:
    """Remove an installation; the last one unregisters the factory."""
    shared = hass.data.get(DATA_KEY)
    if shared is None:
        return
    if coordinator in shared["coordinators"]:
        shared["coordinators"].remove(coordinator)
    if not shared["coordinators"]:
        registration: FeatureRegistration | None = shared.get("registration")
        if registration is not None:
            registration.stop()
        hass.data.pop(DATA_KEY, None)
