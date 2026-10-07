# Contributing

This integration controls a home's heating: a bug means a cold house or a boiler that starts
every minute. Changes are therefore small, tested and reviewed before they reach a boiler.

## Branches

| Branch | Holds | How changes arrive |
|---|---|---|
| `dev` (default) | ongoing work | pull requests (the maintainer's automation pushes here directly) |
| `qas` | the state under test on a test Home Assistant | pull requests from `dev` only, after the checks pass |
| `main` | releases only | pull requests from `qas` only, approved and merged by the repository owner |

- Open every pull request against `dev`. Pull requests against `qas` or `main` from other branches
  are closed.
- Releases (tags `v*` and GitHub releases) are made by the repository owner only, from `main`.
- History is never rewritten on `dev`, `qas` or `main` (no force pushes, no deletions).

## Before a pull request

- Python 3.14; `core/` holds pure logic with no Home Assistant imports.
- Start a change with a test that shows the problem; every new mechanism also gets a test with an
  unknown, missing or `None` input.
- Run, as CI does: `ruff check .`, `ruff format --check .`, `mypy`, the core tests
  (`python -m pytest -q -p no:homeassistant --disable-socket --allow-unix-socket tests/core`)
  and the others (`python -m pytest -q --ignore=tests/core`).
- Every user-visible text goes through `translations/en.json`, with the same keys in every other
  language.
- No installation-specific data (entity IDs, device names, one house's values) in code, defaults,
  tests or docs: every input is picked by the user in the configuration form.
- Do not copy, adapt or translate code from other applications; describe what you need and
  write it anew.

By contributing you agree that your contribution is licensed under the Apache License 2.0.
