# Plan 0.2, step I11 — Control switched in the plugin's settings

Status: history — kept as it was written, in English only; only the ✅ of a finished step is still added. The current documents: [the documentation map](../../README.md).

Goal: control is switched on and off only by an administrator, in the plugin's own settings, as
a feature is turned on in VT's — not from a dashboard. Automations may switch it. What control
does once on, and every safety rule around it, stays as it is. A step of 0.2 after I10, before
the first release (the user's decisions of 2026-11-22), listed in `docs/en/development/plan.md`.

## The user's decisions (2026-11-22)

J4's I10.10 found it (F19, `docs/en/testing/reports/unreleased.md` §7): the Boiler page lets only
an administrator switch control, but the Control switch is an ordinary entity — a user without
administrator rights switched control on with `switch.turn_on`.

1. **Only an administrator, and only from the plugin's settings** ("as part of a configuration
   change, as a feature is turned on in VT"), not from a dashboard.
2. **Automations may** switch control (only an administrator makes automations).
3. The design proposed the same day and accepted ("F19 tak"): a tick in the settings, applied
   without a reload; the switch on dashboards becomes a state shown, nothing to click; the page
   shows the state and leads to the settings; a service for automations, refused when a person
   calls it.

## Facts (checked in the code on 2026-11-22, `dev` 01a5205)

- `switch.py` `ControlSwitch`: the user's wish to control. `async_turn_on` refuses while a blocker
  that needs the user remains (`ServiceValidationError`, the first blocker's text and the count of
  the others); `async_turn_off` hands back and raises `hand_back_failed` where the boiler did not
  take it (PB-39). The wish is kept in the control store at once (`control.stored_wish`) and
  restored when the switch is added; without a stored wish, the switch's restored state. Its
  attributes carry the blockers, what keeps control from writing, the hand-back's effect, frost
  protection, how "off" reaches the boiler, the allowed services, the relay's confirmation, the
  outage effect, the wall thermostat's setting and warning, and the monitor's verdict.
- Tests switch control through one helper, `Rig.switch` (`tests/integration/test_control.py`,
  589 uses); J4's runner through `Run.switch` (`devenv/j4/run.py`) and a few calls in `paths.py`.
- The page switches control with `switch.turn_on`/`turn_off` (`frontend/src/overview.ts`), after
  its own confirmation, an administrator only.
- The options flow applies its changes at "Save and finish"; the update listener reloads the
  entry when the options changed, except the level of detail (`__init__.py`
  `_async_options_updated`). Settings that block control are saved after a confirmation
  (`confirm_blocking`: the first blocker's text and the count).
- To verify in I11.2, with a test: a service called by an automation carries no user
  (`call.context.user_id` is `None`); one called from a dashboard, a script started by a person,
  the developer tools or the REST API carries that person's.

## Design

- **The tick.** "Control on" in the item "Control mode", shown where a control mode is chosen and
  control is configured; it shows the stored wish, it is not an option of its own (no second
  source of truth, no migration). "Save and finish" applies it as the switch did: on — refused
  in the form while a blocker that needs the user remains, with its text; off — the safe
  hand-back, and where the boiler does not take it, the existing alarm and repair issue say so.
  Nothing else changed: no reload. With other changes in the same save, the wish is stored first
  and the reload's new run applies it, waiting for its blockers as after a restart.
- **The state.** The Control switch becomes a binary sensor "Control" with the same attributes;
  nothing on a dashboard switches control. A switch disabled no longer means control off.
- **Automations.** A service `vtherm_smart_boiler.set_control` (`enabled`: on or off) with the
  switch's checks; refused, with a text pointing to the settings, when the call carries a user.
- **The page.** The Control card shows the state and a button "Change in settings" that opens the
  plugin's settings; nothing else on it switches control.
- **J4's runner** switches control through the settings (`walk.save_options`), the real path,
  and reads the binary sensor.

## Steps

| Step | What | J4 impact |
|---|---|---|
| I11.0 ✅ | this plan; `CLAUDE.md` (where to continue) and the development plan EN and PL point to it | none |
| I11.1 ✅ | **The tick.** The field in "Control mode", its texts EN and PL, applied at "Save and finish" as above; the switch still works meanwhile. Tests first: on, off, refused with a blocker, with other changes in the same save, the latch cleared only by off then on (two saves), a non-administrator never reaches it (Home Assistant's options flow is an administrator's) | G2, G3, R8, N4 (`devenv/j4/`): control refused in the settings — once the runner uses the tick (I11.5) |
| I11.2 ✅ | **The service for automations.** Registered with its texts; the checks of the switch; refused when a person calls it. Tests first: an automation's call, a person's call, a blocker, a hand-back not taken | none until I11.5 |
| I11.3 ✅ | **The state.** The switch replaced by the binary sensor with the same attributes; `Rig.switch` through the service; the page's `installation` names the new entity; docs EN and PL (user guide, technical, scope) | every scenario that switches control — after I11.5 |
| I11.4 ✅ | **The page.** The Control card: the state and "Change in settings"; the built page committed; screenshots of sample data | the page by hand, as I10.10's check C |
| I11.5 ✅ | **J4's runner.** Control through the settings; the binary sensor read; `docs/en/testing/test-environment.md` and its Polish twin | every scenario that switches control |
| I11.6 🔒 | **In the test Home Assistant**, after the user says to start: the scenarios above, and a user without administrator rights refused everywhere | — |

One pull request at a time (`CLAUDE.md`), each with its tests and its "J4 impact".

I11.4 was built before I11.3, so the page never calls a switch that is gone; I11.3 follows it.

## Not changed

What control does once on; its blockers, latches and alarms; the hand-back; the stored wish and
its restore after a restart; the "monitoring only" mode, which leaves control out as before.
