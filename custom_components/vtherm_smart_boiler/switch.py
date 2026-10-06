"""The control switch: off by default, experimental, and refused while control is not allowed —
the refusal naming the first blocker in its own text and counting the others (P-74)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .control_config import Topology, WritePath, hand_back_effect, wall_thermostat_applies
from .coordinator import SmartBoilerConfigEntry, SmartBoilerCoordinator
from .entity import ControlEntity, coded_text

# Blockers that pass on their own; control switched on waits for them instead of refusing — the
# control store that cannot be written (PB-16) too, once it has written for a while again.
TRANSIENT_BLOCKERS = frozenset(
    {"ha_starting", "vt_central_boiler_unknown", "monitor_failed", "control_state_not_saved"}
)
# Blockers the switch change itself clears.
CLEARED_BY_SWITCHING = frozenset({"control_error"})
# Latches that switching control off and on clears (answer O; decisions 4 and 6 of 0.2.3):
# switching on is refused, with their text, only while control is on — with control off, on is
# the second half of "off and on", and the next off and on clears the latch as for any other.
CLEARED_BY_OFF_AND_ON = frozenset(
    {"heating_off_ignored", "heating_on_ignored", "relay_off_not_taken"}
)


PARALLEL_UPDATES = 1  # one switch action at a time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartBoilerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ControlSwitch] = (
        [] if coordinator.control is None else [ControlSwitch(coordinator)]
    )
    coordinator.expect_entities("switch", entities)  # none: control removed, its switch goes
    async_add_entities(entities)


class ControlSwitch(ControlEntity, SwitchEntity, RestoreEntity):
    """The user's wish to control the boiler; control runs only while nothing blocks it.

    After a restart the switch comes back as the user left it (the wish is stored at once);
    control then waits for its blockers (Home Assistant starting, missing data) to clear. A
    switch disabled in Home Assistant means control off. Switching on by hand is refused while
    a blocker that needs the user remains. The monitoring period counts calendar days from the
    entry's creation (answer K): once it has passed, control may start without a verdict —
    off-season the monitor may have too little data for one — and the switch shows the verdict
    so that this is said (S-43). Its blockers, and the alarm that keeps it from writing, come
    with their text (P-39).
    """

    _unrecorded_attributes = frozenset({"blockers_text", "blocked_by_text"})

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "control")

    @property
    def is_on(self) -> bool:
        return self.control.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.control.status
        options = self.control.options
        effect = hand_back_effect(options)
        relay = options.write_path is WritePath.RELAY
        if relay:
            off_by = "relay"  # the relay switches the boiler off itself (X8)
        else:
            off_by = "heating_switch" if options.loop.ch_writes else "low_setpoint"
        return {
            "experimental": True,
            "blockers": list(status.blockers),
            "blockers_text": self._text("blockers", status.blockers),
            # Decision 7 (Y1): an allowed alarm active while control is on keeps it from writing
            # — the lost boiler link, until it has been fresh for a minute.
            "blocked_by": list(status.blocked_by),
            "blocked_by_text": self._text("blocked_by", status.blocked_by),
            "hand_back_effect": None if effect is None else effect.value,
            # Who keeps frost protection now: the plugin while it controls, else whoever the
            # hand-back leaves the boiler with — after a stand-alone hand-back, the boiler's own,
            # if it has one (S-57).
            "frost_protection_by": status.frost_protection_by,
            # How "off" reaches the boiler: a heating switch or a relay really switches heating
            # off; a low setpoint may leave the boiler's CH pump running.
            "off_by": off_by,
            "allowed_services": sorted(f"{d}.{s}" for d, s in self.control.allowed_services),
            # The relay path (R15): controlled without confirmation where the relay reports no
            # state, without confirmation that the boiler heats where no proof is mapped.
            **({"confirmation": status.confirmation} if relay else {}),
            # SB-16: a stand-alone gateway drops the plugin's setpoint (CS) within about a
            # minute without Home Assistant, so an outage stops heating as a hand-back does.
            **(
                {"outage_effect": "heating_stops"}
                if not relay and options.topology is Topology.GATEWAY_STANDALONE
                else {}
            ),
            **self._wall_thermostat(),
            # S-43: the monitor's verdict; "not enough data" says control starts without one.
            "verdict": self._verdict(),
        }

    def _text(self, attribute: str, codes: tuple[str, ...]) -> str:
        return coded_text(self.coordinator, "switch", "control", attribute, codes)

    def _verdict(self) -> str | None:
        """The verdict of the last analysis; ``None`` before the first."""
        data = self.coordinator.data
        analysis = None if data is None else data.analysis
        return None if analysis is None else analysis.verdict.verdict.value

    def _wall_thermostat(self) -> dict[str, Any]:
        """With an OpenTherm thermostat on the gateway: the temperature it keeps after a
        hand-back, from the optional signal, and the warning — not mapped, unknown, or below
        15 °C (X6). Nothing where there is no such thermostat."""
        if not wall_thermostat_applies(self.control.options):
            return {}
        data = self.coordinator.data
        wall = None if data is None else data.wall_thermostat
        if wall is None:
            return {"wall_thermostat_setpoint": None, "wall_thermostat_warning": None}
        setpoint = None if wall.setpoint is None else round(wall.setpoint, 1)
        warning = None if wall.warning is None else wall.warning.value
        return {"wall_thermostat_setpoint": setpoint, "wall_thermostat_warning": warning}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The wish the control store kept comes first: the restore cache may be older than a
        # change the user made just before a crash (P-11). Without one (the first start of this
        # version), the switch's restored state, once; without that, off.
        wish = self.control.stored_wish
        if wish is None:
            last = await self.async_get_last_state()
            wish = last is not None and last.state == STATE_ON
        await self.control.async_restore_enabled(wish)

    async def async_turn_on(self, **kwargs: Any) -> None:
        passing = TRANSIENT_BLOCKERS | CLEARED_BY_SWITCHING
        if not self.control.enabled:
            passing |= CLEARED_BY_OFF_AND_ON
        blockers = [
            b for b in self.control.blockers(dt_util.utcnow().timestamp()) if b not in passing
        ]
        if blockers:
            # P-74: the first blocker's own text, and how many more — each named, translated,
            # on the switch's and the control state's ``blockers_text``.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=f"blocked_{blockers[0]}",
                translation_placeholders={"count": str(len(blockers) - 1)},
            )
        await self.control.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.control.async_set_enabled(False)
        self.async_write_ha_state()
