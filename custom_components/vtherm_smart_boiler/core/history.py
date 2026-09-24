"""Recorded history of one installation: boiler signals, VT zones and weather as series.

Exported history, the simulator and live Home Assistant all produce this one container, so the
same core code analyses all three.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from .readings import ZoneState
from .series import Series
from .signals import Signal


@dataclass
class ZoneSeries:
    """One VT zone over time (fractions from 0 to 1 for on-percent and valve opening)."""

    zone_id: str
    temperature: Series[float] = field(default_factory=Series)
    target: Series[float] = field(default_factory=Series)
    heating_enabled: Series[bool] = field(default_factory=Series)
    calling: Series[bool] = field(default_factory=Series)
    on_percent: Series[float] = field(default_factory=Series)
    valve_open: Series[float] = field(default_factory=Series)
    power: Series[float] = field(default_factory=Series)

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
            power=self.power.value_at(t),
            reported_at=t,
        )

    def series(self) -> tuple[Series, ...]:
        return (
            self.temperature,
            self.target,
            self.heating_enabled,
            self.calling,
            self.on_percent,
            self.valve_open,
            self.power,
        )


@dataclass
class History:
    """Boiler signals (only the mapped ones), zones and the weather entity's temperature."""

    signals: dict[Signal, Series] = field(default_factory=dict)
    zones: dict[str, ZoneSeries] = field(default_factory=dict)
    weather: Series[float] = field(default_factory=Series)

    def signal(self, signal: Signal) -> Series:
        """The series of a signal; empty (always unknown) when not mapped."""
        return self.signals.get(signal, Series())

    def is_mapped(self, signal: Signal) -> bool:
        return signal in self.signals

    def outdoor(self) -> Series[float]:
        """The boiler's outdoor sensor when mapped, else the weather entity."""
        return self.signals.get(Signal.OUTDOOR) or self.weather

    def zone_demand(self, start: float, end: float) -> Series[bool] | None:
        """True while any zone wants heat; ``None`` without zone data.

        A zone wants heat when its valve opening or duty cycle is above a few percent; only
        without those does its "calling" flag decide (a relay's flag flips within its cycle).
        """
        per_zone = [
            combine([z.valve_open, z.on_percent, z.calling], start, end, _zone_wants_heat)
            for z in self.zones.values()
            if len(z.valve_open) or len(z.on_percent) or len(z.calling)
        ]
        if not per_zone:
            return None
        return combine(per_zone, start, end, _any_known)

    def drop_before(self, t: float) -> None:
        for series in self.signals.values():
            series.drop_before(t)
        for zone in self.zones.values():
            for series in zone.series():
                series.drop_before(t)
        self.weather.drop_before(t)


DEMAND_OPENING = 0.05


def _zone_wants_heat(values: Sequence[object]) -> bool | None:
    valve, on_percent, calling = values
    for opening in (valve, on_percent):
        if isinstance(opening, int | float) and not isinstance(opening, bool):
            return opening > DEMAND_OPENING
    return calling if isinstance(calling, bool) else None


def _any_known(values: Sequence[bool | None]) -> bool | None:
    if any(v is True for v in values):
        return True
    if all(v is None for v in values):
        return None
    return False


def combine[T, R](
    inputs: Sequence[Series[T]],
    start: float,
    end: float,
    fn: Callable[[Sequence[T | None]], R | None],
) -> Series[R]:
    """A series of ``fn`` applied to the inputs' values at every change in ``[start, end)``."""
    times = sorted({start, *_times_within(inputs, start, end)})
    return Series((t, fn([s.value_at(t) for s in inputs])) for t in times)


def _times_within(inputs: Iterable[Series], start: float, end: float) -> set[float]:
    return {sample.t for series in inputs for sample in series if start < sample.t < end}
