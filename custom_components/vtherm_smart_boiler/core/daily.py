"""Daily summaries: what the verdict needs from each local day, kept for up to a year.

A day's summary holds only amounts that add up across days — known time, heating starts and
burns, the hours with heating, the condensing share as its parts, degree-days, heating gas and
the gas other consumers used, the time under control, and the seconds per whole °C of outdoor
temperature — so the verdict over any window is built from its days. The load share is not
kept: it is computed from the days' outdoor temperatures with the building model of now (P-91),
so stored days never mix load models. The raw history is kept for a few days only; the
summaries outlive it (``SCOPE.md`` §10).

A burn across midnight is found whole, twelve hours on each side of the day: it is one burn of
the day it started in, its time split at midnight, and a day waits for such a burn to end
before it is summarised (P-83). A day checks the boiler's outdoor sensor against the weather
over that day and leaves a stuck one out (P-86).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from itertools import chain
from typing import Any

from .building import DayPoint, LoadFit, fit_daily_load
from .controller import ControlMode
from .cycles import find_burns
from .history import History
from .metrics import CH_KINDS, CycleStats, Share
from .monitor import MonitorOptions, summarize
from .parameters import Estimate, ParameterKey, ParameterSet
from .series import Series, duration_where, time_weighted_mean
from .signal_check import OutdoorStatus, check_outdoor
from .signals import Signal
from .verdict import (
    LoadBasis,
    VerdictOptions,
    VerdictResult,
    assess,
    load_below_min_from_distribution,
)

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
# P-91: a day's outdoor temperatures are kept in whole °C within these ends, colder or warmer
# ones counted at the end (provisional, K4).
OUTDOOR_LOW = -30
OUTDOOR_HIGH = 30

type OutdoorSeconds = tuple[tuple[int, float], ...]


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
    # P-91: seconds per whole °C of outdoor temperature (``OUTDOOR_LOW`` to ``OUTDOOR_HIGH``),
    # the temperatures known that day in order; ``None``: stored before it was kept — left out
    # of the load criterion.
    outdoor_s: OutdoorSeconds | None = None

    @classmethod
    def empty(cls, start: float, end: float) -> DaySummary:
        return cls(start, end, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, None, None)

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
        data = asdict(self)
        if self.outdoor_s is not None:
            data["outdoor_s"] = [[temperature, seconds] for temperature, seconds in self.outdoor_s]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DaySummary:
        """A stored summary; raises ``KeyError``, ``TypeError`` or ``ValueError`` when broken."""

        def number(key: str) -> float:
            return float(data[key])

        def optional(key: str) -> float | None:
            return None if data.get(key) is None else float(data[key])

        def outdoor() -> OutdoorSeconds | None:
            raw = data.get("outdoor_s")
            if raw is None:
                return None
            return tuple((int(temperature), float(seconds)) for temperature, seconds in raw)

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
            degree_days=optional("degree_days"),
            gas=optional("gas"),
            outdoor_mean=optional("outdoor_mean"),
            heat_kwh=optional("heat_kwh"),
            settings=str(data.get("settings") or ""),
            other_gas=optional("other_gas"),
            controlled_s=optional("controlled_s"),
            outdoor_s=outdoor(),
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
        # Over the whole day, from its known part when that covers most of it; unknown else —
        # a stuck sensor without the weather to stand in (P-86) gives no degree-days.
        degree_days=None if summary.degree_days is None else summary.degree_days.estimated_total(),
        gas=None if summary.gas is None else summary.gas.amount,
        outdoor_mean=(outdoor.value if outdoor.known_s >= FIT_COVERAGE * (end - start) else None),
        heat_kwh=heat.amount if heat is not None and heat.complete else None,
        settings=settings,
        other_gas=summary.other_gas,
        controlled_s=duration_where(history.control_state, start, end, _controlled),
        outdoor_s=outdoor_distribution(outdoor_series, start, end),
    )


def _controlled(state: str) -> bool:
    return state in CONTROLLED_MODES


def outdoor_distribution(outdoor: Series[float], start: float, end: float) -> OutdoorSeconds:
    """P-91: the seconds of ``[start, end)`` at each whole °C of outdoor temperature — rounded
    to the nearest, ``OUTDOOR_LOW`` and ``OUTDOOR_HIGH`` taking what lies beyond — in order;
    empty where the temperature is known nowhere."""
    seconds: dict[int, float] = {}
    for segment in outdoor.segments(start, end):
        if segment.value is None:
            continue
        whole = min(OUTDOOR_HIGH, max(OUTDOOR_LOW, math.floor(segment.value + 0.5)))
        seconds[whole] = seconds.get(whole, 0.0) + segment.duration
    return tuple(sorted(seconds.items()))


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


def fit_building(
    days: Sequence[DaySummary],
    threshold: Estimate,
    at: float,
    since: Mapping[ParameterKey, float] | None = None,
) -> LoadFit | None:
    """The building fit over the kept days, ``threshold`` the one in use. ``since``: where the
    user reset a measured value (P-90), the moment it happened — that value is fitted from the
    days that start from then on only; the loss and the threshold are fitted apart where their
    moments differ, so each reset forgets only its own value."""
    since = since or {}
    loss_from = since.get(ParameterKey.LOSS_COEFFICIENT, -math.inf)
    threshold_from = since.get(ParameterKey.HEATING_THRESHOLD, -math.inf)
    loss_fit = fit_daily_load(_points_since(days, loss_from), threshold, at)
    if threshold_from == loss_from:
        return loss_fit
    threshold_fit = fit_daily_load(_points_since(days, threshold_from), threshold, at)
    loss = None if loss_fit is None else loss_fit.loss
    fitted = None if threshold_fit is None else threshold_fit.threshold
    basis = loss_fit or threshold_fit
    if basis is None or (loss is None and fitted is None):
        return None
    return LoadFit(loss, fitted, basis.days, basis.quality)


def _points_since(days: Sequence[DaySummary], since: float) -> list[DayPoint]:
    return fit_points([day for day in days if day.start >= since])


def _part(share: Share | None) -> float:
    if share is None or share.value is None:
        return 0.0
    return share.value * share.basis_s


def verdict_over_days(
    days: Sequence[DaySummary],
    options: VerdictOptions | None = None,
    window_days: int | None = None,
    current: DaySummary | None = None,
    *,
    load: LoadBasis | None = None,
    burner_signal: bool = True,
) -> VerdictResult:
    """The verdict over the latest ``window_days`` complete days with data (all of them by
    default), and ``current``, the day under way, on top: its first hours must not take one of
    the window's days, which left the verdict short every night. Days under control — an hour
    or more of it, today's too — are left out before the window is taken, and counted (P-96):
    the verdict is the installation's own, without control. The load share comes from the
    chosen days' outdoor temperatures with ``load`` — the model and minimum power of now
    (P-91); days kept before the temperatures were leave the load criterion. ``burner_signal``:
    whether a flame signal is mapped (S-43)."""
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
    rests_on = load or LoadBasis()
    distributions = [d.outdoor_s for d in chosen if d.outdoor_s is not None]
    load_share = (
        load_below_min_from_distribution(
            chain.from_iterable(distributions), rests_on.model, rests_on.min_power_kw
        )
        if rests_on.model is not None and rests_on.min_power_kw is not None and distributions
        else None
    )
    result = assess(
        observed,
        heating,
        condensing,
        load_share,
        options,
        # "Estimate only" where the model alone was lacking: outdoor temperatures were known.
        load_estimate_only=rests_on.estimate_only and any(distributions),
        burner_signal=burner_signal,
    )
    return replace(result, days_left_out=left_out)


__all__ = [
    "CH_KINDS",
    "KEEP_DAYS",
    "DaySummary",
    "fit_building",
    "outdoor_distribution",
    "summarize_day",
    "verdict_over_days",
]
