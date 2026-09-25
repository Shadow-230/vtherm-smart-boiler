"""Step-wise time series, the one format every data source is turned into.

A series holds samples ``(t, value)`` with ``t`` in seconds since the Unix epoch (UTC). Like a
Home Assistant state, each value holds until the next sample; ``None`` means unknown or
unavailable. Exported history, the simulator and live Home Assistant all feed the same format.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Sample[T]:
    """One value of a signal from time ``t`` on; ``None`` is unknown."""

    t: float
    value: T | None


@dataclass(frozen=True, slots=True)
class Segment[T]:
    """A stretch of time ``[start, end)`` during which the value did not change."""

    start: float
    end: float
    value: T | None

    @property
    def duration(self) -> float:
        return self.end - self.start


class Series[T]:
    """Samples of one signal in time order; each value holds until the next sample.

    Appending a value equal to the current one adds nothing: only changes are kept, as in the
    Home Assistant recorder. Freshness is tracked separately (``readings.Reading``).
    """

    __slots__ = ("_times", "_values")

    def __init__(self, samples: Iterable[tuple[float, T | None]] = ()) -> None:
        self._times: list[float] = []
        self._values: list[T | None] = []
        for t, value in samples:
            self.append(t, value)

    def append(self, t: float, value: T | None) -> None:
        """Add a sample; ``t`` may not go back in time, an equal ``t`` replaces the last one."""
        if self._times:
            last = self._times[-1]
            if t < last:
                raise ValueError(f"sample at {t} is older than the last sample at {last}")
            if t == last:
                self._values[-1] = value
                if len(self._values) > 1 and self._values[-2] == value:
                    self._times.pop()
                    self._values.pop()
                return
            if self._values[-1] == value:
                return
        self._times.append(t)
        self._values.append(value)

    def prepend(self, older: Series[T]) -> None:
        """Put the samples of ``older`` that come before this series' first sample in front of
        it (a backfill arriving after live samples)."""
        first = self.first_time
        merged: Series[T] = Series(
            (s.t, s.value) for s in older if first is None or s.t < first
        )
        for t, value in zip(self._times, self._values, strict=True):
            merged.append(t, value)
        self._times, self._values = merged._times, merged._values

    def __len__(self) -> int:
        return len(self._times)

    def __iter__(self) -> Iterator[Sample[T]]:
        for t, value in zip(self._times, self._values, strict=True):
            yield Sample(t, value)

    def __repr__(self) -> str:
        return f"Series({list(zip(self._times, self._values, strict=True))!r})"

    @property
    def first_time(self) -> float | None:
        return self._times[0] if self._times else None

    @property
    def last(self) -> Sample[T] | None:
        if not self._times:
            return None
        return Sample(self._times[-1], self._values[-1])

    def value_at(self, t: float) -> T | None:
        """The value holding at ``t``; ``None`` before the first sample."""
        index = bisect_right(self._times, t) - 1
        return self._values[index] if index >= 0 else None

    def segments(self, start: float, end: float) -> Iterator[Segment[T]]:
        """Stretches of constant value covering ``[start, end)``; before any sample: unknown."""
        if end <= start:
            return
        index = bisect_right(self._times, start) - 1
        cursor = start
        value: T | None = self._values[index] if index >= 0 else None
        index += 1
        while index < len(self._times) and self._times[index] < end:
            t = self._times[index]
            if t > cursor:
                yield Segment(cursor, t, value)
                cursor = t
            value = self._values[index]
            index += 1
        yield Segment(cursor, end, value)

    def window(self, start: float, end: float) -> Series[T]:
        """A copy covering ``[start, end)``: the value at ``start`` plus the later changes."""
        return Series((segment.start, segment.value) for segment in self.segments(start, end))

    def drop_before(self, t: float) -> None:
        """Forget samples no longer needed at ``t``; the value holding at ``t`` is kept."""
        index = bisect_right(self._times, t) - 1
        if index > 0:
            del self._times[:index]
            del self._values[:index]


def duration_where[T](
    series: Series[T], start: float, end: float, predicate: Callable[[T], bool]
) -> float:
    """Seconds in ``[start, end)`` during which the value is known and ``predicate`` holds."""
    return sum(
        segment.duration
        for segment in series.segments(start, end)
        if segment.value is not None and predicate(segment.value)
    )


def known_duration[T](series: Series[T], start: float, end: float) -> float:
    """Seconds in ``[start, end)`` during which the value is known."""
    return duration_where(series, start, end, lambda _value: True)


@dataclass(frozen=True, slots=True)
class Mean:
    """A time-weighted mean with the seconds of known data it rests on."""

    value: float | None
    known_s: float


def time_weighted_mean(series: Series[float], start: float, end: float) -> Mean:
    """Time-weighted mean of the known values in ``[start, end)``."""
    total = 0.0
    known = 0.0
    for segment in series.segments(start, end):
        if segment.value is None:
            continue
        total += segment.value * segment.duration
        known += segment.duration
    return Mean(total / known if known > 0 else None, known)


@dataclass(frozen=True, slots=True)
class Transition[T]:
    """A change from one known value to another at time ``t``."""

    t: float
    before: T
    after: T


def transitions[T](series: Series[T], start: float, end: float) -> list[Transition[T]]:
    """Changes between known values inside ``(start, end)``.

    A change across an unknown stretch (known → unknown → known) is not a transition: nobody
    saw when it happened.
    """
    found: list[Transition[T]] = []
    previous: T | None = None
    for segment in series.segments(start, end):
        value = segment.value
        if value is None:
            previous = None
            continue
        if previous is not None and value != previous and segment.start > start:
            found.append(Transition(segment.start, previous, value))
        previous = value
    return found
