# Test report — unreleased (provisionally 0.2.3b1)

**Status: in progress.** J4 runs in the test Home Assistant since 2026-10-08; this report is
filled in as its batches end and is complete once the starts criterion (2026-10-10) and the
scenarios needing other simulator configurations have run. Instance 1 so far (2026-10-09 13:00
UTC): 38 scenarios passed, one partial (E4), one running again (D4), one not reachable here (H2);
no fault of the plugin found. How reports are made:
`docs/test-reports/README.md`.

## 1. Version and code

| | |
|---|---|
| Version | 0.2.3b1 in the manifest (provisional, decided at K4 and K5) |
| Plugin code tested | `dev` at 9df2f06 (control from the first day, PR #22); merged since, not yet in the test Home Assistant: a log level (#34, F2) and a repair text (#35, F5) |
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
gateway's terminals (21 °C 06:00–22:00 UTC, 17 °C otherwise), the gateway with the thermostat, the
expiring setpoint, three radiator zones under VT (TPI; SmartPI in the bedroom), outdoor 3 °C.
"Safe hand-back" is the gateway receiving the lowest water temperature (20 °C), CH on, then the
setpoint released (0), in that order. Runs on 2026-10-08 and 2026-10-09; the plugin as at
9df2f06. "Reviewed" marks a run whose first result was the runner's, explained below.

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| A1 | heating follows VT's zones both ways | pass | CH off 6 s and 0 s after the last valve closed; on 6 s after a valve opened (control step 10 s) |
| A2 | VT's central mode "Stopped" | pass | zones off, no demand, CH off, the setpoint still held — no hand-back; "Auto" heats again |
| A3 | control switched off | pass | the safe hand-back; the gateway back to the wall thermostat's 42 °C; nothing more |
| B1 | the plugin reloaded | pass | the safe hand-back, then control resumed |
| B2 | the plugin's entry disabled, then enabled | pass | the safe hand-back, no loop left for 2 min; enabled: control back as left |
| B3 | Home Assistant restarted cleanly | pass | the safe hand-back at the stop; after the start the switch as left and control holding the boiler again |
| B4 | the thermostat heats again after a hand-back that followed "off" | pass | CH=0 by control, then the safe hand-back with CH=1; the wall thermostat's call reached the boiler |
| B5 | three reloads in a row | pass | 20 gateway commands per 5 min before and after: one control loop |
| B6 | Home Assistant killed (`docker kill`, decision 15) | pass (reviewed) | back in seconds; the switch as the user left it (on), control holding the boiler again at once — "a hand-back is pending until control resumes"; the other branch (wish off) is K1 |
| C1 | stale data (the flow signal) | pass | nothing written for 4 min; then the safe hand-back, "handed back", alarm "boiler data lost" |
| C2 | the outdoor sensor failed | pass | the weather instead (`outdoor_weather`), the setpoint held |
| C3 | the gateway's whole link lost | pass | "handed back", reason `boiler_link_stale`; the hand-back sent again and again; alarm "hand-back failed" |
| C4 | a hand-back while the gateway is away | pass | alarm at once, still on after 3 min; taken within 70 s of the gateway's return; alarm cleared; nothing more |
| C5 | a gateway reset | pass | the command sent again 14 s after the reset (before the 30-s keep-alive); no hand-back, no alarm |
| C6 | no outdoor reading at all for 3 h | pass | `outdoor_held` at first; after 3 h `outdoor_unknown` and the fallback setpoint (51.1 °C, ramping), CH on — never zero heat |
| D1 | commands dropped at the gateway from the start | pass | alarm "boiler does not take the command" after three counted sends (2 min each); never another controller; no hand-back; not sent again |
| D2 | the boiler ignores what the gateway sends | pass | no alarm (the gateway echoes what it sends — the real path's limit); no hand-back; the boiler on its own curve (42 °C) |
| D3 | another controller (setpoint forced to 62 °C) | pass | rewritten once; then the safe hand-back, latched `outside_change`; no fight |
| D5 | overrides dropped | pass | the first two sent again within 12 s; the third within the hour: the safe hand-back, latched `outside_change`; no fight for 10 min |
| D6 | a flat setpoint clipped at the gateway | pass | judged another controller: the safe hand-back, latched `outside_change` |
| D7 | ID 1 refused by the boiler | pass (reviewed) | the sends judged ignored (alarm), never another controller, no hand-back, not sent again; the gateway's acknowledgement lasts less than one simulator step and never shows in the read-back's state |
| D8 | a hot-water draw under control | pass | the SmartPI zone (valve open) paused during the draw and resumed after; no outside change, no latch; the DHW-enable bit never written |
| E1 | hard maximum in hard frost (−25 °C, maximum 48 °C) | pass | highest setpoint 48.0 °C; reason `limit_hard_max` |
| E2 | a zone outside the central mode under "Stopped" | pass | the living room kept asking; the plugin heated for it; no hand-back |
| E3 | VT's activation delay of 120 s | pass | on a long call, heating on 125 and 130 s after the first valve opened; stops not delayed |
| E5 | "Stopped" and a room at 4 °C behind the valve VT keeps closed | pass | no heat against closed valves ("idle", CH off), no hand-back; repair issue `frost_zone_closed` |
| F1 | the boiler's low-pressure fault | pass | nothing for 4 min; then CH=0, no hand-back, no latch, state `boiler_fault`, repair issue; CH back once cleared |
| F2 | the boiler's lockout | pass | as F1 |
| G1 | no confirmed-setpoint source | pass | refused by the options form (`confirmed_entity_missing`) |
| G2 | monitor mode | pass | refused by the options form (`topology_no_control`) |
| G3 | an on/off contact, or "I don't know", on the thermostat terminals | pass | the form warns "This change stops control" and saves only with "Save anyway"; then the switch refused (`blocked_thermostat_on_off`; for "I don't know" control waits), nothing written, the thermostat heating |
| H1 | every VT zone unavailable | pass | the command held 10 min (`zones_recognition`); then alarm "no zone known", repair issue, the safe hand-back to the thermostat; control back when the zones returned |
| M1 | the plugin's own monitor fails (fault injector) | pass | control went on 4 min; then the safe hand-back, a blocker (`monitor_failed`), not a latch; repair issue; nothing written while failing; back by itself a minute after it worked again |
| K1 | stores of a crashed run, the wish off (fault injector) | pass | the safe hand-back first; the switch off; nothing more |
| K2 | an entry store of another version, no control store | pass | the safe hand-back first; the switch off |
| K3 | a stored latch with a hand-back owed | pass | the safe hand-back first; switched on: nothing written, latched `outside_change`; off and on cleared it |
| K4 | the control store gone while the entry store says one was kept | pass | the safe hand-back first; the switch off |
| K5 | a gateway entry without the terminals answer (as before 0.2.2) | pass | nothing written for 10 min; blocker `thermostat_kind_unknown`; repair issue, gone with the answer; the thermostat heating |
| D4 | another controller, with "return by itself" | running again | stepped aside and latched; no return within the hour; the first run met the wall thermostat's program change at 06:00, which counts as the other controller writing again and restarts the hour (as the option says) |
| E4 | the comfort correction | partial | the water rose 2.5 K above the curve (1 K per 30 min while heat flowed) and never above 3 K; it stopped when the burner went off, so the edge notice was not reached — run again with more load |

Runs reviewed by hand, and runs the runner got wrong (none was the plugin's fault):

- B4, G1, G2, G3 first failed on the runner: a precondition never met, an empty field sent as
  null, a refusal by the form taken for a save, the "Save anyway" step not handled.
- D1 and E3 failed the runner's timing: D1's alarm came earlier than in-process because the
  in-process entry starts with the test (its 5-min start trace); E3's runner measured from the last
  valve change, then from TPI pulses shorter than the delay, which never start the boiler — VT's
  rule, warned of in the option's description; on a long call it passed.
- D7 and D8 ran once with the living room still at 4 °C after E5 (frost protection, rightly), and
  D8 again with the SmartPI zone's valve closed (nothing to pause, rightly); the runner now restores
  the rooms and makes the zone call.
- D4 first ran without its option: the form confirms "the return by itself" on a step of its own
  ("both will control the boiler in turns") and the runner had not ticked it.
- Zones in VT's safety mode: VT takes a sensor whose state has not been written for 60 min for
  dead, and the simulator's steady rooms and outdoor temperature keep one value longer; zones were
  in safety at times from 18:34 to 19:43 and 20:42 to 22:31 on 2026-10-08. The scenarios run then
  that depend on the zones (E2, E3, D1, D7, D8, B5) ran again after every zone's safety delay was
  raised to 1440 min (`devenv/README.md`, section 4). The plugin showed a zone in VT's safety mode
  as a zone of unknown state, with its alarm.

Not reachable here: H2, a zone in "auto" or of the over_climate type — VT's over_switch zones offer
only heat and off; covered in-process.

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
| F1 | the simulator had no `services.yaml`: Home Assistant logged an error at start (its services worked) | low, test only | fixed (#32) |
| F2 | on a fresh install the plugin logged a warning "No stored control state could be read; control is not configured, so nothing is owed" — a normal state at warning level | low | fixed (#34): information |
| F3 | VT 10.4.0's Polish translation fails Home Assistant's placeholder check (two strings) | low, VT's own | none here |
| F4 | `select.central_mode` in the notes is the option's name; the entity ID follows the central entry's name | none | none |
| F5 | VT's central configuration created after Home Assistant started — without a central boiler — keeps control waiting until a restart (by design) | low | the user guide says so (#35) |
| F6 | VT switches a zone to its safety mode when its sensor's state is not written for 60 min; a steady room or outdoor temperature can stay one value that long — in the simulator, and so in a real home with a sensor that reports only changes | medium, setup | the test zones' safety delay raised; worth a line in the user guide (VT's safety delay against steady sensors) — to decide |
| L1 | VT's activation delay checks the demand again at its end: a TPI pulse shorter than the delay never starts the boiler | by design | said in the option's description |
| L2 | "return by itself" counts its quiet hour from the other controller's last write, the wall thermostat's own program changes included | by design | said in the option's confirmation |
| L3 | behind an OpenTherm Gateway a boiler that ignores the setpoint is not seen: the gateway echoes what it sends | the real path's limit | known (PB-91) |
