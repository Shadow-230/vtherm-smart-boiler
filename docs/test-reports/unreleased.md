# Test report — unreleased (provisionally 0.2.3b1)

**Status: in progress.** J4 runs in the test Home Assistant since 2026-10-08; this report is
filled in as its batches end and is complete once the starts criterion (2026-10-10) and the
scenarios needing other simulator configurations have run. How reports are made:
`docs/test-reports/README.md`.

## 1. Version and code

| | |
|---|---|
| Version | 0.2.3b1 in the manifest (provisional, decided at K4 and K5) |
| Plugin code tested | `dev` at 9df2f06 (control from the first day, PR #22) — no plugin change since |
| Test tools | `dev` at 5b2cab8: the simulator with `set_room_temperature`, the fault injector `j4_faults` (PR #25), five instances (PR #23), the starts configuration (PR #24) |
| J4 started | 2026-10-08, by the user |

## 2. Environment

| | |
|---|---|
| Home Assistant | 2026.9.3 (the test Home Assistant and CI); 2026.9.0 in CI, the oldest supported |
| Versatile Thermostat | 10.4.0 |
| SmartPI | 0.4.0 |
| `vtherm_api` | 0.5.0, as Home Assistant installed it in the test Home Assistant |
| Python | 3.14 |
| Test Home Assistant | the dedicated test LXC (Debian 13, Docker, the firewall on the Proxmox host blocking the home network: T-25 passed), five instances |

## 3. Automated tests

| Suite | Result |
|---|---|
| Core, without Home Assistant (`tests/core`) | 1399 passed |
| The others, with Home Assistant | 2732 passed, 4 expected failures |
| `ruff check`, `ruff format --check`, `mypy` (strict) | clean |
| CI (both Home Assistant versions, hassfest, HACS) | green on every pull request merged into `dev` |

The four expected failures are strict ones that wait for decisions at K4: J4's starts criterion
with the daily outdoor swing (×1.20 at +8 °C and ×2.16 at −5 °C against the boiler's own
regulation, rooms as warm; `tests/sim/test_control_loop.py`) and its band test.

## 4. J4 in the test Home Assistant — instance 1

Instance 1: the condensing boiler `condensing_small`, an OpenTherm wall thermostat on the
gateway's terminals, the gateway with the thermostat, the expiring setpoint, three radiator zones
under VT (TPI; SmartPI in the bedroom), outdoor 3 °C. "Safe hand-back" is the gateway receiving
the lowest water temperature (20 °C), CH on, then the setpoint released (0), in that order.

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| A1 | heating follows VT's zones both ways | pass | CH off 6 s and 0 s after the last valve closed; on 6 s after a valve opened (control step 10 s) |
| A2 | VT's central mode "Stopped" | pass | zones off, no demand, CH off, the setpoint still held — no hand-back; "Auto" heats again |
| A3 | control switched off | pass | the safe hand-back; the gateway back to the wall thermostat's 42 °C; nothing more |
| B1 | the plugin reloaded | pass | the safe hand-back, then control resumed |
| B2 | the plugin's entry disabled, then enabled | pass | the safe hand-back, no loop left for 2 min; enabled: control back as left |
| B4 | the thermostat heats again after a hand-back that followed "off" | pass | CH=0 by control, then the safe hand-back with CH=1; the wall thermostat's call reached the boiler |
| C1 | stale data (the flow signal) | pass | nothing written for 4 min; then the safe hand-back, "handed back", alarm "boiler data lost" |
| C2 | the outdoor sensor failed | pass | the weather instead (`outdoor_weather`), the setpoint held |
| C3 | the gateway's whole link lost | pass | "handed back", reason `boiler_link_stale`; the hand-back sent again and again; alarm "hand-back failed" |
| C4 | a hand-back while the gateway is away | pass | alarm at once, still on after 3 min; taken within 70 s of the gateway's return; alarm cleared; nothing more |
| C5 | a gateway reset | pass | the command sent again 14 s after the reset (before the 30-s keep-alive); no hand-back, no alarm |
| D1 | commands dropped at the gateway from the start | pass (reviewed) | alarm "boiler does not take the command" 6 min 10 s after control on (three counted sends); never another controller; no hand-back; not sent again |
| D3 | another controller (setpoint forced to 62 °C) | pass | rewritten once; then the safe hand-back, latched `outside_change`; no fight for 2 min |
| D6 | a flat setpoint clipped at the gateway | pass | judged another controller: the safe hand-back, latched `outside_change` |
| E2 | a zone outside the central mode under "Stopped" | pass | the living room kept asking; the plugin heated for it; no hand-back |
| E3 | VT's activation delay of 120 s | pass (reviewed) | starts 125, 120 and 130 s after the first call; a call dropped during the wait neither cancelled nor restarted it; stops 0–10 s |
| F1 | the boiler's low-pressure fault | pass | nothing for 4 min; then CH=0, no hand-back, no latch, state `boiler_fault`, repair issue; CH back once cleared |
| F2 | the boiler's lockout | pass | as F1 |
| G1 | no confirmed-setpoint source | pass | refused by the options form (`confirmed_entity_missing`) |
| G2 | monitor mode | pass | refused by the options form (`topology_no_control`) |
| G3 | an on/off contact, or "I don't know", on the thermostat terminals | pass | the form warns "This change stops control" and saves only with "Save anyway"; then the switch refused (`blocked_thermostat_on_off`; for "I don't know" control waits), nothing written, the thermostat heating |
| H1 | every VT zone unavailable | pass | the command held 10 min (`zones_recognition`); then alarm "no zone known", repair issue, the safe hand-back to the thermostat; control back when the zones returned |
| M1 | the plugin's own monitor fails (fault injector) | pass | control went on 4 min; then the safe hand-back, a blocker (`monitor_failed`), not a latch; repair issue; nothing written while failing |
| K1 | stores of a crashed run (fault injector) | pass | the safe hand-back first; the switch off; nothing more |

Runs reviewed by hand, and runs the runner got wrong (all re-run or explained; none was the
plugin's fault):

- B4, G1, G2, G3 first failed on the runner: a precondition never met, an empty field sent as
  null, a refusal by the form taken for a save, the "Save anyway" step not handled.
- D1 and E3 failed the runner's timing, not the plugin's: D1's alarm came earlier than in-process
  because the in-process entry starts with the test (its 5-min start trace); E3's runner measured
  from the last valve change instead of the first call.

Still to run on instance 1: K2–K5, E5, D2, D4, D5, D7, D8, B3, B5, B6, E1, E4, C6.

## 5. The starts criterion

Four runs side by side, 24 h to settle and 24 h compared (2026-10-09 16:27 to 2026-10-10 16:27
UTC), instances 2 to 5 with `devenv/config/starts.yaml`: the plugin's control against the
boiler's own regulation, at +8 °C and at −5 °C with a ±3 K daily swing. Results: pending.

## 6. Not run, and why

To be completed. The relay path, the entity paths, a stand-alone gateway, a Home Assistant in
°F, underfloor heating and a short-cycling boiler need other simulator configurations; they run
on instances 2 to 5 after the starts criterion.

## 7. Findings and known limits

| # | Finding | Weight | Follow-up |
|---|---|---|---|
| F1 | the simulator has no `services.yaml`: Home Assistant logs an error at start (its services work) | low, test only | to add |
| F2 | on a fresh install the plugin logs a warning "No stored control state could be read; control is not configured, so nothing is owed" — a normal state at warning level | low | to lower to info |
| F3 | VT 10.4.0's Polish translation fails Home Assistant's placeholder check (two strings) | low, VT's own | none here |
| F4 | `select.central_mode` in the notes is the option's name; the entity ID follows the central entry's name | none | none |
| F5 | VT's central configuration created after Home Assistant started — without a central boiler — keeps control waiting until a restart (by design: "changed after Home Assistant started") | low | to say in the user guide: one restart after setting VT up |
