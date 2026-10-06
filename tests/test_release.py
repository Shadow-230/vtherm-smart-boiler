"""What Home Assistant's hassfest and HACS check before a release (P18, P54, P90, P93, P94, P98).

hassfest is not part of the installed Home Assistant package, so its rules for the manifest, the
translations and the icons (Home Assistant 2026.9.3) are written here from what they require;
HACS's from its documentation.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import string
import subprocess
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
RELEASE = "0.2.2b1"  # decision 16's provisional first version (Z2); K5, K7 move it
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


# What Home Assistant's loader accepts for a custom integration's version (a pre-release such
# as 0.2.1b1 is PEP 440).
VERSION_STRATEGIES = [
    AwesomeVersionStrategy.CALVER,
    AwesomeVersionStrategy.SEMVER,
    AwesomeVersionStrategy.SIMPLEVER,
    AwesomeVersionStrategy.BUILDVER,
    AwesomeVersionStrategy.PEP440,
]


def test_manifest_version_is_this_release() -> None:
    """P94: Home Assistant refuses a custom integration without a valid version."""
    assert MANIFEST["version"] == RELEASE
    AwesomeVersion(MANIFEST["version"], ensure_strategy=VERSION_STRATEGIES)


def test_a_pre_release_version_is_one_home_assistant_accepts() -> None:
    """T12: the planned pre-release, 0.2.2b1, and the release after it, 0.2.2, are PEP 440,
    not SemVer (decision 16, provisional)."""
    for version in ("0.2.2b1", "0.2.2"):
        AwesomeVersion(version, ensure_strategy=VERSION_STRATEGIES)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_session_summaries_are_ignored() -> None:
    """P-108: a session summary is the user's own file and never enters the repository."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "session-summary-x.md"],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0


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
    from custom_components.vtherm_smart_boiler.transport.writers import OPENTHERM_GW
    from custom_components.vtherm_smart_boiler.vtherm_link import SMARTPI_DOMAIN

    used = {"mqtt", OPENTHERM_GW, "recorder", SMARTPI_DOMAIN, VT_DOMAIN, "weather"}
    assert used <= set(MANIFEST["after_dependencies"])


def test_gateway_integrations_stay_optional_after_dependencies() -> None:
    """PB-61: mqtt and opentherm_gw are after-dependencies, not dependencies: they start
    first where they are set up (the start order the write paths need), and the plugin sets up
    without them. Home Assistant still installs an after-dependency's own requirements (its
    ``requirements.py`` walks ``dependencies + after_dependencies``), so on an installation
    without network a failed pip install of their client packages would block the plugin's
    setup — accepted for the start order (a README note for non-container installs is open)."""
    import inspect

    from homeassistant import requirements

    source = inspect.getsource(requirements.RequirementsManager._async_process_integration)
    assert "integration.dependencies + integration.after_dependencies" in source
    for domain in ("mqtt", "opentherm_gw"):
        assert domain in MANIFEST["after_dependencies"]
        assert domain not in MANIFEST["dependencies"]


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


def test_ci_runs_the_core_tests_on_their_own_then_the_rest() -> None:
    """P-120: CI runs the core tests without Home Assistant's pytest plugin — layer 1, "no Home
    Assistant" — then every other test with it, coverage with branches over both, its floor
    judged once at the end; no step runs them all in one go."""
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8"))
    runs = [step.get("run", "") for step in workflow["jobs"]["tests"]["steps"]]
    tests = [run for run in runs if "pytest" in run]
    assert len(tests) == 2
    core, rest = tests
    assert "-p no:homeassistant" in core
    assert core.rstrip().endswith("tests/core")
    assert "--disable-socket" in core  # no network, as Home Assistant's plugin ensures
    assert "--cov-fail-under=0" in core  # a partial run: the floor is judged after both
    assert "--ignore=tests/core" in rest
    assert "--cov-append" in rest
    assert "--cov-fail-under" not in rest  # pyproject's floor applies
    assert all("--cov --cov-branch" in run for run in tests)


def _workflow(name: str) -> dict[Any, Any]:
    import yaml

    loaded: dict[Any, Any] = yaml.safe_load(
        (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    )
    return loaded


def test_ci_canaries_run_weekly_on_demand_and_check_types() -> None:
    """PB-85: the upstream canaries run on a weekly schedule and on demand, not only on a push;
    the newest-vtherm_api job runs mypy; a job runs the newest VT and SmartPI releases."""
    workflow = _workflow("tests.yml")
    triggers = workflow[True]  # YAML 1.1 reads the key ``on`` as true
    assert triggers["schedule"]
    assert "workflow_dispatch" in triggers
    jobs = workflow["jobs"]
    for job in ("latest-vtherm-api", "latest-vt-smartpi"):
        runs = [step.get("run", "") for step in jobs[job]["steps"]]
        assert "mypy" in [run.strip() for run in runs]
        assert any("pytest" in run for run in runs)
    newest = "\n".join(step.get("run", "") for step in jobs["latest-vt-smartpi"]["steps"])
    assert "releases/latest" in newest
    assert "vtherm-api" in newest
    assert "workflow_dispatch" in _workflow("validate.yml")[True]


def test_ci_fetches_upstream_by_full_commit_and_pins_actions() -> None:
    """PB-86: VT and SmartPI are fetched by the full commit, not by a tag that can move, and
    every action runs from a full commit, not from a branch or tag."""
    commit = re.compile(r"[0-9a-f]{40}")
    tests = _workflow("tests.yml")
    for job in ("tests", "latest-vtherm-api"):
        fetch = "\n".join(step.get("run", "") for step in tests["jobs"][job]["steps"])
        assert "archive/$commit.tar.gz" in fetch
        assert "refs/tags" not in fetch
        assert re.search(r"versatile_thermostat [0-9a-f]{40}", fetch)
        assert re.search(r"vtherm_smartpi [0-9a-f]{40}", fetch)
    for name in ("tests.yml", "validate.yml"):
        for job in _workflow(name)["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert commit.fullmatch(step["uses"].rpartition("@")[2]), step["uses"]


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

TOP_KEYS = {"title", "config", "options", "selector", "device", "entity", "exceptions", "issues"}
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
        if "[%" in value or "%]" in value:
            # P-128: Home Assistant resolves ``[%key:…%]`` references only in a core
            # integration's strings.json, when it builds its translations; a custom
            # integration's translation files are read as they are, so any reference — even a
            # whole value — would reach the user as its raw text.
            kind = "a whole-value reference" if REFERENCE.fullmatch(value) else "a reference"
            self.problems.append(f"{where}: {kind}, which Home Assistant leaves unresolved here")
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
        for key, device in strings.get("device", {}).items():
            # hassfest: a device's translated name only (verified 2026-10-06, PB-83).
            self.key("device", key)
            device = self.keys(f"device.{key}", device, {"name"})
            if "name" in device:
                self.text(f"device.{key}.name", device["name"], placeholders=False)
        for key, exception in strings.get("exceptions", {}).items():
            self.key("exceptions", key, SLUG)
            exception = self.keys(f"exceptions.{key}", exception, {"message"})
            if "message" in exception:
                self.text(f"exceptions.{key}.message", exception["message"])
        for key, issue in strings.get("issues", {}).items():
            where = f"issues.{key}"
            issue = self.keys(where, issue, {"title", "description", "fix_flow"})
            self.text(f"{where}.title", issue.get("title"))
            if ("description" in issue) == ("fix_flow" in issue):
                self.problems.append(f"{where}: a description or a fix flow, one of the two")
            if "description" in issue:
                self.text(f"{where}.description", issue["description"])
            if "fix_flow" in issue:
                self.flow(f"{where}.fix_flow", issue["fix_flow"])
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
        "issues": {
            "i": {"title": "Mixed [%key:common::x%] text", "description": "ok"},
            "j": {"title": "[%key:common::state::on%]", "description": "ok"},
        },
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
        "i.title: a reference, which Home Assistant leaves unresolved here",
        "j.title: a whole-value reference, which Home Assistant leaves unresolved here",
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
