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

import asyncio
import math
from typing import TYPE_CHECKING, Protocol

from ..control_config import ControlOptions, HandBack, WritePath

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

OTGW_MIN_SETPOINT = 8.0  # below this (and above 0) an OTGW override never lapses
MAX_SETPOINT = 90.0
WRITE_TIMEOUT_S = 10.0  # a service call that hangs longer counts as failed
OPENTHERM_GW = "opentherm_gw"
OTGW_SERVICES = frozenset(
    {(OPENTHERM_GW, "set_control_setpoint"), (OPENTHERM_GW, "set_central_heating_ovrd")}
)


class WriteError(Exception):
    """A write did not go through."""


class Writer(Protocol):
    @property
    def services(self) -> frozenset[tuple[str, str]]: ...

    async def write_setpoint(self, value: float) -> None: ...

    async def write_heating(self, on: bool) -> None: ...

    async def hand_back(self, full: bool = False) -> None:
        """Give control back; ``full`` also clears what an earlier session may have left."""
        ...


def _checked(value: float, low: float) -> float:
    if not math.isfinite(value) or not low <= value <= MAX_SETPOINT:
        raise WriteError(f"setpoint {value} outside {low} to {MAX_SETPOINT}")
    return round(value, 1)


class _ServiceWriter:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def _call(self, domain: str, service: str, data: dict[str, object]) -> None:
        try:
            async with asyncio.timeout(WRITE_TIMEOUT_S):
                await self._hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # every failure is a failed write, reported upstream
            raise WriteError(f"{domain}.{service}: {err!r}") from err


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def writer_services(options: ControlOptions) -> frozenset[tuple[str, str]]:
    """Every service a writer for these options may call; empty when control is not set up."""
    path = options.write_path
    if path is WritePath.OPENTHERM_GW:
        return OTGW_SERVICES
    if path is WritePath.OTGW_MQTT:
        return frozenset({("mqtt", "publish")})
    if path is not WritePath.ENTITY or not options.setpoint_entity:
        return frozenset()
    found = {(_domain(options.setpoint_entity), "set_value")}
    switches = [options.ch_entity if options.loop.ch_writes else None]
    if options.hand_back is HandBack.SWITCH:
        switches.append(options.hand_back_entity)
    for entity in switches:
        if entity:
            found |= {(_domain(entity), "turn_on"), (_domain(entity), "turn_off")}
    return frozenset(found)


class EntityWriter(_ServiceWriter):
    """A setpoint entity (number, input_number) and optionally a heating switch.

    With a switch hand-back, the switch that enables external control is turned on before the
    first write of each control session and off to hand back. A heating switch the session
    turned on or off is turned back on at hand-back, so the boiler heats under its own control.
    """

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        if not options.setpoint_entity:
            raise ValueError("no setpoint entity")
        self._options = options
        self._setpoint = options.setpoint_entity
        self._switch = options.ch_entity if options.loop.ch_writes else None
        self._switched = False
        self._hand_back = options.hand_back
        self._hand_back_value = options.hand_back_value
        self._external = (
            options.hand_back_entity if options.hand_back is HandBack.SWITCH else None
        )
        self._taken = False

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return writer_services(self._options)

    async def _take(self) -> None:
        if self._external and not self._taken:
            await self._call(_domain(self._external), "turn_on", {"entity_id": self._external})
        self._taken = True

    async def write_setpoint(self, value: float) -> None:
        checked = _checked(value, 0.0)
        await self._take()
        await self._call(
            _domain(self._setpoint), "set_value", {"entity_id": self._setpoint, "value": checked}
        )

    async def write_heating(self, on: bool) -> None:
        if not self._switch:
            raise WriteError("no heating switch")
        await self._take()
        self._switched = True
        await self._call(
            _domain(self._switch), "turn_on" if on else "turn_off", {"entity_id": self._switch}
        )

    async def hand_back(self, full: bool = False) -> None:
        """Each step is tried whatever the others do; any failure is raised at the end."""
        self._taken = False
        errors: list[WriteError] = []
        if self._switch and (self._switched or full):
            try:
                await self._call(_domain(self._switch), "turn_on", {"entity_id": self._switch})
                self._switched = False
            except WriteError as err:
                errors.append(err)
        try:
            if self._hand_back is HandBack.VALUE:
                await self._call(
                    _domain(self._setpoint),
                    "set_value",
                    {"entity_id": self._setpoint, "value": self._hand_back_value},
                )
            elif self._external:
                await self._call(
                    _domain(self._external), "turn_off", {"entity_id": self._external}
                )
            # HandBack.TIMEOUT: stop writing; the device's own timeout hands back.
        except WriteError as err:
            errors.append(err)
        if errors:
            raise WriteError("; ".join(str(err) for err in errors))


class OpenthermGwWriter(_ServiceWriter):
    """Built-in OTGW through Home Assistant's opentherm_gw services."""

    DOMAIN = OPENTHERM_GW

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        if not options.gateway_id:
            raise ValueError("no gateway id")
        self._gateway = options.gateway_id

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return OTGW_SERVICES

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

    async def hand_back(self, full: bool = False) -> None:
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

    async def hand_back(self, full: bool = False) -> None:
        await self._publish("ctrlsetpt", "0")


def make_writer(hass: HomeAssistant, options: ControlOptions) -> Writer:
    if options.write_path is WritePath.ENTITY:
        return EntityWriter(hass, options)
    if options.write_path is WritePath.OPENTHERM_GW:
        return OpenthermGwWriter(hass, options)
    if options.write_path is WritePath.OTGW_MQTT:
        return OtgwMqttWriter(hass, options)
    raise ValueError("control is not configured")
