"""Switch zones driven as Versatile Thermostat's TPI drives them: on for ``on_percent`` of each
cycle (P-114).

A stand-in for VT where no VT runs — the offline scenarios and the in-process tests; in the test
Home Assistant VT drives the zone valve switches itself. A generic TPI law, written from its
description: at the start of each cycle the on-percent is
``coef_int · (target − room) + coef_ext · (target − outdoor)``, clamped to 0..1, and the valve is
open for that share of the cycle, from its start. VT 10.4.0's defaults — a 5-minute cycle,
coefficients 0.6 and 0.01 — are verified in its configuration schema
(``vendor/versatile_thermostat-10.4.0/.../config_schema.py:147, 314, 319``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TpiConfig:
    cycle_s: float = 300.0
    coef_int: float = 0.6
    coef_ext: float = 0.01


def on_percent(config: TpiConfig, target: float, room: float, outdoor: float) -> float:
    """The share of the next cycle the valve is open, 0 to 1."""
    raw = config.coef_int * (target - room) + config.coef_ext * (target - outdoor)
    return min(1.0, max(0.0, raw))


@dataclass
class TpiZone:
    """One zone's valve under TPI: its cycle and the on-percent taken at the cycle's start."""

    config: TpiConfig = field(default_factory=TpiConfig)
    cycle_start: float | None = None
    percent: float = 0.0

    def advance(self, t: float, target: float, room: float, outdoor: float) -> float:
        """The valve's opening now, 1 or 0; a new cycle takes a new on-percent."""
        cycle = self.config.cycle_s
        if self.cycle_start is None or t < self.cycle_start:
            self.cycle_start = t  # the first cycle, or a clock set back
            self.percent = on_percent(self.config, target, room, outdoor)
        elif t >= self.cycle_start + cycle:
            self.cycle_start += math.floor((t - self.cycle_start) / cycle) * cycle
            self.percent = on_percent(self.config, target, room, outdoor)
        return 1.0 if t < self.cycle_start + self.percent * cycle else 0.0
