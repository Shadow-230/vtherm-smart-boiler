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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .core.controller import ControlConfig
from .core.curve import HeatingCurve
from .core.demand import DemandConfig
from .core.guards import GuardConfig, WriteType
from .core.installation import BoilerClass, CircuitControl, EmitterType, Installation
from .core.learning import LearningConfig
from .core.limits import FlowLimits, FrostConfig
from .core.loop import DEFAULT_OFF_SETPOINT, LoopConfig

MINUTE = 60.0
KEEPALIVE_S = 30.0

# Every control option's default, in the unit the options store: the parser and the options
# forms both read them here.
CONTROL_DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "hard_min": 25.0,
        "hard_max": 70.0,
        "ceiling_band": 10.0,
        "frost_limit": 5.0,
        "frost_release": 7.0,
        "count_threshold": 1,
        "ramp_k_per_min": 1.0,
        "decision_interval_min": 5.0,
        "off_setpoint": DEFAULT_OFF_SETPOINT,
        "learning_pauses": True,
        "comfort_correction": True,
        # Without the tick, VT giving no answer at all means no heating and an alarm (answer F).
        "own_room_controller": False,
        # VT's activation delay (decision 5): 0 s, VT's own default — heating starts at once.
        "activation_delay_s": 0,
    }
)
CURVE_DEFAULTS: Mapping[str, float] = MappingProxyType(
    {"design_outdoor": -15.0, "design_flow": 55.0, "room": 20.0, "offset": 0.0}
)


class WritePath(StrEnum):
    ENTITY = "entity"  # a writable entity the user picked
    OPENTHERM_GW = "opentherm_gw"  # built-in OTGW through Home Assistant's opentherm_gw
    OTGW_MQTT = "otgw_mqtt"  # built-in OTGW through its firmware's MQTT commands


class Topology(StrEnum):
    GATEWAY_STANDALONE = "gateway_standalone"  # the gateway is master: hand-back stops heating
    GATEWAY_WITH_THERMOSTAT = "gateway_with_thermostat"  # hand-back: the thermostat takes over
    MONITOR_MODE = "monitor_mode"  # the gateway only listens: no control
    VIRTUAL = "virtual"  # a controller on the HA side (e.g. an ESPHome OpenTherm master)


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


class AlarmReaction(StrEnum):
    INFO = "info"
    HAND_BACK = "hand_back"


# Everything ``config_blockers`` may report (translation keys).
CONFIG_BLOCKERS = (
    "no_write_path",
    "boiler_not_flow_setpoint",
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
)
OTGW_PATHS = frozenset({WritePath.OPENTHERM_GW, WritePath.OTGW_MQTT})
# Write types control may use: nothing the boiler stores in its memory.
WRITABLE_TYPES = frozenset({WriteType.EXPIRING, WriteType.HELD})
CONTROLLABLE_TOPOLOGIES = frozenset(
    {Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT, Topology.VIRTUAL}
)
# Alarms that stay information: nothing the plugin counts may hold heating against VT, so many
# starts never hand back (``SCOPE.md`` principle 12); a circuit's water above its alarm
# temperature tells the user of the boiler's overshoot (decision 10).
INFO_ONLY_ALARMS = frozenset({"frequent_starts", "circuit_too_hot"})
# Alarms that always hand control back, with no reaction to choose (decision 7): another
# controller writing to the boiler makes the plugin step aside — the whole safe hand-back, then a
# latch (decision 6, the user's answer H) — and a boiler that ignores "heating off" from the start
# of the session is blocked and handed back like an installation without a working heating switch
# (answer O). A stored reaction for them is neutralised (S-11).
ALWAYS_HAND_BACK_ALARMS = frozenset({"outside_change", "heating_off_ignored"})
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
# Hand-back effects where the heating part leaves a heating switch as it is: the hand-back stops
# heating. X8's relay effects go to the relay's rest state instead, through its own writer.
_HEATING_LEFT_AS_IT_IS = frozenset({HandBackEffect.HEATING_STOPS})


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
    gateway_id: str | None = None
    mqtt_top: str | None = None
    mqtt_node: str | None = None
    confirmed_entity: str | None = None
    ch_confirmed_entity: str | None = None  # echoes heating on/off as the boiler gets it
    topology: Topology | None = None
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

    @property
    def configured(self) -> bool:
        return self.write_path is not None

    def reaction(self, alarm: str) -> AlarmReaction:
        """What an active alarm does: a fixed reaction where there is one, else the user's
        choice; an alarm without one informs."""
        if alarm in ALWAYS_HAND_BACK_ALARMS:
            return AlarmReaction.HAND_BACK
        if alarm in INFO_ONLY_ALARMS:
            return AlarmReaction.INFO
        return self.alarm_reactions.get(alarm, AlarmReaction.INFO)

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
        )
        return tuple(e for e in found if e)


def _float(data: Mapping[str, Any], key: str, default: float | None) -> float | None:
    value = data.get(key, default)
    if value is None or value == "":
        return None
    return float(value)


def _minutes(data: Mapping[str, Any], key: str, default_min: float) -> float:
    value = _float(data, key, default_min)
    return (default_min if value is None else value) * MINUTE


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
    if path in OTGW_PATHS:
        write_type = ch_write_type = WriteType.EXPIRING  # CS and CH lapse unless repeated
    else:
        write_type = WriteType(data.get("write_type", WriteType.UNKNOWN))
        ch_write_type = WriteType(data.get("ch_write_type", WriteType.UNKNOWN))
    circuit_max = circuit.max_flow if circuit is not None else None
    circuit_floor = None
    if circuit is not None and circuit.control is CircuitControl.PASSIVE_FIXED:
        # The mixing valve needs at least its temperature from the boiler; a maximum the user
        # declared still applies.
        circuit_floor = circuit.fixed_temperature
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
        ramp_k_per_min=ramp,
        decision_interval_s=_minutes(value, "decision_interval_min", 5.0),
        comfort_correction=bool(value["comfort_correction"]),
        # Only what the user saved: VT's own value is a pre-fill in the form, never taken here.
        activation_delay_s=float(value["activation_delay_s"]),
    )
    loop = LoopConfig(
        control=control,
        setpoint_guard=GuardConfig(write_type=write_type, keepalive_s=KEEPALIVE_S),
        switch_guard=GuardConfig(
            # An expiring heating override is repeated with the setpoint's keep-alive; without an
            # echo, heating on/off is never judged, only shown unverified.
            write_type=ch_write_type,
            keepalive_s=KEEPALIVE_S,
            read_back=bool(data.get("ch_confirmed_entity")),
            two_valued=True,
        ),
        # A heating switch the boiler may store is left alone: "off" is then a low setpoint.
        ch_writes=path in OTGW_PATHS
        or (bool(data.get("ch_entity")) and ch_write_type in WRITABLE_TYPES),
        off_setpoint=float(value["off_setpoint"]),
    )
    reactions = {
        str(alarm): AlarmReaction(reaction)
        for alarm, reaction in (data.get("alarm_reactions") or {}).items()
        # A fixed reaction leaves nothing to choose: a stored one is neutralised, whatever it
        # holds (0.2.1's form offered "information" for an outside change, S-11).
        if str(alarm) not in ALWAYS_HAND_BACK_ALARMS
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
        gateway_id=data.get("gateway_id") or None,
        mqtt_top=data.get("mqtt_top") or None,
        mqtt_node=data.get("mqtt_node") or None,
        confirmed_entity=data.get("confirmed_entity") or None,
        ch_confirmed_entity=data.get("ch_confirmed_entity") or None,
        topology=Topology(data["topology"]) if data.get("topology") else None,
        curve_entered=bool(curve_data.get("design_flow")),
        loop=loop,
        learning=LearningConfig(),
        learning_pauses=bool(value["learning_pauses"]),
        alarm_reactions=reactions,
        return_after_outside_change=data.get("return_after_outside_change") is True,
        thermostat_setpoint_entity=data.get("thermostat_setpoint_entity") or None,
        restart_entity=data.get("restart_entity") or None,
        own_room_controller=data.get("own_room_controller") is True,
    )
    working = replace(loop.control, working_thermostat=working_thermostat(options))
    return replace(options, loop=replace(loop, control=working))


def own_room_controller_offered(path: WritePath | None, topology: Topology | None) -> bool:
    """Where the tick "the boiler has its own room controller" is offered (answers F, M): the
    entity path with the virtual topology — with a gateway the thermostat on its terminals
    already counts, and with nothing on them a hand-back stops heating anyway. X8 adds the
    relay path, where the tick counts only with the rest state "on"
    (``relay_working_thermostat``)."""
    return path is WritePath.ENTITY and topology is Topology.VIRTUAL


def own_room_controller_counts(control: ControlOptions) -> bool:
    """The tick counts: stored where it is offered, and with a hand-back that leaves the boiler
    heating — with a hand-back value declared "heating stops" (refused in the form) there is
    nothing for the controller to take over. A tick stored anywhere else is ignored."""
    if not control.own_room_controller:
        return False
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


# Hand-back effects that leave a working thermostat heating the house (decision 3).
_WORKING_THERMOSTAT_EFFECTS = frozenset(
    {HandBackEffect.THERMOSTAT_TAKES_OVER, HandBackEffect.OWN_CONTROL_RESUMES}
)


def working_thermostat(control: ControlOptions) -> bool:
    """Decision 3 (answers F, M): with every zone unknown, is there something to hand the boiler
    to that heats by the rooms? A gateway with an OpenTherm thermostat declared on its
    terminals, or the boiler's own room controller where the tick counts. Not a hand-back value
    declared "own control" without the tick, nor "device decides", nor a stand-alone gateway."""
    return hand_back_effect(control) in _WORKING_THERMOSTAT_EFFECTS


def hand_back_effect(control: ControlOptions) -> HandBackEffect | None:
    """The effect of a hand-back: the boiler's own room controller where the user ticked it (and
    it counts); for a hand-back value, what the user declared it does; else what the declared
    topology leads to. ``None`` where control cannot run."""
    if own_room_controller_counts(control):
        return HandBackEffect.OWN_CONTROL_RESUMES
    if control.hand_back is HandBack.VALUE and control.hand_back_value_effect is not None:
        if control.hand_back_value_effect is ValueEffect.HEATING_STOPS:
            return HandBackEffect.HEATING_STOPS
        return HandBackEffect.DEVICE_DECIDES
    return (
        {
            Topology.GATEWAY_WITH_THERMOSTAT: HandBackEffect.THERMOSTAT_TAKES_OVER,
            Topology.GATEWAY_STANDALONE: HandBackEffect.HEATING_STOPS,
            Topology.VIRTUAL: HandBackEffect.DEVICE_DECIDES,
        }.get(control.topology)
        if control.topology is not None
        else None
    )


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
    itself."""
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


def config_blockers(control: ControlOptions, installation: Installation) -> list[str]:
    """What the configuration still lacks for control (translation keys)."""
    if not control.configured:
        return ["no_write_path"]
    found: list[str] = []
    if installation.boiler.boiler_class is not BoilerClass.FLOW_SETPOINT:
        found.append("boiler_not_flow_setpoint")
    path = control.write_path
    if path is WritePath.ENTITY:
        if not control.setpoint_entity:
            found.append("no_setpoint_entity")
        if control.write_type not in WRITABLE_TYPES:
            found.append("write_type_not_supported")
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
        found += hand_back_value_problems(control)
    elif path is WritePath.OPENTHERM_GW and not control.gateway_id:
        found.append("no_gateway")
    elif path is WritePath.OTGW_MQTT and not (control.mqtt_top and control.mqtt_node):
        found.append("no_mqtt_topic")
    if not control.confirmed_entity:
        found.append("no_confirmed_setpoint")
    if control.topology is None:
        found.append("no_topology")
    elif control.topology not in CONTROLLABLE_TOPOLOGIES:
        found.append("topology_no_control")
    if not control.curve_entered:
        found.append("curve_not_entered")
    circuits = installation.circuits
    if len(circuits) != 1 or circuits[0].control not in (
        CircuitControl.UNMIXED_SHARED,
        CircuitControl.PASSIVE_FIXED,
    ):
        found.append("one_direct_circuit_only")
    else:
        circuit = circuits[0]
        if (
            circuit.control is CircuitControl.UNMIXED_SHARED
            and EmitterType.UNDERFLOOR in installation.emitters_in(circuit.circuit_id)
            and circuit.max_flow is None
        ):
            found.append("underfloor_without_max_flow")
    if not installation.zones:
        found.append("no_zones")  # nothing could ever ask for heat (S-04)
    elif control.loop.control.demand.count_threshold > len(installation.zones):
        found.append("count_threshold_above_zones")  # heating would never be asked for
    if not control.loop.ch_writes and off_too_close_to_lowest(
        control.loop.off_setpoint, control.loop.control.limits.hard_min
    ):
        found.append("off_setpoint_not_below_hard_min")  # "off" would heat, or not show
    return found


def off_too_close_to_lowest(off_setpoint: float, lowest: float) -> bool:
    """P-43: "off" as a low setpoint must be at least ``OFF_BELOW_LOWEST_K`` below the lowest
    water temperature."""
    return off_setpoint > lowest - OFF_BELOW_LOWEST_K
