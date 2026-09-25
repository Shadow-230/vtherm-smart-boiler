"""The controller: a state machine that turns what the plugin knows into a boiler command.

Order of precedence, checked on every tick:

1. Control switched off or a precondition missing → no command; hand back once if we were
   controlling. Neither clears a latch.
2. An alarm set to hand back → hand back, latched — with the alarms that caused it — until a new
   session: the user switching control off and on again (the control unit starts it).
3. VT's central mode "Stopped" → hand back; control resumes when the mode changes.
4. The boiler's signals are not fresh → no command (nothing is written without fresh data); if
   that lasts beyond the stale hand-back time, hand back once; control resumes with fresh data.
5. Otherwise heating on or off, decided at every step from frost protection, VT's central mode,
   summer/winter and the zones' demand — nothing counted or timed holds it against VT; and the
   water temperature, decided every decision interval (and at once after any of the above ends):
   the curve on the effective outdoor temperature, limits and ramp. Without an outdoor
   temperature the fallback setpoint applies; without fresh zone data heating is assumed to be
   needed — never zero heat on missing data.

Zone signals only correct the curve (weather is counted once): while a zone's valve is fully open
and the room is still short of its setpoint, the setpoint rises a step per decision; once every
zone is clearly satisfied it falls back a step per decision. The correction never exceeds the
ceiling band and every limit still applies.
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
    Season,
    SeasonConfig,
    frost_needed,
    limit_flow,
    update_season,
)
from .readings import ZoneState

HOUR = 3600.0
FALLBACK_OUTDOOR = 0.0  # the fallback setpoint defaults to the curve at this outdoor temperature


class CentralMode(StrEnum):
    """VT's central mode as the controller sees it."""

    AUTO = "auto"
    STOPPED = "stopped"
    HEAT_ONLY = "heat_only"
    COOL_ONLY = "cool_only"
    FROST_PROTECTION = "frost_protection"


class ControlMode(StrEnum):
    DISABLED = "disabled"
    NOT_ALLOWED = "not_allowed"
    HANDED_BACK = "handed_back"
    WAITING_DATA = "waiting_data"
    HEATING = "heating"
    IDLE = "idle"
    SUMMER = "summer"
    FROST = "frost"
    FALLBACK = "fallback"


class Reason(StrEnum):
    CONTROL_OFF = "control_off"
    PRECONDITION = "precondition"
    ALARM_HAND_BACK = "alarm_hand_back"
    CENTRAL_STOPPED = "central_stopped"
    CENTRAL_COOL_ONLY = "central_cool_only"
    BOILER_LINK_STALE = "boiler_link_stale"
    OUTDOOR_SENSOR = "outdoor_sensor"
    OUTDOOR_WEATHER = "outdoor_weather"
    OUTDOOR_HELD = "outdoor_held"
    OUTDOOR_UNKNOWN = "outdoor_unknown"
    DEMAND = "demand"
    NO_DEMAND = "no_demand"
    ZONES_UNKNOWN = "zones_unknown"
    SUMMER = "summer"
    FROST = "frost"
    RAMP = "ramp"
    LIMIT_HARD_MIN = "limit_hard_min"
    LIMIT_HARD_MAX = "limit_hard_max"
    LIMIT_CIRCUIT_MAX = "limit_circuit_max"
    LIMIT_BOILER_MAX = "limit_boiler_max"
    LIMIT_CEILING = "limit_ceiling"
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
}


@dataclass(frozen=True, slots=True)
class ControlConfig:
    curve: HeatingCurve
    limits: FlowLimits = field(default_factory=FlowLimits)
    circuit_max: float | None = None
    boiler_max: float | None = None
    season: SeasonConfig = field(default_factory=SeasonConfig)
    frost: FrostConfig = field(default_factory=FrostConfig)
    demand: DemandConfig = field(default_factory=DemandConfig)
    fallback_setpoint: float | None = None  # None: the curve at FALLBACK_OUTDOOR
    ramp_k_per_min: float | None = 1.0  # None: no ramp
    decision_interval_s: float = 300.0
    zone_max_age_s: float = 2 * HOUR
    correction_step_k: float | None = 1.0  # None: no comfort correction
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
    central_mode: CentralMode | None = None
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
    season: Season = Season.WINTER
    frost: bool = False
    command: BoilerCommand | None = None
    target: float | None = None
    reasons: tuple[Reason, ...] = ()
    water_reasons: tuple[Reason, ...] = ()  # why the water temperature is what it is
    decided_at: float | None = None  # when the water temperature was last decided
    correction: float = 0.0  # K added to the curve for a zone that cannot reach its setpoint
    waiting_since: float | None = None  # when the boiler's signals went stale


@dataclass(frozen=True, slots=True)
class ControlDecision:
    mode: ControlMode
    command: BoilerCommand | None  # what the boiler should do now; None: write nothing
    hand_back: bool = False  # give control back now
    reasons: tuple[Reason, ...] = ()
    target: float | None = None  # setpoint before the ramp
    effective_outdoor: float | None = None


def fallback_setpoint(config: ControlConfig) -> float:
    if config.fallback_setpoint is not None:
        return config.fallback_setpoint
    return config.curve.flow(FALLBACK_OUTDOOR)


def _release(
    state: ControlState, mode: ControlMode, reason: Reason
) -> tuple[ControlState, ControlDecision]:
    """No command; hand back once if we were controlling. A latch stays as it is."""
    new_state = replace(
        state,
        mode=mode,
        controlling=False,
        command=None,
        reasons=(reason,),
        decided_at=None,
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
    if inputs.central_mode is CentralMode.STOPPED:
        return _release(state, ControlMode.HANDED_BACK, Reason.CENTRAL_STOPPED)
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
    season = update_season(state.season, outdoor.effective, config.season)
    want_heat, heat_reason = _want_heat(season, inputs, config, frost)

    due = (
        state.decided_at is None
        or state.command is None
        or now - state.decided_at >= config.decision_interval_s
        or frost != state.frost
    )
    if due:
        water: list[Reason] = [_OUTDOOR_REASON[outdoor.source]]
        correction = _correction(state, inputs, config)
        if correction > 0:
            water.append(Reason.COMFORT_CORRECTION)
        if outdoor.effective is None:
            curve_value = fallback_setpoint(config)
        else:
            curve_value = config.curve.flow(outdoor.effective)
        limited = limit_flow(
            curve_value + correction, curve_value, config.limits, config.circuit_max,
            config.boiler_max,
        )  # fmt: skip
        water.extend(_LIMIT_REASON[code] for code in limited.applied)
        setpoint = _ramp(state, limited.value, curve_value, now, config, water)
        target: float | None = limited.value
        water_reasons, decided_at = tuple(water), now
    else:
        assert state.command is not None
        setpoint, target, correction = state.command.setpoint, state.target, state.correction
        water_reasons, decided_at = state.water_reasons, state.decided_at

    if frost:
        mode = ControlMode.FROST
    elif outdoor.effective is None:
        mode = ControlMode.FALLBACK
    elif season is Season.SUMMER and not want_heat:
        mode = ControlMode.SUMMER
    elif want_heat:
        mode = ControlMode.HEATING
    else:
        mode = ControlMode.IDLE

    reasons = (*water_reasons[:1], heat_reason, *water_reasons[1:])
    command = BoilerCommand(want_heat, setpoint)
    new_state = replace(
        state,
        mode=mode,
        controlling=True,
        season=season,
        frost=frost,
        command=command,
        target=target,
        reasons=reasons,
        water_reasons=water_reasons,
        decided_at=decided_at,
        correction=correction,
    )
    return new_state, ControlDecision(
        mode, command, reasons=reasons, target=target, effective_outdoor=outdoor.effective
    )


def _want_heat(
    season: Season, inputs: ControlInputs, config: ControlConfig, frost: bool
) -> tuple[bool, Reason]:
    """Whether to heat now and why: frost protection, then VT's modes and the zones' demand."""
    if frost:
        return True, Reason.FROST
    if inputs.central_mode is CentralMode.COOL_ONLY:
        return False, Reason.CENTRAL_COOL_ONLY
    if season is Season.SUMMER:
        return False, Reason.SUMMER
    demand = boiler_demand(inputs.zones, inputs.now, config.zone_max_age_s, config.demand)
    if demand.wanted is None:
        return True, Reason.ZONES_UNKNOWN
    return demand.wanted, Reason.DEMAND if demand.wanted else Reason.NO_DEMAND


SATURATED = 0.95  # a valve or duty cycle this open cannot give the room more
SATISFIED = 0.7  # every zone below this opening is clearly satisfied
SHORT_K = 0.3  # a deficit this large counts as short of the setpoint


def _correction(state: ControlState, inputs: ControlInputs, config: ControlConfig) -> float:
    """Comfort correction for the next decision, within the ceiling band."""
    step = config.correction_step_k
    if step is None:
        return 0.0
    fresh = [
        z
        for z in inputs.zones
        if z.heating_enabled is True and z.is_fresh(inputs.now, config.zone_max_age_s)
    ]
    short = any(
        z.demand is not None
        and z.demand >= SATURATED
        and z.deficit is not None
        and z.deficit >= SHORT_K
        for z in fresh
    )
    satisfied = bool(fresh) and all(z.demand is not None and z.demand < SATISFIED for z in fresh)
    correction = state.correction
    if short:
        correction += step
    elif satisfied:
        correction -= step
    return min(config.limits.ceiling_band, max(0.0, correction))


def _ramp(
    state: ControlState,
    target: float,
    curve_value: float,
    now: float,
    config: ControlConfig,
    reasons: list[Reason],
) -> float:
    """Move from the last setpoint towards ``target`` at the ramp rate; a cap that fell below
    the last setpoint applies at once."""
    previous = state.command.setpoint if state.command is not None else None
    if previous is None:
        return target
    upper = limit_flow(1e6, curve_value, config.limits, config.circuit_max, config.boiler_max).value
    if previous > upper:
        return target
    delta = target - previous
    if abs(delta) < 1e-9:
        return previous
    step = delta
    if config.ramp_k_per_min is not None and state.decided_at is not None:
        allowed = config.ramp_k_per_min * max(0.0, now - state.decided_at) / 60.0
        if abs(delta) > allowed:
            step = allowed if delta > 0 else -allowed
            reasons.append(Reason.RAMP)
    return previous + step
