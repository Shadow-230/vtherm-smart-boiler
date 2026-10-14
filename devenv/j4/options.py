"""J4: the options instance 1 is set up with (devenv/README.md, section 4), as the flat changes
``walk.save_options`` takes, and the menu items that ask them (I8). Pure data, so the
in-process test that walks them through the options flow (``tests/integration/test_j4_walk.py``)
reads the same values the runner writes."""

from __future__ import annotations

# The menu items instance 1's options live in, in the menu's order.
GATEWAY_ITEMS = (
    "interface",
    "signals",
    "circuit_1",
    "control",
    "control_curve",
    "control_behaviour",
    "control_frost",
    "control_alarms",
)

# Instance 1: a gateway with an OpenTherm thermostat, one unmixed circuit without a maximum of
# its own (70 °C, no too-hot alarm), the curve's room entered and the comfort correction off —
# as the scenarios ran before G11; the corrections' scenarios (corrections.py) switch them on.
BASE_GATEWAY: dict[str, object] = {
    # Control device: asked only of an entry made before the connection question.
    "write_path": "opentherm_gw",
    # Boiler interface; the gateway's ID is asked only where there are several gateways.
    "gateway_id": "sim",
    "topology": "gateway_with_thermostat",
    "thermostat_kind": "opentherm",
    # Boiler signals: the read-backs (I8.5b).
    "ch_setpoint": "sensor.otgw_sim_boiler_control_setpoint",
    "ch_enabled": "binary_sensor.otgw_sim_boiler_master_ch_enabled",
    # Circuit 1: its highest water temperature (the curve's former hard maximum, I8 F2).
    "max_flow": None,
    "max_flow_alarm": None,
    "max_flow_alarm_min": None,
    # Heating curve.
    "design_outdoor": -15.0,
    "design_flow": 55.0,
    "hard_min": 20.0,
    "room_mode": "manual",
    "room": 20.0,
    "room_excluded": [],
    "offset": 0.0,
    "comfort_correction": False,
    # Control behaviour; "off" is asked only at the simple level, where S-49 refuses it.
    "activation_delay_s": 0,
    "count_threshold": 1,
    "learning_pauses": True,
    "ramp_k_per_min": 1.0,
    "decision_interval_min": 5.0,
    "off_setpoint": 10.0,
    # Frost protection (the advanced level).
    "frost_limit": 5.0,
    "frost_release": 7.0,
    # Alarm reactions.
    "write_ignored": "info",
    "return_after_outside_change": False,
}

# The base's keys a form asks only in some installations (above); every other key must be asked.
ASKED_SOMETIMES = frozenset({"write_path", "gateway_id", "off_setpoint"})

# E7: a circuit run by other automation (I8.8a), added through "Add circuit" and removed after.
# It asks through a helper of instance 1's configuration (devenv/config/configuration.yaml); its
# need, 50 °C — a fan heater's, the kind of load the field is for —, lies above the curve at the
# simulator's outdoor temperature, so the water shows it, nothing added (2026-10-14).
CIRCUIT_ASKS_ENTITY = "input_boolean.j4_circuit_asks"
CIRCUIT_ASKS_NEED = 50.0
CIRCUIT_ASKS: dict[str, object] = {
    "name": "J4 heater",
    "control": "separate",
    "request_entity": CIRCUIT_ASKS_ENTITY,
    "needed_temperature": CIRCUIT_ASKS_NEED,
}
REMOVE_CIRCUIT: dict[str, object] = {"remove_circuit": True}
