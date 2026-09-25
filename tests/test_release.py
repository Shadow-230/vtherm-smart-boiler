"""What Home Assistant's hassfest and HACS check before a release (P18, P54, P90, P93, P94, P98).

hassfest is not part of the installed Home Assistant package, so its rules for the manifest, the
translations and the icons (Home Assistant 2026.9.3) are written here from what they require;
HACS's from its documentation.
"""

from __future__ import annotations

import ast
import json
import re
import string
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
from awesomeversion import AwesomeVersion, AwesomeVersionStrategy
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/vtherm_smart_boiler"
TRANSLATIONS = sorted((COMPONENT / "translations").glob("*.json"))
RELEASE = "0.2.1"
MIN_HOME_ASSISTANT = "2026.9.0"  # the version tested (the user, 2026-09-25)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


MANIFEST = _load(COMPONENT / "manifest.json")

# --- manifest -----------------------------------------------------------------------------


def test_manifest_keys_are_in_hassfest_order() -> None:
    """``domain`` and ``name`` first, then the rest alphabetically."""
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_manifest_holds_what_a_custom_integration_needs() -> None:
    assert MANIFEST["domain"] == COMPONENT.name
    assert MANIFEST["name"]
    assert isinstance(MANIFEST["codeowners"], list)
    assert all(isinstance(owner, str) for owner in MANIFEST["codeowners"])
    assert MANIFEST["iot_class"] in {
        "assumed_state",
        "calculated",
        "cloud_polling",
        "cloud_push",
        "local_polling",
        "local_push",
    }
    assert MANIFEST["integration_type"] in {
        "device",
        "entity",
        "hardware",
        "helper",
        "hub",
        "service",
        "system",
    }
    assert MANIFEST["config_flow"] is True
    assert (COMPONENT / "config_flow.py").is_file()
    for key in ("dependencies", "after_dependencies", "requirements"):
        assert MANIFEST[key] == sorted(set(MANIFEST[key])), key


def test_manifest_version_is_this_release() -> None:
    """P94: Home Assistant refuses a custom integration without a valid version."""
    assert MANIFEST["version"] == RELEASE
    AwesomeVersion(MANIFEST["version"], ensure_strategy=[AwesomeVersionStrategy.SEMVER])


def test_requires_the_vtherm_api_its_contract_was_checked_on() -> None:
    assert MANIFEST["requirements"] == ["vtherm_api>=0.5.0"]


@pytest.mark.xfail(strict=True, reason="K5: the repository does not exist yet (the user)")
def test_manifest_links_to_the_repository() -> None:
    """hassfest needs ``documentation``, HACS ``issue_tracker`` and ``codeowners`` too."""
    assert MANIFEST["documentation"].startswith("https://")
    assert MANIFEST["issue_tracker"].startswith("https://")
    assert MANIFEST["codeowners"]


def test_integrations_it_uses_are_set_up_before_it() -> None:
    """P90: when present, the integrations it reads or calls start first."""
    from custom_components.vtherm_smart_boiler.const import VT_DOMAIN
    from custom_components.vtherm_smart_boiler.control import SMARTPI_DOMAIN
    from custom_components.vtherm_smart_boiler.transport.writers import OPENTHERM_GW

    used = {"mqtt", OPENTHERM_GW, "recorder", SMARTPI_DOMAIN, VT_DOMAIN, "weather"}
    assert used <= set(MANIFEST["after_dependencies"])


def _imported_modules(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def test_imported_integrations_are_declared() -> None:
    """hassfest: code from another integration needs it among the (after) dependencies;
    entity platforms excepted."""
    allowed = (
        {platform.value for platform in Platform}
        | set(MANIFEST["dependencies"])
        | set(MANIFEST["after_dependencies"])
    )
    found: set[tuple[str, str]] = set()
    for path in COMPONENT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imported_modules(tree):
            parts = module.split(".")
            if parts[:2] == ["homeassistant", "components"] and len(parts) > 2:
                found.add((path.name, parts[2]))
    assert found, "the walk found no imports"
    assert sorted(item for item in found if item[1] not in allowed) == []


# --- HACS ---------------------------------------------------------------------------------


def test_hacs_manifest() -> None:
    """P54: HACS offers the release only from the Home Assistant version it was tested on."""
    hacs = _load(ROOT / "hacs.json")
    allowed = {
        "name",
        "content_in_root",
        "zip_release",
        "filename",
        "hide_default_branch",
        "country",
        "homeassistant",
        "hacs",
        "persistent_directory",
    }
    assert set(hacs) <= allowed
    assert hacs["name"] == MANIFEST["name"]
    assert hacs["homeassistant"] == MIN_HOME_ASSISTANT
    AwesomeVersion(hacs["homeassistant"], ensure_strategy=[AwesomeVersionStrategy.CALVER])


def test_hacs_checks_the_brand() -> None:
    """P93: since Home Assistant 2026.3 the brand ships in the integration's ``brand/`` folder,
    which the HACS action checks — no longer ignored (the icon itself is R2)."""
    workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    assert "ignore:" not in workflow


# --- translations -------------------------------------------------------------------------

# Keys hassfest checks as translation keys: lower case letters and digits, joined by single
# hyphens or underscores; slugs (entity domains, exception keys) take underscores only.
TRANSLATION_KEY = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
REFERENCE = re.compile(r"\[%key:[^%\]]+%\]")
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://|\bwww\.", re.IGNORECASE)

TOP_KEYS = {"title", "config", "options", "selector", "entity", "exceptions", "issues"}
FLOW_KEYS = {"step", "error", "abort", "progress", "create_entry"}
STEP_KEYS = {
    "title",
    "description",
    "data",
    "data_description",
    "menu_options",
    "menu_option_descriptions",
    "submit",
    "sections",
}
SELECTOR_KEYS = {"choices", "options", "unit_of_measurement", "fields"}
ENTITY_KEYS = {"name", "state", "state_attributes", "unit_of_measurement"}
ATTRIBUTE_KEYS = {"name", "state"}


class _Checker:
    """Collects every break of hassfest's translation rules, with where it is."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def keys(self, where: str, mapping: object, allowed: set[str]) -> dict[str, Any]:
        if not isinstance(mapping, dict):
            self.problems.append(f"{where}: not an object")
            return {}
        if extra := sorted(set(mapping) - allowed):
            self.problems.append(f"{where}: unknown keys {extra}")
        return mapping

    def key(self, where: str, key: str, form: re.Pattern[str] = TRANSLATION_KEY) -> None:
        if not form.fullmatch(key):
            self.problems.append(f"{where}: key {key!r} is not in translation-key form")

    def text(self, where: str, value: object, placeholders: bool = True) -> None:
        if not isinstance(value, str) or not value:
            self.problems.append(f"{where}: not a text")
            return
        try:
            cv.string_with_no_html(value)
        except vol.Invalid:
            self.problems.append(f"{where}: reads as HTML")
        if value != value.strip():
            self.problems.append(f"{where}: leading or trailing space")
        if re.search(r"'\{\w+\}'", value):
            self.problems.append(f"{where}: a placeholder in single quotes")
        try:
            fields = [field for _, field, _, _ in string.Formatter().parse(value) if field]
        except ValueError:
            self.problems.append(f"{where}: an unmatched brace")
            fields = []
        if fields and not placeholders:
            self.problems.append(f"{where}: placeholders are not allowed here")
        for field in fields:
            if not field.isidentifier():
                self.problems.append(f"{where}: placeholder {field!r} is not an identifier")
        if ("[%" in value or "%]" in value) and not REFERENCE.fullmatch(value):
            self.problems.append(f"{where}: a reference mixed with text")
        if URL.search(value):
            self.problems.append(f"{where}: a URL (use a placeholder)")

    def texts(self, where: str, mapping: object, placeholders: bool = True) -> None:
        if not isinstance(mapping, dict):
            self.problems.append(f"{where}: not an object")
            return
        for key, value in mapping.items():
            self.text(f"{where}.{key}", value, placeholders)

    def flow(self, where: str, flow: object) -> None:
        flow = self.keys(where, flow, FLOW_KEYS)
        steps = flow.get("step")
        if not isinstance(steps, dict):
            self.problems.append(f"{where}.step: not an object")
            steps = {}
        for step_id, step in steps.items():
            at = f"{where}.step.{step_id}"
            step = self.keys(at, step, STEP_KEYS)
            for key in ("title", "description", "submit"):
                if key in step:
                    self.text(f"{at}.{key}", step[key])
            for key in ("data", "data_description", "menu_options", "menu_option_descriptions"):
                if key in step:
                    self.texts(f"{at}.{key}", step[key])
        for key in FLOW_KEYS - {"step"}:
            if key in flow:
                self.texts(f"{where}.{key}", flow[key])

    def strings(self, strings: object) -> list[str]:
        strings = self.keys("", strings, TOP_KEYS)
        for flow in ("config", "options"):
            if flow in strings:
                self.flow(flow, strings[flow])
        for name, selector in strings.get("selector", {}).items():
            self.key("selector", name, SLUG)
            selector = self.keys(f"selector.{name}", selector, SELECTOR_KEYS)
            for part in ("choices", "options", "unit_of_measurement"):
                for key, value in selector.get(part, {}).items():
                    self.key(f"selector.{name}.{part}", key)
                    self.text(f"selector.{name}.{part}.{key}", value)
        for domain, entities in strings.get("entity", {}).items():
            self.key("entity", domain, SLUG)
            for key, entity in entities.items():
                at = f"entity.{domain}.{key}"
                self.key(f"entity.{domain}", key)
                entity = self.keys(at, entity, ENTITY_KEYS)
                if "name" in entity:
                    self.text(f"{at}.name", entity["name"])
                if "unit_of_measurement" in entity:
                    self.text(f"{at}.unit_of_measurement", entity["unit_of_measurement"], False)
                for state, value in entity.get("state", {}).items():
                    self.key(f"{at}.state", state)
                    self.text(f"{at}.state.{state}", value, placeholders=False)
                for attribute, texts in entity.get("state_attributes", {}).items():
                    where = f"{at}.state_attributes.{attribute}"
                    self.key(f"{at}.state_attributes", attribute)
                    texts = self.keys(where, texts, ATTRIBUTE_KEYS)
                    if "name" in texts:
                        self.text(f"{where}.name", texts["name"], placeholders=False)
                    for state, value in texts.get("state", {}).items():
                        self.key(f"{where}.state", state)
                        self.text(f"{where}.state.{state}", value, placeholders=False)
        for key, exception in strings.get("exceptions", {}).items():
            self.key("exceptions", key, SLUG)
            exception = self.keys(f"exceptions.{key}", exception, {"message"})
            if "message" in exception:
                self.text(f"exceptions.{key}.message", exception["message"])
        for key, issue in strings.get("issues", {}).items():
            issue = self.keys(f"issues.{key}", issue, {"title", "description"})
            self.text(f"issues.{key}.title", issue.get("title"))
            self.text(f"issues.{key}.description", issue.get("description"))
        return self.problems


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda path: path.name)
def test_translations_follow_hassfest_rules(path: Path) -> None:
    """P18, P98: no HTML (``<prefix>`` reads as a tag), no URLs, no stray spaces or braces,
    placeholders only where Home Assistant fills them, keys in translation-key form."""
    assert _Checker().strings(_load(path)) == []


def test_the_checker_catches_what_hassfest_rejects() -> None:
    """The rules above are not vacuous: each break is reported."""
    broken = {
        "config": {
            "step": {
                "user": {
                    "title": "Topic <prefix>/set",
                    "description": " Leading space",
                    "data": {"a": "See https://example.org", "b": "Quoted '{name}'"},
                    "data_descriptions": {},
                }
            }
        },
        "entity": {
            "sensor": {
                "Bad-Key": {"name": "x", "state": {"on": "On {value}"}},
            }
        },
        "exceptions": {"e": {"message": "Unmatched { brace"}},
        "issues": {"i": {"title": "Mixed [%key:common::x%] text", "description": "ok"}},
    }
    problems = "\n".join(_Checker().strings(broken))
    for expected in (
        "user.title: reads as HTML",
        "user.description: leading or trailing space",
        "data.a: a URL",
        "data.b: a placeholder in single quotes",
        "unknown keys ['data_descriptions']",
        "key 'Bad-Key' is not in translation-key form",
        "state.on: placeholders are not allowed here",
        "message: an unmatched brace",
        "i.title: a reference mixed with text",
    ):
        assert expected in problems, expected


# --- icons --------------------------------------------------------------------------------


def test_icons_follow_hassfest_rules() -> None:
    """Material Design icons only; a state icon differs from the default it replaces."""
    icons = _load(COMPONENT / "icons.json")
    checker = _Checker()
    checker.keys("", icons, {"entity"})

    def icon(where: str, value: object) -> None:
        if not isinstance(value, str) or not value.startswith("mdi:"):
            checker.problems.append(f"{where}: not a Material Design icon")

    for domain, entities in icons.get("entity", {}).items():
        checker.key("entity", domain, SLUG)
        for key, entry in entities.items():
            at = f"entity.{domain}.{key}"
            checker.key(f"entity.{domain}", key)
            entry = checker.keys(at, entry, {"default", "state"})
            icon(f"{at}.default", entry.get("default"))
            for state, value in entry.get("state", {}).items():
                checker.key(f"{at}.state", state)
                icon(f"{at}.state.{state}", value)
                if value == entry.get("default"):
                    checker.problems.append(f"{at}.state.{state}: the same as the default")
    assert checker.problems == []
