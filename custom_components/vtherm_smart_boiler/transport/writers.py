"""Writers: the only code that changes the boiler. They exist only while control is enabled.

Each writer knows the services it may call — the list a test checks. A write that fails raises
``WriteError``; the caller reports it and never assumes it applied.

OpenTherm Gateway facts (OTGW firmware documentation, research/2026-09-24-otgw-topologies-f3-f7.md):
a control-setpoint override of 8 °C or more lapses unless repeated within a minute; one between
1 and 7 °C never lapses and would lock out a thermostat for good if Home Assistant stopped, so it
is refused; 0 cancels the override (hand-back). The CH override applies only while a setpoint
override is active. The plugin never touches the DHW-enable override.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

from ..control_config import ControlOptions, HandBack, WritePath

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

OTGW_MIN_SETPOINT = 8.0  # below this (and above 0) an OTGW override never lapses
MAX_SETPOINT = 90.0


class WriteError(Exception):
    """A write did not go through."""


class Writer(Protocol):
    @property
    def services(self) -> frozenset[tuple[str, str]]: ...

    async def write_setpoint(self, value: float) -> None: ...

    async def write_heating(self, on: bool) -> None: ...

    async def hand_back(self) -> None: ...


def _checked(value: float, low: float) -> float:
    if not math.isfinite(value) or not low <= value <= MAX_SETPOINT:
        raise WriteError(f"setpoint {value} outside {low} to {MAX_SETPOINT}")
    return round(value, 1)


class _ServiceWriter:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def _call(self, domain: str, service: str, data: dict[str, object]) -> None:
        try:
            await self._hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # every failure is a failed write, reported upstream
            raise WriteError(f"{domain}.{service}: {err}") from err


class EntityWriter(_ServiceWriter):
    """A setpoint entity (number, input_number) and optionally a heating switch."""

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        if not options.setpoint_entity:
            raise ValueError("no setpoint entity")
        self._setpoint = options.setpoint_entity
        self._switch = options.ch_entity
        self._hand_back = options.hand_back
        self._hand_back_value = options.hand_back_value
        self._hand_back_entity = options.hand_back_entity

    @staticmethod
    def _domain(entity_id: str) -> str:
        return entity_id.split(".", 1)[0]

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        found = {(self._domain(self._setpoint), "set_value")}
        for entity in (self._switch, self._hand_back_entity):
            if entity:
                domain = self._domain(entity)
                found |= {(domain, "turn_on"), (domain, "turn_off")}
        return frozenset(found)

    async def write_setpoint(self, value: float) -> None:
        await self._call(
            self._domain(self._setpoint),
            "set_value",
            {"entity_id": self._setpoint, "value": _checked(value, 0.0)},
        )

    async def write_heating(self, on: bool) -> None:
        if not self._switch:
            raise WriteError("no heating switch")
        await self._call(
            self._domain(self._switch), "turn_on" if on else "turn_off", {"entity_id": self._switch}
        )

    async def hand_back(self) -> None:
        if self._hand_back is HandBack.VALUE:
            await self._call(
                self._domain(self._setpoint),
                "set_value",
                {"entity_id": self._setpoint, "value": self._hand_back_value},
            )
        elif self._hand_back is HandBack.SWITCH and self._hand_back_entity:
            await self._call(
                self._domain(self._hand_back_entity),
                "turn_off",
                {"entity_id": self._hand_back_entity},
            )
        # HandBack.TIMEOUT: stop writing; the device's own timeout hands back.


class OpenthermGwWriter(_ServiceWriter):
    """Built-in OTGW through Home Assistant's opentherm_gw services."""

    DOMAIN = "opentherm_gw"

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        if not options.gateway_id:
            raise ValueError("no gateway id")
        self._gateway = options.gateway_id

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            {(self.DOMAIN, "set_control_setpoint"), (self.DOMAIN, "set_central_heating_ovrd")}
        )

    async def write_setpoint(self, value: float) -> None:
        await self._call(
            self.DOMAIN,
            "set_control_setpoint",
            {"gateway_id": self._gateway, "temperature": _checked(value, OTGW_MIN_SETPOINT)},
        )

    async def write_heating(self, on: bool) -> None:
        await self._call(
            self.DOMAIN,
            "set_central_heating_ovrd",
            {"gateway_id": self._gateway, "ch_override": on},
        )

    async def hand_back(self) -> None:
        # 0 cancels the setpoint override; the CH override applies only alongside it.
        await self._call(
            self.DOMAIN, "set_control_setpoint", {"gateway_id": self._gateway, "temperature": 0}
        )


class OtgwMqttWriter(_ServiceWriter):
    """Built-in OTGW through its firmware's MQTT commands (``<top>/set/<node>/<command>``)."""

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        if not (options.mqtt_top and options.mqtt_node):
            raise ValueError("no MQTT topic")
        self._base = f"{options.mqtt_top.strip('/')}/set/{options.mqtt_node.strip('/')}"

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return frozenset({("mqtt", "publish")})

    async def _publish(self, command: str, payload: str) -> None:
        await self._call(
            "mqtt", "publish", {"topic": f"{self._base}/{command}", "payload": payload}
        )

    async def write_setpoint(self, value: float) -> None:
        await self._publish("ctrlsetpt", f"{_checked(value, OTGW_MIN_SETPOINT):.1f}")

    async def write_heating(self, on: bool) -> None:
        await self._publish("chenable", "1" if on else "0")

    async def hand_back(self) -> None:
        await self._publish("ctrlsetpt", "0")


def make_writer(hass: HomeAssistant, options: ControlOptions) -> Writer:
    if options.write_path is WritePath.ENTITY:
        return EntityWriter(hass, options)
    if options.write_path is WritePath.OPENTHERM_GW:
        return OpenthermGwWriter(hass, options)
    if options.write_path is WritePath.OTGW_MQTT:
        return OtgwMqttWriter(hass, options)
    raise ValueError("control is not configured")
