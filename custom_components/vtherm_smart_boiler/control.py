"""Control on the Home Assistant side: a control step every few seconds, its writes, hand-back on
every exit, learning pauses, and the status the entities show.

The step itself is pure (``core.loop``); this module only gathers its inputs, carries out its
writes through the writer, and turns guard events and failures into alarms. The writer exists
only while control is switched on. An internal error hands back and blocks control until the user
switches it off and on again; unloading the entry and stopping Home Assistant hand back too. A
hand-back is retried until it is confirmed — an entity hand-back counts only once each target
shows what it was given — and a failed one says so.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HassJob, HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import create_eager_task

from .const import CONTROL_TICK_SECONDS, DOMAIN
from .control_config import (
    AlarmReaction,
    ControlOptions,
    HandBack,
    WritePath,
    config_blockers,
)
from .core.controller import ControlInputs, ControlMode, ControlState, Reason
from .core.guards import (
    GuardEvent,
    SetpointGuardState,
    WriteAction,
    WriteKind,
    setpoint_failed,
    switch_failed,
)
from .core.learning import LearningState, ZoneLearning, plan_learning, release_all
from .core.loop import LoopOutput, LoopState, loop_step
from .core.readings import BoilerSnapshot, ZoneState
from .core.signals import SIGNAL_SPECS, Signal
from .transport.entities import read_bounds, read_temperature, read_weather_temperature
from .transport.writers import HandBackCheck, WriteError, Writer, make_writer, writer_services

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
DAY = 86400.0
LEARNING_TIMEOUT_S = 5.0
LEARNING_RETRY_S = 60.0
HAND_BACK_RETRY_S = 60.0
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
    "control_error",
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
    setpoint: float | None = None  # the setpoint last written
    target: float | None = None  # the decided setpoint before the ramp
    heating_on: bool | None = None
    confirmed: float | None = None  # what the boiler reports back
    last_change_at: float | None = None  # last write of a new value (keep-alives aside)
    hand_back_at: float | None = None
    alarms: frozenset[ControlAlarm] = frozenset()
    paused_zones: tuple[str, ...] = ()
    latched_by: tuple[str, ...] = ()  # the alarms that latched control, while it stays latched
    unknown_zones: tuple[str, ...] = ()  # zones whose state is not known now


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
    it never controls, only makes the owed hand-back, shown as a repair issue.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SmartBoilerCoordinator,
        options: ControlOptions,
        writer_factory: WriterFactory = make_writer,
        raw: Mapping[str, Any] | None = None,
        hand_back_only: bool = False,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self.options = options
        self._raw = dict(raw or {})
        self.hand_back_only = hand_back_only
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
        # The boiler may hold a value of ours: set before every write attempt and stored at once,
        # cleared only by a confirmed hand-back. After a crash it makes the next start hand back.
        self._holding = False
        self._unknown_since: dict[str, float] = {}
        self._hand_back_retry_at = 0.0
        self._learning_retry_at = 0.0
        self._restored = False
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

    # --- status, listeners, storage -----------------------------------------------------

    @property
    def hand_back_owed(self) -> bool:
        """A hand-back has not got through, or has not been confirmed, yet."""
        return self._hand_back_pending

    @property
    def status(self) -> ControlStatus:
        return self._status

    @property
    def allowed_services(self) -> frozenset[tuple[str, str]]:
        """Every service control may call, derived from the configuration alone."""
        services = set(writer_services(self.options))
        if services and self.options.learning_pauses:
            services.add((SMARTPI_DOMAIN, SMARTPI_SERVICE))
        return frozenset(services)

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
        latches and a hand-back still to be done."""
        session = self._session
        owed = self._holding or self._hand_back_pending
        return {
            "controlling": self._holding,
            "taken_with": dict(self._raw) if owed and self._raw else None,
            "paused": dict(session.learning.paused),
            "latched": session.loop.control.latched,
            "latched_by": list(session.loop.control.latched_by),
            # The one rewrite after an outside change: within a day of it, no more are made.
            "rewritten_at": session.loop.setpoint.rewritten_at,
            "failed": session.failed,
            "alarms": sorted(alarm.value for alarm in session.alarms & _KEPT_ALARMS),
            "hand_back_pending": self._hand_back_pending,
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        try:
            paused = {str(z): float(t) for z, t in dict(data.get("paused", {})).items()}
            alarms = {ControlAlarm(a) for a in data.get("alarms", [])} & _KEPT_ALARMS
            latched_by = tuple(str(a) for a in data.get("latched_by") or ())
            rewritten = data.get("rewritten_at")
            rewritten_at = None if rewritten is None else float(rewritten)
        except TypeError, ValueError:
            _LOGGER.warning("Ignoring unreadable stored control data")
            return
        latched = bool(data.get("latched", False))
        self._session = _Session(
            loop=LoopState(
                control=ControlState(latched=latched, latched_by=latched_by if latched else ()),
                setpoint=SetpointGuardState(rewritten_at=rewritten_at),
            ),
            learning=LearningState(paused=paused, last_toggle=dict(paused)),
            alarms=alarms,
            failed=bool(data.get("failed", False)),
        )
        self._holding = bool(data.get("controlling", False))
        # The last run held the boiler and never confirmed a hand-back (a crash, a power cut):
        # handed back in full at the first step; control may take the boiler again afterwards.
        self._hand_back_pending = bool(data.get("hand_back_pending", False)) or self._holding

    # --- lifecycle ------------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the control clock and hand back when Home Assistant stops."""
        if not self.options.configured:
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

    def mark_restored(self) -> None:
        """The switch has restored the user's choice: control steps may run."""
        self._restored = True

    async def _async_shutdown(self) -> None:
        # Home Assistant is going through its list of shutdown jobs: removing this one from it
        # now would make it skip the next job, so it stays.
        self._stop_unsub = None
        await self.async_stop()

    async def _async_ha_stop(self, _event: Event) -> None:
        self._stop_unsub = None  # a one-time listener removes itself
        await self.async_stop()

    async def async_stop(self) -> None:
        """Stop the clock and hand back; nothing is written afterwards. Never raises."""
        while self._unsubs:
            self._unsubs.pop()()
        if self._stop_unsub is not None:
            self._stop_unsub()
            self._stop_unsub = None
        if self._session.loop.control.controlling and not self._stopped:
            # Kept (and stored) until the hand-back has gone through: if Home Assistant cuts
            # this short, it is retried at the next start.
            self._hand_back_pending = True
            self._coordinator.schedule_save()
        self._stopping = True
        step = self._step_task
        if step is not None and not step.done():
            step.cancel()  # a slow step (a hanging service) must not hold up the hand-back
        async with self._lock:
            if self._stopped:
                return
            self._stopped = True
            now = dt_util.utcnow().timestamp()
            try:
                await self._async_hand_back_now(now)
            except Exception:
                _LOGGER.exception("Handing control back on stop failed")
            self._writer = None
        await self._async_learning_calls()
        self._coordinator.schedule_save()

    async def _async_timer(self, _now: datetime) -> None:
        # At most one step waits while another runs: a long step delays the next one instead
        # of dropping it, so a due keep-alive follows at once.
        if self._tick_waiting:
            return
        self._tick_waiting = True
        try:
            async with self._lock:
                self._tick_waiting = False  # running now: the next timer call may wait
                if self._stopped:
                    return
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
        if self._outside_entity_range():
            found.append("setpoint_outside_entity_range")
        if self._session.failed:
            found.append("control_error")
        return tuple(found)

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
            if self._stopped or enabled == self.enabled:
                return
            now = dt_util.utcnow().timestamp() if now is None else now
            self.enabled = enabled
            # Any change of the switch clears an internal error (a latch needs off, then on).
            self._session.failed = False
            self._session.alarms.discard(ControlAlarm.CONTROL_ERROR)
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
        self._coordinator.schedule_save()

    # --- the step -------------------------------------------------------------------------

    async def async_tick(self, now: float | None = None) -> None:
        """One control step and its writes; never raises."""
        async with self._lock:
            if self._stopped:
                return
            await self._async_run_step(dt_util.utcnow().timestamp() if now is None else now)
        await self._async_learning_calls()
        self._notify()

    async def _async_tick_locked(self, now: float) -> None:
        if not self.options.configured:
            return
        try:
            await self._async_step(now)
        except Exception:
            _LOGGER.exception("The control step failed; handing control back")
            self._session.failed = True
            self._session.alarms.add(ControlAlarm.CONTROL_ERROR)
            try:
                await self._async_hand_back_now(now)
            except Exception:
                _LOGGER.exception("Handing control back after an error failed")
            self._coordinator.schedule_save()
            self._status = replace(
                self._status,
                blockers=tuple(dict.fromkeys((*self._status.blockers, "control_error"))),
                mode=ControlMode.NOT_ALLOWED,
                alarms=frozenset(self._alarms()),
            )

    async def _async_step(self, now: float) -> None:
        session = self._session
        if self._hand_back_pending and not session.loop.control.controlling:
            await self._async_follow_hand_back(now)
        if self.hand_back_only:
            self._report_owed()
            return
        if not self._restored and now - self._started_at < RESTORE_WAIT_S:
            return  # the switch has not restored the user's choice yet: decide nothing
        blockers = self.blockers(now)
        if self.enabled and not blockers and self._writer is None:
            self._writer = self._writer_factory(self._hass, self.options)
        zones = self._coordinator.link.zones()
        snapshot = self._coordinator.transport.snapshot(now)
        inputs = self._inputs(now, snapshot, zones, blockers)
        confirmed = self._confirmed()
        session.loop, out = loop_step(session.loop, inputs, confirmed, self.options.loop)
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
        ):
            if flagged:
                session.alarms.add(alarm)
            else:
                session.alarms.discard(alarm)
        for event in out.events:
            session.alarms.add(_EVENT_ALARM[event])
        if out.events:
            self._coordinator.schedule_save()
        if session.loop.setpoint.confirmed_at is not None:
            session.alarms.discard(ControlAlarm.WRITE_IGNORED)
        command = out.decision.command
        await self._async_learning(
            now,
            snapshot,
            zones,
            None if command is None else command.setpoint,
            out.heating_on,
        )
        self._status = ControlStatus(
            configured=True,
            enabled=self.enabled,
            blockers=blockers,
            mode=out.decision.mode,
            reasons=tuple(r.value for r in out.decision.reasons),
            setpoint=session.loop.setpoint.written,
            target=out.decision.target,
            heating_on=out.heating_on,
            confirmed=confirmed,
            last_change_at=self._last_change_at,
            hand_back_at=self._hand_back_at,
            alarms=frozenset(self._alarms()),
            paused_zones=tuple(sorted(session.learning.paused)),
            latched_by=session.loop.control.latched_by if session.loop.control.latched else (),
            unknown_zones=unknown,
        )

    def _follow_unknown_zones(self, now: float, zones: Sequence[ZoneState]) -> tuple[str, ...]:
        """Zones whose state is not known: the known ones decide meanwhile; one unknown for long
        raises an alarm, as frost protection cannot see it."""
        max_age = self.options.loop.control.zone_max_age_s
        unknown = tuple(z.zone_id for z in zones if not z.is_known(now, max_age))
        self._unknown_since = {z: self._unknown_since.get(z, now) for z in unknown}
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
        # A missing outdoor reading only moves the curve to the weather entity, so its age limit
        # stays: a sensor stuck at a mild value must not keep the house in summer mode.
        outdoor_age = _capped(
            config.freshness.get(Signal.OUTDOOR), SIGNAL_SPECS[Signal.OUTDOOR].max_age_s
        )
        weather = None
        if config.weather:
            reading = read_weather_temperature(self._hass, config.weather)
            if reading.is_fresh(now, SIGNAL_SPECS[Signal.OUTDOOR].max_age_s):
                weather = float(reading.value) if reading.value is not None else None
        return ControlInputs(
            now=now,
            enabled=self.enabled,
            blockers=blockers,
            hand_back_alarms=self._hand_back_alarms(),
            boiler_link=self._boiler_link(snapshot, now),
            flame=snapshot.flag(Signal.FLAME),
            dhw=coordinator.dhw_now(snapshot),
            outdoor_sensor=snapshot.number(Signal.OUTDOOR, outdoor_age),
            outdoor_weather=weather,
            zones=tuple(zones),
        )

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
            ):
                continue  # a blocker, a retry of its own, and a hand-back already made
            if self.options.reaction(alarm.value) is AlarmReaction.HAND_BACK:
                active.append(alarm.value)
        return tuple(active)

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
            if out.ch_enable is not None or out.setpoint is not None:
                _LOGGER.error("Control asked for a write without a writer; nothing written")
            return
        loop = self._session.loop
        # The setpoint first: a gateway applies heating on/off only while its setpoint override
        # is in force. A write that fails is sent again at the next step.
        if out.setpoint is not None and not await self._async_write(
            "setpoint", writer.write_setpoint(out.setpoint.value), now, out.setpoint
        ):
            loop = replace(loop, setpoint=setpoint_failed(loop.setpoint))
        if out.ch_enable is not None and not await self._async_write(
            "heating", writer.write_heating(out.ch_enable), now, None
        ):
            loop = replace(loop, switch=switch_failed(loop.switch))
        self._session.loop = loop

    async def _async_write(
        self, kind: str, call: Any, now: float, action: WriteAction | None
    ) -> bool:
        session = self._session
        if not self._holding:
            # Before the attempt: a write reported as failed may still reach the boiler.
            self._holding = True
            await self._coordinator.async_save_now()
        try:
            await call
        except WriteError as err:
            _LOGGER.warning("A boiler write failed; sent again at the next step: %s", err)
            session.failing.add(kind)
            session.alarms.add(ControlAlarm.WRITE_FAILED)
            return False
        session.failing.discard(kind)
        if not session.failing:  # each kind of write clears only its own failure
            session.alarms.discard(ControlAlarm.WRITE_FAILED)
        if self._hand_back_pending:
            # Control has the boiler again: the earlier hand-back no longer matters.
            self._hand_back_done()
        if action is None or action.kind is not WriteKind.KEEPALIVE:
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
        self._coordinator.schedule_save()  # a latch set with it must survive a restart
        await self._async_release_learning(now, force=True)

    async def _async_try_hand_back(self, now: float, full: bool = False) -> bool:
        """One hand-back attempt; a failure is kept, shown and retried until it goes through.
        ``full``: also clear what an earlier session may have set (a retry after a restart). An
        attempt whose targets do not show the hand-back yet stays owed until they do."""
        try:
            writer = self._writer or self._writer_factory(self._hass, self.options)
            checks = await writer.hand_back(full=full)
        except (WriteError, ValueError) as err:
            _LOGGER.error("Handing control back failed; retrying every minute: %s", err)
            self._hand_back_pending = True
            self._hand_back_failed = True
            self._hand_back_checks = ()
            self._hand_back_retry_at = now + HAND_BACK_RETRY_S
            self._coordinator.schedule_save()
            self._report_owed()
            return False
        if checks and not self._checks_hold(checks):
            self._hand_back_pending = True
            self._hand_back_checks = checks
            self._hand_back_retry_at = now + HAND_BACK_RETRY_S
            self._coordinator.schedule_save()
            return True
        self._holding = False
        self._hand_back_done()
        return True

    async def _async_follow_hand_back(self, now: float) -> None:
        """An owed hand-back: done once its targets show it; otherwise sent again every minute,
        and shown as failed once a sent one has gone unconfirmed that long."""
        if self._hand_back_checks and self._checks_hold(self._hand_back_checks):
            self._holding = False
            self._hand_back_done()
            return
        if now < self._hand_back_retry_at:
            return
        if self._hand_back_checks:
            _LOGGER.error(
                "The hand-back was not confirmed by %s; sending it again",
                ", ".join(check.entity_id for check in self._hand_back_checks),
            )
            self._hand_back_failed = True
        await self._async_try_hand_back(now, full=True)

    def _checks_hold(self, checks: Sequence[HandBackCheck]) -> bool:
        """Every target shows what the hand-back gave it (a value within half a kelvin)."""
        for check in checks:
            if isinstance(check.expected, str):
                state = self._hass.states.get(check.entity_id)
                if state is None or state.state != check.expected:
                    return False
                continue
            reading = read_temperature(self._hass, check.entity_id)
            if reading.value is None or abs(float(reading.value) - check.expected) > 0.5:
                return False
        return True

    def _hand_back_done(self) -> None:
        """No hand-back is owed any more: it was confirmed, or control has the boiler again."""
        changed = self._hand_back_pending or self._hand_back_failed
        self._hand_back_pending = False
        self._hand_back_failed = False
        self._hand_back_checks = ()
        if changed:
            self._coordinator.schedule_save()
        self._report_owed()

    def _report_owed(self) -> None:
        """Without the control entities, a repair issue shows a hand-back still owed."""
        if not self.hand_back_only:
            return
        issue_id = f"hand_back_owed_{self._coordinator.config_entry.entry_id}"
        if self._hand_back_pending:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="hand_back_owed",
            )
        else:
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)

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
            await self._async_release_learning(now, force=True)

    # --- learning pauses ------------------------------------------------------------------

    async def _async_learning(
        self,
        now: float,
        snapshot: BoilerSnapshot,
        zones: Sequence[ZoneState],
        heating_setpoint: float | None,
        heating: bool | None,
    ) -> None:
        if not (self.options.learning_pauses and self._session.loop.control.controlling):
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
        if plan.pause or plan.resume:
            self._coordinator.schedule_save()
        self._session.learning = plan.state

    async def _async_release_learning(self, now: float, force: bool = False) -> None:
        """Resume every zone the plugin paused; failures are retried a minute later."""
        if not self._session.learning.paused:
            return
        if not force and now < self._learning_retry_at:
            return
        state, zones = release_all(self._session.learning, now)
        self._learning_calls += [(zone_id, True) for zone_id in zones]
        self._session.learning = state
        self._coordinator.schedule_save()

    async def _async_learning_calls(self) -> None:
        """Make the planned SmartPI calls, together and without the lock. A resume that fails
        keeps its zone paused, retried a minute later; a failed pause leaves the zone learning."""
        calls, self._learning_calls = self._learning_calls, []
        if not calls:
            return
        results = await asyncio.gather(
            *(self._async_set_learning(zone_id, enabled) for zone_id, enabled in calls)
        )
        failed = [zone_id for (zone_id, enabled), ok in zip(calls, results, strict=True)
                  if enabled and not ok]  # fmt: skip
        if failed:
            now = dt_util.utcnow().timestamp()
            state = self._session.learning
            paused = {**state.paused, **dict.fromkeys(failed, now)}
            self._session.learning = replace(state, paused=paused)
            self._learning_retry_at = now + LEARNING_RETRY_S
            self._coordinator.schedule_save()

    async def _async_set_learning(self, zone_id: str, enabled: bool) -> bool:
        try:
            async with asyncio.timeout(LEARNING_TIMEOUT_S):
                await self._hass.services.async_call(
                    SMARTPI_DOMAIN,
                    SMARTPI_SERVICE,
                    {"entity_id": zone_id, "learning_enabled": enabled},
                    blocking=True,
                )
        except Exception as err:  # a learning pause must never break control
            action = "resume" if enabled else "pause"
            _LOGGER.warning("Could not %s SmartPI learning of %s: %r", action, zone_id, err)
            return False
        return True


def _capped(configured: float | None, limit: float | None) -> float | None:
    """A freshness limit: the user's, but never longer than ``limit``."""
    if configured is None:
        return limit
    if limit is None:
        return configured
    return min(configured, limit)
