# Test Home Assistant

A Home Assistant 2026.9.3 in Docker, in a dedicated Proxmox LXC, running the plugin, Versatile
Thermostat 10.4.0 and SmartPI 0.4.0 as vendored, and the test-only boiler simulator
(`sim/custom_components/boiler_sim`). The acceptance scenarios run here (`docs/plan-0.2.md`,
J4) before anything reaches a real boiler.

Claude connects to this instance only after you say to start, only at the address in
`devenv/local.env`, and to no other Home Assistant.

## 1. The LXC (you — J2)

- A Debian 12 container with `nesting=1`, plus `keyctl=1` if it is unprivileged.
- Docker Engine with the compose plugin, from Docker's Debian repository.
- A deploy user that logs in with an SSH key and is in the `docker` group.
- A firewall that keeps the container away from your production Home Assistant, its MQTT broker
  and the OpenTherm Gateway. For example with nftables on the LXC (replace the placeholders):

  ```
  table inet test_isolation {
    chain output {
      type filter hook output priority 0; policy accept;
      ip daddr { <production-ha-ip>, <broker-ip>, <gateway-ip> } drop
    }
  }
  ```

- Internet access for pulling the image and VT's Python requirements (`vtherm_api` from PyPI).

## 2. Access for Claude (you — J2)

1. Generate a key pair for this project only, inside the project (git-ignored):
   `ssh-keygen -t ed25519 -N "" -f devenv/ssh/id_ed25519`. Add `devenv/ssh/id_ed25519.pub` to
   the deploy user's `~/.ssh/authorized_keys` on the LXC.
2. Copy `devenv/local.env.example` to `devenv/local.env` and fill in the host, the SSH user, the
   directory on the LXC and the URL.
3. After the first start and onboarding (section 3): create a long-lived access token (profile →
   Security → Long-lived access tokens) and put it in `TEST_HA_TOKEN`.

## 3. Deploy

- `scripts/deploy_test.sh --dry-run` lists what would be copied.
- `scripts/deploy_test.sh` copies the plugin, the vendored VT and SmartPI, the simulator and
  `configuration.yaml`, then starts or restarts the container.
- First start: open the URL, create the owner account, set the location and metric units.

`configuration.yaml` has no `default_config`, so nothing scans the local network. Only
`configuration.yaml` is copied into `config/`; the instance's own files there are left alone.

## 4. The test installation

Set up in the user interface — or by Claude through the API at J4, once you say to start:

1. **VT central configuration**: with the central mode select. Do not configure VT's central
   boiler — the plugin replaces it, and control refuses to start while it exists.
2. **One VT thermostat per simulated zone** (`zone_living`, `zone_bedroom`, `zone_bath`):
   type "over switch"; underlying switch `switch.boiler_sim_<zone>_valve`; room temperature
   `sensor.boiler_sim_<zone>_temperature`; outdoor temperature `sensor.boiler_sim_outdoor`. Use
   SmartPI in one zone, to test the learning pauses.
3. **VTherm Smart Boiler**:
   - Signals: `binary_sensor.boiler_sim_flame`, `sensor.boiler_sim_flow`,
     `sensor.boiler_sim_return`, `sensor.boiler_sim_modulation`,
     `binary_sensor.boiler_sim_dhw_active`, `sensor.boiler_sim_pressure` and
     `sensor.boiler_sim_outdoor`. At the advanced level, also the control setpoint
     `sensor.boiler_sim_ch_setpoint`, `binary_sensor.boiler_sim_ch_active` and
     `binary_sensor.boiler_sim_pump_running`.
   - Weather: `weather.boiler_sim_weather`.
   - Boiler: class "Flow setpoint", DHW "combi"; one unmixed circuit; the three VT zones.
4. **Control** (options → Control):
   - Write path "OpenTherm Gateway", gateway ID `sim`, topology "Gateway with a thermostat".
   - Read-back `sensor.boiler_sim_ch_setpoint`; design flow temperature 55 °C.

The plugin enforces the monitoring period (7 days at least) here as anywhere. The test instance
can simply monitor for 7 days first; or, with your consent at J4, its stored monitoring start can
be moved back while Home Assistant is stopped — on the test instance only.

Other write paths: set `write_type: persistent` (or `held`) in `configuration.yaml` and use the
entity path with `number.boiler_sim_flow_setpoint`; the switch hand-back uses
`switch.boiler_sim_external_control`. The firmware MQTT path needs a broker in the LXC and
`mqtt_topic` in `configuration.yaml`.

## 5. What runs at J4

The acceptance scenarios of `docs/plan-0.2.md` (J4) run first in-process
(`tests/integration/test_acceptance.py`), then here through the API. Scenarios drive the
simulator's services (`boiler_sim.set_outdoor`, `fail_signal`, `force_setpoint`,
`ignore_writes`, `start_dhw`, `set_topology`), the control switch and the options. Their results
come from entity states and the simulator's command counters (attributes of
`sensor.boiler_sim_persistent_writes`). The only address contacted is `TEST_HA_URL`.
