# Contributing

This integration controls a home's heating: a bug means a cold house or a boiler that starts
every minute. Changes are therefore small, tested and reviewed before they reach a boiler.

## Branches

| Branch | Holds | How changes arrive |
|---|---|---|
| your own branch (`feature/…`, `fix/…`; the maintainer's automation uses `claude/…`) | one change | your commits |
| `dev` | integrated work | pull requests from working branches, merged once the checks pass |
| `qas` | the state under test on a test Home Assistant | pull requests from `dev` only, approved and merged by the repository owner |
| `main` (default) | the documentation; from the first release on, the releases | pull requests from `qas` only, approved and merged by the repository owner |

- Nobody pushes to `dev`, `qas` or `main` directly: every change starts on its own branch and
  moves `branch → dev → qas → main` through pull requests.
- Open every pull request against `dev` (not the default branch `main`). Pull requests against
  `qas` or `main` from other branches are closed. A contributor's pull request into `dev` is
  reviewed and merged by the repository owner; the maintainer's automation merges only its own.
- Releases (tags `v*` and GitHub releases) are made by the repository owner only, from `main`.
  Each release carries the report of the tests its version passed, `docs/test-reports/<version>.md`
  (`docs/test-reports/README.md`).
- History is never rewritten on `dev`, `qas` or `main` (no force pushes, no deletions).

## Checks

Every pull request runs these checks on GitHub Actions:

| Check | Runs on | Blocks a merge |
|---|---|---|
| Tests – supported Home Assistant version | every pull request; pushes to `qas` and `main`; weekly | yes |
| Tests – oldest supported Home Assistant version | same | yes |
| Home Assistant integration check (hassfest) | same | no |
| HACS repository check | same | no |
| Early warning – newest vtherm_api | weekly, on demand, pull requests into `qas` and `main` | no |
| Early warning – newest Versatile Thermostat and SmartPI | same | no |

- The two test checks run lint (`ruff`), formatting, types (`mypy`), the core tests without
  Home Assistant, the other tests, and the coverage floor: every module at least 95 % with
  branches, the config and options flows 100 %. The Home Assistant version tested is in each
  run's summary.
- A pull request that changes documentation only (Markdown files, `documentation/`, `docs/`,
  `LICENSE`; not `CLAUDE.md`, nothing under `.github/`) passes the two test checks without running
  the tests, as no test reads those files; anything else runs them in full.
- An early warning tests this integration against the newest releases of the projects it works
  with. Its failure is not a fault of the pull request: it says that something upstream changed
  and needs a look.
- Merging into `dev` needs both test checks green and the branch up to date with `dev`; merging
  into `qas` or `main` needs the same, plus the repository owner's approval, and only the owner
  merges.

## Before a pull request

- Python 3.14; `core/` holds pure logic with no Home Assistant imports.
- Start a change with a test that shows the problem; every new mechanism also gets a test with an
  unknown, missing or `None` input.
- Run, as CI does: `ruff check .`, `ruff format --check .`, `mypy`, the core tests
  (`python -m pytest -q -p no:homeassistant --disable-socket --allow-unix-socket tests/core`)
  and the others (`python -m pytest -q --ignore=tests/core`); add `-n auto` to run them on every
  CPU (pytest-xdist), as CI does.
- Every user-visible text goes through `translations/en.json`, with the same keys in every other
  language.
- No installation-specific data (entity IDs, device names, one house's values) in code, defaults,
  tests or docs: every input is picked by the user in the configuration form.
- Do not copy, adapt or translate code from other applications; describe what you need and
  write it anew.

By contributing you agree that your contribution is licensed under the Apache License 2.0.
