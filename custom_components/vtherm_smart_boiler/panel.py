"""The Boiler page in Home Assistant's sidebar (``docs/en/development/plans/plan-0.2-i10.md``).

The plugin serves its built page from ``frontend/`` and puts it in the sidebar for every user;
the switch "Boiler page in the sidebar" takes it away and puts it back. The sidebar's title is a
plain string, so it is read here from the page's own translations, in Home Assistant's language.
Without Home Assistant's frontend running — a minimal setup, the tests — nothing is registered,
and nothing else depends on it: the page only shows what the plugin already exposes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"
TRANSLATIONS_DIR = FRONTEND_DIR / "translations"
PANEL_MODULE = "vtherm-smart-boiler-panel.js"
PANEL_ELEMENT = "vtherm-smart-boiler-panel"  # the custom element the module defines
PANEL_URL_PATH = "vtherm-smart-boiler"  # the page's address: /vtherm-smart-boiler
PANEL_ICON = "mdi:water-boiler"
STATIC_URL = f"/{DOMAIN}_frontend"
FALLBACK_TITLE = "Boiler"  # only where no translation file can be read
_DATA = f"{DOMAIN}_panel"


def frontend_running(hass: HomeAssistant) -> bool:
    """Whether Home Assistant's frontend and HTTP server are up to take a page."""
    return "frontend" in hass.config.components and getattr(hass, "http", None) is not None


def sidebar_title(language: str) -> str:
    """The page's name in the sidebar in ``language`` ("pt-BR" falls back to "pt"), else in
    English. Reads files: run it in the executor."""
    for code in dict.fromkeys((language, language.split("-")[0], "en")):
        path = TRANSLATIONS_DIR / f"{code}.json"
        try:
            texts: Any = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        title = texts.get("panel", {}).get("title") if isinstance(texts, dict) else None
        if isinstance(title, str) and title.strip():
            return title
    return FALLBACK_TITLE


def module_version() -> str:
    """A short digest of the built page: its address changes with its content, so a browser
    never keeps an old copy after an update. Reads the file: run it in the executor."""
    try:
        return hashlib.sha256((FRONTEND_DIR / PANEL_MODULE).read_bytes()).hexdigest()[:12]
    except OSError:
        return "missing"


async def async_show_panel(hass: HomeAssistant, entry_id: str) -> bool:
    """Put the page in the sidebar, for every user; ``False`` where the frontend is not running.
    Serving the files is registered once per run of Home Assistant — it cannot be undone."""
    if not frontend_running(hass):
        _LOGGER.debug("Home Assistant's frontend is not running: no Boiler page")
        return False
    from homeassistant.components import frontend, panel_custom

    # Defined there; Home Assistant 2026.10 does not re-export it from the package yet.
    from homeassistant.components.http.server import StaticPathConfig

    data: dict[str, Any] = hass.data.setdefault(_DATA, {})
    if not data.get("served"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=True)]
        )
        data["served"] = True
    title = await hass.async_add_executor_job(sidebar_title, hass.config.language)
    version = await hass.async_add_executor_job(module_version)
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=title,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_URL}/{PANEL_MODULE}?v={version}",
        require_admin=False,  # everyone sees it; changes in it are an administrator's
        config={"entry_id": entry_id},
    )
    return True


@callback
def async_hide_panel(hass: HomeAssistant) -> None:
    """Take the page out of the sidebar; nothing where it is not there."""
    if not frontend_running(hass):
        return
    from homeassistant.components import frontend

    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
