[Polska wersja](../../../pl/testing/reports/unreleased.md)

# Test report — unreleased (provisionally 0.2.3b1)

Status: current.

Plain-language versions of this report: [`2026-10-11-test-report.md`](2026-10-11-test-report.md)
(J4 on `dev`, 2026-10-08 to 2026-10-11) and [`2026-10-14-test-report.md`](2026-10-14-test-report.md)
(J4 on `qas` c488e90, 2026-10-14) and [`2026-11-22-test-report.md`](2026-11-22-test-report.md)
(J4 on `qas` b96016c and the Boiler page on `dev` 98d135e, 2026-11-18 to 2026-11-21), and
[`2026-11-22-i11-test-report.md`](2026-11-22-i11-test-report.md) (`qas` fcae678, 2026-11-22), and
[`2026-11-24-test-report.md`](2026-11-24-test-report.md) (`qas` 7b34657 and 76559e7, 2026-11-22 to
2026-11-24).

**Status: `qas` 7b34657 (code h) and `qas` 76559e7 (code i) were checked from 2026-11-22 to
2026-11-24 (section 4.10), narrowed by the user to what changed.**
- Code h, the recalibrated house and the page's display fixes: every scenario passed — R9, N1, S1,
  Q1, Q2, Q3, P2, E4, D8, L1 and Q5. Q5 passed for the first time: on the light bedroom SmartPI
  learned in 7 h 41 min (L15, L16 closed).
- The page by hand: the reasons in the user's language, the times by the profile's zone, the days
  and hours in Home Assistant's, a reason beside "—". In a narrow column the schematic is not cut,
  but its labels overlap (F21).
- The starts criterion on the new house, VT's 15-min cycle, is met. At +8 °C the plugin started
  the burner ×1.01 as often as the boiler's own regulation. At −5 °C it was ×1.42, but with 2.25
  starts an hour and a median burn of 11.8 min, which meets the absolute rule. The rooms were
  0.02–0.09 K warmer under control. It was judged over 2026-11-23 09:00 → 11-24 09:00 UTC, 12 h
  after the runs began (the user's decision; section 5).
- Code i, #207 and #208: no regression — no `write_through_cloud` on any role, the control
  settings save, F1, R9, N1, S1 and P2 pass. Neither change can be shown on the bench (L17, L18).
- One plugin fault: F21, on the page's display (low).

**Earlier status: `qas` fcae678 was checked on 2026-11-22 (code g, section 4.9), narrowed by the
user to what changed since codes e and f.**
- 25 scenario runs and the checks by hand all passed.
- F15, F16, F17 and F18 and L12 are fixed and shown fixed; L14's runner fixes work.
- I11 works: control is switched only in the settings or by an automation, it comes back from the
  store after a restart, and an update in place removes the old switch.
- No new plugin fault.
- Q5 was not run, because SmartPI never leaves its bootstrap on the simulator (L15).
- The simulator's house is heavy and well insulated (L16).

**Earlier status: J4 on `qas` b96016c ran from 2026-11-18 to 2026-11-21 (code e, section 4.7), and
the Boiler page's check I10.10 on `dev` 98d135e on 2026-11-20/21 (code f, section 4.8).**

- **Code e.** 79 scenario runs on instances 1, 6, 7 and 8; 70 passed. Not counted: the six runs made before a setup mapping was corrected, and Q1's second run on instance 2.
  - Q1 failed once. It passed when run again with the comfort correction sampled every minute. The first failure was not reproduced and its cause stays open (L13).
  - One plugin fault: F15. The long-burn rule misses water above its setpoint while the flame burns without a break (Q2).
  - The other failures came from the runner or the scenario's own precondition (V1 twice, R2, R3, Q5), or are known limits (E4; L1 = F11).
  - The starts criterion is met with a 15-min VT cycle, at +8 °C (×1.00) and at −5 °C (×1.23, under 6 starts an hour with a median burn of 11.8 min), the rooms as warm. With VT's default 5-min cycle it is not met (×1.13, ×1.88), as expected (section 5).
- **Code f.** The page and the cards worked on every path tried (A–H). Three plugin faults:
  - F16: the page's curve save drops a stored exponent;
  - F17: a reload throws the user off the open page;
  - F18: the journal misses the hand-back at a reload or restart under control, and the takeover after it.

  One decision for the user: F19, any Home Assistant user can switch control on (decided on
  2026-11-22, section 7).

`dev` d84242f (#178), merged after the check, is not tested here. This update is in English only
for now (the user's decision of 2026-11-21); the Polish twin follows.

**Earlier status: J4 on `qas` c488e90 ran on 2026-10-14** (section 4.6): the fixes since G11 on VT 10.5.1 —
B1, D1, D8, E3, H1, V1, the "Control mode" save (G2), G1, G3, an upgrade under control (P1), the
relay (R1, R7, R17), the entity path (N1, N2) and a circuit run by other automation (E7). Every
scenario passed; four first failed on the runner and were reviewed (E3, V1, R1, E7). Plugin
faults found for this run: two — F12 by reading before it (the "Control mode" save on an entry
made before the connection question; fixed in #127 and confirmed by G2), and F14 by E7 (after a
ramp the setpoint stopped 0.5 K below its target; fixed in #135). The run on `dev` (2026-10-08 to
2026-10-11, some 120 scenario runs on three code states) found one (F7, fixed in #51 and
confirmed). The review's questions (F8, F9, F10) were decided at K4 on 2026-11-17 (#149–#152);
the code since `qas` c488e90 is not tested here yet. How reports are made:
`docs/en/testing/reports/README.md`.

## 1. Version and code

| | |
|---|---|
| Version | 0.2.3b1 in the manifest (provisional, decided at K4 and K5) |
| Plugin code tested | (a) `dev` at 9df2f06 — instance 1's first run, 2026-10-08/09; (b) `dev` through I6 (737b2db … b832a0e) — instances 6 to 8 and instance 1's second run, 2026-10-09/10; (c) `dev` through G11 (4378e02, with #51's F7 fix) — instances 1, 2–5, 7 and 8 from 2026-10-10 16:45 UTC; instance 6 runs `dev` through I7 (663983d) for the user to look at live, untested; (d) `qas` at c488e90 (#133, the same files as `dev` a614299: I8, I9, the mutation tests' fixes #110–#120, VT 10.5.1, #127–#132) — instances 1, 2–4, 6 and 7 on 2026-10-14 (section 4.6), deployed from a detached checkout of that commit; (e) `qas` at b96016c (#162: K4 from the research, Home Assistant 2026.10.4, ready for 2026.11 and VT 10.6, and the J4 tools of #158–#161) — all eight instances, 2026-11-18 to 2026-11-21 (section 4.7), deployed from a detached checkout of that commit by the test bench's own deploy tool; (f) `dev` at 98d135e (#163–#177, step I10: the Boiler page and its cards) — instances 3, 4 and 5, 2026-11-20/21 (section 4.8); (g) `qas` at fcae678 (#199: #178–#198 — I10's fixes, I11, the pre-J4 fixes) — all eight instances, 2026-11-22 (section 4.9), instances 2, 3 and 5 updated in place; (h) `qas` at 7b34657 (#206: #200–#205 — the recalibrated house and the light bedroom, the comfort correction's text, F6, F20 and P2) — all eight instances, 2026-11-22 to 2026-11-24 (section 4.10); (i) `qas` at 76559e7 (#210: #207–#209 — the OTGW firmware's entities without a device, control blocked through an integration that declares a cloud, docs) — instances 5, 6 and 8, 2026-11-23, from a checkout of its own |
| Test tools | branch `claude/j4-results`: the runner (`devenv/j4/run.py`, `paths.py`, `restart.py`, `corrections.py`), the simulator's services for the relay, the write types, the boiler and its lockout, and the configurations in `devenv/config/`. On 2026-10-12, after this run, the runner was brought to `dev` (#93) and its saving of the options adapted to I8's menu (`devenv/j4/walk.py`, `options.py`): each change goes through the item that asks it now — the read-backs among the boiler signals, the gateway's questions in the boiler interface, the hard maximum as the circuit's (E1), monitoring only as the control mode (G2), the underfloor zones in the circuit (U1, U2). Checked in-process against the real options flow over its REST API (`tests/integration/test_j4_walk.py`); first run in a test Home Assistant on 2026-10-14 (code d): every save and restore went through — E3, G1, G2, G3, R17 and the base of instances 2–4. Codes e and f: the runner of the tested commit, run from the test bench, which also set up each installation through the API (the test pack has no setup script yet), computed the starts criterion from the recorders, and drove the Boiler page in headless Chromium (Playwright 1.64.1) logged in with the instance's token |
| J4 started | 2026-10-08, by the user; code e: 2026-11-18, code f: 2026-11-20, code g: 2026-11-22, code h: 2026-11-22, code i: 2026-11-23, by the user |

## 2. Environment

| | |
|---|---|
| Home Assistant | 2026.9.3 (the test Home Assistants and CI); 2026.9.0 in CI, the oldest supported; 2026.11.2 in the test Home Assistants for codes e to i (2026.10.4 the oldest supported since #155) |
| Versatile Thermostat | 10.4.0 (codes a to c); 10.5.1 (code d, 2026-10-14); 10.6.5 (codes e to i) |
| SmartPI | 0.4.0 (codes a to d); 0.6.7, the author's release (codes e to i) |
| `vtherm_api` | 0.5.0, as Home Assistant installed it in the test Home Assistant; still 0.5.0 under VT 10.5.1 on 2026-10-14 (VT asks `>=0.5.0`, which the installed version meets); 0.6.0 only in CI's early warning; 0.9.0 for codes e to i (VT 10.6.5 asks for it) |
| Python | 3.14 |
| Test Home Assistant | the dedicated test LXC (Debian 13, Docker, the firewall on the Proxmox host blocking the home network: T-25 passed), eight instances: 1 the gateway with an OpenTherm wall thermostat; 2–5 the starts criterion; 6 the relay; 7 the entity path (a held device); 8 a stand-alone gateway. On 2026-10-14 instances 2–4 were set as instance 1 (`configuration`, the base walked; the starts criterion's house is to be set again for its next run); the LXC had run since 2026-10-08 14:34 UTC, and a partial check passed: the home router out of reach from the LXC and from a Home Assistant container, a public address in reach. Codes e and f: each instance cleared first (its earlier state kept on it) — except instance 4 for code f, updated in place with its history — set up afresh through the API, and restarted once — control waits for a restart after VT's central configuration is made (F5). Roles moved during the run: 1 the gateway, then the starts criterion (5-min cycle); 2–5 the starts criterion (15-min cycle), then 2 the gateway for Q1's second run; 6 the relay, then the gateway, then the starts criterion (5 min); 7 the entity path, then the gateway, then the starts criterion (5 min); 8 a stand-alone gateway, then the gateway, then the starts criterion (5 min). For I10.10: 3 a fresh full gateway, 4 a gateway updated in place with two days of history, 5 the relay. Code h: 2, 3, 4 and 7 the starts criterion (15-min cycle); 1 the gateway for Q5 alone; 5 the relay, then the gateway; 6 the entity path, then the gateway; 8 a stand-alone gateway, then the gateway. Code i: 6 the gateway, 5 the relay, 8 the entity path, then a stand-alone gateway |

## 3. Automated tests

| Suite | Result |
|---|---|
| Core, without Home Assistant (`tests/core`) | 1473 passed (`dev` through G11); 2036 passed (`qas` c488e90, CI, both Home Assistant versions) |
| The others, with Home Assistant | 2956 passed, 4 expected failures (`dev` through G11); 3116 passed, 4 expected failures (`qas` c488e90, CI, both versions) |
| `ruff check`, `ruff format --check`, `mypy` (strict) | clean (on c488e90 in CI too) |
| CI (both Home Assistant versions, hassfest, HACS) | green on every pull request merged into `dev`; PR #133 and the push to `qas` c488e90 green, the early warnings (the newest VT and SmartPI; the newest `vtherm_api`) included |

The four expected failures are strict ones that wait for decisions at K4: J4's starts criterion
with the daily outdoor swing (×1.20 at +8 °C and ×2.16 at −5 °C against the boiler's own
regulation, rooms as warm; `tests/sim/test_control_loop.py`) and its band test.

Codes e and f: not run again by the test session. CI on `qas` b96016c: every job of both CI groups passed
(`ha` and `ha-minimum`, both pinned to Home Assistant 2026.10.4 at that commit; 2026.11.2 ran only
in the test Home Assistants), with hassfest and HACS (the early warnings skipped). No CI run is
recorded on the merge commit `dev` 98d135e. Code g: CI on `qas` fcae678 passed (14 jobs, 2 early
warnings skipped); on `dev` d739d11 all 30 jobs passed. Code h: "Tests" and "Validate" passed on
`qas` 7b34657. Code i: "Tests" and "Validate" passed on `qas` 76559e7 (the early warnings ran on
`dev` a8f4181, the same content).

## 4. J4 in the test Home Assistants

"Safe hand-back" is the gateway receiving the lowest water temperature (20 °C), CH on, then the
setpoint released (0), in that order. "Reviewed" marks a run whose first result was the runner's,
explained under each table. Codes e and f: the evidence is kept on the test bench (its results and
logs), not in this repository; readings taken from the instances' recorders during the run are
recorded in its decisions log, and the instances keep their databases. Earlier codes: every scenario's evidence is in `research/<date>-j4-*-results.md`
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
  raised to 1440 min (`docs/en/testing/test-environment.md`, section 4). The plugin showed a zone in VT's safety mode
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
| B6 | pass (reviewed) | the switch back as left, control resumed; the runner first expected "off" (fixed, docs/en/specification/scope.md §7) |
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

### 4.6 `qas` c488e90 on VT 10.5.1 (code d, 2026-10-14)

The scope: the scenarios the pull requests since G11 name (#125, #126, #133), the gaps of the
scope check before the run (`research/2026-10-13-j4-scope-check.md`) and the user's choice. Six
instances side by side, one runner each, 05:45–06:45 UTC. Every entry migrated from minor version 8
to 20 at its first start on this code with no warning or error from the plugin; VT 10.5.1 and
`vtherm_api` 0.5.0 in every container. Before every scenario the runner compared the instance's
stored options with its base (none drifted). Evidence: `research/2026-10-14-j4-results-instance<N>.md`.

| ID | Scenario | Instance | Result | Evidence |
|---|---|---|---|---|
| P1 | an upgrade under control (the HACS path): control on under the old code (4378e02), then this code deployed — Home Assistant restarted | 1 | pass | at the stop the gateway's read-back 20.0, then released to the thermostat; after the start control resumed at once (override held, no hand-back owed, no blocker, latch, alarm or issue) |
| D8 | a hot-water draw under control | 1 | pass | the SmartPI zone (valve open) paused during the draw and resumed after; no outside change, no alarm; the DHW-enable bit never written |
| G2 | "monitoring only" in the "Control mode" item, on an entry made before the connection question | 1 | pass | saved (it failed before #127, F12); "this change stops control" confirmed; the switch refused (`blocked_control_mode_monitor`), nothing written; back to full control and the base |
| V1 | every VT zone shows the plugin's water data (`smart_boiler`) | 2 | pass (reviewed) | the two keys; the water 33–34 °C against a flow of 33.3 °C; no heat during the draw; the water unknown with the flow failed; known again (37 °C) |
| G1 | control refused without the CH-setpoint read-back | 2 | pass | refused where it is entered (`confirmed_entity_missing`) |
| G3 | an on/off contact, or "I don't know", on the thermostat terminals | 2 | pass | "Save anyway", then the switch refused (`blocked_thermostat_on_off`, `blocked_thermostat_kind_dont_know`), nothing written, the thermostat's call on |
| H1 | every VT zone unavailable | 3 | pass | held through recognition (`zones_recognition`), then `zones_unknown`, the alarm, the issue `no_zone_known`, the safe hand-back [20, CH on, 0]; back when the zones returned |
| B1 | the plugin reloaded | 3 | pass | [20, CH on, 0] at the reload, then control resumed |
| D1 | commands dropped at the gateway from the start | 3 | pass | no alarm for 4 min; "write ignored" by 12.7 min; never another controller; no hand-back; not sent again |
| E3 | VT's activation delay of 120 s | 4 | pass (reviewed) | starts 95 and 130 s after the call, in each of two runs; a probe with the rooms quiet before the call: 127 s |
| R1 | the relay follows VT's zones both ways | 6 | pass (second run) | on at once with the rooms calling, off 11 s after they were satisfied, on again 10 s after the call |
| R7 | a planned restart (the entry reloaded) on the relay | 6 | pass | off at the stop, then on again |
| R17 | every zone unknown on the relay, the own-room-controller tick | 6 | pass | rest "on": handed back, the relay on, `no_zone_known_handed_back`; rest "off": idle, the relay off, `no_zone_known_off`; the relay's forms walked and put back |
| N1 | a held device restarting | 7 | pass | the setpoint and the heating switch sent again once back; no outside-change or write-ignored alarm |
| E7 | a circuit run by other automation asks through its entity, no zone calling | 4 | pass (reviewed) | heating for the circuit alone (`circuit_asks`, `limit_circuit_need`), off once it stops asking; the water rose at the ramp's rate towards 55.0 °C (50 °C + 5 K) and stopped at 54.5 °C (F14); switched on while the circuit asks: 55.0 °C at once |
| N2 | the device restarting at a hand-back | 7 | pass | "hand-back failed" while away; [20, CH on, 0] once back; the alarm cleared after the retry checks (`taken_by_other`, the K4 question as before) |

Reviewed — each a fault of the runner, none of the plugin:

- **E3.** Its first start was measured from the wrong call. E3's clean-up leaves the rooms at their
  targets, so VT's TPI cycles open the valves up to the moment control is switched on; the plugin
  sees that call at its first step and starts the delay from it, and E3 waits only 30 s after
  heating is off before its own call. A call that drops and returns neither cancels nor restarts a
  pending start (`core/controller.py` `_activation`, as VT's own rule), so heating came 120 s after
  that first call — 95 s after E3's. Both runs' second cycles (130 s) and a probe on the same
  instance with the rooms quiet for 150 s before the call (127 s) show the delay held. The runner
  needs R18's pause of 150 s after the valves close before each call.
- **V1.** With the flow failed, it compared the heat shown with the flame read around its reading,
  but the plugin fills the attribute only when VT writes the climate's state
  (`add_custom_attributes`), and VT wrote none from 06:11:30 to 06:13:20: the flame went out at
  06:11:45, so the attribute still showed the "unknown" that was right at VT's last write. At every
  VT write the heat shown was right ("no" with the flame out, "unknown" with it burning). The runner
  should compare at the climate's `last_updated`.
- **R1.** Its first run waited 120 s for the relay, but VT had not opened the valves by then: the
  rooms were made colder while their setpoints already stood at their targets, which VT applies at
  its next cycle. The valves opened only when the runner set the setpoints again, 121 s after
  control was switched on, and the relay went on 7 s later. Run again: passed. The runner should
  wait for the valves first, as E3 does.
- **E7** (run afterwards, 07:16 UTC). It expected the circuit's floor, 55 °C, within 60 s, but
  control was already on (idle at 37 °C) when the circuit asked, so the rise follows the ramp,
  1 K/min (S-23: only a session's first setpoint is the target itself); the in-process test switches
  control on while the circuit asks. A probe waited for the ramp: 0.5 K every 30 s, ending at
  54.5 °C — F14. A second probe, switched on while the circuit asks: target and setpoint 55.0 °C.

### 4.7 `qas` b96016c on VT 10.6.5 and Home Assistant 2026.11.2 (code e, 2026-11-18 to 2026-11-21)

The scope was the full J4, chosen by the user. The scenarios the pull requests since c488e90 name
ran first on instance 1: E3, E5, E7, V1, D8b, G1–G3 and Q2. R1, the entity path and the
stand-alone gateway ran beside them on instances 6 to 8, and the starts criterion on 2 to 5
(section 5); the rest of the runner followed. Every entry started without a warning or an error from
the plugin. Before every scenario the runner compared the instance's stored options with its base.

The setup on instance 1 first mapped the wall thermostat's room setpoint into the interface's
"Thermostat's own water setpoint" field. That was the test session's mistake: the simulator has
no such entity, and the signal "Wired thermostat setpoint" is the right place. It was corrected,
and the scenarios run before the correction (G1–G3, E5, E3, E7) were run again.

**The gateway path**

| ID | Scenario | Instance | Result | Evidence |
|---|---|---|---|---|
| G1, G2, G3 | control refused without a confirmed setpoint; monitoring only; an on/off contact or "I don't know" on the terminals | 1 | pass | refused where entered; "Save anyway", then the switch refused, nothing written |
| E5 | "Stopped" and a room at 4 °C behind a closed valve | 1 | pass | no frost heat; the issue's advice `frost_zone_closed_central_mode` (#147) |
| E3 | VT's activation delay of 120 s | 1 | pass | starts 125 and 129 s after the call. During the wait the heat call is off with `activation_delay`, and the event gives the time; on at that time (#139) |
| E7 | a circuit run by other automation asks through its entity | 1 | pass | heating for the circuit alone; the water at its need, **50.0 °C** after the ramp (F14 fixed); the heat call on with no zone calling (#139) |
| D8b | the gateway drops the writes through a hot-water draw and takes them again after | 1 | pass | never another controller; confirmed again after the draw |
| V1 | every VT zone shows the plugin's water data | 1, 6 | FAIL ×2 (precondition, reviewed) | every check passed except "heat available while the flame burns: never judged" |
| Q2 | a curve too low, the correction off: the long-burn sensor within 5 h | 1 | **FAIL (plugin, F15)** | the long-burn sensor stayed off at 4.1 h of burning |
| B3 | a clean restart | 1 | pass | the safe hand-back captured before the connection closed; control back at once |
| B6 | `docker kill` | 1 | pass | the switch as left, control resumed |
| Q1 | a curve too low, the correction on, SmartPI learning: the warning at the correction's limit | 1, then 2 | FAIL, then pass (reviewed) | second run: the correction at 3.0 K from 14:50 UTC; `curve_too_low` 3 h later, naming the three zones |
| Q3 | the curve's room in Auto | 1 | pass | |
| B1, B2, B4, B5 | reload; entry disabled and enabled; heating again after a hand-back; three reloads | 6 | pass | |
| C1–C5 | stale data; outdoor sensor failed; gateway link lost; a hand-back with the gateway away; a gateway reset | 6 | pass | |
| D1–D3, D6, D7 | commands dropped; boiler ignoring; another controller; a clipped setpoint; ID 1 refused | 6 | pass | |
| D4 | another controller, with "return by itself" | 6 | pass | started 00:24 UTC, away from the wall thermostat's program changes |
| E1, E2 | hard maximum at −25 °C; a zone outside the central mode | 6 | pass | |
| F1, F2 | the boiler's low-pressure fault; lockout | 6 | pass | fault signals mapped to the simulator's |
| H1, M1, K1–K5 | every zone unavailable; the monitor failing; stores of a crashed run; an entry without the terminals answer | 6 | pass | |
| Q5 | one room short while the others hold | 7 | FAIL (precondition, reviewed) | `curve_too_low` naming the living room **and** the bedroom |
| E4 | the comfort correction raises the water by 3 K at most and says so at its edge | 7 | FAIL on "told at the edge" (known limit) | 40.1 → 42.6 °C, never above 3 K |
| D8, E6, D5 | SmartPI paused during a draw; the short-cycling boiler; overrides dropped | 7 | pass | |
| L1 | 12 h at −2 °C | 8 | FAIL on two checks (F11) | rooms −1.23 / −0.12 / −1.54 K; 20 heating switchings for at least 36 required |
| T1 | Home Assistant in US customary units | 8 | pass | |
| C6 | no outdoor reading for 3 h | 8 | pass | held, then the fallback 50.6 °C, CH on |
| W1 | the wall thermostat's own program at 06:00 UTC | 8 | pass | the switch showed the night setting 17.0; its call at 06:00 reached the boiler; the plugin wrote nothing after its hand-back |

**The relay, the entity path and a stand-alone gateway**

| ID | Instance | Result | Evidence |
|---|---|---|---|
| R1 | 6 | pass | the relay on, off 9 s after the rooms were satisfied, on again. The heat call, the demand sensors and the event follow it (#139) |
| R4–R18 | 6 | pass | |
| R2, R3 | 6 | FAIL (the runner, reviewed) | no zone called at the restart |
| N1–N8, U1, U2 | 7 | pass | U1: setpoints and flow at most 40.0 °C; U2 at most 36.0 °C; the too-hot alarm off |
| S1, S2 | 8 | pass | the hand-back stops heating; every zone unknown: idle, no hand-back |

Reviewed — the runner's, a precondition or a known limit, none of them the plugin's, except Q1's
first run, whose cause stays open:

- **V1 (both runs).** The positive case waits 15 min for a moment when the flame has burned at
  least a minute before VT's last write of a zone. The flame never did:
  - first run: off from 13:16 to 13:42 UTC. The rooms were at their targets, TPI pulses lasted
    about a minute in five, and the water, at 41.4 °C, was above its setpoint of ~40 °C;
  - second run: bursts of 20–60 s.

  Every other V1 check passed. The scenario should make a real demand first.
- **R2, R3.** Control was switched on during a short VT pulse. The 120-s wait saw the relay on,
  but the valves stayed closed until the next VT cycle. At the restart no zone called, so the
  relay was rightly off and there was nothing to send again. This is R1's case of 2026-10-14;
  `relay_on_under_control`, which R9–R11, R13, R14, R16 and R17 use, avoids it.
- **Q5.** The instance was set up one minute before the run, so the bedroom's SmartPI was in
  `bootstrap_hysteresis`: 0 % for 1.2 h, then 100 % for 3.5 h at 0.1–0.4 K under its setpoint.
  The plugin rightly counts such a zone as short (G11 C), so two rooms were short and
  `curve_too_low` was right. The scenario needs a SmartPI past its bootstrap, or a TPI-only house.
- **E4.** The correction reaches its edge about 2 h into a 3-h scenario, and the edge notice needs
  3 h at the edge. Q5 and Q1's second run show the notice.
- **L1.** This is F11 with the correction off, the default since K4. The rooms were short, and
  the zones fully open most of the time, so the heating switched seldom. Every heating write
  matched VT's demand, and none came over 90 s late. The setpoint was kept alive (30 s at most);
  no alarm, latch or hot-water write. During L1 the long-burn sensor came on after 3.0 h with
  `water_too_cool`, which is the rule working where the flow holds its setpoint (see F15).
- **Q1, first run (instance 1) — open, not cleared.** The correction stalled at about 2.9 K, and no
  warning came. It was not reproduced: in the second run the correction stayed at 3.0 K and the warning came after
  3 h. One cause fits the code: a rule-3 step back after reaching the edge, then no rise because
  the day's 3 K (`CORRECTION_DAY_K`) had been spent. An in-process test is proposed (L13).

At its edge the correction reached the boiler as +2.53 K, not +3.0 K. It climbs in steps under
0.5 K, so its last 0.47 K stays inside F14's write deadband (`guards.py`, `TOLERANCE_K` 0.5) — L12.

### 4.8 `dev` 98d135e: the Boiler page and its cards (code f, 2026-11-20/21, step I10.10)

Instances (3 and 5 set up afresh as above; 4 updated in place):
- **4**: a gateway updated in place from b96016c, with two days of history, 48 h of them under control at −5 °C;
- **3**: a fresh full gateway (the wall thermostat, SmartPI in the bedroom);
- **5**: the relay.

Every start ran without a warning or an error from the plugin, `frontend`, `panel_custom` or
`http`, and without "Detected blocking call". The pages were driven in headless Chromium:
- logged in with the instance's token;
- language and theme set in the browser only;
- time zone Europe/Warsaw.

Every tab on instance 4, and the cards on 4 and 5, were opened in Polish, light, at 1280 px, and in
English, dark, at 390 px; instances 3 and 5's pages in Polish at 1280 px only.
Every shot recorded the browser's console: no error anywhere, except the reload in D (F17).

| | Check | Result | Evidence |
|---|---|---|---|
| A | The page "Kocioł" in the sidebar for an administrator and for a user without administrator rights | pass | `get_panels`: title "Kocioł", `require_admin` false |
| A | The switch "Boiler page in the sidebar" takes the page away and puts it back | pass | |
| A | After reloads (B1, a page save) and a restart (B3) | pass | the page is back each time |
| A | A hidden page stays hidden across a restart | pass | |
| B | Every tab reads its data: Overview, Burner, Use, Analyses, Journal, Status and alarms | pass | Burner: 2.7 starts an hour, median burn 12 min, the burns' lengths |
| B | Replay | pass | "odtwarzanie · 03:40": the tiles and the schematic at that moment (−8 °C); the Control switch disabled, "a moment in the past: nothing can be changed" |
| B | Short history | partly | Analyses says why it shows nothing yet (no gas meter on the simulator); Use shows "—" and an empty chart with no reason (F20) |
| B | The hourly calendar | pass | Friday 2026-11-20, the first day closed by this code (at midnight, so the first with hours; the code itself ran only its last six hours), 67 starts; older days hatched "not recorded (days before this version)" |
| B | Polish and English, light and dark, 390 px | pass | the status detail stays in the server's language (F20) |
| C | Control on and off from the page, with confirmation | pass | "Włączyć sterowanie?" / "Wyłączyć sterowanie?", then heating, then disabled; the journal took_over, then handed_back `control_off`; the safe hand-back at the end |
| C | A user without administrator rights cannot switch control from the page | pass on the page | switch disabled, "only an administrator can change this". The same user switched control on with `switch.turn_on` (F19) |
| D | Change the coldest point, confirm → one reload and the journal entry | pass, with F16 and F17 | 55 → 56 °C saved; journal "settings saved from this page: curve", stopped, started. The stored `exponent: 1.0` was dropped (F16). The user was thrown off the page (F17) |
| D | A value the settings refuse | pass | `design_flow` 200 and 19 → `out_of_range`, nothing changed. A design outdoor temperature of +5 °C is accepted: the settings' bounds are −45 to +10 °C |
| D | A save by a user without administrator rights | pass | `vtherm_smart_boiler/curve/save` → `unauthorized`; Save disabled with "only an administrator can save the curve" |
| E | The journal: start, takeover, heat call, water | pass | |
| E | An options save (`walk.save_options`) | pass | |
| E | C1's alarm | pass | handed_back `boiler_link_stale`, alarm on and off |
| E | B3: "stopped" and "started", the store kept across the restart | pass | |
| E | The hand-back at a reload or restart under control (B1, B3, the page's save), and the takeover after it | **missing (F18)** | the gateway got [20, CH on, 0], control resumed, and the journal shows only stopped/started |
| F | Status and alarms: the verdict with its reasons, the signals, the alarms, the building values, the lowest-water suggestion | pass | |
| F | "Forget" | not checkable | it needs a measured building value, three weeks of heating; disabled for a user without administrator rights |
| G | Four cards in the card picker | pass | "Kocioł: stan / schemat / krzywa grzewcza / ostatnie 24 h", and "Boiler: …" in English |
| G | Each card on a test dashboard without settings, also with the page hidden | pass | |
| H | The relay | pass | the page works; the curve card says "control does not set the water here, so there is no curve"; `installation.curve` null; `curve` → `no_curve`; `curve/save` → `not_available` |

Runner note: B1 and C1 came out NOT RUN right after `base.py`. The base check reads `.storage`
before Home Assistant has written the walk's save to disk. B3, run right after, already saw the
base; B1 and C1 passed when run again after it (14:47 and 14:50 UTC).

### 4.9 `qas` fcae678: I11 and the fixes after codes e and f, narrowed to the changes (code g, 2026-11-22, step I11.6)

The user narrowed the scope (2026-11-22): only what the changes since codes e and f can bring
about, plus the scenarios that had failed for the runner's or a precondition's reason. The other
scenarios passed on code e, and their code is unchanged except for how control is switched; the
sample below switches it on every write path. Every instance ran this commit's configuration with
its role marker. Every start ran without a warning or an error from the plugin, `frontend`,
`panel_custom` or `http`, and without "Detected blocking call". Versions as for code e.

| Change | Check | Instance | Result |
|---|---|---|---|
| Control switched only in the settings; the binary sensor; the wish restored at start; the old switch removed (I11.1–I11.3, #196) | an update in place from `qas` b96016c with control on, by hand | 2 | pass. Before: the switch on, the control store `enabled: true`. After: control on (the wish from the store), the old `switch.*_control` gone from the registry, the binary sensor "Control (experimental)" with the same attributes, journal `started, took_over, call_on, water`, log clean |
| | G2, G3, K5 (refused in the settings, with the blocker's window); K1–K4 (a crashed run's stores: control off, the hand-back first); D3 (another controller: the hand-back and the latch); K3 (a latch cleared by off and on in the settings) | 2 | pass |
| | I1: "Control on" saved together with another change | 2 | pass: one reload, and the new run took the boiler (`settings, stopped, started, took_over`) |
| | I2: the automation of the gateway configuration switches control through `vtherm_smart_boiler.set_control` | 2 | pass: on in 2 s, then off with the safe hand-back; the same action with the runner's token refused (`control_in_settings`) |
| | B1, B2, B3, B6: control back after a reload, an entry disabled, a clean restart and a killed one | 2 | pass. Journal (F18): B1, B2 and B3 `handed_back, stopped, started, took_over`; B6 `started, took_over`, no hand-back (an unclean stop) |
| | the relay, the entity path, the stand-alone gateway | 5, 6, 8 | R1, R7, R8, N1, N4 and S1 pass |
| | "Control on" in the settings, by hand | 3, 4 | pass |
| | `set_control` called by a person, by hand | 4 | refused (`control_in_settings`) for an administrator by REST and WebSocket, and for a user without administrator rights; control unchanged |
| | the Control state's entity ID renamed while control is on (#147), by hand | 4 | pass: control went on, the state under the new ID with its attributes, no hand-back in the journal |
| F15 (#181) | Q2 | 7 | pass: the long-burn sensor after 3.0 h, `water_too_cool` (bath, bedroom), no power-limit warning |
| L12 (#184), L13 (#187) | Q1 | 1 | pass: the correction at its limit 3.0 K, the setpoint written exactly (34.7 °C = the curve 31.7 + 3.0, also the gateway's read-back), `curve_too_low` after 3 h naming the three zones |
| F16 (#180) | a curve saved from the page with an exponent (1.2) and a fallback setpoint (45 °C) stored, by hand | 4 | pass: only the design flow changed (55 → 56 °C); the exponent and the fallback kept |
| F17 (#183, #197) | the plugin reloaded with the page open; the page watched for 30 s after a save from it | 4 | pass: the page kept, never "not running", no browser error |
| The page's Control card (I11.4) | by hand, as an administrator and as a user without administrator rights | 4 | pass: the state ("On" / "Off"); the administrator gets "Change in settings", the other user "only an administrator, in the plugin's settings"; a curve save by the other user refused (`unauthorized`) |
| L14, the runner (#194, #198) | V1, R2, R3 (never passing before); the role marker | 2, 5 | pass: V1's positive case (the rooms called first); R2 and R3 restart the relay once it is on for good |
| — | Q5 | 3 | not run: the bedroom's SmartPI never left its bootstrap (L15) |

Home Assistant logs a refused action or command (`control_in_settings`, `unauthorized`) at
error level through its WebSocket API; these were the refusals the checks asked for.

### 4.10 `qas` 7b34657 and 76559e7: the recalibrated house, the page's display fixes, and the safeguards for OTGW over MQTT and the cloud (codes h and i, 2026-11-22 to 2026-11-24)

**Code h** (`qas` 7b34657, #200–#206) changed four things:
- the simulator's house `average` (5.5 kWh/K, a time constant of 22 h instead of 40 h, #201);
- a light bedroom on the gateway, so that SmartPI can learn (0.5 kWh/K, its radiator 2.5 times its load);
- the page's display fixes (F20, #205);
- P2, the runner reading the page's commands.

The Python of `custom_components/` is that of code g.

The user narrowed the scope (2026-11-22) to:
- every scenario whose outcome the house can change;
- one sample for each other role;
- P2 and the page by hand.

The 5-min starts runs were left out.

How it was run:
- Every instance was cleared (its state kept on it), set up afresh through the API, and restarted once.
- Every start's log was clean: no warning or error from the plugin, `frontend`, `panel_custom` or `http`, and no "Detected blocking call". The only warnings were those Q1, E4 and Q5 ask for.
- Versions as for code e.

| Scenario | Instance (role) | UTC | Result |
|---|---|---|---|
| R9 | 5 (relay) | 11-22 20:59–21:46 | pass: the 10-min timer renewed, never lapsed |
| N1 | 6 (entity path) | 20:59–21:03 | pass |
| S1 | 8 (stand-alone) | 20:59 | pass |
| Q1 | 6 (gateway) | 21:04–02:32 | pass: the correction rose after 56 min; at its limit `curve_too_low` named the three zones; written 34.7 °C = the curve 31.7 + 3.0 |
| Q2 | 8 (gateway) | 21:10–00:47 | pass: `water_too_cool` after 3.0 h, the three rooms, no power-limit warning |
| Q3 | 8 | 00:47–01:24 | pass |
| P2 | 8 | 01:24–01:25 | pass: the installation, the curve, a draft that saved nothing, the days, the burns |
| E4 | 6 | 11-23 03:16–08:44 | pass: the correction rose from 40.1 °C after about 65 min and reached 3 K (43.1 °C, written exactly) after about 2 h 20 min; told at its edge. It used 5.5 h of its 6-h window (L19) |
| D8 | 6 | 08:44–09:41 | pass: the bedroom's valve open at the draw; SmartPI paused and resumed; the hot-water bit never written |
| L1 | 5 (gateway) | 11-22 21:47 – 11-23 09:48 | pass at −2 °C for 12 h (details below) |
| Q5 | 1 (gateway) | 11-23 07:46–13:13 | pass, for the first time: the correction rose after 61 min; after 4.4 h `room_short_at_limit` named the living room alone |

L1 in detail:
- The setpoint was 44.5 °C, kept alive (the longest gap 30 s).
- Heating followed VT; there was no alarm or latch.
- The light bedroom was 0.25 K over its setpoint.
- The living room was 1.27 K short and the bath 1.89 K short. Both were told as `water_too_cool` after 3.0 h (F11).

Q5's precondition was met as the run's plan set it:
1. Instance 1 was kept for Q5 alone: the runner's reset, then SmartPI's learning reset at 2026-11-22 20:58:35 UTC, then control switched on in the settings and left on, and nothing else run.
2. The bedroom's SmartPI went from `bootstrap_hysteresis` to `stable` at 2026-11-23 04:39:22 UTC (by the recorder): 7 h 41 min, where the model said about 11 h.
3. On the way there were four swings each way, each about 2 h 5 min, between about 19.0 and 20.1 °C (SmartPI's thresholds are 19.2 and 20.0 °C); the first cooling, from the start, was a partial one. They were sampled every 5 min by the bench. That is fewer phases than L15's reading of SmartPI's documentation (five cooling, four to five heating); SmartPI's own count was not read.
4. Q1, which resets SmartPI's learning, ran on another instance.

**The page by hand (F20, #205)** was checked on instance 8, freshly set as a gateway, in headless Chromium. A test user was made for it, with English over the server's Polish, and removed after.

| Check | Result |
|---|---|
| Status reasons in the user's language | pass: the overview and the status card in English |
| The browser in Asia/Tokyo, the profile's time zone "local" | pass: the burner, the 24-h axis and the journal in Tokyo time; Analyses says "Days and hours in Home Assistant's time zone (Europe/Warsaw)." |
| The profile "server", or a browser in Europe/Warsaw | pass: Warsaw time, and no such note |
| Days and starts by hour, with about 6 h of data | pass: in Home Assistant's zone. Under a Tokyo browser the starts sat in the row "22 Sun", hour 22, as in Warsaw |
| Use on a fresh instance | pass: "—" with its reason ("not known yet — the daily summaries are filled day by day"; later "it needs 7 whole days of data") |
| A narrow dashboard column (a test dashboard, removed after) | at 340 and 420 px the schematic card is not cut and has no scroll bar, but its labels overlap (F21) |
| The browser's console | no error or warning |

**Code i** (`qas` 76559e7, #207–#210) changed three things:
- #207: the OTGW firmware's entities over MQTT are recognised without a device, and while only monitoring;
- #208: control is blocked, and the forms refuse, where a write target's integration declares a cloud `iot_class` (the blocker `write_through_cloud`);
- #209: documents only.

The simulator, the runner, the configurations and the page are those of code h.

Neither change can be shown on the bench:
- There is no MQTT broker. The gateway is the `opentherm_gw` stub, whose entities count as before, because #207's new branch runs only with OTGW over MQTT (L17).
- There is no cloud integration. The simulator's integrations declare `iot_class: calculated` (L18).

The user therefore narrowed code i (2026-11-23) to the absence of regressions:
- It ran on the free instances while code h's starts runs went on, deployed from a checkout of its own.
- The rest is carried over from code h. On the gateway paths the new check has no write target, and the controller, the curve and the correction are unchanged.

| Check | Instance (role) | Result |
|---|---|---|
| The control entities' blockers; the options' "control" item walked and saved unchanged | 5 (relay), 6 (gateway), 8 (entity path, then stand-alone) | pass on all four: no `write_through_cloud`; saved unchanged on all four, the control form walked on the relay (`control_relay`) and entity (`control_entity`) paths, without an error |
| F1, the boiler's own fault | 6 | pass (12:00–12:12): heating off after 5 min, no hand-back, `boiler_fault`, back when the fault cleared |
| P2 | 6 | pass |
| R9 | 5 | pass (12:00–12:47); the blockers still empty after it |
| N1, S1 | 8 | pass |

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

Third run — code (e), K4's criterion (at most 1.10 times the boiler's own starts, or at most 6
starts an hour with a median burn of at least 10 min), the correction off by default, the
plugin's curve the boiler's own. The criterion is judged with VT's 15-min cycle, the one the plugin
advises; the 5-min runs record VT's default. Each pair is judged over the same 24 h, after a day
to settle (the bench's analyser, from the recorders: burner starts are the flame's off → on).

| 15-min cycle, 2026-11-19 11:53 → 11-20 11:53 UTC | +8 °C control (2) | +8 °C own (3) | −5 °C control (4) | −5 °C own (5) |
|---|---|---|---|---|
| burner starts (per hour) | 87 (3.62) | 87 (3.62) | 49 (2.04) | 40 (1.67) |
| median burn (min) | 7.2 | 7.7 | 11.8 | 11.9 |
| heating switchings | 170 | 168 | 98 | 80 |
| mean setpoint / flow | 37.6 / 36.5 | 37.0 / 35.9 | 50.6 / 50.1 | 50.0 / 49.5 |
| rooms (living / bedroom / bath) | 19.44 / 18.61 / 20.66 | 19.38 / 18.56 / 20.60 | 19.48 / 18.57 / 20.81 | 19.44 / 18.55 / 20.79 |

×1.00 at +8 °C — pass; ×1.23 at −5 °C, but 2.04 starts an hour with a median burn of 11.8 min —
pass on the absolute rule. The rooms 0.02–0.06 K warmer under control. `zone_cycle_short` never
shown; the frequent-starts sensor never on.

| 5-min cycle | +8 °C control (6) | +8 °C own (1) | −5 °C control (7) | −5 °C own (8) |
|---|---|---|---|---|
| window (UTC) | 11-20 04:10 → 11-21 04:10 | same | 11-20 06:23 → 11-21 06:23 | same |
| burner starts (per hour) | 163 (6.79) | 144 (6.00) | 60 (2.50) | 32 (1.33) |
| median burn (min) | 2.0 | 1.9 | 2.0 | 1.9 |
| rooms (living / bedroom / bath) | 19.41 / 18.58 / 20.62 | 19.37 / 18.55 / 20.58 | 19.43 / 18.53 / 20.76 | 19.43 / 18.52 / 20.78 |

×1.13 at +8 °C and ×1.88 at −5 °C — not met, as the simulation expects with 5-min cycles; the rooms
as warm. `zone_cycle_short` named the three 5-min zones on every 5-min instance (#150), and the
frequent-starts sensor showed the level `warning` at +8 °C under control (#152). The monitor's
information on the boiler's own regulation at 5 min: "unstable ignition" (+8 °C); at 15 min the
lowest-water suggestion (at the window's end: 31 of 32 burns at 34 °C shorter than 10 min; 36 °C
suggested).

Fourth run — code (h), the recalibrated house (#201), K4's criterion. Instances 2, 3, 4 and 7,
VT's 15-min cycle. The correction was off and the plugin's curve was the boiler's own, as for
code e. The runs started on 2026-11-22 at about 20:56 UTC. They were planned as a day to settle, then
24 h to compare; the user ended them early (below). The 5-min runs were left out by the user. In-process on the new house: ×0.98 at
+8 °C; at −5 °C ×1.34, 2.1 starts an hour, a median burn of 11.8 min.

| 15-min cycle, 2026-11-23 09:00 → 11-24 09:00 UTC | +8 °C control (2) | +8 °C own (3) | −5 °C control (4) | −5 °C own (7) |
|---|---|---|---|---|
| burner starts (per hour) | 86 (3.58) | 85 (3.54) | 54 (2.25) | 38 (1.58) |
| median burn (min) | 7.3 | 7.8 | 11.8 | 11.9 |
| heating switchings | 166 | 168 | 108 | 76 |
| mean setpoint / flow | 37.7 / 36.6 | 37.0 / 35.9 | 50.7 / 50.1 | 50.0 / 49.6 |
| rooms (living / bedroom / bath) | 19.45 / 18.62 / 20.69 | 19.38 / 18.57 / 20.60 | 19.48 / 18.57 / 20.82 | 19.45 / 18.55 / 20.79 |

×1.01 at +8 °C passes. At −5 °C it is ×1.42, but with 2.25 starts an hour and a median burn of
11.8 min it passes on the absolute rule, as in-process (×1.34). The rooms were 0.02–0.09 K warmer
under control. The frequent-starts sensor was off at every check. The monitor's lowest-water suggestion
showed on the boiler's own regulation at +8 °C, as for code e.

The user ended the runs early (2026-11-24). The window starts 12 h after the runs began, instead
of a day:
- The rooms start at their targets.
- The new house settles about twice as fast.
- In the window the two instances of a pair differ by 0.09 K at most.

The first 12 h are left out. The house was still settling then:
- control's rooms ran warmer (0.21–0.29 K at +8 °C, 0.11–0.15 K at −5 °C);
- at −5 °C, control started the burner ×1.92 as often (48 against 25).

At −5 °C the two halves of the day differ:
- 09:00–21:00 UTC, the warmer half (mean −3.2 °C): 33 against 18 starts, ×1.83;
- 21:00–09:00 UTC, the colder half (mean −6.9 °C): 21 against 20, ×1.05.

The warmer half came right after the settling. From one day, it cannot be told whether the
difference comes from the hour or from the house still settling. The criterion is judged over the
whole day. The windows come from the bench's analyser, and its output is kept with the run's
evidence.

## 6. Not run, and why

- Code h:
  - Narrowed by the user to the changes: the scenarios whose outcome the new house can change, one
    sample per other role, P2 and the page by hand. Every other scenario passed on code e or g, and
    the house changes only how fast the rooms move.
  - The starts criterion with VT's 5-min cycle: not run (the user, 2026-11-22). It is expected to
    fail as before (section 5).
  - F20, Use with a whole week without gas or a very warm one: the bench's instances hold under two
    days of data.
- Code i:
  - Narrowed by the user to the absence of regressions (section 4.10). Carried over from code h: Q1,
    Q2, Q3, Q5, E4, D8, L1 and the starts criterion. On the gateway paths the new check has no
    write target, the gateway signals are the same set, and the controller, the curve and the
    correction are unchanged.
  - #207 with the firmware's MQTT entities, and #208 with a cloud integration: neither exists on the
    bench (L17, L18). Both are covered in-process.
- Code g:
  - Narrowed by the user to the changes. Not run, because they passed on code e and their code is
    unchanged except for the switching of control, which section 4.9's sample covers:
    - C1–C6, D1, D2, D4–D8, D8b, E1–E7, F1, F2, H1, M1, B4, B5, L1, W1, T1, Q3, E4;
    - R4–R6 and R9–R18;
    - N2, N3, N5–N8, U1, U2, S2;
    - the starts criterion.
  - Q5: the bedroom's SmartPI stayed in its bootstrap for 27 h (L15).
- Codes e to g, an entry stored before minor version 21 taken to counting devices (#136): no allowed
  backup holds one; covered in-process.
- H2, a zone in "auto" or of the over_climate type: VT's over_switch zones offer only heat and off;
  covered in-process.
- The firmware MQTT path: the `opentherm_gw` stub route works; MQTT needs a broker in the LXC.
- The connection types of I6 beyond the generic paths (ESPHome, EMS-ESP, the boiler's Wi-Fi module):
  the simulator offers the generic entity path only.
- Underfloor heating over six hours: 100 min each (U1, U2), enough for the cap and the alarm.
- Home Assistant in °F on the entity path: on the gateway path only (T1).
- The long-burn rule's classes (G11 E): not reached (Q2, F10). Code e: `water_too_cool` reached in L1
  after 3.0 h; Q2 shows F15.
- `dev` after G11 (I7, I8): not tested on `dev`; tested on `qas` c488e90 (section 4.6).
- On `qas` c488e90, outside the scope agreed for that run: every scenario not in section 4.6 —
  among them the restarts (B3, B6), the starts criterion and the corrections' scenarios. Q4 is obsolete since #64:
  it reads the plugin's window sensor, which is gone.
- VT 10.5.1's valve zones (`over_valve`, `over_climate_valve`), whose "device active" changed: the
  simulator has switch zones only; a real-VT test in-process (#130).
- #110 and #112 (the guards during a draw): the simulator keeps the gateway's override through a
  draw, so D8 cannot show them; #114 cannot change D1's result; #116 needs the comfort correction,
  off in the base: in-process tests (`tests/core/test_guards.py`, `tests/core/test_controller.py`).
- `vtherm_api` 0.6.0 in a test Home Assistant: the instances keep 0.5.0; 0.6.0 runs in CI's early
  warning only.
- Code f, the offset saved from the Boiler page at the simple level: every test entry is at
  the advanced level.
- Code f, "Forget" on the page: it needs a measured building value (three weeks of heating),
  which the simulator never reaches.
- Code f, "no options flow left open" after a page save: Home Assistant's API lists no options flows;
  covered in-process.
- Code f, an English sidebar title: the title follows the server's language, read when the page is
  registered.
- Code f, the plugin's new steps in start, unload and options update failing (the scope check's
  gap): no bench fault can make them fail; in-process tests are proposed.
- Code f, the entry's removal (the journal's store removed with it): covered in-process only.
- Code e, B6 on an instance other than 1: the runner is bound to instance 1's directory.
- Code e, the in-place change of the Control switch's entity ID on Home Assistant 2026.11 (#147), a
  check by hand in the run's plan: not made. Covered in-process only (`async_entity_id_changed`).
- Code e, an entry stored by an older version taken to counting VT's devices (#136, "Count: Zones"
  kept for it), a check in the run's plan: not seen. Every instance was set up afresh, and instance
  4's update in place kept the same entry version, so no migration ran. Covered in-process only.

## 7. Findings and known limits

Status on the morning of 2026-10-11: N2 passed again (code c); N8 running again on instance 7 to check its restore after an owed hand-back.

| # | Finding | Weight | Follow-up |
|---|---|---|---|
| F1 | the simulator had no `services.yaml`: Home Assistant logged an error at start (its services worked) | low, test only | fixed (#32) |
| F2 | on a fresh install the plugin logged a warning "No stored control state could be read; control is not configured, so nothing is owed" — a normal state at warning level | low | fixed (#34): information |
| F3 | VT 10.4.0's Polish translation fails Home Assistant's placeholder check (two strings) | low, VT's own | none here |
| F4 | `select.central_mode` in the notes is the option's name; the entity ID follows the central entry's name | none | none |
| F5 | VT's central configuration created after Home Assistant started — without a central boiler — keeps control waiting until a restart (by design) | low | the user guide says so (#35) |
| F6 | VT switches a zone to its safety mode when its sensor's state is not written for 60 min; a steady room or outdoor temperature can stay one value that long — in the simulator, and so in a real home with a sensor that reports only changes | medium, setup | the test zones' safety delay raised; worth a line in the user guide (VT's safety delay against steady sensors) — to decide; done: the user guide (#204) |
| L1 | VT's activation delay checks the demand again at its end: a TPI pulse shorter than the delay never starts the boiler | by design | said in the option's description |
| L2 | "return by itself" counts its quiet hour from the other controller's last write, the wall thermostat's own program changes included | by design | said in the option's confirmation |
| L3 | behind an OpenTherm Gateway a boiler that ignores the setpoint is not seen: the gateway echoes what it sends | the real path's limit | known (PB-91) |
| F7 | a held device restarting during a hand-back never got the setpoint's hand-back value: a third value on the read-back after the outage was judged another controller's before the plugin wrote it, and the "hand-back failed" alarm cleared | high, entity path | fixed (#51, #58); J4 N2 passes: [20, CH on, 0] written once back |
| F8 | the comfort correction on: at night ×1.30 (+8 °C) and ×4.42 (−5 °C) the boiler's own starts, for 0.00–0.07 K of comfort — the rooms stay about 1 K short through VT's TPI offset, which the correction cannot remove, and the water at the limit makes every TPI cycle stop the burner | medium | decided at K4 (2026-11-17): off by default, as the literature advises with TPI zones (the simulation in the tests says ×1.39 and ×6.28) |
| F9 | the starts criterion fails at −5 °C over a full day with the correction off (×1.72; ×0.93 at night) | medium | K4: heating follows VT at once by the user's rule |
| F10 | the long-burn rule runs only after 3 h of flame without a break; a boiler cycling at its minimum while the rooms stay short never triggers it, so with the correction off nothing tells the user (Q2) | medium | decided at K4 (#151: flame gaps up to 30 min kept); code e: the rule reached `water_too_cool` in L1; Q2 then showed F15 |
| F11 | 12 h at −2 °C with the default curve and the correction off left the rooms 1.1–1.7 K short, the flame on 100 % and the flow at its setpoint — the boiler had reserve, the water was too cool (the case behind G11) | none now | G11 B, D and E address it |
| L4 | the simulator's outdoor sensor, set by hand, stays flat for over 12 h while its weather moves: the plugin rightly judges it stuck and uses the weather | test bed | none |
| L5 | VT's TPI zones (coefficients 0.6 / 0.01) hold the simulated rooms about 1–1.5 K under their setpoints in every regime, with and without the plugin | test bed, VT | none here; it is what F8 meets |
| L6 | a relay timer that is a whole multiple of the plugin's 5-min renewal lapses together with a renewal, hidden from Home Assistant (PB-25) | by design | the runner uses 11 min |
| F12 | "Control mode" could not be saved on an entry made before the connection question: the form showed, its save failed (`apply_mode` read a connection such an entry does not store) and nothing was saved — found by reading, in the scope check of 2026-10-13 | low (control unchanged), entries made before I6 | fixed (#127); G2 passes on instance 1 (code d) |
| F13 | VT 10.5.1 changed when a valve zone counts as "device active", which the plugin reads for a zone's demand; J4's zones are switches | medium, valve zones | a real-VT test (#130) and the user guide (#131) |
| L7 | E3 measures its first start from a call made while a start from an earlier call is pending (section 4.6) | the runner | R18's pause of 150 s before each call |
| L8 | V1 judges the heat shown by the flame around its reading; VT's attribute is as old as VT's last write of the climate's state | the runner | compare at the climate's `last_updated` |
| L9 | R1 waits 120 s for the relay while VT may open the valves only at its next cycle | the runner | wait for the valves first |
| F14 | after a ramp up to a circuit's floor (E7: towards 55.0 °C) the setpoint written stopped at 54.5 °C and stayed there, with no `ramp` reason, until the circuit stopped asking; the controller's target was 55.0 (switched on while asking: 55.0 at once) | low (0.5 K below the floor, 4.5 K above the circuit's need) | cause, read in the code and matching the run: `core/guards.py` `_plan` sends a change only when it differs from the value written by more than the read-back tolerance (`TOLERANCE_K`, 0.5 K), and a keep-alive resends the value written — so a target 0.5 K or less from it is never written (the end of any ramp, a small curve change). fixed in #135: a bound the water is held at is written exactly |
| L11 | E7 expects the circuit's floor within 60 s while control, already on, ramps to it | the runner | wait for the ramp, or switch control on while the circuit asks |
| L10 | after a scenario ends with control off and the rooms calling, the relay's information issue `relay_rests_off` stays (instance 6); the entity path's `hand_back_taken_by_other` stays after N2 (instance 7) | by design | none; left on the instances |
| F15 | code e, Q2: with the flame burning without a break, the long-burn rule says "the water too cool" only while the flow holds its setpoint within 1 K. A boiler at its minimum output with the water above a too-low setpoint (34 °C against 31.7 °C, modulation 0, two rooms fully open and short) gets no class. With one burner stop in the window the same water does (`core/long_run.py` `_classify`: `abs(gap) <= HOLDING_K` against `min(gaps) <= HOLDING_K`; a probe on Q2's values) | medium — no advice where the curve is too low | the unbroken branch to accept a flow at or above its setpoint; Q2 again; fixed (#181), confirmed in code g (Q2) |
| F16 | code f, D: a curve saved from the Boiler page drops the stored exponent at the advanced level (and, by the code, `fallback_setpoint`): 55 → 56 °C asked, `exponent: 1.0` gone, the water 47.9 → 50.2 °C after the reload. The confirmation names only the point and the offset (`websocket_api.py` `_form_values` sends fields with a default only; those two are suggested values) | medium — a silent change of the water | send what the form shows, as J4's walk does; an in-process test with a stored exponent; D again; fixed (#180), confirmed in code g (with an exponent and a fallback stored) |
| F17 | code f: every reload takes the page out of the sidebar for a moment (the sidebar switch hides it at unload, `switch.py`), so a user on the page — after saving the curve from it, or during any settings save — lands on the default dashboard, with a browser error (`Cannot read properties of null (reading '_panel_custom')`) | low to medium — the save's result unseen | keep the page through a reload; fixed (#183, #197), confirmed in code g (a reload and a save with the page open) |
| F18 | code f: the journal records neither the hand-back at a reload or restart under control nor the takeover after it, nor a change of the water across it — a reload under control reads "stopped, started" (B1, B3, a page save; the gateway got [20, CH on, 0]). The journal's first look after a start is a silent baseline (`core/journal.py` `follow`) | low to medium — the journal's account incomplete | journal the hand-back at unload and the state found at start; an in-process test under control; fixed (#182), confirmed in code g (B1, B2, B3, B6 read the journal) |
| F19 | code f: control can be switched on by any Home Assistant user. The page allows only an administrator, but the Control switch is an ordinary entity: a user without administrator rights switched it on with `switch.turn_on` | to decide | decided 2026-11-22: control switched only by an administrator, and only from the plugin's own configuration, not from a dashboard; done in I11 (#189–#193, #196), confirmed in code g by hand (a person's `set_control` refused, the page's card, an update in place) |
| F20 | code f, display: the status detail is the server-side `reasons_text`, in the server's language for a user who chose another; the page shows times in the browser's time zone, not by the profile's setting (a browser in another zone than the server sees days and hours shifted); Use shows "—" and an empty chart without a reason; the schematic card is cut on the right in a narrow dashboard column | low, display | to fix with the page; fixed (#205), confirmed in code h by hand, but for the labels in a narrow column (F21) |
| L12 | code e: at its 3-K limit the comfort correction reaches the boiler as +2.53 K: it climbs in steps under 0.5 K, and the last 0.47 K stays inside F14's write deadband | by design, under 0.5 K | decided 2026-11-22: the correction's limit written exactly, as a bound; done (#184), confirmed in code g (Q1: 34.7 °C = 31.7 + 3.0) |
| L13 | code e: Q1's first run, the correction stalled at about 2.9 K with no warning; not reproduced (second run: 3.0 K and the warning after 3 h). Fits a rule-3 step back after the edge with the day's 3 K already spent | open | an in-process test: the edge reached, one starts rise, whether the correction returns to the edge and the warning comes within the day; the warning now counts the time with the day's 3 K spent (#187); Q1 passed in code g |
| L14 | code e, the runner: V1's positive case waits for a flame that may never burn; R2 and R3 restart the relay before it is on for good; Q5 assumes a SmartPI past its bootstrap; E4 is shorter than the edge notice; L1's bounds (rooms within 1.5 K, 3 switchings an hour) do not fit the default curve at −2 °C; the base check reads `.storage` before Home Assistant writes a save; no scenario's role is checked against the instance's (`Run.options` writes the gateway base on a starts or stand-alone instance); B6 is bound to instance 1; scenarios without a restore after an abort (H1, S2, N5, R17, E2, R6, D4, T1); no setup script and no starts analyser in the test pack | the runner | for the development session; fixed (#194, #198): roles marked, B6 per instance, restores, V1, R2, R3, E4, L1, Q5's precondition (not run while the bedroom's SmartPI learns); V1, R2, R3 passed in code g; E4, L1 and Q5 in code h |
| L15 | code g, Q5 not run: the bedroom's SmartPI never leaves its bootstrap on the simulator. By the author's rules (0.6.7) it needs the dead times, then 5 cooling and 4–5 heating phases, each a full swing from the setpoint −0.3 to +0.5 K. In 27 h (2026-11-21 14:28 to 2026-11-22 17:53 UTC) the bedroom finished none: its valve stayed open, the room peaked at 19.7, then 19.8 °C, against the 20.0 °C stop (Q5 met the same on 2026-11-18) | the test pack | Q5 already refuses to run while SmartPI learns (#194), but no test covers that check; missing is a way to meet the precondition: a faster room (L16) first, a TPI bedroom for Q5 as a fallback; done (#201: the light bedroom, the check's test); Q5 passed in code h, SmartPI learned in 7 h 41 min with control on |
| L16 | the simulator's house `average`, used by every role, is heavy and well insulated: a loss of 0.25 kW/K, a capacity of 10 kWh/K, 0.5 kW of gains, a time constant of 40 h, about 0.35 K/h of cooling at +3 °C (measured 0.29 K/h, the bedroom, 2026-11-22 night). Phases take hours and SmartPI's learning days; the rooms reach their setpoints slowly (L5). `leaky` (about 18 h) is in the simulator, unused | the test environment | the user, 2026-11-22: recalibrate `average` (about 5–6 kWh/K, 20–24 h), a faster house or room for the SmartPI scenarios, the starts criterion checked again after any change; done (#201: 5.5 kWh/K, 22 h); the starts criterion met on it (section 5, code h) |
| F21 | code h, the page: in a dashboard column of 340 or 420 px the schematic card is neither cut nor scrolled, but its labels overlap: "Outdoor" under its temperature's badge, "hot water" and "cold" over the boiler's edge, and at 340 px "burning · heating" wider than the boiler. Seen on the screenshots (kept on the bench); the bench's automatic overlap probe found no labels to compare, so it proved nothing | low, display | to fix with the page; fixed (#213): the outdoor value and its name one block, the combi's words end before the boiler and leave a narrow card, the boiler's state wraps to its width; a check in the page's screenshots measures every label. The same check found the overview's control box wider than a 390-px phone in Polish; it wraps now |
| L17 | code i, #207: the OTGW firmware's entities over MQTT, written by hand without a device, cannot be shown on the bench — no MQTT broker; the `opentherm_gw` stub's entities count as before (the new branch runs only with OTGW over MQTT) | the test environment | in-process tests (`tests/integration/test_transport.py`, `test_alarms.py`); the user decided against a broker on the bench (2026-11-23) |
| L18 | code i, #208: a cloud integration cannot be shown on the bench — the simulator's integrations declare `iot_class: calculated`, so `write_through_cloud` cannot appear | the test environment | in-process tests (`tests/integration/test_control.py`, `test_config_flow.py`, `test_writers.py`) |
| L19 | code h, the test pack: no in-process test runs the comfort correction against the light bedroom, which swings through SmartPI's band. J4's Q1, E4, Q5 and L1 were the first test of it, and passed. E4 used 5.5 h of its 6-h window on the new house | the test pack | an in-process test of the correction on the light bedroom; E4's window checked against the new house; done (#213): the simulator runs a zone on SmartPI's learning from scratch; two closed-loop tests — the ten phases end with the correction on and no room 1 K over, and the correction raised for the learning bedroom is back at 0 within 3 h of its last phase; E4 waits up to 8 h. Found: with only the learning bedroom short, the at-limit warning names it — to decide |

The runner's own faults found and fixed during J4, none the plugin's: timings inside the relay
rule's confirmation window; preconditions not met (rooms at target before a fault, a VT cycle that
began before the call); 10-s samples behind the plugin's changes (L1); a restore refused while a
hand-back was owed and not noticed (N8 → the void N2/N6 runs); options saved without the fields the
runner did not set (G11's new defaults). Since 2026-10-10 the runner refuses to run a scenario on
an instance not in its base state, stops on a refused restore, and attaches the plugin's warnings,
the control state, the alarms and the issues to every failure.

