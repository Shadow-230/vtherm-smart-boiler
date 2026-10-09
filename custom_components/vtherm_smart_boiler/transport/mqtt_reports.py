"""Reports heard on the boiler interface's own MQTT topics (I6, decision 9). Read only.

Home Assistant's MQTT entities write a state only when it changes, so a steady value keeps an old
``last_reported`` though its device repeats it. The OTGW firmware repeats every value it reads from
the boiler at least every 60 s, each on its own topic under ``<top>/value/<node>/`` — and only
while the boiler's data reach it (its ESP's own statistics live deeper, under
``otgw-firmware/``, and are not listened to). EMS-ESP publishes the boiler's values together, as
``<base>/boiler_data`` (and ``<base>/boiler_data_dhw`` in its single-topic format), every 10 s by
default — or only on a change, where its publish time is 0. The plugin subscribes to those topics
itself and takes the time of the last message as the signal's report time, for the signals whose
entity is an MQTT entity: one of another integration is not this device's.

Topic names: the OTGW firmware 1.7.5 (``research/diy/otgw-firmware/v1.7.5/OTGW-Core.h`` and
``OTGW-Core.ino``: the OpenTherm labels and the status bits); EMS-ESP's documentation
("Configuring": the nested and single-topic formats). What the plugin does with the times —
a limit only for a source seen repeating an unchanged value — is ``core.freshness``'s.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..core.signals import Signal

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# The OTGW firmware's topic, under ``<top>/value/<node>/``, for each signal it reads from the
# boiler: an OpenTherm label, or a status bit.
OTGW_TOPICS: Mapping[Signal, str] = {
    Signal.FLAME: "flame",
    Signal.FLOW: "Tboiler",
    Signal.RETURN: "Tret",
    Signal.MODULATION: "RelModLevel",
    Signal.PRESSURE: "CHPressure",
    Signal.DHW_ACTIVE: "domestichotwater",
    Signal.CH_ACTIVE: "centralheating",
    Signal.FAULT_INDICATION: "fault",
    Signal.OUTDOOR: "Toutside",
    Signal.FLUE_GAS: "Texhaust",
    Signal.CH_SETPOINT: "TSet",
}
# EMS-ESP's boiler data, in its nested format and in its single-topic one.
EMS_ESP_TOPICS = ("boiler_data", "boiler_data_dhw")


def otgw_topics(top: str, node: str, signals: Iterable[Signal]) -> dict[str, frozenset[Signal]]:
    """Each OTGW firmware topic to listen to, with the signal a message on it reports."""
    return {
        f"{top}/value/{node}/{OTGW_TOPICS[signal]}": frozenset({signal})
        for signal in signals
        if signal in OTGW_TOPICS
    }


def ems_esp_topics(base: str, signals: Iterable[Signal]) -> dict[str, frozenset[Signal]]:
    """Each EMS-ESP topic to listen to: a message reports every boiler signal at once."""
    found = frozenset(signals)
    if not found:
        return {}
    return {f"{base}/{topic}": found for topic in EMS_ESP_TOPICS}


def mqtt_signals(hass: HomeAssistant, mapping: Mapping[Signal, str]) -> frozenset[Signal]:
    """The mapped signals whose entity Home Assistant's MQTT integration registered: only those
    can be the device's own topics'."""
    registry = er.async_get(hass)
    found = set()
    for signal, entity_id in mapping.items():
        registered = registry.async_get(entity_id)
        if registered is not None and registered.platform == "mqtt":
            found.add(signal)
    return frozenset(found)


class MqttReports:
    """The last message heard for each signal, by wall-clock time; nothing until started."""

    def __init__(self) -> None:
        self.heard: dict[Signal, float] = {}
        self._unsubscribe: list[Callable[[], None]] = []

    async def async_start(
        self, hass: HomeAssistant, topics: Mapping[str, frozenset[Signal]]
    ) -> bool:
        """Subscribe to each topic; ``False`` where MQTT cannot be used — the report times stay
        Home Assistant's own, availability only."""
        if not topics:
            return False
        from homeassistant.components import mqtt
        from homeassistant.exceptions import HomeAssistantError

        for topic, signals in topics.items():
            try:
                unsubscribe = await mqtt.async_subscribe(hass, topic, self._heard(signals), qos=0)
            except HomeAssistantError as err:  # MQTT not set up or disabled: availability only
                _LOGGER.warning("Could not listen to %s for report times: %s", topic, err)
                self.stop()
                return False
            self._unsubscribe.append(unsubscribe)
        return True

    def _heard(self, signals: frozenset[Signal]) -> Callable[[Any], None]:
        @callback
        def heard(_message: Any) -> None:
            now = dt_util.utcnow().timestamp()
            for signal in signals:
                self.heard[signal] = now

        return heard

    def stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
