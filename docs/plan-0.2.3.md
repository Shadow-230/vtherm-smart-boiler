# Plan 0.2.3 — Corrections after the review of 2026-10-04

Goal: close every problem of the full review of 0.2.2 (`docs/review-2026-10-04.md`: PB-01–PB-101 in
the code and the tests, SB-01–SB-39 in the specification, TB-01–TB-38 missing tests) before anything
reaches the test HA. Each one is fixed, made moot by a recorded decision, or named in "Open after
0.2.3" with its release. The review found no critical problem and four high ones: a relay another
controller keeps switching back is re-commanded every 5 min for ever (PB-01); a control switch
restored "on" at start-up is stored "off" until control's first write (PB-02); nothing warns that
the boiler does not heat on the water-temperature paths (SB-01); VT's not-started thermostats count
as the user's "off" (SB-02). The user answered the review's 15 open questions on 2026-10-05
(decisions 1–15 below). The steps of `docs/plan-0.2.md` still open (J2, J4, K1–K7) follow this plan.
The first published version stays the user's decision at K4 and K5 (`docs/plan-0.2.2.md`, decision
16); provisionally pre-release 0.2.3b1, set at step 4.3.
Scope: `SCOPE.md`; overview: `PLAN.md`; the previous corrections: `docs/plan-0.2.2.md`.

The plan is cut into four parts, run in order. **Each part ends with a stop (🔒): the main session
reports what was done, what is left and the tokens the part used, and the user decides whether the
next part starts** (the user's wish of 2026-10-05, to control the tokens spent). Inside a part, its
document step comes first; its diff waits for the user's consent, and the part's code steps may
start meanwhile.

Status on 2026-10-06: part 1 done (its documents consented by the user at the stop 1.6); part 2
under way.

## How to read this plan

- Problems are named as in the review: PB-nn (code and tests), SB-nn (specification), TB-nn (missing
  tests). Each problem's row in `docs/review-2026-10-04.md` §3, §4 or §6 — its proposal and its test —
  says what "closed" means; the review's §7 lists the five changes to make first, which are F1–F5.
- "Decision n" refers to the numbered list below.
- 🔒 marks a step that needs the user's consent or action; ✅ marks a finished step.
- Steps are numbered by part: 1.1, 1.2, … The review's five changes to make first are steps 1.2,
  1.3, 1.4, 2.2 and 2.3.
- The index at the end gives the step for every problem.

## Decisions of 2026-10-05 (the user)

The user's answers to the review's open questions (`docs/review-2026-10-04.md`, appendix E), in its
order:

1. **SB-02:** a VT thermostat VT has not started (`is_ready` not true) counts as unknown after the
   recognition period, so decision 3 of `docs/plan-0.2.2.md` applies — a hand-back to a working
   thermostat, else the "no zone known" alarm and issue; a started zone that shows "off" keeps S-34.
2. **SB-01:** on the water-temperature paths, "no sign the boiler heats": heating commanded, a zone
   calling, the flame known off (or no flow rise) for about 30 min → an information alarm and a
   warning repair issue, never a hand-back, as R12 on the relay path; SCOPE's matrix row corrected.
3. **PB-03:** when no configured demand criterion can be judged, SCOPE §7's rule holds: the "no zone
   known" alarm and a repair issue naming the criterion (an error where heating stops, a warning
   after a hand-back); plan 0.2.2's X3 is written the same.
4. **SB-03:** a heating "on" ignored from the start is treated as answer O treats "off": control
   blocked, the boiler handed back, an error-level notification that the boiler does not take
   heating; the blocker stays until the user switches control off and on.
5. **SB-04:** a timeout hand-back is released also once the read-back has left both the plugin's last
   value and the lowest water temperature; the form asks the device's timeout with this method, and
   the check and its alarm are timed from it.
6. **SB-05, SB-06:** a declared relay timer's lapse counts only within ±60 s of a whole multiple (at
   most 3×) of its length, other switch-offs going to answers C and N; a reporting relay that stops
   taking commands after the start phase raises an error-level issue after about 15 min (3 checks)
   and, for "off", control is blocked and the relay handed back.
7. **SB-07:** moving from VT, where VT's count is 0 beside a power threshold, the count is pre-filled
   0, as VT used it.
8. **SB-08:** J4's starts criterion gets its conditions — comfort parity with the boiler's own
   regulation and the ±3 K daily outdoor swing at +8 and −5 °C — with a test carrying the swing (a
   strict xfail until K4); the acceptable ratio is decided at K4.
9. **PB-08:** the restart latch also holds when VT's central entry changed in this Home Assistant run
   before a plugin entry began watching VT, or when VT's sensor is a stand-in written in this run
   while the entry says off.
10. **SB-36:** the return by itself after the external-control switch's hand-back is the user's
    choice: a separate opt-in, off by default (so by default that method is excluded, as relays
    are), with a text saying what it risks.
11. **SB-11:** principle 13's rules 3 and 5 are built for the comfort correction now: it moves only
    while the starts do not rise and steps back when they do, and it freezes in extreme weather, with
    "extreme" defined.
12. **SB-10:** a setup that fails where a hand-back stops heating, with the stored wish "on", raises
    a persistent error-level issue at once: the plugin did not start and the house is not heated.
13. **SB-18:** the high-pressure alarm has no default (as "add water"); the user enters it from the
    safety valve's rating, and the text says where to read it; the defaults table lists the
    monitor's other alarm thresholds with their reasons.
14. **SB-29:** a boiler-fault "off" pauses zone learning as a hot-water draw does; every draw pauses,
    also within 10 min of a resume; a pause lasts at most 1 h from its start.
15. **Documents:** the specification and plan fixes come before K4, each shown as a diff for consent;
    additions to an "Open after" list are committed at once.

## Rules that shape this release

- Everything in the rules of the earlier plans still applies.
- Every problem of the review has a step (index). One that a decision makes moot is marked so in its
  step; one deferred is named in "Open after 0.2.3" with its release.
- Tests first: the review's proposed test where it has one, else a test that shows the problem; then
  the fix. A step is ✅ only when every scenario of each of its problems is covered, and every new
  mechanism has a negative test with an unknown, missing or `None` input.
- Every change to a `*.md` file is shown as a diff and waits for the user's consent, except a ✅ on a
  finished step and an addition to "Open after 0.2.3", which are committed at once with the diff in
  the step's report.
- Before each code commit: both test runs as CI runs them, the per-module coverage floor, `ruff
  check`, `ruff format --check` and mypy; commits by path.
- Provisional values are marked "(provisional, K4)" in `SCOPE.md` and kept in one place in the code.
- Each part's check is one fresh read-only subagent over that part's commits; a finding it rates
  critical or high is fixed and checked again before the part's stop; medium and low ones are fixed
  or named in "Open after 0.2.3". A multi-agent review only with the user's go-ahead.

## Part 1 — the four high problems

Why: PB-01, PB-02, SB-01 and SB-02 are the review's high problems: a relay fight that cycles a
boiler, a control switch that can come back off after a crash, a boiler that does not heat unseen,
and VT's not-started zones read as the user's "off".

| Step | Work |
|---|---|
| 1.1 ✅ | `SCOPE.md` and `docs/plan-0.2.2.md` take decisions 1–4, 6 and 12 (SB-01, SB-02, SB-03, SB-05, SB-06, SB-10; PB-03's one rule in SCOPE §7 and X3); `CLAUDE.md` "Where to continue" names this plan. |
| 1.2 ✅ | No relay fights (decision 6): PB-01, PB-44, SB-05, SB-06. Keep the one rewrite through resends; a resend the relay never shows counts against another controller (answers C, N); the declared timer's lapse window bounded; a relay that stops taking commands mid-session raises an issue and, for "off", blocks and hands back. |
| 1.3 ✅ | The control unit's wish and hand-back debt hold under errors and restarts: PB-02, PB-04, PB-05, PB-12, PB-13, PB-14, PB-16, TB-02, TB-05, TB-06. The restored wish saved before anything else; the error path keyed on the debt and routed through the minute gate and the confirmation; the fixable owed issue when a hand-back stays unconfirmed; the lost-link issue kept across restarts; the old debt folded at the session's first write; a control-store write that fails noticed. |
| 1.4 ✅ | "Nothing heats" visible and decision 3's end states settled (decisions 1–4, 12): PB-03, PB-23, SB-01, SB-02, SB-03, SB-10, TB-01. |
| 1.5 ✅ | The check of part 1. |
| 1.6 🔒 ✅ | Stop: the report to the user, with the tokens part 1 used; the user decides whether part 2 starts. |

## Part 2 — the rest of the five changes, and the user's other answers

| Step | Work |
|---|---|
| 2.1 | `SCOPE.md` and the plans take decisions 5, 7–11, 13 and 14 (SB-04, SB-07, SB-08, SB-11, SB-18, SB-29, SB-36; PB-08's latch rule); `devenv/README.md` takes Z3's J4 proposal (`research/2026-10-02-z3-readme-proposal.md`) with J4's starts criterion as decision 8 states it. |
| 2.2 ✅ | Hand-backs confirmed correctly, and what judges them frozen while one is owed (decision 5): PB-09, PB-10, PB-11, PB-22, PB-26, PB-27, SB-04, TB-04, TB-13. |
| 2.3 ✅ | Setup and stored options safe, and K4 given the full list (decision 9): PB-06, PB-07, PB-08, PB-24, SB-09, TB-03, TB-08, TB-25. Wrong shapes and non-finite or out-of-range numbers refused with a reason and an owed hand-back reported; platforms unloaded after a late setup failure without wiping the registry; the restart latch's untick gap; SB-09's additions to "Open after 0.2.2" committed at once, and K4's rows pointing to every item marked K4. |
| 2.4 ✅ | The comfort correction meets principle 13's rules 3 and 5 (decision 11): SB-11. Rule 3: it moves only while the starts per hour do not rise against the same hours before it began, and steps back when they do; rule 5: it freezes in extreme weather — an outdoor temperature beyond the design outdoor temperature, or a change faster than a set rate per hour (provisional, K4) — with its tests and the simulator's starts measured with it on. |
| 2.5 ✅ | The smaller answers: learning pauses (decision 14: SB-29); no default for the high-pressure alarm and the monitor's thresholds listed (decision 13: SB-18); the count pre-filled 0 from VT (decision 7: SB-07); the return by itself after the external-control switch as a separate opt-in (decision 10: SB-36); J4's starts criterion with its conditions and a test carrying the daily swing (decision 8: SB-08). |
| 2.6 ✅ | The check of part 2. |
| 2.7 🔒 ✅ | Stop: the report to the user, with the tokens part 2 used; the user decides whether part 3 starts. |

## Part 3 — the remaining problems in the specification, the code and the tests

| Step | Work |
|---|---|
| 3.1 | The remaining specification problems, settled in `SCOPE.md`, `PLAN.md` and the plans: SB-12, SB-13, SB-14, SB-15, SB-16, SB-17, SB-19, SB-20, SB-21, SB-22, SB-23, SB-24, SB-25, SB-26, SB-27, SB-28, SB-30, SB-31, SB-32, SB-33, SB-34, SB-35, SB-37, SB-38, SB-39. |
| 3.2 ✅ | Control, guards, relay, transport, units, lifecycle, stores, repairs, forecasts, the monitor, the VT link and the feature manager: PB-15, PB-21, PB-28, PB-29, PB-30, PB-31, PB-32, PB-33, PB-34, PB-35, PB-36, PB-37, PB-38, PB-40, PB-41, PB-42, PB-43, PB-53, PB-70, PB-72, PB-73, PB-84, PB-17, PB-18, PB-47, PB-51, PB-52, PB-55, PB-56, PB-57, PB-58, PB-59, PB-60, PB-62, PB-19, PB-20, PB-63, PB-64, PB-65, PB-66, PB-67, PB-46, PB-48, PB-49, PB-50. |
| 3.3 ✅ | The config and options flows, entities, texts, icons, the manifest, CI, scripts, tools, the simulator, the test HA files, and wrong or weak tests: PB-45, PB-54, PB-68, PB-69, PB-71, PB-83, PB-39, PB-61, PB-74, PB-75, PB-76, PB-77, PB-78, PB-79, PB-80, PB-81, PB-82, PB-85, PB-86, PB-87, PB-88, PB-89, PB-91, PB-92, PB-93, PB-25, PB-90, PB-94, PB-95, PB-96, PB-97, PB-98, PB-99, PB-100, PB-101. |
| 3.4 | The check of part 3. |
| 3.5 🔒 | Stop: the report to the user, with the tokens part 3 used; the user decides whether part 4 starts. |

## Part 4 — missing tests, version, the final check

| Step | Work |
|---|---|
| 4.1 | The high-priority missing tests not written in parts 1 and 2: TB-07, TB-09, TB-10, TB-11. |
| 4.2 | The medium-priority missing tests: TB-12, TB-14, TB-15, TB-16, TB-17, TB-18, TB-19, TB-20, TB-21, TB-22, TB-23, TB-24, TB-26, TB-27, TB-28, TB-29, TB-30, TB-31, TB-32, TB-33, TB-34, TB-35, TB-36, TB-37, TB-38. |
| 4.3 | The manifest and `tests/test_release.py` set to 0.2.3b1 (provisional, decision 16 of `docs/plan-0.2.2.md`). |
| 4.4 | An independent read-only check of 0.2.3 by a fresh subagent against every problem of the review and decisions 1–15; a finding fixed with a test and checked again by another fresh subagent, until a check finds no critical or high problem. A multi-agent review only with the user's go-ahead. |
| 4.5 🔒 | Stop: the report to the user, with the tokens part 4 used. |

## Open after 0.2.3

Left on purpose for a later release; what a step leaves open is added here by name.

1. Step 1.2 (relay): a relay stuck in one state while the plugin's command alternates faster than
   about 15 min (VT's cycles) is never "not taken" — only the information alarm shows, and a
   stuck-on relay can heat through the "off" periods without an error issue. A count of unshown
   sends within a window would catch it but can turn isolated lost commands into a block — the
   user's decision, K4.
2. Step 1.2: a relay that keeps dropping out of reach every few minutes restarts the 3-check count
   at each outage, so it is never "not taken" ("relay unreachable" and "commands lost" still
   show) — K4.
3. Step 1.2: a switch-back Home Assistant never records (a device coalescing its reports) cannot
   be told from a relay not taking commands: decision 6's path, not answers C and N — K4.
4. Step 1.2: an "on" not taken is sent again at every check for good (decision 6); a relay that
   does switch on briefly but unseen would give the boiler a short pulse every 5 min — K4.
5. Step 1.2: a declared timer must match the relay's real one within 60 s (or its 2× or 3×); a
   longer real timer makes the plugin step aside after the fourth lapse within a day (before:
   answered for good); the field's text says so — K4.
6. Step 1.2, bounded at 1.5: a relay that reports no state gets its command at once at a return
   from unavailable or unknown — at most once per relay check (5 min) and not within 120 s of the
   last write — and each such return counts toward "commands lost"; the bounds — K4.
7. Step 1.3 (PB-16): while the control store cannot be written, control does not take the boiler
   and hands back what it holds — stand-alone, nothing heats until a write works again (an
   error-level issue says so); the store is tried again every minute (provisional) — K4.
8. Step 1.3 (PB-16): a failed write is seen through Home Assistant's private
   `Store._async_write_data` (2026.9.0 and 2026.9.3); a version that stops calling it hides
   failures again, and control runs as before 0.2.3 — the PB-16 tests catch it on the versions CI
   runs — K5.
9. Step 1.3 (PB-16): the repair flow's release and the entry's removal write the control store with
   no unit to block or tell; a failed write there is in Home Assistant's log only — K4.
10. Step 1.3 (PB-14): the lost link's issue ("Control handed the boiler back: its data is lost")
    also shows when control was switched on with the link already lost and never held the boiler;
    its wording — K4.
11. Step 1.3 (TB-05): after a stop that ran out of time, the hand-back stays owed with the
    persistent issue until the next start; a disabled entry has no next start, so that issue is
    the only alarm (as before) — K4.
12. Step 1.4 (PB-03): the issue names the criteria by their codes ("power", "opening"), explained
    in its text, and the alarm keeps its name "no zone known" in this case — wording, K4.
13. Step 1.4 (SB-03): with "off" confirmed first in a session and the heating read-back then frozen
    at "off", a later "on" counts as a lost command, sent again about every 120 s with only
    "commands lost", and the broken read-back is never named — K4.
14. Step 1.4 (SB-03): a relay remembers only the last command it ignored, so an ignored "off"
    followed by an ignored "on" is named "on" (the same latch; its text only) — K4.
15. Step 1.4 (SB-10): a wish never stored counts as "on" at a failed setup; the control switch's
    restored state could tell it — K4.
16. Step 1.4 (SB-01): the 5-K rise of the flow counts from its value at the start of the count, not
    from its lowest since (a boiler firing again after a pause) — K4.
17. Step 1.4 (SB-01): at low load a boiler's restart wait and slow cooling could keep the flame off
    about 30 min while a zone calls in mild weather; the false-alarm rate is checked at K4 (J4's
    runs).
18. Step 1.4 (SB-01): "the boiler heats" (`boiler_heats`) is shown on the relay path only — K4.
19. Step 1.5 (relay): a declared timer that differs from the relay's real one by more than 60 s
    makes the plugin step aside after about 2 h; the latch issue does not name the switch-offs'
    regular age or say the declared length may be wrong — K4.
20. Step 1.5 (relay): a rewrite retried at +115 s is judged at +120 s, before it can be read back,
    so the plugin may step aside a little early — K4.
21. Step 1.5 (relay): a declared timer is timed from the "on" sent at a restart, as before 0.2.3 —
    K4.
22. Step 1.5 (relay): a relay that reports its state and loses power every minute is sent "on" at
    each return (R2), about 30 burner starts an hour, with "commands lost" raised — the user's
    decision, K4.
23. Step 1.5 (relay): for a relay that reports no state, a return within 120 s of the last write
    waits for the regular repeat, so the boiler may stay off up to the repeat interval, as before
    0.2.3; the lost command is counted — K4.
24. Step 1.5 (control store): the 5-min hold after a failed write does not grow after repeated
    failures — a store failing every 7th write takes and hands back the boiler about every 10 min
    — and a flaky store logs an error and a note at each flip — K4.
25. Step 1.5 (hand-back): while the "heating on ignored" latch and a debt last, each restart writes
    the heating switch "on" once more, as a relay's step aside does — K4.
26. Step 1.5 (hand-back): a release is judged against the new session's planned setpoint even when
    that write failed, as before 0.2.3 — K4.
27. Step 1.5 (demand): with the count at 0, an idle zone in a heating mode can give a criterion data
    while a calling zone gives none; the calling zone is then named only by the information sensor
    "a demand criterion has no data", with no repair issue (the form refuses that set-up; it arises
    when a zone stops publishing later) — K4.
28. Step 1.5 (decision 4): a heating read-back slower than 360 s latches control as "on ignored"
    (the 120-s window is provisional) — K4.
29. Step 1.5 (decision 2): on a water path without a flame input, a boiler holding the flow steady
    below the plugin's setpoint raises "no sign the boiler heats" after 30 min — K4.
30. Step 1.5 (decision 2): without a hot-water signal, a draw counts as a sign of heat, so with the
    panel set to summer the alarm and its issue clear at each draw and return 30 min later — K4.
31. Step 2.2: on the OTGW paths with an OpenTherm thermostat, whether the field for the
    thermostat's own request should be required (the release is confirmed through it); the bounds
    (1–60 min) and default (1 min) of a timeout hand-back's device timeout — K4.
32. Step 2.2: after a restart, an owed gateway hand-back still sends `CS=<lowest>` once — K4.
33. Step 2.2: the return by itself after a timeout hand-back still needs the baseline, so a device
    whose own value moves never returns by itself — K4.
34. Step 2.2: while a hand-back is owed, the circuit's and boiler's maxima can still change, and
    they cap the lowest the hand-back writes; only the save's confirmation for a change that would
    block control catches it — K4.
35. Step 2.2: on the entity path, a hand-back retry rewrites a lowest that already shows (the
    gateways skip it) — K4.
36. Step 2.3: boiler and building parameters read from stored options are checked against the
    core's plausible ranges, not the form's (nan and inf are refused) — K4.
37. Step 2.3: an untick of VT's central boiler in the seconds between Home Assistant's start and its
    "started" event, before any plugin entry watches VT, is not caught by the restart latch — K4.
38. Step 2.3: an entry first set up while Home Assistant runs takes the recorder's start time, so
    any stand-in of VT's central-boiler sensor latches until the restart, and without a recorder
    any VT central entry does — K4.
39. Step 2.3: VT's central entry removed during a run while its central boiler was on still counts
    as "not there", as before 0.2.3 — K4.
40. Step 2.3: if the unload in a failed setup itself fails, the old entities stay attached to the
    stopped coordinator until a restart (the registry is kept) — K4.
41. Step 2.4: rule 3's reference — the same length of time just before the comfort correction
    began — does not lower the starts in J4's simulated house, where they were already as high
    before it began (with the correction on, 1.39 to 6.28 times the boiler's own regulation's
    starts, `research/2026-10-06-p2-4-report.md`): another reference, or the correction kept off —
    the user's decision, K4.
42. Step 2.4: rule 5's freeze also stops the correction from falling, so through a long outage of
    the outdoor sensor it keeps its value (at most +3 K) until a hand-back — K4.
43. Step 2.4: the control state does not say why the comfort correction is held — K4.
44. Step 2.5 (decision 13): entries that ran with the old high-pressure defaults keep 2.5 and
    2.8 bar, written into their options at the migration; below a valve rated about 2.1 bar they
    never fire — a one-time hint to confirm the limits — K4.
45. Step 2.5 (decision 14): the 1-h cap's follow-up state is not stored, so a restart while a
    cause lasts gives one more pause — K4.
46. Step 2.5 (decision 10): entries that used the external-control switch's return by itself lose
    it until the user ticks the new option, with no notice; the second confirmation's text names
    only the general return — K4.
47. Step 2.6 (changes item 42): rule 5 now stops only the comfort correction's rise — every fall
    passes, through an outage of the outdoor sensor too — while hot water and foreign heat still
    stop it both ways; confirm both — K4.
48. Step 2.6: rule 3 can step the correction back minutes after its first rise (one start after it
    against none before), and the starts kept from before it began are compared across a new
    session with starts days later — K4.
49. Step 2.6: an entry whose `monitor` section is stored in another shape skips the migration of
    decision 13 and loses its high-pressure limits — K4.
50. Step 2.6: the restart latch also holds for any other change to VT's central entry in this run
    (a migration, another setting), and a reset of the recorder moves the run's start — K4.
51. Step 2.6: with the thermostat's request not mapped, an OTGW hand-back over MQTT with an
    OpenTherm thermostat stays owed with its alarm (see item 31); with a device timeout up to
    60 min, a restart before the release writes the lowest again, so the device may hold it about
    2 h; a stored timeout out of range falls back to 1 min rather than being refused — K4.
52. Step 3.1 (SB-14): the circuit control "controlled separately" (an external mixing controller, a
    mixer driven by Home Assistant, a separate weather controller; `SCOPE.md` §5) has no code — no
    release yet, unless the user names one at K4; it sits beside item 1 of "Open after 0.2.2".
53. Step 3.1 (SB-33): the freshness guard writes nothing while the boiler link's data are stale, so
    a stand-alone gateway's `CS` lapses within about a minute (an extra start) and a held command
    stays up to 5 min against VT (`SCOPE.md` principle 12, exception 7); whether "heating off" is
    exempt from the guard — K4.
54. Step 3.2 (PB-34): a setpoint read-back whose entity has `assumed_state` is shown
    "unverified" but still judged; whether to block control or refuse it in the form — K4.
55. Step 3.2 (PB-84): nine functions on the control path stay above the complexity limit — split
    them behind their precedence tables, or a relaxed limit — K4.
56. Step 3.2 (PB-43): a DS18B20's 85 °C power-on value, or a stuck reading, on a temperature
    source of foreign heat is not caught — K4.
57. Step 3.2 (PB-42, PB-55): a number's device unit is read through Home Assistant's internal
    `hass.data["number"]`, and the follow of a rename during setup through its private
    `setup_tasks` (on a version without it the first setup can race again); a hand-back unit's
    `taken_with` entities renamed during setup are not followed — K5.
58. Step 3.2 (PB-64): a banded alarm level restarts its 5-min count after a gap (only the low-flow
    warning keeps its "since"); J4 confirms that a restart writes one recorder row per entity
    (PB-65) — K4.
59. Step 3.2 (SB-27, SB-32): the closed-room frost issue's advice texts, and the circuit-too-hot
    feature left inactive for a passive circuit without its own flow reading (rather than the
    boiler's flow as an upper bound) — K4.
60. Step 3.3 (PB-61, PB-79, PB-82): a README note for installs without a container about the
    packages of `mqtt` and `opentherm_gw`; `pl.json` read by a native speaker; temperature
    attributes named "(°C)" rather than converted to Home Assistant's unit — K5.
61. Step 3.3 (PB-75): `docs/plan-0.2.2-details.md` Y3 rule 7 worded as the new verdict text — K4.
62. Step 3.3 (PB-85, PB-86): no canary job on the newest Home Assistant (it needs a matching
    pytest-homeassistant-custom-component); the pinned actions are updated by hand — K2.
63. Step 3.3: on the real OTGW path, a boiler that ignores or limits a setpoint the gateway
    acknowledged cannot be seen in the read-back — K4.
64. Step 3.3: with the simulator's tick forced after the plugin's step, six relay acceptance tests
    (restart resent, unreported restarts, switched while available, Wi-Fi loss) fail at checks on
    exact time boundaries — looked at in the check 3.4; what is left — K4.

## After 0.2.3

The open steps of `docs/plan-0.2.md` follow: J2 🔒, J4 🔒 (with J4's starts criterion as step 2.5
writes it), K1 🔒, K2, K4 🔒 (with the items marked K4 in "Open after 0.2.2" and "Open after
0.2.3"), K5 🔒, K6 🔒, K7 🔒.

## Done for 0.2.3

- Every problem of `docs/review-2026-10-04.md` fixed, moot by a recorded decision, or named in "Open
  after 0.2.3" with its release (index).
- Decisions 1–15 built as their steps say.
- Both test runs, `ruff check`, `ruff format --check` and mypy pass; every module at least 95 % with
  branches, the config and options flows 100 %.
- After the fixes, an independent check (4.4) finds no critical or high problem, and the fixes of its
  own findings are checked again.

## Index: review problem → step

Problems in the code and the tests: PB-01 1.2 · PB-02 1.3 · PB-03 1.4 · PB-04 1.3 · PB-05 1.3 · PB-06 2.3 · PB-07 2.3 · PB-08 2.3 · PB-09 2.2 · PB-10 2.2 · PB-11 2.2 · PB-12 1.3 · PB-13 1.3 · PB-14 1.3 · PB-15 3.2 · PB-16 1.3 · PB-17 3.2 · PB-18 3.2 · PB-19 3.2 · PB-20 3.2 · PB-21 3.2 · PB-22 2.2 · PB-23 1.4 · PB-24 2.3 · PB-25 3.3 · PB-26 2.2 · PB-27 2.2 · PB-28 3.2 · PB-29 3.2 · PB-30 3.2 · PB-31 3.2 · PB-32 3.2 · PB-33 3.2 · PB-34 3.2 · PB-35 3.2 · PB-36 3.2 · PB-37 3.2 · PB-38 3.2 · PB-39 3.3 · PB-40 3.2 · PB-41 3.2 · PB-42 3.2 · PB-43 3.2 · PB-44 1.2 · PB-45 3.3 · PB-46 3.2 · PB-47 3.2 · PB-48 3.2 · PB-49 3.2 · PB-50 3.2 · PB-51 3.2 · PB-52 3.2 · PB-53 3.2 · PB-54 3.3 · PB-55 3.2 · PB-56 3.2 · PB-57 3.2 · PB-58 3.2 · PB-59 3.2 · PB-60 3.2 · PB-61 3.3 · PB-62 3.2 · PB-63 3.2 · PB-64 3.2 · PB-65 3.2 · PB-66 3.2 · PB-67 3.2 · PB-68 3.3 · PB-69 3.3 · PB-70 3.2 · PB-71 3.3 · PB-72 3.2 · PB-73 3.2 · PB-74 3.3 · PB-75 3.3 · PB-76 3.3 · PB-77 3.3 · PB-78 3.3 · PB-79 3.3 · PB-80 3.3 · PB-81 3.3 · PB-82 3.3 · PB-83 3.3 · PB-84 3.2 · PB-85 3.3 · PB-86 3.3 · PB-87 3.3 · PB-88 3.3 · PB-89 3.3 · PB-90 3.3 · PB-91 3.3 · PB-92 3.3 · PB-93 3.3 · PB-94 3.3 · PB-95 3.3 · PB-96 3.3 · PB-97 3.3 · PB-98 3.3 · PB-99 3.3 · PB-100 3.3 · PB-101 3.3

Problems in the specification: SB-01 1.4 · SB-02 1.4 · SB-03 1.4 · SB-04 2.2 · SB-05 1.2 · SB-06 1.2 · SB-07 2.5 · SB-08 2.5 · SB-09 2.3 · SB-10 1.4 · SB-11 2.4 · SB-12 3.1 · SB-13 3.1 · SB-14 3.1 · SB-15 3.1 · SB-16 3.1 · SB-17 3.1 · SB-18 2.5 · SB-19 3.1 · SB-20 3.1 · SB-21 3.1 · SB-22 3.1 · SB-23 3.1 · SB-24 3.1 · SB-25 3.1 · SB-26 3.1 · SB-27 3.1 · SB-28 3.1 · SB-29 2.5 · SB-30 3.1 · SB-31 3.1 · SB-32 3.1 · SB-33 3.1 · SB-34 3.1 · SB-35 3.1 · SB-36 2.5 · SB-37 3.1 · SB-38 3.1 · SB-39 3.1

Missing tests: TB-01 1.4 · TB-02 1.3 · TB-03 2.3 · TB-04 2.2 · TB-05 1.3 · TB-06 1.3 · TB-07 4.1 · TB-08 2.3 · TB-09 4.1 · TB-10 4.1 · TB-11 4.1 · TB-12 4.2 · TB-13 2.2 · TB-14 4.2 · TB-15 4.2 · TB-16 4.2 · TB-17 4.2 · TB-18 4.2 · TB-19 4.2 · TB-20 4.2 · TB-21 4.2 · TB-22 4.2 · TB-23 4.2 · TB-24 4.2 · TB-25 2.3 · TB-26 4.2 · TB-27 4.2 · TB-28 4.2 · TB-29 4.2 · TB-30 4.2 · TB-31 4.2 · TB-32 4.2 · TB-33 4.2 · TB-34 4.2 · TB-35 4.2 · TB-36 4.2 · TB-37 4.2 · TB-38 4.2
