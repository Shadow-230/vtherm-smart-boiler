"""The coordinator: follows the mapped entities, keeps a rolling history and computes what the
plugin's entities publish.

Two paths. The quick one runs on state changes (debounced) and every 30 s: current readings,
signal check, hot water, emitter factors, foreign heat, reference room, critical zones, current
alarms. The analysis runs every few minutes on a copy of the history, off the event loop:
summaries, verdict, trend warnings, report, outdoor check and building fit. After a restart the
history is rebuilt from the recorder, which keeps these states anyway; the entry's own store
holds only small things: the monitoring start, held emitter factors, measured parameters and when
the user reset one, the day summaries, a copy of when the plugin was down and a copy of the
control state (P-116). A small store of its own, the last-run record, keeps when the plugin last
ran — written every ten minutes and at a clean stop, so the entry's store is written only when
its own data changes: the time the plugin was down — a stop, a crash, a reload — is unknown in
what is read back (P-95). The control state goes into the history as well, live from the
control unit and back from the recorder's copy of its sensor, so each day knows its time under
control (P-96).

With the analysis it judges the lowest water temperature's evidence and shows a suggestion,
never applied (X6, decision 2); the quick path shows what the wall thermostat on a gateway keeps
after a hand-back. Each has its repair issue, raised here.

The building model's measured values — the heat loss and the heating threshold — feed the
monitor only; control never reads them (review question 11). Each can be reset by the user: the
measured value is forgotten and fitted again from the days that start after the reset only,
without touching the options — no reload, no hand-back (P-90). The installation's warnings (a
circuit without zones, underfloor heating on an unmixed circuit without a maximum) are shown as
repair issues (P-94).

Every feature is checked by what the configuration gives — which entities are created — by that
and the zones' valves as they report — which of them are available — and by what is known now,
which the "Features" sensor shows, each feature available, degraded or inactive with what it
lacks (the missing-data rule, Y4).

Y1's notifications are raised here too, control or not: "add water" below the threshold the user
took from the boiler's manual, high pressure and hot flue gas at their alarm level held five
minutes, the pressure trend's "risk of a leak", and the boiler's own fault — repair issues, each
saying what to do, closing after an hour of known readings in the normal range (the fault's when
it clears). An alarm that cannot judge holds its state for an hour, then shows unknown (S-16).

The control state — whether the boiler may hold a value of ours, an owed hand-back, latches —
lives in a store of its own, written at once and atomically; the entry's store keeps a copy.
One function reads it for every place that asks (``async_read_control_state``): a state that
cannot be read counts as "the plugin held the boiler" wherever control is configured. Home
Assistant's store logs a write that fails and goes on; the control store notes each write's
outcome, so a failed one is known (``control_store_failing``, ``control_store_failures``) and
control does not take the boiler until the store has written for a while without one (PB-16).
"""

from __future__ import annotations

import copy
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import feature_manager
from .config import EntryConfig
from .const import (
    ALIVE_STORE_VERSION,
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
    alive_store_key,
    assumed_owed_state,
    control_state_owed,
    control_store_key,
    has_control_section,
    main_store_key,
    owes_hand_back,
    stored_flag,
)
from .control_config import Topology, WritePath, wall_thermostat_applies
from .core.alarms import (
    HELD,
    Alarm,
    AlarmKind,
    Level,
    Notice,
    banded_alarm,
    circuit_flow,
    circuit_too_hot,
    fault_counts,
    fault_holds,
    follow_fault,
    follow_notice,
    frequent_starts,
    low_flow,
    pressure_alarms,
    unstable_ignition,
)
from .core.analysis import Analysis, analyse
from .core.controller import OutageWindow, follow_outage
from .core.critical_zone import CriticalZone, critical_zone
from .core.daily import (
    DAY_MARGIN_S,
    KEEP_DAYS,
    DaySummary,
    keep_known_control,
    settings_key,
    summarize_day,
)
from .core.emitters import FactorResult, FactorStatus, update_factor
from .core.foreign_heat import ForeignHeatState, update_foreign_heat
from .core.history import History, ZoneSeries, with_downtime
from .core.hot_water import HotWater, hot_water_available
from .core.installation import IssueCode, Severity
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
from .core.parameters import Estimate, ParameterKey, ParameterSet, Source
from .core.readings import BoilerSnapshot, ZoneState
from .core.reference_room import ReferenceRoom, select_reference
from .core.series import Series, known_duration
from .core.signal_check import (
    FAULT_SIGNALS,
    ControlKind,
    Feature,
    FeatureState,
    SignalHealth,
    SignalStatus,
    check_signals,
    features,
    link_connected,
)
from .core.signals import Signal
from .core.supply import circuit_return, circuit_supply
from .core.zone_watch import every_zone_unknown_since, issue_due
from .forecasts import ForecastRecorder
from .transport.entities import (
    EntityTransport,
    gateway_signals,
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
HOUR = 3600.0
DAY = 86400.0
# Decision 3: every configured zone unknown for ten minutes — a repair issue in every mode, the
# monitor only included; its text follows what control does then (translation keys
# ``no_zone_known_off``, ``_handed_back``, ``_monitor``).
NO_ZONE_KNOWN_ISSUE = "no_zone_known"
NO_CRITERION_ISSUE = "no_criterion_judged"  # its text where the zones are known (PB-03)
# X6: the wall thermostat on a gateway would keep the house cool after a hand-back (``_unknown``:
# it reports no setpoint); the lowest water temperature's suggestion (``_boiler``: worded for the
# device that sets the water). Warnings, not fixable.
WALL_ISSUE = "wall_thermostat_fallback"
LOWEST_WATER_ISSUE = "lowest_water_suggestion"
ZONE_MAX_AGE_S: float | None = None  # one freshness rule: a steady room is not a stale one
# Y1's notifications: repair issues the plugin raises itself — warnings, not fixable
# (provisional, K4) — one per cause per entry, each saying what to do. They stay through a reload;
# the entry's removal takes them.
ADD_WATER_ISSUE = "add_water"
PRESSURE_HIGH_ISSUE = "pressure_high"
FLUE_GAS_HIGH_ISSUE = "flue_gas_high"
PRESSURE_FALLING_ISSUE = "pressure_falling"
BOILER_FAULT_ISSUE = "boiler_fault"
NOTICE_ISSUES = (
    ADD_WATER_ISSUE,
    PRESSURE_HIGH_ISSUE,
    FLUE_GAS_HIGH_ISSUE,
    PRESSURE_FALLING_ISSUE,
    BOILER_FAULT_ISSUE,
)
# "Add water" closes once the pressure has stayed this far above the threshold (Y1).
ADD_WATER_CLEAR_BAR = 0.1
# What a notification says when it is raised without a reading (none known).
_NOTICE_DEFAULTS: dict[str, dict[str, str]] = {
    ADD_WATER_ISSUE: {"value": "-", "threshold": "-"},
    PRESSURE_HIGH_ISSUE: {"value": "-", "limit": "-"},
    FLUE_GAS_HIGH_ISSUE: {"value": "-", "limit": "-"},
    PRESSURE_FALLING_ISSUE: {"change": "-"},
    BOILER_FAULT_ISSUE: {"entity": "-"},
}
SAVE_DELAY_S = 120
# P-94: the installation's warnings, each a warning repair issue ``installation_<code>_<entry>``
# naming the circuits concerned, raised at every setup while the options hold it.
INSTALLATION_ISSUE = "installation"
INSTALLATION_WARNINGS = (IssueCode.EMPTY_CIRCUIT, IssueCode.UNDERFLOOR_WITHOUT_MAX_FLOW)
# P-90: the measured values the user can reset, each fitted again from later days only.
RESETTABLE = (ParameterKey.LOSS_COEFFICIENT, ParameterKey.HEATING_THRESHOLD)
# P-80: the starts and ignition alarms count the burns the analysis classified; an analysis
# older than this (three missed runs) has stopped, and its burns judge nothing (provisional,
# K4): the alarms hold their state for an hour, then show unknown (S-16).
ANALYSIS_BURNS_MAX_AGE_S = 3 * SUMMARY_SECONDS
# P-95 (A11): the last-run record says when the plugin was last known to run (``alive_at``),
# written this often (provisional, K4) and at a clean stop — to a small store of its own, not the
# entry's store with a year of days in it (SD cards, eMMC). After a crash the downtime starts at
# its last write. Downtimes are kept as long as the rolling history.
ALIVE_SAVE_S = 10 * 60
UNAVAILABLE_STATES = ("unavailable", "unknown")


# P-101: the entry of this integration, its runtime data typed.
type SmartBoilerConfigEntry = ConfigEntry[SmartBoilerCoordinator]


def _bar(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _degrees(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


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
    # Every mapped link signal fresh and, on the relay path, the relay within reach; ``None``
    # with no link signal mapped and no relay (X8, R4).
    connected: bool | None
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
    # Y4: ``features`` by what the configuration gives (the entities follow it); these by
    # what is known now — the "Features" sensor shows them.
    features_now: dict[Feature, FeatureState] = field(default_factory=dict)


class SmartBoilerCoordinator(DataUpdateCoordinator[MonitorData]):
    """One installation: its boiler, circuits and VT zones."""

    config_entry: SmartBoilerConfigEntry

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
        control = config.control
        # P-17, Q3.9: the signals the OpenTherm Gateway reports, from the registries, once.
        gateway = gateway_signals(
            hass,
            config.signals,
            None if control.write_path is None else control.write_path.value,
            control.confirmed_entity,
        )
        self.transport = EntityTransport(hass, config.signals, gateway)
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
        # P-90: where the user reset a measured value, the moment: it is fitted from the days
        # that start from then on only. Stored with the entry's data.
        self.fit_since: dict[ParameterKey, float] = {}
        self._store = main_store(hass, entry.entry_id)
        self._control_store = control_store(hass, entry.entry_id, self._control_written)
        # PB-16: the last write of the control store failed — its outcome is noted by the store
        # itself, Home Assistant's store only logging it — and how many have failed so far.
        # Control does not take the boiler meanwhile, nor for a while after each failure;
        # nothing written yet counts as no failure.
        self.control_store_failing = False
        self.control_store_failures = 0
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
        # Y1: since when each mapped fault signal has counted (the notification's own clock;
        # control keeps its own), the notifications' states, and what each open issue shows.
        self._fault_since: dict[Signal, float | None] = {}
        self._notices: dict[str, Notice] = {}
        self._notice_shown: dict[str, dict[str, str] | None] = {}
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
        # P-95 (A11): the ``[from, to)`` intervals the plugin was not running, kept as long as the
        # rolling history: unknown time in what is read back from the recorder. The last-run
        # record keeps them, with the moment the plugin last ran; the entry's store a copy.
        self.down: list[tuple[float, float]] = []
        self._alive_store = alive_store(hass, entry.entry_id)
        # P-96: the plugin's own control-state sensor, as the registry names it; its recorded
        # states tell the days under control.
        self._control_entity: str | None = None
        self._stopped = False
        # The entities the platforms create now (disabled ones too): the rest are stale.
        self.expected_unique_ids: set[str] = set()
        # The platforms that set themselves up for this run: only they say what is stale (PB-07).
        self.platforms_set_up: set[str] = set()
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
        self._no_zone_issue: tuple[str, tuple[str, ...]] | None = None
        # X6: the suggestion the last analysis gave; the wall thermostat's warning since, and
        # the issues raised now (their translation key and placeholders).
        self.lowest_water: LowestWaterSuggestion | None = None
        self._wall_since: float | None = None
        self._wall_issue: tuple[str, dict[str, str]] | None = None
        self._lowest_water_issue: tuple[str, dict[str, str]] | None = None
        # P-39: the integration's entity texts in Home Assistant's language, loaded once at
        # setup (English where the language has none): what the coded lists are shown with.
        self.texts: dict[str, str] = {}

    async def async_load_texts(self) -> None:
        """The entity texts in Home Assistant's language, once (P-39). Without them the codes
        stand for themselves."""
        from homeassistant.helpers.translation import async_get_translations

        try:
            self.texts = await async_get_translations(
                self.hass, self.hass.config.language, "entity", {DOMAIN}
            )
        except Exception:  # the texts are an extra: the codes are shown instead
            _LOGGER.exception("Could not load the entity texts; the codes are shown instead")
            self.texts = {}

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
        self.link.watch_vt_central()  # first: a change to VT made unwatched latches (decision 9)
        await self.link.async_detect()
        self._restore_notices()
        self.report_installation()
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
        if self.control is not None:
            # P-96: the time under control, as the unit shows it on its control-state sensor —
            # from the unit itself, so a first setup (the sensor not yet in the registry) or a
            # disabled sensor does not lose it; the recorder's copy fills what came before.
            self._record_control_state()
            self._unsubs.append(self.control.async_add_listener(self._record_control_state))
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
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._async_alive_tick, timedelta(seconds=ALIVE_SAVE_S)
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
        self.link.stop_watching_vt_central()
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
            # A clean stop: the downtime from here on (P-95).
            await self._async_save_alive()
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
        self.down = _downtimes(
            await _async_try_load(self._alive_store), read.main, now, _created_at(entry)
        )
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
        self.fit_since = _fit_since(stored.get("fit_since"), now)
        self._loaded = True
        if read.rewrite:
            # Moved from a 0.2.1 store, or taken cautiously after a loss: written at once, so
            # the next start reads it from the control store.
            await self._control_store.async_save(self._stored_control())
            await self._store.async_save(self._stored_data())

    def _monitoring_start(self, stored: dict[str, Any], now: float) -> float:
        """The entry's creation; for an entry without one (migrated from Home Assistant's old
        storage, epoch 0), the stored start, else now."""
        at = _created_at(self.config_entry)
        if at is not None:
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
            # A copy of the downtimes (P-95), written only with this store's own saves: what is
            # left of them should the last-run record be lost.
            "down": [[since, until] for since, until in self.down],
            "factors": {
                zone: {"value": f.value, "at": f.at, "output_w": f.output_w}
                for zone, f in self._factors.items()
                if f.value is not None
            },
            "measured": measured,
            "fit_since": {key.value: at for key, at in self.fit_since.items()},
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

    async def async_save_control_now(self) -> bool:
        """Write the control state at once: for what a crash must not lose (the controlling
        marker, a latch). The entry store's copy is written at once too when the boiler's hold
        or an owed hand-back changed, otherwise with the delayed save. Whether the control
        state may be taken as stored: ``False`` once a write of it failed and none has worked
        since (PB-16) — before the stores were read, or once stopped, nothing is written and
        nothing failed."""
        if not self._loaded or self._stopped:
            return True
        try:
            await self._control_store.async_save(self._stored_control())
        except Exception:  # an error the store does not log itself: it failed all the same
            _LOGGER.exception("Could not write the control state")
            self._control_written(False)
        if _owed_flags(self._stored_control()) != self._main_owed:
            await self.async_save_now()
        else:
            self.schedule_save()
        return not self.control_store_failing

    def _control_written(self, ok: bool) -> None:
        """The outcome of a write of the control store (PB-16), each failure counted; told
        once when it changes."""
        if not ok:
            self.control_store_failures += 1
        if not ok and not self.control_store_failing:
            _LOGGER.error(
                "The control state could not be written (the log above has why): control does "
                "not take the boiler until it has written for a while again, and a hand-back "
                "already owed is still made"
            )
        elif ok and self.control_store_failing:
            _LOGGER.info("The control state can be written again")
        self.control_store_failing = not ok

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
        """Keep newly summarised days, over one summarised with other settings (keeping the
        time under control that one found, P-96); drop those older than a year."""
        added = [
            keep_known_control(day, kept)
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

    def expect_entities(self, platform: str, entities: list[Any]) -> None:
        """A platform's entities for this run — none where it creates none."""
        self.platforms_set_up.add(platform)
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
        entity_ids = self._recorded_entities()
        down = list(self.down)
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
            # Twelve hours on each side: a burn across a midnight of the chunk is whole (P-83).
            start, end = chunk[0][0] - DAY_MARGIN_S, chunk[-1][1] + DAY_MARGIN_S

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
                history = self._rebuild(states, start, end, down)
                return [
                    summarize_day(
                        history,
                        self.parameters,
                        a,
                        b,
                        self.config.monitor.monitor,
                        self.settings_key,
                        known_until=end,
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
        entity_ids = self._recorded_entities()
        down = list(self.down)

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
            # The downtime is marked up to now: the samples recorded live since setup follow.
            return self._rebuild(states, start.timestamp(), math.inf, down)

        try:
            older = await recorder.async_add_executor_job(read)
        except Exception:  # the history is a convenience; never fail over it
            _LOGGER.warning("Could not read the recorder history", exc_info=True)
            return
        self.history.prepend(older)

    def _recorded_entities(self) -> list[str]:
        """What is read back from the recorder: the watched entities and, where there is one,
        the plugin's own control-state sensor (P-96) — as the registry names it now, so a
        rename is followed. Called in the event loop."""
        entity_ids = list(self.config.watched_entities)
        self._control_entity = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.config_entry.entry_id}_control_state"
        )
        if self._control_entity is not None:
            entity_ids.append(self._control_entity)
        return entity_ids

    def _rebuild(
        self,
        states: dict[str, list[Any]],
        start: float,
        end: float,
        down: Sequence[tuple[float, float]],
    ) -> History:
        """Recorded states as a history, off the event loop (nothing here writes to Home
        Assistant): each entity's rows in time order, the plugin's downtime within
        ``[start, end)`` unknown (P-95)."""
        history = self._empty_history()
        for entity_id, rows in states.items():
            timed = [(row.last_updated.timestamp(), row) for row in rows if isinstance(row, State)]
            for t, state in with_downtime(timed, down, start, end):
                self._record(entity_id, state, t, history)
        return history

    @callback
    def _record_control_state(self) -> None:
        """P-96: the control unit's state now, into the live history."""
        if self.control is not None:
            mode = self.control.status.mode.value
            _append(self.history.control_state, dt_util.utcnow().timestamp(), mode)

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
            _append(history.signals[signal], t, self.transport.reading_of(signal, state).value)
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
        if entity_id == self._control_entity:
            # P-96: the control state as its sensor showed it; unavailable is unknown.
            shown = None if state is None or state.state in UNAVAILABLE_STATES else state.state
            _append(history.control_state, t, shown)

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

    def _relay_reachable(self) -> bool | None:
        """On the relay path: whether the relay shows a state (R4, R6); ``None`` without one."""
        control = self.config.control
        relay = control.relay.entity
        if control.write_path is not WritePath.RELAY or not relay:
            return None
        state = self.hass.states.get(relay)
        return state is not None and state.state not in ("unavailable", "unknown")

    def _max_age(self, signal: Signal) -> float | None:
        return self.config.freshness.get(signal)  # one rule: only a limit the user set

    def _compute(self, now: float) -> MonitorData:
        config = self.config
        snapshot = self.transport.snapshot(now)
        health = check_signals(snapshot, config.freshness)
        mapped = frozenset(config.signals)
        has_rates = self._has_rates()
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

        known_zones = [z for z in zone_states.values() if z.is_fresh(now, ZONE_MAX_AGE_S)]
        zone_valves = all(z.valve_open is not None for z in known_zones) if known_zones else None
        # The configuration's view — which entities exist — and what is known now (Y4).
        feature_states = self._features(mapped, config.weather is not None, has_rates, zone_valves)
        healthy = frozenset(s for s in mapped if health[s].status is SignalStatus.OK)
        features_now = self._features(
            healthy,
            self._weather_known(),
            has_rates,
            zone_valves,
            zone_data=bool(known_zones),
            read_back=self._read_back_serves(),
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
        self._follow_notices(snapshot, alarms, now)
        wall = self._follow_wall_thermostat(snapshot, now)
        return MonitorData(
            now=now,
            snapshot=snapshot,
            health=health,
            features=feature_states,
            connected=link_connected(health, self._relay_reachable()),
            zones=views,
            reference=self._reference,
            critical=dict(self._critical),
            alarms=alarms,
            central_mode=self.link.central_mode(),
            analysis=self.analysis,
            monitoring_since=self.monitoring_since,
            forecast_snapshots=self.forecasts.store.count() if self.forecasts else 0,
            capabilities=self.link.capabilities(),
            parameters=self.parameters,
            lowest_water=self.lowest_water,
            wall_thermostat=wall,
            features_now=features_now,
        )

    def configured_features(self) -> dict[Feature, FeatureState]:
        """The feature table by the configuration alone — what entities are created from: the
        zones' valves, known only once they report, never keep an entity from being created."""
        return self._features(
            frozenset(self.config.signals), self.config.weather is not None, self._has_rates(), None
        )

    def _has_rates(self) -> bool:
        return all(
            self.parameters.value(key) is not None
            for key in (ParameterKey.GAS_AT_MIN_POWER, ParameterKey.GAS_AT_MAX_POWER)
        )

    def _features(
        self,
        mapped: frozenset[Signal],
        has_weather: bool,
        has_rates: bool,
        zone_valves: bool | None,
        *,
        zone_data: bool | None = None,
        read_back: bool | None = None,
    ) -> dict[Feature, FeatureState]:
        """The feature table (the missing-data rule, Y4) for ``mapped`` signals: by default
        what the options give — zones configured, the control's read-back configured — or,
        given, what is known now."""
        config = self.config
        control = config.control
        kind: ControlKind | None = None
        if control.configured:
            kind = ControlKind.RELAY if control.write_path is WritePath.RELAY else ControlKind.WATER
        circuits = config.installation.circuits
        return features(
            mapped,
            has_weather,
            has_rates,
            add_water=config.monitor.alarms.add_water_below is not None,
            bypass=config.installation.boiler.bypass,
            zone_valves=zone_valves,
            zone_data=bool(config.installation.zones) if zone_data is None else zone_data,
            gateway=self.transport.gateway,
            has_dhw=config.monitor.monitor.has_dhw,
            condensing=config.installation.boiler.condensing,
            control=kind,
            # The option as the user left it: a relay's correction is off for want of water
            # control, not by the option.
            comfort_correction=kind is not ControlKind.WATER
            or control.loop.control.comfort_correction,
            circuit_maximum=any(c.max_flow is not None for c in circuits),
            circuit_flow=bool(config.circuit_flow_entities),
            wall_thermostat=wall_thermostat_applies(control),
            read_back=config.setpoint_read_back is not None if read_back is None else read_back,
            power_threshold=control.relay.heats_above_w is not None,
            shared=config.shared_signals,
        )

    def _weather_known(self) -> bool:
        """The weather entity configured and its state known now."""
        weather = self.config.weather
        state = self.hass.states.get(weather) if weather else None
        return state is not None and state.state not in UNAVAILABLE_STATES

    def _read_back_serves(self) -> bool:
        """Control's read-back stands for the CH setpoint now: while the plugin sets the water
        (X6)."""
        unit = self.control
        plugin = unit is not None and not unit.hand_back_only and unit.controlling
        return plugin and self.config.setpoint_read_back is not None

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
        """The monitor's current alarms, each from readings within their own age limits. What
        cannot be judged holds its state for an hour, then shows unknown (S-16)."""
        alarms: dict[AlarmKind, Alarm] = {}
        limits = self.config.monitor.alarms
        previous = self._alarms
        if snapshot.is_mapped(Signal.PRESSURE):
            pressure = snapshot.number(Signal.PRESSURE, self._max_age(Signal.PRESSURE))
            alarms.update(
                pressure_alarms(
                    pressure, limits.add_water_below, limits.pressure_high, previous, now
                )
            )
        if snapshot.is_mapped(Signal.FLUE_GAS) and self.config.installation.boiler.condensing:
            flue = snapshot.number(Signal.FLUE_GAS, self._max_age(Signal.FLUE_GAS))
            kind = AlarmKind.FLUE_GAS_HIGH
            alarms[kind] = banded_alarm(kind, flue, limits.flue_gas, previous.get(kind), now)
        # Heating burns only: a combi's short hot-water draws are no ignition problem, and a
        # burn of unknown kind is counted apart (P47). P-80: the burns of the last day as the
        # analysis classified them, every five minutes — not again at every refresh; they lag
        # by up to one analysis, which is enough for information. Before the first analysis,
        # or once it has stopped, there are none to judge by: unknown.
        options = self.config.monitor.monitor
        analysed = self.analysis
        if analysed is not None and now - analysed.at > ANALYSIS_BURNS_MAX_AGE_S:
            analysed = None  # the analysis has stopped: its burns are too old to judge by
        flame = self.history.signal(Signal.FLAME)
        burns = (
            [burn for burn in analysed.day.burns if burn.kind in CH_KINDS]
            if analysed is not None
            else []
        )
        kind = AlarmKind.FREQUENT_STARTS
        alarms[kind] = frequent_starts(
            burns,
            now,
            limits.starts_per_hour,
            previous.get(kind),
            known_s=known_duration(flame, now - HOUR, now) if analysed is not None else 0.0,
        )
        kind = AlarmKind.UNSTABLE_IGNITION
        alarms[kind] = unstable_ignition(
            burns,
            now,
            limit=limits.unstable_burns_per_day,
            demand=self.history.zone_calling(now - DAY, now),
            # P-81: mapped, the burns the boiler's own hysteresis ends are left out.
            flow=self.history.signals.get(Signal.FLOW),
            setpoint=self.history.signals.get(Signal.CH_SETPOINT),
            previous=previous.get(kind),
            known_s=known_duration(flame, now - DAY, now) if analysed is not None else 0.0,
        )
        too_hot = self._circuit_too_hot(snapshot, now)
        if too_hot is not None:
            alarms[AlarmKind.CIRCUIT_TOO_HOT] = too_hot
        if snapshot.is_mapped(Signal.PUMP_RUNNING) or snapshot.is_mapped(Signal.CH_ACTIVE):
            # Each flag by its own age limit (X2): a stale one is unknown.
            pump = snapshot.flag(Signal.PUMP_RUNNING, self._max_age(Signal.PUMP_RUNNING))
            if pump is None:
                pump = snapshot.flag(Signal.CH_ACTIVE, self._max_age(Signal.CH_ACTIVE))
            alarms[AlarmKind.LOW_FLOW] = low_flow(
                zones,
                pump,
                now,
                ZONE_MAX_AGE_S,
                previous.get(AlarmKind.LOW_FLOW),
                self.dhw_now(snapshot),
                self.config.installation.boiler.bypass,
                has_dhw=options.has_dhw,
            )
        return alarms

    # --- Y1: the boiler's own fault, and the notifications ------------------------------

    def fault_flags(self, snapshot: BoilerSnapshot) -> dict[Signal, bool]:
        """Whether each mapped fault signal of the boiler's counts now (boiler protection): a
        known "on" within its own age limit — on the OpenTherm Gateway only while the boiler's
        fault indication reads a known "on" too (Q3.9). Unknown, unavailable or stale counts as
        no fault. Control and the notification read it alike."""
        gate = snapshot.flag(Signal.FAULT_INDICATION, self._max_age(Signal.FAULT_INDICATION))
        return {
            signal: fault_counts(
                snapshot.flag(signal, self._max_age(signal)),
                gated=signal in self.transport.gateway,
                gate=gate,
            )
            for signal in FAULT_SIGNALS
            if snapshot.is_mapped(signal)
        }

    def _restore_notices(self) -> None:
        """At a start: a notification the last run left open (a reload keeps them) goes on, to
        close by its rule; one whose cause this configuration no longer has goes."""
        registry = ir.async_get(self.hass)
        applies = self._notices_that_apply()
        for key in NOTICE_ISSUES:
            issue_id = f"{key}_{self.config_entry.entry_id}"
            found = registry.async_get_issue(DOMAIN, issue_id)
            if found is None or not found.active:
                continue
            if key not in applies:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            self._notices[key] = Notice(open=True)
            self._notice_shown[key] = None  # shown, with what it said then

    def _notices_that_apply(self) -> set[str]:
        """The notifications this configuration can raise."""
        config = self.config
        found: set[str] = set()
        if Signal.PRESSURE in config.signals:
            found.add(PRESSURE_HIGH_ISSUE)
            if config.monitor.alarms.add_water_below is not None:
                found.add(ADD_WATER_ISSUE)
            if Signal.FLAME in config.signals and Signal.FLOW in config.signals:
                found.add(PRESSURE_FALLING_ISSUE)
        if Signal.FLUE_GAS in config.signals and config.installation.boiler.condensing:
            found.add(FLUE_GAS_HIGH_ISSUE)
        if any(signal in config.signals for signal in FAULT_SIGNALS):
            found.add(BOILER_FAULT_ISSUE)
        return found

    def _follow_notices(
        self, snapshot: BoilerSnapshot, alarms: dict[AlarmKind, Alarm], now: float
    ) -> None:
        """Y1's notifications. "Add water", high pressure and hot flue gas open at their alarm
        level — held five minutes of known readings, hot-water draws included — and close
        after an hour of known readings in the normal range: above the threshold + 0.1 bar;
        below the warning limit less its hysteresis. The trend's opens while it is exceeded and
        closes after an hour of it not. An unknown reading keeps an open one open. The boiler's
        fault opens once it has counted five minutes and closes when it no longer counts. Only
        information: none changes control."""
        limits = self.config.monitor.alarms
        applies = self._notices_that_apply()
        pressure = snapshot.number(Signal.PRESSURE, self._max_age(Signal.PRESSURE))
        flue = snapshot.number(Signal.FLUE_GAS, self._max_age(Signal.FLUE_GAS))
        threshold = limits.add_water_below
        high, gas = limits.pressure_high, limits.flue_gas

        def above(value: float | None, limit: float) -> bool | None:
            return None if value is None else value > limit

        def below(value: float | None, limit: float) -> bool | None:
            return None if value is None else value < limit

        banded: list[tuple[str, AlarmKind, bool | None, dict[str, str]]] = []
        if threshold is not None:
            banded.append(
                (
                    ADD_WATER_ISSUE,
                    AlarmKind.PRESSURE_LOW,
                    above(pressure, threshold + ADD_WATER_CLEAR_BAR),
                    {"value": _bar(pressure), "threshold": f"{threshold:.1f}"},
                )
            )
        for key, kind, band, value, shown in (
            (PRESSURE_HIGH_ISSUE, AlarmKind.PRESSURE_HIGH, high, pressure, _bar),
            (FLUE_GAS_HIGH_ISSUE, AlarmKind.FLUE_GAS_HIGH, gas, flue, _degrees),
        ):
            if band.warning is None or band.alarm is None:
                continue
            limit = f"{band.alarm:.1f}" if shown is _bar else f"{band.alarm:.0f}"
            banded.append(
                (
                    key,
                    kind,
                    below(value, band.warning - band.hysteresis),
                    {"value": shown(value), "limit": limit},
                )
            )
        for key, kind, normal, placeholders in banded:
            if key not in applies:
                continue
            alarm = alarms.get(kind)
            raised = (
                alarm is not None
                and alarm.active is True
                and alarm.level is Level.ALARM
                and alarm.reason != HELD
            )
            self._follow_notice(key, raised, normal, now, placeholders)
        if PRESSURE_FALLING_ISSUE in applies:
            trend = alarms.get(AlarmKind.PRESSURE_FALLING)
            judged = trend is not None and trend.active is not None and trend.reason != HELD
            exceeded = judged and trend is not None and trend.active is True
            change = None if trend is None else trend.value
            self._follow_notice(
                PRESSURE_FALLING_ISSUE,
                exceeded,
                (not exceeded) if judged else None,
                now,
                {"change": "-" if change is None else f"{abs(change):.2f}"},
            )
        if BOILER_FAULT_ISSUE in applies:
            self._follow_fault_notice(snapshot, now)

    def _follow_notice(
        self,
        key: str,
        raised: bool,
        normal: bool | None,
        now: float,
        placeholders: dict[str, str],
    ) -> None:
        notice = follow_notice(self._notices.get(key, Notice()), raised, normal, now)
        self._notices[key] = notice
        # What it says is what raised it: kept while it counts down in the normal range.
        self._show_notice(key, notice.open, placeholders if raised else None)

    def _follow_fault_notice(self, snapshot: BoilerSnapshot, now: float) -> None:
        """The boiler's own fault (boiler protection): the notification once a fault has
        counted for five minutes, naming the fault signals that count; gone the moment none
        does — an unknown one counts as none. Without control configured it opens all the
        same; nothing is written then."""
        flags = self.fault_flags(snapshot)
        self._fault_since = {
            signal: follow_fault(self._fault_since.get(signal), on, now)
            for signal, on in flags.items()
        }
        counting = [signal for signal, on in flags.items() if on]
        held = any(fault_holds(since, now) for since in self._fault_since.values())
        notice = self._notices.get(BOILER_FAULT_ISSUE, Notice())
        open_ = held or (notice.open and bool(counting))
        self._notices[BOILER_FAULT_ISSUE] = Notice(open=open_)
        names = ", ".join(self._entity_name(self.config.signals[s]) for s in counting) or "-"
        self._show_notice(BOILER_FAULT_ISSUE, open_, {"entity": names} if counting else None)

    def _entity_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        name = state.name if state is not None else None
        return f"{name} ({entity_id})" if name and name != entity_id else entity_id

    def _show_notice(self, key: str, open_: bool, placeholders: dict[str, str] | None) -> None:
        """The notification's repair issue: raised, updated when what it says changes, or
        deleted. ``placeholders`` ``None``: what it shows stays."""
        issue_id = f"{key}_{self.config_entry.entry_id}"
        shown = key in self._notice_shown
        if not open_:
            if shown:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                del self._notice_shown[key]
            return
        if placeholders is None:
            if shown:
                return
            placeholders = _NOTICE_DEFAULTS[key]
        if shown and self._notice_shown[key] == placeholders:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
        )
        self._notice_shown[key] = placeholders

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

    async def _async_alive_tick(self, _now: datetime) -> None:
        if not self._stopped:
            await self._async_save_alive()

    async def _async_save_alive(self) -> None:
        """P-95: the last-run record — the plugin runs now, and its downtimes still within the
        rolling history — written to its own small store, every ``ALIVE_SAVE_S`` and at a clean
        stop; nothing before the stores were read (P-04). A write that fails is logged: the next
        start then counts the downtime from the last record, earlier — unknown, never less."""
        if not self._loaded:
            return
        now = dt_util.utcnow().timestamp()
        floor = now - HISTORY_DAYS * DAY
        self.down = [(since, until) for since, until in self.down if until >= floor]
        record = {"alive_at": now, "down": [[since, until] for since, until in self.down]}
        try:
            await self._alive_store.async_save(record)
        except Exception:  # a full disk, say: the stop and the monitor go on
            _LOGGER.warning("Could not write when the plugin last ran", exc_info=True)

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

    def report_no_zone_known(self, kind: str | None, criteria: Sequence[str] = ()) -> None:
        """Decision 3's repair issue: ``kind`` — "off", "handed_back" or "monitor" — while every
        configured zone has been unknown for ten minutes, or, with ``criteria``, while the zones
        are known but none of the configured criteria — those named — could be judged for as
        long (PB-03); ``None`` deletes it. An error where heating stops, else a warning
        (provisional, K4). Raised anew when its kind or its criteria change."""
        wanted = None if kind is None else (kind, tuple(criteria))
        if wanted == self._no_zone_issue:
            return
        issue_id = f"{NO_ZONE_KNOWN_ISSUE}_{self.config_entry.entry_id}"
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._no_zone_issue = wanted
        if kind is None:
            return
        effects = {"off": "heating is off", "handed_back": "the boiler is handed back"}
        if criteria:
            _LOGGER.warning(
                "No demand criterion could be judged for ten minutes: %s has no data (%s)",
                ", ".join(criteria),
                effects.get(kind, "control does not decide now"),
            )
            key = f"{NO_CRITERION_ISSUE}_{kind}"
            placeholders = {"criteria": ", ".join(criteria)}
        else:
            _LOGGER.warning(
                "No Versatile Thermostat zone has answered for ten minutes (%s)",
                effects.get(kind, "the monitor cannot judge them"),
            )
            zones = ", ".join(self.link.zone_name(zone) for zone in self.config.zone_entities)
            key, placeholders = f"{NO_ZONE_KNOWN_ISSUE}_{kind}", {"zones": zones}
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR if kind == "off" else ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
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

    async def async_reset_measured(self, key: ParameterKey) -> None:
        """P-90 (review question 11): the user's reset of a measured building value — the heat
        loss or the heating threshold. Its measured estimate is forgotten, and it is fitted
        again from the days that start from now on only; the other value stays. An entered value
        is not touched. Nothing else changes — no option, so no reload and no hand-back:
        control never reads the building model. Saved at once and shown at once; the analysis
        runs again so the verdict follows."""
        if key not in RESETTABLE:
            raise ValueError(f"{key} is not a measured building value")
        now = dt_util.utcnow().timestamp()
        self.parameters = self.parameters.without(key, Source.MEASURED)
        self.fit_since[key] = now
        _LOGGER.info("The measured %s was reset: it is fitted from new days only", key.value)
        await self.async_save_now()
        await self.async_refresh()
        if not self._stopped:
            self.config_entry.async_create_background_task(
                self.hass, self.async_run_analysis(), f"{DOMAIN} analysis after a reset"
            )

    def report_installation(self) -> None:
        """P-94: each warning of the installation — a circuit without zones, underfloor heating
        on an unmixed circuit without a maximum — as a warning repair issue naming its circuits;
        one the options no longer hold goes. Not fixable here: the options fix it."""
        found: dict[IssueCode, list[str]] = {}
        for issue in self.config.installation.issues():
            if issue.severity is Severity.WARNING:
                found.setdefault(issue.code, []).append(issue.subject or "-")
        entry_id = self.config_entry.entry_id
        for code in INSTALLATION_WARNINGS:
            issue_id = f"{INSTALLATION_ISSUE}_{code.value}_{entry_id}"
            circuits = found.get(code)
            if not circuits:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=f"{INSTALLATION_ISSUE}_{code.value}",
                translation_placeholders={"circuits": ", ".join(circuits)},
            )

    async def async_run_analysis(self) -> None:
        """The periodic analysis, on a copy of the history in an executor thread."""
        if self._analysing:
            return
        self._analysing = True
        try:
            now = dt_util.utcnow().timestamp()
            self.history.drop_before(now - HISTORY_DAYS * DAY)
            # P-53: whether the recorder's history is back, read with the copy: a backfill that
            # ends while this analysis runs does not make its copy whole.
            back = self._history_back
            copy = self.history.copy_window(now - HISTORY_DAYS * DAY, now)
            days = local_days(now - HISTORY_DAYS * DAY, now)
            since = dict(self.fit_since)
            analysis = await self.hass.async_add_executor_job(
                analyse,
                copy,
                self.parameters,
                self.config.monitor.monitor,
                now,
                days,
                tuple(self.daily.values()),
                self.settings_key,
                # A trend that cannot be judged now keeps its last state for an hour (S-16).
                None if self.analysis is None else dict(self.analysis.trends),
                since,
            )
            if self._stopped:
                return  # a reload came meanwhile: the new installation analyses for itself
            self.analysis = analysis
            if back:
                self._keep_days(analysis.new_days, now)
            fit = self.analysis.fit
            if fit is not None:
                moved = False
                for key, estimate in (
                    (ParameterKey.LOSS_COEFFICIENT, fit.loss),
                    (ParameterKey.HEATING_THRESHOLD, fit.threshold),
                ):
                    if estimate is None or self.fit_since.get(key) != since.get(key):
                        continue  # not fitted, or reset while this analysis ran (P-90)
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


class ControlStore(Store[dict[str, Any]]):
    """The control store, whose writes are watched (PB-16). Home Assistant's store logs a write
    that fails — a full disk, a storage turned read-only — and goes on, so each write's outcome
    is noted here and told to ``noted``. Verified in Home Assistant 2026.9.3
    (``helpers/storage.py``): ``_async_handle_write_data`` calls ``_async_write_data`` inside the
    ``try`` that logs ``WriteError`` and ``SerializationError``; a write it defers (Home Assistant
    stopping) or skips tells nothing. A later version that no longer calls it leaves every
    outcome untold: nothing then counts as failed, as before (assumed, not seen)."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, noted: Callable[[bool], None] | None = None
    ) -> None:
        super().__init__(
            hass, CONTROL_STORE_VERSION, control_store_key(entry_id), atomic_writes=True
        )
        self._noted = noted

    async def _async_write_data(self, *args: Any, **kwargs: Any) -> None:
        # Whatever Home Assistant gives its private method is passed on as it is: an argument a
        # later version adds must not make every write of the control store fail (L2).
        try:
            await super()._async_write_data(*args, **kwargs)
        except Exception:
            self._note(False)
            raise
        self._note(True)

    def _note(self, ok: bool) -> None:
        if self._noted is not None:
            self._noted(ok)


def control_store(
    hass: HomeAssistant, entry_id: str, noted: Callable[[bool], None] | None = None
) -> ControlStore:
    """The control state alone, written at once and atomically on every change; ``noted`` is
    told whether each write went through (PB-16)."""
    return ControlStore(hass, entry_id, noted)


def alive_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """The last-run record (P-95): when the plugin last ran and its downtimes — small, written
    every ten minutes and at a clean stop, atomically."""
    return Store(hass, ALIVE_STORE_VERSION, alive_store_key(entry_id), atomic_writes=True)


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


def _downtimes(
    record: object, main: object, now: float, created: float | None
) -> list[tuple[float, float]]:
    """P-95 (A11): the downtimes still within the rolling history, and the one that ends now.

    The last-run record says when the plugin last ran — its clean stop, or its last write before
    a crash — and keeps the earlier downtimes. Without a readable one (missing, damaged, of
    another shape) the downtime is never taken as none: the main store's copy of the downtimes
    is taken, and the one ending now is unknown back to the latest moment the main store shows
    the plugin running (``_last_seen``: a build that kept ``alive_at`` there is read once so).
    Without the main store either — a first run, or both lost — it counts from the entry's
    creation: a new entry marks only the moments since. Never further back than the rolling
    history (what the recorder gives back)."""
    floor = now - HISTORY_DAYS * DAY
    found = record if isinstance(record, dict) else None
    since = _timestamp(found.get("alive_at")) if found is not None else None
    kept: object = found.get("down") if found is not None else None
    stored = main if isinstance(main, dict) else None
    if since is None:
        if record is not None:
            _LOGGER.warning("The record of when the plugin last ran cannot be read")
        kept = stored.get("down") if stored is not None else None
        seen = _last_seen(stored, now) if stored is not None else created
        since = floor if seen is None else max(seen, floor)
        _LOGGER.info(
            "No record of when the plugin last ran: the time since %s is taken as unknown",
            dt_util.utc_from_timestamp(since).isoformat(),
        )
    down: list[tuple[float, float]] = []
    for item in kept if isinstance(kept, list) else ():
        try:
            begin, end = (float(value) for value in item)
        except TypeError, ValueError:
            continue
        if math.isfinite(begin) and begin < end <= now and end >= floor:
            down.append((begin, end))
    if since < now:
        down.append((since, now))
    return sorted(down)


def _timestamp(raw: object) -> float | None:
    """A stored moment, or ``None`` for anything that is not a finite number."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _last_seen(stored: dict[str, Any], now: float) -> float | None:
    """The latest moment the entry's main store shows the plugin running: an ``alive_at`` a
    build kept there, the end of a day it summarised, an emitter factor or a measured value it
    computed, its monitoring start; ``None`` without any. A moment after ``now`` (a clock set
    back) says nothing."""
    moments = [stored.get("alive_at"), stored.get("monitoring_since")]
    for key, field_name in (("daily", "end"), ("factors", "at"), ("measured", "at")):
        section = stored.get(key)
        for item in section.values() if isinstance(section, dict) else ():
            if isinstance(item, dict):
                moments.append(item.get(field_name))
    known = [t for t in map(_timestamp, moments) if t is not None and t <= now]
    return max(known, default=None)


def _created_at(entry: ConfigEntry) -> float | None:
    """The entry's creation, ``None`` where it is not known (epoch 0: migrated from Home
    Assistant's old storage)."""
    created = getattr(entry, "created_at", None)
    try:
        at = created.timestamp() if isinstance(created, datetime) else 0.0
    except OverflowError, OSError, ValueError:
        return None
    return at if math.isfinite(at) and at > 0 else None


def _fit_since(raw: object, now: float) -> dict[ParameterKey, float]:
    """The stored moments of the user's resets (P-90). A reset whose moment cannot be read
    counts from ``now``: the days the user set aside are never fitted again, at the cost of
    waiting for new ones. A value that cannot be reset is ignored."""
    found: dict[ParameterKey, float] = {}
    for key, value in raw.items() if isinstance(raw, dict) else ():
        try:
            parameter = ParameterKey(key)
        except ValueError:
            parameter = None
        if parameter is None or parameter not in RESETTABLE:
            _LOGGER.warning("Ignoring a stored reset of %s, which cannot be reset", key)
            continue
        at = _timestamp(value)
        if at is None or at > now:
            _LOGGER.warning("An unreadable stored reset of %s: it counts from now", key)
            at = now
        found[parameter] = at
    return found


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


# P-87: what a day's summary depends on. Any other option — the water volume, the pressure
# signal, the alarms, control — leaves the stored days as they are. The loss coefficient is not
# here either: the load share is computed from each day's outdoor temperatures with the model
# of now (P-91).
SUMMARY_PARAMETERS = (
    ParameterKey.BOILER_MIN_POWER,
    ParameterKey.BOILER_MAX_POWER,
    ParameterKey.GAS_AT_MIN_POWER,
    ParameterKey.GAS_AT_MAX_POWER,
    ParameterKey.MAX_CH_SETPOINT,
    ParameterKey.HEATING_THRESHOLD,
)
SUMMARY_SIGNALS = (
    Signal.FLAME,
    Signal.FLOW,
    Signal.RETURN,
    Signal.MODULATION,
    Signal.CH_SETPOINT,
    Signal.DHW_ACTIVE,
    Signal.CH_ACTIVE,
    Signal.GAS_METER,
    Signal.OUTDOOR,
)


def summary_settings(config: EntryConfig) -> dict[str, Any]:
    """What shapes a day's summary, and only that (P-87): the monitor's options, the parameters
    it uses as the user entered them, the entities feeding the signals it reads, the weather
    entity and the zones."""
    options = config.monitor.monitor
    return {
        "options": {
            "condensing_return": options.condensing_return,
            "short_burn_s": options.short_burn_s,
            "modulation_scale": options.modulation_scale.value,
            "has_dhw": options.has_dhw,
            "setpoint_margin": options.setpoint_margin,
        },
        "parameters": {key.value: config.parameters.value(key) for key in SUMMARY_PARAMETERS},
        "signals": {signal.value: config.signals.get(signal) for signal in SUMMARY_SIGNALS},
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
