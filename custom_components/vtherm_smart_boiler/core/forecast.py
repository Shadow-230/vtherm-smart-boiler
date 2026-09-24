"""Forecast snapshots (FC0): what the weather entity predicted, kept to learn from later.

Home Assistant keeps no forecast history — forecasts come only from ``weather.get_forecasts`` —
so the plugin stores snapshots itself. Comparing them with the outdoor temperature that followed
gives the forecast error per horizon, which the forecast features learn from. Snapshots are
trimmed to a horizon, kept for a retention period and grouped into weekly partitions so storage
only rewrites the current week.
"""

from __future__ import annotations

import math
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


def partition_of(taken_at: float) -> int:
    """Weekly storage partition of a snapshot."""
    return int(taken_at // PARTITION_S)


@dataclass
class ForecastStore:
    """Snapshots in time order, trimmed to a horizon and kept for ``retention_s``."""

    retention_s: float = DEFAULT_RETENTION_S
    horizon_points: Mapping[ForecastKind, int] = field(
        default_factory=lambda: dict(DEFAULT_HORIZON_POINTS)
    )
    _snapshots: list[ForecastSnapshot] = field(default_factory=list)

    def add(self, snapshot: ForecastSnapshot) -> ForecastSnapshot:
        """Store a trimmed copy; returns what was stored."""
        stored = snapshot.trimmed(self.horizon_points[snapshot.kind])
        self._snapshots.append(stored)
        self._snapshots.sort(key=lambda s: s.taken_at)
        return stored

    def prune(self, now: float) -> int:
        """Drop snapshots older than the retention; returns how many were dropped."""
        cutoff = now - self.retention_s
        before = len(self._snapshots)
        self._snapshots = [s for s in self._snapshots if s.taken_at >= cutoff]
        return before - len(self._snapshots)

    def snapshots(
        self, kind: ForecastKind | None = None, since: float | None = None
    ) -> list[ForecastSnapshot]:
        return [
            s
            for s in self._snapshots
            if (kind is None or s.kind is kind) and (since is None or s.taken_at >= since)
        ]

    def partitions(self) -> dict[int, list[dict[str, Any]]]:
        """Snapshots in their weekly partitions, in the compact form."""
        grouped: dict[int, list[dict[str, Any]]] = {}
        for snapshot in self._snapshots:
            grouped.setdefault(partition_of(snapshot.taken_at), []).append(snapshot.to_dict())
        return grouped

    def load(self, partitions: Iterable[Sequence[Mapping[str, Any]]]) -> int:
        """Add snapshots from stored partitions; unreadable entries are skipped.

        Returns how many were skipped.
        """
        skipped = 0
        for partition in partitions:
            for data in partition:
                try:
                    self._snapshots.append(ForecastSnapshot.from_dict(data))
                except KeyError, TypeError, ValueError, IndexError:
                    skipped += 1
        self._snapshots.sort(key=lambda s: s.taken_at)
        return skipped


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
) -> dict[int, ErrorStats]:
    """Error of hourly forecast temperatures per horizon (hours ahead, nearest listed one).

    The observed value is the mean outdoor temperature over the forecast step.
    """
    errors: dict[int, list[float]] = {h: [] for h in horizons_h}
    for snapshot in snapshots:
        if snapshot.kind is not ForecastKind.HOURLY:
            continue
        for point in snapshot.points:
            if point.temperature is None:
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
