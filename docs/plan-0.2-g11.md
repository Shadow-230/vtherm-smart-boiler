# Plan 0.2, step G11 — Comfort, the curve's room, long runs and open windows

Goal: the corrections the user decided on 2026-10-09/10 from the J4 tests and a review of the
"curve too low" case. A room held above the curve's own room temperature, a SmartPI zone in its
learning phase and an open window could each leave a boiler burning for hours on water too cool,
with nothing raising it or telling the user. Step G11 of `docs/plan-0.2.md`. Control stays off by
default; nothing here writes to the boiler beyond what control already writes.
Scope: `SCOPE.md`; overview: `PLAN.md`; the release plan: `docs/plan-0.2.md`.

Status on 2026-10-10: G11.0 (this plan), G11.A, G11.B and G11.D done; next G11.E.

## How to read this plan

- "Decision X" refers to the lettered list below (the user's letters, A to G).
- ✅ marks a finished step. Every step is one pull request into `dev`, with its "J4 impact": the
  J4 scenarios to run again in the test Home Assistant once it is deployed; the testing session
  runs them. After each step the main session reports to the user in Polish.
- "Claude's call" marks a choice the user left open ("your call, described"): it is written here
  with its reason, provisional until K4 like every value of this plan.
- Facts verified for this plan are under "Facts"; `CLAUDE.md`'s verified facts take the two that
  last beyond it.

## Decisions of 2026-10-10 (the user)

### A. F7: a held device restarting during a hand-back gets its hand-back value

Done as pull request #51 (2026-10-10): a held value target's third value is judged only once
the plugin's hand-back write to it got through in this debt, and not while a trace of an outage
of its device, or a restart, seen since says the device lost it.

### B. The comfort correction: on by default in full control, a user limit, a warning at the edge

Reverses K4.1 (`docs/plan-0.2.2.md`, open item 24; the user, 2026-10-03).

1. **On by default where the control mode is full control** (a flow setpoint); not offered with
   on/off control (the relay), as today.
2. **Upgraded entries keep what they ran with.** An entry whose control section stored an answer
   keeps it. One whose control section never stored it ran with "off" (the default since K4.1):
   the entry migration (minor version 7) writes "off" into it, so nothing changes on upgrade.
   New entries, and entries that set control up after the update, get "on". (Claude's call, the
   cautious reading the user named.)
3. **Shown at both levels** (Claude's call): it is on by default and changes gas use and starts,
   so a user at the simple level must see it and be able to switch it off. It was advanced only
   since K4.1.
   - At the advanced level it stays in the control behaviour step, beside its limit. At the
     simple level, which has no behaviour step, it is shown in the curve step. Each level sees it
     once, and the J4 runner's answers (the behaviour step) keep working.
4. **The limit is the user's:** a new option, "Highest comfort correction", default 3 K, from
   0.5 to 10 K in steps of 0.5, at the advanced level. The weather ceiling's band (default 10 K)
   still caps everything above the curve, so the lower of the two applies. The rise stays at
   most 3 K a day whatever the limit. (Claude's call: a clearer option rather than the band. Every
   saved entry stores the band, 10 K by default, so making the band carry the limit would turn
   it into a 10 K correction on upgrade.)
5. **At the limit for 3 h with a room still short:** the information alarm "comfort correction
   at its limit" stays, and a **warning repair issue** names the rooms. It goes once the
   correction falls below the limit or no room is short any more.
   - **Additions 2 and 3 (the user, 2026-10-10): one room short counts like any other, and the
     limits stay.** The curve must hold every room, so the correction rises for a single short
     room as for several, bounded as above: its limit, 3 K a day, no rise while another heated
     room is more than 1 K too warm, none while the starts rise, and the hard, circuit and
     weather caps. The water never goes higher for one room's sake.
   - The warning names the room and the possible causes: the heating curve too low, the room's
     radiator too small for it, the room losing heat (a window, leaks). With most rooms short
     the curve comes first; with fewer, the radiator and the heat loss come first, then the
     curve — "check also its radiator, valve and window". The correction then holds at its
     limit; the user can lower it.
   - One issue, `curve_too_low`, with the text `curve_too_low` (most) or `room_short_at_limit`
     (fewer). Its placeholders carry the rooms' names (`zones`) and entity IDs (`entities`) —
     J4's Q5 looks for the room there.
6. **The description** says what it does and what it risks: more gas, possibly more starts. The
   simulation showed 1.75 to 5 times the starts of the boiler's own regulation with VT's TPI
   zones, whose own offset can keep a full-duty zone just short of its setpoint. The testing
   session runs a starts comparison with the correction on (results about 2026-10-12
   16:40 UTC); the default may be revisited after it.

### C. SmartPI's learning phase counts in "is the room short"

1. For a zone whose SmartPI is in its learning phase, "short" is judged against **VT's setpoint +
   0.5 K** (SmartPI 0.4.0's upper hysteresis, under Facts): in the comfort correction (short by at
   least 0.3 K against it; "too warm" stays against VT's setpoint), in E's long-run rule, and in
   the critical zone's "saturated" (fully open and below it).
   - The task text names "D's rule"; read as E's long-run rule, the only other "short" judgement.
     The curve's room (D) takes setpoints, not shortfalls.
2. **Calibration, stable, inactive, unknown:** as today, VT's setpoint (Claude's call, the
   cautious reading the user named). In calibration SmartPI drives its own forced cycle, and the
   band does not describe it.
3. **Read only in `vtherm_link.py`, by capability.** The VT climate's `specific_states` names
   SmartPI's diagnostic sensor (`regulation_diagnostics`), and that sensor's state
   "bootstrap_hysteresis" is the learning phase. Without that key, with the sensor away, or with
   any other state, the phase is unknown and today's rule holds.
4. **The band:** SmartPI publishes no hysteresis value, so 0.5 K is fixed, the verified 0.4.0
   value.
5. **Provisional (K4):** with "short by 0.3 K" taken against setpoint + 0.5 K, the correction
   stops rising once the room is 0.2 K over VT's setpoint.

### D. The curve's room temperature: Auto or Manual

1. **A choice "Auto" (default for new entries) or "Manual",** with the rooms Auto leaves out, at
   the advanced level, where the curve's room temperature is today (Claude's call). At the
   simple level Auto applies; a stored "Manual", or a room left out, counts as a hidden advanced
   setting.
2. **Auto:** the highest VT setpoint among the zones in heat mode with heating enabled, known, and
   not left out by the user (a bathroom, say), at most 23 °C. It follows VT's presets (eco at
   night lowers it) through the ramp, as today.
   - It stays within the curve's validity: at least the design outdoor temperature + 10 K, at
     most the design flow − 5 K (the curve step's own checks), and within the room temperature's
     bounds (15 to 25 °C).
   - With no such zone, the last Auto value holds; before the first one, the stored manual value
     (default 20 °C).
3. **Manual:** the value entered. Its description says "the setpoint of the warmest room, the one
   you want heated highest", that too low leaves rooms cold in mild weather, and that too high
   wastes gas.
4. **Upgraded entries:** the entry migration (minor version 8) writes "Manual" into every
   control section, its stored room temperature kept (none stored: 20 °C, as it ran), so nothing
   changes on upgrade. New entries get Auto.
5. **Where the room feeds other things:**
   - The curve step's checks use the manual value; Auto is held inside them at run time.
   - The lowest-water suggestion's design load uses the curve as it runs.

### E. "A long run that does not reach the rooms" — a monitor rule, information and warnings only

1. **Judged once the flame has been on continuously for 3 h** (the flame known throughout;
   without a flame signal the rule does not run), and only while the rooms' temperatures have
   not risen over those 3 h: each counted room rose less than 0.2 K (provisional, K4: a room
   warming is no case for a notice).
2. **Counted rooms:** the zones known, with heating enabled. Left out:
   - zones VT holds for a window;
   - zones under F's guard;
   - zones with foreign heat now.
   "Short" is fully open and short by at least 0.3 K, with C's band.
3. **The classes**, first that fits:
   1. Rooms short, and the flow below the setpoint by more than 1 K at a modulation of at least
      90 % (modulation known) → **warning** "the boiler is at its power limit".
   2. Rooms short — one or more, each counts (addition 2) — and the flow holding the setpoint
      within 1 K → **information** "the water is too cool for {rooms}"; the correction (B) raises
      it, and at its limit B's warning names the room and the causes.
   3. Every counted room over its setpoint by at least 0.3 K at every check of the last hour →
      **information** "the water is too hot: lower the curve".
   4. Rooms at their setpoints → nothing: the ideal state, few starts, condensing.
   - Withdrawn by addition 2: "one room short while the others hold → check room X, never raise
     the curve". A tilted window is now B's warning's business, and a fast-cooling window is
     F's.
4. **Thresholds** (provisional, K4, each with its reason):
   - 1 K for "holding the setpoint" — the boiler's own regulation band;
   - 90 % for "high modulation" — the burner near its top;
   - 0.2 K over 3 h for "not rising" — above a room sensor's noise;
   - 0.3 K over the setpoint for "too hot" — SHORT_K's mirror.
   The setpoint is control's written setpoint, else the boiler's CH setpoint signal; without
   either, classes 1 and 2 are not judged.
5. **How it shows:** one information binary sensor, "Long burn without warming", whose reason
   gives the class and whose attributes name the rooms. The power-limit warning also raises a
   warning repair issue. Nothing here changes control beyond the correction; the user may raise
   B's limit.
6. **Kept for 0.4's tuning** (`PLAN.md` 0.4 "Learning and tuning"; `SCOPE.md` §4 "curve changes:
   suggestions"):
   - the hours the correction sat at its limit;
   - the long runs without warming, as a count and hours per class.
   They are kept in the entry store, shown on the control state's attributes and in the
   diagnostics.

### F. An open window without a sensor

1. **VT's own detection:** a zone VT holds for a window is left out of B, C and E. "Held" means
   `hvac_off_reason` reads `hvac_off_window_detection`, or VT's `window_manager` shows
   `window_state` or `window_auto_state` "on" — its action may be frost or eco rather than off,
   and the zone then still heats a little.
2. **The plugin's own guard:** a counted zone whose valve is open, with heat flowing, and whose
   room falls by at least 0.5 K within 10 min has **a window probably open**.
   - The 0.5 K in 10 min is about VT's 3 °C/h.
   - Such a zone is left out of the correction's rise and of E until its room warms again (0.2 K
     above the lowest reading since the drop), and for at least 30 min.
   - Information only, "a window is probably open in room X", on an information binary sensor
     naming the rooms. Provisional, K4.
   - Reference values read on 2026-10-10: radiator-mounted sensors about 0.5 K in 2 min to 1.5 K
     in 10 min; room sensors away from the window about 0.3–0.5 K in 5–10 min; Danfoss Ally
     pauses 30 min, at least 45 min between detections.
3. **A tilted window** cools slowly; the room stays short, so the correction rises for it within
   its limits, and at the limit B's warning names the room and the heat loss among the causes
   (addition 2).
4. The user guide recommends VT's automatic window detection for zones without a sensor.

### G. Documentation, translations and tests

- **EN and PL:**
  - every new option and notice, each description with its risks;
  - the user guides;
  - `SCOPE.md`;
  - this plan;
  - the texts of "Curve's room temperature" and "Comfort correction".
- **`CLAUDE.md`:**
  - this plan in "Where to continue" and in the list of plans;
  - the verified facts on SmartPI's learning phase and VT's window detection.
- **`PLAN.md`:** the 0.2 row. README lists no options or defaults: unchanged.
- **Tests:** `core/` first for every rule (B's limit and warning, C's band, D's Auto value, E's
  classes, F's guard), then in-process acceptance:
  - B+C: a SmartPI zone in its learning phase just under setpoint + 0.5 K with the water too cool;
  - D: Auto follows a preset change, capped at 23 °C, a left-out zone ignored;
  - E: each class, the 3 h threshold, rooms rising → no notice;
  - F: a fast drop in one room → no rise, then back.

## Facts

- **SmartPI 0.4.0** (`vendor/vtherm_smartpi-0.4.0`):
  - The learning phase, `SmartPIPhase.HYSTERESIS` ("Hysteresis"), runs on/off: off at setpoint +
    `HYST_UPPER_C` (0.5 °C), on again at setpoint − `HYST_LOWER_C` (0.3 °C)
    (`smartpi/const.py:171-172`).
  - Its diagnostic sensor's state is "bootstrap_hysteresis", "calibration" or "stable" ("inactive"
    without SmartPI; `sensor.py` `_get_diagnostic_state`), its attributes the live diagnostics
    with "phase" and "regulation_mode" (`smartpi/diagnostics.py`).
  - The VT climate carries only `specific_states.regulation_diagnostics` (that sensor's entity
    ID) and `smartpi_learning_enabled` (`handler.py` `update_attributes`).
- **VT 10.4.0** window detection (`feature_window_manager.py`, `open_window_algorithm.py`, `const.py`):
  - per zone, a sensor or automatic by the temperature's slope; the author's office values
    3 °C/h to detect and 0 °C/h to end;
  - its action turns the zone off, fan only, frost or eco (`window_turn_off`, `window_fan_only`,
    `window_frost_temp`, `window_eco_temp`);
  - the climate shows `window_manager` with `window_state` and `window_auto_state` ("on", "off";
    unavailable where not configured) and `is_window_configured`;
  - `hvac_off_reason` reads `hvac_off_window_detection` when the action turned it off.
- **Today** (`core/controller.py` `_correction`):
  - a zone fully open (`ZoneState.fully_open`: 0.95, or VT's duty cap) and short by at least
    `SHORT_K` 0.3 K raises the water 1 K per 30 min of heat flow, at most 3 K a day and 3 K in
    all; it falls twice as fast;
  - after 3 h at 3 K, the information alarm `correction_at_limit`;
  - the option `comfort_correction`, off by default and advanced only since K4.1;
  - the curve's room temperature, a fixed option (default 20 °C, `core/curve.py`).

## Steps

| Step | Work | J4 impact |
|---|---|---|
| G11.0 ✅ | this plan; `SCOPE.md` where it states the old behaviour; `CLAUDE.md` (where to continue, the plans, two verified facts); `PLAN.md`'s 0.2 row; `docs/plan-0.2.md`'s step G11 | none |
| G11.A ✅ | F7 (decision A), pull request #51 | N2, N6, N7, N8 (instance 7) |
| G11.B ✅ | B and C: the correction on by default in full control, at both levels, its limit option, the warning repair issue, the entry migration (minor version 7); SmartPI's learning band read in `vtherm_link.py` and used by the correction and the critical zone; translations, tests (`core/` first). Found on the way: a session's stored options (`taken_with`) are read as the migration leaves a section, or a restart after the update would hand back instead of restoring | E4 again; the starts comparison with the correction on (instances 2–5); new: a curve too low in mild weather with a SmartPI zone in its learning phase, correction off and on |
| G11.B2 | additions 2 and 3: the warning's two texts — the curve first with most rooms short, the radiator and the heat loss first with fewer — and the rooms' entity IDs among its placeholders; the plan, `SCOPE.md`, the user guides | E4 again; J4's Q1 and Q5 (a warning repair issue naming the room) |
| G11.D ✅ | D: the curve's room Auto or Manual, the rooms left out, the entry migration (minor version 8: Manual for upgraded entries); translations, tests | E4 again; new: the Auto curve room following a preset |
| G11.E | E and F: the long-run rule and its sensor, warning and kept counts; VT's window detection read and its zones left out of B, C and E; the plugin's own window guard and its sensor; translations, tests | new: a window opened in one room; a long run in each class |
| G11.G | the user guides EN and PL, and every document G names that the steps above did not already change | none |

## Open after G11

- The default of the comfort correction, after the starts comparison (about 2026-10-12).
- Every threshold marked provisional above (K4).
- Using the kept counts to tune the curve (0.4, "Learning and tuning").
