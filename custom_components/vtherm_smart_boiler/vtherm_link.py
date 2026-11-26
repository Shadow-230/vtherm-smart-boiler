"""The only module that reads Versatile Thermostat zones and VT's settings.

Zone values go through ``vtherm_api`` where it has them (the user's rule, 2026-11-24): VT hands
each of its thermostats to the plugin's feature manager, which keeps it here
(``register_thermostat``), and the members the API declares are read from it
(``vtherm_attributes.RUNTIME_MEMBERS``). The rest — and every value of a thermostat VT started
before the plugin registered, until VT's reload — comes from VT's climate entities (state and
top-level attributes, see ``vtherm_attributes``) and VT's central mode select. It detects what is
installed instead of assuming it: VT, its version and ``vtherm_api`` may be missing or older.
Nothing of SmartPI is read (I12.9).

VT's central boiler decides whether the boiler heats (I12): its settings reach the plugin in each
handed-over thermostat's ``entry_infos`` — the thermostat's settings merged over VT's central
entry's (VT 10.6.5 ``base_thermostat.py``) — read here only to check that its commands switch the
helper the user picked, never the boiler (``vt_central_boiler``). The commands are split by the
plugin's own reading of VT's documented format ``entity_id/domain.service[/attribute:value]``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration

from .const import DOMAIN, OPENTHERM_GW_DOMAIN, VT_DOMAIN
from .core.readings import ZoneState
from .transport.entities import reported_at
from .vtherm_attributes import (
    RUNTIME_MEMBERS,
    CentralMode,
    central_mode,
    runtime_zone,
    zone_values,
)

_LOGGER = logging.getLogger(__name__)

# VT's thermostats as VT handed them to the plugin's feature manager, for this Home Assistant run:
# kept across the plugin's reloads, as the managers are (``feature_manager``).
THERMOSTATS_KEY = f"{DOMAIN}_vt_thermostats"
# VT's central boiler settings as a thermostat last handed them over in this Home Assistant run
# (I12): while VT reloads its thermostats none is held, and the last ones stand.
VT_SETTINGS_KEY = f"{DOMAIN}_vt_central_boiler"
CENTRAL_MODE_UNIQUE_ID = "central_mode"
# VT's central boiler settings, as ``entry_infos`` carries them (VT 10.6.5 ``const.py``).
CENTRAL_BOILER_FEATURE = "use_central_boiler_feature"
ACTIVATION_SERVICE = "central_boiler_activation_service"
DEACTIVATION_SERVICE = "central_boiler_deactivation_service"
# VT's central boiler event (``vtherm_api``'s ``EventType.CENTRAL_BOILER_EVENT``; the same name
# in VT 10.4.0 to 10.6.5): ``central_boiler`` once its command has gone out, or
# ``delayed_activation_sec`` when its activation delay starts (``feature_central_boiler_manager``).
CENTRAL_BOILER_EVENT = "versatile_thermostat_central_boiler_event"
EVENT_SWITCHED = "central_boiler"
EVENT_DELAY = "delayed_activation_sec"
# What VT's central boiler commands may do to the helper (I12): turn it on to heat, off to stop.
HELPER_ON = frozenset({("input_boolean", "turn_on"), ("homeassistant", "turn_on")})
HELPER_OFF = frozenset({("input_boolean", "turn_off"), ("homeassistant", "turn_off")})
# The oldest VT supported (I12.6, the user's decision of 2026-11-25): 10.6.5, the newest stable at
# the beta. Its manifest says 10.6.4 (the tag's ``manifest.json``), and Home Assistant reports what
# the manifest says, so the floor is compared as 10.6.4 and named 10.6.5 to the user; a real
# 10.6.4, which drops its API with its last entry, gets the factory again when a VT entry is set
# up (``feature_manager``). Older VT: no registration, control blocked (``vt_too_old``).
VT_OLDEST = "10.6.4"
VT_OLDEST_SHOWN = "10.6.5"
VT_TESTED = "10.6.5"  # the VT version the plugin is tested with (10.5.1 until 2026-11-25)
OVER_SWITCH = "over_switch"  # VT's ``configuration`` ``type`` of a zone it switches on and off
HVAC_OFF_REASON = "hvac_off_reason"  # in a thermostat's ``specific_states`` (VT 10.4.0 to 10.6.5)
ROOM_SENSOR = "temperature_sensor_entity_id"  # in a thermostat's entry data (VT 10.4.0)
# The entities a thermostat drives — switches, valves or climates — in its entry's data (VT 10.4.0
# ``const.py:63``, ``CONF_UNDERLYING_LIST``; migrated there from the older per-slot keys).
UNDERLYING = "underlying_entity_ids"


@dataclass(frozen=True, slots=True)
class ZoneAlgorithm:
    used_by_central_boiler: bool | None = None
    # K4 (2026-11-17): VT's thermostat type ("over_switch", "over_valve", "over_climate", …) and
    # its cycle in minutes (``configuration``, VT 10.5.1 and 10.6.5 ``base_thermostat.py``).
    vtherm_type: str | None = None
    cycle_min: float | None = None
    # PB-47: VT's state was read — the zone known and its configuration published; else none
    # of the above can be told (VT not started, the zone unknown or unavailable).
    known: bool = False

    @property
    def switches_on_off(self) -> bool:
        """VT switches the zone's heating on and off in its cycle (over_switch, TPI or SmartPI):
        each gap between its pulses can stop the boiler. Valve zones open in proportion."""
        return self.vtherm_type == OVER_SWITCH


@dataclass(frozen=True, slots=True)
class VtCommand:
    """One of VT's central boiler commands, as its documented format gives it."""

    entity_id: str
    domain: str
    service: str
    attribute: str | None = None
    value: str | None = None


class VtBoilerCheck(StrEnum):
    """What VT's central boiler settings say against the helper picked (I12): the blockers."""

    NOT_SET = "vt_central_boiler_not_set"  # not ticked, or a command missing
    NOT_HELPER = "vt_command_not_helper"  # a command switches anything but the helper: two
    # controllers


@dataclass(frozen=True, slots=True)
class VtCentralBoiler:
    """VT's central boiler settings as ``entry_infos`` carries them (I12): ticked or not, and its
    two commands as VT keeps them — ``None`` where empty."""

    configured: bool  # "use a central boiler" ticked in VT
    activation: str | None = None
    deactivation: str | None = None

    def check(self, helper: str | None) -> tuple[VtBoilerCheck | None, str | None]:
        """Whether VT's central boiler switches the helper alone: ticked, with both commands —
        VT counts it as configured with one, but then the helper would never turn back — the
        activation command turning ``helper`` on, the deactivation command turning it off. The
        problem, and the entity a command targets instead — the command as VT keeps it where the
        plugin cannot read it — for the user to see; ``(None, None)`` where all is right."""
        if not self.configured or self.activation is None or self.deactivation is None:
            return VtBoilerCheck.NOT_SET, None
        for raw, allowed in ((self.activation, HELPER_ON), (self.deactivation, HELPER_OFF)):
            command = parse_vt_command(raw)
            if command is None:
                return VtBoilerCheck.NOT_HELPER, raw
            does = (command.domain, command.service)
            if command.entity_id != helper or does not in allowed or command.attribute:
                return VtBoilerCheck.NOT_HELPER, command.entity_id
        return None, None


@dataclass(frozen=True, slots=True)
class VtCapabilities:
    vt_loaded: bool
    vt_version: str | None
    vtherm_api_version: str | None


def room_sensor(hass: HomeAssistant, entity_id: str) -> str | None:
    """The room temperature sensor VT reads for a zone, from the thermostat's entry (VT 10.4.0
    keeps it in the entry's data); ``None`` where it is not found."""
    registered = er.async_get(hass).async_get(entity_id)
    if registered is None or registered.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(registered.config_entry_id)
    sensor = entry.data.get(ROOM_SENSOR) if entry is not None else None
    return sensor if isinstance(sensor, str) and sensor else None


def zone_underlying_entities(hass: HomeAssistant, entity_id: str) -> tuple[str, ...] | None:
    """The entities VT drives for a zone, from the thermostat's entry (VT 10.4.0 keeps them in
    the entry's data); ``None`` where they cannot be read — the thermostat not registered, its
    entry away, or an entry without the list (an older VT)."""
    registered = er.async_get(hass).async_get(entity_id)
    if registered is None or registered.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(registered.config_entry_id)
    raw = entry.data.get(UNDERLYING) if entry is not None else None
    if not isinstance(raw, list | tuple):
        return None
    return tuple(item for item in raw if isinstance(item, str) and item)


def zones_on_boiler_thermostat(
    hass: HomeAssistant, zones: Sequence[str], boiler_entities: Sequence[str]
) -> list[str]:
    """X5.19, the wall-thermostat decision: the zones VT builds on the boiler's or the gateway's
    own thermostat — a climate among the zone's underlying entities that ``opentherm_gw``
    registered, or that sits on the same device as an entity the plugin maps as a boiler signal
    or controls through (``boiler_entities``; provisional, K4: also the OTGW firmware's MQTT
    climate and an EMS thermostat's). Such a zone would ask for heat whenever the flame burns. A
    zone whose VT entry cannot be read is not counted: the check repeats at every step."""
    registry = er.async_get(hass)
    devices = {
        registered.device_id
        for entity in boiler_entities
        if (registered := registry.async_get(entity)) is not None and registered.device_id
    }
    found: list[str] = []
    for zone in zones:
        for underlying in zone_underlying_entities(hass, zone) or ():
            if not underlying.startswith("climate."):
                continue
            registered = registry.async_get(underlying)
            if registered is None:
                continue
            if registered.platform == OPENTHERM_GW_DOMAIN or (
                registered.device_id is not None and registered.device_id in devices
            ):
                found.append(zone)
                break
    return found


def relay_used_by_zone(hass: HomeAssistant, entity_id: str) -> bool:
    """R2: a VT thermostat — any of them, not only the plugin's zones — lists the entity among
    the devices it drives: it switches it for a room, so it cannot be the boiler's relay."""
    return any(
        entity_id in (zone_underlying_entities(hass, zone) or ())
        for zone in vt_climate_entities(hass)
    )


def relay_of_boiler_interface(hass: HomeAssistant, entity_id: str) -> bool:
    """R2: the entity belongs to the boiler's gateway integration or to VT — a setting of the
    boiler interface or a VT entity, never a relay contact."""
    registered = er.async_get(hass).async_get(entity_id)
    return registered is not None and registered.platform in (OPENTHERM_GW_DOMAIN, VT_DOMAIN)


def parse_vt_command(raw: object) -> VtCommand | None:
    """One of VT's central boiler commands in VT's documented format
    ``entity_id/domain.service[/attribute:value]`` (the plugin's own reading of the format; the
    value may hold a template, ``/`` included, VT 10.6.1); ``None`` for anything else."""
    if not isinstance(raw, str):
        return None
    parts = [part.strip() for part in raw.strip().split("/", 2)]
    if len(parts) not in (2, 3):
        return None
    entity_id, service = parts[0], parts[1]
    if entity_id.count(".") != 1 or service.count(".") != 1:
        return None
    domain, name = service.split(".")
    if not (entity_id.split(".")[0] and entity_id.split(".")[1] and domain and name):
        return None
    attribute = value = None
    if len(parts) == 3:
        if ":" not in parts[2]:
            return None
        attribute, value = (item.strip() for item in parts[2].split(":", 1))
        if not attribute:
            return None
    return VtCommand(entity_id, domain, name, attribute, value)


def is_vt_climate(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether an entity is a climate Versatile Thermostat registered — what a zone must be
    (review question 19, provisional, K4)."""
    registered = er.async_get(hass).async_get(entity_id)
    return (
        registered is not None
        and registered.domain == "climate"
        and registered.platform == VT_DOMAIN
    )


def vt_zones_in_area(hass: HomeAssistant, area_id: str) -> list[str]:
    """The VT climates in an area (I8, decision F2: a circuit's shortcut to its zones) — an
    entity's own area, else its device's — in the registry's order."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found: list[str] = []
    for entry in entities.entities.values():
        if entry.domain != "climate" or entry.platform != VT_DOMAIN:
            continue
        area = entry.area_id
        if area is None and entry.device_id is not None:
            device = devices.async_get(entry.device_id)
            area = device.area_id if device is not None else None
        if area == area_id:
            found.append(entry.entity_id)
    return found


def zones_of_another_kind(hass: HomeAssistant, zones: Sequence[str]) -> list[str]:
    """Zones known not to be VT climates (a hand edit): registered by another integration or of
    another domain, or not registered at all yet reported — VT registers every thermostat. A
    zone neither registered nor reported is unknown, not of another kind (VT away)."""
    registry = er.async_get(hass)
    found: list[str] = []
    for zone in zones:
        registered = registry.async_get(zone)
        if registered is None:
            if hass.states.get(zone) is not None:
                found.append(zone)
        elif registered.domain != "climate" or registered.platform != VT_DOMAIN:
            found.append(zone)
    return found


def zone_name(hass: HomeAssistant, entity_id: str) -> str:
    """A zone's name as the user sees it. While the thermostat has no state (VT not started
    yet at the plugin's setup), its registry entry's — the user's name, its own, then its
    device's (PB-80); its entity ID only outside the registry."""
    state = hass.states.get(entity_id)
    if state is not None and state.name:
        return state.name
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return entity_id
    if entry.name or entry.original_name:
        return str(entry.name or entry.original_name)
    device = dr.async_get(hass).async_get(entry.device_id) if entry.device_id else None
    if device is not None and (device.name_by_user or device.name):
        return str(device.name_by_user or device.name)
    return entity_id


def vt_climate_entities(hass: HomeAssistant) -> list[str]:
    """Every climate entity registered by VT."""
    registry = er.async_get(hass)
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == VT_DOMAIN and entry.domain == "climate"
    )


def zone_devices(hass: HomeAssistant) -> dict[str, str]:
    """Each VT zone's own devices with the zone, as a circuit's form offers them (I8.8c): what
    each thermostat's entry lists; a zone whose list cannot be read offers none. A device two
    zones name stays with the first, in the zones' order."""
    found: dict[str, str] = {}
    for zone in vt_climate_entities(hass):
        for device in zone_underlying_entities(hass, zone) or ():
            found.setdefault(device, zone)
    return found


def vt_version(hass: HomeAssistant) -> str | None:
    """VT's version as its manifest gives it (Home Assistant refuses a custom integration
    without a valid one); ``None`` while VT is not loaded or on any loader problem."""
    try:
        integration = async_get_loaded_integration(hass, VT_DOMAIN)
        return None if integration.version is None else str(integration.version)
    except Exception:  # any loader problem just means "unknown"
        _LOGGER.debug("VT's version could not be read", exc_info=True)
        return None


def vt_supported(version: str | None) -> bool | None:
    """Whether a VT version is one the plugin supports (``VT_OLDEST``); ``None`` when the version
    is unknown or cannot be compared — capability detection decides then. A beta of the oldest
    counts as older: support is under-claimed, never over."""
    if not version:
        return None
    try:
        return AwesomeVersion(version) >= AwesomeVersion(VT_OLDEST)
    except Exception:  # a version of another form
        return None


def register_thermostat(hass: HomeAssistant, thermostat: Any) -> None:
    """Keep a thermostat VT handed to the plugin's feature manager (``vtherm_api``)."""
    thermostats: list[Any] = hass.data.setdefault(THERMOSTATS_KEY, [])
    if not any(kept is thermostat for kept in thermostats):
        thermostats.append(thermostat)


def unregister_thermostat(hass: HomeAssistant, thermostat: Any) -> None:
    """Forget a thermostat VT stopped (its manager's ``stop_listening``)."""
    thermostats: list[Any] = hass.data.get(THERMOSTATS_KEY, [])
    thermostats[:] = [kept for kept in thermostats if kept is not thermostat]


def vt_thermostat(hass: HomeAssistant, entity_id: str) -> Any | None:
    """The VT thermostat behind a climate entity, as VT handed it to the plugin: matched by the
    unique ID ``vtherm_api`` declares, against the entity's VT registry entry; the newest one
    kept, as VT's own ``get_feature_manager`` picks. ``None`` for a thermostat VT never handed
    over — one VT started before the plugin registered, until VT's reload."""
    thermostats: list[Any] = hass.data.get(THERMOSTATS_KEY, [])
    if not thermostats:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != VT_DOMAIN:
        return None
    for thermostat in reversed(thermostats):
        try:
            unique_id = thermostat.unique_id
        except Exception:  # VT's property failed: not this one
            continue
        if unique_id == entry.unique_id:
            return thermostat
    return None


def vt_central_boiler(hass: HomeAssistant) -> VtCentralBoiler | None:
    """VT's central boiler settings (I12), from the ``entry_infos`` of the newest thermostat VT
    handed over — the thermostat's settings merged over VT's central entry's, so every
    thermostat carries them. While VT holds none (it reloads them all when its central entry
    changes), the settings last handed over in this Home Assistant run stand; ``None`` while VT
    has handed none over in this run (as at every start, until VT starts its thermostats). Read
    defensively: a thermostat whose ``entry_infos`` is missing, fails or is not a mapping is
    passed over."""
    thermostats: list[Any] = hass.data.get(THERMOSTATS_KEY, [])
    for thermostat in reversed(thermostats):
        infos = runtime_readings(thermostat, ("entry_infos",)).get("entry_infos")
        if isinstance(infos, Mapping):
            settings = VtCentralBoiler(
                configured=infos.get(CENTRAL_BOILER_FEATURE) is True,
                activation=_command(infos.get(ACTIVATION_SERVICE)),
                deactivation=_command(infos.get(DEACTIVATION_SERVICE)),
            )
            hass.data[VT_SETTINGS_KEY] = settings
            return settings
    last = hass.data.get(VT_SETTINGS_KEY)
    return last if isinstance(last, VtCentralBoiler) else None


def _command(raw: object) -> str | None:
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def central_boiler_event() -> str:
    """VT's central boiler event's name, as ``vtherm_api`` gives it; the name it has had in
    every VT supported where this ``vtherm_api`` does not."""
    try:
        from vtherm_api.const import EventType

        return str(EventType.CENTRAL_BOILER_EVENT.value)
    except ImportError, AttributeError:
        return CENTRAL_BOILER_EVENT


@dataclass(frozen=True, slots=True)
class VtBoilerEvent:
    """What VT's central boiler event says (I12): its command went out (``switched``), or its
    activation delay starts, this many seconds long (``delay_s``)."""

    switched: bool = False
    delay_s: float | None = None


def read_central_boiler_event(data: Mapping[str, Any]) -> VtBoilerEvent | None:
    """VT's central boiler event's data; ``None`` for anything this version does not read — a
    delay that is no positive, finite number of seconds included."""
    if EVENT_SWITCHED in data:
        return VtBoilerEvent(switched=True)
    delay = data.get(EVENT_DELAY)
    if (
        isinstance(delay, int | float)
        and not isinstance(delay, bool)
        and math.isfinite(delay)
        and delay > 0
    ):
        return VtBoilerEvent(delay_s=float(delay))
    return None


def runtime_readings(thermostat: Any, members: Sequence[str]) -> dict[str, object]:
    """The members a VT thermostat gives now; one that is missing, fails, or is a method where
    ``vtherm_api`` declares a property is left out — the caller keeps the attribute's value."""
    found: dict[str, object] = {}
    for member in members:
        try:
            value = getattr(thermostat, member)
        except Exception:  # missing in this VT, or its property failed
            continue
        if not callable(value):
            found[member] = value
    return found


class VThermLink:
    """Zones as the core sees them, read through ``vtherm_api`` and from VT's climate
    entities."""

    def __init__(self, hass: HomeAssistant, zone_entities: Sequence[str]) -> None:
        self._hass = hass
        self._zones = tuple(zone_entities)
        self._api_version: str | None = None
        self._through_api: set[str] = set()  # the zones read through ``vtherm_api`` last time

    async def async_detect(self) -> None:
        """Read what does not change while Home Assistant runs — the installed ``vtherm_api``
        — once, in the executor: package metadata is read from disk."""
        self._api_version = await self._hass.async_add_executor_job(_vtherm_api_version)

    def zone(self, entity_id: str) -> ZoneState:
        state = self._hass.states.get(entity_id)
        zone = self.zone_from_state(entity_id, state)
        thermostat = self._thermostat(entity_id, state)
        if thermostat is not None:
            unit = str(self._hass.config.units.temperature_unit)
            found = runtime_zone(runtime_readings(thermostat, RUNTIME_MEMBERS), unit)
            zone = replace(zone, **found)
            self._through_api.add(entity_id)
        else:
            self._through_api.discard(entity_id)
        lost = zone.safety_on or self._room_sensor_lost(entity_id)
        return replace(zone, room_sensor_lost=lost)

    def _thermostat(self, entity_id: str, state: State | None) -> Any | None:
        """The zone's VT thermostat as VT handed it to the plugin, while VT shows it running: a
        climate away, unavailable or unknown keeps what its state says."""
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return vt_thermostat(self._hass, entity_id)

    def zones_through_api(self) -> list[str]:
        """The zones whose values came through ``vtherm_api`` at their last read."""
        return sorted(self._through_api)

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
            devices_active=values.devices_active,
            # What a count of devices is capped by (2026-10-14): the devices VT's entry lists.
            device_count=len(zone_underlying_entities(self._hass, entity_id) or ()) or None,
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

    def vt_too_old(self) -> bool:
        """VT is loaded and older than the oldest the plugin supports (I12.6); not while its
        version is unknown."""
        return vt_supported(vt_version(self._hass)) is False

    def zones_of_another_kind(self) -> list[str]:
        """The zones known not to be VT climates (a hand edit, X5.7)."""
        return zones_of_another_kind(self._hass, self._zones)

    def relay_used_by_zone(self, relay: str) -> bool:
        """R2: a VT thermostat drives the relay for a room (``relay_used_by_zone``)."""
        return relay_used_by_zone(self._hass, relay)

    def relay_of_boiler_interface(self, relay: str) -> bool:
        """R2: the relay belongs to the boiler's gateway integration or to VT."""
        return relay_of_boiler_interface(self._hass, relay)

    def zones_on_boiler_thermostat(self, boiler_entities: Sequence[str]) -> list[str]:
        """The zones built on the boiler's or the gateway's own thermostat (X5.19), as VT's
        entries say now: VT can be reconfigured without the plugin's options changing."""
        return zones_on_boiler_thermostat(self._hass, self._zones, boiler_entities)

    def recorded_state(self, entity_id: str) -> State | None:
        """A zone's current state as the history records it."""
        return self._hass.states.get(entity_id)

    def zone_off_reason(self, entity_id: str) -> str | None:
        """Why VT keeps a zone off (SB-27): ``hvac_off_reason``, which VT publishes in the
        thermostat's ``specific_states`` (VT 10.4.0 to 10.6.5 ``base_thermostat.py``:
        ``hvac_off_manual``, ``hvac_off_sleep_mode``, ``hvac_off_window_detection``,
        ``hvac_off_central_mode``, ``hvac_off_safety_detection``, ``hvac_off_auto_start_stop``;
        from 10.6.1 ``hvac_off_inhibition``, a plugin that took the thermostat out of VT's
        control). Beside the other attributes only where ``specific_states`` lacks it (assumed,
        a VT not seen). ``None`` when it is away, missing or not a text."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return None
        thermostat = self._thermostat(entity_id, state)
        if thermostat is not None:
            readings = runtime_readings(thermostat, (HVAC_OFF_REASON,))
            if HVAC_OFF_REASON in readings:
                reason = readings[HVAC_OFF_REASON]
                return reason if isinstance(reason, str) else None
        specific = state.attributes.get("specific_states")
        reason = specific.get(HVAC_OFF_REASON) if isinstance(specific, dict) else None
        if reason is None:
            reason = state.attributes.get(HVAC_OFF_REASON)
        return reason if isinstance(reason, str) else None

    def zone_algorithm(self, entity_id: str) -> ZoneAlgorithm:
        """What runs a zone, from VT's live attributes (not kept by the recorder); its cycle
        through ``vtherm_api`` where VT handed the thermostat over."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return ZoneAlgorithm()
        configuration = state.attributes.get("configuration")
        known = isinstance(configuration, dict) and state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        configuration = configuration if isinstance(configuration, dict) else {}
        used = configuration.get("is_used_by_central_boiler")
        kind = configuration.get("type")
        cycle = configuration.get("cycle_min")
        thermostat = self._thermostat(entity_id, state)
        if thermostat is not None:
            cycle = runtime_readings(thermostat, ("cycle_min",)).get("cycle_min", cycle)
        return ZoneAlgorithm(
            used_by_central_boiler=used if isinstance(used, bool) else None,
            vtherm_type=kind if isinstance(kind, str) else None,
            cycle_min=(
                float(cycle)
                if isinstance(cycle, int | float) and not isinstance(cycle, bool) and cycle > 0
                else None
            ),
            known=known,
        )

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
        return VtCapabilities(
            vt_loaded,
            vt_version(self._hass) if vt_loaded else None,
            self._api_version,
        )


def _vtherm_api_version() -> str | None:
    """The installed ``vtherm_api`` version; ``None`` when it cannot be imported."""
    try:
        import_module("vtherm_api")
        return version("vtherm_api")
    except ImportError, PackageNotFoundError:
        return None
