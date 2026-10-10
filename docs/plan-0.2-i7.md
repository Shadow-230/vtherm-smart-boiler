# Plan 0.2, step I7 — A menu of sections, saved once, as in Versatile Thermostat

Goal: the setup and the options move through a menu of sections as Versatile Thermostat's do — a
section returns to the menu, nothing is saved until the end, and one item at the end saves it
all. Sections that do not apply are not shown. Step I7 of `docs/plan-0.2.md`, decided by the user
on 2026-10-10 after the J4 tests. Nothing here changes what the plugin does with the boiler: only
how its settings are asked and saved.
Scope: `SCOPE.md`; overview: `PLAN.md`; the release plan: `docs/plan-0.2.md`.

Status on 2026-10-10: I7.0 (this plan), I7.1 (the menus) and I7.2 (the limits with their sensors) done — I7 is complete.

## How to read this plan

- "Decision N" refers to the numbered list below.
- ✅ marks a finished step. Every step is one pull request into `dev`, with its "J4 impact": the
  J4 scenarios to run again in the test Home Assistant once it is deployed; the testing session
  runs them and adapts its runner. After each step the main session reports to the user in
  Polish.
- "Claude's call" marks a choice the user left open: written here with its reason, provisional
  until K4 like every value of this release.

## Facts (Versatile Thermostat 10.4.0, `vendor/`, `config_flow.py`)

- VT's flows show a menu (`async_step_menu`) built from the configuration so far: a section
  appears only where it applies (the window panel only with window detection ticked, say).
- Each section's step ends by showing the menu again; nothing is stored until the last item.
- That item is "finalize" once VT's check of the whole configuration passes, and
  "configuration_not_complete" otherwise, which shows the menu again. VT's options flow saves at
  "finalize" — the entry updated, then the flow ends with no data.
- Home Assistant's menu step takes description placeholders (`async_show_menu`,
  `description_placeholders`; Home Assistant 2026.9.3 `data_entry_flow.py`), so the menu's
  description can name the sections changed.

## Decisions of 2026-10-10 (the user)

1. **A menu of sections, as in VT, in the options and in the setup.** A section, once confirmed,
   returns to the menu; nothing is saved. An item at the end saves everything.
2. **Sections are filtered**: one that does not apply to the boiler, its connection or the level
   is not shown, as VT hides its window panel without window detection.
3. **Unsaved changes are shown** on the menu. Closing the window discards them.
4. **The pressure limits and the flue-gas limits are hidden without their sensor.** Mapping the
   sensor in "Boiler signals" shows them in the same session — no need to run the whole setup
   again.
5. **No "back without saving" button** (the user withdrew it): Home Assistant's forms have only
   their confirm button; closing the window discards the session's changes.

## Claude's calls

- **The setup's first panels stay first**: how the boiler is connected, the control mode, then
  the name and the level — they decide which sections and fields follow. Then the menu.
- **The setup's last item**: "Create" once every section the menu shows has been confirmed once
  and the whole configuration passes the check; otherwise "Configuration incomplete", which
  opens the first section not confirmed yet, or the step with the problem the check found. The
  menu's description names what is left. Reason: the entry holds what the step-by-step wizard
  gave it, every section seen once — a section never opened would leave its defaults unseen.
- **"Control" in the menu**: with full control or on/off chosen; for an entry made before the
  control mode (it has none) as before; and also while the session's options still hold a write
  path, so control can be switched off after "monitoring only" is chosen — the control step then
  offers "no control" only. Reason: no dead end where a stored path could no longer be cleared.
- **"Reference room"** only with zones: without a zone there is nothing to refer to.
- **"Monitor thresholds"** at the advanced level only, as before.
- **"Save and finish"** (the options' last item) runs the checks of the save before I7, in the
  same order: a stored section of another shape (PB-06), the whole configuration, the hand-back
  value against the limits, what the hand-back goes through while one is owed (P-12, PB-09), and
  the confirmation of an edit that would stop control. Then the options are saved once and the
  integration reloads once — not where only the level changed, as before.
- **A problem found at the save** opens its step with the error; confirmed, it returns to the
  menu, where "Save and finish" is chosen again.
- **Declining "this change stops control"** returns to the menu with the session's answers kept:
  nothing is saved; they can be changed, saved, or discarded by closing the window. Before I7 the
  declined answers were dropped — then they were one section's.
- **Hidden limits are kept, not dropped**: a limit whose sensor is no longer mapped stays stored
  and judges nothing; it shows again with the sensor.
- **The reload sentence** ("Saving reloads the integration: …") leaves every section's
  description and goes to the menu's, beside "Save and finish".

## Steps

### I7.0 ✅ The plan

This file, step I7 in `docs/plan-0.2.md`, `CLAUDE.md`'s "Where to continue" and plan list,
`PLAN.md`'s list. J4 impact: none.

### I7.1 ✅ The menus (decisions 1, 2, 3, 5)

- Options: every section returns to the menu, the level and freshness steps too; the control
  steps return to it after their last step. A new item "Save and finish" runs the save. The menu
  hides what does not apply (above) and its description lists the sections changed in this
  session, in Home Assistant's language, and says closing the window discards them.
- Setup: connection → (MQTT topics) → mode → name and level → the menu, with every section, the
  connection and the name among them; "Create" or "Configuration incomplete" at its end.
- Translations (EN source, PL), the user guides (EN, PL), tests: every flow test, a test for each
  filter, the unsaved list, closing without saving, the incomplete item, a problem at the save.
- J4 impact: every scenario that walks the options. The runner's `Run.options` and
  `options_walk` (`devenv/j4/`) must choose "Save and finish" (`{"next_step_id": "save"}`) when
  the control steps return the menu; "this change stops control" now follows that choice. Then
  the scenarios that change the options run again.
- Done on 2026-10-10. Facts checked for it: `research/2026-10-10-i7-vt-menu-facts.md`. An entry
  from before the `weather` key reads one change as made where the signals step adds the key
  empty: the menu then names "Boiler signals" though nothing visible changed — harmless.

### I7.2 ✅ The limits shown with their sensor (decision 4)

- The boiler step shows the pressure limits only with a pressure sensor mapped; the monitor step
  shows the flue-gas limits only with a flue-gas sensor mapped (and for a condensing boiler, as
  before). Hidden limits are kept.
- Translations where a description names them, the user guides, tests.
- J4 impact: none unless a scenario sets a pressure or flue-gas limit without the sensor.
- Done on 2026-10-10. A limit stored in a shape this version cannot read, with its sensor not
  mapped, sends the save to its step without the field: mapping the sensor shows it there. Only
  a hand-edited entry can hold one (PB-06, P-70).
