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
from zoneinfo import ZoneInfo

from custom_components.vtherm_smart_boiler.core.building import fit_daily_load
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries
from custom_components.vtherm_smart_boiler.core.metrics import HOUR, ModulationScale
from custom_components.vtherm_smart_boiler.core.monitor import (
    MonitorOptions,
    daily_points,
    summarize,
    verdict,
)
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series, known_duration
from custom_components.vtherm_smart_boiler.core.signals import REQUIRED_SIGNALS, Signal
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


def load_mapping(path: Path) -> EntityMapping:
    with path.open("rb") as file:
        data = tomllib.load(file)
    return parse_mapping(data)


def parse_mapping(data: Mapping[str, Any]) -> EntityMapping:
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
    missing = sorted(s.value for s in REQUIRED_SIGNALS if s not in signals)
    if missing:
        raise MappingError(f"[boiler] missing required signals: {', '.join(missing)}")
    zones: dict[str, str] = {}
    for name, entity in _table(data, "zones").items():
        if not isinstance(entity, str) or "." not in entity:
            raise MappingError(f"[zones] {name}: expected an entity ID")
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
    options_data = _table(data, "options")
    try:
        options = MonitorOptions(
            condensing_return=float(options_data.get("condensing_return", 55.0)),
            modulation_scale=ModulationScale(options_data.get("modulation_scale", "range")),
        )
    except (TypeError, ValueError) as err:
        raise MappingError(f"[options] condensing_return or modulation_scale: {err}") from err
    weather = _table(data, "weather").get("entity")
    if weather is not None and (not isinstance(weather, str) or "." not in weather):
        raise MappingError("[weather] entity: expected an entity ID")
    return EntityMapping(
        signals,
        weather,
        zones,
        parameters,
        options,
        str(options_data.get("temperature_unit", "°C")),
    )


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    """A section of the mapping; anything but a table is explained, not a traceback."""
    section = data.get(name, {})
    if not isinstance(section, Mapping):
        raise MappingError(f"[{name}]: expected a table (e.g. [{name}] with keys under it)")
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


def report(history: History, mapping: EntityMapping, start: float, end: float, tz: ZoneInfo) -> str:
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
    days = local_days(start, end, tz)
    threshold = mapping.parameters.value(ParameterKey.HEATING_THRESHOLD) or 15.0
    fit = fit_daily_load(
        daily_points(history, mapping.parameters, days, mapping.options), threshold
    )
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
    tz = ZoneInfo(args.tz)
    mapping = load_mapping(args.mapping)
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
        start = _parse_date(args.start, tz) if args.start else span[0]
        end = _parse_date(args.end, tz) if args.end else span[1]
        unknown = [e for e in mapping.signals.values() if e not in db.entity_ids()]
        if unknown:
            print(f"warning: not in the database: {', '.join(unknown)}", file=sys.stderr)
        history = read_history(db, mapping, start, end)
    print(report(history, mapping, start, end, tz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
