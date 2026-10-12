# Test report — unreleased (provisionally 0.2.3b1)

A plain-language version of this report: [`2026-10-11-test-report.md`](2026-10-11-test-report.md).

**Status: J4 on `dev` ended on 2026-10-11 in the morning.** The next run is on `qas`, after the
fixes from this report's review (the user's rule: from now on J4 tests what is on `qas`). Over
2026-10-08 to 2026-10-11, eight test Home Assistants ran some 120 scenario runs on three code
states (section 1). Plugin faults found: one (F7, fixed in #51 and confirmed). Open for the review:
the starts criterion at −5 °C (F9) and the comfort correction's starts cost (F8), and the long-burn
rule's trigger (F10). How reports are made: `docs/test-reports/README.md`.

## 1. Version and code

| | |
|---|---|
| Version | 0.2.3b1 in the manifest (provisional, decided at K4 and K5) |
| Plugin code tested | (a) `dev` at 9df2f06 — instance 1's first run, 2026-10-08/09; (b) `dev` through I6 (737b2db … b832a0e) — instances 6 to 8 and instance 1's second run, 2026-10-09/10; (c) `dev` through G11 (4378e02, with #51's F7 fix) — instances 1, 2–5, 7 and 8 from 2026-10-10 16:45 UTC; instance 6 runs `dev` through I7 (663983d) for the user to look at live, untested. `dev` has moved on since (I8, up to 1d6d724): not tested here |
| Test tools | branch `claude/j4-results`: the runner (`devenv/j4/run.py`, `paths.py`, `restart.py`, `corrections.py`), the simulator's services for the relay, the write types, the boiler and its lockout, and the configurations in `devenv/config/`. On 2026-10-12, after this run, the runner was brought to `dev` (#93) and its saving of the options adapted to I8's menu (`devenv/j4/walk.py`, `options.py`): each change goes through the item that asks it now — the read-backs among the boiler signals, the gateway's questions in the boiler interface, the hard maximum as the circuit's (E1), monitoring only as the control mode (G2), the underfloor zones in the circuit (U1, U2). Checked in-process against the real options flow over its REST API (`tests/integration/test_j4_walk.py`); not yet run in a test Home Assistant |
| J4 started | 2026-10-08, by the user |

## 2. Environment

| | |
|---|---|
| Home Assistant | 2026.9.3 (the test Home Assistants and CI); 2026.9.0 in CI, the oldest supported |
| Versatile Thermostat | 10.4.0 |
| SmartPI | 0.4.0 |
| `vtherm_api` | 0.5.0, as Home Assistant installed it in the test Home Assistant |
| Python | 3.14 |
| Test Home Assistant | the dedicated test LXC (Debian 13, Docker, the firewall on the Proxmox host blocking the home network: T-25 passed), eight instances: 1 the gateway with an OpenTherm wall thermostat; 2–5 the starts criterion; 6 the relay; 7 the entity path (a held device); 8 a stand-alone gateway |

## 3. Automated tests

| Suite | Result |
|---|---|
| Core, without Home Assistant (`tests/core`) | 1473 passed (`dev` through G11) |
| The others, with Home Assistant | 2956 passed, 4 expected failures (`dev` through G11) |
| `ruff check`, `ruff format --check`, `mypy` (strict) | clean |
| CI (both Home Assistant versions, hassfest, HACS) | green on every pull request merged into `dev` |

The four expected failures are strict ones that wait for decisions at K4: J4's starts criterion
with the daily outdoor swing (×1.20 at +8 °C and ×2.16 at −5 °C against the boiler's own
regulation, rooms as warm; `tests/sim/test_control_loop.py`) and its band test.

## 4. J4 in the test Home Assistants

"Safe hand-back" is the gateway receiving the lowest water temperature (20 °C), CH on, then the
setpoint released (0), in that order. "Reviewed" marks a run whose first result was the runner's,
explained under each table. Every scenario's evidence is in `research/<date>-j4-*-results.md`
(git-ignored).

### 4.1 Instance 1, first run (code a)

The condensing boiler `condensing_small`, an OpenTherm wall thermostat on the gateway's terminals
(21 °C 06:00–22:00 UTC, 17 °C otherwise), the gateway with the thermostat, the expiring setpoint,
three radiator zones under VT (TPI; SmartPI in the bedroom), outdoor 3 °C.

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
| D4 | another controller, with "return by itself" | pass | stepped aside and latched; no return under an hour of quiet; back once quiet for an hour (the first run met the wall thermostat's 06:00 program change, which rightly restarted the hour) |
| E4 | the comfort correction | partial | the water rose 2.5 K above the curve (1 K per 30 min while heat flowed) and never above 3 K; the edge notice needs 3 h at the limit, longer than the run — the warning at the limit is shown by Q1 and Q5 (section 4.5) |

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

### 4.2 Instance 1, second run (codes b and c)

The entry made by code (a) upgraded in place: its options moved from minor version 5 to 6 at the
first start with no warning or error, and every control scenario of the first run was run again.

| ID | Result | Notes |
|---|---|---|
| G1, G2, G3 | pass | the setup's and options' first steps as I6 changed them |
| F1, F2 | pass (reviewed) | the first try had the rooms at their targets, so heating was not on when the fault came; with the rooms calling: nothing for 4 min, then CH=0, `boiler_fault`, the issue, back when cleared |
| D8 | pass | the SmartPI pause and resume during a draw |
| C1, C2, C3, C4 | pass | as in the first run |
| C5 | pass (reviewed) | the gateway's reset handled (sent again 0.7 s after it); its "no alarm" check met L4 |
| K1, K2, K3, K4, K5 | pass | as in the first run |
| E6 | pass | the short-cycling boiler at +10 °C: 11 starts in the hour; heating never switched off while a valve was open (119 switchings checked) |
| B1, B2, B3, B4, B5 | pass | as in the first run |
| B6 | pass (reviewed) | the switch back as left, control resumed; the runner first expected "off" (fixed, SCOPE.md §7) |
| D1, D2, D3, D5, D6, D7 | pass | as in the first run |
| D4 | pass | stepped aside after 150 s; no return under an hour of quiet; a new session controlled again |
| E1, E2, E3, E5 | pass | as in the first run |
| H1, M1 | pass | as in the first run |
| W1 | pass | the wall thermostat's own program in real time: shown on the switch (17 °C at night); handed back, not calling at night with its room at 19 °C; at 06:00 its program raised the room to 21 °C and it called at once, the boiler heating; the plugin wrote nothing after its hand-back |
| C6 | pass | the last outdoor value held, then after 3 h the fallback setpoint (51.1 °C), CH on |
| E4 | partial | as in the first run (2.4 K in 3 h) |

### 4.3 Instance 6 — the relay path (code b)

An on/off boiler whose thermostat terminals the simulator's relay closes; the relay declared as
reporting its state, "off" after a power cut, no timer, rest state "off". The relay's own settings
are changed in place by the simulator's `relay_setup` for R9 to R16.

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| R1 | the relay follows VT's zones both ways | pass | on with the rooms calling, off once satisfied, on again |
| R2 | the relay restarts, seen unavailable | pass (reviewed) | "on" again 20 s after; no alarm |
| R3 | the relay restarts unseen | pass (reviewed) | "on" again 10 s after |
| R4 | an automation switches the relay while available | pass (reviewed) | written back once; the second time stepped aside 20 s after, the rest state written once, the relay left alone after |
| R5 | the relay loses its Wi-Fi for 8 min | pass | nothing written meanwhile; the alarm and issue after 5 min; the command again on return |
| R6 | a start after the first valve opened | pass | the relay on 125 s after the first valve opened |
| R7 | Home Assistant stopped and started | pass | off at the stop, on again |
| R8 | without the separate-contact tick | pass | "this change stops control", then the switch refused; nothing to the relay |
| R9 | a declared 10-min timer that an "on" restarts | pass (reviewed) | renewed 6 times in 30 min, never lapsed, no alarm, nothing to ask |
| R10 | a declared 11-min timer that runs from the first "on" | pass (reviewed) | each lapse answered at once, never counted, no alarm |
| R11 | the timer "I don't know", the relay's own restarted by "on" | pass | kept on by the repeats (at most 5 min apart); "off" once, not repeated |
| R12 | the state after a power cut (4 cases) | pass | off while commanded on: "on" again; on while commanded off: "off" again; "last": nothing |
| R13 | an optimistic relay entity | pass (reviewed) | "controlled without confirmation", relay check "unverified"; an unseen restart undone by the blind repeat (230 s); "off" repeated too |
| R14 | a 20-min restart lockout against the 30-min proof of heat | pass | the burner fired 19 min after the relay; no "boiler not responding" |
| R15 | an "inching" relay off 2 min after each "on" | pass (reviewed) | three switch-offs answered, the fourth stepped aside 8.8 min into control; the latch issue names "about 2 min"; left alone after |
| R16 | an undeclared 11-min timer | pass | recognised at its second lapse: a warning asks to declare it (11 min); heating goes on |
| R17 | every zone unknown, the own-room-controller tick | pass | rest "on": handed back, relay on, `no_zone_known_handed_back`; rest "off": idle, relay off, `no_zone_known_off` |
| R18 | VT's activation delay of 120 s on the relay path | pass (reviewed) | each start waited 125 and 130 s |

Reviewed: the runner first sent its events inside the relay rule's 120-s confirmation window
(R2–R4; the in-process tests wait 130 s); measured from a VT cycle that began before the call
(R9, R13); used a 10-min timer, which lapses together with the 5-min renewal and so is hidden
from Home Assistant (R10, PB-25); waited for an inching relay to stay on (R15); and measured a start
from a valve opening while a wait from an earlier pulse ran on (R18). Each passed once fixed.

### 4.4 Instance 7 — the entity path, a held device (codes b and c)

`number.boiler_sim_flow_setpoint` and `switch.boiler_sim_ch_enable`, both held; the read-back
the boiler's own control setpoint; the hand-back value 0 "own control".

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| N1 | control and the safe hand-back | pass | |
| N2 | the device restarting during a hand-back | code b: FAIL (F7); code c: pass | code b: only the heating switch written once back — the setpoint judged "held by another controller" before the plugin ever wrote it (twice); code c: [20, CH on, 0] written once back, the alarm cleared after the retry checks (`taken_by_other`) |
| N3 | a setpoint the boiler stores, or might | pass | refused where it is entered (`write_type_not_supported`) |
| N4 | without a heating switch | pass | "this change stops control", then the switch refused |
| N5 | every zone unknown, with and without the own-room tick | pass | with: handed back to the boiler's own controller; without: idle, no hand-back |
| N6 | the setpoint entity alone away during a hand-back | pass | nothing written meanwhile; [20, 0] once back; the alarm cleared after the retry checks (`taken_by_other`: the K4 question of an own-control value read back from the boiler) |
| N7 | a switch enabling external control as the hand-back | pass | on with control, off at the hand-back, on again |
| N8 | a timeout hand-back on an expiring setpoint | pass | the lowest once, then the device's timeout releases it; a device that keeps the value: the alarm 245 s after the hand-back (its timeout + 3 min), nothing written again |
| U1 | underfloor, the circuit's maximum 40 °C, −5 °C | pass | every setpoint ≤ 40.0, `limit_circuit_max` shown; the flow ≤ 40.0; the too-hot alarm (45 °C) off, judged |
| U2 | underfloor and a radiator on one loop, +5 °C | pass | setpoints ≤ 38.0, nothing held back; the alarm off |
| L1 | 12 h at +12 °C | pass (reviewed) | the rooms within 1.5 K; no alarm or latch; heating following VT (the runner's sampling fixed) |

NEW-N2: the run after #51 checked the alarm 50 s after the device's return, before the two retry
checks a minute apart that judge a held device's own-control read-back; the runner now waits for
them, and N2 passed on 2026-10-11 at 07:26 UTC. The runs of N2 and N6 on 2026-10-10 at
16:46 were on a wrong configuration and are void: N8 had left the instance on the timeout
hand-back (its restore refused while a hand-back was owed, unnoticed by the runner) — not a
regression of #51, as first reported; the runner now refuses to run a scenario on an instance not
in its base state, and a refused restore stops it loudly.

### 4.5 Instance 8 — a stand-alone gateway (codes b and c), and the corrections of 2026-10-10

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| S1 | a stand-alone gateway's hand-back | pass | the switch says "heating stops"; heating stops at once |
| S2 | every zone unknown, stand-alone | pass | idle, CH off, no hand-back |
| L1 | 12 h at −2 °C | pass (reviewed) | setpoint kept alive (longest gap 30 s), 94 toggles following VT, no alarm or latch, hot water untouched; the rooms 1.1–1.7 K under their setpoints — F11 |
| T1 | Home Assistant in US customary units | pass | the signals in °F (flow 98.4 °F), the boiler given °C (43.7–44.2 °C), no alarm, the safe hand-back; VT's limits set in °F for the test, all put back after |
| Q2 | a curve too low, the correction off (G11 E) | FAIL (scenario) | the flame never burnt 3 h without a break (2.2 h at most): the long-burn rule rightly did not run — F10 |
| Q5 | one room short while the others hold (G11 B) | pass | the correction rose for it (61 min); at its 3 K limit the warning `room_short_at_limit` naming `climate.zone_living` |

On instance 1 (code c): Q1 pass — a curve too low with the correction on and the bedroom's SmartPI
reset to its learning phase, the rooms 0.2 K under their setpoints: the correction started (55
min) and at its limit the warning `curve_too_low` named the three zones; Q3 pass — the curve's room
in Auto followed the warmest room (22 → 23 °C), capped at 23 °C, unmoved by a cooler room, the
excluded bath ignored (21 °C); Q4 pass — a 1.5-K drop in one room: "window probably open" 10 s
after, no correction for 30 min.

## 5. The starts criterion

Four runs side by side (instances 2 to 5, `devenv/config/starts.yaml`): the plugin's control
against the boiler's own regulation, at +8 °C and at −5 °C with a ±3 K daily swing, every zone on
TPI, the plugin's curve set to the boiler's own. Criterion: control starts the burner at most
1.10 times as often, the rooms at most 0.3 K cooler.

First run — code (a), the correction off, a full day (2026-10-09 16:27 → 2026-10-10 16:27 UTC):

| | +8 °C control | +8 °C own | −5 °C control | −5 °C own |
|---|---|---|---|---|
| burner starts | 149 | 145 | 55 | 32 |
| starts per hour | 6.2 | 6.0 | 2.3 | 1.3 |
| heating switchings | 368 | 356 | 110 | 66 |
| mean setpoint | 37.6 | 37.0 | 50.6 | 50.0 |
| rooms (living / bedroom / bath) | 19.41 / 18.59 / 20.61 | 19.37 / 18.55 / 20.58 | 19.44 / 18.53 / 20.77 | 19.43 / 18.53 / 20.78 |

×1.03 at +8 °C — pass; ×1.72 at −5 °C — FAIL; the rooms as warm in both. In-process: ×1.20 and
×2.16. Control held the boiler throughout. The same water within 0.6 K: control switches heating
on and off more often (heating follows VT's zones at once), and at −5 °C VT's TPI cycles leave short
moments with no zone calling. Over the night hours alone (23:00–07:00) the same run gives ×0.96
and ×0.93.

Second run — code (c), the comfort correction on, the night only (2026-10-10 23:00 → 2026-10-11
07:00 UTC, shortened at the user's request; 6 h to settle):

| night | +8 °C control | +8 °C own | −5 °C control | −5 °C own |
|---|---|---|---|---|
| burner starts | 86 | 66 | 53 | 12 |
| mean setpoint / flow | 41.2 / 37.7 | 39.2 / 37.2 | 55.5 / 51.7 | 52.2 / 51.4 |
| flame on | 44 % | 53 % | 67 % | 92 % |
| rooms (living / bedroom / bath) | 19.40 / 18.54 / 20.67 | 19.40 / 18.53 / 20.66 | 19.49 / 18.59 / 20.86 | 19.45 / 18.55 / 20.79 |

×1.30 at +8 °C and ×4.42 at −5 °C — FAIL; comfort gained 0.00–0.07 K. At −5 °C the correction sat at
its 3 K limit with `curve_too_low` raised — F8.

## 6. Not run, and why

- H2, a zone in "auto" or of the over_climate type: VT's over_switch zones offer only heat and off;
  covered in-process.
- The firmware MQTT path: the `opentherm_gw` stub route works; MQTT needs a broker in the LXC.
- The connection types of I6 beyond the generic paths (ESPHome, EMS-ESP, the boiler's Wi-Fi module):
  the simulator offers the generic entity path only.
- Underfloor heating over six hours: 100 min each (U1, U2), enough for the cap and the alarm.
- Home Assistant in °F on the entity path: on the gateway path only (T1).
- The long-burn rule's classes (G11 E): not reached (Q2, F10).
- `dev` after G11 (I7, I8): not tested; the next run is on `qas`.

## 7. Findings and known limits

Status on the morning of 2026-10-11: N2 passed again (code c); N8 running again on instance 7 to check its restore after an owed hand-back.

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
| F7 | a held device restarting during a hand-back never got the setpoint's hand-back value: a third value on the read-back after the outage was judged another controller's before the plugin wrote it, and the "hand-back failed" alarm cleared | high, entity path | fixed (#51, #58); J4 N2 passes: [20, CH on, 0] written once back |
| F8 | the comfort correction on: at night ×1.30 (+8 °C) and ×4.42 (−5 °C) the boiler's own starts, for 0.00–0.07 K of comfort — the rooms stay about 1 K short through VT's TPI offset, which the correction cannot remove, and the water at the limit makes every TPI cycle stop the burner | medium | G11 made it on by default in full control: to decide at K4 (the simulation in the tests says ×1.39 and ×6.28) |
| F9 | the starts criterion fails at −5 °C over a full day with the correction off (×1.72; ×0.93 at night) | medium | K4: heating follows VT at once by the user's rule |
| F10 | the long-burn rule runs only after 3 h of flame without a break; a boiler cycling at its minimum while the rooms stay short never triggers it, so with the correction off nothing tells the user (Q2) | medium | to decide: count the burner's share of the time, not one unbroken burn |
| F11 | 12 h at −2 °C with the default curve and the correction off left the rooms 1.1–1.7 K short, the flame on 100 % and the flow at its setpoint — the boiler had reserve, the water was too cool (the case behind G11) | none now | G11 B, D and E address it |
| L4 | the simulator's outdoor sensor, set by hand, stays flat for over 12 h while its weather moves: the plugin rightly judges it stuck and uses the weather | test bed | none |
| L5 | VT's TPI zones (coefficients 0.6 / 0.01) hold the simulated rooms about 1–1.5 K under their setpoints in every regime, with and without the plugin | test bed, VT | none here; it is what F8 meets |
| L6 | a relay timer that is a whole multiple of the plugin's 5-min renewal lapses together with a renewal, hidden from Home Assistant (PB-25) | by design | the runner uses 11 min |

The runner's own faults found and fixed during J4, none the plugin's: timings inside the relay
rule's confirmation window; preconditions not met (rooms at target before a fault, a VT cycle that
began before the call); 10-s samples behind the plugin's changes (L1); a restore refused while a
hand-back was owed and not noticed (N8 → the void N2/N6 runs); options saved without the fields the
runner did not set (G11's new defaults). Since 2026-10-10 the runner refuses to run a scenario on
an instance not in its base state, stops on a refused restore, and attaches the plugin's warnings,
the control state, the alarms and the issues to every failure.

