# Plan 0.2, step I10 — The Boiler panel and cards

Status: history — kept as it was written, in English only; only the ✅ of a finished step is still added. The current documents: [the documentation map](../../README.md).

Goal: the plugin shows its data itself, with nothing else to install: a page "Boiler" in Home
Assistant's sidebar and the same parts as cards for the user's own dashboards. The page is used
all the time, so it is ours to build and maintain. It shows the boiler and the house at a glance,
lets the user replay the last day, explains the plugin's decisions, and lets an administrator
change settings — the curve first — with the same checks as the plugin's settings. A step of
0.2 after I9 (`docs/en/development/plans/plan-0.2.md` is history, so the step is listed in
`docs/en/development/plan.md`), before the first release (the user's decision of 2026-11-18).
Nothing here changes how the plugin controls the boiler.

Status on 2026-11-18: I10.0 to I10.2 done. The user's decision of 2026-11-18, asked during
I10.2: the page stays in this repository, part of the plugin — it appears with it, is released
and reviewed with it, and needs no versioned contract between two products; `frontend/` can be
moved out later if its releases ever need their own pace. I10.2: the commands' schemas use
`probatio`, Home Assistant's own since 2026.10; the curve's points come from the new
`core/curve_view.py`. I10.3 is built in four parts, each its own pull request: I10.3a the live
status, the Control switch and the tiles (done); I10.3b the schematic and the rooms (done); I10.3c the
curve card (done; the control state gained `curve_outdoor`, the outdoor temperature the water
was decided with, so "where we are" sits on the curve); I10.3d the last 24 h (done: the history
of every entity the overview reads, the moment picked shown in every part, the Control switch out
of reach then; an unknown value is a gap, never the last one carried on). I10.3 is done.
I10.4 is done, with one difference from its row: rather than a save of its own beside the
settings', `vtherm_smart_boiler/curve/save` drives the plugin's options flow itself — the
"Heating curve" form with the stored values and the changes, then "Save and finish" — so the
checks and the save are the settings' own by construction; a save the settings would stop for is
not made. The offset is saved at the advanced level only, where the settings show it. The
journal entry for a save comes with the journal (I10.6). I10.5 is built in three parts: I10.5a
the tabs and Burner (done — the burns are the monitor's own, through the new
`vtherm_smart_boiler/burns`, and the short-burn length is the monitor's); I10.5b Use (done — the
weeks reckoned by the new `core/weekly.py` and sent with the days); I10.5c Status and alarms
(done — the entities' own texts, the alarms' and signals' names and the verdict's reasons, come
from the plugin's translations, which Home Assistant hands the page in the user's language, so
each is written once; a measured building value is forgotten with the plugin's own buttons).
I10.5 is done. For I10.3a the user consented on 2026-11-18 to Playwright, its
Chromium and the system libraries Chromium needs (`scripts/bootstrap_browser.sh`): every part is
checked on screenshots of sample data before its pull request. I10.1 differs from its row in four points: Node.js
24 LTS, not 26 (26 needs `libatomic`, missing on hosts without it); the option is the
configuration switch "Page in the sidebar" on the plugin's device, not a settings field (it
works at once, with no reload, and the settings' monitor section shows only at the advanced
level); the page's texts live beside the built page, in
`custom_components/vtherm_smart_boiler/frontend/translations/`, where the plugin reads the
sidebar title; the cards' script comes with the cards, in I10.8. The manifest lists `frontend`,
`http` and `panel_custom` as `after_dependencies`: as `dependencies` they would need Home
Assistant's frontend package, which the tests do not have; without the frontend no page is
registered.

## The user's decisions (2026-11-18)

1. A page in the sidebar as the main place, plus the same parts as cards (one code base).
2. Our own code for the page and the cards, with an attractive look; maintaining it is accepted.
3. Built now, before the first release; it moves the release and widens the tests.
4. Node.js (LTS) in `.tools/` and npm packages in the project folder, all git-ignored: `lit`,
   `typescript`, `vite`, `vitest`. Any other package needs the user's consent first.
5. The look agreed on a mock-up (sample data only): the overview "★ Przegląd" — status and the
   Control switch, tiles, the hydraulic schematic with the rooms under their circuits, the curve
   with "where we are" and a preview of changes, the last 24 h with a scrubber that drives every
   part above; and the tabs Burner, Use, Analyses, Journal, Status and alarms. All of them are
   built.
6. The page can change settings (the user: "the panel should allow modification"). Saving goes
   through the same checks as the plugin's settings, asks for confirmation and is written in the
   journal. The curve comes first; other settings are a later step, chosen by the user.
7. Everyone sees the page; only an administrator can change anything in it (the Control switch,
   the curve). No preference was given; the cautious choice is taken.
8. The page appears in the sidebar after installation; an option hides it.

## How to read this plan

- ✅ marks a finished step. Every step is one pull request into `dev`, with its "J4 impact".
  After each step the main session reports to the user in Polish.
- A change in `core/` starts with a test. Logic the page needs (the curve, the fits) is computed
  by the plugin in Python and sent to the page — the page never has its own copy of a law.
- The page only shows what the plugin and Home Assistant already know. A value whose entity is
  not picked in the settings is not shown; nothing is filled in.
- Nothing installation-specific in code, tests or docs: the schematic and the rooms come from the
  entry's settings.
- Every text on the page comes from translation files (English the source, Polish beside it),
  in Home Assistant's language; the key-parity test covers them.

## Facts (checked on 2026-11-18)

Read over the network (Home Assistant core and frontend, `dev` branch) and in this repository;
the notes and sources are in `research/2026-11-18-visualisation-options.md`.

- Serving files: `hass.http.async_register_static_paths([StaticPathConfig(url_path, path,
  cache_headers)])` (`homeassistant.components.http`). The old `register_static_path` is gone.
- A script on every page: `homeassistant.components.frontend.add_extra_js_url(hass, url)` and
  `remove_extra_js_url` — how the cards reach the card picker without a Lovelace resource.
- A sidebar page: `homeassistant.components.panel_custom.async_register_panel(hass,
  frontend_url_path, webcomponent_name, sidebar_title, sidebar_icon, module_url, require_admin,
  config, ...)`, removed with `frontend.async_remove_panel`. The page gets `hass`, `narrow`,
  `route` and `panel`. `panel_custom` depends on `frontend`. The sidebar title is a plain string,
  so the plugin picks it from its translations in Home Assistant's language.
- Cards: `window.customCards.push({type, name, description})`; `getStubConfig`,
  `getConfigForm`, `getGridOptions`.
- Data for the page: the WebSocket commands `history/history_during_period` and
  `recorder/statistics_during_period`; the recorder keeps 10 days by default.
- No built-in card draws one value against another (the curve, the energy signature): our own
  drawing is needed.
- No public API creates a dashboard for the user; we do not use internal ones.
- SmartPI's "Equinox" is a separate card by SmartPI's author (Apache-2.0, Lit, TypeScript, Vite),
  installed on its own through HACS; SmartPI itself ships no page. Ideas only — no code taken.
- This repository: `hacs.json` asks for Home Assistant 2026.10.4 at least; `manifest.json` has
  no `dependencies`; the daily summaries are kept for a year (`core/daily.py`); the curve is
  `core/curve.py`, its checks at saving are in `control_config.py` (the curve's values must fit
  together, `DESIGN_FLOW_OVER_ROOM_K`, `DESIGN_OUTDOOR_UNDER_ROOM_K`); the change report is
  `core/report.py`.

## Layout

- `frontend/` — the page's source: `package.json` and `package-lock.json` with exact versions,
  `tsconfig.json`, `vite.config.ts`, `src/` (TypeScript, Lit), `src/translations/en.json` and
  `pl.json`, tests beside the code (`*.test.ts`, Vitest). `frontend/node_modules/` is
  git-ignored.
- `custom_components/vtherm_smart_boiler/frontend/` — the built files the plugin serves: one
  module for the page and the cards, and `THIRD_PARTY_LICENSES.txt` with the license of every
  bundled package (Lit is BSD-3-Clause, which asks for its notice). They are committed, so HACS
  installs them; CI builds them again and fails when they differ.
- `custom_components/vtherm_smart_boiler/panel.py` — serving the files, the sidebar page, the
  cards' script; `websocket_api.py` — the commands the page reads and writes through.
- `.tools/node/` — Node.js, put there by `scripts/bootstrap_node.sh` (the official archive from
  nodejs.org, checked against its published SHA-256); `scripts/env.sh` puts it on the `PATH`.

## Steps

| Step | Work | J4 impact |
|---|---|---|
| I10.0 ✅ | this plan; `CLAUDE.md` (where to continue, the Node.js consent), the development plan EN and PL point to it | none |
| I10.1 ✅ | **Tooling and an empty page.** `scripts/bootstrap_node.sh`; `scripts/env.sh` with Node.js; `frontend/` with the build and the tests; a page that renders a title in Home Assistant's theme and language. `panel.py`: the files served, the sidebar page (shown to everyone, hidden by the new option "Show the Boiler page in the sidebar", on by default, with its translated description), removed when the entry unloads; the cards' script. The manifest's `dependencies`: `frontend`, `http`, `panel_custom`. Tests: the page registered and removed, the option, the built files present, the translations' parity including the page's. CI: a job that builds the page, runs its tests and checks the committed files match — a change in `.github/workflows/`, so it waits for the user to grant the `workflow` scope for that one push | none — a new page; the scenarios do not open it |
| I10.2 ✅ | **The page's data.** WebSocket commands, read-only, for any signed-in user: `vtherm_smart_boiler/installation` (the boiler type, hot water, the circuits with their type and zones, each zone's emitters, the picked entity of every signal, the plugin's entities by role, the curve's settings); `vtherm_smart_boiler/curve` (the curve's points for given settings and the result of the same checks as the settings, computed by `core.curve` and `control_config`); `vtherm_smart_boiler/days` (the daily summaries). Tests first | none |
| I10.3 ✅ | **The overview.** Status and the Control switch (with confirmation; an administrator only), the tiles, the schematic built from `installation` (combi, single with a tank, circuits straight from the boiler, behind a fixed valve, run by other automation), the rooms under their circuits, the curve with "where we are" and the last 7 days, the last 24 h from the recorder with the scrubber and play driving every part. Light and dark from the theme; usable on a phone. Tests: the schematic's layout and the scales as pure functions | none |
| I10.4 ✅ | **Changing the curve from the page.** The preview (drag the design point, the offset, the room, the exponent, the lowest water) asks `curve` for the points and the checks; "Save" for an administrator only: a confirmation listing old → new, then a new command `vtherm_smart_boiler/curve/save` that runs the same checks as the settings and saves the entry the same way (one reload, as the settings do); a refused value is shown with the reason. Tests: a non-administrator refused, every check refusing as in the settings, the saved entry equal to one saved through the settings | a scenario that saves the curve through the page once it exists; until then the settings scenarios cover the same save path |
| I10.5 ✅ | **Burner, Use, Status and alarms.** From the plugin's entities, the recorder and its long-term statistics: the burn timeline and lengths, starts per hour, condensing; gas per degree-day by week, "use against yesterday"; the verdict with its reasons, the signals' health, the alarms, the building values with "Forget measured values" (an administrator, with confirmation, the existing buttons) | none |
| I10.6 | **The journal.** `core/journal.py`: what the plugin decided and why — the heat call on and off, a water setpoint change of at least 1 K with its reason, a circuit's need holding the water, hand-back and resuming, an alarm raised and cleared, settings saved (from the page or the settings). Kept in the entry's store: 14 days, at most 2,000 entries, the oldest dropped first (provisional, K4). The command `vtherm_smart_boiler/journal`; the tab with the event lane, the list with filters and the zoomable week. Tests first | the scenarios that hand back or raise an alarm: each leaves its journal entry |
| I10.7 | **Analyses.** The energy signature: each day's gas against its mean outdoor temperature, observing and control apart, the fitted lines computed in `core/` and sent with `days`; the calendar of burner starts by hour — new daily summaries keep 24 hourly start counts, older days show without (the store keeps reading them). Tests first | none |
| I10.8 | **Cards.** The overview's parts as cards in the card picker: status and tiles, schematic and rooms, curve, last 24 h; each finds the plugin's one entry by itself | none |
| I10.9 | **Documents.** User guide EN and PL (a section on the page and the cards), technical documentation EN and PL, `docs/en/specification/scope.md` and its Polish twin, `CHANGELOG.md`; this plan marked done | none |
| I10.10 🔒 | **In the test Home Assistant**, after the user says to start (J4): the page and the cards load, every tab reads its data, the curve saves through the page, the journal fills; screenshots for the user's review | the page and the cards |

## Provisional choices (to confirm at K4)

- The journal: 14 days, at most 2,000 entries; a water setpoint change below 1 K is not written.
- The hourly start counts in the daily summaries, from I10.7 on.
- The cards ship inside the plugin and appear in the card picker through `add_extra_js_url`;
  no Lovelace resource is written.

## Documents

- `docs/en/user-guide/user-guide.md`, `docs/pl/user-guide/user-guide.md` — a section on the page
  and the cards, in I10.9.
- `docs/en/technical/technical.md`, `docs/pl/technical/technical.md` — the page's parts, the
  WebSocket commands, the build, in I10.9.
- `docs/en/specification/scope.md`, `docs/pl/specification/scope.md` — the page in the scope, in
  I10.9.
- `CHANGELOG.md` — in each step that changes what a user sees.
