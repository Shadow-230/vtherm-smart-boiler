"""Daily summaries: what the verdict needs from each local day, kept for up to a year.

A day's summary holds only amounts that add up across days — known time, heating starts and
burns, the hours with heating, the condensing and load shares as their parts, degree-days,
heating gas and the gas other consumers used, the time under control — so the verdict over any
window is built from its days. The raw history is kept for a few days only; the summaries
outlive it (``SCOPE.md`` §10).

A burn across midnight is found whole, twelve hours on each side of the day: it is one burn of
the day it started in, its time split at midnight, and a day waits for such a burn to end
before it is summarised (P-83). A day checks the boiler's outdoor sensor against the weather
over that day and leaves a stuck one out (P-86).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from .building import DayPoint
from .controller import ControlMode
from .cycles import find_burns
from .history import History
from .metrics import CH_KINDS, CycleStats, Share
from .monitor import MonitorOptions, summarize
from .parameters import ParameterSet
from .series import Series, duration_where, time_weighted_mean
from .signal_check import OutdoorStatus, check_outdoor
from .signals import Signal
from .verdict import VerdictOptions, VerdictResult, assess

HOUR = 3600.0
DAY = 86400.0
KEEP_DAYS = 365
FIT_COVERAGE = 0.9  # a day the fit uses is known for this much of it
# P-83: burns are found this far on each side of a day, so one across midnight is whole; and a
# day is summarised once no burn that started in it still runs, or this long after its end
# (provisional, K4).
DAY_MARGIN_S = 12 * HOUR
DAY_SETTLE_S = 6 * HOUR
# P-96 (A12): the control states in which the plugin controls the boiler, and the time under
# control from which a day is left out of the verdict (provisional, K4).
CONTROLLED_MODES = frozenset(
    mode.value
    for mode in (
        ControlMode.HEATING,
        ControlMode.IDLE,
        ControlMode.FROST,
        ControlMode.FALLBACK,
        ControlMode.BOILER_FAULT,
    )
)
CONTROLLED_DAY_S = HOUR


@dataclass(frozen=True, slots=True)
class DaySummary:
    start: float
    end: float
    observed_s: float  # flame state known
    starts: int  # heating burns whose start was seen
    complete_burns: int
    short_burns: int
    burn_s: float
    heating_s: float  # time in the clock hours with heating
    condensing_s: float  # heating burn time with a condensing return
    condensing_basis_s: float  # heating burn time with the return known
    below_min_s: float  # heating-season time with the load below the boiler's minimum
    season_s: float  # heating-season time with a known load
    load_known: bool  # a load model and a minimum power existed that day
    degree_days: float | None
    gas: float | None  # heating gas, hot water and other consumers left out where known
    outdoor_mean: float | None = None  # over the day, when known for most of it
    heat_kwh: float | None = None  # heating output, when known for every burn
    settings: str = ""  # the key of the settings it was summarised with ("": not known)
    # S-31: gas the meter counted with the burner known off (another consumer), shown apart;
    # ``None`` without a meter.
    other_gas: float | None = None
    # P-96: time with the plugin controlling the boiler; ``None``: stored before it was kept —
    # uncontrolled, as no release controlled before.
    controlled_s: float | None = None

    @classmethod
    def empty(cls, start: float, end: float) -> DaySummary:
        return cls(start, end, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, None, None)

    @property
    def fit_point(self) -> DayPoint | None:
        """The day as the building fit uses it: known outdoor, complete heat, most of it seen."""
        if (
            self.outdoor_mean is None
            or self.heat_kwh is None
            or self.observed_s < FIT_COVERAGE * (self.end - self.start)
        ):
            return None
        # A day of 23 or 25 hours (the clock change) counts as a whole day of heating.
        return DayPoint(self.outdoor_mean, self.heat_kwh * DAY / (self.end - self.start))

    @property
    def has_data(self) -> bool:
        return self.observed_s > 0

    @property
    def under_control(self) -> bool:
        """P-96: controlled for ``CONTROLLED_DAY_S`` or more: left out of the verdict."""
        return self.controlled_s is not None and self.controlled_s >= CONTROLLED_DAY_S

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DaySummary:
        """A stored summary; raises ``KeyError``, ``TypeError`` or ``ValueError`` when broken."""

        def number(key: str) -> float:
            return float(data[key])

        def optional(key: str) -> float | None:
            return None if data.get(key) is None else float(data[key])

        return cls(
            start=number("start"),
            end=number("end"),
            observed_s=number("observed_s"),
            starts=int(data["starts"]),
            complete_burns=int(data["complete_burns"]),
            short_burns=int(data["short_burns"]),
            burn_s=number("burn_s"),
            heating_s=number("heating_s"),
            condensing_s=number("condensing_s"),
            condensing_basis_s=number("condensing_basis_s"),
            below_min_s=number("below_min_s"),
            season_s=number("season_s"),
            load_known=bool(data["load_known"]),
            degree_days=optional("degree_days"),
            gas=optional("gas"),
            outdoor_mean=optional("outdoor_mean"),
            heat_kwh=optional("heat_kwh"),
            settings=str(data.get("settings") or ""),
            other_gas=optional("other_gas"),
            controlled_s=optional("controlled_s"),
        )


def settings_key(settings: Mapping[str, Any]) -> str:
    """A short key for the settings that shape a day's summary — the monitor's options, the
    parameters the user entered, which entity feeds each signal: a day summarised with others
    no longer counts."""
    text = json.dumps(settings, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def summarize_day(
    history: History,
    parameters: ParameterSet,
    start: float,
    end: float,
    options: MonitorOptions | None = None,
    settings: str = "",
    known_until: float | None = None,
) -> DaySummary:
    """One day of history, reduced to what adds up; ``settings``: the key of the settings.

    Burns are found ``DAY_MARGIN_S`` on each side of the day, up to ``known_until`` — the moment
    the history reaches (the analysis' now): a burn still running then is not followed into the
    future (P-83)."""
    until = end + DAY_MARGIN_S
    if known_until is not None:
        until = max(end, min(until, known_until))
    outdoor_series = day_outdoor(history, start, end)
    summary = summarize(
        history,
        parameters,
        start,
        end,
        options,
        search=(start - DAY_MARGIN_S, until),
        outdoor=outdoor_series,
    )
    heating = summary.heating
    outdoor = time_weighted_mean(outdoor_series, start, end)
    heat = summary.heat_output_kwh
    condensing = summary.condensing
    load = summary.load_below_min
    return DaySummary(
        start=start,
        end=end,
        observed_s=summary.observed_s,
        starts=heating.starts,
        complete_burns=heating.complete_burns,
        short_burns=heating.short_burns,
        burn_s=heating.burn_s,
        heating_s=heating.active_s or 0.0,
        condensing_s=_part(condensing),
        condensing_basis_s=0.0 if condensing is None else condensing.basis_s,
        below_min_s=_part(load),
        season_s=0.0 if load is None else load.basis_s,
        load_known=load is not None,
        # Over the whole day, from its known part when that covers most of it; unknown else —
        # a stuck sensor without the weather to stand in (P-86) gives no degree-days.
        degree_days=None if summary.degree_days is None else summary.degree_days.estimated_total(),
        gas=None if summary.gas is None else summary.gas.amount,
        outdoor_mean=(outdoor.value if outdoor.known_s >= FIT_COVERAGE * (end - start) else None),
        heat_kwh=heat.amount if heat is not None and heat.complete else None,
        settings=settings,
        other_gas=summary.other_gas,
        controlled_s=duration_where(history.control_state, start, end, _controlled),
    )


def _controlled(state: str) -> bool:
    return state in CONTROLLED_MODES


def day_outdoor(history: History, start: float, end: float) -> Series[float]:
    """The outdoor temperature a day's summary uses (P-86): the boiler's sensor, with the
    weather entity where the sensor is unknown — unless ``check_outdoor`` finds the sensor stuck
    over that day: then the weather alone, and where the weather is not known either, the day's
    outdoor temperature is unknown. Without the weather a sensor cannot be found stuck and is
    used as it is."""
    sensor = history.signals.get(Signal.OUTDOOR)
    weather = history.weather
    if (
        sensor is not None
        and len(sensor)
        and len(weather)
        and check_outdoor(sensor, weather, start, end).status is OutdoorStatus.STUCK
    ):
        return weather
    return history.outdoor()


def day_settled(history: History, start: float, end: float, now: float) -> bool:
    """P-83: whether the day ``[start, end)`` may be summarised at ``now`` — no burn that started
    in it is still running (its length and time would be cut), or ``DAY_SETTLE_S`` have passed
    since its end, whichever comes first. A flame that is unknown now runs nothing to wait
    for: the burn it hides ended unseen."""
    if now >= end + DAY_SETTLE_S:
        return True
    flame = history.signal(Signal.FLAME)
    return not any(
        start <= burn.start < end and not burn.end_seen and burn.end >= now
        for burn in find_burns(flame, start - DAY_MARGIN_S, now)
    )


def keep_known_control(day: DaySummary, before: DaySummary | None) -> DaySummary:
    """A day summarised again (with other settings) keeps the time under control its earlier
    summary found: a past day's control does not change, and the recorder may no longer tell it
    — control since removed, its sensor gone (P-96)."""
    if before is None or before.controlled_s is None:
        return day
    if day.controlled_s is not None and day.controlled_s >= before.controlled_s:
        return day
    return replace(day, controlled_s=before.controlled_s)


def fit_points(days: Sequence[DaySummary]) -> list[DayPoint]:
    """Every kept day the building fit can use."""
    return [point for day in days if (point := day.fit_point) is not None]


def _part(share: Share | None) -> float:
    if share is None or share.value is None:
        return 0.0
    return share.value * share.basis_s


def verdict_over_days(
    days: Sequence[DaySummary],
    options: VerdictOptions | None = None,
    window_days: int | None = None,
    current: DaySummary | None = None,
) -> VerdictResult:
    """The verdict over the latest ``window_days`` complete days with data (all of them by
    default), and ``current``, the day under way, on top: its first hours must not take one of
    the window's days, which left the verdict short every night. Days under control — an hour
    or more of it, today's too — are left out before the window is taken, and counted (P-96):
    the verdict is the installation's own, without control."""
    with_data = sorted((d for d in days if d.has_data), key=lambda d: d.start)
    uncontrolled = [d for d in with_data if not d.under_control]
    left_out = len(with_data) - len(uncontrolled)
    chosen = uncontrolled if window_days is None else uncontrolled[-window_days:]
    if current is not None and current.has_data:
        if current.under_control:
            left_out += 1
        else:
            chosen = [*chosen, current]
    observed = sum(d.observed_s for d in chosen)
    heating = CycleStats(
        observed_s=observed,
        starts=sum(d.starts for d in chosen),
        complete_burns=sum(d.complete_burns for d in chosen),
        burn_s=sum(d.burn_s for d in chosen),
        median_burn_s=None,
        p10_burn_s=None,
        p90_burn_s=None,
        short_burns=sum(d.short_burns for d in chosen),
        active_s=sum(d.heating_s for d in chosen),
    )
    basis = sum(d.condensing_basis_s for d in chosen)
    condensing = (
        Share(sum(d.condensing_s for d in chosen) / basis if basis > 0 else None, basis)
        if basis > 0
        else None
    )
    season = sum(d.season_s for d in chosen)
    load = (
        Share(sum(d.below_min_s for d in chosen) / season if season > 0 else None, season)
        if any(d.load_known for d in chosen)
        else None
    )
    return replace(assess(observed, heating, condensing, load, options), days_left_out=left_out)


__all__ = ["CH_KINDS", "KEEP_DAYS", "DaySummary", "summarize_day", "verdict_over_days"]
