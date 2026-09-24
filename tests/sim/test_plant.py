"""The plant stepped from outside: overrides that lapse or hold, valves driven from outside."""

from __future__ import annotations

from sim.plant import Plant, WithoutOverride
from sim.profiles import BOILERS, HOUSES, radiator_zones


def plant(**kwargs) -> Plant:
    return Plant(BOILERS["condensing_small"], HOUSES["average"], radiator_zones(), 40.0, **kwargs)


def test_an_override_lapses_unless_repeated() -> None:
    p = plant(override_expires_s=60.0)
    p.set_override(0.0, 45.0, True)
    assert p.override_active(60.0)
    assert not p.override_active(61.0)


def test_a_holding_override_never_lapses() -> None:
    p = plant(override_expires_s=60.0)
    p.set_override(0.0, 45.0, None, holds=True)
    assert p.override_active(86400.0)
    p.clear_override()
    assert not p.override_active(1.0)


def test_valves_from_outside_drive_the_emitters() -> None:
    p = plant(without_override=WithoutOverride.OWN_CURVE)
    closed = p.step(0.0, 10.0, 0.0, False, [0.0] * len(p.zones))
    assert closed.emitted_kw == 0.0
    assert not closed.demand
    opened = p.step(10.0, 10.0, 0.0, False, [1.0] * len(p.zones))
    assert opened.demand
    assert opened.emitted_kw > 0.0


def test_standalone_without_override_does_not_heat() -> None:
    p = plant(without_override=WithoutOverride.OFF)
    out = p.step(0.0, 10.0, -5.0, False, [1.0] * len(p.zones))
    assert not out.demand
    assert not out.flame
