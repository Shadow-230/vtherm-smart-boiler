"""The only module that reads Versatile Thermostat zones and VT's central configuration.

It reads VT's climate entities (state and top-level attributes, see ``vtherm_attributes``) and
VT's central mode select. It detects what is installed instead of assuming it: VT, its version,
``vtherm_api`` and SmartPI may be missing or older.

Moving over from VT's own central boiler (X8, R14), it reads — never writes — what VT's central
entry keeps (its commands, activation delay and keep-alive) and VT's two threshold numbers, so
the relay path's form can offer them for confirmation before the user unticks VT's central
boiler, which deletes the commands. The commands are split by the plugin's own reading of VT's
documented format ``entity_id/domain.service[/attribute:value]``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    ATTR_RESTORED,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util

from .const import DOMAIN, OPENTHERM_GW_DOMAIN, VT_DOMAIN
from .core.readings import ZoneState
from .transport.entities import reported_at
from .units import parse_number
from .vtherm_attributes import CentralMode, central_mode, zone_values

_LOGGER = logging.getLogger(__name__)

SMARTPI_DOMAIN = "vtherm_smartpi"
CENTRAL_MODE_UNIQUE_ID = "central_mode"
CENTRAL_BOILER_UNIQUE_ID = "central_boiler_state"
CENTRAL_BOILER_FEATURE = "use_central_boiler_feature"  # in VT's central entry (VT 10.4.0)
# VT's central boiler seen configured at any moment of this Home Assistant run (X7): VT's manager
# lives in its API and may switch the boiler until Home Assistant restarts, even once unticked,
# with or without its keep-alive. Kept in Home Assistant's data, so a reload of the plugin does
# not clear it and a restart does; never from VT's keep-alive. Also set (decision 9 of plan
# 0.2.3) when VT's central entry changed in this run while no entry of the plugin watched VT —
# its ``modified_at`` — or VT's sensor is a stand-in written in this run while the entry says
# off: VT provided it in this run, so its central boiler was on, and removed it since.
VT_CENTRAL_SEEN = f"{DOMAIN}_vt_central_seen"
# What the plugin knows of this Home Assistant run for that latch (``VtRun``); a restart starts
# it anew.
VT_RUN = f"{DOMAIN}_vt_run"
# Home Assistant's start neither seen by the plugin nor bounded by the recorder: anything VT's
# entries show may be from this run — a doubt keeps the latch (decision 9).
RUN_START_UNKNOWN = datetime.min.replace(tzinfo=UTC)
# VT's central entry running or being set up again (a reload, Home Assistant starting): its
# stored setting answers (P-105). In any other state — a failed setup (setup error or retry,
# migration error, failed unload), or one a later Home Assistant adds — only "off" rules VT's
# central boiler out: its manager may still run (P-20).
_CENTRAL_RUNNING = frozenset(
    {
        ConfigEntryState.LOADED,
        ConfigEntryState.SETUP_IN_PROGRESS,
        ConfigEntryState.UNLOAD_IN_PROGRESS,
        ConfigEntryState.NOT_LOADED,
    }
)
# VT loads outside feature managers from this version on (research/2026-09-27-q3-1-vt-feature-
# manager-version.md; provisional, K4): VT 10.0 and 10.1 use ``vtherm_api`` for control
# algorithms only — a registration there succeeds, and no manager is ever created (P-60).
VT_FEATURE_MANAGERS_FROM = "10.2.0"
VT_TESTED = "10.4.0"  # the only VT version the plugin is tested with
# VT's central entry is the one whose ``thermostat_type`` is this (VT 10.4.0 ``const.py``); its
# central boiler's activation delay, 0–600 s, stays in its data once the feature is unticked.
THERMOSTAT_TYPE = "thermostat_type"
CENTRAL_CONFIG = "thermostat_central_config"
ACTIVATION_DELAY = "central_boiler_activation_delay_sec"
VT_ACTIVATION_DELAY_MAX_S = 600.0
# VT's central boiler commands and keep-alive in its central entry (VT 10.4.0 ``const.py``), and
# the unique IDs of its two threshold numbers (``number.py``), read for the migration (R14).
ACTIVATION_SERVICE = "central_boiler_activation_service"
DEACTIVATION_SERVICE = "central_boiler_deactivation_service"
KEEP_ALIVE = "keep_alive_boiler_delay_sec"
COUNT_THRESHOLD_UNIQUE_ID = "boiler_activation_threshold"
POWER_THRESHOLD_UNIQUE_ID = "boiler_power_activation_threshold"
# The plugin's repeat interval takes VT's keep-alive only within its own range (R3).
REPEAT_RANGE_S = (10.0, 300.0)
ROOM_SENSOR = "temperature_sensor_entity_id"  # in a thermostat's entry data (VT 10.4.0)
# The entities a thermostat drives — switches, valves or climates — in its entry's data (VT 10.4.0
# ``const.py:63``, ``CONF_UNDERLYING_LIST``; migrated there from the older per-slot keys).
UNDERLYING = "underlying_entity_ids"


@dataclass(frozen=True, slots=True)
class ZoneAlgorithm:
    proportional_function: str | None = None  # "tpi" or "smartpi"
    smartpi_learning: bool | None = None  # SmartPI's learning flag; None: not SmartPI
    auto_tpi: bool = False  # Auto-TPI learning is on (a session or continuous kext)
    used_by_central_boiler: bool | None = None
    # PB-47: VT's state was read — the zone known and its configuration published; else none
    # of the above can be told (VT not started, the zone unknown or unavailable).
    known: bool = False


@dataclass(frozen=True, slots=True)
class VtCommand:
    """One of VT's central boiler commands, as its documented format gives it."""

    entity_id: str
    domain: str
    service: str
    attribute: str | None = None
    value: str | None = None


class VtCommands(StrEnum):
    """What VT's central boiler commands are, for the relay path."""

    NONE = "none"  # VT keeps none (never set, or deleted once unticked)
    RELAY = "relay"  # a switch turned on and off, or a boiler thermostat set to heat and off
    NOT_SUPPORTED = "not_supported"  # anything else: the user picks the relay


@dataclass(frozen=True, slots=True)
class VtCentralBoiler:
    """VT's central boiler settings, as the relay path's form may offer them (R14). ``None``
    wherever the plugin cannot use a value: the field stays empty and the user decides."""

    configured: bool  # "use a central boiler" ticked in VT
    commands: VtCommands
    relay: str | None = None
    activation_delay_s: float | None = None
    keep_alive_s: float | None = None  # VT's keep-alive, above 0
    repeat_s: float | None = None  # the keep-alive where it lies within 10–300 s
    power_threshold_kw: float | None = None  # as VT used it: whole numbers in its unit
    count_threshold: int | None = None  # one device per zone VT counts; VT's 0 beside power

    @property
    def exists(self) -> bool:
        """VT's central boiler is configured, or its commands are still kept."""
        return self.configured or self.commands is not VtCommands.NONE


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
    ``entity_id/domain.service[/attribute:value]`` (the plugin's own reading of the format);
    ``None`` for anything else."""
    if not isinstance(raw, str):
        return None
    parts = [part.strip() for part in raw.strip().split("/")]
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


def relay_from_vt_commands(on: VtCommand | None, off: VtCommand | None) -> str | None:
    """The relay VT's two commands switch, where they fit the relay path: one switch turned on
    and off, or one boiler thermostat set to heat and off; ``None`` for any other pair — VT's
    free-form actions are not supported (Open after 0.2.2)."""
    if on is None or off is None or on.entity_id != off.entity_id:
        return None
    entity = on.entity_id
    kind = entity.split(".")[0]
    if kind == "switch":
        turns = (on.domain, on.service, off.domain, off.service)
        plain = on.attribute is None and off.attribute is None
        return entity if plain and turns == ("switch", "turn_on", "switch", "turn_off") else None
    if kind == "climate":
        sets = all(
            (c.domain, c.service, c.attribute) == ("climate", "set_hvac_mode", "hvac_mode")
            for c in (on, off)
        )
        return entity if sets and (on.value, off.value) == ("heat", "off") else None
    return None


def vt_central_boiler_settings(hass: HomeAssistant, zones: Sequence[str]) -> VtCentralBoiler | None:
    """VT's central boiler as the relay path's form may pre-fill it (R14), read-only; ``None``
    without VT's central entry. ``zones``: the plugin's zones, which cap the count. The
    thresholds as VT used them — each the whole number of its state in VT's own unit — the
    power converted to kW (``W`` ÷ 1000, ``kW`` as is, any other unit not pre-filled), each only
    above 0; the count only where every zone VT counts has one heating device, as VT counts
    devices and the plugin rooms, or 0 where VT's count is 0 beside a power threshold. VT's
    keep-alive becomes the repeat interval only within 10–300 s."""
    entry = vt_central_entry(hass)
    if entry is None:
        return None
    data = entry.data
    raw_on, raw_off = data.get(ACTIVATION_SERVICE), data.get(DEACTIVATION_SERVICE)
    relay = relay_from_vt_commands(parse_vt_command(raw_on), parse_vt_command(raw_off))
    if relay is not None:
        commands = VtCommands.RELAY
    elif any(isinstance(raw, str) and raw.strip() for raw in (raw_on, raw_off)):
        commands = VtCommands.NOT_SUPPORTED
    else:
        commands = VtCommands.NONE
    keep_alive = _positive(data.get(KEEP_ALIVE))
    low, high = REPEAT_RANGE_S
    return VtCentralBoiler(
        configured=data.get(CENTRAL_BOILER_FEATURE) is True,
        commands=commands,
        relay=relay,
        activation_delay_s=VThermLink(hass, zones).vt_central_activation_delay(),
        keep_alive_s=keep_alive,
        repeat_s=keep_alive if keep_alive is not None and low <= keep_alive <= high else None,
        power_threshold_kw=_vt_power_threshold(hass),
        count_threshold=_vt_count_threshold(hass, len(zones)),
    )


def _positive(raw: object) -> float | None:
    value = parse_number(raw)
    return value if value is not None and value > 0 else None


def _vt_number(hass: HomeAssistant, unique_id: str) -> State | None:
    entity_id = er.async_get(hass).async_get_entity_id("number", VT_DOMAIN, unique_id)
    return None if entity_id is None else hass.states.get(entity_id)


def _vt_power_threshold(hass: HomeAssistant) -> float | None:
    """VT's power threshold as VT uses it: the whole number of its value in VT's power unit."""
    state = _vt_number(hass, POWER_THRESHOLD_UNIQUE_ID)
    value = None if state is None else parse_number(state.state)
    if value is None or int(value) <= 0:
        return None
    unit = state.attributes.get("unit_of_measurement") if state is not None else None
    factor = {"W": 0.001, "kW": 1.0}.get(unit if isinstance(unit, str) else "")
    return None if factor is None else int(value) * factor


def _vt_count_threshold(hass: HomeAssistant, zone_count: int) -> int | None:
    """VT's device-count threshold, as a count of rooms: only where every thermostat VT's
    central boiler counts has exactly one device, capped at the plugin's zone count. VT's
    count of 0 is "off" in VT 10.4.0 (``is_nb_active_active_for_boiler_exceeded``): beside a
    power threshold the plugin carries over, it is pre-filled 0, the power criterion alone as
    VT used it (SB-07, decision 7); a count missing or unreadable pre-fills nothing."""
    state = _vt_number(hass, COUNT_THRESHOLD_UNIQUE_ID)
    value = None if state is None else parse_number(state.state)
    if value is not None and int(value) == 0 and value >= 0:
        return 0 if _vt_power_threshold(hass) is not None else None
    if value is None or int(value) <= 0 or zone_count <= 0:
        return None
    link = VThermLink(hass, ())
    counted = [
        zone
        for zone in vt_climate_entities(hass)
        if link.zone_algorithm(zone).used_by_central_boiler is True
    ]
    if not counted:
        return None
    if any(len(zone_underlying_entities(hass, zone) or ()) != 1 for zone in counted):
        return None
    return min(int(value), zone_count)


def is_vt_climate(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether an entity is a climate Versatile Thermostat registered — what a zone must be
    (review question 19, provisional, K4)."""
    registered = er.async_get(hass).async_get(entity_id)
    return (
        registered is not None
        and registered.domain == "climate"
        and registered.platform == VT_DOMAIN
    )


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


def vt_central_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """VT's central configuration entry — the VT entry whose ``thermostat_type`` says so (VT
    10.4.0) — whatever its state; ``None`` without one. With more than one, an enabled entry in
    a running state, else an enabled one, else the first: not a disabled or failed one VT has
    replaced (PB-49). Read only: the plugin never writes to VT's entries."""
    centrals = [
        entry
        for entry in hass.config_entries.async_entries(VT_DOMAIN)
        if entry.data.get(THERMOSTAT_TYPE) == CENTRAL_CONFIG
    ]

    def preference(entry: ConfigEntry) -> tuple[bool, bool]:
        enabled = entry.disabled_by is None
        return enabled and entry.state in _CENTRAL_RUNNING, enabled

    return max(centrals, key=preference, default=None)  # the first of the best


@dataclass
class VtRun:
    """What the plugin knows of this Home Assistant run, for VT's central boiler's restart latch
    (decision 9): ``started`` — when Home Assistant had started, ``None`` while it starts;
    ``watchers`` — the plugin's entries watching VT now; ``unwatched_since`` — when the last of
    them stopped."""

    started: datetime | None = None
    watchers: int = 0
    unwatched_since: datetime | None = None


def vt_run(hass: HomeAssistant) -> VtRun:
    """This run's record, made at the plugin's first setup in the run. While Home Assistant
    starts, its start is taken once it has started — after it wrote the stand-ins of the
    registered entities nobody provides, so those predate it. A plugin first set up later has
    not seen it: the recorder's start (before VT was set up) stands for it, else nothing does
    and everything counts as this run's (a doubt keeps the latch)."""
    run = hass.data.get(VT_RUN)
    if isinstance(run, VtRun):
        return run
    run = VtRun()
    hass.data[VT_RUN] = run
    if hass.state in (CoreState.not_running, CoreState.starting):

        @callback
        def _started(_event: Event) -> None:
            run.started = dt_util.utcnow()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _started)
    else:
        run.started = _recording_start(hass) or RUN_START_UNKNOWN
    return run


def _recording_start(hass: HomeAssistant) -> datetime | None:
    """When the recorder began recording in this run; ``None`` without a recorder or one that
    does not say."""
    if "recorder" not in hass.config.components:
        return None
    try:
        from homeassistant.helpers.recorder import get_instance

        start = get_instance(hass).recorder_runs_manager.recording_start
    except Exception:  # an older or changed recorder: not known
        _LOGGER.debug("The recorder's start could not be read", exc_info=True)
        return None
    return start if isinstance(start, datetime) and start.tzinfo is not None else None


def _changed_since(entry: ConfigEntry, since: datetime) -> bool:
    """Whether a config entry changed after ``since``; a change time it does not give, or one
    without a time zone, counts as changed (a doubt keeps the latch)."""
    modified = getattr(entry, "modified_at", None)
    if not isinstance(modified, datetime) or modified.tzinfo is None:
        return True
    return modified > since


def vt_version(hass: HomeAssistant) -> str | None:
    """VT's version as its manifest gives it (Home Assistant refuses a custom integration
    without a valid one); ``None`` while VT is not loaded or on any loader problem."""
    try:
        integration = async_get_loaded_integration(hass, VT_DOMAIN)
        return None if integration.version is None else str(integration.version)
    except Exception:  # any loader problem just means "unknown"
        _LOGGER.debug("VT's version could not be read", exc_info=True)
        return None


def vt_loads_feature_managers(version: str | None) -> bool | None:
    """Whether a VT version creates the feature managers other integrations register (P-60);
    ``None`` when the version is unknown or cannot be compared — capability detection decides
    then. A beta of the first version counts as older: support is under-claimed, never over."""
    if not version:
        return None
    try:
        return AwesomeVersion(version) >= AwesomeVersion(VT_FEATURE_MANAGERS_FROM)
    except Exception:  # a version of another form
        return None


class VThermLink:
    """Zones as the core sees them, read from VT's climate entities."""

    def __init__(self, hass: HomeAssistant, zone_entities: Sequence[str]) -> None:
        self._hass = hass
        self._zones = tuple(zone_entities)
        self._api_version: str | None = None
        self._watching = False

    async def async_detect(self) -> None:
        """Read what does not change while Home Assistant runs — the installed ``vtherm_api``
        — once, in the executor: package metadata is read from disk."""
        self._api_version = await self._hass.async_add_executor_job(_vtherm_api_version)

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
        known = isinstance(configuration, dict) and state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
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
            known=known,
        )

    def vt_central_boiler_configured(self) -> bool | None:
        """Whether VT's own central boiler is set up — then it must not run alongside; ``None``
        while it cannot be ruled out (X7: P-20, P-105).

        In this order: seen configured at any moment of this Home Assistant run → there until the
        restart VT needs (``VT_CENTRAL_SEEN``; also set by ``watch_vt_central``). VT's sensor for
        it provided → what it says. Else VT's central entry answers — VT creates the sensor only
        while the feature is on, and Home Assistant keeps its registry entry, with a stand-in
        "unavailable" state, once VT no longer provides it: the entry gone or disabled by the
        user → not there; running or being set up again (a reload, Home Assistant starting) →
        its stored setting, unknown without it; stuck in a failed setup → not there only where
        its setting says "off" — unless the stand-in was written in this run after Home
        Assistant had started and VT's central entry changed since, so VT provided the sensor in
        this run (decision 9): there; one from Home Assistant's start, the entry unchanged
        since, is not (M1 of the part-2 check). Without
        the sensor in the registry, only VT's central entry saying "on" counts (VT has not
        registered the sensor yet)."""
        hass = self._hass
        if hass.data.get(VT_CENTRAL_SEEN):
            return True
        found = self._vt_central_boiler_now()
        if found is True:
            hass.data[VT_CENTRAL_SEEN] = True
            _LOGGER.info(
                "Versatile Thermostat's central boiler is configured: control stays blocked "
                "until Home Assistant restarts, even once it is unticked"
            )
        return found

    def _vt_central_boiler_now(self) -> bool | None:
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id(
            "binary_sensor", VT_DOMAIN, CENTRAL_BOILER_UNIQUE_ID
        )
        if entity_id is None:
            central = vt_central_entry(self._hass)
            if central is None or central.data.get(CENTRAL_BOILER_FEATURE) is not True:
                return False
            return _central_entry_says(central)
        state = self._hass.states.get(entity_id)
        entry = registry.async_get(entity_id)
        provided = state is not None and not state.attributes.get(ATTR_RESTORED)
        if state is not None and provided and not (entry is not None and entry.disabled):
            configured = state.attributes.get("is_central_boiler_configured")
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or configured is None:
                return None
            return configured is True
        owner = self._central_owner(entry)
        if owner is None:
            return False  # left behind by a VT entry that is gone
        says = _central_entry_says(owner)
        if says is False and state is not None and self._stand_in_of_this_run(state, owner):
            return True  # VT's central boiler on in this run, unticked since (decision 9)
        return says

    def _stand_in_of_this_run(self, state: State, owner: ConfigEntry) -> bool:
        """A stand-in Home Assistant wrote after it had started, with VT's central entry
        changed since: the entity was provided in this run and removed since. Not judged while
        Home Assistant starts — the stand-ins it writes then are for entities nobody provided.

        VT's central entry unchanged since the run's start (M1 of the part-2 check): the
        stand-in is the one Home Assistant writes at its start for every registered entity
        nobody provides (``entity_registry.py``, ``_write_unavailable_states`` on
        ``EVENT_HOMEASSISTANT_START``, Home Assistant 2026.9.3) — VT's central boiler was off
        before this run began. VT creates the sensor only while its central entry's setting is
        on (VT 10.4.0 ``binary_sensor.py``), and the setting changes only through an update of
        the entry, which moves its ``modified_at`` (``config_entries.py``): a sensor VT provided
        in this run, now off, means the entry changed in this run. Home Assistant keeps no time
        of its start a plugin set up later could read — the recorder's start, before it, stands
        for it — so the entry's change, not the stand-in's time, tells the two apart. A change
        time unknown, or no start known, keeps the latch (a doubt)."""
        if not state.attributes.get(ATTR_RESTORED):
            return False
        started = vt_run(self._hass).started
        return (
            started is not None and state.last_updated > started and _changed_since(owner, started)
        )

    def watch_vt_central(self) -> None:
        """An entry of the plugin begins watching VT (its coordinator starts). VT's central
        entry changed in this Home Assistant run while none watched — an untick the plugin did
        not see, VT's manager perhaps still switching the boiler — latches VT's central boiler as
        there until the restart (decision 9). A watch begun while Home Assistant starts has no
        unwatched time of this run before it."""
        if self._watching:
            return
        self._watching = True
        run = vt_run(self._hass)
        since = run.unwatched_since or run.started
        run.watchers += 1
        if run.watchers > 1 or since is None:
            return
        central = vt_central_entry(self._hass)
        if central is None or not _changed_since(central, since):
            return
        self._hass.data[VT_CENTRAL_SEEN] = True
        _LOGGER.info(
            "Versatile Thermostat's central entry changed in this Home Assistant run before this "
            "integration watched it: control stays blocked until Home Assistant restarts"
        )

    def stop_watching_vt_central(self) -> None:
        """The entry's coordinator stops: once no entry watches, the time is kept."""
        if not self._watching:
            return
        self._watching = False
        run = vt_run(self._hass)
        run.watchers = max(0, run.watchers - 1)
        if run.watchers == 0:
            run.unwatched_since = dt_util.utcnow()

    def _central_owner(self, sensor: er.RegistryEntry | None) -> ConfigEntry | None:
        """The entry of VT's central-boiler sensor; without the sensor in the registry, VT's
        central entry."""
        if sensor is None:
            return vt_central_entry(self._hass)
        if not sensor.config_entry_id:
            return None
        return self._hass.config_entries.async_get_entry(sensor.config_entry_id)

    def vt_central_entry_failed(self) -> bool:
        """VT's central entry is stuck in a failed setup and not disabled: VT's manager may still
        switch the boiler, so an unknown VT central boiler gets no grace there (P-20)."""
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id(
            "binary_sensor", VT_DOMAIN, CENTRAL_BOILER_UNIQUE_ID
        )
        owner = self._central_owner(None if entity_id is None else registry.async_get(entity_id))
        return (
            owner is not None and owner.disabled_by is None and owner.state not in _CENTRAL_RUNNING
        )

    def vt_central_activation_delay(self) -> float | None:
        """VT's central boiler activation delay, in seconds, as VT keeps it in its central
        entry — also once its central boiler is unticked (decision 5); ``None`` without VT, a
        central entry, or a number within VT's 0–600 s. A pre-fill for the form only: the
        plugin's own option is what counts."""
        entry = vt_central_entry(self._hass)
        if entry is None:
            return None
        raw = entry.data.get(ACTIVATION_DELAY)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        value = float(raw)
        inside = math.isfinite(value) and 0.0 <= value <= VT_ACTIVATION_DELAY_MAX_S
        return value if inside else None

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
            SMARTPI_DOMAIN in components,
        )


def _vtherm_api_version() -> str | None:
    """The installed ``vtherm_api`` version; ``None`` when it cannot be imported."""
    try:
        import_module("vtherm_api")
        return version("vtherm_api")
    except ImportError, PackageNotFoundError:
        return None


def _central_entry_says(entry: ConfigEntry) -> bool | None:
    """What VT's central entry says of its central boiler while its sensor does not: disabled
    by the user → not there; in a failed setup → not there only where its setting is "off", as
    VT's manager may still run (P-20); otherwise — running, or being set up again (P-105) — its
    stored setting, unknown without one."""
    if entry.disabled_by is not None:
        return False
    feature = entry.data.get(CENTRAL_BOILER_FEATURE)
    if entry.state not in _CENTRAL_RUNNING:
        return False if feature is False else None
    return feature if isinstance(feature, bool) else None
