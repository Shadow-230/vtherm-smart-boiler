"""The stub gateway's config flow: one entry for the simulated gateway, its data the gateway's
ID as the real integration stores it (``{"id": <gateway ID>}``)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from . import DOMAIN, hub_of


class SimGatewayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Confirm, and the simulated gateway is set up."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        hub = hub_of(self.hass)
        if hub is None:
            return self.async_abort(reason="no_simulator")
        gateway_id = hub.gateway_id
        await self.async_set_unique_id(gateway_id)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                description_placeholders={"gateway_id": gateway_id},
            )
        return self.async_create_entry(
            title=f"Simulated gateway {gateway_id}", data={"id": gateway_id}
        )
