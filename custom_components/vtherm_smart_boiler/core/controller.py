"""The controller: a state machine that turns what the plugin knows into a boiler command.

Order of precedence, checked on every tick:

1. Control switched off or a precondition missing → no command; hand back once if we were
   controlling. Neither clears a latch.
2. An alarm set to hand back → hand back, latched — with the alarms that caused it — until a new
   session: the user switching control off and on again (the control unit starts it).
3. The boiler's signals are not fresh → no command (nothing is written without fresh data); if
   that lasts beyond the stale hand-back time, hand back once; control resumes with fresh data.
4. Otherwise heating on or off, decided at every step from frost protection and the zones'
   demand — VT's central mode and summer or winter reach the plugin through the zones, and
   nothing counted or timed holds heating against VT; and the
   water temperature, decided every decision interval (and at once after any of the above ends):
   the curve on the effective outdoor temperature, limits and ramp. Without an outdoor
   temperature the fallback setpoint applies; without fresh zone data heating is assumed to be
   needed — never zero heat on missing data.

Zone signals only correct the curve (weather is counted once). The comfort correction follows the
rules of bounded learning: while a zone's valve is fully open (or at VT's cap) and its room is
still short of its setpoint, the water rises above the curve — at most 3 K, by 1 K per 30 minutes
and only while heat flows; it falls twice as fast once the zones with an opening are clearly
satisfied, or while another zone is more than 1 K too warm; a zone without an opening never
blocks the fall. It resets at hand-back and with a new session, and when it stays at 3 K for
hours the decision says so: the curve is probably too low. Every limit still applies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .curve import (
    DEFAULT_HOLD_S,
    DEFAULT_TIME_CONSTANT_S,
    HeatingCurve,
    OutdoorSource,
    OutdoorState,
    update_outdoor,
)
from .demand import DemandConfig, boiler_demand
from .limits import (
    FlowLimits,
    FrostConfig,
    LimitCode,
    frost_needed,
    limit_flow,
    watched_temperatures,
)
from .readings import ZoneState

HOUR = 3600.0
CORRECTION_MAX_K = 3.0  # the firm band of the comfort correction
CORRECTION_RISE_S = 30 * 60.0  # seconds of heat flow per kelvin of rise; the fall is twice as fast
CORRECTION_LIMIT_S = 3 * HOUR  # at the band's edge this long: tell the user
OVERHEAT_K = 1.0  # a zone this far over its setpoint stops the rise
FROST_ALARM_S = 2 * HOUR  # frost heating this long without the room warming is reported
FROST_WARMING_K = 0.5  # the watched room must have warmed by this much


class ControlMode(StrEnum):
    DISABLED = "disabled"
    NOT_ALLOWED = "not_allowed"
    HANDED_BACK = "handed_back"
    WAITING_DATA = "waiting_data"
    HEATING = "heating"
    IDLE = "idle"
    FROST = "frost"
    FALLBACK = "fallback"


class Reason(StrEnum):
    CONTROL_OFF = "control_off"
    PRECONDITION = "precondition"
    ALARM_HAND_BACK = "alarm_hand_back"
    BOILER_LINK_STALE = "boiler_link_stale"
    OUTDOOR_SENSOR = "outdoor_sensor"
    OUTDOOR_WEATHER = "outdoor_weather"
    OUTDOOR_HELD = "outdoor_held"
    OUTDOOR_UNKNOWN = "outdoor_unknown"
    DEMAND = "demand"
    NO_DEMAND = "no_demand"
    ZONES_UNKNOWN = "zones_unknown"
    FROST = "frost"
    RAMP = "ramp"
    LIMIT_HARD_MIN = "limit_hard_min"
    LIMIT_HARD_MAX = "limit_hard_max"
    LIMIT_CIRCUIT_MAX = "limit_circuit_max"
    LIMIT_BOILER_MAX = "limit_boiler_max"
    LIMIT_CEILING = "limit_ceiling"
    LIMIT_FIXED_CIRCUIT = "limit_fixed_circuit"
    COMFORT_CORRECTION = "comfort_correction"


_OUTDOOR_REASON = {
    OutdoorSource.SENSOR: Reason.OUTDOOR_SENSOR,
    OutdoorSource.WEATHER: Reason.OUTDOOR_WEATHER,
    OutdoorSource.HELD: Reason.OUTDOOR_HELD,
    OutdoorSource.NONE: Reason.OUTDOOR_UNKNOWN,
}
_LIMIT_REASON = {
    LimitCode.HARD_MIN: Reason.LIMIT_HARD_MIN,
    LimitCode.HARD_MAX: Reason.LIMIT_HARD_MAX,
    LimitCode.CIRCUIT_MAX: Reason.LIMIT_CIRCUIT_MAX,
    LimitCode.BOILER_MAX: Reason.LIMIT_BOILER_MAX,
    LimitCode.CEILING: Reason.LIMIT_CEILING,
    LimitCode.FIXED_CIRCUIT: Reason.LIMIT_FIXED_CIRCUIT,
}


@dataclass(frozen=True, slots=True)
class ControlConfig:
    curve: HeatingCurve
    limits: FlowLimits = field(default_factory=FlowLimits)
    circuit_max: float | None = None
    boiler_max: float | None = None
    circuit_floor: float | None = None  # a fixed circuit's temperature: the boiler flow's floor
    frost: FrostConfig = field(default_factory=FrostConfig)
    demand: DemandConfig = field(default_factory=DemandConfig)
    fallback_setpoint: float | None = None  # None: the curve at its design point
    ramp_k_per_min: float | None = 1.0  # None: no ramp
    decision_interval_s: float = 300.0
    # One freshness rule (O1): a steady reading is not a stale one. VT reports when its room
    # sensor last changed, which a steady room does not do for hours; a zone is unknown by its
    # state (unavailable, not started), and a room sensor gone quiet is VT's own safety mode's.
    zone_max_age_s: float | None = None
    comfort_correction: bool = True
    stale_hand_back_s: float | None = 300.0  # hand back after this long without fresh data
    outdoor_time_constant_s: float = DEFAULT_TIME_CONSTANT_S
    outdoor_hold_s: float = DEFAULT_HOLD_S

    def __post_init__(self) -> None:
        if self.decision_interval_s <= 0:
            raise ValueError("the decision interval must be positive")
        if self.ramp_k_per_min is not None and self.ramp_k_per_min <= 0:
            raise ValueError("the ramp must be positive")


@dataclass(frozen=True, slots=True)
class ControlInputs:
    """What the plugin knows at ``now``; readings are ``None`` when missing or stale."""

    now: float
    enabled: bool
    blockers: tuple[str, ...] = ()  # preconditions not met
    hand_back_alarms: tuple[str, ...] = ()  # active alarms whose reaction is hand-back
    boiler_link: bool = True  # the boiler's own signals are fresh
    flame: bool | None = None
    dhw: bool | None = None
    outdoor_sensor: float | None = None
    outdoor_weather: float | None = None
    zones: Sequence[ZoneState] = ()


@dataclass(frozen=True, slots=True)
class BoilerCommand:
    ch_enable: bool
    setpoint: float


@dataclass(frozen=True, slots=True)
class ControlState:
    mode: ControlMode = ControlMode.DISABLED
    controlling: bool = False  # commands were given and control has not been handed back
    latched: bool = False  # an alarm handed back; stays for the session
    latched_by: tuple[str, ...] = ()  # the alarms that set the latch
    outdoor: OutdoorState = field(default_factory=OutdoorState)
    frost: bool = False
    frost_since: float | None = None  # when frost heating began
    frost_from: float | None = None  # the coldest watched room then
    command: BoilerCommand | None = None
    target: float | None = None
    reasons: tuple[Reason, ...] = ()
    water_reasons: tuple[Reason, ...] = ()  # why the water temperature is what it is
    decided_at: float | None = None  # when the water temperature was last decided
    correction: float = 0.0  # K added to the curve for a zone that cannot reach its setpoint
    heat_s: float = 0.0  # seconds heat has flowed since the last water decision
    last_step_at: float | None = None
    upper: float | None = None  # the highest setpoint the limits allow, at the last decision
    correction_limit_since: float | None = None  # when the correction reached its band's edge
    waiting_since: float | None = None  # when the boiler's signals went stale


@dataclass(frozen=True, slots=True)
class ControlDecision:
    mode: ControlMode
    command: BoilerCommand | None  # what the boiler should do now; None: write nothing
    hand_back: bool = False  # give control back now
    reasons: tuple[Reason, ...] = ()
    target: float | None = None  # setpoint before the ramp
    effective_outdoor: float | None = None
    frost_stuck: bool = False  # frost heating for long without the room warming: tell the user
    correction_at_limit: bool = False  # the correction at its band's edge for hours: tell the user


def fallback_setpoint(config: ControlConfig) -> float:
    """Without any outdoor temperature (the last one held for a while): the user's value, else
    the curve's design point — never too little heat; the valves keep rooms from overheating."""
    if config.fallback_setpoint is not None:
        return config.fallback_setpoint
    return config.curve.flow(config.curve.design_outdoor)


def _release(
    state: ControlState, mode: ControlMode, reason: Reason
) -> tuple[ControlState, ControlDecision]:
    """No command; hand back once if we were controlling. A latch stays as it is; what the
    session learned (the comfort correction) goes."""
    new_state = replace(
        state,
        mode=mode,
        controlling=False,
        command=None,
        reasons=(reason,),
        decided_at=None,
        correction=0.0,
        heat_s=0.0,
        last_step_at=None,
        correction_limit_since=None,
    )
    return new_state, ControlDecision(mode, None, hand_back=state.controlling, reasons=(reason,))


def decide(
    state: ControlState, inputs: ControlInputs, config: ControlConfig
) -> tuple[ControlState, ControlDecision]:
    """One tick of the controller."""
    now = inputs.now
    outdoor = update_outdoor(
        state.outdoor,
        inputs.outdoor_sensor,
        inputs.outdoor_weather,
        now,
        config.outdoor_time_constant_s,
        config.outdoor_hold_s,
    )
    state = replace(state, outdoor=outdoor)

    if not inputs.enabled:
        return _release(state, ControlMode.DISABLED, Reason.CONTROL_OFF)
    if inputs.blockers:
        return _release(state, ControlMode.NOT_ALLOWED, Reason.PRECONDITION)
    if state.latched or inputs.hand_back_alarms:
        latched_by = state.latched_by if state.latched else tuple(inputs.hand_back_alarms)
        state = replace(state, latched=True, latched_by=latched_by)
        return _release(state, ControlMode.HANDED_BACK, Reason.ALARM_HAND_BACK)
    if not inputs.boiler_link:
        since = state.waiting_since if state.waiting_since is not None else now
        state = replace(state, waiting_since=since)
        if (
            state.controlling
            and config.stale_hand_back_s is not None
            and now - since >= config.stale_hand_back_s
        ):
            return _release(state, ControlMode.HANDED_BACK, Reason.BOILER_LINK_STALE)
        reasons = (Reason.BOILER_LINK_STALE,)
        # Once handed back for stale data, that stays what is shown until the data returns.
        mode = (
            ControlMode.HANDED_BACK
            if not state.controlling and state.mode is ControlMode.HANDED_BACK
            else ControlMode.WAITING_DATA
        )
        waiting = replace(state, mode=mode, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(mode, None, reasons=reasons)
    state = replace(state, waiting_since=None)

    frost = frost_needed(inputs.zones, now, config.zone_max_age_s, state.frost, config.frost)
    return _heating_decision(state, inputs, config, frost)


def _heating_decision(
    state: ControlState, inputs: ControlInputs, config: ControlConfig, frost: bool
) -> tuple[ControlState, ControlDecision]:
    """Heating on or off at every step; the water temperature every decision interval."""
    now = inputs.now
    outdoor = state.outdoor
    coldest = min(
        watched_temperatures(inputs.zones, now, config.zone_max_age_s, config.frost), default=None
    )
    if frost and not state.frost:
        state = replace(state, frost_since=now, frost_from=coldest)
    elif not frost:
        state = replace(state, frost_since=None, frost_from=None)
    step_s = 0.0 if state.last_step_at is None else max(0.0, now - state.last_step_at)
    if want_heat_now(inputs, config, frost) and not inputs.dhw:
        state = replace(state, heat_s=state.heat_s + step_s)
    state = replace(state, last_step_at=now)
    # Frost heating is never stopped; heating that does not warm the room is reported.
    frost_stuck = (
        frost
        and state.frost_since is not None
        and now - state.frost_since >= FROST_ALARM_S
        and coldest is not None
        and state.frost_from is not None
        and coldest < state.frost_from + FROST_WARMING_K
    )
    want_heat, heat_reason = _want_heat(inputs, config, frost)

    prior_target, prior_upper = state.target, state.upper
    due = (
        state.decided_at is None
        or state.command is None
        or prior_target is None
        or prior_upper is None
        or now - state.decided_at >= config.decision_interval_s
        or frost != state.frost
    )
    if due:
        water: list[Reason] = [_OUTDOOR_REASON[outdoor.source]]
        correction = _correction(state, inputs, config)
        limit_since = (
            (state.correction_limit_since or now) if correction >= CORRECTION_MAX_K else None
        )
        state = replace(state, heat_s=0.0, correction_limit_since=limit_since)
        if correction > 0:
            water.append(Reason.COMFORT_CORRECTION)
        if outdoor.effective is None:
            curve_value = fallback_setpoint(config)
        else:
            curve_value = config.curve.flow(outdoor.effective)
        limited = limit_flow(
            curve_value + correction, curve_value, config.limits, config.circuit_max,
            config.boiler_max, config.circuit_floor,
        )  # fmt: skip
        water.extend(_LIMIT_REASON[code] for code in limited.applied)
        upper = limit_flow(
            1e6, curve_value, config.limits, config.circuit_max, config.boiler_max,
            config.circuit_floor,
        ).value  # fmt: skip
        target: float = limited.value
        water_reasons, decided_at = tuple(water), now
    else:
        assert prior_target is not None
        assert prior_upper is not None
        assert state.decided_at is not None
        target, upper, correction = prior_target, prior_upper, state.correction
        water_reasons, decided_at = state.water_reasons, state.decided_at
    previous = state.command.setpoint if state.command is not None else None
    setpoint, ramping = _ramp(previous, target, upper, step_s, config.ramp_k_per_min)

    if frost:
        mode = ControlMode.FROST
    elif outdoor.effective is None:
        mode = ControlMode.FALLBACK
    elif want_heat:
        mode = ControlMode.HEATING
    else:
        mode = ControlMode.IDLE

    reasons = (*water_reasons[:1], heat_reason, *water_reasons[1:])
    if ramping:
        reasons = (*reasons, Reason.RAMP)
    command = BoilerCommand(want_heat, setpoint)
    new_state = replace(
        state,
        mode=mode,
        controlling=True,
        frost=frost,
        command=command,
        target=target,
        upper=upper,
        reasons=reasons,
        water_reasons=water_reasons,
        decided_at=decided_at,
        correction=correction,
    )
    return new_state, ControlDecision(
        mode,
        command,
        reasons=reasons,
        target=target,
        effective_outdoor=outdoor.effective,
        frost_stuck=frost_stuck,
        correction_at_limit=(
            state.correction_limit_since is not None
            and now - state.correction_limit_since >= CORRECTION_LIMIT_S
        ),
    )


def want_heat_now(inputs: ControlInputs, config: ControlConfig, frost: bool) -> bool:
    return _want_heat(inputs, config, frost)[0]


def _want_heat(inputs: ControlInputs, config: ControlConfig, frost: bool) -> tuple[bool, Reason]:
    """Whether to heat now and why: frost protection, else the zones' demand — VT's central mode
    and summer or winter act on the zones themselves."""
    if frost:
        return True, Reason.FROST
    demand = boiler_demand(inputs.zones, inputs.now, config.zone_max_age_s, config.demand)
    if demand.wanted is None:
        return True, Reason.ZONES_UNKNOWN
    return demand.wanted, Reason.DEMAND if demand.wanted else Reason.NO_DEMAND


SATISFIED = 0.7  # every zone below this opening is clearly satisfied
SHORT_K = 0.3  # a deficit this large counts as short of the setpoint


def _saturated(zone: ZoneState) -> bool:
    return zone.fully_open  # one meaning, shared with the critical zone


def _correction(state: ControlState, inputs: ControlInputs, config: ControlConfig) -> float:
    """The comfort correction for this water decision, within its firm band (bounded learning)."""
    if not config.comfort_correction:
        return 0.0
    now = inputs.now
    known = [
        z
        for z in inputs.zones
        if z.heating_enabled is True and z.is_known(now, config.zone_max_age_s)
    ]
    too_warm = any(z.deficit is not None and z.deficit < -OVERHEAT_K for z in known)
    short = any(_saturated(z) and z.deficit is not None and z.deficit >= SHORT_K for z in known)
    opened = [z for z in known if z.demand is not None]  # no opening: never blocks the fall
    satisfied = bool(opened) and all(z.demand is not None and z.demand < SATISFIED for z in opened)
    correction = state.correction
    if too_warm or (satisfied and not short):
        elapsed = now - state.decided_at if state.decided_at is not None else 0.0
        correction -= 2.0 * elapsed / CORRECTION_RISE_S
    elif short:
        correction += state.heat_s / CORRECTION_RISE_S  # only while heat flows
    return min(CORRECTION_MAX_K, max(0.0, correction))


def _ramp(
    previous: float | None, target: float, upper: float, step_s: float, rate: float | None
) -> tuple[float, bool]:
    """The setpoint for this step: towards ``target`` at ``rate`` K per minute, at every step.
    The first setpoint of a session is the target itself; a cap that fell below the last
    setpoint applies at once. Whether the ramp held the setpoint back."""
    if previous is None or previous > upper or rate is None:
        return target, False
    delta = target - previous
    allowed = rate * step_s / 60.0
    if abs(delta) <= allowed:
        return target, False
    return previous + (allowed if delta > 0 else -allowed), True
