"""What the plugin exposes about a zone's water (I9; documentation/en/water-interface.md, §4):
the water reaching the zone's circuit, why it is not known, when it was measured, and whether
heat reaches the zone. Pure: the integration layer turns the time into a ``datetime``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .heat import Heat, HeatReason
from .supply import Supply, SupplyReason


@dataclass(frozen=True, slots=True)
class ZoneWater:
    supply_temperature: float | None  # °C, as measured
    supply_reason: SupplyReason | None  # why not known; ``None`` while known
    supply_measured_at: float | None  # seconds since the Unix epoch; ``None`` while not known
    heat_available: bool | None
    heat_reason: HeatReason | None  # why not, or why not known; ``None`` while heat reaches it


def zone_water(supplies: Sequence[Supply], heat: Heat) -> ZoneWater:
    """A zone's water from its circuits' supplies — one, or each circuit its devices are in
    (I8.8b) — and the heat through any of them. Several circuits give their common water where
    every one is known and equal, with the latest reading's time; else ``several_circuits``, a
    lasting fallback: one heat source per VT thermostat is expected."""
    if len(supplies) == 1:
        supply = supplies[0]
        known = supply.temperature is not None
        measured = supply.measured_at if known else None
        return ZoneWater(supply.temperature, supply.reason, measured, heat.available, heat.reason)
    temperatures = {supply.temperature for supply in supplies}
    if None in temperatures or len(temperatures) != 1:
        return ZoneWater(None, SupplyReason.SEVERAL_CIRCUITS, None, heat.available, heat.reason)
    times = [s.measured_at for s in supplies if s.measured_at is not None]
    return ZoneWater(
        supplies[0].temperature, None, max(times, default=None), heat.available, heat.reason
    )
