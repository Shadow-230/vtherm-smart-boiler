# Plan 0.2.2 — Corrections after the review of 2026-09-26

Goal: close every problem of the independent review of 0.2.1 (`docs/review-2026-09-26.md`) before
anything reaches the test HA. Each one is fixed, made moot by a recorded decision, or named for a
later release, and the lessons of the comparison with the 0.2 audit
(`docs/review-2026-09-26-vs-0.2.md`, §7) are applied. The review found no critical problem and five
high ones: a corrupt store makes the plugin forget that it holds the boiler; the control switch goes
unavailable when the monitor fails; one entity can be both heating switch and hand-back switch; the
OTGW "off" masks an on/off thermostat after a crash; and the water's lower bound ignores the boiler's
minimum power. The user's decisions of 2026-09-26/27 settle decisions 1–15 below and bring control of
boilers switched on and off by a relay (class 3) into this release. The steps of `docs/plan-0.2.md`
still open (J2, J4, K1–K7) follow on 0.2.2: it becomes the first version to reach the test HA and to
be published (pre-release 0.2.2b1, then 0.2.2 — the user confirms at K5, decision 16 below).
Scope: `SCOPE.md`; overview: `PLAN.md`; the previous corrections: `docs/plan-0.2.1.md`. Written on
2026-09-26 from the review and the comparison; the user's decisions recorded on 2026-09-27.

Phases run in order: Q, V, X, Y, Z. Q4 waits for the user and does not hold up the build: until the
user decides, each open decision follows the provisional option given below. Q1 and Q2 change
documents, whose diffs wait for the user's consent; phase V may start meanwhile.

Status on 2026-09-27: decisions recorded, nothing built; start at Q1 as
`docs/plan-0.2.2-details.md` "Start here" says.

## In short

- **The plugin never forgets that it holds the boiler** — not after a corrupt file, a failed start
  or a crash between two saves (phase V).
- **The off switch works when something else is broken** (phase V).
- **A hand-back counts only when something other than the plugin's own write confirms it**
  (phase V).
- **Dangerous settings are refused in the form**, not found at the boiler (phase X).
- **The guards and the boiler-link watch keep their memory for the whole session**, and the
  one-rewrite memory for its day (phase X).
- **A boiler switched on and off by a relay can be controlled too**, as VT's own central boiler does,
  with the plugin's safeguards (step X8).
- **Missing data never switches heating off by itself**, the link to the boiler aside; every feature
  works with what the installation gives, and says what it lacks.
- **The user settled the safety gaps (decisions 1–15)**; the first published version and the
  repository's content are decided at K4 and K5 (phase Q).
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
- "Decision n" refers to the numbered list below. Decisions 1–15 are the user's (2026-09-26/27);
  decision 16 keeps its provisional option until the user decides. The user's answers A–O of
  2026-09-27 are recorded where each belongs; the index names their steps.
- The step-by-step details — order of work, tests, values, texts — are in
  `docs/plan-0.2.2-details.md` under each step's name; the plan stays the source of the decisions.

## Terms

The terms of `docs/plan-0.2.1.md` hold (hand-back, write path, write type, read-back, outside change,
latch, blocker, topology, demand, comfort correction, bounded learning, frost protection, freshness,
`CS` / `CH`). New here:

- **Control state** — what the plugin must remember across restarts to hand back safely: the
  "controlling" marker, an owed hand-back and the options it was taken with, the latches, the
  user's on/off wish, a SmartPI zone it paused.
- **Unhappy path** — a start with a corrupt or missing store, a setup that fails, a crash between
  two saves, a monitor that keeps failing.
- **Thermostat kind** — what is wired to a gateway's thermostat terminals, asked in both gateway
  topologies: an OpenTherm thermostat, an on/off contact, nothing, or "I don't know" (decision 1).
- **Grace period** — 10 minutes after a zone becomes unknown while VT runs, during which that zone's
  last known answer holds.
- **Lowest water temperature** — the one setting that bounds the curve from below (today's "lowest
  flow setpoint", 10–50 °C), set by the user like a curve setting; the plugin can suggest a value
  where the boiler, at its minimum power, keeps stopping by itself at it.
- **Provisional option** — the most cautious answer to an open decision, applied until the user
  decides.
- **Relay** — the write target of an on/off boiler (class 3): a switch on the boiler's room-thermostat
  terminals, or a boiler thermostat entity switched between heat and off.
- **Rest state** — the state a relay is left in at hand-back, chosen by the user.
- **Recognition period** — after Home Assistant starts or VT reloads, until every configured zone has
  reported (VT shows it ready), at most 10 minutes. No new decision is taken meanwhile; a command
  the plugin held before is kept or restored (decision 3).
- **Lost command** — the read-back is back at the state from before the plugin (with an OpenTherm
  thermostat, at the thermostat's own value) and there is a trace of an outage: the device
  unavailable just before, or a gateway or device restart — or a single such fall-back without a
  trace (decision 6). The plugin simply sends the command again and counts it.
- **Safe hand-back** — the order of a hand-back: the water to the lowest water temperature set,
  heating on where the boiler
  returns to a thermostat or its own control, then the release, one part after another at once,
  waiting for no read-back. A relay goes to its rest state instead.
- **Working thermostat** — defined in decision 3 (answers F and M of 2026-09-27).
- **Notification** — a Home Assistant repair issue the plugin raises itself (no service call), with a
  translated text that says what to do; it closes when its condition clears.

## Decisions of 2026-09-26/27 (the user)

The user answered decisions 1–8 below and added the following. Where an answer differs from the
provisional option this plan first proposed, the answer holds.

- **Missing data.** Most installations give only some of the parameters. Every feature works with
  what is available; a feature whose input is missing is shown as inactive and names what it lacks;
  missing data never by itself switches heating off or blocks the boiler. The one exception is the
  link with the boiler: control that loses the boiler's confirmations while it controls hands the
  boiler back (for a relay, see "On/off control" below). An installation that gives no confirmation
  at all gets only the monitor — except a relay that reports no state of its own, which the user
  accepted under control with blind repeats (see "On/off control" below), shown as "controlled
  without confirmation". When VT gives no answer at all, nothing asks for heat: the plugin hands the
  boiler to a working thermostat, or, without one, does not heat (decision 3).
- **Boiler protection follows the boiler's own logic.** The plugin stops heating for an alarm only
  where the boiler itself stops: while the boiler reports its own low-water-pressure fault, where it
  reports one, control sends its usual "off" — no hand-back, no latch, frost heating included — and
  heats again by itself when the fault clears. The same for any other fault the boiler reports as
  stopping it. The two faults come from two optional signals the user picks; only a known "on" held
  for a few minutes counts, and an unknown one counts as no fault. Without such a report, low
  pressure raises only an "add water" notification, at a threshold the user takes from the boiler's
  manual — none by default, replacing today's 0.7 bar
  (`core/alarms.py:67`). A broken or silent pressure sensor never stops heating. The plugin's own
  high-pressure and flue-gas thresholds only inform, with a notification that says what to do. With
  enough data the plugin warns earlier, e.g. "your pressure keeps falling — there is a risk of a
  leak", judged with the water temperature taken into account, since heating the water changes the
  pressure.
- **Safe hand-back.** A hand-back first brings the water to the lowest water temperature set, then switches
  heating on where the boiler returns to a thermostat or its own control (on a gateway always
  `CH=1`, so no "off" is left behind), then releases the boiler; the parts follow one another at
  once, waiting for no read-back. Where a target is declared "held" — the device keeps the last
  value it was given (ESPHome, DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires in
  about a minute) — and the release is not confirmed, the boiler is left at that lowest temperature:
  an alarm rises at once and the release is retried until it is confirmed. When another controller
  already holds the target, the hand-back counts as done and is not retried every minute; this
  changes SCOPE §7's "retried every minute until it is confirmed" for that case. Stepping aside from
  another controller is a full safe hand-back too (decision 6, answer H); a relay is then set once
  to its rest state and left alone (answer L).
- **On/off control (class 3) comes into 0.2.2**, as VT's own central boiler works (step X8):
  - a write path "relay" for boilers switched on and off: a switch, or a boiler thermostat entity
    switched between heat and off; not an `input_boolean`, which confirms nothing. The
    water-temperature parts (curve, limits, ramp, comfort correction) do not apply and are hidden;
  - the plugin cannot read the relay's own settings, so the form asks for them — its state after a
    power cut, its own switch-off timer, and whether it reports its state — as the user's
    declaration, and asks the user to tick "this is a separate relay contact, not a setting stored
    in the boiler's memory"; without the tick control does not start (the user, 2026-09-27, G);
  - flame and flow become optional for the whole entry; water-temperature control gets a blocker
    where either of them is missing;
  - the link is the relay: available and in the state the plugin set. A relay out of reach raises
    an alarm after 5 minutes, and gets the command again when it returns; no hand-back is attempted
    meanwhile, as it could not arrive. For relays this departs from "a lost link hands back"
    (2026-09-25) and from X2's stale-link hand-back;
  - a relay found in another state after a power or link loss (it was unavailable, or restarted)
    is sent the command again. So is a relay found back in the state it takes after a power cut, as
    the user declared it in the form, even when Home Assistant did not see it unavailable: that
    counts as a restart, and 3 restarts within 24 hours raise an information warning; a fourth
    within 24 hours counts as another controller — the plugin steps aside with a notification,
    setting the rest state once (the user, 2026-09-27, N). Where the state after a power cut is
    declared "last" or "I don't know", a change while the relay stayed available is taken as a
    possible restart and the command is sent again, up to 3 times within 24 hours; a further one
    counts as another controller in the same way (N). Otherwise only a change to another state while
    the relay stayed available — by an automation, a person or its own button — counts as another
    controller: rewritten once, then decision 6's reactions, never fighting (the user, 2026-09-27,
    C and D);
  - stepping aside because something else keeps switching the relay (an automation or the relay's
    own button) sets the relay once to its rest state — the full safe hand-back of answer H applies
    to relays too — and then leaves it alone (the user, 2026-09-27, L);
  - the tick "the boiler has its own room controller" (decision 3) counts as a working thermostat
    on the relay path only when the relay's rest state is "on" (the relay is the boiler's
    heat-demand contact); with the rest state "off", VT giving no answer means no heating and an
    alarm, as without the tick (the user, 2026-09-27, M);
  - the relay's state is checked at a fixed interval of a few minutes, listed with its reason (S-37),
    and the command is sent again on a mismatch only; blind repeats only for relays that report no
    state or switch themselves off after a time, at VT's repeat interval where one is carried over;
  - at hand-back the relay goes to the rest state the user chooses: "off" by default, "on" only when
    the user chose it, with its risk text; a notification when the rest state leaves the house
    without heating;
  - a planned restart of Home Assistant: the rest state, then the last command restored at once at
    start;
  - optional proof that the boiler heats (a flow-pipe temperature, the boiler's electric power, the
    gas meter) is information only; without it the status says "controlled without confirmation
    that the boiler heats";
  - the power criterion, for every write path (X3): a zone's mean power over its cycle, as VT counts
    it, but only while at least one calling zone has its valve open or its device active;
  - moving over from VT: the relay (where VT's commands name a switch or a boiler thermostat entity;
    otherwise the user picks it), the delay, the repeat interval and the thresholds (as VT actually
    used them) are pre-filled before the user unticks VT's central boiler, since VT then deletes
    them; control waits for the Home Assistant restart VT needs;
  - the setup texts recommend: the relay on the boiler's room-thermostat terminals, never in its power
    supply; the old thermostat kept in parallel and set low, with a note that valves VT drives stay
    where they were when Home Assistant is down, so its heat may not reach every room; the relay
    starting "off" after a power cut; optionally the relay's own switch-off timer, renewed by every
    "on" and set only when control starts; one test in summer.
- **The wall thermostat on a gateway** is not synchronised in 0.2.2. The form's texts say that while
  the plugin controls, the wall thermostat's heating setting and its off switch do nothing (its
  hot-water settings still work), and that after a hand-back or a Home Assistant outage it heats by
  its own setting and program. The plugin shows the temperature the wall thermostat would keep after
  a hand-back, from the optional signal it already has, and warns when that is unknown or low. A VT
  zone built on the gateway's own thermostat entity is refused: it would call for heat whenever the
  flame burns. Synchronisation, VT leading and off by default, comes in 0.3 at the earliest.
- **The user's answers of 2026-09-27 (A–O).** The details live in `docs/plan-0.2.2-details.md` (A).
  A ✅ mark and an addition to "Open after 0.2.2" are committed without waiting (B, see the rules).
  Relays: C, D, G, L, M and N under "On/off control" above; E, H and O in decision 6, O also in
  decisions 7 and 11; F and M in decision 3. If the plugin's own monitor fails for 5 minutes,
  control hands back; it resumes by itself once the monitor works again, with an information note
  (I). A "Reset comfort correction" button, in a new code file
  `button.py`, is approved (J). Confirmed as decisions (K): a lost or damaged store makes the plugin
  assume it was controlling and hand back first, and the monitoring period counts from the entry's
  creation; after a restart the control switch comes back as the user left it, and a switch entity
  disabled in Home Assistant means control off; the verdict "worth enabling" comes only from
  problems 0.2.2's control changes, the others shown as "not changed yet"; lifting the block on
  "off" as a low setpoint (decision 11) and on decision 1's low `CS` waits for the user at K4 even
  if the research is favourable; a gateway entry without an answer to the thermostat-terminals
  question keeps control stopped, with a notice asking for the answer.

## Decisions 1–16 (Q4 🔒)

Decisions 1–15 were taken on 2026-09-26/27; decision 16 waits for Z4, K4 and K5. A provisional
option — the most cautious one found — is written into `SCOPE.md` as provisional (Q1) and built so
that the user's answer changes one place in the code.

1. **OTGW with an on/off thermostat** (S-01, review question 4). The PIC keeps `CH=0` through `CS=0`
   and the override's lapse, so after a crash while "off" an on/off thermostat on the gateway cannot
   heat the house. *Decided:* both gateway topologies — with a thermostat and stand-alone — ask what
   is wired to the gateway's thermostat terminals: an OpenTherm thermostat, an on/off contact,
   nothing, or "I don't know". Control is blocked for an on/off contact and for "I don't know"; the
   monitor works as before. An answer that contradicts the topology (an OpenTherm thermostat with
   stand-alone, nothing with a thermostat) is refused in the form with a hint to pick the other
   topology. A gateway entry without an answer keeps control stopped, with a notice asking for it
   (answer K). "Off" as a low `CS` with `CH` left alone for such installations goes to K4 with L4
   (decision 11).
2. **The water's lowest temperature and the boiler** (S-02, Open after R6 #4). The hard minimum
   (25 °C) was justified by the emitters only; in mild weather the curve lands where many boilers
   short-cycle, and a non-condensing boiler condenses in its flue at a low return. *Decided:* one
   setting, the lowest water temperature (today's "lowest flow setpoint", 10–50 °C), set by the user
   like a curve setting; the lowest value depends on the curve, and a user may want it lower on
   purpose. Its default becomes 20 °C (the user's proposal, 2026-09-27; K4 confirms). Its text
   names both risks: too low — the boiler stops by itself again and again in mild weather, and a
   non-condensing boiler condenses in its flue (take the value from its manual); too high — warmer
   water than the rooms need. Where the plugin sets the water temperature it suggests or decides,
   as an option chooses; 0.2.2 has no such option yet, only "suggest": nothing changes by itself —
   the monitor shows its
   evidence of short burns at that temperature and a suggested value, which the user enters. "Apply"
   comes in 0.3, once the simulator shows it helps: its law checks that each step reduced short
   burns and steps back when it did not, within principle 8's tuning band. Where the boiler's own
   curve sets the water temperature, the plugin only suggests, never a parallel shift of that curve,
   and gives no suggestion while a stand-alone installation is handed back (nothing heats then);
   class 2 means suggestions only (S-56). Principle 13's rule 7 changes: values of a session (the
   comfort correction) reset at hand-back; learned properties of the boiler (the lowest water temperature
   learned in "apply") are kept, and reset by the user or when an input they rest on changes; the user's own
   entry is never reset (S-58).
3. **No zone known** (S-03, review question 1). "No zone known → heat on the curve" had no grace
   period, no season and no time limit, and applied with VT not loaded at all. *Decided:*
   - after Home Assistant starts or VT reloads, the recognition period: no new decision is taken. If
     the plugin controlled the boiler before the restart — a clean restart that handed it back
     included — its last command is kept, or restored at once, with its keep-alives; otherwise the
     plugin waits;
   - a grace period of 10 minutes for a zone that becomes unknown while VT runs: its last answer
     holds; after it the zone drops out and the known zones decide. This changes N3 of 2026-09-25
     (`SCOPE.md` §7) for the grace period. VT zones not started yet are recognised (a test with the
     vendored VT), and the grace also covers the "VT central boiler unknown" blocker during a VT
     reload, where VT's central boiler was known to be off just before (P-105);
   - when every zone is unknown after that, nothing asks for heat (decided 2026-09-27: "without VT
     and without a thermostat nothing can send the need for heat"). A **working thermostat** is a
     gateway with an OpenTherm thermostat declared on its terminals, the entity write path where the
     user ticked the new option "the boiler has its own room controller", or the relay path with
     that tick and the rest state "on" (the relay is the boiler's heat-demand contact); a relay
     resting "on" without the tick is not one, nor the tick with the rest state "off" (the user,
     2026-09-27, F and M). On a gateway the tick is not offered: a thermostat on the terminals
     already counts, and with nothing on the terminals a hand-back stops heating anyway (M). With a
     working thermostat the boiler is handed back to it, or to its own control (for a relay, its
     rest state "on"), after the grace; without one the plugin does not heat — its usual
     "off", for a relay the relay off, never its rest state — with no hand-back. Either way an alarm
     and a repair issue at once, with the monitor only too, and control resumes by itself when a
     zone answers again (after a hand-back: provisional, K4). This replaces "heat on the curve
     when no zone is known" (S-03), whatever the outdoor temperature; no summer switch of the
     plugin's own is needed.
4. **Frost protection and the valves** (S-05). A zone VT switched off keeps its valve closed, so heat
   for it cannot arrive. *Decided:* frost protection still watches every zone, or the one zone the
   user picks (N4), but heats only for a cold zone whose emitter can take heat — VT reports an
   opening above 0 or an active device; the mode alone is not enough. A cold zone VT keeps closed
   raises a repair issue in Home Assistant at once, without starting the boiler: it names the room
   and its temperature, says why the plugin cannot heat it, and what to do (VT's frost preset
   instead of "off"; VT's central frost mode needs a frost temperature in every thermostat). The
   plugin never switches VT's mode itself (rejected: it would fight VT). A zone whose valve state
   cannot be read is heated as today; a per-zone option "closes when VT switches it off" (off by
   default) makes it count as closed while VT has it off. The form states these conditions. This
   changes the decision of 2026-09-25 and `SCOPE.md`'s defaults row "the safety net covers the whole
   house".
5. **VT's activation delay** (S-07). *Decided:* carried over, as in VT 10.4.0: 0–600 s in steps of
   10, default 0. It delays switching on only. The wait starts at the first real call for heat,
   after the recognition period; a call that drops and returns during the wait neither cancels nor
   restarts it, and at its end the boiler starts only if demand is still there. Switching a running
   boiler off is immediate; a hand-back, control switched off or a blocker cancels a pending start.
   Frost heating waits too. No delay where the plugin controlled the boiler before a restart. Shown
   at the simple level and on the relay path; pre-filled from VT's stored value and shown for
   confirmation. The risk text
   names TPI pulses shorter than the delay, and a pump that may run anyway without a heating switch.
   It is one of principle 12's stated exceptions (Q1).
6. **Outside changes: what, where and when** (S-11, S-13, S-48, P-06, P-07, P-09, P-22; review
   question 2; decision 8 merged here). *Decided:* four classes.
   - **Lost command:** back to the state before the plugin, with a trace of an outage (the device
     unavailable just before, a gateway or device restart); with an OpenTherm thermostat, its own
     value after an outage counts too (an optional field). The plugin sends the command again, with
     no alarm; frequent losses raise a warning, never a hold. A single fall-back to the value from
     before the plugin with no visible trace of an outage is a lost command too: sent again and
     counted. A second such fall-back within 1 hour that no send explains counts as another
     controller. A send explains a fall-back when the fall-back comes before the plugin's latest
     send was read back as its value, or within 120 s of a send of a new value. The heating switch
     follows the same classes as the setpoint; this replaces "CH on/off outside the drop rule"
     (S-40). (The user, 2026-09-27, E.)
   - **Ignored from the start:** the boiler never takes the value. The plugin stops trying and says
     "the boiler does not accept the command — check the settings"; no block. A
     fall-back to the state before the plugin without a trace of an outage, repeated after every
     send from the start of the session (e.g. an OTGW override the boiler refuses, which
     `opentherm_gw` shows as confirmed, then dropped), stays here, not another controller (E). One
     exception: where the boiler ignores "heating off" from the start of the session (the heating
     switch's "off" is ignored from the start), control is blocked and the boiler handed back,
     with an alarm — like an installation without a working heating switch (decision 11); a
     blocker names the reason until the user switches control off and on after fixing it (the
     user, 2026-09-27, O). The same holds for a relay whose "off" is ignored from the start: control
     is blocked with an alarm, and the notification says the boiler may keep heating, as the
     relay's rest state cannot be relied on either (O applied to relays, 2026-09-27).
   - **Clipped:** the same lower value whatever the plugin sends. Accepted as the boiler's own limit;
     information only.
   - **Another controller:** rewritten once; a second change within a day makes the plugin step
     aside with a notification. Stepping aside is the full safe hand-back — the water to the lowest
     water temperature set, heating on where the boiler returns to a thermostat or its own control,
     then the release; a relay to its rest state, set once and then left alone (L) — even though it
     briefly writes over the other controller's value (the user's choice, 2026-09-27, H). After it
     the thermostat heats, or the
     other controller where one is active. Control stays latched — stored through reloads and
     restarts, with a repair issue — until the user switches control off and on, or returns by
     itself where the option below is on. The reaction "information" goes.

   An optional return by itself once the cause is gone (no foreign value for 1 hour), not offered
   for relays: off by default, described, confirmed twice. Held values, the heating switch's state
   included, are sent again after the device returns and every few minutes, with no echo required;
   a relay is checked
   first and written on a mismatch only (X8). This changes `SCOPE.md`'s "held — written on change
   only" and the drop rule of 2026-09-25 (`SCOPE.md` §7). The external-control switch is watched:
   switched off by a person, the plugin steps aside without a fight; off after a device restart, it
   is switched on again. Q1 writes out the full matrix of cases (target, path, write type, topology,
   source, moment, what the read-back shows, reaction).
7. **Which alarms may hand back** (S-30, S-62, review question 7). *Decided* for pressure and flue
   gas on 2026-09-27; the other rows as proposed on 2026-09-26, confirmed with this plan's change:
   - always: an internal error; the lost boiler link after 5 minutes (for a relay: an alarm and no
     hand-back, see "On/off control"); another controller as decision 6; the plugin's own monitor
     failed for 5 minutes, control resuming by itself once it works again, with an information note
     (answer I); the boiler ignoring "heating off" from the start of the session, with a blocker
     until the user switches control off and on (decision 6, answer O);
   - optional, information by default: the boiler ignoring any other write, and only where a
     thermostat or the boiler's own control takes over;
   - every other alarm informs. Stopping heating for a boiler fault follows the boiler's own logic
     (above). High pressure and hot flue gas get a notification saying what to do (the safety valve's
     rating read on the valve; water let out only with the heating off and cold);
   - only a known reading at the alarm level, held for about 5 minutes, counts; unknown values never
     do; a notification closes after about an hour back in the normal range;
   - an alarm with a hand-back reaction that is already active when control is switched on blocks
     control at once, and the switch's text says so;
   - an allow-list in the code: a new alarm informs by default; stored reactions no longer allowed
     are neutralised; every hand-back caused by an alarm raises a repair issue, and every latch,
     whatever its cause, the entry's one latch issue.
8. **The drop rule and a value never accepted** (Open after R6 #1, S-48): merged into decision 6.
9. **The fixed fallback** (S-26). *Decided (2026-09-27):* as the code does — with the outdoor
   temperature lost, the last value holds for 3 h, then the user's fixed fallback (or the design
   flow) replaces it; the specification follows.
10. **The circuit maximum and the boiler's overshoot** (S-14). The maximum limits the setpoint; the
    boiler may overshoot it. *Decided (2026-09-27):* the option text says what the maximum limits,
    and an alarm, information only, rises when the measured flow stays above an alarm temperature —
    a temperature value, not a margin — for the time the user sets. Both are the user's settings at
    the advanced level, pre-filled with a starting value (the circuit's maximum + 5 K, and 10
    minutes) so that they are never empty.
    The circuit's maximum itself stays the user's own setting (already required for underfloor
    heating on an unmixed loop). The alarm needs a flow reading; without one it is shown as
    inactive.
11. **"Off" as a low setpoint** (L4 of `docs/plan-0.2.1.md`, S-39). *Decided (2026-09-27):* control
    without a heating switch is blocked — such installations get the monitor — until Q3 shows that
    a low setpoint stops both the boiler and its pump and the user then lifts the block at K4, even
    when the research is favourable (answer K); the same holds for decision 1's alternative (a low
    `CS` with `CH` left alone). A boiler that ignores "heating off" from the start of the session is
    treated like an installation without a working heating switch: control is blocked and the
    boiler handed back, with an alarm, and a blocker names the reason until the user switches
    control off and on after fixing it (the user, 2026-09-27, O).
12. **A deviating outdoor sensor** (Open after R6 #7). *Decided (2026-09-27):* the curve takes the
    colder of the sensor and the weather entity, as `docs/plan-0.2.1.md` provisionally decided.
13. **Before 0.3: anti-cycling and principle 12** (S-18). Class 3 comes into 0.2.2 as VT's own
    central boiler works — no minimum on and off times and no cap on switchings per hour, which VT
    does not have either (the user, 2026-09-27: "as VT's native control works"); Q1 removes both from
    `SCOPE.md`'s class 3. Duty cycling, a start budget and an FC1 summer switch in `PLAN.md` 0.3 still
    contradict principle 12; `PLAN.md` marks them "to be decided against principle 12" (Q2).
14. **Tests with the real VT in CI** (P-119, review question 14). *Decided (2026-09-27):* CI fetches
    VT 10.4.0 and SmartPI 0.4.0 from their tags on GitHub's servers, so the real-VT tests run on
    every change; nothing is downloaded locally.
15. **J4 in the test HA** (review question 15). *Decided (2026-09-27):* an unclean restart and a lost
    link are provoked in the test HA's own container (e.g. `docker kill` over SSH), only in the test
    LXC and only after the user says to start (J4).
16. **The release** (review question 16, S-53). *Decided (2026-09-27):* which version is published
    first depends on how many problems 0.2.2 still has — decided after the independent check (Z4)
    and at K4; *provisional:* pre-release 0.2.2b1, then 0.2.2. Whether the public repository
    carries `CLAUDE.md`, the plans and the reviews (and so whether it starts from a clean history)
    is decided at K5.

The review's other questions get an answer in a step, which the user confirms or changes: 3 (X4),
5 (V1), 6 (V3), 8 and 9 (Y1), 10 and 19 (X5), 11 and 12 (Y3), 20 (Y4). Questions 13, 17 and 18 are
research (Q3).

## Findings of the checks of 2026-09-26

Read-only checks made for the decisions above found these defects, each assigned to a step:

- The OTGW keeps `CH=` until `CH=1` or a reset, while the code and the texts treat it as expiring
  (`control_config.py:208-209`, `core/loop.py:115-117`) → X6.
- A clean restart or reload while controlling resets the one-rewrite memory; only a crash keeps it
  (`control.py:974-981`) → X1.
- Each new setpoint value restarts the 120 s window, so a value another controller writes can be
  overwritten without being judged, and a read-back unknown when a value is sent hides another
  controller (`core/guards.py:319-335`) → X1.
- `write_ignored` clears on the setpoint's confirmation alone: one raised by the heating switch
  clears while the switch is still ignored, and without a setpoint target it never clears
  (`control.py:627-633`) → X1, X8.
- `unstable_ignition` counts short burns that end on temperature (`core/alarms.py:122-157`) → Y1.
- A hand-back reaction stored earlier stays active at the simple level, where the form no longer
  shows it; the menu only says that some hidden advanced settings are active
  (`config_flow.py:157, 1260-1261`) → Y1.
- With every zone unknown and no outdoor temperature for over 3 hours, the plugin heats at the design
  flow in any season (`core/controller.py:198-203`) → X3.
- Before its start, VT shows an over_climate zone as a known "off", and over_switch and over_valve
  zones as "not ready" → X3 (a test with the vendored VT).
- A VT zone built on the gateway's own thermostat entity calls for heat whenever the flame burns →
  X5.
- The plugin's power criterion drops a switch zone in the off part of its cycle, unlike VT
  (`core/demand.py:78-86`) → X3, X8.
- The "VT central boiler active" blocker clears without the restart its text asks for
  (`vtherm_link.py:185-199`) → X7.
- Flame and flow are required for the whole entry, so a home with only a relay cannot even be
  monitored (`core/signals.py:64-65`, `config.py:194-196`) → X8.
- At hand-back the heating switch is turned on whatever the wiring, which leaves a relay boiler
  heating without control (`transport/writers.py:184-193`) → V5, X8.
- The default low-pressure alarm (0.7 bar) lies above many boilers' own cut-offs, so a stop on it
  would stop heating before the boiler does → Y1 (the stop follows the boiler's own fault).
- The optional wired-thermostat setpoint is read but not used to show the fallback
  (`config_flow.py:93-94`) → X6.

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
- Every change to a `*.md` file is shown as a diff and waits for the user's consent, except a ✅
  mark on a finished step and an addition to "Open after 0.2.2": those are committed without
  waiting, and their diff is shown in the step's report (the user, 2026-09-27, B).
- All findings and results are saved locally in the working directory (`research/` for notes and
  raw results).

## Phase Q — specification, plans, research, decisions

Why: the specification has to say what the code will do before the code changes; 62 of the review's
problems are the specification's own, and some questions need facts from the devices' and Home
Assistant's sources.
In practice: `SCOPE.md`, `PLAN.md` and the plans say what 0.2.2 does; the research is kept in
`research/`; the user's decisions are recorded.

| Step | Work |
|---|---|
| Q1 | `SCOPE.md`, `PLAN.md` and `CLAUDE.md` take the decisions of 2026-09-26/27, the answers of 2026-09-27 and the provisional options still open, and each specification problem of the review is settled in the text or assigned to a step (index): the missing-data rule; principle 12's stated exceptions, each with its reason — frost protection (as now), the recognition and grace periods and "no heating when VT gives no answer and no working thermostat is there" (decision 3), the activation delay (decision 5), the stop on the boiler's own fault, the hand-backs decision 7 allows — replacing "frost protection is the one exception"; principle 13's rule 7 (decision 2); class 3 in 0.2.2 without minimum times or a switching cap, with the link, the read-back and the rest state of a relay (X8); the matrix of outside changes (decision 6), with the changed drop rule, "held" resent every few minutes, and no hand-back retries against another controller; the wall thermostat's texts. Text only: "unknown" is written and counts once read back (S-28); SmartPI's promised signals and the Auto-TPI pause marked for a later release — Auto-TPI "detected, not paused" (S-29); a circuit takes its zones' emitter types (S-33); one term for the device and zone count, with a note for users coming from VT (S-36); the fixed thresholds and times listed with their reasons (S-37); switch zones follow VT's device state, one start per TPI cycle (S-38); the heating switch under decision 6's classes, like the setpoint (S-40); units of the options (S-44); settling an owed hand-back by hand (S-45); the ramp's rationale (S-47); principle 9 for SmartPI, which learns its own outdoor term (S-50); removing the entry: a last attempt and a persistent issue, no veto (S-54); class 2's persistent writes dropped, class 2 getting suggestions only (decision 2, S-56); principle 13 resets only session values, says which rule values may be options, and the source chain is clarified (S-58); the internal contradictions (S-59); each feature without a release gets one or goes (S-60); learning pauses under the control stages (S-61); the alarms that have a reaction (S-62); the risks of "held" (S-12); the activation delay (S-07). Details: plan-0.2.2-details.md, Q1. |
| Q2 ✅ | plan corrections: stale texts in `docs/plan-0.1.md`, `docs/plan-0.2.md` and `PLAN.md` (S-46); J2: the firewall rule in `devenv/README.md` also on the forwarding path (`DOCKER-USER`) and for IPv6, with the check T-25 (S-19); J4: its existing scenarios revised to the decisions of 2026-09-26/27; a held device that restarts (S-13), starts under control against the boiler's own regulation (S-15, T-24), control refused for an on/off contact or "I don't know" on the thermostat terminals, the simulator showing why (T-07); K1: the README also covers removal, how often data update, troubleshooting, known limitations and supported devices (S-52); Z2 sets the manifest to 0.2.2b1, K5 publishes it and K7 sets the release version (S-53); in `docs/plan-0.2.1.md`: M4's removal text (S-54), N5's text part reopened (S-50), "After 0.2.1" pointing to this plan, "Done" worded as "after the fixes an independent check finds none" (S-55), L4 marked ✅ with the decision of 2026-09-27 (decision 11); `PLAN.md` 0.3 items marked for decision 13 (S-18); J4 also: a relay that restarts or loses Wi-Fi, the wall thermostat after a hand-back, an unclean restart and a lost link provoked in the test container (decision 15); K1 also: the relay setup recommendations; `PLAN.md`: on/off-only boilers (relay) moved from "Later" into 0.2.2, and in 0.3 the wall-thermostat link and the "apply" mode of the lowest water temperature. Details: plan-0.2.2-details.md, Q2. |
| Q3 | research over the network, kept in `research/`: which VT version first loads external feature managers (review question 13, P-60); whether OpenTherm boilers raise a `CS` below their minimum CH setpoint (ID 49) and fire, and whether `CS` = 10 °C means "no demand" (question 17); whether a low setpoint with CH left enabled also stops the CH pump, on typical boilers and on ESPHome, DIYLess and EMS-ESP masters (decision 11); whether Home Assistant's shutdown stage leaves time for the slowest hand-back (question 18); a generic rule tying the lowest water temperature to the boiler's minimum power, for the suggestion (decision 2, S-02); how soon an ESPHome device reports its value after a start (P-50); how the OTGW firmware over MQTT shows a gateway that drops and a broken link between the ESP and the PIC (Open after R6 #8); `research/diy/INDEX.md` completed for `gateway-6.6.asm`, or the file removed (S-51); which boilers report the low-water-pressure fault over OpenTherm and whether the gateway reads it, and which Home Assistant entity carries the boiler's own faults on each path (boiler protection); how a PIC reset, an ESP restart and a Data-Invalid reply to ID 1 show through `opentherm_gw` and the firmware's MQTT (decision 6's trace of an outage); whether a Shelly relay's switch-off timer restarts on a repeated "on" — moved to K6, where the user checks it on their own relay if they have one (never at J4, which uses the simulator); until then the relay texts say it is not documented, and Q3 is ✅ without it. Web sources read as pages only: the web tool saves a fetched PDF outside the project. Details: plan-0.2.2-details.md, Q3. |
| Q4 🔒 | the user takes decision 16 — the first published version after Z4 and at K4, the repository's content at K5. Decisions 1–15 and L4 of `docs/plan-0.2.1.md` were taken on 2026-09-26/27, answers A–O on 2026-09-27. Details: plan-0.2.2-details.md, Q4. |

Done when: the specification states every decision and every provisional option, the plans have no
stale step, and the research answers are in `research/`.

## Phase V — control state that survives, hand-back, the stop button (review §7, 1 and 2)

Why: the plugin's memory of holding the boiler is lost on the unhappy paths — a corrupt store reads as
a new installation, a failed setup reports no owed hand-back, a crash loses a delayed save — and the
control switch goes unavailable exactly when the monitor fails.
In practice: the control state is written at once and atomically, and read cautiously; every owed
hand-back is sent or shown; a hand-back counts only when confirmed; the switch always works.

| Step | Work |
|---|---|
| V1 ✅ | the store: the control state kept in a small store written at once with atomic writes (or a second copy); a store lost, damaged or read as `None` for an entry that ran before means "was controlling" — a full hand-back first (answer K); one policy for an unreadable store in setup, removal and the options flow; nothing saved before the store was read; the monitoring period counts from the entry's creation (`ConfigEntry.created_at`), so a lost store does not restart it (P-01, P-04, P-58; T-08 with a real truncated file, T-10, T-35; review question 5). Details: plan-0.2.2-details.md, V1. |
| V2 ✅ | a setup that fails: an owed hand-back is sent first, by a hand-back unit built before anything that can fail, and reported by a persistent issue if it is still owed when setup gives up; the forecast load best effort; the code after setup's `try` guarded; options saved while the entry is in setup error reload it (P-05, P-33, P-57; Open after R6 #6: C14, H9; T-09, T-11). Details: plan-0.2.2-details.md, V2. |
| V3 ✅ | saved at once: the last command given to the boiler (heating on or off, the water temperature), so it can be kept or restored after a restart (decision 3, X8); the SmartPI pause, before the service call, and its resume when control leaves the options; the user's on/off wish in the entry's store, so the switch comes back after a restart as the user left it, and a control switch disabled in Home Assistant means control off (answer K); an internal-error latch outlives a restart (P-10, P-11; Open after R6 #6: C10, C15; T-29, T-31, T-39; review question 6). Details: plan-0.2.2-details.md, V3. |
| V4 ✅ | the hand-back's bookkeeping: the owed marker set before every attempt, whatever interrupts it; an end-of-session hand-back is full while an older debt exists; releasing an owed hand-back (repair) serialised with a running attempt; the hand-back blocker checked again when the options are saved; the write coroutine created only when awaited; a device that reports late (ESPHome, MQTT) gets a short wait at start and stop before a hand-back counts as failed; a pyotgw command that times out while the gateway is connected does not count as done; the owed hand-back's retry, the stale-link hand-back and the decision interval not held up by a wall clock set back (P-12, P-42, P-49, P-50, P-51, P-52; Open after R6 #8; T-05, T-06, T-13, T-14). Details: plan-0.2.2-details.md, V4. |
| V5 ✅ | the safe hand-back (decision of 2026-09-26/27), stepping aside from another controller included (decision 6, answer H): the water to the lowest water temperature set, heating on where the boiler returns to a thermostat or its own control, then the release, one after another without waiting for a read-back; where a device keeps the last value (a target declared "held") and the release is not confirmed, an alarm at once and retries until it is; a target another controller holds counts as handed back, with no retry every minute. What confirms a hand-back: one rule for writes and hand-back on `opentherm_gw` — control waits until the read-back has a value (P-21); an entity with `assumed_state`, or without an independent report, is "unconfirmed" and says so (S-09, T-30); a "timeout" hand-back is confirmed by the read-back returning to the value before the session within the lapse time, else it stays owed (S-20); the order of the heating switch and the value per write type, and no heating switched on where the effect is "heating stops" (S-27); the hand-back value within the circuit maximum and the hard maximum (S-21); the external-control switch gets a declared write type, and a persistent one is not used (P-40); "off" refused within 0.5 K of a hand-back value that means the boiler's own control (S-49). Details: plan-0.2.2-details.md, V5. |
| V6 | the stop button: control entities' availability follows the control unit, not the monitor; an exception in the monitor's fast path is caught, logged once with a traceback and once at recovery, and reported as `UpdateFailed`; control hands back if the monitor stays failed for 5 minutes, and resumes by itself once it works again, with an information note (answer I; P-02, P-24; T-15, T-54). Details: plan-0.2.2-details.md, V6. |
| V7 | stopping with an alarm: a blocker that stops control while it held the boiler raises an alarm or repair issue where the hand-back's effect is "heating stops" (S-10); after a stand-alone hand-back the switch says frost protection now rests on the boiler, and an alarm rises when it stays handed back in frost (S-57); the reaction "information" to an outside change goes (S-11): stepping aside is the full safe hand-back, latched and stored, with a repair issue (decision 6, answer H); decision 6's classes are built in X1. Details: plan-0.2.2-details.md, V7. |

Done when: T-05, T-06, T-08–T-11, T-13–T-15, T-29–T-31, T-35, T-39 and T-54 pass, and every unhappy
path the review names ends with the boiler handed back, with the hand-back owed and shown, or —
once X3 is built — with the last command kept or restored under decision 3.

## Phase X — control and configuration (review §7, 3 and 5)

Why: the guards and the link watch forget too easily, a few demand criteria can go silent, and the
form accepts combinations that toggle a switch for ever or never confirm a hand-back.
In practice: the guards keep their memory for the session, a flapping link is caught, and every
dangerous combination the review found is refused in the form and among the blockers.

| Step | Work |
|---|---|
| X1 | the guards: their memory (the block, the baseline) kept across hand-backs inside a session, reset only at its end, and the one-rewrite memory kept for its day, through a clean restart too and through switching control off and on (provisional, K4) (P-06, T-01); the baseline learned from the first known read-back that is not the plugin's value (P-07, T-02); "ignored" tracked per guard, so a boiler ignoring CH on/off is reported (P-09, T-04); an alarm together with a transient blocker latches (P-48, T-49); a hand-back passes while a guard is blocked (T-19); a setpoint entity with a step above 1 K refused, the value rounded inside the limits and compared after rounding (P-15, P-98, T-55); "off" at least 1 K below the hard minimum (P-43); a held device that returns from unavailable with its initial value rewritten without counting an outside change (S-13, T-47); the heating switch under the same classes as the setpoint, a switch and a setpoint falling back together counted as one loss (S-40, answer E); decision 6's classes — lost command (a single fall-back without a trace included; a second within 1 hour that no send explains is another controller, answer E), ignored from the start (where it is the heating switch's "off", control blocked and the boiler handed back with an alarm, the blocker naming it until the user switches control off and on, as decision 11; answer O), clipped, another controller (stepping aside with the full safe hand-back and a latch, answer H) — with the optional return by itself (not for relays), held values sent again after a device returns and every few minutes with no echo required, and the external-control switch watched (S-11, S-48); a value another controller writes judged even while the plugin's value keeps changing or the read-back was unknown at the send; `write_ignored` cleared per guard. Details: plan-0.2.2-details.md, X1. |
| X2 | the boiler link and freshness: staleness judged over a window, so a link fresh one step in five still hands back; `boiler_link_lost` raised whenever the control switch is on, whatever blockers or a latch show, and the link is stale beyond the limit — after a restart, a blocker, or switching on with the link down — and kept while it lasts; each signal's own age limit, the flame's included, and the weather entity's own (P-08, P-41; T-03, T-26); a silent MQTT drop and a broken link between the ESP and the PIC shown as far as Q3 finds the firmware allows (Open after R6 #8). Details: plan-0.2.2-details.md, X2. |
| X3 | demand and zones: the opening threshold over the calling zones only (P-13, T-46); a VT device power ≤ 0 is no data, and a criterion no zone can feed is refused in the form; at run time such a criterion counts as without data — the zones' demand is judged as for unknown zones (decision 3), with an alarm naming the missing input (P-14, T-27); the power criterion, for every write path: a zone's mean power over its cycle, as VT counts it, but only while at least one calling zone has its valve open or its device active (`core/demand.py:64-65, 78-86`); control requires at least one VT zone (S-04); a zone whose mode is "off" has no demand whatever `is_ready` says, once the recognition period is over (S-34, T-17); VT's `safety_state` read as a lost sensor for the zone alarm (S-35, T-44); power shedding removes a zone's demand (T-45); the reference room and the critical zone skip zones with a lost sensor or not ready (P-18); an implausible room temperature of a watched zone is unknown, with the same alarm after its limit, and one plausibility rule for room temperatures (S-06); decision 3: the recognition period, the grace period with VT zones not yet started recognised and the P-105 blocker covered where VT's central boiler was known to be off just before, and, with every zone unknown after the grace, a hand-back to a working thermostat (decision 3's definition, with the new option "the boiler has its own room controller", offered on the entity and relay paths and not on a gateway, and counting on the relay path only with the rest state "on"; answers F and M), else no heating — the usual "off", for a relay the relay off, never its rest state — with an alarm and a repair issue at once (with the monitor only too), control resuming by itself when a zone answers again, replacing "heat on the curve" and the design-flow heating of `core/controller.py:198-203, 395-396` in that case (S-03, T-28). Details: plan-0.2.2-details.md, X3. |
| X4 | frost, fallback, ramp, correction, learning pauses, activation delay: frost protection as decision 4 — heat only for cold zones that can take it, a repair issue for a cold zone VT keeps closed (S-05); VT's activation delay as decision 5 (S-07); `frost_since` reset at hand-back (P-45); FALLBACK shown only while heating (P-47); the fixed fallback as decision 9 (S-26); the ramp skipped only for installation limits — the hard maximum, a circuit, the boiler — not for a falling weather ceiling (S-23); the circuit maximum as decision 10 (S-14; T-20 in Z3); the comfort correction: "heat flows" means the flame when known, else the command (S-24, review question 3), the no-rise rule counts only zones taking heat (S-08), every rule of principle 13 mapped, with a freeze while a cap holds the setpoint (S-25, T-48), no rise with the clock set back (P-46, T-18), its value published and resettable with a "Reset comfort correction" button in a new code file `button.py` (P-38, answer J); learning pauses per cause — the flow condition and the one-hour cap each where it belongs (P-89); a hot-water draw still pauses SmartPI, as the zones get no heat meanwhile, and the specification says so (S-41). Details: plan-0.2.2-details.md, X4. |
| X5 | configuration, refused in the form and, for hand-edited options, among the blockers: the same entity as heating switch and hand-back switch, or the setpoint entity as hand-back switch (P-03, T-38); one entity for two signals, unless it may feed both (P-16, T-32); "off" against the hard minimum at the simple level and after "restore defaults" (P-25); the path and topology pairing (P-44); the MQTT or `opentherm_gw` integration set up and enabled (P-69); an option value this version does not know (P-70); entity domains and integrations checked on the server, zones VT climates only (P-79, review question 19); cross-field checks of the design flow, the room, the hard maximum and the design outdoor range (P-68); the gateway field without custom values (P-106); removing a circuit that has zones (P-64); "restore defaults" keeps the monitoring days, or says it does not (P-65); an options edit that would block control (the boiler class, a second circuit, fewer zones than the count threshold, underfloor without a maximum flow) warned and confirmed before it is saved (Open after R6 #3); a save that does not touch control reloads without a hand-back, or the options say it hands back (P-67, review question 10); a passive fixed circuit's floor with a margin (S-42); the risks of "held" in the option (S-12); control without a heating switch blocked, such installations getting the monitor, until Q3 shows a low setpoint stops the boiler and its pump and the user lifts the block at K4 (decision 11, S-39); a boiler that ignores "heating off" from the start of the session blocked in the same way, the blocker naming the reason until the user switches control off and on (answer O, with X1); one list of the options' keys (P-71); the flow's own paths tested (T-12, T-37); a VT zone built on the gateway's own thermostat entity refused; the per-zone option "closes when VT switches it off" (decision 4). Details: plan-0.2.2-details.md, X5. |
| X6 | the two high specification problems: both gateway topologies ask what is wired to the thermostat terminals, and control is blocked for an on/off contact or "I don't know"; a gateway entry without an answer keeps control stopped, with a notice asking for the answer (decision 1, answer K, S-01; T-07 in Z3); the OTGW's `CH=` given the write type "held" — kept by the PIC until `CH=1` or a reset, not persistent, so the heating switch stays usable — in the code (`control_config.py:208-209`, `core/loop.py:115-117`) and the texts; the lowest water temperature as one setting (today's hard minimum), default 20 °C, with both risks in its text, and its "suggest" mode — the monitor's evidence of short burns at that temperature and a suggested value the user enters — in 0.2.2 a suggestion only, never applied, both where the plugin sets the water temperature and where the boiler's own curve does, then worded for the device that sets it and never a parallel shift (decision 2, S-02, S-56); the wall thermostat's fallback temperature shown from the existing optional signal, with a warning when it is unknown or low, and the form's translated texts on the wall thermostat (its heating setting and off switch do nothing while the plugin controls, its hot-water settings still work; after a hand-back or an outage it heats by its own setting and program); an answer about the thermostat terminals that contradicts the topology refused in the form. Details: plan-0.2.2-details.md, X6. |
| X7 | VT: a VT central entry the user disabled means no VT central boiler, unless VT's central boiler was seen configured earlier in the same Home Assistant run (then "VT central boiler active" holds until the restart, as VT's stale manager may still switch the boiler); one stuck in setup error with its central boiler on keeps control blocked, as VT's manager may still switch the boiler, and raises a visible issue after a time limit (provisional, K4) (P-20, T-52); reloading VT's central entry uses the entry's stored data rather than handing back (P-105); an unknown VT central-boiler state leaves the Auto-TPI issue unchanged (P-54); the "reload VT" repair skips unavailable or not-ready zones (P-59); a VT without external feature managers detected by its version (P-60, from Q3); entity renames followed through the entity registry, or a repair issue (P-19); the public attribute `hot_water` renamed `heat_available` before the first release (P-61); the `smart_boiler` attribute on VT climates changed only on a real change (P-63); registration errors never reach VT (T-53); the "VT central boiler active" blocker kept until the Home Assistant restart its text asks for. Details: plan-0.2.2-details.md, X7. |
| X8 | on/off control (class 3), as decided on 2026-09-26/27: the write path "relay" (a switch, or a boiler thermostat entity between heat and off) for on/off boilers, the water-temperature parts hidden; the relay's own settings asked in the form (its state after a power cut, its switch-off timer, whether it reports its state), and the tick "this is a separate relay contact, not a setting stored in the boiler's memory", without which control does not start (answer G); flame and flow optional for the entry, with a blocker for water-temperature control where either is missing; the link is the relay — the alarm after 5 minutes out of reach, the command sent again on its return, and no hand-back meanwhile (an exception to X2's stale-link hand-back, `core/controller.py:249-257`); a relay found in another state after a power or link loss, or back in its declared power-cut state, sent the command again, with an information warning at 3 such restarts within 24 hours and a fourth within 24 hours treated as another controller; with the power-cut state declared "last" or "I don't know", a change while it stayed available taken as a possible restart and sent the command again up to 3 times within 24 hours, a further one treated as another controller (answer N); otherwise one switched to another state while it stayed available treated as another controller (answers C, D); stepping aside sets the relay once to its rest state, then leaves it alone (answer L); the "own room controller" tick counting as a working thermostat only with the rest state "on" (answer M); its state checked at a fixed interval; a relay that reports no state controlled with blind repeats and shown as "controlled without confirmation"; the rest state at hand-back ("off" by default, "on" only when the user chose it, with its risk text) and a notification when it leaves the house without heating — the hand-back never switches a relay on otherwise, unlike today's heating switch (`transport/writers.py:189-193`, S-27); the last command restored at once after a planned restart; optional proof that the boiler heats; the power criterion as in X3; the migration from VT's central boiler, with the restart it needs; the setup texts; `write_ignored` clearing without a setpoint target; the activation delay shown on the relay path (decision 5); no return by itself for relays (decision 6); tests for each, with missing and unknown inputs. Details: plan-0.2.2-details.md, X8. |

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
| Y1 | alarms: "pressure 0 = unknown" only for the gateway's sources (P-17, T-33; review question 8); an alarm whose input is unknown or cannot be judged holds its state for a short time (proposed: 1 h), then shows `unknown` (S-16, T-34; review question 9); a stuck outdoor sensor judged on the tail since its last change (P-26, T-16); the low-flow warning not judged with hot water unknown on a boiler with DHW (P-27), and why it is unavailable shown (P-99); hysteresis-drift samples only from pauses with demand throughout (P-29); unstable ignition without the burns the boiler's own hysteresis ends (P-81); `frequent_starts` and `unstable_ignition` with hysteresis (P-82); the flue-gas trend entity created only where the trend is computed (P-85); the CH echo's text names the right `opentherm_gw` entity, tested with hot-water draws (P-22, T-21); decision 7 — the allow-list, the alarm level held for a few minutes, stored reactions no longer allowed neutralised, a repair notification for every alarm hand-back or latch (S-30, S-62); heating off (no hand-back, no latch, frost heating included) only while the boiler reports its own low-water-pressure fault, or another fault the boiler reports as stopping it — two new optional signals the user picks, where only a known "on" held for a few minutes counts and unknown or unavailable counts as no fault; without such a report an "add water" notification at a threshold the user enters from the boiler's manual, none by default, replacing today's 0.7 bar (`core/alarms.py:67`); a broken or silent pressure sensor never stops heating; notifications saying what to do for high pressure and hot flue gas, closing after an hour in the normal range; the pressure trend judged with the water temperature taken into account, so a slow leak shows in winter too — "there is a risk of a leak" (Open after R6 #5; in 0.2.2, the user's decision of 2026-09-27). Details: plan-0.2.2-details.md, Y1. |
| Y2 | cycles, gas and days: hot water inferred on weaker evidence, or unknown when the evidence conflicts (P-28); burns across midnight complete (P-83); metered gas split in one pass (P-84), and bounces counted once by one function (P-97); other gas consumers on the meter subtracted or reported apart (S-31); day summaries replace a stuck outdoor sensor by the weather (P-86); a narrower settings key, so an unrelated option keeps the stored days (P-87); forecast errors only for hours observed (P-88, T-40); the importer normalises 23 and 25 h days, rejects a zero or reversed window and does not grow quadratically (P-93, P-111; Open after R6 #6: A13); Home Assistant's downtime unknown (P-95; A11); days under control tagged now (P-96; A12); the analysis reads the backfill state with its copy (P-53); pruned forecast partitions not recreated (P-56); burns classified per analysis, not at every step (P-80). Details: plan-0.2.2-details.md, Y2. |
| Y3 | building model and verdict: the heating threshold with its own uncertainty and a wider spread required (P-31, T-41); the heat loss fitted alone only with an entered or confident threshold (P-32, T-42); the measured threshold shown and resettable (P-90); stored days keep the temperature distribution, not one load model (P-91); an entered design load always wins, and the texts say so (P-92, review question 12); installation warnings shown, or removed (P-94); the load criterion counted only with an entered or confidently measured model (S-17, T-43); the verdict "worth enabling" comes only from problems 0.2.2's control changes, the others shown as "not changed yet" (S-22, answer K); "not worth it" only with at least a set number of criteria judged (S-32); off-season monitoring: the switch says control starts without a verdict (S-43); bounded learning covers what control uses, while the building model feeds the monitor only and is visible and resettable (review question 11). Details: plan-0.2.2-details.md, Y3. |
| Y4 | Home Assistant: forecast snapshots parsed in the executor, and only what is used kept (P-23, T-36); `weather.get_forecasts` skipped while the entity is unavailable, and with a timeout (P-55); diagnostics redact options given as any mapping (P-30, T-50) and work for an entry in setup error (review question 20); verdict reasons, control reasons, blockers and `latched_by` translated (P-39), `critical_zone` states (P-73) and exception placeholders (P-74) too; the gas-per-degree-day unit shown only once the meter's unit is known (P-75); unused texts removed, with a reverse key-parity test (P-76); `ceiling_band`'s text (P-66); the freshness step's field descriptions (P-103); entity names without the device name (P-104); timestamps in ISO (P-78); `change_report` and `forecast_snapshots` created only with their data (P-100); continuous attributes dropped or coarsened (P-72); a typed `ConfigEntry` alias (P-101); the percentage unit Home Assistant 2026.7 asks for (P-102); dead code removed (P-62); docstrings placed and updated (P-77, P-116); every feature whose input is missing shown as inactive, naming the missing input in a translated text, with a test for each feature (the missing-data rule). Details: plan-0.2.2-details.md, Y4. |

Done when: the phase's §6 tests pass, and no alarm shows "OK" on an input it cannot judge.

## Phase Z — tests, tools, simulator, check

Why: several safety paths have no test, CI measures neither branches nor modules, the simulator
cannot run J4's main path, and 0.2.1's lesson is that an item is closed only when every scenario of
it is.
In practice: the missing tests, CI as strict as the local run, a simulator ready for J4, and an
independent check of the fixes.

| Step | Work |
|---|---|
| Z1 | tests: the §6 tests not in a step above (T-22, the MQTT hand-back before MQTT stops; T-51, cancellation); the config and options flows at 100 % (P-34); a backfill with zones (P-117); the allowed-services checks spy on `hass.services.async_call`, the switch domain included (P-118); core tests without the Home Assistant pytest plugin (P-120); weak assertions made exact (P-121); the MQTT path with `mqtt_mock` (P-122); listeners after unload (P-123); migration, and a newer entry refused (P-124); one entry per test of a single-entry integration (P-125; Open after R6 #6: T11); VT safety, shedding, window and "off" not ready as scenarios (P-126); every default of the SCOPE table pinned (P-127); a whole-value `[%key:…%]` refused (P-128); the safety-critical functions split only after table-driven precedence tests (P-115); with P-120's two pytest runs, CI and the commit rule in `CLAUDE.md` (its diff waiting for consent) name both runs, `ruff format --check` and mypy. Details: plan-0.2.2-details.md, Z1. |
| Z2 | tools and CI: coverage with branches, per module, at least 95 % in each module and 100 % for the flows (P-35); current major versions of the actions (P-110); a job with the latest `vtherm_api` (P-109); the real-VT tests as decision 14 (P-119); the deploy's dry run does not read `devenv/local.env` (P-107); `session-summary-*.md` git-ignored (P-108); the manifest's version and `tests/test_release.py`'s `RELEASE` set to 0.2.2b1, decision 16's provisional first version (S-53). Details: plan-0.2.2-details.md, Z2. |
| Z3 | the simulator before J4: a route for the `opentherm_gw` path in the test HA — the MQTT path, or a test-only entry — decided and documented (P-37, T-23); a boiler that regulates its own flow, emitter inertia, daily sums kept (P-112); only persistent writes counted as persistent, CH writes counted (P-113); switch zones driven by `on_percent` over a cycle, and the J4 scenarios reachable (P-114, T-24); off zones close their valves (S-05); a hot-water draw under control in a closed loop (P-36, T-21); starts under control against the boiler's own regulation (S-15); the gateway's read-back as `opentherm_gw` shows it, and a heating switch with its own write type (Open after R6 #2); the PIC's `CH=0` flag with an on/off thermostat (T-07); the circuit maximum with underfloor heating (T-20); a relay with its start-up state, a switch-off timer, a restart and a Wi-Fi loss, and a boiler with its restart lockout and pump overrun (X8); a wall thermostat with its own setting, program and override rules (X6). Details: plan-0.2.2-details.md, Z3. |
| Z4 | an independent read-only check of 0.2.2 by a fresh subagent: each problem of the review checked against every scenario of its row, not only its test, and every decision and answer of 2026-09-26/27 (X8 included); its report kept in `research/` and summarised to the user; a finding of the check fixed with a test and checked again by another fresh subagent, until a check finds no critical or high problem. A multi-agent review only with the user's go-ahead. Details: plan-0.2.2-details.md, Z4. |

Done when: the "Done for 0.2.2" list below holds.

## Open after 0.2.2

Left on purpose for a later release:

1. Radiators and underfloor behind a mixing valve as one written circuit plus passive fixed circuits
   (S-42, its second part) — 0.3.
2. Anti-cycling in 0.3 against principle 12 (decision 13).
3. The wall thermostat linked to a VT zone, VT leading and off by default — 0.3 at the earliest.
4. The "apply" mode of the lowest water temperature (decision 2) — 0.3, once the simulator shows
   it helps.
5. Relay commands beyond a switch and a boiler thermostat entity (VT's free-form actions) — later,
   if asked.
6. Still 🔒 from `docs/plan-0.2.1.md`: R2 (the icon). "Off" as a low setpoint (L4, decision 11) and decision
   1's low `CS` with `CH` left alone stay blocked until the user lifts the block at K4, on Q3's
   research, even if it is favourable.
7. SmartPI's further signals and the Auto-TPI pause (S-29) — release set at K4.
8. The features without a release that Q1 gives a later one (S-60), each with its release.
9. A warning for zones the boiler does not feed — air conditioners in heat mode, electric heaters
   (review question 19, its second half) — 0.3.
10. A recorded "heating commanded" entity and event for users leaving VT's central boiler — 0.3.
11. A wiring field for the relay (alone, parallel, series) — later, if asked.
12. Whether a Shelly relay's switch-off timer restarts on a repeated "on" (Q3.10) — K6, on the
    user's own relay if they have one; until then the relay texts say it is not documented.
13. A broken link between the OTGW firmware's ESP and its PIC is not visible through Home
    Assistant (the firmware keeps its connection flags on by design, Q3.6); X2 keeps
    "availability only" and the option's text says so — later, if the firmware gains a signal.
14. A held target whose hand-back value means "the device's own control resumes", read back from
    the boiler, never shows that value: each such hand-back alarms for 2 min and ends as "taken by
    another controller" with a repair issue (V5) — K4 decides whether the device's own value
    counts as the release.

What a step leaves open is added here by name, as the rules say.

## After 0.2.2

The open steps of `docs/plan-0.2.md` follow: J2 🔒 (with Q2's firewall check), J4 🔒 (with Q2's
scenarios, in the test HA with the simulator only), K1 🔒, K2 (its validation once the repository
exists), K4 🔒 (the review of the control laws, with decision 16, the values marked provisional, the
answers steps gave to review questions 3, 5, 6, 8–12, 19 and 20, and whether to lift the block on
"off" as a low setpoint (decision 11); the 0.2.1 change log read together with
`docs/review-2026-09-26-vs-0.2.md`), K5 🔒 (public repository, pre-release 0.2.2b1), K6 🔒 (with the
Shelly timer check on the user's own relay, Q3), K7 🔒 (the release version, decision 16).

## Done for 0.2.2

- Every problem of `docs/review-2026-09-26.md` fixed, moot by a recorded decision, or named in "Open
  after 0.2.2" with its release (index).
- Every decision of 2026-09-26/27 and every answer of 2026-09-27 built as its step says, or named
  in "Open after 0.2.2".
- The tests (both runs, with and without the Home Assistant pytest plugin, P-120), `ruff check`,
  `ruff format --check` and mypy strict pass; coverage with branches is at least 95 % in every
  module and 100 % in the config and options flows.
- The in-process acceptance scenarios pass, the new ones included — Z3's, and those of Q2's J4
  additions that can run in-process.
- After the fixes, an independent check (Z4) finds no critical or high problem, and the fixes of its
  own findings are checked again.

## Index: review problem → step

Problems (code and tests): P-01 V1 · P-02 V6 · P-03 X5 · P-04 V1 · P-05 V2 · P-06 X1, Q4 (6) · P-07 X1, Q4 (6) ·
P-08 X2 · P-09 X1, Q4 (6) · P-10 V3 · P-11 V3 · P-12 V4 · P-13 X3 · P-14 X3 · P-15 X1 · P-16 X5 · P-17 Y1 ·
P-18 X3 · P-19 X7 · P-20 X7 · P-21 V5 · P-22 Y1, Q4 (6) · P-23 Y4 · P-24 V6 · P-25 X5 · P-26 Y1 · P-27 Y1 ·
P-28 Y2 · P-29 Y1 · P-30 Y4 · P-31 Y3 · P-32 Y3 · P-33 V2 · P-34 Z1 · P-35 Z2 · P-36 Z3 · P-37 Z3 ·
P-38 X4 · P-39 Y4 · P-40 V5 · P-41 X2 · P-42 V4 · P-43 X1 · P-44 X5 · P-45 X4 · P-46 X4 · P-47 X4 ·
P-48 X1 · P-49 V4 · P-50 V4, Q3 · P-51 V4 · P-52 V4 · P-53 Y2 · P-54 X7 · P-55 Y4 · P-56 Y2 ·
P-57 V2 · P-58 V1 · P-59 X7 · P-60 X7, Q3 · P-61 X7 · P-62 Y4 · P-63 X7 · P-64 X5 · P-65 X5 ·
P-66 Y4 · P-67 X5 · P-68 X5 · P-69 X5 · P-70 X5 · P-71 X5 · P-72 Y4 · P-73 Y4 · P-74 Y4 · P-75 Y4 ·
P-76 Y4 · P-77 Y4 · P-78 Y4 · P-79 X5 · P-80 Y2 · P-81 Y1 · P-82 Y1 · P-83 Y2 · P-84 Y2 · P-85 Y1 ·
P-86 Y2 · P-87 Y2 · P-88 Y2 · P-89 X4 · P-90 Y3 · P-91 Y3 · P-92 Y3 · P-93 Y2 · P-94 Y3 · P-95 Y2 ·
P-96 Y2 · P-97 Y2 · P-98 X1 · P-99 Y1 · P-100 Y4 · P-101 Y4 · P-102 Y4 · P-103 Y4 · P-104 Y4 ·
P-105 X3, X7 · P-106 X5 · P-107 Z2 · P-108 Z2 · P-109 Z2 · P-110 Z2 · P-111 Y2 · P-112 Z3 · P-113 Z3 ·
P-114 Z3 · P-115 Z1 · P-116 Y4 · P-117 Z1 · P-118 Z1 · P-119 Z2, Q4 (14) · P-120 Z1 · P-121 Z1 ·
P-122 Z1 · P-123 Z1 · P-124 Z1 · P-125 Z1 · P-126 Z1 · P-127 Z1 · P-128 Z1

Specification: S-01 Q4 (1), X6 · S-02 Q4 (2), Q3, X6 · S-03 Q4 (3), X3 · S-04 X3 ·
S-05 Q4 (4), X4, Z3 · S-06 X3 · S-07 Q4 (5), Q1, X4 · S-08 X4 · S-09 V5 · S-10 V7 · S-11 Q4 (6), V7, X1 ·
S-12 Q1, X5 · S-13 X1, Q2, Q4 (6) · S-14 Q4 (10), X4 · S-15 Q2, Z3 · S-16 Y1 · S-17 Y3 · S-18 Q4 (13), Q2, Open after 0.2.2 (2) ·
S-19 Q2 · S-20 V5 · S-21 V5 · S-22 Y3 · S-23 X4 · S-24 X4 · S-25 X4 · S-26 Q4 (9), X4 · S-27 V5, X8 ·
S-28 Q1 · S-29 Q1 · S-30 Q4 (7), Y1 · S-31 Y2 · S-32 Y3 · S-33 Q1 · S-34 X3 · S-35 X3 · S-36 Q1 ·
S-37 Q1 · S-38 Q1 · S-39 Q4 (11), X5 · S-40 Q1, X1 · S-41 X4 · S-42 X5, Open after 0.2.2 (1) ·
S-43 Y3 · S-44 Q1 · S-45 Q1 · S-46 Q2 · S-47 Q1 · S-48 Q4 (6), X1 · S-49 V5 · S-50 Q1, Q2 · S-51 Q3 ·
S-52 Q2 · S-53 Q2, Q4 (16) · S-54 Q1, Q2 · S-55 Q2 · S-56 Q1, X6 · S-57 V7 · S-58 Q1, Q4 (2) · S-59 Q1 · S-60 Q1 ·
S-61 Q1 · S-62 Q1, Y1, Q4 (7)

Missing tests of review §6: T-01 X1 · T-02 X1 · T-03 X2 · T-04 X1 · T-05 V4 · T-06 V4 · T-07 X6, Z3,
Q2 · T-08 V1 · T-09 V2 · T-10 V1 · T-11 V2 · T-12 X5 · T-13 V4 · T-14 V4 · T-15 V6 · T-16 Y1 ·
T-17 X3 · T-18 X4 · T-19 X1 · T-20 Z3 (X4: decision 10's core test) · T-21 Y1, Z3 · T-22 Z1 · T-23 Z3 · T-24 Z3, Q2 · T-25 Q2
(run at J2) · T-26 X2 · T-27 X3 · T-28 X3 · T-29 V3 · T-30 V5 · T-31 V3 · T-32 X5 · T-33 Y1 ·
T-34 Y1 · T-35 V1 · T-36 Y4 · T-37 X5 · T-38 X5 · T-39 V3 · T-40 Y2 · T-41 Y3 · T-42 Y3 · T-43 Y3 ·
T-44 X3 · T-45 X3 · T-46 X3 · T-47 X1 · T-48 X4 · T-49 X1 · T-50 Y4 · T-51 Z1 · T-52 X7 · T-53 X7 ·
T-54 V6 · T-55 X1

Review questions (Appendix E): 1 Q4 (3) · 2 Q4 (6) · 3 X4 · 4 Q4 (1) · 5 V1 · 6 V3 · 7 Q4 (7) ·
8 Y1 · 9 Y1 · 10 X5 · 11 Y3 · 12 Y3 · 13 Q3 · 14 Q4 (14) · 15 Q4 (15) · 16 Q4 (16) · 17 Q3 · 18 Q3 ·
19 X5 · 20 Y4

Open after R6 (`docs/plan-0.2.1.md`): #1 Q4 (6), X1 · #2 Z3 · #3 X5 · #4 Q4 (2), X6 · #5 Y1 ·
#6: H9 V2, C14 V2, C10 V3, C15 V3, A11 Y2, A12 Y2, A13 Y2, T11 Z1 · #7 Q4 (12) · #8 V4, X2, Q3

Added by the comparison (`docs/review-2026-09-26-vs-0.2.md` §7): S-01 X6 · P-20 X7 · P-01 and P-04
V1 · P-21 V5

Decisions of 2026-09-26/27: 1 X6 · 2 X6, Q1 · 3 X3 · 4 X4, X5 · 5 X4 · 6 X1, V5, V7 · 7 Y1 ·
missing data Q1, X8, Y1, Y4 and every step's negative tests · boiler protection Y1 · safe hand-back V5 ·
on/off control X8 · the wall thermostat X5, X6 · 9 X4, Q1 · 10 X4 · 11 X5, Q3 · 12 Q1 · 14 Z2 · 15 Q2 (J4) · 16 Q4 · the findings of the checks: their own list

Answers of 2026-09-27: A the details file · B Rules · C, D X8 · E X1 · F X3 · G X8 · H V5, X1 · I V6 ·
J X4 · K V1, V3, Y3, X6 · L X8 · M X3, X8 · N X8 · O X1, X5
