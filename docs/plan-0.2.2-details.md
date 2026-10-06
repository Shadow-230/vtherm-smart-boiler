# Plan 0.2.2 — step details

The step-by-step details of [`docs/plan-0.2.2.md`](plan-0.2.2.md): the order of work, the tests to write
first, the values, the texts and what to do when an input is missing, for every step. The plan is the
source of the decisions; where the two differ, the plan wins. Drafted on 2026-09-27 by five agents from
the plan, the review of 2026-09-26, the research notes and the code, corrected against the user's
answers of 2026-09-27 and checked twice (raw results: `research/2026-09-26-session-raw/INDEX.md`).
Values marked "(provisional, K4)" are the most cautious found and wait for the user's review at K4.

This file is large: read the section of the step you work on (use `grep -n '^### '` for the index of
steps) rather than the whole file.

## Start here (for a new session)

This file holds the step-by-step details of `docs/plan-0.2.2.md`. The plan is the source of every decision; this file says how to carry out each step. If the two differ, the plan wins, and the difference is a plan fix to put to the user. Line numbers cited below for `docs/plan-0.2.2.md`, `CLAUDE.md` and the code are those of commit d545869 (`git show d545869:<path>`); the pending plan and `CLAUDE.md` diffs move them (e.g. phase Q's rows are at l.441-444 in the pending plan, not l.383-386), so find a cited text by its heading. Research notes in `research/` are evidence, not decisions. A note may propose something the plan does not state; that proposal is not decided. Where a step needs it anyway, it goes into `SCOPE.md` as provisional, with its most cautious value, and onto the K4 list as a question.

**Where to continue.** Follow `CLAUDE.md` l.3-9: take the first step without ✅ (optional ones aside) in `docs/plan-0.1.md`, then `docs/plan-0.2.1.md`, then `docs/plan-0.2.2.md`, then `docs/plan-0.2.md`. On 2026-09-27:
- `docs/plan-0.1.md`: every step ✅; nothing is open.
- `docs/plan-0.2.1.md`: two 🔒 steps have no ✅, and neither holds anything up:
  - **L4** (l.192) was decided on 2026-09-27. Plan 0.2.2 decision 11 says control without a heating switch stays blocked until Q3 shows that a low setpoint stops both the boiler and its pump; lifting the block waits for the user at K4, even if Q3's research is favourable (answer K). Q2 marks L4 ✅ with that reason.
  - **R2** (l.313), the integration's icon, waits for the user. Only K5 needs it: hassfest's brand check (`docs/plan-0.2.1.md` R1, l.312). It stays in "Open after 0.2.2" #6.
- `docs/plan-0.2.2.md`: start with phase Q, in the order given below, then phases V, X, Y and Z in order (plan l.17-19).
- `docs/plan-0.2.md`: J2, J4, K1, K2 (its ✅ withdrawn until its validation runs, which needs K5's repository) and K4–K7 follow 0.2.2 (plan "After 0.2.2").

Check before starting:
- Run `git status`. An untracked or modified `*.md` file is a pending diff from an earlier session: show it to the user, and never commit or overwrite it without their consent (`CLAUDE.md` l.59-63).
- Run `git log --oneline -10`.
- Find the first step without ✅ in each plan.

**Status on 2026-09-27.** Decisions 1–15 are recorded in `docs/plan-0.2.2.md`; decision 16 keeps its provisional option. The user also gave answers A–O on 2026-09-27. They are decisions, and they win over the research notes and over earlier drafts of this file. This file applies them, and the plan records them (Q1's plan fixes). Earlier drafts numbered the first of them 1–4 (1 = A, 2 = B, 3 = C, 4 = E).
- **A.** The details go into this file, `docs/plan-0.2.2-details.md`, and the plan points to it at every step.
- **B.** A ✅ mark on a finished step, and an addition to "Open after 0.2.2", are committed without waiting for consent; their diff is shown in the step's report. Every other change to a `*.md` file still waits for the user's consent.
- **C.** A relay switched by an automation or by its own button, while it stayed available, counts as another controller: it is rewritten once, then the plugin steps aside, never fighting. A relay found in another state after a power or link loss (it was unavailable, or restarted) is sent the command again.
- **D.** A relay found back in the state it takes after a power cut (as the user declared it in the form), even without Home Assistant having seen it unavailable (for example a Zigbee relay without availability reporting), is treated as a restart: the command is sent again; if this happens 3 times within 24 h, an information warning. Only a change to another state while the relay stayed available counts as another controller (C). Answer N adds a limit, and a rule for "last" and "I don't know".
- **E.** A single fall-back to the value from before the plugin, with no visible trace of an outage, is a lost command: it is sent again and counted. A second such fall-back within 1 hour that no send explains counts as another controller. A send explains a fall-back when the fall-back comes before the plugin's latest send was read back as its value, or within 120 s of a send of a new value (a change, not a keep-alive or resend); such a fall-back is judged as a lost command or as ignored from the start, never as another controller. A fall-back after every send from the start of the session stays "ignored from the start". The heating switch (two-valued) follows the same classes as the setpoint.
- **F.** VT gives no answer at all and there is no wall thermostat: if the user has ticked a new option, "the boiler has its own room controller" (for example an EMS room controller on the bus), the boiler is handed back to its own control after the grace period; without that tick the plugin does not heat (its usual "off") and raises an alarm and a repair issue. A "working thermostat" is therefore a gateway with an OpenTherm thermostat declared on its terminals (effect `THERMOSTAT_TAKES_OVER`), or any path with the "own room controller" tick (effect `OWN_CONTROL_RESUMES`). A relay resting "on" is not a working thermostat. Answer M narrows "any path": the tick is offered on the entity path and the relay path, not on a gateway, and on the relay path it counts only with the rest state "on".
- **G.** The relay form asks the user to tick "this is a separate relay contact, not a setting stored in the boiler's memory"; without the tick, control does not start (a blocker that names its reason).
- **H.** When the plugin steps aside because another controller keeps writing, it makes the full safe hand-back: the water to the lowest water temperature set, heating on where the boiler returns to a thermostat or its own control, then the release — even though this briefly writes over the other controller's value. Control then stays latched, stored through reloads and restarts, until the user switches it off and on, or returns by itself where that option is on (not for relays).
- **I.** If the plugin's own monitor fails for 5 min, control hands back; it resumes by itself once the monitor works again (like the lost boiler link), with an information note.
- **J.** A new code file, `button.py`, with a "Reset comfort correction" button, is approved.
- **K.** Confirmed as decisions:
  - a lost or damaged store makes the plugin assume it was controlling and hand back first, and the monitoring period counts from the entry's creation;
  - after a restart the control switch comes back as the user left it (the wish is saved at once), and a switch entity disabled in Home Assistant means control off;
  - the verdict "worth enabling" comes only from problems that 0.2.2's control changes; the others are shown as "not changed yet";
  - lifting the block on "off" as a low setpoint (and on decision 1's low `CS`) waits for the user at K4, even if Q3's research is favourable;
  - a gateway entry without an answer to the new thermostat-terminals question keeps control stopped, with a notice asking for the answer.
- **L.** When the plugin steps aside because someone else keeps switching a relay (an automation or the relay's own button), it sets the relay once to its rest state (the full safe hand-back of answer H applies to relays too), then leaves it alone.
- **M.** On the relay path the tick "the boiler has its own room controller" counts as a working thermostat only when the relay's rest state is "on" (the relay is the boiler's heat-demand contact); with rest state "off", VT giving no answer means no heating and an alarm, as without the tick. On a gateway the tick is not offered (a thermostat on the terminals covers it; with nothing on the terminals a hand-back stops heating anyway); on the entity path it is offered as answer F says.
- **N.** A relay found back in its declared after-power-cut state counts as a restart (answer D) — but after 3 such restarts within 24 h, a further one is treated as another controller (the plugin steps aside with a notification, setting the rest state once, as L says). The same applies to relays whose after-power-cut state is declared "last" or "I don't know": a change while the relay stayed available is treated as a possible restart (the command is sent again) up to 3 times within 24 h, then as another controller.
- **O.** If the boiler ignores the "heating off" command from the start of the session (the heating switch's "off" is "ignored from the start"), control is blocked and the boiler handed back, with an alarm — like an installation without a working heating switch (decision 11); a blocker names the reason until the user switches control off and on after fixing it.

The user's rules of 2026-09-26/27 also hold: all findings and results are saved in the working directory; replies to the user are in plain, less technical Polish; most parameters may be missing. Earlier drafts called the first two "answer 5".

On 2026-10-02 0.2.2 is built: phases Q, V, X, Y and Z are committed, and the independent check Z4 ended with a re-check finding no critical or high problem (`research/2026-10-02-z4-*.md`). The next step is J2 of `docs/plan-0.2.md`, which is the user's. Each step's build report is in `research/2026-09-2x-<step>-build-report.md`, what one step left for a later one in `research/2026-09-28-carry-over.md`, and the questions for K4 in `research/2026-09-27-k4-questions.md`. Line numbers cited in this file are those of commit d545869; the code has moved since.

**A 🔒 step that holds nothing up.** A 🔒 step waits for the user. Its plan may say it holds nothing up (`docs/plan-0.2.1.md` l.12-13 for L4; `docs/plan-0.2.2.md` l.17-19 for Q4), or, like R2, only a later step may need it (K5). In those cases:
- note it in the step's report and carry on with the next step;
- it keeps no ✅ until the user acts;
- it does not count as "the first step without ✅" when deciding where to continue.

Today that means plan 0.2.1 R2 (needed at K5) and plan 0.2.2 Q4 (it closes at K4 and K5). The 🔒 steps of `docs/plan-0.2.md` (J2, J4, K1, K4–K7) do hold up what follows them: work stops there. K2 is not 🔒. Its ✅ is withdrawn until its validation runs, which needs K5's repository.

**Order inside phase Q.**
1. First, the parts of Q3 that Q1's text depends on:
   - Q3.1: the lowest VT version that loads external feature managers (P-60);
   - Q3.2: a low `CS` and the CH pump (decision 11, and decision 1's alternative);
   - Q3.4: a generic rule behind the lowest-water-temperature estimate, shown beside X6's suggestion (decision 2);
   - Q3.7: how a trace of an outage shows on each gateway path (decision 6);
   - Q3.9: which entity carries the boiler's own fault on each path (boiler protection).
2. Then Q1, then Q2. A sentence that waits for a Q3 answer is written with the marker "(to be settled by Q3)". Once the answer is in `research/`, the sentence is completed with a new diff.
3. The rest of Q3 (Q3.3, Q3.5, Q3.6, Q3.8) can happen at any time before the step that uses it: V4, X2, and the INDEX entry.
4. Q4 is not work to do: it waits for the user (K4, K5).
5. Phase V may start once Q1's diff has been shown, even while it waits for consent (plan l.17-19). If the user changes the text, the code follows the user's version.

**Pending document diffs and code commits.**
- A `*.md` change that waits for consent stays uncommitted in the working tree. Show it as a diff, with a short plain-Polish summary of what it changes for the house and the boiler.
- Commit code and tests by path: first `git add <new paths>` for files git does not track yet, then `git commit -m "<message>" -- <paths>`. That way a pending `*.md` change never ends up in a code commit. Before each code commit, run `scripts/env.sh python -m pytest -q` and `scripts/env.sh ruff check .` (`CLAUDE.md` l.80-81).
- `git commit -- <path>` commits the whole file. So a file that holds a pending change cannot take a separate commit.
  - Make a change that needs no consent (a ✅ mark, or an addition to "Open after 0.2.2") only in a file with no pending change. Commit it at once by path, and show its diff in the step's report (answer B).
  - If the file already holds a pending change, the free change waits and is committed together with it after consent.
- Once the user consents, commit the document change on its own, with the step in the message (for example "Plan 0.2.2 Q1: SCOPE §7, the matrix of outside changes").
- Anything git does not track (`research/`, session summaries) is shown to the user and confirmed before it is deleted or overwritten (`CLAUDE.md` l.62-63).

**Where research lives.**
- `research/` is git-ignored. It holds one note per topic, `research/YYYY-MM-DD-<topic>.md`, in the format of the notes of 2026-09-26:
  - date and source;
  - a plain explanation;
  - sources with their URL and the date read;
  - facts marked verified or assumed;
  - a "Decided by the user" line once the user has decided.
- Raw output of a workflow goes to `research/<date>-session-raw/` (today `research/2026-09-26-session-raw/`). Raw network pages go to `research/raw/`.
- Sources of DIY boiler interfaces go to `research/diy/<solution>/`. Each file is listed in `research/diy/INDEX.md` with its source, date and license (`CLAUDE.md` l.38-47).
- Every finding and result of a step is saved in the working directory (the user's rule): research answers, check results, and test and coverage output. Notes and raw results go to `research/`; throw-away tool output goes to `.tmp/`.
- The notes that shape 0.2.2:
  - `research/2026-09-26-*.md`. Each opens with the user's decision. That line, and the verifier's corrections, hold over the first agent's proposal.
  - `research/2026-09-27-fresh-session-test.md`: the gaps a new session hit.
  - `research/2026-09-27-plan-0.2.2-checks.md`: the plan's fidelity and consistency checks.

**Talking to the user.** Use plain, less technical Polish (the user's rule): what was done, what it means for the house and the boiler, and what needs the user's answer. Each step's report lists:
- the tests and checks run, with their results;
- the diffs committed without waiting (✅ marks, "Open after 0.2.2");
- the diffs waiting for consent;
- anything added to "Open after 0.2.2".

---

### Q1 — Specification: `SCOPE.md`, `PLAN.md`'s release rows and `CLAUDE.md` take the decisions

**Goal and done-when.** Before the code changes, `SCOPE.md` says what 0.2.2 does:
- every decision of 2026-09-26/27 and every answer of 2026-09-27 (A–O);
- every provisional option, marked "(provisional, K4)" and listed in the fixed-values table (S-37);
- the text for every specification problem of the review. This includes the S-items whose code a later step builds, so that phases V–Z build what `SCOPE.md` states and change no `SCOPE.md` text. This follows phase Q's "Why" (plan l.375-377).

`PLAN.md`'s release rows and `CLAUDE.md` follow. The item list is "Document changes of Q1 and Q2, section by section" at the end of this step.

Q1 is done when:
- every item marked [Q1] in that list is written, shown and consented, or its remainder is named in "Open after 0.2.2";
- every check under "Order of work" passes;
- no sentence of `SCOPE.md` contradicts a decision or an answer of 2026-09-27;
- every "(to be settled by Q3)" is completed, or is listed in "Open after 0.2.2" with the Q3 answer it still needs.

**Read first.**
- Plan: "Terms"; "Decisions of 2026-09-26/27"; decisions 1–16; "Findings of the checks"; "Rules that shape this release"; the rows Q1, V5, X1, X3, X4, X6, X8 and Y1; "Open after 0.2.2". Also the answers A–O of 2026-09-27 above; they win where a note or the plan's older text differs.
- Review `docs/review-2026-09-26.md` §4 (l.297-366): every S-row. Also Appendix E (l.1462-1493), for the answers to questions 3, 5, 6, 8–12, 19 and 20 that the steps give.
- `research/2026-09-27-fresh-session-test.md`, "Part: start-and-Q", sections Q1 (a)–(e) (l.58-258), and "Cross-cutting gaps" (l.343-352).
- `research/2026-09-27-plan-0.2.2-checks.md`, both sections.
- `research/2026-09-26-q4-decision-6-outside-change-matrix.md`: §1–§5 (l.24-394), and "Verification" with its corrections, missing rows, safety concerns and conflicts (l.418-546).
- `research/2026-09-26-q4-decision-3-no-zone-known.md`: "Conflicts with decisions" (l.404-409), "Facts" (l.411-449), "Open questions" (l.451-460).
- `research/2026-09-26-on-off-plugin-code.md` §3 (l.61-143) and §4 (l.144-160); `research/2026-09-26-on-off-relays.md` "Missing" (l.259-271); `research/2026-09-26-on-off-vt-native-central-boiler.md` (l.40-56).
- `research/2026-09-26-q4-decision-7-alarms.md` §3–§4 (l.55-110); `research/2026-09-26-boiler-protection-alarms.md` "Corrections" and "Missing" (l.100-160).
- The notes on decisions 1–2 and 4–5, and on the wall thermostat (their headers and "Decided by the user" lines).
- The current texts: `SCOPE.md` (all 651 lines, read in parts), `PLAN.md`, `CLAUDE.md`.
- The code behind the facts that `SCOPE.md` cites: `custom_components/vtherm_smart_boiler/core/guards.py:41-45, 79-85, 153-340`; `core/loop.py:69-130`; `control_config.py:29-122, 195-373`; `control.py:82-87, 147-165, 312-330, 955-972`; `core/controller.py:53-60, 120-135, 198-270, 400-401`; `transport/writers.py:34, 159-214, 228-238, 272-324, 327-343`; `core/alarms.py:67-70, 101-103, 193-197, 271`; `core/signal_check.py:146-149`; `core/readings.py:38-39`; `core/limits.py:81`; `core/zones.py:11-12`; `core/learning.py:41-47`; `core/curve.py:65-66`; `core/metrics.py:24`; `config_flow.py:80-96, 148-158, 520`; `repairs.py:19-58`.

**Order of work.** Q1 changes text only, so its "tests" are checks run with `grep` over the edited files. Each is written down first, then run once the text is written:
- `check_principle_12_lists_its_exceptions`: given the edited `SCOPE.md`, when it is searched for "one exception" and "the one case", then there is no hit; principle 12 lists its stated exceptions.
- `check_lowest_water_temperature_term`: when it is searched for "hard minimum" (any case), then the only hit is the key name `hard_min`, in parentheses. Everywhere else it says "lowest water temperature".
- `check_old_outside_change_rule_gone`: when it is searched for "written again at most once" and "falls back to its value from before the session", then nothing is found outside §11's dated history.
- `check_class_3_without_anti_cycling`: when it is searched for "minimum on and off times" and "switchings per hour", then the only hits are in §11's dated history.
- `check_working_thermostat`: when it is searched for "working thermostat", then every definition names only a gateway with an OpenTherm thermostat declared on its terminals, the "own room controller" tick on the entity path, and the tick on the relay path with the rest state "on" (answers F and M); no hit counts a relay resting "on" without the tick, the tick with the rest state "off", or the tick on a gateway.
- `check_provisional_marks`: every row marked provisional in the fixed-values table appears with "(provisional, K4)" in the text that uses it.
- `check_release_names`: when `SCOPE.md`, `PLAN.md` and `CLAUDE.md` are searched for "0.2.1b1" and "0.2.1, the first release", then nothing is found outside dated history.
- `check_references`: every "decision n" in the text exists in the plan, and every step it names exists.

Then:
1. Collect the Q3 answers that are ready. For each answer still missing, write the marker "(to be settled by Q3)" and the cautious provisional given below.
2. Draft `SCOPE.md`, section by section (list below), from the rules and the matrix in this step.
3. Draft the [Q1] items of `PLAN.md` and `CLAUDE.md`.
4. Run the checks.
5. Show each file's diff to the user with a plain-Polish summary. List every "(provisional, K4)" value, and any question still under "Open for the user".
6. After consent, commit each file on its own ("Plan 0.2.2 Q1: …").
7. Mark Q1 ✅ in the plan. Name any remainder in "Open after 0.2.2". Both are committed without waiting (answer B), and their diff goes in the report.

**Rules and values.**

*A. The missing-data rule*, a new paragraph at the head of §7 "Control base":
- Most installations give only some of the inputs. Every feature works with what it has.
- A feature whose input is missing, unknown or unavailable is shown as inactive, and names what it lacks in a translated text (Y4 builds the texts).
- Missing data never switches heating off by itself, and never blocks the boiler by itself.
- A setting the form requires before control may start can keep control unavailable. These settings are: decisions 1 and 11; the relay's "separate contact" tick (answer G); and, for an existing gateway entry, the answer on its thermostat terminals (answer K: control stays stopped, with a notice asking for the answer). The monitor then runs and the boiler stays with its own control or thermostat. That is not heating switched off by missing data.
- When an input goes missing while the plugin controls, the feature that uses it becomes inactive, and control goes on with what remains. For example, a demand criterion that no zone can feed counts as having no data (X3).
- One entity mapped to two signals: the first signal in `SIGNAL_FIELDS` order keeps it, and the later one is dropped (inactive and named, Y4). Control gets the config blocker `entity_for_two_signals`, and the form refuses it. It is never a `ConfigError` that stops the entry, so the monitor and an owed hand-back go on (X5).
- Two stated exceptions of principle 12 stop heating on missing data:
  - the lost boiler link: a hand-back after 5 min, which stops heating when stand-alone; a relay instead gets the alarm `relay_unreachable` and no hand-back;
  - every VT zone still unknown after the grace period, or no configured demand criterion that can be judged (X3), with no working thermostat (answers F and M): the usual "off", with an alarm and a repair issue.
- An installation that gives no confirmation at all (neither the boiler's signals nor a relay's own reported state) gets only the monitor. The exception is a relay that reports no state of its own: it is controlled with blind repeats and shown as "controlled without confirmation".

*B. Principle 12's stated exceptions.* These replace "Frost protection is the one exception" (`SCOPE.md` l.77-78). Each is written with its reason:
1. Frost protection, a safety net, only for zones whose emitter can take heat (decision 4).
2. The recognition period: at most 10 min after Home Assistant starts or VT reloads, with the last command kept. Reason: the zones report one by one.
3. The grace period: a zone that becomes unknown keeps its last answer for 10 min. Reason: reloading one zone should neither start nor stop the boiler.
4. No heating when every zone is unknown, or no configured demand criterion can be judged (X3), after the grace, and no working thermostat is there (answers F and M). Reason: nothing can ask for heat (decision 3).
5. VT's activation delay, 0–600 s before switching on, as in VT 10.4.0. Reason: slow valves (decision 5).
6. The usual "off" while the boiler reports a fault that stops it (a known "on" held 5 min, provisional, K4). Reason: the plugin follows the boiler's own logic.
7. The lost boiler link: a hand-back after 5 min (stand-alone, heating stops), or for a relay an alarm with no hand-back (the decision of 2026-09-25, and X8).

Also say that a hand-back the rules require (another controller, an internal error, the plugin's own monitor failing for 5 min (answer I), the boiler ignoring "heating off" from the start of the session (answer O), an exit) is not a decision about whether to heat. It returns the boiler to its own control or thermostat, and when stand-alone it stops heating, as §5 says. Anti-cycling for 0.3 is "to be decided against principle 12 (decision 13)".

*C. Principle 13, rule 7* (decision 2; S-58):
- Every learned value is visible and can be reset.
- Values of a session (the comfort correction) reset at hand-back and at the end of the session.
- Learned properties of the boiler (the lowest water temperature, once "apply" learns it in 0.3) are kept. They reset when the user resets them or when an input they rest on changes.
- The user's own entry is never reset.

S-58, provisional (K4):
- The rule values (the band, the rates, the freeze conditions) are fixed.
- The only options are whether a learning feature runs (off / suggest / apply) and principle 8's tuning band (Low / Medium / High / Custom).
- §4's power-user "change-per-day limit" becomes "the tuning band".
- The source chain: the source of each value is shown (class default → the user's entry → measured → learned). The user's entry always wins over measured and learned values. "Apply" (0.3) moves only within the band around the user's entry.

*D. The safe hand-back* (§7 hand-back bullets, `SCOPE.md` l.383-392; S-20, S-21, S-27, S-28, S-45, S-49, S-54). A hand-back happens in this order:
1. **The water goes to the lowest water temperature.** This is one write. The next part follows at once, and each part is tried whatever the others do (`transport/writers.py:184-214, 327-343`). The hand-back waits neither for a read-back nor for the water to cool (provisional, K4).
2. **Heating goes on where the boiler returns to a thermostat or to its own control.** On a gateway this is always `CH=1`, which only clears the plugin's own `CH=0`; stand-alone, `CS=0` still stops heating, so this is not the "heating on" that S-27 forbids. A heating switch on an entity path is not turned on where the declared effect is "heating stops".
3. **The release:** `CS=0` on a gateway, the hand-back value, the external-control switch off, or the timeout.

A relay goes to its rest state instead.

Special cases:
- Where a target is declared "held" — the device keeps the last value it was given (ESPHome, DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires within about a minute) — and the release is not confirmed, the boiler stays at the lowest water temperature. An alarm rises at once, and the release is retried every minute until it is confirmed.
- A step aside (answer H) makes the full hand-back of every target, including one the other controller holds. Each part is written once, which briefly writes over the other controller's value. A relay is set once to its rest state and then left alone, whether or not the rest state is read back (answer L).
- A target the other controller takes after that counts as handed back, with no retry (M12):
  - the setpoint, when a steady foreign value holds for 2 retries;
  - a two-valued target (the heating switch, the external-control switch; a relay alike after a hand-back other than a step aside, provisional, K4), when its hand-back state was read back once and then changed without a trace of an outage. Before that read-back it stays owed and is retried.
  - This changes "retried every minute until it is confirmed" for that case only.

Checks on the hand-back value and its confirmation:
- The hand-back value is exempt only from the lowest water temperature. The circuit's maximum and the highest water temperature still apply (S-21).
- "Off" is refused within 0.5 K of a hand-back value declared "the device's own control resumes" (S-49; plan V5).
- A missing or `unavailable` target means the hand-back failed. An `unknown` target is written, and counts only once it is read back (S-28).
- A timeout hand-back is released when the read-back is back within 0.5 K of the session's baseline. With the baseline unknown, it is released when the read-back is more than 0.5 K from both the plugin's last value and the lowest water temperature just written. No retry writes. `hand_back_failed` rises after 3 min without release (provisional, K4). Until then the hand-back stays owed and is shown (S-20).
- An entity with `assumed_state`, or with no report independent of the plugin, is "unconfirmed", and says so (S-09).

Settling an owed hand-back by hand (S-45): the repair issue "hand_back_owed" is fixable (`control.py:133-144`, `repairs.py:19-35`). It is offered while a hand-back is owed. The user confirms that the boiler runs on its own control again; the plugin then forgets the debt and stops retrying (`control.py:959-972`).

Removing the entry (S-54): Home Assistant offers no veto. The plugin makes a last attempt, and if that fails, raises a persistent repair issue.

*E. Decisions, as the text states them.*
- **Decision 1** (§5 Gateway topology; §4 wizard):
  - Both gateway topologies ask what is wired to the thermostat terminals: an OpenTherm thermostat, an on/off contact, nothing, or "I don't know".
  - Control is blocked for an on/off contact and for "I don't know"; the monitor runs.
  - A gateway entry without an answer to this question (one made before 0.2.2) keeps control stopped, with a notice asking for the answer (answer K).
  - "OpenTherm thermostat" with stand-alone, or "nothing" with a thermostat, is refused in the form, with a hint to pick the other topology.
  - A gateway with an OpenTherm thermostat declared keeps the hand-back effect `THERMOSTAT_TAKES_OVER`.
  - The paragraph on `CS`/`CH` in §11 says that `CH=` is "held": the PIC keeps it until `CH=1` or a reset (X6).
  - The claim "with a thermostat every fallback returns control to it" is qualified: it holds for an OpenTherm thermostat only (S-01).
- **Decision 2** (§7 defaults and options):
  - "Lowest water temperature" (key `hard_min`, 10–50 °C, `config_flow.py:520`), default 20 °C (provisional, K4).
  - Both risks go in its text: too low, and the boiler stops by itself again and again in mild weather, and a non-condensing boiler condenses in its flue (take the value from its manual); too high, and the water is warmer than the rooms need.
  - 0.2.2 has no suggest/apply option. The monitor shows its evidence (burns shorter than 10 min, `core/metrics.py:24`, while the setpoint was at the lowest water temperature) and a suggested value, which the user enters.
  - The suggested value is the reference + 2 K, rounded up to 0.5 °C and kept below the caps (provisional, K4; X6). Where Q3.4 records a generic rule and its inputs exist, that rule's estimate is shown beside the suggestion but never applied.
  - No suggestion while a stand-alone installation is handed back. Where the boiler's own curve rules, only suggestions, never a parallel shift of that curve.
  - Class 2 gets suggestions only. Its persistent writes are dropped (S-56).
- **Decision 3** (§7 Control base, replacing "With no zone known, heating runs on the curve", l.301-303):
  - **Recognition period.** It runs until every configured zone has reported, at most 10 min. A zone has reported when VT shows it started and its mode and demand are known; X3's test with the vendored VT settles what "started" looks like before VT publishes `is_ready`. No new decision is taken meanwhile.
    - If control held the boiler before (including a clean restart that handed it back), its last command is kept, or restored at once, with its keep-alives. The restore happens at once when all of these hold:
      - V3 stored a last command;
      - the stored wish is "control on", and the control switch entity is not disabled (answer K: a disabled switch means control off; V3's T-31);
      - there is no latch or internal error;
      - the control options equal `taken_with`;
      - no blocker other than `ha_starting` holds (`vt_central_boiler_unknown` is allowed only within the P-105 grace).
    - Until the write target and the boiler link are available, nothing is written and the restore waits, within the recognition period. A link not yet reported never turns the restore into a hand-back. When a condition fails, the owed hand-back goes first. Where control did not hold the boiler, nothing is written.
    - A lost or damaged store: the plugin assumes it was controlling and hands back first (answer K).
    - Frost protection acts for zones already known (provisional, K4).
    - A restored command gets no activation delay.
  - **Grace period.** A zone that becomes unknown while VT runs keeps its last answer for 10 min; then it drops out and the known zones decide. This changes N3 of 2026-09-25.
    - A zone still unknown when the recognition period ends has no last answer, and drops out at once.
    - The grace also covers the "VT central boiler unknown" blocker during a VT reload (P-105).
  - **Every zone unknown after that.** Nothing asks for heat.
    - With a working thermostat, the boiler is handed back at once (answers F and M):
      - to the OpenTherm thermostat on a gateway's terminals;
      - or, with the "own room controller" tick, to the boiler's own control: on the entity path its hand-back, on the relay path the rest state "on".
    - Otherwise the plugin sends its usual "off", with no hand-back.
    - Either way, the alarm `no_zone_known` and the repair issue `no_zone_known_<entry_id>` rise at once, with the monitor only too (X3).
    - Control resumes by itself when a zone answers again; this is not a latch (provisional, K4).
    - This replaces "heat on the curve", whatever the outdoor temperature.
    - What counts as a working thermostat (answers F and M): a gateway with an OpenTherm thermostat declared on its terminals (`hand_back_effect` `THERMOSTAT_TAKES_OVER`), the entity path with the "own room controller" tick (`OWN_CONTROL_RESUMES`), or the relay path with the tick and the rest state "on". Nothing else counts:
      - not a relay resting "on" without the tick;
      - not the tick on the relay path with the rest state "off";
      - not a hand-back value declared "the device's own control resumes" without the tick;
      - not a "device decides" effect (a switch or timeout hand-back on a virtual controller).
    - The new option, "the boiler has its own room controller" (for example an EMS room controller on the bus), is a tick on the entity path and the relay path, off by default. It is not offered on a gateway: a thermostat on the terminals already counts, and with nothing on the terminals a hand-back stops heating anyway (the user, 2026-09-27, M). X3 reads "on a gateway" as every gateway topology, the entity path's included, where decision 1 asks the terminals question (to confirm at K4). Its text says what it does and what it risks (X3).
    - On the relay path the hand-back is still the declared rest state, and the tick counts only where that rest state is "on" (the relay is the boiler's heat-demand contact); with rest state "off", VT giving no answer means no heating and an alarm, as without the tick (the user, 2026-09-27, M).
- **Decision 4** (§7 frost bullet; defaults row "Frost protection"):
  - Frost protection watches every zone, or the one zone the user picks.
  - It heats only for a cold zone whose emitter can take heat: VT reports an opening above 0, or an active device.
  - A zone whose valve state cannot be read is heated as before. A per-zone option, "closes when VT switches it off" (off by default), makes such a zone count as closed while VT has it off.
  - A cold zone VT keeps closed raises a repair issue at once and does not start the boiler. The issue gives the room and its temperature, why the plugin cannot heat it, and what to do: VT's frost preset instead of "off"; VT's central frost mode needs a frost temperature in every thermostat.
  - The plugin never switches VT's mode.
  - Frost heating waits for the activation delay.
  - The defaults row "the safety net covers the whole house" changes.
- **Decision 5** (§7 Control base; options; defaults):
  - VT's activation delay: 0–600 s in steps of 10, default 0, shown at the simple level, on the relay path too (X8). It is pre-filled from VT's stored value and shown for confirmation.
  - It delays switching on only. The wait starts at the first real call for heat, after the recognition period.
  - A call that drops and comes back during the wait neither cancels nor restarts it. At the end of the wait, the boiler starts only if demand is still there.
  - Switching a running boiler off is immediate. A hand-back, control switched off, or a blocker cancels a pending start.
  - Frost heating waits too. There is no delay where the plugin controlled the boiler before a restart.
  - The risk text names TPI pulses shorter than the delay, and a pump that may run anyway without a heating switch.
- **Decision 6**: the matrix in F below, which replaces `SCOPE.md` l.374-382 and the drop rule of 2026-09-25.
  - Held values — a target declared held: ESPHome, DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires within about a minute — are sent again after a device returns and every 5 min (provisional, K4), with no echo required. This replaces "held — written on change only" (l.360-361, l.426-427).
  - The S-12 risks go in the write-type option: a parameter the boiler keeps in EEPROM (for example EMS-ESP `heatingtemp`) but declared "held" is written at every change and every 5 min, about 288 writes a day. The last held command, "off" included, stays while Home Assistant is down.
  - S-40: the heating switch falls under the same classes as the setpoint (answer E).
  - The one exception to "ignored from the start: no block" (the user, 2026-09-27, O): where the heating switch's "off" is ignored from the start of the session, the plugin can no longer switch heating off. Control is blocked and the boiler handed back at once (the safe hand-back, D), with the alarm `write_ignored` naming the heating switch — as decision 11 blocks an installation without a working heating switch. A blocker names the reason until the user switches control off and on after fixing it; it is kept through reloads and restarts, since only switching control off and on ends it (X1, X5.21).
- **Decision 7** (§7 options; defaults row "Alarm reaction"; S-62):
  - Always hand back:
    - an internal error;
    - the lost boiler link after 5 min (a relay: an alarm, no hand-back);
    - another controller;
    - the plugin's own monitor failing for 5 min (answer I). Control resumes by itself once the monitor works again, with an information note;
    - the heating switch's "off" ignored from the start (answer O), whatever the hand-back effect: a hand-back and a blocker kept until the user switches control off and on.
  - Optional, information by default: `write_ignored` for any other target or value, offered only where a thermostat or the boiler's own control takes over (hand-back effects `THERMOSTAT_TAKES_OVER`, `OWN_CONTROL_RESUMES`; never on the relay path, whose rest state "on" is not a working thermostat, answer F; Y1 rule 2).
  - Every other alarm informs.
  - Only a known reading at the alarm level, held for 5 min, counts. Unknown values never do. A notification closes after 60 min back in the normal range (both provisional, K4).
  - An alarm with a hand-back reaction that is already active when control is switched on blocks control at once, and the switch's text says so.
  - There is an allow-list in the code: a new alarm informs by default, and stored reactions that are no longer allowed are neutralised.
  - Every hand-back or latch an alarm causes raises a repair issue. Every latch uses one key, `control_latched_<entry_id>`, whose text names its cause. It is at alarm level where the hand-back's effect is "heating stops", and at warning level otherwise.
- **Boiler protection** (a new §7 paragraph):
  - Two optional signals take binary sensors the user maps:
    - "the boiler's own low-water-pressure fault" (simple level);
    - "another fault the boiler reports as stopping it" (advanced).
  - Which entities exist on each path is to be settled by Q3. `opentherm_gw` offers "Low water pressure", "Gas fault", "Air pressure fault" and "Water overtemperature" (`.venv/.../opentherm_gw/binary_sensor.py:122-145`, `strings.json` l.36, 57, 76, 157).
  - While either signal reads a known "on" for 5 min (provisional, K4), control sends its usual "off", frost heating included, with no hand-back and no latch.
  - Control heats again by itself in the step where every mapped fault reads off, unknown or unavailable. An unknown or unavailable fault state counts as no fault (provisional, K4).
  - Without a mapped fault, low pressure raises only an "add water" notification, at a threshold the user takes from the boiler's manual. There is none by default, neither warning nor alarm; this replaces 1.0/0.7 bar (`core/alarms.py:67`).
  - A broken or silent pressure sensor never stops heating.
  - High pressure and hot flue gas inform, with a notification that says what to do: read the safety valve's rating on the valve itself (often 3 bar in Europe, about 2.1 bar in North America); let water out only with the heating off and cold.
  - With enough data, a warning comes earlier: "your pressure keeps falling — there is a risk of a leak", judged with the water temperature taken into account (Y1).
- **Decision 9** (§7 outdoor bullet): with the outdoor temperature lost, the last value holds for 3 h (`core/curve.py:66`). After that, the user's fixed fallback, or the design flow, replaces it.
- **Decision 10** (§7 limits; options):
  - The circuit maximum limits the setpoint, and the boiler may overshoot it. The option's text says so.
  - An information alarm rises when the measured flow stays above an alarm temperature for a time. Both are the user's settings at the advanced level, pre-filled with the circuit's maximum + 5 K and 10 min (decision 10). A circuit without a maximum has no such alarm (X4).
  - The alarm needs a flow reading; without one it is inactive.
- **Decision 11** (§7 "Off" bullet, l.336-337; §11 l.560-561):
  - Control without a usable heating switch is blocked, and such installations get the monitor. The same holds for decision 1's alternative (a low `CS` with `CH` left alone).
  - Q3 researches whether a low setpoint stops both the boiler and its pump. Only the user lifts the block, at K4, even if that research is favourable (answer K).
  - A boiler that ignores "heating off" from the start of the session is treated in the same way (the user, 2026-09-27, O): control is blocked and the boiler handed back, with an alarm, and a blocker names the reason until the user switches control off and on after fixing it (decision 6 above; X1, X5.21).
  - OTGW "off" is `CH=0` (held) with `CS` of at least 8 °C. A relay's "off" is the relay off.
- **Decision 12** (§7 outdoor bullet): the curve takes the colder of the sensor and the weather entity. Drop "(provisional, `docs/plan-0.2.1.md`)".
- **Decision 13** (§5 class 3; §7 stage table; §8):
  - Class 3 has no minimum on and off times and no cap on switchings per hour, as with VT's own central boiler.
  - FC1, duty cycling, the starts-per-hour budget, and §8's SAT start budget are marked "to be decided against principle 12 (decision 13)".
- **Decision 16** (§11, §12): the first published version is 0.2.2, with pre-release 0.2.2b1 (provisional, decided after Z4 and at K4). The repository's content is decided at K5.
- **The wall thermostat** (§5 Gateway topology): no synchronisation in 0.2.2.
  - While the plugin controls, the wall thermostat's heating setting and its off switch do nothing; its hot-water settings still work.
  - After a hand-back or a Home Assistant outage, it heats by its own setting and program.
  - The plugin shows the temperature the wall thermostat would keep, from the optional "Wired thermostat setpoint" signal (`config_flow.py:93`, `translations/en.json:32`). It warns when that value is unknown, or below 15 °C (provisional, K4).
  - A VT zone built on the gateway's own thermostat entity is refused.
  - Synchronisation comes in 0.3 at the earliest.
- **Class 3, the relay** (§5 Boilers class table and class-3 bullet, `SCOPE.md` l.122, 146-149):
  - **Class and write path.** The class is available from 0.2.2. The write path is a "relay": a switch, or a boiler thermostat entity switched between heat and off. An `input_boolean` is refused, because it confirms nothing. The water-temperature parts are hidden. The activation delay field is shown on this path (X8).
  - **The relay's own settings.** The form asks for them as the user's declaration (the defaults and values provisional, K4; the "separate contact" tick itself is decided, answer G):
    - that it is a separate relay contact, not a setting stored in the boiler's memory: a tick, without which control does not start (a blocker that names its reason; answer G);
    - its state after a power cut (off / on / last / I don't know). The default is "I don't know", which is warned about as "maybe on"; with "last" or "I don't know", a change while the relay stayed available is taken as a possible restart up to 3 times within 24 h (answer N);
    - its own switch-off timer (none / its length, 1–120 min / I don't know). The default is "I don't know", treated as "it may have one": while the command is "on", "on" is repeated every `relay_repeat_s`;
    - whether it reports its state (yes / no / I don't know). The default is "I don't know", treated as "no": blind repeats and "controlled without confirmation". An entity with `assumed_state` always counts as "no";
    - the repeat interval `relay_repeat_s`: 10–300 s, default 300 s. It is pre-filled from VT's keep-alive only where that lies within 10–300 s.
  - **Flame and flow** become optional for the entry. Water-temperature control gets a blocker where either is missing.
  - **The link** is the relay: available and, where it reports, in the commanded state.
    - A relay out of reach raises the alarm `relay_unreachable` and its repair issue after 5 min. `boiler_link_lost` does not exist on the relay path.
    - The relay gets the command again when it returns, and gets no hand-back meanwhile.
  - **Read-back.** The relay's own reported state confirms the relay, not that the boiler heats. This is an exception to "a read-back from the written entity confirms nothing". An `assumed_state` entity confirms nothing. A separate echo entity for the relay is not in 0.2.2.
  - **State checks and repeats:**
    - the state is checked every 5 min (provisional, K4), and the command is sent again on a mismatch only;
    - a relay that reports no state, or that may have a switch-off timer, gets blind repeats every `relay_repeat_s`;
    - with a declared timer length, "on" is renewed every min(timer ÷ 2, `relay_repeat_s`), and a switch-off at or after max(timer − 60 s, timer ÷ 2) since the "on" that started the current on-period is the timer's lapse (so a relay that does not restart its timer on a repeated "on" is still recognised; X8 R3);
    - with "I don't know", a switch-off at least one repeat interval after the "on" that started the current on-period is the lapse;
    - an earlier switch-off is R3 (provisional, K4).
  - **Outside changes** as rows R1–R9 of the matrix (answers C, D, H, L and N). A relay found in its declared power-cut state is a restart, and so, where that state is declared "last" or "I don't know", is a change while it stayed available — the command sent again up to 3 times within 24 h; the next one is another controller, and the plugin steps aside at once (answer N).
  - **Rest state at hand-back:** "off" by default, "on" only when the user chose it, with its risk text. A notification rises when "off" leaves the house without heating while a zone calls or frost protection is active. At a step aside the relay is set once to its rest state and then left alone (answer L). There is no return by itself for relays (answer H).
  - **The "own room controller" tick** is shown on the relay path and counts as a working thermostat only with the rest state "on"; with the rest state "off", VT giving no answer means the relay off and an alarm (answer M).
  - **A planned restart:** the rest state at the stop, then the last command restored at once at the start.
  - **Optional proof that the boiler heats** (a flow-pipe temperature, the boiler's electric power, the gas meter) is information only. It is judged within 30 min after "on" (provisional, K4), which is longer than a common 20-min restart lockout. Without it, the status says "controlled without confirmation that the boiler heats".
  - **The power criterion, for every write path:** a zone's mean power over its cycle, as VT counts it (`mean_cycle_power`), counted only while at least one calling zone has its valve open or its device active.
  - **Moving over from VT:**
    - pre-filled before the user unticks VT's central boiler:
      - the relay, where VT's commands name a switch or a boiler thermostat entity;
      - the delay;
      - the repeat interval, only where VT's keep-alive lies within 10–300 s (a longer one is not pre-filled, and the text says why);
      - the power threshold as VT rounded it;
    - VT's device-count threshold is pre-filled only where every zone has one heating device (provisional, K4). The plugin counts calling zones; VT counted heating devices (S-36);
    - control waits for the Home Assistant restart VT needs.
  - **The setup texts recommend:**
    - the relay on the boiler's room-thermostat terminals, never in its power supply;
    - the old thermostat kept in parallel and set low, with the note that valves VT drives stay where they were while Home Assistant is down;
    - the relay starting "off" after a power cut;
    - optionally, the relay's own switch-off timer, renewed by every "on" and set only when control starts. Whether a Shelly's timer restarts on a repeated "on" is not documented; the texts say so until K6 checks it on the user's own relay, if they have one;
    - the relay's local input set to "detached";
    - a relay whose integration reports availability;
    - one test in summer.
  - **Topology table**, a new row: "— | relay (class 3), optional old thermostat in parallel | the plugin, through the relay | heating on/off only | the declared rest state: 'off' — heating stops unless an old thermostat in parallel heats; 'on' — the boiler heats on its own dial or thermostat".
- **Where the answers of 2026-09-27 land:**
  - C and D: Class 3 and rows R2, R2a, R3;
  - E: decision 6 and rows M4–M6;
  - F: decision 3 and the missing-data rule (A);
  - G: Class 3 and A;
  - H: "step aside" in F, D, and rows M8, M14, R3, R8;
  - I: decision 7 and the resume table;
  - J: S-08 in I;
  - K: decisions 1, 3 and 11, §7's "controlling" marker, §10 and §11;
  - L: "step aside" in F, D, Class 3, and rows R2a, R3, R8;
  - M: decision 3, Class 3, H's "working thermostat", §4 and §7 options;
  - N: Class 3, rows R2a and R3, G's fixed values, the resume table;
  - O: decisions 6, 7 and 11, B, row M6, the resume table.

*F. DRAFT — the matrix of outside changes (decision 6, with answers C, D, E and H of 2026-09-27).* `SCOPE.md` §7's "Changes seen in the read-back" is written from this table. It starts from rows A1–E10 of `research/2026-09-26-q4-decision-6-outside-change-matrix.md` §4, applies the decisions and answers, merges rows that behave the same, and adds the relay.

Legend:
- **Target:** S the water setpoint; H heating on/off; E the external-control (hand-back) switch; R a relay (class 3).
- **Path:** EN a picked entity; GW `opentherm_gw`; MQ the OTGW firmware over MQTT; RL a relay (a switch, or a boiler thermostat entity switched heat/off).
- **Write type:**
  - X expiring, repeated every 30 s.
  - Hd held: a target declared held (ESPHome, DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires within about a minute). It is sent on a change, after the device returns, and every 5 min.
  - On GW and MQ, S is X and H is Hd (X6).
- **Topology:**
  - OT: a gateway with an OpenTherm thermostat;
  - SA: a stand-alone gateway, with nothing on its terminals;
  - V: a controller on the Home Assistant side (ESPHome, DIYLess, EMS-ESP);
  - RL: a relay, with an optional old thermostat in parallel.
  - A gateway with an on/off contact or "I don't know" is blocked (decision 1), so no row applies.
- **When:**
  - W0: the session's first write;
  - W1: during control, after the value was read back as the plugin's;
  - W1': within 120 s of a send, before the read-back;
  - W3: during a hand-back;
  - W4: the recognition period;
  - W5: after a hand-back inside a session;
  - W6: during a hot-water draw or within 2 min after it;
  - W7: while the plugin is silent.
- **Baseline:** the first known read-back that is not the plugin's value (X1, P-07).
- **Trace of an outage:** within the 5 min before (provisional, K4), one of these was seen:
  - the target, its read-back, or another entity of the same device or gateway that the plugin reads was `unavailable`, `unknown` or missing;
  - a gateway or device restart. How a restart shows on each path is to be settled by Q3 (Q3.7).
- **Class:** LC lost command; IS ignored from the start; CL clipped; AC another controller; "—" not an outside change.
- **Step aside** (the reaction to AC; answer H):
  - stop writing;
  - the full safe hand-back of every target, including one the other controller holds (D). The water goes to the lowest water temperature, heating goes on where the boiler returns to a thermostat or its own control, then the release; each part is written once, even though this briefly writes over the other controller's value. A relay is set once to its rest state and then left alone (answer L). A target the other controller takes afterwards counts as handed back (M12);
  - a notification, the repair issue `control_latched_<entry_id>`, naming the target, the value seen, and what to do. It is at alarm level where the hand-back effect is "heating stops" (SA; a value declared "heating stops"; a relay left "off"), otherwise at warning level;
  - a step-aside latch, stored through reloads and restarts, until the user switches control off and on;
  - or the optional return by itself (off by default, confirmed twice; not for relays): once no foreign value has been seen for 60 min, a new session starts, with the one-rewrite memory kept for its day.

| # | Case (note rows) | Target | Path | Write type | Topology | Source | When | What the read-back shows | Class | Reaction | Provisional values | Test (step) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | Lost command after an outage (A2 with a trace, E2, E4, E10; C1 with a trace) | S and H together | EN, GW, MQ | X, Hd | OT, SA, V | the device or gateway unavailable (Wi-Fi, broker, power); an ESP, PIC or EMS-ESP restart; `opentherm_gw` reloaded (it sends `CS=0`) | W1 | back at the baseline (SA: 0; OT: the thermostat's own request, where the optional field "the OpenTherm thermostat's requested control setpoint" is mapped; while the plugin commands "off" on OT, the thermostat's CH bit) with a trace | LC | every value sent again at once, both targets as one loss; no rewrite counted, and no alarm for one loss; 3 losses within 24 h → the information alarm `commands_lost`, "the boiler keeps losing the plugin's command", which clears after 24 h without a loss; never a hold | trace window 5 min; `commands_lost` at 3 within 24 h, cleared after 24 h without a loss | core `test_a_fall_back_after_an_outage_is_one_lost_command_for_both_targets`; `test_frequent_losses_raise_a_warning_never_a_hold`; J4 "gateway reset" (X1, Q2) |
| M2 | A held target back from unavailable or unknown, whatever it shows (A3, A4, C3; S-13) | S, H | EN | Hd | V, any EN | a reboot, OTA, Wi-Fi loss, the ESP's 15-min reboot without an API client | when it returns | its restored or initial value, or unknown (NaN) | LC | every held value sent again at once, echo or not; the value it came back with is not judged | — | core `test_a_held_target_device_restart_is_not_an_outside_change` (T-47); `test_held_values_are_sent_again_when_the_device_returns` (X1) |
| M3 | Held values refreshed (decision 6) | S, H (incl. OTGW `CH=`) | EN, GW, MQ | Hd | all | the plugin | every 5 min while controlling | not required | — | sent again with no echo required; not a rewrite; "last change" does not move | 5 min | core `test_held_values_are_sent_again_every_five_minutes_without_an_echo` (X1) |
| M4 | A single fall-back without a trace (answer E; A2 without a trace, B1 first time, C2) | S, H | EN, GW, MQ | X, Hd | OT, SA, V | one Data-Invalid or Unknown-DataID reply to ID 1 (the PIC drops `CS` silently); one lost EMS-ESP keep-alive; a PIC watchdog reset nobody sees; an automation writing the old value, first time | W1 | back at the baseline (or the OT thermostat's request), with no trace, and none such in the last 60 min; the heating switch back at its baseline alike (answer E) | LC | as M1 | — | core `test_a_single_untraced_fall_back_is_a_lost_command`; `test_heating_switched_back_without_a_trace_is_first_a_lost_command` (X1) |
| M5 | A second untraced fall-back within an hour that no send explains (answer E; B1) | S, H | EN, GW, MQ | X, Hd | OT, SA, V | an automation or script writing the old value; another OTGW client sending `CS=0`; an EMS bus controller | W1 | as M4, the second within 60 min, and no send explains it | AC | M8's reaction: this fall-back uses the day's one rewrite; the next change within 24 h → step aside | 60 min and 120 s (decided, answer E). A send explains a fall-back when the fall-back comes before the plugin's latest send was read back as its value, or within 120 s of a send of a new value (a change, not a keep-alive or resend); such a fall-back is judged under M4 or M6, never AC | core `test_a_second_untraced_fall_back_within_an_hour_is_another_controller`; `test_a_fall_back_a_send_explains_is_not_another_controller` (X1) |
| M6 | Refused from the start (A5, C5 cause 4, D1, D2; S-48) | S (H alike) | GW, MQ, EN | X, Hd | OT, SA, V | the boiler refuses the value (Data-Invalid to ID 1, a value outside its range); a gateway in monitor mode | W0–W1' | never read back as the plugin's for longer than 120 s — back at the baseline, or never shown — after each of the session's first 3 sends | IS | an IGNORED event, once; the information alarm `write_ignored` for this target: "the boiler does not accept the command — check the settings"; the confirmation shows `not_confirmed`; that target is not written again this session, keep-alives included; the other target and frost heating go on; no block, no latch; tried again at the next session; a hand-back only with decision 7's option on and a thermostat or the boiler's own control to take over. Exception (answer O): where H is the ignored target and "off" is among the values it did not take, the plugin can no longer switch heating off — control is blocked and the boiler handed back at once (the safe hand-back), with `write_ignored` naming the heating switch; the blocker `heating_off_ignored` names the reason until the user switches control off and on, kept through reloads and restarts (X1, X5.21) | 3 sends; 120 s (provisional, K4) | core `test_a_value_refused_after_every_send_is_ignored_from_the_start` (IGNORED once; no further writes to that target; no OUTSIDE_CHANGE); `test_a_baseline_held_from_the_first_send_is_ignored_not_another_controller`; `test_ignored_from_the_start_keeps_the_other_target_and_frost`; `test_heating_off_ignored_from_the_start_blocks_and_hands_back` (X1); simulator: the gateway dropping `CS` after a refusal (Z3, Open after R6 #2) |
| M7 | Clipped (C7; C5 cause 3) | S | EN (e.g. EMS-ESP `selflowtemp`, whose state is the boiler's selected flow) | X, Hd | V | the boiler's own maximum; a panel dial below the plugin's value | W1', W1 | one value, within 0.5 K, lower than every value sent since the first unconfirmed send, across at least 2 sent values at least 1 K apart | CL | information: "the boiler limits the water to N °C"; the plugin keeps sending its own value (keep-alives and changes, no rewrite counted) and never takes the clip as a limit of its own (principle 13); ends when a read-back matches a sent value. Known limit (K4): a clip of a setpoint that stays flat cannot be told from another controller and is judged as M8; a bus controller holding a steady lower value looks the same. Behind an OTGW a clip cannot be seen (M18) | 1 K; 2 values; 0.5 K (provisional, K4) | core `test_a_lower_value_whatever_the_plugin_sends_is_clipped`; `test_a_clip_is_never_learned_as_a_limit` (X1) |
| M8 | Another controller: a foreign value (A6, E1; device-internal controllers) | S, H | EN, GW, MQ | X, Hd | OT, SA, V | an automation, a script or a person in Home Assistant; another integration (SAT, `opentherm_gw`'s CH override switch, another MQTT client, the OTGW web UI); an ESPHome on-device automation; DIYLess's own mode; an EMS bus controller; the OTGW's boot commands (`CS=x`) | W1; W0/W1' where never read back as the plugin's | a value held 2 steps (20 s) that is none of these: the plugin's value, its previous one, the baseline, the OT thermostat's own request, a clip (M7) | AC | rewritten once (remembered for its day, through a clean restart and through switching control off and on); a second change within 24 h, or the rewrite not read back within 120 s → step aside with the full safe hand-back (answer H). OT: the thermostat keeps heating. SA, or V with "heating stops": the boiler heats under the other controller when one is active, else not | 20 s; 120 s; 24 h | T-01; core `test_another_controller_is_rewritten_once_then_the_plugin_steps_aside`; integration `test_the_step_aside_makes_the_full_safe_hand_back`; `test_the_step_aside_latch_survives_a_restart`; `test_return_by_itself_after_an_hour_without_a_foreign_value` (X1, V5, V7) |
| M9 | A foreign value while the plugin's value keeps changing, or after an unknown read-back at the send (the verifier's missing rows) | S | all | X, Hd | all | as M8 | W1' (a ramp gives a new value every 30–40 s; a new decision; a frost start) | as M8 | AC | as M8: the 120-s window no longer restarts for a value another controller holds, and an unknown read-back at the send no longer hides it | — | core `test_a_foreign_value_is_judged_while_the_setpoint_ramps`; `test_a_foreign_value_after_an_unknown_read_back_at_the_send` (X1) |
| M10 | A difference seen in one step only (C8) | S, H | all | X, Hd | all | a glitch | W1 | differs for one step | — | not judged; judged once it holds 2 steps | 2 steps (20 s) | core `test_a_one_step_difference_is_not_judged` (X1) |
| M11 | Read-back unknown or unavailable while writing (D3) | S (H with an echo) | EN: writes go on; GW, MQ: a write with the read-back unavailable fails and is retried each step (`transport/writers.py:228-238`), while unknown counts as done | X, Hd | all | an echo entity down; a broker restart | W1 | `unknown` or `unavailable` | — | nothing judged meanwhile; after 5 min, the information alarm `confirmation_missing`, "the boiler's confirmation is missing"; never a hand-back by itself — the boiler link (flame, flow) decides that (X2) | 5 min | core `test_an_unknown_read_back_is_not_judged_and_informs_after_five_minutes` (X1) |
| M12 | A hand-back against another controller (B2) | S, H, E | EN | X, Hd | OT, SA, V | as M8 | W3 (a step aside's hand-back included) | S: a steady value that is neither the plugin's nor the hand-back value, for 2 retries. H, E: the hand-back state was read back once, then changed with no trace of an outage; before that read-back the target stays owed and is retried | AC holds it | the hand-back counts as done for that target, with no retry every minute; shown `taken_by_other`; V5's repair issue `hand_back_taken_by_other_<entry_id>`, at alarm level where the effect is "heating stops", else warning; the owed marker clears when every target is done | 2 retries (2 min) | integration `test_a_hand_back_counts_as_done_when_another_controller_holds_the_target`; `test_a_heating_switch_read_back_on_then_switched_off_is_taken_by_another` (V5) |
| M13 | The release not confirmed on a device that keeps its last value | S | EN | Hd | V (a target declared held, e.g. ESPHome, DIYLess) | the device | W3 | still the lowest water temperature the hand-back wrote first | — | an alarm at once; the release retried every minute until it is read back | 60 s (existing, `control.py:84`) | integration `test_an_unconfirmed_release_leaves_the_lowest_water_temperature_and_alarms` (V5) |
| M14 | External-control switch turned off while it stayed available (D4) | E | EN (hand-back method "switch") | declared (P-40) | V, any EN | a person, an automation, its own button | W1 | off, with no trace | AC | step aside at once, without a rewrite ("without a fight"): the full safe hand-back (answer H) — the water to the lowest water temperature, heating on where the boiler returns to a thermostat or its own control; the switch, already off, counts as the release; then no further writes; notification (`control_latched_<entry_id>`); latch. Answer C's way of telling the cases apart applies here too (provisional, K4) | 5 min trace window | integration `test_the_external_control_switch_turned_off_steps_aside` (X1) |
| M15 | External-control switch off after a device restart (D4 × A3) | E | EN | declared | V | a device restart | when it returns | off, after `unavailable` or `unknown` within 5 min | LC | switched on again; counted as a loss | 5 min | integration `test_the_external_control_switch_off_after_a_restart_is_switched_on_again` (X1) |
| M16 | A hot-water draw (C6, E6) | H echo; S | GW, MQ, EN | X, Hd | all | the boiler's hot water | W6 | a boiler-state echo ("running", slave CH active) goes off; `TSet` still carries `CS` (inferred) | — | a boiler-state heating echo is not judged during a draw or for 2 min after it; the form's text names the right `opentherm_gw` entity (Y1, P-22) | 2 min | T-21 (Y1, Z3) |
| M17 | The plugin's own lapse; keep-alives; firmware resends; the clock set back (E3, E5, E7, E8) | S, H | all | X | all | the plugin | W7 | another value after more than 60 s of silence (2 × keep-alive) | — | sent again; not an outside change (as today, `core/guards.py` `_lapsed`) | 60 s (existing) | existing `tests/core/test_guards.py` (regression) |
| M18 | Changes no read-back can see (D5) | — | all | — | all | CH off or summer mode at the boiler's panel; a lockout; the maker's app; another controller's `MM`; the DHW-enable bit; a boiler clamping `CS` behind an OTGW | W1 | nothing: the gateway's echo still shows the plugin's value | outside the guards | not an outside change; seen only through the comfort correction at its limit (about 4.5 h, information) or `frost_not_warming` (2 h, in frost); a fault the boiler reports stops heating under "Boiler protection"; named in K1's known limitations | — | none new (documented) |
| M19 | The recognition period after a start or a VT reload | S, H, R | all | X, Hd | all | Home Assistant restarting; VT reloading | W4 | anything | — | where control held the boiler before, its last command is restored at once under decision 3's restore conditions (E), with keep-alives; until the write target and the boiler link are available nothing is written and the restore waits, and a link not yet reported never turns it into a hand-back; a read-back not yet showing it is the plugin's own lapse: sent again, not counted; a lost or damaged store: assumed controlling, hand-back first (answer K) | at most 10 min | integration `test_a_restart_restores_the_last_command_without_an_outside_change`; `test_a_lost_store_hands_back_first` (X3, V3) |
| M20 | Hand-backs inside a session; the one-rewrite memory across a clean restart (B3, P-06) | S, H | all | — | all | a stale link; a transient blocker | W5 | — | — | the guards' memory (block, baseline) kept through hand-backs inside a session; the one-rewrite time kept for its day, through a clean restart and through switching control off and on (provisional, K4) | 24 h | T-01; core `test_the_rewrite_memory_survives_a_clean_restart` (X1) |
| M21 | The reaction "information" for another controller (A1, S-11) | — | — | — | — | — | — | — | — | moot: another controller always leads to a step aside; a stored "information" for `outside_change` is neutralised by decision 7's allow-list | — | `test_a_stored_information_reaction_for_outside_change_is_neutralised` (Y1) |
| M22 | VT's own central boiler configured (E9) | — | — | — | — | VT | — | — | — | a blocker, never an outside change (X7) | — | existing |
| R1 | Relay out of reach | R | RL | Hd | RL | a power cut; Wi-Fi or Zigbee loss | W1 | `unavailable`, `unknown`, or the entity missing | — (link lost) | nothing written while `unavailable` or missing, as it could not arrive; while `unknown` a new command is written but not confirmed (S-28; X8 R6); `relay_unreachable` and its repair issue after 5 min (`boiler_link_lost` does not exist on the relay path); no hand-back; frost protection keeps watching; on its return → R2 | 5 min (decided) | integration `test_a_relay_out_of_reach_alarms_and_is_not_handed_back` (X8) |
| R2 | Relay back in another state after a power or link loss (answer C) | R | RL | Hd | RL | its power-on state after a cut; a restart | when it returns (a trace: `unavailable` or `unknown` within 5 min) | the other state | LC | the command sent again at once; counted as a lost command (3 within 24 h → `commands_lost`, information) | 5 min; 3 within 24 h | integration `test_a_relay_back_in_another_state_gets_the_command_again` (X8) |
| R2a | Relay found in its declared power-cut state without a trace (answers D and N) | R | RL | Hd | RL | a restart Home Assistant did not see (e.g. a Zigbee relay without availability reporting) | W1 or the periodic check | the state the user declared for after a power cut ("off" or "on"), with no trace; with "last" or "I don't know" declared, any change from the command while the relay stayed available, with no trace | LC, up to 3 within 24 h; then AC | treated as a restart: the command sent again at once; counted; 3 within 24 h → an information warning (`commands_lost`, as R2). A fourth within 24 h is another controller: the plugin steps aside at once, with no rewrite first — the rest state set once, then left alone (answer L), with R3's latch and repair issue (answer N). With "last" or "I don't know" declared, a change while the relay stayed available is a possible restart in the same way: sent again up to 3 times within 24 h, the fourth → step aside (answer N). Restarts with a trace are R2's (answer C) and do not count toward the fourth (this file's reading of "such restarts": the ones without a trace; to confirm at K4) | 3 within 24 h, the fourth steps aside (decided, answers D and N) | integration `test_a_relay_found_in_its_power_cut_state_is_a_restart`; `test_a_fourth_power_cut_state_restart_in_a_day_steps_aside`; `test_a_change_with_the_power_cut_state_unknown_is_resent_three_times_a_day` (X8) |
| R3 | Relay switched while it stayed available (answer C) | R | RL | Hd | RL | an automation; a person in Home Assistant; another integration; its own button or local input | W1 | the other state, with no trace, not the declared power-cut state, and the power-cut state declared "off" or "on" (with "last" or "I don't know", R2a) | AC | rewritten once; a second change within 24 h → step aside with the full safe hand-back (answer H): the rest state written once, even over the other controller's state, then nothing more is written, read back or not (answer L); the repair issue `control_latched_<entry_id>` naming the rest state — "on": the boiler heats on its own dial or thermostat without room control (warning); "off": heating stops unless an old thermostat in parallel heats (alarm); latch; no return by itself for relays | 24 h | integration `test_a_relay_switched_twice_while_available_steps_aside_to_its_rest_state` (X8) |
| R4 | The periodic check finds a mismatch | R | RL | Hd | RL | a change the plugin missed (e.g. during a reload) | every 5 min | not the commanded state | by its trace and state: LC (R2, R2a) or AC (R3) | as R2, R2a or R3 | 5 min | integration `test_the_relay_check_classifies_a_missed_change_by_its_trace` (X8) |
| R5 | The relay's own switch-off timer fires (declared, or "I don't know") | R | RL | behaves as X | RL | the relay's timer | for a declared length: at or after max(timer − 60 s, timer ÷ 2) since the "on" that started the current on-period; for "I don't know": at least one repeat interval after that "on" | off | — (own lapse) | "on" sent again, not counted. An "off" earlier than that is judged as any change while the relay stayed available: R2a or R3 | max(timer − 60 s, timer ÷ 2) from the start of the on-period; `relay_repeat_s` (10–300 s, default 300 s) (provisional, K4) | integration `test_a_relay_timer_lapse_is_not_another_controller` (X8) |
| R6 | A relay that reports no state (declared "no" or "I don't know", or `assumed_state`) | R | RL | Hd | RL | — | W1 | nothing to read | — | blind repeats every `relay_repeat_s`, as in R5; shown "controlled without confirmation"; outside changes cannot be seen, and a manual change is undone at the next repeat (risk text) | `relay_repeat_s` (default 300 s) | integration `test_a_relay_without_a_state_gets_blind_repeats` (X8) |
| R7 | The relay never takes the command | R | RL | Hd | RL | a broken or wrongly picked entity | W0–W1' | never the commanded state for longer than 120 s after each of the session's first 3 sends | IS | not written again this session; `write_ignored` and the repair issue `relay_ignored` at alarm level (severity error), "the relay does not accept the command — check it", because nothing else controls the boiler; tried again at the next session. Where the ignored command is "off": control blocked (`heating_off_ignored`, until off and on), and the issue says the boiler may keep heating (answer O applied to relays, 2026-09-27) | 3 sends; 120 s (provisional, K4) | integration `test_a_relay_that_never_takes_the_command_is_ignored_from_the_start` (X8) |
| R8 | The relay's hand-back (an exit, a blocker, an alarm) | R | RL | Hd | RL | the plugin | W3 | the rest state | — | the rest state: "off" by default, "on" by the user's choice; done once read back (unconfirmed without a state report); at a step aside it is written once even over another controller (answer H), and the relay is then left alone, read back or not (answer L); after any other hand-back, a relay the other controller switches after its rest state was read back once counts as handed back (as M12); a notification when "off" leaves the house without heating while a zone calls or frost protection is active | — | integration `test_a_relay_hand_back_goes_to_its_rest_state` (X8, V5) |
| R9 | A planned restart of Home Assistant | R | RL | Hd | RL | the plugin | at the stop, then W4 | — | — | the rest state at the stop; the last command restored at once at the start, before the zones report, with no activation delay | — | integration `test_a_planned_restart_restores_the_relay_at_once` (X8, V3) |

*G. The fixed values (S-37)*, as a table in §7: value, where it lives in the code, and why. A value whose reason is not recorded is marked "reason to confirm at K4", rather than given a reason. Every value any step defines is listed here, and Q4's K4 agenda takes every provisional one.

- **Existing, from the code:**
  - control step 10 s (`const.py:44`; heating follows the zones at once);
  - keep-alive 30 s (`control_config.py:30`; OTGW needs `CS` at least once a minute);
  - lowest OTGW `CS` 8 °C (`transport/writers.py:34`; below 8 °C an override never lapses);
  - confirmation timeout 120 s (`core/guards.py:81`; reason to confirm);
  - tolerance 0.5 K (`core/guards.py:82`; reason to confirm);
  - write interval at least 5 s (`core/guards.py:43-45`; one write per step);
  - own lapse after 60 s of silence (`core/guards.py` `_lapsed`; an OTGW override lapses after about a minute);
  - rewrite window 24 h (`core/guards.py:42`; decided 2026-09-25);
  - hand-back retry 60 s (`control.py:84`);
  - lost link → hand-back after 5 min (`core/controller.py:130`; decided 2026-09-25);
  - zone-unknown alarm 30 min (`control.py:86`; reason to confirm);
  - restore wait 60 s (`control.py:87`);
  - outdoor hold 3 h (`core/curve.py:66`; decision 9);
  - outdoor time constant 3 h (`core/curve.py:65`; reason to confirm);
  - stuck sensor 12 h within 3 K; deviation 6 K over at least 2 h of overlap (`core/signal_check.py:146-149`; reason to confirm);
  - comfort correction +3 K, 30 min per K, 3 h at the edge, 1 K over stops the rise (`core/controller.py:54-58`; decided 2026-09-25);
  - frost not warming: 2 h, 0.5 K (`core/controller.py:59-60`; reason to confirm);
  - a zone takes heat above 5 % open, and is saturated at 95 % (`core/readings.py:38-39`);
  - comfort correction: satisfied below 70 %, short by 0.3 K (`core/controller.py:400-401`);
  - plausible room reading −30 to 45 °C (`core/limits.py:81`). S-06, provisional (K4): this one rule for every room reading. The narrower 5–35 °C of `core/zones.py:11-12` would hide a cold room from frost protection, so it stays for setpoints only;
  - learning pauses: a swing of 5 K in 30 min, a pause of at least 10 min, resume within 3 K, longest pause 60 min, read back after 1 min (`core/learning.py:41-46`);
  - low-flow warning after 15 min (`core/alarms.py:271`);
  - a short burn is under 10 min (`core/metrics.py:24`; reason to confirm).
- **New in 0.2.2:**
  - decided:
    - recognition period at most 10 min, grace 10 min;
    - relay out of reach 5 min;
    - the untraced fall-back window 60 min, and a send explaining a fall-back within 120 s of a new value (answer E);
    - return by itself after 60 min;
    - a relay found in its declared power-cut state 3 times within 24 h → an information warning (answer D); a fourth within 24 h → another controller, the plugin stepping aside; with the power-cut state "last" or "I don't know", a change while the relay stayed available resent up to 3 times within 24 h, the fourth → another controller (answer N);
    - at a step aside, a relay set once to its rest state and then left alone (answer L);
    - the plugin's own monitor failing → a hand-back after 5 min (answer I; V6's 300 s);
  - decided: the activation delay 0–600 s in steps of 10, default 0;
  - decided: "off" at least 1 K below the lowest water temperature (plan X1, P-43), and "off" refused within 0.5 K of an "own control" hand-back value (plan V5, S-49);
  - decided: the circuit-maximum alarm pre-filled at the maximum + 5 K and 10 min, only for a circuit with a maximum (decision 10, X4);
  - all provisional (K4):
    - relay check 5 min;
    - blind repeats every `relay_repeat_s` (10–300 s, default 300 s, pre-filled from VT's keep-alive only where it lies within 10–300 s);
    - a relay timer's lapse at or after max(timer − 60 s, timer ÷ 2) from the start of the on-period (an unknown timer's: one repeat interval from it), and its renewal every min(timer ÷ 2, `relay_repeat_s`);
    - held values resent every 5 min;
    - the lost-command alarm `commands_lost` at 3 within 24 h, cleared after 24 h without a loss;
    - the trace window 5 min;
    - a difference judged after 2 steps (20 s);
    - ignored from the start: never shown for longer than 120 s after each of the first 3 sends;
    - clipped: one lower value, within 0.5 K, across at least 2 sent values at least 1 K apart;
    - read-back unknown or unavailable → `confirmation_missing` after 5 min;
    - the boiler-state echo not judged within 2 min of a draw;
    - a hand-back held by another controller after 2 retries;
  - more provisional values (K4):
    - an alarm level counts once held 5 min;
    - a notification closes after 60 min in range;
    - an alarm with an unknown input holds 60 min, then shows unknown (Y1);
    - a boiler fault stops heating after 5 min on;
    - the lowest water temperature 20 °C;
    - the wall-thermostat warning below 15 °C;
  - still more provisional values (K4):
    - the margin of a passive fixed circuit 5 K (S-42; reason to confirm);
    - a timeout hand-back released within 0.5 K of the session's baseline, with `hand_back_failed` after 3 min without release (S-20);
    - a relay's proof-of-heat window 30 min after "on", longer than a common 20-min restart lockout (`research/2026-09-26-on-off-plugin-code.md` §3.4 and its corrections; X8);
    - "not worth it" only with at least 2 criteria judged (S-32);
    - a stand-alone installation handed back in frost raises the alarm at the next step while a watched zone reads below the frost limit (5 °C default), and clears it at or above the release (7 °C default) (S-57);
    - the lowest-water-temperature suggestion: the reference + 2 K, rounded up to 0.5 °C, kept below the caps (X6);
    - J4's starts criterion: at most the boiler's own regulation's starts per hour × 1.10 (T-24, S-15);
  - defined by phases V–Z, each with the reason its step records or "reason to confirm at K4" (provisional, K4, unless a decision or an answer names it):
    - V3: the last command saved at once on a move of 1.0 K;
    - V4: stop wait 5 s; stop hand-back 15 s; each stop write 4 s; start grace 60 s; OTGW release window 60 s;
    - V5: a held release's alarm after 10 s; taken by another after 2 checks 60 s apart (3 over 120 s with hot water unknown, none within 120 s of a draw); `hand_back_failed` after 3 min;
    - V6: monitor failure 300 s (answer I) within a 600-s window, and control resuming after 60 s without a failed refresh;
    - V7: the blocker-stopped-heating issue after 60 s;
    - X1: a joint fall-back of both targets within 20 s counted as one loss; an attempt with a trace of an outage not counted toward "ignored from the start"; a target ignored from the start tried again at the next session;
    - X2: link window 600 s, recovery 60 s;
    - X3: the P-105 grace 600 s, with a restorable store standing for "known not configured" after a restart; the restore's wait bounded by the recognition period; frost heating during the recognition period; control resuming by itself after an every-zone-unknown hand-back; the `no_zone_known` issue severities;
    - X4: circuit-alarm hysteresis 1 K; alarm time 1–120 min; correction at most 3 K a day; the DHW resume cap 1 h after the draw; nothing written while the activation delay waits at a new session; the closed-zone issue only while control is configured and on;
    - X5: design flow ≥ room + 5 K; design outdoor ≤ room − 10 K;
    - X6: 7 days; 20 burns; share 0.5; 1 K bands; 50 % opening; +2 K; 2 K under the caps; the 30-min wall-thermostat issue; the 25 °C migration floor;
    - X7: the 10-min setup-error issue; a 0.05 factor change;
    - X8: timer tolerance 60 s; flow rise 5 K; 20 remembered contexts; `relay_repeat_s` 10–300 s, default 300 s; the relay check 5 min; the proof window 30 min;
    - Y1: 5-min holds; 1-h unknown hold; 50 % known flame; limit − 2; 2 K; 10 K slope span; 0.05 bar/K; 40 °C; 0.1 bar;
    - Y2: 0.35–0.65; 12 h; 6 h; 10 min; 1 h;
    - Y3: 8 K; 12 K; 2 K; 3 of 4; 2 of 3;
    - Y4: forecast call 30 s;
    - Z1: complexity 12;
  - the wait for a late report at start and stop: to be settled by Q3 (P-50, question 18); provisionally 60 s at the start, and within Home Assistant's stop budget at the stop.

*H. Terms that the steps' translations follow* (so X- and Y-steps use one wording):
- **Notification:** a Home Assistant repair issue (issue registry, severity by the alarm's level), raised without a service call so that the allowed-services rule holds (`docs/plan-0.2.md` Rules; the pattern is at `control.py:133-144`). Its translated text says what happened and what to do, and it closes by itself when its condition clears.
- **Alarm:** the plugin's alarm entity, at the levels warning and alarm. "Information" is an alarm that never changes control.
- **Zones calling:** the demand count (S-36).
- **Lowest water temperature** (the key `hard_min` stays).
- **Working thermostat:** a gateway with an OpenTherm thermostat declared on its terminals, the entity path with the "own room controller" tick, or the relay path with the tick and the rest state "on" (answers F and M). A relay resting "on" without the tick is not one, nor the tick with the rest state "off"; the tick is not offered on a gateway.
- **Held:** a target declared held (ESPHome, DIYLess and the like); not EMS-ESP's `selflowtemp`, which expires within about a minute.
- **Trace of an outage:** as in F's legend.
- **Rest state; relay; controlled without confirmation.**

*I. The text-only S-items, and the SCOPE text for S-items that later steps build.*
- S-07, S-12: E above.
- S-28, S-20, S-21, S-27, S-45, S-49, S-54: D above.
- S-29, §5 zone algorithms: "SmartPI: learning pause"; SmartPI's "better signal, bootstrap state" go to §9 Later; Auto-TPI is "detected, not paused, with a repair issue".
- S-33: "the emitter types of its zones" (l.193-194).
- S-38: switch zones follow VT's device state, so the boiler may start once per TPI cycle.
- S-44: temperatures in °C, differences in K, and the form shows the unit.
- S-47: the ramp's reason: it keeps a setpoint step small enough that the boiler does not overshoot it, and zone algorithms follow (SmartPI pauses learning on larger swings). It is skipped only for installation limits (S-23).
- S-50, principle 9: SmartPI 0.4.0 learns its own outdoor term (`u_ff1`), which cannot be set, and the documentation says so.
- S-59: remove monitor mode from §5's list of hand-back methods (l.138-139); rewrite §3 p.11's and §7's "On/off without feedback" sentences for class 3; drop "the curve as the main mechanism" from §8's "Not taken"; qualify "never below 8 °C" — `CS=0` at hand-back cancels the override and is not a setpoint.
- S-60: the fresh flow read after a write, the overshoot calibration, MemberID, the condensing indicator and the installer settings go to §9 Later, with no release, unless the user names one at K4.
- S-61: learning pauses (DHW, foreign heat) move to the control stages.
- S-62, S-30: decision 7.
- S-08, S-24, S-25: the comfort correction.
  - It counts only zones taking heat.
  - "Heat flows" means the flame when it is known, else the command.
  - Every rule of principle 13 is mapped, and the correction freezes while a cap holds the setpoint.
  - Its value is published and can be reset (P-38) with a "Reset comfort correction" button, in a new `button.py` (answer J; X4 builds it).
- S-34, S-35, S-06, S-04, and the power criterion: §7 demand.
  - A started zone whose mode is "off" has no demand; one VT has not started (`is_ready` not true) is unknown, also after the recognition period (decision 1 of `docs/plan-0.2.3.md`).
  - VT's `safety_state` counts as a lost sensor.
  - Power shedding removes a zone's demand.
  - Control needs at least one VT zone.
  - A VT device power of 0 or less is no data.
- S-41: every hot-water draw pauses SmartPI, as the zones get no heat meanwhile.
- S-42: the passive fixed circuit's margin.
- S-09, S-10, S-57: after a stand-alone hand-back, the switch says that frost protection now rests on the boiler. The alarm `handed_back_in_frost` rises at the next step while a watched zone reads below the frost limit, and clears at or above the release (provisional, K4).
- S-16, S-17, S-22, S-31, S-32, S-43: §7 alarms and §10, as Y1–Y3 build them:
  - gas measured while the burner is off is reported apart (provisional, K4);
  - the load criterion counts only with an entered or confidently measured model (confidence at least 0.5, `core/parameters.py:85`);
  - the verdict's reasons name what the released control changes. The verdict "worth enabling" comes only from problems that 0.2.2's control changes; the others are shown as "not changed yet" (answer K);
  - off-season, the switch says control starts without a verdict.
- The plan's answers to review questions 3, 5, 6, 8–12, 19 and 20 are written in §11 as provisional (K4).

*Document changes of Q1 and Q2, section by section.*

**`SCOPE.md`** (all Q1):
- **§3 principles:**
  - p.2: add the missing-data rule by reference to §7;
  - p.3: for class 3, only heating on and off;
  - p.9: S-50;
  - p.11:
    - "no write without fresh data" split (water-temperature control needs flame and flow; a relay's link is the relay);
    - the relay's read-back exception;
    - "written again at most once, then an alarm" replaced by decision 6's four classes;
    - "retried until it is confirmed" narrowed: a target another controller takes after the full hand-back of a step aside (answer H, M12), and the safe hand-back;
    - the hand-back value bounded by the circuit maximum and the highest water temperature (S-21);
    - the class-3 sentence at l.72-74 rewritten;
  - p.12: B above;
  - p.13 rule 7 and S-58: C above.
- **§4 user levels:** the wizard adds the thermostat kind, the "own room controller" tick (answer F; on the entity and relay paths only, answer M), and the relay's settings with its "separate contact" tick (answer G). Alarms get thresholds per alarm, and a reaction only where decision 7 allows one. Learning's "change-per-day limit" becomes the tuning band (S-58).
- **§5 Boilers:**
  - class table: class 3 from 0.2.2; class 2 as suggestions only;
  - write-path list: add the relay;
  - hand-back bullet: D above, plus the rest state; monitor mode removed (S-59); S-28 and S-09;
  - class-2 bullet: persistent writes dropped (S-56);
  - class-3 bullet: E "Class 3" above;
  - circuits: S-33 and S-42.
- **§5 Gateway topology:**
  - the table splits "gateway | physical" by thermostat kind, and adds the relay row;
  - bullets: decision 1, with answer K's notice for an entry without the answer; the wall-thermostat texts; the relay exception to "a lost boiler link hands back in every topology"; the OTGW hand-back as `CS`=lowest, `CH=1`, `CS=0` (V5).
- **§5 zone algorithms:** S-29, S-41.
- **§6 data:** the source chain (S-58); installer settings go to Later (S-60).
- **§7 stage table:** alarms with a reaction only where decision 7 allows; the condensing indicator goes to Later; FC1 and the anti-cycling row marked "to be decided against principle 12"; learning pauses moved (S-61).
- **§7 "Across all stages":** S-61.
- **§7 Control base:**
  - the missing-data paragraph (A);
  - demand (S-36, S-38, S-34, S-35, S-04, the power criterion);
  - decision 3, with answers F and M: the working thermostat and the "own room controller" tick;
  - "Stopped" (kept);
  - frost (decision 4);
  - the activation delay (decision 5);
  - the lowest water temperature and its suggestion (decision 2);
  - the circuit maximum (decision 10);
  - the outdoor temperature (decisions 9 and 12);
  - the comfort correction (S-08, S-24, S-25), with its reset button (answer J);
  - "off" (decision 11, with answer K on lifting the block, and answer O: a boiler that ignores "heating off" from the start blocks control too);
  - boiler protection (the two fault signals).
- **§7 fixed safeguards:**
  - freshness (the relay; X2's window and each signal's own age limit);
  - the lost link (the relay exception);
  - hard limits (the lowest water temperature; P-43; S-49; S-59 on 8 °C);
  - persistent memory (held values resent; S-12);
  - units (S-44);
  - read-back (the relay exception; S-09; S-28);
  - the outside-change bullets (l.374-382) replaced by the matrix (F);
  - exits and hand-back (D; S-45; S-54; the step aside's full hand-back, answer H; the plugin's own monitor failing, answer I);
  - the "controlling" marker (V1, V3: control state saved at once and atomically, including the last command). A lost or damaged store: the plugin assumes it was controlling and hands back first (answer K).
- **§7 resume table:** new rows —
  - another controller: a step-aside latch until off/on, or the return by itself; not for relays;
  - the boiler's own fault: resumes by itself in the step where every mapped fault reads off, unknown or unavailable;
  - relay out of reach: the command again when it returns;
  - a relay found in its declared power-cut state: the command again (answer D); the fourth within 24 h, or with that state "last" or "I don't know" the fourth change within 24 h while it stayed available, is another controller: the step-aside latch until off/on (answer N);
  - every zone unknown: resumes when a zone answers;
  - ignored from the start: the next session; the heating switch's "off" ignored from the start: blocked until the user switches control off and on (answer O);
  - the plugin's own monitor failing: resumes by itself once it works again, with an information note (answer I);
  - an alarm with a hand-back reaction already active when switched on: blocks at once.
- **§7 options:**
  - demand (S-36; the per-zone "closes when VT switches it off");
  - the ramp (S-47, S-23);
  - the activation delay (on the relay path too);
  - the lowest water temperature;
  - the circuit-maximum alarm;
  - "off" (decision 11);
  - write type (S-12; OTGW `CH=` held);
  - the heating read-back, and the optional field "the OpenTherm thermostat's requested control setpoint" (only with "gateway with thermostat"; refused as the setpoint read-back);
  - freshness per signal;
  - frost (decision 4);
  - the alarm reactions (decision 7);
  - the two boiler-fault signals and the "add water" threshold;
  - the return by itself (not on the relay path);
  - the thermostat kind;
  - the "own room controller" tick (answer F), on the entity and relay paths only, and on the relay path counting only with the rest state "on" (answer M);
  - the relay's settings (the "separate contact" tick, answer G; `relay_repeat_s`), rest state and proof of heat.
- **§7 defaults table:**
  - "Hard minimum" becomes "Lowest water temperature: 20 °C (provisional, K4)", with both risks;
  - Ramp (S-47);
  - "Off" setpoint (only where "off" uses one);
  - Frost protection (decision 4);
  - Alarm reaction (decision 7);
  - Demand threshold ("one zone calling");
  - new rows:
    - activation delay 0 s;
    - circuit-maximum alarm;
    - "add water" (none);
    - relay rest state "off";
    - relay settings "I don't know" (the state report treated as "no");
    - relay repeat 300 s;
    - relay "separate contact" tick not ticked (control does not start without it);
    - thermostat kind (none — required; "I don't know" blocks control);
    - "own room controller" not ticked;
    - return by itself (off);
  - a new "Fixed values" table (G).
- **§8:** the start budget marked (decision 13); the fresh flow read, the overshoot calibration and Leaf moved to Later (S-60); "Not taken" (S-59).
- **§9 Later:** S-60's items; SmartPI's better signal and bootstrap state; relay commands beyond a switch and a boiler thermostat entity; a separate echo entity for the relay; the "apply" mode (0.3); the wall-thermostat link (0.3 at the earliest); a mixing valve behind one written circuit (0.3).
- **§10:** the monitoring period counts from the entry's creation (V1; answer K); the verdict "worth enabling" only from problems that 0.2.2's control changes, the others shown as "not changed yet" (answer K); S-17, S-22, S-32, S-43.
- **§11 Open decisions:**
  - the L4 item is closed (decision 11); lifting the block waits for the user at K4 (answer K);
  - a "Decided 2026-09-26/27" entry lists decisions 1–15 and answers C–O in one line each;
  - the 2026-09-25 paragraph marks what changed (frost as the "one exception"; the lost link for a relay; "never confirmed = outside change"; "known zones decide");
  - "Provisional control decisions (K4)" and "Provisional write decisions (K4)" are rewritten to the decisions and answers:
    - class 3;
    - the four classes, with no reaction choice;
    - the safe hand-back, made in full at a step aside (answer H);
    - not retried against another controller;
    - "off" without a heating switch blocked until the user lifts it at K4 (answer K); a boiler that ignores "heating off" from the start blocked and handed back until the user switches control off and on (answer O);
    - the heating switch turned on only where the boiler returns to a thermostat or its own control;
    - the control switch back after a restart as the user left it, the wish saved at once, with a disabled switch entity meaning control off (answer K; V3, question 6);
    - the plugin's own monitor failing for 5 min hands back and resumes by itself (answer I);
  - the answers to the review's questions, marked provisional;
  - "the first pre-release is 0.2.1b1" becomes 0.2.2b1 (provisional, decision 16).
- **§12:** "Public from 0.2.2 (provisional, decision 16), pre-release 0.2.2b1"; the repository's content is decided at K5.

**`PLAN.md`:**
- [Q1] "Test environment": CI fetches VT 10.4.0 and SmartPI 0.4.0 from their tags on GitHub's servers, so the real-VT tests run on every change; nothing is downloaded locally (decision 14).
- [Q1] "Releases" (l.47-48): "0.1 is published with 0.2, as 0.2.2 — the first release (provisional, decision 16); 0.2.1 and 0.2.2 correct 0.2 after its reviews (`docs/plan-0.2.1.md`, `docs/plan-0.2.2.md`)."
- [Q1] The 0.2 row (l.55):
  - "published as 0.2.2 (provisional)";
  - frost as one of principle 12's stated exceptions;
  - "boiler demand from zones calling";
  - held values resent after a return and every 5 min;
  - write guards as decision 6's classes;
  - alarm reactions as decision 7;
  - the safe hand-back;
  - class 3 through a relay;
  - the missing-data rule;
  - the thermostat kind and the "own room controller" tick.
- [Q1] "Release plans": add "0.2.2 — `docs/plan-0.2.2.md` (details: `docs/plan-0.2.2-details.md`): the corrections after the review of 2026-09-26 and the user's decisions of 2026-09-26/27; the first version to be published (provisional)". Drop "the first version to be published" from the 0.2.1 line.
- [Q2] The 0.3 row (l.56):
  - duty cycling and FC1 marked "to be decided against principle 12 (decision 13)" (S-18);
  - add the wall-thermostat link (VT leading, off by default, at the earliest);
  - add the "apply" mode of the lowest water temperature;
  - add radiators and underfloor behind a mixing valve (S-42's second part).
- [Q2] "Later" (l.59): drop "on/off-only boilers (relay)"; add "relay commands beyond a switch and a boiler thermostat entity (VT's free-form actions), if asked".
- [Q2] Track C (l.24, S-46): what the simulator has — one unmixed loop (`sim/custom_components/boiler_sim/profiles.py:113`). Mixed and separately controlled circuits come with 0.3.

**`CLAUDE.md`** (all Q1):
- **"Where to continue" (l.3-9):**
  - name `docs/plan-0.2.2-details.md`;
  - "0.2 is the first release" becomes "the first published version is 0.2.2 (provisional, `docs/plan-0.2.2.md` decision 16)";
  - add: "A 🔒 step waits for the user; where its plan says it holds nothing up, or only a later step needs it, note it and continue (today: plan 0.2.1 R2, plan 0.2.2 Q4)".
- **Plans list (l.12-14):** add the details file.
- **Working rules:**
  - l.23: replies to the user in plain, less technical Polish; every finding and result saved in the working directory (the user's rule of 2026-09-26/27);
  - l.59-63: ✅ marks and additions to "Open after 0.2.2" are committed without waiting, with the diff in the step's report; pending `*.md` diffs stay uncommitted, and code is committed by path (answer B);
  - l.64: "work stops at every 🔒 step" qualified as above;
  - l.38-47: CI on GitHub's servers fetches VT 10.4.0 and SmartPI 0.4.0 from their tags, with nothing downloaded locally (decision 14);
  - l.72-77: J4 may provoke an unclean restart with `docker kill` over SSH in the test LXC only, after the user says to start (decision 15).
- **Verified facts**, each fact with its source:
  - VT 10.4.0's central boiler (vendored; `config_schema.py:228-238`, `const.py:236-237, 532`; the checks note's reading of `feature_central_boiler_manager.py:143-216`):
    - activation delay 0–600 s in steps of 10, default 0; a drop during the wait does not cancel it, and demand is checked again at its end;
    - repeat interval `keep_alive_boiler_delay_sec` 0–3600 s, default 0;
    - its commands are free-form actions;
    - its power criterion uses each zone's `mean_cycle_power` (`sensor.py:1041`);
    - it counts heating devices, not zones;
    - unticking it deletes its two commands and needs a restart (the VT-native note; check against `vendor/` before writing);
  - `opentherm_gw` (`.venv/.../opentherm_gw/binary_sensor.py:43-49, 122-145, 354-358`; `strings.json` l.36, 57, 76, 157; `sensor.py:512-521`; `__init__.py:104-108`):
    - the boiler device has "Low water pressure", "Gas fault", "Air pressure fault" and "Water overtemperature" problem sensors;
    - it has two "Central heating 1" entities (running and enable);
    - the thermostat device has its own "Control setpoint 1";
    - it sends `CS=0` when it unloads;
  - pyotgw skips Data-Invalid and Unknown-DataID frames (`research/diy/pyotgw/2.2.3/messageprocessor.py:71-79`);
  - an OTGW firmware ESP boot resets the PIC (`research/diy/otgw-firmware/v1.7.5/OTGW-firmware.ino:196-199`).
  - Each topic lives in its own file: decisions are not copied into `CLAUDE.md`.

**`docs/plan-0.1.md`, `docs/plan-0.2.md`, `docs/plan-0.2.1.md`, `devenv/README.md`:** all [Q2], see Q2.

**Code to change.** None; Q1 changes text only. The code facts it cites are listed under "Read first". Z1 pins every default of the new SCOPE table in a test (P-127). Answer J's `button.py` is X4's code, not Q1's.

**Texts.** No translation key changes in Q1. The terms in H bind the later steps' `en.json` and `pl.json`: X6 renames `hard_min` from "Lowest flow setpoint" (`translations/en.json:532, 546`) to "Lowest water temperature" / "Najniższa temperatura wody". The new names Q1 writes follow them too: `commands_lost`, `confirmation_missing`, `relay_unreachable`, `relay_ignored`, `no_zone_known`, `control_latched`, `hand_back_taken_by_other`, the "own room controller" tick (X3) and the "separate contact" tick (X8).

**Missing data.**
- **A Q3 answer is not in yet:** write "(to be settled by Q3)" and the cautious provisional given here:
  - control without a heating switch stays blocked, and a favourable answer does not lift the block by itself (answer K);
  - the suggestion is X6's reference + 2 K, with no estimate from power;
  - only an entity that is unavailable, unknown or missing counts as a trace, and a restart counts only where Q3.7 finds a way to see it;
  - the two boiler-fault signals accept any binary sensor the user maps;
  - the late-report wait stays provisional.
- **The user has not consented yet:** the diff stays uncommitted, and phase V may go on.
- **A research note contradicts the plan:** the plan wins, and the note's proposal stays out of `SCOPE.md`. An answer of 2026-09-27 wins over both.
- **Unknown pieces of an installation** (thermostat kind, relay settings): the "I don't know" paths above, each taken as the cautious case. An existing gateway entry without the thermostat-kind answer keeps control stopped, with a notice (answer K).

**Do not.**
- Change code or translations.
- Copy decisions into `CLAUDE.md` (`CLAUDE.md` l.19).
- Commit an unconsented `*.md` change.
- Use the network (Q3 does).
- Write these proposals the plan rejected or never adopted:
  - counted drops leading to a hand-back, and "3 drops an hour";
  - a counted hand-back for repeated refusals;
  - "user_id → step aside at once" for relays;
  - "clamped → the cap becomes the upper limit";
  - a hand-back after 5 min of unknown read-back;
  - cancelling the activation delay when demand drops;
  - "refuse rest 'on' unless wired in series";
  - option B's banded hand-backs;
  - option C's season switch;
  - "heat on the curve with no zone known";
  - the "writes stopped" state;
  - the plugin switching VT's mode.
- Write what the answers of 2026-09-27 and the checks replaced:
  - a relay resting "on", or a hand-back value declared "own control" without the tick, counted as a working thermostat (answer F);
  - the "own room controller" tick offered on a gateway, or counted on the relay path with the rest state "off" (answer M);
  - a step aside that leaves out a target the other controller holds (answer H);
  - a relay's rest state written again after a step aside (answer L);
  - a relay that keeps turning up in its power-cut state, or (with "last" or "I don't know") keeps changing while available, answered for ever instead of stepped aside from at the fourth time within 24 h (answer N);
  - a heating switch whose "off" is ignored from the start left under control as information only (answer O);
  - a 10-min clip rule (M8 would always judge first);
  - "I don't know" on the relay's state report decided by `assumed_state`;
  - a declared relay timer refused when not longer than the repeat interval;
  - a separate echo entity for the relay;
  - a `ConfigError` for one entity mapped to two signals;
  - a Shelly test at J4 (K6 has it).

**Open for the user.** The draft's two questions are settled:
- answer E defines "a send that explains a fall-back" (M5);
- answer D treats a relay found in its declared power-cut state as a restart (R2a).

Answer H also settles a relay: its full safe hand-back is its rest state (the plan's "Safe hand-back": a relay goes to its rest state instead; decision 6: "a relay to its rest state"), written once at a step aside even over the other controller's state (R3, R8).

The two questions that remained are answered too, and are rules now:
1. On the relay path the "own room controller" tick counts as a working thermostat only where the rest state is "on"; with rest state "off", VT giving no answer means no heating and an alarm, as without the tick (decision 3). On a gateway the tick is not offered; on the entity path it is offered as answer F says (the user, 2026-09-27, M).
2. A relay found in its declared power-cut state is a restart only up to 3 times within 24 h; a fourth is another controller, and the plugin steps aside, setting the rest state once. With the power-cut state declared "last" or "I don't know" (the default), a change while the relay stayed available is a possible restart — the command sent again — up to 3 times within 24 h, then another controller in the same way (R2a; the user, 2026-09-27, N).

Answer L confirms answer H for relays: the step aside sets the relay once to its rest state, then leaves it alone (R3, R8; the user, 2026-09-27, L). Answer O settles a heating switch whose "off" is ignored from the start (decisions 6, 7 and 11 above; row M6; the user, 2026-09-27, O).

Two readings are put on the K4 list: that only restarts without a trace count toward N's fourth (R2a); and that M's "on a gateway" means every gateway topology, the entity path with a gateway topology included (X3).

---

### Q2 — Plan corrections: stale texts, J2, J4, K1, K4, K5, K7, `docs/plan-0.2.1.md`, `PLAN.md`'s 0.3 and "Later" rows

**Goal and done-when.** The plans, `PLAN.md`'s 0.3, "Later" and Track C rows, and `devenv/README.md` carry no stale step and no text that the decisions of 2026-09-26/27 or the answers of 2026-09-27 made wrong. L4 is ✅. J2, J4, K1, K4, K5, K6 and K7 describe what 0.2.2 needs. Done when:
- every item below is written, shown and consented, or its remainder is named in "Open after 0.2.2";
- the checks pass;
- phase Q's "the plans have no stale step" holds.

**Read first.**
- Plan: the Q2 row (l.384); decisions 1, 3, 4, 6, 7, 11, 13, 15, 16; the answers A–O of 2026-09-27 (above); "After 0.2.2".
- Review: S-15, S-18, S-19, S-46, S-50, S-52, S-53, S-54, S-55 (`docs/review-2026-09-26.md` l.318-358), and T-07, T-24, T-25 (l.1300, 1317, 1318).
- `research/2026-09-27-fresh-session-test.md` "Q2" (l.260-297); `research/2026-09-27-plan-0.2.2-checks.md` (l.267-269).
- `docs/plan-0.1.md` (B4 l.77, B7 l.80, D5 l.115).
- `docs/plan-0.2.md` (l.6-8, 14-19, G0 l.99, G7 l.106, G10 l.109, H0 l.122, H2 l.124, H3 l.125, I3 l.137, J1–J4 l.148-151, K1–K7 l.159-165, "Done for 0.2" l.167-171, "Open for 0.2" l.173-202).
- `docs/plan-0.2.1.md` (l.1-13, 158-169, L4 l.192, M4 l.213, N5 l.237, "Open after R6" l.319-351, l.353-363).
- `devenv/README.md` l.11-28; `devenv/compose.yaml` l.11-12 (port 8123 is published, so the traffic is forwarded).

**Order of work.** Checks as tests:
- `check_l4_marked`: given `docs/plan-0.2.1.md`, when the L4 row is read, then it shows ✅ and its reason.
- `check_versions`: when `docs/plan-0.2.md` is searched for "0.2.1b1" and "release 0.2.0", then the only hits are marked history.
- `check_j4_covers_decisions`: J4 names each of decision 6's classes, the relay, decision 3's periods, decision 4's frost, decision 7's alarms, decisions 1 and 11's refusals, and the scenarios of answers D, F, G, H, I, K, L, M, N and O.
- `check_j4_simulator_only`: J4 names no test on the user's own relay or boiler; the Shelly check is under K6.
- `check_placeholders_only`: `devenv/README.md` has no address, only `<…>` placeholders.
- `check_relay_not_later`: `PLAN.md`'s "Later" has no "relay (on/off-only)".

Then:
1. Mark L4 ✅ first, while `docs/plan-0.2.1.md` holds no pending change. Its reason: "Decided 2026-09-27 (`docs/plan-0.2.2.md` decision 11): control without a heating switch stays blocked, and such installations get the monitor. Research looks at whether a low setpoint stops both the boiler and its pump; only the user lifts the block, at K4, even if that research is favourable (answer K of 2026-09-27)." Commit it at once by path, with the diff in the report (answer B).
2. Draft the `docs/plan-0.2.1.md` edits.
3. Draft `docs/plan-0.2.md`.
4. Draft `docs/plan-0.1.md`.
5. Draft `PLAN.md` [Q2].
6. Draft `devenv/README.md`.
7. Run the checks.
8. Show the diffs.
9. Commit each file after consent.
10. Mark Q2 ✅.

**Rules and values.**
- **`docs/plan-0.1.md`** (S-46): annotate
  - B4: "0.2.1: inference from a shared return removed (W2)";
  - B7: "0.2.1: unknown, not 'no', while the flow is unknown or stale (W5)";
  - D5: "0.2: the store also keeps the control state; 0.2.2 V1: in its own store, written at once".
- **`docs/plan-0.2.md`:**
  - l.6-7: "(0.2.2: on/off boilers through a relay, `docs/plan-0.2.2.md` X8)".
  - The status line becomes "Status on 2026-09-27: built through 0.2.1 and its review (`docs/review-2026-09-26.md`); the corrections of `docs/plan-0.2.2.md` come next; then J2, J4 and phase K publish 0.2.2 (provisional, decision 16). S3 stays optional." The words "K2 done" go, as K2's ✅ is withdrawn.
  - Annotations:
    - G0: "0.2.1: no summer state; summer and winter come from VT";
    - G7: rewritten so the interval is an option (default 5 min) and the keep-alive is 30 s;
    - G10 and J4: S-15 / T-24 as below;
    - H0: a writer lives through hand-backs inside a session; a hand-back-only unit may exist (M4);
    - H2: monitor mode is not offered; 0.2.2's safe hand-back;
    - H3: a blocker, cleared only after the restart VT needs (X7);
    - I3: no anti-cycling state in 0.2;
    - J1: "0.2.1 R4: one tar stream over SSH, no rsync; the simulator component instead of helpers".
- **J2** (S-19):
  - `devenv/README.md` keeps the LXC's own output rule, adds `ip6 daddr { <…> } drop`, and adds a rule on the forwarding path for the container: the `DOCKER-USER` chain, for IPv4 and IPv6. The exact syntax is checked against Docker's packet-filtering documentation, read as a page over the network.
  - T-25: `docker exec ha-test` tries TCP to the production Home Assistant, its broker and the gateway, over IPv4 and IPv6. Every attempt must time out or be refused.
  - The user runs T-25 at J2. Claude repeats it over SSH only after the user has said to start J4.
- **J4** (the simulator only; nothing reaches a real boiler before K4): the existing scenarios are revised to the decisions and answers, and new ones are added:
  - one scenario per class of decision 6:
    - a lost command with a trace;
    - a single untraced fall-back;
    - a second one within an hour, and one that a send explains (answer E);
    - ignored from the start;
    - clipped;
    - another controller, with the full safe hand-back (answer H), the latch and the return by itself;
  - a held device that restarts (S-13, T-47);
  - the lost link, and for a relay: an alarm, the command again on its return, no hand-back;
  - the recognition period, the grace period and "every zone unknown", with and without the "own room controller" tick (answer F), and on the relay path with the tick and each rest state (answer M);
  - frost heating only for zones that can take heat, and a repair issue for a closed one;
  - only decision 7's alarms hand back. This includes the plugin's own monitor failing for 5 min: a hand-back, then control resumes by itself (answer I). The boiler's own fault gives the usual "off" after 5 min;
  - the safe hand-back: its parts at once, one after the other; at a step aside, written once even over the other controller's value, with a target the other controller then takes counting as done (answer H, M12);
  - control refused:
    - for an on/off contact or "I don't know";
    - without a heating switch;
    - for a boiler that ignores "heating off" from the start of the session: blocked and handed back, until control is switched off and on (answer O);
    - for a gateway entry with no answer on its thermostat terminals (answer K);
    - for a relay without the "separate contact" tick (answer G).
    The simulator's PIC `CH=0` flag with an on/off thermostat shows why (T-07, Z3);
  - a lost or damaged store: a hand-back first (answer K);
  - the activation delay, on the relay path too;
  - a relay that restarts (seen unavailable, or found in its declared power-cut state without that, answer D; the fourth such restart within 24 h, and a relay declared "last" or "I don't know" changing while available, stepping aside, answer N), loses Wi-Fi, is switched by an automation or its own button (the step aside setting the rest state once, then leaving the relay alone, answer L), has a switch-off timer, or goes through a planned restart;
  - the wall thermostat after a hand-back;
  - an unclean restart with `docker kill ha-test` over SSH, and a lost link provoked by a means Z3 prepares. Both run in the test container only, after the user says to start (decision 15);
  - starts under control: at most the boiler's own regulation's starts per hour × 1.10 (provisional, K4), over 24 h at +8 °C and at −5 °C in the same simulated house (T-24, S-15). The ratio is reported for K4.
- **K1:** the README also covers:
  - removal;
  - how often data updates (the 30 s tick, the 10 s control step, the 5-min analysis, forecasts every 30 min: `const.py:41-46`);
  - troubleshooting;
  - known limitations: among them M18's invisible changes, and a clip of a flat setpoint judged as another controller;
  - supported devices (S-52);
  - the relay setup recommendations, with the Shelly timer "not documented" until K6;
  - the wall-thermostat texts.
- **K4:** the agenda adds Q4's list (below), and "the 0.2.1 change log read with `docs/review-2026-09-26-vs-0.2.md`".
- **K5 and K7** (S-53):
  - Z2 sets the manifest (`manifest.json:20`) and `tests/test_release.py:27` to 0.2.2b1 (decision 16's provisional first version);
  - K5 publishes it, or sets both to the version decision 16 picks at K4, and K5 decides the repository's content;
  - K7 sets both to the release version (provisional 0.2.2).
- **K6:** where the user has a Shelly relay of their own, they check whether its switch-off timer restarts on a repeated "on" (Q3.10); the result is kept in `research/`. It is never done at J4, which uses the simulator only.
- **"Done for 0.2":** "published as 0.2.2 (provisional)".
- **"Open for 0.2" K4 list:**
  - "two gateway disturbances latch" → "0.2.2: moot, decision 6";
  - the daily cap → "removed, 0.2.1 M0";
  - "up to 10 K" → "+3 K, 0.2.1 N5";
  - the stand-alone item → decision 7 narrows the alarm hand-backs, and a relay out of reach gets an alarm and no hand-back.
- **`docs/plan-0.2.1.md`:**
  - l.7-9: "(0.2.2: the first published version is 0.2.2, provisional)";
  - l.12-13 and "Provisional decision": both decided on 2026-09-27 (decisions 11 and 12); lifting decision 11's block waits for the user at K4 (answer K);
  - M4: "0.2.2: removal cannot be refused, as Home Assistant offers no veto: a last attempt and a persistent issue" (S-54);
  - N5 keeps its ✅, and adds "its documentation part — SmartPI learns its own outdoor term — is written by plan 0.2.2 Q1 (S-50)";
  - "Open after R6": "Taken over by `docs/plan-0.2.2.md` (index)";
  - "After 0.2.1": "The corrections of `docs/plan-0.2.2.md` follow, then J2, J4, K1, K2 (its ✅ withdrawn until its validation runs, which needs K5's repository) and K4–K7 of `docs/plan-0.2.md` (pre-release and release 0.2.2, provisional)";
  - "Done": "After the fixes, an independent check finds no critical or high problem" (S-55).
- **`PLAN.md`:** the [Q2] items in Q1's list.

**Code to change.** None. The manifest and `tests/test_release.py` change at Z2, K5 and K7, not here.

**Texts.** None.

**Missing data.**
- The production addresses are not known and are never written: placeholders only.
- If J2 has not happened, T-25 waits for it.
- If Docker's documentation cannot be read, the forward-path rule is written as the `DOCKER-USER` example, marked "to check at J2".

**Do not.**
- Write real addresses.
- Run T-25 or connect to the LXC.
- Remove N5's ✅.
- Decide J4's lost-link mechanism (Z3 does).
- Put a test on the user's own relay or boiler into J4 (the Shelly check is K6's).
- Change code.

**Open for the user.** None.

---

### Q3 — Research over the network, kept in `research/`

**Goal and done-when.** Each question gets a note, `research/2026-09-2x-<topic>.md`:
- sources with their URL and the date read;
- facts marked verified or assumed;
- "what this changes", pointing at the step and the code that use it.

Research decides nothing. A finding that could lift a block (decision 11, decision 1's alternative) goes to the user at K4, and only the user lifts it (answer K). Done when:
- every item Q3.1–Q3.9 has its note, or "not found" with its cautious consequence;
- Q3.10 is moved to K6 and named in "Open after 0.2.2", and Q3 is ✅ without it;
- the diff of `research/diy/INDEX.md` has been shown.

**Read first.**
- Plan: the Q3 row (l.385); decisions 1, 2, 6, 11; "Boiler protection"; answer K of 2026-09-27.
- Review: questions 13, 17, 18 (l.1482-1488); P-50, P-60 (l.177, 187); S-51.
- `research/2026-09-27-fresh-session-test.md` "Q3" (l.299-329), and Q1 (c) on the trace (l.182-185).
- `research/2026-09-25-l3-device-facts.md`.
- `research/2026-09-26-boiler-protection-alarms.md` "Missing" (l.147-156).
- `research/2026-09-26-q4-decision-6-outside-change-matrix.md` "Open questions" (l.598-612).
- `research/diy/INDEX.md` l.14.

**Order of work.** Research has no tests. For each item: write the question, read local sources first (`.venv/` Home Assistant sources, `research/diy/`, `vendor/`, for interface facts only), then network pages, then write the note. Order: Q3.1, Q3.2, Q3.4, Q3.7, Q3.9 (Q1 needs them), then Q3.3, Q3.5, Q3.6, Q3.8.

- **Q3.1 — the lowest VT version that loads external feature managers** (question 13, P-60).
  - Where to look: VT's GitHub release pages and changelog, and `vtherm_api`'s release history on PyPI (pages). Locally: VT 10.4.0 loads them (`vendor/`), and `get_feature_manager(name)` exists only from 10.5.0.beta1 (`CLAUDE.md`).
  - Who uses the answer: X7 (`feature_manager.py:188-208`), and K1's minimum VT version.
  - Until it is answered: the issue text names no version.
- **Q3.2 — a low `CS`** (question 17, decision 11):
  - (a) Do OpenTherm boilers raise a `CS` below their lowest CH setpoint (ID 49's lower bound) to that bound, and fire?
  - (b) Is `CS` = 10 °C "no demand" for them?
  - (c) With CH enabled and a low `CS`, does the CH pump run, on typical boilers and on ESPHome, DIYLess and EMS-ESP masters? This builds on L3: ESPHome leaves CH enabled with a low setpoint, and on DIYLess users report the pump running.
  - Where to look: the OTGW documentation pages, forum threads and issue pages; manufacturers' HTML pages. Not PDFs.
  - Who uses the answer: decision 11's block (X5), decision 1's alternative, K4.
  - Until it is answered: both stay blocked. A favourable answer does not lift them by itself; the user decides at K4 (answer K).
- **Q3.3 — the slowest hand-back against Home Assistant's stop** (question 18).
  - Locally: `.venv/lib/python3.14/site-packages/homeassistant/core.py:111-114` (stages of 20, 100, 60 and 30 s) and where the shutdown jobs run (around l.1140-1190); `CLAUDE.md` says shutdown jobs run before `EVENT_HOMEASSISTANT_STOP`, on which MQTT disconnects.
  - The slowest hand-back is the safe hand-back over the firmware's MQTT: `CS`=lowest, `CH=1`, `CS=0`, three publishes, which the firmware resends after 5 s up to 5 times. Add V4's wait for a late report. Over `opentherm_gw` it is three service calls, each waiting for pyotgw's reply.
  - Who uses the answer: V4, V5.
  - Until it is answered: the hand-back at the stop is tried, and stays owed if it is not confirmed (as today).
- **Q3.4 — a generic rule tying the lowest water temperature to the boiler's minimum power** (decision 2, S-02).
  - The candidate to check, not decided: below the flow temperature at which the emitters give off the boiler's minimum power at the current room temperature (EN 442: output scales with ΔT^n, `core/emitters.py`), the boiler short-cycles.
  - What it needs: the minimum power, the design load at the design flow, and the emitter exponent.
  - Who uses the answer: X6, which shows the rule's estimate beside its suggestion (the reference + 2 K), never applied.
  - Until it is answered: X6's reference + 2 K only, with no estimate from the boiler's power.
- **Q3.5 — how soon an ESPHome device reports its value after a start** (P-50).
  - Where to look: `research/diy/esphome-opentherm/docs/` (`components_api.mdx`) and the ESPHome API pages.
  - Who uses the answer: V4's late-report wait.
  - Until it is answered: 60 s at the start.
- **Q3.6 — how the OTGW firmware over MQTT shows a gateway that drops, and a broken link between the ESP and the PIC** (Open after R6 #8).
  - Locally: `research/diy/otgw-firmware/v1.7.5/MQTTstuff.ino`, `OTGW-Core.ino`, `OTGW-firmware.ino` (the LWT and availability topic, a PIC watchdog or "no PIC" state, uptime); then the firmware's wiki pages.
  - Who uses the answer: X2.
  - Until it is answered: availability only, and the option's text says that a broken ESP–PIC link may not be seen.
- **Q3.7 — a trace of an outage on each gateway path** (decision 6): how a PIC reset, an ESP restart and a Data-Invalid reply to ID 1 show through `opentherm_gw` and through the firmware's MQTT — entity availability, a reset counter or boot message, or nothing.
  - Locally: `research/diy/pyotgw/2.2.3/` (reset handling, `PS=1` after a reset), `research/diy/otgw-pic/gateway-6.6.asm` (a start-up banner?), the firmware's boot publishes, and `.venv/.../opentherm_gw/`.
  - Who uses the answer: X1's trace and the matrix.
  - Until it is answered: only an entity that is unavailable, unknown or missing counts, and answer E keeps a single untraced fall-back harmless.
- **Q3.8 — `research/diy/INDEX.md`, `gateway-6.6.asm`** (S-51): find the file's origin (URL) and the name of its license, reading pages over the network. The INDEX diff waits for consent. The file is removed only with the user's confirmation, and `CLAUDE.md` then notes that the PIC 6.6 facts were read from a copy no longer kept.
- **Q3.9 — the boiler's own fault on each path**:
  - Which boilers report the low-water-pressure flag over OpenTherm (ID 5), and which faults mean the boiler has stopped.
  - Whether the gateway reads ID 5 with and without a thermostat (stand-alone, the PIC polls some IDs itself: `gateway-6.6.asm`).
  - Which entity carries each fault:
    - `opentherm_gw`: `binary_sensor.py:122-145`, verified ("Low water pressure", "Gas fault", "Air pressure fault", "Water overtemperature");
    - the firmware's MQTT topics (`OTGW-Core.ino`);
    - ESPHome (`research/diy/esphome-opentherm/binary_sensor/__init__.py`);
    - EMS-ESP (`research/diy/ems-esp/src/boiler.cpp`).
  - Who uses the answer: Y1's two optional signals and Q1's text.
  - Until it is answered: both signals accept any binary sensor the user maps, and none by default.
- **Q3.10 — whether a Shelly's switch-off timer restarts on a repeated "on"**: moved to K6, where the user checks it on their own relay if they have one; the result is kept in `research/`. Until then the relay texts say it is not documented. It is named in "Open after 0.2.2". Tasmota is already verified (`research/2026-09-26-on-off-relays.md`).

**Rules and values.** The answers are facts, not decisions. Every value a note proposes goes to K4 as provisional. The "(to be settled by Q3)" sentences of Q1 are completed with a new diff.

**Code to change.** None. The consumers are named for each item.

**Texts.** None.

**Missing data.** If a source is unreachable, PDF-only or silent: the note says "not found" or "not read (PDF)", the cautious default above stays, and the question goes onto the K4 list.

**Do not.**
- Clone, download or install anything. The only downloads allowed are DIY interface sources into `research/diy/<solution>/`, each listed in `INDEX.md` (that diff waits for consent).
- Fetch PDFs through the web tool, which saves them outside the project.
- Connect to any Home Assistant instance or device.
- Read SAT's code.
- Treat a finding as lifting a block.

**Open for the user.** Only Q3.8's removal, if the source of `gateway-6.6.asm` cannot be found.

---

### Q4 — Decision 16: the first published version and the repository's content (🔒)

**Goal and done-when.** Nothing is built. The provisional option (pre-release 0.2.2b1, then 0.2.2) stands until the user decides:
- the version after Z4, at K4;
- whether the public repository carries `CLAUDE.md`, the plans and the reviews, and whether it starts from a clean history, at K5.

Done when both answers are recorded in the plan (decision 16), `SCOPE.md` §11/§12, `PLAN.md` and `docs/plan-0.2.md` K5/K7, and at K5/K7 also in `manifest.json:20` and `tests/test_release.py:27` (Z2 sets both to 0.2.2b1 first). Q4 holds nothing up, and stays without ✅ until K5.

**Read first.** Plan: decision 16 and the Q4 row. Review: S-53 and question 16. `research/2026-09-27-fresh-session-test.md` "Q4" (l.331-341).

**Order of work.**
1. Q1 writes the provisional option into `SCOPE.md` §11/§12. Q2 puts decision 16 and the K4 agenda into `docs/plan-0.2.md`.
2. When Z4 ends, summarise its remaining problems for the user in plain Polish, with the choice of first version.
3. At K4, record the version.
4. At K5, record the repository's content.
5. Mark Q4 ✅.

**Rules and values.** The K4 agenda (to be added to `docs/plan-0.2.md` K4):
- the version, the default of 20 °C, and every "(provisional, K4)" value of Q1's fixed-values table, V–Z's included;
- the plan's answers to review questions 3, 5, 6, 8–12, 19 and 20;
- every "Open for the user" question of V1, V3, V6, V7, X1, X3, X4, X6, X8 and Y3 still open after the answers of 2026-09-27;
- Q1's two former open questions are answered (the user, 2026-09-27, M and N) and are no longer on the agenda, nor is a heating switch whose "off" is ignored from the start (O); what stays are two readings of these answers: that only relay restarts without a trace count toward answer N's fourth (Q1 R2a, X8 R7), and that answer M's "on a gateway" means every gateway topology, the entity path with a gateway topology included (X3);
- frost protection during the recognition period;
- control resuming after an every-zone-unknown hand-back;
- the known limit that a clip of a flat setpoint is judged as another controller, and that a bus controller holding a steady lower value looks like a clip;
- the external-control switch's detection;
- the relay's "I don't know" answers and its repeat interval;
- the two boiler-fault signals, with frost heating stopping during a fault (after 5 min);
- lifting the block on "off" as a low setpoint and on decision 1's low `CS`, which only the user does, even after a favourable Q3 answer (answer K);
- the migration's device-count pre-fill;
- the wall-thermostat warning below 15 °C;
- the J4 margin of 1.10 over the boiler's own regulation;
- S-58's fixed rule values.

**Code to change.** None now. At K5/K7: `custom_components/vtherm_smart_boiler/manifest.json:20` and `tests/test_release.py:27` (Z2 sets both to 0.2.2b1 before that).

**Texts.** None.

**Missing data.** Without an answer the provisional option stays. K5 cannot start without the answer on content (it is 🔒 anyway).

**Do not.** Create a repository, add a remote, push or publish, or decide for the user.

**Open for the user.** Decision 16 itself, at K4 and K5.

## Phase V — details of V1–V7

Conventions for this part. Paths without a directory are in `custom_components/vtherm_smart_boiler/`. Line numbers refer to commit d545869; once code moves, use `git show d545869:<path>`. "HA" means Home Assistant 2026.9.3 as installed in `.venv/` (read only for interface facts). "(provisional, K4)" marks a value or rule that the plan and the decisions leave open. Each one is the most cautious option found, and each is listed in the table "Fixed values of phase V" at the end, for S-37's list. Where a decision of `docs/plan-0.2.2.md` changes what the review expected, the decision wins and the test's Then is adjusted as stated. "The user's answer <letter> of 2026-09-27" cites the user's answers A–O of that date; each citation also says what the answer decided. A step is ✅ only when every scenario of each of its problems is covered (the review's row, its §6 test, section 4's proposal) and every new mechanism has a negative test with a missing, unknown or `None` input. `python -m pytest -q` and `ruff check .` must pass through `scripts/env.sh` before each commit. Marking a finished step ✅, and adding a remainder to "Open after 0.2.2", is committed without waiting for consent, with the diff shown in the step's report; every other `*.md` change waits for consent (the user's answer B of 2026-09-27).

---

### V1 — the control store (P-01, P-04, P-58; T-08, T-10, T-35; review question 5)

**Goal and done-when.** Goal: a missing, corrupt or half-written file must never make the plugin forget that it holds the boiler or owes a hand-back, and a lost file must not restart the monitoring period. Done when:
- T-08, T-10 and T-35 pass as written below;
- every reading case in rule R4 has its own test: corrupt file, missing file of an entry that ran, new entry, 0.2.1 layout, both stores lost, broken fields;
- setup, the options flow, removal, the repair release and the unreadable-options path all give the same answer (P-58).

**Read first.**
- Plan: Terms "Control state"; the V1 row; review question 5, whose answer below the user confirmed on 2026-09-27 (answer K).
- Review: P-01 (§3.1), P-04 (§3.2), P-58 (§3.3); §6 T-08, T-10, T-35.
- `research/2026-09-27-fresh-session-test.md`, "## Part: V-and-X1-X4", "### V1".
- Code:
  - `coordinator.py:158, 163-165, 191-195, 237-266, 304-338, 360-371, 828-833`
  - `const.py:51-56`
  - `__init__.py:131-164, 190-245`
  - `config_flow.py:1188-1215`
  - `repairs.py:37-72`
  - `control.py:104-106, 312-373`
- HA facts:
  - `helpers/storage.py:360-421`: a corrupt JSON file is renamed `*.corrupt.<time>`, a CRITICAL persistent `storage_corruption` issue is raised and `None` is returned; a file holding `{}` also returns `None`.
  - `Store(..., atomic_writes=True)`: `helpers/storage.py:228-240`.
  - `ConfigEntry.created_at`: `config_entries.py:429, 561`. Entries migrated from HA storage 1.2 get `created_at` = epoch 0 (`config_entries.py:2116-2119`).
  - `created_at` is not a frozen attribute, so a test may set it (`config_entries.py:282-291, 578-587`).
  - The test storage mock reads no file (`pytest_homeassistant_custom_component/common.py:1517-1551`).

**Order of work.**
1. Tests first:
   - Cases that need the fake gateway go in `tests/integration/test_control.py`: T-08 and tests 2, 4, 5 and 8–11 below.
   - The monitor-only cases go in `tests/integration/test_setup.py`.
2. List of tests:
   1. T-08 `test_a_corrupt_store_file_hands_back_first`.
      - Given: a real truncated file `.storage/vtherm_smart_boiler.<id>.control`; a main store with the marker `control_store: 1`; OTGW control configured; the switch restored on.
      - When: the entry is set up and 30 s of steps run.
      - Then:
        - the file was renamed `*.corrupt.*` and HA's `storage_corruption` issue exists;
        - the first step sends a full hand-back (today `CH=1`, then `CS=0`; the order changes in V5);
        - the `control_state_unreadable` issue exists;
        - the monitoring start equals `entry.created_at`.
      - How to use a real file: point `hass.config.config_dir` at `tmp_path`, so the file lives under `.tmp/` and never in the default test directory inside `.venv/`. Capture `Store._async_load` at module import, before the mock patches it, and restore it with `monkeypatch` for this test. This recipe is assumed to work; verify it when writing the test.
   2. `test_a_missing_control_store_of_an_entry_that_ran_hands_back_first`.
      - Given: a main store with the marker and no control store; control configured.
      - When: setup.
      - Then: a full hand-back first.
   3. `test_a_new_entry_without_control_owes_nothing` (negative).
      - Given: no stores; options without a control section.
      - When: setup.
      - Then: no hand-back and no issue; both stores are written only after the read.
   4. `test_a_0_2_1_store_moves_to_the_control_store`.
      - Given: only a main store in 0.2.1 layout (`control` without the marker), `controlling: false`.
      - When: setup.
      - Then: no hand-back; the control store holds the same fields; the main store has the marker.
   5. `test_a_0_2_1_store_that_held_the_boiler_still_hands_back`.
      - Given: as 4, but `controlling: true`.
      - Then: a full hand-back first.
   6. T-10 `test_setup_failing_before_the_store_is_read_leaves_it_intact`.
      - Given: a store with `controlling: true`, a monitoring start a week ago and day summaries; `VThermLink.async_detect` raises.
      - When: setup.
      - Then: setup fails and both stores are unchanged; the next good setup hands back. V2 changes this Then (see V2).
   7. T-35 `test_a_lost_monitoring_start_falls_back_to_the_entry_creation`.
      - Given: `entry.created_at` 10 days ago, `monitoring_days` 7, a store without `monitoring_since`.
      - When: setup.
      - Then: no `monitoring_period` blocker; the verdict attribute `monitoring_since` equals `created_at`.
   8. `test_monitoring_counts_from_the_entry_creation_even_after_a_restarted_start`.
      - Given: `created_at` 10 days ago; a stored `monitoring_since` of yesterday (a 0.2.1 store loss).
      - Then: no `monitoring_period` blocker.
   9. `test_an_entry_without_a_creation_time_uses_the_stored_start` (negative).
      - Given: `created_at` = epoch 0.
      - Then: the stored start is used; without one, now.
   10. `test_an_unreadable_store_guards_the_options_flow`.
       - Given: the entry not loaded; the control store unreadable while the marker is present; a control section.
       - When: the options change the write path.
       - Then: error `hand_back_pending`.
   11. `test_removing_an_entry_with_an_unreadable_store_raises_the_issue`.
       - Then: the persistent `hand_back_owed_after_removal` issue exists, and the control store file is gone.
   12. `test_unreadable_options_and_an_unreadable_store_still_report_a_held_boiler`.
       - Given: raw options whose `control` mapping has a `write_path` but fails parsing; the store unreadable.
       - Then: the persistent `hand_back_owed` issue.
   13. `test_a_release_by_hand_writes_the_control_store`.
       - Given: the entry not loaded; the release is confirmed in the repair flow.
       - Then: the control store has `controlling` and `hand_back_pending` false (a fresh store if the old one was unreadable).
   14. `test_both_stores_are_written_atomically`.
       - Then: both `Store` objects were created with `atomic_writes=True`.
3. Implement R1–R8. Then adjust the existing tests:
   - `tests/integration/test_setup.py:422` and `:448`: the docstrings change (a broken or lost start no longer restarts monitoring); the asserted value stays about now, because a `MockConfigEntry` is created now.
   - `test_setup.py:897`: set `entry.created_at` to the stored start, or assert `created_at`.
   - `test_control.py:1030-1033` (`stored_control`): read the control store key.
   - `start_with_stored` (`test_control.py:1762-1778`) seeds the 0.2.1 layout and so exercises the migration. Keep it, and add a variant that seeds the control store.

**Rules and values.**
- R1 — two stores.
  - The control store has the key `vtherm_smart_boiler.<entry_id>.control`, version 1, `atomic_writes=True`. It holds exactly the control state: the fields of `control.py:312-330`, plus V3's `enabled` and `last_command`.
  - The main store `vtherm_smart_boiler.<entry_id>` also gets `atomic_writes=True`. It keeps a copy of the control state under `"control"`, as in 0.2.1 (this keeps a downgrade working and serves as the fallback), and the marker `"control_store": 1`.
- R2 — writing.
  - The control store is written at once on every change of the control state: `await async_save(...)` in async code, `async_delay_save(..., 0)` in synchronous code.
  - The main store's copy is written at once when `controlling` or `hand_back_pending` changes, otherwise with the delayed save (120 s, `coordinator.py:97`).
- R3 — nothing is saved before both stores were read. A `_loaded` flag gates `schedule_save` (`coordinator.py:360-371`), `async_save_now` (336-338), every control-store save and the save in `async_stop` (245).
- R4 — reading. One function (`async_read_control_state` in `coordinator.py`) is used by setup, the options flow, removal, the repair release and the unreadable-options report:
  - (a) The control store is a mapping: it is the control state.
  - (b) Otherwise, if the main store is a mapping without the marker, the entry comes from 0.2.1 (or 0.2.2 never saved it). Its `"control"` mapping is the state, or `{}` if there is none; 0.2.1 saved it at once (`control.py:821-825`). The control store and the marker are then written at once.
  - (c) Otherwise the state is **unreadable**.
    - It is owed when the options hold a control section (a `"control"` mapping with a `write_path`; control can only be configured in the options flow of an entry that has run, `config_flow.py:1283` onwards) or when the main copy owes a hand-back. The state is then the main copy (if it is a mapping) with `controlling` and `hand_back_pending` forced true, else `{"controlling": true, "hand_back_pending": true}`. An ERROR is logged once and the issue `control_state_unreadable` is raised.
    - Otherwise nothing is owed: `{}` and a WARNING (a monitor-only entry).
- R5 — the cautious answer, the same everywhere (P-58). The pure part goes next to `owes_hand_back` (`const.py:51-56`).
  - Setup: a full hand-back first (the path of `control.py:370-373`, `full=True`).
  - Options flow with the entry not running: the `hand_back_pending` blocker.
  - Removal: the persistent `hand_back_owed_after_removal` issue.
  - Unreadable options (`__init__.py:190-204`): the persistent `hand_back_owed` issue.
  - Repair release (`repairs.py:60-72`): the control store and the main copy get `controlling` and `hand_back_pending` false; an unreadable control store is replaced by a fresh one, because the user stated that the boiler was returned.
- R6 — monitoring start.
  - It is `entry.created_at` (as a timestamp) when that is above 0.
  - Otherwise the stored `monitoring_since` if it can be read, else now.
  - `monitoring_since` is still written, for diagnostics and a downgrade, but a lost store never restarts it.
- R7 — stored fields are still read field by field (`control.py:337-369`), and an unreadable owed flag counts as set (`control.py:104-106`).
- R8 — removal deletes the control store together with the main store (`__init__.py:161`).

**Code to change.**
- `coordinator.py:158`: the monitoring start from `created_at` (R6).
- `coordinator.py:163-165`: the main `Store` gets `atomic_writes=True`, and a second `Store` is added for the control store.
- `coordinator.py:251-266`: reading as in R4 and R6.
- `coordinator.py:304-325`: the main store gets the marker and keeps the copy.
- `coordinator.py:327-338`: `provide_stored_control` stays; `async_save_now` is split into `async_save_control_now` (control store, plus the main copy when the owed flags changed) and the main save.
- `coordinator.py:360-371`: `schedule_save` is gated by `_loaded`, as is the save at 245.
- `coordinator.py:828-833`: `_mapping` stays for the main store's fields.
- `const.py:51-56`: the pure helper `control_state_owed(state, *, readable, has_control_section)`.
- `__init__.py:131-164`: removal reads through R4 and removes the control store; `control_state_unreadable` joins the issue keys deleted at removal (`__init__.py:141-147`).
- `__init__.py:190-204`: R5.
- `__init__.py:219`: `_hand_back_unit` reads the state loaded through R4.
- `config_flow.py:1206-1215`: `_async_owed_in_store` goes through R4.
- `repairs.py:37-72`: the in-memory release (`async_release`, lines 50-57) writes the control store; the stored release (`_async_release_stored`) as R5.
- `control.py`: every `self._coordinator.async_save_now()` and control-state `schedule_save()` becomes the control save. The calls are at lines 427, 448, 561, 578, 630, 825, 863, 886, 893, 943, 972, 1035, 1045 and 1052.

**Texts.**
- `issues.control_state_unreadable`:
  - en title: "The plugin's memory of the boiler could not be read".
  - en description: "The file in which the plugin remembers whether it holds the boiler could not be read: it is missing or damaged (Home Assistant may show its own notice about a damaged file). To be safe, the plugin assumed it held the boiler and handed it back first. Control then works as usual; check that the boiler and the control switch are as you expect."
  - pl title: "Nie udało się odczytać pamięci wtyczki o kotle".
  - pl description: "Plik, w którym wtyczka pamięta, czy steruje kotłem, nie dał się odczytać: brakuje go albo jest uszkodzony (Home Assistant może osobno zgłosić uszkodzony plik). Dla bezpieczeństwa wtyczka przyjęła, że sterowała kotłem, i najpierw go oddała. Potem sterowanie działa normalnie; sprawdź, czy kocioł i przełącznik sterowania są w stanie, jakiego oczekujesz."
- The issue is not fixable and not persistent. It is deleted when the hand-back it caused is confirmed or settled by hand.

**Missing data.**
- Control store missing or unreadable: R4 (b) or (c).
- Main store missing or unreadable: the monitor starts empty (days, factors and measured values are lost); the monitoring start comes from `created_at`; the control state comes from the control store.
- Both lost: R4 (c).
- `created_at` 0 or missing: R6.
- Options without a control section and nothing owed in the copy: nothing is owed and no issue is raised.
- A broken field: skipped and logged (R7).
- Missing data never switches heating on or off here. It only makes the hand-back owed.

**Do not.**
- Do not treat `None` as "new" while the options hold a control section.
- Do not restart the monitoring period after a lost store.
- Do not write either store before both were read.
- Do not drop the main store's copy of the control state.
- Do not delete or rename the `*.corrupt.*` file (HA keeps it for the user).
- Do not write test files into `.venv/`.

**Open for the user.** None. Review question 5 is answered here, and the user confirmed the answer on 2026-09-27 (answer K): a lost or corrupt memory counts as "the plugin held the boiler", so the boiler is handed back first, and the monitoring period always counts from the moment the integration was added (the entry's creation).

---

### V2 — a setup that fails (P-05, P-33, P-57; Open after R6 #6: C14, H9; T-09, T-11)

**Goal and done-when.** Goal: whatever fails during setup, a hand-back owed from an earlier run is sent first, and if it is still owed when setup gives up, it is reported by a persistent issue. Nothing keeps running after a failed setup, the forecasts never fail setup, and options saved while the entry is in setup error reload it. Done when:
- T-09 and T-11 (with its forecast variant) pass;
- the tests for H9, C14 and P-57 below pass;
- T-10 is updated to the new order.

**Read first.**
- Plan: the V2 row.
- Review: P-05 (§3.2), P-33 (§3.2), P-57 (§3.3); §6 T-09, T-11.
- `docs/plan-0.2.1.md`, "Open after R6" #6 (H9, C14).
- `research/2026-09-27-fresh-session-test.md`, "### V2".
- Code: `__init__.py:30-87, 207-258`; `coordinator.py:191-235`; `forecasts.py:99-112`; `config_flow.py:1274-1278`; `control.py:377-399, 415-448, 946-957`.
- HA facts:
  - A failed setup runs the entry's on-unload callbacks, which removes an update listener added before the failure (`config_entries.py:911-914`).
  - `ConfigEntryNotReady` is retried, with backoff up to 10 min (`config_entries.py:838-878`).
  - An options flow only calls update listeners (`config_entries.py:3935-3972, 2672-2683`).
  - `async_schedule_reload` starts a task eagerly (`config_entries.py:2464-2471`).

**Order of work.**
1. Tests, in `tests/integration/test_control.py`:
   1. T-11 `test_an_owed_hand_back_is_made_before_the_first_refresh_fails`.
      - Given: a stored `hand_back_pending: true` (OTGW); `_compute` raises on every refresh.
      - When: setup (SETUP_RETRY) and one retry.
      - Then:
        - the gateway got the hand-back writes before the failure, at each attempt;
        - if the hand-back is not confirmed, the persistent `hand_back_owed_<id>` issue exists;
        - no control clock runs after the failure.
   2. T-11 variant `test_an_unreadable_forecast_partition_does_not_fail_setup`.
      - Given: one forecast partition whose `Store.async_load` raises.
      - Then: the entry is LOADED; one WARNING; the other partitions are loaded.
   3. T-09 `test_an_owed_hand_back_without_its_options_raises_a_fixable_issue`.
      - Given: a control state `{"controlling": true}` without `taken_with` (variant: an unparsable `taken_with`); options without control.
      - When: setup, then the repair flow "returned by hand".
      - Then:
        - the entry is LOADED and the monitor runs;
        - the fixable `hand_back_owed_<id>` issue exists, with one ERROR log;
        - after confirming, the control store has `controlling` and `hand_back_pending` false;
        - no issue after a restart.
   4. H9 `test_options_saved_in_setup_error_reload_the_entry`.
      - Given: an entry in SETUP_ERROR (`async_forward_entry_setups` fails once).
      - When: the options flow saves a change.
      - Then: the entry is set up again with the new options (LOADED once the cause is gone).
   5. P-57 `test_a_failure_after_the_platforms_still_stops_everything`.
      - Given: `coordinator.async_start_background` raises.
      - Then: setup fails; the control clock is stopped; the feature manager is detached; no update listener is left.
   6. C14 `test_an_owed_hand_back_does_not_wait_for_the_first_refresh`.
      - Given: an owed hand-back; `_compute` spied.
      - Then: the first hand-back write comes before the first `_compute` call.
2. Update T-10 (V1): with the new order, the hand-back is attempted in the failing setup itself. The Then becomes: "the owed hand-back was sent before the failure; the day summaries and the monitoring start are unchanged; if still owed, the persistent issue exists".
3. Implement the setup order, the failure path, the best-effort forecasts and H9. `test_control.py:237` (`test_a_setup_that_fails_late_leaves_nothing_running`) must still pass.

**Rules and values.**
- Setup order (`__init__.py:62-87`):
  1. parse the options (unchanged);
  2. build the coordinator;
  3. read both stores (V1, R4), before `link.async_detect()` (`coordinator.py:194`);
  4. build the unit from the state read (the control unit when control is configured, else the hand-back-only unit of `__init__.py:207-245`) and set it on the coordinator. `provide_stored_control` is registered when the unit is built, not in `async_start` (`control.py:379`); otherwise a save made before the start would write the stale loaded state;
  5. if a hand-back is owed, make one attempt at once (`full=True`) under the unit's lock (new `ControlUnit.async_hand_back_owed(now)`), before anything else can fail;
  6. then `link.async_detect()`, the history seed and listeners, the forecasts (best effort), the first refresh, the unit's start (clock and shutdown job), the platforms, the feature manager, the update listener and `async_start_background`. All of step 6 sits inside the `try` (P-57).
- Failure path: stop every unit. `async_stop` hands back again if still owed and raises the persistent issue (`control.py:442-446`). Then `coordinator.async_stop`, which saves only if the stores were read. Nothing keeps running.
  - In SETUP_RETRY, HA retries setup, which repeats step 5.
  - In SETUP_ERROR, the persistent issue stays, and nothing retries until a reload or an options change.
- Forecasts (`forecasts.py:99-112`): each partition's load sits in its own `try`. A failure skips that partition; one WARNING per load names how many were skipped. The removal of old partition files still runs.
- H9: in `async_step_save` (`config_flow.py:1274-1278`), when the entry is SETUP_ERROR or SETUP_RETRY, the flow applies the options itself (`async_update_entry`) and then calls `async_schedule_reload`, before returning `async_create_entry` (whose own update is then a no-op). The options are then in place before the eagerly started reload reads them. `_async_options_updated` (`__init__.py:248-258`) reloads when the entry has no `runtime_data`.
- T-09 path: an owed state whose `taken_with` is missing or cannot be parsed gives the fixable `hand_back_owed_<id>` issue. It is not persistent and is raised again at each setup while owed. One ERROR is logged, and the monitor runs (`__init__.py:219-242`).
- Values: none new.

**Code to change.**
- `__init__.py:62-87`: the order above.
- `__init__.py:207-245`: `_hand_back_unit` takes the state read in step 3.
- `__init__.py:248-258`: the guard on `runtime_data`.
- `coordinator.py:191-223`: split into `async_load()` (both stores) and `async_start()` (the rest).
- `forecasts.py:99-112`: best effort per partition.
- `config_flow.py:1274-1278`: H9.
- `control.py:377-379`: `provide_stored_control` moves to construction or `restore`; the new `async_hand_back_owed`.

**Texts.** None new. The existing `hand_back_owed` issue and its repair flow are used.

**Missing data.**
- Stores unreadable: V1, R4.
- `taken_with` missing or broken: the fixable issue.
- A forecast partition unreadable: skipped.
- VT not detectable (`async_detect` raises): setup fails after the owed hand-back was sent.
- The gateway or target unavailable at the attempt: the attempt fails and the hand-back stays owed; the persistent issue follows if setup fails.

**Do not.**
- Do not rely on an update listener to survive a failed setup (HA removes it).
- Do not leave any clock, listener or task running after a failed setup.
- Do not fail setup because of forecasts.
- Do not retry the hand-back from a loop while the entry is in SETUP_ERROR; the persistent issue tells the user.

**Open for the user.** None.

---

### V3 — saved at once: last command, SmartPI pause, on/off wish, error latch (P-10, P-11; C10, C15; T-29, T-31, T-39; review question 6)

**Goal and done-when.** Goal: a crash at any moment loses nothing the next start needs. That covers:
- the user's on/off wish;
- an internal-error latch;
- a SmartPI pause the plugin made;
- the last command given to the boiler, which X3 restores in the recognition period (decision 3) and X8 reuses for a relay.

A SmartPI resume that did not take is followed even after control leaves the options. Done when T-29, T-31, T-39 and the tests below pass, each with its negative case.

**Read first.**
- Plan: decision 3, first bullet; Terms "Control state" and "Recognition period"; decision 5 ("no delay where the plugin controlled the boiler before a restart"); the V3 row; review question 6, whose answer below the user confirmed on 2026-09-27 (answer K).
- Review: P-10, P-11 (§3.2); §6 T-29, T-31, T-39.
- `docs/plan-0.2.1.md`, "Open after R6" #6 (C10, C15).
- Research:
  - `research/2026-09-26-q4-decision-3-no-zone-known.md`: "Decided by the user", and Facts ("the stored control state holds no zone demand", `control.py:312-330`);
  - `research/2026-09-27-plan-0.2.2-checks.md`: Consistency, the recognition-period item (a)–(d);
  - `research/2026-09-27-fresh-session-test.md`: "### V3".
- Code:
  - `control.py:87, 312-373, 539-561, 565-584, 586-594, 800-852, 989-1054`
  - `switch.py:71-76`
  - `core/learning.py:36-49` (`check_s` 60 s, `give_up_s` one day)
  - `__init__.py:207-245`

**Order of work.**
1. Tests, in `tests/integration/test_control.py`:
   1. T-29 `test_a_smartpi_pause_is_stored_before_the_call`.
      - Given: a SmartPI zone with its valve open, and a hot-water draw starting.
      - When: the plugin pauses the zone.
      - Then: when `set_smartpi_learning(False)` is called, the control store already lists the zone under `paused`. A restart from that store resumes the zone.
   2. T-31 `test_control_waits_for_the_switch_to_restore_then_counts_as_off`.
      - Given: the control switch disabled in the entity registry; a hand-back owed; a stored wish "on".
      - When: steps run over 0–70 s.
      - Then: the owed hand-back goes at once; no decision for 60 s; then control counts as off and nothing more is written.
   3. T-39 `test_the_switch_off_survives_an_unclean_restart`.
      - Given: the restore cache holds "on"; the control store's `enabled` is false.
      - When: setup.
      - Then: the switch is off and nothing is written.
   4. `test_the_wish_is_stored_at_once`.
      - When: switch on.
      - Then: the control store has `enabled: true` with no delay; after off, false.
   5. `test_a_first_start_without_a_stored_wish_uses_the_restored_switch`.
      - Given: no `enabled` in the store; the restore cache holds "on".
      - Then: control is on. Negative: no restored state, so control is off.
   6. C10 `test_an_internal_error_outlives_a_restart`.
      - Given: stored `failed: true` and a wish "on".
      - When: setup.
      - Then: the switch shows on, but `control_error` blocks and nothing is written; off, then on, clears it.
   7. `test_an_internal_error_is_stored_at_once`.
      - When: the step raises.
      - Then: the control store has `failed: true` at once.
   8. `test_the_last_command_is_stored_at_once`.
      - Given: control heating at the curve value.
      - Then: `last_command` is `{heating: true, setpoint: <written>, at}` at once; a heating on/off change is stored at once; a ramp step below 1 K is not stored at once.
   9. `test_the_last_command_survives_only_the_stops_hand_back`.
      - Then: after the HA stop's hand-back `last_command` is kept; after switch-off, a latch, an internal error or a blocker hand-back it is `null`.
   10. C15 `test_a_resume_that_did_not_take_is_followed_after_control_leaves_the_options`.
       - Given: a paused SmartPI zone whose resume does not take.
       - When: the options remove control.
       - Then: after the reload, a unit sends the resume every 60 s until the flag reads on, and gives up after a day.
   11. Negative: `test_an_unreadable_last_command_is_ignored`.
       - Given: `last_command: "garbage"`.
       - Then: `null` and a WARNING; nothing else changes.
2. Implement. `test_control.py:656` (`test_the_switch_comes_back_after_a_restart`) keeps passing through the upgrade path (no stored wish). `test_control.py:1797` (an internal error cleared by a switch change) keeps passing, because a user's change still clears it.

**Rules and values.**
- The control state gains two fields:
  - `enabled` (bool, the user's wish);
  - `last_command`: `{"heating": bool, "setpoint": float | null, "at": float}` or `null`.
- Saved at once (V1, R2):
  - the wish at every change made by the user;
  - `failed` and `CONTROL_ERROR` when an internal error is caught (`control.py:572-578`, today delayed);
  - the SmartPI pause and resume state before the service call (`control.py:1032-1036`, today delayed; the calls are made later, in `_async_learning_calls`, 1056-1063);
  - `last_command` as below;
  - everything already saved at once today (the controlling marker, an outside-change event, a latch).
- The wish:
  - At start the switch entity, once added, asks the unit. The stored wish comes first; if none is stored (the first start of 0.2.2, or an unreadable store with no copy), the switch's restored state is used once; otherwise off.
  - A disabled switch is never added, so after `RESTORE_WAIT_S` (60 s, `control.py:87, 593-594`) control counts as off, while an owed hand-back still goes at once (T-31).
  - The restore sets `enabled` through a new `ControlUnit.restore_enabled(on)`, which does not clear `failed`. Only a user's switch change clears it (`control.py:547-549`, C10).
- The last command:
  - It is updated after each successful write: heating on/off as commanded (`LoopOutput.heating_on`) and the setpoint as written after the ramp.
  - It is saved at once when heating on/off changes, or when the setpoint differs from the stored one by at least 1.0 K (provisional, K4); otherwise with the next control save.
  - It is set to `null` (saved at once) when a session ends for any reason other than the stop's own hand-back: a switch-off, a latch, an internal error, a blocker, an alarm, a stale-link hand-back, or a hand-back confirmed while running.
  - It is kept through the hand-back made by `async_stop` (an unload, a reload, the HA stop).
  - V3 does not restore it. X3 does, in the recognition period, at once when all of these hold: V3 stored a last command; the stored wish is "control on" and the control switch entity is not disabled (answer K); no latch or internal error; the control options equal `taken_with`; no blocker other than `ha_starting` (and `vt_central_boiler_unknown` only within X3's P-105 grace). Until the write target and the boiler link are available, nothing is written and the restore waits, within the recognition period (at most 10 min); a link not yet reported never turns the restore into a hand-back. Otherwise the owed hand-back goes first. Until X3 is built, a start after holding makes the full hand-back first, as today (`control.py:370-373`).
  - X8 uses `heating` as the relay's commanded state.
- C15: the hand-back-only unit is also built when the stored state lists `paused` or `resuming` zones, even with nothing owed.
  - Without `taken_with`, it is built with the default `ControlOptions()` and a flag `follow_learning`.
  - It starts its clock even though its options are not configured.
  - Each step calls `_async_release_learning` (resend every `check_s` = 60 s until SmartPI's flag reads on, give up after `give_up_s` = 86400 s).
  - `allowed_services` includes `vtherm_smartpi.set_smartpi_learning` for such a unit.
- Values:
  - 1.0 K (provisional, K4);
  - 60 s restore wait (existing);
  - 60 s and one day for the resume follow-up (existing, `core/learning.py`).

**Code to change.**
- `control.py:312-330`: `stored()` gains `enabled` and `last_command`.
- `control.py:332-373`: `restore()` reads both, field by field.
- `control.py:539-554`: `async_set_enabled` saves the wish at once; the new `restore_enabled`.
- `control.py:556-561`: `_end_session` clears `last_command` unless the unit is stopping.
- `control.py:572-578`: saved at once.
- `control.py:800-852`: `last_command` is updated after the writes.
- `control.py:1032-1052`: saves at once.
- `control.py:377-381, 565-567, 590-592`: a hand-back-only or learning-only unit runs its clock and follows learning.
- `control.py:289-294`: `allowed_services`.
- `switch.py:71-76`: the wish from the unit first, the restored state only as the fallback.
- `__init__.py:207-245`: the unit is also built for `paused` or `resuming` zones.

**Texts.** None new.

**Missing data.**
- No stored wish: the restored switch state once; without it, off.
- A disabled switch: off after 60 s.
- An unreadable `last_command`: `null`, so nothing can be restored (X3 then waits, as decision 3 says for "no command held").
- SmartPI's flag unknown (`None`): the follow-up keeps resending every 60 s for at most a day.
- A zone gone: dropped after a day (existing).

**Do not.**
- Do not switch control on from a stored wish while the switch entity is disabled or absent.
- Do not let the restore clear an internal error.
- Do not restore the last command in V3 (X3 does).
- Do not write the store at every ramp step.

**Open for the user.** None. Review question 6 is answered here, and the user confirmed the answer on 2026-09-27 (answer K): after a restart the control switch comes back as the user left it, because the wish is saved at once, and a control switch disabled in Home Assistant means control off.

---

### V4 — the hand-back's bookkeeping (P-12, P-42, P-49, P-50, P-51, P-52; Open after R6 #8; T-05, T-06, T-13, T-14)

**Goal and done-when.** Goal: no exception, cancellation, late echo, concurrent repair, options save or clock change can make a hand-back count as done when it is not, or lose the fact that it is owed. Done when T-05, T-06, T-13 and T-14 (extended to the save) pass, plus the tests below, each with a `None` or unknown read-back variant.

**Read first.**
- Plan: the V4 row.
- Review: P-12 (§3.2), P-42, P-49, P-50, P-51, P-52 (§3.3); §6 T-05, T-06, T-13, T-14; Appendix E question 18.
- `docs/plan-0.2.1.md`, "Open after R6" #8.
- Research:
  - `research/2026-09-27-fresh-session-test.md`, "### V4";
  - `research/diy/pyotgw/2.2.3/pyotgw.py:564-580` (on success, `set_control_setpoint` writes the accepted value to the status at once), `:600-621` (the same for the CH bit), `:704-719` (on a timeout it logs and returns `None`, and the service returns normally);
  - `research/2026-09-24-vt-otgw-interfaces-f2-f4-f5.md`, F5.
- Code:
  - `control.py:84, 405-448, 467-481, 586-594, 800-852, 866-931, 946-972`
  - `repairs.py:37-57`
  - `config_flow.py:908-921, 1188-1215, 1274-1278, 1283-1310`
  - `core/controller.py:249-257, 303-311`
  - `transport/writers.py:228-238, 272-290, 319-324, 327-343`
- HA: the stage-1 budget for all shutdown jobs together is 20 s (`core.py:111, 1148-1163`).

**Order of work.**
1. Tests:
   1. T-05 `test_a_hand_back_cut_by_a_foreign_cancel_stays_owed`.
      - Given: control active; the hand-back service raises `CancelledError` (not from a stop), or `RuntimeError`.
      - When: a step decides to hand back.
      - Then: `hand_back_owed` is true; a retry after 60 s; the `hand_back_failed` alarm.
   2. T-06 `test_stop_never_raises_when_the_hand_back_raises_unexpectedly`.
      - Given: control holds the boiler; `writer.hand_back` raises `RuntimeError`.
      - When: (a) unload or reload; (b) `_async_step` raises.
      - Then:
        - nothing escapes and the owed marker is true;
        - (a) the persistent issue; (b) the issue shown and `control_error`;
        - the next start retries a full hand-back.
   3. P-49 `test_an_end_of_session_hand_back_is_full_while_an_older_debt_exists`.
      - Given: a debt from an earlier run with a held heating switch left off; a new session whose writes fail.
      - When: switch-off.
      - Then: the hand-back is full (the switch goes back as V5 says).
   4. P-51 `test_a_release_by_hand_waits_for_a_running_attempt`.
      - Given: a hand-back attempt blocked in a slow service.
      - When: the repair release runs.
      - Then: it waits for the attempt; afterwards nothing is owed and the attempt did not set the debt again.
   5. T-13 `test_gateway_id_cannot_change_while_a_hand_back_is_owed`.
      - Given: two opentherm_gw entries; control through gw1.
      - When: the control step passes with nothing owed, the unit starts owing before the save, then the flow saves gw2.
      - Then: the save goes back to the control step with `{"base": "hand_back_pending"}`; the options are unchanged; gw1 goes on.
   6. T-14 `test_mqtt_topics_cannot_change_while_control_holds_the_boiler`.
      - The same at the save for `control_mqtt`. A changed node is refused; the same node with spaces passes.
   7. P-52 `test_a_stop_during_the_save_leaves_no_unawaited_write`.
      - Given: a slow control save before a write.
      - When: the unit stops.
      - Then: no "coroutine was never awaited" `RuntimeWarning` (checked with `recwarn`).
   8. P-50 `test_a_late_echo_at_stop_counts_within_the_wait`.
      - Given: a held entity that echoes 3 s after the write.
      - When: HA stops.
      - Then: the hand-back counts as done and there is no persistent issue. Negative: an echo after 8 s leaves it owed, with the persistent issue.
   9. P-50 `test_the_first_hand_back_after_start_raises_no_alarm_within_the_grace`.
      - Given: an owed hand-back; the target unavailable for 40 s after the start.
      - Then: no `hand_back_failed` and no ERROR; the hand-back is sent when the target returns. Negative: unavailable for 70 s, so the alarm rises after 60 s.
   10. Open after R6 #8 `test_an_otgw_hand_back_the_gateway_did_not_take_stays_owed`.
       - Given: the gateway connected; the fake ignores `CS=0` (the service returns, the read-back stays at the plugin's value).
       - Then: owed; retried every 60 s; `hand_back_failed` after 60 s; done as soon as the read-back leaves the plugin's value. Negative: the read-back `unknown`, so it stays owed.
   11. Clock set back:
       - in `tests/core/test_controller.py`: `test_a_clock_set_back_does_not_hold_up_the_stale_hand_back` and `test_a_clock_set_back_makes_the_water_decision_due`;
       - in `test_control.py`: `test_a_clock_set_back_does_not_hold_up_the_owed_retry`.
2. Implement R1–R8.

**Rules and values.**
- R1 (P-42): before every hand-back attempt, set `_hand_back_pending = True` and `_hand_back_retry_at = now + 60 s` and save the control state at once; then write.
  - Any `Exception` counts as a failed attempt: owed, `hand_back_failed`, the issue as in `control.py:946-957`.
  - A `CancelledError` while the current task is not being cancelled (a foreign cancel inside a service) counts as a failed attempt.
  - A real cancellation is re-raised, and the owed marker stays set.
- R2 (P-49): an attempt is full when a debt existed at its start (`_hand_back_pending`) or `_full_hand_back_due` is set (`control.py:870`).
- R3 (P-51): `release_owed_hand_back` becomes `async_release_owed_hand_back` and takes the unit's lock, so a running attempt ends first. `repairs.async_release` awaits it.
- R4 (P-12): `async_step_save` re-runs `_async_hand_back_blocker()` when any of `HAND_BACK_KEYS` (`config_flow.py:431-434`) or an OTGW read-back differs from the entry's current options. On a blocker the flow goes back to the control step with `{"base": <blocker>}` (`_PROBLEM_STEPS` gains `hand_back_pending` and `control_holds_boiler` → `control`), and nothing is saved.
- R5 (P-52): `_async_write` takes a factory (`Callable[[], Awaitable[None]]`). The coroutine is created only after the store save (`control.py:809-827`).
- R6 (P-50, Open after R6 #8), a late report:
  - At the stop: after the hand-back writes, wait up to 5 s (provisional, K4) for the checks. The wait comes after every part of the hand-back was written; the parts themselves follow one another at once (V5). The whole stop hand-back (writes plus wait) must end within 15 s, with each write capped at 4 s (both provisional, K4; Q3 answers review question 18), inside HA's 20 s stage-1 budget. Still unconfirmed means owed, with the persistent issue, as today.
  - At the start: for 60 s after the unit starts (provisional, K4; Q3 gives ESPHome's figure), an owed hand-back that fails or stays unconfirmed raises no `hand_back_failed` and logs only at DEBUG. The persistent issue stored at the last stop is neither deleted nor raised again. The hand-back is retried at each step (10 s) while the target is unavailable; after the grace, the normal rules apply.
- R7 (Open after R6 #8), an OTGW hand-back is judged by the read-back. The writer returns a release check on the gateway's setpoint read-back (`confirmed_entity`).
  - Released: the read-back is known and more than 0.5 K from the plugin's last written setpoint (this session's, else the stored `last_command`). With neither known: a value reported after the command (`last_updated` later than the send).
  - Not released within 60 s (provisional, K4; the override's own lapse time): owed, retried every 60 s, `hand_back_failed`.
  - The `CH=1` part has no read-back check. After `CS=0` the CH echo shows the thermostat's own bit or the PIC's own 0 (assumed from the PIC facts in `CLAUDE.md`; Q3 confirms what `opentherm_gw` shows after `CS=0` in each topology).
  - V5 adds "and more than 0.5 K from the lowest water temperature written".
- R8 (C9), a clock set back: a moment later than now counts as now.
  - `ControlState.waiting_since` (`core/controller.py:250`) is reset to now when it lies in the future.
  - The water decision is due when `decided_at` lies in the future (`core/controller.py:304-311`).
  - `_hand_back_retry_at` more than 60 s ahead is set to now.
  - Pure checks in core, as the guards already do for keep-alives (`core/guards.py:163-167`).

**Code to change.**
- `control.py`: 866-898 (R1, R2), 900-918 (R6, R8), 959-972 (R3), 809-827 (R5), 415-448 (R6 at the stop), 946-957 (the start grace in `_report_owed`).
- `repairs.py:37-57` (R3).
- `config_flow.py:908-921, 1274-1278` (R4).
- `core/controller.py:249-257, 303-311` (R8).
- `transport/writers.py:272-290, 319-324`: return a release check (R7). `HandBackCheck` (47-52) gains a kind "leaves value X".

**Texts.** None new. The save-time refusal reuses `options.error.hand_back_pending` and `options.error.control_holds_boiler` as base errors.

**Missing data.**
- A read-back that is missing, `unknown` or `unavailable`: the hand-back is never counted as done; it stays owed and is retried.
- No last written value and no stored command: R7's "reported after the command".
- The gateway not connected: the existing `_require_connected(reported=True)` fails the attempt.
- A clock set back: R8.

**Do not.**
- Do not count a service call's normal return as a release on the gateway paths.
- Do not swallow a real cancellation of the step.
- Do not raise an ERROR or alarm for an owed hand-back within the start grace.
- Do not create a write coroutine before it is awaited.
- Do not let the repair release run while an attempt is in flight.

**Open for the user.** None. The provisional values go to K4 with Q3's answers.

---

### V5 — the safe hand-back and what confirms it (P-21, P-40; S-09, S-20, S-21, S-27, S-49; T-30)

**Goal and done-when.** Goal: every hand-back follows the decided order and counts only on real evidence:
1. the water to the lowest water temperature;
2. heating on where the boiler returns to a thermostat or its own control;
3. the release.

The parts follow one another at once. A target declared held (the device keeps the last value: ESPHome, DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires within about a minute) alarms at once when its release is not confirmed. A target another controller holds ends the retries, and a repair issue says so. The form refuses the combinations the review found. Done when T-30 and every test below pass, including the negative ones.

**Read first.**
- Plan: the decision "Safe hand-back"; Terms "Safe hand-back"; decision 6 ("Another controller"); the V5 row. The user's answers of 2026-09-27: F (the "own room controller" tick, whose hand-back effect is `OWN_CONTROL_RESUMES`) and H (a step-aside makes the whole safe hand-back, even over the other controller's value).
- Review: P-21, P-40 (§3.2); S-09, S-20, S-21 (§3.2), S-27, S-49 (§3.3), and their section 4 proposals; §6 T-30.
- Research:
  - `research/2026-09-26-q4-decision-6-outside-change-matrix.md`: §5 (rule W3, W6), row B2, and Verification, "Missing" (B2's rule cannot work for a two-valued target) and "Safety concerns" (the alarm level follows the hand-back effect);
  - `research/2026-09-27-plan-0.2.2-checks.md`: Fidelity item 2 (a failed DIY release, so an alarm and retries) and Consistency, the "Safe hand-back" item;
  - `research/2026-09-25-l3-device-facts.md`: ESPHome holds its values; EMS-ESP's `selflowtemp` expires within about a minute;
  - `research/2026-09-27-fresh-session-test.md`: "### V5".
- Q1's matrix of outside changes, rows M12 (a hand-back against another controller) and M13 (a held release not confirmed).
- Code:
  - `transport/writers.py:91-214, 217-324`
  - `control.py:508-537, 688-698, 765-782, 856-931`
  - `control_config.py:94-111, 130-172, 187-296, 299-374`
  - `config_flow.py:431-476, 693-719, 1312-1337, 1395-1445`
  - `sensor.py:458-498`
  - `__init__.py:141-147` (the issue keys deleted at removal)

**Order of work.**
1. Tests, in `tests/integration/test_control.py` and `tests/integration/test_writers.py`:
   1. `test_the_hand_back_order_per_path`, parametrised:
      - OTGW: `CS=<lowest>`, `CH=1`, `CS=0`;
      - entity + value with "own control": the lowest, heating switch on, the hand-back value (the same once Y1 names this effect `OWN_CONTROL_RESUMES`, and for any entity path with the "own room controller" tick);
      - entity + value with "heating stops": the lowest, the hand-back value, the heating switch untouched;
      - entity + timeout: the lowest, heating switch on, then silence;
      - entity + switch: the lowest, heating switch on, the external switch off.
   2. `test_a_stand_alone_gateway_still_gets_ch_1_at_hand_back`.
   3. T-30 `test_an_optimistic_setpoint_entity_does_not_confirm_a_hand_back`.
      - Given: a setpoint entity with `assumed_state`; the device not receiving.
      - When: control is switched off.
      - Then: the hand-back is done once written; `hand_back_confirmation: unverified`; no retry.
   4. `test_a_held_release_not_confirmed_raises_the_alarm_at_once`.
      - Given: a held entity; the write of the hand-back value fails.
      - Then: `hand_back_failed` at once (outside V4's start grace); retried every 60 s; the entity holds the lowest.
   5. `test_a_timeout_hand_back_is_confirmed_when_the_read_back_returns_to_the_baseline`.
      - Given: the session's baseline 45 °C known.
      - Then: released once the read-back is back within 0.5 K of 45 °C. Variant: the baseline unknown, so released once the read-back is more than 0.5 K from both the plugin's last value and the lowest just written.
      - Negative: the read-back stays, so there are no rewrite retries and `hand_back_failed` rises after 3 min.
   6. `test_a_target_another_controller_holds_counts_as_handed_back`.
      - Given: a held entity; after the hand-back, the read-back holds 60 °C at two checks 60 s apart, with no hot water.
      - Then: done, no more retries, `taken_by_other`, the `hand_back_taken_by_other_<id>` issue (error with a stand-alone gateway or "heating stops", warning with a thermostat), one WARNING.
      - Negatives:
        - a hot-water draw now or within 120 s gives no judgement; with hot water unknown it takes three checks over 120 s;
        - a heating switch read back "on" once, then "off" with no trace of an outage → `taken_by_other`; never read back "on" → still owed and retried; "off" after the switch was unavailable within the 5 min before → a lost command, "on" written again (the external switch the same, with "off" as its hand-back state);
        - no `hand_back_taken_by_other` issue while V7's `control_latched` issue for another controller is up.
   7. P-21 `test_otgw_control_waits_until_the_gateway_has_reported`.
      - Given: the gateway's read-back `unknown` since the start.
      - Then: no write and `waiting_data` until it holds a value; then control takes the boiler.
      - Variant `test_an_unknown_gateway_read_back_while_controlling_is_not_a_hand_back_by_itself`: controlling; the read-back turns `unknown` while the flame and the flow stay fresh → nothing judged, X1's `confirmation_missing` after 5 min, no hand-back; the flame and the flow going stale → X2's stale-link hand-back.
   8. S-21 `test_a_hand_back_value_above_the_maximum_is_refused`.
      - The form refuses it at the save; hand-edited options give the blocker `hand_back_value_above_max`; the value is never clamped.
   9. P-40:
      - `test_an_external_switch_of_unknown_write_type_blocks_control`: the form error and the blocker `hand_back_switch_not_writable`;
      - `test_an_expiring_external_switch_is_turned_on_every_keep_alive`;
      - `test_a_held_external_switch_is_turned_on_once_per_take`.
   10. S-49 `test_off_near_an_own_control_hand_back_value_is_refused`.
       - The form and the blocker; allowed when a heating switch is used, or when the value effect is "heating stops".
   11. `test_the_hand_back_does_not_wait_between_its_parts`.
       - Given: a read-back that never shows the lowest water temperature (variant: the write of the lowest fails).
       - Then: the heating part and the release are written in the same attempt, with no wait.
2. Update every test that pins the old hand-back calls to the new order. Search `tests/integration/test_control.py` and `tests/integration/test_writers.py` for `("setpoint", 0.0)` and `setpoints() ==`, for example `test_control.py:237-265, 1046-1083`.

**Rules and values.**
- Order.
  1. The first hand-back write is the lowest water temperature set: today's hard minimum `limits.hard_min`, 10–50 °C (`config_flow.py:520`); its default becomes 20 °C in X6. This applies on every path, the gateway included; a relay is X8. A passive fixed circuit's floor does not apply at hand-back. In a hand-back attempt it is written on every target, a target another controller holds included: at a step-aside the whole safe hand-back briefly writes over the other controller's value (the user's answer H of 2026-09-27; V7).
  2. Heating on:
     - on a gateway, `CH=1` always. It only clears the plugin's own `CH=0` flag, so it is not the "heating on" S-27 forbids; stand-alone, `CS=0` still leaves the boiler without demand;
     - on an entity path, the heating switch is turned on when the effect (`control_config.py:299-314`) is "thermostat takes over" or "device decides" (today a value with "own control", or the timeout or switch method in the virtual topology). `OWN_CONTROL_RESUMES`, which Y1 adds for a value declared "own control" and for any path with the "own room controller" tick (the user's answer F of 2026-09-27), is treated as "device decides" here;
     - it is left as it is when the effect is "heating stops";
     - a relay has X8's `RELAY_RESTS_OFF` / `RELAY_RESTS_ON` and goes to its rest state instead (X8).
  3. The release: the hand-back value (value method); the external switch off (switch method); nothing more (timeout method); `CS=0` (gateway).
  - Each part is tried whatever the others do, as today (`transport/writers.py:184-214, 327-343`).
  - The parts follow one another at once: the hand-back waits neither for a read-back nor for the water to cool (provisional, K4). Only the confirmation below waits for the read-back.
- What confirms a release:
  - A value target with a separate read-back (`confirmed_entity` differs from the written entity and has no `assumed_state`) gives "confirmed".
    - A **held** target (write type "held", declared by the user: ESPHome, DIYLess and the like; not EMS-ESP's `selflowtemp`, which expires within about a minute): released only when the read-back is within 0.5 K of the hand-back value.
    - An **expiring** target or the gateway: released when the read-back is within 0.5 K of the hand-back value, or more than 0.5 K from both the plugin's last written value and the lowest just written.
  - The read-back is the written entity itself: the same check, shown "unverified".
  - `assumed_state`: no check; done once the writes succeed; shown "unverified" (T-30).
  - The external switch and the heating switch have no separate report: each counts when its own state reads "off" or "on" and it has no `assumed_state`, shown "unverified"; with `assumed_state`, done once written.
- A held target not confirmed: `hand_back_failed` rises when the release write fails, or when the release is still unconfirmed 10 s (one step) after it (provisional, K4), but not within V4's start grace. It is retried every 60 s; meanwhile the device holds the lowest water temperature.
- Timeout (S-20): released when the read-back is back within 0.5 K of the session's baseline (X1: the value from before the plugin); with the baseline unknown, when it is more than 0.5 K from both the plugin's last value and the lowest just written. No retry writes, because each would re-arm the device's timer. `hand_back_failed` rises after 3 min without release (provisional, K4; the same value as Q1's safe hand-back). The hand-back stays owed and shown until the release.
- Taken by another controller (decision "Safe hand-back", W3; Q1 matrix row M12).
  - A value target: held value targets only. An expiring target under the value method that leaves the plugin's value is already released, and a timeout hand-back is never rewritten anyway.
    - Trigger: at two consecutive retry checks 60 s apart, the read-back shows the same third value (more than 0.5 K from the plugin's last value, the lowest and the hand-back value). With no hot-water draw now or in the last 120 s (W6). With hot water unknown: three checks over 120 s. (All provisional, K4.)
    - While such a value is being judged, the retry write is held back.
  - A two-valued target (the heating switch, the external-control switch) counts as taken by another controller when its hand-back state ("on" for the heating switch, "off" for the external switch) was read back once and then changed with no trace of an outage (provisional, K4). A trace of an outage is X1's: within the 5 min before (provisional, K4), the target, its read-back, or another entity of the same device or gateway that the plugin reads was unavailable, unknown or missing, or a gateway or device restart was seen. Before the hand-back state was read back once, the target stays owed and is retried. A change with a trace is a lost command: the hand-back state is written again (X1).
  - Result, for either kind: the hand-back counts as done for that target and is not retried; the owed marker clears when every target is done. The target is shown `taken_by_other`, one WARNING is logged, and the repair issue `hand_back_taken_by_other_<entry_id>` is raised (severity error where the hand-back effect is "heating stops" — stand-alone, a value declared "heating stops", X8's relay left "off" — else warning; not fixable, not persistent). The issue is deleted when control takes the boiler again or the entry is removed. It is not raised while V7's `control_latched` issue for another controller is up, which already says so.
- P-21, one rule for writes and hand-back on the gateway paths: control takes the boiler only once the gateway's setpoint read-back holds a value (not `unknown`, not `unavailable`), the same evidence a hand-back needs to count (V4, R7). Before that nothing is written (waiting for data). Once controlling, a read-back that turns unknown or unavailable is not judged: after 5 min (provisional, K4) X1's information alarm `confirmation_missing` rises, never a hand-back by itself; X2's boiler link (flame, flow) decides the hand-back.
- S-21: the hand-back value must not exceed min(`hard_max`, the circuit maximum, the boiler maximum).
  - It is refused in the form: at the `control_entity` step, and at the save when a later step lowered a maximum (`_back_to_problem`, mapped to `control_entity`).
  - It is the blocker `hand_back_value_above_max` for hand-edited options.
  - It is exempt only from `hard_min`, and never clamped.
- S-49: when "off" goes as a low setpoint (no heating switch) and the hand-back is a value with "own control", "off" within 0.5 K of the hand-back value is refused. It is a form error in `control_behaviour` and at the save, and the blocker `off_setpoint_near_hand_back_value`. In 0.2.2 control without a heating switch is blocked anyway (decision 11), and lifting that block waits for the user at K4 (the user's answer K of 2026-09-27); the check is built now so the options stay safe once it is lifted.
- P-40: a new option `hand_back_entity_write_type` (expiring / held / persistent / unknown; default unknown), required with the switch method.
  - Persistent or unknown: form error `hand_back_entity_write_type_not_supported` and blocker `hand_back_switch_not_writable`.
  - Held: turned on once each time control takes the boiler (today's `_take`, `transport/writers.py:166-169`). X1 adds the resend of held values after the device returns and every 300 s (provisional, K4).
  - Expiring: turned on again every 30 s (`KEEPALIVE_S`) while control holds the boiler.
  - There is no migration: an entry without it is blocked until the user declares it.
- A status field `hand_back_check` feeds the `control_state` attribute `hand_back_confirmation`: `confirmed`, `confirmed_by_gateway`, `unverified`, `waiting`, `not_confirmed`, `taken_by_other`.
- Values:
  - release tolerance 0.5 K (existing, `control.py:929`);
  - 10 s, 3 min, 2 checks / 60 s, 3 checks / 120 s, 120 s after hot water, the two-valued rule's 5 min trace window (X1's), no wait between the parts (all provisional, K4);
  - keep-alive 30 s (existing);
  - S-49 margin 0.5 K (plan).

**Code to change.**
- `transport/writers.py`:
  - 184-214: the new order and the effect rule for the heating switch;
  - 159-169: the external switch's write type;
  - 272-290, 319-324: `CS=<lowest>` first;
  - 47-52: `HandBackCheck` gains the kind (value / switch / leaves-value / back-to-baseline), the source (separate / self / assumed) and whether the target is held.
- `control.py`:
  - 920-931: the release rules;
  - 900-918: the held alarm, no retry writes for a timeout, taken-by-other for value and two-valued targets, and its repair issue;
  - 688-698: `_boiler_link` unchanged; a new check before the take waits, on the gateway paths, for the read-back to hold a value (P-21);
  - 169-195: `ControlStatus.hand_back_check`.
- `control_config.py`:
  - 94-111: three new blocker keys;
  - 130-151, 187-296: the option;
  - 317-374: the blockers;
  - a pure `hand_back_value_problem()` shared with the flow.
- `config_flow.py`: 431-434 (`HAND_BACK_KEYS` gains the new option), 452-476, 591-610, 693-719, 908-921, 1420-1445.
- `sensor.py:458-498`: the attribute, which is also unrecorded.
- `__init__.py:141-147`: `hand_back_taken_by_other` joins the issue keys deleted at removal.

**Texts.**
- `options.step.control_entity.data.hand_back_entity_write_type`: "External control switch write type" / "Typ zapisu przełącznika sterowania zewnętrznego".
- Its `data_description`:
  - en: "Needed with the switch method: what the device does with the switch's state. Expiring: dropped unless repeated — turned on again every 30 s while control holds the boiler. Held: the device keeps it — turned on once each time control takes the boiler. Persistent or unknown (default): it may be stored in the boiler's memory, which every switching would wear, so control is not available with it."
  - pl: "Potrzebny przy metodzie przełącznika: co urządzenie robi ze stanem przełącznika. Wygasający: znika, jeśli nie jest powtarzany — włączany ponownie co 30 s, dopóki sterowanie trzyma kocioł. Trzymany: urządzenie go zachowuje — włączany raz za każdym razem, gdy sterowanie przejmuje kocioł. Trwały albo nieznany (domyślnie): może być zapisywany w pamięci kotła, którą każde przełączenie zużywa, więc sterowanie z nim jest niedostępne."
- Changed `data_description` texts in `control_entity`, en and pl:
  - `hand_back`: states the order: first the lowest water temperature, then heating on where the boiler returns to its own control or a thermostat, then the chosen method.
  - `hand_back_value`: "must not exceed the highest flow setpoint or the circuit's maximum; it counts as done once the read-back shows it".
  - `ch_entity`: "turned back on at hand-back where the boiler returns to its own control or a thermostat; left as it is where the hand-back stops heating".
- `options.error.hand_back_entity_write_type_not_supported`:
  - en: "Declare the external control switch expiring or held: the plugin never writes to the boiler's persistent memory."
  - pl: "Zadeklaruj przełącznik sterowania zewnętrznego jako wygasający albo trzymany: wtyczka nigdy nie zapisuje do trwałej pamięci kotła."
- `options.error.hand_back_value_above_max`:
  - en: "The hand-back value is above the highest flow setpoint or the circuit's maximum: the boiler would get hotter water than the circuit allows."
  - pl: "Wartość oddania jest wyższa niż najwyższa nastawa zasilania albo maksimum obiegu: kocioł dostałby cieplejszą wodę, niż obieg dopuszcza."
- `options.error.off_setpoint_near_hand_back_value`:
  - en: "\"Off\" is within 0.5 K of the hand-back value, which returns the boiler to its own control: \"off\" would hand the boiler back instead of stopping heating. Pick another value."
  - pl: "„Wyłączone” różni się od wartości oddania o mniej niż 0,5 K, a ta wartość oddaje kotłowi własne sterowanie: „wyłączone” oddałoby kocioł zamiast wyłączyć grzanie. Wybierz inną wartość."
- `exceptions.blocked_hand_back_switch_not_writable`, `blocked_hand_back_value_above_max` and `blocked_off_setpoint_near_hand_back_value`: `message` = the matching error text + " Other reasons: {others}." / " Inne powody: {others}."
- `issues.hand_back_taken_by_other`:
  - en title: "After the hand-back another controller holds the boiler".
  - en description: "The plugin handed the boiler back, and another controller — an automation, a device's own program or another integration — now holds what the plugin had set: {target}. The plugin counts the hand-back as done and does not write there again. With a thermostat or the boiler's own control, heating goes on under it; where the hand-back stops heating, the boiler heats only under that other controller. If you do not expect another controller, find it."
  - pl title: "Po oddaniu kotłem steruje inny sterownik".
  - pl description: "Wtyczka oddała kocioł, a inny sterownik — automatyzacja, własny program urządzenia albo inna integracja — trzyma teraz to, co wtyczka ustawiła: {target}. Wtyczka uznaje oddanie za wykonane i więcej tam nie zapisuje. Z termostatem albo własnym sterowaniem kotła grzanie idzie dalej pod nim; tam, gdzie oddanie zatrzymuje grzanie, kocioł grzeje tylko pod tym innym sterownikiem. Jeśli nie spodziewasz się innego sterownika, znajdź go."
- `entity.sensor.control_state.state_attributes.hand_back_confirmation`: name "Hand-back read-back" / "Odczyt oddania". States:

  | State | en | pl |
  |---|---|---|
  | `confirmed` | Confirmed by the device | Potwierdzone przez urządzenie |
  | `confirmed_by_gateway` | Confirmed by the gateway | Potwierdzone przez bramkę |
  | `unverified` | Unverified: only the written entity shows it | Niezweryfikowane: pokazuje je tylko zapisana encja |
  | `waiting` | Sent, waiting for the read-back | Wysłane, czeka na odczyt |
  | `not_confirmed` | Not confirmed: sent again every minute | Niepotwierdzone: wysyłane ponownie co minutę |
  | `taken_by_other` | Another controller holds the value | Wartość trzyma inny sterownik |

**Missing data.**
- The read-back missing, `unknown` or `unavailable`: never released; owed and retried (a timeout hand-back is not rewritten).
- `assumed_state`: unverified; done once written.
- Hot water unknown: three checks (above).
- A two-valued target never read back in its hand-back state: owed and retried, never judged taken by another.
- No outage information for a two-valued target: a change counts as without a trace, so it can be judged taken by another only after its hand-back state was read back once.
- `hand_back_value` missing: the existing `no_hand_back` blocker.
- The write type of the external switch missing: unknown, so the blocker.
- No circuit maximum: only `hard_max` and the boiler maximum bound the value.
- The gateway read-back without a value: no writes before control takes the boiler (P-21); while controlling, `confirmation_missing` after 5 min and no hand-back by itself (X1, X2).
- The session's baseline unknown for a timeout hand-back: the release is judged against the plugin's last value and the lowest just written.

**Do not.**
- Never clamp the hand-back value.
- Never switch the heating switch on where the effect is "heating stops".
- Never count a service's success as a release.
- No retry writes for a timeout hand-back.
- Do not judge a two-valued target as taken by another before its hand-back state was read back once.
- Do not retry every minute against a target another controller holds.
- Do not wait between the hand-back's parts, for a read-back or for the water to cool.
- Do not skip a part of the hand-back because another controller holds its target (the user's answer H); only the retries stop, once the target is judged taken by another.

**Open for the user.** None. The provisional values go to K4.

---

### V6 — the stop button (P-02, P-24; T-15, T-54)

**Goal and done-when.** Goal: the control switch and the control alarms stay usable when the monitor fails; a lasting failure is logged once and its recovery once; control hands the boiler back when the monitor stays failed, and resumes by itself, with an information note, once the monitor works again (the user's answer I of 2026-09-27). Done when T-15, T-54 and the tests below pass.

**Read first.**
- Plan: decision 7 ("always: an internal error"); the V6 row. The user's answer I of 2026-09-27: if the plugin's own monitor fails for 5 min, control hands back; it resumes by itself once the monitor works again, like after the lost boiler link, with an information note.
- X2 in this file: the link window (stale for 300 s within 600 s) and the recovery (60 s fresh without a break), which V6 applies to the monitor.
- Research:
  - `research/2026-09-26-q4-decision-7-alarms.md`: "Decided by the user";
  - `research/2026-09-27-fresh-session-test.md`: "### V6".
- Code: `entity.py:56-68`; `coordinator.py:532-534, 815-825`; `control.py:91-99, 147-165, 485-506, 565-584, 740-763`; `switch.py:21-24`; `binary_sensor.py:64-65`; `__init__.py:141-147`.
- HA:
  - `helpers/update_coordinator.py:510-513` (`UpdateFailed` is logged once per failure streak), `:567-575` (any other exception is logged with a traceback at every refresh; the recovery INFO is logged once);
  - `helpers/issue_registry.py:339-354` (creating an issue with an existing id replaces it), `:287-300` (a non-persistent issue is inactive after a restart).

**Order of work.**
1. Tests, in `tests/integration/test_control.py`:
   1. T-15 `test_control_switch_stays_usable_when_the_monitor_refresh_fails`.
      - Given: control on and writing; `_compute` (variant: `feature_manager.async_check`) raises at every refresh.
      - When: `switch.turn_off`.
      - Then: the boiler is handed back; the switch and the control alarms are not `unavailable`.
   2. T-54 `test_a_lasting_fast_path_error_is_logged_once`.
      - Given: `_compute` raises for 10 min, then works.
      - Then:
        - exactly one ERROR with a traceback from the plugin;
        - at most one ERROR without a traceback ("Error fetching …", HA);
        - one recovery INFO.
   3. `test_control_hands_back_when_the_monitor_keeps_failing`.
      - Given: controlling; `_compute` raises.
      - Then: at 300 s the blocker `monitor_failed`, a hand-back, the alarm `monitor_failed` and the `monitor_failed_<id>` issue (error with a stand-alone gateway, warning with a thermostat). When `_compute` works again for 60 s, control resumes on its own, the alarm goes off and the issue becomes the information note `monitor_recovered`. A single good refresh does not resume.
   4. `test_stale_monitor_alarms_do_not_hand_back`.
      - Given: a monitor alarm set to hand back is active in the last data, then the monitor fails.
      - Then: no hand-back caused by it while the monitor fails.
   5. `test_a_lasting_control_step_error_is_logged_once`.
      - Given: `_async_step` raises at every step for 5 min.
      - Then: one ERROR with a traceback, one INFO at recovery.
   6. Negative: `test_a_short_monitor_failure_changes_nothing`.
      - Given: 290 s of failures.
      - Then: no blocker and no hand-back.
   7. `test_a_flapping_monitor_still_hands_back`.
      - Given: controlling; 9 refreshes in 10 fail.
      - Then: a hand-back once the failed refreshes cover 300 s within 600 s. Negative: one failed refresh every 5 min → nothing.
   8. `test_the_monitor_recovered_note_goes_when_control_is_switched_off`.
      - Then: after the resume, switching control off deletes `monitor_recovered`; a reload keeps it.
2. Implement the rules below.

**Rules and values.**
- Control entities (switch, `control_state`, `control_setpoint`, control alarms) are available while the control unit exists and is not stopping. They override `available` in `ControlEntity`, independent of `coordinator.last_update_success`.
- `_async_update_data` wraps `feature_manager.async_check` and `_compute`.
  - An exception is logged once with a traceback (`_job_failed("The monitor refresh")`, `coordinator.py:815-821`) and raised as `UpdateFailed`.
  - Success after a failure logs once (`_job_works`).
  - The coordinator keeps the refresh outcomes of the last 600 s (time, failed), each counting until the next refresh, at most 60 s, as X2 keeps the link samples; and `monitor_failed_since` (the first failure of the current streak) for the attributes and the note.
- The runtime blocker `monitor_failed` holds once failed refreshes cover at least 300 s within the last 600 s (300 s decided by the user's answer I; the 600 s window as X2's link, provisional, K4).
  - The controller releases, so a hand-back.
  - `ControlAlarm.MONITOR_FAILED` is on while it lasts.
  - Control resumes on its own once the refreshes have succeeded for 60 s without a failure (X2's recovery; provisional, K4); the samples are then cleared (the user's answer I).
  - It is a transient blocker (`switch.py:21`): switching on waits instead of being refused.
  - The window rule is a pure function in `core/controller.py`, which X2's link window reuses.
- The information note (the user's answer I). Home Assistant has no information level for repair issues (`helpers/issue_registry.py:46-51`: critical, error, warning), so:
  - when the blocker hands back a session that held the boiler, the repair issue `monitor_failed_<entry_id>` is raised (translation key `monitor_failed`; severity error where the hand-back effect is "heating stops" — stand-alone, a value declared "heating stops", X8's relay left "off" — else warning; not fixable, not persistent). V7's `control_stopped_heating` is not raised for this blocker;
  - when control resumes, the same issue id is created again with the translation key `monitor_recovered`, severity warning: the note that the monitor failed, from when to when, and that control resumed by itself;
  - the issue is deleted when the user switches control off or removes the entry; a reload keeps it; being not persistent, it is gone after a Home Assistant restart. A new failure replaces the note with `monitor_failed`.
  - The monitor fails before control ever took the boiler: no issue (nothing was handed back); the alarm and the blocker show it.
- While the monitor fails, `_hand_back_alarms` ignores `coordinator.data.alarms`, because they are stale; unknown values never count (decision 7).
- An exception in the control step (`control.py:568-571`) is logged with a traceback only on the first failure of a streak, then at DEBUG; the first step without one logs INFO once.
- Values: 300 s (decided, the user's answer I); 600 s window and 60 s recovery (provisional, K4).

**Code to change.**
- `entity.py:56-68`: `available`.
- `control.py`: a public `stopping` property on `ControlUnit`; 91-99 (`RUNTIME_BLOCKERS`), 147-165 (`ControlAlarm`), 485-506 (the resume and the note), 565-584, 740-763.
- `coordinator.py:532-534`: as above, with the refresh outcomes.
- `core/controller.py`: the pure window rule, shared with X2.
- `switch.py:21`: `TRANSIENT_BLOCKERS`.
- `__init__.py:141-147`: `monitor_failed` joins the issue keys deleted at removal.

**Texts.**
- `entity.binary_sensor.alarm_monitor_failed`: "Control: the monitor keeps failing" / "Sterowanie: monitor stale zawodzi".
- `exceptions.blocked_monitor_failed`:
  - en: "The plugin's monitor has failed for 5 minutes, so control handed the boiler back; it resumes on its own once the monitor works again. Check the log. Other reasons: {others}."
  - pl: "Monitor wtyczki zawodzi od 5 minut, więc sterowanie oddało kocioł; wróci samo, gdy monitor znów zadziała. Sprawdź log. Inne powody: {others}."
- `issues.monitor_failed`:
  - en title: "Control handed the boiler back: the plugin's monitor keeps failing".
  - en description: "The plugin's monitor has failed for 5 minutes — an error in the plugin; the log has the details — so control handed the boiler back. It resumes by itself once the monitor works again. Meanwhile a thermostat or the boiler's own control heats where your installation has one; where a hand-back stops heating, the boiler does not heat until control resumes."
  - pl title: "Sterowanie oddało kocioł: monitor wtyczki stale zawodzi".
  - pl description: "Monitor wtyczki zawodzi od 5 minut — to błąd we wtyczce; szczegóły są w logu — więc sterowanie oddało kocioł. Wróci samo, gdy monitor znów zadziała. Do tego czasu grzeje termostat albo własne sterowanie kotła, jeśli instalacja je ma; tam, gdzie oddanie zatrzymuje grzanie, kocioł nie grzeje, dopóki sterowanie nie wróci."
- `issues.monitor_recovered`:
  - en title: "The plugin's monitor failed for a while; control has resumed".
  - en description: "The plugin's monitor failed from {since} to {until}, so control handed the boiler back meanwhile. The monitor works again and control has resumed by itself. The log has the error; if this happens again, report it."
  - pl title: "Monitor wtyczki przez pewien czas zawodził; sterowanie wróciło".
  - pl description: "Monitor wtyczki zawodził od {since} do {until}, więc w tym czasie sterowanie oddało kocioł. Monitor znów działa i sterowanie wróciło samo. Błąd jest w logu; jeśli to się powtórzy, zgłoś go."

**Missing data.**
- Monitor data stale: its alarms are ignored.
- `coordinator.data` is `None` only before the first refresh, which setup requires.
- The monitor fails before control ever took the boiler: the blocker keeps control from starting, and nothing is written.
- No refresh outcome yet in the window (just after the start): nothing counts as failed.

**Do not.**
- Do not tie control entities to the monitor's success.
- Do not log a lasting error at every refresh or step.
- Do not act on stale monitor alarms.
- Do not resume on a single good refresh.

**Open for the user.** None. The user decided on 2026-09-27 (answer I): a monitor that keeps failing for 5 minutes hands the boiler back, and control comes back on its own once the monitor works again, like after a lost boiler link, with an information note — not only after the user switches it off and on, as after an internal error. The window and recovery times go to K4.

---

### V7 — stopping with an alarm (S-10, S-57, S-11)

**Goal and done-when.** Goal: control never stops heating silently.
- A blocker that ends a session holding the boiler, where the hand-back stops heating, raises a repair issue.
- After a hand-back the switch says who keeps frost protection, and an alarm rises when a room is near freezing while handed back.
- An outside change always makes the plugin step aside: the whole safe hand-back (the user's answer H of 2026-09-27), latched and stored, with a repair issue. The reaction "information" goes.

Decision 6's classes (lost command, ignored from the start, clipped, another controller) are built in X1. V7 changes only what happens once a guard reports another controller. Done when the tests below pass, including the negatives.

**Read first.**
- Plan: decision 6 ("Another controller"); decision 7; the V7 row.
- The user's answers of 2026-09-27:
  - C–E: a single fall-back to the value from before the plugin with no visible trace of an outage is a lost command; a second within an hour that no send explains counts as another controller; a relay switched while it stayed available counts as another controller. These are X1's and X8's classes; V7 reacts to what they classify;
  - H: the step-aside makes the whole safe hand-back, even over the other controller's value, then the latch.
- Review: S-10, S-11 (§3.2), S-57 (§3.3), their section 4 proposals; Appendix E question 2.
- Research:
  - `research/2026-09-26-q4-decision-6-outside-change-matrix.md`: rows A1, A6, B2; §5 W3; "Decided by the user";
  - `research/2026-09-26-q4-decision-7-alarms.md`: "Decided by the user";
  - `research/2026-09-27-fresh-session-test.md`: "### V7".
- Code:
  - `control.py:11-16, 147-165, 485-506, 605-616, 666-686, 856-864`
  - `core/loop.py:1-9, 79-83, 101-108`
  - `core/limits.py:85-122`
  - `control_config.py:118-122, 157-160, 299-314`
  - `config_flow.py:403-408, 569-582`
  - `switch.py:58-69`
  - `tests/integration/test_control.py:534-550`
  - `__init__.py:141-147`

**Order of work.**
1. Tests:
   1. `test_a_blocker_that_stops_a_stand_alone_session_raises_an_issue`.
      - Given: stand-alone gateway, controlling.
      - When: `vt_central_boiler_active` appears.
      - Then: a hand-back; 60 s later the `control_stopped_heating_<id>` issue, severity error; it is deleted when control resumes.
      - Negatives: no issue for `ha_starting`, `control_error` or `monitor_failed` (V6 raises its own), with the "thermostat takes over" effect, or when the blocker clears within 60 s.
   2. `test_the_switch_says_who_keeps_frost_protection`.
      - `frost_protection_by` is `plugin` while controlling, `boiler` after a stand-alone hand-back, `thermostat` with a thermostat, `device` for "device decides" and for "own control" (`OWN_CONTROL_RESUMES`, once Y1 adds it).
   3. `test_handed_back_in_frost_raises_an_alarm`.
      - Given: stand-alone; control off; a watched zone at 4 °C.
      - Then: at the next step `handed_back_in_frost` is on; at 7.5 °C it is off.
      - Negatives: the zone temperature unknown, so off; with a thermostat, never; while controlling, off.
      - Core part: a pure function in `tests/core/test_limits.py`.
   4. Replaces `test_control.py:534` with `test_an_outside_change_always_steps_aside`.
      - Given: a stored reaction `{"outside_change": "info"}`.
      - When: another controller holds 60 °C after the one rewrite.
      - Then: a latch, the whole safe hand-back, the `control_latched_<id>` issue (error with a stand-alone gateway, warning with a thermostat), and the latch after a restart; off, then on, clears it. With `return_after_outside_change` on, X1's return by itself also clears it (X1's test).
   5. `test_stepping_aside_makes_the_whole_safe_hand_back` (the user's answer H of 2026-09-27).
      - Given: a held setpoint entity; another controller holds 60 °C after the one rewrite.
      - Then: at the step-aside the setpoint entity gets the lowest water temperature over the other controller's 60 °C, the heating switch goes on where the effect allows, then the release; on a gateway `CS=<lowest>`, `CH=1`, `CS=0`. When the other controller writes 60 °C again, V5 judges it taken by another controller: no retry every minute, and no `hand_back_taken_by_other` issue beside `control_latched`.
   6. `test_the_form_no_longer_offers_a_reaction_to_outside_changes`.
2. Implement the rules below, and update `core/loop.py`'s and `control.py`'s docstrings and SCOPE's resume table text in Q1.

**Rules and values.**
- S-10: when a blocker releases a session that was controlling, where the effect is "heating stops" (`HEATING_STOPS`, and X8's `RELAY_RESTS_OFF` once it exists), and the blocker still holds 60 s later (provisional, K4; longer than a VT reload, short enough to warn):
  - the repair issue `control_stopped_heating_<entry_id>` is raised (severity error, as the hand-back stops heating — the same level rule as every hand-back notice; not fixable, not persistent);
  - any blocker counts except `ha_starting`, `control_error` (it has its own alarm) and `monitor_failed` (V6 raises its own issue);
  - the issue is deleted when control controls again, when the user switches control off, or on unload.
- S-57, who keeps frost protection: the switch attribute `frost_protection_by` is `plugin` while the session controls, and otherwise follows the effect: `thermostat` ("thermostat takes over"), `boiler` ("heating stops", and X8's `RELAY_RESTS_OFF`) or `device` ("device decides", and — once Y1 and X8 add them — `OWN_CONTROL_RESUMES` and `RELAY_RESTS_ON`).
- S-57, the alarm: `ControlAlarm.HANDED_BACK_IN_FROST` is on when:
  - the effect is "heating stops" (X8's `RELAY_RESTS_OFF` included);
  - the unit does not control (for any reason, a switch-off included);
  - and a watched zone (`watched_temperatures`, every zone or the picked one, `core/limits.py:99-111`) reads below the frost limit (option, default 5 °C): the alarm rises at the next step (provisional, K4).
  - It goes off when every watched zone with a known temperature is at or above the frost release (option, default 7 °C), or when control controls again.
  - It is information only: it never starts heating (principle 12). The rule is a pure function in `core/limits.py`.
- S-11, outside change:
  - `outside_change` always hands back: `ControlOptions.reaction("outside_change")` returns `HAND_BACK` whatever is stored (`control_config.py:157-160`), so a stored "info" is neutralised;
  - it leaves `REACTION_ALARMS` (`config_flow.py:403-408`);
  - after the one rewrite, the guard's block leads at the next step to a latch and the whole safe hand-back (V5); the latch is stored, as today;
  - the repair issue `control_latched_<entry_id>` is raised when the latch is set, and again at start while a stored latch holds; severity error where the hand-back effect is "heating stops" (stand-alone, a value declared "heating stops", X8's relay left "off"), else warning; not fixable. It is deleted when the latch clears: off, then on, or X1's optional return by itself (`return_after_outside_change`, off by default; relays do not have it). X1 raises this same issue for its step-aside; Y1 extends it to every alarm latch, with the text naming the alarm (placeholder `{alarm}`);
  - "writes stopped" remains only for the step between the block and the latch.
- The step-aside makes the whole safe hand-back (the user's answer H of 2026-09-27; decision 6: "a safe hand-back and a notification"): the lowest water temperature, heating on where the boiler returns to a thermostat or its own control, then the release, on every target — the one the other controller holds included, although this briefly writes over its value. A relay is set once to its rest state and then left alone (answer L; X8).
  - The hand-back write already passes a blocked guard (`control.py:856-858`; X1, T-19), so no target is skipped and `LoopOutput` needs no skip set.
  - Afterwards V5's rules judge each target: a target the other controller writes again counts as taken by another controller, with no retry every minute (decision "Safe hand-back": "when another controller already holds the target, the hand-back counts as done").
  - Control then stays latched, stored through reloads and restarts, until the user switches it off and on, or X1's return by itself brings it back where that option is on (not for relays).
- Values: 60 s and "at the next step" (provisional, K4); frost limit and release are the existing options.

**Code to change.**
- `control.py`:
  - 147-165: the new alarm; `_KEPT_ALARMS` unchanged;
  - 485-506 and 605-616: follow a blocker release for S-10;
  - 666-686: the frost-while-handed-back check;
  - 856-864: the latch's hand-back is V5's whole safe hand-back, with nothing skipped;
  - 11-16: the docstring.
- `core/loop.py:1-9, 79-83, 101-108`: the docstring (no skip set, the user's answer H).
- `control_config.py:118-122, 157-160`.
- `config_flow.py:403-408`.
- `switch.py:58-69`: the attribute.
- `core/limits.py`: the pure frost check.
- `__init__.py:141-147`: `control_stopped_heating` and `control_latched` join the issue keys deleted at removal.

**Texts.**
- `issues.control_stopped_heating`:
  - en title: "Control stopped and the boiler does not heat".
  - en description: "Control handed the boiler back because something now blocks it (the control switch lists what). With this installation a hand-back stops heating: the boiler heats again when control resumes once the blocker is gone, or when you return it to its own control. Frost protection now rests on the boiler's own, if it has one."
  - pl title: "Sterowanie stanęło, a kocioł nie grzeje".
  - pl description: "Sterowanie oddało kocioł, bo coś je teraz blokuje (przełącznik sterowania pokazuje co). W tej instalacji oddanie zatrzymuje grzanie: kocioł znów grzeje, gdy sterowanie wróci po zniknięciu blokady albo gdy przywrócisz mu własne sterowanie. Ochrona przed mrozem zależy teraz od własnej ochrony kotła, jeśli ją ma."
- `issues.control_latched`:
  - en title: "Control stepped aside: another controller writes to the boiler".
  - en description: "Another controller changed what the plugin writes to the boiler again after the plugin had written its value back once, so the plugin stepped aside and does not fight it. It handed the boiler back safely: first the lowest water temperature, then heating on where a thermostat or the boiler's own control takes over, then the release — this wrote over the other controller's value once, briefly. With a thermostat, the thermostat keeps heating; without one, the boiler heats only under the other controller. To give control back to the plugin, stop the other controller, then switch control off and on. If \"Return by itself after another controller\" is on, control also comes back on its own after an hour in which nothing else wrote to the boiler (not for relays)."
  - pl title: "Sterowanie ustąpiło: do kotła pisze inny sterownik".
  - pl description: "Inny sterownik znów zmienił to, co wtyczka zapisuje do kotła, po tym jak wtyczka raz przywróciła swoją wartość, więc wtyczka ustąpiła i z nim nie walczy. Oddała kocioł bezpiecznie: najpierw najniższa temperatura wody, potem włączone grzanie tam, gdzie przejmuje termostat albo własne sterowanie kotła, potem zwolnienie — przez to raz, na chwilę, nadpisała wartość innego sterownika. Z termostatem grzeje dalej termostat; bez niego kocioł grzeje tylko pod innym sterownikiem. Aby oddać sterowanie wtyczce, zatrzymaj inny sterownik, a potem wyłącz i włącz sterowanie. Jeśli włączono „Powrót po innym sterowniku bez udziału użytkownika”, sterowanie wraca też samo po godzinie, w której nic innego nie pisało do kotła (nie dotyczy przekaźników)."
- `entity.binary_sensor.alarm_handed_back_in_frost`: "Control: handed back while a room is near freezing" / "Sterowanie: oddane, a w pomieszczeniu grozi mróz".
- `entity.switch.control.state_attributes.frost_protection_by`: name "Frost protection by" / "Ochrona przed mrozem przez". States:

  | State | en | pl |
  |---|---|---|
  | `plugin` | The plugin | Wtyczka |
  | `thermostat` | The thermostat | Termostat |
  | `boiler` | The boiler's own, if it has one | Własna ochrona kotła, jeśli ją ma |
  | `device` | The boiler's or the device's own control | Własne sterowanie kotła lub urządzenia |

- Removed, en and pl: `options.step.control_alarms.data.outside_change` and `data_description.outside_change`. The step's `description` gains: "Another controller writing to the boiler always makes the plugin step aside." / "Inny sterownik piszący do kotła zawsze sprawia, że wtyczka ustępuje."

**Missing data.**
- Zone temperature unknown or implausible: not counted.
- No watched zone known: the alarm stays off, and `unknown_zones` on `control_state` shows why (the "inactive, names what it lacks" display is Y4's).
- The effect unknown (no topology): control is blocked anyway; no issue, no alarm.
- The guard's block state lost at a restart: the stored latch keeps control off, so there is nothing to write.

**Do not.**
- Do not keep "information" for an outside change.
- Do not fight the other controller: after the one whole safe hand-back at the step-aside, no rewrite and no retry every minute against a target it holds (V5's taken-by-other).
- Do not skip a part of the step-aside's hand-back because another controller holds its target (the user's answer H).
- Do not switch VT's mode.
- Do not start heating for `handed_back_in_frost`.
- Do not raise `control_stopped_heating` for `ha_starting`, `control_error` or `monitor_failed`, or with a thermostat.

**Open for the user.** None. The user decided on 2026-09-27 (answer H): when the plugin steps aside because another controller keeps writing, it makes the whole safe hand-back — the lowest water temperature, heating on where the boiler returns to a thermostat or its own control, then the release — even though this briefly writes over the other controller's value; control then stays latched, stored through reloads and restarts, until the user switches it off and on, or returns by itself where that option is on (not for relays). The provisional values go to K4.

---

### Fixed values of phase V (for S-37's list)

| Value | Number | Reason | Step | Status |
|---|---|---|---|---|
| Control store | key `vtherm_smart_boiler.<entry_id>.control`, version 1, atomic | the control state apart from the monitor's data | V1 | technical |
| Last command saved at once on a setpoint move of | 1.0 K | enough to restore; no write at every ramp step | V3 | provisional, K4 |
| Wait for the control switch to restore | 60 s | existing, `control.py:87` | V3 | existing |
| SmartPI resume follow-up | every 60 s, at most one day | existing, `core/learning.py` | V3 | existing |
| Hand-back retry | 60 s | existing, `control.py:84` | V4 | existing |
| Wait for a late echo at the stop | 5 s | ESPHome and MQTT report late (P-50) | V4 | provisional, K4 (Q3) |
| Whole stop hand-back; each write at the stop | 15 s; 4 s | HA's 20 s stage-1 budget (`core.py:111`) | V4 | provisional, K4 (Q3) |
| Start grace for an owed hand-back | 60 s | devices come back after HA starts (P-50) | V4 | provisional, K4 (Q3) |
| OTGW release window | 60 s | the override's own lapse | V4 | provisional, K4 |
| Wait between the hand-back's parts | none: one after another at once | a wait could stall a hand-back, the stop's included | V5 | provisional, K4 |
| Release tolerance | 0.5 K | existing, `control.py:929` | V5 | existing |
| Held target unconfirmed, then an alarm | 10 s (one step) | "an alarm at once" (decision) | V5 | provisional, K4 |
| Timeout hand-back without release, then an alarm | 3 min | an earlier alarm is the cautious choice; the same value as Q1's safe hand-back | V5 | provisional, K4 |
| Taken by another controller, value target | 2 checks 60 s apart; 3 over 120 s with hot water unknown; not within 120 s after a draw | W3 and W6 of the decision 6 note | V5 | provisional, K4 |
| Taken by another controller, two-valued target | the hand-back state read back once, then changed with no trace of an outage (X1's 5 min window) | the decision 6 note's "Missing" item; Q1 matrix row M12 | V5 | provisional, K4 |
| External switch, expiring | turned on every 30 s | the keep-alive, `control_config.py:30` | V5 | existing value |
| "Off" against an own-control hand-back value | 0.5 K | S-49 | V5 | plan |
| Monitor failure before a hand-back | 300 s of failed refreshes within 600 s | the user's answer I (5 min); the window as X2's boiler link | V6 | 300 s decided; 600 s provisional, K4 |
| Monitor back, control resumes | 60 s without a failed refresh | as X2's link recovery (the user's answer I: "like the lost boiler link") | V6 | provisional, K4 |
| Blocker stopping heating, then an issue | 60 s | longer than a VT reload | V7 | provisional, K4 |
| Handed back while near freezing | at the next step below the frost limit (5 °C default); off at or above the release (7 °C default) | S-57; an alarm at once is the cautious choice | V7 | provisional, K4 |

## Common to X1–X4

- Line numbers are those of commit `d545869`; after phase V they drift, so find cited code with `git show d545869:<path>`.
- Where a decision in `docs/plan-0.2.2.md`, or one of the user's answers A–O of 2026-09-27 (recorded in the plan), differs from a research note or from the review's proposal or §6 "Then", the decision wins. The §6 test is kept and its "Then" is changed as each step below says.
- Phases V and X may run while Q1's `SCOPE.md` diff waits. Until Q1 is accepted, the plan's decisions win over `SCOPE.md`, and each commit message names the SCOPE sentence it departs from.
- New test cases go into the existing test files (`tests/core/test_*.py`, `tests/integration/test_*.py`). A new test file in `tests/core/` or `tests/integration/` is inside the agreed layout. A new module in `core/` is inside the layout (`core/ pure logic`). A new Home Assistant platform file is not, except `button.py` for the "Reset comfort correction" button, which the user approved on 2026-09-27 (answer J; X4).
- "(provisional, K4)" means the value or rule is this file's most cautious choice. It is kept in one named constant or function and listed for S-37 in its step; Q1's fixed-values table (S-37) and the K4 agenda list every one of them. The user confirms or changes it at K4.
- A step is ✅ only when every scenario of each of its problems passes (the review row, its §6 test, section 4's proposal as changed by the decisions), and every new mechanism has a negative test with a `None`, missing or unavailable input. A remainder goes to "Open after 0.2.2" by name. The ✅ mark and such a remainder are committed without waiting for consent, and the step's report shows the diff (answer B of 2026-09-27).

---

### X1 — the guards and decision 6's four classes

**Goal and done-when.** The write guards keep their memory for the whole session. The one-rewrite memory lasts for its day. Every change the read-back shows falls into one of decision 6's classes, with one pure classification function and one reaction table: lost command, ignored from the start, clipped, another controller. The heating switch follows the same classes as the setpoint (answer E, S-40). "Ignored" is tracked for each guard separately. The heating switch's "off" ignored from the start blocks control and hands the boiler back, with an alarm and a blocker kept until the user switches control off and on (answer O). Another controller makes the plugin step aside with the full safe hand-back and a latch (answer H). A read-back that stays missing while the plugin writes is reported, never judged. A setpoint entity's step and "off" are checked. Held values are sent again after the device returns and every 5 min. The external-control switch is watched. The step is done when:
- the scenarios of P-06, P-07, P-09, P-15, P-43, P-48 and P-98 pass;
- so do those of S-11, S-13, S-40 and S-48, and the rows of Q1's matrix of outside changes that name X1 (M1–M11, M14, M15, M20);
- T-01, T-02, T-04, T-19, T-47, T-49 and T-55 pass, with their "Then" changed as below;
- every class has a negative test with a `None` read-back, no outage information and no thermostat field.

**Read first.**
- Plan: decision 6, with the user's answers E and H of 2026-09-27 written into it:
  - a single fall-back to the value from before the plugin without a trace of an outage is a lost command; a second one within 1 hour that no send explains is another controller; a send explains a fall-back when the fall-back comes before the plugin's latest send was read back as its value, or within 120 s of a send of a new value;
  - a fall-back after every send from the start of the session stays "ignored from the start";
  - the heating switch follows the same classes as the setpoint (S-40);
  - stepping aside is the full safe hand-back, latched and stored, until the user switches control off and on, or the return by itself comes (not for relays).
- Plan: decisions 6 and 11 with the user's answer O of 2026-09-27: where the boiler ignores "heating off" from the start of the session (the heating switch's "off" ignored from the start), control is blocked and the boiler handed back, with an alarm, like an installation without a working heating switch; a blocker names the reason until the user switches control off and on after fixing it (X5.21 adds the blocker's text).
- Plan: "On/off control", answers C and D (a relay switched while it stayed available is another controller; one found in another state after a power or link loss is sent the command again). They are built for relays in X8; the external-control switch here tells its cases apart the same way.
- Plan: decision 7 (write_ignored's reaction, which Y1 restricts), the Terms "Lost command" and "Safe hand-back", X1's row, and the finding at `core/guards.py:319-335`.
- Review rows:
  - problems: P-06, P-07, P-09, P-15, P-43, P-48, P-98;
  - specification: S-11, S-13, S-40, S-48;
  - §6 tests: T-01, T-02, T-04, T-19, T-47, T-49, T-55;
  - Appendix B, the state table; review question 2.
- `research/2026-09-26-q4-decision-6-outside-change-matrix.md`:
  - use: §1 (today's rules), rows A1–E10 of §4 (the scenarios to test), and the verifier's "Corrections", "Missing" and "Safety concerns";
  - do not use: §5 "3 drops an hour → hand back" and "the cap becomes the upper limit", which were rejected.
- `research/2026-09-27-fresh-session-test.md`, "### X1".
- `research/2026-09-27-plan-0.2.2-checks.md`, the decision-6 items.
- This file: Q1's matrix of outside changes (rows M1–M22), V5 (the safe hand-back) and V7 (the one latch issue `control_latched_<entry_id>`).
- Code:
  - `core/guards.py` (all; `GuardState` at 101-114, `plan_write` at 153-211, `_follow_read_back` at 221-252, `_dropped` at 268-274, `_write` at 296-339);
  - `core/loop.py:71-125`;
  - `control.py` at 160-165, 312-373, 556-561, 586-664, 740-782, 800-852, 974-985;
  - `control_config.py` at 118-122, 157-160, 251-270, 317-374;
  - `transport/writers.py:69-88, 141-214`;
  - `config_flow.py` at 403-408, 437-475, 549-582, 639-642, 1312-1337, 1420-1464.

**Order of work.**
1. Core tests in `tests/core/test_guards.py`, written first. Each takes a `None` read-back variant.
   - `test_a_confirmed_value_that_falls_back_after_an_outage_is_a_lost_command`
     - Given: confirmed 45, held past the start phase; baseline 0; `outage_at` 4 min before.
     - When: the read-back shows 0.
     - Then: RESEND at once, a loss is counted, no event.
     - Negative: `outage_at` 6 min before → no trace; the trace-less rows apply.
   - `test_a_first_fall_back_without_a_trace_is_a_lost_command`
     - Given: confirmed 45; no trace.
     - When: the read-back shows 0.
     - Then: RESEND, a trace-less fall-back is counted, no event.
   - `test_a_second_fall_back_within_an_hour_without_a_trace_is_another_controller`
     - Given: as above, resent and confirmed.
     - When: a second trace-less fall-back comes 20 min later, not explained by a send.
     - Then: REWRITE once; a third within 24 h → OUTSIDE_CHANGE and a block.
   - `test_two_fall_backs_more_than_an_hour_apart_stay_lost_commands`: the same with a 70 min gap → RESEND both times, no event.
   - `test_a_fall_back_a_send_explains_is_not_another_controller`
     - Given: 45 confirmed.
     - When: 50 is sent and the read-back falls to 0 within 120 s, twice in 20 min; and, separately, 50 is sent, the read-back still shows 45 and then falls to 0 before it ever shows 50.
     - Then: RESEND each time; never another controller.
     - Negative: a fall-back just after a keep-alive or a resend of the same value is not explained; the second such within 1 h → REWRITE.
   - `test_frequent_losses_raise_a_warning_never_a_hold`: 3 losses within 24 h → the loss-warning flag is set; writing goes on; the flag clears after 24 h without a loss. Negative: 2 losses in 24 h → off.
   - `test_a_fall_back_after_every_send_from_the_start_is_ignored_from_the_start`
     - Given: each of the session's first 3 sends is read back for less than 120 s, then falls back to the baseline.
     - Then: RESEND after the first and the second; IGNORED once after the third; no further writes to that target, keep-alives included; no OUTSIDE_CHANGE.
   - `test_a_baseline_held_from_the_first_send_is_ignored_not_another_controller`: the read-back stays at the pre-session value after each of the first 3 sends (each sent 120 s after the one before) → IGNORED, no REWRITE.
   - `test_ignored_from_the_start_keeps_the_other_target_and_frost`: the setpoint ignored from the start → the heating switch is still written, and frost heating still switches it on; no block, no latch. A new session tries the setpoint again.
   - `test_an_attempt_with_an_outage_does_not_count_toward_ignored` (provisional, K4): a trace of an outage within an attempt's 120 s → sent again, not counted; 3 counted failed attempts are still needed.
   - `test_a_lower_value_whatever_the_plugin_sends_is_clipped`: 45, then 50 sent; the read-back is 40 throughout → confirmation `clipped`, no event, no REWRITE. The clip ends once a read-back shows a sent value. Negative: one sent value only (a flat setpoint) → not clipped; the steady row applies (REWRITE).
   - `test_a_clip_is_never_learned_as_a_limit`: while clipped, no curve limit, lowest or highest water temperature changes, and the comfort correction does not rise (X4).
   - `test_a_steady_other_value_for_two_steps_is_another_controller`: after confirmation, 60 at 2 consecutive steps → REWRITE; again within 24 h → block.
   - `test_a_one_step_difference_is_not_judged`: 60 for one step, then 45 → nothing.
   - `test_another_controller_is_judged_while_the_plugins_value_keeps_changing`
     - Given: the desired value rises 0.2 K each step.
     - When: the read-back holds 60 from the first send.
     - Then: REWRITE at the first send + 120 s; later changes neither delay nor clear it.
   - `test_another_controller_is_judged_when_the_read_back_was_unknown_at_the_send`: read-back `None` at the send, then 60 steadily → REWRITE at the send + 120 s, not only IGNORED.
   - `test_a_failed_rewrite_is_judged_after_a_new_value_too`: REWRITE, then a new value, and the read-back holds the foreign value → block at the rewrite + 120 s.
   - `test_heating_switched_back_without_a_trace_is_first_a_lost_command` (S-40, answer E): after the start phase, the echo flips back to its baseline while it stayed available → RESEND, one trace-less fall-back counted; a second flip within 1 h that no send explains → REWRITE; the next within 24 h → block.
   - `test_heating_switched_away_from_its_baseline_is_another_controller`: baseline "on", the plugin commands "on", the echo shows "off" at 2 consecutive steps with no trace → REWRITE; again within 24 h → block. Negative: baseline unknown → the same.
   - `test_heating_switched_back_after_an_outage_is_a_lost_command`: echo unavailable, then back at its pre-session state → RESEND, no event.
   - `test_a_gateway_reset_loses_both_overrides_as_one_lost_command`: S at baseline 0 and H at its baseline in the same step (or the next), no other trace → both RESEND, one loss for the warning, each guard's first trace-less fall-back, no event.
   - `test_a_held_target_device_restart_is_not_an_outside_change` (T-47)
     - Given: held; pre-session 0; confirmed 45.
     - When: the target is unavailable, then back with 40, twice in a day.
     - Then: RESEND each time; no OUTSIDE_CHANGE, no block.
   - `test_held_values_are_sent_again_every_five_minutes_without_an_echo`: held, no read-back, value unchanged → a repeat every 300 s, and one at once when the target returns from unavailable.
   - `test_a_draw_is_not_judged` (provisional, K4): with `dhw=True`, and for 120 s after it, a read-back change is not judged. Negative: `dhw=None` → judged.
   - `test_the_thermostats_own_value_after_an_outage_is_a_lost_command`: with the thermostat's value 38 and a trace, a read-back of 38 → RESEND. Negative: no thermostat value given → as without the field.
   - `test_an_unknown_read_back_is_not_judged_and_informs_after_five_minutes` (M11): Given writes going on. When the read-back is unknown for 5 min. Then `confirmation_missing` is on, nothing judged, no hand-back; it clears at the first known read-back. Negative: 4 min 50 s → off.
2. Core tests in `tests/core/test_loop.py` and `tests/core/test_controller.py`.
   - `test_the_guards_keep_their_memory_across_a_hand_back_in_a_session` (T-01, core half)
     - Given: rewritten at t0.
     - When: a stale-link hand-back, the resume, and another outside change the same day.
     - Then: no second REWRITE; block → OUTSIDE_CHANGE. This replaces `tests/core/test_loop.py:55`.
   - `test_a_hand_back_passes_while_a_guard_is_blocked` (T-19)
     - Given: the setpoint guard is blocked.
     - When: a step with `enabled=False`, and separately a step with a hand-back alarm.
     - Then: `hand_back` is true and no setpoint is written. Block, baseline and `rewritten_at` are kept; the per-send fields are reset.
   - `test_an_alarm_during_a_blocker_still_latches` (T-49): a step with a transient blocker and a hand-back alarm → `latched` with `latched_by`; the next step, blocker gone → HANDED_BACK.
3. Integration tests in `tests/integration/test_control.py`.
   - `test_the_one_rewrite_is_remembered_across_a_clean_reload` (P-06, T-01 integration half)
     - Given: one rewrite.
     - When: the entry reloads cleanly and another controller writes within the day.
     - Then: no second rewrite; the plugin steps aside with the full safe hand-back (the lowest water temperature, heating on where a thermostat or the boiler's own control takes over, then the release), the latch and the repair issue `control_latched`.
   - `test_an_ignored_heating_switch_raises_write_ignored` (T-04)
     - Given: OTGW with `ch_confirmed_entity`; setpoint confirmed.
     - When: the CH echo never follows CH=0 for more than 120 s after each of the session's first 3 sends.
     - Then (answer O): `alarm_write_ignored` is on with `targets: ["heating"]`; at the next step control is blocked and the boiler handed back (the safe hand-back, V5: the lowest water temperature, `CH=1`, then `CS=0`), whatever alarm reaction is stored and whatever the hand-back effect; `latched_by` holds `heating_off_ignored`, V7's `control_latched_<entry_id>` names it, and the blocker `heating_off_ignored` is listed. The latch survives a reload and a restart, and clears only when control is switched off and on.
     - Negative: the CH echo never follows CH=1 while it stays off (only "on" ignored) → as decision 6 says: `write_ignored` on, no block, no latch, the setpoint still written.
   - `test_write_ignored_clears_per_guard`: the heating switch's "on" ignored from the start (the switch stays off; its "off" is never refused, so answer O does not apply) and the setpoint confirmed → the alarm stays on with `targets: ["heating"]`; the setpoint's confirmation never clears it. Control switched off and on (a new session), and the heating value then holds 120 s → off. Negative: a path without a heating target → the setpoint alone decides.
   - `test_heating_off_ignored_from_the_start_blocks_and_hands_back` (answer O; entity path with a held `ch_entity`): the switch stays on after each of the session's first 3 sends of "off" → the hand-back and the blocker as in T-04 above; switching control off and on clears the blocker and a new session tries the switch again. Negatives: the switch unavailable within an attempt (a trace, not counted); a read-back `None` throughout (nothing judged, no blocker); the switch refusing "off" after it once took "off" in this session (not "from the start": decision 6's other classes judge it).
   - `test_a_stored_information_reaction_for_outside_change_is_neutralised`: options `alarm_reactions: {"outside_change": "info"}` → another controller → the plugin steps aside.
   - `test_the_external_control_switch_switched_off_steps_aside_without_a_rewrite`: the switch goes off while it stayed available (no trace within 5 min) → no `turn_on`; OUTSIDE_CHANGE, the full safe hand-back (its release counts as done), latch, the repair issue `control_latched`.
   - `test_the_external_control_switch_off_after_its_device_restart_is_switched_on_again`: unavailable within the 5 min before, then off → `turn_on` at the next step, counted as a loss, no alarm. Negative: unavailable 6 min before → another controller.
   - `test_the_return_by_itself_after_an_hour_without_a_foreign_value`: option on; the plugin stepped aside; 60 min with the read-back only at the hand-back state → control resumes as a new session; the latch and `control_latched` clear; `rewritten_at` stays. With the option off it stays aside after 2 h. Negative: an unknown read-back for the hour → no return.
   - `test_setpoint_step_over_1k_is_refused_or_compared_after_rounding` (T-55)
     - `input_number` with step 5 → form error `setpoint_step_too_coarse`.
     - The step raised to 5 after setup → runtime blocker `setpoint_step_too_coarse`.
     - Step 0.5 with `min` 0.25 and `hard_max` 70 → 70 is sent as 69.75. The read-back 69.75 confirms, with no false "ignored"; the hand-back value is checked after rounding.
     - A °F entity with step 1 °F is accepted (0.56 K), with step 2 °F refused (1.1 K); its grid is applied in °F and the guard compares in °C.
   - `test_off_must_be_at_least_1k_below_the_hard_minimum` (P-43): off 24.5, hard minimum 25 → blocker and form error `off_setpoint_not_below_hard_min`; off 24 → allowed.
   - `test_the_return_option_needs_a_second_confirmation` (flow): turning it on without the tick → error `return_needs_confirmation`.
   - `test_the_step_aside_issue_is_an_error_where_heating_stops`: stand-alone gateway → `control_latched` at severity error; with a thermostat → warning.
   - `test_confirmation_missing_never_hands_back`: the read-back unavailable for 10 min while the link stays fresh → `confirmation_missing` on, control goes on, no hand-back.
4. Rewrite the tests that pin the old behaviour, each with the decision that changes it (decision 6, answers E and H):
   - `tests/core/test_loop.py:55` → keeps memory;
   - `tests/integration/test_control.py:496` → ignored from the start (write_ignored, no hand-back; the target is not written again this session);
   - `:513` → in the start phase (the value never held 120 s), each drop is sent again at once, and the third makes it ignored from the start (write_ignored on, no outside change, control stays on); a first trace-less drop after the start phase is a lost command, and later ones follow the rows below;
   - `:534` → no "information" reaction: the plugin steps aside with the full safe hand-back;
   - `:2128` → the CH flip away from its baseline is written again once, then the plugin steps aside with the full safe hand-back, whose writes now begin with the lowest water temperature (V5); add the case of a flip back to the baseline without a trace, which is first a lost command;
   - `tests/integration/test_acceptance.py:363` → ignored from the start, control stays on;
   - `:484` → unchanged in outcome; check it still steps aside, now with the full safe hand-back.
5. Implement in core, then `control.py`, then `control_config.py` and `config_flow.py`, then the translations. Run `python -m pytest -q` and `ruff check .` through `scripts/env.sh`, then commit.

**Rules and values.**

The fall-back set of a target:
- its baseline — the first known read-back of the session that is not within 0.5 K (for on/off: not equal) of a value the plugin sent in this session or of the last command stored by V3 (P-07);
- for the setpoint, where the thermostat field is set: the thermostat's own current value.

A trace of an outage exists when, within the 5 min before (provisional, K4), either of these happened:
- the target entity, its read-back, or another entity of the same device or gateway that the plugin reads was unavailable, unknown or missing;
- a restart of that gateway or device was seen.

Which signal shows a restart on each path is to be settled by Q3 (Q3.7); until then a restart counts only through the unavailability it causes. A failed write is not a trace: it has its own row below. The boiler link's freshness is X2's, not a trace.

A send explains a fall-back when the fall-back comes before the plugin's latest send was read back as its value, or within 120 s of a send of a new value (a CHANGE, not a keep-alive or resend) (decided, answer E). Such a fall-back is judged as a lost command or as ignored from the start, never as another controller.

The start phase of a target runs from the session's first send until the read-back has held a sent value (within 0.5 K; for on/off: equal) for 120 s. In it:
- every send (a change or a resend) starts an attempt; keep-alives and changes inside an attempt's 120 s belong to it;
- an attempt fails when the read-back is in the fall-back set — it fell back, or it has not shown the plugin's value 120 s after the send;
- a failed attempt is sent again at once (RESEND), which starts the next attempt;
- an attempt with a trace of an outage in it does not count (provisional, K4);
- a fall-back is never judged as another controller.

A joint fall-back — the setpoint and the heating switch back in their fall-back sets in the same step or the next (20 s, provisional, K4) — is one loss for the warning; each guard still counts its own trace-less fall-back (the plan's X1 row, answer E).

Classification of each guarded target at every step, in this order (the fixed table of `SCOPE.md` §7 that Q1 writes):

| Read-back | Class | Reaction |
|---|---|---|
| unknown, unavailable or missing | — | nothing is judged; a trace of an outage; after 5 min while the plugin writes, `confirmation_missing` (below) |
| within 0.5 K of the current value, or of a value sent in the last 120 s (on/off: equal) | confirmed | none |
| during a hot-water draw, or within 120 s after one | — | not judged (provisional, K4) |
| the plugin's expiring override silent for more than 60 s, with a mismatch | own lapse | RESEND (as today, `core/guards.py:282-288`) |
| after its own write failed | retry | RESEND, as today |
| held target, first known value after returning from unavailable or unknown | lost command | RESEND, not a rewrite, never an outside change (S-13, T-47) |
| in the start phase: in the fall-back set — fallen back, or still there 120 s after the send | — (a failed attempt) | RESEND at once, starting the next attempt; an attempt with a trace in it does not count |
| in the start phase: the third failed attempt — the read-back never showed the plugin's value for longer than 120 s after each of the session's first 3 sends (back at the baseline, or never shown) (provisional, K4) | ignored from the start | the reaction below |
| after the start phase, in the fall-back set, with a trace | lost command | RESEND at once; one loss counted |
| after the start phase, in the fall-back set, no trace, the first within 1 h or one a send explains | lost command | RESEND; one loss and one trace-less fall-back counted |
| after the start phase, in the fall-back set, no trace, a second within 1 h that no send explains | another controller | the reaction below |
| heating on/off (two values): after the start phase, back to its baseline, no trace | as the fall-back rows above (answer E): the first within 1 h, or one a send explains, is a lost command; a second within 1 h that no send explains is another controller | as those rows |
| heating on/off: after the start phase, in a state that is not its baseline (baseline unknown, or equal to the plugin's value), at 2 consecutive steps | another controller | the reaction below |
| one value, within 0.5 K, lower than every value sent since the first unconfirmed send, across at least 2 sent values at least 1 K apart (provisional, K4) | clipped | no event; shown as `clipped`; writing goes on; the comfort correction does not rise (X4); ends when a read-back shows a sent value again |
| any other value, the same within 0.5 K at 2 consecutive steps (provisional, K4), after a confirmation or not confirmed within 120 s of the first unconfirmed send | another controller | the reaction below |

Reactions:
- **Lost command.** RESEND, no alarm, and the loss is counted (a joint fall-back of both targets is one loss). Three losses within 24 h (provisional, K4) raise the information alarm `commands_lost`, which clears after 24 h without a loss. Never a hold.
- **Ignored from the start.**
  - An IGNORED event, once. `write_ignored` is on for this guard, and the confirmation shows `not_confirmed`.
  - That target is not written again this session, keep-alives included; a hand-back still releases it (V5). The other target and frost heating go on. No block, no latch; control stays on.
  - It is tried again at the next session: after control is switched off and on, or after a restart (provisional, K4).
  - Both targets ignored: nothing is written, and the alarm names both.
  - The heating switch's "off" ignored from the start (answer O): where the heating guard reaches this class with "off" among the values it did not take, the plugin can no longer switch heating off. Control is blocked and the boiler handed back at the next step, with the full safe hand-back (V5) — whatever alarm reaction is stored and whatever the hand-back effect, like an installation without a working heating switch (decision 11). With it: `latched_by: ["heating_off_ignored"]`, stored at once with the other latches (V3) and kept through reloads and restarts; V7's repair issue `control_latched_<entry_id>` naming the cause (Y1 rule 9), at severity error where the hand-back's effect is "heating stops", otherwise warning; and the blocker `heating_off_ignored` in the switch's `blocked_by`, whose text names the reason (X5.21). All clear only when the user switches control off and on; the new session tries the heating switch again. Where only "on" was not taken (the switch stays off), the rules above apply unchanged.
  - Where decision 7's optional reaction "hand back" is set and allowed (Y1), the hand-back follows.
- **Another controller.**
  - The first time: REWRITE once and set `rewritten_at`.
  - A second change of any "another controller" row within 24 h of the rewrite, or the rewrite not confirmed within 120 s → the guard blocks → OUTSIDE_CHANGE.
  - The reaction is fixed, with no choice: at the next step the plugin steps aside with the full safe hand-back (V5, answer H): the water to the lowest water temperature set, heating on where the boiler returns to a thermostat or its own control, then the release — even though this briefly writes over the other controller's value. The parts follow one another at once; each part is tried whatever the others do; the hand-back waits neither for a read-back nor for the water to cool.
  - With it: `latched_by: ["outside_change"]`, and V7's repair issue `control_latched_<entry_id>` — the one issue for every latch — at severity error where the hand-back's effect is "heating stops" (stand-alone, a hand-back value declared "heating stops", a relay left "off"), otherwise warning.
  - It stays aside, stored through reloads and restarts, until the user switches control off and on, or the optional return comes (not for relays).
  - A stored reaction `info` for `outside_change` is read as this fixed reaction. Y1 generalises this to every alarm.
- **Clipped: known limit.** A boiler that clips a setpoint that stays flat cannot show two sent values 1 K apart. Such a clip is judged by the steady-value row as another controller, as today — a known limit, on the K4 list.

Read-back missing while writing (M11):
- A read-back unknown or unavailable for 5 min (provisional, K4) while the plugin writes raises the information alarm `confirmation_missing`, with the attribute `targets`.
- Nothing is judged meanwhile. It is never a hand-back by itself: the boiler link (X2) decides that.
- It clears at the first known read-back.
- On the gateway paths a write with the read-back unavailable fails and is retried each step (`transport/writers.py:228-238`), as today.

Memory:
- Kept across hand-backs inside a session (stale link, blocker, alarm), and reset only when the user switches control off:
  - baseline;
  - block;
  - the counters (trace-less fall-backs, the loss times, the start phase and its attempts);
  - the class "ignored from the start";
  - the clip value.
- Reset at every hand-back: the per-send fields (`written`, `written_at`, `sent_at`, `confirmed_at`, `previous`, `foreign`, `retry`).
- `rewritten_at` of each guard is kept for 24 h through everything: hand-backs, clean and unclean restarts, reloads, and switching control off and on. The last one is provisional, K4.
- Stored at once in the control store (V1): `rewritten_at`, `heating_rewritten_at`, both baselines, and the last trace-less fall-back time of each guard.

Held values:
- "Held" means a target whose write type is declared held: ESPHome, DIYLess and the like, and the OTGW's `CH=` after X6. EMS-ESP's `selflowtemp` is not held: it expires within about a minute and is declared expiring.
- Every held target, the heating switch included, is sent again (kind KEEPALIVE: not a change, not judged) every 300 s (provisional, K4; "every few minutes" is decided), with no echo required.
- It is also sent at the first step after its target returns from unavailable.
- A target ignored from the start gets no keep-alives.
- A relay is not covered here (X8).

External-control switch (the hand-back switch of `HandBack.SWITCH`):
- While the session holds it on, it is read at every step.
- It goes off with a trace — within the 5 min before (provisional, K4), the switch or another entity of the same device that the plugin reads was unavailable, unknown or missing, or a restart of the device was seen → `turn_on` at once, counted as a loss.
- It goes off without a trace (answer C's way of telling the cases apart: a person, an automation or its own button while it stayed available) → OUTSIDE_CHANGE at once, with no rewrite; the plugin steps aside with the full safe hand-back as above, whose release counts as done, as the switch is already off.
- It is not judged in the step that the plugin's own hand-back turns it off.
- During a hand-back, V5's rule for two-valued targets applies: taken by another controller only once the hand-back state was read back and then changed without a trace; before that it stays owed and is retried.

The optional return by itself (`return_after_outside_change`):
- Off by default, advanced, confirmed twice. Not offered on the relay path (X8 hides it; answer H).
- After the plugin stepped aside for another controller, control resumes by itself once the read-backs have shown, for 1 h without a break, only the hand-back state (for a gateway with an OpenTherm thermostat, also the thermostat's own value where that field is set).
- An unknown read-back breaks the hour.
- Without the thermostat field, a thermostat's moving CS never goes quiet, so the return never comes. The option text says so.
- The return starts a new session. It clears the latch and the repair issue. `rewritten_at` stays.

`write_ignored`:
- On while any guard is in the class "ignored from the start" (a relay's own case: X8).
- Off when none is: at the next session, or once the guard's target holds a sent value for 120 s. It is computed from both guard states at every step (P-09), with the attribute `targets`; a guard without a target contributes nothing.
- Its reaction is looked up as today. Y1 restricts "hand back" to installations where a thermostat or the boiler's own control takes over (decision 7). The heating switch's "off" ignored from the start is not this reaction: it always blocks and hands back (above, answer O).

Order in `decide` (P-48, T-49): after "switched off", the latch and hand-back alarm check comes before the blocker check. An alarm with the reaction "hand back" latches whatever blockers show. The status still lists the blockers.

Setpoint entity step (P-15, P-98):
- Refused in the form and as a runtime blocker `setpoint_step_too_coarse` above 1.0 K (the entity's `step` taken in its own unit: above 1.8 for a °F entity).
- Every value is converted to the entity's unit, put on its grid (`min` + n × `step`) inside [lower bound, upper bound] in that unit, and converted back to °C before the guard. When the nearest grid value falls outside, the grid value just inside is used.
- The guard's `written` is that °C value. The hand-back value is put on the same grid, and its check expects the value on the grid.
- No grid value inside the bounds → the blocker `setpoint_outside_entity_range`, which already exists.

"Off" (P-43): `off_setpoint ≤ hard_min − 1.0 K` (decided in the plan). The blocker and the form error keep the key `off_setpoint_not_below_hard_min`; their text changes.

Values for S-37:
- decided: 1 h (the second trace-less fall-back); 120 s (a send that explains a fall-back, answer E); 24 h (the rewrite memory); 1 h (the quiet time for the return); 1 K (setpoint step and "off" margin); the heating switch's "off" ignored from the start blocks control until off and on (answer O; its 3 sends of 120 s stay provisional, below);
- kept as today: 120 s (confirmation timeout); 0.5 K (tolerance); 60 s (the plugin's own lapse);
- provisional, K4: 5 min (outage trace); 20 s (joint fall-back); 3 per 24 h and 24 h (losses); 300 s (held repeat); 2 steps (steady); 1 K, 2 values and 0.5 K (clip); 3 attempts of 120 s (ignored from the start); an attempt with an outage not counted; the ignored target tried again at the next session; 120 s (after a draw); 5 min (confirmation missing); the rewrite memory kept through switching control off and on.

**Code to change.**
- `core/guards.py`:
  - `GuardState` gets the memory and counter fields named above, plus `unconfirmed_since`, `foreign_steps`, `rewrite_pending`, `clip`, `loss_times`, `fallbacks`, `start_phase`, `attempts`, `ignored_class`, `ignored_values` (the values the start phase's failed attempts did not take, for answer O) and `unknown_since`.
  - A pure function `classify(state, read_back, fall_back_set, trace, dhw_quiet, now, config)` returns the class. A table `REACTIONS: Mapping[Class, Reaction]` maps it to a reaction.
  - `plan_write` becomes: classify, then react, then plan the change or keep-alive. A target ignored from the start plans nothing.
  - `_follow_read_back` (221-252) follows a foreign value seen after the send too, and does not restart the timeout on a CHANGE (fixes 319-335).
  - `_dropped` / `two_valued` (268-274) → the class rows above; heating on/off under the same rows.
  - New `after_hand_back(state)` and `for_new_session(state, now)`, which keep the memory fields.
  - `GuardConfig` gets `refresh_s: float | None = 300.0` for held targets.
  - Rewrite the docstring (1-33): the classes; heating on/off under the same classes (S-40, answer E).
- `core/loop.py`:
  - 79-80: `LoopState(control, after_hand_back(state.setpoint), after_hand_back(state.switch))`.
  - `loop_step` takes, per target, `outage_at: float | None`, `thermostat_value: float | None`, `dhw: bool | None` and an optional `grid` for the setpoint (step, `min` and unit). It puts `desired` on the grid before `plan_write`.
  - A joint fall-back of both guards (the same step or the next) is one loss for the warning; each guard keeps its own trace-less count. 110-117 stays.
- `core/limits.py`: a pure `on_grid(value, step, base, low, high) -> float | None`, working in the entity's unit.
- `core/controller.py:241-248`: move the latch and alarm branch above the blocker branch (P-48).
- `control.py`:
  - `stored()` and `restore()` (312-373): the new stored fields.
  - `_async_hand_back_now` (974-985): keep the guard memory.
  - `_end_session` (556-561): `for_new_session`.
  - 627-633: `write_ignored` computed per guard; `commands_lost`; `confirmation_missing`.
  - A new `_follow_outages()` keeps `outage_at` per target: from the target entity, its read-back, and every other entity of the same device or gateway that the plugin reads (unavailable, unknown or missing), read through the transport's snapshot; and from a restart signal where Q3 (Q3.7) names one.
  - A new `_watch_external_switch()`.
  - The step-aside raises V7's repair issue `control_latched_<entry_id>` (severity as above), created with the latch and deleted at off→on or at the return.
  - Answer O: the latch cause `heating_off_ignored`, set when the heating guard is ignored from the start with "off" in `ignored_values`, stored with the other latches (V3), shown as the blocker `heating_off_ignored` (X5.21), raising the same `control_latched_<entry_id>`, and cleared only at off→on.
  - The return-by-itself timer (runs only while latched by `outside_change`).
  - `RUNTIME_BLOCKERS` gets `setpoint_step_too_coarse`, checked from the entity's `step` attribute in its unit.
  - Pass the grid (`step`, `min`, unit) read from the setpoint entity each step.
  - `ControlAlarm` gets `COMMANDS_LOST` and `CONFIRMATION_MISSING`, both excluded from reactions at 750-760.
- `control_config.py`:
  - A new `FIXED_REACTIONS = {"outside_change": AlarmReaction.HAND_BACK}`, checked first in `reaction()` (157-160), so a stored `info` is neutralised.
  - Parse `return_after_outside_change` (bool, default False) and `thermostat_setpoint_entity`, and add the latter to `entities`.
  - Blocker 370-373: `off_setpoint > hard_min - 1.0`.
- `transport/writers.py:75-88`: keep the unit conversion. The grid rounding moves before the guard (in the entity's unit, as above). The writer checks that the value it gets is on the grid and inside the entity's `min` and `max`, else `WriteError`.
- `config_flow.py`:
  - `REACTION_ALARMS` (403-408) drops `outside_change`.
  - `control_alarms_schema` (569-582) adds `return_after_outside_change` (X8 hides it on the relay path).
  - A new step `control_return_confirm` is shown when the option goes from off to on, with the required tick `understood`.
  - `control_schema` (437-449) adds the optional `thermostat_setpoint_entity` (sensor/number, temperature), shown for `gateway_with_thermostat`, and refused when it equals `confirmed_entity`.
  - `async_step_control_entity` (1312-1337): error `setpoint_step_too_coarse`.
  - `async_step_control_behaviour` (1431-1434): the 1 K margin.

**Texts** (`translations/en.json` is the source; `pl.json` has the same keys).

| Key | en | pl |
|---|---|---|
| `options.step.control.data.thermostat_setpoint_entity` | Thermostat's own water setpoint | Nastawa wody zadana przez termostat |
| `options.step.control.data_description.thermostat_setpoint_entity` | Optional, for a gateway with an OpenTherm thermostat: the water temperature the thermostat itself asks for (with opentherm_gw, the thermostat device's "Control setpoint 1"), not the boiler's read-back. When the boiler falls back to it after an outage, the plugin sends its command again instead of taking it for another controller. Empty (default): only the value from before the plugin counts. | Opcjonalnie, dla bramki z termostatem OpenTherm: temperatura wody, o którą prosi sam termostat (w opentherm_gw „Control setpoint 1" urządzenia termostatu), nie odczyt zwrotny kotła. Gdy kocioł wróci do niej po przerwie, wtyczka wyśle swoje polecenie ponownie, zamiast uznać to za inny sterownik. Puste (domyślnie): liczy się tylko wartość sprzed wtyczki. |
| `options.error.thermostat_setpoint_same_as_read_back` | Pick the thermostat's own entity, not the setpoint read-back. | Wybierz encję termostatu, nie odczyt zwrotny nastawy. |
| `options.step.control_alarms.data.return_after_outside_change` | Return by itself after another controller | Powrót po innym sterowniku bez udziału użytkownika |
| `options.step.control_alarms.data_description.return_after_outside_change` | Off (default): after another controller changed the boiler twice, the plugin hands the boiler back and steps aside until you switch control off and on. On: it takes the boiler back by itself after an hour in which nothing else wrote to it. Risk: if the other controller only pauses, the two take turns; with a thermostat that keeps changing its request, the hour never passes. | Wyłączone (domyślnie): gdy inny sterownik dwa razy zmieni ustawienia kotła, wtyczka oddaje kocioł i ustępuje, dopóki nie wyłączysz i nie włączysz sterowania. Włączone: wtyczka sama przejmie kocioł po godzinie, w której nic innego do niego nie pisało. Ryzyko: jeśli inny sterownik tylko robi przerwę, będą się zmieniać; przy termostacie, który stale zmienia żądanie, ta godzina nigdy nie minie. |
| `options.step.control_return_confirm.title` | Confirm the return by itself | Potwierdź samodzielny powrót |
| `options.step.control_return_confirm.description` | The plugin will take the boiler back by itself an hour after another controller last wrote to it. If that controller is still there, both will control the boiler in turns. Tick to confirm. | Wtyczka sama przejmie kocioł godzinę po ostatnim zapisie innego sterownika. Jeśli ten sterownik nadal działa, oba będą sterować kotłem na zmianę. Zaznacz, aby potwierdzić. |
| `options.step.control_return_confirm.data.understood` | I understand | Rozumiem |
| `options.error.return_needs_confirmation` | Tick the box to switch this on, or go back. | Zaznacz pole, aby to włączyć, albo wróć. |
| `options.step.control_alarms.description` | add: "Another controller always makes the plugin step aside; it never fights it." | dopisz: „Inny sterownik zawsze sprawia, że wtyczka ustępuje; nigdy z nim nie walczy." |
| `options.step.control_alarms.data.outside_change`, `data_description.outside_change` | removed | usunięte |
| `options.error.setpoint_step_too_coarse` | This entity takes values in steps above 1 °C: a rounded value would read back as ignored. Pick an entity with a finer step. | Ta encja przyjmuje wartości co ponad 1 °C: zaokrąglona wartość wyglądałaby na zignorowaną. Wybierz encję o drobniejszym kroku. |
| `exceptions.blocked_setpoint_step_too_coarse.message` | The setpoint entity now takes values in steps above 1 °C, so its read-back cannot confirm a value: pick another entity in the options. Other reasons: {others}. | Encja nastawy przyjmuje teraz wartości co ponad 1 °C, więc odczyt zwrotny nie potwierdzi wartości: wybierz inną encję w opcjach. Inne powody: {others}. |
| `options.error.off_setpoint_not_below_hard_min` | "Off" must be at least 1 °C below the lowest water temperature, or the boiler would not see a change. | „Wyłączone" musi być co najmniej 1 °C poniżej najniższej temperatury wody, inaczej kocioł nie zauważy zmiany. |
| `exceptions.blocked_off_setpoint_not_below_hard_min.message` | The "off" setpoint is not at least 1 °C below the lowest water temperature: lower it in the options. Other reasons: {others}. | Nastawa „wyłączone" nie jest co najmniej 1 °C poniżej najniższej temperatury wody: obniż ją w opcjach. Inne powody: {others}. |
| `entity.binary_sensor.alarm_write_ignored.name` | Control: the boiler does not accept a command — check the settings | Sterowanie: kocioł nie przyjmuje polecenia — sprawdź ustawienia |
| `entity.binary_sensor.alarm_commands_lost.name` | Control: commands often lost | Sterowanie: polecenia często giną |
| `entity.binary_sensor.alarm_confirmation_missing.name` | Control: the boiler's confirmation is missing | Sterowanie: brak potwierdzenia z kotła |
| `…confirmation.state.clipped` (in `control_setpoint` and in `control_state`'s `heating_confirmation`) | Held lower by the boiler (its own limit) | Obniżone przez kocioł (jego własny limit) |
| `issues.outside_change.title`, `.description` | not created: the step-aside raises V7's `issues.control_latched`, the one issue for every latch | nie tworzone: ustąpienie zgłasza `issues.control_latched` z V7, jedno zgłoszenie dla każdej blokady |

**Missing data.**
- Read-back unknown or unavailable: never judged; it is a trace and does not break the confirmation clock; after 5 min while the plugin writes, `confirmation_missing` (information only).
- Baseline never known in the session: no lost-command row applies, and the other rows still do.
- `outage_at` unknown (no availability history yet): no trace.
- Thermostat field missing, or its entity unavailable: not in the fall-back set.
- DHW unknown: the draw rule does not apply.
- Entity `step` missing or ≤ 0: no grid, as today. `min` missing: the grid is based on 0.
- External switch unavailable: not judged; a trace.
- Hand-back switch not configured: no watch.
- None of these switches heating off by itself.

**Do not.**
- Count drops toward a hand-back ("3 drops an hour → hand back", research §5, rejected).
- Take a clip value as a limit of the curve.
- Offer a reaction choice for `outside_change`.
- Treat an off external switch after an outage as another controller.
- Judge a fall-back as another controller in the start phase, or when a send explains it.
- Write a target ignored from the start again in the same session, keep-alives included.
- Keep control running when the heating switch's "off" is ignored from the start, or clear that blocker at a restart (answer O).
- Hand back or latch for `commands_lost` or `confirmation_missing`.
- Leave the other controller's value in place when stepping aside: the step-aside is the full safe hand-back (answer H).
- Offer the return by itself on the relay path.
- Raise a step-aside issue of its own: V7's `control_latched` is the one latch issue.
- Build relays (X8), the OTGW `CH=` write type (X6), P-22's echo entity (Y1) or decision 7's allow-list (Y1).
- Write the matrix into `SCOPE.md` without consent (Q1).
- Add a read-back to targets that have none.

**Open for the user.** Nothing is needed before building: answers E and H of 2026-09-27 settle how the heating switch is judged (the same classes as the setpoint) and how the plugin steps aside (the full safe hand-back). A boiler that ignores the heating switch's "off" from the start is settled too, and is the rule above: control is blocked and the boiler handed back, with an alarm, like an installation without a working heating switch (decision 11), and a blocker names the reason until the user switches control off and on after fixing it (the user, 2026-09-27, O). On the K4 list:
- A clipped setpoint that stays flat is judged as another controller (a known limit).
- Every "(provisional, K4)" value above.

---

### X2 — the boiler link and freshness

**Goal and done-when.** A lost link is judged over a window, so a link that is fresh one step in five still hands back. `boiler_link_lost` rises whenever the control switch is on and the link is lost, whatever blockers or restarts say, and stays while the loss lasts. Every signal is read with its own age limit, the flame's included. The weather entity gets its own optional age limit. Done when:
- T-03 and T-26 pass;
- so do the P-08 and P-41 scenarios below, with negative tests for flame, flow and weather that are `None` or stale;
- Q3's finding on the silent MQTT drop is applied, or named in "Open after 0.2.2".

**Read first.**
- Plan: X2's row; decision 7 ("the lost boiler link after 5 minutes"); "Missing data" (the link is one of the two stated exceptions).
- Review: P-08, P-41, T-03, T-26; Appendix B, the first row.
- `docs/plan-0.2.1.md`, "Open after R6" #8.
- `research/2026-09-27-fresh-session-test.md`, "### X2".
- `research/2026-09-25-l3-device-facts.md` (OTGW MQTT: a 60 s heartbeat for each status bit).
- Q3's note on OTGW over MQTT (written in phase Q).
- This file, X3 "Restore after a restart" (a link not yet reported never turns a restore into a hand-back).
- Code:
  - `core/controller.py:128-130, 163-183, 241-267`;
  - `control.py:609-616, 688-698, 700-733`;
  - `coordinator.py:654-664`;
  - `config_flow.py:180-193`;
  - `config.py:349-357`.

**Order of work.**
1. Core tests in `tests/core/test_controller.py`:
   - `test_a_flapping_boiler_link_still_hands_back` (T-26): controlling; the link is fresh one step in every 290 s for an hour → hand-back once the link has been stale 300 s within 600 s; `decision.link_lost` is true.
   - `test_one_stale_step_every_five_minutes_never_hands_back`: stale for one step every 300 s → no hand-back, `link_lost` false.
   - `test_after_a_stale_hand_back_control_resumes_after_a_minute_of_fresh_data`: flapping as in T-26 → no resume. Then 60 s fresh without a break → the window is cleared and control resumes. A single stale step later → no hand-back.
   - `test_a_clock_set_back_does_not_stretch_the_window` (negative): samples later than `now` are dropped.
   - Update `test_long_data_loss_hands_back_once_and_resumes` (`:375`) and `test_stale_boiler_link_writes_nothing_and_keeps_control` (`:134`) to the resume after 60 s.
2. Integration tests in `tests/integration/test_control.py`:
   - `test_a_lost_link_after_a_restart_raises_boiler_link_lost` (T-03): stand-alone, stored `controlling`, the link lost at restart → 10 min → the alarm is on and the state shows the hand-back or the wait.
   - `test_boiler_link_lost_rises_while_a_blocker_holds`: switch on, a `monitoring_period` blocker, link down for 6 min → the alarm is on.
   - `test_switching_on_with_the_link_down_raises_the_alarm`: after 300 s → on.
   - `test_the_link_alarm_is_off_while_control_is_switched_off` (negative).
   - `test_a_stale_flame_counts_by_its_own_limit` (P-41): freshness `flame` 600 s; the flame frozen, the flow fresh → nothing is written after 600 s, and the hand-back comes after the window rule.
   - `test_the_weather_entity_uses_its_own_age_limit`: outdoor limit 10 min and no weather limit → an old weather report is still used; weather limit 30 min → unused after 30 min.
   - Update `test_a_lost_boiler_link_raises_an_alarm_and_hands_back` (`:1863`): control resumes 60 s after the flow returns.
   - The restore's wait for a link not yet reported is tested in X3 (`test_a_link_not_yet_reported_does_not_turn_a_restore_into_a_hand_back`).
3. Implement, then apply Q3's result for OTGW over MQTT.

**Rules and values.**
- The link is fresh when the flame and the flow are known and within their own user age limits (none by default: availability only).
- `ControlState` keeps `link_samples`: (time, stale) for each step in the last 600 s (provisional, K4). Each sample counts its step's duration, capped at 60 s (`MAX_STEP_S`).
- The link is lost when the stale time within the last 600 s is at least 300 s (decided: 5 min). While lost and controlling → hand back (`Reason.BOILER_LINK_STALE`), as today, and nothing is written at a stale step.
- A fresh step before that writes as usual.
- The link counts as back once it has been fresh for 60 s without a break (provisional, K4). The samples are then cleared, and a stale-link hand-back resumes by itself.
- `waiting_since` is replaced by the samples.
- The samples are updated at every step, before the checks for "switched off", blockers and latch. The decision carries `link_lost`.
- `boiler_link_lost` is on while the control switch is on and `link_lost` is true, whatever the blockers, the latch or a restart. Otherwise it is off.
- After a restart the samples start empty. While X3's restore waits in the recognition period for a link that has not reported since the start, that missing report is not counted as stale: a link not yet reported never turns a restore into a hand-back (X3). From the end of the recognition period the time since the start counts as stale, so a link still silent then is lost at once. Without a restore waiting, the alarm rises 300 s after the start if the link stays down.
- Each signal's own limit: the flame in `_boiler_link`; the DHW, CH-active and flame flags that `dhw_now` reads (`coordinator.py:654-664`), one rule for the monitor and control; the outdoor sensor keeps its own.
- The weather entity: an optional age limit in the freshness step, stored as `freshness["weather"]` in seconds. `config.py` `_freshness` takes that key out into `EntryConfig.weather_max_age_s` before it parses the signals. None by default.
- Silent MQTT drop and a broken ESP–PIC link: X2 uses what Q3 finds, for example a signal the firmware republishes on a fixed period with a recommended limit, or an availability topic. Where the firmware gives no signal Home Assistant can see, the item goes to "Open after 0.2.2" with that reason.
- Values for S-37: 300 s (decided), 600 s window, 60 s recovery (provisional, K4); 60 s step cap (`MAX_STEP_S`, existing).

**Code to change.**
- `core/controller.py`:
  - 163-183: `link_samples`, `link_fresh_since` instead of `waiting_since`;
  - 241-267: the window rule, evaluated before line 241, with `link_lost` in `ControlDecision`; a flag in `ControlInputs` for X3's waiting restore (a link not yet reported since the start);
  - 130: `stale_hand_back_s` stays 300.
- `control.py`:
  - 609-616: the alarm from `self.enabled and out.decision.link_lost`;
  - 688-698: `snapshot.flag(Signal.FLAME, limit_flame)`;
  - 714-719: `config.weather_max_age_s`.
- `coordinator.py:654-664`: read the flags with their own limits.
- `config_flow.py:180-193`: the `weather` field when a weather entity is set.
- `config.py:349-357`: the `weather` key.

**Texts.**

| Key | en | pl |
|---|---|---|
| `options.step.freshness.data.weather` | Weather entity | Encja pogody |
| `options.step.freshness.description` | add: "Control reads the flame and the flow each by its own limit; a link that keeps dropping in and out counts as lost once it has been stale for five minutes within ten. The weather entity has its own limit, none by default." | dopisz: „Sterowanie sprawdza płomień i temperaturę zasilania, każde według jego limitu; połączenie, które co chwilę znika, uznaje się za utracone, gdy przez pięć minut w ciągu dziesięciu nie ma świeżych danych. Encja pogody ma własny limit, domyślnie brak." |

**Missing data.**
- Flame or flow `None`, unmapped or stale → the link is stale. This is one of the two stated exceptions to the missing-data rule (the other is decision 3's end state, X3): missing data from the boiler hands back (a relay is handled in X8). After X8, an unmapped flame or flow is X8's blocker for water-temperature control instead.
- No age limit set → availability only.
- Weather `None`, unavailable or older than its limit → no weather reading; the curve holds and then falls back (decision 9).
- DHW or CH-active stale → unknown.

**Do not.**
- Build the relay exception (X8).
- Add default age limits.
- Count the outdoor sensor or the weather as part of the link.
- Delay writes at a fresh step before the hand-back.
- Hand back while X3's restore waits, within the recognition period, for a link not yet reported since the start.

**Open for the user.** None.

---

### X3 — demand, zones, decision 3

**Goal and done-when.** Demand is judged as VT judges it, and the rules for zones hold as decided:
- the opening threshold counts calling zones only;
- a power of 0 or less is no data, and the power criterion is the zones' mean power over the cycle, counted only while at least one of those zones has its valve open or its device active;
- a criterion without data is refused in the form, and at run time is treated as for unknown zones, with an alarm;
- control needs at least one zone;
- an "off" zone that VT has not started is known to have no demand once the recognition period is over;
- VT's safety mode flags the zone;
- power shedding removes a zone's demand;
- one plausibility rule applies to room temperatures;
- the reference room and the critical zone skip lost-sensor and not-ready zones;
- decision 3 is implemented in full: the recognition period, with the last command restored at once after a restart under the conditions below; the grace for each zone; and the end state when every zone is unknown — a hand-back to a working thermostat (a gateway with an OpenTherm thermostat, or the new option "the boiler has its own room controller" on the entity path, and on the relay path with the rest state "on"; answers F and M), else the usual "off" — with an alarm and a repair issue, in monitor-only mode too. It replaces heating on the curve, or at the design flow, with no zone known.

Done when:
- T-17, T-27, T-28, T-44, T-45 and T-46 pass, with their "Then" changed as below;
- so do the scenarios of P-13, P-14, P-18 and P-105 (the grace part) and of S-03, S-04, S-06, S-34 and S-35;
- the vendored-VT observation test passes;
- the new option's form tests pass;
- negative tests pass for unavailable zones, missing power or opening, a missing stored command, and a link not yet reported at a restore.

**Read first.**
- Plan:
  - decision 3, with answers F and M of 2026-09-27 (the working thermostat and the new option "the boiler has its own room controller": offered on the entity and relay paths, not on a gateway; on the relay path counting only with the rest state "on"); Terms "Recognition period", "Grace period" and "Working thermostat";
  - answer K (a gateway entry without an answer to the thermostat-terminals question keeps control stopped; after a restart the control switch comes back as the user left it, and a disabled switch entity means control off);
  - "Missing data" (decision 3 is the other stated exception);
  - the findings at `core/controller.py:198-203` and on VT before its start;
  - the power-criterion bullet under "On/off control" (X8 points to X3);
  - X3's row.
- Review:
  - problems: P-13, P-14, P-18, P-105;
  - specification: S-03, S-04, S-06, S-34, S-35;
  - §6 tests: T-17, T-27, T-28, T-44, T-45, T-46;
  - Appendix B; Appendix E question 1.
- `research/2026-09-26-q4-decision-3-no-zone-known.md`:
  - use: (a) the chain, (b) the situations, and the verifier's corrections (F1 overstated: over_switch and over_valve zones publish `is_ready: false` before their start; the P-105 path; the pre-start states);
  - do not use: the recommendation of heat on the curve, option C, or the heating threshold, which were overruled.
- `research/2026-09-27-fresh-session-test.md`, "### X3".
- `research/2026-09-27-plan-0.2.2-checks.md`, the decision-3 items.
- This file, V3 (the stored last command, cleared at every session end but the stop's hand-back, and the stored wish) and V5 (the safe hand-back and its effects).
- Code:
  - `core/demand.py` (all);
  - `core/readings.py:89-157`;
  - `core/zones.py`;
  - `core/limits.py:81, 99-111`;
  - `core/controller.py:198-203, 226-270, 385-397`;
  - `vtherm_attributes.py:47-70, 126-137`;
  - `vtherm_link.py:98-133, 171-203`;
  - `control.py:485-506, 586-604, 666-680`;
  - `control_config.py:70-86, 299-314` (the hand-back effects), `317-374`;
  - `config_flow.py:437-475` (the control step), `1420-1448`;
  - `switch.py:58-69`;
  - `coordinator.py:539-560, 744-757`;
  - `tests/integration/harness.py:84-107`.
- Vendored VT 10.4.0, for interface facts only:
  - `base_thermostat.py:1994-1999` (`is_ready` published with `specific_states`);
  - `feature_safety_manager.py:260-266`;
  - `feature_power_manager.py:109-125, 373-387`;
  - `sensor.py:1061-1075`.

**Order of work.**
1. First, the observation test `tests/integration/test_vendor.py::test_what_a_vt_zone_shows_before_its_start_during_a_reload_and_after` (requires vendor). It covers over_switch, and over_climate if the vendored fixtures allow it, and records the state, `is_ready` and `specific_states`:
   - before `EVENT_HOMEASSISTANT_STARTED`;
   - after it;
   - during a thermostat reload;
   - during a reload of the central entry.

   The rules below are written against what it shows. Where it differs from this file, the observation wins, and the step's report says so.
2. Core tests:
   - `tests/core/test_demand.py`:
     - `test_the_opening_threshold_follows_calling_zones_only` (T-46): over_switch, `on_percent` 0.6, `device_active` false, opening threshold 0.5 → no demand.
     - `test_the_power_criterion_counts_a_switch_zone_through_its_off_phase`: mean power 1.2 kW (`on_percent` 0.6 × 2 kW), device off for this part of the cycle, another zone's valve open → power 1.2.
     - `test_the_power_criterion_needs_an_open_valve_or_an_active_device`: mean power 3 kW but no zone open or active → the criterion says no demand.
     - `test_a_criterion_without_data_is_not_no_demand` (T-27): count 0, power threshold only, every zone's power `None` → `wanted` is `None` and `criteria_without_data == ("power",)`.
     - `test_only_the_criterion_without_data_is_left_out`: count 1 and a power threshold without data → the count decides.
     - `test_an_off_zone_not_ready_is_known_without_demand` (T-17, core): outside the recognition period → `wanted` false. The controller then gives IDLE with `Reason.NO_DEMAND`.
     - `test_a_heating_zone_not_ready_is_unknown`.
     - `test_a_shed_zone_has_no_demand_and_no_power`: `shedding` true → no demand.
   - `tests/core/test_controller.py` (decision 3):
     - `test_no_new_decision_during_recognition_without_a_last_command`: at the start, zones not reported → no command, WAITING_DATA, `Reason.ZONES_RECOGNITION`.
     - `test_a_kept_command_goes_on_during_recognition`: a restored command (on, 45 °C) → the same command at every step until the recognition ends.
     - `test_recognition_ends_when_every_zone_reported_or_after_ten_minutes`.
     - `test_a_vt_reload_starts_a_recognition_period`: every zone is unknown at once after having been reported → recognition.
     - `test_a_zone_unknown_for_less_than_ten_minutes_keeps_its_last_answer`: A called, then went unavailable → still calls at 9 min 50 s, drops out at 10 min.
     - `test_a_zone_never_known_this_session_gets_no_grace`.
     - `test_every_zone_unknown_after_the_grace_hands_back_to_a_thermostat`: `working_thermostat` true through THERMOSTAT_TAKES_OVER → HANDED_BACK, `Reason.ZONES_UNKNOWN`, `hand_back` once, no latch.
     - `test_every_zone_unknown_hands_back_to_the_boilers_own_room_controller_where_ticked`: the entity path with `own_room_controller` ticked → HANDED_BACK, `Reason.ZONES_UNKNOWN`, no latch.
     - `test_every_zone_unknown_without_a_thermostat_means_the_usual_off`: `working_thermostat` false (stand-alone; "device decides"; a hand-back value declared "own control" without the tick; the relay path with the tick and the rest state "off", answer M) → IDLE, command `ch_enable` false, `Reason.ZONES_UNKNOWN`, no hand-back.
     - `test_heating_resumes_when_a_zone_answers_again`: after the usual "off", and after a hand-back.
     - `test_no_design_flow_heating_with_every_zone_and_the_outdoor_temperature_unknown`: outdoor unknown for 4 h and every zone unknown → no heat, and never the design flow.
     - `test_a_transient_loss_of_every_zone_does_not_start_the_boiler` (T-28, core): summer, the only zone off → unavailable for 3 steps → recognition keeps "off"; no ON command.
     - Rewrite `test_unknown_zones_mean_heat` (`:151`) into the last three tests.
   - `tests/core/test_zones.py` (new) or `test_reference_room.py`:
     - `test_reference_room_and_critical_zone_skip_lost_sensor_and_not_ready_zones` (P-18).
     - `test_one_plausibility_rule_for_room_temperatures` (S-06): 2 °C is valid for frost, the reference room and the critical zone; 85 °C and −40 °C are not.
   - `tests/test_vtherm_attributes.py`:
     - `test_a_device_power_of_zero_is_no_data` (P-14).
     - `test_vt_safety_state_on_is_read`.
     - `test_overpowering_state_on_is_read`.
     - `test_mean_cycle_power_is_read_in_its_unit`.
     - `test_a_zone_without_vt_attributes_has_not_reported`.
   - `tests/test_control_config.py` (or the existing options test file):
     - `test_the_own_room_controller_tick_makes_a_working_thermostat`: the tick on the entity path → `hand_back_effect` is `OWN_CONTROL_RESUMES` and `working_thermostat` true.
     - `test_an_own_control_hand_back_value_without_the_tick_is_not_a_working_thermostat`.
     - `test_the_tick_on_the_relay_path_counts_only_with_rest_state_on` (answer M): the relay path with the tick and rest state "on" → `working_thermostat` true and `hand_back_effect` `RELAY_RESTS_ON`; rest state "off" → `working_thermostat` false.
     - `test_a_tick_stored_with_a_gateway_is_ignored` (answer M; hand-edited options, on a gateway path and on the entity path with a gateway topology): an OpenTherm thermostat on the terminals and the tick → `THERMOSTAT_TAKES_OVER`, `working_thermostat` true through the thermostat; stand-alone with the tick → `HEATING_STOPS`, `working_thermostat` false.
3. Integration tests:
   - `test_control_needs_at_least_one_zone` (S-04): blocker `no_zones`; the control form refuses with `no_zones`.
   - `test_a_criterion_no_zone_can_feed_is_refused_in_the_form`: zones readable, none publishes a power → error `power_criterion_no_zone`. With every zone unavailable → accepted.
   - `test_no_zone_known_raises_an_alarm_and_a_repair_issue`: control on, every zone unavailable for 10 min → `alarm_no_zone_known` and issue `no_zone_known_<entry>`, both at once at the end of the recognition period.
   - `test_no_zone_known_raises_the_repair_issue_with_the_monitor_only`: no control configured → the issue after 10 min.
   - `test_the_last_command_is_restored_at_once_after_a_restart`: a V3 store with `controlling` and the last command (on, 45), the stored wish on and the options equal to `taken_with` → the first write is 45 with CH on, no hand-back first. Negatives, each → the hand-back comes first, as today: no stored command; the wish off, or the switch entity disabled; a stored latch or internal error; options that differ from `taken_with`; a blocker other than `ha_starting` (e.g. the gateway's terminals question unanswered, answer K).
   - `test_a_link_not_yet_reported_does_not_turn_a_restore_into_a_hand_back`: a restorable store; the gateway's link reports 3 min after the start → nothing written meanwhile, then the restore, no hand-back first. Negative: the link still silent at the end of the recognition period → the owed hand-back and `boiler_link_lost` (X2).
   - `test_a_vt_central_reload_does_not_hand_back_within_the_grace` (P-105, X3 part): VT's boiler known off, then `vt_central_boiler_unknown` for 2 min → no hand-back; for 11 min → blocker, hand-back.
   - `test_a_restore_passes_vt_central_boiler_unknown_within_the_grace` (provisional, K4): a restorable store and VT's central boiler unknown at the start → the restore; still unknown after 600 s → blocker, hand-back.
   - Flow tests:
     - `test_the_own_room_controller_tick_is_offered_on_the_entity_and_relay_paths_only`: shown on the entity path with the virtual topology and on the relay path; not on either gateway path, nor on the entity path with a gateway topology (answers F and M, with the reading above).
     - `test_the_tick_is_refused_with_a_hand_back_value_that_stops_heating`: error `own_room_controller_but_heating_stops`.
   - Vendor tests:
     - `test_a_vt_safety_mode_zone_follows_vt_and_is_flagged` (T-44);
     - `test_vt_power_shedding_removes_demand` (T-45). This is a test first; the code changes only if it fails.
   - Harness: `FakeZones.set` publishes `is_ready: True` and `specific_states: {}` by default, as VT 10.4.0 does once started. The not-started variants are explicit.
   - Rewrite:
     - `tests/integration/test_control.py:1913`: add a second zone so the known zone decides; move the single-zone case into the end-state tests;
     - `tests/integration/test_acceptance.py:629` `test_zones_that_cannot_be_read_mean_heat_not_cold` → the end state of decision 3 (the rig's topology decides whether it is a hand-back or "off");
     - `tests/core/test_demand.py:78-106` (not-ready rows).

**Rules and values.**

Zone states (`ZoneState.is_known` and a new `ZoneState.reported`):
- unknown: no state; unavailable or unknown; a mode not listed; stale beyond a user age limit;
- unknown: any mode with `is_ready: false`, because VT does not run it — also after the recognition period (decision 1 of `docs/plan-0.2.3.md`; until 0.2.3, off, cool, dry or fan_only with `is_ready: false` counted as known, no demand, outside the recognition period);
- as today: `is_ready` absent.

A zone has reported when:
- VT publishes `is_ready: true`; or
- the zone carries VT's `specific_states` but no `is_ready` key (an older VT, assumed; Q3 or X7's minimum version decides) and its mode is known.

A zone with neither (VT 10.4.0 before its first attribute refresh) has not reported.

The recognition period (decided: at most 10 min):
- It starts:
  - when the control unit starts (Home Assistant start or entry reload);
  - when every configured zone becomes unknown or unreported at once after having been reported (a VT reload).
- It ends when every configured zone has reported since it began, or after 600 s.
- Meanwhile no new decision on heating or the water temperature is made:
  - the command held before (in this session, or the last command V3 restored) is repeated with its keep-alives;
  - without one, nothing is written: WAITING_DATA with `Reason.ZONES_RECOGNITION`;
  - frost protection may still start frost heating, for zones that can take heat, because it only adds heat (provisional, K4);
  - the closed-zone repair issue (X4) waits.
- `ha_starting` does not stop keeping or restoring a command. It still stops new decisions: the recognition period cannot end before Home Assistant runs.

Restore after a restart:
- Restore at once when all of these hold:
  - V3 stored a last command;
  - the stored wish is "control on", and the control switch entity is not disabled (answer K);
  - no latch or internal error;
  - the control options equal `taken_with`;
  - no blocker other than `ha_starting`, and `vt_central_boiler_unknown` only within the P-105 grace below.
- Until the write target and the boiler link are available, nothing is written and the restore waits, within the recognition period (at most 10 min). A link not yet reported never turns the restore into a hand-back (X2). A restore still waiting when the recognition period ends gives way to the owed hand-back, and X2's link rule applies as usual.
- On a restore, the owed hand-back is folded into the session (`_full_hand_back_due`), as `control.py:845-849` does.
- Otherwise the owed hand-back goes first, as today.
- No activation delay applies to a restored "on" (X4).

The grace for each zone (decided: 10 min):
- A zone that becomes unknown after being known keeps its last known state (mode, action, opening, device, power) in demand for 600 s. Then it drops out and the known zones decide.
- The count threshold stays capped at the known zones (`core/demand.py:88`).
- Not stored across a restart; the recognition period covers restarts.

A working thermostat (decision 3, answers F and M) is:
- a gateway with an OpenTherm thermostat declared on its terminals: `hand_back_effect(...)` is `THERMOSTAT_TAKES_OVER` (X6 adds the terminals question; a gateway entry without its answer keeps control stopped, answer K); or
- the new option "the boiler has its own room controller" ticked on the entity path; its hand-back effect is `OWN_CONTROL_RESUMES`; or
- the same tick on the relay path with the rest state "on" (the relay is the boiler's heat-demand contact; answer M).

Not a working thermostat: a hand-back value declared "own control" without the tick (e.g. EMS-ESP back to the boiler's own dial), "device decides", a stand-alone gateway, a relay resting "on" without the tick, and the tick on the relay path with the rest state "off" (answer M).

The option "the boiler has its own room controller" (`own_room_controller`, answers F and M):
- Bool, default off. Off means that when VT gives no answer at all, the plugin does not heat and raises an alarm and a repair issue.
- In the `control` step, next to the hand-back fields, at the simple level. Shown on the entity path and the relay path; not offered with a gateway (the user, 2026-09-27, M): a thermostat on the terminals already counts (`THERMOSTAT_TAKES_OVER`), and with nothing on the terminals a hand-back stops heating anyway. "With a gateway" is read here as every entry whose topology is `gateway_standalone` or `gateway_with_thermostat` — the `opentherm_gw` and `otgw_mqtt` paths, and the entity path with a gateway topology, where decision 1 asks the terminals question — so the entity path offers the tick with the virtual topology only (this file's reading of answer M's "on a gateway", to confirm at K4). A tick stored where it is not offered (hand-edited, or left from an earlier write path or topology) is ignored. On the relay path, whose hand-back is its rest state (X8), `hand_back_effect` stays `RELAY_RESTS_OFF` / `RELAY_RESTS_ON`, and the tick counts for the working thermostat only where the rest state is "on"; with rest state "off", VT giving no answer means no heating and an alarm, as without the tick (the user, 2026-09-27, M). A relay resting "on" without the tick is not a working thermostat.
- Refused in the form together with a hand-back value declared "heating stops" (error `own_room_controller_but_heating_stops`). On the relay path with the rest state "off", a stored tick counts as not ticked (answer M).
- With the tick, `hand_back_effect` returns the new member `OWN_CONTROL_RESUMES` for every hand-back of an entity-path entry with the virtual topology; not with a gateway (the tick is ignored there: `THERMOSTAT_TAKES_OVER` with an OpenTherm thermostat, `HEATING_STOPS` stand-alone) nor on the relay path (X8's `RELAY_RESTS_OFF` / `RELAY_RESTS_ON`, where `working_thermostat` reads the tick itself); Y1 also maps a hand-back value declared "own control" to it. V5's heating-switch rule and V7's `frost_protection_by` treat it as they treat "device decides" (heating switch on at hand-back; `device`).

End state:
- It applies when every configured zone is unknown after the recognition period and all graces, or when every configured criterion lacks data (T-27).
- With a working thermostat → HANDED_BACK with `Reason.ZONES_UNKNOWN`: a safe hand-back at once, without a latch.
- Otherwise → the usual "off" (CH off; for a relay the relay off, never its rest state, X8), IDLE, `Reason.ZONES_UNKNOWN`, no hand-back. "Off" as a low setpoint stays blocked by decision 11.
- Either way it resumes by itself when a zone is known again (after a hand-back: provisional, K4).
- `fallback_setpoint` (`core/controller.py:198-203`) is used only with zones known (decision 9).
- Alarm and repair issue:
  - the control alarm `no_zone_known` comes at once when the end state begins, while the switch is on;
  - the coordinator raises the repair issue `no_zone_known_<entry_id>` in every mode, the monitor only included, when every configured zone has been unknown for 600 s. There are three translation keys: `no_zone_known_off`, `no_zone_known_handed_back` and `no_zone_known_monitor`. Severity: error for `no_zone_known_off` (heating stops), warning for the others (provisional, K4);
  - with zero zones configured: no issue;
  - where the zones are known but no configured criterion can be judged, the same end state raises the same alarm and a repair issue that names the criterion — error where heating stops, warning after a hand-back or with the monitor only (decision 3 of `docs/plan-0.2.3.md`, as SCOPE §7).

The P-105 part:
- `vt_central_boiler_unknown` does not count as a blocker for up to 600 s when VT's central boiler was known to be not configured (`False`) at the last step before it became unknown. The status shows it with the suffix "(grace)" in `blockers_waiting`.
- After a restart, a restorable store stands for "known not configured just before": V3 keeps a last command only through the stop's hand-back, and a session cannot run while VT's central boiler is configured (provisional, K4).
- After 600 s it blocks as today.
- X7 then reads the entry's stored data during a reload.

Power criterion (every write path):
- A zone's mean power is `power_manager.mean_cycle_power` in its unit where VT publishes it, else `device_power × on_percent`.
- It is summed over zones in a heating mode with a duty cycle or opening above 0 and not shedding.
- It counts only while at least one of them has an opening above `ZONE_OPEN` (0.05) or `device_active` true.
- A power ≤ 0 is no data.

Opening criterion: the widest opening among the zones that call (`zone_wants_heat`).

Criterion without data:
- power: no known zone has a power above 0;
- opening: no known heating zone publishes an opening.
- Only that criterion is left out. When no configured criterion can be judged → `wanted` is `None` → the end state after the zones' grace. The control alarm `demand_criterion_no_data` names the criterion; the end state's alarm `no_zone_known` and its repair issue rise as above.
- In the form: refused when at least one zone is readable and none can feed the criterion.

Other zone rules:
- S-04: the config blocker `no_zones` when the installation has no zone.
- S-35: `safety_manager.safety_state == "on"` → `room_sensor_lost` true (the zone alarm after 30 min). Demand still follows VT.
- T-45: `power_manager.overpowering_state == "on"` → no demand, no power.
- S-06: one rule for room temperatures, −30 to 45 °C (`core/limits.py:81`), for frost protection, the reference room and the critical zone; setpoints keep 5–35 °C.
  - An implausible temperature makes the zone blind for frost protection, and it joins the 30 min `zone_unknown` alarm.
  - Its demand still counts.
- P-18: `eligible_zones` skips `room_sensor_lost` and `ready is False` zones.
- The 30 min `zone_unknown` alarm also covers zones not started for 30 min.

Values for S-37:
- 600 s recognition and 600 s grace (decided);
- 600 s P-105 grace; the restore's wait for the write target and the link bounded by the recognition period (provisional, K4);
- 30 min zone alarm (as today);
- −30 to 45 °C and 5 to 35 °C (as today);
- the power gate at `ZONE_OPEN` 5 % (as today).

**Code to change.**
- `vtherm_attributes.py`:
  - 126-137: `number <= 0` → `None`;
  - new fields `mean_power`, `safety_on`, `shedding` and `reported` in `ZoneValues` (47-70).
- `vtherm_link.py:98-133`: carry them; `room_sensor_lost` also from `safety_on`.
- `core/readings.py:89-157`: the new fields, `is_known` as above, `reported`.
- `core/demand.py`:
  - `boiler_demand` takes an optional `memory` (the grace);
  - openings over calling zones (79-80);
  - the power as above (81-86);
  - `Demand.criteria_without_data`.
- New module `core/zone_watch.py`: pure functions for recognition, grace and end state, and a `ZoneWatch` state held in `ControlState`.
- `core/controller.py`:
  - `_want_heat` (389-397) and `decide` (226-270) use the watch;
  - new reasons `ZONES_RECOGNITION` and (for X4) `ACTIVATION_DELAY`;
  - `ControlConfig.working_thermostat: bool`;
  - `ControlInputs.restored_command`;
  - docstring points 3-4 (1-26).
- `core/zones.py`: one plausibility rule; skip lost and not-ready zones.
- `control.py`:
  - `NO_ZONE_KNOWN` and `DEMAND_CRITERION_NO_DATA` in `ControlAlarm`, excluded from reactions;
  - the restore rule in `_async_step` (586-604), with the wait for the write target and the link;
  - the P-105 grace in `blockers()` (495-499), and its reading after a restart;
  - `_follow_unknown_zones` (666-680) adds not-started and implausible zones.
- `control_config.py`:
  - the `no_zones` blocker;
  - `HandBackEffect.OWN_CONTROL_RESUMES` (70-86);
  - the option `own_room_controller` (bool, default False) in `CONTROL_DEFAULTS` and the parser; `hand_back_effect` (299-314) returns `OWN_CONTROL_RESUMES` where the tick counts (the entity path);
  - `working_thermostat` = `hand_back_effect(...) is THERMOSTAT_TAKES_OVER`, or the tick on the entity path with the virtual topology, or the tick on the relay path with the rest state "on"; a tick with a gateway topology is ignored (answer M).
- `config_flow.py`: the control step's `no_zones` error; the `own_room_controller` field on the entity and relay paths only (answers F and M) and its error; the behaviour step's criteria checks (1431-1440).
- `switch.py:58-69`: the `hand_back_effect` attribute shows the new state.
- `coordinator.py`: the `no_zone_known` issue, deleted at stop like the others (`coordinator.py:243`).

**Texts.**

| Key | en | pl |
|---|---|---|
| `exceptions.blocked_no_zones.message` | Control needs at least one Versatile Thermostat zone: add them in the options. Other reasons: {others}. | Sterowanie wymaga co najmniej jednej strefy Versatile Thermostat: dodaj je w opcjach. Inne powody: {others}. |
| `options.error.no_zones` | Add at least one Versatile Thermostat zone before setting up control. | Przed konfiguracją sterowania dodaj co najmniej jedną strefę Versatile Thermostat. |
| `options.error.power_criterion_no_zone` | No zone reports a device power in Versatile Thermostat, so this threshold could never be reached: set the power in VT or leave it empty. | Żadna strefa nie podaje mocy urządzenia w Versatile Thermostat, więc tego progu nie da się osiągnąć: ustaw moc w VT albo zostaw puste. |
| `options.error.opening_criterion_no_zone` | No zone reports a valve opening or duty cycle, so this threshold could never be reached. | Żadna strefa nie podaje otwarcia zaworu ani wypełnienia, więc tego progu nie da się osiągnąć. |
| `options.step.control_behaviour.data_description.power_threshold_kw` | Optional: heating is needed when the zones' mean power over their cycle, as Versatile Thermostat counts it, reaches this, in kW — counted only while at least one of them has its valve open or its device on. Too high leaves small rooms without heat. | Opcjonalnie: grzanie jest potrzebne, gdy średnia moc stref w cyklu, liczona jak w Versatile Thermostat, osiągnie tę wartość, w kW — liczona tylko wtedy, gdy choć jedna z nich ma otwarty zawór albo włączone urządzenie. Za wysoki próg zostawia małe pokoje bez ciepła. |
| `options.step.control.data.own_room_controller` | The boiler has its own room controller | Kocioł ma własny regulator pokojowy |
| `options.step.control.data_description.own_room_controller` | Tick only if the boiler has a room controller of its own that asks for heat by itself once the plugin lets go — for example a room unit on the boiler's bus (EMS). If Versatile Thermostat gives no answer at all, the plugin then hands the boiler back to it; without the tick the boiler does not heat, and an alarm and a repair notice tell you why. Every other hand-back also goes to that controller. With a relay it counts only when the relay's state after hand-back is "on"; with "off", the boiler does not heat when Versatile Thermostat gives no answer. Off by default. Risk: without such a controller, the boiler would be left on its own dial, heating with no room in charge. | Zaznacz tylko wtedy, gdy kocioł ma własny regulator pokojowy, który sam prosi o ciepło, gdy wtyczka odda sterowanie — na przykład panel pokojowy na magistrali kotła (EMS). Jeśli Versatile Thermostat w ogóle nie odpowiada, wtyczka odda mu wtedy kocioł; bez zaznaczenia kocioł nie grzeje, a alarm i zgłoszenie do naprawy powiedzą dlaczego. Każde inne oddanie sterowania też trafia do tego regulatora. Przy przekaźniku liczy się to tylko wtedy, gdy stan przekaźnika po oddaniu sterowania to „włączony”; przy „wyłączony” kocioł nie grzeje, gdy Versatile Thermostat nie odpowiada. Domyślnie wyłączone. Ryzyko: bez takiego regulatora kocioł zostałby na własnym pokrętle i grzałby bez kontroli temperatury w pokojach. |
| `options.error.own_room_controller_but_heating_stops` | A hand-back value that stops heating leaves nothing for the boiler's own room controller to take over: untick the box or change what the hand-back value does. | Wartość przy oddaniu, która zatrzymuje grzanie, nie zostawia nic do przejęcia własnemu regulatorowi kotła: odznacz pole albo zmień działanie wartości przy oddaniu. |
| `entity.switch.control.state_attributes.hand_back_effect.state.own_control_resumes` | The boiler's own control takes over | Przejmuje własne sterowanie kotła |
| `entity.binary_sensor.alarm_no_zone_known.name` | Control: no zone answers | Sterowanie: żadna strefa nie odpowiada |
| `entity.binary_sensor.alarm_demand_criterion_no_data.name` | Control: a demand criterion has no data | Sterowanie: kryterium zapotrzebowania bez danych |
| `issues.no_zone_known_off.title` | Versatile Thermostat gives no answer: the boiler is not heating | Versatile Thermostat nie odpowiada: kocioł nie grzeje |
| `issues.no_zone_known_off.description` | None of the zones answers ({zones}), so nothing can ask for heat. The plugin keeps the boiler's heating off and resumes as soon as a zone answers. Check that Versatile Thermostat is loaded, its thermostats are enabled and their entity IDs are the ones in the plugin's options. | Żadna strefa nie odpowiada ({zones}), więc nic nie może poprosić o ciepło. Wtyczka trzyma grzanie kotła wyłączone i wznowi je, gdy tylko któraś strefa odpowie. Sprawdź, czy Versatile Thermostat jest załadowany, jego termostaty są włączone, a ich identyfikatory encji zgadzają się z opcjami wtyczki. |
| `issues.no_zone_known_handed_back.title` / `.description` | Versatile Thermostat gives no answer: the boiler is back on its thermostat or its own room controller / the same text, with "The plugin handed the boiler back to the thermostat on the gateway, or to the boiler's own room controller, and takes it again as soon as a zone answers." | Versatile Thermostat nie odpowiada: kocioł wrócił do termostatu albo własnego regulatora pokojowego / ten sam tekst, z „Wtyczka oddała kocioł termostatowi na bramce albo własnemu regulatorowi pokojowemu kotła i przejmie go znów, gdy tylko strefa odpowie." |
| `issues.no_zone_known_monitor.title` / `.description` | Versatile Thermostat gives no answer / "None of the zones answers ({zones}); the monitor cannot judge them. Check …" (as above) | Versatile Thermostat nie odpowiada / „Żadna strefa nie odpowiada ({zones}); monitor nie może ich ocenić. Sprawdź …" |

**Missing data.**
- A zone with no state or unavailable: unknown (grace, then drops out).
- `mean_cycle_power` missing: `device_power × on_percent`. Both missing: no power.
- `safety_manager` or `overpowering_state` missing: not flagged, not shedding.
- `is_ready` and `specific_states` missing: not reported, so the recognition period waits (at most 10 min).
- No V3 stored command: the plugin waits, and the owed hand-back comes first.
- Write target or boiler link not yet reported after a restart: the restore waits, writing nothing, within the recognition period; then the owed hand-back.
- VT's central entry unreadable: the P-105 grace, then the blocker.
- `own_room_controller` missing: not ticked. Stored with a gateway topology: ignored (answer M).
- Every zone missing: decision 3's end state. This is a stated exception to the missing-data rule, not a silent "no demand".

**Do not.**
- Heat on the curve, or at the design flow, with no zone known.
- Add a summer switch or use the building's heating threshold for control (option C, rejected).
- Make the grace cover the whole house instead of each zone.
- Latch the end-state hand-back.
- Count a relay resting "on", or a hand-back value declared "own control" without the tick, as a working thermostat.
- Offer the "own room controller" tick with a gateway, or count it on the relay path with the rest state "off" (answer M).
- Turn a restore into a hand-back because the link has not reported yet, within the recognition period.
- Switch VT's modes.
- Read VT outside `vtherm_link.py`.
- Treat "off & not ready" as known during the recognition period.

**Open for the user.** Nothing is needed before building. Answer F of 2026-09-27 settles the case the draft asked about: when VT gives no answer at all, the boiler goes back to its own control only where the user ticked "the boiler has its own room controller"; a hand-back value declared "own control" alone (e.g. EMS-ESP back to the boiler's dial) is not enough, and without the tick the plugin keeps heating off and raises an alarm and a repair issue. Answer M of 2026-09-27 settles the paths: the tick is offered on the entity path as answer F says and on the relay path, where it counts only with the rest state "on"; it is not offered on a gateway. On the K4 list: this step's reading that "on a gateway" covers the entity path with a gateway topology too.

---

### X4 — frost, activation delay, fallback, ramp, circuit maximum, comfort correction, learning pauses

**Goal and done-when.** The step covers:
- frost protection heats only for cold zones that can take heat, and a cold zone VT keeps closed raises a repair issue (decision 4);
- VT's activation delay, carried over (decision 5);
- `frost_since` reset at hand-back; FALLBACK shown only while heating; the fixed fallback pinned (decision 9);
- the ramp skipped only for installation limits;
- the circuit maximum's text and an information alarm (decision 10);
- the comfort correction:
  - "heat flows" means the flame when known, else the command;
  - only zones taking heat stop the rise;
  - every rule of principle 13 is mapped, with a freeze while a cap holds;
  - no rise with the clock set back;
  - its value is published, and a "Reset comfort correction" button resets it (answer J);
- learning pauses per cause, and a hot-water draw still pauses SmartPI.

Done when:
- T-18 and T-48 pass;
- decision 10 has its core test (T-20 itself runs in Z3);
- the scenarios of S-05, S-07, S-08, S-14, S-23, S-24, S-25, S-26 and S-41, and of P-38, P-45, P-46, P-47 and P-89, pass;
- the reset button's tests pass;
- negative tests pass for missing openings, flame, VT's stored delay, the flow reading and the circuit maximum.

**Read first.**
- Plan: decisions 4, 5, 9 and 10; answer J of 2026-09-27 (the reset button in a new file `button.py`); principle 13 in `SCOPE.md` §3; X4's row; review question 3.
- Review:
  - problems: P-38, P-45, P-46, P-47, P-89;
  - specification: S-05, S-07, S-08, S-14, S-23, S-24, S-25, S-26, S-41;
  - §6 tests: T-18, T-20, T-48.
- `research/2026-09-26-q4-decisions-4-5-frost-valves-activation-delay.md`:
  - use: the VT facts, and tests 1-2 and 4-12 of decision 4 as the verifier corrected them, i.e. the published opening or device decides and the mode alone does not;
  - use: the option name `activation_delay_s`, the VT key `central_boiler_activation_delay_sec` (VT 10.4.0 `const.py:236`, `config_schema.py:228-232`, kept in the central entry's `data`), and tests 1, 2 and 4-13 of decision 5;
  - replaced: test 3, by "a gap neither cancels nor restarts the wait"; "every level", by the simple level; "counts anew after a restart", by "no delay where the plugin controlled before".
- `research/2026-09-27-fresh-session-test.md`, "### X4".
- Code:
  - `core/limits.py:84-125`;
  - `core/controller.py:53-60, 206-223, 273-383, 400-443`;
  - `core/learning.py`;
  - `core/alarms.py:24-34`;
  - `core/installation.py:48-74`;
  - `config.py:200-247`;
  - `config_flow.py:232-246, 503-542, 1038-1090, 1395-1418`;
  - `control_config.py:34-48, 219-250`;
  - `vtherm_link.py:171-203`;
  - `sensor.py:458-498`;
  - `diagnostics.py:53-63`;
  - `control.py:168-190, 700-733, 989-1036`;
  - `__init__.py:22` (`PLATFORMS`), `entity.py:56-68` (`ControlEntity`) and `switch.py:30-40` (how a control entity is added).

**Order of work.**
1. Frost tests in `tests/core/test_limits.py` and `tests/core/test_controller.py`:
   - `test_a_cold_off_zone_with_its_valve_closed_gets_no_frost_heat`: A off, opening 0, device false, 4 °C; B heat at 20 °C not calling → CH off, A flagged as closed, no FROST reason.
   - `test_a_call_below_the_threshold_still_gets_frost_heat`.
   - `test_a_sleeping_valve_open_at_100_gets_frost_heat`.
   - `test_open_and_closed_cold_zones_together`: frost heats for the open one, the closed one is flagged; frost ends when the open one reaches 7 °C.
   - `test_vt_closing_the_zone_mid_frost_ends_frost_heating`.
   - `test_a_zone_whose_valve_state_cannot_be_read_is_heated_as_today` (negative): opening and device `None` → frost heats. An over_climate zone off, device false and no opening published → frost heats.
   - `test_a_heating_zone_with_a_closed_valve_cannot_take_heat`: heat mode, opening 0, device false, 4 °C → no frost heat, flagged.
   - `test_closes_when_off_makes_an_off_zone_closed`: the per-zone option on, off, no opening data → flagged, no heat.
   - `test_the_picked_frost_zone_closed_is_flagged`.
   - `test_frost_since_resets_at_hand_back` (P-45): frost for 90 min, a hand-back, a resume → `frost_stuck` only 2 h after the new start.
2. Integration frost tests:
   - `test_a_cold_zone_vt_keeps_closed_raises_a_repair_issue`: at the next step, naming the room and its temperature; no CH on; cleared at 7 °C or when the zone opens.
   - `test_no_closed_zone_issue_during_recognition`.
   - `test_the_frost_preset_clears_the_issue`.
   - Rewrite `test_acceptance.py:377` and `:423` for the closed case and the SLEEP case.
3. Activation delay tests, core:
   - `test_no_delay_by_default` (regression).
   - `test_the_delay_counts_from_the_first_call`: 120 s → off with `Reason.ACTIVATION_DELAY` through t0+110, on at t0+120.
   - `test_a_gap_neither_cancels_nor_restarts_the_wait`: call at t0, none at t0+60, back at t0+70 → on at t0+120.
   - `test_no_demand_at_the_end_drops_the_start`.
   - `test_stopping_is_never_delayed`.
   - `test_frost_heating_waits_too`, with `frost_since` from the real start.
   - `test_a_hand_back_a_blocker_or_switching_off_cancels_a_pending_start`.
   - `test_no_delay_for_a_command_restored_after_a_restart`.
   - `test_at_a_new_session_nothing_is_written_while_waiting`: `controlling` false, nothing owed.
   - `test_a_clock_jump_does_not_end_or_stretch_the_wait`: steps capped at 60 s.
   - `test_the_delay_waits_after_the_recognition_period`.
4. Activation delay tests, integration and flow:
   - `test_the_delay_is_pre_filled_from_vts_central_entry`: 120 → the form default is 120. Key missing, VT not loaded, not a number, or 900 → 0. A stored plugin value wins. Shown at the simple level.
   - `test_the_delay_is_refused_outside_0_to_600`.
   - The relay path shows the same field in its behaviour step: X8's `test_the_relay_path_shows_the_activation_delay`.
5. Other core tests:
   - `test_fallback_is_shown_only_while_heating` (P-47).
   - `test_the_fixed_fallback_applies_after_the_three_hour_hold` (S-26, decision 9): 48 °C set, outdoor lost → the curve's last value until 3 h, then 48.
   - `test_a_falling_weather_ceiling_ramps_down` (S-23): the ceiling drops by 24 K → the ramp at 1 K/min. `test_an_installation_cap_applies_at_once`: hard maximum, circuit maximum, boiler maximum.
   - `test_the_circuit_too_hot_alarm` (decision 10): max 40, alarm 45, 10 min; the flow at 46 for 9 min → off; 10 min → on; below 44 → off. No flow → inactive, reason `no_flow_reading`. No maximum → not created.
   - `test_heat_flows_by_the_flame_when_known` (S-24): flame off while CH is commanded → no rise; flame `None` → the command decides; DHW → no rise.
   - `test_only_zones_taking_heat_stop_the_rise` (S-08): a zone 2 K too warm with opening 0 (eco) → the rise goes on.
   - `test_the_correction_stays_while_a_cap_holds_the_setpoint` (T-48): circuit maximum equal to the curve, a saturated cold zone, 200 min → no rise, no "at limit".
   - `test_the_correction_does_not_rise_when_the_clock_goes_back` (T-18): the review's Given/When/Then as written.
   - `test_the_correction_rises_at_most_3_k_a_day`.
   - `test_the_correction_freezes_during_hot_water_and_foreign_heat`.
   - `test_the_correction_does_not_rise_while_the_boiler_clips`.
   - `test_reset_correction_clears_the_value_and_its_timers`: the pure `reset_correction` → correction 0, the "at limit" timer cleared; the rise may start again under its rules.
6. Learning tests in `tests/core/test_learning.py`:
   - `test_the_flow_condition_applies_to_hot_water_only` (P-89): after foreign heat, resume after the minimum pause with the flow at 30 against 45.
   - `test_the_hot_water_flow_wait_is_capped_an_hour_after_the_draw_ended`: a draw of 50 min, then the flow stays low → resume 60 min after the draw ended.
   - `test_a_short_draw_still_pauses_smartpi` (S-41).
   - Rewrite `test_learning_resumes_after_the_longest_pause_whatever_the_flow` (`:143`) for the cap counted from the draw's end.
7. Integration:
   - `test_the_comfort_correction_is_published` (P-38), as the attribute `comfort_correction` on `sensor.control_state` and in diagnostics.
   - `test_the_reset_button_resets_the_comfort_correction` (P-38, answer J): correction 2 K → press → 0 at once in the running control unit; no hand-back, no reload, no option saved; the status shows 0 at once.
   - `test_the_reset_button_exists_only_with_control_configured`: without control, no button entity. Negatives: control switched off (the correction is already 0) → pressing changes nothing and raises no error; while the control unit is unavailable, the button is unavailable (V6).

**Rules and values.**

Frost (decision 4):
- Watched zones: every zone, or the picked one, as now.
- A watched zone can take heat when VT reports an opening above 0 (`valve_open`, else `on_percent`) or `device_active` true. The mode alone never counts.
- A zone publishing no opening (valve state not readable) can take heat, as today, unless its option `closes_when_off` is on and VT has it off.
- Frost heating:
  - starts when a watched zone that can take heat is below the frost limit (5 °C);
  - continues while any such zone is below the release temperature (7 °C);
  - closed zones neither start it nor hold it;
  - does not start while Y1's boiler-protection "off" holds (the boiler's own fault stops it, frost heating included).
- `frost_not_warming` (2 h, 0.5 K) is computed over the zones that can take heat.
- The repair issue `frost_zone_closed_<entry_id>`:
  - it is raised at the next step when a watched zone below the frost limit cannot take heat, outside the recognition period, while control is configured and switched on (provisional, K4: not in monitor-only mode, where the plugin does no frost heating);
  - it names each room and its temperature;
  - it clears when the zone is at or above the release temperature, or can take heat.
- `_release` resets `frost`, `frost_since` and `frost_from` (P-45).

Activation delay (decision 5), option `activation_delay_s`:
- 0–600 s, step 10, default 0.
- It is in the `control_curve` step, which the simple level shows, and not in `CONTROL_ADVANCED_KEYS`, so "restore defaults" keeps it. On the relay path, whose curve step is hidden, X8 shows the same field, with the same pre-fill and range, in its behaviour step (decision 5).
- The form default is the stored value, else VT's `central_boiler_activation_delay_sec` read from VT's central entry by `vtherm_link` (a number 0–600), else 0. The user confirms by saving; the value is never taken at parse time.
- Semantics:
  - An off→on transition waits. The wait starts at the first step with heating wanted (demand or frost) while the command is off or there is none, after the recognition period.
  - Elapsed time is the sum of step durations, each capped at 60 s.
  - A call that drops and returns neither cancels nor restarts the wait. At its end heating goes on only if it is still wanted, else the pending start is dropped.
  - "On" to "off" is at once.
  - `_release` (hand-back, control switched off, a blocker) cancels a pending start.
  - A stale-link wait pauses it.
  - No delay for a command restored after a restart (X3).
  - At a new session with zones calling, nothing is written while waiting (provisional, K4). Mid-session, the current "off" goes on.
- Status: `Reason.ACTIVATION_DELAY`, mode IDLE, and the attribute `activation_at` (ISO time).

Fallback:
- FALLBACK only when heating is wanted and the outdoor temperature is unknown; otherwise IDLE (P-47).
- Decision 9 as the code does: the last value held 3 h, then the fixed value or the design flow.

Ramp: skipped only when the previous setpoint is above the lowest installation cap (hard maximum, circuit maximum, boiler maximum). A falling weather ceiling ramps down at the ramp's rate (S-23).

Circuit maximum (decision 10):
- The option text says it limits the setpoint and that the boiler may overshoot.
- New circuit options at the advanced level:
  - `max_flow_alarm` (°C; must be above `max_flow`, else the error `max_flow_alarm_not_above_max`);
  - `max_flow_alarm_min` (1–120 min, provisional, K4).
- Pre-filled when `max_flow` is first entered with `max_flow + 5 K` and 10 min, and not changed by itself later. The parser uses the same values when they are absent, so they are never empty.
- New `AlarmKind.CIRCUIT_TOO_HOT`:
  - active once the measured flow has stayed above the alarm temperature for the set time;
  - clears below the alarm temperature − 1 K (provisional, K4);
  - information only, added to `INFO_ONLY_ALARMS`;
  - created only for a circuit with a maximum;
  - the flow is the circuit's own flow entity where mapped, else the boiler flow for an unmixed circuit; a passive fixed circuit without its own flow entity is inactive, with its reason.

Comfort correction, principle 13 mapped:

| Rule | 0.2.2 |
|---|---|
| 1. band | 0 to +3 K (met) |
| 2. rate | +1 K per 30 min of heat flow, so at most 2 K/h (met); per day: at most +3 K rise within 24 h (built, provisional, K4) |
| 3. other criteria hold | comfort, as the rise only for a short saturated zone (met); no zone overheating, counting only zones taking heat (opening above `ZONE_OPEN` or device active), S-08 (built); cycling not rising: not applicable in 0.2.2, anti-cycling is decision 13's 0.3; every limit kept: no rise while an upper cap (hard, circuit, boiler, weather ceiling) or a clipped read-back holds the setpoint, and the "at limit" timer paused (built, S-25, T-48); step back: the fall (met) |
| 4. good-enough band | the rise stops once no zone is 0.3 K short (met) |
| 5. freezes | hot water and foreign heat: neither rise nor fall (built; foreign heat from the monitor's zone views, unknown means no freeze); data gaps: held while the link is stale or no zone is known (met); hand-back: reset (met); extreme weather: no agreed definition, named in "Open after 0.2.2" |
| 6. inform at the edge | `correction_at_limit` after 3 h at 3 K (met) |
| 7. visible and resettable, reset at hand-back | published as the attribute and in diagnostics (built); reset at hand-back and session end (met); reset on demand: the "Reset comfort correction" button (built, answer J) |

The table goes into the docstring of `core/controller.py`, and into `SCOPE.md` through Q1.

More correction rules:
- "Heat flows" (S-24, review question 3): the flame is true and hot water is not true. With the flame unknown: heating is commanded and hot water is not true.
- The rise and the fall count step durations capped at 60 s, never a negative time (P-46), replacing `now - decided_at` at 424.
- The reset button (answer J): pressing it sets the running unit's correction to 0 and clears its "at limit" timer. It saves no option, reloads nothing and hands nothing back. The rise may start again under its rules. While control does not run, the correction is already 0 and a press changes nothing.

Learning pauses per cause (P-89):
- DHW: pause while a draw runs and the zone's valve is open. Resume when the draw has ended, the minimum pause of 10 min has passed, and either the flow is within 3 K of the heating setpoint, or heating is off, or 1 h has passed since the draw ended (the anchor is provisional, K4).
- Foreign heat and water swing: resume when the cause is gone and the minimum pause has passed, with no flow condition.
- The causes of each pause are kept in `LearningState` and stored by V3. Unknown causes after a restart are treated as DHW.
- S-41: every draw pauses SmartPI, as the zones get no heat meanwhile. The spec text comes through Q1.

Values for S-37:
- decided: activation delay 0–600/10/0; frost opening above 0; alarm pre-fill +5 K and 10 min;
- kept as today: frost 5 and 7 °C; 2 h and 0.5 K; correction 3 K, 30 min per K and 3 h; minimum pause 10 min, 3 K; cap 1 h; 60 s step cap (`MAX_STEP_S`) for the delay and the correction;
- provisional, K4: the 1 K hysteresis; the 1–120 min range; 3 K a day; the DHW cap anchor; nothing written while waiting at a new session; the closed-zone issue only with control on.

**Code to change.**
- `core/limits.py:84-125`: `FrostConfig.closes_when_off: frozenset[str]`; `can_take_heat(zone, config)`; `frost_needed` and `watched_temperatures` over the zones that can take heat; a new `frost_closed(zones, now, config) -> tuple[str, ...]`.
- `core/controller.py`:
  - `_release` (206-223);
  - frost (269-300);
  - the delay state in `ControlState` and `ControlConfig.activation_delay_s`;
  - mode (345-352);
  - `_ramp` (431-443) with an `install_upper`;
  - `_correction` (408-428) and the heat flow (286-291);
  - a pure `reset_correction(state) -> ControlState`;
  - `ControlInputs.foreign_heat`, `clipped`;
  - `ControlDecision` gets `frost_closed`, `activation_at` and `correction`.
- `core/learning.py:106-173`: per-cause state and rules.
- `core/alarms.py`: `CIRCUIT_TOO_HOT` and its function.
- `core/installation.py`: `Circuit.max_flow_alarm`, `max_flow_alarm_s`.
- `config.py:200-247`: parse the circuit alarm keys and `closes_when_off` in the zone item.
- `control_config.py`: `activation_delay_s` in `CONTROL_DEFAULTS` (0); `INFO_ONLY_ALARMS` adds `circuit_too_hot`.
- `config_flow.py`:
  - `control_curve_schema` (503-542) adds `activation_delay_s`, with the pre-fill;
  - `circuit_schema` (232-246) adds the alarm fields at the advanced level;
  - `async_step_zone` (1038-1090) keeps a stored `closes_when_off` (not shown until X5).
- `vtherm_link.py`: `vt_central_activation_delay() -> float | None`.
- `control.py`: the frost repair issue; the correction status; foreign heat from `coordinator.data.zones`; the clip flag from X1; `reset_correction()`, which applies the pure function to the running session and pushes the status.
- `button.py` (new, approved by the user on 2026-09-27, answer J): `ResetCorrectionButton(ControlEntity, ButtonEntity)` with the key `reset_comfort_correction`, added in `async_setup_entry` only when `coordinator.control` is set (as `switch.py:30-40` does); `async_press` calls `control.reset_correction()`.
- `__init__.py:22`: `PLATFORMS` gains `"button"`.
- `icons.json`: an icon for the button.
- `sensor.py:458-498`: attributes `comfort_correction` and `activation_at` (unrecorded).
- `diagnostics.py:53-63`: the correction.

**Texts.**

| Key | en | pl |
|---|---|---|
| `options.step.control_curve.data.activation_delay_s` | Activation delay | Opóźnienie włączenia |
| `options.step.control_curve.data_description.activation_delay_s` | Seconds heating waits after the first call for heat, so slow valves (thermoelectric, underfloor) open before the boiler and its pump run — as Versatile Thermostat's central boiler did; pre-filled from VT's own setting where VT kept one. Stopping is never delayed. Default 0: at once. Risk: a zone whose heating pulse is shorter than the delay never starts the boiler, and pulses close to it give short burns; without a heating switch ("off" as a low setpoint) the pump may run anyway. | Sekundy, przez które grzanie czeka po pierwszym wezwaniu, aby wolne zawory (termoelektryczne, podłogówka) otworzyły się, zanim ruszą kocioł i pompa — jak w centralnym kotle Versatile Thermostat; wstępnie wypełnione ustawieniem VT, jeśli VT je zachował. Wyłączenie nigdy nie jest opóźniane. Domyślnie 0: od razu. Ryzyko: strefa z impulsem grzania krótszym niż opóźnienie nigdy nie uruchomi kotła, a impulsy niewiele dłuższe dają krótkie palenia; bez przełącznika grzania („wyłączone" jako niska nastawa) pompa i tak może pracować. |
| `options.step.control_curve.data_description.frost_zone` | Optional: watch only this zone for frost. Empty (default): every zone. Frost heating runs only for a cold room whose valve can open — Versatile Thermostat reports it open or its device on; a cold room VT keeps closed raises a repair issue instead. Frost heating that does not warm the room for two hours raises an alarm; it is never stopped. | Opcjonalnie: pilnuj przed mrozem tylko tej strefy. Puste (domyślnie): wszystkich stref. Grzanie przeciwmrozowe działa tylko dla zimnego pokoju, którego zawór może się otworzyć — Versatile Thermostat podaje go jako otwarty albo urządzenie jako włączone; zimny pokój, który VT trzyma zamknięty, zgłasza zamiast tego problem do naprawy. Grzanie, które przez dwie godziny nie ogrzewa pokoju, podnosi alarm; nigdy nie jest przerywane. |
| `issues.frost_zone_closed.title` | A room below the frost limit cannot get heat | Pokój poniżej progu mrozu nie może dostać ciepła |
| `issues.frost_zone_closed.description` | {zones}: Versatile Thermostat keeps the valve closed (the thermostat is off, or its target is below the frost limit), so the plugin cannot heat it and does not start the boiler for it. Use VT's frost preset instead of off; VT's central frost mode needs a frost temperature set in every thermostat. | {zones}: Versatile Thermostat trzyma zawór zamknięty (termostat wyłączony albo jego nastawa jest poniżej progu mrozu), więc wtyczka nie może go ogrzać i nie włącza dla niego kotła. Użyj presetu mrozowego VT zamiast wyłączenia; centralny tryb mrozowy VT wymaga ustawienia temperatury mrozowej w każdym termostacie. |
| `config.step.circuit.data_description.max_flow` and `options.step.circuit.data_description.max_flow` | The most this circuit may receive, in °C, e.g. underfloor heating on an unmixed loop: control never asks for more, but the boiler may overshoot it by its own hysteresis — set the alarm below to be told. Needed for underfloor on an unmixed loop. Too high overheats the floor. | Najwyższa temperatura dla tego obiegu, w °C, np. podłogówka bez mieszacza: sterowanie nigdy nie prosi o więcej, ale kocioł może ją przekroczyć o własną histerezę — ustaw alarm poniżej, aby o tym wiedzieć. Wymagane dla podłogówki bez mieszacza. Za wysoka przegrzewa podłogę. |
| `…circuit.data.max_flow_alarm` / `data_description` | Too hot alarm at / "Information alarm when the measured flow stays above this, in °C. Starts at the maximum + 5 °C. Needs a flow reading." | Alarm za gorąco od / „Alarm informacyjny, gdy zmierzone zasilanie utrzymuje się powyżej tej wartości, w °C. Na start maksimum + 5 °C. Wymaga odczytu zasilania." |
| `…circuit.data.max_flow_alarm_min` / `data_description` | For at least / "How long, in minutes, before the alarm rises. Starts at 10. Too short reports every overshoot of the boiler's hysteresis." | Przez co najmniej / „Po ilu minutach alarm się podnosi. Na start 10. Za krótko zgłasza każde przekroczenie z histerezy kotła." |
| `config.error.max_flow_alarm_not_above_max`, `options.error.…` | The alarm temperature must be above the circuit's maximum. | Temperatura alarmu musi być wyższa niż maksimum obiegu. |
| `entity.binary_sensor.alarm_circuit_too_hot.name` | Circuit water too hot | Za gorąca woda w obiegu |
| `entity.button.reset_comfort_correction.name` | Reset comfort correction | Wyzeruj korektę komfortu |
| `options.step.control_behaviour.data_description.comfort_correction` | reword to: "…only while heat flows (the flame, where known) … it never rises while another zone taking heat is more than 1 K too warm, nor while a limit holds the water, and at most 3 K a day; it holds during hot water and foreign heat; shown on the control state; resets at hand-back and with the 'Reset comfort correction' button…" | przeredaguj odpowiednio: „…tylko gdy płynie ciepło (płomień, jeśli znany) … nie rośnie, gdy inna strefa przyjmująca ciepło jest o ponad 1 K za ciepła, ani gdy limit trzyma wodę, i najwyżej 3 K na dobę; wstrzymuje się podczas ciepłej wody i obcego ciepła; widoczna w stanie sterowania; zeruje się przy oddaniu i przyciskiem „Wyzeruj korektę komfortu"…" |
| `options.step.control_behaviour.data_description.learning_pauses` | add: "After hot water it waits for the water to come back, at most an hour after the draw; after foreign heat or a swing, only the minimum pause." | dopisz: „Po ciepłej wodzie czeka na powrót temperatury wody, najwyżej godzinę po poborze; po obcym cieple lub wahaniu tylko minimalną przerwę." |

**Missing data.**
- Opening unpublished → frost heats, as today. Temperature missing or implausible → the zone is blind; the zone alarm after 30 min (X3).
- VT's stored delay missing or not a number → 0 is offered. The option missing → 0.
- Flame unknown → the command decides the heat flow.
- Foreign heat unknown → no freeze. Clip unknown → none.
- Flow reading missing or stale → `circuit_too_hot` is inactive, with its reason. No circuit maximum → no alarm entity.
- Flow unknown → the DHW flow wait passes, as today.
- Button pressed while control does not run → nothing to reset (the correction is 0).
- None of these switches heating off, except frost's closed zones, which get no heat because it cannot reach them (decision 4).

**Do not.**
- Restart the wait on a gap (rejected).
- Delay switching off.
- Switch VT to its frost preset (rejected: it would fight VT).
- Count the heat mode alone as open.
- Raise the closed-zone issue during recognition.
- Put the delay at the advanced level only, or take VT's value silently at parse time.
- Lower the setpoint to "maximum − overshoot" (decision 10 chose the text and the alarm).
- Resume learning during a continuing draw or foreign heat.
- Save an option, reload the entry or hand back to reset the correction.
- Run T-20 here (Z3).

**Open for the user.** None. The "Reset comfort correction" button in the new file `button.py` was approved on 2026-09-27 (answer J).

### X5 — Configuration refused in the form and among the blockers

**Goal and done-when.** Every dangerous or impossible combination the review names is refused where the user enters it (a translated error on the field that causes it), and — where options can reach the plugin without the form (a hand edit, options of an older version) — the same rule is a control blocker, so control never starts on it. Only where the monitor itself cannot run is it a `ConfigError`, as today's `unknown_signal`. Done when each item X5.1–X5.21 below has its form test (X5.21 is a runtime blocker only, with no form field) and, where marked "blocker", a blocker test, each with a negative test on a missing, unknown or `None` input; T-12, T-32, T-37 and T-38 pass; `scripts/env.sh python -m pytest -q` and `scripts/env.sh ruff check .` pass; X5 is marked ✅ in `docs/plan-0.2.2.md` and committed without waiting, its diff shown in the step's report (answer B of 2026-09-27); remainders are added by name to "Open after 0.2.2" (at least: a warning for zones not fed by the boiler, review question 19 — 0.3; already there as item 9).

**Read first.**
- Plan: X5 row; decisions 4 and 11, with answer O of 2026-09-27 (a boiler that ignores "heating off" from the start of the session is blocked like an installation without a working heating switch, the blocker naming the reason until the user switches control off and on); "The wall thermostat on a gateway" (a VT zone on the gateway's own thermostat entity is refused); Findings of the checks ("A VT zone built on the gateway's own thermostat entity … → X5"); "Rules that shape this release".
- Review: P-03, P-16, P-25, P-44, P-64, P-65, P-67, P-68, P-69, P-70, P-71, P-79, P-106 (§3.2, §3.3); S-12, S-39, S-42 (§3 and §4); T-12, T-32, T-37, T-38 (§6.1, §6.2); Appendix E questions 10 and 19.
- Research: `research/2026-09-26-wall-thermostat-vt-design.md` §3 recommendation 2, Verification → Missing ("the self-latch check has to be generic and run continuously … a runtime blocker") and → Unsupported (no gateway ID on the MQTT and entity paths); `research/2026-09-26-q4-decisions-4-5-frost-valves-activation-delay.md` "Recommended rule (C)"; `research/2026-09-27-fresh-session-test.md` "### X5"; `research/2026-09-27-plan-0.2.2-checks.md` (decision 4 item).
- Code: `config_flow.py` (whole file); `control_config.py:94-111, 130-172, 187-296, 317-374`; `config.py:140-247, 292-325, 360-366`; `transport/entities.py:38-65`; `transport/writers.py:141-214`; `control.py:485-506`; `__init__.py:248-259`; `vtherm_link.py:52-60` (the pattern for reading a VT entry's data); vendor VT `const.py:63` (`underlying_entity_ids`).

**Order of work.** Tests first; each named test is one Given/When/Then.
1. `tests/integration/test_config_flow.py`:
   - `test_same_switch_for_heating_and_external_control_is_refused` (T-38): Given the entity path with hand-back "switch", When `ch_entity` equals `hand_back_entity`, Then the error `hand_back_switch_is_heating_switch` on `hand_back_entity`; Negative: `hand_back_entity` empty → `hand_back_entity_missing` as today.
   - `test_one_entity_for_two_signals_is_refused` (T-32): Given the signals step, When `flame` and `ch_active` name one binary sensor, Then `entity_for_two_signals` on the later field; Negative: every field empty → accepted.
   - `test_options_save_problem_returns_to_its_step` (T-12): Given `chosen_zone` on zone A, When zone A is removed and saved, Then the reference form with `reference_zone_unknown`; after another strategy, CREATE_ENTRY.
   - `test_frost_release_must_be_above_the_limit` (T-37): Given the advanced level and a gateway path, When limit 7 and release 7, Then `frost_release_not_above_limit`.
   - `test_off_must_stay_below_the_lowest_water_temperature_at_every_level` (P-25): Given a path without heating writes and the simple level, When the lowest water temperature is set within 1 K of the stored or default "off", Then `off_setpoint_not_below_hard_min`; the same after "restore defaults" on the level form; Negative: with a heating switch nothing is checked.
   - `test_a_disabled_gateway_is_not_offered_and_mqtt_must_be_set_up` (P-69): Given a disabled `opentherm_gw` entry, Then it is not offered and typing its ID gives `gateway_unknown`; Given a not-loaded one, `gateway_not_set_up`; Given the MQTT path without a loaded MQTT entry, `mqtt_not_set_up`.
   - `test_an_unknown_stored_value_is_a_form_error` (P-70): Given options with `boiler.class = "steam"`, When any section is saved, Then the boiler form with `invalid_boiler`, no exception.
   - `test_entities_are_checked_on_the_server` (P-79): Given a non-VT climate submitted as a zone, Then `zone_not_vt`; a `sensor` submitted as `flame`, Then `entity_not_suitable`; Negative: an entity without a state yet but of the right domain is accepted.
   - `test_curve_cross_field_checks` (P-68): one case per rule of X5.8; Negative: the defaults with design flow 55 °C pass.
   - `test_the_gateway_field_takes_no_custom_value` (P-106): the schema's selector has `custom_value=False`.
   - `test_a_circuit_with_zones_cannot_be_removed` (P-64): Given two circuits with a zone on the second, When the advanced circuit step ends after the first, Then `circuit_has_zones`, nothing saved.
   - `test_restoring_defaults_keeps_the_monitoring_days` (P-65): Given `monitoring_days` 14 and `verdict_window_days` 30, When "restore defaults", Then both stay.
   - `test_an_edit_that_would_block_control_is_confirmed_first` (Open after R6 #3): Given control configured and allowed, When the boiler class is changed to read-only, Then the `confirm_blocking` form; `save_anyway` false → back to the menu, nothing saved; true → saved. Negative: an edit that adds no blocker saves at once.
   - `test_every_options_section_says_saving_hands_back` (P-67): every options step's description in `en.json` ends with the reload sentence of X5.13 (a text test over the keys).
   - `test_a_zone_built_on_the_boilers_thermostat_is_refused` (X5.19): Given a VT zone whose entry lists an `opentherm_gw` climate in `underlying_entity_ids`, Then `zone_on_boiler_thermostat`; Negative: a zone whose VT entry cannot be read is accepted.
   - `test_the_zone_step_offers_closes_when_off` (X5.20): the field is shown at both levels, default off, stored per zone, kept when the step is saved again.
2. `tests/test_control_config.py` (blockers for hand-edited options): `test_a_hand_back_switch_that_is_the_heating_switch_blocks` (X5.1), `test_the_topology_must_suit_the_path` (X5.4, `topology_not_for_path`), `test_control_without_a_heating_switch_is_blocked` (X5.16: entity path, `ch_entity` empty or its write type persistent/unknown → `no_heating_switch`; OTGW paths never), `test_curve_cross_field_blockers` (X5.8), `test_a_passive_fixed_circuit_floor_has_a_margin` (X5.14: fixed 45 °C → `circuit_floor` 50 °C; Negative: no fixed temperature → `ConfigError` as today); keep `test_every_blocker_is_listed` (`tests/test_control_config.py:161`) green with the new keys.
3. `tests/test_config.py`: `test_one_entity_for_two_signals_drops_the_later_one` (X5.2: the later signal in `SIGNAL_FIELDS` order is absent from the parsed signals, the feature that needs it is inactive and names it, and `config_blockers` lists `entity_for_two_signals`; no `ConfigError`, the monitor runs; Negative: two different entities → both kept, no blocker); `test_unknown_stored_values_name_their_section` (one case per code of X5.6).
4. `tests/integration/test_control.py`: `test_a_boiler_ignoring_heating_off_shows_the_blocker_until_off_and_on` (X5.21, answer O: with X1's latch `heating_off_ignored` set, `blocked_by` names `heating_off_ignored` with its text, through a restart; switching control off and on clears it; Negative: a stored latch without its cause is read as today's latch, not as this blocker); `test_a_zone_reconfigured_onto_the_boilers_thermostat_blocks_control` (runtime blocker, VT reconfigured without an options change); `test_a_gateway_entry_removed_or_disabled_blocks_control` (X5.5 runtime); `test_an_entity_writer_refuses_one_switch_in_two_roles` (a hand-back through such options fails and stays owed, no toggling every minute).
5. The code, in the order of the items; then the texts; then the key-parity tests (`tests/test_translations.py`).

**Rules and values.**
- **X5.1 One entity, one role (P-03, T-38).** `ch_entity`, `hand_back_entity` and `setpoint_entity` are pairwise different. Form: error on the later field; blocker `hand_back_switch_is_heating_switch` (hand-edited). `EntityWriter.__init__` (`transport/writers.py:149-160`) raises `ValueError` when two roles coincide, so a hand-back through such options fails, stays owed and is shown (repair issue, settled by hand) instead of toggling the switch every minute.
- **X5.2 One entity, one signal (P-16, T-32).** No signal pair may share an entity in 0.2.2 (the allow-list of "may feed both" is empty — provisional, K4): a shared entity would make, e.g., `dhw_now` (`coordinator.py:654-665`) never see "flame on, heating off". Form: `entity_for_two_signals` on the later field. Parse: `config._signals` (`config.py:184-197`) keeps the first signal in `SIGNAL_FIELDS` order and drops the later one, which is then inactive and named (Y4); control gets the config blocker `entity_for_two_signals`. Never a `ConfigError` that stops the entry: a shared entity does not stop the monitor, and a `ConfigError` at setup (`__init__.py:42-60`) would stop the monitor and leave an owed hand-back only reported. The weather entity is not a signal.
- **X5.3 "Off" and the lowest water temperature (P-25).** Decision 11 blocks control without a heating switch, so no configuration that may control writes "off" as a low setpoint in 0.2.2; the check stays for when L4's block is lifted: where the path has no heating writes, `off_setpoint` (stored, else 10 °C) must be at least 1 K below the lowest water temperature (X1's rule, P-43) — checked in `control_curve` at both levels, and after "restore defaults" on the level form.
- **X5.4 Path and topology (P-44).** `_PATH_TOPOLOGIES` (`config_flow.py:656-664`) moves to `control_config.py` as `PATH_TOPOLOGIES`; `config_blockers` adds `topology_not_for_path`. X8 adds the relay path, which has no topology.
- **X5.5 Gateway and MQTT set up and enabled (P-69).** The gateway step offers only `opentherm_gw` entries with `disabled_by is None`; a picked entry that is not `LOADED` → `gateway_not_set_up`. The MQTT step needs a loaded MQTT config entry → `mqtt_not_set_up`. Runtime blockers (`control.py:485-506`, added to `RUNTIME_BLOCKERS`): `gateway_not_set_up` when the entry for `gateway_id` is missing or disabled; `mqtt_not_set_up` when no MQTT entry exists or it is disabled. A gateway that is merely not loaded yet at start is covered by `ha_starting`; one offline later fails its writes as today.
- **X5.6 Unknown stored values (P-70).** Every enum parse in `config.py` (boiler class, DHW type, modulation scale, circuit control, emitter, foreign-heat kind, reference strategy) raises `ConfigError(code, key)` with `invalid_boiler` → boiler step, `invalid_circuit` → circuit, `invalid_zone` → zones, `invalid_reference` → reference, `invalid_monitor` → monitor (added to `_PROBLEM_STEPS`, `config_flow.py:908-920`); `validate_problem` (`config_flow.py:899-905`) also catches `KeyError`, `TypeError`, `ValueError` → `("unreadable_options", None)` on the signals step. Setup keeps its own handling (`__init__.py:42-61`).
- **X5.7 Entities checked on the server (P-79; review question 19).** One helper `entity_error(hass, entity_id, filter)` re-applies each field's selector filter on submit: the domain from the entity ID always; the integration from the entity registry's `platform`; the device class only when the entity has a state (an entity not reported yet passes on its domain). Error `entity_not_suitable`; for zones and the reference/frost zone `zone_not_vt` (only climates with `platform == versatile_thermostat`). Answer to question 19 (provisional, K4): zones are VT climates only; no warning for zones not fed by the boiler in 0.2.2 ("Open after 0.2.2", item 9, 0.3). Runtime blocker `zone_not_vt` for a hand-edited zone of another platform.
- **X5.8 Curve cross-field checks (P-68)** in `control_curve` (both levels) and as blockers (provisional, K4; S-37): design flow ≥ the curve's room temperature + 5 K (`design_flow_too_low`); design flow ≤ the highest water temperature (`design_flow_above_hard_max`: the curve would be cut off in frost); design outdoor ≤ the curve's room temperature − 10 K (`design_outdoor_too_warm`); lowest water temperature < design flow (`hard_min_not_below_design_flow`).
- **X5.9 Gateway field (P-106):** `custom_value=False` (`config_flow.py:484`).
- **X5.10 Circuits with zones (P-64):** at the end of the circuit steps, a circuit ID some zone still uses but the new list lacks → `circuit_has_zones` on the circuit form; nothing saved.
- **X5.11 Restore defaults (P-65):** `restore_advanced_defaults` (`config_flow.py:811-822`) keeps `monitoring_days` and `verdict_window_days` (the rest of the monitor section goes as today).
- **X5.12 An edit that would block control (Open after R6 #3).** In the options flow's save (`config_flow.py:1274-1278`), with a control section present: the config blockers of the new options minus those of the stored options; any new one → step `confirm_blocking` showing the first new blocker's translated text (read with `homeassistant.helpers.translation.async_get_translations` from `exceptions.blocked_<key>.message`) and the count of others; field `save_anyway` (default false). Only config blockers are compared (no runtime ones).
- **X5.13 Saves reload and hand back (P-67, review question 10; provisional, K4).** Every options save except the level still reloads (`__init__.py:248-259`) and, while control holds the boiler, hands it back and takes it again (a relay: its rest state, then the stored command at once, X8). The options menu and every section step say so. No reload without a hand-back in 0.2.2.
- **X5.14 Passive fixed circuit (S-42):** `circuit_floor = fixed_temperature + 5 K` (`FIXED_CIRCUIT_MARGIN_K`, provisional, K4; reason: a mixing valve needs supply water above its own target) at `control_config.py:214-218`.
- **X5.15 "Held" risks (S-12)** in the `write_type` and `ch_write_type` texts. "Held" means the device keeps the last value it was given (ESPHome, DIYLess and the like); EMS-ESP's flow setpoint `selflowtemp` is not held — it expires within about a minute and EMS-ESP never resends it — so the texts say to declare it expiring.
- **X5.16 Control without a heating switch (decision 11, S-39):** blocker `no_heating_switch` when `ch_writes` is false (`control_config.py:263-264`); such installations get the monitor. OTGW paths always have heating writes; the relay path (X8) is not concerned.
- **X5.17 One list of keys (P-71):** `control_config.py` gets `TARGET_KEYS` (the tuple at `config_flow.py:592-597` and `606-610`) and `HAND_BACK_KEYS` (`config_flow.py:431-434`); every use reads them. X6 and X8 add their keys there.
- **X5.18** T-12 and T-37 as listed.
- **X5.19 A VT zone on the boiler's or gateway's own thermostat entity (the wall-thermostat decision).** A zone is refused when its VT entry lists, in `underlying_entity_ids` (vendor VT `const.py:63`), a climate entity that (a) is registered by `opentherm_gw`, or (b) sits on the same Home Assistant device as an entity the plugin maps as a boiler signal or picks as a write target or read-back (provisional, K4: this also covers the OTGW firmware's MQTT climate and an EMS thermostat climate, which the plugin cannot name otherwise). Read through `vtherm_link.py` only (new `zone_underlying_entities(hass, zone)` modelled on `room_sensor`, `vtherm_link.py:52-60`). Form error `zone_on_boiler_thermostat`; runtime blocker `zone_on_boiler_thermostat`, checked at every step, since VT can be reconfigured without the plugin's options changing.
- **X5.20 "Closes when VT switches it off" (decision 4):** per-zone key `closes_when_off` (bool, default false), shown at both levels in the zone step (provisional, K4); X4 builds its effect in frost protection. If X4 has already added the key to `config._zones` (`config.py:220-247`) and the core, X5 adds only the field and texts; otherwise X5 adds the key too.
- **X5.21 A boiler that ignores "heating off" from the start (answer O, with decision 11).** Runtime blocker `heating_off_ignored` (added to `RUNTIME_BLOCKERS`), shown while X1's latch cause `heating_off_ignored` holds: the heating switch's "off" was ignored from the start of a session, so control was blocked and the boiler handed back with an alarm, as for an installation without a working heating switch (X5.16). It names the reason until the user switches control off and on after fixing it; it outlives reloads and restarts with the stored latch (V3). No form field: the form cannot know in advance that a boiler ignores "off". The monitor runs meanwhile.

Values for S-37's list: 5 K (X5.8 design flow over room), 10 K (X5.8 design outdoor under room), 5 K (X5.14), all provisional, K4.

**Code to change.** `config_flow.py`: `signals_schema`/`async_step_signals` (162-177, 971-985) duplicates; `control_entity_schema` and `control_details_error` (452-475, 693-720) X5.1; `control_gateway_schema` (478-490) and `async_step_control_gateway` (1339-1362) X5.5, X5.9; `async_step_control_mqtt` (1364-1393) X5.5; `_PATH_TOPOLOGIES`/`control_error` (654-682) X5.4; `validate_problem`/`_PROBLEM_STEPS` (899-927) X5.6; `async_step_circuit` (998-1029) X5.10; `zone_schema`/`async_step_zone` (260-300, 1038-1090) X5.19, X5.20; `zones_schema` step (1031-1036) X5.7; `async_step_control_curve` (1395-1418) X5.3, X5.8; `async_step_level` (1258-1264) X5.3; `restore_advanced_defaults` (811-822) X5.11; `async_step_save` (1274-1278) and a new `async_step_confirm_blocking` X5.12; the key tuples (431-434, 592-597, 606-610) X5.17. `control_config.py`: `CONFIG_BLOCKERS` (94-111, with `entity_for_two_signals`), `config_blockers` (317-374), `PATH_TOPOLOGIES`, `FIXED_CIRCUIT_MARGIN_K` (214-218), `TARGET_KEYS`, `HAND_BACK_KEYS`. `config.py`: `_signals` (184-197: keep the first, drop the later one, record the drop for the blocker), enum parses (146-152, 220-247, 292-325). `transport/writers.py:149-160`. `control.py:91-99, 485-506` (with `heating_off_ignored`, X5.21, read from X1's latch). `vtherm_link.py`: `zone_underlying_entities`. Translations `en.json`, then `pl.json`.

**Texts** (options and config `error` sections as each step exists there; blockers also as `exceptions.blocked_<key>.message` with `{others}`):
- `hand_back_switch_is_heating_switch` — en "The external control switch must not be the heating switch or the setpoint entity: handing back would switch it on and off for ever." / pl "Przełącznik sterowania zewnętrznego nie może być przełącznikiem ogrzewania ani encją nastawy: oddawanie sterowania przełączałoby go bez końca."
- `entity_for_two_signals` — en "One entity can feed only one signal: pick another entity, or leave this field empty." / pl "Jedna encja może zasilać tylko jeden sygnał: wybierz inną encję albo zostaw to pole puste." Blocker `blocked_entity_for_two_signals` — en "One entity feeds two signals, so the later one is not used. Pick another entity for it in the signals options. Other reasons: {others}." / pl "Jedna encja zasila dwa sygnały, więc późniejszy nie jest używany. Wybierz dla niego inną encję w opcjach sygnałów. Inne powody: {others}."
- `topology_not_for_path` (blocker) — en "The gateway connection does not suit the write path." / pl "Podłączenie bramki nie pasuje do ścieżki zapisu."
- `gateway_not_set_up` — en "This gateway's OpenTherm Gateway integration is not set up, not running or disabled." / pl "Integracja OpenTherm Gateway tej bramki nie jest skonfigurowana, nie działa albo jest wyłączona."
- `mqtt_not_set_up` — en "The MQTT integration is not set up: the commands would go nowhere." / pl "Integracja MQTT nie jest skonfigurowana: polecenia nie trafiłyby nigdzie."
- `invalid_boiler`, `invalid_circuit`, `invalid_zone`, `invalid_reference`, `invalid_monitor`, `unreadable_options` — en "A value saved here is not one this version knows; choose it again." / pl "Zapisana tu wartość jest nieznana tej wersji; wybierz ją ponownie."
- `entity_not_suitable` — en "This entity is not of a kind this field takes." / pl "Ta encja nie jest rodzaju, który przyjmuje to pole."
- `zone_not_vt` — en "Only Versatile Thermostat thermostats can be zones." / pl "Strefą może być tylko termostat Versatile Thermostat."
- `design_flow_too_low` — en "The design flow temperature must be at least 5 K above the curve's room temperature." / pl "Projektowa temperatura zasilania musi być co najmniej 5 K wyższa od temperatury pokojowej krzywej."
- `design_flow_above_hard_max` — en "The design flow temperature is above the highest water temperature, so the curve would be cut off in frost. Raise the highest water temperature or lower the design flow." / pl "Projektowa temperatura zasilania jest wyższa od najwyższej temperatury wody, więc w mróz krzywa zostałaby obcięta. Podnieś najwyższą temperaturę wody albo obniż temperaturę projektową."
- `design_outdoor_too_warm` — en "The design outdoor temperature must be at least 10 K below the curve's room temperature." / pl "Projektowa temperatura zewnętrzna musi być co najmniej 10 K niższa od temperatury pokojowej krzywej."
- `hard_min_not_below_design_flow` — en "The lowest water temperature must be below the design flow temperature." / pl "Najniższa temperatura wody musi być niższa od projektowej temperatury zasilania."
- `circuit_has_zones` — en "Zones still use a circuit you left out: move them to another circuit in the zones step first." / pl "Strefy nadal używają pominiętego obiegu: najpierw przenieś je do innego obiegu w kroku stref."
- `zone_on_boiler_thermostat` — en "This Versatile Thermostat zone is built on the boiler's or gateway's own thermostat entity: it would ask for heat whenever the flame burns. Build the zone on a room sensor and its valves or radiator thermostats instead." / pl "Ta strefa Versatile Thermostat jest zbudowana na encji termostatu samego kotła lub bramki: prosiłaby o ciepło zawsze, gdy pali się płomień. Zbuduj strefę na czujniku pokojowym i jej zaworach albo głowicach."
- `no_heating_switch` (blocker) — en "Control needs a heating switch that the boiler does not store in its memory. Without one, \"off\" would be a low setpoint, and whether that stops the boiler and its pump is not known yet. The monitor keeps running. Other reasons: {others}." / pl "Sterowanie wymaga przełącznika ogrzewania, którego kocioł nie zapisuje w pamięci. Bez niego „wyłączone” byłoby niską nastawą, a nie wiadomo jeszcze, czy to zatrzymuje kocioł i jego pompę. Monitor działa dalej. Inne powody: {others}."
- `heating_off_ignored` (blocker, X5.21) — en "From the start of the session the boiler did not take the plugin's \"heating off\", so the plugin could not switch heating off. Control stopped and the boiler was handed back. Check the heating switch picked in the options and the boiler's settings, then switch control off and on. The monitor keeps running. Other reasons: {others}." / pl "Od początku sesji kocioł nie przyjął polecenia wtyczki „wyłącz grzanie”, więc wtyczka nie mogła wyłączyć ogrzewania. Sterowanie się zatrzymało, a kocioł został oddany. Sprawdź przełącznik ogrzewania wybrany w opcjach i ustawienia kotła, a potem wyłącz i włącz sterowanie. Monitor działa dalej. Inne powody: {others}."
- Step `confirm_blocking` — title en "This change stops control" / pl "Ta zmiana zatrzymuje sterowanie"; description en "With this change control cannot run: {first} ({more} other reasons). Saving hands the boiler back now." / pl "Po tej zmianie sterowanie nie może działać: {first} (innych powodów: {more}). Zapisanie od razu oddaje kocioł."; field `save_anyway` en "Save anyway" / pl "Zapisz mimo to".
- The options menu and every section's description end with en "Saving reloads the integration: while control holds the boiler, it is handed back and taken again (a relay goes to its rest state and back)." / pl "Zapisanie przeładowuje integrację: gdy sterowanie trzyma kocioł, zostaje on oddany i przejęty ponownie (przekaźnik przechodzi w stan spoczynkowy i z powrotem)."
- `write_type` and `ch_write_type` descriptions add (S-12) en "Held: the device keeps the last value it was given (ESPHome, DIYLess and the like). EMS-ESP's flow setpoint (selflowtemp) is not held — it expires within about a minute — so declare it expiring. Held: risks — a boiler parameter kept in its memory but declared held is written at every change and wears the memory (e.g. EMS-ESP's heating temperature parameter); and the last held value, \"off\" included, stays on the boiler while Home Assistant is down." / pl "Trzymany: urządzenie zachowuje ostatnią podaną wartość (ESPHome, DIYLess i podobne). Nastawa zasilania EMS-ESP (selflowtemp) nie jest trzymana — wygasa po mniej więcej minucie — więc zadeklaruj ją jako wygasającą. Trzymany: ryzyka — parametr zapisywany w pamięci kotła, a zadeklarowany jako trzymany, jest zapisywany przy każdej zmianie i zużywa pamięć (np. parametr temperatury grzania w EMS-ESP); a ostatnia trzymana wartość, także „wyłączone”, zostaje w kotle, gdy Home Assistant nie działa."
- `fixed_temperature` description adds en "The boiler's water is kept at least 5 K above it, so the mixing valve can reach it." / pl "Woda z kotła jest utrzymywana co najmniej 5 K wyżej, żeby zawór mieszający mógł ją osiągnąć."
- Zone field `closes_when_off` — en "Closes when VT switches it off" / "Tick if this zone's valve or emitter closes whenever Versatile Thermostat switches the zone off, although VT does not report its opening (e.g. a radiator thermostat VT turns off). Frost protection then does not heat for this zone while VT keeps it off, and raises a repair issue instead. Off (default): the zone is heated in frost as before, which may run the boiler against a closed valve." / pl "Zamyka się, gdy VT ją wyłącza" / "Zaznacz, jeśli zawór lub grzejnik tej strefy zamyka się zawsze, gdy Versatile Thermostat wyłącza strefę, choć VT nie podaje jej otwarcia (np. głowica, którą VT wyłącza). Ochrona przed mrozem nie grzeje wtedy dla tej strefy, dopóki VT trzyma ją wyłączoną, i zamiast tego zgłasza problem do naprawy. Wyłączone (domyślnie): strefa jest grzana w mróz jak dotąd, co może pracować kotłem na zamknięty zawór."

**Missing data.** A role or signal field left empty is never a duplicate. An entity mapped to two signals is kept for the first only; the later signal is inactive and named, and control is blocked (X5.2); the monitor runs. An entity without a state yet is checked by domain and registry only. A VT zone whose entry or `underlying_entity_ids` cannot be read (VT not loaded, older VT) is accepted and not blocked — the check repeats at every step. A missing `opentherm_gw` entry is an error in the form and a blocker at run time. A zone opening VT does not report, with `closes_when_off` off, is heated in frost as today (decision 4). A curve without a design flow keeps today's `curve_not_entered`. None of these switches heating off by itself; a blocker hands back as blockers do today. `heating_off_ignored` (X5.21) is not missing data: it rests on a known read-back that never showed "off" after each of the session's first 3 sends; an unknown read-back never sets it (X1).

**Do not.** Allow any signal pair to share an entity; stop the entry with a `ConfigError` for a shared entity; add the "zones not fed by the boiler" warning (0.3); reload without a hand-back (the other half of P-67); write "off" as a low setpoint (decision 11); rename stored option keys (`hard_min` stays); read VT's data anywhere but `vtherm_link.py`; switch VT's mode or write to VT.

**Open for the user.** None (the answers to review questions 10 and 19 are built as written and confirmed at K4). Answer O of 2026-09-27 (a boiler that ignores "heating off" from the start is blocked until the user switches control off and on) is built as X5.21, with X1.

---

### X6 — Thermostat kind, the OTGW heating override held, the lowest water temperature, the wall thermostat

**Goal and done-when.** Both gateway topologies ask what is wired to the gateway's thermostat terminals, and control is blocked for an on/off contact and for "I don't know" (S-01); a gateway entry without an answer keeps control stopped, with a notice asking for it (answer K of 2026-09-27); the OTGW heating override `CH=` is modelled as held, not expiring; the lowest water temperature is one setting with a 20 °C default, both risks in its text, and a "suggest" mode that shows evidence and a value the user enters and changes nothing by itself (S-02, S-56); the wall thermostat's fallback temperature is shown from the existing optional signal, with a warning when it is unknown or low, and the form states what the wall thermostat does. Done when every test below passes with its negative cases, T-07 is handed to Z3, the tests and ruff pass through `scripts/env.sh`, X6 is marked ✅ and committed (diff in the report), remainders named in "Open after 0.2.2".

**Read first.**
- Plan: decisions 1 and 2; "The wall thermostat on a gateway"; X6 row; Findings (OTGW `CH=`, `control_config.py:208-209`, `core/loop.py:115-117`; `config_flow.py:93-94`); Q3 (the generic rule for the lowest water temperature); "Open after 0.2.2" items 3, 4, 6.
- Review: S-01, S-02 (§3.1, §4), S-56, S-58 (rule 7 is Q1's), T-07 (Z3).
- Research: `research/2026-09-26-q4-decisions-1-2-otgw-thermostat-kind-lowest-water.md` — Decision 1 (a)–(d) and "Tests"; Decision 2 (c) and (e); Verification → Corrections (the kind asked in both topologies; `CH=` is not a lapsing override; the suggestion worded per source, never a parallel shift, none while stand-alone is handed back) and → Missing (valves as an input; `unstable_ignition` is Y1's); `research/2026-09-26-wall-thermostat-device.md` Verification → Corrections 1–3 (read the thermostat-side "Room setpoint 1", not the climate target; hot water still works) and → Missing (T0 needs no new field; `TrSet_thermostat`); `research/2026-09-26-wall-thermostat-vt-design.md` Corrections (the off switch does nothing for heating); `research/2026-09-27-fresh-session-test.md` "### X6".
- Code: `control_config.py:34-48, 60-65, 130-172, 187-296 (207-212), 317-374`; `core/loop.py:110-125`; `transport/writers.py:9-18`; `config_flow.py:80-96 (room_setpoint at 93), 437-449, 503-542, 585-601, 667-682, 1133-1135`; `core/limits.py:49-78`; `core/cycles.py:35-45, 105-136`; `core/alarms.py:151-157` (`_asked_throughout`); `core/verdict.py:63-76`; `coordinator.py:491-530, 717-805`; `switch.py:57-69`; `__init__.py:90-107`; `en.json:32, 49, 272, 289, 469-475, 511, 532, 546`.

**Order of work.**
1. `tests/test_control_config.py`:
   - `test_the_thermostat_kind_decides_whether_a_gateway_may_be_controlled`: Given `gateway_with_thermostat` or `gateway_standalone` and a kind `on_off`, `unknown`, missing or unreadable, When `config_blockers`, Then `thermostat_on_off` / `thermostat_kind_unknown`; `opentherm` with a thermostat and `none` stand-alone → neither.
   - `test_a_kind_that_contradicts_the_topology_blocks`: `opentherm` + stand-alone, `none` + with thermostat → `thermostat_kind_contradicts_topology`.
   - `test_no_kind_is_needed_without_a_gateway_topology`: `virtual` without a kind → no kind blocker.
   - `test_the_otgw_heating_override_is_held`: both OTGW paths → setpoint guard `EXPIRING`, switch guard `HELD`, `ch_writes` true.
   - `test_the_lowest_water_temperature_defaults_to_20`: `CONTROL_DEFAULTS["hard_min"] == 20.0`; parsed without `hard_min` → 20.
2. `tests/core/test_loop.py`: `test_a_recovered_setpoint_still_resends_the_heating_override`: Given CH held and the setpoint back at its pre-session value after a gateway reset, When the step resends the setpoint, Then heating on/off is resent too (a PIC reset loses both).
3. `tests/integration/test_config_flow.py`: `test_the_thermostat_kind_is_asked_for_a_gateway` (gateway topology without a kind → `thermostat_kind_missing`; a contradicting kind → `thermostat_kind_contradicts_topology`; `virtual` drops the key).
4. `tests/integration/test_control.py`: `test_a_gateway_entry_without_a_kind_is_blocked_and_told`: Given stored gateway options without a kind, When the entry starts, Then the blocker `thermostat_kind_unknown` and the repair issue `thermostat_kind_missing`, and an owed hand-back still sends V5's safe hand-back, `CS=<lowest>`, `CH=1`, `CS=0`.
5. `tests/integration/test_setup.py`: `test_migration_keeps_the_floor_of_a_control_section_without_it`: a minor-version-2 entry with a control section without `hard_min` → 25.0 after migration; with 30 → unchanged; without control → no key.
6. `tests/core/test_lowest_water.py` (new module, `core/` is in the agreed layout):
   - `test_no_suggestion_without_enough_burns` (19 counted → `no_data`, value `None`);
   - `test_short_burns_at_the_floor_suggest_two_kelvin_more` (30 counted, 70 % short → floor + 2 K);
   - `test_burns_ended_by_demand_or_hot_water_do_not_count`;
   - `test_missing_flame_flow_or_setpoint_names_what_is_missing` (each `None` → `inactive` with the signal named);
   - `test_the_suggestion_stays_under_the_caps`;
   - `test_no_suggestion_while_standalone_is_handed_back`;
   - `test_the_boilers_own_curve_is_judged_from_its_reported_setpoint`.
7. `tests/core/test_lowest_water.py` (or a small `wall_thermostat_fallback` function beside it): `test_the_wall_thermostat_fallback_is_shown_and_warned`: not mapped → `not_mapped`; `None` → `unknown`; 12 °C → `low`; 20 °C → no warning.
8. `tests/integration/test_control.py`: `test_the_switch_shows_the_wall_thermostat_fallback` (attributes; the repair issue after 30 min unknown or low; none with `virtual` or stand-alone); `tests/integration/test_no_writes.py`: `test_the_suggestion_calls_no_service`.
9. Code, texts, key parity.

**Rules and values.**
- **Thermostat kind (decision 1).** Key `thermostat_kind` in the control section; values `opentherm`, `on_off`, `none`, `unknown`; asked in the first control step whenever the topology is `gateway_standalone` or `gateway_with_thermostat`, on every write path that takes those topologies (entity, `opentherm_gw`, `otgw_mqtt`); no default — missing with a gateway topology is a form error `thermostat_kind_missing`. `virtual` (and the relay path, X8) drops the key. Blockers: `on_off` → `thermostat_on_off`; `unknown`, missing or unreadable → `thermostat_kind_unknown` (parse never raises for it: an unreadable value is `unknown`); `opentherm` + stand-alone or `none` + with a thermostat → `thermostat_kind_contradicts_topology` (form error of the same key, with the hint to pick the other topology). The monitor works as before. A stored gateway control section without the key raises the repair issue `thermostat_kind_missing` (error, not fixable) at setup, and control stays stopped until the user answers (answer K of 2026-09-27); the issue goes once the key is set. An owed hand-back still runs, as it comes before the blockers (`control.py:586-589`).
- **OTGW `CH=` held.** `control_config.py:208-209` becomes `write_type = WriteType.EXPIRING` (CS lapses unless repeated within a minute) and `ch_write_type = WriteType.HELD` (the PIC keeps `CH=` until `CH=1` or a reset; not stored, so the heating switch stays usable). `ch_writes` stays true (`HELD` is writable). X1's rule — held values sent again after the device returns and every 5 minutes (X1; provisional, K4), no echo required — now covers `CH=`; a gateway reset is X1's "lost command" trace. `core/loop.py:115-117` keeps its resend; only its comment changes ("a PIC reset loses `CS` and `CH` together"). `transport/writers.py:9-17` already says it right.
- **Lowest water temperature (decision 2).** The setting is today's `hard_min` (key unchanged, 10–50 °C), label "Lowest water temperature", default 20.0 °C (`control_config.py:36`). Entries set up through the form store it explicitly (`config_flow.py:520`, `626-629`) and keep their value; the entry migration to minor version 3 (`__init__.py:90-107`, `config_flow.py:1135`) writes 25.0 into a control section without the key, so no installation's floor drops silently (provisional, K4). No mode option in 0.2.2 ("apply" comes in 0.3 with its option).
- **The "suggest" evidence (pure function in `core/lowest_water.py`; every number provisional, K4, S-37).**
  - Window: the last 7 days of the history, evaluated with the periodic analysis (`coordinator.py:759-805`).
  - A burn counts when: it is a complete heating burn (`find_burns` and `classify_burns`, CH kinds); the zones asked for heat throughout it and at its end (`_asked_throughout`, `core/alarms.py:151-157`); the setpoint in force at its start was within 1 K of the reference; it ended on temperature (flow at its end ≥ setpoint − 1 K); and, where any calling zone reports an opening, at least one calling zone was ≥ 50 % open during it (valves as an input; zones that report no opening do not exclude the burn).
  - The setpoint source: the `ch_setpoint` signal where mapped; else, under control, the control's setpoint read-back (`confirmed_entity`), which the coordinator then also records into the history; else the feature is inactive naming `ch_setpoint`.
  - The reference: under control, the lowest water temperature set; where the boiler's own curve sets the water (monitor only, control off or not allowed, any class), the lowest setpoint the source showed during counted heating burns.
  - Qualifies with ≥ 20 counted burns (`VerdictOptions.min_heating_burns`, `core/verdict.py:66`) and a short share (burns shorter than the monitor's `short_burn_min`, default 10 min) > 0.5 (`core/verdict.py:69`).
  - Suggested value: reference + 2 K, rounded up to 0.5 °C, never above min(highest water temperature, circuit maximum) − 2 K nor 50 °C; where Q3 recorded a generic rule and its inputs exist, its estimate is shown beside it as `estimate_from_power`, never applied.
  - No suggestion while a stand-alone installation is handed back (topology `gateway_standalone` and control not controlling): nothing heats then.
  - Output: sensor `lowest_water_suggestion` (°C; unknown without a suggestion) with attributes `state` (`suggestion`, `good_enough`, `no_data`, `inactive`, `not_applicable`), `counted_burns`, `short_share`, `reference`, `source`, `window_days`, `missing`, `estimate_from_power`; and a repair issue (warning, not fixable) while `state` is `suggestion`: `lowest_water_suggestion` under control, `lowest_water_suggestion_boiler` where the boiler's own curve rules. Nothing is written; the writer services are unchanged.
- **Wall thermostat fallback.** Only with topology `gateway_with_thermostat` and kind `opentherm`. The control switch gets attributes `wall_thermostat_setpoint` (°C from `Signal.ROOM_SETPOINT`, or `None`) and `wall_thermostat_warning` (`not_mapped`, `unknown`, `low` or `None`). `low` = below 15 °C (provisional, K4; reason: below comfort, the house cools after a hand-back). A repair issue (warning, not fixable) `wall_thermostat_fallback` / `wall_thermostat_fallback_unknown` when the mapped value has been low or unknown for 30 min (provisional, K4); none for `not_mapped` (the missing-data rule: inactive, naming the signal). The signal's description names the thermostat-side sensor ("Room setpoint 1" on the gateway's thermostat device; the firmware's `TrSet_thermostat` with separate sources); never the `opentherm_gw` climate target, which shows a value the thermostat may not have taken.
- **Form texts on the wall thermostat:** while the plugin controls, its heating setting and its off switch do nothing and its hot-water settings still work; after a hand-back or while Home Assistant is down it heats by its own setting and program.

Values for S-37's list: 7 days, 20 burns, 0.5 share, 1 K band, 1 K "ended on temperature", 50 % opening, +2 K, 2 K under the caps, 15 °C, 30 min, 25 °C migration floor — all provisional, K4. (The 5-minute resend of held values is X1's.)

**Code to change.** `control_config.py`: `ThermostatKind` enum, `ControlOptions.thermostat_kind`, parse, three blockers in `CONFIG_BLOCKERS` (94-111), `CONTROL_DEFAULTS["hard_min"]` (36), write types (208-209). `config_flow.py`: `control_schema` (437-449) optional select `thermostat_kind`; `control_error` (667-682); `apply_control` (585-601) keeps or drops the key; `MINOR_VERSION = 3` (1135). `__init__.py:90-107` migration. `core/loop.py:115-117` comment. New `core/lowest_water.py`; `coordinator.py` records the setpoint source and runs the evaluation with the analysis; `sensor.py` the new sensor; `switch.py:57-69` the two attributes; issues raised from the coordinator. Translations.

**Texts.**
- Control step field `thermostat_kind` — en "What is wired to the gateway's thermostat terminals" / "Only for a gateway, with a thermostat or stand-alone. OpenTherm thermostat: it talks to the boiler and may show the water temperature. On/off contact: a simple thermostat or switch on two wires — the gateway turns it into a heating request, and the plugin's \"heating off\" would block it after a Home Assistant crash, so control is not offered. Nothing: no thermostat at all. I don't know: control is not offered until you check. With a thermostat pick OpenTherm; stand-alone pick Nothing." / pl "Co jest podłączone do zacisków termostatu bramki" / "Tylko dla bramki, z termostatem albo samodzielnej. Termostat OpenTherm: rozmawia z kotłem i może pokazywać temperaturę wody. Styk wł./wył.: prosty termostat lub włącznik na dwóch przewodach — bramka zamienia go w żądanie grzania, a „wyłączone ogrzewanie” wtyczki blokowałoby go po awarii Home Assistant, więc sterowanie nie jest dostępne. Nic: brak termostatu. Nie wiem: sterowanie nie jest dostępne, dopóki tego nie sprawdzisz. Z termostatem wybierz OpenTherm; bez termostatu wybierz Nic."
- Selector `thermostat_kind`: `opentherm` "OpenTherm thermostat" / "Termostat OpenTherm"; `on_off` "On/off contact (two wires)" / "Styk wł./wył. (dwa przewody)"; `none` "Nothing" / "Nic"; `unknown` "I don't know" / "Nie wiem".
- Errors: `thermostat_kind_missing` en "Say what is wired to the gateway's thermostat terminals." / pl "Podaj, co jest podłączone do zacisków termostatu bramki."; `thermostat_kind_contradicts_topology` en "This answer does not fit the gateway connection: an OpenTherm thermostat means \"Gateway with a thermostat\", nothing means stand-alone. Pick the other connection." / pl "Ta odpowiedź nie pasuje do podłączenia bramki: termostat OpenTherm oznacza „Bramka z termostatem”, brak termostatu oznacza pracę samodzielną. Wybierz drugie podłączenie."
- Blockers: `blocked_thermostat_on_off` en "An on/off contact is wired to the gateway's thermostat terminals: the gateway's \"heating off\" would block it after a Home Assistant crash, so control is not offered. The monitor keeps running. Other reasons: {others}." / pl "Do zacisków termostatu bramki podłączony jest styk wł./wył.: „wyłączone ogrzewanie” bramki blokowałoby go po awarii Home Assistant, więc sterowanie nie jest dostępne. Monitor działa dalej. Inne powody: {others}."; `blocked_thermostat_kind_unknown` en "Control waits until you say, in the control options, what is wired to the gateway's thermostat terminals. Other reasons: {others}." / pl "Sterowanie czeka, aż w opcjach sterowania podasz, co jest podłączone do zacisków termostatu bramki. Inne powody: {others}."; `blocked_thermostat_kind_contradicts_topology` = the error text + `{others}`.
- Issue `thermostat_kind_missing` — en title "Say what is wired to the gateway's thermostat terminals" / description "Control of the boiler waits for the answer to a new question in the control options: what is wired to the gateway's thermostat terminals. Without a thermostat (stand-alone) the boiler does not heat meanwhile." / pl "Podaj, co jest podłączone do zacisków termostatu bramki" / "Sterowanie kotłem czeka na odpowiedź na nowe pytanie w opcjach sterowania: co jest podłączone do zacisków termostatu bramki. Bez termostatu (praca samodzielna) kocioł do tego czasu nie grzeje."
- `hard_min` label en "Lowest water temperature" / pl "Najniższa temperatura wody"; description en "The lowest water temperature the plugin sets, in °C, set like a point of the curve. Default 20 °C. Too low: in mild weather the boiler stops by itself again and again, and a boiler that is not condensing condenses in its flue — take the value from its manual. Too high: water warmer than the rooms need, and more gas. When the boiler keeps stopping at this temperature, the plugin shows its evidence and a suggested value; it never changes this setting itself." / pl "Najniższa temperatura wody, jaką ustawia wtyczka, w °C — ustawiana jak punkt krzywej. Domyślnie 20 °C. Za niska: przy łagodnej pogodzie kocioł raz po raz sam się wyłącza, a kocioł niekondensacyjny skrapla spaliny w przewodzie kominowym — weź wartość z jego instrukcji. Za wysoka: woda cieplejsza, niż potrzebują pokoje, i więcej gazu. Gdy kocioł wciąż się wyłącza przy tej temperaturze, wtyczka pokazuje dowody i proponowaną wartość; sama nigdy nie zmienia tego ustawienia."
- `topology` description adds en "With a thermostat: while the plugin controls, the wall thermostat's heating setting and its off switch do nothing — its hot-water settings still work; after a hand-back, or while Home Assistant is down, it heats by its own setting and program, so keep them at what the house should get." / pl "Z termostatem: gdy steruje wtyczka, nastawa ogrzewania termostatu ściennego i jego wyłącznik nic nie robią — ustawienia ciepłej wody nadal działają; po oddaniu sterowania albo gdy Home Assistant nie działa, termostat grzeje według własnej nastawy i programu, więc ustaw je tak, jak ma być w domu."
- `gateway_id` description adds en "Heating on/off (CH=) is kept by the gateway until it changes or the gateway restarts; the plugin sends it again after the gateway returns and every 5 minutes." / pl "Włączenie ogrzewania (CH=) bramka trzyma, dopóki się nie zmieni albo bramka nie uruchomi się ponownie; wtyczka wysyła je znowu po powrocie bramki i co 5 minut."
- `room_setpoint` signal description (config and options) en "The room setpoint of a wall thermostat on the gateway, from the thermostat's side — e.g. \"Room setpoint 1\" on the gateway's thermostat device, or the firmware's TrSet_thermostat with separate sources on; not the gateway's climate target. Shown as the temperature the wall thermostat keeps after a hand-back." / pl "Nastawa pokojowa termostatu ściennego przy bramce, od strony termostatu — np. „Room setpoint 1” na urządzeniu termostatu bramki albo TrSet_thermostat firmware'u z włączonymi osobnymi źródłami; nie cel encji climate bramki. Pokazywana jako temperatura, którą termostat ścienny utrzyma po oddaniu sterowania."
- Switch attributes: `wall_thermostat_setpoint` en "Wall thermostat after hand-back" / pl "Termostat ścienny po oddaniu sterowania"; `wall_thermostat_warning` states `not_mapped` "Not known: map the wall thermostat's setpoint" / "Nieznana: przypisz nastawę termostatu ściennego", `unknown` "The wall thermostat reports no setpoint" / "Termostat ścienny nie podaje nastawy", `low` "Below 15 °C: the house cools after a hand-back" / "Poniżej 15 °C: po oddaniu sterowania dom się wychłodzi".
- Issues `wall_thermostat_fallback` en "The wall thermostat would keep the house cool after a hand-back" / "The wall thermostat on the gateway is set to {value} °C. After a hand-back, or while Home Assistant is down, it heats the house by this setting and its own program. Set it to what the house should get." / pl "Termostat ścienny utrzymałby w domu chłód po oddaniu sterowania" / "Termostat ścienny przy bramce ma nastawę {value} °C. Po oddaniu sterowania albo gdy Home Assistant nie działa, grzeje dom według tej nastawy i własnego programu. Ustaw ją tak, jak ma być w domu."; `wall_thermostat_fallback_unknown` with "reports no setpoint" instead of the value.
- Sensor `lowest_water_suggestion` en "Suggested lowest water temperature" / pl "Proponowana najniższa temperatura wody". Issue `lowest_water_suggestion` en title "The boiler keeps stopping at the lowest water temperature" / description "In the last {days} days, {short} of {burns} heating burns at about {reference} °C were shorter than {limit} min and ended because the water was warm enough, while rooms still asked for heat. Consider raising the lowest water temperature to about {value} °C in the control options. Longer burns are likely; fewer starts are not guaranteed. Nothing changes until you do." / pl "Kocioł wciąż się wyłącza przy najniższej temperaturze wody" / "W ostatnich {days} dniach {short} z {burns} cykli grzania przy około {reference} °C trwało krócej niż {limit} min i skończyło się, bo woda była dość ciepła, choć pokoje wciąż prosiły o ciepło. Rozważ podniesienie najniższej temperatury wody do około {value} °C w opcjach sterowania. Dłuższe cykle są prawdopodobne; mniej uruchomień — nie na pewno. Nic się nie zmieni, dopóki tego nie zrobisz."; `lowest_water_suggestion_boiler` ends instead en "Consider raising the minimum flow temperature, or the foot point of the heating curve, of the device that sets your water temperature to about {value} °C — not the curve's parallel shift, which raises the water in frost too. The plugin changes nothing there." / pl "Rozważ podniesienie minimalnej temperatury zasilania albo punktu początkowego krzywej grzewczej w urządzeniu, które ustala temperaturę wody, do około {value} °C — nie równoległego przesunięcia krzywej, które podnosi też wodę w mróz. Wtyczka niczego tam nie zmienia."

**Missing data.** Kind missing with a gateway topology → `unknown`: blocked, repair issue (answer K). `room_setpoint` not mapped → `not_mapped`, no issue; mapped and unknown → warning after 30 min. For the suggestion: no flame → inactive (`flame`); no flow → inactive (`flow`: an end on temperature cannot be told); no setpoint source → inactive (`ch_setpoint`); demand unknown during a burn → the burn is not counted; openings unreported → the valve condition is skipped; too few burns → `no_data`. None of these changes heating.

**Do not.** Offer "off" as a low `CS` with `CH` left alone for an on/off contact (decision 1: K4 with L4, blocked by decision 11; lifting it waits for the user at K4 even if Q3's research is favourable, answer K); declare `CH=` persistent (the heating switch would go unused); remove the resend at `core/loop.py:115-117`; apply a suggestion, add a suggest/apply option, advise a parallel shift, or suggest while stand-alone is handed back; write to the wall thermostat or read its climate target (sync is 0.3 at the earliest); build T-07 here (Z3); let control run on for a gateway entry without an answer to the thermostat-terminals question.

**Open for the user.** None. Answered on 2026-09-27 (answer K): an existing gateway installation without an answer to the new question keeps control stopped, with the notice `thermostat_kind_missing` asking for it; stand-alone, the boiler does not heat until the user answers. Built as above.

---

### X7 — VT: the central entry, reloads, renames, the public attribute

**Goal and done-when.** The plugin reads VT's central configuration correctly in every state — disabled by the user, stuck in a failed setup, reloading — and keeps the "VT central boiler active" blocker until the Home Assistant restart its text asks for; the Auto-TPI and "reload VT" repair issues stop reacting to unknown or unavailable states; renamed entities are followed; the public attribute gets its lasting name before the first release; the feature manager never lets an error reach VT. Done when T-52, T-53 and a test per item below pass with their negative cases, tests and ruff pass through `scripts/env.sh`, X7 is marked ✅ and committed, remainders named.

**Read first.**
- Plan: X7 row (a central entry stuck in setup error with its central boiler on keeps control blocked and raises a visible issue after a time limit); decision 3 (the grace also covers the P-105 blocker — X3's part); "On/off control", migration bullet (control waits for the restart VT needs); Findings ("The 'VT central boiler active' blocker clears without the restart", `vtherm_link.py:185-199`).
- Review: P-19, P-20, P-54, P-59, P-60, P-61, P-63, P-105 (§3.2, §3.3); T-52, T-53 (§6.2); Appendix E question 13.
- Research: `research/2026-09-26-on-off-vt-native-central-boiler.md` Verification → Corrections (after unticking, VT's stale manager can still switch the relay until a restart, even with keep-alive 0; the latch "seen configured in this run", not `modified_at`) and Facts (VT keeps its configuration in `entry.data`; unticking deletes only the two commands; the manager lives in the API object while any VT entry remains); `research/2026-09-27-fresh-session-test.md` "### X7".
- Code: `vtherm_link.py:171-231`; `control.py:485-506`; `switch.py:22`; `coordinator.py:721-757`; `feature_manager.py:50-65, 118-148, 182-208, 252-268, 315-346`; `binary_sensor.py:95-115`; `entity.py:38-39` (unique ID from the key); `__init__.py:30-87, 248-259`; `config.py:123-138`; `control.py:312-373` (the store's zone keys and `taken_with`). HA: `helpers/event.py:521` (`async_track_entity_registry_updated_event`); `awesomeversion` (an HA dependency).

**Order of work.**
1. `tests/integration/test_vtherm_link.py`:
   - `test_a_disabled_vt_central_entry_does_not_block_for_ever` (T-52): Given VT's boiler sensor in the registry and its central entry disabled by the user, Then `False`; with the latch set earlier in the run, Then `True`.
   - `test_a_vt_central_entry_in_setup_error_is_told_after_ten_minutes`: Given the entry in `SETUP_ERROR` with the feature `True` in its data, Then `None`, and after 10 min the issue `vt_central_entry_not_running`; with the feature `False` in its data, Then `False` and no issue.
   - `test_a_reloading_vt_central_entry_is_read_from_its_data` (P-105): Given `SETUP_IN_PROGRESS` and data `False`, Then `False` (no blocker, no hand-back); data `True`, Then `True`.
   - `test_vt_central_boiler_seen_once_blocks_until_the_restart`: Given `True` once, When the feature is unticked and VT reloads, Then still `True` in this run; in a new `hass` (restart), `False`.
2. `tests/integration/test_control.py`: `test_while_vt_reloads_its_central_entry_control_does_not_hand_back` (extends `test_while_vt_reloads_its_central_entry_control_waits`, l.1544); `test_the_vt_boiler_blocker_waits_for_the_restart`; `test_auto_tpi_issue_is_left_as_it_is_while_vt_boiler_is_unknown` (P-54, `coordinator.check_learning`): Given the issue raised, When the state turns unknown, Then it stays; Given no issue, Then none is raised.
3. `tests/integration/test_feature_manager.py`: `test_registration_errors_never_reach_vt` (T-53: an API whose `register_feature_manager`, `get_vtherm_api` and `unregister_feature_manager` raise → attach, check, detach raise nothing; state `UNSUPPORTED` or `WAITING`; unload clean); `test_the_reload_repair_skips_zones_that_are_away_or_not_ready` (P-59); `test_an_old_vt_is_detected_by_its_version` (P-60, once Q3 recorded the minimum; Negative: version unknown → capability detection as today); `test_the_zone_value_is_named_heat_available` (P-61); `test_the_attribute_changes_only_on_a_real_change` (P-63: factor 0.812 → 0.826 publishes nothing new; → 0.87 publishes; `heat_available` flip publishes).
4. `tests/integration/test_setup.py`: `test_a_renamed_entity_is_followed` (P-19: a VT climate and a signal renamed → the options hold the new IDs after one reload; the store's paused-zone keys and `taken_with` follow); `test_a_removed_entity_raises_a_repair_issue` (Negative: an entity the options do not name → nothing).
5. Code, texts.

**Rules and values.**
- **Restart latch.** Whenever VT's central boiler is found configured, `vtherm_link` sets `hass.data["vtherm_smart_boiler_vt_central_seen"] = True` (in `hass.data`, not in the link, so a reload of the plugin does not clear it; a Home Assistant restart does). While it is set, `vt_central_boiler_configured()` returns `True` and the blocker `vt_central_boiler_active` stays. It depends neither on VT's keep-alive nor on the entry's `modified_at`.
- **The central entry's states (P-20, T-52, P-105).** Order in `vt_central_boiler_configured()` (`vtherm_link.py:171-203`): the latch → `True`. No registry entry for VT's boiler sensor → `False`. The sensor provided and enabled → its `is_central_boiler_configured` as today. Otherwise the owner entry: gone → `False`; `disabled_by` set → `False`; `LOADED`, `SETUP_IN_PROGRESS`, `UNLOAD_IN_PROGRESS` or `NOT_LOADED` (a reload) → `use_central_boiler_feature` from `owner.data` (a bool; missing → `None`); `SETUP_ERROR`, `SETUP_RETRY`, `MIGRATION_ERROR`, `FAILED_UNLOAD` → data `False` → `False`, else `None`. `None` held for 10 min (`VT_CENTRAL_UNKNOWN_ISSUE_S = 600`, provisional, K4) raises the repair issue `vt_central_entry_not_running` (warning, not fixable); control stays blocked meanwhile, as VT's manager may still switch the boiler (the cautious side); the issue goes when the state is known.
- **Auto-TPI issue (P-54).** In `coordinator.check_learning` (`coordinator.py:727`), `None` leaves `auto_tpi_blocked` as it is (no create, no delete); only `True`/`False` decide.
- **"Reload VT" repair (P-59).** `feature_manager.async_check` (`feature_manager.py:331-334`) lists a zone only when its state is available and known and VT reports it ready (`ZoneState.ready is not False`, `heating_enabled is not None`), read through `vtherm_link.py`.
- **Old VT (P-60).** The minimum VT version that loads external feature managers is the one Q3 recorded in `research/`; `_api` (`feature_manager.py:188-208`) compares `capabilities().vt_version` with it using `AwesomeVersion`; below → `UNSUPPORTED`. Version unknown, or Q3 found none → capability detection as today, and the issue text names 10.4.0 as the version tested.
- **Renames (P-19; follow, provisional, K4).** The entry listens (`async_track_entity_registry_updated_event`) for every entity its options name (`EntryConfig.watched_entities` plus the control section's entities). `update` with a new entity ID: the ID is replaced everywhere in the options (signals, weather, circuits' flow entities, zones, foreign-heat sources, reference zone, frost zone, control entities), in the store's `paused`/`resuming` zone keys and in `taken_with`, then the options are saved — one reload, as any options save (X5.13). `remove`: the repair issue `entity_removed` naming the field; the plugin goes on without it (missing-data rules).
- **Public name (P-61).** The key inside `smart_boiler` and the manager's property become `heat_available` (`feature_manager.py:50-65, 118-122`); the plugin's own binary sensor keeps its key and unique ID (`entity.py:38-39`, history kept) and is named "{zone} heat available".
- **Real change only (P-63).** The manager keeps the values it last published per zone and replaces them only when `heat_available` changes, the factor goes to or from `None`, or it moves by ≥ 0.05 (provisional, K4) from the published value.
- **Never into VT (T-53).** Every call the plugin makes on VT's API is inside `try`; `add_custom_attributes` already is (`feature_manager.py:134-148`).

Values for S-37's list: 10 min (setup-error issue), 0.05 (factor change) — provisional, K4.

**Code to change.** `vtherm_link.py:171-203` (latch, states); `coordinator.py:721-742`; `feature_manager.py:50-65, 118-148, 188-208, 315-346`; a registry listener started in `__init__.py` after setup (`__init__.py:78-86`) with its unsubscribe on unload; `control.py` a method to rename stored zone keys; translations.

**Texts.**
- Issue `vt_central_entry_not_running` — en title "Versatile Thermostat's central configuration is not running" / description "Its setup failed, and its settings say VT's central boiler is on. Control waits, so that two controllers never drive the boiler: fix VT's central configuration, or untick its central boiler and restart Home Assistant." / pl "Centralna konfiguracja Versatile Thermostat nie działa" / "Jej uruchomienie się nie powiodło, a jej ustawienia mówią, że kocioł centralny VT jest włączony. Sterowanie czeka, żeby kotłem nigdy nie sterowały dwa sterowniki: napraw centralną konfigurację VT albo odznacz w niej kocioł centralny i uruchom ponownie Home Assistant."
- Issue `entity_removed` — en title "An entity the plugin uses is gone" / description "{field}: {entity} is no longer in Home Assistant. Pick another one in the options; until then the plugin works without it." / pl "Encja używana przez wtyczkę zniknęła" / "{field}: {entity} nie ma już w Home Assistant. Wybierz inną w opcjach; do tego czasu wtyczka działa bez niej."
- `blocked_vt_central_boiler_active` adds en "Control keeps waiting until Home Assistant has restarted, even once you have unticked it." / pl "Sterowanie czeka do ponownego uruchomienia Home Assistant, nawet po odznaczeniu."
- `vt_feature_manager_unsupported` description: the version becomes the placeholder `{version}` (Q3's minimum, else "10.4.0").
- Binary sensor `hot_water` name en "{zone} heat available" / pl "{zone} ciepło dostępne".

**Missing data.** VT not loaded: the registry entry and the owner's data still answer; nothing at all → `False`. Owner data without the flag → `None` (waits; issue after 10 min). VT version unknown → capability detection. A zone state unknown → not listed for reload. A registry event for an entity the options do not name → ignored. A removed entity → issue, the feature that used it inactive.

**Do not.** Use `modified_at` or VT's keep-alive for the restart rule; write to VT's entries or call VT's services; change the plugin binary sensor's unique ID; let control start while VT's central entry is in a failed setup with its feature on.

**Open for the user.** None.

---

### X8 — On/off control through a relay (class 3)

**Goal and done-when.** A boiler switched on and off by a relay is controlled as VT's own central boiler did, with the plugin's safeguards: a write path "relay" for class `on_off`; the relay's own settings asked as the user's declaration, and the tick "this is a separate relay contact, not a setting stored in the boiler's memory", without which control does not start (answer G); flame and flow optional for the whole entry, with a blocker for water-temperature control where either is missing; the link is the relay (alarm after 5 minutes out of reach, the command sent again on its return, no hand-back meanwhile); the relay's state checked and written on a mismatch only — a relay back in another state after a power or link loss, or found in the state it takes after a power cut as the user declared it, gets the command again (answers C and D); one switched to another state while it stayed available is rewritten once, then the plugin steps aside with the relay's hand-back, its rest state set once, and a latch, leaving the relay alone afterwards (answers C, H and L); a fourth restart within 24 h in the declared power-cut state — or, with that state declared "last" or "I don't know", a fourth change within 24 h while the relay stayed available, each of the first three sent the command again as a possible restart — makes the plugin step aside in the same way (answer N); X3's "own room controller" tick counts on the relay path only with the rest state "on" (answer M); blind repeats only for relays that report no state or may switch themselves off (a timer declared, or "I don't know"), shown as "controlled without confirmation" where no state is reported; the rest state at hand-back ("off" by default, "on" only when chosen) with a notification when it leaves the house without heating; the last command restored at once after a planned restart; optional proof that the boiler heats; the migration from VT's central boiler; the activation delay shown on the relay path; no return by itself for relays; the setup texts. Done when every test below passes with its negative cases (missing, unknown, unavailable, `None`), the relay's allowed services are exactly those listed, tests and ruff pass through `scripts/env.sh`, X8 is marked ✅ and committed (diff in the report), and remainders are named in "Open after 0.2.2" (at least: a recorded "heating commanded" entity and event for users leaving VT's central boiler — 0.3, item 10; a wiring field for the relay, item 11; whether a Shelly relay's timer restarts on a repeated "on" — checked on the user's own relay at K6, never at J4, which uses the simulator only; until then the texts say it is not documented — added to "Open after 0.2.2" if it is not there yet). The simulator's relay acceptance is Z3's.

**Read first.**
- Plan: "Decisions of 2026-09-26/27" → "Missing data" and "On/off control" (every sub-bullet); decisions 3, 5, 6, 7, 13; Terms (relay, rest state, recognition period, lost command, safe hand-back, working thermostat); X8 row; Findings (`core/demand.py:78-86` → X3; `core/signals.py:64-65`, `config.py:194-196`; `transport/writers.py:184-193`; `control.py:627-633`); "Open after 0.2.2" items 5, 10 and 11. The user's answers of 2026-09-27 as the plan records them: **C** and **D** under "On/off control" (a relay found in another state after a power or link loss, or back in its declared power-cut state even without Home Assistant seeing it unavailable, is sent the command again, with an information warning at 3 within 24 h; only a change to another state while the relay stayed available counts as another controller: rewritten once, then decision 6's reactions, never fighting); **G** under "On/off control" (the separate-contact tick); **H** in decision 6 (stepping aside is the full safe hand-back — for a relay its rest state — even though it briefly writes over the other controller's value; then a latch until the user switches control off and on); **E** in decision 6 (the second-untraced-fall-back rule) is for the setpoint and the heating switch, not for relays, where C and D decide; **F** in decision 3 (a working thermostat: a gateway with an OpenTherm thermostat declared, or any write path with the "own room controller" tick; a relay resting "on" is not one); **I** in decision 7 (the monitor-failure hand-back); **L** under "On/off control" (stepping aside from a relay sets it once to its rest state, then leaves it alone); **M** under "On/off control" and in decision 3 (on the relay path the tick counts only with the rest state "on"; not offered on a gateway); **N** under "On/off control" (the fourth restart within 24 h in the declared power-cut state is another controller; with "last" or "I don't know", a change while available is a possible restart up to 3 times within 24 h, then another controller).
- Review: S-18 (decision 13), S-27, S-09 (V5), P-09 (X1), P-14 (X3), the "Findings" rows above.
- Research (each note's "Decided by the user" line and its Verification → Corrections hold over the first answer): `research/2026-09-26-on-off-plugin-code.md` §2 (every blocker), §3.1–3.12, §4, §6, Corrections (VT's delay, the 5-s context window, the owed hand-back plus resume in one step, frost fields only advanced), Missing, Safety concerns; `research/2026-09-26-on-off-relays.md` §2 table, §3 table, §4 table, §5, Corrections (the gap is no test for a restart; Zigbee availability; rest ON allowed with its risk), Missing (a cautious "unknown" path; the relay's own input; the timer set during the monitoring week; the electrical note), Safety concerns (a boiler's stored switch); `research/2026-09-26-on-off-vt-native-central-boiler.md` (a) table, (d) "Moving over from VT", Corrections (VT truncates thresholds with `int()`; the restart latch; climate "heat" confirms nothing about firing), Facts (entry keys, number unique IDs, command format); `research/2026-09-27-plan-0.2.2-checks.md` (relay items); `research/2026-09-27-fresh-session-test.md` "### X8".
- Code: `core/installation.py:10-16`; `core/signals.py:22-82`; `config.py:184-197`; `config_flow.py:80-96, 162-177, 196-213, 397-400, 437-449, 549-566, 585-612, 654-682, 1283-1310, 1420-1448`; `control_config.py` (whole); `core/controller.py:113-160, 226-270, 303-357, 385-397`; `core/loop.py` (whole); `core/guards.py:1-34, 153-211`; `transport/writers.py:91-138, 141-214, 346-353`; `control.py:84-130, 147-165, 312-373, 377-448, 485-506, 586-698, 765-918`; `switch.py:22, 57-76`; `sensor.py:342-343, 458-499`; `binary_sensor.py:30-92, 206-218`; `coordinator.py:620-665`; `core/signal_check.py:53-55`; `core/learning.py:106-166`; `vtherm_link.py:52-60, 171-203`. Vendor VT: `const.py:111-112, 120, 234-237, 239, 532`; `config_schema.py:228-239`; `number.py:180, 246-259, 280-289`; `feature_central_boiler_manager.py:361-398` (thresholds used as `int()`); `commons.py:35-50` and `documentation/en/feature-central-boiler.md:56-66` (the command format, read for the format only). HA: `helpers/entity.py:86` (context kept 5 s); `const.py:442` (`assumed_state`).

**Order of work.** X8 comes after X1–X4 and V3/V5/V7 and uses them: X1's classes, per-guard `write_ignored`, `commands_lost` and the trace-of-an-outage window, V3's stored last command and on/off wish, V5's safe hand-back and confirmation rules (a two-valued target taken by another controller included), V7's latch issue `control_latched_<entry_id>`, X3's recognition and grace periods, restore conditions, power criterion and the "own room controller" option, X4's activation delay (and the read-only reader of VT's central entry, if X4 built it; otherwise X8 builds it, R14).
1. Core tests.
   - `tests/core/test_controller.py`:
     - `test_on_off_mode_heats_without_a_water_temperature`: Given the on/off mode, a calling zone and no outdoor temperature, Then `ch_enable` true, `setpoint` `None`, mode `HEATING`, never `FALLBACK`.
     - `test_on_off_mode_idle_and_frost`: no demand → `IDLE`, off; a cold zone that can take heat → `FROST`, on.
     - `test_on_off_mode_every_zone_unknown_after_the_grace_is_off` (decision 3 via X3): relay off, reason `zones_unknown`; with X3's "own room controller" tick and the rest state "on" → `HANDED_BACK`, the relay on, no latch (answers F and M); with the tick and the rest state "off" → still off, with the alarm (answer M); Negative: a rest state "on" without the tick → still off.
     - `test_on_off_mode_never_hands_back_for_a_lost_link`: `stale_hand_back_s` `None`; 1 h without a link → no hand-back.
   - `tests/core/test_relay.py` (new; `core/` is in the agreed layout):
     - `test_a_new_command_is_written_at_once`;
     - `test_a_confirmed_state_is_not_written_again` (a state-reporting relay declared without a timer gets no repeats);
     - `test_a_relay_back_from_unavailable_in_another_state_gets_the_command_again` (lost command, no rewrite counted);
     - `test_a_relay_back_in_its_declared_power_cut_state_is_a_restart` (answer D: power-cut state `off`, command on, the relay reads off with no trace while it stayed available → sent again, +1 loss, no rewrite counted; the third within 24 h → `commands_lost`);
     - `test_a_fourth_power_cut_state_restart_in_a_day_steps_aside` (answer N: power-cut state `off`; three such restarts within 24 h → each sent again; the fourth within 24 h → another controller: the plugin steps aside at once, with no rewrite first — the rest state written once (answer L), the latch and `control_latched_<entry_id>`; Negatives: the fourth more than 24 h after the first → a restart again; restarts with a trace (R2) do not count toward the fourth);
     - `test_a_change_with_the_power_cut_state_last_or_unknown_is_a_possible_restart_three_times` (answer N: power-cut state `last`, then `unknown`; a change while the relay stayed available, no trace → sent again, +1 loss, no rewrite counted, three times within 24 h; the fourth → step aside as above; Negative: a relay that reports no state → nothing judged, blind repeats only);
     - `test_a_relay_out_of_reach_is_not_written_and_alarms_after_five_minutes` (4 min 59 s: no alarm; 5 min: alarm; never a hand-back);
     - `test_a_change_while_available_is_rewritten_once_then_the_plugin_steps_aside` (answer C; power-cut state `off`, command off, the relay switched on while available; the second within 24 h → step aside: the rest state written once (answers H and L), then no write at all — also when the rest state is never read back, or the other controller switches the relay again at once);
     - `test_a_change_a_day_after_the_rewrite_is_rewritten_again`;
     - `test_the_declared_timer_switching_off_is_a_lost_command` (also when the relay does not restart its timer on a repeated "on": the switch-off comes the timer's length after the start of the on-period) and `test_an_early_switch_off_with_a_timer_is_another_controller` (power-cut state `on` declared; with `off`, `last` or `unknown` declared the early switch-off is R2a's possible restart, answer N);
     - `test_an_unknown_timer_gets_on_repeats_and_a_late_switch_off_is_a_lost_command` (timer `unknown`, state reported: "on" every `relay_repeat_s` while commanded on; a switch-off at least one repeat interval after the start of the on-period → lost command; earlier → judged as any change while available: with power-cut state `on` another controller, otherwise R2a's possible restart (answer N); "off" is not repeated);
     - `test_three_losses_in_a_day_raise_commands_lost` (two do not; it clears after 24 h without a loss; it never blocks);
     - `test_a_relay_without_a_state_gets_blind_repeats` (every 300 s, or the carried interval; never judged);
     - `test_a_timer_relay_is_renewed_at_half_its_timer` (only while "on"; never less often than every `relay_repeat_s`);
     - `test_an_unconfirmed_command_is_reported_and_clears_when_it_holds` (`write_ignored` raised after 120 s; cleared once the state has held 120 s);
     - `test_a_relay_that_never_takes_the_command_is_ignored_from_the_start` (never the command for longer than 120 s after each of the session's first 3 sends → not written again this session, repeats included; `relay_ignored`; Negative: taken after the second send → nothing of this);
     - `test_a_late_echo_of_the_previous_command_is_not_a_change` (within 120 s of a send);
     - `test_the_periodic_check_resends_a_mismatch_no_event_explained`;
     - `test_unknown_inputs_change_nothing` (desired `None` → no write; state `None` without an outage mark → nothing judged);
     - `test_heat_evidence` (flame → heats; flow +5 K → heats; a gas step → heats; power above the threshold → heats; nothing mapped or all `None` → unknown; 30 min of nothing → not seen).
   - `tests/core/test_loop.py`: `test_a_relay_has_no_setpoint_guard`.
2. Config tests.
   - `tests/test_control_config.py`: `test_relay_control_needs_an_on_off_boiler` (on_off + relay + an entity → none of the path blockers; flow_setpoint + relay and on_off + entity → `path_not_for_boiler_class`; curve_only/read_only → `boiler_class_no_control`); `test_a_relay_is_a_switch_or_a_climate` (missing → `no_relay_entity`; `input_boolean.x`/`light.x` → `relay_domain_not_supported`); `test_relay_control_needs_the_separate_contact_tick` (answer G: missing or false → `relay_contact_not_confirmed`; true → none); `test_water_temperature_control_needs_flame_and_flow` (`no_flame_signal`, `no_flow_signal`; the relay path needs neither); `test_relay_settings_have_cautious_defaults` (reports `unknown`, power-cut state `unknown`, timer `unknown`, repeat 300 s, rest `off`, no power proof, the tick off); `test_a_declared_timer_without_its_length_is_read_as_unknown`; `test_the_repeat_interval_stays_within_10_to_300_s` (a hand-edited value outside is read as 300 s); `test_the_rest_state_decides_the_hand_back_effect`; `test_the_circuit_rules_do_not_apply_to_a_relay`; `test_every_blocker_is_listed` extended.
   - `tests/test_config.py`: `test_an_entry_without_boiler_signals_parses` (replaces the `missing_signal` case, `tests/test_config.py:128`); `test_the_boiler_power_signal_parses`.
3. Integration tests.
   - `tests/integration/test_writers.py`: `test_relay_writer_switch` (turn_on/turn_off with the plugin's own `Context`; the hand-back writes only the rest state, check "off"); `test_relay_writer_climate` (`set_hvac_mode` heat/off; checks "off"/"heat"); `test_a_relay_hand_back_switches_on_only_when_chosen`; `test_an_unavailable_relay_is_a_failed_write`; `test_a_relay_without_a_state_gives_no_hand_back_check`; `test_relay_writer_services` (switch → `turn_on`, `turn_off`; climate → `set_hvac_mode`; none → empty).
   - `tests/integration/test_control.py`: `test_relay_control_follows_vt_both_ways`; `test_a_relay_out_of_reach_alarms_and_never_hands_back` (resent on return, no rest-state write); `test_a_relay_restart_gets_the_command_again`; `test_a_relay_switched_by_an_automation_is_rewritten_once_then_handed_back` (answers C, H and L: at the second change within 24 h the rest state is written once, then nothing, even when the automation switches the relay again at once; the repair issue `control_latched_<entry_id>`, error when the relay rests off, warning when on; the latch survives a restart; switching control off and on clears it); `test_a_relay_rest_state_changed_after_the_hand_back_is_left` (a hand-back other than a step aside — control switched off: read back once at the rest state, then changed with no trace → taken by another controller, not retried; never read back → still owed and retried; at a step aside, never retried, answer L); `test_a_relay_that_keeps_restarting_steps_aside_on_the_fourth_time` (answer N: power-cut state `off`, four unreported restarts within 24 h → the fourth steps aside with the rest state once, the latch surviving a restart; with `unknown` declared, four changes while available → the same); `test_a_planned_restart_rests_then_restores_at_once` (stop → rest state; start → the stored command at the first step under X3's restore conditions, no activation delay); `test_a_crash_restores_without_a_hand_back_first`; `test_an_unreadable_store_hands_a_relay_back_first`; `test_no_restore_when_the_wish_was_off_or_latched_or_blocked` (and when the control options differ from `taken_with`); `test_an_owed_relay_hand_back_is_folded_when_control_resumes` (no off-then-on in one step); `test_the_rest_state_notice_when_a_zone_calls` (and when frost protection would heat; none after the relay was taken by another controller); `test_controlled_without_confirmation_is_shown` (declared "no", "unknown", and `assumed_state`); `test_boiler_not_responding_after_thirty_minutes` (Negative: no proof signal → no alarm, status "without confirmation that the boiler heats"); `test_only_the_relays_services_are_called`; `test_learning_pauses_apply_to_a_relay`; `test_a_relay_that_never_takes_the_command_raises_relay_ignored`.
   - `tests/integration/test_config_flow.py`: `test_the_relay_path_is_offered_only_for_on_off_boilers`; `test_the_relay_step_asks_the_relays_own_settings` (including the separate-contact tick, default off, never pre-filled); `test_the_relay_path_shows_the_activation_delay` (on the relay path's behaviour step at the simple and the advanced level, pre-filled from VT's stored value and shown for confirmation); `test_the_relay_path_offers_no_return_by_itself`; `test_the_relay_path_offers_the_own_room_controller_tick` (answer M: shown on the relay step's control form; saved with the rest state "off", it is kept but does not count as a working thermostat); `test_a_declared_timer_needs_its_length` (`relay_off_timer_min_missing`); `test_a_relay_used_by_a_vt_zone_or_the_gateway_is_refused`; `test_an_input_boolean_relay_is_refused`; `test_the_relay_step_is_prefilled_from_vts_central_boiler` (a fake central entry with VT 10.4.0's keys: switch pairs, climate pairs, a free-form command → "not supported", thresholds by `int()`, W → kW, 0/0 → nothing, a multi-device zone → no count, a keep-alive above 300 s → the repeat interval not pre-filled; nothing written to VT); `test_prefill_without_a_vt_central_entry_leaves_the_fields_empty`; `test_the_signals_step_accepts_no_signals`.
   - `tests/integration/test_setup.py`: `test_a_relay_only_entry_monitors_without_boiler_signals` (connection unknown; features name `flame` as missing; no frequent-starts or unstable-ignition entity).
   - `tests/integration/test_vtherm_link.py`: `test_vt_central_boiler_settings_are_read_without_writing`.
4. The code (R1–R15), then the texts, then the key-parity tests.

**Rules and values.**
- **R1 Path and class.** `WritePath.RELAY = "relay"`. The path select offers `none` + `relay` for class `on_off`; `none` + `entity`, `opentherm_gw`, `otgw_mqtt` for `flow_setpoint`; only `none` otherwise. Blockers: `path_not_for_boiler_class` (relay with another class, or `on_off` with another path); `boiler_class_no_control` replaces `boiler_not_flow_setpoint` (`control_config.py:322-323`) for `curve_only` and `read_only`. For the relay path the setpoint, topology, thermostat-kind, read-back, curve and circuit blockers do not apply (`control_config.py:325-367`); the demand thresholds do (`count_threshold_above_zones`). No minimum on/off times, no switching cap (decision 13).
- **R2 The relay entity** (`relay_entity`). A `switch`, or a `climate` driven with `climate.set_hvac_mode` `heat`/`off` whose `hvac_modes` contain both (else `relay_climate_modes`). Refused in the form and as blockers: any other domain, `input_boolean` included (`relay_domain_not_supported`); an entity a VT thermostat lists in `underlying_entity_ids` (`relay_used_by_zone`, read through `vtherm_link.py`); an entity registered by `opentherm_gw` or `versatile_thermostat` (`relay_of_boiler_interface`); an entity the options already use in another role or as a signal. A boiler's own stored switch reached through MQTT (EMS-ESP's "heating activated") cannot be recognised: the field's text forbids it, and the form asks the user to confirm with the separate-contact tick (R3, answer G).
- **R3 The relay's own settings** — the user's declaration; the plugin cannot read them. Cautious defaults, all provisional, K4:
  - `relay_reports_state`: `yes` / `no` / `unknown` (default `unknown`). `no`, `unknown`, or an entity with `assumed_state: true` = "reports no state": blind repeats (R8) and "controlled without confirmation"; nothing is judged from its state.
  - `relay_power_on_state`: `off` / `on` / `last` / `unknown` (default `unknown`). `off` or `on`: a relay found in that state while it differs from the command is taken as a restart, even when Home Assistant saw no outage (R7, answer D), up to 3 times within 24 h; the fourth is another controller (answer N). `last` and `unknown`: no power-cut state is known, so any change while the relay stayed available is taken as a possible restart in the same way — the command sent again up to 3 times within 24 h, the fourth another controller (answer N). Also used in the texts and the out-of-reach notice; `on`, `last` and `unknown` carry the warning that after a power cut the boiler may heat without control until Home Assistant is back.
  - `relay_off_timer`: `none` / `minutes` / `unknown` (default `unknown`), with `relay_off_timer_min` (1–120 min) required when `minutes` (form error `relay_off_timer_min_missing`; hand-edited options with `minutes` and no valid length are read as `unknown`). `unknown` is treated as "it may have one": while the command is "on", "on" is repeated every `relay_repeat_s`, and a switch-off at least one repeat interval after the "on" that started the current on-period is the lapse (a lost command); an earlier one is judged as any change while the relay stayed available (R7). With a declared length, "on" is renewed every min(timer ÷ 2, `relay_repeat_s`), and a switch-off at or after max(timer − 60 s, timer ÷ 2) since the "on" that started the current on-period is the lapse. Both windows count from the start of the on-period rather than from the last "on" sent, so a relay that does not restart its timer on a repeated "on" (not documented for a Shelly) is still recognised; the floor of half the timer keeps a 1-minute timer from taking every switch-off for its lapse.
  - `relay_repeat_s`: empty (default 300 s) or 10–300 s in steps of 10; pre-filled from VT's keep-alive where one between 10 and 300 s is carried over (a longer one is not pre-filled, and the text says why) (R14). Used for blind repeats, for "on" repeats with the timer unknown, and as the cap on a declared timer's renewal.
  - `relay_rest_state`: `off` (default) / `on`, with its risk text.
  - `boiler_heats_above_w`: empty (default: the power is not used as proof) or 10–10000 W.
  - `relay_is_separate_contact` (answer G): a tick, default off, never pre-filled (also not when moving over from VT): "this is a separate relay contact, not a setting stored in the boiler's memory". Without it the config blocker `relay_contact_not_confirmed`: control does not start and says why; the monitor runs.
- **R4 Signals optional.** `SIGNAL_SPECS` (`core/signals.py:64-65`): flame and flow lose `required`; `SignalSpec.required` becomes `link` (flame, flow), used for the connection sensor and class 1's link; `REQUIRED_SIGNALS` (`core/signals.py:80-82`), the check at `config.py:194-196` and `REQUIRED_FIELDS` (`config_flow.py:96`) go — the signals step accepts nothing mapped. `config_blockers` gets the mapped signals and adds `no_flame_signal` / `no_flow_signal` for the three water-temperature paths. New optional signal `boiler_power` (`SignalKind.POWER`, a `sensor` with device class `power`, W; kW converted in `units.py`; plausible 0–100000 W), at the advanced level. With flame not mapped, the frequent-starts and unstable-ignition alarm entities are not created (`binary_sensor.py:30-42`), as pressure alarms without pressure. The connection sensor (`coordinator.py:641`, `binary_sensor.py:70-92`): on when every mapped link signal is OK and, on the relay path, the relay is reachable; `None` (unknown) when no link signal is mapped and there is no relay; its `problems` attribute adds `relay`.
- **R5 The command.** `ControlConfig.on_off` (true on the relay path): `_heating_decision` (`core/controller.py:273-382`) skips the curve, limits, ramp and comfort correction; `BoilerCommand.setpoint` is `None`; modes `FROST`, `HEATING`, `IDLE`, never `FALLBACK`; the outdoor temperature is not needed. The loop plans no setpoint write and hands heating on/off to the relay rule (R7). Frost (decision 4), the activation delay (decision 5), the recognition and grace periods and "every zone unknown after the grace → the usual off" (decision 3) apply unchanged; for a relay "the usual off" is the relay off, never the rest state. X3's option "the boiler has its own room controller" (answer F) is shown on the relay path too, as on the entity path (it is not offered on a gateway, answer M): with it ticked and the rest state "on" — the relay is the boiler's heat-demand contact — every zone unknown after the grace hands the relay back to its rest state instead (`HANDED_BACK`, no latch); with the rest state "off" the tick counts as not ticked there — the usual off, never the rest state, with the alarm (the user, 2026-09-27, M) — with X3's alarm and repair issue either way, and control resumes by itself when a zone answers again. A relay resting "on" without the tick is not a working thermostat. `hand_back_effect()` stays `relay_rests_off` / `relay_rests_on` on the relay path (R9), so X3's working-thermostat test reads the tick itself there.
- **R6 The link is the relay.** On the relay path `ControlConfig.stale_hand_back_s = None` (`core/controller.py:130, 249-257`) and `ControlInputs.boiler_link` stays true: the controller keeps deciding. Reachable = the relay's state is its on/off value (switch `on`/`off`; climate `heat`/`off` or another `hvac_mode`). `unavailable` or a missing entity: no write is attempted; `unknown`: a new command is written (the writer allows it, `transport/writers.py:95-104`) but not confirmed. Out of reach (unavailable, missing or unknown) for 5 min (decided) → alarm `relay_unreachable` and its repair issue; no hand-back meanwhile — an exception to decision 7's lost-link hand-back and X2's; on its return the current command is sent at once (a lost command). Flame and flow never gate relay control.
- **R7 The relay's state as its read-back, and what a change means.** For a relay that reports its state, its own reported state confirms the relay — writes and the rest-state hand-back — never the boiler: an exception to the self-echo rule (`control.py:121-130, 776-782`) and to V5's "without an independent report". The plugin passes a `Context` of its own on every relay write (none today, `transport/writers.py:113`) and remembers the last 20; a listener on the relay (`async_track_state_change_event`) records every transition through `unavailable`, `unknown` or removal between steps, and changes carrying its own context. A trace of an outage (X1's, provisional, K4): within the 5 min before the change, the relay, or another entity of its device that the plugin reads, was `unavailable`, `unknown` or missing, or a restart of the relay was seen. Pure rule `plan_relay` in `core/relay.py`, per step, rows in this order:

  | Seen | Condition | Class | Reaction |
  |---|---|---|---|
  | state = command | — | confirmed | nothing |
  | state ≠ command | within 120 s of a send, or equal to the previous command within 120 s | waiting | nothing |
  | state ≠ command | a trace of an outage, or the first report after Home Assistant starts | lost command (answer C) | sent again at once; +1 loss |
  | state ≠ command | timer declared or `unknown`, command on, state off, inside the lapse window of R3 | lost command (the timer's lapse) | "on" sent again; +1 loss |
  | state ≠ command | after a confirmation, no trace of an outage: the state is the declared state after a power cut (`relay_power_on_state` `off` or `on`); or, with `relay_power_on_state` `last` or `unknown`, any change while the relay stayed available and not the plugin's context — fewer than 3 such within the last 24 h | lost command: a restart the relay did not report (answers D and N) | sent again at once; +1 loss; the time kept for the count (stored at once) |
  | state ≠ command | as the row above, with 3 such already within the last 24 h | another controller (answer N) | the plugin steps aside at once, with no rewrite first: the rest state written once (unless the relay already reads it), then nothing more is written, read back or not (answer L); latched and stored until the user switches control off and on; V7's repair issue `control_latched_<entry_id>` as in the row below |
  | state ≠ command | changed after a confirmation to a state that is not the declared power-cut state (`relay_power_on_state` `off` or `on`), relay available throughout, no trace, context not the plugin's | another controller (answer C) | the first: rewritten once (`rewritten_at` stored at once); a second within 24 h of that rewrite: the plugin steps aside with the full safe hand-back — for a relay its rest state, written once even over the other controller's state (answer H), unless the relay already reads it — and writes nothing more, read back or not (answer L); latched and stored until the user switches control off and on; X1's return by itself does not apply to relays and is not offered on the relay path; V7's repair issue `control_latched_<entry_id>` (severity error when the relay rests off, warning when it rests on) |
  | state ≠ command | never confirmed since a send, > 120 s | not confirmed | `write_ignored` on; sent again at the next check |
  | state ≠ command | never the commanded state for longer than 120 s after each of the session's first 3 sends | ignored from the start | not written again this session, repeats included; `write_ignored` stays on and the repair issue `relay_ignored` (severity error: "the relay does not accept the command — check it"), as nothing else controls the boiler; tried again at the next session (provisional, K4). Where the ignored command is "off" (answer O applied to relays): control is blocked with the latch/blocker `heating_off_ignored`, kept until the user switches control off and on; the repair issue adds "the boiler may keep heating: the relay does not switch off"; no rest-state write is relied on |

  3 losses within 24 h (for relay restarts decided by answers C and D; otherwise X1's provisional count, K4) → X1's information alarm `commands_lost`, which clears after 24 h without a loss; it never stops control. The step aside at the fourth untraced restart within 24 h (answer N) is counted apart from `commands_lost`: only the rows of answers D and N feed it, not restarts with a trace (answer C; this file's reading of N, to confirm at K4), nor the timer's lapse. `write_ignored` from the relay clears once the relay has held the command for 120 s (X1's per-guard clearing; `control.py:627-633` no longer looks at the setpoint alone), except after "ignored from the start", where it stays until the next session. A relay that reports no state: nothing in this table applies. Known limits: a restart the relay does not report cannot be told from another controller, so an automation that keeps switching the relay to its declared power-cut state — or, with `last` or `unknown`, to any state — is answered up to 3 times within 24 h before the plugin steps aside (answer N); an undeclared timer shorter than the repeat interval looks like a restart or another controller.
- **R8 Check, blind repeats, renewals** (`RELAY_CHECK_S = 300`, provisional, K4; reason: undoes a wrong state within one VT TPI cycle at its default, without writing to relays that may store each command). A relay that reports its state is compared at every step (10 s, from the state machine) and, every 300 s, even without an event; it is written only on a mismatch, and with "on" repeats while the command is on where its timer is declared (every min(timer ÷ 2, `relay_repeat_s`)) or `unknown` (every `relay_repeat_s`); "off" is not repeated where the state is reported. A relay that reports no state gets its current command (on or off) every `relay_repeat_s` (default 300 s). Repeats and renewals continue through the recognition period. Writes to the relay stay ≥ 5 s apart (`MIN_WRITE_INTERVAL_S`).
- **R9 Hand-back and rest state.** `RelayWriter.hand_back()` writes only the rest state: `off` (default) → `turn_off` / `hvac_mode: off`; `on` (chosen) → `turn_on` / `hvac_mode: heat`. It never switches the relay on otherwise, unlike the heating switch (`transport/writers.py:189-193`, S-27). The same write is the relay's part of every safe hand-back, stepping aside from another controller included (answer H). At a step aside — answer C's second change, or answer N's fourth restart — it is written once and the relay is then left alone, read back or not, and never retried (the user, 2026-09-27, L); a relay out of reach at that moment gets that one write when it returns (R6). Check: `HandBackCheck(relay, "off"|"on"|"heat")` where the relay reports its state; none where it does not (shown unconfirmed, not owed for ever). After any other hand-back, a rest state read back once and then changed with no trace of an outage counts as taken by another controller (V5's rule for two-valued targets, provisional, K4): the hand-back is done, not retried, shown `taken_by_other`, with V5's repair issue; before it was read back once it stays owed and is retried. An unreachable relay at a hand-back: `WriteError`, owed, retried every minute (`control.py:866-918`). An owed relay hand-back and a session that commands the relay in the same step (control on, no blocker): only the command is written and the owed hand-back is folded into the session, whose own hand-back comes at its end — no off-then-on (provisional, K4; `control.py:588-589` changes for the relay path). `hand_back_effect()` (`control_config.py:299-314`) returns `relay_rests_off` / `relay_rests_on`; the switch's `off_by` (`switch.py:67`) is `relay`.
- **R10 Notice when the rest state leaves the house without heating** (no wiring field in 0.2.2, provisional, K4). While control is not holding the relay, the rest state is `off`, the relay's hand-back was not taken by another controller, and at least one zone wants heat or frost protection would heat, the repair issue `relay_rests_off` (warning, not fixable) is raised; it goes when control takes the relay again. Not raised during a planned stop (Home Assistant is going down) nor while the relay is out of reach (R6 has its own).
- **R11 Restart, crash, recognition.** A planned stop (shutdown job, unload, reload): the rest state; V3 has stored the last command and whether a session was controlling at the stop. At start, with a readable store, for a session that was controlling (a clean stop or a crash) and under X3's restore conditions — V3 stored a last relay command; the stored wish is "control on" and the control switch entity is not disabled (answer K); no latch or internal error; the control options equal `taken_with`; no blocker other than `ha_starting` (and `vt_central_boiler_unknown` only within X3's P-105 grace) — the command is written at the first step, before the switch's restore wait (`control.py:593-594`; V3 knows the wish from the store); no activation delay (decision 5). Any other case leaves the relay as found (and a hand-back owed goes out as the rest state). After a crash a relay gets no "full hand-back first" (`control.py:370-373` changes for the relay path); V1's full hand-back first (the rest state) applies only to an unreadable store (answer K: a lost or damaged store means "was controlling"). The restored command is kept, with its repeats, until the recognition period ends (X3). A relay not yet reported or unreachable at start: R6 — nothing is written until it is reachable, the command is written when it returns, and a relay not yet reported never turns the restore into a hand-back.
- **R12 Proof that the boiler heats** (information only; provisional, K4). `heat_evidence()` in `core/relay.py`: heats when flame is on, flow has risen ≥ 5 K since the "on", the gas meter has advanced since the "on", or `boiler_power` ≥ `boiler_heats_above_w`; unknown when no proof input is mapped and known; else not seen. After 30 min (`PROOF_WINDOW_S = 1800`; reason: longer than a common 20-min restart lockout) of the relay on (confirmed, or since the send where unconfirmed) with at least one proof input known and none showing heat → the information alarm `boiler_not_responding`; it clears on any proof or when the relay goes off. No proof input at all → the status "controlled without confirmation that the boiler heats", no alarm. Never offered a hand-back reaction.
- **R13 The rest of the decisions.** The power criterion is X3's (every path); learning pauses apply as for class 1 except the water-swing cause (`core/learning.py:119-132`); the stop on the boiler's own fault is Y1's — for a relay the relay off, no hand-back, no latch, frost heating included, heating again when the fault reads off; the monitor-failure hand-back after 5 min (V6, answer I) applies as on every path: the rest state, control resuming by itself once the monitor works again, with an information note; frost as decision 4, the delay as decision 5, zones unknown as decision 3 (R5).
- **R14 Moving over from VT** (through `vtherm_link.py` only, never writing to VT). `vt_central_boiler_settings(hass)` reads VT's central entry (`thermostat_type` = `thermostat_central_config`): `central_boiler_activation_service`, `central_boiler_deactivation_service`, `central_boiler_activation_delay_sec`, `keep_alive_boiler_delay_sec` (vendor `const.py:234-237`), and the number entities with unique IDs `boiler_activation_threshold` and `boiler_power_activation_threshold` (vendor `number.py:180, 246`), each as `int()` of its state in VT's unit, as VT uses them (vendor `feature_central_boiler_manager.py:361-383`). The commands are parsed by the plugin's own parser of VT's documented format `entity_id/domain.service[/attribute:value]`. Pre-filled only: `switch.X/switch.turn_on` with `switch.X/switch.turn_off`, or `climate.X/climate.set_hvac_mode/hvac_mode:heat` with `…:off` (same X) → `relay_entity`; any other → "not supported: pick the relay" (free-form actions are "Open after 0.2.2" item 5). The delay → X4's activation delay (0–600 s); a keep-alive between 10 and 300 s → `relay_repeat_s` (a longer one is not pre-filled; the field's text says why); the power threshold → kW (`W` ÷ 1000, `kW` as is, another unit → not pre-filled) when > 0; the count threshold only when > 0 and every zone VT flags `is_used_by_central_boiler` has one underlying device, capped at the plugin's zone count; both thresholds 0 → nothing (VT never switched on). The separate-contact tick is never pre-filled. Pre-filled values are shown for confirmation, never saved silently. The step is `control_relay_from_vt` when VT's central boiler is configured or its settings exist (its description lists the migration steps), else `control_relay`. Control waits for the Home Assistant restart through X7's latch. Once VT has deleted its commands, the relay is left for the user to pick.
- **R15 What is shown.** `ControlStatus` gets `relay_state`, `relay_check` (`confirmed`, `waiting`, `not_confirmed`, `ignored`, `unverified`, `changed_from_outside`) and `boiler_heats` (`heats`, `not_seen`, `unverified`); the control-state sensor shows them (unrecorded); the switch shows `confirmation` = `controlled_without_confirmation` for a relay without a state and `without_heat_confirmation` without a proof input. `ControlSetpointSensor` is not created (`sensor.py:342-343`). The relay alarms (`relay_unreachable`, `boiler_not_responding`) exist only on the relay path; X1's `commands_lost` is shared with the other paths; `boiler_link_lost` does not exist on the relay path, nor X1's `confirmation_missing`: an unknown or unavailable relay is `relay_unreachable` (R6).

Values for S-37's list: 5 min out of reach (decided); 300 s check; `relay_repeat_s` 10–300 s, default 300 s; a declared timer 1–120 min, renewed at min(timer ÷ 2, repeat interval); its lapse at or after max(timer − 60 s, timer ÷ 2) from the start of the on-period; an unknown timer's lapse at least one repeat interval from the start of the on-period; 5 min trace window (X1's); 3 losses in 24 h, cleared after 24 h (X1's); 3 untraced restarts (or, with "last" or "I don't know", 3 changes while available) within 24 h answered, the fourth stepping aside (decided, answer N); the rest state written once at a step aside (decided, answer L); 120 s confirmation; 3 sends for "ignored from the start"; 24 h rewrite window (decision 6); 30 min proof window; 5 K flow rise; 20 remembered contexts — provisional, K4 except where decided.

**Code to change.** `core/installation.py` (no change: `ON_OFF` exists). `core/signals.py:22-82` (optional flame/flow, `link`, `BOILER_POWER`, `SignalKind.POWER`); `units.py` (W/kW). `config.py:184-197`. `control_config.py`: `WritePath.RELAY`, the R3 keys (`relay_reports_state`, `relay_power_on_state`, `relay_off_timer`, `relay_off_timer_min`, `relay_repeat_s`, `relay_rest_state`, `boiler_heats_above_w`, `relay_is_separate_contact`) and their parse with defaults, `RelayOptions` in `ControlOptions`, `CONFIG_BLOCKERS` (with `relay_contact_not_confirmed`), `config_blockers` (new parameter: the mapped signals), `hand_back_effect`, `HandBackEffect.RELAY_RESTS_OFF/ON`, `TARGET_KEYS`. `core/controller.py:113-160` (`on_off`, optional setpoint), `303-357` (skip water), `345-352` (no FALLBACK). `core/loop.py:71-125` (relay branch). New `core/relay.py` (`plan_relay`, `heat_evidence`, the fixed values). `transport/writers.py`: `RelayWriter` (context, domains, rest-state hand-back), `writer_services` (122-138), `make_writer` (346-353), `_call` passes a `Context` (106-116). `control.py`: `_boiler_link` (688-698), the relay listener in `async_start` (377-399) and its removal in `async_stop`, the relay step in `_async_step` (586-664), `_async_follow_hand_back` folding (588-589, 900-918), `restore` (370-373), `_checks` (765-782), `ControlAlarm` (147-157), `RUNTIME_BLOCKERS` (91-99, with `relay_used_by_zone`, `relay_of_boiler_interface`), `ControlStatus` (168-195), the `relay_ignored` issue. `config_flow.py`: path choices per class in `control_schema` (437-449) and `control_error` (667-682, relay: no read-back, topology or kind); new `control_relay_schema` and `async_step_control_relay` / `async_step_control_relay_from_vt`; the relay path's behaviour step shows the thresholds, opening, learning pauses, the frost fields and the activation delay `activation_delay_s` (X4's field, with its pre-fill from VT), moved from the curve step for this path only, with the same T-37 check; on the relay path this step is reached at the simple level too, where it shows the activation delay only (decision 5: shown at the simple level), the other fields following `CONTROL_ADVANCED_KEYS` as today; X1's `return_after_outside_change` is not offered on the relay path; `signals_schema` without `REQUIRED_FIELDS`; `boiler_power` in `SIGNAL_FIELDS` (advanced). `vtherm_link.py`: `vt_central_boiler_settings`, `parse_vt_command`, the underlying-entities reader (X5.19). `switch.py:57-69`, `sensor.py:342-343, 458-499`, `binary_sensor.py:30-92, 206-218`, `coordinator.py:620-665`, `core/signal_check.py:53-55`. Translations.

**Texts** (en / pl).
- `selector.write_path.options.relay` — "Relay (on/off boiler)" / "Przekaźnik (kocioł wł./wył.)". Boiler-class description (`en.json:70, 330`) — "Control: a flow setpoint (water temperature) or on/off (relay); the other classes are monitored only." / "Sterowanie: nastawa zasilania (temperatura wody) albo wł./wył. (przekaźnik); pozostałe klasy są tylko monitorowane."
- Step `control_relay` — title "Relay" / "Przekaźnik"; description en "How the plugin switches an on/off boiler, as Versatile Thermostat's central boiler did. Recommended: the relay contact on the boiler's room-thermostat terminals — a volt-free contact; check the manual or ask an installer, as these terminals may carry mains voltage — never in the boiler's power supply, which would also cut its pump overrun and its own frost protection. Keep the old thermostat wired in parallel on the boiler's terminals (not on the relay's input), set low: it heats if Home Assistant fails — but valves Versatile Thermostat drives stay where they were while Home Assistant is down, so its heat may not reach every room. Set the relay to start off after a power cut. Set the relay's own button or input to \"detached\", so pressing it does not switch the boiler. Optionally give the relay its own switch-off timer, renewed by every \"on\"; set it only once the plugin's control starts. Test all this once in summer. The boiler sets its own water temperature: the curve and water limits do not apply, and with underfloor heating on a loop without a mixing valve its own setting must suit the floor." / pl "Jak wtyczka włącza i wyłącza kocioł dwustanowy — tak jak kocioł centralny Versatile Thermostat. Zalecane: styk przekaźnika na zaciskach termostatu pokojowego kotła — styk bezpotencjałowy; sprawdź instrukcję albo zapytaj instalatora, bo na tych zaciskach może być napięcie sieciowe — nigdy w zasilaniu kotła, co odcięłoby też wybieg pompy i jego własną ochronę przed zamarzaniem. Zostaw stary termostat podłączony równolegle na zaciskach kotła (nie na wejściu przekaźnika), nastawiony nisko: zagrzeje, gdy Home Assistant zawiedzie — ale zawory sterowane przez Versatile Thermostat zostają wtedy tam, gdzie były, więc ciepło może nie dojść do każdego pokoju. Ustaw przekaźnik tak, by po zaniku zasilania startował wyłączony. Ustaw własny przycisk lub wejście przekaźnika jako „odłączone”, żeby jego naciśnięcie nie przełączało kotła. Opcjonalnie włącz w przekaźniku własny wyłącznik czasowy, odnawiany każdym „włącz”; ustaw go dopiero, gdy ruszy sterowanie wtyczki. Sprawdź to wszystko raz latem. Temperaturę wody ustala sam kocioł: krzywa i granice temperatury wody nie mają zastosowania, a przy ogrzewaniu podłogowym bez zaworu mieszającego jego ustawienie musi pasować do podłogi."
- Step `control_relay_from_vt` — the same, plus en "Versatile Thermostat's central boiler drives this boiler now. Its settings are filled in where the plugin can use them — the relay from its commands (a switch turned on and off, or a boiler thermostat set to heat and off; otherwise pick the relay), the start delay, the repeat interval, and the thresholds as VT really used them (VT rounds them down to whole numbers in its power unit; VT counts devices and the plugin counts rooms, so the count is filled in only where every room has one device). Check them and save. Then: 1. wait for the monitoring period; 2. in VT's central configuration untick \"Use a central boiler\" (VT then deletes its commands); 3. restart Home Assistant — until then VT may still switch the relay, so control waits; 4. untick \"Used by central boiler\" in rooms where Auto-TPI learns (the plugin's repair issue names them); 5. move automations and dashboards off VT's boiler sensor and event; 6. switch control on — and only now set the relay's own timer." / pl "Tym kotłem steruje teraz kocioł centralny Versatile Thermostat. Jego ustawienia są wpisane tam, gdzie wtyczka może ich użyć — przekaźnik z jego poleceń (przełącznik włączany i wyłączany albo termostat kotła ustawiany na grzanie i wyłączenie; w innym razie wybierz przekaźnik), opóźnienie startu, odstęp powtórzeń i progi tak, jak VT ich naprawdę używał (VT zaokrągla je w dół do liczb całkowitych w swojej jednostce mocy; VT liczy urządzenia, a wtyczka pokoje, więc liczba jest wpisana tylko tam, gdzie każdy pokój ma jedno urządzenie). Sprawdź je i zapisz. Potem: 1. poczekaj na koniec okresu monitorowania; 2. w centralnej konfiguracji VT odznacz „Użyj kotła centralnego” (VT usunie wtedy swoje polecenia); 3. uruchom ponownie Home Assistant — do tego czasu VT może jeszcze przełączać przekaźnik, więc sterowanie czeka; 4. odznacz „Używany przez kocioł centralny” w pokojach, w których uczy się Auto-TPI (problem do naprawy wtyczki je wymienia); 5. przenieś automatyzacje i pulpity z czujnika i zdarzenia kotła VT; 6. włącz sterowanie — i dopiero teraz ustaw własny wyłącznik czasowy przekaźnika."
- Fields (label / description):
  - `relay_entity` — "Relay" / en "The switch on the boiler's room-thermostat terminals, or a boiler thermostat entity the plugin sets to heat or off. Not a helper (input_boolean): it confirms nothing. Never a setting the boiler stores in its memory (e.g. EMS-ESP's \"heating activated\"): every switching would wear it. Not a switch a Versatile Thermostat zone uses. For a boiler thermostat entity, \"heat\" confirms the command, not that the burner fires. A Zigbee relay may look available for up to 2 hours after it dies (ZHA), or always (Zigbee2MQTT with availability off): turn availability reporting on." / pl "Przekaźnik" / "Przełącznik na zaciskach termostatu pokojowego kotła albo encja termostatu kotła, którą wtyczka ustawia na grzanie lub wyłączenie. Nie pomocnik (input_boolean): niczego nie potwierdza. Nigdy ustawienie, które kocioł zapisuje w pamięci (np. „heating activated” w EMS-ESP): każde przełączenie by ją zużywało. Nie przełącznik używany przez strefę Versatile Thermostat. Dla encji termostatu kotła „grzanie” potwierdza polecenie, nie to, że palnik się pali. Przekaźnik Zigbee może wyglądać na dostępny do 2 godzin po awarii (ZHA) albo zawsze (Zigbee2MQTT z wyłączoną dostępnością): włącz raportowanie dostępności."
  - `relay_is_separate_contact` — "This is a separate relay contact, not a setting stored in the boiler's memory" / en "Tick to confirm that the relay is a separate contact (e.g. on the boiler's room-thermostat terminals), not an on/off setting the boiler keeps in its memory, such as EMS-ESP's \"heating activated\": every switching would wear that memory. Control does not start until this is ticked." / pl "To osobny styk przekaźnika, a nie ustawienie zapisywane w pamięci kotła" / "Zaznacz, aby potwierdzić, że przekaźnik jest osobnym stykiem (np. na zaciskach termostatu pokojowego kotła), a nie ustawieniem wł./wył., które kocioł trzyma w pamięci, jak „heating activated” w EMS-ESP: każde przełączenie zużywałoby tę pamięć. Sterowanie nie ruszy, dopóki tego nie zaznaczysz."
  - `relay_reports_state` — "The relay reports its real state" / en "Yes: the relay sends its contact state to Home Assistant; the plugin checks it every 5 minutes and after every return, writes only when it differs, sends its command again after a restart (up to 3 unreported restarts a day), and sets it back once if something else switches it; a second switch within a day, or a fourth unreported restart, makes the plugin set the relay to its state after hand-back once, step aside and leave it alone. No, or I don't know (default): the plugin cannot see the relay, repeats its command at the repeat interval and shows \"controlled without confirmation\"; a change made at the relay is undone within that time. An entity marked as an assumed state always counts as no." / pl "Przekaźnik zgłasza swój rzeczywisty stan" / "Tak: przekaźnik wysyła do Home Assistant stan styku; wtyczka sprawdza go co 5 minut i po każdym powrocie, zapisuje tylko przy różnicy, po restarcie wysyła polecenie ponownie (do 3 niezgłoszonych restartów na dobę), a gdy przełączy go coś innego — przywraca raz; drugie przełączenie w ciągu doby albo czwarty niezgłoszony restart sprawia, że wtyczka raz ustawia przekaźnik w stan po oddaniu sterowania, wycofuje się i więcej go nie rusza. Nie albo Nie wiem (domyślnie): wtyczka nie widzi przekaźnika, powtarza polecenie co podany odstęp i pokazuje „sterowany bez potwierdzenia”; zmiana zrobiona na przekaźniku zostanie w tym czasie cofnięta. Encja oznaczona jako stan zakładany zawsze liczy się jako Nie." Options `yes` "Yes"/"Tak", `no` "No"/"Nie", `unknown` "I don't know"/"Nie wiem".
  - `relay_power_on_state` — "State after a power cut" / en "What the relay does when its power returns — its own setting, which the plugin cannot read. Off (recommended): the boiler waits off until Home Assistant is back and gives its command. On, last state, or I don't know (default): after a power cut the boiler may heat without control until Home Assistant is back. Off or On: a relay found in that state, although Home Assistant saw no outage, is taken as restarted, and the plugin sends its command again — up to 3 times a day; the fourth time counts as something else switching the relay, and the plugin steps aside. Last state or I don't know: any change at the relay is taken as a possible restart in the same way." / pl "Stan po zaniku zasilania" / "Co robi przekaźnik po powrocie zasilania — to jego własne ustawienie, którego wtyczka nie odczyta. Wyłączony (zalecane): kocioł czeka wyłączony, aż wróci Home Assistant i wyda polecenie. Włączony, ostatni stan albo Nie wiem (domyślnie): po zaniku zasilania kocioł może grzać bez sterowania, dopóki nie wróci Home Assistant. Wyłączony albo Włączony: przekaźnik zastany w tym stanie, choć Home Assistant nie widział przerwy, jest traktowany jak po restarcie i wtyczka wysyła polecenie ponownie — do 3 razy na dobę; za czwartym razem uznaje, że przekaźnik przełącza coś innego, i się wycofuje. Ostatni stan albo Nie wiem: każda zmiana na przekaźniku jest w ten sam sposób traktowana jak możliwy restart." Options `off` "Off"/"Wyłączony", `on` "On"/"Włączony", `last` "Last state"/"Ostatni stan", `unknown` "I don't know"/"Nie wiem".
  - `relay_off_timer` — "Relay's own switch-off timer" / en "Whether the relay switches itself off some time after an \"on\" (Tasmota's PulseTime; a Shelly's auto-off — whether a Shelly restarts it on a repeated \"on\" is not documented, so test it). None: the plugin writes only when the relay's state differs. A length (enter it below): the plugin repeats \"on\" at half that time, at most at the repeat interval, and the relay switches heating off by itself if Home Assistant stops. I don't know (default): treated as \"it may have one\" — the plugin repeats \"on\" at the repeat interval; a timer shorter than that interval looks like something else switching the relay, so declare it. Set a timer in the relay only once the plugin's control starts, or it switches heating off while VT still drives the relay." / pl "Własny wyłącznik czasowy przekaźnika" / "Czy przekaźnik sam się wyłącza po pewnym czasie od „włącz” (PulseTime w Tasmocie; auto-off w Shelly — nie jest udokumentowane, czy Shelly odnawia go przy powtórzonym „włącz”, więc to sprawdź). Brak: wtyczka zapisuje tylko wtedy, gdy stan przekaźnika się różni. Długość (podaj ją niżej): wtyczka powtarza „włącz” co połowę tego czasu, nie rzadziej niż co odstęp powtórzeń, a przekaźnik sam wyłączy ogrzewanie, gdy Home Assistant stanie. Nie wiem (domyślnie): traktowane jak „może go mieć” — wtyczka powtarza „włącz” co odstęp powtórzeń; wyłącznik krótszy niż ten odstęp wygląda jak przełączenie przekaźnika przez coś innego, więc go podaj. Ustaw wyłącznik w przekaźniku dopiero, gdy ruszy sterowanie wtyczki, bo inaczej wyłączy ogrzewanie, gdy VT wciąż steruje przekaźnikiem." Options `none` "None"/"Brak", `minutes` "A length"/"Długość", `unknown` "I don't know"/"Nie wiem".
  - `relay_off_timer_min` — "Timer length (min)" / en "Only with a length above: the minutes, 1–120, after which the relay switches itself off." / pl "Długość wyłącznika czasowego (min)" / "Tylko gdy powyżej wybrano długość: liczba minut, 1–120, po której przekaźnik sam się wyłącza." Error `relay_off_timer_min_missing` en "Enter the timer's length in minutes." / pl "Podaj długość wyłącznika czasowego w minutach."
  - `relay_repeat_s` — "Repeat interval" / en "For a relay that reports no state, or has or may have its own timer: how often the plugin repeats its command, in seconds, 10–300. Empty (default): 300 s. Filled in from Versatile Thermostat's keep-alive when it had one of at most 300 s; a longer one is not filled in. At most 300 s: a relay that restarted in the wrong state stays so at most this long. Some relays store every command, so shorter is not always better." / pl "Odstęp powtórzeń" / "Dla przekaźnika, który nie zgłasza stanu albo ma lub może mieć własny wyłącznik czasowy: co ile sekund wtyczka powtarza polecenie, 10–300. Puste (domyślnie): 300 s. Wpisywane z podtrzymania Versatile Thermostat, jeśli było ustawione na najwyżej 300 s; dłuższe nie jest wpisywane. Najwyżej 300 s: przekaźnik, który po restarcie jest w złym stanie, zostaje w nim najwyżej tyle. Niektóre przekaźniki zapisują każde polecenie, więc krótszy odstęp nie zawsze jest lepszy."
  - `relay_rest_state` — "Relay after hand-back" / en "What the relay is set to whenever the plugin gives control back (control switched off, an error, a Home Assistant stop, or stepping aside from another controller). Off (default): the boiler heats only through a thermostat wired in parallel, if there is one; without one heating stops, and the plugin tells you when a room asks for heat or is near freezing. On: the boiler heats by its own setting with no room control — rooms are limited only by their valves, and the boiler may run against closed valves; choose it only for a boiler meant to run so, e.g. one delivered with a jumper on these terminals or with a thermostat wired in series." / pl "Przekaźnik po oddaniu sterowania" / "Na co przekaźnik jest ustawiany, gdy wtyczka oddaje sterowanie (sterowanie wyłączone, błąd, zatrzymanie Home Assistant albo wycofanie się przed innym sterownikiem). Wyłączony (domyślnie): kocioł grzeje tylko przez termostat podłączony równolegle, jeśli jest; bez niego grzanie ustaje, a wtyczka powiadomi, gdy pokój poprosi o ciepło albo zbliży się do zamarzania. Włączony: kocioł grzeje według własnego ustawienia bez sterowania pokojami — pokoje ograniczają tylko ich zawory, a kocioł może pracować na zamknięte zawory; wybierz to tylko dla kotła, który ma tak pracować, np. dostarczonego ze zworką na tych zaciskach albo z termostatem połączonym szeregowo."
  - `boiler_heats_above_w` — "Boiler heats above" / en "Optional, with the boiler's electric power mapped: the power in W above which the boiler counts as heating. Empty (default): the power is not used as proof." / pl "Kocioł grzeje powyżej" / "Opcjonalnie, gdy przypisana jest moc elektryczna kotła: moc w W, powyżej której kocioł uznaje się za grzejący. Puste (domyślnie): moc nie służy jako dowód."
- Signal `boiler_power` — "Boiler electric power" / en "Optional: the boiler's electric power, e.g. from a plug that measures it; used only as proof that a relay-driven boiler heats." / pl "Moc elektryczna kotła" / "Opcjonalnie: moc elektryczna kotła, np. z gniazdka z pomiarem; służy tylko jako dowód, że kocioł sterowany przekaźnikiem grzeje."
- Blockers (`exceptions.blocked_<key>.message`, with `{others}`): `no_relay_entity` "Pick the relay in the control options." / "Wybierz przekaźnik w opcjach sterowania."; `relay_contact_not_confirmed` "Control waits until you confirm, in the relay options, that the relay is a separate contact and not a setting stored in the boiler's memory." / "Sterowanie czeka, aż w opcjach przekaźnika potwierdzisz, że przekaźnik jest osobnym stykiem, a nie ustawieniem zapisywanym w pamięci kotła."; `path_not_for_boiler_class` "The write path does not suit the boiler class: a relay for an on/off boiler, a setpoint path for a flow-setpoint boiler." / "Ścieżka zapisu nie pasuje do klasy kotła: przekaźnik dla kotła wł./wył., ścieżka nastawy dla kotła z nastawą zasilania."; `boiler_class_no_control` "Control needs a boiler of the class \"Flow setpoint\" or \"On/off (relay)\"." / "Sterowanie wymaga kotła klasy „Nastawa zasilania” albo „Wł./wył. (przekaźnik)”."; `relay_domain_not_supported` "The relay must be a switch or a boiler thermostat entity, not a helper." / "Przekaźnik musi być przełącznikiem albo encją termostatu kotła, nie pomocnikiem."; `relay_climate_modes` "This thermostat entity cannot be set to both heat and off." / "Tej encji termostatu nie da się ustawić zarówno na grzanie, jak i na wyłączenie."; `relay_used_by_zone` "A Versatile Thermostat zone already switches this entity." / "Tę encję przełącza już strefa Versatile Thermostat."; `relay_of_boiler_interface` "This entity belongs to the boiler's or VT's own integration, not to a relay." / "Ta encja należy do integracji kotła albo VT, nie do przekaźnika."; `no_flame_signal` / `no_flow_signal` "Water-temperature control needs the flame (the flow temperature) mapped in the signals." / "Sterowanie temperaturą wody wymaga przypisania płomienia (temperatury zasilania) w sygnałach." (The same keys as form errors where the form checks them.)
- Alarms (entity names): `alarm_relay_unreachable` "Control: relay out of reach" / "Sterowanie: przekaźnik poza zasięgiem"; `alarm_boiler_not_responding` "Control: no sign the boiler heats" / "Sterowanie: brak oznak grzania kotła". (Lost commands, the relay's restarts included, use X1's `alarm_commands_lost`.)
- Issues: `relay_unreachable` en title "The relay cannot be reached" / "{relay} has been out of reach for 5 minutes. The plugin cannot switch the boiler and does not hand it back, as nothing could reach the relay; it sends its command again as soon as the relay returns. Until then the relay stays as it was, or does what its own settings say (state after a power cut: {power_on})." / pl "Przekaźnik jest nieosiągalny" / "{relay} jest poza zasięgiem od 5 minut. Wtyczka nie może przełączać kotła i nie oddaje sterowania, bo nic nie dotarłoby do przekaźnika; wyśle polecenie ponownie, gdy tylko przekaźnik wróci. Do tego czasu przekaźnik zostaje, jak był, albo robi to, co mówią jego własne ustawienia (stan po zaniku zasilania: {power_on})." (`{power_on}` filled with the untranslated option value is avoided: one issue key per declared value, `relay_unreachable_off`/`_on`/`_last`/`_unknown`, with the sentence built in.) `relay_ignored` (severity error) en title "The relay does not accept the command — check it" / description "{relay} did not take the plugin's command after three tries this session. Nothing else controls the boiler now: check the relay and the entity picked in the options. The plugin tries again when control next takes the boiler." / pl "Przekaźnik nie przyjmuje polecenia — sprawdź go" / "{relay} nie przyjął polecenia wtyczki po trzech próbach w tej sesji. Nic innego nie steruje teraz kotłem: sprawdź przekaźnik i encję wybraną w opcjach. Wtyczka spróbuje ponownie, gdy sterowanie następnym razem przejmie kocioł." `relay_rests_off` en "The boiler does not heat while control is off" / "Control of the boiler is off and the relay rests off, while {zones} ask for heat or are near freezing. The boiler now heats only through a thermostat wired in parallel, if you have one. Switch control on again, or change the relay's state after hand-back in the options." / pl "Kocioł nie grzeje, gdy sterowanie jest wyłączone" / "Sterowanie kotłem jest wyłączone, a przekaźnik pozostaje wyłączony, choć {zones} proszą o ciepło albo zbliżają się do zamarzania. Kocioł grzeje teraz tylko przez termostat podłączony równolegle, jeśli taki masz. Włącz ponownie sterowanie albo zmień w opcjach stan przekaźnika po oddaniu sterowania." Another controller on a relay: V7's repair issue `control_latched_<entry_id>` (one issue per entry), with the translation key `control_latched_relay_off` (severity error) or `control_latched_relay_on` (severity warning) by the rest state: title en "Control stepped aside: something else switches the relay" / pl "Sterowanie się wycofało: coś innego przełącza przekaźnik"; description (off) en "Something else keeps switching {relay} — an automation, its own button, a person, or restarts the relay does not report. The plugin set it back; it kept changing, so the plugin stepped aside: it switched the relay off once, its state after hand-back, and now leaves it alone. The boiler heats only through a thermostat wired in parallel, if there is one. If the relay restarts without reporting it, or has its own switch-off timer, declare its state after a power cut and its timer in the options; if it restarts several times a day, check its power supply and connection. Switch control off and on to take the relay back." / pl "Coś innego przełącza {relay} — automatyzacja, jego własny przycisk, osoba albo restarty, których przekaźnik nie zgłasza. Wtyczka przywracała stan; zmieniał się dalej, więc wtyczka się wycofała: raz wyłączyła przekaźnik, zgodnie z jego stanem po oddaniu sterowania, i teraz go nie rusza. Kocioł grzeje tylko przez termostat podłączony równolegle, jeśli taki jest. Jeśli przekaźnik uruchamia się ponownie bez zgłoszenia albo ma własny wyłącznik czasowy, podaj w opcjach jego stan po zaniku zasilania i ten wyłącznik; jeśli restartuje się kilka razy na dobę, sprawdź jego zasilanie i łączność. Wyłącz i włącz sterowanie, aby znów przejąć przekaźnik."; description (on) the same, with en "it switched the relay on once, its state after hand-back, and now leaves it alone; the boiler heats by its own setting, without room control." instead of the sentence on "off" and the parallel thermostat / pl "raz włączyła przekaźnik, zgodnie z jego stanem po oddaniu sterowania, i teraz go nie rusza; kocioł grzeje według własnego ustawienia, bez sterowania pokojami."
- Switch attributes: `off_by.state.relay` "The relay" / "Przekaźnik"; `hand_back_effect.state.relay_rests_off` "The relay rests off: heat only from a thermostat in parallel" / "Przekaźnik zostaje wyłączony: ciepło tylko z termostatu równoległego"; `relay_rests_on` "The relay rests on: the boiler heats by its own setting" / "Przekaźnik zostaje włączony: kocioł grzeje według własnego ustawienia"; `confirmation.state.controlled_without_confirmation` "Controlled without confirmation" / "Sterowany bez potwierdzenia"; `without_heat_confirmation` "Controlled without confirmation that the boiler heats" / "Sterowany bez potwierdzenia, że kocioł grzeje".

**Missing data.** No relay picked → `no_relay_entity`: control inactive, naming it. The separate-contact tick not given → `relay_contact_not_confirmed`: control does not start, the monitor runs (answer G). The relay unavailable, removed or `unknown` → R6: the alarm after 5 min, no hand-back, nothing switched by the plugin meanwhile, the command sent on return. Relay settings unanswered → the cautious defaults of R3 (state report "I don't know": blind repeats; timer "I don't know": "on" repeated; power-cut state "I don't know": a change while the relay stayed available is a possible restart, the command sent again up to 3 times within 24 h, the fourth another controller (answer N), and the warning that the boiler may heat without control after a power cut). Flame, flow, gas meter, power or its threshold missing → the proof is inactive ("without confirmation that the boiler heats"), control unchanged. Outdoor temperature missing → irrelevant (no curve), never `FALLBACK`. Zones unknown → X3's recognition, grace and "every zone unknown → relay off" with the alarm and repair issue (decision 3), or, with X3's "own room controller" tick and the rest state "on", the rest state (answers F and M; with the rest state "off" the tick changes nothing). No stored last command, the wish unknown, or an unreadable store → no restore; the relay is left as found until the recognition period ends (an unreadable store: V1's full hand-back first, the rest state). VT's central entry absent, its commands free-form or deleted, its thresholds 0, its keep-alive above 300 s → nothing pre-filled for that field; the user picks. A proof signal known but never showing heat → only the information alarm. None of these switches the relay off by itself, except decision 3's case (every zone unknown after the grace, without the tick), a stop for the boiler's own fault (Y1), and a hand-back the user, a blocker or stepping aside causes.

**Do not.** Add minimum on/off times or a switching cap (decision 13); hand back while the relay is out of reach; write the rest state against another controller more than once — the step-aside writes it once (answer H) and then leaves the relay alone, read back or not (answer L), and a rest state then changed with no trace is left to the other controller, never retried (never fighting, answer C); answer a relay that keeps turning up in its power-cut state — or, with "last" or "I don't know", keeps changing while available — more than 3 times within 24 h (answer N); count the "own room controller" tick with the rest state "off" (answer M); step aside at once on a Home Assistant user's context (not adopted); offer X1's return by itself on the relay path; cancel or restart the activation delay when demand drops (not adopted; X4 builds VT's semantics); refuse rest "on" unless series wiring (not adopted); accept `input_boolean` or free-form VT actions; start control without the separate-contact tick, or pre-fill it; treat the relay's state as proof that the boiler heats; turn the relay on at a hand-back except when the rest state is "on"; write to VT or read VT outside `vtherm_link.py`; build the recorded "heating commanded" entity and event (0.3, "Open after 0.2.2" item 10); add a wiring field (not decided; "Open after 0.2.2" item 11, provisional, K4); check the Shelly timer at J4 (K6, on the user's own relay).

**Open for the user.** Answered on 2026-09-27 and built as above: how a relay found in another state is judged (answers C and D, R7: E's second-fall-back rule is not used for relays); the separate-contact tick (answer G, R3); stepping aside with the rest state and a latch (answer H, R7, R9); no return by itself for relays (decision 6). The two questions left before are answered too, and are rules now: the "own room controller" tick counts on the relay path only with the rest state "on" (the user, 2026-09-27, M; R5); a relay found in its declared power-cut state is answered as a restart only 3 times within 24 h, the fourth being another controller, and with "last" or "I don't know" a change while available is a possible restart in the same way (the user, 2026-09-27, N; R3, R7). Stepping aside sets the relay once to its rest state and then leaves it alone (the user, 2026-09-27, L; R7, R9). On the K4 list: the reading that restarts with a trace (answer C) do not count toward N's fourth (R7).

## Phases Y and Z, and the closing sections — details

These sections give the "how" for steps Y1–Y4 and Z1–Z4 of `docs/plan-0.2.2.md`, and what a session does at "Open after 0.2.2", "After 0.2.2" and "Done for 0.2.2". The plan is still the source of the decisions. Where a rule below differs from a research note's proposal, the plan and its decisions win; the user's answers of 2026-09-27 (A–O) win over both. Where the plan, the decisions and the answers are silent, the most cautious option is taken and marked "(provisional, K4)". Every such number also goes into the fixed-values list of S-37 (Q1 G): its value, its reason and its step; K4's agenda (Q4) lists it.

Common to every step below:

- **Done** means every scenario of each problem the step names is covered: the review's row, its §6 test and section 4's proposal. Every new mechanism also gets a negative test with an unknown, missing or `None` input. Anything left over is named in "Open after 0.2.2", with a release.
- **Before each commit**, run `scripts/env.sh python -m pytest -q` and `scripts/env.sh ruff check .`. From Z1 on, run the two pytest invocations Z1 sets up, plus `ruff format --check` and `mypy`.
- **Bookkeeping without waiting** (the user's answer B of 2026-09-27): marking a step ✅ in `docs/plan-0.2.2.md`, and adding a remainder to "Open after 0.2.2", are committed without waiting. The diff goes into the step's report to the user. Every other `*.md` change (SCOPE, PLAN, CLAUDE.md, READMEs, `devenv/README.md`) is shown as a diff and waits for consent.
- **Reports and results:** reports to the user are in plain, less technical Polish. All findings and raw results are saved locally, under `research/`.
- **Polish in the repository:** Polish wording goes only into `translations/pl.json`, because everything else in the repository is English (CLAUDE.md). The "Texts" parts below give the English source and say what the Polish must keep: the placeholders, the units, and entity names as the Polish Home Assistant UI shows them.
- **Line numbers:** "current lines" below are those of commit d545869. Phases V and X run earlier and move them, so find the code by the names given.

### Y1 — Alarms: unknown inputs, the boiler's own fault, notifications, the pressure trend

**Goal and done-when.**
- An alarm that cannot judge says `unknown`, after a short hold.
- Heating stops for an alarm only while the boiler itself reports a fault that stops it. Control then sends its usual "off": no hand-back, no latch.
- Low pressure without such a fault only raises an "add water" notification, at a threshold the user enters. There is no threshold by default.
- High pressure and hot flue gas only inform, with a notification that says what to do.
- Only an allow-list of alarms may hand back.
- The pressure trend takes the water temperature into account, so a slow leak shows in winter too.

Done when:
- every scenario of P-17, P-22, P-26, P-27, P-29, P-81, P-82, P-85, P-99, S-16, S-30 and S-62 is covered, together with the three Y1 findings of the checks: unstable ignition counting burns that end on temperature, a stored hand-back reaction hidden at the simple level, and the 0.7 bar default;
- the user's answers F, H, I, M and O of 2026-09-27 are built where they touch the alarms (the "own control resumes" effect and where the tick counts, the step-aside's full hand-back, the monitor failure and the heating switch's "off" ignored from the start in the allow-list);
- T-16, T-33, T-34 and the integration part of T-21 pass;
- the step's report answers review questions 8 and 9;
- Y1 is ✅ and committed.

**Read first.**
- **Plan:**
  - "Decisions of 2026-09-26/27": "Missing data" and "Boiler protection follows the boiler's own logic";
  - decision 7;
  - the user's answers of 2026-09-27: F (the tick "the boiler has its own room controller"; a relay resting "on" is not a working thermostat), H (the full safe hand-back when stepping aside from another controller), I (the monitor failure), M (the tick not offered on a gateway; on the relay path it counts only with the rest state "on") and O (the heating switch's "off" ignored from the start blocks control and hands back);
  - "Findings of the checks": the `unstable_ignition`, hidden-reaction and 0.7 bar bullets;
  - the Y1 row.
- **Review:**
  - P-17, P-22, P-26, P-27, P-29, P-81, P-82, P-85, P-99 (§3);
  - S-16, S-30, S-62 (§3 and §4);
  - T-16, T-21, T-33, T-34 (§6);
  - Appendix E, questions 8 and 9.
- **Research:**
  - `research/2026-09-26-boiler-protection-alarms.md`: "Decided by the user", "Verification → Corrections", "Missing", "Safety concerns";
  - `research/2026-09-26-q4-decision-7-alarms.md`: "Decided by the user" (its option B was **not** adopted), "Corrections", "Missing";
  - `research/2026-09-27-fresh-session-test.md` § Y1;
  - `research/2026-09-27-plan-0.2.2-checks.md`, Fidelity items 5 and 6.
- **Code:**
  - `core/alarms.py` (all), `core/analysis.py:107-153`, `core/signal_check.py:58-187`, `core/signals.py`;
  - `units.py:104-128`, `transport/entities.py:30-66`;
  - `coordinator.py:539-713`;
  - `core/controller.py:142-156, 226-270`;
  - `control.py:147-157, 586-640, 700-763`;
  - `control_config.py:80-122, 157-160, 267-270, 299-314`;
  - `config_flow.py:80-95, 349-384, 395-408, 569-582, 1244-1261, 1420-1443`;
  - `config.py:88-97, 300-346`;
  - `binary_sensor.py:24-42, 143-171`;
  - `__init__.py:90-107`;
  - `translations/en.json:177-198, 437-458, 470-480, 582-612, 985-1060, 1225-1275`.
- **Home Assistant (interface only):** `.venv/.../opentherm_gw/binary_sensor.py`.
  - The boiler device has "Low water pressure", "Gas fault", "Air pressure fault", "Water overtemperature" and "Fault indication" (l. 38-142).
  - It has **two** "Central heating 1" entities. One is the boiler's own status: device class running, `DATA_SLAVE_CH_ACTIVE` (l. 44-49). The other is the CH enable the gateway sends: no device class, `DATA_MASTER_CH_ENABLED` (l. 354-359).

**Order of work.**
1. **Core tests, `tests/core/test_alarms.py`** — unknown inputs and holds:
   - `test_an_unknown_input_holds_the_alarm_one_hour_then_is_unknown` — Given `pressure_high` active at 2.9 bar; When the value is `None` for 59 min, then for 61 min; Then it stays active (reason `held`), then `active is None`.
   - `test_an_input_unknown_from_the_start_is_unknown_at_once` — Given no reading ever; When judged; Then `active is None`, never `False`.
   - `test_the_alarm_level_needs_five_minutes_of_known_readings` — Given 2.9 bar known; When 4 min 59 s pass, then 5 min; Then level `warning`, then `alarm`. A `None` sample in between restarts the count.
2. **Core tests, `tests/core/test_alarms.py`** — low pressure:
   - `test_low_pressure_has_no_default_threshold` — Given no `add_water_below`; When the pressure is 0.3 bar; Then no `pressure_low` alarm is computed.
   - `test_add_water_after_five_minutes_below_the_threshold` — Given a threshold of 0.8 bar; When the pressure is 0.75 bar for 5 min; Then `pressure_low` is on. At 4 min it is still off.
3. **Core tests, `tests/core/test_alarms.py`** — counts, burns and pauses:
   - `test_frequent_starts_clears_two_below_its_limit` — Given limit 12; When 13, then 12, 11, then 10 starts per hour; Then on, on, on, off. `test_unstable_ignition_clears_two_below_its_limit` works the same way.
   - `test_a_short_burn_ending_at_its_setpoint_is_not_unstable` — Given a 40 s burn whose flow at its end is ≥ the CH setpoint − 2 K; Then it is not counted. A burn ending 10 K below is counted.
   - `test_unstable_ignition_without_flow_or_setpoint_counts_as_before` (negative) — flow and CH setpoint not mapped: counted as today, and the feature is degraded.
   - `test_hysteresis_samples_only_from_pauses_with_demand_throughout` — a pause during which zone demand turns `False` gives no sample. Negative: zone demand unknown gives no sample.
   - `test_low_flow_is_not_judged_with_hot_water_unknown` — Given `has_dhw` and `dhw=None`; Then reason `hot_water_unknown`, held, then `unknown`. Given `has_dhw=False`; Then it is judged.
4. **Core tests, `tests/core/test_alarms.py`** — the pressure trend:
   - `test_the_pressure_trend_sees_a_leak_with_warm_water` — Given 8 days where the flow never drops below 35 °C, the pressure follows 0.01 bar/K, and a real loss of 0.3 bar lies between the windows; Then `pressure_falling` is on. Without the loss it is off.
   - `test_the_pressure_trend_without_a_slope_falls_back_to_cold_samples` — flow spread < 10 K: only cold samples count. With fewer than 20 per window the result is `unknown`.
   - `test_the_pressure_trend_is_unknown_without_flow_or_flame` (negative).
5. **Core test, `tests/core/test_signal_check.py`**: T-16 `test_outdoor_stuck_is_detected_within_twelve_hours`. Negative: a sensor that last changed 11 h ago is not stuck.
6. **Core tests, `tests/core/test_controller.py`:**
   - `test_a_boiler_fault_sends_off_without_hand_back_or_latch` — Given control holding and `boiler_fault` true for 5 min; Then `command.ch_enable is False`, `hand_back is False`, `latched is False` and mode `boiler_fault`. When the fault clears, heating follows the zones in the same step.
   - `test_the_fault_stop_ends_at_once_when_the_signal_is_unknown`.
   - `test_frost_heating_waits_while_the_boiler_reports_its_fault`.
   - `test_a_fault_shorter_than_five_minutes_changes_nothing`.
   - `test_no_fault_signal_mapped_changes_nothing` (negative).
7. **`tests/test_control_config.py`:**
   - `test_only_allow_listed_alarms_may_hand_back` — a stored `pressure_low: hand_back`, `write_failed: hand_back` or an unknown key gives `reaction()` = info.
   - `test_own_control_resumes_is_its_own_effect` — a hand-back value declared `own_control`, or answer F's tick "the boiler has its own room controller" on the entity path: `OWN_CONTROL_RESUMES`. A gateway with an OpenTherm thermostat declared: still `THERMOSTAT_TAKES_OVER`, a tick stored there ignored (answer M). A relay: `RELAY_RESTS_OFF` / `RELAY_RESTS_ON` by its rest state. An undeclared virtual topology: `DEVICE_DECIDES`. Stand-alone: `HEATING_STOPS`.
   - `test_write_ignored_may_hand_back_only_where_a_thermostat_or_own_control_takes_over` — Stand-alone: a stored `hand_back` gives info. With an OpenTherm thermostat declared, a hand-back value declared `own_control`, or answer F's tick: hand back. Negatives: a relay path (either rest state) and an undeclared effect give info.
   - `test_heating_off_ignored_from_the_start_always_hands_back` (answer O) — the heating switch's "off" ignored from the start: `reaction()` gives a hand-back and a latch whatever is stored (`info` included) and whatever the effect, stand-alone included; Negative: only "on" ignored → the optional `write_ignored` rule above.
8. **`tests/test_units.py` and integration:**
   - T-33 `test_zero_pressure_from_a_non_gateway_sensor_raises_add_water` — Given a threshold of 0.8 bar entered, and a pressure entity registered by a platform other than `opentherm_gw`, or by `mqtt` on a device that does not carry the OTGW firmware's read-back (e.g. an EMS-ESP sensor); When the value goes 1.5 → 0.0 and stays for 5 min; Then `pressure_low` is on and the repair issue `add_water_<entry>` exists.
   - `test_zero_pressure_from_the_gateway_is_unknown` — registry platform `opentherm_gw`; and registry platform `mqtt` on the device of the `otgw_mqtt` read-back.
9. **Integration tests, in `tests/integration/test_control.py` or a new `tests/integration/test_alarms.py`:**
   - T-34 `test_the_pressure_alarm_is_unknown_while_pressure_is_unknown` — the pressure entity unavailable from the start: the alarm state is `unknown`. Unavailable for 61 min after a reading: `unknown`.
   - `test_notifications_open_after_five_minutes_and_close_after_an_hour_in_range` — 2.9 bar for 5 min: issue `pressure_high_<entry>`. Then 2.3 bar: still open at 59 min, gone at 60 min. An unknown value keeps it open.
   - `test_flue_gas_notification_counts_during_hot_water`.
   - `test_every_alarm_hand_back_or_latch_raises_a_repair_issue`: a latch by `outside_change`, by `write_ignored` set to hand back, or by the heating switch's "off" ignored from the start (`heating_off_ignored`, answer O) raises V7's `control_latched_<entry>`, naming the cause; a hand-back by `control_error` or `boiler_link_lost` raises `hand_back_<alarm>_<entry>`; one by `monitor_failed` raises only V6's `monitor_failed_<entry>`. Severity error where the hand-back effect is "heating stops" (stand-alone, a value declared "heating stops", a relay left "off"), else warning. Negative: never two issues for one cause.
   - `test_an_allow_listed_alarm_active_at_switch_on_blocks_control_at_once` (with `boiler_link_lost`, X2).
   - T-21 (integration part) `test_hot_water_draws_with_the_named_ch_echo_raise_no_outside_change` — the gateway harness, the echo taken from the boiler device's CH-enable entity, two 10-min draws: no `outside_change`, no `write_ignored`, no latch.
10. **Flow tests, `tests/integration/test_config_flow.py`:**
    - the monitor step offers `add_water_below` (optional, empty) and no longer offers `pressure_low_warning` or `pressure_low_alarm`;
    - the signals step offers `low_pressure_fault` and `boiler_lockout` (binary sensors only), and refuses one entity for both;
    - the alarm-reaction choice appears only where it is allowed, at both levels, and never on the relay path;
    - "restore defaults" resets it.
11. **Migration test, `tests/integration/test_setup.py` (feeds P-124):**
    - stored 1.0 / 0.7 are dropped;
    - stored 0.8 / 0.5 give `add_water_below` 0.8;
    - reactions no longer allowed are dropped, and one warning repair issue names them;
    - the minor version rises.
12. Then the code, the texts and both commands. Mark ✅ and commit.

**Rules and values.**
1. **Allow-list (decision 7, S-30, S-62).** It lives in one place: `control_config.py`, next to `DEFAULT_REACTIONS`.
   - **Always:**
     - `control_error`;
     - `boiler_link_lost`, but not for a relay (X8: its `relay_unreachable` informs, with no hand-back);
     - `outside_change`, meaning another controller as decision 6 describes: the full safe hand-back, then the latch (answer H);
     - `monitor_failed`, V6's runtime blocker after 5 min: control hands back and resumes by itself once the monitor works again, with an information note (answer I).
     - `write_ignored` for the heating switch's "off" ignored from the start (answer O): control is blocked and the boiler handed back, with the latch `heating_off_ignored` and X5.21's blocker until the user switches control off and on — like an installation without a working heating switch (decision 11), whatever the hand-back effect.
     - `control_error` and `monitor_failed` hand back as runtime blockers, and `boiler_link_lost` through X2's stale-link rule (no latch; it resumes by itself), whatever a stored reaction says; `outside_change` through the guard's block (V7); the heating switch's "off" ignored from the start through X1's latch.
   - **Optional, information by default:** `write_ignored` for any other target or value. It is offered only where the hand-back effect is "thermostat takes over" or "the boiler's own control resumes" (rule 2).
   - **Information:** everything else. That is every `AlarmKind` (`core/alarms.py:25-34`), `write_failed`, and every alarm added later (X1's `commands_lost` and `confirmation_missing`, X4's circuit alarm, V7's `handed_back_in_frost`, X8's `relay_unreachable` and `boiler_not_responding`).
   - `ControlOptions.reaction()` (`control_config.py:157-160`) returns information for anything not allowed, whatever is stored. This is how stored reactions are neutralised.
   - `_hand_back_alarms` (`control.py:740-763`) takes only allowed alarms with `active is True`. An unknown value (`None`) never hands back.
2. **"Own control resumes" is its own effect.** `hand_back_effect` (`control_config.py:299-314`) today maps a value declared `own_control` and an undeclared virtual topology to the same `DEVICE_DECIDES`.
   - Add `OWN_CONTROL_RESUMES` for a hand-back value declared `own_control`, and for answer F's tick "the boiler has its own room controller" (X3 adds the tick; if X3 already added the effect with it, Y1 keeps it and adds only the alarm rules here).
   - A gateway with an OpenTherm thermostat declared stays `THERMOSTAT_TAKES_OVER` (`control_config.py:307-313`). A relay keeps X8's `RELAY_RESTS_OFF` / `RELAY_RESTS_ON`: its rest state decides whether the boiler can heat at all. Answer M of 2026-09-27 settles how answer F's tick combines with the paths: on the relay path it counts toward the working thermostat only with the rest state "on" (X3, X8), while `hand_back_effect` stays the relay's own; on a gateway it is not offered, and a stored one is ignored.
   - `write_ignored`'s hand-back is offered where the effect is `THERMOSTAT_TAKES_OVER` or `OWN_CONTROL_RESUMES`. It is not offered where the effect is `HEATING_STOPS`, undeclared (`DEVICE_DECIDES`), or on the relay path (`RELAY_RESTS_OFF` / `RELAY_RESTS_ON`): X8 treats an ignored relay command as information, sent again with no block, and a relay resting "on" is not a working thermostat (answer F). The heating switch's "off" ignored from the start is not this optional reaction: rule 1 always hands back and latches (answer O).
   - Where the effects are read: V5's heating-switch rule treats `OWN_CONTROL_RESUMES` as it treats `DEVICE_DECIDES` (the heating switch on at hand-back); V7's `frost_protection_by` shows `device` for it.
3. **The boiler's own fault (Boiler protection; a stated exception of principle 12, Q1).**
   - Add two optional binary signals to `core/signals.py`: `low_pressure_fault` (the signals step's simple level) and `boiler_lockout` ("another fault the boiler reports as stopping it", advanced level). Neither is required. Neither is part of the boiler link (X2). Which entities exist for them on each path is settled by Q3; the texts name the gateway's as an example only.
   - `low_pressure_fault` comes before `boiler_lockout` in `SIGNAL_FIELDS`. One entity for both: the form refuses it; in stored options the later one is dropped, shown inactive and named (Y4), and control gets the config blocker `entity_for_two_signals` (X5's rule).
   - While either one reads a known "on" for 5 min (decision 7's hold, (provisional, K4)), `decide()` gives the usual "off": `BoilerCommand(ch_enable=False, setpoint=<as decided>)`, mode `BOILER_FAULT`, reason `BOILER_FAULT`. There is no hand-back and no latch.
   - It sits after the stale-link check (`core/controller.py:249-267`) and before frost (`:269`). Frost heating waits too, because the boiler cannot heat.
   - It ends in the step where the signal reads off, unknown or unavailable. No hold applies at the end.
   - On the relay path, "off" is the relay off (X8).
   - Without control configured nothing is written, but the notification still opens.
   - While the fault lasts, repair issue `boiler_fault_<entry>` (warning, not fixable) (provisional, K4).
4. **Unknown inputs (S-16, question 9).** An alarm whose input is unknown, or which cannot be judged, keeps its last state for 1 h (provisional, K4). After that `active is None`, and the entity shows `unknown`. An input unknown from the start gives `unknown` at once. "Cannot be judged" means:
   - banded alarms: the value is `None`;
   - `low_flow`: `no_pump_signal`, `hot_water`, `hot_water_unknown`, `no_fresh_zone` or `zone_without_valve`;
   - counting alarms: the flame known for less than 50 % of their window (1 h or 24 h) (provisional, K4);
   - trends: the trend is `None`.
   
   An unknown value never raises an alarm, never completes a hold and never hands back. `Alarm.active` becomes `bool | None` (`core/alarms.py:42-50`), and `Alarm` gains `known_at`.
5. **The alarm level needs time.** A banded alarm reaches level `alarm` only after 5 min of continuous known readings beyond the alarm limit (decision 7: "about 5 minutes"). A `None` reading restarts the count. The warning level shows at once, as today. The 5 min hold gates both the entity's alarm level and the notification.
6. **Low pressure.**
   - `PRESSURE_LOW_BAND` (`core/alarms.py:67`, 1.0 / 0.7 bar) goes.
   - One optional user value replaces it: `add_water_below`, in bar, 0.1–2.0 in steps of 0.1, empty by default. It gives `Band(warning=None, alarm=value, rising=False, hysteresis=0.1)`.
   - Without it there is no `pressure_low` alarm and no entity, and the feature is inactive with "add-water threshold not entered".
   - It never stops heating.
7. **High pressure and flue gas.** The defaults stay: 2.5 / 2.8 bar with 0.1 bar hysteresis; 85 / 100 °C with 5 K, condensing boilers only. They inform: a notification at the alarm level held 5 min, hot-water draws included. There is no 10-minute hot-water filter.
8. **Notifications.**
   - They are Home Assistant repair issues: severity warning, not fixable (provisional, K4). There is one per cause per entry: `add_water_<entry>`, `pressure_high_<entry>`, `flue_gas_high_<entry>`, `pressure_falling_<entry>`, `boiler_fault_<entry>`.
   - Placeholders: `value`, and `limit`, `threshold` or `change`.
   - An issue closes after 60 min of known readings in the normal range (decision 7: "about an hour"). The normal range is:
     - for high pressure and flue gas, below the warning limit minus the hysteresis;
     - for add water, above the threshold plus 0.1 bar;
     - for the trend, not exceeded.
   - An unknown input keeps an open issue open.
   - A reload does not remove issues. Entry removal does: add the keys to the list at `__init__.py:141-147`.
9. **Repair issues for hand-backs and latches (decision 7).** Every hand-back or latch caused by an allowed alarm raises one:
   - A latch (`outside_change`, `write_ignored` set to hand back, or the heating switch's "off" ignored from the start, `heating_off_ignored`, answer O) reuses V7's `control_latched_<entry_id>`: the entry's one latch issue, whose text names the alarm that caused it (placeholder `{alarm}`). It is deleted when the latch clears (off, then on).
   - A hand-back without a latch raises `hand_back_<alarm>_<entry_id>`: `hand_back_boiler_link_lost` and `hand_back_control_error`. It is deleted when control resumes, or when the user switches control off. The monitor failure raises only V6's `monitor_failed_<entry_id>` (with its `monitor_recovered` note), never a second issue.
   - Severity is error where the hand-back effect is "heating stops" (stand-alone, a value declared "heating stops", a relay left "off"), otherwise warning.
   - One issue per cause: where V7 (`control_stopped_heating_<entry_id>`), V6 or X1 already raise an issue for the same cause, it is reused rather than doubled.
10. **An alarm active at switch-on.** If an allowed alarm is active when control is switched on, control does not start writing: mode `handed_back` at once, without a latch: the lost link resumes by itself once it has been fresh for 60 s (X2). The switch's attribute `blocked_by` names the alarm, and the control switch's text says so.
    - After the allow-list, only `boiler_link_lost` can be active at that moment (a latch and an internal error are cleared by switching off and on). X2 raises it at switch-on; Y1 adds the text and the test.
    - V6's `monitor_failed` is a transient blocker: switching on waits (V6).
11. **Pressure 0.0 (P-17, question 8).** 0.0 bar is unknown only for a pressure entity registered by `opentherm_gw`, or by `mqtt` on the same Home Assistant device as the OTGW firmware's setpoint read-back where the write path is `otgw_mqtt` (provisional, K4). That the firmware's discovery puts both on one device is assumed; it is checked at this step in the firmware's discovery file (read over the network or in `research/diy/`). Every other 0.0 is a reading, an EMS-ESP or Zigbee2MQTT sensor over MQTT included.
    - This is decided at setup, in the event loop, from the entity and device registries, and passed to `signal_value` as a flag.
    - An entity not in the registry counts as a reading.
12. **Stuck outdoor sensor (P-26).** The sensor is stuck when it has held one value since its last change for ≥ 12 h (`STUCK_WINDOW_S`, `core/signal_check.py:148`), and the weather has moved ≥ 3 K over that same tail.
13. **Low flow (P-27).** It is not judged (reason `hot_water_unknown`) when the boiler has hot water and `dhw_now` is `None`.
14. **Hysteresis drift (P-29).** Samples come only from pauses whose zone demand (`History.zone_calling`) is known `True` throughout.
15. **Unstable ignition (P-81).** A short burn counts only if, at its end, the flow was known and below the CH setpoint then in force minus 2 K (provisional, K4).
    - Mapped but unknown at the end: not counted.
    - Flow or CH setpoint not mapped: counted as today, and the feature is degraded, naming the missing signal.
16. **Hysteresis of the counts (P-82).** `frequent_starts` and `unstable_ignition` turn off only at ≤ limit − 2 (provisional, K4).
17. **Flue-gas trend entity (P-85).** `flue_gas_rising` is created only for a condensing boiler with flue gas and return mapped: the trend's own condition, `core/analysis.py:133`.
18. **Low-flow feature (P-99).** Add `Feature.LOW_FLOW`. It needs `pump_running` or `ch_active` mapped and zones with a valve opening. It is inactive with a declared bypass. Y4 shows it.
19. **The CH echo (P-22).** The CH echo text names the boiler device's "Central heating 1" that reads On/Off, which is the enable the gateway sends. It warns against the one that reads Running/Not running, which goes off during hot water.
20. **Pressure trend with the water temperature (Open after R6 #5; decided for 0.2.2).**
    - Samples are taken every 10 min where the flame has been known off for the preceding 10 min, and pressure and flow are known.
    - A slope b (bar/K) is fitted by least squares over the whole 8-day history (`HISTORY_DAYS`, `core/analysis.py:38`; a longer window is impossible). It is used only when the flow spans ≥ 10 K and 0 ≤ b ≤ 0.05 bar/K (provisional, K4).
    - Corrected pressure = p − b·(flow − 40 °C).
    - Medians are compared, as today, between 8–4 days ago and the last day (`core/analysis.py:113-114`), with ≥ 20 samples per window. A fall above 0.2 bar (`DEFAULT_PRESSURE_DROP_BAR`) raises the warning.
    - With no usable slope, only today's cold samples count (flow < 35 °C).
    - The text is "your pressure keeps falling — there is a risk of a leak", never "likely".
21. **Migration.** `config_flow.py:1135` goes from `MINOR_VERSION = 2` to 3. X steps may already have raised it; there is one migration per release.
    - No version with stored options has ever been released (nothing is published before decision 16's first version, provisionally 0.2.2b1). The migration exists for development entries and hand-edited options, and it is tested.
    - Stored `pressure_low_warning = 1.0` and `pressure_low_alarm = 0.7` are dropped.
    - Otherwise `add_water_below` = the stored warning if it differs from 1.0, else the stored alarm if it differs from 0.7 (provisional, K4).
    - Stored reactions no longer allowed are dropped. One warning issue, `reactions_removed_<entry>`, names them.
22. **Values for S-37's list:** 5 min (alarm level, notifications, the fault stop), 1 h (unknown hold), 60 min (notification close), 50 % known, limit − 2, 2 K, 10 min, 10 K, 0.05 bar/K, 40 °C, 0.1 bar; the rules for 0.0 bar (rule 11) and for the migration (rule 21), and the notification severity (rule 8).

**Code to change.**
- **`core/signals.py:22-38, 63-78`:** the two fault signals.
- **`core/alarms.py`:**
  - `Alarm` (42-50): `active: bool | None`, `known_at`;
  - `banded_alarm` (73-98): the hold, then `unknown`; the alarm level after 5 min;
  - `PRESSURE_LOW_BAND` (67): removed; the add-water band;
  - `frequent_starts` and `unstable_ignition` (106-157): hysteresis and P-81;
  - `cold_pressure_samples` (200-217): replaced by temperature-corrected samples;
  - `hysteresis_samples` (240-266): the demand argument;
  - `low_flow` (274-309): `hot_water_unknown`.
- **`core/analysis.py:107-153`:** `_trends` gets the corrected pressure trend and the zone demand passed to the hysteresis samples, and returns `unknown` when it cannot judge.
- **`core/signal_check.py`:** `Feature` (58-68) gains `LOW_FLOW`, `BOILER_FAULT_STOP`, `ADD_WATER` and `PRESSURE_TREND`, with their `need()` rules (83-129); the stuck test on the tail (152-187).
- **`units.py:121-123`:** the 0-bar rule takes a `zero_is_unknown` flag.
- **`transport/entities.py:30-66`:** the flag per signal, from the entity and device registries at construction.
- **`core/controller.py`:** `ControlMode`, `Reason`, `ControlInputs.boiler_fault`, and the new branch in `decide()` (226-270).
- **`control.py`:**
  - `_inputs` (700-733): the fault with its 5-min hold, measured on the control clock;
  - `_hand_back_alarms` (740-763): the allow-list;
  - the repair issues (next to `report_owed_hand_back`, 118-131): the latch issue's `{alarm}`, the `hand_back_<alarm>` issues and their severity;
  - the switch-on check.
- **`control_config.py`:** `INFO_ONLY_ALARMS` and `DEFAULT_REACTIONS` (118-122) replaced by the allow-list; `reaction()` (157-160); `HandBackEffect` and `hand_back_effect` (80-86, 299-314): `OWN_CONTROL_RESUMES`, unless X3 added it.
- **Where the effects are read:** V5's heating-switch rule and V7's `frost_protection_by` (`switch.py`), for `OWN_CONTROL_RESUMES` (rule 2).
- **`config_flow.py`:**
  - `SIGNAL_FIELDS` (80-95): the two faults, `_BINARY`, in that order;
  - `monitor_schema` (349-384): `add_water_below` replaces the two low-pressure fields;
  - `REACTION_ALARMS` (400-408) and `control_alarms_schema` (569-582): only the offered alarms;
  - the alarm step reached at both levels where something is offered (1420-1443); `restore_advanced_defaults` (811-822) keeps resetting it.
- **`config.py`:** `AlarmThresholds` (88-97) with `pressure_low: Band | None`; `_band` (328-335) with a `None` limit.
- **`coordinator.py`:** `_current_alarms` (667-713): the holds, add water, and the fault read for the notification; the notification issues, reusing `_issue` (744-757).
- **`binary_sensor.py`:** `_alarm_kinds` (30-42): `pressure_low` only with a threshold, `flue_gas_rising` only for condensing boilers; `AlarmSensor.is_on` (156-159) returns `None` when unknown.
- **`__init__.py:90-107`:** the migration.

**Texts** (en source; pl with the same meaning in `pl.json`).
- **Signals step:** `data` and `data_description` for `low_pressure_fault` and `boiler_lockout`.
  - `low_pressure_fault`: "Optional: the boiler's own low-water-pressure fault, e.g. the gateway's \"Low water pressure\" on its boiler device. While it reads on for 5 minutes, control switches heating off — without handing the boiler back — and on again when it clears, as the boiler itself does. Unknown or unavailable counts as no fault. Pick only the boiler's own report: a wrong pick stops heating while the boiler could heat."
  - `boiler_lockout`: the same, adding "a fault your boiler's manual says stops the boiler (a lockout); not a general fault or service indication, which would stop heating needlessly."
- **Monitor step:** `add_water_below`: "Optional: below this pressure you are told to add water, in bar — take it from your boiler's manual (its minimum operating pressure). Empty by default: no notification. It only informs; heating stops only while the boiler itself reports a fault that stops it. Too low tells you late; too high tells you while the pressure is fine."
  - Remove `pressure_low_warning` and `pressure_low_alarm` from `data` and `data_description`, in both the config and the options flow (`en.json:177-178, 193-194, 437-438, 453-454`).
  - `pressure_high_alarm`: replace "below a typical 3 bar safety valve" with "below your safety valve's rating, read on the valve (often 3 bar in Europe, about 2.1 bar / 30 psi in North America)".
- **`control_alarms` step:** keep `write_ignored` only. Its description: "Offered only where a hand-back returns the boiler to a thermostat or to its own control. Hand back: after the boiler ignores a write, control steps aside until you switch it off and on, and the thermostat or the boiler's own control heats meanwhile. Information (default): the plugin keeps trying and tells you. If the boiler ignores \"heating off\" from the start, control always stops and hands the boiler back, whatever you choose here."
  - The step description: "Other alarms only inform; the plugin stops heating only while the boiler itself reports a fault that stops it."
  - Remove the other keys (`en.json:586-611`).
- **`ch_confirmed_entity`** (`en.json:477`): "…the gateway's \"Central heating 1\" on its boiler device that reads On/Off — what the gateway sends. Not the one that reads Running/Not running: that is the boiler's own status, which goes off during hot water and would look like another controller."
- **Entity texts:**
  - `control_state`: state and reason `boiler_fault` — "Boiler fault: heating off".
  - The alarm entities' `state_attributes.reason.state` gain `held`, `hot_water_unknown` and `unknown_input`.
  - `switch.control`: attribute `blocked_by`.
- **`issues`:**
  - `add_water` — title "Heating water pressure is low — add water". Description: "The pressure is {value} bar, below the {threshold} bar you set from the boiler's manual. Add water with the filling tap as the manual describes, watching the boiler's gauge, then close the tap. If it keeps falling, look for a leak. Heating carries on; the boiler stops by itself if the pressure falls too far."
  - `pressure_high` — "The pressure is {value} bar, above your alarm limit of {limit} bar. Your limit must be below the safety valve's rating, printed on the valve. Check that the filling tap is closed. To lower the pressure, switch the heating off and let the system cool, then let a little water out at a radiator's bleed valve until the gauge shows the cold pressure from the manual. If the pressure jumps each time the heating runs, have the expansion vessel checked; on a combi boiler, if it creeps up on its own, have the heat exchanger checked. Heating carries on."
  - `flue_gas_high` — "The flue gas is {value} °C, above your alarm limit of {limit} °C. Book a boiler service: heat exchanger, flue and condensate pipe, water circulation. The boiler's own flue protection may turn it down or lock it out. Heating carries on."
  - `pressure_falling` — "Your pressure keeps falling — there is a risk of a leak. Over the last days it fell by {change} bar, with the water temperature taken into account. Look for drips at radiators, valves and the boiler, and at the safety valve's outlet; if you find none, have the system checked."
  - `boiler_fault` — "The boiler reports a fault that stops it ({entity}). The plugin keeps heating off while it does and switches it on again when the boiler clears it. Read the fault on the boiler and follow its manual."
  - `control_latched` (V7's issue) — gains the placeholder `{alarm}` and a sentence for each cause (another controller; the boiler ignoring a write; the boiler ignoring "heating off" from the start of the session, answer O: "the plugin could not switch heating off, so it handed the boiler back; check the heating switch and the boiler's settings"), saying what heats now (by the declared hand-back effect) and that switching control off and on takes it back.
  - `hand_back_boiler_link_lost`, `hand_back_control_error` — each says why control stepped aside, what heats now (by the declared hand-back effect), and how control resumes: by itself for the lost link, by switching control off and on after an internal error. The monitor failure uses V6's `monitor_failed` / `monitor_recovered` texts.
  - `reactions_removed` — "These alarm reactions are no longer offered and now only inform: {alarms}."

**Missing data.**
- **Pressure not mapped:** no pressure alarms, notifications or trend; the features name "pressure".
- **Pressure unknown or unavailable:** held for 1 h, then `unknown`. It never opens a notification and never affects heating.
- **0.0 bar:** as rule 11.
- **The OTGW firmware over MQTT with monitor only, or with another write path:** 0.0 bar counts as a reading, since no `otgw_mqtt` read-back names the gateway's device; after a gateway reset the add-water notification may open wrongly, which only informs.
- **`add_water_below` empty:** add-water inactive, named.
- **Fault signals not mapped:** the fault stop is inactive, named "boiler fault signal", and heating is decided as usual. Unknown or unavailable counts as no fault.
- **One entity for both fault signals:** the later one is dropped and named, and control is blocked with `entity_for_two_signals` (rule 3).
- **Flame not mapped** (a relay home, X8): starts, ignition, hysteresis drift and the pressure trend are inactive, named "flame".
- **Flow not mapped:** the pressure trend and hysteresis drift are inactive; unstable ignition is degraded.
- **CH setpoint not mapped:** unstable ignition is degraded.
- **Zone data missing:** hysteresis drift is inactive, named "zone data".
- **Hot water unknown on a boiler with hot water:** low flow is not judged.
- **Weather entity missing:** the outdoor check is inactive (as today).
- **Hand-back effect undeclared, or the relay path:** `write_ignored` is not offered.

**Do not.**
- Do not stop heating, cap the water or hand back for a pressure or flue-gas reading, a trend or a count. Option B of the decision-7 note (hand-backs on banded alarms behind a thermostat) was not adopted.
- Do not add a 10-minute hot-water filter for flue gas (the verification found it unsupported).
- Do not keep the fault stop through an unknown signal, and never infer a fault from a pressure reading.
- Do not treat "Fault indication" or "Service required" as stopping unless the user picked it as the lockout signal.
- Do not build notifications on `banded_alarm`'s indefinite hold.
- Do not change the high-pressure or flue-gas defaults.
- Do not write "a leak is likely".
- Do not hide a 0.0 bar from an MQTT sensor that is not the OTGW firmware's.
- Do not map a gateway with an OpenTherm thermostat, or a relay, to `OWN_CONTROL_RESUMES`, and do not offer `write_ignored`'s hand-back on the relay path.
- Do not raise a second repair issue for a cause V6, V7 or X1 already report.
- Do not add a platform file.

**Open for the user.** None.

### Y2 — Cycles, gas and days

**Goal and done-when.**
- Day summaries and gas figures rest on what was measured: burns across midnight are complete, hot water is inferred only on consistent evidence, and meter bounces and other gas users do not count as heating.
- Home Assistant's downtime is unknown time.
- Days under control are tagged, and unrelated option changes keep the stored days.
- The forecast statistics, the importer and the analysis race are fixed.

Done when:
- every scenario of P-28, P-53, P-56, P-80, P-83, P-84, P-86, P-87, P-88, P-93, P-95, P-96, P-97, P-111 and S-31 is covered, together with A11, A12 and A13 of Open after R6 #6;
- T-40 passes, and each mechanism has its negative test;
- Y2 is ✅ and committed.

**Read first.**
- **Plan:** the Y2 row; `docs/plan-0.2.1.md` "Open after R6" #6 (A11, A12, A13).
- **Review:** the rows above (§3); S-31 (§4); T-40 (§6).
- **Research:** `research/2026-09-27-fresh-session-test.md` § Y2.
- **Code:**
  - `core/cycles.py` (all), `core/daily.py` (all), `core/monitor.py:134-182`, `core/metrics.py:160-190`;
  - `core/history.py:72-139`, `core/series.py:102-117`;
  - `coordinator.py:237-300, 374-490, 667-713, 759-783, 855-871`;
  - `core/forecast.py:111-211`, `forecasts.py:99-174`;
  - `tools/import_history.py:170-260`.

**Order of work.**
1. **`tests/core/test_cycles.py`:**
   - `test_conflicting_inferred_evidence_is_unknown` (P-28) — Given no DHW or CH signal, no zone demand, flow within the setpoint; Then `UNKNOWN`, not DHW.
   - `test_single_inferred_evidence_is_unchanged` (negative).
2. **`tests/core/test_daily.py`:**
   - `test_a_burn_across_midnight_is_complete_in_its_start_day` (P-83) — Given 23:50–00:20; Then the start day has 1 complete burn of 30 min and 10 min of burn time, and the next day has 20 min of burn time and no start.
   - `test_a_day_waits_for_a_burn_still_running` — Given a burn running at 00:03; Then the day is not summarised until the flame goes off, or 6 h have passed.
   - `test_days_under_control_carry_controlled_s` (P-96).
   - `test_a_stuck_outdoor_sensor_gives_way_to_the_weather_in_a_day` (P-86); negative: no weather gives outdoor unknown for the day.
3. **`tests/core/test_monitor.py`:**
   - `test_metered_gas_is_split_in_one_pass` (P-84) — the result equals today's; a counter on segment visits is linear in readings + burns.
   - `test_a_meter_bounce_counts_once` (P-97) — readings 100.0, 99.9, 100.0, 100.2 give a rise of 0.2.
   - `test_gas_without_burner_is_reported_apart` (S-31) — a rise over an interval with the flame known off throughout goes to `other_gas`, not to heating. Negative: flame unknown over it keeps it as today.
4. **`tests/core/test_forecast.py`:** T-40 `test_forecast_errors_skip_hours_not_yet_observed`.
5. **`tests/core/test_series.py` or `test_history.py`:** `test_downtime_is_unknown` (P-95, A11) — Given a downtime interval stored as 10:00–16:00, the flame last on; Then burn time and heat in it are 0, and `observed_s` excludes it.
6. **`tests/tools/test_import_history.py`:**
   - `test_23_and_25_hour_days_are_normalised` (P-93);
   - `test_a_zero_or_reversed_window_is_refused` (P-111);
   - `test_each_day_is_summarised_from_its_own_window` (A13): a spy on `summarize_day` sees only that day's samples, plus the margin.
7. **Integration tests:**
   - `test_analysis_during_backfill_keeps_no_partial_days` (P-53);
   - `test_pruned_forecast_partitions_are_not_recreated` (P-56);
   - `test_an_unrelated_option_keeps_the_stored_days` (P-87) — a change to `water_volume` or to the pressure signal keeps them; a change to `short_burn_min` drops them;
   - `test_burns_are_classified_per_analysis` (P-80) — no `classify_burns` call in `_compute`.
8. Code, texts, both commands. ✅ and commit.

**Rules and values.**
1. **P-28 (`core/cycles.py:136-164`).** When the inferred evidence points both ways (at least one observation above 0.5 and one below), and the combined probability lies within 0.35–0.65 (provisional, K4), the burn is `UNKNOWN`. It is counted apart, as today (P47). A single piece of evidence is unchanged.
2. **P-83.**
   - Burns are found over [day start − 12 h, day end + 12 h] (provisional, K4). This is limited by the history.
   - A burn belongs to the day of its start for `starts`, `complete_burns` and `short_burns`. Time amounts (burn, condensing, heat) are split at midnight.
   - A complete day is summarised only once no burn that started in it is still running, or 6 h after its end, whichever comes first (provisional, K4).
3. **P-84.** `_metered_hot_water` (`core/monitor.py:161-182`) walks the readings and the time-sorted burns with two cursors.
4. **P-97.** One function, `meter_rise(high, value) -> (rise, high)`, in `core/metrics.py`:
   - a rise counts only above the high-water mark;
   - a value below 10 % of the mark is a reset (`METER_RESET_FRACTION`) and counts from 0.
   
   Both `meter_consumption` (`:169-190`) and the split use it.
5. **S-31.**
   - A meter rise between two readings whose interval has the flame known off throughout is "other gas". It is left out of heating gas and shown apart (`MonitorSummary.other_gas`, `DaySummary.other_gas`, attribute `other_gas` on `gas_per_degree_day`). It is never silently subtracted.
   - A rise over an interval with burner time is split as today. Other users' gas during burns counts as heating, and the text says so.
6. **P-86.** Each day checks the outdoor sensor with `check_outdoor` over that day. If it is `STUCK`, the day uses the weather entity. Without a weather entity, the day's outdoor is unknown.
7. **P-87.** `summary_settings` (`coordinator.py:855-871`) keeps only what changes a summary:
   - the monitor options it lists now;
   - the parameters `boiler_min_power`, `boiler_max_power`, `gas_at_min_power`, `gas_at_max_power`, `max_ch_setpoint`, `heating_threshold`;
   - the entities of flame, flow, return, modulation, CH setpoint, hot water, CH active, gas meter and outdoor;
   - the weather entity and the zones.
   
   The load model's parameters leave the key: Y3's P-91 recomputes the load from each day's distribution.
8. **P-88.** `forecast_errors(..., observed_until)` skips a point whose hour ends after `observed_until`. The analysis passes its `now`.
9. **P-93, P-111, A13 (`tools/import_history.py`).**
   - The importer summarises with `summarize_day` and uses `fit_points`, instead of `daily_points` (`:251`).
   - `end <= start` is refused with a message and exit code 2.
   - Each day is summarised on `History.copy_window(day start − 12 h, day end + 12 h)`.
10. **P-95 (A11).**
    - The coordinator keeps its own record of downtime in the entry's store: `down` is a list of [from, to] intervals kept for 8 days.
      - At a clean stop, `from` = the stop time, written in `async_stop` (`coordinator.py:237-247`).
      - After a crash, `from` = the last `alive_at`. The store writes `alive_at` at most every 10 min (provisional, K4), along with its other saves.
      - `to` = the start time.
    - At start and after the backfill (`:452-490`), every series gets a `None` sample at each `from` inside the history. The data after `to` makes the series known again.
    - Home Assistant's own run table (`recorder_runs`) is not a public interface: 2026.9.3's `RecorderRunsManager` offers no listing. It is not used.
    - Days summarised from the recorder before the plugin's first run cannot know about downtime. This goes to "Open after 0.2.2".
11. **P-96 (A12).**
    - `DaySummary.controlled_s` = the day's time with the control state in `heating`, `idle`, `frost`, `fallback` or `boiler_fault` (provisional, K4). It is read from the history of the plugin's own `control_state` sensor, which the recorder keeps, so the backfill has it too.
    - Stored days without the field read `None` and count as uncontrolled; no controlled day was ever released.
    - The verdict leaves out days with `controlled_s ≥ 1 h` (provisional, K4), and says how many it left out.
12. **P-53.** Read `_history_back` together with the copy, before the executor job (`coordinator.py:767` vs `:782`).
13. **P-56.** A partition pruned in `_async_prune` (`forecasts.py:161-165`) is discarded from `_dirty`, so `async_flush` does not recreate it.
14. **P-80.** `classify_burns` over 24 h runs in the analysis, every `SUMMARY_SECONDS` (300 s). `frequent_starts` and `unstable_ignition` use the analysis' burns, so they lag by up to 300 s, which is acceptable for information.
15. **Values for S-37's list:** 0.35–0.65, 12 h, 6 h, 10 min, 1 h.

**Code to change.** `core/cycles.py:35-45, 136-164`; `core/daily.py:30-104, 114-148, 162-199`; `core/monitor.py:134-182, 185-252`; `core/metrics.py:169-190`; `core/history.py:72-85`; `core/forecast.py:181-211`; `coordinator.py` (the lines above, plus `_record` for the control state); `forecasts.py:161-174`; `tools/import_history.py:192-260`.

**Texts.**
- `gas_meter`'s `data_description`: "…Gas the meter counts while the burner is off (a cooker, another appliance) is shown apart; gas they use while the burner runs cannot be told apart and counts as heating."
- The verdict attributes gain `days_left_out` (translated name).
- `other_gas` gets a translated attribute name.

**Missing data.**
- **No gas meter:** gas from modulation, as today; `other_gas` is absent.
- **Flame unknown over a meter interval:** that rise is split as today.
- **No weather and a stuck sensor:** that day's degree-days are unknown.
- **No stored `down` record** (first run): nothing is marked.
- **No `control_state` history** (control never configured): `controlled_s` = 0.
- **Recorder not loaded:** as today, live data only.

**Do not.**
- Do not subtract other gas silently.
- Do not read the recorder in the event loop.
- Do not use private recorder tables.
- Do not drop stored days on unrelated options.
- Do not reclassify 24 h of burns on the fast path.

**Open for the user.** None.

### Y3 — Building model and verdict

**Goal and done-when.** The verdict and the building model claim only what the data supports:
- the heating threshold has its own uncertainty;
- the heat loss is fitted alone only on a trustworthy threshold;
- the load criterion needs a real model;
- "not worth it" needs enough judged criteria;
- the reasons say what 0.2.2's control changes, and "worth enabling" comes only from a problem it changes (answer K);
- measured values are shown and can be reset;
- starting control without a verdict is said.

Done when:
- every scenario of P-31, P-32, P-90, P-91, P-92, P-94, S-17, S-22, S-32, S-43 and review questions 11 and 12 is covered;
- the user's answers J and K of 2026-09-27 are built as rules 7, 8 and 10 say;
- T-41, T-42 and T-43 pass;
- Y3 is ✅ and committed.

**Read first.**
- **Plan:** the Y3 row; decision 13 (anti-cycling in 0.3 is "to be decided against principle 12"); the user's answers of 2026-09-27: J (`button.py` approved) and K (the verdict; the monitoring period counted from the entry's creation).
- **Review:** the rows above (§3 and §4), T-41–T-43 (§6), Appendix E questions 11 and 12.
- **Research:** `research/2026-09-27-fresh-session-test.md` § Y3.
- **Code:** `core/building.py` (all), `core/parameters.py:18-29, 88-196`, `core/verdict.py` (all), `core/daily.py:30-49, 139-142, 162-199`, `core/analysis.py:85-104`, `core/installation.py:110-160`, `config.py:156-158`, `sensor.py:180-201, 212-315`, `switch.py:57-69`, X4's `button.py`.

**Order of work.**
1. **`tests/core/test_building.py`:**
   - T-41 `test_a_threshold_from_a_narrow_cold_band_is_not_trusted`;
   - T-42 `test_loss_alone_through_a_default_threshold_is_not_trusted`;
   - `test_a_wide_spread_fits_a_trusted_threshold` (positive control);
   - `test_loss_alone_with_an_entered_threshold_is_fitted`.
2. **`tests/core/test_verdict.py`:**
   - T-43 `test_the_verdict_load_criterion_needs_a_confident_model`;
   - `test_not_worth_it_needs_three_of_four_criteria_judged` (S-32), with a variant for a non-condensing boiler: 2 of 3;
   - `test_each_problem_reason_says_whether_this_release_changes_it` (S-22);
   - `test_worth_it_only_from_a_problem_control_changes` (answer K) — Given only frequent starts and short burns as problems; Then not `worth_it`, and both stay in the reasons with `changed_by_control` false. Given low condensing on a flow-setpoint path; Then `worth_it`. Given low condensing on the relay path; Then not `worth_it`.
   - `test_the_load_share_uses_the_current_model_on_stored_days` (P-91).
3. **Integration tests:**
   - `test_the_measured_threshold_is_shown` (P-90);
   - `test_reset_buttons_forget_measured_values_and_refit_from_new_days_only` — each button resets only its own estimate; no option saved, no reload, no hand-back;
   - `test_installation_warnings_raise_an_issue` (P-94);
   - `test_the_switch_says_control_starts_without_a_verdict` (S-43);
   - `test_an_entered_design_load_always_wins` (P-92);
   - `test_control_uses_no_building_model` (question 11): a core-import test showing that `controller`, `loop`, `limits` and `demand` do not import `building`.
4. Code, texts, commands. ✅ and commit.

**Rules and values.**
1. **P-31.** The threshold is fitted only when the outdoor spread is ≥ 8 K (provisional, K4; `MIN_OUTDOOR_SPREAD_K` is 4.0 today).
   - Its confidence = min(0.95, coverage × R² × min(1, spread / 12 K)) (provisional, K4).
   - If its standard error (delta method, from the fit) is > 2 K (provisional, K4), its confidence is capped at 0.3 (`CLAMPED_CONFIDENCE`): shown, never used.
2. **P-32.** H is fitted alone only when the threshold passed in is `ENTERED`, or has confidence ≥ 0.5 (`MIN_CONFIDENCE`). `analyse()` passes the `Estimate`, not the value (`core/analysis.py:85-89`).
3. **S-17.** The verdict's load criterion counts only when both H and the threshold are `ENTERED`, or measured or learned with confidence ≥ 0.5. Otherwise it is `LOAD_UNKNOWN` (missing), with the reason "estimate only".
4. **P-91.** Each day stores `outdoor_s`: seconds per whole °C from −30 to +30 °C, with the ends clamped. The load share is recomputed from it with the current model and minimum power. Old stored days without it are left out of the load criterion.
5. **P-92 (question 12).** An entered design load always wins. The texts and `core/building.py:1-8` say "data never replace it; they show a mismatch".
6. **S-32.** "Not worth it" needs at least 3 of the 4 criteria judged: starts, burn length, condensing, load (a non-condensing boiler: 2 of 3) (provisional, K4). "Judged" means the input was known. Otherwise the verdict is "not enough data", with reason `criteria_judged`.
7. **S-22.** Each `problem` reason carries `changed_by_control`.
   - Low condensing is true for control that sets the water temperature (flow setpoint), and false for a relay (X8).
   - Frequent starts, short burns and load below minimum power are false. Their text: "not changed by control in 0.2.2; anti-cycling is planned for 0.3, still to be decided (PLAN.md)".
   - **Decided (the user, 2026-09-27, answer K):** "worth it" comes only from a problem with `changed_by_control` true. `assess` (`core/verdict.py:202-203`) gives `worth_it` only then. Otherwise, with enough criteria judged (rule 6), it gives `not_worth_it`, and the problems found stay in the reasons, shown as "not changed yet".
   - On the relay path no problem is changed by 0.2.2's control, so the verdict is never "worth it" there; the switch's text (rule 10) still says control may start.
8. **P-90.**
   - A sensor `heating_threshold`, hidden by default, like `loss_coefficient` (`sensor.py:180-201`): source, confidence, entered, measured, mismatch.
   - Reset uses the mechanism X4 chose for the comfort correction (P-38): a button in `button.py`, which the user approved on 2026-09-27 (answer J). Y3 adds two buttons to that file, `reset_heating_threshold` and `reset_loss_coefficient` (entity category config).
     - A press removes that `MEASURED` estimate and stores its `fit_since = now`; only later days are fitted.
     - It changes no option, so there is no reload and no hand-back.
9. **P-94.** Installation warnings (`EMPTY_CIRCUIT`, `UNDERFLOOR_WITHOUT_MAX_FLOW`, `core/installation.py:147-155`) raise a warning repair issue each, `installation_<code>_<entry>`.
10. **S-43.** The switch gets the attribute `verdict` (translated states). The control step's description says control may start once the monitoring days have passed, counted from the entry's creation (answer K), even without a verdict. Without a flame signal the verdict stays "not enough data" with reason `no_burner_signal`.
11. **Question 11.** Bounded learning covers what control uses (the comfort correction). The building model feeds the monitor only, and is visible and resettable.
12. **Values for S-37's list:** 8 K, 12 K, 2 K, 3 of 4, 2 of 3, −30…+30 °C.

**Code to change.** `core/building.py:127-186`; `core/verdict.py:48-62, 101-203`; `core/daily.py` (`outdoor_s`, `verdict_over_days`); `core/analysis.py:85-104`; `coordinator.py:784-797` (`fit_since`, one per estimate); `sensor.py` (the new description); `switch.py:57-69`; `button.py` (X4's file: the two reset buttons); the issue creation in `coordinator.py`.

**Texts.**
- The `heating_threshold` sensor's name and attributes.
- Verdict reason codes `criteria_judged` and `no_burner_signal`; attribute `changed_by_control`, with its "not changed yet" text.
- The switch attribute `verdict`.
- The buttons' names: `reset_heating_threshold` "Reset measured heating threshold", `reset_loss_coefficient` "Reset measured heat loss".
- Issues `installation_empty_circuit` and `installation_underfloor_without_max_flow`.
- The building texts for P-92.

**Missing data.**
- **No flame:** the verdict stays "not enough data", with its reason.
- **No return:** condensing is not judged.
- **No outdoor or weather:** no load criterion and no fit.
- **No minimum power:** no load criterion.
- **Fewer than 7 usable days:** no fit (`MIN_FIT_DAYS`).
- **Nothing entered:** defaults are shown with their source and never decide the verdict.

**Do not.**
- Do not let a measured value override an entered one.
- Do not add another platform file: the reset buttons go into X4's `button.py`, which the user approved (answer J).
- Do not let "worth it" rest on a problem 0.2.2's control does not change.
- Do not name a release as a promise.
- Do not let control read the building model.

**Open for the user.** None. The verdict rule is the user's answer K of 2026-09-27; the reset buttons use answer J.

### Y4 — The Home Assistant layer and the missing-data rule

**Goal and done-when.** The integration follows Home Assistant's rules:
- forecasts load off the event loop, and the forecast service is guarded;
- diagnostics redact everything, and work in setup error;
- coded attributes have translated text;
- units, names, timestamps and entity creation are right;
- dead code, texts and docstrings are cleaned up;
- every feature whose input is missing is shown as inactive, naming the missing input.

Done when:
- every scenario of P-23, P-30, P-39, P-55, P-62, P-66, P-72–P-78, P-100–P-104 and P-116 is covered, with review question 20;
- T-36 and T-50 pass;
- one test per feature for the missing-data display passes;
- Y4 is ✅ and committed.

**Read first.**
- **Plan:** the Y4 row; "Missing data" (Decisions of 2026-09-26/27).
- **Review:** the rows above; T-36 and T-50; Appendix E question 20.
- **Research:** `research/2026-09-27-fresh-session-test.md` § Y4; `research/2026-09-27-plan-0.2.2-checks.md`, the low item on the missing-data display.
- **Code:** `forecasts.py:85-174`, `core/forecast.py:111-170`, `diagnostics.py` (all), `sensor.py` (all), `switch.py:79-89`, `binary_sensor.py:95-177`, `__init__.py:22-87`, `core/signal_check.py:58-129`, `vtherm_link.py:94-96`, `translations/en.json:294-313, 537, 551, 862-874, 944, 1130`.
- **Home Assistant:** `homeassistant.const.UnitOfRatio` (`const.py:800-805`); `homeassistant.helpers.translation.async_get_translations`.

**Order of work.**
1. **Integration tests:**
   - T-36 `test_forecasts_load_off_the_event_loop`;
   - `test_get_forecasts_is_skipped_while_the_weather_is_unavailable` and `test_get_forecasts_times_out_after_30_s` (P-55);
   - T-50 `test_diagnostics_redact_an_entity_that_is_away`;
   - `test_diagnostics_work_for_an_entry_in_setup_error` (question 20).
2. **Translation and text tests:**
   - `tests/test_translations.py::test_every_key_is_used` (P-76, the reverse parity);
   - `test_coded_lists_have_translated_text` (P-39): every code in reasons, blockers, `latched_by` and the verdict reasons has a text in en and pl;
   - `test_critical_zone_states_are_translated` (P-73);
   - `test_blocked_switch_error_counts_the_others` (P-74);
   - `test_gas_per_degree_day_has_no_unit_until_the_meter_has_one` (P-75);
   - `test_timestamps_are_iso` (P-78);
   - `test_change_report_and_forecast_snapshots_need_their_data` (P-100);
   - `test_percent_sensors_use_unit_of_ratio` (P-102);
   - `test_entity_names_do_not_repeat_the_device` (P-104).
3. **`test_every_feature_names_its_missing_input`:** parametrised over the feature table below. For each feature, remove each required input; Then its status is `inactive`, its missing list names that input with a text in en and pl, and its entities are not created (or are unavailable where they already exist). One more case: a signal dropped because its entity is mapped to an earlier signal (X5) is named with the code `entity_for_two_signals` and the signal that kept the entity.
4. Code, texts, commands. ✅ and commit.

**Rules and values.**
1. **P-23.**
   - `ForecastRecorder.async_load` parses the partitions in the executor (`hass.async_add_executor_job`), where `ForecastStore.load` runs today (`forecasts.py:107`).
   - RAM keeps only the current week's partition, plus a snapshot count for the others. The count is what 0.2.2 uses (`coordinator.py:649`).
2. **P-55.**
   - `async_take` (`forecasts.py:114-148`) returns 0 without calling while the weather entity is missing, `unavailable` or `unknown`.
   - Each call is wrapped in `asyncio.timeout(30)` (provisional, K4). A timeout is logged at debug level and skipped.
3. **P-30.** `_named_entities` (`diagnostics.py:165-173`) accepts any `Mapping`.
4. **Question 20.** Without `runtime_data`, diagnostics return:
   - the redacted options;
   - `{"state": "setup_error"}`;
   - the control state read from the entry's store (as `repairs.py:63-66` reads it), redacted.
5. **P-39.** Coded attributes stay codes, for automations. Each list attribute (`reasons`, `blockers`, `latched_by`, the verdict's `reasons`) gets a sibling `<name>_text`.
   - The text is built from the integration's own translations in `hass.config.language`, loaded once at setup with `async_get_translations(hass, language, "entity", {DOMAIN})` and joined with ", " (provisional, K4).
   - The codes live under each entity's `state_attributes.<name>.state`.
   - The `_text` attributes are unrecorded.
6. **P-73.** The `critical_zone` status states are translated (`en.json:862-874`). The entity name uses the circuit's label from the options.
7. **P-74.** Switch errors (`switch.py:84-88`) give the first blocker's key, plus `{count}` more, instead of raw codes.
8. **P-75.** `gas_per_degree_day` gives no value and no unit until the meter's unit is known; no English "gas".
9. **P-76.** Unused keys go, the frequent-starts reaction (`en.json:589, 603`) among them.
   - The reverse test builds the set of used keys from the flow schemas (built at both levels), the entity descriptions, the `translation_key=` literals in the package, and the selectors.
10. **P-66.** `ceiling_band`'s text states the correction's real bound, as X4 leaves it; "3 K" today.
11. **P-103.** The freshness step gets a `data_description` per signal.
12. **P-104.** "Boiler signals" becomes "Signals", and "Boiler control (experimental)" becomes "Control (experimental)" (`en.json:944, 1130`).
13. **P-78.** Every timestamp attribute is ISO 8601 (`sensor.py:110, 448`).
14. **P-100.** `change_report` and `forecast_snapshots` get `needs=`: the report needs a heating threshold and degree-days; snapshots need a weather entity.
15. **P-72.** `value` (`AlarmSensor`) and `excess` (`HotWaterSensor`) are dropped from the attributes (provisional, K4). Diagnostics keep them.
16. **P-101.** `type SmartBoilerConfigEntry = ConfigEntry[SmartBoilerCoordinator]` goes in `coordinator.py`, and every platform uses it. `__init__.py` keeps its imports inside functions.
17. **P-102.** `UnitOfRatio.PERCENTAGE` replaces `PERCENTAGE` (`sensor.py:17, 237-297, 430`).
18. **P-62.** Remove the dead code the row lists: `vtherm_link.py:94-96`, `transport/entities.py:46-52`, `config_flow.py:893-896`, `core/readings.py:42-54`, `feature_manager.py:226-228`, `control.py:389-399`, together with the tests that kept them alive.
19. **P-77, P-116.** Class docstrings go above the attributes (`binary_sensor.py:95-98, 143-146, 174-177`). Update `coordinator.py:7-9` and `core/demand.py:9-11`.
20. **The missing-data display.**
    - A diagnostic sensor `features`: its state is the number of inactive features. Its attributes are one status per feature (`available`, `degraded` or `inactive`, translated), plus `<feature>_missing` (codes) and `<feature>_missing_text` (translated names).
    - It replaces the `features` attribute of `signal_problems` (`sensor.py:122-126`).
    - `FeatureState.missing` becomes a tuple of input codes: signals, entered values, "zone data", "weather entity" and "control".
    - A signal dropped because an earlier signal in `SIGNAL_FIELDS` order uses its entity (X5) is named with the code `entity_for_two_signals`, and its text names the signal that kept the entity.
21. **The feature table** (inputs as each step defines them):
    - `cycles` (flame);
    - `condensing` (flame, return);
    - `dhw_detection`;
    - `gas`;
    - `degree_days`;
    - `hot_water` (flow);
    - `emitter_factor` (flow);
    - `flue_gas_warning` (flue gas, return, condensing boiler);
    - `pressure_warning` (pressure);
    - `add_water` (pressure, threshold);
    - `pressure_trend` (pressure, flame, flow);
    - `hysteresis_drift` (flow, flame, zone data);
    - `unstable_ignition` (flame; degraded without flow or CH setpoint);
    - `low_flow` (pump or CH active, valve openings; not with a bypass);
    - `outdoor_check` (outdoor, weather);
    - `boiler_fault_stop` (a fault signal, control);
    - `verdict` (flame);
    - from phase X: `comfort_correction` and `frost_protection` (X4), `activation_delay` (X4), `circuit_overshoot_alarm` (X4, flow), `lowest_water_suggestion` and `wall_thermostat_fallback` (X6), `relay_proof` (X8).
22. **Values for S-37's list:** 30 s (the forecast call's timeout).

**Code to change.** `forecasts.py:99-148, 161-174`; `core/forecast.py:156-169`; `diagnostics.py:85-173`; `sensor.py` (the lines above, and the new description); `switch.py:57-89`; `binary_sensor.py:95-177`; `coordinator.py` (the alias); `core/signal_check.py:71-129`; the files P-62 names; `translations/en.json` and `pl.json`.

**Texts.** A `state_attributes.*.state` entry for every code the lists carry; the `features` sensor's name, attributes and states, `entity_for_two_signals` included; the new names (P-104); `freshness` descriptions (P-103); `ceiling_band` (P-66); switch errors with `{count}` (P-74); removal of unused keys.

**Missing data.**
- **Weather missing or unavailable:** no forecast call, `forecast_snapshots` not created or unknown.
- **Language without a translation:** the English text.
- **Diagnostics without runtime data:** as rule 4.
- **Each feature:** as the table.
- **A signal whose entity an earlier signal uses:** as rule 20.

**Do not.**
- Do not replace codes in attributes automations use.
- Do not parse anything large in the event loop.
- Do not call `get_forecasts` on an unavailable entity.
- Do not leave a key the code does not use.

**Open for the user.** None.

### Z1 — The remaining tests

**Goal and done-when.** The review's missing tests not taken by a step are written; the flows reach 100 %; weak tests are made exact; the safety-critical functions get table-driven precedence tests before any split. Done when:
- T-22 and T-51 pass;
- P-34, P-115, P-117, P-118 and P-120–P-128 are closed, with T11 of Open after R6 #6;
- the flows are at 100 % with branches;
- Z1 is ✅ and committed.

**Read first.**
- **Plan:** the Z1 row; `PLAN.md` "Test environment" (layer 1 "no Home Assistant").
- **Review:** the rows above (§3); T-22 and T-51 (§6); Appendix D.
- **Research:** `research/2026-09-27-fresh-session-test.md` § Z1.
- **Code and tests:**
  - `tests/integration/test_no_writes.py:20-40`, `tests/integration/test_control.py:180-195, 824-842`;
  - `tests/integration/test_setup.py:139-154`, `tests/integration/test_feature_manager.py:101-111`;
  - `tests/test_release.py:170-250`, `tests/core/test_guards.py:344-357`, `tests/core/test_loop.py:89-98`;
  - `tests/integration/test_acceptance.py:243`, `tests/sim/test_control_loop.py:192-196`;
  - `control_config.py:34-51`, `core/history.py:134-139`, `__init__.py:90-107`, `tests/conftest.py`.
- `.venv/.../pytest_homeassistant_custom_component-*.dist-info/entry_points.txt`: the plugin is named `homeassistant`.

**Order of work.**
1. **T-22** `test_mqtt_hand_back_is_published_before_mqtt_stops` — `mqtt_mock_entry`, control through `otgw_mqtt`, read-back from MQTT entities; When `hass.async_stop()`; Then V5's safe hand-back (`ctrlsetpt` = the lowest water temperature, `chenable=1`, `ctrlsetpt=0`, in V5's order, one part after another at once, each published whatever the others do, with no wait for a read-back) reaches the MQTT client before it disconnects, and no owed hand-back is stored.
2. **T-51** `test_an_outer_cancellation_propagates_and_cancels_the_step`.
3. **Flows at 100 % (P-34):** the paths `coverage` reports as missing, including T-12, T-13, T-14 and T-37, if X5 or V4 did not take them.
4. **P-117:** a backfill test with zones (`History.prepend`, zone branch).
5. **P-118:** `test_no_writes.py` and the control rig spy on `hass.services.async_call` (patched wrapper), with the `switch` domain included; the test's own switch calls are tagged and left out.
6. **P-121:** exact assertions at the four places the row names.
7. **P-122:** `mqtt_mock` for the MQTT path, replacing the registered stub at `test_control.py:824-842`.
8. **P-123:** `hass.bus.async_listeners()` after unload equals before setup.
9. **P-124:** a parametrised migration test, from minor 1 → 2 → the current version (Y1's and X's changes), plus `test_a_newer_entry_is_refused` (version 2).
10. **P-125, T11:** one entry per test, in `test_feature_manager.py`.
11. **P-126:** core scenarios in `tests/core/test_demand.py`: VT safety, power shedding, an open window, "off" and not ready. The vendored-VT versions are X3's T-44 and T-45.
12. **P-127:** `tests/test_defaults.py` pins every default of the `SCOPE.md` §7 defaults table as Q1 leaves it. Each row cites its SCOPE row and reads the value from `CONTROL_DEFAULTS`, `CURVE_DEFAULTS`, the alarm bands and the monitor schema.
13. **P-128:** `test_release.py` refuses any whole-value `[%key:…%]`.
14. **P-115:** table-driven precedence tests for `control.py` `_async_step`, `control_config.py` `config_blockers`, `core/guards.py` `plan_write`, `core/controller.py` `decide` and `_heating_decision`, and `core/verdict.py` `assess`. Only then is a function split where `ruff check --select C901` with max complexity 12 (provisional, K4; run ad hoc, no configuration change) still flags it; the tables must stay green.
15. **P-120:** two runs, core first:
    - `scripts/env.sh python -m pytest -q -p no:homeassistant --cov --cov-branch tests/core`;
    - then `scripts/env.sh python -m pytest -q --cov --cov-branch --cov-append --ignore=tests/core`.
    
    CI (Z2) runs both. The CLAUDE.md commit rule names both runs, `ruff format --check` and `mypy`; that diff waits for consent. Until then, run both anyway.
16. ✅ and commit.

**Rules and values.** Tests only change to become stricter. A split changes no behaviour, and the tables prove it. Complexity 12 goes to S-37's list.

**Code to change.** The test files named above; `.github/workflows/tests.yml:52-55` (the two runs, which Z2 finishes). No production code changes, except the splits of step 14.

**Texts.** None.

**Missing data.** A test that needs `vendor/` keeps `requires_vendor` locally. In CI, decision 14 (Z2) makes it run.

**Do not.**
- Do not weaken or delete a test to reach coverage.
- Do not split before the precedence tables exist.
- Do not use the network in tests.

**Open for the user.** Consent to the CLAUDE.md commit-rule diff (P-120).

### Z2 — Tools and CI

**Goal and done-when.**
- CI is as strict as the local run: branches, per module, and the real VT and SmartPI.
- The actions are current.
- The deploy dry run reads no private file.
- Session summaries are ignored.
- The manifest carries the version this release publishes first.

Done when P-35, P-107, P-108, P-109, P-110 and P-119 are closed, and a pushed-equivalent local run of the workflow commands passes. There is no push: git is local only. Z2 is ✅ and committed.

**Read first.**
- **Plan:** the Z2 row; decision 14; decision 16; Q2's K5/K7 wording.
- **Review:** the rows above; Appendix E question 14.
- **Research:** `research/2026-09-27-fresh-session-test.md` § Z2.
- **Code:** `pyproject.toml:73-80`, `.github/workflows/tests.yml`, `.github/workflows/validate.yml`, `.gitignore`, `scripts/deploy_test.sh:50-60`, `tests/test_deploy.py`, `tests/test_release.py:27, 86-94`, `tests/integration/conftest.py:9-14`, `custom_components/.../manifest.json`.
- **`docs/plan-0.1.md` A5:** commits VT `78090166e88a` and SmartPI `51db763bb0db`; `vendor/custom_components/` links. The vendored SmartPI manifest says `0.0.0`, so check the tag's commit, not the manifest.

**Order of work.**
1. **Tests first:**
   - `test_the_dry_run_reads_no_private_file` (P-107) — Given a `devenv/local.env` that would fail if sourced (a temporary copy of the script's root in `.tmp/` with a poisoned file); Then the dry run succeeds and prints no host.
   - `test_session_summaries_are_ignored` (P-108): `git check-ignore session-summary-x.md`.
   - `test_manifest_version_is_this_release` with `RELEASE = "0.2.2b1"` (see Rules).
2. **`pyproject.toml`:** `[tool.coverage.run] branch = true`.
3. **Per-module check (P-35):** an inline step in `tests.yml`. After both runs: `coverage json -o .tmp/coverage.json`, then a short Python heredoc that fails if any module under `custom_components/vtherm_smart_boiler` is below 95 % with branches, or `config_flow.py` is below 100 %.
   - Locally the same heredoc runs through `scripts/env.sh`.
   - A separate `scripts/check_coverage.py` is outside every Layout section. It is created only if the user consents or the plan gains a 0.2.2 Layout section.
4. **P-110:** the current major versions of `actions/checkout` and `actions/setup-python`, checked over the network at this step (release pages read as pages). `validate.yml` keeps `hassfest@master` and `hacs/action@main`, as those projects document.
5. **P-109:** a job `latest-vtherm-api` that installs the pinned environment, then `pip install -U vtherm-api`, then runs all tests. A failure is a finding, not something to ignore.
6. **P-119, decision 14:** a CI step before the tests.
   - It downloads the VT 10.4.0 and SmartPI 0.4.0 tag archives from GitHub (`jmcollin78/versatile_thermostat`, `kipk/vtherm_smartpi`; tag names checked at this step).
   - It checks each tag's commit with `git ls-remote` against `78090166e88a` and `51db763bb0db`, and fails on a mismatch.
   - It unpacks them to `vendor/versatile_thermostat-10.4.0/` and `vendor/vtherm_smartpi-0.4.0/`, and creates the two `vendor/custom_components/` links as A5 did.
   - `tests.yml`'s header comment is updated: `vendor/` tests now run in CI.
   - Nothing is downloaded locally.
7. **P-107:** `deploy_test.sh` sources `local.env` only when not in a dry run; the dry run prints "the test HA named in devenv/local.env".
8. **P-108:** `.gitignore` gets `session-summary-*.md`.
9. **Manifest:** the version, and `RELEASE` in `test_release.py`.
10. ✅ and commit.

**Rules and values.**
- Floors: 95 % per module with branches, 100 % for `config_flow.py` (the plan). The total `fail_under` (`pyproject.toml:80`) stays 95.
- **Version (decision 16, S-53).** The manifest (`manifest.json`) and `RELEASE` (`tests/test_release.py:27`) become `0.2.2b1`: decision 16's provisional first version. K5 publishes it, or sets both to the version decision 16 picks at K4; K7 sets both to the release version (provisional 0.2.2). The plan's Z2 row says the same since its fix of 2026-09-27; the version never moves backwards.

**Code to change.** `pyproject.toml:73-80`; `.github/workflows/tests.yml:1-55`; `.github/workflows/validate.yml:18-19`; `.gitignore`; `scripts/deploy_test.sh:50-60`; `tests/test_deploy.py`; `tests/test_release.py:27, 86-94`; `manifest.json`.

**Texts.** None.

**Missing data.**
- **A tag archive unreachable in CI:** the job fails. It does not skip, because decision 14 wants the real-VT tests on every change.
- **`vendor/` missing locally:** the tests skip as today (`requires_vendor`), and the report says so.

**Do not.**
- Do not download VT or SmartPI locally, or copy them into the repository.
- Do not read `devenv/local.env` in a dry run.
- Do not add a remote or push.
- Do not create `scripts/check_coverage.py` without consent.

**Open for the user.** None; the version follows decision 16.

### Z3 — The simulator before J4

**Goal and done-when.** J4's main path and the new 0.2.2 behaviours can be run against the simulator, in-process and in the test HA. Done when:
- P-36, P-37, P-112, P-113, P-114, S-05's simulator part, S-15, T-07, T-20, T-21, T-23 and T-24, and Open after R6 #2 are covered;
- the relay, boiler and wall-thermostat models for X8 and X6 exist, each with in-process scenarios in `tests/integration/test_acceptance.py` or `tests/sim/`, the user's answers C, D, G, L and N of 2026-09-27 included;
- Z3 is ✅ and committed.

**Read first.**
- **Plan:** the Z3 row; X6; X8; decision 15; Q2's J4 additions; the user's answers of 2026-09-27: C and D (a relay switched while available, or found back in its power-cut state), G (the "separate relay contact" tick), L (the step aside sets the rest state once, then leaves the relay alone) and N (the fourth unreported restart within 24 h is another controller; with "last" or "I don't know", a change while available is a possible restart up to 3 times within 24 h).
- **Review:** the rows above; S-05 and S-15 (§4); T-07, T-20, T-21, T-23 and T-24 (§6).
- **Research:**
  - `research/2026-09-26-on-off-relays.md` §2, §4, "Corrections", Facts (Vaillant lockout and pump overrun, l. 314-315);
  - `research/2026-09-26-on-off-plugin-code.md`, the corrections on the 15-minute window (Vaillant's 20-minute anti-cycling, adjustable 2–60 min, l. 284-287);
  - `research/2026-09-26-wall-thermostat-device.md` "Tests", "Device side";
  - `research/2026-09-24-otgw-topologies-f3-f7.md` (the PIC's `CH=0` flag);
  - `research/2026-09-27-fresh-session-test.md` § Z3.
- **Code:**
  - `sim/custom_components/boiler_sim/__init__.py:100-253`;
  - `sim/custom_components/boiler_sim/plant.py:88-244`;
  - `sim/custom_components/boiler_sim/profiles.py:24` (`anti_cycle_s`, 180 s today);
  - `sim/custom_components/boiler_sim/simulation.py:35-198`;
  - `sim/simulator.py:160-262`;
  - `config_flow.py:1339-1362`;
  - `devenv/README.md:73-83`, `devenv/compose.yaml`, `scripts/deploy_test.sh:39-47`.

**Order of work.**
1. **Tests first,** each a Given/When/Then scenario:
   - T-23 `test_options_flow_configures_control_on_the_simulator` — the flow completes with gateway ID `sim`.
   - T-21 `test_a_dhw_draw_under_control_raises_no_outside_change` — closed loop, with a SmartPI zone learning.
   - T-24 `test_tpi_switch_zones_starts_per_hour_under_control` — at +8 °C and at −5 °C, against the boiler's own regulation in the same simulated house (rule 6).
   - T-07 `test_otgw_on_off_thermostat_heats_after_an_unclean_exit_while_off` — after X6, control is blocked for an on/off contact, so the test shows the blocker; and with `CH=0` forced, the flag that masks the contact.
   - T-20 `test_underfloor_flow_stays_within_the_circuit_maximum` (with X4's alarm).
   - `test_off_zones_close_their_valves` (S-05).
   - `test_only_persistent_writes_count_as_persistent` and `test_ch_writes_are_counted` (P-113).
   - `test_the_boiler_regulates_its_own_flow_with_emitter_inertia` and `test_daily_sums_are_kept` (P-112).
   - `test_gateway_read_back_confirms_then_drops_on_a_refused_id1` (Open after R6 #2).
   - `test_heating_switch_has_its_own_write_type` (EMS-ESP: CH does not renew the setpoint override).
   - Relay:
     - `test_relay_restart_is_resent`;
     - `test_relay_restart_without_unavailability_is_resent` (answer D) — the relay comes back in its declared power-cut state with no unavailable phase: the command is sent again; the third time within 24 h raises the information warning;
     - `test_relay_fourth_unreported_restart_in_a_day_steps_aside` (answer N) — a fourth such restart within 24 h: the plugin steps aside, the rest state set once, latched; with the model's start-up state "last" and the relay declared "I don't know", the same after four changes while available;
     - `test_relay_switched_while_available_is_rewritten_once_then_stepped_aside` (answers C, H and L) — an automation switches it while it stays available: rewritten once; a second change: the step-aside X8 defines, latched; the automation switching it again afterwards gets no write from the plugin;
     - `test_relay_wifi_loss_raises_alarm_after_5_min_and_resends`;
     - `test_relay_off_timer_lapses_without_repeats`;
     - `test_relay_with_an_unknown_timer_is_kept_on_by_repeats` — the timer declared "I don't know": "on" is repeated every `relay_repeat_s` while the command is on, and a 10-min timer in the model never lapses;
     - `test_relay_start_up_state_after_power_cut`;
     - `test_relay_path_without_the_separate_contact_tick_is_blocked` (answer G).
   - Boiler:
     - `test_restart_lockout_and_pump_overrun`;
     - `test_relay_proof_of_heat_outlasts_the_restart_lockout` — X8's 30-min proof window against the model's 20-min lockout: no "boiler not responding".
   - Wall thermostat: `test_wall_thermostat_takes_over_after_hand_back_with_its_own_program`.
2. Then the models, then `devenv/`, then the J4 notes.

**Rules and values.**
1. **The J4 route (P-37).** A test-only stub integration `opentherm_gw` at `sim/custom_components/opentherm_gw` (provisional, K4; test HA and in-process only).
   - Its config flow creates an entry with `data = {"id": "sim"}`.
   - It registers `set_control_setpoint`, `set_central_heating_ovrd`, `set_max_modulation` and `send_transparent_command`, forwarding them to `boiler_sim`'s hub. `_register_gateway_services` (`__init__.py:136-178`) moves there.
   - It creates the boiler-device entities the plugin reads: the control setpoint and the CH enable.
   - That a custom integration may override a built-in one in HA 2026.9.3 is (assumed; verify in `.venv/.../loader.py` at this step). If it may not, the route is the firmware MQTT path, and the broker is the user's action at J2.
   - `deploy_test.sh` (`COMPONENTS`, `pack`) and `devenv/compose.yaml` add the stub.
   - `devenv/README.md` §4 says so: a diff for consent.
2. **P-112.** The simulated boiler holds its flow at the setpoint with its own hysteresis (5 K, provisional, K4); there is no auxiliary flow above the setpoint. Emitters get first-order inertia: radiators 20 min, underfloor 2 h (provisional, K4). `sim/simulator.py:255-257` keeps the daily sums across steps.
3. **P-113.** Only writes of type persistent count in `persistent_writes`. CH writes are counted in their own counter.
4. **P-114.** Switch zones are driven by `on_percent` × the zone's TPI cycle, 5 min by default: on for `on_percent` of each cycle. The J4 scenarios are reachable through services.
5. **S-05.** A zone VT switched off closes its valve in the simulator.
6. **S-15, T-24.** Over 24 h at +8 °C and at −5 °C, in the same simulated house, starts per hour under control ≤ 1.10 × those of the boiler's own regulation (provisional, K4). This is J4's starts criterion too.
7. **The relay model** (X8, the relays note §2 and §4, the user's answers C, D, G, L and N):
   - start-up state off, on or last;
   - an optional off-timer, restarted by every "on" (Tasmota PulseTime);
   - a restart: unavailable for 10 s, then the start-up state;
   - a restart that is not reported (a relay without availability reporting, e.g. a Zigbee relay with it off): the start-up state with no unavailable phase (answer D);
   - a Wi-Fi loss: unavailable with the state kept, for a set time;
   - a switch by another controller while it stays available: an automation or its own button (answer C), once or repeatedly (answers L and N);
   - an optional `assumed_state`.
   
   The scenarios configure the relay path with answer G's tick ("this is a separate relay contact"); one scenario without it shows the blocker.
8. **The boiler model:** the restart lockout after each burner stop (`anti_cycle_s`, today 180 s by default, `profiles.py:24`, applied at `plant.py:231`) is set to 20 min — Vaillant's factory setting, adjustable 2–60 min — in the relay and boiler scenarios only, as a test-only value; the existing profiles keep their values. Pump overrun of 5 min after the heating demand ends (Vaillant factory value; provisional, K4).
9. **The wall-thermostat model (X6):** one setpoint with a day program, 21 °C 06:00–22:00 and 17 °C otherwise (test-only values).
   - It sends its demand and room setpoint to the gateway, and has no effect while `CS` is overridden.
   - After a hand-back it takes over within 1 min.
   - An on/off-contact variant is added for T-07.
10. **Values for S-37's list:**
    - test-only: 5 K, 20 min (radiators), 2 h, 20 min (restart lockout), 5 min (pump overrun), 10 s (a relay restart);
    - provisional, K4: 1.10× (J4's starts criterion, rule 6).

**Code to change.** The `sim/` files named above; `sim/custom_components/opentherm_gw/` (new, inside the `sim/` layout); `tests/sim/`; `tests/integration/test_acceptance.py`, `test_boiler_sim.py`; `scripts/deploy_test.sh`; `devenv/compose.yaml`; `devenv/configuration.yaml`.

**Texts.** The stub's `strings.json` (English only; test-only); `devenv/README.md` §4 and §5 (diff for consent).

**Missing data.** The simulator can drop any signal (`fail_signal`). Each new scenario includes a run with the relay state unknown, the fault signal missing, the wall thermostat's setpoint unknown, and no flame or flow for a relay home.

**Do not.**
- Do not connect to any Home Assistant. The in-process runs need none; the test HA comes only at J4, after the user says to start.
- Do not install a broker.
- Do not deploy the stub anywhere but the test HA.
- Do not use real device facts as defaults.
- Do not test on a real relay or boiler: J4 uses the simulator only; the Shelly timer check waits for K6.

**Open for the user.** Consent to the `devenv/README.md` diff; at J2, a broker only if the stub route fails.

### Z4 — Independent check of 0.2.2

**Goal and done-when.** One fresh subagent reads 0.2.2 read-only and checks:
- every problem of the review, against every scenario of its row, its §6 test and §4's proposal;
- every decision of 2026-09-26/27 and every answer of 2026-09-27 (A–O), the relay control (X8) included;
- the "Findings of the checks" list;
- the provisional options and values against `SCOPE.md`, S-37's fixed-values table included.

Each finding is fixed with a test first, and another fresh subagent checks the fixes. Done when a check finds no critical or high problem, and the fixes of its own findings have been checked again. Z4 is ✅ and committed.

**Read first.** The plan's Z4 row and "Done for 0.2.2"; CLAUDE.md "Working rules" and "Code conventions"; the user's restrictions of 2026-09-26 (verbatim) and 2026-09-26/27; the user's answers of 2026-09-27 (A–O); `docs/review-2026-09-26.md`; the index of `docs/plan-0.2.2.md`; the research notes of 2026-09-26/27.

**Order of work.**
1. **Brief a fresh subagent.**
   - Include, in full, every rule of CLAUDE.md "Working rules" and "Code conventions", the user's restrictions (verbatim Polish), and the standing rules of 2026-09-27: results saved locally, plain Polish to the user.
   - Scope: the whole code, tests, `SCOPE.md`, `PLAN.md` and the plans; read-only; no network. Tests with coverage, `mypy` and `ruff` run through `scripts/env.sh`, where installed.
   - It must not read `home-assessment.md`, `devenv/local.env`, `devenv/ssh/`, `session-summary-*.md` or earlier analysis reports.
2. **The report** goes to `research/2026-MM-DD-z4-check.md` (git-ignored, no consent needed), with every finding's file:line and a severity. It is summarised to the user in plain Polish.
3. **Each finding:** a failing test first, then the fix, then both test runs, `ruff`, `mypy` and the coverage check; one commit each.
4. **A new fresh subagent** checks the fixes and the scenarios around them. Repeat from step 3 until a check finds no critical or high problem.
5. A copy of the report under `docs/` is made only with the user's consent.

**Rules and values.**
- One subagent at a time. A multi-agent workflow runs only if the user asks for one (CLAUDE.md, the plan).
- Medium and low findings are fixed, or named in "Open after 0.2.2" with a release.

**Code to change.** Only what the findings require, test first.

**Texts.** As the findings require.

**Missing data.** Research notes are git-ignored but local, so the subagent reads them there. If a note is missing, the finding is judged on the plan alone, and the report says so.

**Do not.**
- Do not run a multi-agent review without the user's go-ahead.
- Do not write a report into `docs/` without consent.
- Do not leave the decisions or the answers out of scope.
- Do not change the specification to fit the code: a spec error is reported as such.

**Open for the user.** None; the user sees the summary. A multi-agent review happens only if the user asks.

### Open after 0.2.2 — what a session does

- **At the end of every step,** add each remainder by name, with its release (or "release set at K4"). Commit it without waiting and show the diff in the step's report (answer B).
- **Items this list must hold** (a session adds each one the plan does not name yet):
  - S-29: SmartPI's further signals and the Auto-TPI pause — release set at K4.
  - Each feature S-60 assigns a later release, by name.
  - Review question 19's second half: a warning for zones not fed by the boiler — 0.3.
  - What X2 could not show of a silent MQTT drop or a broken ESP–PIC link, per Q3 — release set at K4.
  - The Shelly off-timer check (Q3.10): at K6, on the user's own relay if they have one, never at J4, which uses the simulator only; the result is kept in `research/`. Until then the relay texts say it is not documented.
  - The Zigbee availability limit for relays: a dead Zigbee relay may look available for a long time (ZHA), or always with availability reporting off (Zigbee2MQTT). Answer D covers a restart that was not seen, not a relay that died — release set at K4.
  - A recorded "heating commanded" entity and event for users leaving VT's central boiler — 0.3.
  - Y2's remainder: days read from the recorder before the plugin's first run cannot tell Home Assistant's downtime — release set at K4.
- **Item 6 stays as the user decided (answer K, 2026-09-27):** "off" as a low setpoint (L4, decision 11) and decision 1's low `CS` with `CH` left alone stay blocked until the user lifts the block at K4, even if Q3's research is favourable. No step lifts it by itself.

### After 0.2.2 — what a session does

- **Continue with the open steps of `docs/plan-0.2.md`, in order:**
  - J2 🔒, with Q2's firewall check T-25;
  - J4 🔒, in the test HA with the simulator only, after the user says to start, with Q2's scenarios and the starts criterion (at most 1.10 × the boiler's own regulation's starts per hour over 24 h at +8 °C and −5 °C, provisional, K4; Z3 rule 6); decision 15's `docker kill` only in the test LXC; no real relay or boiler;
  - K1 🔒, with the relay setup texts;
  - K2, whose ✅ was withdrawn until its validation runs, which needs K5's repository;
  - K4 🔒: the review of the control laws, with decision 16; every "(provisional, K4)" value of S-37's table (Q1 G), as Q4's agenda lists them; the answers the steps gave to review questions 3, 5, 6, 8–12, 19 and 20; the known limits named for K4 (a clipped setpoint that stays flat is judged as another controller); the reading that only relay restarts without a trace count toward answer N's fourth (X8 R7), and that answer M's "on a gateway" covers the entity path with a gateway topology (X3); whether to lift the block on "off" as a low setpoint and on decision 1's low `CS` (answer K); the 0.2.1 change log read together with `docs/review-2026-09-26-vs-0.2.md`. L4 itself is decided (decision 11: blocked);
  - K5 🔒, publishing `0.2.2b1`, or setting the manifest and `RELEASE` to the version decision 16 picks at K4;
  - K6 🔒, including the Shelly check on the user's own relay, if they have one;
  - K7 🔒, setting the manifest and `RELEASE` to the release version (provisional `0.2.2`).
- Stop at every 🔒.
- Update CLAUDE.md's "Where to continue", as a diff for consent.

### Done for 0.2.2 — what a session does

- **Run:**
  - both pytest runs with branch coverage (Z1);
  - the per-module coverage check (Z2);
  - `ruff check`, `ruff format --check` and `mypy`;
  - the in-process acceptance scenarios, including Q2's J4 additions that run in-process and Z3's new ones.
- **Confirm:**
  - every step of the plan is ✅;
  - every problem in the index is fixed, moot by a recorded decision, or named in "Open after 0.2.2";
  - every decision of 2026-09-26/27 and every answer of 2026-09-27 (A–O) is built as its step says, X8 included, or named there;
  - every value the steps define is in S-37's fixed-values table (Q1 G) with its reason, and K4's agenda (Q4) lists every "(provisional, K4)" one;
  - Z4's last check found no critical or high problem;
  - `SCOPE.md` and `PLAN.md` changes (Q1, Q2) were accepted by the user.
- Report in plain Polish, with the results saved in `research/`.
