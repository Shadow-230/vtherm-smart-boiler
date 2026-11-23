[Polska wersja](../../pl/specification/device-connections.md)

# Boiler connections and the device template

Status: current. **The plugin does not read these files yet.** Today the same facts are in its
code. This document records them device by device, in the format the plugin will read after the
first release ([the plan](../development/plans/plan-device-templates.md)). Names and values are
in English in every language.

## 1. Three layers

One device can be reached in several ways, and each way can differ. So a template has three
layers:

1. **`protocol`**: what the device uses to talk to the boiler (`opentherm`, `ems`, `ebus`, `bsb`,
   `on_off`, `proprietary`, `unknown`).
2. **`behaviour`**: what the device does, however it is reached: how it keeps a setpoint, how it
   stops heating, how it hands the boiler back, and what it does with hot water. Safety depends
   on this layer.
3. **`access`**: a list of routes from Home Assistant to the device. Each route has its own `id`,
   integration, commands, readings and level of verification.

An `access` `id` is the connection name an installation stores today (`opentherm_gw`,
`otgw_mqtt` …), so moving to templates needs no migration.

Files are in YAML, one per device, and ship with a release after review. Users cannot add their
own in the first version, because a template decides what is written to a boiler.

## 2. What a template may not do

A template **chooses** among mechanisms in the code. It does not describe their steps.

- **Writers:** service, MQTT command, entity, relay.
- **Stopping heating:** switch, gateway flag, setpoint value, relay.
- **Hand-back:** value, timeout, switch, gateway release, the relay's rest state.

A device that uses these needs only a file. A new mechanism needs code and tests.

These rules stay in the code and apply whatever a file says:

- nothing is written to a boiler's permanent memory, and a write type that is not known is not
  written;
- a timeout hand-back needs a setpoint that lapses;
- "off" as a low setpoint only where the device falls back by itself;
- the water temperature limits and the write guards are not parameters;
- **nothing is written through a cloud service** ([section 6](#6-wi-fi-and-the-cloud));
- the plugin never writes hot water (`dhw.write` is always `none`).

A file that fails its check leaves that connection at monitoring only.

## 3. The fields

Top level: `schema_version`, `id`, `name`, `protocol`, `behaviour`, `access`. Units end the name:
`_s` is seconds, `_c` is °C.

**`behaviour`**

| Field | Values | Meaning |
|---|---|---|
| `topologies` | `gateway_standalone`, `gateway_with_thermostat`, `virtual` | how the device can sit between Home Assistant and the boiler |
| `setpoint.write_type`, `ch.write_type` | `expiring`, `held`, `persistent`, `unknown` | how the device keeps a written value; `unknown`: the user declares it, and until then nothing is written |
| `setpoint.expires_after_s`, `repeat_every_s`, `min_c` | numbers | when the value lapses, how often it is repeated, the lowest value the device takes as a lapsing one |
| `ch.off_method` | `switch`, `gateway_flag`, `setpoint`, `relay` | how heating is stopped |
| `ch.off_setpoint_c` | number | the value that means "off", with `off_method: setpoint` |
| `hand_back.method` | `value`, `timeout`, `switch`, `gateway_release`, `relay_rest` | how the boiler is given back |
| `hand_back.value`, `timeout_s` | numbers | that method's parameters |
| `hand_back.confirmed_by` | `read_back`, `none` | what shows the boiler was given back |
| `on_ha_stop.effect` | `setpoint_lapses`, `held_until_restart`, `stays`, `unknown` | what happens when Home Assistant stops |
| `on_ha_stop.within_s` | number | how soon, by default |
| `dhw.write` | `none` | the plugin never writes hot water |
| `dhw.active_source` | `status_bit`, `entity`, `inferred`, `none` | how a hot-water run is seen |
| `dhw.enable_kept_by` | `thermostat`, `device`, `not_kept`, `unknown`, or one per topology | who keeps hot water allowed |
| `dhw.flow_during_draw` | `dhw_water`, `ch_water`, `unknown` | what the flow reading shows during a run; it depends on the boiler, so a template leaves it `unknown` |
| `dhw.signals` | `active`, `enable`, `setpoint`, `setpoint_bounds`, `temperature`, `flow_rate`, `burner_starts`, `burner_hours`, `pump_starts`, `pump_hours` | what the device can report |
| `fault_details.needs_indication` | `true`, `false` | a fault's details count only with the boiler's general fault indication on |
| `safety.must_confirm` | setting names | what the user must confirm before control |
| `safety.known_limits` | names | what the user must be told |

The boiler's type (combi, tank) and hot-water priority are not here: they belong to the
installation, not to how it is connected.

**Each route in `access`**

| Field | Values | Meaning |
|---|---|---|
| `id` | a connection name | as stored in the installation |
| `integration` | a Home Assistant domain | absent where any integration will do |
| `link` | `local`, `cloud` | only where Home Assistant cannot tell, as behind an MQTT bridge |
| `verified` | see section 4 | how far this route was checked |
| `boiler_class` | `flow_setpoint`, `on_off`, `read_only`, `by_mode` | what the plugin can do with the boiler |
| `control_modes` | `full`, `on_off`, `monitor` | what the user can choose |
| `setup_fields` | field names | what the setup asks |
| `transport.type` | `service`, `mqtt`, `entity`, `relay`, `none` | how commands go |
| `transport.domain`, `command_topic`, `setpoint_command`, `ch_command` | text | the commands |
| `gateway_source` | `platform`, `same_device`, `none` | how the gateway's own entities are told |
| `readings.report_mode` | `periodic`, `on_change`, `unknown` | how the device reports |
| `readings.report_every_s`, `heartbeat_s` | numbers | its rhythm |
| `readings.unknown_values` | signal: value | a value that means "not known" |
| `readings.signal_topics` | signal: topic | MQTT topics; `"*"`: a message reports every signal |

## 4. How far a route was checked

| `verified` | Meaning |
|---|---|
| `real_device` | run on a real boiler |
| `simulator` | run in J4, on a test Home Assistant with the simulator |
| `documents` | read from the device's source or documents, and tested in-process |
| `none` | not checked |

**No route has run on a real boiler yet.** The first will be at step K6.

## 5. The cards

### OpenTherm Gateway

```yaml
schema_version: 1
id: otgw
name: OpenTherm Gateway
protocol: opentherm
behaviour:
  topologies: [gateway_standalone, gateway_with_thermostat]
  setpoint: {write_type: expiring, expires_after_s: 60, repeat_every_s: 30, min_c: 8}
  ch: {write_type: held, off_method: gateway_flag}
  hand_back: {method: gateway_release, confirmed_by: read_back}
  on_ha_stop: {effect: setpoint_lapses, within_s: 60}
  dhw:
    write: none
    active_source: status_bit
    enable_kept_by: {gateway_with_thermostat: thermostat, gateway_standalone: not_kept}
    flow_during_draw: unknown
    signals: [active, enable, setpoint, setpoint_bounds, temperature]
  fault_details: {needs_indication: true}
  safety: {must_confirm: [], known_limits: [read_back_is_gateway_echo]}
access:
  - id: opentherm_gw
    integration: opentherm_gw
    verified: simulator
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [gateway_id]
    transport:
      type: service
      domain: opentherm_gw
      setpoint_command: set_control_setpoint
      ch_command: set_central_heating_ovrd
    gateway_source: platform
    readings:
      report_mode: periodic
      unknown_values: {flow: 0, return: 0, pressure: 0, flue_gas: 0, outdoor: 0, room_temperature: 0}
  - id: otgw_mqtt
    integration: mqtt
    verified: documents
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [mqtt_top, mqtt_node]
    transport:
      type: mqtt
      command_topic: "{mqtt_top}/set/{mqtt_node}/{command}"
      setpoint_command: ctrlsetpt
      ch_command: chenable
    gateway_source: same_device
    readings:
      report_mode: on_change
      heartbeat_s: 60
      unknown_values: {flow: 0, return: 0, pressure: 0, flue_gas: 0, outdoor: 0, room_temperature: 0}
      signal_topics:
        flame: flame
        flow: Tboiler
        return: Tret
        modulation: RelModLevel
        pressure: CHPressure
        dhw_active: domestichotwater
        ch_active: centralheating
        fault_indication: fault
        outdoor: Toutside
        flue_gas: Texhaust
        ch_setpoint: TSet
```

`CS` lapses unless repeated, and `CH=0` stays until `CH=1` or a gateway reset. Without a thermostat
the gateway does not keep hot water allowed. On the MQTT route, entities written by hand in YAML
have no Home Assistant device: they count as the gateway's when its setpoint has none either.

### ESPHome OpenTherm

```yaml
schema_version: 1
id: esphome_opentherm
name: ESPHome OpenTherm
protocol: opentherm
behaviour:
  topologies: [virtual]
  setpoint: {write_type: held}
  ch: {write_type: held, off_method: switch}
  hand_back: {method: value, confirmed_by: read_back}
  on_ha_stop: {effect: held_until_restart, within_s: 900}
  dhw:
    write: none
    active_source: status_bit
    enable_kept_by: device
    flow_during_draw: unknown
    signals: [active, enable, setpoint, temperature]
  fault_details: {needs_indication: false}
  safety: {must_confirm: [esphome_safe_start], known_limits: [low_setpoint_leaves_ch_enabled]}
access:
  - id: esphome
    integration: esphome
    verified: documents
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [setpoint_entity, ch_entity]
    transport: {type: entity}
    gateway_source: none
    readings: {report_mode: on_change}
```

The ESP keeps its last values until it restarts, by default 15 minutes after it loses Home
Assistant's API, and then takes its own start values. A low setpoint leaves heating enabled, so
heating is stopped by its switch.

### EMS-ESP

```yaml
schema_version: 1
id: ems_esp
name: EMS-ESP
protocol: ems
behaviour:
  topologies: [virtual]
  setpoint: {write_type: expiring, expires_after_s: 60, repeat_every_s: 30}
  ch: {write_type: unknown, off_method: setpoint, off_setpoint_c: 0}
  hand_back: {method: timeout, timeout_s: 60}
  on_ha_stop: {effect: setpoint_lapses, within_s: 60}
  dhw:
    write: none
    active_source: entity
    enable_kept_by: device
    flow_during_draw: unknown
    signals: [active, setpoint, temperature]
  fault_details: {needs_indication: false}
  safety: {must_confirm: [], known_limits: [setpoint_only_below_panel_setting]}
access:
  - id: ems_esp
    integration: mqtt
    verified: documents
    boiler_class: flow_setpoint
    control_modes: [full, monitor]
    setup_fields: [ems_esp_base, setpoint_entity]
    transport: {type: entity}
    gateway_source: none
    readings:
      report_mode: periodic
      report_every_s: 10
      signal_topics: {"*": [boiler_data, boiler_data_dhw]}
```

`selflowtemp` lapses within about a minute, and 0 repeated keeps heating off. The boiler takes a
setpoint from the bus only below its own panel setting.

### Relay on an on/off boiler

```yaml
schema_version: 1
id: relay
name: Relay on an on/off boiler
protocol: on_off
behaviour:
  ch: {off_method: relay}
  hand_back: {method: relay_rest}
  on_ha_stop: {effect: stays}
  dhw: {write: none, active_source: none, enable_kept_by: unknown, flow_during_draw: unknown}
  fault_details: {needs_indication: false}
access:
  - id: relay
    verified: simulator
    boiler_class: on_off
    control_modes: [on_off, monitor]
    setup_fields: [relay_entity]
    transport: {type: relay}
    gateway_source: none
    readings: {report_mode: unknown}
```

The relay's timers and repeats are its own mechanism, set in the relay's form.

### The boiler's Wi-Fi module or the maker's integration

```yaml
schema_version: 1
id: boiler_module
name: The boiler's Wi-Fi module or the maker's integration
protocol: proprietary
behaviour:
  topologies: [gateway_standalone, gateway_with_thermostat, virtual]
  setpoint: {write_type: unknown}
  ch: {write_type: unknown, off_method: switch}
  on_ha_stop: {effect: unknown}
  dhw: {write: none, active_source: entity, enable_kept_by: unknown, flow_during_draw: unknown}
  fault_details: {needs_indication: false}
access:
  - id: boiler_module
    verified: none
    boiler_class: by_mode
    control_modes: [full, monitor]   # through a cloud: monitoring only
    setup_fields: [setpoint_entity, ch_entity]
    transport: {type: entity}
    gateway_source: none
    readings: {report_mode: unknown}
```

Nothing is known in advance, so nothing is written until the user declares how the entity keeps a
value. Through a cloud it stays monitoring only.

### Another writable entity

```yaml
schema_version: 1
id: other_entity
name: Another writable entity
protocol: unknown
behaviour:
  topologies: [gateway_standalone, gateway_with_thermostat, virtual]
  setpoint: {write_type: unknown}
  ch: {write_type: unknown, off_method: switch}
  on_ha_stop: {effect: unknown}
  dhw: {write: none, active_source: entity, enable_kept_by: unknown, flow_during_draw: unknown}
  fault_details: {needs_indication: false}
access:
  - id: other_entity
    verified: simulator
    boiler_class: flow_setpoint
    control_modes: [full, monitor]   # through a cloud: monitoring only
    setup_fields: [setpoint_entity, ch_entity]
    transport: {type: entity}
    gateway_source: none
    readings: {report_mode: unknown}
```

The user fills in what this card leaves `unknown`.

### Another integration, read only

```yaml
schema_version: 1
id: read_only
name: Another integration, read only
protocol: unknown
behaviour:
  dhw: {write: none, active_source: entity, enable_kept_by: unknown, flow_during_draw: unknown}
access:
  - id: read_only
    verified: none
    boiler_class: read_only
    control_modes: [monitor]
    setup_fields: []
    transport: {type: none}
    gateway_source: none
    readings: {report_mode: unknown}
```

## 6. Wi-Fi and the cloud

Wi-Fi is how a device connects. It says nothing about where commands go. Home Assistant knows:
each integration's manifest has `iot_class`.

| `iot_class` | Examples | Control |
|---|---|---|
| `local_push` | `opentherm_gw`, `mqtt`, `esphome` | allowed |
| `local_polling` | `incomfort`, `bsblan` | allowed |
| `cloud_polling`, `cloud_push` | `vicare`, `evohome` | **monitoring only** |

A cloud cannot carry this control. With no internet the plugin could not hand the boiler back, and
cloud services limit their calls. On Viessmann's free tier, for example, 1450 calls a day are
allowed and going over blocks the account for 24 hours; Home Assistant's own polling takes 1440.

The plugin cannot see a helper or an MQTT bridge in front of a cloud, and takes an integration
that does not declare `iot_class` for a local one. A template can say `link: cloud` for a route it
knows.

## 7. Routes not covered yet

These exist but have no card of their own, and work today only as "another writable entity" where
they offer writable entities:

- ESPHome over MQTT instead of its native API, with its own `reboot_timeout`;
- the REST interfaces of the OTGW firmware, EMS-ESP and DIYLess;
- DIYLess, on its stock firmware or on ESPHome;
- other boiler buses and bridges, such as eBUS or BSB-LAN.
