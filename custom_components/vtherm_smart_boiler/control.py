"""Control on the Home Assistant side: a control step every few seconds, its writes, hand-back on
every exit, learning pauses, and the status the entities show.

The step itself is pure (``core.loop``); this module only gathers its inputs, carries out its
writes through the writer, and turns guard events and failures into alarms. The writer exists
only while control is switched on. An internal error hands back and blocks control until the user
switches it off and on again; unloading the entry and stopping Home Assistant hand back too. A
hand-back is retried until it is confirmed — an entity hand-back counts only once each target
shows what it was given, a gateway's once its read-back has left the value the plugin wrote —
and a failed one says so. Before each attempt the debt is marked and stored at once, so nothing
that cuts an attempt short can lose it.

How control resumes after it stopped (``SCOPE.md`` §7):
- an alarm set to hand back, an outside change included: a latch, shown with its cause, until
  the user switches control off and on; it survives a restart and never expires on its own;
- an internal error: at any change of the control switch;
- a lost boiler link: on its own, once the data is fresh again;
- a blocker: on its own, once it is gone.
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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import create_eager_task

from .const import CONTROL_TICK_SECONDS, DOMAIN, stored_flag
from .control_config import (
    OTGW_PATHS,
    AlarmReaction,
    ControlOptions,
    HandBack,
    WritePath,
    config_blockers,
)
from .core.controller import (
    ControlInputs,
    ControlMode,
    ControlState,
    Reason,
    clock_due,
    clock_start,
)
from .core.guards import (
    Confirmation,
    GuardConfig,
    GuardEvent,
    GuardState,
    WriteAction,
    WriteKind,
    confirmation,
    write_failed,
)
from .core.learning import (
    LearningState,
    ZoneLearning,
    follow_resumes,
    plan_learning,
    release_all,
)
from .core.loop import (
    ON,
    LastCommand,
    LoopOutput,
    LoopState,
    loop_step,
    parse_last_command,
    remember_command,
)
from .core.readings import BoilerSnapshot, ZoneState
from .core.signal_check import OutdoorStatus, curve_sensor
from .core.signals import Signal
from .transport.entities import (
    read_bounds,
    read_on_off,
    read_temperature,
    read_weather_temperature,
    temperature_from_state,
    temperature_unit_of,
)
from .transport.writers import HandBackCheck, WriteError, Writer, make_writer, writer_services

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
ZONE_UNKNOWN_ALARM_S = 30 * 60.0  # a zone unknown this long is reported
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
    "control_error",
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


def _zones_changed(before: LearningState, after: LearningState) -> bool:
    """Whether the zones paused or followed changed (not only when a resume was last sent)."""
    return before.paused.keys() != after.paused.keys() or (
        before.resuming.keys() != after.resuming.keys()
    )


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
    BOILER_LINK_LOST = "boiler_link_lost"  # handed back without the boiler's data
    ZONE_UNKNOWN = "zone_unknown"  # a zone unknown for long: frost protection cannot see it
    FROST_NOT_WARMING = "frost_not_warming"  # frost heating for long without the room warming
    CORRECTION_AT_LIMIT = "correction_at_limit"  # the comfort correction at 3 K for hours
    OUTDOOR_SENSOR_SUSPECT = "outdoor_sensor_suspect"  # stuck, or far from the weather


_EVENT_ALARM = {
    GuardEvent.IGNORED: ControlAlarm.WRITE_IGNORED,
    GuardEvent.OUTSIDE_CHANGE: ControlAlarm.OUTSIDE_CHANGE,
}
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

    @property
    def confirmed_setpoint(self) -> float | None:
        """The setpoint as the device confirms it; unknown otherwise, never the requested one."""
        return self.read_back if self.setpoint_check in _SHOWN_CONFIRMED else None


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
        self._status = ControlStatus(options.configured)
        self._published: ControlStatus | None = None
        self._last_change_at: float | None = None
        self._hand_back_at: float | None = None
        # A hand-back is owed: it failed, or it has not been confirmed yet. Retried until it is.
        self._hand_back_pending = False
        self._hand_back_failed = False  # shown as an alarm: an attempt failed or went unconfirmed
        self._hand_back_checks: tuple[HandBackCheck, ...] = ()
        # The setpoint a gateway's release must leave: the last one the plugin wrote, kept and
        # stored while its hand-back is owed — the session and its last command may be gone.
        self._release_from: float | None = None
        # Gateway releases seen since the hand-back went out: pyotgw shows the accepted CS=0 only
        # until the boiler's next report, so a release counts from the moment it is seen.
        self._released: set[str] = set()
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
        # A session took the boiler while a hand-back was owed: what the earlier one set (a
        # held heating switch left off, say) is this session's to give back too.
        self._full_hand_back_due = False
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
        latches, a hand-back still to be done, the user's wish and the last command."""
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
        return {
            "enabled": enabled,
            "last_command": None if command is None else command.as_dict(),
            "controlling": self._holding,
            "taken_with": dict(self._raw) if owed and self._raw else None,
            "paused": dict(session.learning.paused),
            "resuming": dict(session.learning.resuming),
            "resume_since": dict(session.learning.resume_since),
            "latched": session.loop.control.latched,
            "latched_by": list(session.loop.control.latched_by),
            # The one rewrite after an outside change: within a day of it, no more are made.
            "rewritten_at": session.loop.setpoint.rewritten_at,
            "heating_rewritten_at": session.loop.switch.rewritten_at,
            "failed": session.failed,
            "alarms": sorted(alarm.value for alarm in session.alarms & _KEPT_ALARMS),
            "hand_back_pending": self._hand_back_pending,
            "release_from": self._release_from,
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
        alarms: set[ControlAlarm] = field("alarms", _kept_alarms, set())
        latched_by: tuple[str, ...] = field(
            "latched_by", lambda raw: tuple(str(a) for a in raw), ()
        )
        rewritten_at: float | None = field("rewritten_at", float, None)
        heating_rewritten_at: float | None = field("heating_rewritten_at", float, None)
        latched = _flag(data.get("latched"))
        self._session = _Session(
            loop=LoopState(
                control=ControlState(latched=latched, latched_by=latched_by if latched else ()),
                setpoint=GuardState(rewritten_at=rewritten_at),
                switch=GuardState(rewritten_at=heating_rewritten_at),
            ),
            learning=LearningState(
                paused=paused,
                last_toggle=dict(paused),
                resuming=resuming,
                resume_since={z: t for z, t in resume_since.items() if z in resuming},
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
        # The wish: only a clear "on" is on; one that cannot be read is off, not the restored
        # switch (P-11).
        wish = data.get("enabled")
        if wish is not None and not isinstance(wish, bool):
            _LOGGER.warning("Ignoring unreadable stored control data: enabled; control is off")
            wish = False
        self._stored_enabled = wish
        self._last_command = field("last_command", parse_last_command, None)
        self._command_stored = self._last_command
        # From now on the stores get this unit's state: a save made before its start must not
        # write the state loaded earlier over a hand-back made since.
        self._coordinator.provide_stored_control(self.stored)

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
            try:
                await self._async_try_hand_back(now, full=True)
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
        self._started_at = dt_util.utcnow().timestamp()
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
            self._follow_checks(())
        if self._hand_back_pending:
            # The entry unloads — disabled, reloaded, Home Assistant stopping — with the
            # hand-back still owed: the issue outlives it, until a later run gets it through or
            # the user settles it by hand.
            self._report_owed(persistent=True)
        await self._async_learning_calls(deadline)
        self._coordinator.schedule_control_save()

    async def _async_stop_hand_back(self, now: float, deadline: float) -> None:
        """The stop's own hand-back, each write capped at ``STOP_WRITE_TIMEOUT_S``. One its
        targets do not show yet gets ``STOP_REPORT_WAIT_S`` more, within the budget, for a device
        that reports late (ESPHome, MQTT); still unconfirmed, it stays owed (R6)."""
        await self._async_hand_back_now(now)
        if self._hand_back_pending and self._hand_back_checks:
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
        found = config_blockers(self.options, config.installation)
        if self._hass.state is not CoreState.running:
            # VT starts its thermostats only once Home Assistant has started; `is_running` is
            # already true while it starts.
            found.append("ha_starting")
        if now - self._coordinator.monitoring_since < config.monitor.monitoring_days * DAY:
            found.append("monitoring_period")
        vt_boiler = self._coordinator.link.vt_central_boiler_configured()
        if vt_boiler is None:
            found.append("vt_central_boiler_unknown")  # cannot be ruled out: wait
        elif vt_boiler:
            found.append("vt_central_boiler_active")
        if self._unit_not_supported():
            found.append("setpoint_unit_not_supported")  # its range cannot be checked either
        elif self._outside_entity_range():
            found.append("setpoint_outside_entity_range")
        if self._session.failed:
            found.append("control_error")
        return tuple(found)

    def _unit_not_supported(self) -> bool:
        """A setpoint entity in a unit that is not a temperature: a value written would mean
        something else to it."""
        options = self.options
        if options.write_path is not WritePath.ENTITY or not options.setpoint_entity:
            return False
        return temperature_unit_of(self._hass, options.setpoint_entity) is False

    def _outside_entity_range(self) -> bool:
        """A setpoint entity that would reject a value control may write (a limit, the low "off"
        value or the hand-back value): every write of it would fail."""
        options = self.options
        if options.write_path is not WritePath.ENTITY or not options.setpoint_entity:
            return False
        low, high = read_bounds(self._hass, options.setpoint_entity)
        control = options.loop.control
        highest = min(
            v
            for v in (control.limits.hard_max, control.circuit_max, control.boiler_max)
            if v is not None
        )
        values = [control.limits.hard_min, highest]
        if not options.loop.ch_writes:
            values.append(options.loop.off_setpoint)
        if options.hand_back is HandBack.VALUE and options.hand_back_value is not None:
            values.append(options.hand_back_value)
        return any(
            (low is not None and value < low) or (high is not None and value > high)
            for value in values
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
            # The wish is stored before anything else can fail (P-11).
            await self._coordinator.async_save_control_now()
            await self._async_run_step(now)
            if not enabled:
                self._end_session()
        await self._async_learning_calls()
        self._notify()

    def _end_session(self) -> None:
        """A new session starts fresh; only the learning pauses carry on (a pending hand-back and
        its alarm belong to the unit, not the session)."""
        self._session = _Session(learning=self._session.learning)
        self._writer = None
        self._forget_last_command()
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
            _LOGGER.exception("The control step failed; handing control back")
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
                _LOGGER.exception("Handing control back after an error failed")
            self._coordinator.schedule_control_save()
            self._status = replace(
                self._status,
                blockers=tuple(dict.fromkeys((*self._status.blockers, "control_error"))),
                mode=ControlMode.NOT_ALLOWED,
                alarms=frozenset(self._alarms()),
            )

    async def _async_step(self, now: float) -> None:
        session = self._session
        if (
            self._hand_back_pending
            and not session.loop.control.controlling
            and self.options.configured
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
        blockers = self.blockers(now)
        if self.enabled and not blockers and self._writer is None:
            self._writer = self._writer_factory(self._hass, self.options)
        zones = self._coordinator.link.zones()
        snapshot = self._coordinator.transport.snapshot(now)
        inputs = self._inputs(now, snapshot, zones, blockers)
        confirmed = self._confirmed()
        session.loop, out = loop_step(
            session.loop, inputs, confirmed, self.options.loop, self._confirmed_heating()
        )
        if out.hand_back:
            await self._async_hand_back_writes(now)
        else:
            await self._async_writes(out, now)
        if Reason.BOILER_LINK_STALE in out.decision.reasons and (
            out.hand_back or out.decision.mode is ControlMode.HANDED_BACK
        ):
            # Every topology: without the boiler's data control hands back; stand-alone that
            # stops heating, so the user is told.
            session.alarms.add(ControlAlarm.BOILER_LINK_LOST)
        elif inputs.boiler_link:
            session.alarms.discard(ControlAlarm.BOILER_LINK_LOST)
        unknown = self._follow_unknown_zones(now, zones)
        for flagged, alarm in (
            (out.decision.frost_stuck, ControlAlarm.FROST_NOT_WARMING),  # heating goes on
            (out.decision.correction_at_limit, ControlAlarm.CORRECTION_AT_LIMIT),  # information
            (self._outdoor_suspect(), ControlAlarm.OUTDOOR_SENSOR_SUSPECT),  # left out
        ):
            if flagged:
                session.alarms.add(alarm)
            else:
                session.alarms.discard(alarm)
        for event in out.events:
            session.alarms.add(_EVENT_ALARM[event])
        if out.events:
            await self._coordinator.async_save_control_now()  # the alarm behind a latch
        setpoint = session.loop.setpoint
        if setpoint.confirmed_at is not None and not setpoint.ignored_reported:
            session.alarms.discard(ControlAlarm.WRITE_IGNORED)  # the value holds
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
        )

    def _follow_unknown_zones(self, now: float, zones: Sequence[ZoneState]) -> tuple[str, ...]:
        """Zones whose state is not known: the known ones decide meanwhile; one unknown for long
        raises an alarm, as frost protection cannot see it. So does one whose room sensor is
        lost for long (R6, T2): VT keeps the last temperature and still runs the zone, so its
        demand counts."""
        max_age = self.options.loop.control.zone_max_age_s
        unknown = tuple(z.zone_id for z in zones if not z.is_known(now, max_age))
        blind = {*unknown, *(z.zone_id for z in zones if z.room_sensor_lost)}
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
        return alarms

    def _boiler_link(self, snapshot: BoilerSnapshot, now: float) -> bool:
        """The boiler's own signals are there: flame and flow known.

        Many sources (MQTT among them) report only on change, so a steady reading is not a stale
        one; the age of the flow reading counts only when the user set a freshness limit for it.
        """
        flow = snapshot.reading(Signal.FLOW)
        if snapshot.flag(Signal.FLAME) is None or flow.value is None:
            return False
        limit = self._coordinator.config.freshness.get(Signal.FLOW)
        return limit is None or flow.is_fresh(now, limit)

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
        # limit the user set. A sensor the monitor found stuck leaves the curve to the weather
        # entity, then the held value and the fallback; one far from the weather gives way where
        # the weather reads colder (more heat, which the valves throttle), and without a weather
        # reading where the check saw it read warmer.
        outdoor_age = config.freshness.get(Signal.OUTDOOR)
        weather = None
        if config.weather:
            reading = read_weather_temperature(self._hass, config.weather)
            if reading.is_fresh(now, outdoor_age):
                weather = float(reading.value) if reading.value is not None else None
        check = getattr(self._coordinator.analysis, "outdoor", None)
        sensor = curve_sensor(check, snapshot.number(Signal.OUTDOOR, outdoor_age), weather)
        return ControlInputs(
            now=now,
            enabled=self.enabled,
            blockers=blockers,
            hand_back_alarms=self._hand_back_alarms(),
            boiler_link=self._boiler_link(snapshot, now),
            flame=snapshot.flag(Signal.FLAME),
            dhw=coordinator.dhw_now(snapshot),
            outdoor_sensor=sensor,
            outdoor_weather=weather,
            zones=tuple(zones),
        )

    def _outdoor_suspect(self) -> bool:
        """The monitor's check found the outdoor sensor stuck, or far from the weather."""
        check = getattr(self._coordinator.analysis, "outdoor", None)
        return check is not None and check.status in (OutdoorStatus.STUCK, OutdoorStatus.DEVIATES)

    def _hand_back_alarms(self) -> tuple[str, ...]:
        """Active alarms whose reaction is to hand control back."""
        active: list[str] = []
        data = self._coordinator.data
        if data is not None:
            active += [
                kind.value
                for kind, alarm in data.alarms.items()
                if alarm.active and self.options.reaction(kind.value) is AlarmReaction.HAND_BACK
            ]
        for alarm in sorted(self._session.alarms):
            if alarm in (
                ControlAlarm.CONTROL_ERROR,
                ControlAlarm.HAND_BACK_FAILED,
                ControlAlarm.BOILER_LINK_LOST,
                ControlAlarm.ZONE_UNKNOWN,
                ControlAlarm.FROST_NOT_WARMING,
                ControlAlarm.CORRECTION_AT_LIMIT,
                ControlAlarm.OUTDOOR_SENSOR_SUSPECT,
            ):
                continue  # a blocker, a retry of its own, and a hand-back already made
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
        if self._hand_back_pending:
            # Control has the boiler again: the earlier hand-back is folded into this session's,
            # which gives back in full whatever the earlier one left.
            self._full_hand_back_due = True
            self._hand_back_done()
        if action.kind is not WriteKind.KEEPALIVE:  # a repeat changes nothing
            self._last_change_at = now
        return True

    # --- hand-back ------------------------------------------------------------------------

    async def _async_hand_back_writes(self, now: float) -> None:
        """The hand-back write, which no guard holds back, and the release of learning. When the
        boiler holds nothing of ours there is nothing to give back."""
        if self._holding or self._hand_back_pending:
            await self._async_try_hand_back(now)
        self._hand_back_at = now
        self._last_change_at = now
        self._forget_last_command()  # the session ended; a stop's own hand-back keeps it
        await self._coordinator.async_save_control_now()  # a latch set with it must survive a crash
        await self._async_release_learning(now)

    async def _async_try_hand_back(self, now: float, full: bool = False) -> None:
        """One hand-back attempt; a failure is kept, shown and retried until it goes through.
        ``full``: also clear what an earlier session may have set (a retry after a restart) — so
        is every attempt made while a debt exists (P-49). The debt is marked and stored at once
        before anything is written, so whatever cuts the attempt short — any exception, a cancel
        inside a service, a crash — leaves it owed (P-42); a real cancellation passes, the debt
        kept. An attempt whose targets do not show the hand-back yet stays owed until they do."""
        full = full or self._full_hand_back_due or self._hand_back_pending
        self._release_from = self._value_to_leave()
        self._hand_back_pending = True
        self._hand_back_retry_at = now + HAND_BACK_RETRY_S
        self._follow_checks(())
        await self._async_store_owed()
        try:
            writer = self._writer or self._writer_factory(self._hass, self.options)
            checks = await writer.hand_back(
                full=full,
                release_from=self._release_from,
                write_timeout_s=STOP_WRITE_TIMEOUT_S if self._stopping else None,
            )
            self._follow_checks(checks)
            confirmed = self._checks_hold()
        except asyncio.CancelledError as err:
            if _cancelled_from_outside():
                raise  # a real cancellation: the debt stays marked and stored
            self._attempt_failed(now, err, expected=False)
            return
        except WriteError as err:
            self._attempt_failed(now, err, expected=True)
            return
        except Exception as err:  # a bug must not lose the debt either
            self._attempt_failed(now, err, expected=False)
            return
        if not confirmed:
            self._hand_back_pending = True
            self._coordinator.schedule_control_save()
            return
        await self._async_hand_back_confirmed()

    async def _async_store_owed(self) -> None:
        """The debt in the store before a hand-back's first write. A store that cannot be written
        does not hold the hand-back up: the boiler gets its own control back all the same."""
        try:
            await self._coordinator.async_save_control_now()
        except Exception:
            _LOGGER.exception("Could not store the owed hand-back before making it; made anyway")

    def _value_to_leave(self) -> float | None:
        """The setpoint the plugin last wrote, which a gateway's release must leave: this
        session's, else the last command stored, else the one an earlier attempt at the same
        debt had; ``None`` when none is known."""
        written = self._session.loop.setpoint.written
        if written is not None:
            return written
        command = self._last_command
        if command is not None and command.setpoint is not None:
            return command.setpoint
        return self._release_from

    def _attempt_failed(self, now: float, err: BaseException, expected: bool) -> None:
        """An attempt that did not get through: owed, shown, and sent again a minute later.
        Within the start grace a target not back yet (``expected``: a failed write) is only sent
        again at the next step, logged at DEBUG (P-50); anything else — a bug — shows at once."""
        self._hand_back_pending = True
        self._follow_checks(())
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
        self._coordinator.schedule_control_save()
        self._report_owed()

    async def _async_hand_back_confirmed(self) -> None:
        """The boiler has its own control back. Unless this is a stop's own hand-back, the last
        command is not to be given again."""
        self._holding = False
        self._full_hand_back_due = False
        self._hand_back_done()
        if self._forget_last_command():
            await self._coordinator.async_save_control_now()

    async def _async_follow_hand_back(self, now: float) -> None:
        """An owed hand-back: done once its targets show it; otherwise sent again every minute,
        and shown as failed once a sent one has gone unconfirmed that long — not within the
        start grace (P-50)."""
        if self._hand_back_checks and self._checks_hold():
            await self._async_hand_back_confirmed()
            return
        # A retry further ahead than planned means the wall clock went back: due now (C9).
        self._hand_back_retry_at = clock_due(self._hand_back_retry_at, now, HAND_BACK_RETRY_S)
        if now < self._hand_back_retry_at:
            return
        if self._hand_back_checks:
            targets = ", ".join(check.entity_id for check in self._hand_back_checks)
            if self._in_start_grace(now):
                _LOGGER.debug("The hand-back the last run left owed is not shown yet: %s", targets)
            else:
                if not self._hand_back_logged:
                    _LOGGER.error(
                        "The hand-back was not confirmed by %s; sending it again every minute",
                        targets,
                    )
                    self._hand_back_logged = True
                self._hand_back_failed = True
        await self._async_try_hand_back(now, full=True)

    def _checks_hold(self) -> bool:
        """Every target shows what the hand-back gave it: a value within half a kelvin, a switch
        state, or — a gateway — a read-back that has left the value the plugin wrote. A release
        seen once counts from then on: pyotgw shows the accepted CS=0 only until the boiler's
        next report, which may carry a thermostat asking for about the same value."""
        for check in self._hand_back_checks:
            if check.leaves and self._released_now(check):
                self._released.add(check.entity_id)
        return all(self._check_holds(check) for check in self._hand_back_checks)

    def _check_holds(self, check: HandBackCheck) -> bool:
        if check.leaves:
            return check.entity_id in self._released
        if isinstance(check.expected, str):
            state = self._hass.states.get(check.entity_id)
            return state is not None and state.state == check.expected
        reading = read_temperature(self._hass, check.entity_id)
        return (
            reading.value is not None
            and check.expected is not None
            and abs(float(reading.value) - check.expected) <= RELEASE_TOLERANCE_K
        )

    def _released_now(self, check: HandBackCheck) -> bool:
        """A gateway's read-back holds a value, and not the plugin's: more than half a kelvin
        from the setpoint the plugin wrote or — that one unknown — reported after the command. A
        read-back missing, unknown or unavailable never shows a release."""
        state = self._hass.states.get(check.entity_id)
        reading = temperature_from_state(state)
        if reading.value is None:
            return False
        if check.expected is None or isinstance(check.expected, str):
            return state is not check.before
        return abs(float(reading.value) - check.expected) > RELEASE_TOLERANCE_K

    def _follow_checks(self, checks: tuple[HandBackCheck, ...]) -> None:
        """The targets a hand-back waits on. Each of their reports is looked at as it comes, so a
        release shown only for a moment still counts, and a stop waiting for them ends once all
        show the hand-back."""
        self._hand_back_checks = checks
        self._released = set()
        if self._checks_unsub is not None:
            self._checks_unsub()
            self._checks_unsub = None
        if checks:
            self._checks_unsub = async_track_state_change_event(
                self._hass, sorted({check.entity_id for check in checks}), self._on_check_report
            )

    @callback
    def _on_check_report(self, _event: Event[EventStateChangedData]) -> None:
        if self._checks_hold() and self._checks_seen is not None:
            self._checks_seen.set()

    async def _async_wait_for_checks(self, until: float) -> None:
        """At a stop: the hand-back's targets get until ``until`` (the loop's clock) to show it."""
        seen = asyncio.Event()
        self._checks_seen = seen
        try:
            if not self._checks_hold():
                async with asyncio.timeout_at(until):
                    await seen.wait()
        except TimeoutError:
            _LOGGER.debug("The hand-back at the stop was not shown in time; it stays owed")
            return
        finally:
            self._checks_seen = None
        await self._async_hand_back_confirmed()

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
        self._follow_checks(())
        self._release_from = None
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
                self._full_hand_back_due = False
            self._hand_back_done()
            await self._coordinator.async_save_control_now()

    async def _async_hand_back_now(self, now: float) -> None:
        """Hand back at once if control holds the boiler (unload, stop, error)."""
        loop = self._session.loop
        if loop.control.controlling:
            await self._async_hand_back_writes(now)
            loop = self._session.loop
            control = replace(loop.control, controlling=False, command=None, decided_at=None)
            self._session.loop = LoopState(control)
        else:
            if self._hand_back_pending:
                await self._async_try_hand_back(now, full=True)
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
            snapshot.number(Signal.FLOW),
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
        elif plan.resume or plan.state.resuming != before.resuming:
            self._coordinator.schedule_control_save()  # a resume sent again: only its time

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
