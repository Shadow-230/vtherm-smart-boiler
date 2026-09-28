"""The controller: a state machine that turns what the plugin knows into a boiler command.

Order of precedence, checked on every tick:

1. Control switched off → no command; hand back once if we were controlling. It does not clear
   a latch.
2. A latch, or an alarm set to hand back → hand back, latched — with the alarms that caused it —
   until a new session: the user switching control off and on again (the control unit starts
   it). An alarm latches whatever blockers show at the same step (P-48); the status still lists
   them.
3. A precondition missing (a blocker) → no command; hand back once if we were controlling. Home
   Assistant starting (``HA_STARTING``) does not stop a command kept or restored in the
   recognition period (point 5), but nothing new is decided before it runs.
4. The boiler link lost, or the boiler's signals not fresh at this step → no command (nothing
   is written without fresh data). The link is judged over a window, at every step and before
   anything above (X2): lost once stale steps cover five minutes within ten — a link fresh one
   step in five is still lost — and back once fresh for a minute without a break. Lost while
   controlling, control hands back once; it resumes by itself once the link is back. A stale
   step short of a loss only writes nothing; the next fresh step writes at once. Before control
   takes the boiler, the read-back that would show its hand-back must hold a value (P-21):
   until then nothing is written either.
5. Otherwise heating on or off, decided at every step from frost protection and the zones'
   demand — VT's central mode and summer or winter reach the plugin through the zones, and
   nothing counted or timed holds heating against VT; and the
   water temperature, decided every decision interval (and at once after any of the above ends):
   the curve on the effective outdoor temperature, limits and ramp. Without an outdoor
   temperature the fallback setpoint applies, with zones known. Decision 3 (``core.zone_watch``)
   decides what missing zone data means:
   - in the recognition period (after a start, or when every zone went away at once: VT
     reloading) nothing new is decided: the command held before — this session's, or the last
     one V3 stored, given again at once after a restart where the control unit found every
     condition for it — is kept with its keep-alives; without one nothing is written. Frost
     protection, which only adds heat, still acts for the zones already known;
   - a zone that went away keeps its last answer for ten minutes (its grace);
   - with every zone unknown after that, or no configured demand criterion that can be judged,
     nothing can ask for heat: a working thermostat — a gateway with an OpenTherm thermostat,
     or the boiler's own room controller where the user ticked it — is handed the boiler at
     once, without a latch; otherwise heating is off, with the water at the lowest temperature
     where no outdoor temperature is known — never the design flow. Either way control resumes
     by itself the step a zone answers again.

Zone signals only correct the curve (weather is counted once). The comfort correction follows the
rules of bounded learning: while a zone's valve is fully open (or at VT's cap) and its room is
still short of its setpoint, the water rises above the curve — at most 3 K, by 1 K per 30 minutes
and only while heat flows; it falls twice as fast once the zones with an opening are clearly
satisfied, or while another zone is more than 1 K too warm; a zone without an opening never
blocks the fall. It resets at hand-back and with a new session, and when it stays at 3 K for
hours the decision says so: the curve is probably too low. Every limit still applies. While the
boiler holds the water lower than the plugin asks (a clip, its own limit), the correction does
not rise: a clip is never learned as a limit.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
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
from .demand import Demand, DemandConfig, boiler_demand
from .limits import (
    FlowLimits,
    FrostConfig,
    LimitCode,
    frost_needed,
    limit_flow,
    watched_temperatures,
)
from .readings import ZoneState
from .zone_watch import ZoneWatch, follow_zones, graced, in_recognition

HOUR = 3600.0
CORRECTION_MAX_K = 3.0  # the firm band of the comfort correction
CORRECTION_RISE_S = 30 * 60.0  # seconds of heat flow per kelvin of rise; the fall is twice as fast
CORRECTION_LIMIT_S = 3 * HOUR  # at the band's edge this long: tell the user
MAX_STEP_S = 60.0  # the most heat flow a single step counts (a clock jumping forward)
OVERHEAT_K = 1.0  # a zone this far over its setpoint stops the rise
FROST_ALARM_S = 2 * HOUR  # frost heating this long without the room warming is reported
FROST_WARMING_K = 0.5  # the watched room must have warmed by this much
# A lasting outage — the plugin's own monitor failing (V6), the boiler link gone stale (X2) — is
# judged over a window: each check counts until the next one, at most ``MAX_STEP_S``; failed
# checks covering ``OUTAGE_LOST_S`` within the last ``OUTAGE_WINDOW_S`` are a loss, which ends
# once the checks have been good for ``OUTAGE_BACK_S`` without a break.
OUTAGE_LOST_S = 300.0  # decided: five minutes (the user's answer I; decision 7)
OUTAGE_WINDOW_S = 600.0  # provisional, K4
OUTAGE_BACK_S = 60.0  # provisional, K4
# The blocker "Home Assistant is starting": it does not stop a command kept or restored in the
# recognition period, which it keeps from ending (decision 3).
HA_STARTING = "ha_starting"


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
    READ_BACK_UNKNOWN = "read_back_unknown"  # nothing could show a hand-back got through
    OUTDOOR_SENSOR = "outdoor_sensor"
    OUTDOOR_WEATHER = "outdoor_weather"
    OUTDOOR_HELD = "outdoor_held"
    OUTDOOR_UNKNOWN = "outdoor_unknown"
    DEMAND = "demand"
    NO_DEMAND = "no_demand"
    ZONES_UNKNOWN = "zones_unknown"
    ZONES_RECOGNITION = "zones_recognition"  # the zones are still reporting: nothing new decided
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
class OutageWindow:
    """The checks of something that may fail or go stale, judged over a window: the plugin's own
    monitor (a refresh that failed; V6), the boiler link (a step without fresh data; X2)."""

    checks: tuple[tuple[float, bool], ...] = ()  # (time, bad) of each check that still counts
    lost: bool = False  # bad for five minutes within ten; stays until good for a minute
    lost_from: float | None = None  # the first bad moment in the window when the loss began
    good_since: float | None = None  # the first check of the current run of good ones


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
    # The boiler link is lost once its stale steps cover this long within the last
    # ``OUTAGE_WINDOW_S`` (X2): control then hands back. ``None``: never lost (tests, simulator).
    stale_hand_back_s: float | None = OUTAGE_LOST_S
    outdoor_time_constant_s: float = DEFAULT_TIME_CONSTANT_S
    outdoor_hold_s: float = DEFAULT_HOLD_S
    # Decision 3: with every zone unknown, a working thermostat is handed the boiler — a gateway
    # with an OpenTherm thermostat, or the boiler's own room controller where the user ticked
    # it (answers F, M); without one, the usual "off".
    working_thermostat: bool = False

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
    # X3's restore waits, within the recognition period, for a boiler link that has not reported
    # since the start: that silence declares no loss yet (X2) — a link not yet reported never
    # turns a restore into a hand-back.
    link_unreported: bool = False
    # The read-back that shows a hand-back got through holds a value: control takes the boiler
    # only with it (P-21, the gateway paths); once controlling, its loss decides nothing here.
    read_back_known: bool = True
    flame: bool | None = None
    dhw: bool | None = None
    outdoor_sensor: float | None = None
    outdoor_weather: float | None = None
    zones: Sequence[ZoneState] = ()  # every configured zone
    clipped: bool = False  # the boiler holds the water lower than asked: its own limit
    # Decision 3: the last command V3 stored, given again at once after a restart where the
    # control unit found every condition for it; kept with its keep-alives while the
    # recognition period runs. ``target_ready``: the write target can take it — until it can,
    # nothing is written.
    restored_command: BoilerCommand | None = None
    target_ready: bool = True


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
    # The boiler link over a window (X2): a sample at every step — stale or fresh — whether it is
    # lost, and since when it has been fresh. Kept through a hand-back and a new session (a fact
    # about the link, not the session); empty after a restart.
    link: OutageWindow = field(default_factory=OutageWindow)
    link_unreported: bool = False  # the last step's restore waited for a link not yet reported
    # The zones' recognition period and graces (decision 3): a fact about the zones, kept
    # through a hand-back and a new session; empty after a restart.
    zones: ZoneWatch = field(default_factory=ZoneWatch)


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
    link_lost: bool = False  # the boiler link is lost (X2): stale for five minutes within ten
    # Decision 3: every configured zone unknown after the recognition period and the graces;
    # the configured demand criteria no known zone can feed (both outside the recognition).
    zones_unknown: bool = False
    criteria_without_data: tuple[str, ...] = ()


def clock_start(since: float | None, now: float) -> float:
    """When a wait began. A start later than now means the wall clock was set back: the wait
    starts again now, rather than lasting until the clock has caught up (C9)."""
    return now if since is None or since > now else since


def clock_due(at: float, now: float, longest_s: float) -> float:
    """When a moment planned at most ``longest_s`` ahead is due. One further ahead means the wall
    clock was set back: it is due now, rather than once the clock has caught up (C9)."""
    return now if at - now > longest_s else at


def _spans(checks: Sequence[tuple[float, bool]], at: float) -> Iterator[tuple[float, float, bool]]:
    """Each check from its time until the next check — the last one until ``at`` — and at most
    ``MAX_STEP_S``: a source that goes quiet is not judged on its last check for ever."""
    for i, (t, bad) in enumerate(checks):
        end = checks[i + 1][0] if i + 1 < len(checks) else at
        yield t, min(end, t + MAX_STEP_S), bad


def bad_time(
    checks: Sequence[tuple[float, bool]], now: float, window_s: float = OUTAGE_WINDOW_S
) -> float:
    """The seconds within the last ``window_s`` that bad checks cover; none without checks."""
    start = now - window_s
    return sum(max(0.0, end - max(t, start)) for t, end, bad in _spans(checks, now) if bad)


def follow_outage(
    window: OutageWindow, now: float, bad: bool | None = None, lost_s: float = OUTAGE_LOST_S
) -> OutageWindow:
    """The window at ``now``, with a check made now (``bad``) or none (``None``: time passing).

    A loss begins once bad checks cover ``lost_s`` (``OUTAGE_LOST_S``) within the last
    ``OUTAGE_WINDOW_S`` — a source that keeps dropping out counts, not only one gone for good —
    and ends once the checks have been good for ``OUTAGE_BACK_S`` without a break; its checks are
    then cleared, so a single failure afterwards is no loss. No check yet counts as nothing bad.
    A check earlier than the last one means the wall clock was set back: the later ones go (C9);
    a moment taken just before the last check is judged at that check.
    """
    checks = window.checks
    good_since = window.good_since
    if bad is not None:
        checks = (*(check for check in checks if check[0] <= now), (now, bad))
        if bad:
            good_since = None
        elif good_since is None or good_since > now:
            good_since = now
    at = max(now, checks[-1][0]) if checks else now
    start = at - OUTAGE_WINDOW_S
    checks = tuple(check for check in checks if check[0] > start - MAX_STEP_S)
    if window.lost:
        if good_since is not None and at - good_since >= OUTAGE_BACK_S:
            return OutageWindow(good_since=good_since)
        return replace(window, checks=checks, good_since=good_since)
    if bad_time(checks, at) >= lost_s:
        spans = _spans(checks, at)
        first = min(max(t, start) for t, end, failed in spans if failed and end > start)
        return OutageWindow(checks, True, first, good_since)
    return OutageWindow(checks, False, None, good_since)


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


def follow_link(state: ControlState, inputs: ControlInputs, config: ControlConfig) -> OutageWindow:
    """The boiler link's window after this step (X2): the step is a sample, stale where the
    boiler's signals are not fresh. The link is lost once stale samples cover
    ``stale_hand_back_s`` within the last ``OUTAGE_WINDOW_S``, and back once fresh for
    ``OUTAGE_BACK_S`` without a break (``follow_outage``).

    While X3's restore waits for a link not yet reported since the start, no loss is declared.
    Once the link reports, that silence is forgotten — it was no staleness; still silent when
    the wait ends, the samples since the start count as stale, so it is lost at once where they
    cover the limit.
    """
    stale = not inputs.boiler_link
    window = state.link
    if state.link_unreported and not inputs.link_unreported and not stale:
        window = OutageWindow()  # it has reported: the wait's silence was no staleness
    limit = config.stale_hand_back_s
    if limit is None or inputs.link_unreported:
        limit = math.inf
    return follow_outage(window, inputs.now, stale, lost_s=limit)


def decide(
    state: ControlState, inputs: ControlInputs, config: ControlConfig
) -> tuple[ControlState, ControlDecision]:
    """One tick of the controller. The boiler link and the zones are followed first, at every
    step — switched off, latched or blocked alike — and every decision says whether the link is
    lost (X2) and whether every zone is unknown or a criterion has no data (decision 3)."""
    now = inputs.now
    outdoor = update_outdoor(
        state.outdoor,
        inputs.outdoor_sensor,
        inputs.outdoor_weather,
        now,
        config.outdoor_time_constant_s,
        config.outdoor_hold_s,
    )
    link = follow_link(state, inputs, config)
    watch = follow_zones(
        state.zones,
        inputs.zones,
        now,
        config.zone_max_age_s,
        starting=HA_STARTING in inputs.blockers,
    )
    state = replace(
        state, outdoor=outdoor, link=link, link_unreported=inputs.link_unreported, zones=watch
    )
    recognition = in_recognition(watch)
    demand = boiler_demand(
        inputs.zones,
        now,
        config.zone_max_age_s,
        config.demand,
        memory=graced(watch),
        recognition=recognition,
    )
    state, decision = _decide(state, inputs, config, demand)
    return state, replace(
        decision,
        link_lost=link.lost,
        zones_unknown=not recognition and bool(inputs.zones) and demand.fresh_zones == 0,
        criteria_without_data=() if recognition else demand.criteria_without_data,
    )


def _decide(
    state: ControlState, inputs: ControlInputs, config: ControlConfig, demand: Demand
) -> tuple[ControlState, ControlDecision]:
    now = inputs.now
    if not inputs.enabled:
        return _release(state, ControlMode.DISABLED, Reason.CONTROL_OFF)
    if state.latched or inputs.hand_back_alarms:
        # Before the blockers (P-48): an alarm set to hand back latches whatever they show.
        latched_by = state.latched_by if state.latched else tuple(inputs.hand_back_alarms)
        state = replace(state, latched=True, latched_by=latched_by)
        return _release(state, ControlMode.HANDED_BACK, Reason.ALARM_HAND_BACK)
    recognition = in_recognition(state.zones)
    held = state.command if state.controlling else inputs.restored_command
    # Home Assistant starting alone does not stop a command kept or restored meanwhile.
    keeps = recognition and held is not None and set(inputs.blockers) <= {HA_STARTING}
    if inputs.blockers and not keeps:
        return _release(state, ControlMode.NOT_ALLOWED, Reason.PRECONDITION)
    if state.link.lost and state.controlling:
        # Stale for five minutes within ten, a flapping link included (P-08): hand back once;
        # control resumes by itself once the link has been fresh for a minute.
        return _release(state, ControlMode.HANDED_BACK, Reason.BOILER_LINK_STALE)
    if state.link.lost or not inputs.boiler_link:
        # Nothing is written without fresh data. A stale step short of a loss keeps control: the
        # next fresh step writes at once.
        reasons = (Reason.BOILER_LINK_STALE,)
        # Once handed back for a lost link, that stays what is shown until the link is back.
        mode = (
            ControlMode.HANDED_BACK
            if not state.controlling and state.mode is ControlMode.HANDED_BACK
            else ControlMode.WAITING_DATA
        )
        waiting = replace(state, mode=mode, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(mode, None, reasons=reasons)
    if not state.controlling and not inputs.read_back_known:
        # A boiler taken now could never be seen handed back: nothing is written yet (P-21).
        reasons = (Reason.READ_BACK_UNKNOWN,)
        waiting = replace(state, mode=ControlMode.WAITING_DATA, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(ControlMode.WAITING_DATA, None, reasons=reasons)

    max_age = config.zone_max_age_s
    watched = [z for z in inputs.zones if not recognition or z.is_known(now, max_age, True)]
    frost = frost_needed(watched, now, max_age, state.frost, config.frost)
    if not frost:
        if recognition:
            if not state.controlling and not inputs.target_ready:
                held = None  # the restored command waits for its write target
            return _keep(state, now, held)
        if (
            inputs.restored_command is not None
            and not state.controlling
            and not inputs.target_ready
        ):
            # The recognition period ended while the restored command still waited for its write
            # target: nothing new this step — the owed hand-back goes first; the next step
            # decides. (Everything there, control simply decides anew.)
            return _keep(state, now, None)
        if demand.wanted is None and config.working_thermostat:
            # Nothing can ask for heat: the working thermostat takes the boiler — no latch.
            return _release(state, ControlMode.HANDED_BACK, Reason.ZONES_UNKNOWN)
    return _heating_decision(state, inputs, config, frost, demand)


def _keep(
    state: ControlState, now: float, held: BoilerCommand | None
) -> tuple[ControlState, ControlDecision]:
    """The recognition period: nothing new is decided. The command held before goes on, with
    its keep-alives; without one nothing is written."""
    reasons = (Reason.ZONES_RECOGNITION,)
    if held is None:
        waiting = replace(state, mode=ControlMode.WAITING_DATA, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(ControlMode.WAITING_DATA, None, reasons=reasons)
    mode = ControlMode.HEATING if held.ch_enable else ControlMode.IDLE
    target = state.target if state.controlling else held.setpoint
    kept = replace(
        state,
        mode=mode,
        controlling=True,
        frost=False,
        frost_since=None,
        frost_from=None,
        command=held,
        target=target,
        reasons=reasons,
        last_step_at=now,
    )
    return kept, ControlDecision(mode, held, reasons=reasons, target=target)


def _heating_decision(
    state: ControlState,
    inputs: ControlInputs,
    config: ControlConfig,
    frost: bool,
    demand: Demand,
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
    want_heat, heat_reason = _want_heat(demand, frost)
    # Decision 3's "off": every zone unknown, or no criterion that can be judged, and no working
    # thermostat to hand the boiler to — nothing asks for heat.
    nobody_asks = not frost and demand.wanted is None
    if want_heat and not inputs.dhw:
        # Heat flow counts a minute a step at most: a wall clock jumping forward must not count
        # an hour of it, which would raise the comfort correction past its rate at once.
        state = replace(state, heat_s=state.heat_s + min(MAX_STEP_S, step_s))
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

    prior_target, prior_upper = state.target, state.upper
    due = (
        state.decided_at is None
        or state.command is None
        or prior_target is None
        or prior_upper is None
        or state.decided_at > now  # the wall clock was set back: decided again now (C9)
        or now - state.decided_at >= config.decision_interval_s
        or frost != state.frost
        # Nothing asks for heat and no outdoor temperature: the lowest water temperature at
        # once — never a fallback decided before (decision 3).
        or (nobody_asks and outdoor.effective is None)
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
        if outdoor.effective is not None:
            curve_value = config.curve.flow(outdoor.effective)
        elif nobody_asks:
            curve_value = config.limits.hard_min  # the fallback serves only with zones known
        else:
            curve_value = fallback_setpoint(config)
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
    elif nobody_asks:
        mode = ControlMode.IDLE
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


def _want_heat(demand: Demand, frost: bool) -> tuple[bool, Reason]:
    """Whether to heat now and why: frost protection, else the zones' demand — VT's central mode
    and summer or winter act on the zones themselves. Demand unknown asks for nothing (decision
    3): heating off, or the working thermostat's, before this."""
    if frost:
        return True, Reason.FROST
    if demand.wanted is None:
        return False, Reason.ZONES_UNKNOWN
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
        # A decision later than now (the wall clock set back) counts as made now (C9).
        elapsed = max(0.0, now - state.decided_at) if state.decided_at is not None else 0.0
        correction -= 2.0 * elapsed / CORRECTION_RISE_S
    elif short and not inputs.clipped:
        # Only while heat flows; never while the boiler holds the water lower than asked.
        correction += state.heat_s / CORRECTION_RISE_S
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
