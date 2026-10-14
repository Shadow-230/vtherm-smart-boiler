[Polska wersja](../pl/README.md)

# Documentation

This folder holds all the documentation of Smart Boiler for Versatile Thermostat. Each folder
has one topic. English is the main language; every current document also has a Polish copy at
the same place under `docs/pl/`.

## Where to find what

| Folder | What is in it | For whom |
|---|---|---|
| [`user-guide/`](user-guide/user-guide.md) | how to install, set up and use the plugin | users |
| [`technical/`](technical/technical.md) | how the plugin is built: its parts, one control step, tests | developers |
| [`specification/`](specification/scope.md) | what the plugin does and why: the scope, the water data interface, the codes used in the code | developers, reviewers |
| [`development/`](development/plan.md) | the development plan; the plans of each release and the reviews | developers |
| [`testing/`](testing/test-environment.md) | the test Home Assistant and the test reports | testers |
| `../images/` | pictures shared by every language | — |

## The documents

| Document | Status | Polish |
|---|---|---|
| [User guide](user-guide/user-guide.md) | current | [yes](../pl/user-guide/user-guide.md) |
| [Technical documentation](technical/technical.md) | current | [yes](../pl/technical/technical.md) |
| [Scope](specification/scope.md) | current | [yes](../pl/specification/scope.md) |
| [Water data for zone algorithms](specification/water-interface.md) | current | [yes](../pl/specification/water-interface.md) |
| [Reference codes](specification/references.md) | current | [yes](../pl/specification/references.md) |
| [Development plan](development/plan.md) | current | [yes](../pl/development/plan.md) |
| [Test environment](testing/test-environment.md) | current | [yes](../pl/testing/test-environment.md) |
| [Test reports: how they are made](testing/reports/README.md) | current | [yes](../pl/testing/reports/README.md) |
| [Test report in progress](testing/reports/unreleased.md) | current | [yes](../pl/testing/reports/unreleased.md) |
| [Release plans](development/plans/) | history | no |
| [Code reviews](development/reviews/) | history | no |
| [Test report of 2026-10-11](testing/reports/2026-10-11-test-report.md) | history | no |

**Current** documents change together with the code, in both languages in the same pull
request. **History** is the record of how the plugin was built. It stays in English only and is
not rewritten. The one exception: a step of a release plan is still marked ✅ when it is done.

The other files at the top of the repository: `README.md` (start here), `CHANGELOG.md` (what each
release changes), `CONTRIBUTING.md` (how to contribute) and `LICENSE`.
