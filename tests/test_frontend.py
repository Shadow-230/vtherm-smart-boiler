"""The Boiler page's files (``docs/en/development/plans/plan-0.2-i10.md``, I10.1): the built page
and its licenses ship with the plugin; its texts exist in every language with the same keys; the
sidebar title is read from them; and the page's packages are the ones the user consented to, at
exact versions (CLAUDE.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.vtherm_smart_boiler.panel import (
    FALLBACK_TITLE,
    FRONTEND_DIR,
    PANEL_ELEMENT,
    PANEL_MODULE,
    TRANSLATIONS_DIR,
    module_version,
    sidebar_title,
)

ROOT = Path(__file__).parent.parent
PACKAGE = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
# The user's consents of 2026-11-18: these packages and what they depend on, nothing else —
# Playwright for the page's screenshots only.
CONSENTED = {"lit", "typescript", "vite", "vitest", "playwright"}


def flatten(texts: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in texts.items():
        if isinstance(value, dict):
            out.update(flatten(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


def texts(language: str) -> dict[str, str]:
    return flatten(json.loads((TRANSLATIONS_DIR / f"{language}.json").read_text("utf-8")))


def test_the_built_page_ships_with_the_plugin() -> None:
    module = (FRONTEND_DIR / PANEL_MODULE).read_text(encoding="utf-8")
    assert f'"{PANEL_ELEMENT}"' in module  # the element the sidebar asks for
    assert len(module_version()) == 12


def test_the_bundled_packages_licenses_ship_with_it() -> None:
    licenses = (FRONTEND_DIR / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
    assert "lit 3.3.3 (BSD-3-Clause)" in licenses
    assert "Redistribution and use in source and binary forms" in licenses


def test_the_page_has_english_and_polish() -> None:
    assert sorted(p.stem for p in TRANSLATIONS_DIR.glob("*.json")) == ["en", "pl"]


@pytest.mark.parametrize("language", ["pl"])
def test_same_keys_in_every_language(language: str) -> None:
    source, other = texts("en"), texts(language)
    assert sorted(other) == sorted(source)
    assert all(value.strip() for value in other.values())


def test_the_sidebar_title_is_in_home_assistants_language() -> None:
    assert sidebar_title("pl") == "Kocioł"
    assert sidebar_title("pl-PL") == "Kocioł"
    assert sidebar_title("en") == "Boiler"
    assert sidebar_title("de") == "Boiler"  # no German: English
    assert FALLBACK_TITLE == texts("en")["panel.title"]


def test_the_page_uses_only_the_consented_packages_at_exact_versions() -> None:
    direct = {**PACKAGE.get("dependencies", {}), **PACKAGE.get("devDependencies", {})}
    assert set(direct) == CONSENTED
    for name, version in direct.items():
        assert version[0].isdigit(), f"{name} {version}: an exact version"
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    root = lock["packages"][""]
    assert {**root.get("dependencies", {}), **root.get("devDependencies", {})} == direct


def test_an_unreadable_translation_falls_back(tmp_path: Path, monkeypatch) -> None:
    """A file that is not JSON, not an object, or has no title is passed over; with none left
    the fixed English title stands."""
    from custom_components.vtherm_smart_boiler import panel

    (tmp_path / "pl.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "fr.json").write_text("[]", encoding="utf-8")
    (tmp_path / "en.json").write_text('{"panel": {"title": "  "}}', encoding="utf-8")
    monkeypatch.setattr(panel, "TRANSLATIONS_DIR", tmp_path)
    assert panel.sidebar_title("pl") == FALLBACK_TITLE
    assert panel.sidebar_title("fr") == FALLBACK_TITLE
    (tmp_path / "en.json").write_text('{"panel": {"title": "Boiler room"}}', encoding="utf-8")
    assert panel.sidebar_title("pl") == "Boiler room"


def test_a_missing_page_gets_a_version_anyway(tmp_path: Path, monkeypatch) -> None:
    from custom_components.vtherm_smart_boiler import panel

    monkeypatch.setattr(panel, "FRONTEND_DIR", tmp_path)
    assert panel.module_version() == "missing"
