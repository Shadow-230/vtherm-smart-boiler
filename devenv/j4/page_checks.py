"""J4: what the Boiler page reads from the plugin, checked as the page depends on it — the
installation, the curve with a draft, the days and the burns (scenario P2 in ``run.py``). Pure, so
that the in-process test (``tests/integration/test_j4_page.py``) holds these checks against the
plugin's real commands. Each function returns what is wrong, in words; nothing means all is well.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import pairwise
from typing import Any

BURN_KINDS = frozenset({"ch", "dhw", "unknown"})
WEEKS_SHOWN = 12
WEEK_KEYS = frozenset({"start", "end", "days", "gas", "degree_days", "per_degree_day"})
SIGNATURE_KEYS = frozenset(
    {"days", "observing", "control", "comparison", "min_days", "min_spread_k"}
)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def installation_problems(answer: Mapping[str, Any], zones: Iterable[str]) -> list[str]:
    """The entry as the page draws it: its circuits with these zones, the flame and flow it
    reads, its own entities — control the state shown, a binary sensor since I11.3 — and the
    curve's settings."""
    problems: list[str] = []
    circuits = answer.get("circuits") or []
    if not circuits:
        problems.append("no circuit")
    shown = {zone.get("entity_id") for circuit in circuits for zone in circuit.get("zones", [])}
    if shown != set(zones):
        problems.append(f"zones {sorted(str(z) for z in shown)}")
    signals = answer.get("signals") or {}
    problems += [f"no signal {name}" for name in ("flame", "flow") if not signals.get(name)]
    entities = answer.get("entities") or {}
    if not str(entities.get("control", "")).startswith("binary_sensor."):
        problems.append(f"control is {entities.get('control')!r}")
    if not str(entities.get("control_state", "")).startswith("sensor."):
        problems.append(f"control state is {entities.get('control_state')!r}")
    curve = answer.get("curve")
    if not isinstance(curve, Mapping) or not _number(curve.get("design_flow")):
        problems.append(f"no curve: {curve!r}")
    return problems


def curve_problems(answer: Mapping[str, Any]) -> list[str]:
    """The curve's points: outdoor rising, the water never rising with it, no problem named."""
    points = answer.get("points") or []
    if len(points) < 2:
        return [f"{len(points)} points"]
    if not all(len(p) == 2 and _number(p[0]) and _number(p[1]) for p in points):
        return ["a point is not (outdoor, water)"]
    problems: list[str] = []
    pairs = list(pairwise(points))
    if not all(a[0] < b[0] for a, b in pairs):
        problems.append("the outdoor temperature does not rise")
    if not all(b[1] <= a[1] for a, b in pairs):
        problems.append("the water rises with the outdoor temperature")
    if answer.get("problems"):
        problems.append(f"problems named: {answer['problems']}")
    return problems


def draft_problems(saved: Mapping[str, Any], draft: Mapping[str, Any]) -> list[str]:
    """A draft with a warmer design point: warmer water somewhere, cooler nowhere."""
    before, after = saved.get("points") or [], draft.get("points") or []
    if len(before) != len(after) or not before:
        return [f"{len(before)} points against {len(after)}"]
    if any(b[1] < a[1] for a, b in zip(before, after, strict=True)):
        return ["the draft's water is cooler somewhere"]
    if not any(b[1] > a[1] for a, b in zip(before, after, strict=True)):
        return ["the draft changes nothing"]
    return []


def days_problems(answer: Mapping[str, Any]) -> list[str]:
    """The days oldest first, at most 12 weeks with their fields, and the signature's parts."""
    problems: list[str] = []
    starts = [day.get("start") for day in answer.get("days", [])]
    if not all(_number(start) for start in starts) or starts != sorted(starts):
        problems.append("the days are not oldest first")
    weeks = answer.get("weeks")
    if not isinstance(weeks, list) or len(weeks) > WEEKS_SHOWN:
        problems.append(f"weeks: {weeks!r}")
    else:
        problems += [
            f"a week lacks {sorted(WEEK_KEYS - set(week))}"
            for week in weeks
            if not WEEK_KEYS <= set(week)
        ]
    signature = answer.get("signature")
    if not isinstance(signature, Mapping) or not SIGNATURE_KEYS <= set(signature):
        problems.append("the signature lacks its parts")
    if "gas_unit" not in answer:
        problems.append("no gas unit")
    return problems


def burns_problems(answer: Mapping[str, Any]) -> list[str]:
    """The monitor's burns: none before its first analysis, each with its times and kind."""
    burns = answer.get("burns")
    if not isinstance(burns, list):
        return [f"burns: {burns!r}"]
    at = answer.get("at")
    if at is None:
        return [f"{len(burns)} burns before any analysis"] if burns else []
    problems: list[str] = [] if _number(at) else [f"analysed at {at!r}"]
    for burn in burns:
        if not (_number(burn.get("start")) and _number(burn.get("end"))):
            problems.append(f"a burn's times: {burn}")
        elif burn["end"] < burn["start"]:
            problems.append(f"a burn ends before it starts: {burn}")
        if burn.get("kind") not in BURN_KINDS:
            problems.append(f"a burn's kind: {burn.get('kind')!r}")
        if not (
            isinstance(burn.get("start_seen"), bool) and isinstance(burn.get("end_seen"), bool)
        ):
            problems.append(f"a burn's edges: {burn}")
    return problems
