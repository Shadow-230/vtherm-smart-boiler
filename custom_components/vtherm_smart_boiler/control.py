"""Control on the Home Assistant side: a control step every few seconds, its writes, hand-back on
every exit, learning pauses, and the status the entities show.

The step itself is pure (``core.loop``); this module only gathers its inputs, carries out its
writes through the writer, and turns guard events and failures into alarms. The writer exists
only while control is switched on. An internal error hands back and blocks control until the user
switches it off and on again; unloading the entry and stopping Home Assistant hand back too.
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
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import CONTROL_TICK_SECONDS
from .control_config import AlarmReaction, CapReaction, ControlOptions, config_blockers
from .core.controller import CentralMode as ControlCentralMode
from .core.controller import ControlInputs, ControlMode
from .core.guards import GuardEvent, SetpointGuardState, WriteAction, WriteKind
from .core.learning import LearningState, ZoneLearning, plan_learning, release_all
from .core.loop import LoopOutput, LoopState, loop_step
from .core.readings import ZoneState
from .core.signals import SIGNAL_SPECS, Signal
from .transport.entities import read_temperature, read_weather_temperature
from .transport.writers import WriteError, Writer, make_writer, writer_services
from .vtherm_attributes import CentralMode

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)
DAY = 86400.0
LINK_MAX_AGE_S = 600.0  # control needs the boiler's flow reported at least this recently
CONFIRM_MAX_AGE_S = 600.0  # a read-back older than this is unknown
LEARNING_TIMEOUT_S = 10.0
LEARNING_RETRY_S = 60.0
SMARTPI_DOMAIN = "vtherm_smartpi"
SMARTPI_SERVICE = "set_smartpi_learning"
# Blockers found while running, besides those of the configuration (translation keys).
RUNTIME_BLOCKERS = ("ha_starting", "monitoring_period", "vt_central_boiler_active", "control_error")

_CENTRAL = {
    CentralMode.AUTO: ControlCentralMode.AUTO,
    CentralMode.STOPPED: ControlCentralMode.STOPPED,
    CentralMode.HEAT_ONLY: ControlCentralMode.HEAT_ONLY,
    CentralMode.COOL_ONLY: ControlCentralMode.COOL_ONLY,
    CentralMode.FROST_PROTECTION: ControlCentralMode.FROST_PROTECTION,
}


class ControlAlarm(StrEnum):
    WRITE_FAILED = "write_failed"
    WRITE_IGNORED = "write_ignored"
    OUTSIDE_CHANGE = "outside_change"
    DAILY_CAP = "daily_cap"
    CONTROL_ERROR = "control_error"


_EVENT_ALARM = {
    GuardEvent.IGNORED: ControlAlarm.WRITE_IGNORED,
    GuardEvent.OUTSIDE_CHANGE: ControlAlarm.OUTSIDE_CHANGE,
    GuardEvent.DAILY_CAP: ControlAlarm.DAILY_CAP,
}


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
    hold_until: float | None = None  # anti-cycling holds the boiler until then
    alarms: frozenset[ControlAlarm] = frozenset()
    paused_zones: tuple[str, ...] = ()


@dataclass
class _Session:
    """One control session: from switching control on to switching it off."""

    loop: LoopState = field(default_factory=LoopState)
    learning: LearningState = field(default_factory=LearningState)
    alarms: set[ControlAlarm] = field(default_factory=set)
    failed: bool = False


type WriterFactory = Callable[[HomeAssistant, ControlOptions], Writer]


class ControlUnit:
    """Control for one installation; writes nothing until configured, allowed and switched on."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SmartBoilerCoordinator,
        options: ControlOptions,
        writer_factory: WriterFactory = make_writer,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self.options = options
        self._writer_factory = writer_factory
        self._writer: Writer | None = None
        self.enabled = False
        self._session = _Session()
        self._status = ControlStatus(options.configured)
        self._published: ControlStatus | None = None
        self._last_change_at: float | None = None
        self._hand_back_at: float | None = None
        self._learning_retry_at = 0.0
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._stop_unsub: CALLBACK_TYPE | None = None
        self._stopped = False

    # --- status, listeners, storage -----------------------------------------------------

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
        """What must survive a restart: recent wearing writes (daily cap) and paused zones."""
        guard = self._session.loop.setpoint
        writes = list(guard.history) if self.options.loop.setpoint_guard.wears else []
        return {"writes": writes, "paused": dict(self._session.learning.paused)}

    def restore(self, data: Mapping[str, Any]) -> None:
        try:
            writes = tuple(float(t) for t in data.get("writes", []))
            paused = {str(z): float(t) for z, t in dict(data.get("paused", {})).items()}
        except TypeError, ValueError:
            _LOGGER.warning("Ignoring unreadable stored control data")
            return
        self._session = _Session(
            loop=LoopState(setpoint=SetpointGuardState(history=writes)),
            learning=LearningState(paused=paused, last_toggle=dict(paused)),
        )

    # --- lifecycle ------------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the control clock and hand back when Home Assistant stops."""
        if not self.options.configured:
            return
        self._unsubs.append(
            async_track_time_interval(
                self._hass, self._async_timer, timedelta(seconds=CONTROL_TICK_SECONDS)
            )
        )
        self._stop_unsub = self._hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_ha_stop
        )

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
        self._coordinator.schedule_save()

    async def _async_timer(self, _now: datetime) -> None:
        if self._lock.locked():
            _LOGGER.debug("Control step skipped: the previous one is still running")
            return
        await self.async_tick()

    # --- switching ------------------------------------------------------------------------

    def blockers(self, now: float) -> tuple[str, ...]:
        """Why control may not run now (translation keys); empty when it may."""
        config = self._coordinator.config
        found = config_blockers(self.options, config.installation)
        if not self._hass.is_running:
            found.append("ha_starting")
        if now - self._coordinator.monitoring_since < config.monitor.monitoring_days * DAY:
            found.append("monitoring_period")
        if self._coordinator.link.vt_central_boiler_configured():
            found.append("vt_central_boiler_active")
        if self._session.failed:
            found.append("control_error")
        return tuple(found)

    async def async_set_enabled(self, enabled: bool, now: float | None = None) -> None:
        """Switch control on or off; switching off hands back at once."""
        async with self._lock:
            if self._stopped or enabled == self.enabled:
                return
            now = dt_util.utcnow().timestamp() if now is None else now
            self.enabled = enabled
            await self._async_tick_locked(now)
            if not enabled:
                self._end_session()
        self._notify()

    def _end_session(self) -> None:
        """A new session starts fresh; only the record of wearing writes and pauses carries on."""
        old = self._session
        self._session = _Session(
            loop=LoopState(setpoint=SetpointGuardState(history=old.loop.setpoint.history)),
            learning=old.learning,
        )
        self._writer = None

    # --- the step -------------------------------------------------------------------------

    async def async_tick(self, now: float | None = None) -> None:
        """One control step and its writes; never raises."""
        async with self._lock:
            if self._stopped:
                return
            await self._async_tick_locked(dt_util.utcnow().timestamp() if now is None else now)
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
            self._status = replace(
                self._status,
                blockers=(*self._status.blockers, "control_error"),
                mode=ControlMode.NOT_ALLOWED,
                alarms=frozenset(self._session.alarms),
            )

    async def _async_step(self, now: float) -> None:
        session = self._session
        blockers = self.blockers(now)
        if self.enabled and not blockers and self._writer is None:
            self._writer = self._writer_factory(self._hass, self.options)
        zones = self._coordinator.link.zones()
        self._unblock_daily_cap(now)
        inputs = self._inputs(now, zones, blockers)
        confirmed = self._confirmed(now)
        session.loop, out = loop_step(session.loop, inputs, confirmed, self.options.loop)
        if out.hand_back:
            await self._async_hand_back_writes(now)
        else:
            await self._async_writes(out, now)
        for event in out.events:
            session.alarms.add(_EVENT_ALARM[event])
        if session.loop.setpoint.confirmed_at is not None:
            session.alarms.discard(ControlAlarm.WRITE_IGNORED)
        await self._async_learning(now, zones)
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
            hold_until=out.decision.hold_until,
            alarms=frozenset(session.alarms),
            paused_zones=tuple(sorted(session.learning.paused)),
        )

    def _inputs(
        self, now: float, zones: Sequence[ZoneState], blockers: tuple[str, ...]
    ) -> ControlInputs:
        coordinator = self._coordinator
        config = coordinator.config
        snapshot = coordinator.transport.snapshot(now)
        link = snapshot.flag(Signal.FLAME) is not None and snapshot.reading(Signal.FLOW).is_fresh(
            now, _capped(config.freshness.get(Signal.FLOW), LINK_MAX_AGE_S)
        )
        outdoor_age = _capped(
            config.freshness.get(Signal.OUTDOOR), SIGNAL_SPECS[Signal.OUTDOOR].max_age_s
        )
        weather = None
        if config.weather:
            reading = read_weather_temperature(self._hass, config.weather)
            if reading.is_fresh(now, SIGNAL_SPECS[Signal.OUTDOOR].max_age_s):
                weather = float(reading.value) if reading.value is not None else None
        central = coordinator.link.central_mode()
        return ControlInputs(
            now=now,
            enabled=self.enabled,
            blockers=blockers,
            hand_back_alarms=self._hand_back_alarms(),
            central_mode=_CENTRAL.get(central) if central is not None else None,
            boiler_link=link,
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
            if alarm is ControlAlarm.CONTROL_ERROR:
                continue  # handled as a blocker
            if alarm is ControlAlarm.DAILY_CAP:
                if self.options.cap_reaction is CapReaction.HAND_BACK:
                    active.append(alarm.value)
            elif self.options.reaction(alarm.value) is AlarmReaction.HAND_BACK:
                active.append(alarm.value)
        return tuple(active)

    def _confirmed(self, now: float) -> float | None:
        """The setpoint the boiler reports back; ``None`` when unknown or stale."""
        entity = self.options.confirmed_entity
        if not entity:
            return None
        reading = read_temperature(self._hass, entity)
        if reading.value is None or not reading.is_fresh(now, CONFIRM_MAX_AGE_S):
            return None
        return float(reading.value)

    # --- writes ---------------------------------------------------------------------------

    async def _async_writes(self, out: LoopOutput, now: float) -> None:
        writer = self._writer
        if writer is None:
            if out.ch_enable is not None or out.setpoint is not None:
                _LOGGER.error("Control asked for a write without a writer; nothing written")
            return
        if out.ch_enable is not None:
            await self._async_write(writer.write_heating(out.ch_enable), now, None)
        if out.setpoint is not None:
            await self._async_write(writer.write_setpoint(out.setpoint.value), now, out.setpoint)

    async def _async_write(self, call: Any, now: float, action: WriteAction | None) -> None:
        try:
            await call
        except WriteError as err:
            _LOGGER.warning("A boiler write failed: %s", err)
            self._session.alarms.add(ControlAlarm.WRITE_FAILED)
            return
        self._session.alarms.discard(ControlAlarm.WRITE_FAILED)
        if action is None or action.kind is not WriteKind.KEEPALIVE:
            self._last_change_at = now
        if action is not None and self.options.loop.setpoint_guard.wears:
            self._coordinator.schedule_save()

    def _unblock_daily_cap(self, now: float) -> None:
        """A daily cap frees up as its 24-hour window moves on."""
        guard = self._session.loop.setpoint
        if guard.blocked is not GuardEvent.DAILY_CAP:
            return
        recent = tuple(t for t in guard.history if now - t < DAY)
        if len(recent) < self.options.loop.setpoint_guard.daily_cap:
            self._session.loop = replace(
                self._session.loop, setpoint=replace(guard, blocked=None, history=recent)
            )
            self._session.alarms.discard(ControlAlarm.DAILY_CAP)

    # --- hand-back ------------------------------------------------------------------------

    async def _async_hand_back_writes(self, now: float) -> None:
        """The hand-back write, which no guard holds back, and the release of learning."""
        writer = self._writer or self._writer_factory(self._hass, self.options)
        try:
            await writer.hand_back()
        except WriteError as err:
            _LOGGER.error("Handing control back failed: %s", err)
            self._session.alarms.add(ControlAlarm.WRITE_FAILED)
        self._hand_back_at = now
        self._last_change_at = now
        await self._async_release_learning(now, force=True)

    async def _async_hand_back_now(self, now: float) -> None:
        """Hand back at once if control holds the boiler (unload, stop, error)."""
        loop = self._session.loop
        if loop.control.controlling:
            await self._async_hand_back_writes(now)
            control = replace(loop.control, controlling=False, command=None, decided_at=None)
            fresh = SetpointGuardState(history=loop.setpoint.history)
            self._session.loop = LoopState(control, fresh)
        else:
            await self._async_release_learning(now, force=True)

    # --- learning pauses ------------------------------------------------------------------

    async def _async_learning(self, now: float, zones: Sequence[ZoneState]) -> None:
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
        snapshot = coordinator.transport.snapshot(now)
        plan = plan_learning(
            self._session.learning,
            learning_zones,
            coordinator.dhw_now(snapshot),
            snapshot.number(Signal.FLOW),
            self._session.loop.setpoint.written,
            now,
            self.options.learning,
        )
        state = plan.state
        for zone_id in plan.pause:
            await self._async_set_learning(zone_id, False)
        for zone_id in plan.resume:
            if not await self._async_set_learning(zone_id, True):
                state = replace(state, paused={**state.paused, zone_id: now})  # retried later
        if plan.pause or plan.resume:
            self._coordinator.schedule_save()
        self._session.learning = state

    async def _async_release_learning(self, now: float, force: bool = False) -> None:
        """Resume every zone the plugin paused; failures are retried a minute later."""
        if not self._session.learning.paused:
            return
        if not force and now < self._learning_retry_at:
            return
        state, zones = release_all(self._session.learning, now)
        failed = {}
        for zone_id in zones:
            if not await self._async_set_learning(zone_id, True):
                failed[zone_id] = now
        if failed:
            state = replace(state, paused=failed)
            self._learning_retry_at = now + LEARNING_RETRY_S
        self._session.learning = state
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
    """A freshness limit for control: the user's, but never longer than ``limit``."""
    if configured is None:
        return limit
    if limit is None:
        return configured
    return min(configured, limit)
