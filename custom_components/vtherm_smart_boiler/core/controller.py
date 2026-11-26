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
5. The boiler reports its own fault that stops it — its low-water-pressure fault, or another
   fault the user mapped as stopping it — held five minutes on the control clock (Y1, boiler
   protection; ``ControlInputs.boiler_fault``): the usual "off" — heating off, the water as
   decided; the relay off — with no hand-back and no latch, as the boiler cannot heat. It ends
   in the step the fault reads off, unknown or unavailable. In the recognition period it takes
   nothing new: a command held goes on as "off", none is written.
6. Otherwise heating on or off, decided at every step from VT's decision — VT's central boiler,
   with its own thresholds and activation delay, switches a helper the plugin follows (I12,
   ``ControlInputs.vt_heat``), and nothing counted or timed here holds heating against it; and
   the water temperature, decided every decision interval (and at once after any of the above
   ends): the curve on the effective outdoor temperature, limits and ramp. Without an outdoor
   temperature the last one holds three hours, then the fallback setpoint applies (decision 9),
   with zones known; FALLBACK is shown only while heating is wanted. Frost protection is VT's
   (I12, decision 4): its frost preset and central mode make the rooms call, and its central
   boiler turns the helper on. Decision 3 (``core.zone_watch``) decides what missing zone data
   means:
   - in the recognition period (after a start, or when every zone went away at once: VT
     reloading) nothing new is decided: the command held before — this session's, or the last
     one V3 stored, given again at once after a restart where the control unit found every
     condition for it — is kept with its keep-alives; without one nothing is written;
   - a zone that went away keeps its last answer for ten minutes (its grace);
   - with every zone unknown after that, or VT's decision unknown (its helper neither on nor
     off), nothing can ask for heat: a working thermostat — a gateway with an OpenTherm thermostat,
     or the boiler's own room controller where the user ticked it — is handed the boiler at
     once, without a latch; otherwise heating is off, with the water at the lowest temperature
     where no outdoor temperature is known — never the design flow. Either way control resumes
     by itself the step a zone answers again.

VT's activation delay is VT's own (I12): while VT's central boiler waits it out — its event said
so and the helper is still off (``ControlInputs.vt_delay``) — "off" carries the reason
``activation_delay``; nothing is held or timed here.

Zone signals only correct the curve (weather is counted once). A room's temperature judges it only
while trusted (I12, decision 8; ``core.zones.room_trusted``): not in VT's safety mode, its
thermometer available, and measured since the plugin started. The comfort correction follows the
rules of bounded learning (principle 13), each mapped:

1. Band: 0 to +3 K.
2. Rate: +1 K per 30 min of heat flow, so at most 2 K an hour; at most +3 K of rise within 24 h
   (provisional, K4).
3. Other criteria: the rise only for a saturated zone short of its setpoint (comfort); none while
   another zone taking heat — an opening above 5 % or its device on — is more than 1 K too warm
   (S-08); cycling not rising: the rise only while the boiler's heating starts since it began
   are no more than in the same hours before it began, stepping back (the fall) while they are
   more, no rise with the starts unknown (``core.comfort_rules``, decision 11 of 0.2.3); every
   limit kept: no rise while an upper cap (the hard maximum, the circuit's, the boiler's) or a
   clip holds the setpoint, the "at limit" timer paused meanwhile (S-25,
   T-48); stepping back: the fall.
4. Good enough: the rise stops once no zone is 0.3 K short.
5. Freezes: hot water — neither rise nor fall; data gaps — held while the link is stale or no
   zone is known; hand-back — reset; extreme weather — the outdoor reading below the design
   outdoor temperature or changing faster than 2 K per hour, or unknown (``core.comfort_rules``,
   decision 11 of 0.2.3).
6. At the edge: "at limit" after 3 h at 3 K.
7. Visible and resettable: published with each decision (the control state, diagnostics); reset
   at hand-back, at a session's end and by the user (``reset_correction``, the "Reset comfort
   correction" button, answer J).

On/off control through a relay (class 3, X8; ``ControlConfig.on_off``) decides heating on or off
by the same rules — VT's decision, the recognition and grace periods and decision 3 — without a
water temperature: the boiler sets its own, so the curve, limits, ramp and comfort correction do
not apply, no outdoor temperature is needed, and FALLBACK never shows. Its link is the relay
itself: the control unit keeps ``boiler_link`` true and ``stale_hand_back_s`` unset there, and the
relay rule (``core.relay``) judges its reach.

"Heat flows" (S-24) is the flame burning without hot water; with the flame unknown, heating
commanded without hot water. The rise and the fall count the steps' time, each step a minute at
most and never a negative one (P-46): a clock set back moves nothing. The fall is twice as fast
as the rise, once the zones with an opening are clearly satisfied or a zone taking heat is too
warm; a zone without an opening never blocks the fall. A clip is never learned as a limit.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .circuit_requests import CircuitsAsking, OtherAutomation, circuits_asking
from .comfort_rules import (
    Readings,
    StartsBaseline,
    extreme_weather,
    follow_baseline,
    follow_outdoor,
    may_rise,
    starts_rose,
)
from .curve import (
    DEFAULT_HOLD_S,
    DEFAULT_TIME_CONSTANT_S,
    HeatingCurve,
    OutdoorSource,
    OutdoorState,
    auto_room,
    update_outdoor,
)
from .demand import Demand, boiler_demand, zone_wants_heat
from .limits import FlowLimits, LimitCode, install_cap, limit_flow
from .readings import ZONE_OPEN, ZoneState
from .zone_watch import ZoneWatch, follow_zones, graced, in_recognition, unjudged_since

HOUR = 3600.0
DAY = 24 * HOUR
CORRECTION_MAX_K = 3.0  # the correction's limit by default; the user's, 0.5 to 10 K (G11)
CORRECTION_RISE_S = 30 * 60.0  # seconds of heat flow per kelvin of rise; the fall is twice as fast
CORRECTION_LIMIT_S = 3 * HOUR  # at the band's edge this long: tell the user
CORRECTION_DAY_K = 3.0  # at most this much rise within 24 h (principle 13 (2); provisional, K4)
# The most time a single step counts — heat flow, the correction's fall — so a clock jumping
# forward counts a minute at most.
MAX_STEP_S = 60.0
OVERHEAT_K = 1.0  # a zone this far over its setpoint stops the rise
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
# The blocker "VT's central boiler settings not known yet" (I12): no thermostat handed over yet,
# as at every start until VT starts its thermostats. Like Home Assistant starting, it does not stop
# a command kept or restored in the recognition period, but it does not keep that period going.
VT_SETTINGS_UNKNOWN = "vt_central_boiler_unknown"
KEPT_IN_RECOGNITION = frozenset({HA_STARTING, VT_SETTINGS_UNKNOWN})


class ControlMode(StrEnum):
    DISABLED = "disabled"
    NOT_ALLOWED = "not_allowed"
    HANDED_BACK = "handed_back"
    WAITING_DATA = "waiting_data"
    HEATING = "heating"
    IDLE = "idle"
    FALLBACK = "fallback"
    BOILER_FAULT = "boiler_fault"  # the boiler reports its own fault: heating off (Y1)


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
    RAMP = "ramp"
    LIMIT_HARD_MIN = "limit_hard_min"
    LIMIT_HARD_MAX = "limit_hard_max"
    LIMIT_CIRCUIT_MAX = "limit_circuit_max"
    LIMIT_BOILER_MAX = "limit_boiler_max"
    COMFORT_CORRECTION = "comfort_correction"
    ACTIVATION_DELAY = "activation_delay"  # VT's central boiler waits its activation delay
    BOILER_FAULT = "boiler_fault"  # the boiler reports its own fault that stops it (Y1)
    # I8 (decision F3): a circuit run by other automation asks for heat; one cannot say
    # (its entity unreadable: it does not ask, the user's answer of 2026-10-12); its need
    # holds the water.
    CIRCUIT_ASKS = "circuit_asks"
    CIRCUIT_REQUEST_UNKNOWN = "circuit_request_unknown"
    LIMIT_CIRCUIT_NEED = "limit_circuit_need"


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
    LimitCode.CIRCUIT_NEED: Reason.LIMIT_CIRCUIT_NEED,
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
    # I8 (decisions F3, F6): circuits run by other automation — they ask for heat, and while
    # asking hold the water at their need at least; and the zones of the circuit the curve serves
    # (the one fed straight from the boiler), which its comfort correction, room and short
    # rooms read — ``None``: every zone.
    other_automation: tuple[OtherAutomation, ...] = ()
    curve_zones: frozenset[str] | None = None
    fallback_setpoint: float | None = None  # None: the curve at its design point
    ramp_k_per_min: float | None = 1.0  # None: no ramp
    decision_interval_s: float = 300.0
    # One freshness rule (O1): a steady reading is not a stale one. VT reports when its room
    # sensor last changed, which a steady room does not do for hours; a zone is unknown by its
    # state (unavailable, not started), and a room sensor gone quiet is VT's own safety mode's.
    zone_max_age_s: float | None = None
    # Off by default (K4, the user's decision of 2026-11-17, reversing G11 B); the option's
    # default lives in the options, the core's own serves tests and the bare config.
    comfort_correction: bool = False
    correction_max_k: float = CORRECTION_MAX_K  # its limit, the user's (G11 B)
    # The curve's room temperature (G11 D): Auto follows the warmest setpoint among the zones
    # that heat, but those left out; Manual (``False``) keeps ``curve.room``, the value entered.
    room_auto: bool = False
    room_excluded: frozenset[str] = frozenset()
    # The boiler link is lost once its stale steps cover this long within the last
    # ``OUTAGE_WINDOW_S`` (X2): control then hands back. ``None``: never lost (tests, simulator).
    stale_hand_back_s: float | None = OUTAGE_LOST_S
    outdoor_time_constant_s: float = DEFAULT_TIME_CONSTANT_S
    outdoor_hold_s: float = DEFAULT_HOLD_S
    # Decision 3: with every zone unknown, a working thermostat is handed the boiler — a gateway
    # with an OpenTherm thermostat, or the boiler's own room controller where the user ticked
    # it (answers F, M); without one, the usual "off".
    working_thermostat: bool = False
    # On/off control through a relay (class 3, X8): heating on or off only — no water
    # temperature, so the curve, the limits, the ramp and the comfort correction do not apply,
    # the outdoor temperature is not needed, and FALLBACK never shows.
    on_off: bool = False

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
    # VT's decision (I12): its central boiler's helper on (heat), off (not), or neither — not
    # known, which counts as nothing asking (decision 3). And whether VT's central boiler waits
    # its activation delay now: its event said so and the helper is still off.
    vt_heat: bool | None = None
    vt_delay: bool = False
    clipped: bool = False  # the boiler holds the water lower than asked: its own limit
    # The boiler's heating starts within ``comfort_rules.STARTS_WINDOW_S`` up to ``now``
    # (``comfort_rules.heating_starts``), for the comfort correction's rule 3. ``None``: not
    # known — the correction does not rise.
    starts: tuple[float, ...] | None = None
    # Decision 3: the last command V3 stored, given again at once after a restart where the
    # control unit found every condition for it; kept with its keep-alives while the
    # recognition period runs. ``target_ready``: the write target can take it — until it can,
    # nothing is written.
    restored_command: BoilerCommand | None = None
    target_ready: bool = True
    # Boiler protection (Y1): the boiler has reported its own fault that stops it for five
    # minutes — the control unit holds it on its clock; an unknown fault counts as none.
    boiler_fault: bool = False
    # I8 (decision F3): each circuit run by other automation's request (``None``: unreadable)
    # and need as their entities read now (``None``: unreadable, the value entered then).
    circuit_requests: Mapping[str, bool | None] = field(default_factory=dict)
    circuit_needs: Mapping[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BoilerCommand:
    ch_enable: bool
    setpoint: float | None  # None: on/off control through a relay sets no water temperature


@dataclass(frozen=True, slots=True)
class ControlState:
    mode: ControlMode = ControlMode.DISABLED
    controlling: bool = False  # commands were given and control has not been handed back
    latched: bool = False  # an alarm handed back; stays for the session
    latched_by: tuple[str, ...] = ()  # the alarms that set the latch
    outdoor: OutdoorState = field(default_factory=OutdoorState)
    command: BoilerCommand | None = None
    target: float | None = None
    reasons: tuple[Reason, ...] = ()
    water_reasons: tuple[Reason, ...] = ()  # why the water temperature is what it is
    decided_at: float | None = None  # when the water temperature was last decided
    correction: float = 0.0  # K added to the curve for a zone that cannot reach its setpoint
    curve_room: float | None = None  # the curve's room temperature at the last water decision
    heat_s: float = 0.0  # seconds heat has flowed since the last water decision
    water_s: float = 0.0  # seconds counted since the last water decision (P-46)
    last_step_at: float | None = None
    upper: float | None = None  # the highest setpoint the limits allow, at the last decision
    circuit_need: float | None = None  # the circuits' need held then (I8, F3): its change decides
    correction_limit_s: float = 0.0  # seconds at the band's edge, a cap's time left out
    # The last water decision found the correction as high as it may go: at its limit, or a
    # room short with the day's rise spent (L13).
    correction_at_top: bool = False
    # The correction's rises within the last day, (time, K): at most ``CORRECTION_DAY_K``. Kept
    # through a hand-back (the day's rate is not reset by one); a new session starts afresh.
    rises: tuple[tuple[float, float], ...] = ()
    # Rule 3 (decision 11 of 0.2.3): when the correction began and the starts before it; kept
    # through a hand-back, a reset and a new session until it has stayed at 0 for the window.
    starts_baseline: StartsBaseline | None = None
    # Rule 5: the outdoor readings of the last hour, at every step — a fact about the weather,
    # kept through a hand-back and a new session; empty after a restart.
    outdoor_seen: Readings = ()
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
    correction_at_limit: bool = False  # the correction at its band's edge for hours: tell the user
    # The rooms fully open and short now — the ones the correction rises for, named by the
    # "curve too low" warning at its limit (G11 B).
    short_zones: tuple[str, ...] = ()
    # More than half of the rooms judged are short: the curve first among the warning's causes;
    # fewer, the room's radiator and its heat loss first (G11, addition 3).
    most_short: bool = False
    curve_room: float | None = None  # the curve's room temperature the water was decided with
    link_lost: bool = False  # the boiler link is lost (X2): stale for five minutes within ten
    # Decision 3: every configured zone unknown after the recognition period and the graces;
    # the zones known but VT's decision unknown (PB-03, I12) — both outside the recognition
    # period.
    zones_unknown: bool = False
    vt_unknown: bool = False
    correction: float = 0.0  # the comfort correction
    # Decision 2 of 0.2.3 (SB-01): VT asks for heat — at every step; "no sign the boiler heats"
    # counts only then.
    calling: bool = False
    # The demand at this step: VT's decision and the zones that call.
    demand: Demand | None = None


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
    session learned (the comfort correction) goes. The day's rises stay: a hand-back does not
    reset the correction's daily rate."""
    new_state = replace(
        state,
        mode=mode,
        controlling=False,
        command=None,
        reasons=(reason,),
        decided_at=None,
        correction=0.0,
        heat_s=0.0,
        water_s=0.0,
        last_step_at=None,
        correction_limit_s=0.0,
        correction_at_top=False,
    )
    return new_state, ControlDecision(mode, None, hand_back=state.controlling, reasons=(reason,))


def reset_correction(state: ControlState) -> ControlState:
    """The user resets the comfort correction (answer J): 0 at once, its "at limit" timer and
    the heat flow counted towards a rise cleared, and the water decided anew at the next step.
    Nothing is handed back and nothing else changes; the rise may start again under its rules
    — the day's rises still count (principle 13's daily rate)."""
    return replace(
        state,
        correction=0.0,
        heat_s=0.0,
        water_s=0.0,
        correction_limit_s=0.0,
        correction_at_top=False,
        decided_at=None,
        last_step_at=None,
    )


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
    lost (X2) and whether every zone or VT's decision is unknown (decision 3)."""
    now = inputs.now
    outdoor = update_outdoor(
        state.outdoor,
        inputs.outdoor_sensor,
        inputs.outdoor_weather,
        now,
        config.outdoor_time_constant_s,
        config.outdoor_hold_s,
    )
    seen = follow_outdoor(state.outdoor_seen, _outdoor_reading(inputs), now)
    link = follow_link(state, inputs, config)
    watch = follow_zones(
        state.zones,
        inputs.zones,
        now,
        config.zone_max_age_s,
        starting=HA_STARTING in inputs.blockers,
    )
    state = replace(
        state,
        outdoor=outdoor,
        outdoor_seen=seen,
        link=link,
        link_unreported=inputs.link_unreported,
        zones=watch,
    )
    recognition = in_recognition(watch)
    demand = boiler_demand(
        inputs.zones, now, config.zone_max_age_s, inputs.vt_heat, memory=graced(watch)
    )
    # PB-03, I12: the zones known, and VT's decision unknown — decision 3's end state too, and
    # since when, for its repair issue; held through a recognition period.
    unjudged = not recognition and demand.wanted is None and demand.fresh_zones > 0
    if not recognition:
        watch = replace(watch, unjudged_since=unjudged_since(watch.unjudged_since, unjudged, now))
        state = replace(state, zones=watch)
    state, decision = _decide(state, inputs, config, demand)
    return state, replace(
        decision,
        link_lost=link.lost,
        zones_unknown=not recognition and bool(inputs.zones) and demand.fresh_zones == 0,
        vt_unknown=unjudged,
        correction=state.correction,
        calling=demand.wanted is True,
        demand=demand,
    )


def _decide(
    state: ControlState, inputs: ControlInputs, config: ControlConfig, demand: Demand
) -> tuple[ControlState, ControlDecision]:
    """Whether control may decide at all — switched off, a latch, the blockers, the boiler
    link, the read-back, in that order — then a boiler fault, the recognition period and
    decision 3's end state, then the heating decision (the table in
    ``tests/core/test_controller.py`` pins the order, P-115)."""
    stopped = _stopped(state, inputs)
    if stopped is not None:
        return stopped
    waiting = _waiting_for_data(state, inputs)
    if waiting is not None:
        return waiting
    now = inputs.now
    recognition = in_recognition(state.zones)
    if inputs.boiler_fault:
        # Boiler protection (Y1): the usual "off" while the boiler reports its own fault; no
        # hand-back, no latch.
        if recognition:
            held = _held(state, inputs)
            off = None if held is None else replace(held, ch_enable=False)
            return _keep(state, now, off, fault=True)
        return _heating_decision(state, inputs, config, demand, fault=True)
    nothing_new = _nothing_new(state, inputs, config, demand, recognition)
    if nothing_new is not None:
        return nothing_new
    return _heating_decision(state, inputs, config, demand)


def _stopped(
    state: ControlState, inputs: ControlInputs
) -> tuple[ControlState, ControlDecision] | None:
    """Switched off; a latch, or an alarm set to hand back — before the blockers (P-48); the
    blockers, but for Home Assistant starting or VT's settings not known yet alone while a command
    is kept or restored. ``None`` where none of them stops control."""
    if not inputs.enabled:
        return _release(state, ControlMode.DISABLED, Reason.CONTROL_OFF)
    if state.latched or inputs.hand_back_alarms:
        # An alarm set to hand back latches whatever the blockers show.
        latched_by = state.latched_by if state.latched else tuple(inputs.hand_back_alarms)
        state = replace(state, latched=True, latched_by=latched_by)
        return _release(state, ControlMode.HANDED_BACK, Reason.ALARM_HAND_BACK)
    # Home Assistant starting, or VT's settings not known yet, alone does not stop a command
    # kept or restored meanwhile.
    held = state.command if state.controlling else inputs.restored_command
    keeps = in_recognition(state.zones) and held is not None
    if inputs.blockers and not (keeps and set(inputs.blockers) <= KEPT_IN_RECOGNITION):
        return _release(state, ControlMode.NOT_ALLOWED, Reason.PRECONDITION)
    return None


def _waiting_for_data(
    state: ControlState, inputs: ControlInputs
) -> tuple[ControlState, ControlDecision] | None:
    """The boiler link lost while controlling hands back; a stale link, or a read-back unknown
    before the take, writes nothing yet. ``None`` with fresh data."""
    if state.link.lost and state.controlling:
        # Stale for five minutes within ten, a flapping link included (P-08): hand back once;
        # control resumes by itself once the link has been fresh for a minute.
        return _release(state, ControlMode.HANDED_BACK, Reason.BOILER_LINK_STALE)
    if state.link.lost or not inputs.boiler_link:
        # Nothing is written without fresh data. A stale step short of a loss keeps control: the
        # next fresh step writes at once.
        reasons = (Reason.BOILER_LINK_STALE,)
        # Once handed back for a lost link, that stays what is shown until the link is back; a
        # link lost when control is switched on shows it at once (decision 7, Y1): control does
        # not start writing until the link has been fresh for a minute.
        handed_back = state.link.lost or state.mode is ControlMode.HANDED_BACK
        mode = (
            ControlMode.HANDED_BACK
            if not state.controlling and handed_back
            else ControlMode.WAITING_DATA
        )
        waiting = replace(state, mode=mode, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(mode, None, reasons=reasons)
    if not state.controlling and not inputs.read_back_known:
        # A boiler taken now could never be seen handed back: nothing is written yet (P-21).
        reasons = (Reason.READ_BACK_UNKNOWN,)
        waiting = replace(state, mode=ControlMode.WAITING_DATA, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(ControlMode.WAITING_DATA, None, reasons=reasons)
    return None


def _held(state: ControlState, inputs: ControlInputs) -> BoilerCommand | None:
    """The command held: this session's, else the one restored — which waits for its write
    target."""
    if state.controlling:
        return state.command
    return inputs.restored_command if inputs.target_ready else None


def _nothing_new(
    state: ControlState,
    inputs: ControlInputs,
    config: ControlConfig,
    demand: Demand,
    recognition: bool,
) -> tuple[ControlState, ControlDecision] | None:
    """The recognition period keeps what is held and decides nothing new; a restored command
    still waiting for its write target when it ends gives way this step; and nothing that can ask
    for heat hands the boiler to a working thermostat (decision 3). ``None``: the heating
    decision follows."""
    now = inputs.now
    if recognition:
        return _keep(state, now, _held(state, inputs))
    if inputs.restored_command is not None and not state.controlling and not inputs.target_ready:
        # The recognition period ended while the restored command still waited for its write
        # target: nothing new this step — the owed hand-back goes first; the next step
        # decides. (Everything there, control simply decides anew.)
        return _keep(state, now, None)
    if demand.wanted is None and config.working_thermostat:
        # Nothing can ask for heat: the working thermostat takes the boiler — no latch.
        return _release(state, ControlMode.HANDED_BACK, Reason.ZONES_UNKNOWN)
    return None


def _keep(
    state: ControlState, now: float, held: BoilerCommand | None, *, fault: bool = False
) -> tuple[ControlState, ControlDecision]:
    """The recognition period: nothing new is decided. The command held before goes on, with
    its keep-alives; without one nothing is written. ``fault``: the boiler reports its own
    fault — the command held goes on as "off" (Y1)."""
    reasons: tuple[Reason, ...] = (Reason.ZONES_RECOGNITION,)
    if fault:
        reasons = (*reasons, Reason.BOILER_FAULT)
    if held is None:
        waiting = replace(state, mode=ControlMode.WAITING_DATA, reasons=reasons, decided_at=None)
        return waiting, ControlDecision(ControlMode.WAITING_DATA, None, reasons=reasons)
    mode = ControlMode.HEATING if held.ch_enable else ControlMode.IDLE
    if fault:
        mode = ControlMode.BOILER_FAULT
    target = state.target if state.controlling else held.setpoint
    kept = replace(
        state,
        mode=mode,
        controlling=True,
        command=held,
        target=target,
        reasons=reasons,
        last_step_at=now,
    )
    return kept, ControlDecision(mode, held, reasons=reasons, target=target)


def _water_due(state: ControlState, now: float, config: ControlConfig, lowest_now: bool) -> bool:
    """Whether the water temperature is decided anew this step: nothing decided yet, the
    decision interval passed — or the wall clock set back (C9) — or (``lowest_now``) nothing
    asking for heat without an outdoor temperature, which takes the lowest water temperature at
    once, never a fallback decided before (decision 3)."""
    decided_at = state.decided_at
    return (
        decided_at is None
        or state.command is None
        or state.target is None
        or state.upper is None
        or decided_at > now
        or now - decided_at >= config.decision_interval_s
        or lowest_now
    )


def _heating_mode(fault: bool, want_heat: bool, outdoor_unknown: bool) -> ControlMode:
    """A boiler fault before heating; FALLBACK only while heating is wanted without an outdoor
    temperature (P-47)."""
    if fault:
        return ControlMode.BOILER_FAULT
    if want_heat:
        return ControlMode.FALLBACK if outdoor_unknown else ControlMode.HEATING
    return ControlMode.IDLE


def _heating_decision(
    state: ControlState,
    inputs: ControlInputs,
    config: ControlConfig,
    demand: Demand,
    *,
    fault: bool = False,
) -> tuple[ControlState, ControlDecision]:
    """Heating on or off at every step, and the water temperature every decision interval.
    ``fault``: the boiler reports its own fault that stops it — heating off, the water decided as
    usual (Y1)."""
    if config.on_off:
        return _on_off_decision(state, inputs, config, demand, fault=fault)
    now = inputs.now
    outdoor = state.outdoor
    # Only time under a command of the plugin's counts.
    step_s = (
        0.0
        if state.last_step_at is None or state.command is None
        else max(0.0, now - state.last_step_at)
    )
    # A step counts a minute at most: a wall clock jumping forward must not count an hour of
    # heat flow or of fall, which would move the comfort correction past its rate at once.
    counted_s = min(MAX_STEP_S, step_s)
    asks = _circuits(inputs, config)
    want_heat, heat_reason = _want_heat(demand, fault, bool(asks.asking))
    waiting = _vt_waits(inputs, want_heat)
    # Decision 3's "off": every zone unknown, or VT's decision unknown, and no working thermostat
    # to hand the boiler to — nothing asks for heat.
    nobody_asks = demand.wanted is None and not asks.asking
    dhw = inputs.dhw is True
    # "Heat flows" (S-24): the flame burning without hot water; the flame unknown, heating
    # commanded without hot water.
    flows = (inputs.flame if inputs.flame is not None else want_heat) and not dhw
    state = replace(
        state,
        heat_s=state.heat_s + (counted_s if flows else 0.0),
        water_s=state.water_s + counted_s,
        last_step_at=now,
    )

    prior_target, prior_upper = state.target, state.upper
    # A circuit's need changing — one starting or ending to ask — is decided at once (I8, F3).
    need_changed = asks.floor != state.circuit_need
    lowest_now = nobody_asks and outdoor.effective is None
    if need_changed or _water_due(state, now, config, lowest_now):
        water: list[Reason] = [_OUTDOOR_REASON[outdoor.source]]
        room = _curve_room(state, inputs, config)
        state = replace(state, curve_room=room)
        if outdoor.effective is not None:
            curve_value = replace(config.curve, room=room).flow(outdoor.effective)
        elif nobody_asks:
            curve_value = config.limits.hard_min  # the fallback serves only with zones known
        else:
            curve_value = fallback_setpoint(config)
        upper = limit_flow(1e6, config.limits, config.circuit_max, config.boiler_max).value
        state = replace(state, circuit_need=asks.floor)
        # An upper cap — the hard maximum, the circuit's, the boiler's — or a clip holds the
        # setpoint: a rise could not show, so it is not learned (S-25).
        held = inputs.clipped or curve_value + state.correction >= upper - _EPSILON
        correction, rises, baseline = _correction(state, inputs, config, held)
        top = correction >= config.correction_max_k or (
            config.comfort_correction and _day_spent(rises) and bool(_short_zones(inputs, config))
        )
        state = replace(
            state,
            heat_s=0.0,
            water_s=0.0,
            rises=rises,
            starts_baseline=baseline,
            correction_limit_s=_limit_time(state, top, held),
            correction_at_top=top,
        )
        if correction > 0:
            water.append(Reason.COMFORT_CORRECTION)
        limited = limit_flow(
            curve_value + correction, config.limits, config.circuit_max, config.boiler_max,
            asks.floor,
        )  # fmt: skip
        water.extend(_LIMIT_REASON[code] for code in limited.applied)
        target: float = limited.value
        water_reasons, decided_at = tuple(water), now
    else:
        assert prior_target is not None
        assert prior_upper is not None
        assert state.decided_at is not None
        target, upper, correction = prior_target, prior_upper, state.correction
        water_reasons, decided_at = state.water_reasons, state.decided_at
    previous = state.command.setpoint if state.command is not None else None
    cap = install_cap(config.limits, config.circuit_max, config.boiler_max)
    # A step counts a minute at most here too: a clock jumping forward is no hour of ramp (PB-28).
    setpoint, ramping = _ramp(previous, target, cap, counted_s, config.ramp_k_per_min)

    mode = _heating_mode(fault, want_heat, outdoor.effective is None)
    reasons = (*water_reasons[:1], heat_reason, *water_reasons[1:])
    if asks.unknown:
        reasons = (*reasons, Reason.CIRCUIT_REQUEST_UNKNOWN)
    if waiting:
        reasons = (*reasons, Reason.ACTIVATION_DELAY)
    if ramping:
        reasons = (*reasons, Reason.RAMP)
    command = BoilerCommand(want_heat, setpoint)
    new_state = replace(
        state,
        mode=mode,
        controlling=True,
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
        correction_at_limit=new_state.correction_limit_s >= CORRECTION_LIMIT_S,
        short_zones=_short_zones(inputs, config),
        most_short=_most_short(inputs, config),
        curve_room=new_state.curve_room,
    )


def _on_off_decision(
    state: ControlState,
    inputs: ControlInputs,
    config: ControlConfig,
    demand: Demand,
    *,
    fault: bool = False,
) -> tuple[ControlState, ControlDecision]:
    """On/off control through a relay (class 3, X8, R5): heating on or off at every step, from
    VT's decision — the same rules as the water-temperature path, without a water temperature:
    the boiler sets its own.
    Modes HEATING and IDLE, and BOILER_FAULT with the relay off while the boiler reports its own
    fault (Y1); never FALLBACK, as no outdoor temperature is needed."""
    now = inputs.now
    asks = _circuits(inputs, config)
    want_heat, heat_reason = _want_heat(demand, fault, bool(asks.asking))
    waiting = _vt_waits(inputs, want_heat)
    reasons: tuple[Reason, ...] = (
        (heat_reason, Reason.ACTIVATION_DELAY) if waiting else (heat_reason,)
    )
    if asks.unknown:
        reasons = (*reasons, Reason.CIRCUIT_REQUEST_UNKNOWN)
    mode = ControlMode.HEATING if want_heat else ControlMode.IDLE
    if fault:
        mode = ControlMode.BOILER_FAULT
    command = BoilerCommand(want_heat, None)
    new_state = replace(
        state,
        mode=mode,
        controlling=True,
        command=command,
        target=None,
        upper=None,
        reasons=reasons,
        water_reasons=(),
        decided_at=now,
        correction=0.0,
        last_step_at=now,
    )
    return new_state, ControlDecision(
        mode,
        command,
        reasons=reasons,
        effective_outdoor=state.outdoor.effective,
    )


def _vt_waits(inputs: ControlInputs, want_heat: bool) -> bool:
    """VT's central boiler waits its activation delay while heating is off for it: the reason
    ``activation_delay`` beside "off" (I12). Heating on — a circuit asking — shows no wait."""
    return inputs.vt_delay and inputs.vt_heat is False and not want_heat


def _want_heat(demand: Demand, fault: bool = False, asking: bool = False) -> tuple[bool, Reason]:
    """Whether to heat now and why: never while the boiler reports its own fault that stops it
    (Y1); VT's decision (I12) — VT's central mode, its frost protection and summer or winter act
    on the zones themselves — else a circuit run by other automation asking (``asking``, I8,
    decision F3: by itself, on top of VT's decision). VT's decision unknown and nothing asking
    asks for nothing (decision 3): heating off, or the working thermostat's, before this."""
    if fault:
        return False, Reason.BOILER_FAULT
    if demand.wanted:
        return True, Reason.DEMAND
    if asking:
        return True, Reason.CIRCUIT_ASKS
    if demand.wanted is None:
        return False, Reason.ZONES_UNKNOWN
    return False, Reason.NO_DEMAND


def _circuits(inputs: ControlInputs, config: ControlConfig) -> CircuitsAsking:
    """The circuits run by other automation that ask now (I8, decision F3): their entity on,
    or one of their known zones wanting heat. A zone split between circuits by its devices asks
    through each of them (I8.8b): ``vtherm_api`` does not tell which of its devices VT has on
    (I12.7), so the warmer side stands."""
    now = inputs.now
    wanting = {
        z.zone_id
        for z in inputs.zones
        if z.is_known(now, config.zone_max_age_s) and zone_wants_heat(z)
    }
    return circuits_asking(
        config.other_automation, inputs.circuit_requests, inputs.circuit_needs, wanting
    )


SATISFIED = 0.7  # every zone below this opening is clearly satisfied
SHORT_K = 0.3  # a deficit this large counts as short of the setpoint
_EPSILON = 1e-9


def _saturated(zone: ZoneState) -> bool:
    return zone.fully_open  # one meaning, shared with the critical zone


def _counted(inputs: ControlInputs, config: ControlConfig) -> list[ZoneState]:
    """The zones the correction judges: heating enabled, and known. A window is VT's to act on
    (I8.1b): a zone it holds off or lowers for one no longer asks, nor looks short."""
    now = inputs.now
    curve = config.curve_zones  # the curve's circuit's zones (I8, F6); None: every zone
    return [
        z
        for z in inputs.zones
        if z.heating_enabled is True
        and z.is_known(now, config.zone_max_age_s)
        and (curve is None or z.zone_id in curve)
    ]


def _judged(inputs: ControlInputs, config: ControlConfig) -> list[ZoneState]:
    """The counted zones whose room temperature may judge the curve (I12, decision 8): not one
    in VT's safety mode, with its thermometer unavailable, or without a measurement since the
    plugin started (``ZoneState.room_sensor_lost``, ``core.zones.room_trusted``). Such a room
    still counts for whether it calls and for the curve's room temperature, which reads
    setpoints."""
    return [z for z in _counted(inputs, config) if not z.room_sensor_lost]


def is_short(zone: ZoneState) -> bool:
    """Fully open and short of VT's setpoint by at least ``SHORT_K``."""
    deficit = zone.deficit
    return _saturated(zone) and deficit is not None and deficit >= SHORT_K


def _curve_room(state: ControlState, inputs: ControlInputs, config: ControlConfig) -> float:
    """The curve's room temperature for this water decision (G11 D): in Manual the value
    entered; in Auto the warmest setpoint among the zones that heat — heating enabled, known,
    not left out by the user — within ``auto_room``'s bounds, the last one holding without
    any."""
    if not config.room_auto:
        return config.curve.room
    targets = [
        z.target
        for z in _counted(inputs, config)
        if z.target is not None and z.zone_id not in config.room_excluded
    ]
    return auto_room(targets, config.curve, state.curve_room)


def _short_zones(inputs: ControlInputs, config: ControlConfig) -> tuple[str, ...]:
    """The rooms fully open and short now (G11 B), of those whose temperature is trusted."""
    return tuple(z.zone_id for z in _judged(inputs, config) if is_short(z))


def _most_short(inputs: ControlInputs, config: ControlConfig) -> bool:
    """More than half of the rooms judged are short (G11, addition 3)."""
    judged = _judged(inputs, config)
    return 2 * sum(1 for z in judged if is_short(z)) > len(judged)


def _taking_heat(zone: ZoneState) -> bool:
    """The zone takes heat now: an opening above ``ZONE_OPEN`` or its device on (S-08) — one
    VT lowered (eco, away, frost) with its valve closed does not."""
    opening = zone.demand
    return zone.device_active is True or (opening is not None and opening > ZONE_OPEN)


def _outdoor_reading(inputs: ControlInputs) -> float | None:
    """The outdoor reading the curve takes now: the sensor's, else the weather entity's."""
    return inputs.outdoor_sensor if inputs.outdoor_sensor is not None else inputs.outdoor_weather


def _correction(
    state: ControlState, inputs: ControlInputs, config: ControlConfig, held: bool
) -> tuple[float, tuple[tuple[float, float], ...], StartsBaseline | None]:
    """The comfort correction for this water decision, within its firm band (bounded learning),
    the rises within the last day and rule 3's baseline. ``held``: a cap or a clip holds the
    setpoint — no rise. Frozen — neither rise nor fall — while hot water runs; no rise while the
    weather is extreme or unknown (rule 5), while every fall — rooms satisfied or too warm, rule
    3's step back — passes, the cautious side (M1 of the part-2 check); rising only while the
    starts are known and do not rise, stepping back while they do (rule 3)."""
    now = inputs.now
    rises = tuple((t, k) for t, k in state.rises if abs(now - t) < DAY)
    if not config.comfort_correction:
        return 0.0, rises, None
    baseline = state.starts_baseline
    if inputs.dhw is True:
        return state.correction, rises, baseline
    extreme = extreme_weather(
        state.outdoor_seen, _outdoor_reading(inputs), now, config.curve.design_outdoor
    )
    baseline = follow_baseline(baseline, state.correction, now)
    starts = inputs.starts
    rose = starts is not None and baseline is not None and starts_rose(baseline, starts, now)
    known = _counted(inputs, config)
    judged = _judged(inputs, config)  # a room's temperature only where it is trusted
    too_warm = any(
        _taking_heat(z) and z.deficit is not None and z.deficit < -OVERHEAT_K for z in judged
    )
    short = any(is_short(z) for z in judged)
    opened = [z for z in known if z.demand is not None]  # no opening: never blocks the fall
    satisfied = bool(opened) and all(z.demand is not None and z.demand < SATISFIED for z in opened)
    correction = state.correction
    if too_warm or (satisfied and not short) or rose:
        correction -= 2.0 * state.water_s / CORRECTION_RISE_S
    elif (
        short
        and not held
        and not extreme
        and starts is not None
        and may_rise(baseline, starts, now)
    ):
        # Only while heat flows; never while a cap or the boiler holds the water; at most
        # ``CORRECTION_DAY_K`` within a day; the first rise keeps the starts before it.
        spent = sum(k for _t, k in rises)
        rise = min(
            state.heat_s / CORRECTION_RISE_S,
            CORRECTION_DAY_K - spent,
            config.correction_max_k - correction,
        )
        if rise > _EPSILON:
            if baseline is None:
                baseline = StartsBaseline(now, tuple(t for t in starts if t < now))
            correction += rise
            rises = (*rises, (now, rise))
    limit = config.correction_max_k
    if correction > limit - _EPSILON:
        correction = limit  # the band's edge, not a rounding error below it
    return max(0.0, correction), rises, baseline


def _day_spent(rises: tuple[tuple[float, float], ...]) -> bool:
    """The day's rise spent: the correction cannot rise until a day has passed since its first
    rises (principle 13 (2))."""
    return sum(k for _t, k in rises) >= CORRECTION_DAY_K - _EPSILON


def _limit_time(state: ControlState, top: bool, held: bool) -> float:
    """The time the correction has been as high as it may go (``top``) — at its band's edge,
    the user's limit, or, with a room short, the day's rise spent, so that one step back after
    the edge does not hide the warning for a day (J4's L13, the user's decision of 2026-11-22) —
    counted from the decision that found it there; paused while a cap or a clip holds the
    setpoint (S-25, T-48)."""
    if not top:
        return 0.0
    if not state.correction_at_top or held:
        return state.correction_limit_s
    return state.correction_limit_s + state.water_s


def _ramp(
    previous: float | None, target: float, cap: float, step_s: float, rate: float | None
) -> tuple[float, bool]:
    """The setpoint for this step: towards ``target`` at ``rate`` K per minute, at every step.
    The first setpoint of a session is the target itself; an installation cap (``cap``: the
    hard maximum, the circuit's, the boiler's) that fell below the last setpoint applies at
    once, while a falling curve is followed at the ramp's rate (S-23). Whether the ramp held the
    setpoint back."""
    if previous is None or previous > cap or rate is None:
        return target, False
    delta = target - previous
    allowed = rate * step_s / 60.0
    if abs(delta) <= allowed:
        return target, False
    return previous + (allowed if delta > 0 else -allowed), True
