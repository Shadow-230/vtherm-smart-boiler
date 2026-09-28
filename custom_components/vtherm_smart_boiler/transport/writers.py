"""Writers: the only code that changes the boiler. They exist only while control is enabled.

Each writer knows the services it may call — the list a test checks. A write that fails raises
``WriteError``; the caller reports it and never assumes it applied. Home Assistant skips an
unavailable entity without an error (and a missing one with a log line only), so a write to an
entity first checks that it is there and available.

Every hand-back is the safe hand-back (``SCOPE.md`` §5; the user's decision of 2026-09-26/27), its
parts one after another at once, each tried whatever the others do, waiting for no read-back:
(1) the water to the lowest water temperature set; (2) heating on where the boiler returns to a
thermostat or its own control — on a gateway always ``CH=1``; (3) the release — ``CS=0``, the
hand-back value, the external-control switch off, or nothing (the device's own timeout). It
returns what each target must show once the hand-back reached it (``HandBackCheck``); only that
confirmation waits for the read-back.

A relay (class 3, X8) goes to its rest state instead, through a writer of its own: "off" unless
the user chose "on" — the relay is never switched on otherwise (S-27). Its own reported state
confirms the relay — not that the boiler heats — an exception to "the written entity confirms
nothing"; a relay that reports no state, or an ``assumed_state`` entity, confirms nothing, and its
hand-back is done once written. At a step aside the rest state is written once, unless the relay
already reads it, and the relay is then left alone (answers H, L). Every relay write carries a
``Context`` of the plugin's own, remembered, so the relay's own changes can be told from the
plugin's.

OpenTherm Gateway facts (OTGW firmware documentation and the PIC 6.6 source,
research/2026-09-24-otgw-topologies-f3-f7.md): a control-setpoint override of 8 °C or more lapses
unless repeated within a minute; one between 1 and 7 °C never lapses and would lock out a
thermostat for good if Home Assistant stopped, so it is refused; 0 cancels the override. ``CH=0``
sets a flag the gateway keeps through ``CS=0`` and the override's lapse until ``CH=1`` or a reset:
it masks CH enable under any later setpoint override and the demand of an on/off thermostat. So a
hand-back always sends ``CH=1`` before ``CS=0`` — it only clears the plugin's own flag; stand-alone,
``CS=0`` still leaves the boiler without demand. The plugin never touches the DHW-enable override.

A gateway service's normal return proves nothing: pyotgw returns after a timeout of its own, and
an MQTT publish once it is written to the socket. So a gateway's hand-back counts only once its
setpoint read-back shows the release.
"""

from __future__ import annotations

import asyncio
import math
from collections import deque
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from homeassistant.core import Context
from homeassistant.util import dt as dt_util

from ..control_config import (
    KEEPALIVE_S,
    RELAY_DOMAINS,
    ControlOptions,
    HandBack,
    WritePath,
    hand_back_heating_on,
    highest_water_temperature,
    one_entity_in_two_roles,
)
from ..core.guards import HELD_REFRESH_S, WriteType
from ..core.hand_back import CheckKind, CheckSource, ReleaseRule
from ..core.limits import GRID_EPSILON, is_on_grid
from ..core.relay import CONTEXTS_KEPT
from ..units import celsius_to, parse_number
from .entities import grid_from_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

OTGW_MIN_SETPOINT = 8.0  # below this (and above 0) an OTGW override never lapses
MAX_SETPOINT = 90.0
WRITE_TIMEOUT_S = 10.0  # a service call that hangs longer counts as failed
OPENTHERM_GW = "opentherm_gw"
OTGW_SERVICES = frozenset(
    {(OPENTHERM_GW, "set_control_setpoint"), (OPENTHERM_GW, "set_central_heating_ovrd")}
)


class WriteError(Exception):
    """A write did not go through."""


@dataclass(frozen=True, slots=True)
class HandBackCheck:
    """What one target must show once the hand-back has reached it (V5).

    ``entity_id``: the entity read — a separate read-back where there is one; ``target``: the
    entity written, where it is another (``None``: the same); ``expected``: the hand-back value
    (0 on a gateway: ``CS=0`` read back), or a switch's hand-back state; ``kind`` and ``source``:
    how the release shows, and whether a separate read-back, the written entity itself or an
    optimistic one (``assumed_state``) shows it; ``held``: declared held — the device keeps the
    last value it was given; ``written``: this attempt wrote every part of the target. What its
    release is judged against: ``release_from``, the plugin's last value, ``lowest``, written
    first, and ``baseline``, the value from before the session (the timeout); ``before``: the
    read-back as it stood before the commands, for a value reported after them. ``known``: the
    states a two-valued target shows once known — ``None``: any it reports (a boiler thermostat
    entity's modes).
    """

    entity_id: str
    expected: float | str | None
    kind: CheckKind = CheckKind.VALUE
    source: CheckSource = CheckSource.SEPARATE
    held: bool = False
    target: str | None = None
    release_from: float | None = None
    lowest: float | None = None
    baseline: float | None = None
    written: bool = True
    before: State | None = field(default=None, compare=False, repr=False)
    known: tuple[str, ...] | None = ("on", "off")

    @property
    def key(self) -> str:
        """The target this check stands for: the entity written."""
        return self.target or self.entity_id

    @property
    def rule(self) -> ReleaseRule:
        expected = None if isinstance(self.expected, str) else self.expected
        return ReleaseRule(self.kind, expected, self.release_from, self.lowest, self.baseline)


class HandBackFailed(WriteError):
    """A part of a hand-back failed; ``checks``: what the targets must show all the same — one
    whose part failed stays owed until it shows the hand-back."""

    def __init__(self, message: str, checks: tuple[HandBackCheck, ...]) -> None:
        super().__init__(message)
        self.checks = checks


class Writer(Protocol):
    @property
    def services(self) -> frozenset[tuple[str, str]]: ...

    async def write_setpoint(self, value: float) -> None: ...

    async def write_heating(self, on: bool) -> None: ...

    async def keep_alive(self, returned: bool = False) -> None:
        """While control holds the boiler: repeat what the loop does not — an external-control
        switch declared expiring every keep-alive, one declared held every five minutes and at
        once when it came back from unavailable (``returned``)."""
        ...

    async def renew_external(self) -> None:
        """Turn an external-control switch on again now: found off after an outage of its device
        while control holds the boiler (a lost command, M15)."""
        ...

    async def hand_back(
        self,
        *,
        release_from: float | None = None,
        baseline: float | None = None,
        write_timeout_s: float | None = None,
        skip: Collection[str] = (),
        once: bool = False,
    ) -> tuple[HandBackCheck, ...]:
        """The safe hand-back. Returns what every target must show for it to count as done.
        ``release_from``: the setpoint the plugin last wrote; ``baseline``: the read-back from
        before the session (``None``: not known). ``write_timeout_s``: each write's cap, when not
        the usual one (at a stop). ``skip``: targets not written this time — done, held by
        another controller, a third value being judged, a timeout never rewritten — whose checks
        are returned all the same. ``once``: a step aside — a relay's rest state is written
        once and then left alone (answer L); the other writers make the whole hand-back."""
        ...


def _checked(value: float, low: float) -> float:
    if not math.isfinite(value) or not low <= value <= MAX_SETPOINT:
        raise WriteError(f"setpoint {value} outside {low} to {MAX_SETPOINT}")
    return round(value, 1)


def _finite(value: float) -> float:
    """A setpoint for an entity: finite and within the plausible range; not rounded — it comes
    on the entity's grid already (P-15)."""
    if not math.isfinite(value) or not 0.0 <= value <= MAX_SETPOINT:
        raise WriteError(f"setpoint {value} outside 0 to {MAX_SETPOINT}")
    return value


def _as_entity_takes_it(state: State, value: float) -> float:
    """A °C value in a number entity's own unit (a °F entity gets °F). It must already lie on
    the entity's grid (``min`` + n * ``step``) and inside its ``min`` and ``max`` — the loop and
    the hand-back put it there, inside the limits (P-15, P-98); anything else is refused, never
    rounded here, so the guard compares the value the device gets."""
    unit = state.attributes.get("unit_of_measurement")
    step = parse_number(state.attributes.get("step"))
    if step is None or step <= 0:
        value = round(value, 1)  # no grid: a tenth of a kelvin, as always
    converted = celsius_to(value, unit if isinstance(unit, str) else None)
    if converted is None:
        raise WriteError(f"{state.entity_id}: unit {unit!r} is not a temperature unit")
    low = parse_number(state.attributes.get("min"))
    high = parse_number(state.attributes.get("max"))
    slack = GRID_EPSILON * (step if step is not None and step > 0 else 1.0)
    if (low is not None and converted < low - slack) or (
        high is not None and converted > high + slack
    ):
        raise WriteError(f"{state.entity_id}: {converted:g} outside its range")
    if step is not None and step > 0:
        base = 0.0 if low is None else low
        if not is_on_grid(converted, step, base):
            raise WriteError(f"{state.entity_id}: {converted:g} is not on its step {step:g}")
        converted = base + round((converted - base) / step) * step  # the grid value exactly
    return round(converted, 6)


class _ServiceWriter:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def _check_target(self, entity_id: str) -> State:
        """Home Assistant would skip a missing or unavailable entity without an error. One whose
        state is unknown is available, only without a value yet, and it is called: so is it
        here — a hand-back above all — and the read-back tells whether it took the value."""
        state = self._hass.states.get(entity_id)
        if state is None:
            raise WriteError(f"{entity_id} is missing")
        if state.state == "unavailable":
            raise WriteError(f"{entity_id} is unavailable")
        return state

    async def _call_entity(
        self,
        service: str,
        entity_id: str,
        *,
        timeout_s: float | None = None,
        **data: object,
    ) -> None:
        self._check_target(entity_id)
        await self._call(
            _domain(entity_id), service, {"entity_id": entity_id, **data}, timeout_s=timeout_s
        )

    async def _call(
        self,
        domain: str,
        service: str,
        data: dict[str, object],
        *,
        timeout_s: float | None = None,
        context: Context | None = None,
    ) -> None:
        """One service call, capped at ``timeout_s`` (else ``WRITE_TIMEOUT_S``), with the
        plugin's own ``context`` where given (a relay's writes)."""
        try:
            async with asyncio.timeout(WRITE_TIMEOUT_S if timeout_s is None else timeout_s):
                await self._hass.services.async_call(
                    domain, service, data, blocking=True, context=context
                )
        except asyncio.CancelledError as err:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise  # the caller is being cancelled (a stop): not a failed write
            # A task inside the integration was cancelled under the call (P-42).
            raise WriteError(f"{domain}.{service}: cancelled inside the service") from err
        except Exception as err:  # every failure is a failed write, reported upstream
            raise WriteError(f"{domain}.{service}: {err!r}") from err


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def writer_services(options: ControlOptions) -> frozenset[tuple[str, str]]:
    """Every service a writer for these options may call; empty when control is not set up."""
    path = options.write_path
    if path is WritePath.RELAY:
        relay = options.relay.entity
        domain = None if not relay else _domain(relay)
        if domain == "switch":
            return frozenset({("switch", "turn_on"), ("switch", "turn_off")})
        if domain == "climate":
            return frozenset({("climate", "set_hvac_mode")})
        return frozenset()
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
    first write each time control takes the boiler — declared expiring, again every keep-alive
    while control holds it (P-40) — and off to hand back. The hand-back turns a heating switch
    back on where the boiler returns to a thermostat or its own control, and leaves it as it is
    where the hand-back stops heating (S-27).

    One entity in two roles — the heating switch as the external-control switch, say — is
    refused (P-03): every hand-back would switch it on and off for ever. A hand-back through such
    options fails instead, stays owed and is shown, to be settled by hand.
    """

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        if not options.setpoint_entity:
            raise ValueError("no setpoint entity")
        if one_entity_in_two_roles(options):
            raise ValueError("one entity in two roles")
        self._options = options
        self._setpoint = options.setpoint_entity
        self._switch = options.ch_entity if options.loop.ch_writes else None
        self._heating_on = hand_back_heating_on(options)
        self._lowest = options.loop.control.limits.hard_min
        self._highest = highest_water_temperature(options.loop.control)
        self._hand_back = options.hand_back
        self._hand_back_value = options.hand_back_value
        self._external = options.hand_back_entity if options.hand_back is HandBack.SWITCH else None
        self._external_expiring = options.hand_back_entity_write_type is WriteType.EXPIRING
        self._taken = False
        self._taken_at: float | None = None  # when the external switch was last turned on

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return writer_services(self._options)

    def _external_due(self, returned: bool = False) -> bool:
        """The external switch is to be turned on now: control takes the boiler; declared
        expiring, a keep-alive has passed since; declared held, five minutes have (with no echo
        required), or it came back from unavailable. A clock set back counts as passed."""
        if not self._taken or self._taken_at is None:
            return True
        elapsed = dt_util.utcnow().timestamp() - self._taken_at
        if elapsed < 0:
            return True
        if self._external_expiring:
            return elapsed >= KEEPALIVE_S
        return returned or elapsed >= HELD_REFRESH_S

    async def _take(self, returned: bool = False) -> None:
        if self._external and self._external_due(returned):
            await self._call_entity("turn_on", self._external)
            self._taken_at = dt_util.utcnow().timestamp()
        self._taken = True

    async def keep_alive(self, returned: bool = False) -> None:
        """An expiring external-control switch lapses unless repeated: turned on again every
        keep-alive while control holds the boiler, whatever else is written; a held one every
        five minutes, and at once when it came back from unavailable."""
        if self._taken and self._external:
            await self._take(returned)

    async def renew_external(self) -> None:
        """Found off after an outage of its device while control holds the boiler: turned on
        again at once (M15)."""
        if self._external:
            await self._call_entity("turn_on", self._external)
            self._taken_at = dt_util.utcnow().timestamp()
            self._taken = True

    async def write_setpoint(self, value: float) -> None:
        checked = _as_entity_takes_it(self._check_target(self._setpoint), _finite(value))
        await self._take()
        await self._call_entity("set_value", self._setpoint, value=checked)

    async def write_heating(self, on: bool) -> None:
        if not self._switch:
            raise WriteError("no heating switch")
        self._check_target(self._switch)
        await self._take()
        await self._call_entity("turn_on" if on else "turn_off", self._switch)

    async def _set_value(self, celsius: float | None, timeout_s: float | None) -> None:
        if celsius is None:
            raise WriteError(f"{self._setpoint}: no value on its grid inside the limits")
        value = _as_entity_takes_it(self._check_target(self._setpoint), celsius)
        await self._call_entity("set_value", self._setpoint, timeout_s=timeout_s, value=value)

    async def hand_back(
        self,
        *,
        release_from: float | None = None,
        baseline: float | None = None,
        write_timeout_s: float | None = None,
        skip: Collection[str] = (),
        once: bool = False,
    ) -> tuple[HandBackCheck, ...]:
        """The lowest water temperature, the heating switch on where the effect says so, then the
        release; each part tried whatever the others do, and any failure raised at the end with
        the checks (``HandBackFailed``). The lowest is written only with the release target."""
        self._taken = False
        self._taken_at = None
        errors: list[WriteError] = []
        checks: list[HandBackCheck] = []
        before = self._hass.states.get(self._value_read_back())
        release = self._external if self._hand_back is HandBack.SWITCH else self._setpoint
        # Without a release to follow it, the lowest would stay with a device that keeps it.
        releasing = self._hand_back is not None and release is not None and release not in skip
        # The values on the setpoint entity's grid, inside the limits (P-15): the lowest never
        # below itself, the hand-back value never above the highest water temperature.
        grid = grid_from_state(self._hass.states.get(self._setpoint))
        lowest: float | None = _checked(self._lowest, 0.0)
        if grid is not None:
            lowest = grid.put(self._lowest, self._lowest, self._highest)
        # 1. The lowest water temperature, with the release target only.
        lowest_ok = releasing and await _part(
            errors, lambda: self._set_value(lowest, write_timeout_s)
        )
        # 2. Heating on, where the boiler returns to a thermostat or its own control.
        switch = self._switch
        if switch and self._heating_on:
            written = switch not in skip and await _part(
                errors, lambda: self._call_entity("turn_on", switch, timeout_s=write_timeout_s)
            )
            checks.append(self._switch_check(switch, "on", written))
        # 3. The release.
        external = self._external
        if self._hand_back is HandBack.VALUE:
            value = None if self._hand_back_value is None else float(self._hand_back_value)
            if value is not None and grid is not None:
                value = grid.put(value, None, self._highest)
            written = releasing and await _part(
                errors, lambda: self._set_hand_back_value(value, write_timeout_s)
            )
            held = self._options.write_type is WriteType.HELD
            kind = CheckKind.VALUE if held else CheckKind.LEAVES_VALUE
            checks.append(
                self._value_check(
                    kind, value, lowest_ok and written, release_from, None, before, lowest
                )
            )
        elif self._hand_back is HandBack.SWITCH and external:
            written = releasing and await _part(
                errors, lambda: self._call_entity("turn_off", external, timeout_s=write_timeout_s)
            )
            checks.append(self._switch_check(external, "off", lowest_ok and written))
        elif self._hand_back is HandBack.TIMEOUT:
            # Nothing more: the device's own timeout releases, back to the value from before.
            kind = CheckKind.BACK_TO_BASELINE
            checks.append(
                self._value_check(kind, None, lowest_ok, release_from, baseline, before, lowest)
            )
        if errors:
            raise HandBackFailed("; ".join(str(err) for err in errors), tuple(checks))
        return tuple(checks)

    async def _set_hand_back_value(self, value: float | None, timeout_s: float | None) -> None:
        if value is None:
            raise WriteError("no hand-back value, or none on the entity's grid")
        await self._set_value(value, timeout_s)

    def _value_read_back(self) -> str:
        """What judges the setpoint's release: the separate read-back, else the entity itself."""
        return self._options.confirmed_entity or self._setpoint

    def _source(self, read: str, written: str) -> CheckSource:
        state = self._hass.states.get(read)
        if state is not None and state.attributes.get("assumed_state") is True:
            return CheckSource.ASSUMED  # it shows what it was given, not what the device has
        return CheckSource.SELF if read == written else CheckSource.SEPARATE

    def _value_check(
        self,
        kind: CheckKind,
        expected: float | None,
        written: bool,
        release_from: float | None,
        baseline: float | None,
        before: State | None,
        lowest: float | None,
    ) -> HandBackCheck:
        """What the setpoint's read-back must show; ``expected`` and ``lowest`` as written, on
        the entity's grid."""
        read = self._value_read_back()
        return HandBackCheck(
            read,
            expected,
            kind,
            self._source(read, self._setpoint),
            held=self._options.write_type is WriteType.HELD,
            target=None if read == self._setpoint else self._setpoint,
            release_from=release_from,
            lowest=self._lowest if lowest is None else lowest,
            baseline=baseline,
            written=written,
            before=before,
        )

    def _switch_check(self, entity: str, state: str, written: bool) -> HandBackCheck:
        """A switch has no separate report: its own state shows it, unverified."""
        write_type = (
            self._options.ch_write_type
            if entity == self._switch
            else self._options.hand_back_entity_write_type
        )
        return HandBackCheck(
            entity,
            state,
            CheckKind.SWITCH,
            self._source(entity, entity),
            held=write_type is WriteType.HELD,
            written=written,
        )


class _GatewayWriter(_ServiceWriter):
    """A built-in OTGW: its commands can go nowhere without an error — opentherm_gw's services
    return while the gateway is not connected (the command is dropped), and an MQTT publish
    succeeds once the broker has it, the firmware offline or not. Where the gateway's own
    read-back shows it unavailable, a write, and above all a hand-back, is taken as failed:
    kept, shown and sent again once the gateway is back."""

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        self._reachable_by = options.confirmed_entity
        self._lowest = options.loop.control.limits.hard_min

    async def keep_alive(self, returned: bool = False) -> None:
        """The loop repeats the gateway's overrides itself."""

    async def renew_external(self) -> None:
        """A gateway has no external-control switch."""

    def _require_connected(self, reported: bool = False) -> None:
        """``reported``: the read-back must also hold a value — opentherm_gw's entities can stay
        available with none after pyotgw resets its status on a lost connection."""
        entity = self._reachable_by
        if not entity:
            return
        state = self._hass.states.get(entity)
        if state is None or state.state == "unavailable":
            raise WriteError(f"the gateway is not connected: {entity} is unavailable")
        if reported and state.state == "unknown":
            raise WriteError(f"the gateway has reported nothing since: {entity} is unknown")

    def _read_back_now(self) -> State | None:
        """The read-back as it stands before a hand-back's commands go out."""
        return self._hass.states.get(self._reachable_by) if self._reachable_by else None

    def _release_check(self, before: State | None, release_from: float | None) -> HandBackCheck:
        """What shows the release: the read-back at 0 (``CS=0``), or away from both the plugin's
        last value and the lowest just written — the thermostat's own value."""
        if not self._reachable_by:
            raise WriteError("no gateway read-back: the release cannot be seen")
        return HandBackCheck(
            self._reachable_by,
            0.0,
            CheckKind.LEAVES_VALUE,
            CheckSource.SEPARATE,
            release_from=release_from,
            lowest=self._lowest,
            before=before,
        )


class OpenthermGwWriter(_GatewayWriter):
    """Built-in OTGW through Home Assistant's opentherm_gw services."""

    DOMAIN = OPENTHERM_GW

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass, options)
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
        self._require_connected()

    async def write_heating(self, on: bool) -> None:
        await self._call(
            self.DOMAIN,
            "set_central_heating_ovrd",
            {"gateway_id": self._gateway, "ch_override": on},
        )
        self._require_connected()

    async def hand_back(
        self,
        *,
        release_from: float | None = None,
        baseline: float | None = None,
        write_timeout_s: float | None = None,
        skip: Collection[str] = (),
        once: bool = False,
    ) -> tuple[HandBackCheck, ...]:
        """``CS=<lowest>``, ``CH=1``, then ``CS=0``; each tried whatever the others do, and the
        hand-back counts only with the gateway connected, once its read-back shows the release.
        pyotgw writes the value the gateway accepted to its status at once; after a timeout it
        writes nothing, and the service returns all the same."""
        before = self._read_back_now()
        await _all_of(
            lambda: self._call(
                self.DOMAIN,
                "set_control_setpoint",
                {
                    "gateway_id": self._gateway,
                    "temperature": _checked(self._lowest, OTGW_MIN_SETPOINT),
                },
                timeout_s=write_timeout_s,
            ),
            lambda: self._call(
                self.DOMAIN,
                "set_central_heating_ovrd",
                {"gateway_id": self._gateway, "ch_override": True},
                timeout_s=write_timeout_s,
            ),
            lambda: self._call(
                self.DOMAIN,
                "set_control_setpoint",
                {"gateway_id": self._gateway, "temperature": 0},
                timeout_s=write_timeout_s,
            ),
        )
        # The gateway's full status comes with every (re)connection, so a read-back without a
        # value means nothing has come from the gateway since the connection was lost.
        self._require_connected(reported=True)
        return (self._release_check(before, release_from),)


class OtgwMqttWriter(_GatewayWriter):
    """Built-in OTGW through its firmware's MQTT commands (``<top>/set/<node>/<command>``)."""

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass, options)
        if not (options.mqtt_top and options.mqtt_node):
            raise ValueError("no MQTT topic")
        self._base = f"{options.mqtt_top.strip('/')}/set/{options.mqtt_node.strip('/')}"

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return frozenset({("mqtt", "publish")})

    async def _publish(self, command: str, payload: str, timeout_s: float | None = None) -> None:
        await self._call(
            "mqtt",
            "publish",
            {"topic": f"{self._base}/{command}", "payload": payload},
            timeout_s=timeout_s,
        )

    async def write_setpoint(self, value: float) -> None:
        await self._publish("ctrlsetpt", f"{_checked(value, OTGW_MIN_SETPOINT):.1f}")
        self._require_connected()

    async def write_heating(self, on: bool) -> None:
        await self._publish("chenable", "1" if on else "0")
        self._require_connected()

    async def hand_back(
        self,
        *,
        release_from: float | None = None,
        baseline: float | None = None,
        write_timeout_s: float | None = None,
        skip: Collection[str] = (),
        once: bool = False,
    ) -> tuple[HandBackCheck, ...]:
        """``CS=<lowest>``, ``CH=1``, then ``CS=0``; each tried whatever the others do, and the
        hand-back counts only with the gateway connected, once its read-back shows the release:
        a publish is done once written to the socket, the firmware offline or not."""
        before = self._read_back_now()
        await _all_of(
            lambda: self._publish(
                "ctrlsetpt", f"{_checked(self._lowest, OTGW_MIN_SETPOINT):.1f}", write_timeout_s
            ),
            lambda: self._publish("chenable", "1", write_timeout_s),
            lambda: self._publish("ctrlsetpt", "0", write_timeout_s),
        )
        self._require_connected()
        return (self._release_check(before, release_from),)


class RelayWriter(_ServiceWriter):
    """The relay of an on/off boiler (X8, R2, R9): a switch turned on and off, or a boiler
    thermostat entity set to heat or off. Writes go only to the relay — nothing the boiler
    stores — each with a ``Context`` of the plugin's own, remembered (the last
    ``CONTEXTS_KEPT``) so the relay's changes the plugin made can be told apart."""

    def __init__(self, hass: HomeAssistant, options: ControlOptions) -> None:
        super().__init__(hass)
        relay = options.relay.entity
        if not relay or _domain(relay) not in RELAY_DOMAINS:
            raise ValueError("no relay: a switch or a boiler thermostat entity")
        self._options = options
        self._relay = relay
        self._climate = _domain(relay) == "climate"
        self._rest_on = options.relay.rests_on
        self._contexts: deque[str] = deque(maxlen=CONTEXTS_KEPT)

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return writer_services(self._options)

    def ours(self, context_id: str | None) -> bool:
        """Whether a change carried one of the plugin's own relay writes."""
        return context_id is not None and context_id in self._contexts

    def _value(self, on: bool) -> str:
        """The state the relay shows for ``on``: a switch on or off, a boiler thermostat heat or
        off."""
        if self._climate:
            return "heat" if on else "off"
        return "on" if on else "off"

    async def _switch(self, on: bool, timeout_s: float | None = None) -> None:
        self._check_target(self._relay)
        context = Context()
        self._contexts.append(context.id)
        if self._climate:
            await self._call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self._relay, "hvac_mode": self._value(on)},
                timeout_s=timeout_s,
                context=context,
            )
        else:
            await self._call(
                "switch",
                "turn_on" if on else "turn_off",
                {"entity_id": self._relay},
                timeout_s=timeout_s,
                context=context,
            )

    async def write_setpoint(self, value: float) -> None:
        raise WriteError("a relay takes no water temperature")

    async def write_heating(self, on: bool) -> None:
        await self._switch(on)

    async def keep_alive(self, returned: bool = False) -> None:
        """The relay rule repeats and renews the relay itself."""

    async def renew_external(self) -> None:
        """A relay has no external-control switch."""

    def _reports(self, state: State | None) -> bool:
        """Its own state confirms the relay: declared so, and not an optimistic entity."""
        assumed = state is not None and state.attributes.get("assumed_state") is True
        return self._options.relay.config.reports_state and not assumed

    async def hand_back(
        self,
        *,
        release_from: float | None = None,
        baseline: float | None = None,
        write_timeout_s: float | None = None,
        skip: Collection[str] = (),
        once: bool = False,
    ) -> tuple[HandBackCheck, ...]:
        """Only the rest state: "off" by default, "on" only where the user chose it (S-27).
        A relay that reports its state and already shows it is not written. At a step aside
        (``once``) it is written once and then left alone, read back or not: its check counts
        once written (answers H, L)."""
        relay = self._relay
        expected = self._value(self._rest_on)
        state = self._hass.states.get(relay)
        reports = self._reports(state)
        shows = state is not None and state.state == expected
        errors: list[WriteError] = []
        if relay in skip or ((reports or once) and shows):
            written = True
        else:
            written = await _part(errors, lambda: self._switch(self._rest_on, write_timeout_s))
        source = CheckSource.SEPARATE if reports and not once else CheckSource.ASSUMED
        check = HandBackCheck(
            relay,
            expected,
            CheckKind.SWITCH,
            source,
            written=written,
            known=None if self._climate else ("on", "off"),
        )
        if errors:
            raise HandBackFailed("; ".join(str(err) for err in errors), (check,))
        return (check,)


async def _part(errors: list[WriteError], write: Callable[[], Awaitable[None]]) -> bool:
    """One part of a hand-back, whatever the others do: whether it went through; its failure
    is kept for the end."""
    try:
        await write()
    except WriteError as err:
        errors.append(err)
        return False
    return True


async def _all_of(*steps: Callable[[], Awaitable[None]]) -> None:
    """Run every step in order, each whatever the others do; raise their failures at the end.
    Each write is made only when its turn comes: cancelled midway (a stop), none is left
    behind unawaited (P-52)."""
    errors: list[WriteError] = []
    for step in steps:
        try:
            await step()
        except WriteError as err:
            errors.append(err)
    if errors:
        raise WriteError("; ".join(str(err) for err in errors))


def make_writer(hass: HomeAssistant, options: ControlOptions) -> Writer:
    if options.write_path is WritePath.RELAY:
        return RelayWriter(hass, options)
    if options.write_path is WritePath.ENTITY:
        return EntityWriter(hass, options)
    if options.write_path is WritePath.OPENTHERM_GW:
        return OpenthermGwWriter(hass, options)
    if options.write_path is WritePath.OTGW_MQTT:
        return OtgwMqttWriter(hass, options)
    raise ValueError("control is not configured")
