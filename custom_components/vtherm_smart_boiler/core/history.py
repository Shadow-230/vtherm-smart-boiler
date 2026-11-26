"""Recorded history of one installation: boiler signals, VT's call, the rooms and weather as
series.

Exported history, the simulator and live Home Assistant all produce this one container, so the
same core code analyses all three.

The rooms' history is the plugin's own (I12.7b, the user's decision of 2026-11-25): what it read
of each room through ``vtherm_api``, kept about eight days in a store of its own — never rebuilt
from the recorder's records of VT's climates. "Was the boiler called for heating" is VT's own
decision where the helper VT's central boiler switches is known (``vt_called``, the user's
entity, its recorder history allowed), the rooms elsewhere. ``rooms_to_stored`` and
``rooms_from_stored`` turn the rooms into the store's data and back: each series one line of
text, as Home Assistant writes its stores indented, one number per line otherwise.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .readings import ZONE_OPEN, ZoneState
from .series import Sample, Series
from .signals import Signal

# The rooms' series in the store, in ``ZoneSeries.series`` order; the flags among them.
STORED_SERIES = ("temperature", "target", "heating_enabled", "calling", "on_percent", "valve_open")
_FLAGS = frozenset({"heating_enabled", "calling"})
STORED_DECIMALS = 3  # a temperature to a thousandth of a degree, an opening to 0.1 %


@dataclass
class ZoneSeries:
    """One room over time, as the plugin read it from VT (fractions from 0 to 1 for on-percent
    and valve opening)."""

    zone_id: str
    temperature: Series[float] = field(default_factory=Series)
    target: Series[float] = field(default_factory=Series)
    heating_enabled: Series[bool] = field(default_factory=Series)
    calling: Series[bool] = field(default_factory=Series)
    on_percent: Series[float] = field(default_factory=Series)
    valve_open: Series[float] = field(default_factory=Series)

    def record(self, state: ZoneState, t: float) -> bool:
        """A room as read at ``t`` (I12.7b): each value into its series, changes only; a moment
        earlier than a series' last sample takes that sample's time. Whether anything changed."""
        changed = False
        values = (
            state.temperature,
            state.target,
            state.heating_enabled,
            state.calling,
            state.on_percent,
            state.valve_open,
        )
        for series, value in zip(self.series(), values, strict=True):
            last = series.last
            series.append(t if last is None else max(t, last.t), value)
            changed = changed or series.last != last
        return changed

    def state_at(self, t: float) -> ZoneState:
        """The zone at ``t``, treated as freshly reported (history keeps only changes)."""
        return ZoneState(
            self.zone_id,
            temperature=self.temperature.value_at(t),
            target=self.target.value_at(t),
            heating_enabled=self.heating_enabled.value_at(t),
            calling=self.calling.value_at(t),
            on_percent=self.on_percent.value_at(t),
            valve_open=self.valve_open.value_at(t),
            reported_at=t,
        )

    def calling_between(self, start: float, end: float) -> Series[bool]:
        """True while the zone asks for heat: its "calling" flag, and its opening only where the
        flag is not known (as ``History.zone_calling`` counts it)."""
        return combine([self.calling, self.valve_open, self.on_percent], start, end, _zone_calls)

    def series(self) -> tuple[Series[Any], ...]:
        return (
            self.temperature,
            self.target,
            self.heating_enabled,
            self.calling,
            self.on_percent,
            self.valve_open,
        )


@dataclass
class History:
    """Boiler signals (only the mapped ones), VT's call, the rooms and the weather entity's
    temperature."""

    signals: dict[Signal, Series[Any]] = field(default_factory=dict)
    zones: dict[str, ZoneSeries] = field(default_factory=dict)
    weather: Series[float] = field(default_factory=Series)
    # VT's call for heat (I12.7b): the helper VT's central boiler switches, on or off — VT's own
    # decision, from the recorder and live. Empty where no helper is set (monitoring only).
    vt_called: Series[bool] = field(default_factory=Series)
    # Under control without a CH setpoint signal: the control's setpoint read-back, the source
    # of the lowest water temperature's evidence (X6). Empty elsewhere.
    setpoint_read_back: Series[float] = field(default_factory=Series)
    # The plugin's own control state (its control-state sensor's states): the time under
    # control each day is told from it (P-96). Empty where control never ran.
    control_state: Series[str] = field(default_factory=Series)

    def signal(self, signal: Signal) -> Series[Any]:
        """The series of a signal; empty (always unknown) when not mapped."""
        return self.signals.get(signal, Series())

    def is_mapped(self, signal: Signal) -> bool:
        return signal in self.signals

    def outdoor(self) -> Series[float]:
        """The boiler's outdoor sensor where it is known, the weather entity elsewhere: a mapped
        sensor that is unavailable no longer blocks the weather (P46)."""
        sensor = self.signals.get(Signal.OUTDOOR)
        if sensor is None or not len(sensor):
            return self.weather
        if not len(self.weather):
            return sensor
        times = sorted({s.t for s in sensor} | {s.t for s in self.weather})
        merged: Series[float] = Series()
        for t in times:
            value = sensor.value_at(t)
            merged.append(t, value if value is not None else self.weather.value_at(t))
        return merged

    def zone_demand(self, start: float, end: float) -> Series[bool] | None:
        """True while the boiler was called for heat; ``None`` without VT's call or room data.

        VT's call decides wherever its helper's state is known (I12.7b: VT's own decision, with
        its thresholds); elsewhere the rooms: one wants heat when its valve opening or duty cycle
        is above a few percent; only without those does its "calling" flag decide (a relay's flag
        flips within its cycle).
        """
        per_zone = [
            combine([z.valve_open, z.on_percent, z.calling], start, end, _zone_wants_heat)
            for z in self._reporting()
        ]
        return self._vt_call_or(_any_room(per_zone, start, end), start, end)

    def zone_calling(self, start: float, end: float) -> Series[bool] | None:
        """True while the boiler was called for heat at that moment; ``None`` without VT's call
        or room data.

        VT's call decides wherever its helper's state is known (I12.7b); elsewhere the rooms: a
        room's "calling" flag decides — its heater or valve active now, VT's action — and its
        opening only where the flag is not known: a TPI zone's duty cycle stays the same through
        its cycle while its relay pulses, and the burns follow the relay (R6, A2).
        """
        per_zone = [z.calling_between(start, end) for z in self._reporting()]
        return self._vt_call_or(_any_room(per_zone, start, end), start, end)

    def _reporting(self) -> list[ZoneSeries]:
        """The rooms with anything recorded of whether they ask for heat."""
        return [
            z
            for z in self.zones.values()
            if len(z.valve_open) or len(z.on_percent) or len(z.calling)
        ]

    def _vt_call_or(
        self, rooms: Series[bool] | None, start: float, end: float
    ) -> Series[bool] | None:
        """VT's call where its helper's state is known, ``rooms`` where it is not."""
        if not len(self.vt_called):
            return rooms
        inputs = [self.vt_called] if rooms is None else [self.vt_called, rooms]
        return combine(inputs, start, end, _first_known)

    def copy_window(self, start: float, end: float) -> History:
        """An independent copy of ``[start, end)``, safe to analyse in another thread."""
        return History(
            signals={s: series.window(start, end) for s, series in self.signals.items()},
            zones={
                zid: ZoneSeries(zid, *(series.window(start, end) for series in zone.series()))
                for zid, zone in self.zones.items()
            },
            weather=self.weather.window(start, end),
            vt_called=self.vt_called.window(start, end),
            setpoint_read_back=self.setpoint_read_back.window(start, end),
            control_state=self.control_state.window(start, end),
        )

    def prepend(self, older: History) -> None:
        """Put an older history in front of this one, series by series (a backfill)."""
        for signal, series in self.signals.items():
            if signal in older.signals:
                series.prepend(older.signals[signal])
        for zone_id, zone in self.zones.items():
            if zone_id in older.zones:
                for series, earlier in zip(
                    zone.series(), older.zones[zone_id].series(), strict=True
                ):
                    series.prepend(earlier)
        self.weather.prepend(older.weather)
        self.vt_called.prepend(older.vt_called)
        self.setpoint_read_back.prepend(older.setpoint_read_back)
        self.control_state.prepend(older.control_state)

    def drop_before(self, t: float) -> None:
        for series in self.signals.values():
            series.drop_before(t)
        for zone in self.zones.values():
            for series in zone.series():
                series.drop_before(t)
        self.weather.drop_before(t)
        self.vt_called.drop_before(t)
        self.setpoint_read_back.drop_before(t)
        self.control_state.drop_before(t)


def with_downtime[X](
    rows: Iterable[tuple[float, X]],
    down: Sequence[tuple[float, float]],
    start: float,
    end: float,
) -> Iterator[tuple[float, X | None]]:
    """One entity's recorded rows, in time order, with its downtime unknown (P-95, A11).

    ``down`` holds the ``[from, to)`` intervals the plugin was not running — Home Assistant
    stopped or crashed (PB-65: a reload is not recorded, the recorder ran through it). Over each
    one that overlaps ``[start, end)``, the value is unknown from ``from`` on: a ``None`` row
    there, and the rows inside dropped — one may be from before a crash the last sign of life
    (``from``) came minutes earlier than, and none says how long its value held. At ``to`` — the
    plugin's setup — the latest row inside is the entity's state then (Home Assistant writes
    every state at its start, before the plugin's setup): known again from ``to`` (PB-65);
    without a row inside, from the first row after ``to``. An interval that began before
    ``start``, or at it, makes ``start`` itself unknown, as the recorder's state for it is the
    one from before — that row is not the state at ``to`` either."""
    marks: list[tuple[float, float, bool]] = []  # from, to, began at or before ``start``
    for a, b in sorted((a, b) for a, b in down if a < b and b > start and a < end):
        low = max(a, start)
        if marks and low <= marks[-1][1]:
            marks[-1] = (marks[-1][0], max(marks[-1][1], b), marks[-1][2])  # one downtime
        else:
            marks.append((low, b, a <= start))
    index = 0
    marked = False  # the current interval's ``None`` is out
    last: list[X] = []  # the latest row inside the current interval: its state at ``to``
    for t, value in rows:
        while index < len(marks) and marks[index][1] <= t:
            low, high, _before = marks[index]
            if not marked:
                yield low, None
            if last and high < t:
                yield high, last[0]
            index += 1
            marked = False
            last = []
        if index < len(marks) and marks[index][0] <= t:
            if not marked:
                yield marks[index][0], None
                marked = True
            if t > start or not marks[index][2]:
                last = [value]
            continue  # inside the downtime: its value is not known to hold before ``to``
        yield t, value
    for low, high, _before in marks[index:]:
        if not marked:
            yield low, None
        if last and high < end:
            yield high, last[0]
        marked = False
        last = []


def _zone_wants_heat(values: Sequence[object]) -> bool | None:
    valve, on_percent, calling = values
    for opening in (valve, on_percent):
        if isinstance(opening, int | float) and not isinstance(opening, bool):
            return opening > ZONE_OPEN
    return calling if isinstance(calling, bool) else None


def _zone_calls(values: Sequence[object]) -> bool | None:
    calling, valve, on_percent = values
    if isinstance(calling, bool):
        return calling
    return _zone_wants_heat((valve, on_percent, None))


def _any_room(per_zone: Sequence[Series[bool]], start: float, end: float) -> Series[bool] | None:
    """True while any room asks for heat; ``None`` without any room's data."""
    if not per_zone:
        return None
    return combine(per_zone, start, end, _any_known)


def _first_known(values: Sequence[bool | None]) -> bool | None:
    """The first value known: VT's call over the rooms."""
    return next((value for value in values if value is not None), None)


def _any_known(values: Sequence[bool | None]) -> bool | None:
    """True when any zone calls; False only when every zone is known not to (an unknown zone
    may be calling)."""
    if any(v is True for v in values):
        return True
    if any(v is None for v in values):
        return None
    return False


def combine[R](
    inputs: Sequence[Series[Any]],
    start: float,
    end: float,
    fn: Callable[[Sequence[Any]], R | None],
) -> Series[R]:
    """A series of ``fn`` applied to the inputs' values at every change in ``[start, end)``."""
    times = sorted({start, *_times_within(inputs, start, end)})
    return Series((t, fn([s.value_at(t) for s in inputs])) for t in times)


def _times_within(inputs: Iterable[Series[Any]], start: float, end: float) -> set[float]:
    return {t for series in inputs for t in series.times_between(start, end)}


# --- the rooms' store (I12.7b) ---------------------------------------------------------------


def rooms_to_stored(
    zones: Mapping[str, ZoneSeries], since: float, max_points: int
) -> dict[str, dict[str, str]]:
    """Each room's series as the store keeps them: from ``since`` on — the value holding then
    included —, at most the ``max_points`` newest samples of each, as text
    (``series_to_text``). A series with nothing recorded is left out."""
    stored: dict[str, dict[str, str]] = {}
    for zone_id, zone in zones.items():
        texts: dict[str, str] = {}
        for name, series in zip(STORED_SERIES, zone.series(), strict=True):
            samples = list(series)
            if not samples:
                continue
            first = max(0, bisect_right([s.t for s in samples], since) - 1)
            texts[name] = series_to_text(samples[first:][-max_points:], flag=name in _FLAGS)
        if texts:
            stored[zone_id] = texts
    return stored


def rooms_from_stored(
    raw: object, zone_ids: Iterable[str], since: float, unknown_from: float
) -> tuple[dict[str, ZoneSeries], int]:
    """The rooms ``rooms_to_stored`` kept, for the rooms in ``zone_ids`` only: each series from
    ``since`` on, and unknown from ``unknown_from`` — the store's last write: what came after it
    was not kept. A series that cannot be read is left empty; how many were is returned too."""
    found: dict[str, ZoneSeries] = {}
    damaged = 0
    rooms = raw if isinstance(raw, Mapping) else {}
    for zone_id in zone_ids:
        texts = rooms.get(zone_id)
        if not isinstance(texts, Mapping):
            continue
        zone = ZoneSeries(zone_id)
        for name, series in zip(STORED_SERIES, zone.series(), strict=True):
            if name not in texts:
                continue
            read = series_from_text(texts[name], flag=name in _FLAGS)
            if read is None:
                damaged += 1
                continue
            read.drop_before(since)
            last = read.last
            if last is None:
                continue
            read.append(max(unknown_from, last.t), None)
            series.prepend(read)
        found[zone_id] = zone
    return found, damaged


def series_to_text(samples: Iterable[Sample[Any]], *, flag: bool) -> str:
    """Samples as one line: ``seconds:value`` pairs joined by commas — the first moment in whole
    seconds since the epoch, each later one as the seconds since the one before; a flag as ``1``
    or ``0``, a number to ``STORED_DECIMALS`` decimals, nothing where unknown."""
    parts: list[str] = []
    previous: int | None = None
    for sample in samples:
        t = round(sample.t)
        parts.append(f"{t if previous is None else t - previous}:{_text(sample.value, flag)}")
        previous = t
    return ",".join(parts)


def series_from_text(text: object, *, flag: bool) -> Series[Any] | None:
    """The samples ``series_to_text`` wrote, as a series; ``None`` where anything in it cannot be
    read (a step back in time included)."""
    if not isinstance(text, str):
        return None
    series: Series[Any] = Series()
    if not text:
        return series
    t = 0
    for index, part in enumerate(text.split(",")):
        step, colon, raw = part.partition(":")
        try:
            seconds = int(step)
        except ValueError:
            return None
        value = _from_text(raw, flag)
        if not colon or (seconds < 0 and index > 0) or value is _DAMAGED:
            return None
        t = seconds if index == 0 else t + seconds
        series.append(float(t), value)
    return series


_DAMAGED = object()


def _text(value: object, flag: bool) -> str:
    if flag:
        return {True: "1", False: "0"}.get(value, "") if isinstance(value, bool) else ""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return ""
    return repr(round(float(value), STORED_DECIMALS))


def _from_text(raw: str, flag: bool) -> object:
    if not raw:
        return None
    if flag:
        return {"1": True, "0": False}.get(raw, _DAMAGED)
    try:
        number = float(raw)
    except ValueError:
        return _DAMAGED
    return number if math.isfinite(number) else _DAMAGED
