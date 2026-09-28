"""Forecast snapshots (FC0): what the weather entity predicted, kept to learn from later.

Home Assistant keeps no forecast history — forecasts come only from ``weather.get_forecasts`` —
so the plugin stores snapshots itself. Comparing them with the outdoor temperature that followed
gives the forecast error per horizon, which the forecast features learn from. Snapshots are
trimmed to a horizon, kept for a retention period and grouped into weekly partitions so storage
only rewrites the current week.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .series import Series, time_weighted_mean

HOUR = 3600.0
DAY = 86400.0
DEFAULT_RETENTION_S = 90 * DAY
PARTITION_S = 7 * DAY
FORMAT_VERSION = 1


class ForecastKind(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"


STEP_S: dict[ForecastKind, float] = {ForecastKind.HOURLY: HOUR, ForecastKind.DAILY: DAY}
DEFAULT_HORIZON_POINTS: dict[ForecastKind, int] = {ForecastKind.HOURLY: 48, ForecastKind.DAILY: 7}


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One forecast step starting at ``t``: temperatures in °C, cloud coverage in %,
    wind speed in m/s, precipitation in mm."""

    t: float
    temperature: float | None = None
    temperature_low: float | None = None
    cloud_coverage: float | None = None
    wind_speed: float | None = None
    precipitation: float | None = None


_FIELDS = ("temperature", "temperature_low", "cloud_coverage", "wind_speed", "precipitation")
_KEYS = ("temp", "low", "cloud", "wind", "rain")


@dataclass(frozen=True, slots=True)
class ForecastSnapshot:
    taken_at: float
    kind: ForecastKind
    points: tuple[ForecastPoint, ...]

    def trimmed(self, max_points: int) -> ForecastSnapshot:
        """Points from the step holding ``taken_at`` on, at most ``max_points`` of them."""
        step = STEP_S[self.kind]
        current = [p for p in self.points if p.t + step > self.taken_at]
        return ForecastSnapshot(self.taken_at, self.kind, tuple(current[:max_points]))

    def to_dict(self) -> dict[str, Any]:
        """Compact form: offsets from ``taken_at`` in seconds and one list per field."""
        data: dict[str, Any] = {
            "at": round(self.taken_at),
            "kind": self.kind.value,
            "dt": [round(p.t - self.taken_at) for p in self.points],
        }
        for name, key in zip(_FIELDS, _KEYS, strict=True):
            values = [getattr(p, name) for p in self.points]
            if any(v is not None for v in values):
                data[key] = [None if v is None else round(v, 1) for v in values]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ForecastSnapshot:
        taken_at = float(data["at"])
        offsets = data["dt"]
        columns = {key: data.get(key) or [None] * len(offsets) for key in _KEYS}
        points = tuple(
            ForecastPoint(
                taken_at + offset,
                *(_as_float(columns[key][index]) for key in _KEYS),
            )
            for index, offset in enumerate(offsets)
        )
        return cls(taken_at, ForecastKind(data["kind"]), points)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _taken_at(snapshot: ForecastSnapshot) -> float:
    return snapshot.taken_at


def partition_of(taken_at: float) -> int:
    """Weekly storage partition of a snapshot."""
    return int(taken_at // PARTITION_S)


@dataclass
class ForecastStore:
    """Snapshots in time order, trimmed to a horizon and kept for ``retention_s``.

    Only the week being written is kept in memory, snapshot by snapshot; of the older weeks only
    when each snapshot was taken, to count them — this release uses no more (P-23). A snapshot
    of a week older than the one in memory is refused: that week's file would otherwise be
    written again with it alone."""

    retention_s: float = DEFAULT_RETENTION_S
    horizon_points: Mapping[ForecastKind, int] = field(
        default_factory=lambda: dict(DEFAULT_HORIZON_POINTS)
    )
    _snapshots: list[ForecastSnapshot] = field(default_factory=list)
    _partition: int | None = None  # the week in memory
    _older: dict[int, list[float]] = field(default_factory=dict)  # when, per older week

    def add(self, snapshot: ForecastSnapshot) -> ForecastSnapshot | None:
        """Store a trimmed copy; returns what was stored, ``None`` for an older week's."""
        partition = partition_of(snapshot.taken_at)
        if self._partition is not None and partition < self._partition:
            return None
        if self._partition is None or partition > self._partition:
            self._retire()
            self._partition = partition
        stored = snapshot.trimmed(self.horizon_points[snapshot.kind])
        self._snapshots.append(stored)
        self._snapshots.sort(key=lambda s: s.taken_at)
        return stored

    def _retire(self) -> None:
        """The week in memory becomes an older one: only its times are kept."""
        if self._partition is not None and self._snapshots:
            self._older[self._partition] = [s.taken_at for s in self._snapshots]
        self._snapshots = []

    def count(self) -> int:
        """Every snapshot within the retention, of every week."""
        return len(self._snapshots) + sum(len(times) for times in self._older.values())

    def prune(self, now: float) -> int:
        """Drop snapshots older than the retention; returns how many were dropped."""
        cutoff = now - self.retention_s
        before = self.count()
        self._snapshots = [s for s in self._snapshots if s.taken_at >= cutoff]
        older = {p: [t for t in times if t >= cutoff] for p, times in self._older.items()}
        self._older = {p: times for p, times in older.items() if times}
        return before - self.count()

    def snapshots(
        self, kind: ForecastKind | None = None, since: float | None = None
    ) -> list[ForecastSnapshot]:
        """The snapshots of the week in memory."""
        return [
            s
            for s in self._snapshots
            if (kind is None or s.kind is kind) and (since is None or s.taken_at >= since)
        ]

    def in_partition(self, partition: int) -> list[ForecastSnapshot]:
        """The snapshots of one weekly partition, in time order: the week in memory's; none
        for any other."""
        if partition != self._partition:
            return []
        start = bisect_left(self._snapshots, partition * PARTITION_S, key=_taken_at)
        end = bisect_left(self._snapshots, (partition + 1) * PARTITION_S, key=_taken_at)
        return self._snapshots[start:end]

    def partitions(self) -> dict[int, list[dict[str, Any]]]:
        """The week in memory's snapshots in the compact form, by partition."""
        grouped: dict[int, list[dict[str, Any]]] = {}
        for snapshot in self._snapshots:
            grouped.setdefault(partition_of(snapshot.taken_at), []).append(snapshot.to_dict())
        return grouped

    def load(self, partitions: Mapping[int, Sequence[object]], current: int) -> int:
        """Replace what is held with stored weekly partitions: ``current`` — the week being
        written — read in full, every older one only as far as counting it needs; a later week
        is left out. Unreadable entries are skipped. Returns how many were skipped. Parsing
        takes long for months of snapshots: run it in the executor, on a store nothing else
        uses meanwhile (P-23)."""
        skipped = 0
        snapshots: list[ForecastSnapshot] = []
        older: dict[int, list[float]] = {}
        for partition, entries in partitions.items():
            if partition > current:
                continue
            for data in entries:
                if partition == current:
                    try:
                        if not isinstance(data, Mapping):
                            raise TypeError("not a mapping")
                        snapshots.append(ForecastSnapshot.from_dict(data))
                    except KeyError, TypeError, ValueError, IndexError:
                        skipped += 1
                    continue
                taken_at = _stored_taken_at(data)
                if taken_at is None:
                    skipped += 1
                else:
                    older.setdefault(partition, []).append(taken_at)
        self._snapshots = sorted(snapshots, key=lambda s: s.taken_at)
        self._partition = current
        self._older = older
        return skipped


def _stored_taken_at(data: object) -> float | None:
    """When a stored snapshot was taken, where its entry can be read as one; else ``None``."""
    if not isinstance(data, Mapping) or not isinstance(data.get("dt"), list):
        return None
    if data.get("kind") not in {kind.value for kind in ForecastKind}:
        return None
    return _as_float(data.get("at"))


@dataclass(frozen=True, slots=True)
class ErrorStats:
    """Forecast minus observed temperature at one horizon."""

    count: int
    bias: float  # mean error, K
    mean_absolute: float  # K


def forecast_errors(
    snapshots: Iterable[ForecastSnapshot],
    observed: Series[float],
    horizons_h: Sequence[int] = (1, 3, 6, 12, 24, 48),
    *,
    observed_until: float,
) -> dict[int, ErrorStats]:
    """Error of hourly forecast temperatures per horizon (hours ahead, nearest listed one).

    The observed value is the mean outdoor temperature over the forecast step. A series holds
    its last value for ever, so a step ending after ``observed_until`` — the moment the
    observation reaches, the caller's now — is skipped: it has not been observed yet (P-88).
    """
    errors: dict[int, list[float]] = {h: [] for h in horizons_h}
    for snapshot in snapshots:
        if snapshot.kind is not ForecastKind.HOURLY:
            continue
        for point in snapshot.points:
            if point.temperature is None or point.t + HOUR > observed_until:
                continue
            ahead = (point.t - snapshot.taken_at) / HOUR
            if ahead < 0:
                continue
            horizon = min(horizons_h, key=lambda h: abs(h - ahead))
            if abs(horizon - ahead) > 0.5:
                continue
            mean = time_weighted_mean(observed, point.t, point.t + HOUR)
            if mean.value is None or mean.known_s < HOUR / 2:
                continue
            errors[horizon].append(point.temperature - mean.value)
    return {
        h: ErrorStats(len(e), sum(e) / len(e), sum(abs(x) for x in e) / len(e))
        for h, e in errors.items()
        if e
    }
