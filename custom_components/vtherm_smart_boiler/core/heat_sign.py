"""Decision 2 of 0.2.3 (SB-01): "no sign the boiler heats" on the water-temperature paths.

A lockout, a panel set to summer or with heating off, or a gas fault leaves every read-back
confirming the plugin's values, and a boiler fault signal is optional (none by default). Heating
commanded while a zone calls and, for ``PROOF_WINDOW_S`` running, the flame known off — or, with
the flame unknown, no rise of the flow of ``PROOF_FLOW_RISE_K`` since the count began — while the
flow, where known, stays below the plugin's setpoint raises the information alarm "no sign the
boiler heats" (and the control unit's warning repair issue). Never a hand-back: control goes on
writing.

The count starts again whenever a condition ends. During a hot-water draw and ``DRAW_QUIET_S``
after it nothing is judged — the burner and the flow serve the hot water, on a panel set to
summer too — and with neither the flame nor the flow known nothing is judged. Once raised, the
alarm holds through all of these (a boiler locked out stays so while no room calls) until a sign
of heat: the flame on, the flow risen by ``PROOF_FLOW_RISE_K`` since the count began, or, with
the flame unknown, the flow at the plugin's setpoint while heating is commanded — the boiler
holds the water where asked. The window and the rise are the relay's proof's (R12,
``core/relay.py``): one value for every path, provisional, K4.
"""

from __future__ import annotations

from dataclasses import dataclass

from .guards import DRAW_QUIET_S
from .relay import PROOF_WINDOW_S, HeatEvidence, ProofSeen, heat_evidence


@dataclass(frozen=True, slots=True)
class HeatSignSeen:
    """One step's inputs. ``commanded``: control holds the boiler with heating on — not its
    "off", not handed back, no blocker, other controller or boiler fault stopping heating;
    ``calling``: a zone calls for heat (the zones' demand). ``None``: not mapped or not known —
    the flame, the flow (°C), the plugin's flow setpoint (°C) and hot water now (unknown: the
    draw rule does not apply)."""

    commanded: bool
    calling: bool
    flame: bool | None = None
    flow: float | None = None
    setpoint: float | None = None
    dhw: bool | None = None


@dataclass(frozen=True, slots=True)
class HeatSignState:
    since: float | None = None  # the count's start
    flow_from: float | None = None  # the flow then (its first known value after it)
    draw_at: float | None = None  # hot water last seen
    alarm: bool = False  # "no sign the boiler heats": holds until a sign of heat


def follow_heat_sign(state: HeatSignState, seen: HeatSignSeen, now: float) -> HeatSignState:
    """One step of the count (the module's rule); the state's ``alarm`` is the alarm's."""
    draw_at = state.draw_at
    if seen.dhw is True or (draw_at is not None and draw_at > now):
        draw_at = now  # a draw now; one later than now counts as now (C9)
    if draw_at is not None and now - draw_at <= DRAW_QUIET_S:
        return HeatSignState(draw_at=draw_at, alarm=state.alarm)
    evidence = heat_evidence(ProofSeen(flame=seen.flame, flow=seen.flow), state.flow_from, None)
    below = seen.flow is None or seen.setpoint is None or seen.flow < seen.setpoint
    held = seen.commanded and seen.flame is None and not below
    if evidence is HeatEvidence.HEATS or held:
        return HeatSignState(draw_at=draw_at)
    if not (seen.commanded and seen.calling and below and evidence is HeatEvidence.NOT_SEEN):
        return HeatSignState(draw_at=draw_at, alarm=state.alarm)
    since, flow_from = state.since, state.flow_from
    if since is None or since > now:
        since, flow_from = now, seen.flow  # the count begins (again, after a clock set back)
    elif flow_from is None:
        flow_from = seen.flow
    return HeatSignState(since, flow_from, draw_at, state.alarm or now - since >= PROOF_WINDOW_S)
