"""Control on the Home Assistant side: a control step every few seconds, its writes, hand-back on
every exit, learning pauses, and the status the entities show.

The step itself is pure (``core.loop``); this module only gathers its inputs, carries out its
writes through the writer, and turns guard events and failures into alarms. The writer exists
only while control is switched on. An internal error hands back and blocks control until the user
switches it off and on again; unloading the entry and stopping Home Assistant hand back too. A
hand-back is the safe hand-back — the lowest water temperature, heating on where the boiler
returns to a thermostat or its own control, then the release — and is retried until every target
shows it (``core.hand_back``: a held target alarms at once when it does not, a timeout is never
written again, a target another controller takes counts as done with no retry), and a failed one
says so. Before each attempt the debt is marked and stored at once, so nothing that cuts an
attempt short can lose it. Control takes the boiler through a gateway only once its read-back
holds a value, so its hand-back can be seen (P-21).

What the read-back shows is judged by decision 6's classes (``core.guards``, ``core.loop``): a
lost command is sent again and counted — three a day raise "commands lost", never a hold; a
command ignored from the start is not sent again this session ("write ignored", per target); a
clip is shown; another controller is written over once, then the plugin steps aside. Each guard
is told the trace of an outage around its target — the target, its read-back or another entity
of the same device unavailable, unknown or missing within five minutes, or the optional restart
indicator showing a restart — the OpenTherm thermostat's own request where it is mapped, hot
water, and a target back from unavailable. The external-control switch is watched while control
holds the boiler: off after an outage of its device, it is switched on again; off with no trace,
the plugin steps aside at once without a fight.

How control resumes after it stopped (``SCOPE.md`` §7):
- another controller — an outside change always makes the plugin step aside, whatever reaction
  an earlier version stored: the whole safe hand-back, the target the other controller holds
  included (the user's answer H) — or an alarm set to hand back: a latch, shown with its cause,
  until the user switches control off and on; it survives a restart and never expires on its
  own. Stepping aside raises the entry's one latch issue, again at each start while it holds.
  Where the option is on, control also returns by itself — a new session — after an hour in
  which the read-backs showed only the hand-back state;
- heating off ignored from the start of a session (answer O): a latch and a blocker naming it,
  until the user switches control off and on;
- an internal error: at any change of the control switch;
- a lost boiler link — stale for five minutes within ten, a flapping one included: on its own,
  once the data has been fresh for a minute without a break (X2);
- the plugin's own monitor failing for five minutes: on its own, once it has worked for a minute
  without a failure, with an information note (the user's answer I);
- a blocker: on its own, once it is gone — the configuration's own (``config_blockers``) and those
  found at every step: the gateway's or MQTT's integration removed or disabled, a zone that is
  no VT climate, a zone VT builds on the boiler's own thermostat (X5). Where a hand-back stops
  heating, a blocker that ended a session holding the boiler and still holds a minute later
  raises a repair issue (S-10) — a session a clean restart carried over included: one whose
  restore a blocker stopped;
- every zone unknown (decision 3): on its own, the step a zone answers again.

Decision 3 at a start: where control held the boiler before — a clean restart that handed it
back included — its last command is given again at once, with its keep-alives, instead of the
owed hand-back first, when every condition holds: V3 stored a last command, the stored wish is
"control on" and the control switch entity is not disabled, no latch or internal error holds, the
control options are those the boiler was taken with, the store could be read, and no blocker
but Home Assistant starting holds (VT's central boiler unknown only within its grace, P-105).
Until the write target and the boiler link are there nothing is written and the restore waits,
within the recognition period; a link not yet reported declares no loss meanwhile (X2). A
restore still waiting when the recognition period ends, or whose conditions fail meanwhile,
gives way to the owed hand-back. With every zone unknown, the alarm "no zone known" and a repair
issue (the monitor's too) tell the user; a demand criterion no zone can feed has its own alarm.

Control never stops heating silently: where a hand-back stops heating, the control switch says
that frost protection rests on the boiler's own, and a room near freezing while control does
not hold the boiler raises an alarm, which never starts heating itself (S-57). A watched room
below the frost limit that VT keeps closed gets no frost heat — it could not reach it — and
raises a repair issue instead, naming the room and its temperature, while control is switched on
and outside the recognition period (decision 4).

The comfort correction is shown on the control state and in diagnostics, and the "Reset comfort
correction" button sets it to 0 in the running session — nothing saved, reloaded or handed back
(answer J). VT's activation delay shows as the reason ``activation_delay`` and when heating will
start (decision 5).

The control switch and control's entities stay available whatever the monitor does (P-02).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import (
    CALLBACK_TYPE,
    CoreState,
    Event,
    EventStateChangedData,
    HassJob,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import create_eager_task
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONTROL_TICK_SECONDS,
    DOMAIN,
    MQTT_DOMAIN,
    OPENTHERM_GW_DOMAIN,
    stored_flag,
)
from .control_config import (
    OTGW_PATHS,
    AlarmReaction,
    ControlOptions,
    HandBack,
    HandBackEffect,
    Topology,
    WritePath,
    config_blockers,
    frost_protection_by,
    hand_back_effect,
    highest_water_temperature,
    working_thermostat,
)
from .core.controller import (
    HA_STARTING,
    BoilerCommand,
    ControlInputs,
    ControlMode,
    ControlState,
    Reason,
    clock_due,
    clock_start,
    reset_correction,
)
from .core.guards import (
    TOLERANCE_K,
    Confirmation,
    GuardConfig,
    GuardContext,
    GuardEvent,
    GuardState,
    WriteAction,
    WriteKind,
    WriteType,
    add_loss,
    confirmation,
    trace_seen,
    write_failed,
)
from .core.hand_back import (
    DHW_QUIET_S,
    HELD_UNCONFIRMED_S,
    TIMEOUT_RELEASE_S,
    UNAVAILABLE_STATES,
    CheckKind,
    CheckSource,
    ForeignWatch,
    HandBackConfirmation,
    SwitchVerdict,
    TargetView,
    judge_switch,
    outage_seen,
    released,
    restart_seen,
    shown,
    third_value,
    watch_foreign,
)
from .core.learning import (
    LearningState,
    PauseCause,
    ZoneLearning,
    follow_resumes,
    plan_learning,
    release_all,
)
from .core.limits import Grid, handed_back_in_frost, write_bounds
from .core.loop import (
    HEATING_OFF_IGNORED,
    OFF,
    ON,
    LastCommand,
    LoopOutput,
    LoopState,
    after_hand_back_loop,
    loop_step,
    new_session,
    parse_last_command,
    remember_command,
)
from .core.readings import BoilerSnapshot, ZoneState
from .core.signal_check import OutdoorStatus, curve_sensor
from .core.signals import Signal
from .core.zone_watch import in_recognition, no_zone_issue_due
from .core.zones import plausible_room
from .transport.entities import (
    read_bounds,
    read_grid,
    read_on_off,
    read_temperature,
    read_weather_temperature,
    restart_reading,
    temperature_from_state,
    temperature_unit_of,
)
from .transport.writers import (
    HandBackCheck,
    HandBackFailed,
    WriteError,
    Writer,
    make_writer,
    writer_services,
)
from .units import parse_binary

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
DAY = 86400.0
LEARNING_TIMEOUT_S = 5.0
# An owed hand-back is sent again this long after an attempt; a gateway's not released by then
# counts as failed — its override's own lapse time (provisional, K4).
HAND_BACK_RETRY_S = 60.0
RELEASE_TOLERANCE_K = 0.5  # a target within this of what it was given shows it
# For this long after a unit starts, the hand-back the last run left owed raises no alarm and
# logs at DEBUG only: a device may report again only once it has reconnected (P-50; provisional,
# K4; Q3.5, ESPHome). A target still away meanwhile is tried again at every step.
START_GRACE_S = 60.0
# The stop's hand-back — its writes, a short wait for a device that reports late, SmartPI's
# calls — ends within this: Home Assistant cancels every shutdown job at 20 s (provisional, K4;
# Q3.3). Each write at a stop is capped at 3 s (pyotgw gives each command 3 s itself), and the
# wait is 5 s at most.
STOP_BUDGET_S = 15.0
STOP_WRITE_TIMEOUT_S = 3.0
STOP_REPORT_WAIT_S = 5.0
OWED_ISSUE = "hand_back_owed"  # a repair issue, fixable by saying the boiler was returned
TAKEN_ISSUE = "hand_back_taken_by_other"  # after the hand-back another controller holds a target
# The entry's one latch issue: control stepped aside from another controller (V7; Y1 extends it
# to every latch).
LATCHED_ISSUE = "control_latched"
# A blocker ended a session that held the boiler where a hand-back stops heating: a repair issue
# once the blocker has held this long — longer than a VT reload, short enough to warn (S-10;
# provisional, K4).
STOPPED_HEATING_ISSUE = "control_stopped_heating"
STOPPED_HEATING_S = 60.0
# Blockers that raise no such issue: Home Assistant starting (the minute starts once it runs),
# an internal error (its own alarm), the monitor failing (V6's own issue) and heating off ignored
# from the start (the latch issue says so).
_QUIET_BLOCKERS = frozenset({"ha_starting", "control_error", "monitor_failed", HEATING_OFF_IGNORED})
# After stepping aside from another controller, where the option is on: control returns by
# itself once the read-backs have shown only the hand-back state this long (decided).
RETURN_QUIET_S = 3600.0
# The monitor failing handed the boiler back: a repair issue, which becomes an information note
# under the same id once control has resumed (the user's answer I).
MONITOR_ISSUE = "monitor_failed"
MONITOR_NOTE = "monitor_recovered"
# Decision 4: a watched room below the frost limit that VT keeps closed — a repair issue, not
# raised while the zones report in the recognition period, and only while control is on
# (provisional, K4). Shown again when a room's temperature has moved this much.
FROST_CLOSED_ISSUE = "frost_zone_closed"
FROST_CLOSED_SHOWN_K = 1.0
ZONE_UNKNOWN_ALARM_S = 30 * 60.0  # a zone unknown this long is reported
# VT's central boiler unknown — its central entry reloading — does not block control for this long
# where it was known to be off at the step before (P-105; provisional, K4). A restorable store
# after a restart stands for "known off just before": a session cannot run while it is on.
VT_BOILER_GRACE_S = 600.0
RESTORE_WAIT_S = 60.0  # without the switch restoring its state by then, control counts as off
SMARTPI_DOMAIN = "vtherm_smartpi"
SMARTPI_SERVICE = "set_smartpi_learning"
# Blockers found while running, besides those of the configuration (translation keys).
RUNTIME_BLOCKERS = (
    "ha_starting",
    "monitoring_period",
    "vt_central_boiler_active",
    "vt_central_boiler_unknown",
    "setpoint_outside_entity_range",
    "setpoint_unit_not_supported",
    "setpoint_step_too_coarse",
    "control_error",
    "monitor_failed",
    HEATING_OFF_IGNORED,
    # X5: the gateway's or MQTT's integration gone or disabled (X5.5); a zone that is not a VT
    # climate (X5.7); a zone VT built on the boiler's own thermostat (X5.19).
    "gateway_not_set_up",
    "mqtt_not_set_up",
    "zone_not_vt",
    "zone_on_boiler_thermostat",
)
CONFIRMED_BY_GATEWAY = "confirmed_by_gateway"
_SHOWN_CONFIRMED = frozenset({Confirmation.CONFIRMED.value, CONFIRMED_BY_GATEWAY})


def _flag(raw: Any) -> bool:
    """A stored flag; anything that is not a clear "no" counts as set (the cautious side)."""
    return stored_flag(raw)


def _setpoint(raw: Any) -> float:
    """A stored setpoint: a finite number; anything else raises ``ValueError``."""
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise ValueError(f"not a finite number: {raw!r}")
    return float(raw)


def _cancelled_from_outside() -> bool:
    """Whether the running task is itself being cancelled — a stop, Home Assistant's own cut —
    rather than a ``CancelledError`` raised inside a call it made."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


def _local_minute(t: float) -> str:
    """A moment as a note shows it: Home Assistant's local time, to the minute."""
    return dt_util.as_local(dt_util.utc_from_timestamp(t)).strftime("%Y-%m-%d %H:%M")


def _level(raw: Any) -> float:
    """A stored heating on/off baseline: 0 or 1; anything else raises ``ValueError``."""
    value = _setpoint(raw)
    if value not in (OFF, ON):
        raise ValueError(f"not heating on/off: {raw!r}")
    return value


def _last(times: Sequence[float]) -> float | None:
    return max(times) if times else None


def _entity_ids(raw: Any) -> set[str]:
    """A stored list of entity ids; anything else raises ``ValueError``."""
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"not a list of entity ids: {raw!r}")
    return set(raw)


def _kept_alarms(raw: Any) -> set[ControlAlarm]:
    kept = set()
    for value in raw:
        try:
            alarm = ControlAlarm(value)
        except ValueError:
            continue  # an alarm this version no longer has
        if alarm in _KEPT_ALARMS:
            kept.add(alarm)
    return kept


def _memory_moved(before: LoopState, after: LoopState) -> bool:
    """Whether a value stored at once changed: a guard's baseline or its last fall-back without
    a trace."""
    return any(
        old.baseline != new.baseline or _last(old.fallbacks) != _last(new.fallbacks)
        for old, new in ((before.setpoint, after.setpoint), (before.switch, after.switch))
    )


def _zones_changed(before: LearningState, after: LearningState) -> bool:
    """Whether the zones paused or followed, or a pause's causes, changed (not only when a
    resume was last sent)."""
    return (
        before.paused.keys() != after.paused.keys()
        or before.resuming.keys() != after.resuming.keys()
        or before.causes != after.causes
    )


def _causes(raw: Any) -> dict[str, tuple[PauseCause, ...]]:
    """Stored pause causes; a cause this version does not know is left out — a pause left with
    none is taken for hot water."""
    causes: dict[str, tuple[PauseCause, ...]] = {}
    for zone_id, values in raw.items():
        known = []
        for value in values:
            try:
                known.append(PauseCause(value))
            except ValueError:
                continue
        if known:
            causes[str(zone_id)] = tuple(known)
    return causes


def _shown(check: Confirmation | None, gateway: bool, self_echo: bool) -> str | None:
    """How a write's standing is shown. An OTGW read-back is confirmed by the gateway: it shows
    what the gateway sends, not what the boiler accepted. A read-back taken from the written
    entity itself confirms nothing."""
    if check is Confirmation.CONFIRMED:
        if self_echo:
            return Confirmation.UNVERIFIED.value
        if gateway:
            return CONFIRMED_BY_GATEWAY
    return None if check is None else check.value


def report_owed_hand_back(hass: HomeAssistant, entry_id: str, persistent: bool = False) -> None:
    """The repair issue of a hand-back still owed; fixable by saying the boiler was returned."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{OWED_ISSUE}_{entry_id}",
        is_fixable=True,
        is_persistent=persistent,
        severity=ir.IssueSeverity.ERROR,
        translation_key=OWED_ISSUE,
        data={"entry_id": entry_id},
    )


class ControlAlarm(StrEnum):
    WRITE_FAILED = "write_failed"
    WRITE_IGNORED = "write_ignored"
    OUTSIDE_CHANGE = "outside_change"
    HAND_BACK_FAILED = "hand_back_failed"
    CONTROL_ERROR = "control_error"
    BOILER_LINK_LOST = "boiler_link_lost"  # the boiler's data lost while control is on (X2)
    ZONE_UNKNOWN = "zone_unknown"  # a zone unknown for long: frost protection cannot see it
    FROST_NOT_WARMING = "frost_not_warming"  # frost heating for long without the room warming
    CORRECTION_AT_LIMIT = "correction_at_limit"  # the comfort correction at 3 K for hours
    OUTDOOR_SENSOR_SUSPECT = "outdoor_sensor_suspect"  # stuck, or far from the weather
    MONITOR_FAILED = "monitor_failed"  # the plugin's own monitor fails for five minutes
    # Control does not hold the boiler where a hand-back stops heating, and a room is near
    # freezing: frost protection rests on the boiler's own (S-57). Information only.
    HANDED_BACK_IN_FROST = "handed_back_in_frost"
    COMMANDS_LOST = "commands_lost"  # three lost commands within a day: information only
    CONFIRMATION_MISSING = "confirmation_missing"  # the read-back unknown for five minutes
    # Decision 3: every zone unknown after the recognition period and the graces — nothing can
    # ask for heat; and a demand criterion no known zone can feed (P-14). Neither has a reaction.
    NO_ZONE_KNOWN = "no_zone_known"
    DEMAND_CRITERION_NO_DATA = "demand_criterion_no_data"


_EVENT_ALARM = {
    GuardEvent.IGNORED: ControlAlarm.WRITE_IGNORED,
    GuardEvent.OUTSIDE_CHANGE: ControlAlarm.OUTSIDE_CHANGE,
}
# Alarms that inform and never hand back, whatever reaction was stored: a lost command is sent
# again, a missing confirmation decides nothing (the boiler link does).
_INFO_ONLY = frozenset({ControlAlarm.COMMANDS_LOST, ControlAlarm.CONFIRMATION_MISSING})
# Alarms kept across a restart: they explain a latch that survives it.
_KEPT_ALARMS = frozenset({ControlAlarm.OUTSIDE_CHANGE, ControlAlarm.CONTROL_ERROR})


@dataclass(frozen=True, slots=True)
class ControlStatus:
    """What the entities show about control."""

    configured: bool
    enabled: bool = False
    blockers: tuple[str, ...] = ()
    mode: ControlMode = ControlMode.DISABLED
    reasons: tuple[str, ...] = ()
    requested: float | None = None  # the setpoint last written
    target: float | None = None  # the decided setpoint before the ramp
    heating_on: bool | None = None  # heating on/off last commanded
    read_back: float | None = None  # what the device reports back for the setpoint
    setpoint_check: str | None = None  # a Confirmation value, or "confirmed_by_gateway"
    heating_check: str | None = None  # the same for heating on/off
    last_change_at: float | None = None  # last write of a new value (keep-alives aside)
    hand_back_at: float | None = None
    alarms: frozenset[ControlAlarm] = frozenset()
    paused_zones: tuple[str, ...] = ()
    latched_by: tuple[str, ...] = ()  # the alarms that latched control, while it stays latched
    unknown_zones: tuple[str, ...] = ()  # zones whose state is not known now
    room_sensor_lost_zones: tuple[str, ...] = ()  # VT keeps their last temperature
    writes_stopped: bool = False  # another controller has the boiler: nothing is written
    hand_back_check: str | None = None  # where the last hand-back stands (HandBackConfirmation)
    monitor_failed_since: float | None = None  # the monitor's current run of failed refreshes
    frost_protection_by: str | None = None  # who keeps frost protection now (FrostProtection)
    ignored_targets: tuple[str, ...] = ()  # targets ignored from the start ("write ignored")
    unconfirmed_targets: tuple[str, ...] = ()  # targets whose confirmation is missing
    # Blockers that do not count yet: VT's central boiler unknown within its grace (P-105).
    blockers_waiting: tuple[str, ...] = ()
    criteria_without_data: tuple[str, ...] = ()  # demand criteria no known zone can feed
    correction: float = 0.0  # the comfort correction now, K (P-38)
    activation_at: float | None = None  # when a start waiting VT's activation delay is due
    frost_closed_zones: tuple[str, ...] = ()  # watched rooms below the frost limit VT keeps closed

    @property
    def confirmed_setpoint(self) -> float | None:
        """The setpoint as the device confirms it; unknown otherwise, never the requested one."""
        return self.read_back if self.setpoint_check in _SHOWN_CONFIRMED else None


@dataclass
class _Target:
    """One target of an owed hand-back, and what its read-back has shown so far."""

    check: HandBackCheck
    sent_at: float  # when its parts were last written: a held target alarms a step later
    first_at: float  # when this debt first wrote it: a timeout alarms three minutes later
    released: bool = False  # it shows the hand-back (a value target: seen once counts)
    taken: bool = False  # another controller holds it: done, and not written again
    seen: bool = False  # a two-valued target read back in its hand-back state once
    lost: bool = False  # it left that state with a trace of an outage: written again at once
    third: bool = False  # a held target shows a third value: its retry write is held back
    watch: ForeignWatch | None = None  # that value at the retry checks

    @property
    def done(self) -> bool:
        return self.released or self.taken


@dataclass
class _Session:
    """One control session: from switching control on to switching it off."""

    loop: LoopState = field(default_factory=LoopState)
    learning: LearningState = field(default_factory=LearningState)
    alarms: set[ControlAlarm] = field(default_factory=set)
    failed: bool = False
    failing: set[str] = field(default_factory=set)  # writes whose last attempt failed


type WriterFactory = Callable[[HomeAssistant, ControlOptions], Writer]


class ControlUnit:
    """Control for one installation; writes nothing until configured, allowed and switched on.

    ``raw``: the control options as stored; kept with the state while the boiler may hold a value
    of ours, so a later start can hand back through what took the boiler even if the options
    changed. ``hand_back_only``: built from such stored options after control left the options;
    it never controls, only makes the owed hand-back, shown as a repair issue, and follows the
    SmartPI resumes the last run left. ``follow_learning``: such a unit built without options
    (nothing owed, only resumes to follow): it only follows them.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SmartBoilerCoordinator,
        options: ControlOptions,
        writer_factory: WriterFactory = make_writer,
        raw: Mapping[str, Any] | None = None,
        hand_back_only: bool = False,
        follow_learning: bool = False,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self.options = options
        self._raw = dict(raw or {})
        self.hand_back_only = hand_back_only or follow_learning
        self.follow_learning = follow_learning
        self._writer_factory = writer_factory
        self._writer: Writer | None = None
        self.enabled = False
        self._session = _Session()
        self._status = ControlStatus(
            options.configured, frost_protection_by=self._frost_protection_shown()
        )
        self._published: ControlStatus | None = None
        self._last_change_at: float | None = None
        self._hand_back_at: float | None = None
        # A hand-back is owed: it failed, or it has not been confirmed yet. Retried until it is.
        self._hand_back_pending = False
        self._hand_back_failed = False  # shown as an alarm: an attempt failed or went unconfirmed
        # The targets of the owed hand-back, each with what its read-back has shown (V5).
        self._targets: dict[str, _Target] = {}
        # What a release is judged against, kept and stored while its hand-back is owed — the
        # session and its last command may be gone: the setpoint the plugin last wrote, and the
        # read-back from before the session (a timeout releases back to it).
        self._release_from: float | None = None
        self._release_baseline: float | None = None
        self._baseline: float | None = None  # this session's, noted before a step may reset it
        # Targets another controller holds after the hand-back: done, never written again.
        self._taken_targets: set[str] = set()
        self._taken_issue = False  # its repair issue is up
        self._attempt_whole = False  # the last attempt's every write went out
        self._hand_back_shown: str | None = None  # where the last hand-back stands, as shown
        self._outages: dict[str, float] = {}  # when each entity was last seen unavailable
        self._dhw_seen_at: float | None = None  # when hot water last ran
        self._checks_unsub: CALLBACK_TYPE | None = None
        self._checks_seen: asyncio.Event | None = None  # a stop waits on it for a late report
        # The start grace: the debt the last run left, and when this unit was built.
        self._carried_debt = False
        self._grace_from = dt_util.utcnow().timestamp()
        # The boiler may hold a value of ours: set before every write attempt and stored at once,
        # cleared only by a confirmed hand-back. After a crash it makes the next start hand back.
        self._holding = False
        self._unknown_since: dict[str, float] = {}
        self._hand_back_retry_at = 0.0
        self._restored = False  # the user's wish is known: restored by the switch, or timed out
        # The wish as the last run stored it: ``None`` when none was stored (the first start of
        # 0.2.2). Stored as it is until the switch restores it.
        self._stored_enabled: bool | None = None
        # The last command given to the boiler, and the one last stored at once (V3).
        self._last_command: LastCommand | None = None
        self._command_stored: LastCommand | None = None
        self._started_at = dt_util.utcnow().timestamp()
        self._lock = asyncio.Lock()
        self._tick_waiting = False
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._stop_unsub: CALLBACK_TYPE | None = None
        self._stopped = False
        self._stopping = False
        self._step_task: asyncio.Task[None] | None = None  # the step running now, if any
        # SmartPI calls planned by a step or a hand-back; made after the lock is released, so a
        # slow SmartPI never holds up control or a hand-back.
        self._learning_calls: list[tuple[str, bool]] = []
        # Failures already logged: a lasting one is logged once, and its recovery once.
        self._learning_failing: set[str] = set()
        self._hand_back_logged = False
        self._step_failing = False  # the control step failed: logged once, its end once
        # The monitor's issue is up for a hand-back it caused: when its failures began. It
        # becomes the information note once control holds the boiler again (answer I).
        self._monitor_issue_since: float | None = None
        # S-10: a blocker ended a session that held the boiler where a hand-back stops heating.
        # Kept, and stored, until control controls again or the user switches it off; its
        # repair issue follows once a blocker has held for ``STOPPED_HEATING_S``.
        self._stopped_by_blocker = False
        self._blocked_since: float | None = None  # the current run of blockers that count
        self._stopped_heating_issue = False  # the issue is up
        # S-57: the alarm "handed back in frost"; kept across sessions for its hysteresis.
        self._frost_alarm = False
        # X1: the restart indicator's last restart seen (a trace of an outage), which targets
        # were unavailable at the last step, the external-control switch's watch, and the quiet
        # hour before control returns by itself.
        self._restart_at: float | None = None
        self._restart_value: float | None = None
        self._targets_down: dict[str, bool] = {}
        self._external_seen_on = False
        self._external_renew = False
        self._external_returned = False
        self._quiet_since: float | None = None
        # Decision 3: the last command given again at once after a restart, pending until a
        # write of it goes through or the owed hand-back takes its place; the options the boiler
        # was taken with, as the last run stored them; and whether the boiler link has reported
        # since the start (a restore waits for it without declaring a loss, X2).
        self._restore_command: BoilerCommand | None = None
        self._restore_pending = False
        self._taken_with: object = None
        self._link_seen = False
        # P-105: VT's central boiler was known to be off at the last step, and since when it has
        # been unknown after that.
        self._vt_boiler_off = False
        self._vt_boiler_unknown_since: float | None = None
        # Decision 4: the rooms the frost issue shows now, with the temperature it shows.
        self._frost_issue_shown: dict[str, float] = {}

    # --- status, listeners, storage -----------------------------------------------------

    @property
    def hand_back_owed(self) -> bool:
        """A hand-back has not got through, or has not been confirmed, yet."""
        return self._hand_back_pending

    @property
    def holding(self) -> bool:
        """The boiler may hold a value control wrote: its hand-back is still to come."""
        return self._holding

    @property
    def controlling(self) -> bool:
        """The session holds the boiler: the plugin sets the water now."""
        return self._session.loop.control.controlling

    @property
    def stopping(self) -> bool:
        """The unit is stopping or stopped (unload, reload, Home Assistant stopping): its
        entities are unavailable from then on, and only then (P-02)."""
        return self._stopping or self._stopped

    @property
    def status(self) -> ControlStatus:
        return self._status

    @property
    def allowed_services(self) -> frozenset[tuple[str, str]]:
        """Every service control may call, derived from the configuration alone."""
        services = set(writer_services(self.options))
        if (services and self.options.learning_pauses) or self.follow_learning:
            services.add((SMARTPI_DOMAIN, SMARTPI_SERVICE))
        return frozenset(services)

    @property
    def stored_wish(self) -> bool | None:
        """The user's on/off wish as the last run stored it; ``None`` when none was stored."""
        return self._stored_enabled

    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        def remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return remove

    def _notify(self) -> None:
        if self._status == self._published:
            return
        self._published = self._status
        for update in list(self._listeners):
            update()

    def stored(self) -> dict[str, Any]:
        """What must survive a restart: whether the boiler may hold a value of ours, paused zones,
        latches, a hand-back still to be done, the user's wish, the last command, and a blocker
        that stopped heating (S-10)."""
        session = self._session
        owed = self._holding or self._hand_back_pending
        if self.hand_back_only:
            enabled: bool | None = False  # control is not in the options: it is off
        elif self._restored:
            enabled = self.enabled
        else:
            enabled = self._stored_enabled  # kept until the switch restores it
        # Control not in the options has no command to give again.
        command = None if self.hand_back_only else self._last_command
        # The options the boiler was taken with: for the owed hand-back, and for a last command
        # to be given again only through the same options (decision 3).
        kept = owed or command is not None
        return {
            "enabled": enabled,
            "last_command": None if command is None else command.as_dict(),
            "controlling": self._holding,
            "taken_with": dict(self._raw) if kept and self._raw else None,
            "paused": dict(session.learning.paused),
            # What each pause is for (P-89): a pause after hot water waits for the flow.
            "pause_causes": {
                zone: [cause.value for cause in causes]
                for zone, causes in session.learning.causes.items()
            },
            "dhw_ended": dict(session.learning.dhw_ended),
            "resuming": dict(session.learning.resuming),
            "resume_since": dict(session.learning.resume_since),
            "latched": session.loop.control.latched,
            "latched_by": list(session.loop.control.latched_by),
            # The one rewrite after an outside change: within a day of it, no more are made.
            "rewritten_at": session.loop.setpoint.rewritten_at,
            "heating_rewritten_at": session.loop.switch.rewritten_at,
            # Decision 6: the values from before the plugin, and the last fall-back without a
            # trace of each guard — a second within the hour is another controller's.
            "baseline": session.loop.setpoint.baseline,
            "heating_baseline": session.loop.switch.baseline,
            "fallback_at": _last(session.loop.setpoint.fallbacks),
            "heating_fallback_at": _last(session.loop.switch.fallbacks),
            "failed": session.failed,
            "alarms": sorted(alarm.value for alarm in session.alarms & _KEPT_ALARMS),
            "hand_back_pending": self._hand_back_pending,
            "release_from": self._release_from,
            "release_baseline": self._release_baseline,
            "taken_by_other": sorted(self._taken_targets),
            # A blocker ended a session where a hand-back stops heating: the next run tells the
            # user again while it holds (S-10).
            "stopped_heating": self._stopped_by_blocker and not self.hand_back_only,
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        """What the last run stored, field by field: a broken field is skipped and logged, the
        rest restored. Whether the boiler may hold a value of ours, a hand-back owed and a latch
        read cautiously: what cannot be read counts as set."""

        def field[T](key: str, parse: Callable[[Any], T], default: T) -> T:
            raw = data.get(key)
            if raw is None:
                return default
            try:
                return parse(raw)
            except TypeError, ValueError, AttributeError:
                _LOGGER.warning("Ignoring unreadable stored control data: %s", key)
                return default

        paused: dict[str, float] = field(
            "paused", lambda raw: {str(z): float(t) for z, t in raw.items()}, {}
        )
        resuming: dict[str, float] = field(
            "resuming", lambda raw: {str(z): float(t) for z, t in raw.items()}, {}
        )
        resume_since: dict[str, float] = field(
            "resume_since", lambda raw: {str(z): float(t) for z, t in raw.items()}, {}
        )
        # A pause's causes, where stored (P-89); without them it is taken for hot water.
        causes: dict[str, tuple[PauseCause, ...]] = field("pause_causes", _causes, {})
        dhw_ended: dict[str, float] = field(
            "dhw_ended", lambda raw: {str(z): float(t) for z, t in raw.items()}, {}
        )
        alarms: set[ControlAlarm] = field("alarms", _kept_alarms, set())
        latched_by: tuple[str, ...] = field(
            "latched_by", lambda raw: tuple(str(a) for a in raw), ()
        )
        rewritten_at: float | None = field("rewritten_at", _setpoint, None)
        heating_rewritten_at: float | None = field("heating_rewritten_at", _setpoint, None)
        baseline: float | None = field("baseline", _setpoint, None)
        heating_baseline: float | None = field("heating_baseline", _level, None)
        fallback_at: float | None = field("fallback_at", _setpoint, None)
        heating_fallback_at: float | None = field("heating_fallback_at", _setpoint, None)
        latched = _flag(data.get("latched"))
        self._session = _Session(
            loop=LoopState(
                control=ControlState(latched=latched, latched_by=latched_by if latched else ()),
                setpoint=GuardState(
                    rewritten_at=rewritten_at,
                    baseline=baseline,
                    fallbacks=() if fallback_at is None else (fallback_at,),
                ),
                switch=GuardState(
                    rewritten_at=heating_rewritten_at,
                    baseline=heating_baseline,
                    fallbacks=() if heating_fallback_at is None else (heating_fallback_at,),
                ),
            ),
            learning=LearningState(
                paused=paused,
                last_toggle=dict(paused),
                resuming=resuming,
                resume_since={z: t for z, t in resume_since.items() if z in resuming},
                causes={z: c for z, c in causes.items() if z in paused},
                dhw_ended={z: t for z, t in dhw_ended.items() if z in paused},
            ),
            alarms=alarms,
            failed=_flag(data.get("failed")),
        )
        self._holding = _flag(data.get("controlling"))
        # The last run held the boiler and never confirmed a hand-back (a crash, a power cut):
        # handed back in full at the first step; control may take the boiler again afterwards.
        self._hand_back_pending = _flag(data.get("hand_back_pending")) or self._holding
        self._carried_debt = self._hand_back_pending
        self._release_from = field("release_from", _setpoint, None)
        self._release_baseline = field("release_baseline", _setpoint, None)
        # Only an owed hand-back has targets another controller holds; unreadable, none counts
        # as taken — every target is handed back again.
        taken: set[str] = field("taken_by_other", _entity_ids, set())
        self._taken_targets = taken if self._hand_back_pending else set()
        # The wish: only a clear "on" is on; one that cannot be read is off, not the restored
        # switch (P-11).
        wish = data.get("enabled")
        if wish is not None and not isinstance(wish, bool):
            _LOGGER.warning("Ignoring unreadable stored control data: enabled; control is off")
            wish = False
        self._stored_enabled = wish
        self._last_command = field("last_command", parse_last_command, None)
        self._command_stored = self._last_command
        self._taken_with = data.get("taken_with")
        # Read cautiously too: the issue follows only while a blocker holds (S-10).
        self._stopped_by_blocker = _flag(data.get("stopped_heating")) and not self.hand_back_only
        self._plan_restore(dt_util.utcnow().timestamp())
        # From now on the stores get this unit's state: a save made before its start must not
        # write the state loaded earlier over a hand-back made since.
        self._coordinator.provide_stored_control(self.stored)

    def _plan_restore(self, now: float) -> None:
        """Decision 3 at the start: the last command is given again at once — instead of the
        owed hand-back first — where every condition holds (the module's docstring). A store
        that could not be read makes the plugin assume it held the boiler: the hand-back first
        (answer K). A blocker stopping it, where a hand-back stops heating, raises S-10's issue
        as for a session a blocker ended (V7)."""
        command = self._last_command
        if self.hand_back_only or command is None or command.setpoint is None:
            return
        control = self._session.loop.control
        refused = (
            not self._coordinator.control_readable
            or self._stored_enabled is not True
            or self._switch_disabled()
            or control.latched
            or self._session.failed
            or self._taken_with != self._raw
        )
        if refused:
            _LOGGER.debug("The last command is not given again after the restart")
            return
        self._vt_boiler_off = True  # a session cannot run while VT's central boiler is on
        blockers = [blocker for blocker in self.blockers(now) if blocker != HA_STARTING]
        if blockers:
            self._vt_boiler_off = False
            _LOGGER.info(
                "The last command is not given again after the restart: %s", ", ".join(blockers)
            )
            if any(b not in _QUIET_BLOCKERS for b in blockers) and self._stops_heating():
                self._stopped_by_blocker = True  # the session carried over, ended by a blocker
            return
        self._restore_command = BoilerCommand(command.heating, command.setpoint)
        self._restore_pending = True

    def _switch_disabled(self) -> bool:
        """The control switch entity is disabled in Home Assistant: control is off (answer K)."""
        registry = er.async_get(self._hass)
        unique_id = f"{self._coordinator.config_entry.entry_id}_control"
        entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
        entry = registry.async_get(entity_id) if entity_id is not None else None
        return entry is not None and entry.disabled

    # --- lifecycle ------------------------------------------------------------------------

    async def async_hand_back_owed(self, now: float) -> None:
        """At setup, before anything else can fail: one full attempt at a hand-back the last
        run left owed. A failure stays owed and is retried by the clock — shown once the start
        grace is over — or reported for good if setup gives up. Never raises."""
        if not self.options.configured:
            return
        async with self._lock:
            if self._stopped or self._stopping or not self._hand_back_pending:
                return
            if self._restore_pending:
                # Decision 3: the last command is given again instead; the owed hand-back is
                # folded into it, or made once the restore gives way.
                return
            try:
                await self._async_try_hand_back(now)
            except Exception:
                _LOGGER.exception("Handing back what the last run left owed failed")
                self._hand_back_pending = True
                self._hand_back_failed = True
                self._hand_back_retry_at = now + HAND_BACK_RETRY_S
                self._report_owed()
            self._coordinator.schedule_control_save()

    async def async_start(self) -> None:
        """Start the control clock and hand back when Home Assistant stops."""
        if not (self.options.configured or self.follow_learning):
            return
        self._report_owed()
        self._report_latched(anew=False)  # a stored latch holds: its issue again (V7)
        self._started_at = dt_util.utcnow().timestamp()
        self._monitor_issue_since = self._monitor_issue_left()
        self._track_outages(self._started_at)
        self._unsubs.append(
            async_track_time_interval(
                self._hass, self._async_timer, timedelta(seconds=CONTROL_TICK_SECONDS)
            )
        )
        # Hand back before Home Assistant stops its integrations (MQTT disconnects on the stop
        # event itself); older versions without shutdown jobs get the stop event.
        add_shutdown_job = getattr(self._hass, "async_add_shutdown_job", None)
        if callable(add_shutdown_job):
            self._stop_unsub = add_shutdown_job(
                HassJob(self._async_shutdown, "vtherm_smart_boiler hand-back")
            )
        else:
            self._stop_unsub = self._hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._async_ha_stop
            )

    async def async_restore_enabled(self, on: bool) -> None:
        """The switch, once added, gives the user's wish back after a restart (the stored wish,
        or its own restored state when none was stored): control steps may run. Unlike a change
        made by the user, it does not clear an internal error (C10). A switch that is never
        added (disabled) leaves control off once ``RESTORE_WAIT_S`` has passed."""
        async with self._lock:
            if self._restored or self._stopped or self._stopping:
                return
            self._restored = True
            self._stored_enabled = on
            await self._coordinator.async_save_control_now()
            if on != self.enabled:
                self.enabled = on
                await self._async_run_step(dt_util.utcnow().timestamp())
        await self._async_learning_calls()
        self._notify()

    async def _async_shutdown(self) -> None:
        # Home Assistant is going through its list of shutdown jobs: removing this one from it
        # now would make it skip the next job, so it stays.
        self._stop_unsub = None
        await self.async_stop()

    async def _async_ha_stop(self, _event: Event) -> None:
        self._stop_unsub = None  # a one-time listener removes itself
        await self.async_stop()

    async def async_stop(self) -> None:
        """Stop the clock and hand back — the writes, a short wait for a device that reports
        late and SmartPI's calls, all within ``STOP_BUDGET_S`` — and write nothing afterwards.
        Never raises; Home Assistant's own cancellation passes, the debt stored before the first
        write (R1), and the next start makes the hand-back."""
        deadline = self._hass.loop.time() + STOP_BUDGET_S
        while self._unsubs:
            self._unsubs.pop()()
        if self._stop_unsub is not None:
            self._stop_unsub()
            self._stop_unsub = None
        self._stopping = True
        step = self._step_task
        if step is not None and not step.done():
            step.cancel()  # a slow step (a hanging service) must not hold up the hand-back
        try:
            async with asyncio.timeout_at(deadline), self._lock:
                if self._stopped:
                    return
                self._stopped = True
                await self._async_stop_hand_back(dt_util.utcnow().timestamp(), deadline)
        except TimeoutError:
            _LOGGER.error(
                "The hand-back at the stop ran out of time (%.0f s); it stays owed and is made "
                "at the next start",
                STOP_BUDGET_S,
            )
            if self._holding or self._session.loop.control.controlling:
                self._hand_back_pending = True
        except Exception:
            _LOGGER.exception("Handing control back on stop failed")
        finally:
            self._stopped = True
            self._writer = None
            if self._checks_unsub is not None:
                self._checks_unsub()
                self._checks_unsub = None
        if self._hand_back_pending:
            # The entry unloads — disabled, reloaded, Home Assistant stopping — with the
            # hand-back still owed: the issue outlives it, until a later run gets it through or
            # the user settles it by hand.
            self._report_owed(persistent=True)
        # The issue of a blocker that stopped heating goes with the unit; the stored flag makes
        # the next run raise it again while a blocker holds (S-10). So does the frost issue: the
        # next run raises it again at its first step outside the recognition period.
        self._delete_stopped_heating_issue()
        self._show_frost_closed({})
        await self._async_learning_calls(deadline)
        self._coordinator.schedule_control_save()

    async def _async_stop_hand_back(self, now: float, deadline: float) -> None:
        """The stop's own hand-back, each write capped at ``STOP_WRITE_TIMEOUT_S``. One its
        targets do not show yet gets ``STOP_REPORT_WAIT_S`` more, within the budget, for a device
        that reports late (ESPHome, MQTT); still unconfirmed, it stays owed (R6)."""
        await self._async_hand_back_now(now)
        if self._hand_back_pending and self._targets and self._attempt_whole:
            # Only where every write went out: a late report cannot mend one that did not.
            until = min(self._hass.loop.time() + STOP_REPORT_WAIT_S, deadline)
            await self._async_wait_for_checks(until)

    async def _async_timer(self, _now: datetime) -> None:
        # At most one step waits while another runs: a long step delays the next one instead
        # of dropping it, so a due keep-alive follows at once.
        if self._tick_waiting:
            return
        self._tick_waiting = True
        try:
            async with self._lock:
                self._tick_waiting = False  # running now: the next timer call may wait
                if self._stopped or self._stopping:
                    return  # a step queued behind a slow one does not go before the stop
                await self._async_run_step(dt_util.utcnow().timestamp())
        finally:
            self._tick_waiting = False
        await self._async_learning_calls()
        self._notify()

    async def _async_run_step(self, now: float) -> None:
        """One step (lock held) as a task that a stop can cancel."""
        # Started eagerly: a step that never waits runs to its end at once, as a plain call would.
        task = create_eager_task(self._async_tick_locked(now), name="vtherm_smart_boiler step")
        self._step_task = task
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                task.cancel()
                raise
            # Cancelled by a stop, which hands back next.
        finally:
            self._step_task = None

    # --- switching ------------------------------------------------------------------------

    def blockers(self, now: float) -> tuple[str, ...]:
        """Why control may not run now (translation keys); empty when it may."""
        config = self._coordinator.config
        found = config_blockers(self.options, config.installation, config.shared_signals)
        if (missing := self._integration_missing()) is not None:
            found.append(missing)
        link = self._coordinator.link
        if link.zones_of_another_kind():
            found.append("zone_not_vt")  # a hand edit: only VT climates are zones (X5.7)
        if link.zones_on_boiler_thermostat([*config.signals.values(), *self.options.entities]):
            # X5.19: it would ask for heat whenever the flame burns; VT's entries are read at
            # every step, as VT can be reconfigured without the options changing.
            found.append("zone_on_boiler_thermostat")
        if self._hass.state is not CoreState.running:
            # VT starts its thermostats only once Home Assistant has started; `is_running` is
            # already true while it starts.
            found.append("ha_starting")
        if now - self._coordinator.monitoring_since < config.monitor.monitoring_days * DAY:
            found.append("monitoring_period")
        vt_boiler = self._coordinator.link.vt_central_boiler_configured()
        if vt_boiler is None:
            if not self._vt_boiler_in_grace(now):
                found.append("vt_central_boiler_unknown")  # cannot be ruled out: wait
        elif vt_boiler:
            found.append("vt_central_boiler_active")
        if self._unit_not_supported():
            found.append("setpoint_unit_not_supported")  # its range cannot be checked either
        else:
            grid = self._grid()
            if grid is not None and grid.too_coarse:
                # A value on so coarse a grid could read back beyond the tolerance (P-15).
                found.append("setpoint_step_too_coarse")
            if self._outside_entity_range(grid):
                found.append("setpoint_outside_entity_range")
        if self._session.failed:
            found.append("control_error")
        if self._coordinator.monitor_lost(now):
            # A hand-back; control resumes on its own once the monitor works again (answer I).
            found.append("monitor_failed")
        control = self._session.loop.control
        if control.latched and HEATING_OFF_IGNORED in control.latched_by:
            # The boiler did not take "heating off" from the start of the session (answer O):
            # blocked until the user switches control off and on after fixing it (X5.21).
            found.append(HEATING_OFF_IGNORED)
        return tuple(found)

    def _integration_missing(self) -> str | None:
        """X5.5 (P-69): the integration a gateway path writes through is gone or disabled — the
        ``opentherm_gw`` entry of the gateway picked, or every MQTT entry. One merely not loaded
        yet at a start is Home Assistant starting; one offline later fails its writes."""
        path = self.options.write_path
        entries = self._hass.config_entries.async_entries
        if path is WritePath.OPENTHERM_GW and self.options.gateway_id:
            gateway = self.options.gateway_id
            if not any(
                entry.disabled_by is None
                for entry in entries(OPENTHERM_GW_DOMAIN, include_ignore=False)
                if str(entry.data.get("id")) == gateway
            ):
                return "gateway_not_set_up"
        elif path is WritePath.OTGW_MQTT and not any(
            entry.disabled_by is None for entry in entries(MQTT_DOMAIN, include_ignore=False)
        ):
            return "mqtt_not_set_up"
        return None

    def _vt_boiler_in_grace(self, now: float) -> bool:
        """P-105: VT's central boiler unknown — its central entry reloading — does not count as
        a blocker for ``VT_BOILER_GRACE_S`` where it was known to be off at the step before."""
        if not self._vt_boiler_off:
            return False
        since = self._vt_boiler_unknown_since
        return since is None or now - clock_start(since, now) < VT_BOILER_GRACE_S

    def _follow_vt_boiler(self, now: float) -> tuple[str, ...]:
        """VT's central boiler at this step, for P-105's grace; the blockers that wait in it."""
        configured = self._coordinator.link.vt_central_boiler_configured()
        if configured is not None:
            self._vt_boiler_off = configured is False
            self._vt_boiler_unknown_since = None
            return ()
        if self._vt_boiler_off and self._vt_boiler_unknown_since is None:
            self._vt_boiler_unknown_since = now
        return ("vt_central_boiler_unknown (grace)",) if self._vt_boiler_in_grace(now) else ()

    def _grid(self) -> Grid | None:
        """The setpoint entity's grid (P-15), on the entity path; ``None`` elsewhere or without
        a step."""
        options = self.options
        if options.write_path is not WritePath.ENTITY or not options.setpoint_entity:
            return None
        return read_grid(self._hass, options.setpoint_entity)

    def _unit_not_supported(self) -> bool:
        """A setpoint entity in a unit that is not a temperature: a value written would mean
        something else to it."""
        options = self.options
        if options.write_path is not WritePath.ENTITY or not options.setpoint_entity:
            return False
        return temperature_unit_of(self._hass, options.setpoint_entity) is False

    def _outside_entity_range(self, grid: Grid | None) -> bool:
        """A setpoint entity that would reject a value control may write (a limit, the low "off"
        value or the hand-back value), or has no value on its grid for it inside the limits
        (P-15): every write of it would fail."""
        options = self.options
        if options.write_path is not WritePath.ENTITY or not options.setpoint_entity:
            return False
        low, high = read_bounds(self._hass, options.setpoint_entity)
        control = options.loop.control
        lowest, highest = write_bounds(
            control.limits, control.circuit_max, control.boiler_max, control.circuit_floor
        )
        # Each value with the bounds its grid value must keep.
        values: list[tuple[float, float | None, float | None]] = [
            (control.limits.hard_min, control.limits.hard_min, highest),
            (highest_water_temperature(control), lowest, highest),
        ]
        if not options.loop.ch_writes:
            values.append((options.loop.off_setpoint, None, options.loop.off_setpoint))
        if options.hand_back is HandBack.VALUE and options.hand_back_value is not None:
            values.append((options.hand_back_value, None, highest))
        if any(
            (low is not None and value < low) or (high is not None and value > high)
            for value, _low, _high in values
        ):
            return True
        return grid is not None and any(
            grid.put(value, below, above) is None for value, below, above in values
        )

    async def async_set_enabled(self, enabled: bool, now: float | None = None) -> None:
        """Switch control on or off; switching off hands back at once."""
        async with self._lock:
            self._restored = True
            if self._stopped or self._stopping or enabled == self.enabled:
                return
            now = dt_util.utcnow().timestamp() if now is None else now
            self.enabled = enabled
            # Any change of the switch by the user clears an internal error (a latch needs off,
            # then on).
            self._session.failed = False
            self._session.alarms.discard(ControlAlarm.CONTROL_ERROR)
            if not enabled:
                self._clear_stopped_heating()  # the user has seen to it (S-10)
            # The wish is stored before anything else can fail (P-11).
            await self._coordinator.async_save_control_now()
            await self._async_run_step(now)
            if not enabled:
                self._end_session()
                # The user has seen to it: the monitor's issue, or its note, goes (answer I).
                self._delete_monitor_issue()
        await self._async_learning_calls()
        self._notify()

    def _end_session(self) -> None:
        """A new session starts fresh; only the learning pauses carry on (a pending hand-back and
        its alarm belong to the unit, not the session), and each guard's one rewrite, kept for its
        day (provisional, K4). A latch goes with the session, and its repair issue with it; so
        does a target ignored from the start, which the new session tries again."""
        now = dt_util.utcnow().timestamp()
        self._session = _Session(
            loop=new_session(self._session.loop, now), learning=self._session.learning
        )
        self._writer = None
        self._baseline = None
        self._quiet_since = None
        self._external_seen_on = False
        self._external_renew = False
        self._forget_last_command()
        self._report_latched(anew=False)
        self._coordinator.schedule_control_save()

    def _forget_last_command(self) -> bool:
        """A session ended for a reason other than a stop's own hand-back: its last command is
        not to be given again. Whether there was one; the caller stores it."""
        if self._stopping or self._last_command is None:
            return False
        self._last_command = None
        self._command_stored = None
        return True

    # --- the step -------------------------------------------------------------------------

    async def _async_tick_locked(self, now: float) -> None:
        if not (self.options.configured or self.follow_learning):
            return
        try:
            await self._async_step(now)
        except Exception:
            # A lasting error is logged once with its trace, then at DEBUG (P-24).
            first = not self._step_failing
            self._step_failing = True
            if first:
                _LOGGER.exception("The control step failed; handing control back")
            else:
                _LOGGER.debug("The control step failed again", exc_info=True)
            newly = not self._session.failed or ControlAlarm.CONTROL_ERROR not in (
                self._session.alarms
            )
            self._session.failed = True
            self._session.alarms.add(ControlAlarm.CONTROL_ERROR)
            if self._forget_last_command() or newly:
                # Stored before the hand-back is tried: the error outlives a crash (C10).
                await self._coordinator.async_save_control_now()
            try:
                await self._async_hand_back_now(now)
            except Exception:
                if first:
                    _LOGGER.exception("Handing control back after an error failed")
                else:
                    _LOGGER.debug("Handing control back after an error failed again", exc_info=True)
            self._coordinator.schedule_control_save()
            self._status = replace(
                self._status,
                blockers=tuple(dict.fromkeys((*self._status.blockers, "control_error"))),
                mode=ControlMode.NOT_ALLOWED,
                alarms=frozenset(self._alarms()),
                hand_back_check=self._hand_back_shown,
                frost_protection_by=self._frost_protection_shown(),
            )
        else:
            if self._step_failing:
                self._step_failing = False
                if self._session.failed:
                    _LOGGER.info(
                        "The control step works again; control stays stopped until the control "
                        "switch is switched off and on"
                    )
                else:
                    _LOGGER.info("The control step works again")

    async def _async_step(self, now: float) -> None:
        session = self._session
        if (
            self._hand_back_pending
            and not session.loop.control.controlling
            and self.options.configured
            and not self._restore_pending  # decision 3: the restore comes first
        ):
            await self._async_follow_hand_back(now)
        if self.hand_back_only:
            # Resumes the last run left are followed until SmartPI's flag reads on (C15).
            await self._async_release_learning(now)
            self._report_owed()
            return
        if not self._restored:
            if now - self._started_at < RESTORE_WAIT_S:
                return  # the switch has not restored the user's choice yet: decide nothing
            # The switch never came (disabled in Home Assistant): control counts as off, and
            # so does the wish from now on (answer K).
            _LOGGER.info("The control switch did not restore its state: control is off")
            self._restored = True
            self._coordinator.schedule_control_save()
        if self._follow_return(now):
            await self._coordinator.async_save_control_now()  # the latch is gone
            session = self._session
        waiting = self._follow_vt_boiler(now)
        blockers = self.blockers(now)
        monitor_failed = "monitor_failed" in blockers
        # Home Assistant starting alone does not stop a command kept or restored (decision 3).
        if self.enabled and set(blockers) <= {HA_STARTING} and self._writer is None:
            self._writer = self._writer_factory(self._hass, self.options)
        zones = self._coordinator.link.zones()
        snapshot = self._coordinator.transport.snapshot(now)
        dhw = self._coordinator.dhw_now(snapshot)
        if dhw:
            self._dhw_seen_at = now  # a draw keeps a third value from being judged (W6)
        self._watch_external(now)  # another controller switching it off steps aside at once
        inputs = self._inputs(now, snapshot, zones, blockers)
        confirmed = self._confirmed()
        if session.loop.setpoint.baseline is not None:
            # Noted before the step: a timeout hand-back is released back to this value.
            self._baseline = session.loop.setpoint.baseline
        was_latched = session.loop.control.latched
        before = session.loop
        setpoint_context, heating_context = self._contexts(now, dhw)
        session.loop, out = loop_step(
            session.loop,
            inputs,
            confirmed,
            self.options.loop,
            self._confirmed_heating(),
            setpoint_context=setpoint_context,
            heating_context=heating_context,
            grid=self._grid(),
        )
        if session.loop.control.latched and not was_latched:
            self._latched_now()
            blockers = self.blockers(now)  # a latch may name a blocker of its own (answer O)
        if out.hand_back:
            self._note_blocker_release(out, blockers)  # stored with the hand-back, at once
            await self._async_hand_back_writes(now)
        else:
            await self._async_writes(out, now)
        await self._follow_restore(now, blockers, out.hand_back)
        controlling = session.loop.control.controlling
        if out.hand_back and monitor_failed:
            self._report_monitor_failed(now)  # the session held the boiler
        elif self._monitor_issue_since is not None and controlling and not monitor_failed:
            self._note_monitor_recovered(now)  # control holds the boiler again
        self._follow_stopped_heating(now, blockers)
        self._follow_frost(now, zones)
        self._follow_frost_closed(out.decision.frost_closed, zones)
        unknown = self._follow_unknown_zones(now, zones)
        self._follow_no_zone_known(now, out.decision.reasons)
        decision = out.decision
        for flagged, alarm in (
            # Decision 3: nothing can ask for heat — every zone unknown after the recognition
            # period and the graces; or a criterion no known zone can feed (P-14).
            (self.enabled and decision.zones_unknown, ControlAlarm.NO_ZONE_KNOWN),
            (
                self.enabled and bool(decision.criteria_without_data),
                ControlAlarm.DEMAND_CRITERION_NO_DATA,
            ),
            # Every topology, whenever the switch is on and the link is lost — whatever a
            # blocker, a latch or a restart shows (P-08): control hands back if it held the
            # boiler; stand-alone that stops heating, so the user is told.
            (self.enabled and out.decision.link_lost, ControlAlarm.BOILER_LINK_LOST),
            (out.decision.frost_stuck, ControlAlarm.FROST_NOT_WARMING),  # heating goes on
            (out.decision.correction_at_limit, ControlAlarm.CORRECTION_AT_LIMIT),  # information
            (self._outdoor_suspect(), ControlAlarm.OUTDOOR_SENSOR_SUSPECT),  # left out
            (monitor_failed, ControlAlarm.MONITOR_FAILED),  # a blocker: control is handed back
        ):
            if flagged:
                session.alarms.add(alarm)
            else:
                session.alarms.discard(alarm)
        for event in out.events:
            session.alarms.add(_EVENT_ALARM[event])
        # Per target (P-09): on while a guard is ignored from the start, whichever it is — and
        # while the latch for heating off ignored from the start holds, a restart included.
        ignored = out.ignored
        latch = session.loop.control
        if latch.latched and HEATING_OFF_IGNORED in latch.latched_by and "heating" not in ignored:
            ignored = (*ignored, "heating")
        for flagged, alarm in (
            (bool(ignored), ControlAlarm.WRITE_IGNORED),
            (out.commands_lost, ControlAlarm.COMMANDS_LOST),  # information: sent again
            (bool(out.unconfirmed), ControlAlarm.CONFIRMATION_MISSING),  # information only
        ):
            if flagged:
                session.alarms.add(alarm)
            else:
                session.alarms.discard(alarm)
        if out.events or _memory_moved(before, session.loop):
            # The alarm behind a latch; the values from before the plugin and the fall-backs
            # without a trace a later judgement rests on.
            await self._coordinator.async_save_control_now()
        setpoint_check, heating_check = self._checks()
        command = out.decision.command
        await self._async_learning(
            now,
            snapshot,
            zones,
            None if command is None else command.setpoint,
            out.heating_on,
            out.blocked,
        )
        self._status = ControlStatus(
            configured=True,
            enabled=self.enabled,
            blockers=blockers,
            mode=out.decision.mode,
            reasons=tuple(r.value for r in out.decision.reasons),
            requested=session.loop.setpoint.written,
            target=out.decision.target,
            heating_on=out.heating_on,
            read_back=confirmed,
            setpoint_check=setpoint_check,
            heating_check=heating_check,
            last_change_at=self._last_change_at,
            hand_back_at=self._hand_back_at,
            alarms=frozenset(self._alarms()),
            paused_zones=tuple(sorted(session.learning.paused)),
            latched_by=session.loop.control.latched_by if session.loop.control.latched else (),
            unknown_zones=unknown,
            room_sensor_lost_zones=tuple(z.zone_id for z in zones if z.room_sensor_lost),
            writes_stopped=out.blocked,
            hand_back_check=self._hand_back_shown,
            monitor_failed_since=self._coordinator.monitor_failed_since,
            frost_protection_by=self._frost_protection_shown(),
            ignored_targets=ignored,
            unconfirmed_targets=out.unconfirmed,
            blockers_waiting=waiting,
            criteria_without_data=decision.criteria_without_data,
            correction=decision.correction,
            activation_at=decision.activation_at,
            frost_closed_zones=tuple(self._frost_issue_shown),
        )

    async def async_reset_correction(self) -> None:
        """The "Reset comfort correction" button (answer J): the running session's correction to
        0 at once, with its "at limit" timer; the water is decided anew at the next step. No
        option is saved, nothing is reloaded or handed back; the rise may start again under its
        rules. While control does not hold the boiler the correction is already 0: nothing to
        do, and no error."""
        async with self._lock:
            if self._stopped or self._stopping:
                return
            loop = self._session.loop
            if not loop.control.controlling:
                return
            was = loop.control.correction
            self._session.loop = replace(loop, control=reset_correction(loop.control))
            self._status = replace(self._status, correction=0.0)
            self._session.alarms.discard(ControlAlarm.CORRECTION_AT_LIMIT)
            self._status = replace(self._status, alarms=frozenset(self._alarms()))
            _LOGGER.info("The comfort correction was reset by the user (it was %.1f K)", was)
        self._notify()

    async def _follow_restore(self, now: float, blockers: Sequence[str], handed_back: bool) -> None:
        """Decision 3: a restore still pending once the recognition period is over, or whose
        conditions failed — control switched off, a latch, an internal error, a blocker other
        than Home Assistant starting — gives way: the owed hand-back goes first (the core wrote
        nothing new in that step), and the next step decides. A blocker that stops it, where a
        hand-back stops heating, raises S-10's issue as for a session a blocker ended."""
        if not self._restore_pending:
            return
        control = self._session.loop.control
        blocked = [blocker for blocker in blockers if blocker != HA_STARTING]
        failed = not self.enabled or control.latched or self._session.failed or bool(blocked)
        if control.controlling and not failed:
            return  # the core holds it: the first write that goes through completes it
        if not failed and in_recognition(control.zones):
            return  # it waits for its write target or the boiler link
        self._restore_pending = False
        _LOGGER.info(
            "The last command could not be given again after the restart; the owed hand-back "
            "goes first"
        )
        counting = [blocker for blocker in blocked if blocker not in _QUIET_BLOCKERS]
        if self.enabled and counting and self._stops_heating():
            self._stopped_by_blocker = True  # the session a restart carried over, ended (S-10)
        if self._hand_back_pending and not handed_back and not control.controlling:
            await self._async_try_hand_back(now)
        self._coordinator.schedule_control_save()

    def _follow_no_zone_known(self, now: float, reasons: Sequence[Reason]) -> None:
        """Decision 3's repair issue once every configured zone has been unknown for ten
        minutes, whatever control does: what it says follows what control does then — the
        usual "off", the hand-back to a working thermostat, or only the monitor."""
        kind: str | None = None
        if no_zone_issue_due(self._session.loop.control.zones, now):
            kind = "monitor"
            if Reason.ZONES_UNKNOWN in reasons:
                kind = "handed_back" if working_thermostat(self.options) else "off"
        self._coordinator.report_no_zone_known(kind)

    def _target_ready(self) -> bool:
        """The write target can take a command: on the entity path each entity written to is
        there with a value (a gateway's read-back tells for the gateway paths, P-21)."""
        options = self.options
        if options.write_path is not WritePath.ENTITY:
            return True
        targets = [options.setpoint_entity]
        if options.loop.ch_writes:
            targets.append(options.ch_entity)
        if options.hand_back is HandBack.SWITCH:
            targets.append(options.hand_back_entity)
        for entity in filter(None, targets):
            state = self._hass.states.get(entity)
            if state is None or state.state in UNAVAILABLE_STATES:
                return False
        return True

    def _follow_unknown_zones(self, now: float, zones: Sequence[ZoneState]) -> tuple[str, ...]:
        """Zones whose state is not known: the known ones decide meanwhile; one unknown for long
        raises an alarm, as frost protection cannot see it. So does one whose room sensor is
        lost for long, or whose VT safety mode is on (R6, T2, S-35): VT keeps the last
        temperature and still runs the zone, so its demand counts; one VT has not started; and
        one frost protection watches whose room temperature is implausible (S-06)."""
        control = self.options.loop.control
        max_age = control.zone_max_age_s
        watched = control.frost.zone
        unknown = tuple(z.zone_id for z in zones if not z.is_known(now, max_age))
        blind = {
            *unknown,
            *(
                z.zone_id
                for z in zones
                if z.room_sensor_lost
                or not z.started
                or (
                    (watched is None or z.zone_id == watched)
                    and z.temperature is not None
                    and not plausible_room(z.temperature)
                )
            ),
        }
        self._unknown_since = {z: self._unknown_since.get(z, now) for z in sorted(blind)}
        long_unknown = any(now - t >= ZONE_UNKNOWN_ALARM_S for t in self._unknown_since.values())
        if self.enabled and long_unknown:
            self._session.alarms.add(ControlAlarm.ZONE_UNKNOWN)
        else:
            self._session.alarms.discard(ControlAlarm.ZONE_UNKNOWN)
        return unknown

    def _alarms(self) -> set[ControlAlarm]:
        alarms = set(self._session.alarms)
        if self._hand_back_failed:
            alarms.add(ControlAlarm.HAND_BACK_FAILED)
        if self._frost_alarm:
            alarms.add(ControlAlarm.HANDED_BACK_IN_FROST)
        return alarms

    # --- stopping with an alarm (V7: S-10, S-57, S-11) ------------------------------------

    def _frost_protection_shown(self) -> str | None:
        """Who keeps frost protection now, as the control switch shows it (S-57)."""
        shown = frost_protection_by(self.options, self._session.loop.control.controlling)
        return None if shown is None else shown.value

    def _stops_heating(self) -> bool:
        """A hand-back stops heating: nothing heats the house once control lets go."""
        return hand_back_effect(self.options) is HandBackEffect.HEATING_STOPS

    def _follow_frost(self, now: float, zones: Sequence[ZoneState]) -> None:
        """S-57: while control does not hold the boiler where a hand-back stops heating, a room
        near freezing raises the alarm "handed back in frost" at the step that sees it, and it
        goes once every watched room with a known temperature is back at the release, or once
        control holds the boiler again. Information only: it never starts heating."""
        control = self.options.loop.control
        raised = handed_back_in_frost(
            zones,
            now,
            control.zone_max_age_s,
            control.frost,
            heating_stops=self._stops_heating(),
            controlling=self._session.loop.control.controlling,
            active=self._frost_alarm,
        )
        if raised and not self._frost_alarm:
            _LOGGER.warning(
                "A room is near freezing while control does not hold the boiler, and with this "
                "installation nothing heats then: frost protection rests on the boiler's own"
            )
        elif self._frost_alarm and not raised:
            _LOGGER.info("No room is near freezing any more, or control holds the boiler again")
        self._frost_alarm = raised

    def _follow_frost_closed(self, closed: Sequence[str], zones: Sequence[ZoneState]) -> None:
        """Decision 4: a watched room below the frost limit that VT keeps closed raises a repair
        issue at the step that sees it — the core flags it outside the recognition period and
        holds its flags meanwhile — while control is switched on (provisional, K4: not with
        control off or in monitor-only mode, where the plugin does no frost heating). It names
        each room and its temperature; it goes once no room is flagged — at or above the
        release, or able to take heat — or control is switched off."""
        flagged = tuple(closed) if self.enabled and self.options.configured else ()
        temperatures = {z.zone_id: z.temperature for z in zones if z.temperature is not None}
        self._show_frost_closed(
            {zone: temperatures[zone] for zone in flagged if zone in temperatures}
        )

    def _show_frost_closed(self, rooms: Mapping[str, float]) -> None:
        """The frost issue for these rooms (°C): raised, updated when the rooms change or a
        temperature moved by ``FROST_CLOSED_SHOWN_K``, deleted when there are none."""
        shown = self._frost_issue_shown
        issue_id = f"{FROST_CLOSED_ISSUE}_{self._coordinator.config_entry.entry_id}"
        if not rooms:
            if shown:
                ir.async_delete_issue(self._hass, DOMAIN, issue_id)
                _LOGGER.info("No watched room below the frost limit is kept closed any more")
                self._frost_issue_shown = {}
            return
        moved = rooms.keys() != shown.keys() or any(
            abs(rooms[zone] - shown[zone]) >= FROST_CLOSED_SHOWN_K for zone in rooms
        )
        if not moved:
            return
        if rooms.keys() != shown.keys():
            _LOGGER.warning(
                "A room below the frost limit cannot get heat: Versatile Thermostat keeps it "
                "closed (%s)",
                ", ".join(rooms),
            )
        unit = str(self._hass.config.units.temperature_unit)
        named = ", ".join(
            f"{self._coordinator.link.zone_name(zone)} "
            f"({TemperatureConverter.convert(t, '°C', unit):.1f} {unit})"
            for zone, t in rooms.items()
        )
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=FROST_CLOSED_ISSUE,
            translation_placeholders={"zones": named},
        )
        self._frost_issue_shown = dict(rooms)

    def _note_blocker_release(self, out: LoopOutput, blockers: tuple[str, ...]) -> None:
        """S-10: a blocker ends the session that held the boiler, where a hand-back stops
        heating — any blocker but Home Assistant starting, an internal error or the monitor
        failing, which have their own. Noted before the hand-back, whose save stores it at
        once: a run that ends before the issue is raised leaves it to the next."""
        if (
            Reason.PRECONDITION in out.decision.reasons
            and any(blocker not in _QUIET_BLOCKERS for blocker in blockers)
            and self._stops_heating()
        ):
            self._stopped_by_blocker = True

    def _follow_stopped_heating(self, now: float, blockers: tuple[str, ...]) -> None:
        """S-10: once a blocker has ended a session that held the boiler where a hand-back
        stops heating, a repair issue follows when a blocker that counts has held for
        ``STOPPED_HEATING_S`` — with Home Assistant running. The issue goes when control
        controls again or the user switches control off; the unit stopping takes it too, and
        the next run raises it again while a blocker holds."""
        if self._session.loop.control.controlling:
            self._clear_stopped_heating()  # control holds the boiler again
            return
        counting = [blocker for blocker in blockers if blocker not in _QUIET_BLOCKERS]
        if not counting or "ha_starting" in blockers:
            self._blocked_since = None  # the minute counts once Home Assistant runs
            return
        self._blocked_since = clock_start(self._blocked_since, now)  # a clock set back (C9)
        if (
            self._stopped_by_blocker
            and self.enabled
            and self._stops_heating()
            and not self._stopped_heating_issue
            and now - self._blocked_since >= STOPPED_HEATING_S
        ):
            self._report_stopped_heating(counting)

    def _stopped_heating_issue_id(self) -> str:
        return f"{STOPPED_HEATING_ISSUE}_{self._coordinator.config_entry.entry_id}"

    def _report_stopped_heating(self, blockers: Sequence[str]) -> None:
        """The repair issue of a blocker that stopped heating: an error, as the hand-back stops
        heating; raised anew, so an earlier one the user dismissed does not hide it."""
        _LOGGER.warning(
            "Control stays stopped by %s, and with this installation a hand-back stops heating: "
            "the boiler does not heat until control resumes",
            ", ".join(blockers),
        )
        issue_id = self._stopped_heating_issue_id()
        ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=STOPPED_HEATING_ISSUE,
        )
        self._stopped_heating_issue = True

    def _clear_stopped_heating(self) -> None:
        """Control holds the boiler again, or the user switched it off: nothing of S-10 is left,
        and the store follows."""
        self._blocked_since = None
        if self._stopped_by_blocker:
            self._stopped_by_blocker = False
            self._coordinator.schedule_control_save()
        if self._stopped_heating_issue:
            self._delete_stopped_heating_issue()

    def _delete_stopped_heating_issue(self) -> None:
        self._stopped_heating_issue = False
        ir.async_delete_issue(self._hass, DOMAIN, self._stopped_heating_issue_id())

    def _latched_now(self) -> None:
        """The latch was set in this step: for another controller, the plugin steps aside — the
        whole safe hand-back follows at once, which no guard holds back and which skips no
        target (the user's answer H); for heating off ignored from the start, control is blocked
        and hands back (answer O). Its repair issue is raised anew."""
        latched_by = self._session.loop.control.latched_by
        if ControlAlarm.OUTSIDE_CHANGE.value in latched_by:
            _LOGGER.warning(
                "Another controller writes to the boiler: control steps aside with the safe "
                "hand-back and stays off until control is switched off and on"
            )
        if HEATING_OFF_IGNORED in latched_by:
            _LOGGER.warning(
                'The boiler did not take "heating off" from the start of the session: control '
                "hands the boiler back and stays blocked until control is switched off and on"
            )
        self._report_latched(anew=True)

    def _latch_cause(self) -> str | None:
        """The cause the entry's one latch issue names: another controller, or heating off
        ignored from the start; ``None`` for any other latch (Y1 names those)."""
        control = self._session.loop.control
        if self.hand_back_only or not control.latched:
            return None
        for cause in (ControlAlarm.OUTSIDE_CHANGE.value, HEATING_OFF_IGNORED):
            if cause in control.latched_by:
                return cause
        return None

    def _report_latched(self, anew: bool) -> None:
        """The entry's one latch issue while control stays latched after stepping aside from
        another controller (V7), or blocked for heating off ignored from the start (answer O),
        its text naming the cause; deleted otherwise. ``anew``: the latch was just set — raised
        anew, so an earlier one the user dismissed does not hide it; at a start the issue a
        stored latch keeps is raised as it was left. An error where the hand-back stops heating,
        else a warning; not fixable: switching control off and on clears the latch."""
        issue_id = f"{LATCHED_ISSUE}_{self._coordinator.config_entry.entry_id}"
        cause = self._latch_cause()
        if cause is None:
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)
            return
        if anew:
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if self._stops_heating() else ir.IssueSeverity.WARNING,
            translation_key=(
                LATCHED_ISSUE
                if cause == ControlAlarm.OUTSIDE_CHANGE.value
                else f"{LATCHED_ISSUE}_{HEATING_OFF_IGNORED}"
            ),
        )

    def _boiler_link(self, snapshot: BoilerSnapshot) -> bool:
        """The boiler's own signals are fresh at this step: flame and flow known, each within its
        own age limit where the user set one — the flame's included (P-41). The core judges the
        steps over a window (X2): lost after five stale minutes within ten.

        Many sources (MQTT among them) report only on change, so a steady reading is not a stale
        one: without a limit only availability counts. The OTGW firmware over MQTT turns every
        entity unavailable within about 90 s of dropping off (its availability topic); a broken
        link between its ESP and its PIC is not seen through Home Assistant at all — its values
        only freeze (Q3.6), which the freshness option's text says.
        """
        freshness = self._coordinator.config.freshness
        flame = snapshot.flag(Signal.FLAME, freshness.get(Signal.FLAME))
        flow = snapshot.number(Signal.FLOW, freshness.get(Signal.FLOW))
        return flame is not None and flow is not None

    def _inputs(
        self,
        now: float,
        snapshot: BoilerSnapshot,
        zones: Sequence[ZoneState],
        blockers: tuple[str, ...],
    ) -> ControlInputs:
        coordinator = self._coordinator
        config = coordinator.config
        # One freshness rule: a steady reading is not a stale one, so its age counts only with a
        # limit the user set — each by its own, the weather entity's apart from the outdoor
        # sensor's (P-41). A sensor the monitor found stuck leaves the curve to the weather
        # entity, then the held value and the fallback; one far from the weather gives way where
        # the weather reads colder (more heat, which the valves throttle), and without a weather
        # reading where the check saw it read warmer.
        outdoor_age = config.freshness.get(Signal.OUTDOOR)
        weather = None
        if config.weather:
            reading = read_weather_temperature(self._hass, config.weather)
            if reading.is_fresh(now, config.weather_max_age_s):
                weather = float(reading.value) if reading.value is not None else None
        check = getattr(self._coordinator.analysis, "outdoor", None)
        sensor = curve_sensor(check, snapshot.number(Signal.OUTDOOR, outdoor_age), weather)
        link = self._boiler_link(snapshot)
        self._link_seen = self._link_seen or link
        restoring = self._restore_pending
        return ControlInputs(
            now=now,
            enabled=self.enabled,
            blockers=blockers,
            hand_back_alarms=self._hand_back_alarms(),
            boiler_link=link,
            # Decision 3's restore waits, within the recognition period, for a link that has
            # not reported since the start: no loss is declared meanwhile (X2).
            link_unreported=restoring and not self._link_seen,
            restored_command=self._restore_command if restoring else None,
            target_ready=self._target_ready(),
            read_back_known=self._read_back_known(),
            flame=snapshot.flag(Signal.FLAME, config.freshness.get(Signal.FLAME)),
            dhw=coordinator.dhw_now(snapshot),
            outdoor_sensor=sensor,
            outdoor_weather=weather,
            zones=tuple(zones),
            foreign_heat=self._foreign_heat(),
        )

    def _foreign_heat(self) -> bool | None:
        """Foreign heat warms a zone, as the monitor sees it (the comfort correction freezes):
        ``None`` where no zone has a source, or the monitor's data is stale — unknown freezes
        nothing."""
        coordinator = self._coordinator
        data = coordinator.data
        if data is None or coordinator.monitor_failing:
            return None
        states = [view.foreign_heat for view in data.zones.values() if view.foreign_heat]
        if not states:
            return None
        return any(state.active for state in states)

    def _read_back_known(self) -> bool:
        """On a gateway path its setpoint read-back holds a value: without one, a hand-back could
        never be seen to get through, so control does not take the boiler (P-21)."""
        return self.options.write_path not in OTGW_PATHS or self._confirmed() is not None

    def _outdoor_suspect(self) -> bool:
        """The monitor's check found the outdoor sensor stuck, or far from the weather."""
        check = getattr(self._coordinator.analysis, "outdoor", None)
        return check is not None and check.status in (OutdoorStatus.STUCK, OutdoorStatus.DEVIATES)

    def _hand_back_alarms(self) -> tuple[str, ...]:
        """Active alarms whose reaction is to hand control back. The monitor's are left out
        while its refresh fails: its last data is stale, and unknown values never count
        (decision 7)."""
        active: list[str] = []
        data = self._coordinator.data
        if data is not None and not self._coordinator.monitor_failing:
            active += [
                kind.value
                for kind, alarm in data.alarms.items()
                if alarm.active and self.options.reaction(kind.value) is AlarmReaction.HAND_BACK
            ]
        for alarm in sorted(self._session.alarms):
            if alarm in _INFO_ONLY or alarm in (
                ControlAlarm.CONTROL_ERROR,
                ControlAlarm.HAND_BACK_FAILED,
                ControlAlarm.BOILER_LINK_LOST,
                ControlAlarm.ZONE_UNKNOWN,
                ControlAlarm.FROST_NOT_WARMING,
                ControlAlarm.CORRECTION_AT_LIMIT,
                ControlAlarm.OUTDOOR_SENSOR_SUSPECT,
                ControlAlarm.MONITOR_FAILED,
                ControlAlarm.HANDED_BACK_IN_FROST,
                ControlAlarm.NO_ZONE_KNOWN,
                ControlAlarm.DEMAND_CRITERION_NO_DATA,
            ):
                # A blocker, a retry of its own, a hand-back already made, information, or
                # decision 3's own end state.
                continue
            if self.options.reaction(alarm.value) is AlarmReaction.HAND_BACK:
                active.append(alarm.value)
        return tuple(active)

    def _checks(self) -> tuple[str | None, str | None]:
        """Where the setpoint and heating on/off stand with the device, as shown."""
        options = self.options
        loop = self._session.loop
        gateway = options.write_path in OTGW_PATHS
        self_echo = bool(options.confirmed_entity) and (
            options.confirmed_entity == options.setpoint_entity
        )
        setpoint = _shown(
            confirmation(loop.setpoint, options.loop.setpoint_guard), gateway, self_echo
        )
        if not options.loop.ch_writes:
            return setpoint, setpoint  # "off" goes as a low setpoint
        switch: GuardConfig = options.loop.switch_guard
        self_echo = bool(options.ch_confirmed_entity) and (
            options.ch_confirmed_entity == options.ch_entity
        )
        return setpoint, _shown(confirmation(loop.switch, switch), gateway, self_echo)

    def _confirmed_heating(self) -> bool | None:
        """Heating on/off as its echo reports it; ``None`` without one."""
        entity = self.options.ch_confirmed_entity
        return read_on_off(self._hass, entity) if entity else None

    def _confirmed(self) -> float | None:
        """The setpoint the boiler reports back; ``None`` when unknown. A read-back that reports
        only on change keeps its value, so its age does not make it unknown."""
        entity = self.options.confirmed_entity
        if not entity:
            return None
        reading = read_temperature(self._hass, entity)
        return None if reading.value is None else float(reading.value)

    # --- writes ---------------------------------------------------------------------------

    async def _async_writes(self, out: LoopOutput, now: float) -> None:
        writer = self._writer
        if writer is None:
            if out.heating is not None or out.setpoint is not None:
                _LOGGER.error("Control asked for a write without a writer; nothing written")
            return
        loop = self._session.loop
        # The setpoint first: a gateway applies heating on/off only while its setpoint override
        # is in force. A write that fails is sent again at the next step. Each write is made
        # only once it is due: a stop cancelling the step leaves none behind unawaited (P-52).
        setpoint_ok = heating_ok = False
        if out.setpoint is not None:
            value = out.setpoint.value
            setpoint_ok = await self._async_write(
                "setpoint", lambda: writer.write_setpoint(value), now, out.setpoint
            )
            if not setpoint_ok:
                loop = replace(loop, setpoint=write_failed(loop.setpoint))
        if out.heating is not None:
            on = out.heating.value == ON
            heating_ok = await self._async_write(
                "heating", lambda: writer.write_heating(on), now, out.heating
            )
            if not heating_ok:
                loop = replace(loop, switch=write_failed(loop.switch))
        self._session.loop = loop
        await self._async_remember_command(out, setpoint_ok, heating_ok, now)
        holds = out.decision.command is not None and not out.blocked
        if self._external_renew and holds:
            # Found off after an outage of its device (M15): turned on again at once.
            self._external_renew = False
            await self._async_write(
                "external", writer.renew_external, now, WriteAction(ON, WriteKind.RESEND)
            )
        elif self._keeps_external_alive() and holds:
            # Control holds the boiler: an external-control switch declared expiring is turned on
            # again every keep-alive (P-40), one declared held every five minutes and at once
            # when it came back from unavailable (X1), whatever else is written.
            returned, self._external_returned = self._external_returned, False
            await self._async_write(
                "external",
                lambda: writer.keep_alive(returned),
                now,
                WriteAction(ON, WriteKind.KEEPALIVE),
            )

    def _keeps_external_alive(self) -> bool:
        options = self.options
        return (
            options.hand_back is HandBack.SWITCH
            and options.hand_back_entity_write_type in (WriteType.EXPIRING, WriteType.HELD)
            and self._session.loop.control.controlling
        )

    async def _async_remember_command(
        self, out: LoopOutput, setpoint_ok: bool, heating_ok: bool, now: float
    ) -> None:
        """The last command after a write went through: heating on/off as commanded and the
        setpoint as written. What did not get through keeps its earlier value; a heating state
        never known is not stored. Stored at once when it matters (``remember_command``)."""
        if not (setpoint_ok or heating_ok):
            return
        previous = self._last_command
        if setpoint_ok and out.setpoint is not None:
            setpoint: float | None = out.setpoint.value
        else:
            setpoint = None if previous is None else previous.setpoint
        if heating_ok and out.heating is not None:
            heating: bool | None = out.heating.value == ON
        elif out.heating is None:
            heating = out.heating_on  # not written now: as last written
        else:
            heating = None if previous is None else previous.heating  # its write failed
        if heating is None:
            return
        command, save_now = remember_command(self._command_stored, heating, setpoint, now)
        self._last_command = command
        if save_now:
            self._command_stored = command
            await self._coordinator.async_save_control_now()

    async def _async_write(
        self, kind: str, write: Callable[[], Awaitable[None]], now: float, action: WriteAction
    ) -> bool:
        session = self._session
        if not self._holding or action.kind is WriteKind.REWRITE:
            # Before the attempt: a write reported as failed may still reach the boiler, and
            # the one rewrite a day must be remembered even if Home Assistant crashes now.
            self._holding = True
            await self._coordinator.async_save_control_now()
        try:
            await write()  # made only now, after the save (P-52)
        except WriteError as err:
            if kind in session.failing:
                _LOGGER.debug("The boiler %s write failed again: %s", kind, err)
            else:
                _LOGGER.warning(
                    "A boiler write failed; sent again at every step until it works: %s",
                    err,
                    exc_info=err,
                )
            session.failing.add(kind)
            session.alarms.add(ControlAlarm.WRITE_FAILED)
            return False
        if kind in session.failing:
            _LOGGER.info("The boiler %s write works again", kind)
        session.failing.discard(kind)
        if not session.failing:  # each kind of write clears only its own failure
            session.alarms.discard(ControlAlarm.WRITE_FAILED)
        # A restored command went through (decision 3): the restore is done.
        self._restore_pending = False
        if self._hand_back_pending:
            # Control has the boiler again: the earlier hand-back is folded into this session's,
            # which gives back whatever the earlier one left — every hand-back is whole.
            self._hand_back_done()
        self._hand_back_shown = None
        if self._taken_issue:
            # Control has the boiler again: what another controller held after the last
            # hand-back is past.
            entry_id = self._coordinator.config_entry.entry_id
            ir.async_delete_issue(self._hass, DOMAIN, f"{TAKEN_ISSUE}_{entry_id}")
            self._taken_issue = False
        if action.kind is not WriteKind.KEEPALIVE:  # a repeat changes nothing
            self._last_change_at = now
        return True

    # --- hand-back ------------------------------------------------------------------------

    async def _async_hand_back_writes(self, now: float) -> None:
        """The hand-back write, which no guard holds back, and the release of learning. When the
        boiler holds nothing of ours there is nothing to give back."""
        if self._holding or self._hand_back_pending:
            await self._async_try_hand_back(now, new=True)
        self._hand_back_at = now
        self._last_change_at = now
        self._forget_last_command()  # the session ended; a stop's own hand-back keeps it
        await self._coordinator.async_save_control_now()  # a latch set with it must survive a crash
        await self._async_release_learning(now)

    async def _async_try_hand_back(
        self, now: float, new: bool = False, only: set[str] | None = None
    ) -> None:
        """One attempt at the safe hand-back; a failure is kept, shown and retried until it goes
        through. ``new``: the session's own hand-back, which writes every part — the setpoint a
        timeout releases through included; a later attempt at the same debt writes only what is
        still owed (``only``: just these targets — a lost command). The debt is marked and stored
        at once before anything is written, so whatever cuts the attempt short — any exception,
        a cancel inside a service, a crash — leaves it owed (P-42); a real cancellation passes,
        the debt kept. A target that does not show the hand-back yet stays owed until it does."""
        self._release_from = self._value_to_leave()
        if new:
            self._release_baseline = self._session_baseline()
        self._hand_back_pending = True
        self._hand_back_retry_at = now + HAND_BACK_RETRY_S
        await self._async_store_owed()
        skip = self._skip(new, only)
        self._attempt_whole = False
        try:
            writer = self._writer or self._writer_factory(self._hass, self.options)
            checks = await writer.hand_back(
                release_from=self._release_from,
                baseline=self._release_baseline,
                write_timeout_s=STOP_WRITE_TIMEOUT_S if self._stopping else None,
                skip=skip,
            )
        except asyncio.CancelledError as err:
            if _cancelled_from_outside():
                raise  # a real cancellation: the debt stays marked and stored
            self._attempt_failed(now, err, expected=False)
            return
        except HandBackFailed as err:  # a part failed; what did go out is followed all the same
            self._follow_targets(err.checks, now, skip, new)
            if not self._all_done():
                self._attempt_failed(now, err, expected=True)
                return
            _LOGGER.warning("Part of the hand-back failed, yet every target shows it: %s", err)
        except WriteError as err:
            self._attempt_failed(now, err, expected=True)
            return
        except Exception as err:  # a bug must not lose the debt either
            self._attempt_failed(now, err, expected=False)
            return
        else:
            self._attempt_whole = True
            self._follow_targets(checks, now, skip, new)
        if not self._all_done():
            self._hand_back_pending = True
            self._coordinator.schedule_control_save()
            return
        await self._async_hand_back_confirmed()

    def _skip(self, new: bool, only: set[str] | None) -> set[str]:
        """Targets an attempt leaves alone: one another controller holds; after the session's
        own hand-back also one done, one showing a third value being judged, and the setpoint a
        timeout releases through — each write would arm its timer again."""
        skip = set(self._taken_targets)
        if new:
            return skip
        skip |= {key for key, target in self._targets.items() if target.done or target.third}
        if self.options.hand_back is HandBack.TIMEOUT and self.options.setpoint_entity:
            skip.add(self.options.setpoint_entity)
        if only is not None:
            skip |= {key for key in self._targets if key not in only}
        return skip

    async def _async_store_owed(self) -> None:
        """The debt in the store before a hand-back's first write. A store that cannot be written
        does not hold the hand-back up: the boiler gets its own control back all the same."""
        try:
            await self._coordinator.async_save_control_now()
        except Exception:
            _LOGGER.exception("Could not store the owed hand-back before making it; made anyway")

    def _value_to_leave(self) -> float | None:
        """The setpoint the plugin last wrote, which a release must leave: this session's, else
        the last command stored, else the one an earlier attempt at the same debt had; ``None``
        when none is known."""
        written = self._session.loop.setpoint.written
        if written is not None:
            return written
        command = self._last_command
        if command is not None and command.setpoint is not None:
            return command.setpoint
        return self._release_from

    def _session_baseline(self) -> float | None:
        """The read-back from before the session's first write — what a timeout hand-back
        releases back to; ``None`` when not known."""
        baseline = self._session.loop.setpoint.baseline
        return baseline if baseline is not None else self._baseline

    def _attempt_failed(self, now: float, err: BaseException, expected: bool) -> None:
        """An attempt that did not get through: owed, shown, and sent again a minute later.
        Within the start grace a target not back yet (``expected``: a failed write) is only sent
        again at the next step, logged at DEBUG (P-50); anything else — a bug — shows at once."""
        self._hand_back_pending = True
        if expected and self._in_start_grace(now):
            _LOGGER.debug("The hand-back the last run left owed did not get through yet: %s", err)
            self._hand_back_retry_at = now
        else:
            if self._hand_back_logged:
                _LOGGER.debug("Handing control back failed again: %s", err)
            else:
                _LOGGER.error(
                    "Handing control back failed; retrying every minute: %s", err, exc_info=err
                )
                self._hand_back_logged = True
            self._hand_back_failed = True
            self._hand_back_retry_at = now + HAND_BACK_RETRY_S
        self._hand_back_shown = self._shown_now()
        self._coordinator.schedule_control_save()
        self._report_owed()

    async def _async_hand_back_confirmed(self) -> None:
        """Every target shows the hand-back, or another controller holds it: the boiler has its
        own control back. Unless this is a stop's own hand-back, the last command is not to be
        given again."""
        self._hand_back_shown = self._shown_now()
        self._holding = False
        self._hand_back_done()
        if self._forget_last_command():
            await self._coordinator.async_save_control_now()

    async def _async_follow_hand_back(self, now: float) -> None:
        """An owed hand-back, at every step: done once every target shows it or another
        controller holds it. A held target not shown a step after its release, and a timeout
        not released after three minutes, show as failed — not within the start grace (P-50);
        a lost command is written again at once; every minute what is still owed is sent again
        (after a retry check of the third values a held target shows), and a target unconfirmed
        by then shows as failed. A timeout hand-back is never written again."""
        self._evaluate(now)
        if self._targets and self._all_done():
            await self._async_hand_back_confirmed()
            return
        self._alarm_if_unconfirmed(now)
        lost = {key for key, target in self._targets.items() if target.lost}
        if lost:
            await self._async_try_hand_back(now, only=lost)
            return
        # A retry further ahead than planned means the wall clock went back: due now (C9).
        self._hand_back_retry_at = clock_due(self._hand_back_retry_at, now, HAND_BACK_RETRY_S)
        if now < self._hand_back_retry_at:
            return
        self._judge_third_values(now)
        if self._targets and self._all_done():
            await self._async_hand_back_confirmed()
            return
        unconfirmed = [
            key
            for key, target in self._targets.items()
            if not target.done and target.check.kind is not CheckKind.BACK_TO_BASELINE
        ]
        if unconfirmed:
            self._unconfirmed(now, unconfirmed)
        await self._async_try_hand_back(now)

    def _alarm_if_unconfirmed(self, now: float) -> None:
        """A held target keeps what it was given: not released a step after its release, the
        boiler stays at the lowest water temperature — an alarm at once. A timeout hand-back
        writes nothing more: not released after three minutes, an alarm."""
        late = [
            key
            for key, target in self._targets.items()
            if not target.done
            and (
                (target.check.held and now - target.sent_at >= HELD_UNCONFIRMED_S)
                or (
                    target.check.kind is CheckKind.BACK_TO_BASELINE
                    and now - target.first_at >= TIMEOUT_RELEASE_S
                )
            )
        ]
        if late and not self._hand_back_failed:
            self._unconfirmed(now, late)

    def _unconfirmed(self, now: float, targets: Sequence[str]) -> None:
        """Targets that do not show the hand-back in time: shown as failed, and logged once —
        within the start grace only at DEBUG (P-50)."""
        shown = ", ".join(sorted(targets))
        if self._in_start_grace(now):
            _LOGGER.debug("The hand-back the last run left owed is not shown yet: %s", shown)
            return
        if not self._hand_back_logged:
            _LOGGER.error(
                "The hand-back was not confirmed by %s; sending it again every minute", shown
            )
            self._hand_back_logged = True
        self._hand_back_failed = True
        self._hand_back_shown = self._shown_now()

    def _judge_third_values(self, now: float) -> None:
        """The retry check of held value targets (W3, W6): a third value held at consecutive
        checks — two a minute apart, three over two minutes with hot water unknown, none during
        a draw or two minutes after it — is another controller's. While one is shown, its retry
        write is held back."""
        dhw = self._note_hot_water(now)
        recent = self._dhw_seen_at is not None and now - self._dhw_seen_at <= DHW_QUIET_S
        for target in self._targets.values():
            check = target.check
            if target.done or not check.held or check.kind is not CheckKind.VALUE:
                continue
            value = read_temperature(self._hass, check.entity_id).value
            target.third = third_value(check.rule, value)
            target.watch, taken = watch_foreign(target.watch, value, target.third, dhw, recent)
            if taken:
                self._taken_by_other(target)

    def _note_hot_water(self, now: float) -> bool | None:
        """Hot water now (``None``: unknown), and when it last ran."""
        dhw = self._coordinator.dhw_now(self._coordinator.transport.snapshot(now))
        if dhw:
            self._dhw_seen_at = now
        return dhw

    def _all_done(self) -> bool:
        return all(target.done for target in self._targets.values())

    def _follow_targets(
        self, checks: Sequence[HandBackCheck], now: float, skip: set[str], new: bool
    ) -> None:
        """The targets an attempt stands for. One written now starts afresh — the one a stored
        debt had judged held by another controller stays so; one left alone keeps what its
        read-back showed. Each report of them is looked at as it comes: a release shown only for
        a moment still counts, and a stop waiting for them ends once all show the hand-back."""
        if new:
            self._targets = {}
        for check in checks:
            key = check.key
            known = self._targets.get(key)
            if known is not None and key in skip:
                continue
            target = _Target(check, now, now if known is None else known.first_at)
            target.seen = known is not None and known.seen
            target.taken = key in self._taken_targets
            self._targets[key] = target
        self._watch_targets()
        self._evaluate(now)

    def _watch_targets(self) -> None:
        if self._checks_unsub is not None:
            self._checks_unsub()
            self._checks_unsub = None
        entities = sorted({target.check.entity_id for target in self._targets.values()})
        if entities:
            self._checks_unsub = async_track_state_change_event(
                self._hass, entities, self._on_check_report
            )

    def _evaluate(self, now: float) -> None:
        """What each target's read-back shows now. A value target's release seen once counts
        from then on: pyotgw shows the accepted CS=0 only until the boiler's next report. An
        optimistic target is done once written. A two-valued target is judged at every report."""
        for target in self._targets.values():
            check = target.check
            if target.taken or (target.released and check.kind is not CheckKind.SWITCH):
                continue
            if check.source is CheckSource.ASSUMED:
                target.released = target.released or check.written
            elif check.kind is CheckKind.SWITCH:
                self._judge_two_valued(target, now)
            else:
                state = self._hass.states.get(check.entity_id)
                value = temperature_from_state(state).value
                if released(check.rule, value, reported_after=state is not check.before):
                    target.released = True
        self._hand_back_shown = self._shown_now()

    def _judge_two_valued(self, target: _Target, now: float) -> None:
        check = target.check
        state = self._hass.states.get(check.entity_id)
        traced = outage_seen(self._outages, self._trace_entities(check.entity_id), now)
        verdict = judge_switch(
            None if state is None else state.state,
            str(check.expected),
            target.seen,
            traced or trace_seen(self._restart_at, now),  # X1's trace, the restart included
        )
        target.released = verdict is SwitchVerdict.RELEASED
        target.lost = verdict is SwitchVerdict.LOST
        if target.released:
            target.seen = True
        elif verdict is SwitchVerdict.TAKEN:
            self._taken_by_other(target)

    def _taken_by_other(self, target: _Target) -> None:
        """Another controller holds the target: the hand-back counts as done there and is not
        written again — told once in the log, and by a repair issue."""
        target.taken = True
        target.released = target.lost = target.third = False
        key = target.check.key
        if key in self._taken_targets:
            return
        self._taken_targets.add(key)
        _LOGGER.warning(
            "After the hand-back another controller holds %s: the hand-back counts as done there "
            "and is not sent again",
            key,
        )
        self._report_taken()
        self._coordinator.schedule_control_save()

    def _report_taken(self) -> None:
        """The repair issue of a target another controller holds after the hand-back: an error
        where the hand-back stops heating, else a warning. V7's issue for a control that stepped
        aside from another controller says so already."""
        entry_id = self._coordinator.config_entry.entry_id
        issues = ir.async_get(self._hass)
        if issues.async_get_issue(DOMAIN, f"{LATCHED_ISSUE}_{entry_id}") is not None:
            return
        stops = hand_back_effect(self.options) is HandBackEffect.HEATING_STOPS
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            f"{TAKEN_ISSUE}_{entry_id}",
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if stops else ir.IssueSeverity.WARNING,
            translation_key=TAKEN_ISSUE,
            translation_placeholders={"target": ", ".join(sorted(self._taken_targets))},
        )
        self._taken_issue = True

    # --- the monitor failing (V6, the user's answer I) ------------------------------------------

    def _monitor_issue_id(self) -> str:
        return f"{MONITOR_ISSUE}_{self._coordinator.config_entry.entry_id}"

    def _monitor_issue_left(self) -> float | None:
        """The monitor's issue an earlier run of this entry left up (a reload keeps it): when its
        failures began — the time it kept, else when the issue was raised — so the note follows
        once control holds the boiler again; ``None`` without one, or with only its note."""
        issue = ir.async_get(self._hass).async_get_issue(DOMAIN, self._monitor_issue_id())
        if issue is None or not issue.active or issue.translation_key != MONITOR_ISSUE:
            return None
        since = (issue.data or {}).get("since")
        if isinstance(since, bool) or not isinstance(since, int | float):
            return issue.created.timestamp()
        return float(since) if math.isfinite(since) else issue.created.timestamp()

    def _report_monitor_failed(self, now: float) -> None:
        """The monitor has failed for five minutes and control handed back the boiler it held: a
        repair issue — an error where the hand-back stops heating, else a warning. Raised anew,
        so an earlier one the user dismissed does not hide it."""
        since = self._coordinator.monitor_lost_from
        since = now if since is None else since
        stops = hand_back_effect(self.options) is HandBackEffect.HEATING_STOPS
        _LOGGER.warning(
            "The plugin's monitor has failed for five minutes: control hands the boiler back, "
            "and resumes on its own once the monitor works again"
        )
        issue_id = self._monitor_issue_id()
        ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if stops else ir.IssueSeverity.WARNING,
            translation_key=MONITOR_ISSUE,
            data={"since": since},
        )
        self._monitor_issue_since = since

    def _note_monitor_recovered(self, now: float) -> None:
        """Control holds the boiler again after the monitor's hand-back: the issue becomes the
        information note — from the first failure to the first good refresh — under the same id,
        a warning, as Home Assistant has no information level."""
        since = self._monitor_issue_since
        self._monitor_issue_since = None
        until = self._coordinator.monitor_works_since
        until = now if until is None else until
        _LOGGER.info("The plugin's monitor works again: control has resumed")
        issue_id = self._monitor_issue_id()
        ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=MONITOR_NOTE,
            translation_placeholders={
                "since": _local_minute(now if since is None else since),
                "until": _local_minute(until),
            },
        )

    def _delete_monitor_issue(self) -> None:
        self._monitor_issue_since = None
        ir.async_delete_issue(self._hass, DOMAIN, self._monitor_issue_id())

    def _trace_entities(self, entity_id: str | set[str]) -> set[str]:
        """Where an outage of a target would show (X1's trace): the target, its read-back, the
        optional restart indicator, and every entity of the same device the plugin reads or
        writes."""
        found = {entity_id} if isinstance(entity_id, str) else set(entity_id)
        if self.options.ch_entity in found and self.options.ch_confirmed_entity:
            found.add(self.options.ch_confirmed_entity)
        if self.options.restart_entity:
            found.add(self.options.restart_entity)  # unavailable or unknown: a trace too
        registry = er.async_get(self._hass)
        devices = {
            entry.device_id
            for entry in (registry.async_get(entity) for entity in list(found))
            if entry is not None and entry.device_id is not None
        }
        if not devices:
            return found
        for other in self._outages:
            other_entry = registry.async_get(other)
            if other_entry is not None and other_entry.device_id in devices:
                found.add(other)
        return found

    def _outage_at(self, entities: set[str]) -> float | None:
        """When the last trace of an outage around these entities was seen: one of them, or
        another entity of the same device, unavailable, unknown or missing; or a restart the
        optional indicator showed (Q3.7)."""
        moments = [
            self._outages[entity]
            for entity in self._trace_entities(entities)
            if entity in self._outages
        ]
        if self._restart_at is not None:
            moments.append(self._restart_at)
        return max(moments) if moments else None

    def _returned(self, key: str, entity: str | None) -> bool:
        """Whether a target came back from unavailable or unknown since the last step."""
        if not entity:
            return False
        state = self._hass.states.get(entity)
        up = state is not None and state.state not in UNAVAILABLE_STATES
        was_down = self._targets_down.get(key, False)
        self._targets_down[key] = not up
        return up and was_down

    def _thermostat_value(self) -> float | None:
        """The OpenTherm thermostat's own requested water setpoint, where a gateway has one and
        the optional field is mapped; ``None`` otherwise, or while it is unavailable."""
        options = self.options
        entity = options.thermostat_setpoint_entity
        if not entity or options.topology is not Topology.GATEWAY_WITH_THERMOSTAT:
            return None
        return read_temperature(self._hass, entity).value

    def _contexts(self, now: float, dhw: bool | None) -> tuple[GuardContext, GuardContext]:
        """What each guard knows beside its read-back: the trace of an outage around its target,
        the thermostat's own request (the setpoint), hot water, the target back from unavailable
        or unknown, and the last command stored (never a baseline)."""
        options = self.options
        gateway = options.write_path in OTGW_PATHS
        setpoint_target = options.confirmed_entity if gateway else options.setpoint_entity
        if gateway:
            heating_target = options.ch_confirmed_entity or options.confirmed_entity
        else:
            heating_target = options.ch_entity if options.loop.ch_writes else None
        setpoint_around = {e for e in (setpoint_target, options.confirmed_entity) if e}
        heating_around = {e for e in (heating_target, options.ch_confirmed_entity) if e}
        last = self._last_command
        return (
            GuardContext(
                outage_at=self._outage_at(setpoint_around),
                thermostat=self._thermostat_value(),
                dhw=dhw,
                returned=self._returned("setpoint", setpoint_target),
                last_command=None if last is None else last.setpoint,
            ),
            GuardContext(
                outage_at=self._outage_at(heating_around),
                dhw=dhw,
                returned=self._returned("heating", heating_target),
                last_command=None if last is None else (ON if last.heating else OFF),
            ),
        )

    def _watch_external(self, now: float) -> None:
        """M14, M15: while control holds the boiler through the external-control switch it
        turned on, the switch is read at every step. Off after an outage of the switch or its
        device (unavailable, unknown or missing within five minutes, or a restart seen) — turned
        on again at once, counted as a lost command. Off with no trace — a person, an automation,
        its own button, while it stayed available — another controller: the plugin steps aside
        at once, with no rewrite (the whole safe hand-back; the switch, already off, counts as
        released). Not judged while unknown, nor before it was read back on."""
        options = self.options
        entity = options.hand_back_entity
        returned = self._returned("external", entity)
        control = self._session.loop.control
        if (
            options.hand_back is not HandBack.SWITCH
            or not entity
            or self._writer is None
            or not control.controlling
            or control.latched
        ):
            self._external_seen_on = False
            self._external_returned = False
            return
        self._external_returned = self._external_returned or returned
        state = self._hass.states.get(entity)
        on = None if state is None else parse_binary(state.state)
        if on is True:
            self._external_seen_on = True
            return
        if on is None or not self._external_seen_on:
            return
        self._external_seen_on = False
        traced = outage_seen(self._outages, self._trace_entities(entity), now) or trace_seen(
            self._restart_at, now
        )
        if traced:
            _LOGGER.info(
                "The external-control switch came back off after an outage of its device: "
                "switched on again"
            )
            self._external_renew = True
            loop = self._session.loop
            self._session.loop = replace(loop, losses=add_loss(loop.losses, now, "external"))
            return
        _LOGGER.warning(
            "The external-control switch was switched off while it stayed available: control "
            "steps aside without a fight"
        )
        self._session.alarms.add(ControlAlarm.OUTSIDE_CHANGE)

    def _follow_return(self, now: float) -> bool:
        """The optional return by itself (off by default; not for relays): after the plugin
        stepped aside from another controller, control comes back — a new session, which clears
        the latch and its issue and keeps the one rewrite — once the read-backs have shown only
        the hand-back state for an hour without a break; an unknown read-back breaks it. Whether
        it returned now."""
        control = self._session.loop.control
        if not (
            self.options.return_after_outside_change
            and self.enabled
            and control.latched
            and ControlAlarm.OUTSIDE_CHANGE.value in control.latched_by
        ):
            self._quiet_since = None
            return False
        if not self._hand_back_state_shown():
            self._quiet_since = None
            return False
        self._quiet_since = clock_start(self._quiet_since, now)  # a clock set back (C9)
        if now - self._quiet_since < RETURN_QUIET_S:
            return False
        _LOGGER.info(
            "Nothing else has written to the boiler for an hour: control returns by itself"
        )
        self._end_session()
        return True

    def _hand_back_state_shown(self) -> bool:
        """Whether the read-backs show only the hand-back state: the gateway's released override
        (0), the hand-back value, the value from before the session (a timeout), or the external
        switch off — with an OpenTherm thermostat also its own request, where that field is
        mapped. Without a known value to compare, never: the return does not come."""
        options = self.options
        read_back = self._confirmed()
        if read_back is None:
            return False  # an unknown read-back breaks the hour
        thermostat = self._thermostat_value()
        if thermostat is not None and abs(read_back - thermostat) <= TOLERANCE_K:
            return True
        expected: float | None = None
        if options.write_path in OTGW_PATHS:
            expected = 0.0
        elif options.hand_back is HandBack.VALUE and options.hand_back_value is not None:
            grid = self._grid()
            value = float(options.hand_back_value)
            placed = None if grid is None else grid.put(value, None, None)
            expected = value if placed is None else placed
        elif options.hand_back is HandBack.TIMEOUT:
            expected = self._session.loop.setpoint.baseline
        elif options.hand_back is HandBack.SWITCH and options.hand_back_entity:
            state = self._hass.states.get(options.hand_back_entity)
            return state is not None and state.state == "off"
        return expected is not None and abs(read_back - expected) <= TOLERANCE_K

    def _shown_now(self) -> str | None:
        """Where the hand-back stands, as ``hand_back_confirmation`` shows it."""
        views = [
            TargetView(target.released, target.taken, target.check.source)
            for target in self._targets.values()
        ]
        gateway = self.options.write_path in OTGW_PATHS
        found = shown(views, gateway, self._hand_back_failed)
        if found is None and self._hand_back_pending:
            found = (
                HandBackConfirmation.NOT_CONFIRMED
                if self._hand_back_failed
                else HandBackConfirmation.WAITING
            )
        return None if found is None else found.value

    @callback
    def _on_check_report(self, event: Event[EventStateChangedData]) -> None:
        self._note_outage(event)
        self._evaluate(dt_util.utcnow().timestamp())
        if self._targets and self._all_done() and self._checks_seen is not None:
            self._checks_seen.set()

    async def _async_wait_for_checks(self, until: float) -> None:
        """At a stop: the hand-back's targets get until ``until`` (the loop's clock) to show it."""
        seen = asyncio.Event()
        self._checks_seen = seen
        try:
            if not self._all_done():
                async with asyncio.timeout_at(until):
                    await seen.wait()
        except TimeoutError:
            _LOGGER.debug("The hand-back at the stop was not shown in time; it stays owed")
            return
        finally:
            self._checks_seen = None
        await self._async_hand_back_confirmed()

    # --- the trace of an outage (X1's rule; V5 judges two-valued targets by it) ---------------

    def _track_outages(self, now: float) -> None:
        """When each entity the plugin reads or writes was last unavailable, unknown or missing.
        The unit's start counts as such a moment for all of them: nothing before it was seen."""
        entities = sorted({*self.options.entities, *self._coordinator.config.signals.values()})
        self._outages = dict.fromkeys(entities, now)
        if self.options.restart_entity:
            self._restart_value = restart_reading(
                self._hass.states.get(self.options.restart_entity)
            )[0]
        if entities:
            self._unsubs.append(
                async_track_state_change_event(self._hass, entities, self._note_outage)
            )

    @callback
    def _note_outage(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        now = dt_util.utcnow().timestamp()
        if entity_id in self._outages and any(
            state is None or state.state in UNAVAILABLE_STATES for state in (old, new)
        ):
            self._outages[entity_id] = now
        if entity_id == self.options.restart_entity:
            # Q3.7: a restart the device's entities may never show as unavailable.
            value, kind = restart_reading(new)
            if value is not None:
                if restart_seen(self._restart_value, value, kind):
                    self._restart_at = now
                self._restart_value = value

    def _in_start_grace(self, now: float) -> bool:
        """Within a minute of this unit's start, while it still owes what the last run left: a
        device may not have reported since its own restart (P-50)."""
        self._grace_from = clock_start(self._grace_from, now)  # a clock set back (C9)
        return self._carried_debt and now - self._grace_from < START_GRACE_S

    def _hand_back_done(self) -> None:
        """No hand-back is owed any more: it was confirmed, or control has the boiler again."""
        changed = self._hand_back_pending or self._hand_back_failed
        if self._hand_back_logged:
            _LOGGER.info("The hand-back went through")
            self._hand_back_logged = False
        self._hand_back_pending = False
        self._hand_back_failed = False
        self._targets = {}
        self._watch_targets()
        self._release_from = None
        self._release_baseline = None
        self._taken_targets = set()
        self._carried_debt = False
        if changed:
            self._coordinator.schedule_control_save()
        self._report_owed()

    def _report_owed(self, persistent: bool = False) -> None:
        """A repair issue shows a hand-back still owed — without the control entities at once,
        with them once it has failed, and for good when the entry unloads with it — and lets the
        user say they returned the boiler by hand (its target gone for good, say), which nothing
        else could settle. Within the start grace the issue the last stop left stays as it was,
        neither deleted nor raised again (P-50)."""
        entry_id = self._coordinator.config_entry.entry_id
        shown = persistent or self._hand_back_failed
        if (
            self._hand_back_pending
            and not shown
            and self._in_start_grace(dt_util.utcnow().timestamp())
        ):
            return
        if self._hand_back_pending and (shown or self.hand_back_only):
            report_owed_hand_back(self._hass, entry_id, persistent=persistent)
        else:
            ir.async_delete_issue(self._hass, DOMAIN, f"{OWED_ISSUE}_{entry_id}")

    async def async_release_owed_hand_back(self) -> None:
        """The user returned the boiler to its own control by hand: nothing is owed any more, and
        retrying stops. An attempt on its way ends first — it would set the debt again (P-51).
        Control, if on, takes the boiler afresh at its next step. A session that has taken the
        boiler again since keeps what it holds — a confirmation given late must not make a
        crash forget it — and makes its own hand-back at the end (R6, C7)."""
        async with self._lock:
            controlling = self._session.loop.control.controlling
            if not (self._hand_back_pending or (self._holding and not controlling)):
                return
            _LOGGER.warning("The owed hand-back is settled by hand, as the user confirmed")
            if not controlling:
                self._holding = False
            self._hand_back_done()
            self._hand_back_shown = None
            await self._coordinator.async_save_control_now()

    async def _async_hand_back_now(self, now: float) -> None:
        """Hand back at once if control holds the boiler (unload, stop, error). The guards keep
        their memory — above all the one rewrite, stored after it (P-06)."""
        loop = self._session.loop
        if loop.control.controlling:
            await self._async_hand_back_writes(now)
            loop = self._session.loop
            control = replace(loop.control, controlling=False, command=None, decided_at=None)
            self._session.loop = after_hand_back_loop(loop, control)
        else:
            if self._hand_back_pending:
                await self._async_try_hand_back(now)
            await self._async_release_learning(now)

    # --- learning pauses ------------------------------------------------------------------

    async def _async_learning(
        self,
        now: float,
        snapshot: BoilerSnapshot,
        zones: Sequence[ZoneState],
        heating_setpoint: float | None,
        heating: bool | None,
        writes_stopped: bool = False,
    ) -> None:
        controlling = self._session.loop.control.controlling and not writes_stopped
        if not (self.options.learning_pauses and controlling):
            await self._async_release_learning(now)
            return
        coordinator = self._coordinator
        data = coordinator.data
        opening = self.options.loop.control.demand.zone_opening
        learning_zones = []
        for zone in zones:
            algorithm = coordinator.link.zone_algorithm(zone.zone_id)
            if algorithm.smartpi_learning is None:
                continue
            view = data.zones.get(zone.zone_id) if data is not None else None
            heat = view.foreign_heat if view is not None else None
            foreign = heat is not None and heat.active
            demand = zone.demand
            learning_zones.append(
                ZoneLearning(
                    zone.zone_id,
                    algorithm.smartpi_learning,
                    demand is not None and demand > opening,
                    foreign,
                )
            )
        plan = plan_learning(
            self._session.learning,
            learning_zones,
            coordinator.dhw_now(snapshot),
            # The flow by its own age limit, as everywhere (X2): a stale one is unknown.
            snapshot.number(Signal.FLOW, coordinator.config.freshness.get(Signal.FLOW)),
            heating_setpoint,  # the heating setpoint, not a low "off" value: no false swings
            now,
            self.options.learning,
            heating,
        )
        self._learning_calls += [(zone_id, False) for zone_id in plan.pause]
        self._learning_calls += [(zone_id, True) for zone_id in plan.resume]
        before = self._session.learning
        self._session.learning = plan.state
        if plan.pause or _zones_changed(before, plan.state):
            # Stored before SmartPI is asked (the calls come after the step): a crash right
            # after a pause must still know the zone is the plugin's to resume (P-10).
            await self._coordinator.async_save_control_now()
        elif (
            plan.resume
            or plan.state.resuming != before.resuming
            or plan.state.dhw_ended != before.dhw_ended
        ):
            # A resume sent again, or when a pause's hot water ended: only times.
            self._coordinator.schedule_control_save()

    async def _async_release_learning(self, now: float) -> None:
        """Resume every zone the plugin paused, and follow the resumes until SmartPI's flag
        reads on: one that did not take is sent again every minute."""
        before = learning = self._session.learning
        if learning.paused:
            learning, zones = release_all(learning, now)
            self._learning_calls += [(zone_id, True) for zone_id in zones]
        if learning.resuming:
            link = self._coordinator.link
            flags = {z: link.zone_algorithm(z).smartpi_learning for z in learning.resuming}
            followed, again = follow_resumes(learning, flags, now, self.options.learning)
            self._learning_calls += [(zone_id, True) for zone_id in again]
            learning = followed
        self._session.learning = learning
        if _zones_changed(before, learning):
            # Which zones are paused or followed is stored before SmartPI is asked (P-10).
            await self._coordinator.async_save_control_now()
        elif learning.resuming != before.resuming:
            self._coordinator.schedule_control_save()  # only when a resume was last sent

    async def _async_learning_calls(self, deadline: float | None = None) -> None:
        """Make the planned SmartPI calls, together and without the lock. Whether each took is
        read back from SmartPI's flag at the next steps, whatever the call reported. At a stop
        they fit in what is left of its budget (``deadline``, the loop's clock); with nothing
        left they are not made, and the stored resumes are sent again at the next start."""
        calls, self._learning_calls = self._learning_calls, []
        if not calls:
            return
        timeout_s = LEARNING_TIMEOUT_S
        if deadline is not None:
            timeout_s = min(timeout_s, deadline - self._hass.loop.time())
            if timeout_s <= 0:
                _LOGGER.debug("No time left at the stop for %d SmartPI call(s)", len(calls))
                return
        await asyncio.gather(
            *(self._async_set_learning(zone_id, enabled, timeout_s) for zone_id, enabled in calls)
        )

    async def _async_set_learning(
        self, zone_id: str, enabled: bool, timeout_s: float = LEARNING_TIMEOUT_S
    ) -> bool:
        try:
            async with asyncio.timeout(timeout_s):
                await self._hass.services.async_call(
                    SMARTPI_DOMAIN,
                    SMARTPI_SERVICE,
                    {"entity_id": zone_id, "learning_enabled": enabled},
                    blocking=True,
                )
        except (HomeAssistantError, TimeoutError, vol.Invalid) as err:
            if zone_id not in self._learning_failing:
                action = "resume" if enabled else "pause"
                _LOGGER.warning(
                    "Could not %s SmartPI learning of %s; tried again every minute: %s",
                    action,
                    zone_id,
                    err,
                )
            self._learning_failing.add(zone_id)
            return False
        except Exception:  # a learning pause must never break control; any other error is a bug
            if zone_id not in self._learning_failing:
                _LOGGER.exception("Setting SmartPI learning of %s failed unexpectedly", zone_id)
            self._learning_failing.add(zone_id)
            return False
        if zone_id in self._learning_failing:
            _LOGGER.info("SmartPI learning of %s can be set again", zone_id)
            self._learning_failing.discard(zone_id)
        return True
