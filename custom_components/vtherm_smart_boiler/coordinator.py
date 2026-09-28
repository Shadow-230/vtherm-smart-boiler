"""The coordinator: follows the mapped entities, keeps a rolling history and computes what the
plugin's entities publish.

Two paths. The quick one runs on state changes (debounced) and every 30 s: current readings,
signal check, hot water, emitter factors, foreign heat, reference room, critical zones, current
alarms. The analysis runs every few minutes on a copy of the history, off the event loop:
summaries, verdict, trend warnings, report, outdoor check and building fit. After a restart the
history is rebuilt from the recorder, which keeps these states anyway; the plugin's own storage
holds only small things (monitoring start, held emitter factors, measured parameters).

With the analysis it judges the lowest water temperature's evidence and shows a suggestion,
never applied (X6, decision 2); the quick path shows what the wall thermostat on a gateway keeps
after a hand-back. Each has its repair issue, raised here.

The control state — whether the boiler may hold a value of ours, an owed hand-back, latches —
lives in a store of its own, written at once and atomically; the entry's store keeps a copy.
One function reads it for every place that asks (``async_read_control_state``): a state that
cannot be read counts as "the plugin held the boiler" wherever control is configured.
"""

from __future__ import annotations

import copy
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import feature_manager
from .config import EntryConfig
from .const import (
    CONTROL_STORE_MARKER,
    CONTROL_STORE_VERSION,
    DOMAIN,
    FORECAST_SECONDS,
    HISTORY_DAYS,
    REFRESH_COOLDOWN_SECONDS,
    STORAGE_VERSION,
    SUMMARY_SECONDS,
    TICK_SECONDS,
    UNREADABLE_ISSUE,
    assumed_owed_state,
    control_state_owed,
    control_store_key,
    has_control_section,
    main_store_key,
    owes_hand_back,
    stored_flag,
)
from .control_config import Topology, wall_thermostat_applies
from .core.alarms import (
    Alarm,
    AlarmKind,
    banded_alarm,
    circuit_flow,
    circuit_too_hot,
    frequent_starts,
    low_flow,
    unstable_ignition,
)
from .core.analysis import Analysis, analyse
from .core.controller import OutageWindow, follow_outage
from .core.critical_zone import CriticalZone, critical_zone
from .core.cycles import classify_burns, find_burns
from .core.daily import KEEP_DAYS, DaySummary, settings_key, summarize_day
from .core.emitters import FactorResult, FactorStatus, update_factor
from .core.foreign_heat import ForeignHeatState, update_foreign_heat
from .core.history import History, ZoneSeries
from .core.hot_water import HotWater, hot_water_available
from .core.lowest_water import (
    LowestWaterSuggestion,
    SetpointSource,
    SuggestionContext,
    SuggestionState,
    WallFallback,
    WallWarning,
    WaterSetBy,
    design_load_kw,
    entered_min_power,
    estimate_from_power,
    suggest_lowest_water,
    wall_issue_due,
    wall_thermostat_fallback,
    wall_warning_since,
)
from .core.metrics import CH_KINDS
from .core.monitor import dhw_inputs
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
from .core.signals import Signal
from .core.supply import circuit_return, circuit_supply
from .core.zone_watch import every_zone_unknown_since, issue_due
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

if TYPE_CHECKING:
    from .control import ControlUnit

_LOGGER = logging.getLogger(__name__)
DAY = 86400.0
# Decision 3: every configured zone unknown for ten minutes — a repair issue in every mode, the
# monitor only included; its text follows what control does then (translation keys
# ``no_zone_known_off``, ``_handed_back``, ``_monitor``).
NO_ZONE_KNOWN_ISSUE = "no_zone_known"
# X6: the wall thermostat on a gateway would keep the house cool after a hand-back (``_unknown``:
# it reports no setpoint); the lowest water temperature's suggestion (``_boiler``: worded for the
# device that sets the water). Warnings, not fixable.
WALL_ISSUE = "wall_thermostat_fallback"
LOWEST_WATER_ISSUE = "lowest_water_suggestion"
ZONE_MAX_AGE_S: float | None = None  # one freshness rule: a steady room is not a stale one
SAVE_DELAY_S = 120
# An emitter factor is recomputed at every update while its zone heats: saved at this pace, so
# the store is not rewritten every two minutes all winter.
FACTOR_SAVE_DELAY_S = 15 * 60
MONITOR_REFRESH = "The monitor refresh"  # the quick path, as its failure and recovery are logged


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
    # X6: the lowest water temperature's suggestion (the last analysis'), and what the wall
    # thermostat on a gateway keeps after a hand-back (``None`` where there is none to show).
    lowest_water: LowestWaterSuggestion | None = None
    wall_thermostat: WallFallback | None = None


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
        # The options this instance runs with: another value of them is what needs a reload.
        self.options: dict[str, Any] = copy.deepcopy(dict(entry.options))
        self.transport = EntityTransport(hass, config.signals)
        self.link = VThermLink(hass, config.zone_entities)
        self.history = self._empty_history()
        self.parameters = config.parameters
        # Days summarised with other settings no longer count (A4): the key of the current ones.
        self.settings_key = settings_key(summary_settings(config))
        # Counts from the entry's creation (set when the store is read), so a lost store never
        # starts the monitoring period again.
        self.monitoring_since = dt_util.utcnow().timestamp()
        self.forecasts = (
            ForecastRecorder(hass, entry.entry_id, config.weather) if config.weather else None
        )
        self.analysis: Analysis | None = None
        self._store = main_store(hass, entry.entry_id)
        self._control_store = control_store(hass, entry.entry_id)
        # Nothing is written before both stores were read: a setup that fails earlier must not
        # write the defaults over what the last run left (P-04).
        self._loaded = False
        # The boiler's hold and an owed hand-back as last written to the entry store's copy: a
        # change of them is written there at once too.
        self._main_owed: tuple[bool, bool] | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._factors: dict[str, FactorResult] = {}
        self._hot_water: dict[str, bool | None] = {}
        self._foreign: dict[str, ForeignHeatState] = {}
        self._reference: ReferenceRoom | None = None
        self._critical: dict[str, CriticalZone] = {}
        self._alarms: dict[AlarmKind, Alarm] = {}
        self._circuit_alarms: dict[str, Alarm] = {}  # each circuit's too-hot alarm (decision 10)
        self._analysing = False
        # A lasting failure of a periodic job is logged once, with its trace, and its end once.
        self._failing: set[str] = set()
        # The monitor's refreshes of the last ten minutes, each failed or not: control hands back
        # while they fail for five (V6); and the first failure of the current streak, shown.
        self._refreshes = OutageWindow()
        self.monitor_failed_since: float | None = None
        self._save_due: float | None = None  # when the pending delayed save runs
        # Day summaries for the verdict, kept for up to a year (SCOPE.md §10).
        self.daily: dict[float, DaySummary] = {}
        self._history_back = False  # the recorder's history has been read (or cannot be)
        self._stopped = False
        # The entities the platforms create now (disabled ones too): the rest are stale.
        self.expected_unique_ids: set[str] = set()
        self.control: ControlUnit | None = None
        # Control left the options while a hand-back was still owed: this unit only hands back.
        self.hand_back_unit: ControlUnit | None = None
        self.stored_control: dict[str, Any] = {}
        # Whether the stored control state could be read: a lost or damaged store gives no
        # last command to restore (decision 3, answer K).
        self.control_readable = True
        self._control_provider: Callable[[], dict[str, Any]] | None = None
        # Decision 3's repair issue: every zone unknown since, for the monitor only; the kind
        # raised now.
        self._zones_unknown_since: float | None = None
        self._no_zone_issue: str | None = None
        # X6: the suggestion the last analysis gave; the wall thermostat's warning since, and
        # the issues raised now (their translation key and placeholders).
        self.lowest_water: LowestWaterSuggestion | None = None
        self._wall_since: float | None = None
        self._wall_issue: tuple[str, dict[str, str]] | None = None
        self._lowest_water_issue: tuple[str, dict[str, str]] | None = None

    # --- lifecycle ------------------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        """Both stores have been read: what the last run left is known."""
        return self._loaded

    async def async_load(self) -> None:
        """Read both stores — first in setup, so a hand-back the last run left owed is known
        (and made) before anything else can fail."""
        await self._async_load_store(dt_util.utcnow().timestamp())

    async def async_start(self) -> None:
        """Find VT, rebuild the history and start following the entities (after
        ``async_load``)."""
        now = dt_util.utcnow().timestamp()
        await self.link.async_detect()
        # Current states seed the history too: without the recorder they are all there is, and
        # an entity that does not change would otherwise never enter it.
        zones = set(self.config.zone_entities)
        for entity_id in self.config.watched_entities:
            if entity_id in zones:  # zone data only through the VT link
                state = self.link.recorded_state(entity_id)
            else:
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
            try:
                await self.forecasts.async_load(now)
            except Exception:  # forecasts are an extra: they never fail setup
                _LOGGER.exception("Could not load the stored forecasts; recording goes on")
            self._unsubs.append(
                async_track_time_interval(
                    self.hass, self._async_forecast_tick, timedelta(seconds=FORECAST_SECONDS)
                )
            )
        self.schedule_save()

    def async_start_background(self) -> None:
        """The recorder's history, then the first analysis, and the first forecast snapshot,
        without holding up setup."""
        self.check_learning()
        self.config_entry.async_create_background_task(
            self.hass, self._async_backfill_then_analyse(), f"{DOMAIN} analysis"
        )
        if self.forecasts is not None:
            self.config_entry.async_create_background_task(
                self.hass, self._async_forecast_tick(None), f"{DOMAIN} forecasts"
            )

    async def async_stop(self) -> None:
        """Stop every listener and timer and write what is pending."""
        self._stopped = True
        while self._unsubs:
            self._unsubs.pop()()
        for key in (
            "auto_tpi_blocked",
            "learning_not_paused",
            NO_ZONE_KNOWN_ISSUE,
            WALL_ISSUE,
            LOWEST_WATER_ISSUE,
        ):
            ir.async_delete_issue(self.hass, DOMAIN, f"{key}_{self.config_entry.entry_id}")
        self._no_zone_issue = None
        self._wall_issue = self._lowest_water_issue = None
        await self.async_shutdown()
        if self._loaded:
            await self._control_store.async_save(self._stored_control())
            await self._store.async_save(self._stored_data())
        if self.forecasts is not None:
            await self.forecasts.async_flush()

    # --- storage --------------------------------------------------------------------------

    async def _async_load_store(self, now: float) -> None:
        """What the last run stored, field by field: a broken field is skipped, not the rest.
        The control state comes through ``async_read_control_state``: one that cannot be read
        where control is configured makes a full hand-back first. The monitoring start is the
        entry's creation; a lost store does not start it again."""
        entry = self.config_entry
        read = await async_read_control_state(
            self.hass, entry.entry_id, entry.options, main=self._store, control=self._control_store
        )
        stored = _mapping(read.main)
        self.monitoring_since = self._monitoring_start(stored, now)
        self.stored_control = dict(read.state)
        self.control_readable = read.readable
        self._main_owed = _owed_flags(stored.get("control"))
        if read.owed and not read.readable:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{UNREADABLE_ISSUE}_{entry.entry_id}",
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=UNREADABLE_ISSUE,
            )
        factors = stored.get("factors")
        for zone_id, data in factors.items() if isinstance(factors, dict) else ():
            if zone_id not in self.config.zone_entities or not isinstance(data, dict):
                continue
            try:
                if data.get("value") is not None:
                    self._factors[zone_id] = FactorResult(
                        float(data["value"]),
                        FactorStatus.HELD,
                        None,
                        _optional_float(data.get("at")),
                        _optional_float(data.get("output_w")),
                    )
            except TypeError, ValueError:
                _LOGGER.warning("Ignoring an unreadable stored emitter factor for %s", zone_id)
        daily = stored.get("daily")
        for data in daily.values() if isinstance(daily, dict) else ():
            try:
                day = DaySummary.from_dict(data)
            except KeyError, TypeError, ValueError:
                _LOGGER.warning("Ignoring an unreadable stored day summary")
                continue
            if day.start >= now - KEEP_DAYS * DAY:
                self.daily[day.start] = day
        measured = stored.get("measured")
        for key, data in measured.items() if isinstance(measured, dict) else ():
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
        self._loaded = True
        if read.rewrite:
            # Moved from a 0.2.1 store, or taken cautiously after a loss: written at once, so
            # the next start reads it from the control store.
            await self._control_store.async_save(self._stored_control())
            await self._store.async_save(self._stored_data())

    def _monitoring_start(self, stored: dict[str, Any], now: float) -> float:
        """The entry's creation; for an entry without one (migrated from Home Assistant's old
        storage, epoch 0), the stored start, else now."""
        created = getattr(self.config_entry, "created_at", None)
        try:
            at = created.timestamp() if isinstance(created, datetime) else 0.0
        except OverflowError, OSError, ValueError:
            at = 0.0
        if math.isfinite(at) and at > 0:
            return at
        raw = stored.get("monitoring_since")
        if raw is None:
            return now
        try:
            since = float(raw)
        except TypeError, ValueError:
            since = math.nan
        if not math.isfinite(since):
            _LOGGER.warning("Ignoring an unreadable start of monitoring: it starts again now")
            return now
        return since

    def _stored_data(self) -> dict[str, Any]:
        self._save_due = None
        measured = {}
        for key in (ParameterKey.LOSS_COEFFICIENT, ParameterKey.HEATING_THRESHOLD):
            estimate = self.parameters.get(key).estimate(Source.MEASURED)
            if estimate is not None:
                measured[key.value] = {
                    "value": estimate.value,
                    "confidence": estimate.confidence,
                    "at": estimate.at,
                }
        control = self._stored_control()
        self._main_owed = _owed_flags(control)
        return {
            "monitoring_since": self.monitoring_since,
            "factors": {
                zone: {"value": f.value, "at": f.at, "output_w": f.output_w}
                for zone, f in self._factors.items()
                if f.value is not None
            },
            "measured": measured,
            "daily": {str(int(start)): day.to_dict() for start, day in sorted(self.daily.items())},
            # A copy of the control state: the fallback, and what 0.2.1 reads after a downgrade.
            "control": control,
            CONTROL_STORE_MARKER: CONTROL_STORE_VERSION,
        }

    def provide_stored_control(self, provider: Callable[[], dict[str, Any]]) -> None:
        """What control keeps across restarts comes from the unit that runs it; kept after the
        unit stops, for the last save."""
        self._control_provider = provider

    def _stored_control(self) -> dict[str, Any]:
        provider = self._control_provider
        return provider() if provider is not None else self.stored_control

    async def async_save_control_now(self) -> None:
        """Write the control state at once: for what a crash must not lose (the controlling
        marker, a latch). The entry store's copy is written at once too when the boiler's hold
        or an owed hand-back changed, otherwise with the delayed save."""
        if not self._loaded or self._stopped:
            return
        await self._control_store.async_save(self._stored_control())
        if _owed_flags(self._stored_control()) != self._main_owed:
            await self.async_save_now()
        else:
            self.schedule_save()

    def schedule_control_save(self) -> None:
        """``async_save_control_now`` from code that cannot wait: written at the next turn of
        the event loop."""
        if not self._loaded or self._stopped:
            return
        self._control_store.async_delay_save(self._stored_control, 0)
        changed = _owed_flags(self._stored_control()) != self._main_owed
        self.schedule_save(0 if changed else SAVE_DELAY_S)

    async def async_save_now(self) -> None:
        """Write the entry's store at once."""
        if not self._loaded or self._stopped:
            return
        await self._store.async_save(self._stored_data())

    def _keep_days(self, days: Sequence[DaySummary], now: float) -> None:
        """Keep newly summarised days, over one summarised with other settings; drop those
        older than a year."""
        added = [
            day
            for day in days
            if (kept := self.daily.get(day.start)) is None or kept.settings != day.settings
        ]
        for day in added:
            self.daily[day.start] = day
        cutoff = now - KEEP_DAYS * DAY
        dropped = [start for start in self.daily if start < cutoff]
        for start in dropped:
            del self.daily[start]
        if added or dropped:
            self.schedule_save(FACTOR_SAVE_DELAY_S)

    def rename_zone(self, old: str, new: str) -> None:
        """P-19: a zone's VT climate renamed: the emitter factor learned for it follows, stored
        under the new entity ID at the next save (the reload that follows makes one)."""
        if old in self._factors:
            self._factors[new] = self._factors.pop(old)

    def expect_entities(self, entities: list[Any]) -> None:
        self.expected_unique_ids.update(e.unique_id for e in entities if e.unique_id)

    def schedule_save(self, delay: float = SAVE_DELAY_S) -> None:
        """Save within ``delay``. Each delayed save restarts the store's timer, so one is
        scheduled only when it comes sooner than the one pending: frequent updates would
        otherwise postpone the write for ever. A stopped installation saves nothing more: the
        one set up after a reload owns the store; nothing is saved before the store was read."""
        if self._stopped or not self._loaded:
            return
        due = dt_util.utcnow().timestamp() + delay
        if self._save_due is None or due < self._save_due:
            self._save_due = due
            self._store.async_delay_save(self._stored_data, delay)

    # --- history --------------------------------------------------------------------------

    async def _async_backfill_then_analyse(self) -> None:
        now = dt_util.utcnow().timestamp()
        try:
            await self._async_backfill(now)
        finally:
            # From now on the rolling history holds whatever the recorder could give: days
            # summarised from it are worth keeping; before, a few hours would pass for a day.
            self._history_back = True
        await self._async_fill_days(now)
        await self.async_run_analysis()

    async def _async_fill_days(self, now: float) -> None:
        """Day summaries from the recorder for the days before the rolling history, as far back
        as the recorder reaches — a week at a time, and at most a year: the verdict does not
        then depend on how long the recorder keeps its data."""
        if "recorder" not in self.hass.config.components:
            return
        try:
            recorder, significant_states = _recorder(self.hass), _significant_states()
        except ImportError:
            return
        # Whole local days only, up to the rolling history's first whole day, a week at a time
        # from the newest back.
        rolling = local_days(now - HISTORY_DAYS * DAY, now)
        fill_end = rolling[0][0] if rolling else now - HISTORY_DAYS * DAY
        windows = local_days(now - KEEP_DAYS * DAY, fill_end)
        entity_ids = list(self.config.watched_entities)
        flame = self.config.signals.get(Signal.FLAME)
        while windows and flame is not None and not self._stopped:
            chunk, windows = windows[-7:], windows[:-7]
            missing = [
                window
                for window in chunk
                if (kept := self.daily.get(window[0])) is None or kept.settings != self.settings_key
            ]
            if not missing:
                continue
            start, end = chunk[0][0], chunk[-1][1]

            def read(start: float = start, end: float = end, days: Any = missing) -> Any:
                states = significant_states(
                    self.hass,
                    dt_util.utc_from_timestamp(start),
                    end_time=dt_util.utc_from_timestamp(end),
                    entity_ids=entity_ids,
                    include_start_time_state=True,
                    significant_changes_only=False,
                    minimal_response=False,
                    no_attributes=False,
                )
                if not states.get(flame):
                    return None  # the recorder reaches no further back
                history = self._empty_history()
                for entity_id, rows in states.items():
                    for state in rows:
                        if isinstance(state, State):
                            self._record(entity_id, state, state.last_updated.timestamp(), history)
                return [
                    summarize_day(
                        history,
                        self.parameters,
                        a,
                        b,
                        self.config.monitor.monitor,
                        self.settings_key,
                    )
                    for a, b in days
                ]

            try:
                summaries = await recorder.async_add_executor_job(read)
            except Exception:  # the history is a convenience; never fail over it
                _LOGGER.warning("Could not read older days from the recorder", exc_info=True)
                return
            if summaries is None:
                return
            self._keep_days([day for day in summaries if day.has_data], now)

    async def _async_backfill(self, now: float) -> None:
        """Rebuild the rolling history from the recorder, when it is loaded: read and turned
        into samples in the recorder's executor, then put before the samples recorded live
        since setup."""
        if "recorder" not in self.hass.config.components:
            return
        try:
            recorder, significant_states = _recorder(self.hass), _significant_states()
        except ImportError:
            return
        start = dt_util.utc_from_timestamp(now - HISTORY_DAYS * DAY)
        entity_ids = list(self.config.watched_entities)

        def read() -> History:
            states = significant_states(
                self.hass,
                start,
                end_time=None,
                entity_ids=entity_ids,
                include_start_time_state=True,
                significant_changes_only=False,  # every change, as the live history keeps
                minimal_response=False,
                no_attributes=False,  # zones need their attributes
            )
            history = self._empty_history()
            for entity_id, rows in states.items():
                for state in rows:
                    if isinstance(state, State):
                        self._record(entity_id, state, state.last_updated.timestamp(), history)
            return history

        try:
            older = await recorder.async_add_executor_job(read)
        except Exception:  # the history is a convenience; never fail over it
            _LOGGER.warning("Could not read the recorder history", exc_info=True)
            return
        self.history.prepend(older)

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        moment = state.last_updated.timestamp() if state is not None else event.time_fired
        if isinstance(moment, datetime):
            moment = moment.timestamp()
        self._record(event.data["entity_id"], state, float(moment))
        self.config_entry.async_create_task(self.hass, self.async_request_refresh())

    def _empty_history(self) -> History:
        return History(
            signals={signal: Series() for signal in self.config.signals},
            zones={zone: ZoneSeries(zone) for zone in self.config.zone_entities},
        )

    def _record(
        self, entity_id: str, state: State | None, t: float, history: History | None = None
    ) -> None:
        """A state into the history (the live one, or one being rebuilt off the event loop:
        nothing here writes to Home Assistant)."""
        history = self.history if history is None else history
        signal = self.transport.signal_of(entity_id)
        if signal is not None:
            _append(history.signals[signal], t, reading_from_state(signal, state).value)
        if entity_id in history.zones:
            zone = self.link.zone_from_state(entity_id, state)
            series = history.zones[entity_id]
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
            _append(history.weather, t, weather_from_state(state).value)
        if entity_id == self.config.setpoint_read_back:
            # Read as the CH setpoint signal would be: the evidence's setpoint under control.
            value = reading_from_state(Signal.CH_SETPOINT, state).value
            _append(history.setpoint_read_back, t, value)

    # --- quick path -----------------------------------------------------------------------

    async def _async_update_data(self) -> MonitorData:
        """The quick path. Any exception in it is logged once with its trace, and its end once;
        Home Assistant is told through ``UpdateFailed``, so the monitor's entities go unavailable
        while control's stay (P-02); and each refresh, failed or not, is counted for control."""
        now = dt_util.utcnow().timestamp()
        try:
            feature_manager.async_check(self.hass, self)
            data = self._compute(now)
        except Exception as err:
            self._job_failed(MONITOR_REFRESH)
            self._count_refresh(now, failed=True)
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="monitor_refresh_failed"
            ) from err
        self._count_refresh(now, failed=False)
        self._job_works(MONITOR_REFRESH)
        return data

    def _count_refresh(self, now: float, failed: bool) -> None:
        self._refreshes = follow_outage(self._refreshes, now, failed)
        if not failed:
            self.monitor_failed_since = None
        elif self.monitor_failed_since is None or self.monitor_failed_since > now:
            self.monitor_failed_since = now

    @property
    def monitor_failing(self) -> bool:
        """The monitor's last refresh failed: its data, alarms included, is stale."""
        return self.monitor_failed_since is not None

    def monitor_lost(self, now: float) -> bool:
        """The monitor counts as failed at ``now``: its failed refreshes cover five minutes within
        ten, until it has worked for a minute without a failure (V6, the user's answer I)."""
        self._refreshes = follow_outage(self._refreshes, now)
        return self._refreshes.lost

    @property
    def monitor_lost_from(self) -> float | None:
        """While the monitor counts as failed: its first failure in the window then."""
        return self._refreshes.lost_from

    @property
    def monitor_works_since(self) -> float | None:
        """The first refresh of the current run of good ones; ``None`` after a failure."""
        return self._refreshes.good_since

    def _max_age(self, signal: Signal) -> float | None:
        return self.config.freshness.get(signal)  # one rule: only a limit the user set

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
        dhw = self.dhw_now(snapshot)

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
                self._factors.get(zone.zone_id),
                zone,
                state,
                supply,
                circuit_return(circuit, return_temp),  # a mixed circuit's is not the boiler's
                now,
                dhw,
            )
            if factor.status is FactorStatus.COMPUTED:
                self.schedule_save(FACTOR_SAVE_DELAY_S)
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
        self._zones_unknown_since = every_zone_unknown_since(
            self._zones_unknown_since, list(zone_states.values()), now, ZONE_MAX_AGE_S
        )
        if self.control is None:
            # No control unit (monitor only, or one that only hands back): the monitor tells.
            due = issue_due(self._zones_unknown_since, now)
            self.report_no_zone_known("monitor" if due else None)
        alarms = dict(self._alarms)
        if self.analysis is not None:
            alarms.update(self.analysis.trends)
        wall = self._follow_wall_thermostat(snapshot, now)
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
            lowest_water=self.lowest_water,
            wall_thermostat=wall,
        )

    def _follow_wall_thermostat(self, snapshot: BoilerSnapshot, now: float) -> WallFallback | None:
        """The wall thermostat on a gateway with an OpenTherm thermostat: what it keeps after a
        hand-back, from the optional signal; its repair issue once low or unknown for 30
        minutes, whether control is on or off — after a hand-back it heats the house anyway.
        ``None`` (and no issue) without such a thermostat."""
        if not wall_thermostat_applies(self.config.control):
            self._wall_since = None
            self._report_wall(None)
            return None
        fallback = wall_thermostat_fallback(
            snapshot.is_mapped(Signal.ROOM_SETPOINT),
            snapshot.number(Signal.ROOM_SETPOINT, self._max_age(Signal.ROOM_SETPOINT)),
        )
        self._wall_since = wall_warning_since(self._wall_since, fallback, now)
        self._report_wall(fallback if wall_issue_due(self._wall_since, now) else None)
        return fallback

    def _report_wall(self, fallback: WallFallback | None) -> None:
        """The wall thermostat's repair issue for ``fallback`` (low or unknown); ``None``
        deletes it. Raised anew when its kind changes."""
        wanted: tuple[str, dict[str, str]] | None = None
        if fallback is not None and fallback.warning is WallWarning.UNKNOWN:
            wanted = (f"{WALL_ISSUE}_unknown", {})
        elif (
            fallback is not None
            and fallback.warning is WallWarning.LOW
            and fallback.setpoint is not None
        ):
            wanted = (WALL_ISSUE, {"value": f"{fallback.setpoint:.1f}"})
        self._wall_issue = self._set_issue(WALL_ISSUE, self._wall_issue, wanted)

    def _set_issue(
        self,
        key: str,
        raised: tuple[str, dict[str, str]] | None,
        wanted: tuple[str, dict[str, str]] | None,
    ) -> tuple[str, dict[str, str]] | None:
        """A warning repair issue (not fixable) under ``key``: ``wanted`` — its translation
        key and placeholders — or deleted with ``None``; written only when it changes, and
        raised anew (deleted first) when its translation key does."""
        if wanted == raised:
            return raised
        issue_id = f"{key}_{self.config_entry.entry_id}"
        if wanted is None or (raised is not None and raised[0] != wanted[0]):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        if wanted is not None:
            translation_key, placeholders = wanted
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=translation_key,
                translation_placeholders=placeholders,
            )
        return wanted

    def dhw_now(self, snapshot: BoilerSnapshot) -> bool | None:
        """DHW running now: its own signal, else flame on without heating demand from the CH
        signal; otherwise unknown. Each flag is read by its own age limit, for the monitor and
        control alike (one freshness rule, X2): a stale one is unknown."""
        if not self.config.monitor.monitor.has_dhw:
            return False  # declared: the boiler heats no hot water
        dhw = snapshot.flag(Signal.DHW_ACTIVE, self._max_age(Signal.DHW_ACTIVE))
        if dhw is not None:
            return dhw
        flame = snapshot.flag(Signal.FLAME, self._max_age(Signal.FLAME))
        ch = snapshot.flag(Signal.CH_ACTIVE, self._max_age(Signal.CH_ACTIVE))
        if flame is True and ch is False:
            return True
        return None

    def _current_alarms(
        self, snapshot: BoilerSnapshot, now: float, zones: list[ZoneState]
    ) -> dict[AlarmKind, Alarm]:
        alarms: dict[AlarmKind, Alarm] = {}
        limits = self.config.monitor.alarms
        pressure = snapshot.number(Signal.PRESSURE, self._max_age(Signal.PRESSURE))
        if snapshot.is_mapped(Signal.PRESSURE):
            for kind, band in (
                (AlarmKind.PRESSURE_LOW, limits.pressure_low),
                (AlarmKind.PRESSURE_HIGH, limits.pressure_high),
            ):
                alarms[kind] = banded_alarm(kind, pressure, band, self._alarms.get(kind))
        if snapshot.is_mapped(Signal.FLUE_GAS) and self.config.installation.boiler.condensing:
            flue = snapshot.number(Signal.FLUE_GAS, self._max_age(Signal.FLUE_GAS))
            kind = AlarmKind.FLUE_GAS_HIGH
            alarms[kind] = banded_alarm(kind, flue, limits.flue_gas, self._alarms.get(kind))
        # Heating burns only: a combi's short hot-water draws are no ignition problem, and a
        # burn of unknown kind is counted apart (P47).
        options = self.config.monitor.monitor
        inputs = dhw_inputs(self.history, self.parameters, now - DAY, now, options)
        flame = self.history.signal(Signal.FLAME)
        burns = [
            burn
            for burn in classify_burns(find_burns(flame, now - DAY, now), inputs)
            if burn.kind in CH_KINDS
        ]
        alarms[AlarmKind.FREQUENT_STARTS] = frequent_starts(burns, now, limits.starts_per_hour)
        alarms[AlarmKind.UNSTABLE_IGNITION] = unstable_ignition(
            burns,
            now,
            limit=limits.unstable_burns_per_day,
            demand=self.history.zone_calling(now - DAY, now),
        )
        too_hot = self._circuit_too_hot(snapshot, now)
        if too_hot is not None:
            alarms[AlarmKind.CIRCUIT_TOO_HOT] = too_hot
        if snapshot.is_mapped(Signal.PUMP_RUNNING) or snapshot.is_mapped(Signal.CH_ACTIVE):
            pump = snapshot.flag(Signal.PUMP_RUNNING)
            if pump is None:
                pump = snapshot.flag(Signal.CH_ACTIVE)
            alarms[AlarmKind.LOW_FLOW] = low_flow(
                zones,
                pump,
                now,
                ZONE_MAX_AGE_S,
                self._alarms.get(AlarmKind.LOW_FLOW),
                self.dhw_now(snapshot),
                self.config.installation.boiler.bypass,
            )
        return alarms

    def _circuit_too_hot(self, snapshot: BoilerSnapshot, now: float) -> Alarm | None:
        """Decision 10: a circuit's water above its alarm temperature for its time — information
        only, for circuits with a maximum; ``None`` without one. The flow is the circuit's own
        sensor where mapped, else the boiler's for an unmixed circuit, each by the flow's age
        limit; without it the alarm is inactive with its reason. With several such circuits, one
        in alarm is shown, else one that could be judged."""
        found: list[Alarm] = []
        boiler_flow = snapshot.number(Signal.FLOW, self._max_age(Signal.FLOW))
        for circuit in self.config.installation.circuits:
            if circuit.max_flow_alarm is None or circuit.max_flow_alarm_s is None:
                continue
            entity = self.config.circuit_flow_entities.get(circuit.circuit_id)
            own: float | None = None
            if entity is not None:
                reading = read_temperature(self.hass, entity)
                value = reading.value
                if reading.is_fresh(now, self._max_age(Signal.FLOW)) and isinstance(value, float):
                    own = value
            flow, reason = circuit_flow(circuit, boiler_flow, own, own_mapped=entity is not None)
            alarm = circuit_too_hot(
                flow,
                circuit.max_flow_alarm,
                circuit.max_flow_alarm_s,
                now,
                self._circuit_alarms.get(circuit.circuit_id),
                reason,
            )
            self._circuit_alarms[circuit.circuit_id] = alarm
            found.append(alarm)
        if not found:
            return None
        active = [alarm for alarm in found if alarm.active]
        judged = [alarm for alarm in found if alarm.reason is None]
        return (active or judged or found)[0]

    # --- analysis -------------------------------------------------------------------------

    async def _async_analysis_tick(self, _now: datetime) -> None:
        self.check_learning()
        await self.async_run_analysis()

    def check_learning(self) -> None:
        """Warn about zone learning the plugin affects but cannot protect, each warning with
        what its advice costs: Auto-TPI that cannot learn — flagged as used by VT's central
        boiler while that feature is off, which is how the plugin replaces it (research F2) —
        and, while control runs with learning pauses, learning it cannot pause: Auto-TPI (only a
        reset would pause it) and SmartPI without its learning flag. VT's central boiler unknown
        says nothing about Auto-TPI's learning in the zones VT's central boiler uses: the first
        issue is left as it is, and those zones are in neither (P-54)."""
        central = self.link.vt_central_boiler_configured()
        control = self.config.control
        pauses = control.configured and control.learning_pauses
        blocked: list[str] = []
        unpaused: list[str] = []
        for zone_id in self.config.zone_entities:
            algorithm = self.link.zone_algorithm(zone_id)
            flagless_smartpi = (
                algorithm.proportional_function == "smartpi" and algorithm.smartpi_learning is None
            )
            depends = algorithm.auto_tpi and algorithm.used_by_central_boiler
            if depends and central is None:
                continue  # whether it learns is not known either way
            if depends and central is False:
                blocked.append(self.link.zone_name(zone_id))
            elif pauses and (algorithm.auto_tpi or flagless_smartpi):
                unpaused.append(self.link.zone_name(zone_id))
        if central is not None:
            self._issue("auto_tpi_blocked", blocked)
        self._issue("learning_not_paused", unpaused)

    def report_no_zone_known(self, kind: str | None) -> None:
        """Decision 3's repair issue: ``kind`` — "off", "handed_back" or "monitor" — while every
        configured zone has been unknown for ten minutes; ``None`` deletes it. An error where
        heating stops, else a warning (provisional, K4). Raised anew when its kind changes."""
        if kind == self._no_zone_issue:
            return
        issue_id = f"{NO_ZONE_KNOWN_ISSUE}_{self.config_entry.entry_id}"
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._no_zone_issue = kind
        if kind is None:
            return
        _LOGGER.warning(
            "No Versatile Thermostat zone has answered for ten minutes (%s)",
            {"off": "heating is off", "handed_back": "the boiler is handed back"}.get(
                kind, "the monitor cannot judge them"
            ),
        )
        zones = ", ".join(self.link.zone_name(zone) for zone in self.config.zone_entities)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if kind == "off" else ir.IssueSeverity.WARNING,
            translation_key=f"{NO_ZONE_KNOWN_ISSUE}_{kind}",
            translation_placeholders={"zones": zones},
        )

    def _issue(self, key: str, zones: list[str]) -> None:
        issue_id = f"{key}_{self.config_entry.entry_id}"
        if zones:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders={"zones": ", ".join(zones)},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

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
            analysis = await self.hass.async_add_executor_job(
                analyse,
                copy,
                self.parameters,
                self.config.monitor.monitor,
                now,
                days,
                tuple(self.daily.values()),
                self.settings_key,
            )
            if self._stopped:
                return  # a reload came meanwhile: the new installation analyses for itself
            self.analysis = analysis
            if self._history_back:
                self._keep_days(analysis.new_days, now)
            fit = self.analysis.fit
            if fit is not None:
                fitted = [(ParameterKey.LOSS_COEFFICIENT, fit.loss)]
                if fit.threshold is not None:
                    fitted.append((ParameterKey.HEATING_THRESHOLD, fit.threshold))
                moved = False
                for key, estimate in fitted:
                    moved |= _moved(self.parameters.get(key).estimate(Source.MEASURED), estimate)
                    self.parameters = self.parameters.with_estimate(key, estimate)
                if moved:  # a fit that has not moved is not written again every five minutes
                    self.schedule_save()
            await self._async_suggest_lowest_water(copy, now)
            # Published as of now, not as of the analysis' start: the quick path may have
            # moved on meanwhile (a reading gone stale), and must not be set back. Through the
            # refresh itself, so a failure of it is counted and logged there, once (V6).
            await self.async_refresh()
        except Exception:  # the monitor keeps its last results; the next run tries again
            self._job_failed("The periodic analysis")
        else:
            self._job_works("The periodic analysis")
        finally:
            self._analysing = False

    async def _async_suggest_lowest_water(self, history: History, now: float) -> None:
        """X6 (decision 2): the lowest water temperature's evidence over the history, with the
        estimate from the boiler's minimum power beside it; shown, and told by a repair issue
        while it suggests a value — never applied, nothing written. A failure keeps the last
        result and never holds up the analysis."""
        try:
            source, context = self._lowest_water_context()
            suggestion = await self.hass.async_add_executor_job(
                suggest_lowest_water,
                history,
                source,
                now,
                self.parameters,
                self.config.monitor.monitor,
                context,
            )
        except Exception:
            self._job_failed("The lowest water temperature's evidence")
            return
        self._job_works("The lowest water temperature's evidence")
        if self._stopped:
            return
        self.lowest_water = suggestion
        self._report_lowest_water(suggestion)

    def _lowest_water_context(self) -> tuple[SetpointSource | None, SuggestionContext]:
        """Who sets the water now and what the evidence is judged against: under control the
        lowest water temperature set, with the CH setpoint signal or, without it, the control's
        read-back as the source; otherwise the boiler's own curve or its thermostat, with the
        CH setpoint signal only. The caps known, and whether nothing heats (a stand-alone
        gateway handed back)."""
        config = self.config
        control = config.control
        unit = self.control
        plugin = unit is not None and not unit.hand_back_only and unit.controlling
        if Signal.CH_SETPOINT in config.signals:
            source: SetpointSource | None = SetpointSource.CH_SETPOINT
        elif plugin and config.setpoint_read_back:
            source = SetpointSource.READ_BACK
        else:
            source = None
        limits = control.loop.control
        caps = [circuit.max_flow for circuit in config.installation.circuits if circuit.max_flow]
        if control.configured:
            caps.append(limits.limits.hard_max)
        boiler_max = self.parameters.value(ParameterKey.MAX_CH_SETPOINT)
        if boiler_max is not None:
            caps.append(boiler_max)
        curve = limits.curve if control.configured and control.curve_entered else None
        estimate = estimate_from_power(
            entered_min_power(self.parameters),
            None if curve is None else design_load_kw(self.parameters, curve),
            curve,
            condensing=config.installation.boiler.condensing,
        )
        context = SuggestionContext(
            set_by=WaterSetBy.PLUGIN if plugin else WaterSetBy.DEVICE,
            lowest=limits.limits.hard_min if plugin else None,
            caps=tuple(float(cap) for cap in caps if cap is not None),
            nothing_heats=control.topology is Topology.GATEWAY_STANDALONE and not plugin,
            estimate=estimate,
        )
        return source, context

    def _report_lowest_water(self, suggestion: LowestWaterSuggestion) -> None:
        """The suggestion's repair issue while it suggests a value: worded for the plugin's
        option where the plugin sets the water, else for the device that sets it."""
        wanted: tuple[str, dict[str, str]] | None = None
        value, reference = suggestion.value, suggestion.reference
        if (
            suggestion.state is SuggestionState.SUGGESTION
            and value is not None
            and reference is not None
        ):
            key = LOWEST_WATER_ISSUE
            if suggestion.set_by is WaterSetBy.DEVICE:
                key = f"{LOWEST_WATER_ISSUE}_boiler"
            wanted = (
                key,
                {
                    "days": str(suggestion.window_days),
                    "short": str(suggestion.short),
                    "burns": str(suggestion.counted),
                    "reference": f"{reference:.1f}",
                    "limit": f"{suggestion.short_burn_s / 60.0:g}",
                    "value": f"{value:.1f}",
                },
            )
        self._lowest_water_issue = self._set_issue(
            LOWEST_WATER_ISSUE, self._lowest_water_issue, wanted
        )

    async def _async_forecast_tick(self, _now: datetime | None) -> None:
        if self.forecasts is None:
            return
        try:
            await self.forecasts.async_take(dt_util.utcnow().timestamp())
        except Exception:  # a missed snapshot only thins the forecast record
            self._job_failed("Taking a forecast snapshot")
        else:
            self._job_works("Taking a forecast snapshot")

    def _job_failed(self, job: str) -> None:
        if job in self._failing:
            _LOGGER.debug("%s failed again", job, exc_info=True)
        else:
            _LOGGER.exception("%s failed; tried again at its next run", job)
            self._failing.add(job)

    def _job_works(self, job: str) -> None:
        if job in self._failing:
            _LOGGER.info("%s works again", job)
            self._failing.discard(job)


def main_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """The entry's store: the monitor's data and a copy of the control state. Written atomically:
    a crash while writing leaves the old file whole."""
    return Store(hass, STORAGE_VERSION, main_store_key(entry_id), atomic_writes=True)


def control_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """The control state alone, written at once and atomically on every change."""
    return Store(hass, CONTROL_STORE_VERSION, control_store_key(entry_id), atomic_writes=True)


@dataclass(frozen=True, slots=True)
class ControlRead:
    """The control state as read, with the cautious answer to whether a hand-back is owed."""

    state: dict[str, Any]
    readable: bool  # read from the control store, or from a 0.2.1 entry store
    owed: bool
    main: object  # the entry's store as loaded: None when missing or unreadable
    rewrite: bool  # not from the control store: it (and the marker) are to be written


async def _async_try_load(store: Store[dict[str, Any]]) -> object:
    try:
        return await store.async_load()
    except Exception:  # an unsupported version, a read error: it cannot be read
        _LOGGER.exception("Could not read the stored data of %s", store.key)
        return None


async def async_read_control_state(
    hass: HomeAssistant,
    entry_id: str,
    options: Any,
    *,
    main: Store[dict[str, Any]] | None = None,
    control: Store[dict[str, Any]] | None = None,
) -> ControlRead:
    """The control state of an entry, for setup, the options flow, removal, the repair release
    and a report of unreadable options alike:
    - the control store, when it holds a mapping;
    - otherwise, from an entry store without the marker (0.2.1's, or one 0.2.2 never saved),
      its ``control`` copy, or nothing owed without one. Such a store next to a control store
      was written by 0.2.1 after a downgrade: its copy is the newer one, and a hand-back either
      of them owes stays owed;
    - otherwise it cannot be read (missing, damaged, of another shape — Home Assistant renames a
      damaged file and returns nothing, as it does for a new entry). A hand-back is then owed
      when the options hold a control section or the entry store's copy owes one, and the state
      is that copy with the boiler held; otherwise nothing is owed.
    """
    main = main_store(hass, entry_id) if main is None else main
    control = control_store(hass, entry_id) if control is None else control
    raw_control = await _async_try_load(control)
    raw_main = await _async_try_load(main)
    main_data = raw_main if isinstance(raw_main, dict) else None
    copy = main_data.get("control") if main_data is not None else None
    from_0_2_1 = main_data is not None and CONTROL_STORE_MARKER not in main_data
    if isinstance(raw_control, dict):
        if not (from_0_2_1 and isinstance(copy, dict)):
            return ControlRead(raw_control, True, owes_hand_back(raw_control), raw_main, False)
        _LOGGER.warning("The stored data was written by an earlier version; its copy is taken")
        state = dict(copy)
        if owes_hand_back(raw_control):
            state = assumed_owed_state(state)
        return ControlRead(state, True, owes_hand_back(state), raw_main, True)
    if from_0_2_1 and (copy is None or isinstance(copy, dict)):
        state = dict(copy or {})
        return ControlRead(state, True, owes_hand_back(state), raw_main, True)
    if raw_control is not None:
        _LOGGER.warning("Ignoring stored control data that is not a mapping")
    if control_state_owed(copy, readable=False, has_control_section=has_control_section(options)):
        _LOGGER.error(
            "The stored control state cannot be read (missing or damaged); taken as holding the "
            "boiler: it is handed back first"
        )
        return ControlRead(assumed_owed_state(copy), False, True, raw_main, True)
    _LOGGER.warning(
        "No stored control state could be read; control is not configured, so nothing is owed"
    )
    return ControlRead({}, False, False, raw_main, True)


def _owed_flags(control: object) -> tuple[bool, bool] | None:
    if not isinstance(control, dict):
        return None
    return stored_flag(control.get("controlling")), stored_flag(control.get("hand_back_pending"))


def _mapping(value: object) -> dict[str, Any]:
    """Stored data as the mapping it should be: whatever the file holds, whatever its type
    says; nothing stored, or anything else, is empty."""
    if value is not None and not isinstance(value, dict):
        _LOGGER.warning("Ignoring stored data that is not a mapping")
    return value if isinstance(value, dict) else {}


def _append(series: Series[Any], t: float, value: object) -> None:
    last = series.last
    series.append(max(t, last.t) if last is not None else t, value)


FIT_MOVED = 0.01  # a relative change in a fitted value worth saving
FIT_CONFIDENCE_MOVED = 0.02


def _moved(before: Estimate | None, after: Estimate) -> bool:
    """Whether a measured value moved enough to be saved again."""
    if before is None:
        return True
    return (
        abs(after.value - before.value) > FIT_MOVED * max(abs(before.value), 1e-9)
        or abs(after.confidence - before.confidence) > FIT_CONFIDENCE_MOVED
    )


def summary_settings(config: EntryConfig) -> dict[str, Any]:
    """What shapes a day's summary: the monitor's options, the parameters as the user entered
    them, the entities feeding the signals, the weather entity and the zones."""
    options = config.monitor.monitor
    return {
        "options": {
            "condensing_return": options.condensing_return,
            "short_burn_s": options.short_burn_s,
            "modulation_scale": options.modulation_scale.value,
            "has_dhw": options.has_dhw,
            "setpoint_margin": options.setpoint_margin,
        },
        "parameters": {key.value: config.parameters.value(key) for key in ParameterKey},
        "signals": {signal.value: entity for signal, entity in config.signals.items()},
        "weather": config.weather,
        "zones": sorted(config.zone_entities),
    }


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


def _recorder(hass: HomeAssistant) -> Any:
    from homeassistant.helpers.recorder import get_instance

    return get_instance(hass)


def _significant_states() -> Any:
    from homeassistant.components.recorder import history as recorder_history

    return recorder_history.get_significant_states


def _optional_float(raw: Any) -> float | None:
    return None if raw is None else float(raw)
