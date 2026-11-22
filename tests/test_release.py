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
RELEASE = "0.2.3b1"  # decision 16's provisional first version (Z2); K5, K7 move it
# The newest VT (10.6.5) needs Home Assistant 2026.10.4 (its hacs.json): the plugin's minimum
# follows it (the user, 2026-11-17; 2026.9.0 from 2026-09-25).
MIN_HOME_ASSISTANT = "2026.10.4"


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
    """T12: the planned pre-release, 0.2.3b1, and the release after it, 0.2.3, are PEP 440,
    not SemVer (decision 16, provisional)."""
    for version in ("0.2.3b1", "0.2.3"):
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
    setup — accepted for the start order; the user guide's known limitations say so."""
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


def _release_problems(root: Path) -> list[str]:
    """What a release from ``root`` would wrongly carry: anything in ``custom_components/`` but
    the plugin, and a manifest of the test-only gateway stub or simulator under it."""
    components = root / "custom_components"
    problems = [
        f"{path.name} in custom_components"
        for path in sorted(components.iterdir())
        if path.name != "vtherm_smart_boiler" and path.name != "__pycache__"
    ]
    for manifest in sorted(components.rglob("manifest.json")):
        domain = _load(manifest).get("domain")
        if domain in ("opentherm_gw", "boiler_sim"):
            problems.append(f"{manifest.relative_to(root)}: {domain}")
    return problems


def test_the_release_holds_only_the_plugin() -> None:
    """TB-37: HACS installs what ``custom_components/`` holds — the plugin alone; the test-only
    ``opentherm_gw`` stub and ``boiler_sim`` stay in ``sim/`` (P-37). An ``opentherm_gw`` shipped
    there would override Home Assistant's own on the user's system."""
    assert _release_problems(ROOT) == []


def test_the_release_check_finds_a_stub(tmp_path: Path) -> None:
    """Negative: a stub copied in, or a gateway manifest under the plugin, is found."""
    plugin = tmp_path / "custom_components/vtherm_smart_boiler"
    plugin.mkdir(parents=True)
    (plugin / "manifest.json").write_text(json.dumps({"domain": "vtherm_smart_boiler"}))
    assert _release_problems(tmp_path) == []
    (plugin / "sub").mkdir()
    (plugin / "sub/manifest.json").write_text(json.dumps({"domain": "opentherm_gw"}))
    (tmp_path / "custom_components/boiler_sim").mkdir()
    assert _release_problems(tmp_path) == [
        "boiler_sim in custom_components",
        "custom_components/vtherm_smart_boiler/sub/manifest.json: opentherm_gw",
    ]


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


def test_ci_runs_the_core_tests_on_their_own_then_the_rest_in_parts() -> None:
    """P-120: CI runs the core tests without Home Assistant's pytest plugin — layer 1, "no Home
    Assistant", sockets closed — and every other test with it. Since 2026-11-18 side by side in
    parts, for each Home Assistant version: the core tests, test_acceptance.py, test_control.py
    and the rest, which leaves out exactly those three — every test once; coverage with branches
    in each part, no floor there, and the floor judged once, in the job the rulesets require,
    over the four parts combined, which it checks all passed."""
    workflow = _workflow("tests.yml")
    parts = workflow["jobs"]["parts"]
    assert parts["strategy"]["matrix"]["group"] == ["ha", "ha-minimum"]
    assert parts["strategy"]["matrix"]["part"] == ["core", "acceptance", "control", "rest"]
    run = next(step["run"] for step in parts["steps"] if "pytest" in step.get("run", ""))
    assert "coverage=(--cov --cov-branch --cov-report= --cov-fail-under=0)" in run

    def part(name: str) -> str:
        begin = run.index(f"{name})")
        return run[begin : run.index(";;", begin)]

    core = part("core")
    assert "-p no:homeassistant" in core
    assert "--disable-socket" in core
    assert core.rstrip().endswith("tests/core")
    assert part("acceptance").rstrip().endswith("tests/integration/test_acceptance.py")
    assert part("control").rstrip().endswith("tests/integration/test_control.py")
    rest = part("rest")
    for left_out in (
        "tests/core",
        "tests/integration/test_acceptance.py",
        "tests/integration/test_control.py",
    ):
        assert f"--ignore={left_out}" in rest
    for name in ("core", "acceptance", "control", "rest"):
        assert '"${coverage[@]}"' in part(name), name
        assert "-p no:homeassistant" not in part(name) or name == "core"
    required = workflow["jobs"]["tests"]
    assert required["needs"] == ["changes", "parts", "page"]  # the Boiler page's job too (I10.1)
    labels = [entry["label"] for entry in required["strategy"]["matrix"]["include"]]
    assert labels == [
        "Tests – supported Home Assistant version",
        "Tests – oldest supported Home Assistant version",
    ]
    checks = "\n".join(step.get("run", "") for step in required["steps"])
    assert "for part in core acceptance control rest" in checks
    assert '"$PAGE" != success' in checks
    assert "coverage combine" in checks
    assert "floors = {" in checks


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
    """PB-86: VT and SmartPI are fetched by the full commit, not by a tag that can move — in the
    shared test environment (`.github/actions/test-env`), which the parts and the newest-
    vtherm_api canary use as it is — and every action runs from a full commit, not from a branch
    or tag; only the repository's own action is used by its path."""
    import yaml

    commit = re.compile(r"[0-9a-f]{40}")
    action = yaml.safe_load(
        (ROOT / ".github/actions/test-env/action.yml").read_text(encoding="utf-8")
    )
    fetch = "\n".join(step.get("run", "") for step in action["runs"]["steps"])
    assert "archive/$commit.tar.gz" in fetch
    assert "refs/tags" not in fetch
    assert re.search(r"versatile_thermostat [0-9a-f]{40}", fetch)
    assert re.search(r"vtherm_smartpi [0-9a-f]{40}", fetch)
    tests = _workflow("tests.yml")
    for job in ("parts", "latest-vtherm-api"):
        local = [
            s for s in tests["jobs"][job]["steps"] if s.get("uses") == "./.github/actions/test-env"
        ]
        assert local, job
        assert all((s.get("with") or {}).get("vendor", "pinned") == "pinned" for s in local), job
    steps = [
        step
        for name in ("tests.yml", "validate.yml")
        for job in _workflow(name)["jobs"].values()
        for step in job["steps"]
    ]
    for step in steps + action["runs"]["steps"]:
        uses = step.get("uses")
        if uses is None or uses == "./.github/actions/test-env":
            continue
        assert commit.fullmatch(uses.rpartition("@")[2]), uses


def test_hacs_checks_the_brand() -> None:
    """P93: since Home Assistant 2026.3 the brand ships in the integration's ``brand/`` folder,
    which the HACS action checks — no longer ignored (the icon itself is R2)."""
    workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    assert "ignore:" not in workflow


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_the_brand_images_meet_home_assistants_sizes() -> None:
    """K1: the icon square at 256 and 512 pixels; the logo's shortest side 128-256 pixels, its
    @2x 256-512 (Home Assistant's brand rules)."""
    brand = ROOT / "custom_components/vtherm_smart_boiler/brand"
    assert _png_size(brand / "icon.png") == (256, 256)
    assert _png_size(brand / "icon@2x.png") == (512, 512)
    assert 128 <= min(_png_size(brand / "logo.png")) <= 256
    assert 256 <= min(_png_size(brand / "logo@2x.png")) <= 512


# --- translations -------------------------------------------------------------------------

# Keys hassfest checks as translation keys: lower case letters and digits, joined by single
# hyphens or underscores; slugs (entity domains, exception keys) take underscores only.
TRANSLATION_KEY = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
REFERENCE = re.compile(r"\[%key:[^%\]]+%\]")
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://|\bwww\.", re.IGNORECASE)

TOP_KEYS = {
    "title", "config", "options", "selector", "device", "entity", "exceptions", "issues",
    "services",  # I11.2: the action for automations
}  # fmt: skip
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
        for key, action in strings.get("services", {}).items():
            # hassfest: an action's name and description, and each field's (I11.2).
            self.key("services", key, SLUG)
            action = self.keys(f"services.{key}", action, {"name", "description", "fields"})
            for part in ("name", "description"):
                if part in action:
                    self.text(f"services.{key}.{part}", action[part], placeholders=False)
            for field, texts in action.get("fields", {}).items():
                where = f"services.{key}.fields.{field}"
                self.key(f"services.{key}.fields", field, SLUG)
                texts = self.keys(where, texts, {"name", "description", "example"})
                for part in ("name", "description"):
                    if part in texts:
                        self.text(f"{where}.{part}", texts[part], placeholders=False)
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


def test_ci_builds_the_boiler_page_as_committed() -> None:
    """I10.1 (``docs/en/development/plans/plan-0.2-i10.md``): CI installs the page's packages
    from the lock file, runs its tests, builds it — its types checked first — and fails where
    the files committed beside the plugin differ from what the source builds; with the Node.js
    version ``scripts/bootstrap_node.sh`` puts on the developer's machine."""
    import re

    workflow = _workflow("tests.yml")
    page = workflow["jobs"]["page"]
    assert page["needs"] == "changes"
    assert page["if"] == "needs.changes.outputs.only != 'true'"
    assert page["defaults"]["run"]["working-directory"] == "frontend"
    setup = next(s for s in page["steps"] if s.get("uses", "").startswith("actions/setup-node@"))
    script = (ROOT / "scripts" / "bootstrap_node.sh").read_text(encoding="utf-8")
    pinned = re.search(r'^VERSION="v([0-9.]+)"', script, re.MULTILINE)
    assert pinned is not None
    assert str(setup["with"]["node-version"]) == pinned.group(1)
    runs = [s.get("run", "") for s in page["steps"]]
    assert runs[2:5] == ["npm ci", "npm test", "npm run build"]
    assert "git status --porcelain -- ../custom_components/vtherm_smart_boiler/frontend" in runs[5]
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["build"] == "tsc --noEmit && vite build"
