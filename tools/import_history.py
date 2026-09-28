"""Import a copy of a Home Assistant recorder database into the core's ``History``.

Usage (every command through scripts/env.sh):

    scripts/env.sh python -m tools.import_history --db data/home-assistant_v2.db \\
        --mapping data/mapping.toml [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--tz <IANA zone>]

The mapping (see tools/mapping.example.toml) says which entity provides each signal. The database
is only read. The report shows signal coverage, burns, metrics and the verdict.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from custom_components.vtherm_smart_boiler.core.building import fit_daily_load
from custom_components.vtherm_smart_boiler.core.daily import (
    DAY_MARGIN_S,
    DaySummary,
    fit_points,
    summarize_day,
)
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries
from custom_components.vtherm_smart_boiler.core.metrics import HOUR, ModulationScale
from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions, summarize, verdict
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series, known_duration
from custom_components.vtherm_smart_boiler.core.signals import LINK_SIGNALS, Signal
from custom_components.vtherm_smart_boiler.units import signal_value, temperature_to_celsius
from custom_components.vtherm_smart_boiler.vtherm_attributes import zone_values

from .recorder_db import RecorderDatabase

DAY = 86400.0


@dataclass(frozen=True, slots=True)
class EntityMapping:
    """The user's mapping: signals, weather entity, zones, parameters and options."""

    signals: dict[Signal, str]
    weather: str | None = None
    zones: dict[str, str] = field(default_factory=dict)
    parameters: ParameterSet = field(default_factory=ParameterSet)
    options: MonitorOptions = field(default_factory=MonitorOptions)
    temperature_unit: str = "°C"  # Home Assistant's unit, for the VT zone temperatures


class MappingError(ValueError):
    pass


# What the mapping may hold: anything else is a misspelling that would be silently ignored.
SECTIONS = ("boiler", "zones", "parameters", "options", "weather")
OPTION_KEYS = ("condensing_return", "modulation_scale", "temperature_unit")
TEMPERATURE_UNITS = ("°C", "°F")  # Home Assistant's unit systems
CONDENSING_RETURN = (40.0, 65.0)  # as the plugin's options allow


def load_mapping(path: Path) -> EntityMapping:
    with path.open("rb") as file:
        data = tomllib.load(file)
    return parse_mapping(data)


def parse_mapping(data: Mapping[str, Any]) -> EntityMapping:
    for name in data:
        if name not in SECTIONS:
            raise MappingError(f"[{name}]: not a known section ({', '.join(SECTIONS)})")
    boiler = _table(data, "boiler")
    signals: dict[Signal, str] = {}
    for key, entity in boiler.items():
        try:
            signal = Signal(key)
        except ValueError as err:
            raise MappingError(f"[boiler] {key}: not a known signal") from err
        if not isinstance(entity, str) or "." not in entity:
            raise MappingError(f"[boiler] {key}: expected an entity ID")
        signals[signal] = entity
    # The history's analysis needs the boiler link's signals (the entry itself no longer does).
    missing = sorted(s.value for s in LINK_SIGNALS if s not in signals)
    if missing:
        raise MappingError(f"[boiler] missing required signals: {', '.join(missing)}")
    zones: dict[str, str] = {}
    for name, entity in _table(data, "zones").items():
        if not isinstance(entity, str) or not entity.startswith("climate."):
            raise MappingError(f"[zones] {name}: expected a VT thermostat (climate.*)")
        zones[str(name)] = entity
    parameters = ParameterSet()
    for key, value in _table(data, "parameters").items():
        try:
            parameter = ParameterKey(key)
        except ValueError as err:
            raise MappingError(f"[parameters] {key}: not a known parameter") from err
        try:
            estimate = Estimate(float(value), Source.ENTERED)
            parameters = parameters.with_estimate(parameter, estimate)
        except (TypeError, ValueError) as err:
            raise MappingError(f"[parameters] {key}: {err}") from err
    options_data = _table(data, "options", OPTION_KEYS)
    try:
        options = MonitorOptions(
            condensing_return=float(options_data.get("condensing_return", 55.0)),
            modulation_scale=ModulationScale(options_data.get("modulation_scale", "range")),
        )
    except (TypeError, ValueError) as err:
        raise MappingError(f"[options] condensing_return or modulation_scale: {err}") from err
    low, high = CONDENSING_RETURN
    if not low <= options.condensing_return <= high:
        raise MappingError(f"[options] condensing_return: expected {low:g} to {high:g} °C")
    unit = options_data.get("temperature_unit", "°C")
    if unit not in TEMPERATURE_UNITS:
        raise MappingError(f"[options] temperature_unit: expected {' or '.join(TEMPERATURE_UNITS)}")
    weather = _table(data, "weather", ("entity",)).get("entity")
    if weather is not None and (not isinstance(weather, str) or "." not in weather):
        raise MappingError("[weather] entity: expected an entity ID")
    return EntityMapping(signals, weather, zones, parameters, options, unit)


def _table(
    data: Mapping[str, Any], name: str, keys: Sequence[str] | None = None
) -> Mapping[str, Any]:
    """A section of the mapping; anything but a table, or a key it does not know, is explained,
    not a traceback."""
    section = data.get(name, {})
    if not isinstance(section, Mapping):
        raise MappingError(f"[{name}]: expected a table (e.g. [{name}] with keys under it)")
    for key in section:
        if keys is not None and key not in keys:
            raise MappingError(f"[{name}] {key}: not a known key ({', '.join(keys)})")
    return section


def read_history(db: RecorderDatabase, mapping: EntityMapping, start: float, end: float) -> History:
    history = History()
    for signal, entity in mapping.signals.items():
        series: Series = Series()
        for row in db.states(entity, start, end):
            unit = row.attributes.get("unit_of_measurement")
            series.append(row.t, signal_value(signal, row.state, unit))
        history.signals[signal] = series
    if mapping.weather is not None:
        for row in db.states(mapping.weather, start, end):
            raw = row.attributes.get("temperature")
            unit = row.attributes.get("temperature_unit")
            value = None
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                value = temperature_to_celsius(float(raw), unit)
            history.weather.append(row.t, value)
    for zone_id, entity in mapping.zones.items():
        zone = ZoneSeries(zone_id)
        for row in db.states(entity, start, end):
            values = zone_values(row.state, row.attributes, mapping.temperature_unit)
            zone.temperature.append(row.t, values.temperature)
            zone.target.append(row.t, values.target)
            zone.heating_enabled.append(row.t, values.heating_enabled)
            zone.calling.append(row.t, values.calling)
            zone.on_percent.append(row.t, values.on_percent)
            zone.valve_open.append(row.t, values.valve_open)
            zone.power.append(row.t, values.power)
        history.zones[zone_id] = zone
    return history


def local_days(start: float, end: float, tz: ZoneInfo) -> list[tuple[float, float]]:
    """Whole local days (midnight to midnight) inside ``[start, end)``."""
    first = datetime.fromtimestamp(start, tz).date()
    days: list[tuple[float, float]] = []
    day = first
    while True:
        begin = datetime.combine(day, time(), tz).timestamp()
        finish = datetime.combine(day + timedelta(days=1), time(), tz).timestamp()
        if begin >= end:
            break
        if begin >= start and finish <= end:
            days.append((begin, finish))
        day += timedelta(days=1)
    return days


def day_summaries(
    history: History,
    mapping: EntityMapping,
    start: float,
    end: float,
    tz: ZoneInfo,
    known_until: float | None = None,
) -> list[DaySummary]:
    """Each whole local day of ``[start, end)`` summarised as the plugin does (P-93: a day of 23
    or 25 hours is fitted as a whole day), each from its own window — the day and twelve hours
    on each side, for the burns across midnight — so the work grows with the days, not with
    their square (A13). ``known_until``: where the history ends."""
    days = []
    for begin, finish in local_days(start, end, tz):
        own = history.copy_window(begin - DAY_MARGIN_S, finish + DAY_MARGIN_S)
        days.append(
            summarize_day(
                own,
                mapping.parameters,
                begin,
                finish,
                mapping.options,
                known_until=finish + DAY_MARGIN_S if known_until is None else known_until,
            )
        )
    return days


def report(
    history: History,
    mapping: EntityMapping,
    start: float,
    end: float,
    tz: ZoneInfo,
    known_until: float | None = None,
) -> str:
    if end <= start:
        raise ValueError("the window is empty or reversed")  # P-111: the CLI refuses it first
    lines: list[str] = []
    span = end - start
    lines.append(
        f"Window: {datetime.fromtimestamp(start, tz):%Y-%m-%d %H:%M} – "
        f"{datetime.fromtimestamp(end, tz):%Y-%m-%d %H:%M} ({span / DAY:.1f} days)"
    )
    lines.append("Signals (share of the window with a known value):")
    for signal, series in history.signals.items():
        lines.append(f"  {signal.value:18} {known_duration(series, start, end) / span:6.1%}")
    if len(history.weather):
        lines.append(f"  {'weather':18} {known_duration(history.weather, start, end) / span:6.1%}")
    for zone_id, zone in history.zones.items():
        lines.append(
            f"  zone {zone_id:13} {known_duration(zone.temperature, start, end) / span:6.1%}"
        )

    summary = summarize(history, mapping.parameters, start, end, mapping.options)
    heating, dhw = summary.heating, summary.dhw
    lines.append("Heating burns:")
    lines.append(f"  starts per hour     {_fmt(heating.starts_per_hour)}")
    lines.append(f"  median burn (min)   {_fmt(_minutes(heating.median_burn_s))}")
    lines.append(
        f"  p10 / p90 (min)     {_fmt(_minutes(heating.p10_burn_s))} / "
        f"{_fmt(_minutes(heating.p90_burn_s))}"
    )
    lines.append(f"  short burns share   {_fmt(heating.short_burn_share)}")
    lines.append(f"  burner hours        {heating.burn_s / HOUR:.1f}")
    lines.append(f"DHW burns: {dhw.starts} starts, {dhw.burn_s / HOUR:.1f} h")
    if summary.condensing is not None:
        lines.append(f"Condensing share:    {_fmt(summary.condensing.value)}")
    if summary.degree_days is not None:
        lines.append(
            f"Degree-days:         {summary.degree_days.value:.1f} "
            f"(coverage {summary.degree_days.coverage:.0%})"
        )
    if summary.gas is not None:
        lines.append(
            f"Gas ({summary.gas_source}): {summary.gas.amount:.2f}, per degree-day "
            f"{_fmt(summary.gas_per_degree_day)}"
        )
    if summary.by_outdoor:
        lines.append("Heating starts per hour by outdoor temperature:")
        for low, stats in sorted(summary.by_outdoor.items()):
            lines.append(
                f"  {low:5.0f} °C .. {low + mapping.options.bin_width:3.0f} °C   "
                f"{_fmt(stats.starts_per_hour)} per h, median burn "
                f"{_fmt(_minutes(stats.median_burn_s))} min, {stats.observed_s / HOUR:.0f} h"
            )
    result = verdict(summary, mapping.options)
    lines.append(f"Verdict: {result.verdict.value}")
    for reason in result.reasons:
        lines.append(
            f"  - {reason.code.value} ({reason.kind.value}): {_fmt(reason.value)} "
            f"against {_fmt(reason.limit)}"
        )
    threshold = mapping.parameters.value(ParameterKey.HEATING_THRESHOLD) or 15.0
    days = day_summaries(history, mapping, start, end, tz, known_until)
    fit = fit_daily_load(fit_points(days), threshold)
    if fit is not None:
        fitted = "" if fit.threshold is None else f", threshold {fit.threshold.value:.1f} °C"
        lines.append(
            f"Building fit: {fit.loss.value:.3f} kW/K{fitted} from {fit.days} days "
            f"(quality {fit.quality:.2f})"
        )
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _minutes(seconds: float | None) -> float | None:
    return None if seconds is None else seconds / 60.0


def _parse_date(text: str, tz: ZoneInfo) -> float:
    return datetime.combine(datetime.strptime(text, "%Y-%m-%d").date(), time(), tz).timestamp()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, required=True, help="copy of home-assistant_v2.db")
    parser.add_argument("--mapping", type=Path, required=True, help="data/mapping.toml")
    parser.add_argument("--start", help="first day, YYYY-MM-DD (default: first state)")
    parser.add_argument("--end", help="day after the last, YYYY-MM-DD (default: last state)")
    parser.add_argument("--tz", default="UTC", help="time zone for day boundaries")
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except _UsageError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


class _UsageError(Exception):
    """A mistake in the arguments or the mapping, told in one line."""


def _run(args: argparse.Namespace) -> int:
    try:
        tz = ZoneInfo(args.tz)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise _UsageError(f"--tz {args.tz}: not a known time zone") from err
    try:
        mapping = load_mapping(args.mapping)
    except MappingError as err:
        raise _UsageError(f"mapping {args.mapping}: {err}") from err
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise _UsageError(f"mapping {args.mapping}: {err}") from err
    requested = {}
    for name in ("start", "end"):
        text = getattr(args, name)
        if text:
            try:
                requested[name] = _parse_date(text, tz)
            except ValueError as err:
                raise _UsageError(f"--{name} {text}: expected a date as YYYY-MM-DD") from err
    if "start" in requested and "end" in requested and requested["end"] <= requested["start"]:
        raise _UsageError("--end must come after --start")
    with RecorderDatabase(args.db) as db:
        if db.wal_warning:
            print(
                "warning: a -wal file lies next to the database; recent states may be missing",
                file=sys.stderr,
            )
        span = db.span()
        if span is None:
            print("the database holds no states", file=sys.stderr)
            return 1
        start = requested.get("start", span[0])
        end = requested.get("end", span[1])
        if end <= start:
            # P-111: zero long, the report would divide by zero; reversed, it would be negative.
            raise _UsageError(
                f"the window {_moment(start, tz)} – {_moment(end, tz)} is empty or reversed; "
                f"the database holds {_moment(span[0], tz)} – {_moment(span[1], tz)}"
            )
        unknown = [e for e in mapping.signals.values() if e not in db.entity_ids()]
        if unknown:
            print(f"warning: not in the database: {', '.join(unknown)}", file=sys.stderr)
        # Twelve hours on each side: the burns across the window's midnights are whole (P-83).
        known_until = min(end + DAY_MARGIN_S, max(span[1], end))
        history = read_history(db, mapping, start - DAY_MARGIN_S, known_until)
    print(report(history, mapping, start, end, tz, known_until))
    return 0


def _moment(t: float, tz: ZoneInfo) -> str:
    return f"{datetime.fromtimestamp(t, tz):%Y-%m-%d %H:%M}"


if __name__ == "__main__":
    sys.exit(main())
