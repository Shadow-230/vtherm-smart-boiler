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
      ip6 daddr { <production-ha-ipv6>, <broker-ipv6>, <gateway-ipv6> } drop
    }
  }
  ```

  The container's traffic is forwarded (port 8123 is published), so it does not pass the LXC's
  output chain: block it on the forwarding path too, in Docker's `DOCKER-USER` chain, for IPv4
  and IPv6 (the IPv6 chain exists where Docker manages ip6tables; to check at J2):

  ```
  iptables  -I DOCKER-USER -d <production-ha-ip>,<broker-ip>,<gateway-ip> -j DROP
  ip6tables -I DOCKER-USER -d <production-ha-ipv6>,<broker-ipv6>,<gateway-ipv6> -j DROP
  ```

  Make both rules persistent (for example with `iptables-persistent`), since Docker rebuilds its
  chains at start but keeps `DOCKER-USER`'s rules only while they are loaded.
- The check (T-25): from inside the container, every TCP attempt to each service port of the
  production Home Assistant, its broker and the gateway, over IPv4 and IPv6, must time out. A
  refusal is a failure: with the DROP rules above it means the packet reached the target. For
  each address and port:

  ```
  docker exec ha-test python3 -c "
  import socket, sys
  try:
      socket.create_connection((sys.argv[1], int(sys.argv[2])), 5); print('REACHABLE')
  except TimeoutError:
      print('blocked')
  except OSError as e:
      print('REACHABLE or rejected:', e)" '<ip>' <port>
  ```

  Only "blocked" passes. First run it once against an address and port the container must reach
  (e.g. a public web server on 443): it must print REACHABLE, which shows the check itself works.
  Run the whole check again after a reboot of the LXC, to see the rules persist. You run it at
  J2; Claude repeats it over SSH only after you have said to start J4.

- Internet access for pulling the image and VT's Python requirements (`vtherm_api` from PyPI).
  Home Assistant installs the newest `vtherm_api` at its first start, not the 0.5.0 the tests
  pin; J4's report records the version installed (CI's job with the latest `vtherm_api` runs the
  same combination).

## 2. Access for Claude (you — J2)

1. Generate a key pair for this project only, inside the project (git-ignored):
   `ssh-keygen -t ed25519 -N "" -f devenv/ssh/id_ed25519`. Add `devenv/ssh/id_ed25519.pub` to
   the deploy user's `~/.ssh/authorized_keys` on the LXC.
2. Copy `devenv/local.env.example` to `devenv/local.env` and fill in the host, the SSH user, the
   directory on the LXC and the URL.
   That directory is not created by the deploy: create it on the LXC yourself, and in it the
   empty marker file `.vtherm-smart-boiler-test-ha` (`touch .vtherm-smart-boiler-test-ha`), which
   tells the deploy that this host is the test LXC — without it nothing is copied and Home
   Assistant is not restarted (PB-87).
3. After the first start and onboarding (section 3): create a long-lived access token (profile →
   Security → Long-lived access tokens) and put it in `TEST_HA_TOKEN`.

## 3. Deploy

- `scripts/deploy_test.sh --dry-run` lists what would be copied; it needs no key and connects
  nowhere.
- `scripts/deploy_test.sh` copies the plugin, the vendored VT and SmartPI, the simulator (which
  carries its physics) and `configuration.yaml` as files — links into `vendor/` followed — in one
  tar stream over SSH, so only `tar` and `ssh` are needed on either side; each integration
  replaces its old copy whole. Then it starts or restarts the container.
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
3. **Smart Boiler for Versatile Thermostat**:
   - Signals: `binary_sensor.boiler_sim_flame`, `sensor.boiler_sim_flow`,
     `sensor.boiler_sim_return`, `sensor.boiler_sim_modulation`,
     `binary_sensor.boiler_sim_dhw_active`, `sensor.boiler_sim_pressure` and
     `sensor.boiler_sim_outdoor`. At the advanced level, also the control setpoint
     `sensor.boiler_sim_ch_setpoint`, `binary_sensor.boiler_sim_ch_active` and
     `binary_sensor.boiler_sim_pump_running`.
   - Weather: `weather.boiler_sim_weather`.
   - Boiler: class "Flow setpoint", DHW "combi"; one unmixed circuit; the three VT zones.
4. **The simulated gateway**: Settings → Devices & services → Add integration → "OpenTherm Gateway
   (simulator stub, test only)" → Submit. Its entry has the gateway ID `sim`. It is a test-only
   stand-in on the simulator for Home Assistant's own OpenTherm Gateway integration, which it
   overrides in this instance only (`scripts/deploy_test.sh` deploys it nowhere else).
5. **Control** (options → Control):
   - Write path "OpenTherm Gateway", topology "Gateway with a thermostat", thermostat terminals
     "OpenTherm thermostat"; read-back `sensor.otgw_sim_boiler_control_setpoint`, heating read-back
     `binary_sensor.otgw_sim_boiler_master_ch_enabled`; gateway ID `sim`; design flow 55 °C.
   - At the advanced level, the signal "Wired thermostat setpoint"
     `sensor.otgw_sim_thermostat_room_setpoint` (the wall thermostat's own setting, 21 °C 06:00–22:00
     and 17 °C otherwise, UTC).

No monitoring period holds control back (the user's decision, 2026-10-08): control may be switched
on as soon as the installation is set up; the verdict comes after 7 days of data.

Other write paths: set `write_type: held` (or `persistent`) and `ch_write_type` in
`configuration.yaml` and use the entity path with `number.boiler_sim_flow_setpoint` and
`switch.boiler_sim_ch_enable`; the switch hand-back uses `switch.boiler_sim_external_control`. The
relay (an on/off boiler): uncomment the relay block in `configuration.yaml` (and drop
`wall_thermostat`), redeploy, set the boiler class to "On/off" and use the relay path with
`switch.boiler_sim_relay`, declaring its settings as the block gives them and ticking "this is a
separate relay contact". The firmware MQTT path needs a broker in the LXC and `mqtt_topic` in
`configuration.yaml` — only if the stub route fails.

## 5. What runs at J4

The acceptance scenarios of `docs/plan-0.2.md` (J4) run first in-process
(`tests/integration/test_acceptance.py`), then here through the API. Scenarios drive the
simulator's services — `boiler_sim.set_outdoor`, `fail_signal` (a boiler signal; `gateway`: the
gateway out of reach, its commands dropped — the lost link; `relay`: the relay's state unknown;
`thermostat_setpoint`; a fault signal), `force_setpoint` (another controller), `ignore_writes`,
`refuse_id1` (confirmed, then dropped), `clip_setpoint`, `drop_override` (a single fall-back),
`start_dhw`, `set_topology`, `set_zone_mode` (a zone VT switched off closes its valve),
`set_room_temperature` (one room set at once, as to 4 °C for frost),
`reset_gateway` and `restart_device` (a lost command with a trace), `relay_restart` (seen, or with
`reported: false` unseen), `relay_wifi_loss`, `relay_switch` (an automation or its button),
`set_wall_setpoint`, `set_fault` — the stub's own `opentherm_gw.reset_gateway`, the control
switch and the options, and the test-only fault injector `j4_faults` (on instance 1, by
`configuration.yaml`): `monitor` (the plugin's own monitor fails, or works again),
`restart_with_stores` (the entry stopped, its stores replaced or removed as a crash, a lost file
or another version leaves them, and started again) and `remove_options` (answers taken from its
options, as an entry made before 0.2.2 lacks them). It is sent to the test Home Assistant only
and is never part of the plugin's release. Their results come from entity states and the simulator's command
counters (attributes of `sensor.boiler_sim_persistent_writes`: commands per path, `ch_writes`,
`relay_commands`, `dhw_enable_writes`; its state counts only writes of type persistent). The
starts criterion (decision 8 of `docs/plan-0.2.3.md`; `SCOPE.md`, fixed values) reads the
monitor's starts per hour over 24 h at +8 °C and at −5 °C, each with a ±3 K daily outdoor swing,
against the boiler's own regulation's, with the rooms as warm as under it (comfort parity); the
acceptable ratio is decided at K4 (1.10 until then), and in-process the test carrying the swing
is a strict xfail until K4. Z3 measured the criterion holding only with the comfort correction
off (`research/2026-10-02-z3-starts-ratio.md`). The only address contacted is `TEST_HA_URL`.

### The starts criterion on four instances

The criterion's four runs go side by side on instances 2 to 5, each deployed with
`scripts/deploy_test.sh --instance N --config starts`: `devenv/config/starts.yaml` is the house of
`tests/sim/test_control_loop.py`'s comparison — the large condensing boiler, three radiator zones,
no wall thermostat, so that without the plugin the boiler runs its own regulation (its own curve,
heating whenever a zone valve is open) — with a ±3 K daily swing around the mean in
`input_number.j4_outdoor_mean`. Instance 1 keeps `configuration.yaml` for the other scenarios.

| Instance | Port | Run |
|---|---|---|
| 1 | 8123 | the other scenarios, one after another |
| 2 | 8124 | under control, +8 °C ±3 K |
| 3 | 8125 | the boiler's own regulation (control off), +8 °C ±3 K |
| 4 | 8126 | under control, −5 °C ±3 K |
| 5 | 8127 | the boiler's own regulation (control off), −5 °C ±3 K |

On each: the three VT zones on TPI, heating at 20.5, 19.5 and 22 °C (the simulator's targets);
the plugin's curve the boiler's own (design flow 55 °C at −15 °C, exponent 1, offset 5 K, lowest
25 °C, highest 70 °C), every other option at its default — the comfort correction off; the mean
set on `input_number.j4_outdoor_mean`; control switched on on 2 and 4 only. After a day to settle,
the next 24 h are compared: burner starts per hour (`binary_sensor.boiler_sim_flame` off → on),
heating switchings, and each room's mean temperature (comfort parity: at most 0.3 K below the
boiler's own regulation's); the criterion is at most 1.10 times its starts per hour
(provisional, K4).

## 6. More instances (optional)

Up to five Home Assistants can run in the same LXC, so long scenarios run side by side — the
starts criterion's four runs of 24 h (under control and under the boiler's own regulation, at
+8 °C and at −5 °C) in one day instead of four, with a fifth instance for the short scenarios
meanwhile, or the gateway path on one and the relay path on another. Instance N = 2 to 5 shares
the image, has its own directory, configuration, marker and container (`ha-test-N`), and listens
on port 8122 + N (8124 to 8127). Each costs about 0.5–0.8 GB of memory and 1 GB of disk, plus
its recorder's growth over a day's run: two fit in 4 GB; five want 8 GB, 4 cores and some 24 GB
of disk.

1. On the Proxmox host, allow its port into the container: add `IN ACCEPT -p tcp -dport 8124`
   (8125 to 8127) to the container's rules (`/etc/pve/firewall/<CT ID>.fw`, or the container →
   Firewall). Out stays as it is.
2. In the LXC, as root: `mkdir -p /opt/ha-test-2 && touch
   /opt/ha-test-2/.vtherm-smart-boiler-test-ha && chown -R deploy:deploy /opt/ha-test-2`
   (`-3` to `-5` alike).
3. In `devenv/local.env`: `TEST_HA_DIR_N` and `TEST_HA_URL_N` with its port.
4. `scripts/deploy_test.sh --instance N` (first a dry run with `--dry-run --instance N`).
   Then either open the URL, create the owner account and put a long-lived access token in
   `TEST_HA_TOKEN_N`; or — simpler, and what the test LXC does — give it the first instance's
   login: stop it (`docker compose stop homeassistant` in its directory), copy the four files
   with `docker cp ha-test:/config/.storage/<file> - | docker cp - ha-test-N:/config/.storage/`
   for `auth`, `auth_provider.homeassistant`, `onboarding` and `core.config`, and start it
   again. It then needs no owner account of its own, `TEST_HA_TOKEN` works there, and
   `TEST_HA_TOKEN_N` stays empty.
5. Set up the test installation there as in section 4. Claude repeats T-25 in it too
   (`docker exec ha-test-N …`).

