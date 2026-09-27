# Plan 0.2.1 — Corrections after the review, and the user's control model

Goal: finish the 0.2 build before the test HA. Every finding of the independent code review of
2026-09-24 (`docs/review-2026-09-24.md`) is fixed, or made moot by a recorded decision, and the
user's decisions of 2026-09-25 are applied: Versatile Thermostat decides whether to heat, no
counter or timer blocks the boiler, and every value the plugin learns stays within firm limits.
The steps of `docs/plan-0.2.md` still open (J2, J4, K1–K7) follow on 0.2.1: it is the first
version to reach the test HA and to be published (pre-release 0.2.1b1, then 0.2.1 — confirmed by
the user at K5).
Scope: `SCOPE.md`; overview: `PLAN.md`.

Phases run in order: L, M, N, O, U, W, R. R1 and R4 are small and may come earlier. L4 waits for
the user and does not hold up the build.

## In short

- **Handing the boiler back must never fail silently.** Today some hand-backs only look done
  (phase M).
- **VT's thermostats decide whether to heat.** The plugin switches heating on and off exactly
  when VT's zones ask, and only chooses how warm the water is (phase N).
- **Nothing the plugin counts or times can keep the house cold.** Budgets and anti-cycling
  timers go (phase N).
- **Whatever the plugin adjusts by itself stays within firm limits**, and stops at "good enough"
  (phase N).
- **The plugin knows whether its data and its writes are real** (phase O).
- **The integration becomes a good Home Assistant citizen**, and the monitor's verdict and
  numbers get right (phases U, W).
- **The release passes Home Assistant's and HACS's checks**, and the test HA works (phase R).

## How to read this plan

- Steps are named by phase letter and number: L1, M2, N5… The review's findings keep the
  review's own names: P01–P111 are problems in the code, S01–S32 problems in the specification;
  "review question 1–10" are the review's open questions. The index at the end gives the step for
  every one of them.
- 🔒 marks a step that needs the user's consent or action; ✅ marks a finished step.
- A provisional decision is the most cautious option, used until the user decides; it is marked
  as such where it applies.

## Terms

- **Hand-back** — the plugin gives the boiler back to its own control or its thermostat: it
  cancels what it set (an OTGW gets `CH=1`, then `CS=0`; a picked entity gets its hand-back
  value, or the external-control switch goes off). It happens on every exit: switching control
  off, reload, unload, Home Assistant stopping, an error, lost data, an alarm set to hand back.
- **Write path** — how the plugin reaches the boiler: an entity the user picked (e.g. an
  EMS-ESP or ESPHome number), the OpenTherm Gateway integration's services, or the OTGW
  firmware's MQTT commands.
- **Write type** — what the device does with a written value:
  - *expiring* — dropped unless repeated, so the plugin repeats it every 30 s (the
    *keep-alive*); OTGW's `CS` is one;
  - *persistent* — stored in the boiler's memory, which every write wears; 0.2.1 never writes
    it (the user's decision below);
  - *held* — kept by the device, which repeats it by itself (e.g. an ESPHome OpenTherm master);
  - *unknown* — treated as persistent, so not written either.
- **Daily cap** and **reserve for heat** (removed with persistent writes) — a cap on writes to the
  boiler's memory per 24 hours, whose last writes were kept for returning to heat.
- **Read-back** — the value the boiler (or the gateway) reports back, compared with what was
  written: a write the boiler ignores, or another controller's value, is noticed.
- **Outside change** — another controller has changed the value. The plugin writes its own once;
  if it changes again within a day, the plugin stops writing and raises an alarm — no fight.
- **Latch** — after some alarms control stays handed back until the user switches it off and on.
- **Blocker** — a reason control may not run now (a missing setting, the monitoring period, VT's
  own central boiler configured…), shown on the control switch.
- **Topology** — how the gateway sits between thermostat and boiler: *with a thermostat* (on
  hand-back the thermostat takes over), *stand-alone* (no thermostat: on hand-back heating
  stops), *monitor mode* (it only listens: no control), *virtual* (a controller on the Home
  Assistant side).
- **Demand** — whether VT's zones want heat: from their valve opening, duty cycle or heating
  action, against a threshold (number of zones, power, opening).
- **Budget** (removed by the decisions below) — a count per hour of burner starts or of heating
  on/off switchings which, once used up, held heating off for up to tens of minutes.
- **Anti-cycling timers** (removed) — a minimum burn and a minimum pause that held heating on or
  off regardless of VT.
- **Comfort correction** — when a zone's valve is fully open and its room is still cold, the
  plugin raises the water a little above the curve.
- **Bounded learning** — the rules for every value the plugin adjusts by itself (below).
- **Frost protection** — heating when a room falls below 5 °C, even without VT's call.
- **Freshness** — whether a reading is still valid: its entity available and, if the user set an
  age limit, reported within it.
- **VT's central modes** — VT's global modes (Auto, Stopped, Heat only, Cool only, Frost
  protection); VT applies them only to zones that follow the central mode.
- **`CS` / `CH` (OTGW)** — `CS` sets the control setpoint, the water temperature; `CH` enables or
  disables central heating.

## Decisions of 2026-09-25 (the user)

- **VT decides whether to heat.** The plugin replaces VT's central boiler: heating on/off follows
  the zones' demand at once, in both directions, at every control step. The plugin decides only
  the water temperature — the curve, the limits and the ramp.
  Why: the thermostats know the rooms; a second on/off policy in the plugin only fights them.
- **No hard blocking of the boiler.** No counter or timer holds heating off, or on, against VT:
  minimum burn, minimum pause, the budget of starts, minimum on and off times and the switching
  budget go. Old boilers with a high minimum output cycle a lot on their own; blocking would leave
  the house cold. Frequent starts are information: an alarm with its threshold, and the verdict.
  Technical safeguards stay because they do not decide whether to heat: the hard limits of the
  water temperature, a write-rate guard against a runaway loop (a repeated write waits at most one
  step) and hand-back on every exit.
  Why: the review showed the budgets holding heating off for 20–40 minutes while rooms called.
- **Bounded learning.** Every value the plugin adapts or learns by itself — now and in later
  releases — follows fixed rules that are not options:
  1. a firm band around its starting point (the user's entry or the default), never left;
  2. a limited rate of change, per hour and per day;
  3. it moves only while every other criterion holds — comfort in every zone, no zone
     overheating, cycling not rising, every limit kept — and steps back when another one gets
     worse;
  4. the aim is a "good enough" band, not an optimum: learning stops inside it;
  5. it freezes in unusual conditions: hot water, foreign heat, data gaps, hand-back, extreme
     weather;
  6. at the band's edge it informs instead of pushing on — the starting point is probably wrong;
  7. every learned value is visible and can be reset; hand-back resets it.

  Why: pushing one quantity to its ideal can break another (warm one room, overheat the rest).
- Recorded on 2026-09-24, already in `CLAUDE.md`: the language is Home Assistant's; DIY interface
  sources are downloaded on purpose into `research/diy/`.

The user's answers of 2026-09-25 to the questions this plan raised:
- **Frost protection stays** as a safety net — the one case where the plugin heats without VT's
  call. It watches every zone, or one zone the user picks (N4).
- **Summer and winter come from VT.** The plugin has no summer switch of its own: with VT off it
  does not heat; with VT calling it heats (N2).
- **VT's central modes act through the zones' demand**, as VT applies them per zone; zones
  outside the central mode still count (N2).
- **"Off" into the boiler's memory depends on what is written and where** — no single rule: it is
  decided per write target (N6). Settled by the later answer below: nothing goes into the
  boiler's memory.
- **Stand-alone gateway: alarm and off.** A lost boiler link raises an alarm and control hands
  back, so heating stops; "no write without fresh data" holds for every topology (M7).
- **The comfort correction** under bounded learning: at most +3 K, rising slowly (1 K per 30 min,
  only while heat flows), falling twice as fast, no rise while another zone is more than 1 K over
  its setpoint, reset at hand-back and at the end of a session (N5).

The user's answers of 2026-09-25 to the questions left by the review (its report and its areas'
notes in `research/2026-09-24-code-review/findings.md`):
- **Nothing is written to the boiler's persistent memory.** Control writes only to targets
  declared expiring or held; a setpoint target declared persistent or unknown keeps control off,
  with the reason shown, and a heating switch declared so is not used. The daily cap, its
  reserve, the cap reaction and the minimum change go (M0). Installations with only a persistent
  parameter get the monitor.
- **"Stopped" is not a hand-back** — the two are different things: with VT's zones stopped there
  is no demand, control goes on and keeps heating off, and frost protection still watches (N2).
- **A value never confirmed**, because the read-back shows another steady value from the start
  of the session (another controller still writing), counts as an outside change: one rewrite,
  then an alarm and no more writes (O2).
- **Some zones unknown:** the known zones decide, and a zone unknown for longer than a limit
  raises an alarm (N3).
- **The verdict's window** is an option; by default it covers every day with data, from daily
  summaries the plugin keeps (up to a year) and fills at start from the recorder as far back as
  it reaches (W1).
- **The monitoring period** stays as it is: calendar days from the first setup, lengthened only.
- **Degree-days** as the code has them — the hourly integral below the building's heating
  threshold — with hot-water gas left out where hot water is known (W1).
- **"Hot water available"** is unknown while the flow is unknown or stale (W5).
- **Home Assistant 2026.9.0** is the declared minimum, the version tested (R1).
- **The GitHub repository** does not exist yet: the manifest's `documentation`,
  `issue_tracker` and `codeowners` follow at K5 (R1).

## Provisional decision (the most cautious option; the user confirms it, L4 or K4)

- An outdoor sensor deviating from the weather entity (R6, A3): the curve takes the colder of
  the two, so a sensor right in a cold-air pool, or a weather entity for somewhere else, cannot
  leave the house cold; without a weather reading, the sensor only where the check saw it read
  colder, else the fallback; a stuck sensor is replaced as before. Was: a deviating sensor
  always gave way to the weather entity (N7).

- How "off" is sent (N6): through the heating switch where one is configured and declared
  expiring or held (built-in OTGW: `CH=0` with `CS` of at least 8 °C); without one, as a low
  setpoint. L3 finds out whether a low setpoint stops the CH pump on the usual masters; the user
  then decides whether control without a heating switch stays allowed (L4).

## Rules that shape this release

- Everything in the rules of `docs/plan-0.1.md` and `docs/plan-0.2.md` still applies.
- Every finding of the review has a step (index at the end); a finding a decision makes moot is
  marked so in its step.
- Tests first: a test that shows the finding fails, then the fix. The tests the review found
  entrenching defects (P58) change with the decisions.
- 🔒 marks steps that need the user's consent or action; ✅ marks a finished step.

## Phase L — specification and research

Why: the decisions have to be written into the specification before the code changes, and a few
questions need facts from the devices' own sources first.
In practice: `SCOPE.md`, `PLAN.md` and `CLAUDE.md` say what the plugin now does; the research
answers are kept in `research/`.

| Step | Work |
|---|---|
| L1 ✅ | `SCOPE.md`, `PLAN.md` and `CLAUDE.md` take the decisions and the provisional decisions above; each specification problem of the review (S01–S32) is settled in the text or assigned to a step (index); a table of the safety options' defaults with their reasons (S25); features without a step are assigned to a release or removed (S27); SCOPE's claim that rate limits and guard times are options is corrected (P85) |
| L2 ✅ | plan corrections (S26): outdated step texts in `docs/plan-0.2.md` (G1, H5, H6, I2); K2's ✅ withdrawn until the validation passes (R1); `vtherm-api>=0.5.0` in `docs/plan-0.1.md` D1; K5 states that HACS installs only from public repositories and that the HACS action checks the repository's description, topics and issues; K1's README states the minimum VT version; K5 and K7 name 0.2.1b1 and 0.2.1; the steps and acceptance scenarios the decisions change (G5, G9, H1, H2, H3, I2, J4) |
| L3 ✅ | research, sources downloaded into `research/diy/`: does a low "off" setpoint stop the CH pump on ESPHome, DIYLess and EMS-ESP masters (review question 1); the CH-mode bit with the flame on, flame and CH-active over the firmware's MQTT (question 2); flame flicker (question 3); VT finishing its setup after Home Assistant has started, and reloading its central entry (question 9); the PIC 6.6 answers recorded in the F3 note: CH=0 surviving CS=0 (P02), and a boiler's DATA-INVALID answer clearing the CS override; whether ESPHome, EMS-ESP and DIYLess devices restore the last written value after a reconnect or restart, or return to their own control (M1, M3); whether OTGW reports water pressure (ID 18) as 0 after a gateway reset (W6) |
| L4 🔒 ✅ | the user decides, after L3, whether control without a heating switch stays allowed, "off" then being a low setpoint (N6) — at any time, at the latest at K4. Decided 2026-09-27 (`docs/plan-0.2.2.md` decision 11): control without a heating switch stays blocked, and such installations get the monitor. Research looks at whether a low setpoint stops both the boiler and its pump; only the user lifts the block, at K4, even if that research is favourable (answer K of 2026-09-27). |

Done when: the specification states every decision, and the steps below have no open question
left but L4.

## Phase M — hand-back that holds (review §7.1)

Why: hand-back is the last line of safety — when anything goes wrong, the boiler must return to
its own control. The review found hand-backs that only looked done: to an entity that was
unavailable (Home Assistant drops such a call without an error), to an OTGW that keeps its
`CH=0` after `CS=0` (so the thermostat calls and the boiler does not heat), after a crash of Home
Assistant, or after an options change.
In practice: every hand-back is checked, remembered and retried until it is confirmed, and the
user sees when one is pending.

| Step | Work |
|---|---|
| M0 ✅ | nothing written to the boiler's persistent memory (the user's decision): a setpoint target declared persistent or unknown is a blocker, and a heating switch declared so is not used; the daily cap, its reserve, the cap reaction and the minimum change removed from the code, the options, the translations and the tests; the write-type description warns that a stored parameter declared expiring would be written every 30 s. Moot: the cap parts of P09, P51 and S07, review question 6 |
| M1 ✅ | entity path: every write and hand-back checks its target — missing, `unavailable` or `unknown` is a failure, since Home Assistant skips such an entity without an error (corrected at R5: `unknown` is written, as Home Assistant calls it); a value hand-back counts as done only once read back; the hand-back value is declared with its effect (P01, S08) |
| M2 ✅ | OTGW hand-back sends CH=1, then CS=0 — the PIC keeps a CH=0 through CS=0 — over the services and the firmware's MQTT, also after a restart; `TSet` stays a valid read-back, as the PIC sends it with CH=0 too (P02, S02) |
| M3 ✅ | a "controlling" marker stored at once, not after the 120 s save delay, and after an unclean restart handled like a pending hand-back when control does not resume; "a write since the last hand-back" set before each attempt (P04, P05, S07) |
| M4 ✅ | a pending hand-back outlives option changes: "No control", another write path or removing the entry is refused while it is pending, or a hand-back-only unit keeps retrying, with a repair issue; the retry is the one loop allowed after an exit (P06, S21) |
| M5 ✅ | Home Assistant's stop: the hand-back cancels a running step instead of waiting for it; SmartPI calls leave the step's critical section (P28, P89) |
| M6 ✅ | latches and resumption: a table "cause → how control resumes" (alarm hand-back, internal error, outside change, daily cap, blockers) in the specification and the code; an internal-error latch is cleared by any switch change; a restored latch shows its cause and never expires on its own; the guards' memory (rewrite window) survives a restart; review question 6 moot with the cap gone (M0); an option check tightened by an update does not stop a pending hand-back (P29, P35, P86, S22) |
| M7 ✅ | stand-alone gateway (the user's decision): a lost boiler link raises an alarm and control hands back — heating stops, as the options and the control switch say; "no write without fresh data" holds for every topology; a failed outdoor sensor still leads to the fallback setpoint, not to zero heat, so sensor failure and link loss are told apart (S06, S09) |

Done when: every hand-back path is tested against an unavailable target, a restart without a
clean stop, an option change while a hand-back is pending, and Home Assistant stopping during a
slow step.

## Phase N — VT decides, no hard blocks, bounded learning (review §7.2, §7.3)

Why: the user's decisions change what the plugin decides. The review also found that missing VT
data could mean no heat: a VT zone that is `unavailable`, or in "auto" mode, counted as "does not
want heat", and the comfort correction could climb 10 K and stay there.
In practice: heating follows VT at once, both ways; when VT's data is missing the plugin heats on
the curve rather than not at all; the correction stays within +3 K; frost protection remains the
only case where the plugin heats on its own.

| Step | Work |
|---|---|
| N1 ✅ | heating on/off follows the zones' demand at every step (10 s), both ways, at once; minimum burn, minimum pause, start budget, minimum on and off times and switching budget removed from the code, the options, the translations and the tests; the frequent-starts alarm stays information. Moot by the decisions: P08, P09, P20, P110, S01; the control part of P21; P58's tests rewritten |
| N2 ✅ | VT's modes: central modes through the zones' demand, zones outside the central mode counting (P15, S04); "Stopped" is not a hand-back: control goes on with no demand, frost protection still watching (the user); an unknown central mode is not Auto (P84); no summer switch of the plugin's own — summer and winter come from VT, and with VT off the plugin does not heat; the summer threshold goes, the monitor keeping the building's heating threshold for its degree-days (P100, S15); VT's central-boiler detection fails closed (P52); VT's load state follows its entries (P111); VT's setup after Home Assistant's start (review question 9, from L3) |
| N3 ✅ | demand from VT: a zone with an unknown or `unavailable` mode is unknown, and with no zone known the curve heats (P03); "auto" and heat_cool heat by `hvac_action` and `on_percent` (P12); the demand source per VT type, VT's minimum activation respected (P40, S31); zone freshness from the temperature's age (P91); `count_threshold` checked against the zones (P19); a criterion can stand alone, as in VT (review question 7); with some zones unknown the known ones decide, and a zone unknown for longer than a limit raises an alarm (the user) |
| N4 ✅ | frost protection stays as a safety net and watches every zone, or one zone the user picks (the user's decisions); implausible temperatures rejected; frost heating that goes on without the zone warming raises an alarm — it is not stopped (P14, S03) |
| N5 ✅ | bounded learning on the comfort correction: band +3 K, 1 K per 30 min only while heat flows, falling twice as fast, a zone without opening data not blocking the fall, no rise while another zone is more than 1 K over its setpoint, reset at hand-back and at the end of a session, information when it stays at the band's edge for hours; its interaction with the zones' PI integrators and with the outdoor terms of TPI and SmartPI described, with recommended VT settings (P13, P24, S13, S30, review question 8) |
| N6 ✅ | "off" (provisional, L4): through the heating switch where one is configured and declared expiring or held, else as a low setpoint; the options say what a low setpoint may leave running (the CH pump, as L3 finds) (S01, P51) |
| N7 ✅ | the curve's inputs: an outdoor sensor found stuck or deviating hands the curve to the weather entity or the fallback setpoint, with an alarm (P16, S05); the outdoor reading's age under the one freshness rule (P26, O1); fallback setpoint = the last effective outdoor temperature for a limited time, then the design point (P25, S16); the ramp in K per minute at every step, not one step per decision (P83) |
| N8 ✅ | limits and option dependencies: the weather ceiling never below `hard_min` (P27, S10); the "off" setpoint checked against `hard_min` and the entity (P51, S10); an opening threshold of 0 refused, a passive fixed circuit's maximum flow applied (P51); the emitter type without a default, or a warning (P60); what "one written circuit" means with several configured circuits (S32) |

Done when: in-process acceptance scenarios show VT's demand switching heating at once, both ways,
with no hold; a short-cycling old boiler never left without heat; the correction staying in its
band; and the right demand for `unavailable`, "auto" and over_climate zones.

## Phase O — freshness, read-back, units, guards (review §7.4)

Why: the plugin must tell real data and real writes from stale or lost ones. The review found no
way for the user to set a freshness limit, a gap in the "no fight" guard after an ignored write,
no use of the heating on/off echo where one exists, and °F entities receiving °C values.
In practice: one freshness rule the user can tighten; the setpoint shown is the one the boiler
confirmed; units are converted; the guard never fights another controller.

| Step | Work |
|---|---|
| O1 ✅ | one freshness rule for the monitor and control: availability, plus an age limit per signal the user may set in the options flow, with its risk described (P10, P26, P43, S11) |
| O2 ✅ | write guards: the rewrite timeout independent of an earlier "ignored" (P07); an outside change stops every write, heating on/off included, whatever the reaction (P53); `plan_setpoint` split, its retry-plus-change branch tested, failed attempts rate-limited (P82); a value never confirmed while the read-back shows another steady value from the start counts as an outside change (the user); a boiler's DATA-INVALID answer, which clears the OTGW's CS override, told apart from an outside change (L3) |
| O3 ✅ | read-back and state: heating on/off confirmed where an echo exists, under the one-rewrite rule (P22, S12); the setpoint entity shows the confirmed value or unknown, heating on/off marked unverified without an echo (P23); a read-back entity equal to the write entity refused or marked unverified (P75, S23); an OTGW read-back called "confirmed by the gateway" (S24); keep-alives do not move "last change" (P88) |
| O4 ✅ | units: °C and °F converted on write and in the range checks, or a blocker (P11); the setpoint rounded to the entity's step (P87); pressure and power units (P67) |
| O5 ✅ | clocks and logs: the decision interval applies to the water temperature only (S14); a failure logged once and its recovery once; exceptions logged with their trace, no blind `except` (P42, P106) |
| O6 ✅ | learning pauses: SmartPI's flag read back after a pause or resume (P41); learning the user switched off never resumed; a resume tolerance and a longest pause (S20); the Auto-TPI warning states its cost (S19) |

## Phase U — Home Assistant integration

Why: the plugin must not slow Home Assistant down or leave clutter behind. The review found
blocking work in the event loop, a large forecast store saved too often, lost feature-manager
values after a reload, raw codes in the interface and a few gaps in the options flow.
In practice: a lighter, tidier integration with clear texts; one entry per boiler.

| Step | Work |
|---|---|
| U1 ✅ | no blocking I/O or imports in the event loop; version detection once, off the loop; the entry reloads only for changes that need it (P30, P73) |
| U2 ✅ | forecast storage: only the current partition saved, off the loop, orphaned files removed; an unsupported forecast told without an exception's English text (P31, P96) |
| U3 ✅ | feature manager: a stable access point, registered again after VT recreates its API, its state visible when inactive; values also as properties for other plugins (P32, P92, P107) |
| U4 ✅ | recorder: changing attributes excluded (P33) |
| U5 ✅ | recorder backfill in the background, with named arguments, off the loop, tested (P34, P109) |
| U6 ✅ | a single config entry (P36, S18) |
| U7 ✅ | config and options flow: form errors instead of aborts; the simple level merges with the stored options; "restore defaults" keeps facts about the installation; an incomplete control configuration refused; MQTT topic and gateway ID validated; the write path checked against the topology; signal filters as in plan-0.1 D2 (P37, P38, P74, P79, P85, P99); a foreign-heat temperature sensor at the simple level gets its threshold field, or is not offered there |
| U8 ✅ | entity registry: a stable `unique_id`, clean-up after option changes (P39) |
| U9 ✅ | user-facing texts: translated states and reasons, every option with its risk, 0.1 descriptions updated, the `opening_threshold` wording, consistent naming, `icons.json`, `PARALLEL_UPDATES`, the emitter factor hidden by default (P50, P101, P104, P108) |
| U10 ✅ | storage and lifecycle: loading robust to corrupt data, no analysis in progress overwriting the store after a reload, restore not all-or-nothing, an entry migration, `async_remove_entry` (P66, P71, P72) |
| U11 ✅ | code hygiene: dead code and duplicated constants removed, the coupling between the control unit and the coordinator loosened, options defined once, VT states read only through `vtherm_link.py`, outdated docstrings (P68, P76, P78, P81) |
| U12 ✅ | diagnostics: non-personal data no longer redacted; the control section tested (P69) |

## Phase W — monitor

Why: the monitor's verdict ("is control worth it") could practically never appear — a few
seconds of unknown flame state reset it — and some numbers were skewed (hot water taken for
heating, gas-meter resets, starts per hour diluted over idle hours).
In practice: a verdict that appears after the monitoring period, and metrics that match what the
boiler did.

| Step | Work |
|---|---|
| W1 ✅ | verdict: reachable despite short data gaps; its window an option, by default every day with data, from daily summaries the plugin keeps (up to a year) and fills at start from the recorder as far back as it reaches — the recorder keeps 10 days by default; starts per hour counted over hours of heating; degree-days as the code has them, hot-water gas left out where hot water is known (the user) (P17, P49, S17, review questions 4 and 5) |
| W2 ✅ | burns: a heating overshoot not taken for hot water; the declared DHW type used; ignition alarms exclude hot water; a burn of unknown kind counted apart; flame flicker merged if L3 finds it (it found none, and merging could hide real short cycles: not merged); the `shared_return` flag used or removed (the monitor part of P21, P47, review questions 2 and 3) |
| W3 ✅ | building model: consistent windows, a clamped result, a reachable confidence; the declared-versus-measured mismatch shown (P44, P77) |
| W4 ✅ | metrics: gas meter resets only on a large drop; the switch to the weather entity with an unavailable outdoor sensor; gas per degree-day with incomplete data; the report's `complete` flag; days of 23 and 25 hours; unknown zones; the gas unit followed; the importer's mapping, command line and DST tested, its usage text and test without the author's time zone (P45, P46, P63, P70, P103) |
| W5 ✅ | zones: no emitter factor during hot water or from the boiler's return on mixed circuits; the critical zone as its docstring says; EN 442 continuous near room temperature; the reference room's average from one set of zones; hot water available unknown while the flow is unknown or stale (the user) (P48, P61, P62, S29, review question 10) |
| W6 ✅ | alarms: hysteresis kept with unknown values and between levels; the low-flow warning with exclusions (pump overrun, hot water, bypass) and its unavailability reason; a water pressure of 0 after a gateway reset counted as unknown, if L3 confirms it (P64, P65, S28) |

## Phase R — release validation, tools, test environment, review

Why: Home Assistant's and HACS's checks fail today (a text with `<…>`, missing manifest fields),
the test HA's simulator could not load its physics, and restart and the passage of time are
hardly tested. An independent review closes the release.
In practice: a release that validates, a test HA that runs, and tests for what happens over days
and across restarts.

| Step | Work |
|---|---|
| R1 ✅ | release validation: translation texts without `<…>`; manifest `after_dependencies`, `vtherm_api>=0.5.0`, version 0.2.1 — `documentation`, `issue_tracker` and `codeowners` follow at K5, as the repository does not exist yet (the user); `hacs.json` with `homeassistant: 2026.9.0`, the version tested (the user); the brands check no longer ignored; a pytest check of the hassfest rules (P18, P54, P90, P93, P94, P98). Until K5 and R2, hassfest still misses `documentation` and the HACS action the brand and the repository; `tests/test_release.py` expects the K5 keys to be missing and fails once they are there, so its mark is removed then |
| R2 🔒 | the icon for the integration's `brand/` folder: the user provides or approves it (P93) |
| R3 ✅ | tools: `ruff format`; mypy from PyPI into `.venv`, strict where practical; CI with coverage, formatting, mypy and Home Assistant's constraints, on the declared minimum version; `.gitignore` for coverage and mypy caches (P80, P95, P97, P105). mypy 2.3.1 (Home Assistant's pin) is strict on the whole component; coverage 97 %, with a floor of 95 %; the tests and mypy also pass on Home Assistant 2026.9.0, tried in `.venv` and put back to 2026.9.3 |
| R4 ✅ | test environment: the simulator carries its physics inside the component (Home Assistant keeps `/config` on the import path only while it loads `custom_components`); the deploy copies files, not symlinks; its dry run connects nowhere — before J2 (P55). `plant.py` and `profiles.py` moved into `boiler_sim`; the deploy packs one tar stream with links followed and unpacks it over SSH, without rsync; tests check the component's imports and a dry run that must not call `ssh` |
| R5 ✅ | tests: the high-priority tests of review §6; a restart with stored state; the passage of time (the cap freeing up after 24 h, latches kept); real VT thermostats from `vendor/` in-process; the closed-loop harness asserting on `loop_step`'s commands; vacuous tests fixed (P56, P57, P58, P59, P102, P103). The §6 list checked test by test: the start and switch budgets, the minimum pause, the daily cap and its reaction went with M0 and N1, so the cap freeing up after 24 h is moot — a day and more of control steps instead (the one rewrite a day, a latch that never lapses). Added: in-process acceptance scenarios for every J4 case, restarts with stored state, VT 10.4.0 thermostats in-process, Home Assistant's own recorder, Home Assistant in °F. Fixed on the way: a write target whose state is unknown is written (M1 took it for one Home Assistant skips; only an unavailable one is); the feature manager registers with an API VT recreated before the rebuilt thermostat starts; the healthy-boiler analysis passed its pressure trend without judging it |
| R6 ✅ | an independent read-only review of 0.2.1, as on 2026-09-24. Done 2026-09-25 by four reviewers — control and hand-back, the Home Assistant integration, the monitor, tests and release — rather than the full multi-agent review of 2026-09-24, which needs the user's go-ahead. Found 1 critical, 7 high (T1 repeats C1), 22 medium, 22 low. Fixed, each with a test: every critical and high one (H1, H2, C1/T1, T2, A1, A2, A3 — provisional, A4) and C2, C3, C4, C7/H3, C9, C11, H4, H5, H7, H8, H10, H11, A5–A10, A14, T4, T6–T10, T12 and the texts (C5, C8, C12, C13, H12). An independent check of the fixes (2026-09-26) confirmed them but one high — A2's fix read the duty cycle, which a TPI or SmartPI switch zone keeps through its cycle — and found three new medium problems: the gateway's read-back could be re-picked with a hand-back owed, and no guard held while the entry was not running; A3 took a warm deviating sensor with the weather entity unavailable; T2 dropped the alarm for a dead room sensor. Fixed, each with a test, with three lows: a repair confirmed late cleared a controlling session's hold (C7); an opentherm_gw read-back left without a value by pyotgw's reset now means no connection for a hand-back (C1); removing VT's central boiler asks for a restart (H1). What is left: "Open after R6" |

## Open after R6 (the user decides, at K4 at the latest)

1. The drop rule (a2, C6): a value that keeps falling back to the one before the session is sent
   again for good; behind an OpenTherm thermostat a rejected `CS` falls back to the thermostat's
   modulating value and can read as another controller — a false outside change and a latched
   hand-back. Escalating repeated drops, or comparing with the thermostat's setpoint, changes a
   decided rule.
2. The simulator before J4 (T3, T5): its OTGW read-back shows the boiler's working setpoint, where
   `opentherm_gw` shows the gateway's acknowledgement at once, so a boiler refusing ID 1 reads
   "confirmed, then dropped" in a real installation; its heating switch shares the setpoint's
   write type and renews the setpoint's override, which EMS-ESP never does.
3. An edit outside control that blocks it (H6) — the boiler class, a second circuit, fewer zones
   than the count threshold, underfloor without a maximum flow — is saved and hands back at once;
   with a stand-alone gateway heating then stops. A confirmation step or a warning in those forms.
4. A non-condensing boiler: control's hard minimum is 25 °C for every boiler, and a low return
   makes a non-condensing boiler condense in its flue; a higher minimum for such a boiler needs
   the user's value.
5. The pressure trend is judged on cold water only, which cold days lack: a slow leak in winter
   shows at the absolute low-pressure alarm only.
6. Smaller ones: options saved while the entry is in setup error do not reload it (H9); Home
   Assistant's downtime counts as known data (A11); the verdict mixes days under control with
   the baseline (A12); the importer grows quadratically with the days (A13); an internal-error
   block does not survive a restart (C10); an owed hand-back waits for the monitor's first
   refresh at setup (C14); a SmartPI resume that did not take is left behind when control
   leaves the options (C15); tests set up two entries of a single-entry integration (T11).
7. The provisional decision on a deviating outdoor sensor (A3), above.
8. From the check of the fixes, low: an unload with a target that echoes later (ESPHome, MQTT)
   stores the hand-back as owed and raises the persistent issue, which stays while the entry is
   disabled — a short wait for the echo at stop would settle it; a pyotgw command that times
   out while the gateway is connected lets a hand-back count; over MQTT a gateway that drops
   without warning shows unavailable only after the broker's keep-alive, and a broken link
   between the ESP and the PIC never does; the owed hand-back's retry, the stale-link hand-back
   and the decision interval still sit out a wall clock set back (C9).

## After 0.2.1

The open steps of `docs/plan-0.2.md` follow: J2 🔒, J4 🔒, K1 🔒, K4 🔒 (the review, with L4 if
still open), K5 🔒 (public repository, pre-release 0.2.1b1), K6 🔒, K7 🔒 (release 0.2.1).

## Done for 0.2.1

- Every finding of `docs/review-2026-09-24.md` fixed, or moot by a recorded decision (index).
- All tests, `ruff check` and `ruff format --check` pass; mypy runs in CI.
- The in-process acceptance scenarios pass, the new ones included.
- The independent review (R6) finds no critical or high problem.

## Index: review finding → step

Problems: P01 M1 · P02 M2, L3 · P03 N3 · P04 M3 · P05 M3 · P06 M4 · P07 O2 · P08 N1 · P09 N1, M0 ·
P10 O1 · P11 O4 · P12 N3 · P13 N5 · P14 N4 · P15 N2 · P16 N7 · P17 W1 · P18 R1 · P19 N3 ·
P20 N1 · P21 N1, W2 · P22 O3 · P23 O3 · P24 N5 · P25 N7 · P26 N7, O1 · P27 N8 · P28 M5 · P29 M6 ·
P30 U1 · P31 U2 · P32 U3 · P33 U4 · P34 U5 · P35 M6 · P36 U6 · P37 U7 · P38 U7 · P39 U8 · P40 N3 ·
P41 O6 · P42 O5 · P43 O1 · P44 W3 · P45 W4 · P46 W4 · P47 W2 · P48 W5 · P49 W1 · P50 U9 ·
P51 M0, N6, N8 · P52 N2 · P53 O2 · P54 R1 · P55 R4 · P56 R5 · P57 R5 · P58 N1, R5 · P59 R5 · P60 N8 ·
P61 W5 · P62 W5 · P63 W4 · P64 W6 · P65 W6 · P66 U10 · P67 O4 · P68 U11 · P69 U12 · P70 W4 ·
P71 U10 · P72 U10 · P73 U1 · P74 U7 · P75 O3 · P76 U11 · P77 W3 · P78 U11 · P79 U7 · P80 R3 ·
P81 U11 · P82 O2 · P83 N7 · P84 N2 · P85 L1, U7 · P86 M6 · P87 O4 · P88 O3 · P89 M5 · P90 R1 ·
P91 N3 · P92 U3 · P93 R1, R2 · P94 R1 · P95 R3 · P96 U2 · P97 R3 · P98 R1 · P99 U7 · P100 N2 ·
P101 U9 · P102 R5 · P103 W4, R5 · P104 U9 · P105 R3 · P106 O5 · P107 U3 · P108 U9 · P109 U5 ·
P110 N1 · P111 N2

Specification: S01 N1, N6 · S02 M2 · S03 N4 · S04 N2 · S05 N7 · S06 M7 · S07 M3, M0 · S08 M1 ·
S09 M7 · S10 N8 · S11 O1 · S12 O3 · S13 N5 · S14 O5 · S15 N2 · S16 N7 · S17 W1 · S18 U6 · S19 O6 ·
S20 O6 · S21 M4 · S22 M6 · S23 O3 · S24 O3 · S25 L1 · S26 L2 · S27 L1 · S28 W6 · S29 W5 · S30 N5 ·
S31 N3 · S32 N8

Open questions of the review: 1, 2, 3 and 9 → L3 (then N6, W2, N2) · 4 and 5 → W1 · 6 moot
(M0) · 7 → N3 · 8 → N5 · 10 → W5. Missing tests of review §6 → R5 and each step's own tests.
