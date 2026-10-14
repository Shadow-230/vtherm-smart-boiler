[Polska wersja](../../pl/specification/references.md)

# Reference codes

Status: current.

Code comments, tests, plans and the scope use short codes such as `P-12` or `PB-25`. Each code
points to the place where a problem, a decision or a test finding was first written down, so the
reason for a piece of code can be traced back. This page says where each kind of code is
explained.

Almost all of these places are history documents: they stay in English and are not rewritten
(see [the documentation map](../README.md)). Two codes that look alike can come from different
documents, so the table below gives the exact form of each.

## Problems found in code reviews

Each review numbers its own problems. The form of the code tells which review it is from.

| Code | Example | What it is | Where it is explained |
|---|---|---|---|
| `P01`…`P66` (two digits, no dash) | `P02` | a problem in the code | [review of 2026-09-24](../development/reviews/review-2026-09-24.md), §3 |
| `S01`…`S20` (two digits, no dash) | `S04` | a problem in the specification | review of 2026-09-24, §4 |
| `P-n` | `P-60` | a problem in the code | [review of 2026-09-26](../development/reviews/review-2026-09-26.md), §3 |
| `S-n` | `S-34` | a problem in the specification | review of 2026-09-26, §4 |
| `T-n` | `T-01` | a missing test | review of 2026-09-26, §6 |
| `PB-n` | `PB-25` | a problem in the code | [review of 2026-10-04](../development/reviews/review-2026-10-04.md), §3 |
| `SB-n` | `SB-02` | a problem in the specification | review of 2026-10-04, §4 |
| `TB-n` | `TB-03` | a missing test | review of 2026-10-04, §6 |
| `SC1-n`, `SC2-n`, `PL-n`, `P21-n`, `P22-n`, `VT-n`, `HA-n` | `SC2-140` | one requirement in the table of requirements and tests | §5 of the review of 2026-09-26 or of 2026-10-04 (each review numbers its rows on its own) |

What was done with each problem is listed at the end of the plan that fixed it: "Index: review
problem → step" in [plan 0.2.2](../development/plans/plan-0.2.2.md) and
[plan 0.2.3](../development/plans/plan-0.2.3.md). [The comparison of 2026-09-26](../development/reviews/review-2026-09-26-vs-0.2.md)
says what happened to every problem of the first review.

## Findings of the independent checks of 0.2.2

| Code | What it is | Where it is explained |
|---|---|---|
| `Z4-n` | a finding of the independent check of release 0.2.2 (step Z4) | [plan 0.2.2](../development/plans/plan-0.2.2.md), "Open after 0.2.2" |
| `Z4R-n`, `Z4R2-n`, `Z4R3-n` | a finding of the first, second and third repeat of that check | the same place |
| `KD-n`, `KDF-n` | the heating switch's stuck test and the relay timer, decided on 2026-10-03 | plan 0.2.2, "Open after 0.2.2", items 35 to 37 |

The full reports of these checks stay in the `research/` folder of the author's computer; it is
not part of the repository. What was decided is in the plan.

## Decisions of the user

| Code | Example | Where it is explained |
|---|---|---|
| "decision n" (1 to 16) | "decision 6" | plan 0.2.2, "Decisions 1–16" |
| "answer A" to "answer O" | "answer H" | plan 0.2.2, "Decisions of 2026-09-26/27", the user's answers of 2026-09-27; details in [plan 0.2.2 details](../development/plans/plan-0.2.2-details.md) |
| a numbered decision of 2026-10-05 | "decision 4 of 0.2.3" | [plan 0.2.3](../development/plans/plan-0.2.3.md), "Decisions of 2026-10-05" |
| a letter and a number in step I8 | "F3", "A4" | [plan of step I8](../development/plans/plan-0.2-i8.md), "Decisions of 2026-10-10": group A (scope) to I (plans) |
| "decision n of I6" | "decision 4 of I6" | [plan of step I6](../development/plans/plan-0.2-i6.md), "Decisions of 2026-10-08 and 2026-10-09" |
| "review question n" | "review question 4" | the review's appendix E, "Open questions for the user" |

## Steps of the plans

A step is a letter and a number. Each letter belongs to one plan:

| Letters | Plan |
|---|---|
| A, B, C, D | [plan 0.1](../development/plans/plan-0.1.md) |
| F, G, H, I, J, K, S | [plan 0.2](../development/plans/plan-0.2.md); steps I6, I7, I8, I9 and G11 have plans of their own in the same folder |
| L, M, N, O, R, U, W | [plan 0.2.1](../development/plans/plan-0.2.1.md) |
| Q, V, X, Y, Z | [plan 0.2.2](../development/plans/plan-0.2.2.md); `Q3.n` is one question of the research step Q3 |

Plan 0.2.3 is split into parts 1 to 4 and uses the review codes above as its steps.

## Tests in the test Home Assistant (J4)

| Code | Example | What it is | Where it is explained |
|---|---|---|---|
| a scenario | `C5`, `N2`, `L1` | one test the J4 runner plays out | `devenv/j4/run.py`; results in [the test report in progress](../testing/reports/unreleased.md), §4 |
| `F-n` in a report's findings | `F7` | a finding of a J4 run | the test report, §7 |
| `L-n` in a report's findings | `L6` | a known limit found in a J4 run | the test report, §7 |

A scenario and a finding can share a code (scenario `F1` is the boiler's low-pressure fault,
finding `F1` a missing file in the simulator); the table it appears in tells which. A finding
the report does not list yet — `F14`, from the runs of 2026-10-14 — is explained in the
code comment that cites it until the test report adds it.
