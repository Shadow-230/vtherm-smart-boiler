"""Foreign heat in a zone: a fireplace, stove or electric heater the user mapped — not the sun.

A source is a switch or binary sensor (on means heating), a power sensor above a threshold, or a
temperature sensor above a threshold. The room stays warmed for a while after a source stops, so
the zone counts as affected for a hold time afterwards. A source in an unknown state is listed
but does not make the zone affected.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_HOLD_S = 60 * 60.0
DEFAULT_POWER_THRESHOLD_W = 100.0


class SourceKind(StrEnum):
    SWITCH = "switch"
    BINARY = "binary"
    POWER = "power"
    TEMPERATURE = "temperature"


@dataclass(frozen=True, slots=True)
class ForeignHeatSource:
    source_id: str
    kind: SourceKind
    threshold: float | None = None  # W for power, °C for temperature

    def is_active(self, value: bool | float | None) -> bool | None:
        """Whether this source heats now; ``None`` when its state is unknown."""
        if value is None:
            return None
        if self.kind in (SourceKind.SWITCH, SourceKind.BINARY):
            return value if isinstance(value, bool) else None
        if isinstance(value, bool):
            return None
        threshold = self.threshold
        if threshold is None:
            if self.kind is SourceKind.TEMPERATURE:
                return None  # a temperature source needs the user's threshold
            threshold = DEFAULT_POWER_THRESHOLD_W
        return value > threshold


@dataclass(frozen=True, slots=True)
class ForeignHeatState:
    active: bool
    sources: tuple[str, ...] = ()  # sources heating now
    unknown: tuple[str, ...] = ()  # sources whose state is not known
    last_active_at: float | None = None
    holding: bool = False  # no source heats now, but the hold time has not run out


def update_foreign_heat(
    previous: ForeignHeatState | None,
    readings: Sequence[tuple[ForeignHeatSource, bool | float | None]],
    now: float,
    hold_s: float = DEFAULT_HOLD_S,
) -> ForeignHeatState:
    """Foreign-heat state of one zone from its sources' current values."""
    heating: list[str] = []
    unknown: list[str] = []
    for source, value in readings:
        state = source.is_active(value)
        if state is None:
            unknown.append(source.source_id)
        elif state:
            heating.append(source.source_id)
    if heating:
        return ForeignHeatState(True, tuple(heating), tuple(unknown), now)
    last = previous.last_active_at if previous is not None else None
    if last is not None:
        last = min(last, now)  # "later than now": the wall clock set back (PB-28)
    if last is not None and now - last < hold_s:
        return ForeignHeatState(True, (), tuple(unknown), last, holding=True)
    return ForeignHeatState(False, (), tuple(unknown), last)
