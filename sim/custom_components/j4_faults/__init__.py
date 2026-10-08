"""J4's fault injector: test only, for the dedicated test Home Assistant alone.

What the in-process acceptance tests make happen with patches and seeded stores, made to happen
in a real Home Assistant, so J4 can run those scenarios there too (docs/plan-0.2.md, J4):

- ``monitor``: the plugin's own monitor fails, or works again (answer I);
- ``restart_with_stores``: the plugin's entry stopped, its stores replaced or removed — what a
  crash, a lost or damaged file, or another version leaves — and started again (V1, answer K);
- ``remove_options``: answers removed from a section of the plugin's options, as an entry made
  by an earlier version lacks them (answer K).

scripts/deploy_test.sh sends it to the test Home Assistant only; it is never part of the
plugin's release. It reaches into the plugin's coordinator, so it follows that code's names.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

DOMAIN = "j4_faults"
PLUGIN = "vtherm_smart_boiler"
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)
# The stores of the plugin's entry, by name: the entry store and the control store.
STORES = {"main": "", "control": ".control"}
_LOGGER = logging.getLogger(__name__)


def _coordinator_class() -> Any:
    try:
        module = importlib.import_module(f"custom_components.{PLUGIN}.coordinator")
    except ImportError as err:
        raise ServiceValidationError("The plugin is not loaded") from err
    return module.SmartBoilerCoordinator


def _plugin_entry(hass: HomeAssistant) -> ConfigEntry:
    entries = hass.config_entries.async_entries(PLUGIN)
    if len(entries) != 1:
        raise ServiceValidationError(f"Expected one entry of {PLUGIN}, found {len(entries)}")
    return entries[0]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The services; nothing changes until one is called."""
    original: dict[str, Any] = {}

    async def monitor(call: ServiceCall) -> None:
        cls = _coordinator_class()
        if call.data["failing"]:
            if "compute" not in original:
                original["compute"] = cls._compute

                def broken(self: Any, now: float) -> Any:
                    raise RuntimeError("j4_faults: the monitor cannot compute (test only)")

                cls._compute = broken
            _LOGGER.warning("Test only: the plugin's monitor fails from now on")
        elif "compute" in original:
            cls._compute = original.pop("compute")
            _LOGGER.warning("Test only: the plugin's monitor works again")

    async def restart_with_stores(call: ServiceCall) -> None:
        entry = _plugin_entry(hass)
        await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
        # Whatever the stopped entry still had in flight — its last saves — ends first, so it
        # cannot write over the stores replaced below.
        await hass.async_block_till_done()
        for name, suffix in STORES.items():
            store = Store[Any](
                hass, call.data.get(f"{name}_version", 1), f"{PLUGIN}.{entry.entry_id}{suffix}"
            )
            if call.data.get(f"{name}_removed"):
                await store.async_remove()
            elif name in call.data:
                await store.async_save(call.data[name])
        _LOGGER.warning("Test only: the plugin starts on replaced stores: %s", sorted(call.data))
        await hass.config_entries.async_set_disabled_by(entry.entry_id, None)

    async def remove_options(call: ServiceCall) -> None:
        entry = _plugin_entry(hass)
        section = call.data["section"]
        values = {
            k: v
            for k, v in (entry.options.get(section) or {}).items()
            if k not in call.data["keys"]
        }
        _LOGGER.warning(
            "Test only: %s removed from the plugin's %s options", call.data["keys"], section
        )
        hass.config_entries.async_update_entry(entry, options={**entry.options, section: values})
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(
        DOMAIN, "monitor", monitor, vol.Schema({vol.Required("failing"): cv.boolean})
    )
    store_fields: dict[Any, Any] = {}
    for name in STORES:
        store_fields[vol.Optional(name)] = dict
        store_fields[vol.Optional(f"{name}_version")] = vol.All(vol.Coerce(int), vol.Range(min=1))
        store_fields[vol.Optional(f"{name}_removed")] = cv.boolean
    hass.services.async_register(
        DOMAIN, "restart_with_stores", restart_with_stores, vol.Schema(store_fields)
    )
    hass.services.async_register(
        DOMAIN,
        "remove_options",
        remove_options,
        vol.Schema({vol.Required("section"): cv.string, vol.Required("keys"): [cv.string]}),
    )
    return True
