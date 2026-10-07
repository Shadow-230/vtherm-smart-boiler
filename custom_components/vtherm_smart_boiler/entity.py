"""Base of the plugin's entities: one device per installation, translated names, and the
missing-data rule: an entity of a feature the configuration leaves inactive is not created, and
one whose feature turns inactive while it runs is unavailable (Y4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .control import ControlUnit
from .coordinator import SmartBoilerCoordinator
from .core.signal_check import Feature, FeatureStatus

# Y4: the entities of each feature, by key. The verdict keeps its sensor without a flame signal:
# it says itself that there is no verdict without one (S-43).
FEATURE_ENTITIES: Mapping[Feature, tuple[str, ...]] = MappingProxyType(
    {
        Feature.CYCLES: (
            "starts_per_hour",
            "median_burn",
            "burner_hours",
            "short_burn_share",
            "alarm_frequent_starts",
        ),
        Feature.CONDENSING: ("condensing_share",),
        Feature.GAS: ("gas_per_degree_day",),
        Feature.DEGREE_DAYS: ("degree_days", "change_report"),
        Feature.HOT_WATER: ("hot_water",),
        Feature.EMITTER_FACTOR: ("emitter_power_factor",),
        Feature.FLUE_GAS_WARNING: ("alarm_flue_gas_high", "alarm_flue_gas_rising"),
        Feature.PRESSURE_WARNING: ("alarm_pressure_high",),
        Feature.ADD_WATER: ("alarm_pressure_low",),
        Feature.PRESSURE_TREND: ("alarm_pressure_falling",),
        Feature.HYSTERESIS_DRIFT: ("alarm_hysteresis_drift",),
        Feature.UNSTABLE_IGNITION: ("alarm_unstable_ignition",),
        Feature.LOW_FLOW: ("alarm_low_flow",),
        Feature.OUTDOOR_CHECK: ("outdoor_sensor_problem", "alarm_outdoor_sensor_suspect"),
        Feature.COMFORT_CORRECTION: ("reset_comfort_correction", "alarm_correction_at_limit"),
        Feature.FROST_PROTECTION: ("alarm_frost_not_warming", "alarm_handed_back_in_frost"),
        Feature.CIRCUIT_OVERSHOOT_ALARM: ("alarm_circuit_too_hot",),
        Feature.LOWEST_WATER_SUGGESTION: ("lowest_water_suggestion",),
        Feature.RELAY_PROOF: ("alarm_boiler_not_responding",),
        Feature.FORECASTS: ("forecast_snapshots",),
    }
)
_FEATURE_OF = {key: feature for feature, keys in FEATURE_ENTITIES.items() for key in keys}


def feature_of(key: str) -> Feature | None:
    """The feature an entity key belongs to; ``None`` for one of no feature."""
    return _FEATURE_OF.get(key)


def feature_configured(coordinator: SmartBoilerCoordinator, key: str) -> bool:
    """Whether the entity ``key`` is created: its feature is not inactive by the configuration
    alone — nothing known only at run time keeps an entity from being created."""
    feature = feature_of(key)
    if feature is None:
        return True
    return coordinator.configured_features()[feature].status is not FeatureStatus.INACTIVE


def feature_active(coordinator: SmartBoilerCoordinator, key: str) -> bool:
    """Whether the entity ``key`` is available as far as its feature goes: not inactive by the
    configuration and the zones' valves as they report."""
    feature = feature_of(key)
    data = coordinator.data
    if feature is None or data is None:
        return True
    state = data.features.get(feature)
    return state is None or state.status is not FeatureStatus.INACTIVE


def coded_text(
    coordinator: SmartBoilerCoordinator,
    platform: str,
    key: str,
    attribute: str,
    codes: Iterable[str],
) -> str:
    """P-39: codes of a list attribute as one text in Home Assistant's language — each from
    the entity's ``state_attributes.<attribute>.state.<code>``, English where the language has
    none, the code itself where no text exists — joined with ", " (provisional, K4)."""
    return ", ".join(code_text(coordinator, platform, key, attribute, code) for code in codes)


def code_text(
    coordinator: SmartBoilerCoordinator, platform: str, key: str, attribute: str, code: str
) -> str:
    """One code's text (``coded_text``)."""
    path = f"component.{DOMAIN}.entity.{platform}.{key}.state_attributes.{attribute}.state"
    return coordinator.texts.get(f"{path}.{code}", code)


def circuit_label(coordinator: SmartBoilerCoordinator, circuit_id: str) -> str:
    """P-73: a circuit as the options show it — its number in their list, as the circuit's form
    is titled — not its stored ID."""
    circuits = [circuit.circuit_id for circuit in coordinator.config.installation.circuits]
    return str(circuits.index(circuit_id) + 1) if circuit_id in circuits else circuit_id


def zone_key(hass: HomeAssistant, zone: str) -> str:
    """What a zone's entities are keyed on: the thermostat's registry entry, which stays when
    its entity ID is renamed; the entity ID only for a thermostat outside the registry."""
    entry = er.async_get(hass).async_get(zone)
    return entry.id if entry is not None else zone


class SmartBoilerEntity(CoordinatorEntity[SmartBoilerCoordinator]):
    """An entity of the plugin; ``zone`` or ``circuit`` make it one per zone or circuit."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartBoilerCoordinator,
        key: str,
        *,
        zone: str | None = None,
        circuit: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.key = key
        self.zone = zone
        self.circuit = circuit
        scope = zone_key(coordinator.hass, zone) if zone is not None else circuit
        self._attr_unique_id = f"{entry.entry_id}_{key}" + (f"_{scope}" if scope else "")
        self._attr_translation_key = key
        if zone is not None:
            self._attr_translation_placeholders = {"zone": coordinator.link.zone_name(zone)}
        elif circuit is not None:
            self._attr_translation_placeholders = {"circuit": circuit_label(coordinator, circuit)}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Versatile Thermostat Smart Boiler",
            model="Boiler monitor",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """The monitor's last refresh worked, and the entity's feature is not inactive (Y4)."""
        return super().available and feature_active(self.coordinator, self.key)


class ControlEntity(SmartBoilerEntity):
    """An entity showing control; it updates whenever control's status changes."""

    def __init__(self, coordinator: SmartBoilerCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        control = coordinator.control
        if control is None:
            raise ValueError("control is not set up")
        self.control: ControlUnit = control

    @property
    def available(self) -> bool:
        """Available while the control unit runs, whatever the monitor's refresh does: the
        control switch must stop the plugin exactly when something is wrong (P-02) — and
        while its feature is not inactive (Y4)."""
        return not self.control.stopping and feature_active(self.coordinator, self.key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.control.async_add_listener(self.async_write_ha_state))
