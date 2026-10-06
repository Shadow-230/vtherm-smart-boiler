"""Control options (flow-setpoint mode) as core objects, and what keeps control from starting.

No Home Assistant imports. Every value has a cautious default; a blocker is a translation key
naming what the user must provide or fix before control may be switched on. Nothing goes to the
boiler's persistent memory: a picked setpoint entity and an external-control switch must be
declared expiring or held, and a heating switch declared otherwise is left alone ("off" is then a
low setpoint). The hand-back value is bound by the highest water temperature, never clamped, and
"off" must not read as it (S-21, S-49); "off" sent as a low setpoint stays at least 1 K below the
lowest water temperature, or the boiler would not see a change (P-43). Provisional
decisions of phase F (to be confirmed at the review, `docs/plan-0.2.md` K4): control only for an
installation with one circuit fed by the boiler flow (unmixed, or passive fixed); the curve must
be entered, never silently defaulted; VT's central boiler must not run alongside.

What the form refuses is a blocker too, for options that reach the plugin without it (a hand
edit, an older version's options — X5): one entity in two roles (P-03), one entity for two
signals (P-16), a topology that does not suit the path (P-44), a curve whose values do not fit
together (P-68), and — decision 11, until the user lifts it at K4 — control without a heating
switch the boiler does not store, where "off" would be a low setpoint (S-39).

Both gateway topologies ask what is wired to the gateway's thermostat terminals (decision 1,
S-01): an OpenTherm thermostat, an on/off contact, nothing, or "I don't know". The gateway keeps
a ``CH=0`` through ``CS=0`` and the override's lapse, so after a crash while "off" an on/off
contact could not heat the house: control is blocked for it, for "I don't know", and for no
answer — a gateway entry made before 0.2.2 keeps control stopped until the user answers, with a
notice asking for it (answer K). An answer that contradicts the topology blocks too.

An on/off boiler (class 3, X8) is switched through a relay: a switch, or a boiler thermostat
entity set to heat or off — never a helper, which confirms nothing. The relay's own settings are
the user's declaration, each unanswered one read cautiously (``core.relay``); without the tick
"this is a separate relay contact, not a setting stored in the boiler's memory" control does not
start (answer G). The water-temperature parts — curve, limits, ramp, comfort correction, the
circuit rules, the topology and the read-back — do not apply there; the demand thresholds do,
and the hand-back's effect is the relay's rest state. Water-temperature control needs flame and
flow mapped, which the entry itself no longer requires.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .const import CONTROL, has_control_section
from .core.controller import OUTAGE_LOST_S, ControlConfig
from .core.curve import HeatingCurve
from .core.demand import DemandConfig
from .core.guards import HELD_REFRESH_S, GuardConfig, WriteType
from .core.hand_back import DEVICE_TIMEOUT_BOUNDS_S, DEVICE_TIMEOUT_DEFAULT_S
from .core.installation import Boiler, BoilerClass, CircuitControl, EmitterType, Installation
from .core.learning import LearningConfig
from .core.limits import FlowLimits, FrostConfig
from .core.loop import DEFAULT_OFF_SETPOINT, LoopConfig
from .core.relay import (
    REPEAT_DEFAULT_S,
    REPEAT_MAX_S,
    REPEAT_MIN_S,
    TIMER_MAX_S,
    TIMER_MIN_S,
    RelayConfig,
    RelayPowerOn,
    RelayReports,
    RelayRest,
    RelayTimer,
)
from .core.signals import Signal

_LOGGER = logging.getLogger(__name__)

MINUTE = 60.0
KEEPALIVE_S = 30.0
# The OTGW's heating override CH= is held — the PIC keeps it in its RAM until CH=1 or a reset —
# yet it goes out again with every CS keep-alive: no memory wears, and a PIC reset nothing traces
# then loses "heating off" for one keep-alive at most, not X1's 5-minute held refresh
# (provisional, K4). Entity paths keep the 5-minute refresh.
OTGW_CH_REFRESH_S = KEEPALIVE_S

# Every control option's default, in the unit the options store: the parser and the options
# forms both read them here.
CONTROL_DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        # The lowest water temperature (decision 2): 20 °C, provisional until K4. An entry whose
        # control section had none keeps 25 °C, written by the entry migration.
        "hard_min": 20.0,
        "hard_max": 70.0,
        "ceiling_band": 10.0,
        "frost_limit": 5.0,
        "frost_release": 7.0,
        "count_threshold": 1,
        "ramp_k_per_min": 1.0,
        "decision_interval_min": 5.0,
        "off_setpoint": DEFAULT_OFF_SETPOINT,
        "learning_pauses": True,
        # Off: with VT's TPI zones it can hold the water at its +3 K edge and multiply the
        # burner's starts (decided by the user 2026-10-03, K4.1).
        "comfort_correction": False,
        # Without the tick, VT giving no answer at all means no heating and an alarm (answer F).
        "own_room_controller": False,
        # VT's activation delay (decision 5): 0 s, VT's own default — heating starts at once.
        "activation_delay_s": 0,
    }
)
CURVE_DEFAULTS: Mapping[str, float] = MappingProxyType(
    {"design_outdoor": -15.0, "design_flow": 55.0, "room": 20.0, "offset": 0.0}
)
# The lowest water temperature written by the entry migration (minor version 3) into a control
# section stored without one: 0.2.1's default, so no installation's floor drops silently
# (provisional, K4).
MIGRATED_HARD_MIN = 25.0


class WritePath(StrEnum):
    ENTITY = "entity"  # a writable entity the user picked
    OPENTHERM_GW = "opentherm_gw"  # built-in OTGW through Home Assistant's opentherm_gw
    OTGW_MQTT = "otgw_mqtt"  # built-in OTGW through its firmware's MQTT commands
    RELAY = "relay"  # an on/off boiler's relay: heating on and off only (class 3, X8)


class Topology(StrEnum):
    GATEWAY_STANDALONE = "gateway_standalone"  # the gateway is master: hand-back stops heating
    GATEWAY_WITH_THERMOSTAT = "gateway_with_thermostat"  # hand-back: the thermostat takes over
    MONITOR_MODE = "monitor_mode"  # the gateway only listens: no control
    VIRTUAL = "virtual"  # a controller on the HA side (e.g. an ESPHome OpenTherm master)


class ThermostatKind(StrEnum):
    """What is wired to a gateway's thermostat terminals (decision 1)."""

    OPENTHERM = "opentherm"  # an OpenTherm thermostat: it talks to the boiler
    ON_OFF = "on_off"  # an on/off contact: the gateway turns it into a heating request
    NONE = "none"  # nothing: the gateway is the master
    UNKNOWN = "unknown"  # "I don't know"


class HandBack(StrEnum):
    VALUE = "value"  # write a hand-back value to the setpoint entity
    TIMEOUT = "timeout"  # stop writing: the device's own timeout hands back
    SWITCH = "switch"  # turn off an entity that enables external control


class ValueEffect(StrEnum):
    """What the hand-back value does on the device, as the user declares it."""

    OWN_CONTROL = "own_control"  # the device's own control resumes
    HEATING_STOPS = "heating_stops"


class HandBackEffect(StrEnum):
    """What handing control back leads to, shown to the user."""

    THERMOSTAT_TAKES_OVER = "thermostat_takes_over"
    HEATING_STOPS = "heating_stops"  # a gateway without a thermostat: no heat until control
    DEVICE_DECIDES = "device_decides"  # a controller on the HA side: its own fallback applies
    # The user ticked "the boiler has its own room controller" (answer F): it takes over.
    OWN_CONTROL_RESUMES = "own_control_resumes"
    # A relay goes to its rest state (X8, R9): "off" — heat only from a thermostat in parallel;
    # "on" — the boiler heats by its own setting.
    RELAY_RESTS_OFF = "relay_rests_off"
    RELAY_RESTS_ON = "relay_rests_on"


class AlarmReaction(StrEnum):
    INFO = "info"
    HAND_BACK = "hand_back"


# Everything ``config_blockers`` may report (translation keys).
CONFIG_BLOCKERS = (
    "no_write_path",
    # X8: the write path suits the boiler class — a setpoint path a flow-setpoint boiler, the
    # relay an on/off boiler; the other classes are monitored only.
    "boiler_class_no_control",
    "path_not_for_boiler_class",
    "no_setpoint_entity",
    "write_type_not_supported",
    "no_hand_back",
    "timeout_needs_expiring_writes",
    "no_gateway",
    "no_mqtt_topic",
    "no_confirmed_setpoint",
    "no_topology",
    "topology_no_control",
    "curve_not_entered",
    "one_direct_circuit_only",
    "underfloor_without_max_flow",
    "no_zones",
    "count_threshold_above_zones",
    "off_setpoint_not_below_hard_min",
    "hand_back_switch_not_writable",
    "hand_back_value_above_max",
    "off_setpoint_near_hand_back_value",
    # X5: what the form refuses, for options that reach the plugin without it.
    "hand_back_switch_is_heating_switch",
    "entity_for_two_signals",
    "topology_not_for_path",
    "design_flow_too_low",
    "design_flow_above_hard_max",
    "design_outdoor_too_warm",
    "hard_min_not_below_design_flow",
    "no_heating_switch",
    # X6: what is wired to the gateway's thermostat terminals (decision 1).
    "thermostat_on_off",
    "thermostat_kind_unknown",
    "thermostat_kind_contradicts_topology",
    # X8: water-temperature control needs the boiler link mapped; the relay path its relay, as a
    # switch or a boiler thermostat entity used in no other role, and the separate-contact tick.
    "no_flame_signal",
    "no_flow_signal",
    "no_relay_entity",
    "relay_domain_not_supported",
    "relay_in_another_role",
    "relay_contact_not_confirmed",
)
OTGW_PATHS = frozenset({WritePath.OPENTHERM_GW, WritePath.OTGW_MQTT})
# Write types control may use: nothing the boiler stores in its memory.
WRITABLE_TYPES = frozenset({WriteType.EXPIRING, WriteType.HELD})
CONTROLLABLE_TOPOLOGIES = frozenset(
    {Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT, Topology.VIRTUAL}
)
# The topologies with thermostat terminals: each asks what is wired to them (decision 1).
GATEWAY_TOPOLOGIES = frozenset({Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT})
# The kind each gateway topology cannot have: an OpenTherm thermostat means "with a thermostat",
# nothing means stand-alone.
_CONTRADICTING_KIND = MappingProxyType(
    {
        Topology.GATEWAY_STANDALONE: ThermostatKind.OPENTHERM,
        Topology.GATEWAY_WITH_THERMOSTAT: ThermostatKind.NONE,
    }
)
# The topologies each write path can control with (P-44): the paths through a built-in OTGW need
# a gateway topology; "virtual" is a controller on the Home Assistant side, reached through an
# entity. The relay path has no topology (X8).
PATH_TOPOLOGIES: Mapping[WritePath, frozenset[Topology]] = MappingProxyType(
    {
        WritePath.RELAY: frozenset(),
        WritePath.OPENTHERM_GW: frozenset(
            {Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT}
        ),
        WritePath.OTGW_MQTT: frozenset(
            {Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT}
        ),
        WritePath.ENTITY: frozenset(CONTROLLABLE_TOPOLOGIES),
    }
)
# The relay step's answers (X8): the relay, its own settings as the user declares them, and the
# power above which the boiler counts as heating.
RELAY_KEYS = (
    "relay_entity", "relay_is_separate_contact", "relay_reports_state", "relay_power_on_state",
    "relay_off_timer", "relay_off_timer_min", "relay_repeat_s", "relay_rest_state",
    "boiler_heats_above_w",
)  # fmt: skip
# The answers of the writable-entity step — what control writes to, and how it hands back —
# dropped when the write path changes (P-71: one list; X6 and X8 add their keys here).
TARGET_KEYS = (
    "setpoint_entity", "write_type", "ch_entity", "ch_write_type", "hand_back",
    "hand_back_value", "hand_back_value_effect", "hand_back_entity", "hand_back_entity_write_type",
    "hand_back_timeout_min", "gateway_id", "mqtt_top", "mqtt_node", "own_room_controller",
    *RELAY_KEYS,
)  # fmt: skip
# The control section's keys that name an entity (P-19: a rename is followed there, a removal
# told).
ENTITY_KEYS = (
    "setpoint_entity", "ch_entity", "hand_back_entity", "confirmed_entity", "ch_confirmed_entity",
    "thermostat_setpoint_entity", "restart_entity", "frost_zone", "relay_entity",
)  # fmt: skip
# What a hand-back goes through: fixed while one is owed — for a relay, the relay and its rest
# state.
HAND_BACK_KEYS = (
    "setpoint_entity", "ch_entity", "hand_back", "hand_back_value", "hand_back_value_effect",
    "hand_back_entity", "hand_back_entity_write_type", "gateway_id", "mqtt_top", "mqtt_node",
    "relay_entity", "relay_rest_state",
)  # fmt: skip
# The relay's own settings unanswered: each its cautious reading (R3; provisional, K4) — its
# state report "I don't know" (blind repeats), its state after a power cut "I don't know" (maybe
# on), a timer "I don't know" (it may have one), the rest state "off", the tick not given. The
# repeat interval empty means 300 s; no power threshold means the power proves nothing.
RELAY_DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "relay_reports_state": RelayReports.UNKNOWN.value,
        "relay_power_on_state": RelayPowerOn.UNKNOWN.value,
        "relay_off_timer": RelayTimer.UNKNOWN.value,
        "relay_rest_state": RelayRest.OFF.value,
        "relay_is_separate_contact": False,
    }
)
RELAY_DOMAINS = ("switch", "climate")  # a switch, or a boiler thermostat entity (never a helper)
# A declared switch-off timer, in minutes: 10 to 120 — the shortest the plugin takes for the
# relay's own (decided by the user 2026-10-03, K4.2).
RELAY_TIMER_MIN = (TIMER_MIN_S / MINUTE, TIMER_MAX_S / MINUTE)
# The device's own timeout of the timeout hand-back, in minutes (decision 5 of 0.2.3): 1 to 60,
# and the shortest where none is stored (provisional, K4).
HAND_BACK_TIMEOUT_MIN = (DEVICE_TIMEOUT_BOUNDS_S[0] / MINUTE, DEVICE_TIMEOUT_BOUNDS_S[1] / MINUTE)
HAND_BACK_TIMEOUT_DEFAULT_MIN = DEVICE_TIMEOUT_DEFAULT_S / MINUTE
RELAY_HEATS_ABOVE_W = (10.0, 10000.0)  # the power above which the boiler counts as heating
# Boiler classes the plugin monitors only: nothing it can write controls them.
_MONITOR_ONLY_CLASSES = frozenset({BoilerClass.CURVE_ONLY, BoilerClass.READ_ONLY})
# Decision 11 (S-39; provisional until the user lifts it at K4, even where the research is
# favourable): control without a heating switch the boiler does not store is blocked — "off"
# would be a low setpoint, and whether that stops the boiler and its pump is not known. Such
# installations get the monitor. The one place that lifts the block.
OFF_AS_LOW_SETPOINT_ALLOWED = False
# A thermostatic mixing valve needs supply water above its own temperature: the boiler's flow is
# kept at least this far above a passive fixed circuit's temperature (S-42; provisional, K4).
FIXED_CIRCUIT_MARGIN_K = 5.0
# The curve's values must fit together (P-68; provisional, K4): the design flow at least this far
# above the curve's room temperature, and the design outdoor temperature at least this far below
# it.
DESIGN_FLOW_OVER_ROOM_K = 5.0
DESIGN_OUTDOOR_UNDER_ROOM_K = 10.0
# Decision 7's allow-list (S-30, S-62), the one place that says which alarms may hand back.
# Always, with no reaction to choose: an internal error and the plugin's own monitor failing for
# five minutes (runtime blockers: control hands back, and resumes once they are gone — answer I);
# the lost boiler link (X2's stale-link rule, resuming by itself; not for a relay, whose own
# alarm only informs, X8); another controller writing to the boiler, which makes the plugin step
# aside — the whole safe hand-back, then a latch (decision 6, answer H); and heating off ignored
# from the start of the session, blocked and handed back like an installation without a working
# heating switch (answer O), and so heating on ignored from the start (decision 4 of 0.2.3) and a
# relay that stops taking "off" in the session (decision 6 of 0.2.3). A stored reaction for them
# is neutralised (S-11).
ALWAYS_HAND_BACK_ALARMS = frozenset(
    {
        "control_error",
        "boiler_link_lost",
        "outside_change",
        "monitor_failed",
        "heating_off_ignored",
        "heating_on_ignored",
        "relay_off_not_taken",
    }
)
# Optional, information by default: the boiler ignoring any other write — offered only where a
# thermostat or the boiler's own control takes over (``write_ignored_offered``), never on the
# relay path.
OPTIONAL_HAND_BACK_ALARMS = frozenset({"write_ignored"})
# Every other alarm informs — every monitor alarm, a failed write, and each alarm added later
# (a new alarm informs by default): nothing the plugin counts, times or measures holds heating
# against VT (principle 12). Stopping heating for a boiler fault follows the boiler's own logic
# (boiler protection), not an alarm.
_NOT_FOR_RELAY = frozenset({"boiler_link_lost"})
# "Off" sent as a low setpoint at least this far below the lowest water temperature (P-43,
# decided): the boiler sees a change, and the guard's 0.5 K tolerance tells the two apart.
OFF_BELOW_LOWEST_K = 1.0
EXPONENT_BY_EMITTER = {
    EmitterType.RADIATOR: 1.3,
    EmitterType.CONVECTOR: 1.4,
    EmitterType.UNDERFLOOR: 1.1,
}
# "Off" sent as a low setpoint this close to a hand-back value that returns the boiler to its own
# control would hand the boiler back instead of stopping heating (S-49).
OFF_NEAR_HAND_BACK_K = 0.5
# Hand-back effects where the heating part leaves heating as it is: the hand-back stops heating —
# a relay resting "off" included (its writer goes to the rest state, never "on" otherwise).
_HEATING_LEFT_AS_IT_IS = frozenset({HandBackEffect.HEATING_STOPS, HandBackEffect.RELAY_RESTS_OFF})


@dataclass(frozen=True, slots=True)
class RelayOptions:
    """The relay path's answers (X8, R3): the relay, and its own settings as the user declared
    them — the plugin cannot read them."""

    entity: str | None = None
    reports: RelayReports = RelayReports.UNKNOWN
    power_on: RelayPowerOn = RelayPowerOn.UNKNOWN
    timer: RelayTimer = RelayTimer.UNKNOWN
    timer_min: float | None = None  # a declared length, 10–120 min
    repeat_s: float = REPEAT_DEFAULT_S
    rest: RelayRest = RelayRest.OFF
    heats_above_w: float | None = None  # None: the boiler's power proves nothing
    separate_contact: bool = False  # answer G: control does not start without it

    @property
    def config(self) -> RelayConfig:
        """The relay rule's settings."""
        timer_s = None if self.timer_min is None else self.timer_min * MINUTE
        return RelayConfig(self.reports, self.power_on, self.timer, timer_s, self.repeat_s)

    @property
    def rests_on(self) -> bool:
        return self.rest is RelayRest.ON


@dataclass(frozen=True, slots=True)
class ControlOptions:
    write_path: WritePath | None = None
    setpoint_entity: str | None = None
    ch_entity: str | None = None
    write_type: WriteType = WriteType.UNKNOWN
    ch_write_type: WriteType = WriteType.UNKNOWN
    hand_back: HandBack | None = None
    hand_back_value: float | None = None  # never assumed: 0 means different things on devices
    hand_back_value_effect: ValueEffect | None = None
    hand_back_entity: str | None = None
    # What the device does with the external-control switch (P-40): never assumed.
    hand_back_entity_write_type: WriteType = WriteType.UNKNOWN
    # The timeout method: the device's own timeout, after which it lets go of the last value it
    # was given — the release is judged from it, and the alarm comes three minutes after it.
    hand_back_timeout_s: float = DEVICE_TIMEOUT_DEFAULT_S
    gateway_id: str | None = None
    mqtt_top: str | None = None
    mqtt_node: str | None = None
    confirmed_entity: str | None = None
    ch_confirmed_entity: str | None = None  # echoes heating on/off as the boiler gets it
    topology: Topology | None = None
    # What is wired to the gateway's thermostat terminals (decision 1); ``None``: no answer
    # stored, or one this version cannot read. Only a gateway topology reads it.
    thermostat_kind: ThermostatKind | None = None
    curve_entered: bool = False
    loop: LoopConfig = field(default_factory=lambda: LoopConfig(ControlConfig(HeatingCurve())))
    learning: LearningConfig = field(default_factory=LearningConfig)
    learning_pauses: bool = True
    alarm_reactions: Mapping[str, AlarmReaction] = field(default_factory=dict)
    # After stepping aside from another controller, take the boiler back by itself once nothing
    # else wrote for an hour (decision 6; off by default, confirmed twice; not for relays).
    return_after_outside_change: bool = False
    # With an OpenTherm thermostat on a gateway: the thermostat's own requested water setpoint,
    # which a fall-back after an outage shows (a lost command, not another controller).
    thermostat_setpoint_entity: str | None = None
    # A sensor that shows the gateway's or device's restarts — an uptime starting again, a restart
    # counter going up, a boot time moving — a trace of an outage (Q3.7; none by default).
    restart_entity: str | None = None
    # "The boiler has its own room controller" (answers F, M): with every zone unknown, the
    # boiler is handed back to it; not ticked by default. It counts only where it is offered.
    own_room_controller: bool = False
    relay: RelayOptions = field(default_factory=RelayOptions)  # the relay path (X8)

    @property
    def configured(self) -> bool:
        return self.write_path is not None

    def reaction(self, alarm: str) -> AlarmReaction:
        """What an active alarm does (decision 7): the allow-list's fixed hand-backs; the user's
        choice for an ignored write, where it is offered; information for anything else,
        whatever is stored — this is how stored reactions no longer allowed are neutralised."""
        relay = self.write_path is WritePath.RELAY
        if alarm in ALWAYS_HAND_BACK_ALARMS and not (relay and alarm in _NOT_FOR_RELAY):
            return AlarmReaction.HAND_BACK
        if alarm in OPTIONAL_HAND_BACK_ALARMS and _write_ignored_offered(self):
            return self.alarm_reactions.get(alarm, AlarmReaction.INFO)
        return AlarmReaction.INFO

    @property
    def entities(self) -> tuple[str, ...]:
        """Entities the control part reads (read-back) or writes."""
        found = (
            self.setpoint_entity,
            self.ch_entity,
            self.hand_back_entity,
            self.confirmed_entity,
            self.ch_confirmed_entity,
            self.thermostat_setpoint_entity,
            self.restart_entity,
            self.relay.entity,
        )
        return tuple(e for e in found if e)


def map_control_entities(
    section: Mapping[str, Any], visit: Callable[[str, str], str]
) -> dict[str, Any]:
    """A control section — the options' own, or one stored with the control state ("taken
    with") — rebuilt with ``visit(key, entity)`` for every entity it names (``ENTITY_KEYS``);
    everything else as it is."""
    result = dict(section)
    for key in ENTITY_KEYS:
        entity = section.get(key)
        if isinstance(entity, str) and entity:
            result[key] = visit(key, entity)
    return result


def rename_in_control(section: Mapping[str, Any], old: str, new: str) -> dict[str, Any]:
    """A control section with the entity ``old`` renamed ``new`` wherever it names it (P-19)."""
    return map_control_entities(section, lambda _key, entity: new if entity == old else entity)


def _float(data: Mapping[str, Any], key: str, default: float | None) -> float | None:
    value = data.get(key, default)
    if value is None or value == "":
        return None
    return float(value)


def _minutes(data: Mapping[str, Any], key: str, default_min: float) -> float:
    value = _float(data, key, default_min)
    return (default_min if value is None else value) * MINUTE


def _number(raw: object) -> float | None:
    """A stored number, finite; anything else — text, a flag, nothing — ``None``."""
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _within(raw: object, bounds: tuple[float, float]) -> float | None:
    value = _number(raw)
    low, high = bounds
    return value if value is not None and low <= value <= high else None


def _hand_back_timeout_s(data: Mapping[str, Any]) -> float:
    """The device's own timeout of the timeout hand-back, in seconds. None stored — an entry
    from before the field — or one outside 1 to 60 min (a hand edit): the shortest, 1 min, so
    "hand-back failed" comes rather too early than too late (decision 5 of 0.2.3; provisional,
    K4). One outside the bounds is logged."""
    raw = data.get("hand_back_timeout_min")
    minutes = _within(raw, HAND_BACK_TIMEOUT_MIN)
    if minutes is None:
        if raw not in (None, "") and data.get("hand_back") == HandBack.TIMEOUT:
            _LOGGER.warning(
                "The device's timeout of %r min is outside 1 to 60 min: read as 1 min", raw
            )
        return DEVICE_TIMEOUT_DEFAULT_S
    return minutes * MINUTE


def parse_relay(data: Mapping[str, Any]) -> RelayOptions:
    """The relay's answers, each unanswered one with its cautious default (R3). A choice this
    version does not know raises ``ValueError`` (P-70); hand-edited numbers outside their range
    are read cautiously: a declared timer without a valid length as "I don't know" — one given
    outside 10–120 min (below 10, K4.2) logged — a repeat interval outside 10–300 s as 300 s, a
    power threshold outside 10–10000 W as none."""
    value = {**RELAY_DEFAULTS, **{k: v for k, v in data.items() if v not in (None, "")}}
    timer = RelayTimer(value["relay_off_timer"])
    raw_min = data.get("relay_off_timer_min")
    timer_min = _within(raw_min, RELAY_TIMER_MIN)
    if timer is RelayTimer.MINUTES and timer_min is None and raw_min not in (None, ""):
        _LOGGER.warning(
            "The declared relay switch-off timer of %r min is outside 10 to 120 min: read as "
            "unknown — 'on' repeated, and its switch-offs counted toward stepping aside",
            raw_min,
        )
    if timer is not RelayTimer.MINUTES or timer_min is None:
        timer = RelayTimer.UNKNOWN if timer is RelayTimer.MINUTES else timer
        timer_min = None
    repeat = _within(data.get("relay_repeat_s"), (REPEAT_MIN_S, REPEAT_MAX_S))
    return RelayOptions(
        entity=data.get("relay_entity") or None,
        reports=RelayReports(value["relay_reports_state"]),
        power_on=RelayPowerOn(value["relay_power_on_state"]),
        timer=timer,
        timer_min=timer_min,
        repeat_s=REPEAT_DEFAULT_S if repeat is None else repeat,
        rest=RelayRest(value["relay_rest_state"]),
        heats_above_w=_within(data.get("boiler_heats_above_w"), RELAY_HEATS_ABOVE_W),
        separate_contact=data.get("relay_is_separate_contact") is True,
    )


def parse_thermostat_kind(raw: object) -> ThermostatKind | None:
    """A stored answer to the thermostat-terminals question; ``None`` for no answer or one this
    version cannot read — never an exception: such an entry is blocked and asked again."""
    if not isinstance(raw, str):
        return None
    try:
        return ThermostatKind(raw)
    except ValueError:
        return None


def parse_control(
    data: Mapping[str, Any] | None, installation: Installation, boiler_max: float | None
) -> ControlOptions:
    """The control options; an empty section means control is not configured."""
    data = data or {}
    if not data.get("write_path"):
        return ControlOptions()
    path = WritePath(data["write_path"])
    curve_data = data.get("curve") or {}
    circuit = installation.circuits[0] if installation.circuits else None
    emitters = installation.emitters_in(circuit.circuit_id) if circuit is not None else frozenset()
    default_exponent = min((EXPONENT_BY_EMITTER[e] for e in emitters), default=1.3)
    curve_value = {**CURVE_DEFAULTS, **curve_data}
    curve = HeatingCurve(
        design_outdoor=float(curve_value["design_outdoor"]),
        design_flow=float(curve_value["design_flow"]),
        room=float(curve_value["room"]),
        exponent=float(curve_data.get("exponent", default_exponent)),
        offset=float(curve_value["offset"]),
    )
    value = {**CONTROL_DEFAULTS, **{k: v for k, v in data.items() if v is not None}}
    relay = parse_relay(data) if path is WritePath.RELAY else RelayOptions()
    on_off = path is WritePath.RELAY
    if on_off:
        # Nothing is written but the relay: no write type to declare.
        write_type = ch_write_type = WriteType.UNKNOWN
    elif path in OTGW_PATHS:
        # CS lapses unless repeated within a minute; the PIC keeps CH= until CH=1 or a reset —
        # held, not stored, so the heating switch stays in use (X6).
        write_type = WriteType.EXPIRING
        ch_write_type = WriteType.HELD
    else:
        write_type = WriteType(data.get("write_type", WriteType.UNKNOWN))
        ch_write_type = WriteType(data.get("ch_write_type", WriteType.UNKNOWN))
    circuit_max = circuit.max_flow if circuit is not None else None
    circuit_floor = None
    if (
        circuit is not None
        and circuit.control is CircuitControl.PASSIVE_FIXED
        and circuit.fixed_temperature is not None
    ):
        # The mixing valve needs supply water above its own temperature (S-42); a maximum the
        # user declared still applies, and wins.
        circuit_floor = circuit.fixed_temperature + FIXED_CIRCUIT_MARGIN_K
    ramp = _float(value, "ramp_k_per_min", None)
    frost_zone = data.get("frost_zone") or None
    control = ControlConfig(
        curve=curve,
        limits=FlowLimits(
            hard_min=float(value["hard_min"]),
            hard_max=float(value["hard_max"]),
            ceiling_band=float(value["ceiling_band"]),
        ),
        circuit_max=circuit_max,
        boiler_max=boiler_max,
        circuit_floor=circuit_floor,
        frost=FrostConfig(
            room_limit=float(value["frost_limit"]),
            release=float(value["frost_release"]),
            # A zone no longer configured must not leave frost protection watching nothing.
            zone=frost_zone if frost_zone in {z.zone_id for z in installation.zones} else None,
            closes_when_off=frozenset(z.zone_id for z in installation.zones if z.closes_when_off),
        ),
        demand=DemandConfig(
            count_threshold=int(value["count_threshold"]),
            power_threshold_kw=_float(data, "power_threshold_kw", None),
            opening_threshold=(
                None
                if (opening := _float(data, "opening_threshold", None)) is None
                else opening / 100.0
            ),
        ),
        fallback_setpoint=_float(data, "fallback_setpoint", None),
        ramp_k_per_min=None if on_off else ramp,
        decision_interval_s=_minutes(value, "decision_interval_min", 5.0),
        # The relay sets no water temperature: nothing to correct (R5).
        comfort_correction=bool(value["comfort_correction"]) and not on_off,
        # Only what the user saved: VT's own value is a pre-fill in the form, never taken here.
        activation_delay_s=float(value["activation_delay_s"]),
        # The relay path (R5, R6): heating on and off only, and its link is the relay itself —
        # never a hand-back for the boiler's signals, which never gate it.
        on_off=on_off,
        stale_hand_back_s=None if on_off else OUTAGE_LOST_S,
    )
    loop = LoopConfig(
        control=control,
        setpoint_guard=GuardConfig(write_type=write_type, keepalive_s=KEEPALIVE_S),
        switch_guard=GuardConfig(
            # An expiring heating switch is repeated with the setpoint's keep-alive; a held one is
            # sent on a change, when it returns and every 5 minutes — the OTGW's CH= with every
            # keep-alive instead. Without an echo, heating on/off is never judged, only shown
            # unverified.
            write_type=ch_write_type,
            keepalive_s=KEEPALIVE_S,
            read_back=bool(data.get("ch_confirmed_entity")),
            two_valued=True,
            refresh_s=OTGW_CH_REFRESH_S if path in OTGW_PATHS else HELD_REFRESH_S,
        ),
        # A heating switch the boiler may store is left alone: "off" is then a low setpoint.
        ch_writes=not on_off
        and (
            path in OTGW_PATHS or (bool(data.get("ch_entity")) and ch_write_type in WRITABLE_TYPES)
        ),
        off_setpoint=float(value["off_setpoint"]),
        relay=relay.config if on_off else None,
    )
    reactions = {
        str(alarm): AlarmReaction(reaction)
        for alarm, reaction in (data.get("alarm_reactions") or {}).items()
        # Only the optional reaction is kept; a fixed one leaves nothing to choose, and any other
        # is no longer offered — a stored one is neutralised, whatever it holds (S-11, S-30).
        if str(alarm) in OPTIONAL_HAND_BACK_ALARMS and not on_off
    }
    options = ControlOptions(
        write_path=path,
        setpoint_entity=data.get("setpoint_entity") or None,
        ch_entity=data.get("ch_entity") or None,
        write_type=write_type,
        ch_write_type=ch_write_type,
        hand_back=HandBack(data["hand_back"]) if data.get("hand_back") else None,
        hand_back_value=_float(data, "hand_back_value", None),
        hand_back_value_effect=(
            ValueEffect(data["hand_back_value_effect"])
            if data.get("hand_back_value_effect")
            else None
        ),
        hand_back_entity=data.get("hand_back_entity") or None,
        hand_back_entity_write_type=WriteType(
            data.get("hand_back_entity_write_type") or WriteType.UNKNOWN
        ),
        hand_back_timeout_s=_hand_back_timeout_s(data),
        gateway_id=data.get("gateway_id") or None,
        mqtt_top=data.get("mqtt_top") or None,
        mqtt_node=data.get("mqtt_node") or None,
        confirmed_entity=data.get("confirmed_entity") or None,
        ch_confirmed_entity=data.get("ch_confirmed_entity") or None,
        topology=Topology(data["topology"]) if data.get("topology") else None,
        thermostat_kind=parse_thermostat_kind(data.get("thermostat_kind")),
        curve_entered=bool(curve_data.get("design_flow")),
        loop=loop,
        # R13: no water swing on a relay — it sets no water temperature.
        learning=LearningConfig(pause_on_water_swing=not on_off),
        learning_pauses=bool(value["learning_pauses"]),
        alarm_reactions=reactions,
        # Decision 6: the return by itself is not offered for relays.
        return_after_outside_change=data.get("return_after_outside_change") is True and not on_off,
        thermostat_setpoint_entity=data.get("thermostat_setpoint_entity") or None,
        restart_entity=data.get("restart_entity") or None,
        own_room_controller=data.get("own_room_controller") is True,
        relay=relay,
    )
    working = replace(loop.control, working_thermostat=working_thermostat(options))
    return replace(options, loop=replace(loop, control=working))


def own_room_controller_offered(path: WritePath | None, topology: Topology | None) -> bool:
    """Where the tick "the boiler has its own room controller" is offered (answers F, M): the
    entity path with the virtual topology — with a gateway the thermostat on its terminals
    already counts, and with nothing on them a hand-back stops heating anyway — and the relay
    path, where the tick counts only with the rest state "on" (``relay_working_thermostat``)."""
    if path is WritePath.RELAY:
        return True
    return path is WritePath.ENTITY and topology is Topology.VIRTUAL


def own_room_controller_counts(control: ControlOptions) -> bool:
    """The tick counts: stored where it is offered, and with a hand-back that leaves the boiler
    heating — with a hand-back value declared "heating stops" (refused in the form) there is
    nothing for the controller to take over; on the relay path only with the rest state "on"
    (answer M). A tick stored anywhere else is ignored."""
    if not control.own_room_controller:
        return False
    if control.write_path is WritePath.RELAY:
        return relay_working_thermostat(ticked=True, rests_on=control.relay.rests_on)
    if not own_room_controller_offered(control.write_path, control.topology):
        return False
    return not (
        control.hand_back is HandBack.VALUE
        and control.hand_back_value_effect is ValueEffect.HEATING_STOPS
    )


def relay_working_thermostat(*, ticked: bool, rests_on: bool) -> bool:
    """Answer M, for the relay path (X8): the tick counts as a working thermostat only where
    the relay rests "on" — the relay is the boiler's heat-demand contact, so the boiler's own
    room controller then heats; with the rest state "off" nothing would. A relay resting "on"
    without the tick is no working thermostat either."""
    return ticked and rests_on


def working_thermostat(control: ControlOptions) -> bool:
    """Decision 3 (answers F, M): with every zone unknown, is there something to hand the boiler
    to that heats by the rooms? A gateway with an OpenTherm thermostat declared on its
    terminals, or the boiler's own room controller where the tick counts. Not a hand-back value
    declared "own control" without the tick — its effect is "own control resumes" (Y1), but
    nothing says a room controller heats by the rooms then — nor "device decides", nor a
    stand-alone gateway, nor a gateway whose terminals hold something else or were not answered
    for. On the relay path the tick itself is read, with the rest state (answer M): its hand-back
    effect is the rest state either way."""
    if control.write_path is WritePath.RELAY:
        return own_room_controller_counts(control)
    if hand_back_effect(control) is HandBackEffect.THERMOSTAT_TAKES_OVER:
        return control.thermostat_kind is ThermostatKind.OPENTHERM
    return own_room_controller_counts(control)


def _write_ignored_offered(control: ControlOptions) -> bool:
    """Decision 7: the reaction to an ignored write is offered where a hand-back returns the
    boiler to a thermostat — an OpenTherm thermostat declared on the gateway's terminals — or to
    the boiler's own control; never stand-alone, with an undeclared effect ("device decides"),
    or on the relay path, whatever its rest state (X8: an ignored relay command informs)."""
    if control.write_path is WritePath.RELAY:
        return False
    effect = hand_back_effect(control)
    if effect is HandBackEffect.THERMOSTAT_TAKES_OVER:
        return control.thermostat_kind is ThermostatKind.OPENTHERM
    return effect is HandBackEffect.OWN_CONTROL_RESUMES


def migrated_reactions(control: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Y1's entry migration of the stored alarm reactions: only the one decision 7 still
    offers stays — an ignored write's, where it is offered; and the names of those that were
    set to hand back and now only inform (the fixed hand-backs are not among them)."""
    stored = control.get("alarm_reactions")
    if not isinstance(stored, Mapping):
        return {}, []
    offered = write_ignored_offered(control)
    kept: dict[str, Any] = {}
    removed: list[str] = []
    for alarm, reaction in stored.items():
        name = str(alarm)
        if name in OPTIONAL_HAND_BACK_ALARMS and offered:
            kept[name] = reaction
        elif reaction == AlarmReaction.HAND_BACK.value and name not in ALWAYS_HAND_BACK_ALARMS:
            removed.append(name)
    return kept, sorted(removed)


def write_ignored_offered(data: Mapping[str, Any] | None) -> bool:
    """The form's question, from a stored control section: is the reaction to an ignored write
    offered? A section that cannot be read offers nothing."""
    if not isinstance(data, Mapping):
        return False
    try:
        path = WritePath(str(data["write_path"]))
        control = ControlOptions(
            write_path=path,
            hand_back=HandBack(data["hand_back"]) if data.get("hand_back") else None,
            hand_back_value_effect=(
                ValueEffect(data["hand_back_value_effect"])
                if data.get("hand_back_value_effect")
                else None
            ),
            topology=Topology(data["topology"]) if data.get("topology") else None,
            thermostat_kind=parse_thermostat_kind(data.get("thermostat_kind")),
            own_room_controller=data.get("own_room_controller") is True,
        )
    except KeyError, TypeError, ValueError:
        return False
    return _write_ignored_offered(control)


def thermostat_kind_blocker(control: ControlOptions) -> str | None:
    """Decision 1 (S-01): what the answer about the gateway's thermostat terminals blocks, on a
    gateway topology — an on/off contact (the gateway's ``CH=0`` would mask it after a crash),
    "I don't know" or no answer (answer K), or an answer the topology contradicts. ``None``
    where it allows control, or without a gateway topology."""
    topology = control.topology
    if topology is None or topology not in GATEWAY_TOPOLOGIES:
        return None
    kind = control.thermostat_kind
    if kind is None or kind is ThermostatKind.UNKNOWN:
        return "thermostat_kind_unknown"
    if kind is ThermostatKind.ON_OFF:
        return "thermostat_on_off"
    if kind_contradicts_topology(topology, kind):
        return "thermostat_kind_contradicts_topology"
    return None


def kind_contradicts_topology(topology: Topology, kind: ThermostatKind) -> bool:
    """An OpenTherm thermostat with stand-alone, nothing with a thermostat (the form's check)."""
    return _CONTRADICTING_KIND.get(topology) is kind


def thermostat_kind_missing(control: ControlOptions) -> bool:
    """A gateway entry without an answer to the thermostat-terminals question — made before
    0.2.2, or holding one this version cannot read: control stays stopped, and a notice asks for
    the answer (answer K). An explicit "I don't know" is an answer."""
    return (
        control.configured
        and control.topology in GATEWAY_TOPOLOGIES
        and control.thermostat_kind is None
    )


def wall_thermostat_applies(control: ControlOptions) -> bool:
    """Whether the wall thermostat's fallback is shown: a gateway with an OpenTherm thermostat
    declared on its terminals — after a hand-back it heats by its own setting."""
    return (
        control.configured
        and control.topology is Topology.GATEWAY_WITH_THERMOSTAT
        and control.thermostat_kind is ThermostatKind.OPENTHERM
    )


def hand_back_effect(control: ControlOptions) -> HandBackEffect | None:
    """The effect of a hand-back: a relay's rest state (X8, R9); the boiler's own room controller
    where the user ticked it (and it counts); for a hand-back value, what the user declared it
    does — "own control" is its own effect (Y1); else what the declared topology leads to.
    ``None`` where control cannot run."""
    if control.write_path is WritePath.RELAY:
        if control.relay.rests_on:
            return HandBackEffect.RELAY_RESTS_ON
        return HandBackEffect.RELAY_RESTS_OFF
    if own_room_controller_counts(control):
        return HandBackEffect.OWN_CONTROL_RESUMES
    if control.hand_back is HandBack.VALUE and control.hand_back_value_effect is not None:
        if control.hand_back_value_effect is ValueEffect.HEATING_STOPS:
            return HandBackEffect.HEATING_STOPS
        return HandBackEffect.OWN_CONTROL_RESUMES
    return (
        {
            Topology.GATEWAY_WITH_THERMOSTAT: HandBackEffect.THERMOSTAT_TAKES_OVER,
            Topology.GATEWAY_STANDALONE: HandBackEffect.HEATING_STOPS,
            Topology.VIRTUAL: HandBackEffect.DEVICE_DECIDES,
        }.get(control.topology)
        if control.topology is not None
        else None
    )


# Where nothing heats the house once control lets go.
_STOPS_HEATING = frozenset({HandBackEffect.HEATING_STOPS, HandBackEffect.RELAY_RESTS_OFF})


def hand_back_stops_heating(control: ControlOptions) -> bool | None:
    """A hand-back stops heating: nothing heats the house once control lets go — a relay resting
    "off" included, unless a thermostat in parallel heats (X8). ``None`` where control cannot
    run, so no effect is known."""
    effect = hand_back_effect(control)
    return None if effect is None else effect in _STOPS_HEATING


def _stored_section(data: object) -> ControlOptions | None:
    """A stored control section as options; ``None`` where it cannot be read. The effect of a
    hand-back needs the section alone, so a bare installation stands in for one that may not be
    readable."""
    if not isinstance(data, Mapping):
        return None
    try:
        return parse_control(data, Installation(Boiler(BoilerClass.READ_ONLY), ()), None)
    except Exception:  # whatever cannot be read tells nothing
        return None


def section_stops_heating(data: object) -> bool | None:
    """Whether a hand-back through a stored control section — the options', or those the control
    was taken with — stops heating; ``None`` where it holds no control or cannot be read."""
    control = _stored_section(data)
    if control is None or not control.configured:
        return None
    return hand_back_stops_heating(control)


def section_monitors_only(data: object) -> bool:
    """A stored control section whose topology allows no control — ``monitor_mode``, refused by
    today's form, so old data only: the plugin never takes the boiler with it."""
    control = _stored_section(data)
    return control is not None and control.topology is Topology.MONITOR_MODE


class FailedSetupReport(StrEnum):
    """What a setup that fails tells of the house (SB-10): its repair issue's translation key."""

    NOT_HEATED = "setup_failed_not_heated"
    MAY_NOT_BE_HEATED = "setup_failed_may_not_be_heated"


def failed_setup_report(
    options: object, state: Mapping[str, Any] | None
) -> FailedSetupReport | None:
    """SB-10 (decision 12): a setup that failed, where a hand-back stops heating — by the
    options' control section where it can be read, else by the options the control was taken
    with (``taken_with`` in the stored control state ``state``; ``None`` where it could not be
    read) — and the stored wish is not a clear "off": the plugin did not start and the house is
    not heated. A wish never stored or unreadable counts as "on" (the cautious side). Where
    neither section tells what a hand-back does, the house may not be heated. Nothing where the
    options hold no control section — a setup that worked would not heat either — or the
    hand-back leaves heating to a thermostat or the boiler's own control; nor where the options'
    section only monitors and the stored state shows no session holding the boiler: the plugin
    never takes it there (finding 6 of the part-1 check D)."""
    if not isinstance(options, Mapping) or not has_control_section(options):
        return None
    if state is not None and state.get("enabled") is False:
        return None
    section = options[CONTROL]
    stops = section_stops_heating(section)
    if stops is None and state is not None:
        taken_with = state.get("taken_with")
        stops = section_stops_heating(taken_with)
        if stops is None and taken_with is None and section_monitors_only(section):
            return None
    if stops is False:
        return None
    return FailedSetupReport.NOT_HEATED if stops else FailedSetupReport.MAY_NOT_BE_HEATED


class FrostProtection(StrEnum):
    """Who keeps frost protection now (S-57), as the control switch shows it."""

    PLUGIN = "plugin"  # the session controls: the plugin's own frost protection
    THERMOSTAT = "thermostat"  # handed back to the thermostat
    BOILER = "boiler"  # a hand-back stops heating: the boiler's own, if it has one
    DEVICE = "device"  # the boiler's or the device's own control


_FROST_PROTECTION_AFTER = {
    HandBackEffect.THERMOSTAT_TAKES_OVER: FrostProtection.THERMOSTAT,
    HandBackEffect.HEATING_STOPS: FrostProtection.BOILER,
    HandBackEffect.DEVICE_DECIDES: FrostProtection.DEVICE,
    HandBackEffect.OWN_CONTROL_RESUMES: FrostProtection.DEVICE,
    # A relay resting "off": the boiler's own, if it has one (or a thermostat in parallel); one
    # resting "on": the boiler's own control.
    HandBackEffect.RELAY_RESTS_OFF: FrostProtection.BOILER,
    HandBackEffect.RELAY_RESTS_ON: FrostProtection.DEVICE,
}


def frost_protection_by(control: ControlOptions, controlling: bool) -> FrostProtection | None:
    """S-57: the plugin while its session controls; otherwise whoever the hand-back's effect
    leaves the boiler with. ``None`` where the effect is not known (control cannot run)."""
    if controlling:
        return FrostProtection.PLUGIN
    effect = hand_back_effect(control)
    return None if effect is None else _FROST_PROTECTION_AFTER[effect]


def hand_back_heating_on(control: ControlOptions) -> bool:
    """The safe hand-back's heating part (S-27): a heating switch goes back on where the boiler
    returns to a thermostat or its own control ("thermostat takes over", "device decides", and
    "own control resumes", the user's tick), and is left as it is where the hand-back stops
    heating. An effect not known turns it on: missing data never switches heating off by
    itself. A relay goes to its rest state: on only where the user chose "on"."""
    return hand_back_effect(control) not in _HEATING_LEFT_AS_IT_IS


def highest_water_temperature(control: ControlConfig) -> float:
    """The highest water temperature control may write: the hard maximum, and the circuit's and
    the boiler's where they are set."""
    return min(
        value
        for value in (control.limits.hard_max, control.circuit_max, control.boiler_max)
        if value is not None
    )


def hand_back_value_above_max(value: float | None, highest: float) -> bool:
    """S-21: the hand-back value is exempt only from the lowest water temperature."""
    return value is not None and value > highest


def off_near_hand_back_value(off_setpoint: float, hand_back_value: float | None) -> bool:
    """S-49: "off" this close to the hand-back value would read as the hand-back."""
    return hand_back_value is not None and abs(off_setpoint - hand_back_value) <= (
        OFF_NEAR_HAND_BACK_K
    )


def hand_back_value_problems(control: ControlOptions) -> list[str]:
    """What makes a hand-back value unsafe (translation keys), the form's check and a blocker
    alike: above the highest water temperature (S-21) — it is never clamped, as a clamped value
    would mean something else to the device; and "off" sent as a low setpoint within half a
    kelvin of a value that returns the boiler to its own control (S-49)."""
    if control.hand_back is not HandBack.VALUE or control.hand_back_value is None:
        return []
    found: list[str] = []
    highest = highest_water_temperature(control.loop.control)
    if hand_back_value_above_max(control.hand_back_value, highest):
        found.append("hand_back_value_above_max")
    if (
        not control.loop.ch_writes
        and control.hand_back_value_effect is ValueEffect.OWN_CONTROL
        and off_near_hand_back_value(control.loop.off_setpoint, control.hand_back_value)
    ):
        found.append("off_setpoint_near_hand_back_value")
    return found


def heating_writes(data: Mapping[str, Any]) -> bool:
    """Whether stored control options switch heating with a heating switch — the gateway paths
    always, with CH; the entity path with a heating switch declared expiring or held — rather
    than sending "off" as a low setpoint. A write type this version does not know counts as
    none. The relay switches heating itself (X8)."""
    if data.get("write_path") in (*OTGW_PATHS, WritePath.RELAY):
        return True
    try:
        ch_write_type = WriteType(data.get("ch_write_type") or WriteType.UNKNOWN)
    except ValueError:
        return False
    return bool(data.get("ch_entity")) and ch_write_type in WRITABLE_TYPES


def _roles(control: ControlOptions) -> list[str]:
    """The entities control writes to, one per role in use: the setpoint entity, the heating
    switch (whatever its write type: declared as the heating switch, it is that), and the
    external-control switch where the hand-back uses it."""
    found = [control.setpoint_entity, control.ch_entity]
    if control.hand_back is HandBack.SWITCH:
        found.append(control.hand_back_entity)
    return [entity for entity in found if entity]


def one_entity_in_two_roles(control: ControlOptions) -> bool:
    """X5.1 (P-03): one entity picked for two roles — the heating switch as the external-control
    switch, say — would be switched on and off by every hand-back for ever. A role left empty is
    no duplicate."""
    roles = _roles(control)
    return len(roles) != len(set(roles))


def curve_problems(
    design_flow: float | None,
    design_outdoor: float,
    room: float,
    hard_min: float,
    hard_max: float,
) -> list[tuple[str, str]]:
    """X5.8 (P-68; provisional, K4): what does not fit together in the curve and its limits, as
    (field, translation key) in the form's order. The design flow at least
    ``DESIGN_FLOW_OVER_ROOM_K`` above the curve's room temperature, and not above the highest
    water temperature — the curve would be cut off in frost; the design outdoor temperature at
    least ``DESIGN_OUTDOOR_UNDER_ROOM_K`` below the room; the lowest water temperature below the
    design flow. Nothing is checked before a design flow is entered ("curve_not_entered")."""
    if design_flow is None:
        return []
    found: list[tuple[str, str]] = []
    if design_flow < room + DESIGN_FLOW_OVER_ROOM_K:
        found.append(("design_flow", "design_flow_too_low"))
    if design_flow > hard_max:
        found.append(("design_flow", "design_flow_above_hard_max"))
    if design_outdoor > room - DESIGN_OUTDOOR_UNDER_ROOM_K:
        found.append(("design_outdoor", "design_outdoor_too_warm"))
    if hard_min >= design_flow:
        found.append(("hard_min", "hard_min_not_below_design_flow"))
    return found


def relay_in_another_role(
    control: ControlOptions, signals: Collection[Signal] | Mapping[Signal, str] | None = None
) -> bool:
    """R2: the relay is an entity the options already use in another role — one control reads
    or writes, or a mapped signal (``signals``, where given as their entities)."""
    entity = control.relay.entity
    if not entity:
        return False
    others = [
        e
        for e in (
            control.setpoint_entity,
            control.ch_entity,
            control.hand_back_entity,
            control.confirmed_entity,
            control.ch_confirmed_entity,
            control.thermostat_setpoint_entity,
            control.restart_entity,
        )
        if e
    ]
    if isinstance(signals, Mapping):
        others += [str(e) for e in signals.values()]
    return entity in others


def relay_blockers(
    control: ControlOptions, signals: Collection[Signal] | Mapping[Signal, str] | None = None
) -> list[str]:
    """What the relay path lacks (R1–R3): the relay, a switch or a boiler thermostat entity used
    in no other role, and the separate-contact tick (answer G)."""
    found: list[str] = []
    entity = control.relay.entity
    if not entity:
        found.append("no_relay_entity")
    elif entity.split(".", 1)[0] not in RELAY_DOMAINS:
        found.append("relay_domain_not_supported")
    elif relay_in_another_role(control, signals):
        found.append("relay_in_another_role")
    if not control.relay.separate_contact:
        found.append("relay_contact_not_confirmed")
    return found


def _zone_blockers(control: ControlOptions, installation: Installation) -> list[str]:
    if not installation.zones:
        return ["no_zones"]  # nothing could ever ask for heat (S-04)
    if control.loop.control.demand.count_threshold > len(installation.zones):
        return ["count_threshold_above_zones"]  # heating would never be asked for
    return []


def config_blockers(
    control: ControlOptions,
    installation: Installation,
    shared_signals: Mapping[Signal, Signal] | None = None,
    *,
    signals: Collection[Signal] | Mapping[Signal, str] | None = None,
) -> list[str]:
    """What the configuration still lacks for control (translation keys). ``shared_signals``:
    signals dropped because their entity feeds an earlier one (``EntryConfig.shared_signals``,
    X5.2). ``signals``: the mapped signals (``EntryConfig.signals``) — water-temperature control
    needs flame and flow among them (X8); ``None``: not given here, not checked. The order is
    the one the table in ``tests/test_control_config.py`` pins (P-115)."""
    if not control.configured:
        return ["no_write_path"]
    found = _class_blockers(control, installation, shared_signals)
    if control.write_path is WritePath.RELAY:
        # The relay sets no water temperature: the setpoint, topology, read-back, curve and
        # circuit rules do not apply; the demand thresholds do (R1).
        return [*found, *relay_blockers(control, signals), *_zone_blockers(control, installation)]
    return [
        *found,
        *_signal_blockers(signals),
        *_target_blockers(control),
        *_topology_blockers(control),
        *_curve_blockers(control),
        *_circuit_blockers(installation),
        *_zone_blockers(control, installation),
        *_off_blockers(control),
    ]


def _class_blockers(
    control: ControlOptions,
    installation: Installation,
    shared_signals: Mapping[Signal, Signal] | None,
) -> list[str]:
    """A boiler class the path cannot control, and one entity feeding two signals."""
    found: list[str] = []
    boiler_class = installation.boiler.boiler_class
    if boiler_class in _MONITOR_ONLY_CLASSES:
        found.append("boiler_class_no_control")
    elif (control.write_path is WritePath.RELAY) != (boiler_class is BoilerClass.ON_OFF):
        found.append("path_not_for_boiler_class")
    if shared_signals:
        found.append("entity_for_two_signals")
    return found


def _signal_blockers(signals: Collection[Signal] | Mapping[Signal, str] | None) -> list[str]:
    """Water-temperature control needs flame and flow mapped (X8); not checked without them."""
    if signals is None:
        return []
    found: list[str] = []
    if Signal.FLAME not in signals:
        found.append("no_flame_signal")
    if Signal.FLOW not in signals:
        found.append("no_flow_signal")
    return found


def _target_blockers(control: ControlOptions) -> list[str]:
    """What the writes go to and what reads them back: one entity in two roles, the path's own
    target — the entity path's setpoint entity, heating switch and hand-back, the gateway, the
    firmware's topics — and the confirmed setpoint."""
    found: list[str] = []
    if one_entity_in_two_roles(control):
        found.append("hand_back_switch_is_heating_switch")
    path = control.write_path
    if path is WritePath.ENTITY:
        found += _entity_path_blockers(control)
    elif path is WritePath.OPENTHERM_GW and not control.gateway_id:
        found.append("no_gateway")
    elif path is WritePath.OTGW_MQTT and not (control.mqtt_top and control.mqtt_node):
        found.append("no_mqtt_topic")
    if not control.confirmed_entity:
        found.append("no_confirmed_setpoint")
    return found


def _entity_path_blockers(control: ControlOptions) -> list[str]:
    """The entity path: its setpoint entity and write type, a heating switch (decision 11) and
    a hand-back that is known and does not wear the boiler's memory."""
    found: list[str] = []
    if not control.setpoint_entity:
        found.append("no_setpoint_entity")
    if control.write_type not in WRITABLE_TYPES:
        found.append("write_type_not_supported")
    if not control.loop.ch_writes and not OFF_AS_LOW_SETPOINT_ALLOWED:
        found.append("no_heating_switch")  # decision 11: the monitor only, until K4
    if (
        control.hand_back is None
        or (control.hand_back is HandBack.SWITCH and not control.hand_back_entity)
        or (
            control.hand_back is HandBack.VALUE
            and (control.hand_back_value is None or control.hand_back_value_effect is None)
        )
    ):
        found.append("no_hand_back")
    elif control.hand_back is HandBack.TIMEOUT and control.write_type is not WriteType.EXPIRING:
        # Only a lapsing value goes back on its own; any other would stay for good.
        found.append("timeout_needs_expiring_writes")
    elif (
        control.hand_back is HandBack.SWITCH
        and control.hand_back_entity_write_type not in WRITABLE_TYPES
    ):
        # A switch the boiler may store would be worn by every take and hand-back (P-40).
        found.append("hand_back_switch_not_writable")
    return found + hand_back_value_problems(control)


def _topology_blockers(control: ControlOptions) -> list[str]:
    """A topology that allows control and suits the path, and — on a gateway topology — the
    answer about the thermostat terminals (decision 1, on every path that takes one)."""
    found: list[str] = []
    path = control.write_path
    if control.topology is None:
        found.append("no_topology")
    elif control.topology not in CONTROLLABLE_TOPOLOGIES:
        found.append("topology_no_control")
    elif path is not None and control.topology not in PATH_TOPOLOGIES[path]:
        found.append("topology_not_for_path")
    if (kind := thermostat_kind_blocker(control)) is not None:
        found.append(kind)
    return found


def _curve_blockers(control: ControlOptions) -> list[str]:
    """The curve entered, never silently defaulted, and its values fitting together (P-68)."""
    if not control.curve_entered:
        return ["curve_not_entered"]
    curve, limits = control.loop.control.curve, control.loop.control.limits
    problems = curve_problems(
        curve.design_flow, curve.design_outdoor, curve.room, limits.hard_min, limits.hard_max
    )
    return [key for _field, key in problems]


def _circuit_blockers(installation: Installation) -> list[str]:
    """One circuit fed straight by the boiler flow (unmixed, or passive fixed); underfloor on
    an unmixed one needs its maximum flow."""
    circuits = installation.circuits
    if len(circuits) != 1 or circuits[0].control not in (
        CircuitControl.UNMIXED_SHARED,
        CircuitControl.PASSIVE_FIXED,
    ):
        return ["one_direct_circuit_only"]
    circuit = circuits[0]
    if (
        circuit.control is CircuitControl.UNMIXED_SHARED
        and EmitterType.UNDERFLOOR in installation.emitters_in(circuit.circuit_id)
        and circuit.max_flow is None
    ):
        return ["underfloor_without_max_flow"]
    return []


def _off_blockers(control: ControlOptions) -> list[str]:
    """Without heating writes, "off" is a low setpoint: it must stay clear of the lowest water
    temperature, or it would heat, or not show (P-43)."""
    if not control.loop.ch_writes and off_too_close_to_lowest(
        control.loop.off_setpoint, control.loop.control.limits.hard_min
    ):
        return ["off_setpoint_not_below_hard_min"]
    return []


def off_too_close_to_lowest(off_setpoint: float, lowest: float) -> bool:
    """P-43: "off" as a low setpoint must be at least ``OFF_BELOW_LOWEST_K`` below the lowest
    water temperature."""
    return off_setpoint > lowest - OFF_BELOW_LOWEST_K
