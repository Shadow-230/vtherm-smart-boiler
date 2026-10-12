"""I8 (decision H): the control options' chain of forms became five menu items, each one form
that saves to the menu. Tests written for the chain answer its forms in its order; these
helpers walk the items as the chain went: after an item, the next one shown opens as the
chain's next form did, and what moved between forms goes to the form that asks it now."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.vtherm_smart_boiler.config_flow import CONTROL_ITEMS, section_of

# What a flow's control forms were given that their form no longer asks, kept for the form
# that asks it now — by flow; and each flow's last control answer.
_KEPT: dict[str, dict[str, Any]] = {}
_LAST: dict[str, dict[str, Any]] = {}
# The item that asks each key that moved (I8.9a): the comfort correction to the curve, VT's
# activation delay to the behaviour, frost protection to its own item.
_HOME = {
    "comfort_correction": "control_curve",
    "comfort_correction_max_k": "control_curve",
    "activation_delay_s": "control_behaviour",
    "frost_limit": "control_frost",
    "frost_release": "control_frost",
    "frost_zone": "control_frost",
}


def is_control_form(result: dict[str, Any]) -> bool:
    return result.get("type") is FlowResultType.FORM and str(result.get("step_id", "")).startswith(
        "control"
    )


def _fields(result: dict[str, Any]) -> set[str]:
    return {str(marker) for marker in result["data_schema"].schema}


def answer(result: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """A control form's answer: the keys it asks, with those kept for it; the others kept for
    the form that asks them now."""
    if not is_control_form(result):
        return data
    kept = _KEPT.setdefault(result["flow_id"], {})
    asked = _fields(result)
    given = {k: kept.pop(k) for k in list(kept) if k in asked and k not in data}
    kept.update({k: v for k, v in data.items() if k not in asked and k != "next_step_id"})
    sent = given | {k: v for k, v in data.items() if k in asked or k == "next_step_id"}
    _LAST[result["flow_id"]] = sent
    return sent


async def again(manager: Any, result: dict[str, Any], answered: str) -> dict[str, Any]:
    """A control form shown again with the fields its answer revealed (I8, decision A2): the
    test's answer held them; answered again with it, as a user fills the new fields in."""
    while (
        is_control_form(result)
        and result["step_id"] == answered
        and not result.get("errors")
        and any(k in _fields(result) for k in _KEPT.get(result["flow_id"], {}))
    ):
        last = {k: v for k, v in _LAST.get(result["flow_id"], {}).items() if k != "next_step_id"}
        result = await manager.async_configure(result["flow_id"], answer(result, last))
    return result


def form_values(result: dict[str, Any]) -> dict[str, Any]:
    """What a form shows: each field's default, else its suggested value."""
    values: dict[str, Any] = {}
    for marker in result["data_schema"].schema:
        default = marker.default
        if default is not vol.UNDEFINED:
            values[str(marker)] = default() if callable(default) else default
        elif isinstance(marker.description, dict) and "suggested_value" in marker.description:
            values[str(marker)] = marker.description["suggested_value"]
    return values


def _taken(result: dict[str, Any]) -> dict[str, Any]:
    kept = _KEPT.setdefault(result["flow_id"], {})
    asked = _fields(result)
    return {k: kept.pop(k) for k in list(kept) if k in asked}


def no_step_of_its_own(result: dict[str, Any], menu: list[str]) -> bool:
    """A form the chain had no step for, its fields another form's: frost protection (the
    curve's or the relay behaviour's), and the behaviour of full control at the simple level
    (the curve's activation delay)."""
    step = result["step_id"]
    if step == "control_frost":
        return True
    return (
        step == "control_behaviour"
        and _fields(result) == {"activation_delay_s"}
        and "control_curve" in menu
    )


async def answer_shown(manager: Any, result: dict[str, Any]) -> dict[str, Any]:
    """A control form answered with what it shows and what was kept for it."""
    return await manager.async_configure(result["flow_id"], form_values(result) | _taken(result))


async def after(manager: Any, result: dict[str, Any], answered: str) -> dict[str, Any]:
    """The menu after the control form ``answered``: the next control items shown open as the
    chain went on — a form the chain showed is returned; one it had no step for is answered
    with what it shows and what was kept for it. At the end, a key kept for an item the walk
    passed — the comfort correction, given with the behaviour, is the curve's now — is
    answered in that item."""
    if result.get("type") is not FlowResultType.MENU or not answered.startswith("control"):
        return result
    flow_id = result["flow_id"]
    order = list(CONTROL_ITEMS)
    for item in order[order.index(section_of(answered)) + 1 :]:
        if result.get("type") is not FlowResultType.MENU:
            return result
        menu = list(result["menu_options"])
        if item not in menu:
            continue
        result = await manager.async_configure(flow_id, {"next_step_id": item})
        if result.get("type") is FlowResultType.FORM and no_step_of_its_own(result, menu):
            result = await answer_shown(manager, result)
            continue
        return result
    return await leftovers(manager, result)


async def leftovers(manager: Any, result: dict[str, Any]) -> dict[str, Any]:
    """A key kept for an item the walk passed — the comfort correction, given with the
    behaviour, is the curve's now — answered in that item, from the menu."""
    flow_id = result["flow_id"]
    kept = _KEPT.get(flow_id, {})
    for item in dict.fromkeys(_HOME[k] for k in list(kept) if k in _HOME):
        if result.get("type") is not FlowResultType.MENU or item not in result["menu_options"]:
            continue
        result = await manager.async_configure(flow_id, {"next_step_id": item})
        if result.get("type") is FlowResultType.FORM:
            result = await answer_shown(manager, result)
    return result


def chained(manager: Any) -> Any:
    """``manager.async_configure`` walking on as the chain did after a control form."""

    async def configure(flow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        step = str(manager.async_get(flow_id).get("step_id", ""))
        current = {"type": FlowResultType.FORM, "flow_id": flow_id, "step_id": step}
        if step.startswith("control"):
            current["data_schema"] = manager._progress[flow_id].cur_step["data_schema"]
        result = await manager.async_configure(flow_id, answer(current, data))
        if "next_step_id" in data:
            return result
        return await after(manager, await again(manager, result, step), step)

    return configure
