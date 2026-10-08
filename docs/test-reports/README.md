# Test reports

Every release carries a report of the tests its version passed: `docs/test-reports/<version>.md`
(the user's decision, 2026-10-08). Until the version is named (`docs/plan-0.2.md`, K4 and K5)
the report being written is `unreleased.md`; at the release it is renamed to the version and
goes with the pull request from `dev` to `qas`.

## What a report holds

1. **Version and code** — the version, the commit tested, the dates.
2. **Environment** — Home Assistant (the version the plugin is built on and the oldest
   supported), Versatile Thermostat, SmartPI, the `vtherm_api` Home Assistant installed, Python.
3. **Automated tests** — the counts of the core tests (without Home Assistant) and of the
   others, the expected failures and why, lint and types, the CI runs.
4. **J4 in the test Home Assistant** — every scenario with its identifier, what it checks, the
   result, the date and the evidence (what was written to the boiler, the states and alarms
   seen); the runs reviewed by hand, with why.
5. **The starts criterion** — starts per hour and room temperatures of its four runs, the ratio
   against the criterion and the in-process figures.
6. **Not run, and why** — scenarios a real Home Assistant cannot reach, or left for later.
7. **Findings and known limits** — what the runs found, with its follow-up.

## How the J4 part is made

The test Home Assistant is the dedicated test LXC (`devenv/README.md`). Its instances are
deployed with `scripts/deploy_test.sh --instance N [--config NAME]` and set up as section 4 of
`devenv/README.md` says. The scenarios run with the runner in `devenv/j4/`:

```
HA_INSTANCE=1 scripts/env.sh python devenv/j4/run.py B1 C2 ...      # scenarios by identifier
HA_INSTANCE=1 scripts/env.sh python devenv/j4/restart.py B3 B6     # the restarts
```

Each scenario starts and ends from a clean state — control off and handed back, the
simulator's faults cleared, the zones heating at their targets — and checks what the in-process
acceptance test of the same scenario checks (`tests/integration/test_acceptance.py`): the
plugin's states, alarms and repair issues, and every command sent to the gateway, captured live
over Home Assistant's WebSocket. Its results, with the evidence, go to
`research/<date>-j4-results.md` (git-ignored); the report takes them from there. The runner
reads where to connect from `devenv/local.env` only.
