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

## Decisions of 2026-09-25 (the user)

- **VT decides whether to heat.** The plugin replaces VT's central boiler: heating on/off follows
  the zones' demand at once, in both directions, at every control step. The plugin decides only
  the water temperature — the curve, the limits and the ramp.
- **No hard blocking of the boiler.** No counter or timer holds heating off, or on, against VT:
  minimum burn, minimum pause, the budget of starts, minimum on and off times and the switching
  budget go. Old boilers with a high minimum output cycle a lot on their own; blocking would leave
  the house cold. Frequent starts are information: an alarm with its threshold, and the verdict.
  Technical safeguards stay because they do not decide whether to heat: the hard limits of the
  water temperature, a write-rate guard against a runaway loop (a repeated write waits at most one
  step) and hand-back on every exit.
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
  decided per write target (N6). The form of that rule the user leaves open for now.
- **Stand-alone gateway: alarm and off.** A lost boiler link raises an alarm and control hands
  back, so heating stops; "no write without fresh data" holds for every topology (M7).
- **The comfort correction** under bounded learning: at most +3 K, rising slowly (1 K per 30 min,
  only while heat flows), falling twice as fast, no rise while another zone is more than 1 K over
  its setpoint, reset at hand-back and at the end of a session (N5).

## Provisional decision (the most cautious option; the user confirms it, L4 or K4)

- The per-target rule for "off" (N6): the setpoint entity and the heating switch each declare
  their own write type; "off" goes through a target freely when its type is expiring or held,
  and within the daily cap, with the reserve kept for heat, when it is persistent; an unknown
  type counts as persistent; the options state how many on/off cycles fit in the cap. L3's
  research on the devices informs the user's decision.

## Rules that shape this release

- Everything in the rules of `docs/plan-0.1.md` and `docs/plan-0.2.md` still applies.
- Every finding of the review has a step (index at the end); a finding a decision makes moot is
  marked so in its step.
- Tests first: a test that shows the finding fails, then the fix. The tests the review found
  entrenching defects (P58) change with the decisions.
- 🔒 marks steps that need the user's consent or action; ✅ marks a finished step.

## Phase L — specification and research

| Step | Work |
|---|---|
| L1 | `SCOPE.md`, `PLAN.md` and `CLAUDE.md` take the decisions and the provisional decisions above; each specification problem of the review (S01–S32) is settled in the text or assigned to a step (index); a table of the safety options' defaults with their reasons (S25); features without a step are assigned to a release or removed (S27); SCOPE's claim that rate limits and guard times are options is corrected (P85) |
| L2 | plan corrections (S26): outdated step texts in `docs/plan-0.2.md` (G1, H5, H6, I2); K2's ✅ withdrawn until the validation passes (R1); `vtherm-api>=0.5.0` in `docs/plan-0.1.md` D1; K5 states that HACS installs only from public repositories |
| L3 | research, sources downloaded into `research/diy/`: does a low "off" setpoint stop the CH pump on ESPHome, DIYLess and EMS-ESP masters (review question 1); the CH-mode bit with the flame on, flame and CH-active over the firmware's MQTT (question 2); flame flicker (question 3); VT finishing its setup after Home Assistant has started, and reloading its central entry (question 9); the PIC 6.6 answer on CH=0 recorded in the F3 note (P02) |
| L4 🔒 | the user confirms or changes the provisional rule for "off" (N6), after L3 — at any time, at the latest at K4 |

Done when: the specification states every decision, and the steps below have no open question
left but L4.

## Phase M — hand-back that holds (review §7.1)

| Step | Work |
|---|---|
| M1 | entity path: every write and hand-back checks its target — missing, `unavailable` or `unknown` is a failure, since Home Assistant skips such an entity without an error; a value hand-back counts as done only once read back; the hand-back value is declared with its effect (P01, S08) |
| M2 | OTGW hand-back sends CH=1, then CS=0 — the PIC keeps a CH=0 through CS=0 — over the services and the firmware's MQTT, also after a restart; `TSet` stays a valid read-back, as the PIC sends it with CH=0 too (P02, S02) |
| M3 | a "controlling" marker stored at once, not after the 120 s save delay, and after an unclean restart handled like a pending hand-back when control does not resume; "a write since the last hand-back" set before each attempt (P04, P05, S07) |
| M4 | a pending hand-back outlives option changes: "No control", another write path or removing the entry is refused while it is pending, or a hand-back-only unit keeps retrying, with a repair issue; the retry is the one loop allowed after an exit (P06, S21) |
| M5 | Home Assistant's stop: the hand-back cancels a running step instead of waiting for it; SmartPI calls leave the step's critical section (P28, P89) |
| M6 | latches and resumption: a table "cause → how control resumes" (alarm hand-back, internal error, outside change, daily cap, blockers) in the specification and the code; an internal-error latch is cleared by any switch change; a restored latch shows its cause and never expires on its own; the guards' memory (rewrite window, cap history) survives a restart; whether a cap hand-back latches (review question 6) (P29, P35, P86, S22) |
| M7 | stand-alone gateway (the user's decision): a lost boiler link raises an alarm and control hands back — heating stops, as the options and the control switch say; "no write without fresh data" holds for every topology; a failed outdoor sensor still leads to the fallback setpoint, not to zero heat, so sensor failure and link loss are told apart (S06, S09) |

Done when: every hand-back path is tested against an unavailable target, a restart without a
clean stop, an option change while a hand-back is pending, and Home Assistant stopping during a
slow step.

## Phase N — VT decides, no hard blocks, bounded learning (review §7.2, §7.3)

| Step | Work |
|---|---|
| N1 | heating on/off follows the zones' demand at every step (10 s), both ways, at once; minimum burn, minimum pause, start budget, minimum on and off times and switching budget removed from the code, the options, the translations and the tests; the frequent-starts alarm stays information. Moot by the decisions: P08, P09, P20, P110, S01; the control part of P21; P58's tests rewritten |
| N2 | VT's modes: central modes through the zones' demand, zones outside the central mode counting (P15, S04); an unknown central mode is not Auto (P84); no summer switch of the plugin's own — summer and winter come from VT, and with VT off the plugin does not heat; the threshold kept for the monitor (P100, S15); VT's central-boiler detection fails closed (P52); VT's load state follows its entries (P111); VT's setup after Home Assistant's start (review question 9, from L3) |
| N3 | demand from VT: a zone with an unknown or `unavailable` mode is unknown, and with no zone known the curve heats (P03); "auto" and heat_cool heat by `hvac_action` and `on_percent` (P12); the demand source per VT type, VT's minimum activation respected (P40, S31); zone freshness from the temperature's age (P91); `count_threshold` checked against the zones (P19); a criterion can stand alone, as in VT (review question 7) |
| N4 | frost protection stays as a safety net and watches every zone, or one zone the user picks (the user's decisions); implausible temperatures rejected; frost heating that goes on without the zone warming raises an alarm — it is not stopped (P14, S03) |
| N5 | bounded learning on the comfort correction: band +3 K, 1 K per 30 min only while heat flows, falling twice as fast, a zone without opening data not blocking the fall, no rise while another zone is more than 1 K over its setpoint, reset at hand-back and at the end of a session, information when it stays at the band's edge for hours; its interaction with the zones' PI integrators and with the outdoor terms of TPI and SmartPI described, with recommended VT settings (P13, P24, S13, S30, review question 8) |
| N6 | "off" per write target (the user: it depends on what is written and where; the rule below is provisional): the setpoint entity and the heating switch each declare their own write type; "off" goes through a target only as its type allows — freely when expiring or held, within the daily cap with the reserve kept for heat when persistent, unknown counting as persistent; the options state how many on/off cycles fit in the cap; a daily cap of 3 or less no longer silently drops "off" (S01, S07, P09, P51) |
| N7 | the curve's inputs: an outdoor sensor found stuck or deviating hands the curve to the weather entity or the fallback setpoint, with an alarm (P16, S05); the outdoor reading's age under the one freshness rule (P26, O1); fallback setpoint = the last effective outdoor temperature for a limited time, then the design point (P25, S16); the ramp in K per minute at every step, not one step per decision (P83) |
| N8 | limits and option dependencies: the weather ceiling never below `hard_min` (P27, S10); the "off" setpoint checked against `hard_min` and the entity (P51, S10); an opening threshold of 0 refused, a passive fixed circuit's maximum flow applied (P51); the emitter type without a default, or a warning (P60); what "one written circuit" means with several configured circuits (S32) |

Done when: in-process acceptance scenarios show VT's demand switching heating at once, both ways,
with no hold; a short-cycling old boiler never left without heat; the correction staying in its
band; and the right demand for `unavailable`, "auto" and over_climate zones.

## Phase O — freshness, read-back, units, guards (review §7.4)

| Step | Work |
|---|---|
| O1 | one freshness rule for the monitor and control: availability, plus an age limit per signal the user may set in the options flow, with its risk described (P10, P26, P43, S11) |
| O2 | write guards: the rewrite timeout independent of an earlier "ignored" (P07); an outside change stops every write, heating on/off included, whatever the reaction (P53); `plan_setpoint` split, its retry-plus-change branch tested, failed attempts rate-limited (P82) |
| O3 | read-back and state: heating on/off confirmed where an echo exists, under the one-rewrite rule (P22, S12); the setpoint entity shows the confirmed value or unknown, heating on/off marked unverified without an echo (P23); a read-back entity equal to the write entity refused or marked unverified (P75, S23); an OTGW read-back called "confirmed by the gateway" (S24); keep-alives do not move "last change" (P88) |
| O4 | units: °C and °F converted on write and in the range checks, or a blocker (P11); the setpoint rounded to the entity's step (P87); pressure and power units (P67) |
| O5 | clocks and logs: the decision interval applies to the water temperature only (S14); a failure logged once and its recovery once; exceptions logged with their trace, no blind `except` (P42, P106) |
| O6 | learning pauses: SmartPI's flag read back after a pause or resume (P41); learning the user switched off never resumed; a resume tolerance and a longest pause (S20); the Auto-TPI warning states its cost (S19) |

## Phase U — Home Assistant integration

| Step | Work |
|---|---|
| U1 | no blocking I/O or imports in the event loop; version detection once, off the loop; the entry reloads only for changes that need it (P30, P73) |
| U2 | forecast storage: only the current partition saved, off the loop, orphaned files removed; an unsupported forecast told without an exception's English text (P31, P96) |
| U3 | feature manager: a stable access point, registered again after VT recreates its API, its state visible when inactive; values also as properties for other plugins (P32, P92, P107) |
| U4 | recorder: changing attributes excluded (P33) |
| U5 | recorder backfill in the background, with named arguments, off the loop, tested (P34, P109) |
| U6 | a single config entry (P36, S18) |
| U7 | config and options flow: form errors instead of aborts; the simple level merges with the stored options; "restore defaults" keeps facts about the installation; an incomplete control configuration refused; MQTT topic and gateway ID validated; the write path checked against the topology; signal filters as in plan-0.1 D2 (P37, P38, P74, P79, P85, P99) |
| U8 | entity registry: a stable `unique_id`, clean-up after option changes (P39) |
| U9 | user-facing texts: translated states and reasons, every option with its risk, 0.1 descriptions updated, the `opening_threshold` wording, consistent naming, `icons.json`, `PARALLEL_UPDATES`, the emitter factor hidden by default (P50, P101, P104, P108) |
| U10 | storage and lifecycle: loading robust to corrupt data, no analysis in progress overwriting the store after a reload, restore not all-or-nothing, an entry migration, `async_remove_entry` (P66, P71, P72) |
| U11 | code hygiene: dead code and duplicated constants removed, the coupling between the control unit and the coordinator loosened, options defined once, VT states read only through `vtherm_link.py`, outdated docstrings (P68, P76, P78, P81) |
| U12 | diagnostics: non-personal data no longer redacted; the control section tested (P69) |

## Phase W — monitor

| Step | Work |
|---|---|
| W1 | verdict: reachable despite short data gaps, its window equal to `monitoring_days`, starts per hour counted over hours of heating, the degree-day definition in the specification (P17, P49, S17, review questions 4 and 5) |
| W2 | burns: a heating overshoot not taken for hot water; the declared DHW type used; ignition alarms exclude hot water; a burn of unknown kind counted apart; flame flicker merged if L3 finds it (the monitor part of P21, P47, review questions 2 and 3) |
| W3 | building model: consistent windows, a clamped result, a reachable confidence; the declared-versus-measured mismatch shown (P44, P77) |
| W4 | metrics: gas meter resets only on a large drop; the switch to the weather entity with an unavailable outdoor sensor; gas per degree-day with incomplete data; the report's `complete` flag; days of 23 and 25 hours; unknown zones; the gas unit followed; the importer's mapping, command line and DST tested (P45, P46, P63, P70, P103) |
| W5 | zones: no emitter factor during hot water or from the boiler's return on mixed circuits; the critical zone as its docstring says; EN 442 continuous near room temperature; the reference room's average from one set of zones; hot water available with an unknown flow (P48, P61, P62, S29, review question 10) |
| W6 | alarms: hysteresis kept with unknown values and between levels; the low-flow warning with exclusions (pump overrun, hot water, bypass) and its unavailability reason (P64, P65, S28) |

## Phase R — release validation, tools, test environment, review

| Step | Work |
|---|---|
| R1 | release validation: translation texts without `<…>`; manifest `documentation`, `issue_tracker`, `codeowners`, `after_dependencies`, `vtherm_api>=0.5.0`, version 0.2.1; `hacs.json` with `homeassistant: 2026.3.0` (the code needs Python 3.14); the brands check no longer ignored; a pytest check of the hassfest rules (P18, P54, P90, P93, P94, P98) |
| R2 🔒 | the icon for the integration's `brand/` folder: the user provides or approves it (P93) |
| R3 | tools: `ruff format`; mypy from PyPI into `.venv`, strict where practical; CI with coverage, formatting, mypy and Home Assistant's constraints; `.gitignore` for coverage and mypy caches (P80, P95, P97, P105) |
| R4 | test environment: the simulator carries its physics inside the component (Home Assistant keeps `/config` on the import path only while it loads `custom_components`); the deploy copies files, not symlinks; its dry run connects nowhere — before J2 (P55) |
| R5 | tests: the high-priority tests of review §6; a restart with stored state; the passage of time (the cap freeing up after 24 h, latches kept); real VT thermostats from `vendor/` in-process; the closed-loop harness asserting on `loop_step`'s commands; vacuous tests fixed (P56, P57, P58, P59, P102, P103) |
| R6 | an independent read-only review of 0.2.1, as on 2026-09-24 |

## After 0.2.1

The open steps of `docs/plan-0.2.md` follow: J2 🔒, J4 🔒, K1 🔒, K4 🔒 (the review, with L4 if
still open), K5 🔒 (public repository, pre-release 0.2.1b1), K6 🔒, K7 🔒 (release 0.2.1).

## Done for 0.2.1

- Every finding of `docs/review-2026-09-24.md` fixed, or moot by a recorded decision (index).
- All tests, `ruff check` and `ruff format --check` pass; mypy runs in CI.
- The in-process acceptance scenarios pass, the new ones included.
- The independent review (R6) finds no critical or high problem.

## Index: review finding → step

Problems: P01 M1 · P02 M2, L3 · P03 N3 · P04 M3 · P05 M3 · P06 M4 · P07 O2 · P08 N1 · P09 N1, N6 ·
P10 O1 · P11 O4 · P12 N3 · P13 N5 · P14 N4 · P15 N2 · P16 N7 · P17 W1 · P18 R1 · P19 N3 ·
P20 N1 · P21 N1, W2 · P22 O3 · P23 O3 · P24 N5 · P25 N7 · P26 N7, O1 · P27 N8 · P28 M5 · P29 M6 ·
P30 U1 · P31 U2 · P32 U3 · P33 U4 · P34 U5 · P35 M6 · P36 U6 · P37 U7 · P38 U7 · P39 U8 · P40 N3 ·
P41 O6 · P42 O5 · P43 O1 · P44 W3 · P45 W4 · P46 W4 · P47 W2 · P48 W5 · P49 W1 · P50 U9 ·
P51 N6, N8 · P52 N2 · P53 O2 · P54 R1 · P55 R4 · P56 R5 · P57 R5 · P58 N1, R5 · P59 R5 · P60 N8 ·
P61 W5 · P62 W5 · P63 W4 · P64 W6 · P65 W6 · P66 U10 · P67 O4 · P68 U11 · P69 U12 · P70 W4 ·
P71 U10 · P72 U10 · P73 U1 · P74 U7 · P75 O3 · P76 U11 · P77 W3 · P78 U11 · P79 U7 · P80 R3 ·
P81 U11 · P82 O2 · P83 N7 · P84 N2 · P85 L1, U7 · P86 M6 · P87 O4 · P88 O3 · P89 M5 · P90 R1 ·
P91 N3 · P92 U3 · P93 R1, R2 · P94 R1 · P95 R3 · P96 U2 · P97 R3 · P98 R1 · P99 U7 · P100 N2 ·
P101 U9 · P102 R5 · P103 W4, R5 · P104 U9 · P105 R3 · P106 O5 · P107 U3 · P108 U9 · P109 U5 ·
P110 N1 · P111 N2

Specification: S01 N1, N6 · S02 M2 · S03 N4 · S04 N2 · S05 N7 · S06 M7 · S07 M3, N6 · S08 M1 ·
S09 M7 · S10 N8 · S11 O1 · S12 O3 · S13 N5 · S14 O5 · S15 N2 · S16 N7 · S17 W1 · S18 U6 · S19 O6 ·
S20 O6 · S21 M4 · S22 M6 · S23 O3 · S24 O3 · S25 L1 · S26 L2 · S27 L1 · S28 W6 · S29 W5 · S30 N5 ·
S31 N3 · S32 N8

Open questions of the review: 1, 2, 3 and 9 → L3 (then N6, W2, N2) · 4 and 5 → W1 · 6 → M6 ·
7 → N3 · 8 → N5 · 10 → W5. Missing tests of review §6 → R5 and each step's own tests.
