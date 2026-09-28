"""The only module that reads Versatile Thermostat zones and VT's central configuration.

It reads VT's climate entities (state and top-level attributes, see ``vtherm_attributes``) and
VT's central mode select. It detects what is installed instead of assuming it: VT, its version,
``vtherm_api`` and SmartPI may be missing or older.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration

from .const import VT_DOMAIN
from .core.readings import ZoneState
from .transport.entities import reported_at
from .vtherm_attributes import CentralMode, central_mode, zone_values

_LOGGER = logging.getLogger(__name__)

SMARTPI_DOMAIN = "vtherm_smartpi"
CENTRAL_MODE_UNIQUE_ID = "central_mode"
CENTRAL_BOILER_UNIQUE_ID = "central_boiler_state"
CENTRAL_BOILER_FEATURE = "use_central_boiler_feature"  # in VT's central entry (VT 10.4.0)
# VT's central entry is the one whose ``thermostat_type`` is this (VT 10.4.0 ``const.py``); its
# central boiler's activation delay, 0–600 s, stays in its data once the feature is unticked.
THERMOSTAT_TYPE = "thermostat_type"
CENTRAL_CONFIG = "thermostat_central_config"
ACTIVATION_DELAY = "central_boiler_activation_delay_sec"
VT_ACTIVATION_DELAY_MAX_S = 600.0
ROOM_SENSOR = "temperature_sensor_entity_id"  # in a thermostat's entry data (VT 10.4.0)


@dataclass(frozen=True, slots=True)
class ZoneAlgorithm:
    proportional_function: str | None = None  # "tpi" or "smartpi"
    smartpi_learning: bool | None = None  # SmartPI's learning flag; None: not SmartPI
    auto_tpi: bool = False  # Auto-TPI learning is on (a session or continuous kext)
    used_by_central_boiler: bool | None = None


@dataclass(frozen=True, slots=True)
class VtCapabilities:
    vt_loaded: bool
    vt_version: str | None
    vtherm_api_version: str | None
    smartpi_loaded: bool


def room_sensor(hass: HomeAssistant, entity_id: str) -> str | None:
    """The room temperature sensor VT reads for a zone, from the thermostat's entry (VT 10.4.0
    keeps it in the entry's data); ``None`` where it is not found."""
    registered = er.async_get(hass).async_get(entity_id)
    if registered is None or registered.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(registered.config_entry_id)
    sensor = entry.data.get(ROOM_SENSOR) if entry is not None else None
    return sensor if isinstance(sensor, str) and sensor else None


def zone_name(hass: HomeAssistant, entity_id: str) -> str:
    """A zone's name as the user sees it; its entity ID while the thermostat is away."""
    state = hass.states.get(entity_id)
    if state is not None and state.name:
        return state.name
    return entity_id


def vt_climate_entities(hass: HomeAssistant) -> list[str]:
    """Every climate entity registered by VT."""
    registry = er.async_get(hass)
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == VT_DOMAIN and entry.domain == "climate"
    )


class VThermLink:
    """Zones as the core sees them, read from VT's climate entities."""

    def __init__(self, hass: HomeAssistant, zone_entities: Sequence[str]) -> None:
        self._hass = hass
        self._zones = tuple(zone_entities)
        self._api_version: str | None = None

    async def async_detect(self) -> None:
        """Read what does not change while Home Assistant runs — the installed ``vtherm_api``
        — once, in the executor: package metadata is read from disk."""
        self._api_version = await self._hass.async_add_executor_job(_vtherm_api_version)

    @property
    def zone_entities(self) -> tuple[str, ...]:
        return self._zones

    def zone(self, entity_id: str) -> ZoneState:
        zone = self.zone_from_state(entity_id, self._hass.states.get(entity_id))
        lost = zone.safety_on or self._room_sensor_lost(entity_id)
        return replace(zone, room_sensor_lost=lost)

    def _room_sensor_lost(self, entity_id: str) -> bool:
        """The room sensor VT reads is gone, unavailable or unknown: VT keeps its last
        temperature, and its own safety check sleeps while the zone is off (R6, T2). A steady
        sensor is fine, however long ago it changed. VT's own safety mode on counts the same
        (S-35): VT has seen the sensor go quiet, and runs the zone on its safety duty."""
        sensor = room_sensor(self._hass, entity_id)
        if sensor is None:
            return False
        state = self._hass.states.get(sensor)
        return state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    def zone_from_state(self, entity_id: str, state: State | None) -> ZoneState:
        """A zone from a given state of its climate entity (current or recorded)."""
        if state is None:
            return ZoneState(entity_id, reported=False)
        unit = str(self._hass.config.units.temperature_unit)
        values = zone_values(state.state, state.attributes, unit)
        return ZoneState(
            entity_id,
            temperature=values.temperature,
            target=values.target,
            heating_enabled=values.heating_enabled,
            calling=values.calling,
            on_percent=values.on_percent,
            valve_open=values.valve_open,
            power=values.power,
            reported_at=reported_at(state),
            auto_mode=values.auto_mode,
            device_active=values.device_active,
            ready=values.ready,
            temperature_at=values.temperature_at,
            max_on_percent=values.max_on_percent,
            mean_power=values.mean_power,
            safety_on=values.safety_on,
            shedding=values.shedding,
            reported=values.reported,
        )

    def zones(self) -> list[ZoneState]:
        return [self.zone(entity_id) for entity_id in self._zones]

    def zone_name(self, entity_id: str) -> str:
        return zone_name(self._hass, entity_id)

    def recorded_state(self, entity_id: str) -> State | None:
        """A zone's current state as the history records it."""
        return self._hass.states.get(entity_id)

    def shows_attribute(self, entity_id: str, attribute: str) -> bool | None:
        """Whether a zone's thermostat carries an attribute now; ``None`` when it is away."""
        state = self._hass.states.get(entity_id)
        return None if state is None else attribute in state.attributes

    def zone_algorithm(self, entity_id: str) -> ZoneAlgorithm:
        """What runs a zone, from VT's live attributes (not kept by the recorder)."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return ZoneAlgorithm()
        configuration = state.attributes.get("configuration")
        specific = state.attributes.get("specific_states")
        configuration = configuration if isinstance(configuration, dict) else {}
        specific = specific if isinstance(specific, dict) else {}
        smartpi = specific.get("smartpi_learning_enabled")
        used = configuration.get("is_used_by_central_boiler")
        function = configuration.get("proportional_function")
        return ZoneAlgorithm(
            proportional_function=function if isinstance(function, str) else None,
            smartpi_learning=smartpi if isinstance(smartpi, bool) else None,
            # VT publishes these keys for every TPI zone; "on" means Auto-TPI is learning.
            auto_tpi="on"
            in (specific.get("auto_tpi_state"), specific.get("auto_tpi_continuous_kext")),
            used_by_central_boiler=used if isinstance(used, bool) else None,
        )

    def vt_central_boiler_configured(self) -> bool | None:
        """Whether VT's own central boiler feature is set up (then it must not run alongside);
        ``None`` while it cannot be ruled out — VT's entity for it is away while VT sets its
        central entry up (a reload, a late start).

        VT creates the entity only while the feature is on, and Home Assistant keeps its
        registry entry, with a stand-in "unavailable" state, once VT no longer provides it: with
        VT's central entry loaded, that stand-in means the feature is off."""
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id(
            "binary_sensor", VT_DOMAIN, CENTRAL_BOILER_UNIQUE_ID
        )
        if entity_id is None:
            return False
        state = self._hass.states.get(entity_id)
        entry = registry.async_get(entity_id)
        provided = state is not None and not state.attributes.get(ATTR_RESTORED)
        if not provided or (entry is not None and entry.disabled):
            owner = (
                self._hass.config_entries.async_get_entry(entry.config_entry_id)
                if entry is not None and entry.config_entry_id
                else None
            )
            if owner is None:
                return False  # left behind by a VT entry that is gone
            if owner.state is not ConfigEntryState.LOADED:
                return None
            feature = owner.data.get(CENTRAL_BOILER_FEATURE)
            return feature if isinstance(feature, bool) else False
        configured = None if state is None else state.attributes.get("is_central_boiler_configured")
        if state is None or state.state in ("unavailable", "unknown") or configured is None:
            return None
        return configured is True

    def vt_central_activation_delay(self) -> float | None:
        """VT's central boiler activation delay, in seconds, as VT keeps it in its central
        entry — also once its central boiler is unticked (decision 5); ``None`` without VT, a
        central entry, or a number within VT's 0–600 s. A pre-fill for the form only: the
        plugin's own option is what counts."""
        for entry in self._hass.config_entries.async_entries(VT_DOMAIN):
            if entry.data.get(THERMOSTAT_TYPE) != CENTRAL_CONFIG:
                continue
            raw = entry.data.get(ACTIVATION_DELAY)
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                return None
            value = float(raw)
            inside = math.isfinite(value) and 0.0 <= value <= VT_ACTIVATION_DELAY_MAX_S
            return value if inside else None
        return None

    def central_mode(self) -> CentralMode | None:
        """VT's central mode, or ``None`` when VT has no central configuration."""
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id("select", VT_DOMAIN, CENTRAL_MODE_UNIQUE_ID)
        if entity_id is None:
            return None
        state = self._hass.states.get(entity_id)
        return None if state is None else central_mode(state.state)

    def capabilities(self) -> VtCapabilities:
        components = self._hass.config.components
        # Loaded only with an entry that is: VT set up with every entry failed runs no zones.
        vt_loaded = VT_DOMAIN in components and any(
            entry.state is ConfigEntryState.LOADED
            for entry in self._hass.config_entries.async_entries(VT_DOMAIN)
        )
        vt_version: str | None = None
        if vt_loaded:
            try:
                integration = async_get_loaded_integration(self._hass, VT_DOMAIN)
                vt_version = None if integration.version is None else str(integration.version)
            except Exception:  # any loader problem just means "unknown"
                _LOGGER.debug("VT's version could not be read", exc_info=True)
                vt_version = None
        return VtCapabilities(
            vt_loaded, vt_version, self._api_version, SMARTPI_DOMAIN in components
        )


def _vtherm_api_version() -> str | None:
    """The installed ``vtherm_api`` version; ``None`` when it cannot be imported."""
    try:
        import_module("vtherm_api")
        return version("vtherm_api")
    except ImportError, PackageNotFoundError:
        return None
