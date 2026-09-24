"""Basic anti-cycling."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.anticycling import (
    AntiCycleConfig,
    AntiCycleResult,
    AntiCycleState,
    Hold,
    apply_anticycling,
    observe_flame,
)

MIN = 60.0
CONFIG = AntiCycleConfig(min_burn_s=5 * MIN, min_pause_s=10 * MIN, max_starts_per_hour=3)


def run(events: list[tuple[float, bool | None, bool | None]]) -> AntiCycleState:
    state = AntiCycleState()
    for t, flame, dhw in events:
        state = observe_flame(state, flame, dhw, t * MIN)
    return state


def test_edges_between_known_states_are_starts_and_ends() -> None:
    state = run([(0, False, False), (1, True, False), (4, False, False)])
    assert state.starts == (1 * MIN,)
    assert state.burn_started_at == 1 * MIN
    assert state.burn_ended_at == 4 * MIN
    assert state.burning is False


def test_no_edge_is_seen_across_unknown() -> None:
    state = run([(0, True, False), (1, None, None), (2, True, False), (3, False, False)])
    assert state.starts == ()
    assert state.burn_started_at is None
    assert state.burn_ended_at == 3 * MIN


def test_dhw_burns_are_not_heating_starts() -> None:
    state = run([(0, False, False), (1, True, True), (5, False, False)])
    assert state.starts == ()
    assert state.burn_ended_at is None


def test_starts_leave_the_budget_after_an_hour() -> None:
    state = run([(0, False, False), (1, True, False), (2, False, False), (70, False, False)])
    assert state.starts == ()


def test_unknown_flame_holds_nothing() -> None:
    state = run([(0, None, None)])
    assert apply_anticycling(True, state, 0.0, CONFIG) == AntiCycleResult(True)
    assert apply_anticycling(False, state, 0.0, CONFIG) == AntiCycleResult(False)


def test_minimum_burn_keeps_heating_enabled() -> None:
    state = run([(0, False, False), (10, True, False)])
    held = apply_anticycling(False, state, 12 * MIN, CONFIG)
    assert held == AntiCycleResult(True, Hold.MIN_BURN, 15 * MIN)
    assert apply_anticycling(False, state, 15 * MIN, CONFIG) == AntiCycleResult(False)


def test_minimum_pause_after_a_heating_burn() -> None:
    state = run([(0, False, False), (1, True, False), (5, False, False)])
    held = apply_anticycling(True, state, 8 * MIN, CONFIG)
    assert held == AntiCycleResult(False, Hold.MIN_PAUSE, 15 * MIN)
    assert apply_anticycling(True, state, 15 * MIN, CONFIG) == AntiCycleResult(True)


def test_start_budget_holds_until_the_oldest_start_expires() -> None:
    state = run(
        [
            (0, False, False),
            (1, True, False),
            (2, False, False),
            (13, True, False),
            (14, False, False),
            (25, True, False),
            (26, False, False),
        ]
    )
    assert len(state.starts) == 3
    held = apply_anticycling(True, state, 40 * MIN, CONFIG)
    assert held == AntiCycleResult(False, Hold.START_BUDGET, 61 * MIN)


def test_urgent_heat_skips_pause_and_budget() -> None:
    state = run([(0, False, False), (1, True, False), (5, False, False)])
    assert apply_anticycling(True, state, 6 * MIN, CONFIG, urgent=True) == AntiCycleResult(True)


def test_while_burning_heat_stays_enabled() -> None:
    state = run([(0, False, False), (1, True, False)])
    assert apply_anticycling(True, state, 30 * MIN, CONFIG) == AntiCycleResult(True)


@pytest.mark.parametrize("kwargs", [{"min_burn_s": -1.0}, {"max_starts_per_hour": 0}])
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        AntiCycleConfig(**kwargs)
