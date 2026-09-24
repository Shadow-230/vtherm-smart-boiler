"""The only module that reads Versatile Thermostat zones and VT's central configuration.

It reads VT's climate entities (state and top-level attributes, see ``vtherm_attributes``) and
VT's central mode select. It detects what is installed instead of assuming it: VT, its version,
``vtherm_api`` and SmartPI may be missing or older.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration

from .const import VT_DOMAIN
from .core.readings import ZoneState
from .transport.entities import reported_at
from .vtherm_attributes import CentralMode, central_mode, zone_values

SMARTPI_DOMAIN = "vtherm_smartpi"
CENTRAL_MODE_UNIQUE_ID = "central_mode"


@dataclass(frozen=True, slots=True)
class VtCapabilities:
    vt_loaded: bool
    vt_version: str | None
    vtherm_api_version: str | None
    smartpi_loaded: bool


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

    @property
    def zone_entities(self) -> tuple[str, ...]:
        return self._zones

    def zone(self, entity_id: str) -> ZoneState:
        return self.zone_from_state(entity_id, self._hass.states.get(entity_id))

    def zone_from_state(self, entity_id: str, state: State | None) -> ZoneState:
        """A zone from a given state of its climate entity (current or recorded)."""
        if state is None:
            return ZoneState(entity_id)
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
        )

    def zones(self) -> list[ZoneState]:
        return [self.zone(entity_id) for entity_id in self._zones]

    def zone_name(self, entity_id: str) -> str:
        state = self._hass.states.get(entity_id)
        if state is not None and state.name:
            return state.name
        return entity_id

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
        vt_loaded = VT_DOMAIN in components
        vt_version: str | None = None
        if vt_loaded:
            try:
                integration = async_get_loaded_integration(self._hass, VT_DOMAIN)
                vt_version = None if integration.version is None else str(integration.version)
            except Exception:  # any loader problem just means "unknown"
                vt_version = None
        try:
            import_module("vtherm_api")
            api_version: str | None = version("vtherm_api")
        except ImportError, PackageNotFoundError:
            api_version = None
        return VtCapabilities(vt_loaded, vt_version, api_version, SMARTPI_DOMAIN in components)
