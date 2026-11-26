"""The only module that reads Versatile Thermostat's thermostats and VT's settings.

They go only through ``vtherm_api`` (the user's rule, 2026-11-24/25; I12.7): VT hands each of
its thermostats to the plugin's feature manager, which keeps it here (``register_thermostat``).
The plugin's rooms are the thermostats VT hands over whose ``entry_infos`` say VT's central
boiler counts them (``used_by_controls_central_boiler``; I12.11, the user's decision of
2026-11-25): VT's central boiler decides whether the boiler heats from those alone (``rooms``).
One handed over and not marked is no room (``not_counted``). The link keeps a room it knew while
VT holds no thermostat for it — VT reloading it, or not started yet — as not known rather than
gone (``VThermLink.rooms``, decision 3). A room is matched by its declared
``entity_id`` and named by its declared ``name``; its live values are the members the API
declares (``vtherm_attributes.RUNTIME_MEMBERS``), its settings its ``entry_infos`` — the
thermostat's settings merged over VT's central entry's (VT 10.6.5 ``base_thermostat.py``). VT
started it once it called the manager's ``refresh_state`` (``thermostat_started``: VT calls it
first only once the thermostat is ready), and the duty and valve opening VT applied come from its
power hook (``thermostat_power``: each cycle start, valve update and stop; never for a plain
over_climate). A thermostat VT has not handed over — one VT started before the plugin
registered, until VT's reload — is no room yet: nothing of VT's climate entity stands in for it.
Nothing of SmartPI is read (I12.9), nor VT's central mode (I12.11).

Nothing of VT's climate entities is read, nor goes into the history: the rooms' history is what
the plugin read here, kept in its own store (I12.7b). What the plugin takes from Home Assistant
about VT is Home Assistant's own information, not VT's data (gap 19): VT's version and whether VT
is loaded (its integrations and config entries), and its entity registry — whether VT has climate
entities at all (the first installation's reload repair, ``vt_climates_registered``) and an
entity's area (a circuit's area shortcut, ``rooms_in_area``).

VT's central boiler decides whether the boiler heats (I12): its settings reach the plugin in each
handed-over thermostat's ``entry_infos``, read here only to check that its commands switch the
helper the user picked, never the boiler (``vt_central_boiler``). The commands are split by the
plugin's own reading of VT's documented format ``entity_id/domain.service[/attribute:value]``.

The rooms' trust (I12, decision 8): a room's temperature judges the curve only while VT does not
run its thermostat in safety mode — VT's safety event, listened to here while the plugin runs
(``VThermLink.start``) and kept per thermostat until it ends or VT hands over another one —, its
thermometer is available — the room's sensor ``entry_infos`` names, the user's device, its state
read from Home Assistant —, and VT's ``last_temperature_measure`` for it is newer than the
plugin's start (``core.zones.room_trusted``). A room's window is open while VT holds it off for a
window (``hvac_off_reason``), VT's automatic window detection says so (its event), or the window
sensor ``entry_infos`` names reads on (the critical zone's window rule, ``core.critical_zone``).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util

from .const import DOMAIN, OPENTHERM_GW_DOMAIN, VT_DOMAIN
from .core.readings import ZoneState
from .core.zones import room_trusted
from .vtherm_attributes import RUNTIME_MEMBERS, live_zone

_LOGGER = logging.getLogger(__name__)

# VT's thermostats as VT handed them to the plugin's feature manager, for this Home Assistant run:
# kept across the plugin's reloads, as the managers are (``feature_manager``).
THERMOSTATS_KEY = f"{DOMAIN}_vt_thermostats"
# Whether VT has handed any thermostat over in this Home Assistant run (I12.11): one stopped
# while VT reloads leaves it set.
HANDED_OVER_KEY = f"{DOMAIN}_vt_handed_over"
# VT's central boiler settings as a thermostat last handed them over in this Home Assistant run
# (I12): while VT reloads its thermostats none is held, and the last ones stand.
VT_SETTINGS_KEY = f"{DOMAIN}_vt_central_boiler"
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
# VT's safety and automatic window events (``vtherm_api``'s ``EventType.SAFETY_EVENT`` and
# ``WINDOW_AUTO_EVENT``; VT 10.6.5 ``feature_safety_manager.py`` 199–227,
# ``feature_window_manager.py`` 301–304 and 357–360): ``type`` "start" or "end", the thermostat
# in ``entity_id`` (``const.py`` ``send_vtherm_event``, 654).
SAFETY_EVENT = "versatile_thermostat_safety_event"
WINDOW_AUTO_EVENT = "versatile_thermostat_window_auto_event"
EVENT_START = "start"
EVENT_END = "end"
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
HVAC_OFF_REASON = "hvac_off_reason"  # a member ``vtherm_api`` declares (0.9.0 ``interfaces.py``)
WINDOW_DETECTION = "hvac_off_window_detection"  # VT holds the zone off for a window (``const.py``)
# A thermostat's settings in its ``entry_infos`` (VT 10.6.5 ``const.py``): the user's devices VT
# reads for a room (65, 72), its type (111; the type of a zone VT switches on and off, 113), its
# cycle in minutes (90) and whether VT's central boiler counts it (240).
ROOM_THERMOMETER = "temperature_sensor_entity_id"
WINDOW_SENSOR = "window_sensor_entity_id"
THERMOSTAT_TYPE = "thermostat_type"
OVER_SWITCH = "thermostat_over_switch"
CYCLE_MIN = "cycle_min"
USED_BY_CENTRAL_BOILER = "used_by_controls_central_boiler"
# The kinds of device VT's power hook names (``vtherm_api`` 0.9.0 ``underlying_hooks.py``
# ``UnderlyingPowerCommand.underlying_type``: "switch", "valve" or "valve_regulation"): for a
# valve, the applied value is its opening.
VALVE_DEVICES = frozenset({"valve", "valve_regulation"})
# A device of the user's that has no state at all: removed, or not set up yet.
_MISSING = "missing"
# The room thermometer's states that leave the room's temperature out (I12, decision 8): gone too,
# as VT then keeps its last reading.
_LOST = frozenset({STATE_UNAVAILABLE, STATE_UNKNOWN, _MISSING})
# The entities a thermostat drives — switches, valves or climates — in its ``entry_infos`` (VT
# 10.6.5 ``const.py:63``, ``CONF_UNDERLYING_LIST``).
UNDERLYING = "underlying_entity_ids"


@dataclass(frozen=True, slots=True)
class ZoneAlgorithm:
    """A zone's settings, from its thermostat's ``entry_infos`` (I12.7)."""

    used_by_central_boiler: bool | None = None
    # K4 (2026-11-17): VT's thermostat type ("thermostat_over_switch", "thermostat_over_valve",
    # "thermostat_over_climate") and its cycle in minutes.
    vtherm_type: str | None = None
    cycle_min: float | None = None
    # PB-47: the thermostat's settings were read; else none of the above can be told (VT has not
    # handed the thermostat over).
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


def zone_underlying_entities(hass: HomeAssistant, entity_id: str) -> tuple[str, ...] | None:
    """The entities VT drives for a zone, from its thermostat's ``entry_infos``; ``None`` where
    they cannot be read — VT has not handed the thermostat over, or its settings hold no list."""
    thermostat = vt_thermostat(hass, entity_id)
    return None if thermostat is None else _underlying(thermostat)


def _underlying(thermostat: Any) -> tuple[str, ...] | None:
    raw = _entry_infos(thermostat).get(UNDERLYING)
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
    zone whose thermostat VT has not handed over cannot be read and is not counted: the check
    repeats at every step."""
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
    the devices it drives (its ``entry_infos``): it switches it for a room, so it cannot be the
    boiler's relay. A thermostat VT has not handed over is not seen: the check repeats at every
    step."""
    return any(entity_id in (_underlying(kept.thermostat) or ()) for kept in _handed_over(hass))


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


def rooms_in_area(hass: HomeAssistant, area_id: str) -> list[str]:
    """The rooms in an area (I8, decision F2: a circuit's shortcut to its rooms), in the rooms'
    order: a room's entity in it, or its device — Home Assistant's registries, not VT's data."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found: list[str] = []
    for room in rooms(hass):
        entry = entities.async_get(room)
        if entry is None:
            continue
        area = entry.area_id
        if area is None and entry.device_id is not None:
            device = devices.async_get(entry.device_id)
            area = device.area_id if device is not None else None
        if area == area_id:
            found.append(room)
    return found


def vt_climates_registered(hass: HomeAssistant) -> bool:
    """Whether Home Assistant's entity registry holds a climate entity of VT's that is not
    disabled — Home Assistant's information, no state of VT's: VT has thermostats (I12.11, the
    first installation's reload repair)."""
    return any(
        entry.platform == VT_DOMAIN and entry.domain == "climate" and entry.disabled_by is None
        for entry in er.async_get(hass).entities.values()
    )


def room_devices(hass: HomeAssistant) -> dict[str, str]:
    """Each room's own devices with the room, as a circuit's form offers them (I8.8c): what each
    thermostat's ``entry_infos`` lists. A device two rooms name stays with the first, in the
    rooms' order."""
    found: dict[str, str] = {}
    for room in rooms(hass):
        for device in zone_underlying_entities(hass, room) or ():
            found.setdefault(device, room)
    return found


def vt_version(hass: HomeAssistant) -> str | None:
    """VT's version as its manifest gives it (Home Assistant refuses a custom integration
    without a valid one); ``None`` while VT is not loaded or on any loader problem. Home
    Assistant's information about its integrations, not VT's data (gap 19)."""
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


@dataclass(slots=True)
class _Handed:
    """A thermostat VT handed to the plugin's feature manager, with what VT told the manager of
    it since: started (its ``refresh_state``), and the duty and valve opening VT last applied (its
    power hook) — ``None`` until VT's first call."""

    thermostat: Any
    started: bool = False
    duty: float | None = None
    valve: float | None = None


def _handed_over(hass: HomeAssistant) -> list[_Handed]:
    kept: list[_Handed] = hass.data.setdefault(THERMOSTATS_KEY, [])
    return kept


def _record(hass: HomeAssistant, thermostat: Any) -> _Handed | None:
    return next((kept for kept in _handed_over(hass) if kept.thermostat is thermostat), None)


def register_thermostat(hass: HomeAssistant, thermostat: Any) -> None:
    """Keep a thermostat VT handed to the plugin's feature manager (``vtherm_api``)."""
    if _record(hass, thermostat) is None:
        _handed_over(hass).append(_Handed(thermostat))
    hass.data[HANDED_OVER_KEY] = True


def any_handed_over(hass: HomeAssistant) -> bool:
    """Whether VT has handed any thermostat over in this Home Assistant run (I12.11)."""
    return hass.data.get(HANDED_OVER_KEY) is True


def holds_thermostats(hass: HomeAssistant) -> bool:
    """Whether VT holds any thermostat handed over now — none while it reloads them."""
    return bool(_handed_over(hass))


def _declared(kept: _Handed) -> str | None:
    """A thermostat's declared ``entity_id``; ``None`` where VT's property fails or is no
    entity."""
    try:
        declared = kept.thermostat.entity_id
    except Exception:  # VT's property failed: not this one
        return None
    return declared if isinstance(declared, str) and declared else None


def _marked(hass: HomeAssistant) -> dict[str, bool]:
    """Each thermostat VT holds now by its declared entity — the newest where two declare one,
    as ``_kept`` picks — with whether its ``entry_infos`` say VT's central boiler counts it
    (only a clear true counts)."""
    found: dict[str, bool] = {}
    for kept in reversed(_handed_over(hass)):
        entity_id = _declared(kept)
        if entity_id is None or entity_id in found:
            continue
        found[entity_id] = _entry_infos(kept.thermostat).get(USED_BY_CENTRAL_BOILER) is True
    return found


def rooms(hass: HomeAssistant) -> list[str]:
    """The plugin's rooms (I12.11): the thermostats VT holds now whose ``entry_infos`` say VT's
    central boiler counts them, by their declared entity, sorted — VT hands them over in no set
    order."""
    return sorted(entity_id for entity_id, marked in _marked(hass).items() if marked)


def not_counted(hass: HomeAssistant) -> list[str]:
    """The thermostats VT holds now that VT's central boiler does not count — no rooms of the
    plugin's (I12.11), sorted."""
    return sorted(entity_id for entity_id, marked in _marked(hass).items() if not marked)


def room_name(hass: HomeAssistant, entity_id: str) -> str:
    """A room's name: its thermostat's declared ``name``; its entity ID while VT holds no
    thermostat for it, or the name cannot be read."""
    thermostat = vt_thermostat(hass, entity_id)
    if thermostat is None:
        return entity_id
    try:
        name = thermostat.name
    except Exception:  # VT's property failed
        return entity_id
    return name if isinstance(name, str) and name else entity_id


def unregister_thermostat(hass: HomeAssistant, thermostat: Any) -> None:
    """Forget a thermostat VT stopped (its manager's ``stop_listening``), and with it what VT
    told of it: a thermostat VT hands over again starts unknown."""
    kept = _handed_over(hass)
    kept[:] = [record for record in kept if record.thermostat is not thermostat]


def thermostat_started(hass: HomeAssistant, thermostat: Any) -> None:
    """VT called the manager's ``refresh_state``: VT 10.6.5 calls it first in
    ``init_underlyings_completed`` and then in its control loop, each only once the thermostat is
    ready (``base_thermostat.py`` 735–760, 1959–2005) — the thermostat has started."""
    record = _record(hass, thermostat)
    if record is not None:
        record.started = True


def thermostat_power(hass: HomeAssistant, thermostat: Any, command: Any) -> None:
    """VT's power hook (``async_on_underlying_power``, ``vtherm_api`` 0.9.0
    ``underlying_hooks.py``): the share of the cycle VT applied to one of the thermostat's devices
    at a cycle start, a valve update or a stop (0 then) — the zone's duty, and for a valve its
    opening. A command that cannot be read changes nothing."""
    record = _record(hass, thermostat)
    applied = _applied(command)
    if record is None or applied is None:
        return
    record.duty, record.valve = applied


def _applied(command: Any) -> tuple[float, float | None] | None:
    """The duty VT applied, and the valve's opening where the device is a valve; ``None`` for a
    command without a share from 0 to 1."""
    try:
        applied = command.applied_on_percent
        device = command.underlying_type
    except Exception:  # not a power command of this ``vtherm_api``
        return None
    if (
        not isinstance(applied, int | float)
        or isinstance(applied, bool)
        or not math.isfinite(applied)
        or not 0.0 <= applied <= 1.0
    ):
        return None
    share = float(applied)
    return share, share if device in VALVE_DEVICES else None


def _kept(hass: HomeAssistant, entity_id: str) -> _Handed | None:
    """The thermostat behind a climate entity as VT handed it to the plugin: the one whose
    declared ``entity_id`` matches, the newest kept, as VT's own ``get_feature_manager`` picks.
    ``None`` for a thermostat VT never handed over — one VT started before the plugin
    registered, until VT's reload."""
    for kept in reversed(_handed_over(hass)):
        if _declared(kept) == entity_id:
            return kept
    return None


def vt_thermostat(hass: HomeAssistant, entity_id: str) -> Any | None:
    """The VT thermostat behind a climate entity, as VT handed it to the plugin (``_kept``)."""
    kept = _kept(hass, entity_id)
    return None if kept is None else kept.thermostat


def _entry_infos(thermostat: Any) -> Mapping[str, Any]:
    """A thermostat's ``entry_infos``; empty where it is missing, fails or is not a mapping."""
    infos = runtime_readings(thermostat, ("entry_infos",)).get("entry_infos")
    return infos if isinstance(infos, Mapping) else {}


def vt_central_boiler(hass: HomeAssistant) -> VtCentralBoiler | None:
    """VT's central boiler settings (I12), from the ``entry_infos`` of the newest thermostat VT
    handed over — the thermostat's settings merged over VT's central entry's, so every
    thermostat carries them. While VT holds none (it reloads them all when its central entry
    changes), the settings last handed over in this Home Assistant run stand; ``None`` while VT
    has handed none over in this run (as at every start, until VT starts its thermostats). Read
    defensively: a thermostat whose ``entry_infos`` is missing, fails or is not a mapping is
    passed over."""
    for kept in reversed(_handed_over(hass)):
        infos = runtime_readings(kept.thermostat, ("entry_infos",)).get("entry_infos")
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


def _vt_event(member: str, fallback: str) -> str:
    """A VT event's name, as ``vtherm_api`` gives it; the name it has had in every VT supported
    where this ``vtherm_api`` does not."""
    try:
        from vtherm_api.const import EventType

        return str(getattr(EventType, member).value)
    except ImportError, AttributeError:
        return fallback


def central_boiler_event() -> str:
    """VT's central boiler event's name."""
    return _vt_event("CENTRAL_BOILER_EVENT", CENTRAL_BOILER_EVENT)


def safety_event() -> str:
    """VT's safety event's name."""
    return _vt_event("SAFETY_EVENT", SAFETY_EVENT)


def window_auto_event() -> str:
    """VT's automatic window detection event's name."""
    return _vt_event("WINDOW_AUTO_EVENT", WINDOW_AUTO_EVENT)


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
    ``vtherm_api`` declares a property is left out — not known."""
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
    """The rooms as the core sees them, read through ``vtherm_api`` only (I12.7, I12.11)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._api_version: str | None = None
        # The rooms the plugin knows (I12.11, decision 3): those VT counted while it held their
        # thermostat in this run, and those the last run knew (``expect``), in order.
        self._known: dict[str, None] = {}
        # The plugin's start: a room's temperature counts once VT measured it after this.
        self._started_at = dt_util.utcnow().timestamp()
        # The thermostats VT's events said are in safety mode, or have a window open by its
        # automatic detection: each with the thermostat VT handed over then (``None``: none), so
        # a new one handed over — VT reloaded it — is not taken for the old one.
        self._safety: dict[str, Any] = {}
        self._window_auto: dict[str, Any] = {}

    def start(self, now: float) -> CALLBACK_TYPE:
        """Start following VT's safety and automatic window events, from ``now`` — the plugin's
        start, which a room's measurement must be newer than. Returns what stops it."""
        self._started_at = now
        self._safety.clear()
        self._window_auto.clear()
        stops = [
            self._hass.bus.async_listen(safety_event(), self._on_safety),
            self._hass.bus.async_listen(window_auto_event(), self._on_window_auto),
        ]

        @callback
        def stop() -> None:
            for unsubscribe in stops:
                unsubscribe()

        return stop

    @callback
    def _on_safety(self, event: Event[dict[str, Any]]) -> None:
        self._follow_event(self._safety, event.data)

    @callback
    def _on_window_auto(self, event: Event[dict[str, Any]]) -> None:
        self._follow_event(self._window_auto, event.data)

    def _follow_event(self, held: dict[str, Any], data: Mapping[str, Any]) -> None:
        """A VT event that starts or ends a state of one thermostat; anything else is passed
        over."""
        entity_id = data.get("entity_id")
        if not isinstance(entity_id, str):
            return
        kind = data.get("type")
        if kind == EVENT_START:
            held[entity_id] = vt_thermostat(self._hass, entity_id)
        elif kind == EVENT_END:
            held.pop(entity_id, None)

    def _held(self, held: dict[str, Any], entity_id: str, thermostat: Any) -> bool:
        """Whether an event's state still holds for a zone: started, not ended, and VT has not
        handed over another thermostat since — that one is forgotten."""
        if entity_id not in held:
            return False
        if held[entity_id] is not thermostat:
            del held[entity_id]
            return False
        return True

    async def async_detect(self) -> None:
        """Read what does not change while Home Assistant runs — the installed ``vtherm_api``
        — once, in the executor: package metadata is read from disk."""
        self._api_version = await self._hass.async_add_executor_job(_vtherm_api_version)

    def zone(self, entity_id: str) -> ZoneState:
        """A room as its thermostat gives it now (I12.7): its live members, the duty and valve
        VT last applied and whether VT has started it, as VT told the manager; read now, so fresh.
        Not known — not started, no mode — while VT has not handed the thermostat over."""
        kept = _kept(self._hass, entity_id)
        if kept is None:
            return ZoneState(entity_id, started=False, room_sensor_lost=True)
        thermostat = kept.thermostat
        raw = runtime_readings(thermostat, RUNTIME_MEMBERS)
        values = live_zone(raw, str(self._hass.config.units.temperature_unit))
        infos = _entry_infos(thermostat)
        trusted = room_trusted(
            safety=self._held(self._safety, entity_id, thermostat),
            thermometer_lost=self._device_state(infos.get(ROOM_THERMOMETER)) in _LOST,
            measured_at=values.get("temperature_at"),  # VT's own clock
            started_at=self._started_at,
        )
        window = (
            raw.get(HVAC_OFF_REASON) == WINDOW_DETECTION
            or self._held(self._window_auto, entity_id, thermostat)
            or self._device_state(infos.get(WINDOW_SENSOR)) == "on"
        )
        return ZoneState(
            entity_id,
            **values,
            on_percent=kept.duty,
            valve_open=kept.valve,
            reported_at=dt_util.utcnow().timestamp(),
            started=kept.started,
            room_sensor_lost=not trusted,
            window_open=window,
        )

    def _device_state(self, entity_id: object) -> str | None:
        """The state of a device of the user's that VT names for a room — its thermometer, its
        window sensor —, read from Home Assistant: ``"missing"`` for one that has no state;
        ``None`` where VT names none."""
        if not isinstance(entity_id, str) or not entity_id:
            return None
        state = self._hass.states.get(entity_id)
        return _MISSING if state is None else state.state

    def expect(self, entity_ids: Iterable[str]) -> None:
        """The rooms the last run knew — its rooms' store (I12.7b) —, expected until VT hands
        their thermostats over: at a start, before VT has handed them over, a room is not known
        yet rather than no room, so decision 3's recognition period waits for it."""
        for entity_id in entity_ids:
            self._known.setdefault(entity_id, None)

    def rooms(self) -> list[str]:
        """The rooms now, read at each refresh and control step (I12.11): the thermostats VT
        holds and its central boiler counts (``rooms``), and those the plugin knew while VT
        holds no thermostat for them — VT reloading them, or not started yet — so a room VT
        reloads is not known for a while rather than gone, as decision 3 wants. A known room
        goes once VT hands its thermostat over not counted, or once Home Assistant's registry no
        longer lists its entity (removed or renamed: Home Assistant's information). Sorted."""
        marked = _marked(self._hass)
        for entity_id, counted in marked.items():
            if counted:
                self._known.setdefault(entity_id, None)
            else:
                self._known.pop(entity_id, None)
        registry = er.async_get(self._hass)
        for entity_id in list(self._known):
            if entity_id not in marked and registry.async_get(entity_id) is None:
                del self._known[entity_id]
        return sorted(self._known)

    def not_counted(self) -> list[str]:
        """The thermostats VT holds now that its central boiler does not count."""
        return not_counted(self._hass)

    def zones(self) -> list[ZoneState]:
        """Each room as its thermostat gives it now."""
        return [self.zone(entity_id) for entity_id in self.rooms()]

    def zone_name(self, entity_id: str) -> str:
        """A room's name: its thermostat's declared ``name`` (``room_name``)."""
        return room_name(self._hass, entity_id)

    def vt_too_old(self) -> bool:
        """VT is loaded and older than the oldest the plugin supports (I12.6); not while its
        version is unknown."""
        return vt_supported(vt_version(self._hass)) is False

    def relay_used_by_zone(self, relay: str) -> bool:
        """R2: a VT thermostat drives the relay for a room (``relay_used_by_zone``)."""
        return relay_used_by_zone(self._hass, relay)

    def relay_of_boiler_interface(self, relay: str) -> bool:
        """R2: the relay belongs to the boiler's gateway integration or to VT."""
        return relay_of_boiler_interface(self._hass, relay)

    def zones_on_boiler_thermostat(self, boiler_entities: Sequence[str]) -> list[str]:
        """The rooms built on the boiler's or the gateway's own thermostat (X5.19), as VT's
        settings say now: VT can be reconfigured without the plugin's options changing."""
        return zones_on_boiler_thermostat(self._hass, self.rooms(), boiler_entities)

    def zone_algorithm(self, entity_id: str) -> ZoneAlgorithm:
        """A zone's settings, from its thermostat's ``entry_infos`` (I12.7); not known while VT
        has not handed the thermostat over."""
        thermostat = vt_thermostat(self._hass, entity_id)
        if thermostat is None:
            return ZoneAlgorithm()
        infos = _entry_infos(thermostat)
        used = infos.get(USED_BY_CENTRAL_BOILER)
        kind = infos.get(THERMOSTAT_TYPE)
        cycle = infos.get(CYCLE_MIN)
        return ZoneAlgorithm(
            used_by_central_boiler=used if isinstance(used, bool) else None,
            vtherm_type=kind if isinstance(kind, str) else None,
            cycle_min=(
                float(cycle)
                if isinstance(cycle, int | float) and not isinstance(cycle, bool) and cycle > 0
                else None
            ),
            known=bool(infos),
        )

    def capabilities(self) -> VtCapabilities:
        """VT loaded and its version, and the installed ``vtherm_api``: Home Assistant's
        information about its integrations and config entries, not VT's data (gap 19)."""
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
