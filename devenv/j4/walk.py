"""J4: the plugin's options saved through Home Assistant's REST API as a user saves them (I7,
I8): the menu's items opened one after another, each form answered with what it shows and the
changes it asks for, back to the menu, then "Save and finish".

The changes are one flat set of field names: each goes to whichever form asks it, so a field
that moved between forms (I8: the read-backs to the boiler signals, the gateway's questions to
the boiler interface, the comfort correction to the curve, VT's activation delay to the
behaviour, frost protection to its own item) needs no other change here. A ``None`` value
empties the field. Pure: the caller passes its ``rest`` — the runner's client, or a test's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

Rest = Callable[[str, str, dict[str, Any] | None], Awaitable[tuple[int, dict[str, Any]]]]

FLOW = "/api/config/config_entries/options/flow"
# The forms that only ask to confirm, and their answer.
CONFIRMATIONS = {
    "control_return_confirm": {"understood": True},
    "confirm_blocking": {"save_anyway": True},
}
# A form shown more often than this in one item is going round in circles.
MAX_SHOWINGS = 4


class OptionsNotSaved(RuntimeError):
    """The options were not saved: a form refused its answer, or the flow went elsewhere."""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


def shown(form: Mapping[str, Any]) -> dict[str, Any]:
    """What a form shows: each field's suggested value, else its default; empty fields left
    out, as a user leaves them."""
    values: dict[str, Any] = {}
    for field in form.get("data_schema") or []:
        value = (field.get("description") or {}).get("suggested_value", field.get("default"))
        if value is not None:
            values[field["name"]] = value
    return values


def fields(form: Mapping[str, Any]) -> set[str]:
    return {field["name"] for field in form.get("data_schema") or []}


async def save_options(
    rest: Rest,
    entry_id: str,
    changes: Mapping[str, Any],
    items: Iterable[str],
    *,
    required: Iterable[str] = (),
    strict: bool = True,
    note: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Open the options, answer ``items`` in order — an item not on the menu is passed by —
    with ``changes``, and save. Every key of ``required`` must be asked by a form on the way,
    or nothing is saved. Returns the flow's last answer, and under ``"seen"`` what each form
    showed before it was answered (a scenario puts back what it changed from it).

    ``strict``: a refusal raises ``OptionsNotSaved``; otherwise the refusing answer is returned
    — its ``errors`` — for a scenario whose point is the refusal. Either way the flow is closed
    and nothing is saved."""
    _status, d = await rest("POST", FLOW, {"handler": entry_id, "show_advanced_options": True})
    path = f"{FLOW}/{d['flow_id']}"
    asked: set[str] = set()
    seen: dict[str, dict[str, Any]] = {}

    async def refused(message: str, result: dict[str, Any]) -> dict[str, Any]:
        await rest("DELETE", path, None)
        if strict:
            raise OptionsNotSaved(message, result)
        if note is not None:
            note(f"options not saved: {message}")
        return result if result.get("errors") else {**result, "errors": {"base": message}}

    async def answer_forms(d: dict[str, Any]) -> dict[str, Any]:
        showings: dict[str, int] = {}
        while d.get("type") == "form":
            step = str(d["step_id"])
            if d.get("errors"):
                return d
            showings[step] = showings.get(step, 0) + 1
            if showings[step] > MAX_SHOWINGS:
                return {**d, "errors": {"base": f"{step} shown again and again"}}
            if step in CONFIRMATIONS:
                if note is not None:
                    placeholders = d.get("description_placeholders") or {}
                    note(f"options: '{step}' confirmed {placeholders}".rstrip(" {}"))
                body = dict(CONFIRMATIONS[step])
            else:
                seen.setdefault(step, shown(d))
                body = shown(d)
                for key in fields(d) & set(changes):
                    asked.add(key)
                    value = changes[key]
                    if value is None:
                        body.pop(key, None)
                    else:
                        body[key] = value
            _status, d = await rest("POST", path, body)
        return d

    for item in items:
        if d.get("type") != "menu":
            return await refused(f"not at the menu before {item}: {str(d)[:200]}", d)
        if item not in d.get("menu_options", []):
            continue
        _status, d = await rest("POST", path, {"next_step_id": item})
        d = await answer_forms(d)
        if d.get("errors"):
            return await refused(f"{item}: {d['errors']}", d)
    missing = sorted(set(required) - asked)
    if missing:
        return await refused(f"no form asked {missing}", {"type": "not_asked", "missing": missing})
    if d.get("type") != "menu":
        return await refused(f"not at the menu before saving: {str(d)[:200]}", d)
    _status, d = await rest("POST", path, {"next_step_id": "save"})
    d = await answer_forms(d)
    if d.get("errors") or d.get("type") != "create_entry":
        return await refused(f"save: {d.get('errors') or str(d)[:200]}", d)
    return {**d, "seen": seen}
