"""The coordinator: follows the mapped entities, keeps a rolling history and computes what the
plugin's entities publish.

Two paths. The quick one runs on state changes (debounced) and every 30 s: current readings,
signal check, hot water, emitter factors, foreign heat, reference room, critical zones, current
alarms. The analysis runs every few minutes on a copy of the history, off the event loop:
summaries, verdict, trend warnings, report, outdoor check and building fit. After a restart the
history is rebuilt from the recorder, which keeps these states anyway; the plugin's own storage
holds only small things (monitoring start, held emitter factors, measured parameters).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .config import EntryConfig
from .const import (
    DOMAIN,
    FORECAST_SECONDS,
    HISTORY_DAYS,
    REFRESH_COOLDOWN_SECONDS,
    SUMMARY_SECONDS,
    TICK_SECONDS,
)
from .core.alarms import (
    FLUE_GAS_CONDENSING_BAND,
    PRESSURE_HIGH_BAND,
    PRESSURE_LOW_BAND,
    Alarm,
    AlarmKind,
    banded_alarm,
    frequent_starts,
    low_flow,
    unstable_ignition,
)
from .core.analysis import Analysis, analyse
from .core.critical_zone import CriticalZone, critical_zone
from .core.cycles import BurnKind, ClassifiedBurn, find_burns
from .core.emitters import FactorResult, FactorStatus, update_factor
from .core.foreign_heat import ForeignHeatState, update_foreign_heat
from .core.history import History, ZoneSeries
from .core.hot_water import HotWater, hot_water_available
from .core.parameters import Estimate, ParameterKey, ParameterSet, Source
from .core.readings import BoilerSnapshot, ZoneState
from .core.reference_room import ReferenceRoom, select_reference
from .core.series import Series
from .core.signal_check import (
    Feature,
    FeatureState,
    SignalHealth,
    check_signals,
    features,
    required_problems,
)
from .core.signals import SIGNAL_SPECS, Signal
from .core.supply import circuit_supply
from .forecasts import ForecastRecorder
from .transport.entities import (
    EntityTransport,
    read_source,
    read_temperature,
    reading_from_state,
    weather_from_state,
)
from .vtherm_attributes import CentralMode
from .vtherm_link import VtCapabilities, VThermLink

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
DAY = 86400.0
ZONE_MAX_AGE_S = 2 * 3600.0
SAVE_DELAY_S = 120


@dataclass(frozen=True, slots=True)
class ZoneView:
    zone_id: str
    name: str
    circuit_id: str
    state: ZoneState
    hot_water: HotWater
    factor: FactorResult
    foreign_heat: ForeignHeatState | None


@dataclass(frozen=True, slots=True)
class MonitorData:
    now: float
    snapshot: BoilerSnapshot
    health: dict[Signal, SignalHealth]
    features: dict[Feature, FeatureState]
    connected: bool
    zones: dict[str, ZoneView]
    reference: ReferenceRoom
    critical: dict[str, CriticalZone]
    alarms: dict[AlarmKind, Alarm]
    central_mode: CentralMode | None
    analysis: Analysis | None
    monitoring_since: float
    forecast_snapshots: int
    capabilities: VtCapabilities
    parameters: ParameterSet


class SmartBoilerCoordinator(DataUpdateCoordinator[MonitorData]):
    """One installation: its boiler, circuits and VT zones."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, config: EntryConfig) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=TICK_SECONDS),
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REFRESH_COOLDOWN_SECONDS, immediate=False
            ),
        )
        self.config = config
        self.transport = EntityTransport(hass, config.signals)
        self.link = VThermLink(hass, config.zone_entities)
        self.history = History(
            signals={signal: Series() for signal in config.signals},
            zones={zone: ZoneSeries(zone) for zone in config.zone_entities},
        )
        self.parameters = config.parameters
        self.monitoring_since = dt_util.utcnow().timestamp()
        self.forecasts = (
            ForecastRecorder(hass, entry.entry_id, config.weather) if config.weather else None
        )
        self.analysis: Analysis | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._factors: dict[str, FactorResult] = {}
        self._hot_water: dict[str, bool | None] = {}
        self._foreign: dict[str, ForeignHeatState] = {}
        self._reference: ReferenceRoom | None = None
        self._critical: dict[str, CriticalZone] = {}
        self._alarms: dict[AlarmKind, Alarm] = {}
        self._analysing = False
        self._save_pending = False

    # --- lifecycle ------------------------------------------------------------------------

    async def async_start(self) -> None:
        """Load stored state, rebuild the history and start following the entities."""
        now = dt_util.utcnow().timestamp()
        await self._async_load_store(now)
        await self._async_backfill(now)
        # Current states seed the history too: without the recorder they are all there is, and
        # an entity that does not change would otherwise never enter it.
        for entity_id in self.config.watched_entities:
            state = self.hass.states.get(entity_id)
            if state is not None:
                self._record(entity_id, state, state.last_updated.timestamp())
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, list(self.config.watched_entities), self._handle_state_event
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_analysis_tick, timedelta(seconds=SUMMARY_SECONDS)
            )
        )
        if self.forecasts is not None:
            await self.forecasts.async_load(now)
            self._unsubs.append(
                async_track_time_interval(
                    self.hass, self._async_forecast_tick, timedelta(seconds=FORECAST_SECONDS)
                )
            )
        self._schedule_save()

    def async_start_background(self) -> None:
        """First analysis and first forecast snapshot, without holding up setup."""
        self.config_entry.async_create_background_task(
            self.hass, self.async_run_analysis(), f"{DOMAIN} analysis"
        )
        if self.forecasts is not None:
            self.config_entry.async_create_background_task(
                self.hass, self._async_forecast_tick(None), f"{DOMAIN} forecasts"
            )

    async def async_stop(self) -> None:
        """Stop every listener and timer and write what is pending."""
        while self._unsubs:
            self._unsubs.pop()()
        await self.async_shutdown()
        await self._store.async_save(self._stored_data())
        if self.forecasts is not None:
            await self.forecasts.async_flush()

    # --- storage --------------------------------------------------------------------------

    async def _async_load_store(self, now: float) -> None:
        stored = await self._store.async_load() or {}
        self.monitoring_since = float(stored.get("monitoring_since", now))
        for zone_id, data in stored.get("factors", {}).items():
            if zone_id in self.config.zone_entities and data.get("value") is not None:
                self._factors[zone_id] = FactorResult(
                    float(data["value"]),
                    FactorStatus.HELD,
                    None,
                    data.get("at"),
                    data.get("output_w"),
                )
        for key, data in stored.get("measured", {}).items():
            try:
                estimate = Estimate(
                    float(data["value"]),
                    Source.MEASURED,
                    float(data["confidence"]),
                    data.get("at"),
                )
                self.parameters = self.parameters.with_estimate(ParameterKey(key), estimate)
            except KeyError, TypeError, ValueError:
                _LOGGER.warning("Ignoring an unreadable stored value for %s", key)

    def _stored_data(self) -> dict[str, Any]:
        self._save_pending = False
        measured = {}
        for key in (ParameterKey.LOSS_COEFFICIENT, ParameterKey.HEATING_THRESHOLD):
            estimate = self.parameters.get(key).estimate(Source.MEASURED)
            if estimate is not None:
                measured[key.value] = {
                    "value": estimate.value,
                    "confidence": estimate.confidence,
                    "at": estimate.at,
                }
        return {
            "monitoring_since": self.monitoring_since,
            "factors": {
                zone: {"value": f.value, "at": f.at, "output_w": f.output_w}
                for zone, f in self._factors.items()
                if f.value is not None
            },
            "measured": measured,
        }

    def _schedule_save(self) -> None:
        # Each delayed save restarts the store's timer: schedule only when none is pending, or
        # frequent updates would postpone the write forever.
        if not self._save_pending:
            self._save_pending = True
            self._store.async_delay_save(self._stored_data, SAVE_DELAY_S)

    # --- history --------------------------------------------------------------------------

    async def _async_backfill(self, now: float) -> None:
        """Rebuild the rolling history from the recorder, when it is loaded."""
        if "recorder" not in self.hass.config.components:
            return
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder import history as recorder_history
        except ImportError:
            return
        start = dt_util.utc_from_timestamp(now - HISTORY_DAYS * DAY)
        entity_ids = list(self.config.watched_entities)
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                partial(
                    recorder_history.get_significant_states,
                    self.hass,
                    start,
                    None,
                    entity_ids,
                    None,
                    True,
                    False,
                    False,
                    False,
                )
            )
        except Exception:  # the history is a convenience; never fail setup over it
            _LOGGER.warning("Could not read the recorder history", exc_info=True)
            return
        for entity_id, rows in states.items():
            for state in rows:
                if isinstance(state, State):
                    self._record(entity_id, state, state.last_updated.timestamp())

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        moment = state.last_updated.timestamp() if state is not None else event.time_fired
        if isinstance(moment, datetime):
            moment = moment.timestamp()
        self._record(event.data["entity_id"], state, float(moment))
        self.config_entry.async_create_task(self.hass, self.async_request_refresh())

    def _record(self, entity_id: str, state: State | None, t: float) -> None:
        signal = self.transport.signal_of(entity_id)
        if signal is not None:
            _append(self.history.signals[signal], t, reading_from_state(signal, state).value)
        if entity_id in self.history.zones:
            zone = self.link.zone_from_state(entity_id, state)
            series = self.history.zones[entity_id]
            for target, value in (
                (series.temperature, zone.temperature),
                (series.target, zone.target),
                (series.heating_enabled, zone.heating_enabled),
                (series.calling, zone.calling),
                (series.on_percent, zone.on_percent),
                (series.valve_open, zone.valve_open),
                (series.power, zone.power),
            ):
                _append(target, t, value)
        if entity_id == self.config.weather:
            _append(self.history.weather, t, weather_from_state(state).value)

    # --- quick path -----------------------------------------------------------------------

    async def _async_update_data(self) -> MonitorData:
        return self._compute(dt_util.utcnow().timestamp())

    def _max_age(self, signal: Signal) -> float | None:
        return self.config.freshness.get(signal, SIGNAL_SPECS[signal].max_age_s)

    def _compute(self, now: float) -> MonitorData:
        config = self.config
        snapshot = self.transport.snapshot(now)
        health = check_signals(snapshot, config.freshness)
        mapped = frozenset(config.signals)
        has_rates = all(
            self.parameters.value(key) is not None
            for key in (ParameterKey.GAS_AT_MIN_POWER, ParameterKey.GAS_AT_MAX_POWER)
        )
        feature_states = features(mapped, config.weather is not None, has_rates)
        flow = snapshot.number(Signal.FLOW)
        flow_fresh = snapshot.reading(Signal.FLOW).is_fresh(now, self._max_age(Signal.FLOW))
        return_temp = snapshot.number(Signal.RETURN, self._max_age(Signal.RETURN))
        dhw = self._dhw_now(snapshot)

        zone_states = {z.zone_id: self.link.zone(z.zone_id) for z in config.installation.zones}
        views: dict[str, ZoneView] = {}
        for zone_config, zone in zip(config.zones, config.installation.zones, strict=True):
            state = zone_states[zone.zone_id]
            circuit = config.installation.circuit(zone.circuit_id)
            assert circuit is not None  # the config was validated
            circuit_flow = None
            flow_entity = config.circuit_flow_entities.get(circuit.circuit_id)
            if flow_entity is not None:
                reading = read_temperature(self.hass, flow_entity)
                if reading.is_fresh(now, self._max_age(Signal.FLOW)):
                    circuit_flow = reading.value
            supply = circuit_supply(circuit, flow, flow_fresh, circuit_flow)
            hot = hot_water_available(
                supply,
                state.temperature,
                dhw,
                self._hot_water.get(zone.zone_id),
                config.monitor.near_room_k,
            )
            self._hot_water[zone.zone_id] = hot.available
            factor = update_factor(
                self._factors.get(zone.zone_id), zone, state, supply, return_temp, now
            )
            if factor.status is FactorStatus.COMPUTED:
                self._schedule_save()
            if factor.value is not None:
                self._factors[zone.zone_id] = factor
            foreign = None
            if zone_config.foreign_heat:
                foreign = update_foreign_heat(
                    self._foreign.get(zone.zone_id),
                    [
                        (source, read_source(self.hass, source.source_id, source.kind))
                        for source in zone_config.foreign_heat
                    ],
                    now,
                    config.monitor.foreign_heat_hold_s,
                )
                self._foreign[zone.zone_id] = foreign
            views[zone.zone_id] = ZoneView(
                zone.zone_id,
                self.link.zone_name(zone.zone_id),
                zone.circuit_id,
                state,
                hot,
                factor,
                foreign,
            )

        reference_config = config.reference_room
        self._reference = select_reference(
            list(zone_states.values()),
            reference_config.strategy,
            now,
            ZONE_MAX_AGE_S,
            self._reference,
            reference_config.zone,
            reference_config.switch_margin,
        )
        for circuit in config.installation.circuits:
            members = [
                zone_states[z.zone_id] for z in config.installation.zones_in(circuit.circuit_id)
            ]
            self._critical[circuit.circuit_id] = critical_zone(
                circuit.circuit_id,
                members,
                now,
                ZONE_MAX_AGE_S,
                self._critical.get(circuit.circuit_id),
            )

        self._alarms = self._current_alarms(snapshot, now, list(zone_states.values()))
        alarms = dict(self._alarms)
        if self.analysis is not None:
            alarms.update(self.analysis.trends)
        return MonitorData(
            now=now,
            snapshot=snapshot,
            health=health,
            features=feature_states,
            connected=not required_problems(health),
            zones=views,
            reference=self._reference,
            critical=dict(self._critical),
            alarms=alarms,
            central_mode=self.link.central_mode(),
            analysis=self.analysis,
            monitoring_since=self.monitoring_since,
            forecast_snapshots=len(self.forecasts.store.snapshots()) if self.forecasts else 0,
            capabilities=self.link.capabilities(),
            parameters=self.parameters,
        )

    def _dhw_now(self, snapshot: BoilerSnapshot) -> bool | None:
        """DHW running now: its own signal, else flame on without heating demand from the CH
        signal; otherwise unknown."""
        dhw = snapshot.flag(Signal.DHW_ACTIVE)
        if dhw is not None:
            return dhw
        flame, ch = snapshot.flag(Signal.FLAME), snapshot.flag(Signal.CH_ACTIVE)
        if flame is True and ch is False:
            return True
        return None

    def _current_alarms(
        self, snapshot: BoilerSnapshot, now: float, zones: list[ZoneState]
    ) -> dict[AlarmKind, Alarm]:
        alarms: dict[AlarmKind, Alarm] = {}
        pressure = snapshot.number(Signal.PRESSURE, self._max_age(Signal.PRESSURE))
        if snapshot.is_mapped(Signal.PRESSURE):
            for kind, band in (
                (AlarmKind.PRESSURE_LOW, PRESSURE_LOW_BAND),
                (AlarmKind.PRESSURE_HIGH, PRESSURE_HIGH_BAND),
            ):
                alarms[kind] = banded_alarm(kind, pressure, band, self._alarms.get(kind))
        if snapshot.is_mapped(Signal.FLUE_GAS) and self.config.installation.boiler.condensing:
            flue = snapshot.number(Signal.FLUE_GAS, self._max_age(Signal.FLUE_GAS))
            kind = AlarmKind.FLUE_GAS_HIGH
            alarms[kind] = banded_alarm(
                kind, flue, FLUE_GAS_CONDENSING_BAND, self._alarms.get(kind)
            )
        flame = self.history.signal(Signal.FLAME)
        burns = [
            ClassifiedBurn(burn, BurnKind.UNKNOWN, 0.0)
            for burn in find_burns(flame, now - DAY, now)
        ]
        alarms[AlarmKind.FREQUENT_STARTS] = frequent_starts(burns, now)
        alarms[AlarmKind.UNSTABLE_IGNITION] = unstable_ignition(burns, now)
        if snapshot.is_mapped(Signal.PUMP_RUNNING) or snapshot.is_mapped(Signal.CH_ACTIVE):
            pump = snapshot.flag(Signal.PUMP_RUNNING)
            if pump is None:
                pump = snapshot.flag(Signal.CH_ACTIVE)
            alarms[AlarmKind.LOW_FLOW] = low_flow(zones, pump, now, ZONE_MAX_AGE_S)
        return alarms

    # --- analysis -------------------------------------------------------------------------

    async def _async_analysis_tick(self, _now: datetime) -> None:
        await self.async_run_analysis()

    async def async_run_analysis(self) -> None:
        """The periodic analysis, on a copy of the history in an executor thread."""
        if self._analysing:
            return
        self._analysing = True
        try:
            now = dt_util.utcnow().timestamp()
            self.history.drop_before(now - HISTORY_DAYS * DAY)
            copy = self.history.copy_window(now - HISTORY_DAYS * DAY, now)
            days = local_days(now - HISTORY_DAYS * DAY, now)
            self.analysis = await self.hass.async_add_executor_job(
                analyse, copy, self.parameters, self.config.monitor.monitor, now, days
            )
            fit = self.analysis.fit
            if fit is not None:
                self.parameters = self.parameters.with_estimate(
                    ParameterKey.LOSS_COEFFICIENT, fit.loss
                )
                if fit.threshold is not None:
                    self.parameters = self.parameters.with_estimate(
                        ParameterKey.HEATING_THRESHOLD, fit.threshold
                    )
                self._schedule_save()
            self.async_set_updated_data(self._compute(now))
        except Exception:
            _LOGGER.exception("The periodic analysis failed")
        finally:
            self._analysing = False

    async def _async_forecast_tick(self, _now: datetime | None) -> None:
        if self.forecasts is None:
            return
        try:
            await self.forecasts.async_take(dt_util.utcnow().timestamp())
        except Exception:
            _LOGGER.exception("Taking a forecast snapshot failed")


def _append(series: Series, t: float, value: object) -> None:
    last = series.last
    series.append(max(t, last.t) if last is not None else t, value)


def local_days(start: float, end: float) -> list[tuple[float, float]]:
    """Whole days in Home Assistant's time zone inside ``[start, end)``."""
    tz = dt_util.get_default_time_zone()
    day = datetime.fromtimestamp(start, tz).date()
    days: list[tuple[float, float]] = []
    while True:
        begin = datetime.combine(day, time(), tz).timestamp()
        if begin >= end:
            return days
        finish = datetime.combine(day + timedelta(days=1), time(), tz).timestamp()
        if begin >= start and finish <= end:
            days.append((begin, finish))
        day += timedelta(days=1)
