"""The vendored VT and SmartPI integrations load in the in-process Home Assistant."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .conftest import requires_vendor

pytestmark = [requires_vendor, pytest.mark.usefixtures("enable_custom_integrations")]


@pytest.mark.parametrize(
    ("domain", "version"),
    [("versatile_thermostat", "10.4.0"), ("vtherm_smartpi", "0.0.0")],
)
async def test_vendored_integration_loads(hass: HomeAssistant, domain: str, version: str) -> None:
    integration = await async_get_integration(hass, domain)
    assert str(integration.version) == version
    assert await integration.async_get_component() is not None
