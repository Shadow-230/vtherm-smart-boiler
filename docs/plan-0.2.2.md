# Plan 0.2.2 — Corrections after the review of 2026-09-26

Goal: close every problem of the independent review of 0.2.1 (`docs/review-2026-09-26.md`) before
anything reaches the test HA. Each one is fixed, made moot by a recorded decision, or named for a
later release, and the lessons of the comparison with the 0.2 audit
(`docs/review-2026-09-26-vs-0.2.md`, §7) are applied. The review found no critical problem and five
high ones: a corrupt store makes the plugin forget that it holds the boiler; the control switch goes
unavailable when the monitor fails; one entity can be both heating switch and hand-back switch; the
OTGW "off" masks an on/off thermostat after a crash; and the water's lower bound ignores the boiler's
minimum power. The steps of `docs/plan-0.2.md` still open (J2, J4, K1–K7) follow on 0.2.2: it becomes
the first version to reach the test HA and to be published (pre-release 0.2.2b1, then 0.2.2 — the
user confirms at K5, decision 16 below).
Scope: `SCOPE.md`; overview: `PLAN.md`; the previous corrections: `docs/plan-0.2.1.md`. Written on
2026-09-26 from the review and the comparison.

Phases run in order: Q, V, X, Y, Z. Q4 waits for the user and does not hold up the build: until the
user decides, each step follows the provisional option given below. Q1 and Q2 change documents,
whose diffs wait for the user's consent; phase V may start meanwhile.

## In short

- **The plugin never forgets that it holds the boiler** — not after a corrupt file, a failed start
  or a crash between two saves (phase V).
- **The off switch works when something else is broken** (phase V).
- **A hand-back counts only when something other than the plugin's own write confirms it**
  (phase V).
- **Dangerous settings are refused in the form**, not found at the boiler (phase X).
- **The guards and the boiler-link watch keep their memory for the whole session** (phase X).
- **A few safety gaps in the specification are the user's to decide**; until then the most cautious
  option applies (phase Q).
- **The monitor says "unknown" when it cannot judge**, and its numbers stop drifting (phase Y).
- **The missing safety tests, coverage per module and a simulator ready for J4** (phase Z).

## How to read this plan

- Steps are named by phase letter and number: Q1, V2, X5… The letters skip P, S and T, which the
  review uses. The review's names are kept: P-01–P-128 are problems in the code and the tests,
  S-01–S-62 problems in the specification, T-01–T-55 its missing tests (§6), "review question 1–20"
  its Appendix E. "Open after R6 #1–8" are the items left at the end of `docs/plan-0.2.1.md`. The
  index at the end gives the step for every one of them.
- A step names the problems it must close; the review's row, its §6 test and section 4's proposal
  say what "closed" means.
- 🔒 marks a step that needs the user's consent or action; ✅ marks a finished step.
- "Decision n" refers to the list below; its provisional option applies until the user decides.

## Terms

The terms of `docs/plan-0.2.1.md` hold (hand-back, write path, write type, read-back, outside change,
latch, blocker, topology, demand, comfort correction, bounded learning, frost protection, freshness,
`CS` / `CH`). New here:

- **Control state** — what the plugin must remember across restarts to hand back safely: the
  "controlling" marker, an owed hand-back and the options it was taken with, the latches, the
  user's on/off wish, a SmartPI zone it paused.
- **Unhappy path** — a start with a corrupt or missing store, a setup that fails, a crash between
  two saves, a monitor that keeps failing.
- **Thermostat kind** — with a gateway between thermostat and boiler: an OpenTherm thermostat, or
  an on/off contact on the gateway's thermostat terminals.
- **Grace period** — a short time after the zones become unknown (e.g. while VT reloads) during
  which the last known demand holds.
- **Lowest flow for the boiler** — the lowest water temperature at which the boiler, at its minimum
  power, burns without short cycling; it depends on the boiler and the emitters.
- **Provisional option** — the most cautious answer to an open decision, applied until the user
  decides.

## Decisions for the user (Q4 🔒), with the provisional option

Each provisional option is the most cautious one found. It is written into `SCOPE.md` as provisional
(Q1) and built so that the user's answer changes one place in the code.

1. **OTGW with an on/off thermostat** (S-01, review question 4). The PIC keeps `CH=0` through `CS=0`
   and the override's lapse, so after a crash while "off" an on/off thermostat on the gateway cannot
   heat the house. *Provisional:* the topology "gateway with a thermostat" asks for the thermostat's
   kind; with an on/off thermostat, or when the user does not know, control is blocked with that
   reason, and the monitor works as before. *Alternative:* "off" as a low `CS` with `CH` left alone
   for such a thermostat — this depends on L4's answer (the pump may keep running).
2. **The water's lowest temperature and the boiler** (S-02, Open after R6 #4). The hard minimum
   (25 °C) protects the emitters only; in mild weather the curve lands where many boilers
   short-cycle, and a non-condensing boiler condenses in its flue at a low return. *Provisional:* an
   option "lowest flow for the boiler", by default equal to the hard minimum — nothing changes until
   the user sets it — with a risk text for both sides (too low: short burns in mild weather, flue
   condensation in a non-condensing boiler; too high: warmer water than the rooms need). *Open:* a
   default by boiler type, or one estimated from the boiler's minimum power and the design load
   (Q3 looks for a generic rule).
3. **No zone known** (S-03, review question 1). "No zone known → heat on the curve" has no grace
   period, no season and no time limit, and applies with VT not loaded at all. *Provisional:* a grace
   period with the last known demand (proposed: 10 min), so a VT reload neither starts nor stops the
   boiler; after it, heating on the curve as now; `zone_unknown` rises at once when no VT entry is
   loaded. *Open:* no heating above the building's heating threshold; a hand-back after a time limit.
4. **Frost protection behind closed valves** (S-05). A zone VT switched off keeps its valve closed,
   so heat for it cannot arrive. *Provisional:* frost protection keeps watching every zone, as the
   house comes first; when frost heating runs and no watched zone can take heat (no opening, no
   active device), `frost_not_warming` rises at once; the texts say frost protection needs an
   emitter that can open, and recommend VT's frost preset over "off". *Open:* watch only zones that
   can take heat.
5. **VT's activation delay** (S-07). VT's central boiler can wait before starting, for slow valves;
   the plugin has no such delay. *Provisional:* not carried over — a delay is a timer against VT's
   call (decision of 2026-09-25) — and the specification, the migration text and the "VT central
   boiler active" blocker say so. *Open:* an off→on delay option, default 0 as in VT, cancelled when
   the demand goes.
6. **Outside change with reaction "information"** (S-11, review question 2). Today all writes stop,
   frost heating too; the plugin's overrides (`CH=0`) stay; nothing is stored; a reload resumes
   silently. *Provisional:* an outside change always hands back and latches — the reaction choice
   goes for this alarm; the latch is stored and outlives a reload and a restart; control resumes
   when the user switches it off and on. *Open:* a "writes stopped" state that undoes the plugin's
   overrides without the rest of a hand-back.
7. **Which alarms may hand back** (S-30, review question 7). *Provisional:* the reaction "hand back"
   acts only from the alarm level, and is not offered for the counting alarms and trends (unstable
   ignition, pressure falling, flue gas rising, hysteresis drift), which inform only, like frequent
   starts. *Open:* another list.
8. **The drop rule and a value never accepted** (Open after R6 #1, S-48). *Provisional:* as decided
   on 2026-09-25 — a value the boiler never takes from the start is an outside change; the
   specification states the consequence behind an OpenTherm thermostat (a false outside change, then
   a latch). *Open:* escalating repeated drops; telling "ignored" (a read-back equal to the value
   before the session from the start) from a foreign value.
9. **The fixed fallback** (S-26). *Provisional:* the specification follows the code — the user's
   fixed fallback replaces the last value after 3 h of holding it. *Open:* apply it at once.
10. **The circuit maximum and the boiler's overshoot** (S-14). The maximum limits the setpoint; the
    boiler may overshoot it. *Provisional:* the option text says what it limits; a new alarm rises
    when the measured flow stays above a circuit's maximum by more than a margin (proposed: 5 K),
    reaction "information" by default. *Open:* the setpoint limited to the maximum minus the
    measured overshoot.
11. **"Off" as a low setpoint** (L4 of `docs/plan-0.2.1.md`, S-39) — still open. *Provisional until
    L4:* its risk (the CH pump may keep running) is shown at every level, in the form and on the
    control switch.
12. **A deviating outdoor sensor** (Open after R6 #7). The provisional decision of
    `docs/plan-0.2.1.md` (the curve takes the colder of the two) stays until the user confirms it.
13. **Before 0.3: anti-cycling and principle 12** (S-18). Duty cycling, a start budget, an FC1 summer
    switch and class-3 minimum times in `PLAN.md` 0.3 contradict principle 12. Not needed for 0.2.2;
    `PLAN.md` marks them "to be decided against principle 12" (Q2).
14. **Tests with the real VT in CI** (P-119, review question 14): may CI fetch VT 10.4.0 and SmartPI
    0.4.0 from their tags? *Provisional:* no; the real-VT tests keep running locally before every
    commit.
15. **J4 in the test HA** (review question 15): an unclean restart and a lost keep-alive through the
    test container (e.g. `docker kill` over SSH), or in-process only. *Provisional:* in-process only.
16. **The release** (review question 16, S-53): 0.2.2 is the first version published (pre-release
    0.2.2b1, then 0.2.2); whether the public repository carries `CLAUDE.md`, the plans and the
    reviews is decided at K5.

The review's other questions get an answer in a step, which the user confirms or changes: 3 (X4),
5 (V1), 6 (V3), 8 and 9 (Y1), 10 and 19 (X5), 11 and 12 (Y3), 20 (Y4). Questions 13, 17 and 18 are
research (Q3).

## Rules that shape this release

- Everything in the rules of `docs/plan-0.1.md`, `docs/plan-0.2.md` and `docs/plan-0.2.1.md` still
  applies.
- Every problem of the review has a step (index). One that a decision makes moot is marked so in its
  step; one deferred is named in "Open after 0.2.2" with its release.
- Tests first: the review's §6 test where it has one, else a test that shows the problem; then the
  fix.
- A step is ✅ only when every scenario of each of its problems is covered — the review's row, its §6
  test and section 4's proposal — not only the one tested; a remainder is named in "Open after
  0.2.2" (comparison §7, 1).
- Every new mechanism gets a negative test with an unknown, missing or `None` input before its step
  is ✅ (comparison §7, 2).
- A provisional option is marked so in `SCOPE.md` and kept in one place in the code.
- Every change to a `*.md` file is shown as a diff and waits for the user's consent.

## Phase Q — specification, plans, research, decisions

Why: the specification has to say what the code will do before the code changes; 62 of the review's
problems are the specification's own, and some questions need facts from the devices' and Home
Assistant's sources.
In practice: `SCOPE.md`, `PLAN.md` and the plans say what 0.2.2 does; the research is kept in
`research/`; the user's decisions are recorded.

| Step | Work |
|---|---|
| Q1 | `SCOPE.md`, `PLAN.md` and `CLAUDE.md` take the provisional options of the decisions above, and each specification problem of the review is settled in the text or assigned to a step (index). Text only: "unknown" is written and counts once read back (S-28); SmartPI's promised signals and the Auto-TPI pause marked for a later release — Auto-TPI "detected, not paused" (S-29); a circuit takes its zones' emitter types (S-33); one term for the device and zone count, with a note for users coming from VT (S-36); the fixed thresholds and times listed with their reasons (S-37); switch zones follow VT's device state, one start per TPI cycle (S-38); CH on/off outside the drop rule (S-40); units of the options (S-44); settling an owed hand-back by hand (S-45); the ramp's rationale (S-47); principle 9 for SmartPI, which learns its own outdoor term (S-50); removing the entry: a last attempt and a persistent issue, no veto (S-54); class 2's persistent writes a stated exception, or dropped (S-56); principle 13 resets only session values, says which rule values may be options, and the source chain is clarified (S-58); the internal contradictions (S-59); each feature without a release gets one or goes (S-60); learning pauses under the control stages (S-61); the alarms that have a reaction (S-62); the risks of "held" (S-12); the activation delay (S-07) |
| Q2 | plan corrections: stale texts in `docs/plan-0.1.md`, `docs/plan-0.2.md` and `PLAN.md` (S-46); J2: the firewall rule in `devenv/README.md` also on the forwarding path (`DOCKER-USER`) and for IPv6, with the check T-25 (S-19); J4: a held device that restarts (S-13), starts under control against the boiler's own regulation (S-15, T-24), an on/off thermostat after a crash (T-07); K1: the README also covers removal, how often data update, troubleshooting, known limitations and supported devices (S-52); K5 sets the manifest to 0.2.2b1 and K7 to 0.2.2 (S-53); in `docs/plan-0.2.1.md`: M4's removal text (S-54), N5's text part reopened (S-50), "After 0.2.1" pointing to this plan, "Done" worded as "after the fixes an independent check finds none" (S-55); `PLAN.md` 0.3 items marked for decision 13 (S-18) |
| Q3 | research over the network, kept in `research/`: which VT version first loads external feature managers (review question 13, P-60); whether OpenTherm boilers raise a `CS` below their minimum CH setpoint (ID 49) and fire, and whether `CS` = 10 °C means "no demand" (question 17); whether Home Assistant's shutdown stage leaves time for the slowest hand-back (question 18); a generic rule tying the lowest flow to the boiler's minimum power (decision 2, S-02); how soon an ESPHome device reports its value after a start (P-50); how the OTGW firmware over MQTT shows a gateway that drops and a broken link between the ESP and the PIC (Open after R6 #8); `research/diy/INDEX.md` completed for `gateway-6.6.asm`, or the file removed (S-51) |
| Q4 🔒 | the user takes decisions 1–16 above — at any time, at the latest at K4, together with L4 of `docs/plan-0.2.1.md` |

Done when: the specification states every provisional option, the plans have no stale step, and the
research answers are in `research/`.

## Phase V — control state that survives, hand-back, the stop button (review §7, 1 and 2)

Why: the plugin's memory of holding the boiler is lost on the unhappy paths — a corrupt store reads as
a new installation, a failed setup reports no owed hand-back, a crash loses a delayed save — and the
control switch goes unavailable exactly when the monitor fails.
In practice: the control state is written at once and atomically, and read cautiously; every owed
hand-back is sent or shown; a hand-back counts only when confirmed; the switch always works.

| Step | Work |
|---|---|
| V1 | the store: the control state kept in a small store written at once with atomic writes (or a second copy); a store read as `None` for an entry that ran before counts as unreadable — a full hand-back first; one policy for an unreadable store in setup, removal and the options flow; nothing saved before the store was read; the monitoring period counts from the entry's creation (`ConfigEntry.created_at`), so a lost store does not restart it (P-01, P-04, P-58; T-08 with a real truncated file, T-10, T-35; review question 5) |
| V2 | a setup that fails: an owed hand-back is sent by a hand-back unit built first, or reported by a persistent issue, whatever fails after it; the forecast load best effort; the code after setup's `try` guarded; options saved while the entry is in setup error reload it (P-05, P-33, P-57; Open after R6 #6: C14, H9; T-09, T-11) |
| V3 | saved at once: the SmartPI pause, before the service call, and its resume when control leaves the options; the user's on/off wish in the entry's store, so the switch comes back on after a restart only if it was on; an internal-error latch outlives a restart (P-10, P-11; Open after R6 #6: C10, C15; T-29, T-31, T-39; review question 6) |
| V4 | the hand-back's bookkeeping: the owed marker set before every attempt, whatever interrupts it; an end-of-session hand-back is full while an older debt exists; releasing an owed hand-back (repair) serialised with a running attempt; the hand-back blocker checked again when the options are saved; the write coroutine created only when awaited; a device that reports late (ESPHome, MQTT) gets a short wait at start and stop before a hand-back counts as failed; a pyotgw command that times out while the gateway is connected does not count as done; the owed hand-back's retry, the stale-link hand-back and the decision interval not held up by a wall clock set back (P-12, P-42, P-49, P-50, P-51, P-52; Open after R6 #8; T-05, T-06, T-13, T-14) |
| V5 | what confirms a hand-back: one rule for writes and hand-back on `opentherm_gw` — control waits until the read-back has a value (P-21); an entity with `assumed_state`, or without an independent report, is "unconfirmed" and says so (S-09, T-30); a "timeout" hand-back is confirmed by the read-back returning to the value before the session within the lapse time, else it stays owed (S-20); the order of the heating switch and the value per write type, and no heating switched on where the effect is "heating stops" (S-27); the hand-back value within the circuit maximum and the hard maximum (S-21); the external-control switch gets a declared write type, and a persistent one is not used (P-40); "off" refused within 0.5 K of a hand-back value that means the boiler's own control (S-49) |
| V6 | the stop button: control entities' availability follows the control unit, not the monitor; an exception in the monitor's fast path is caught, logged once with a traceback and once at recovery, and reported as `UpdateFailed`; control hands back if the monitor stays failed beyond a limit (P-02, P-24; T-15, T-54) |
| V7 | stopping with an alarm: a blocker that stops control while it held the boiler raises an alarm or repair issue where the hand-back's effect is "heating stops" (S-10); after a stand-alone hand-back the switch says frost protection now rests on the boiler, and an alarm rises when it stays handed back in frost (S-57); an outside change as decision 6 (S-11) |

Done when: T-05, T-06, T-08–T-11, T-13–T-15, T-29–T-31, T-35, T-39 and T-54 pass, and every unhappy
path the review names ends with the boiler handed back, or with the hand-back owed and shown.

## Phase X — control and configuration (review §7, 3 and 5)

Why: the guards and the link watch forget too easily, a few demand criteria can go silent, and the
form accepts combinations that toggle a switch for ever or never confirm a hand-back.
In practice: the guards keep their memory for the session, a flapping link is caught, and every
dangerous combination the review found is refused in the form and among the blockers.

| Step | Work |
|---|---|
| X1 | the guards: their memory (the rewrite, the block, the baseline) kept across hand-backs inside a session, reset only at its end (P-06, T-01); the baseline learned from the first known read-back that is not the plugin's value (P-07, T-02); "ignored" tracked per guard, so a boiler ignoring CH on/off is reported (P-09, T-04); an alarm together with a transient blocker latches (P-48, T-49); a hand-back passes while a guard is blocked (T-19); a setpoint entity with a step above 1 K refused, the value rounded inside the limits and compared after rounding (P-15, P-98, T-55); "off" at least 1 K below the hard minimum (P-43); a held device that returns from unavailable with its initial value rewritten without counting an outside change (S-13, T-47); CH on/off outside the drop rule, as stated (S-40); decision 8 (S-48) |
| X2 | the boiler link and freshness: staleness judged over a window, so a link fresh one step in five still hands back; `boiler_link_lost` raised whenever control is on and the link is stale beyond the limit — after a restart, a blocker, or switching on with the link down — and kept while it lasts; each signal's own age limit, the flame's included, and the weather entity's own (P-08, P-41; T-03, T-26); a silent MQTT drop and a broken link between the ESP and the PIC shown as far as Q3 finds the firmware allows (Open after R6 #8) |
| X3 | demand and zones: the opening threshold over the calling zones only (P-13, T-46); a VT device power ≤ 0 is no data, and a criterion no zone can feed is refused in the form and a blocker with an alarm (P-14, T-27); control requires at least one VT zone (S-04); a zone whose mode is "off" has no demand whatever `is_ready` says (S-34, T-17); VT's `safety_state` read as a lost sensor for the zone alarm (S-35, T-44); power shedding removes a zone's demand (T-45); the reference room and the critical zone skip zones with a lost sensor or not ready (P-18); an implausible room temperature of a watched zone is unknown, with the same alarm after its limit, and one plausibility rule for room temperatures (S-06); decision 3's grace period (S-03, T-28) |
| X4 | frost, fallback, ramp, correction, learning pauses: frost protection as decision 4 (S-05); `frost_since` reset at hand-back (P-45); FALLBACK shown only while heating (P-47); the fixed fallback as decision 9 (S-26); the ramp skipped only for installation limits — the hard maximum, a circuit, the boiler — not for a falling weather ceiling (S-23); the circuit maximum as decision 10 (S-14, T-20); the comfort correction: "heat flows" means the flame when known, else the command (S-24, review question 3), the no-rise rule counts only zones taking heat (S-08), every rule of principle 13 mapped, with a freeze while a cap holds the setpoint (S-25, T-48), no rise with the clock set back (P-46, T-18), its value published and resettable (P-38); learning pauses per cause — the flow condition and the one-hour cap each where it belongs (P-89); a hot-water draw still pauses SmartPI, as the zones get no heat meanwhile, and the specification says so (S-41) |
| X5 | configuration, refused in the form and, for hand-edited options, among the blockers: the same entity as heating switch and hand-back switch, or the setpoint entity as hand-back switch (P-03, T-38); one entity for two signals, unless it may feed both (P-16, T-32); "off" against the hard minimum at the simple level and after "restore defaults" (P-25); the path and topology pairing (P-44); the MQTT or `opentherm_gw` integration set up and enabled (P-69); an option value this version does not know (P-70); entity domains and integrations checked on the server, zones VT climates only (P-79, review question 19); cross-field checks of the design flow, the room, the hard maximum and the design outdoor range (P-68); the gateway field without custom values (P-106); removing a circuit that has zones (P-64); "restore defaults" keeps the monitoring days, or says it does not (P-65); an options edit that would block control (the boiler class, a second circuit, fewer zones than the count threshold, underfloor without a maximum flow) warned and confirmed before it is saved (Open after R6 #3); a save that does not touch control reloads without a hand-back, or the options say it hands back (P-67, review question 10); a passive fixed circuit's floor with a margin (S-42); the risks of "held" in the option (S-12); the risk of "off" as a low setpoint at every level (decision 11, S-39); one list of the options' keys (P-71); the flow's own paths tested (T-12, T-37) |
| X6 | the two high specification problems: the gateway topology asks for the thermostat's kind, and control is blocked for an on/off thermostat or an unknown kind (decision 1, S-01; T-07 in Z3); the option "lowest flow for the boiler" with its default and risk texts, applied as a lower bound together with the hard minimum (decision 2, S-02) |
| X7 | VT: a VT central entry the user disabled means no VT central boiler, and one stuck in setup error raises a visible issue after a time limit instead of blocking for ever (P-20, T-52); reloading VT's central entry uses the entry's stored data rather than handing back (P-105); an unknown VT central-boiler state leaves the Auto-TPI issue unchanged (P-54); the "reload VT" repair skips unavailable or not-ready zones (P-59); a VT without external feature managers detected by its version (P-60, from Q3); entity renames followed through the entity registry, or a repair issue (P-19); the public attribute `hot_water` renamed `heat_available` before the first release (P-61); the `smart_boiler` attribute on VT climates changed only on a real change (P-63); registration errors never reach VT (T-53) |

Done when: the phase's §6 tests pass, and the form and the blockers refuse every dangerous combination
the review names.

## Phase Y — monitor and Home Assistant

Why: some alarms show "OK" on inputs they cannot judge, some numbers drift with the weather or the
day's boundaries, and the integration still has rough edges (the event loop, translations,
diagnostics).
In practice: an alarm says "unknown" when it cannot judge, the day summaries and the verdict rest on
what was measured, and the Home Assistant layer follows its rules.

| Step | Work |
|---|---|
| Y1 | alarms: "pressure 0 = unknown" only for the gateway's sources (P-17, T-33; review question 8); an alarm whose input is unknown or cannot be judged holds its state for a short time (proposed: 1 h), then shows `unknown` (S-16, T-34; review question 9); a stuck outdoor sensor judged on the tail since its last change (P-26, T-16); the low-flow warning not judged with hot water unknown on a boiler with DHW (P-27), and why it is unavailable shown (P-99); hysteresis-drift samples only from pauses with demand throughout (P-29); unstable ignition without the burns the boiler's own hysteresis ends (P-81); `frequent_starts` and `unstable_ignition` with hysteresis (P-82); the flue-gas trend entity created only where the trend is computed (P-85); the CH echo's text names the right `opentherm_gw` entity, tested with hot-water draws (P-22, T-21); decision 7 (S-30); the alarms that have a reaction (S-62) |
| Y2 | cycles, gas and days: hot water inferred on weaker evidence, or unknown when the evidence conflicts (P-28); burns across midnight complete (P-83); metered gas split in one pass (P-84), and bounces counted once by one function (P-97); other gas consumers on the meter subtracted or reported apart (S-31); day summaries replace a stuck outdoor sensor by the weather (P-86); a narrower settings key, so an unrelated option keeps the stored days (P-87); forecast errors only for hours observed (P-88, T-40); the importer normalises 23 and 25 h days, rejects a zero or reversed window and does not grow quadratically (P-93, P-111; Open after R6 #6: A13); Home Assistant's downtime unknown (P-95; A11); days under control tagged now (P-96; A12); the analysis reads the backfill state with its copy (P-53); pruned forecast partitions not recreated (P-56); burns classified per analysis, not at every step (P-80) |
| Y3 | building model and verdict: the heating threshold with its own uncertainty and a wider spread required (P-31, T-41); the heat loss fitted alone only with an entered or confident threshold (P-32, T-42); the measured threshold shown and resettable (P-90); stored days keep the temperature distribution, not one load model (P-91); an entered design load always wins, and the texts say so (P-92, review question 12); installation warnings shown, or removed (P-94); the load criterion counted only with an entered or confidently measured model (S-17, T-43); the verdict's reasons name what the released control changes, and the release that addresses the rest (S-22); "not worth it" only with at least a set number of criteria judged (S-32); off-season monitoring: the switch says control starts without a verdict (S-43); bounded learning covers what control uses, while the building model feeds the monitor only and is visible and resettable (review question 11) |
| Y4 | Home Assistant: forecast snapshots parsed in the executor, and only what is used kept (P-23, T-36); `weather.get_forecasts` skipped while the entity is unavailable, and with a timeout (P-55); diagnostics redact options given as any mapping (P-30, T-50) and work for an entry in setup error (review question 20); verdict reasons, control reasons, blockers and `latched_by` translated (P-39), `critical_zone` states (P-73) and exception placeholders (P-74) too; the gas-per-degree-day unit shown only once the meter's unit is known (P-75); unused texts removed, with a reverse key-parity test (P-76); `ceiling_band`'s text (P-66); the freshness step's field descriptions (P-103); entity names without the device name (P-104); timestamps in ISO (P-78); `change_report` and `forecast_snapshots` created only with their data (P-100); continuous attributes dropped or coarsened (P-72); a typed `ConfigEntry` alias (P-101); the percentage unit Home Assistant 2026.7 asks for (P-102); dead code removed (P-62); docstrings placed and updated (P-77, P-116) |

Done when: the phase's §6 tests pass, and no alarm shows "OK" on an input it cannot judge.

## Phase Z — tests, tools, simulator, check

Why: several safety paths have no test, CI measures neither branches nor modules, the simulator
cannot run J4's main path, and 0.2.1's lesson is that an item is closed only when every scenario of
it is.
In practice: the missing tests, CI as strict as the local run, a simulator ready for J4, and an
independent check of the fixes.

| Step | Work |
|---|---|
| Z1 | tests: the §6 tests not in a step above (T-22, the MQTT hand-back before MQTT stops; T-51, cancellation); the config and options flows at 100 % (P-34); a backfill with zones (P-117); the allowed-services checks spy on `hass.services.async_call`, the switch domain included (P-118); core tests without the Home Assistant pytest plugin (P-120); weak assertions made exact (P-121); the MQTT path with `mqtt_mock` (P-122); listeners after unload (P-123); migration, and a newer entry refused (P-124); one entry per test of a single-entry integration (P-125; Open after R6 #6: T11); VT safety, shedding, window and "off" not ready as scenarios (P-126); every default of the SCOPE table pinned (P-127); a whole-value `[%key:…%]` refused (P-128); the safety-critical functions split only after table-driven precedence tests (P-115) |
| Z2 | tools and CI: coverage with branches, per module, at least 95 % in each module and 100 % for the flows (P-35); current major versions of the actions (P-110); a job with the latest `vtherm_api` (P-109); the real-VT tests as decision 14 (P-119); the deploy's dry run does not read `devenv/local.env` (P-107); `session-summary-*.md` git-ignored (P-108); the manifest's version 0.2.2 |
| Z3 | the simulator before J4: a route for the `opentherm_gw` path in the test HA — the MQTT path, or a test-only entry — decided and documented (P-37, T-23); a boiler that regulates its own flow, emitter inertia, daily sums kept (P-112); only persistent writes counted as persistent, CH writes counted (P-113); switch zones driven by `on_percent` over a cycle, and the J4 scenarios reachable (P-114, T-24); off zones close their valves (S-05); a hot-water draw under control in a closed loop (P-36, T-21); starts under control against the boiler's own regulation (S-15); the gateway's read-back as `opentherm_gw` shows it, and a heating switch with its own write type (Open after R6 #2); the PIC's `CH=0` flag with an on/off thermostat (T-07); the circuit maximum with underfloor heating (T-20) |
| Z4 | an independent read-only check of 0.2.2: each problem of the review checked against every scenario of its row, not only its test; a finding of the check fixed with a test, and the fix checked again. A multi-agent review only with the user's go-ahead |

Done when: the "Done for 0.2.2" list below holds.

## Open after 0.2.2

Left on purpose for a later release:

1. The pressure trend is judged on cold water only, which cold days lack (Open after R6 #5) — 0.3:
   a trend on warm water, or of the refills.
2. Radiators and underfloor behind a mixing valve as one written circuit plus passive fixed circuits
   (S-42, its second part) — 0.3.
3. Anti-cycling in 0.3 against principle 12 (decision 13).
4. Still 🔒 from `docs/plan-0.2.1.md`: L4 (decision 11) and R2 (the icon).

What a step leaves open is added here by name, as the rules say.

## After 0.2.2

The open steps of `docs/plan-0.2.md` follow: J2 🔒 (with Q2's firewall check), J4 🔒 (with Q2's
scenarios), K1 🔒, K4 🔒 (the review of the control laws, with Q4's open decisions and L4; the 0.2.1
change log read together with `docs/review-2026-09-26-vs-0.2.md`), K5 🔒 (public repository,
pre-release 0.2.2b1), K6 🔒, K7 🔒 (release 0.2.2).

## Done for 0.2.2

- Every problem of `docs/review-2026-09-26.md` fixed, moot by a recorded decision, or named in "Open
  after 0.2.2" with its release (index).
- The tests, `ruff check`, `ruff format --check` and mypy strict pass; coverage with branches is at
  least 95 % in every module and 100 % in the config and options flows.
- The in-process acceptance scenarios pass, the new ones included.
- After the fixes, an independent check (Z4) finds no critical or high problem, and the fixes of its
  own findings are checked again.

## Index: review problem → step

Problems (code and tests): P-01 V1 · P-02 V6 · P-03 X5 · P-04 V1 · P-05 V2 · P-06 X1 · P-07 X1 ·
P-08 X2 · P-09 X1 · P-10 V3 · P-11 V3 · P-12 V4 · P-13 X3 · P-14 X3 · P-15 X1 · P-16 X5 · P-17 Y1 ·
P-18 X3 · P-19 X7 · P-20 X7 · P-21 V5 · P-22 Y1 · P-23 Y4 · P-24 V6 · P-25 X5 · P-26 Y1 · P-27 Y1 ·
P-28 Y2 · P-29 Y1 · P-30 Y4 · P-31 Y3 · P-32 Y3 · P-33 V2 · P-34 Z1 · P-35 Z2 · P-36 Z3 · P-37 Z3 ·
P-38 X4 · P-39 Y4 · P-40 V5 · P-41 X2 · P-42 V4 · P-43 X1 · P-44 X5 · P-45 X4 · P-46 X4 · P-47 X4 ·
P-48 X1 · P-49 V4 · P-50 V4, Q3 · P-51 V4 · P-52 V4 · P-53 Y2 · P-54 X7 · P-55 Y4 · P-56 Y2 ·
P-57 V2 · P-58 V1 · P-59 X7 · P-60 X7, Q3 · P-61 X7 · P-62 Y4 · P-63 X7 · P-64 X5 · P-65 X5 ·
P-66 Y4 · P-67 X5 · P-68 X5 · P-69 X5 · P-70 X5 · P-71 X5 · P-72 Y4 · P-73 Y4 · P-74 Y4 · P-75 Y4 ·
P-76 Y4 · P-77 Y4 · P-78 Y4 · P-79 X5 · P-80 Y2 · P-81 Y1 · P-82 Y1 · P-83 Y2 · P-84 Y2 · P-85 Y1 ·
P-86 Y2 · P-87 Y2 · P-88 Y2 · P-89 X4 · P-90 Y3 · P-91 Y3 · P-92 Y3 · P-93 Y2 · P-94 Y3 · P-95 Y2 ·
P-96 Y2 · P-97 Y2 · P-98 X1 · P-99 Y1 · P-100 Y4 · P-101 Y4 · P-102 Y4 · P-103 Y4 · P-104 Y4 ·
P-105 X7 · P-106 X5 · P-107 Z2 · P-108 Z2 · P-109 Z2 · P-110 Z2 · P-111 Y2 · P-112 Z3 · P-113 Z3 ·
P-114 Z3 · P-115 Z1 · P-116 Y4 · P-117 Z1 · P-118 Z1 · P-119 Z2, Q4 (14) · P-120 Z1 · P-121 Z1 ·
P-122 Z1 · P-123 Z1 · P-124 Z1 · P-125 Z1 · P-126 Z1 · P-127 Z1 · P-128 Z1

Specification: S-01 Q4 (1), X6 · S-02 Q4 (2), Q3, X6 · S-03 Q4 (3), X3 · S-04 X3 ·
S-05 Q4 (4), X4, Z3 · S-06 X3 · S-07 Q4 (5), Q1 · S-08 X4 · S-09 V5 · S-10 V7 · S-11 Q4 (6), V7 ·
S-12 Q1, X5 · S-13 X1, Q2 · S-14 Q4 (10), X4 · S-15 Q2, Z3 · S-16 Y1 · S-17 Y3 · S-18 Q4 (13), Q2 ·
S-19 Q2 · S-20 V5 · S-21 V5 · S-22 Y3 · S-23 X4 · S-24 X4 · S-25 X4 · S-26 Q4 (9), X4 · S-27 V5 ·
S-28 Q1 · S-29 Q1 · S-30 Q4 (7), Y1 · S-31 Y2 · S-32 Y3 · S-33 Q1 · S-34 X3 · S-35 X3 · S-36 Q1 ·
S-37 Q1 · S-38 Q1 · S-39 Q4 (11), X5 · S-40 Q1, X1 · S-41 X4 · S-42 X5, Open after 0.2.2 (2) ·
S-43 Y3 · S-44 Q1 · S-45 Q1 · S-46 Q2 · S-47 Q1 · S-48 Q4 (8), X1 · S-49 V5 · S-50 Q1, Q2 · S-51 Q3 ·
S-52 Q2 · S-53 Q2, Q4 (16) · S-54 Q1, Q2 · S-55 Q2 · S-56 Q1 · S-57 V7 · S-58 Q1 · S-59 Q1 · S-60 Q1 ·
S-61 Q1 · S-62 Q1, Y1

Missing tests of review §6: T-01 X1 · T-02 X1 · T-03 X2 · T-04 X1 · T-05 V4 · T-06 V4 · T-07 X6, Z3,
Q2 · T-08 V1 · T-09 V2 · T-10 V1 · T-11 V2 · T-12 X5 · T-13 V4 · T-14 V4 · T-15 V6 · T-16 Y1 ·
T-17 X3 · T-18 X4 · T-19 X1 · T-20 X4, Z3 · T-21 Y1, Z3 · T-22 Z1 · T-23 Z3 · T-24 Z3, Q2 · T-25 Q2
(run at J2) · T-26 X2 · T-27 X3 · T-28 X3 · T-29 V3 · T-30 V5 · T-31 V3 · T-32 X5 · T-33 Y1 ·
T-34 Y1 · T-35 V1 · T-36 Y4 · T-37 X5 · T-38 X5 · T-39 V3 · T-40 Y2 · T-41 Y3 · T-42 Y3 · T-43 Y3 ·
T-44 X3 · T-45 X3 · T-46 X3 · T-47 X1 · T-48 X4 · T-49 X1 · T-50 Y4 · T-51 Z1 · T-52 X7 · T-53 X7 ·
T-54 V6 · T-55 X1

Review questions (Appendix E): 1 Q4 (3) · 2 Q4 (6) · 3 X4 · 4 Q4 (1) · 5 V1 · 6 V3 · 7 Q4 (7) ·
8 Y1 · 9 Y1 · 10 X5 · 11 Y3 · 12 Y3 · 13 Q3 · 14 Q4 (14) · 15 Q4 (15) · 16 Q4 (16) · 17 Q3 · 18 Q3 ·
19 X5 · 20 Y4

Open after R6 (`docs/plan-0.2.1.md`): #1 Q4 (8) · #2 Z3 · #3 X5 · #4 Q4 (2), X6 · #5 Open after
0.2.2 (1) · #6: H9 V2, C14 V2, C10 V3, C15 V3, A11 Y2, A12 Y2, A13 Y2, T11 Z1 · #7 Q4 (12) ·
#8 V4, X2, Q3

Added by the comparison (`docs/review-2026-09-26-vs-0.2.md` §7): S-01 X6 · P-20 X7 · P-01 and P-04
V1 · P-21 V5
