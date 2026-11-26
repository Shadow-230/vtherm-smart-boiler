# Plan 0.2, step I13 — Corrections from the literature

Status: planned 2026-11-26; nothing built yet. History once built: only the ✅ of a finished step is
added.

## The user's decision (2026-11-26)

After the analysis of Smart Boiler's code against the literature (five reviews,
`research/2026-11-26-lit-*.md`, summary `research/2026-11-26-lit-summary.md`; the open-licence
sources kept locally in the git-ignored `research/literature/`, never in the repository; their
references in `docs/en/specification/literature.md`), the user: "Wchodzi wszystko" — every proposal
goes in. The VT issue (I12.14) stays aside. The test environment's move to Home Assistant 2026.11
and J4 come after these steps (I12.15).

The restart pause (I13.6) and the modulation cap (I13.7) were planned for 0.3; they come in here.
The restart pause is a stated exception to principle 12 (heating follows VT at once), now decided
by the user, and stays off by default.

## Steps (one pull request each, in this order)

### I13.1 "Gives no heat" only while a room is withheld heat ✅

Today the sensor is on whenever the boiler stands, a room calling or not (`core/boiler_call.no_heat`:
`vt_not_calling` while idle). Literature on supervising self-learning controllers (Hägglund and
Åström 2000; Ramadane and Bohnet 2026) says to flag missing heat only where a
controller asks for heat and does not get it; a flag on at rest hides every cooling period from a
zone model. The sensor is on only while at least one room VT counts calls for heat and gets none
(VT not calling, its activation delay, hot water with priority, a boiler fault, handed back); off
while no room calls. Its reasons stay. The rooms calling come from VT's rooms (I12.11), not from
VT's decision.

### I13.2 The boiler link: no chatter, a better freshness estimate ✅

A link lost then back after 60 s good forgets its earlier failures (`core/controller.follow_outage`),
so a link that drops for 5 of every 6–10 minutes hands the boiler back and takes it again each
time. Delay timers and failure detectors (Adnan 2013; Chen, Toueg, Aguilera 2002) lengthen the
confirmation after a repeat: a second loss within an hour needs a longer good period before
control takes the boiler again (provisional 10 min, K4). The link's freshness estimate uses more of
the source's reporting gaps (the largest recent one), so a slow but steady source is not judged
stale.

### I13.3 The comfort correction's pace ✅

The correction rises 1 K per 30 min of heat from the first moment one room is short. Mid-ranging
and valve-position reset (Skogestad 2023; Hägglund 2021) want the slow loop 4 to 10 times slower
than the rooms' loops, and a held deficit before acting. So:
- a room counts as short only after it has been fully open and short for two of its own cycles and
  at least 60 min;
- the rise is no faster than one step per four of the slowest counted room's cycles;
- no rise while a room is still warming after its setpoint was raised (a morning setback's
  recovery), with the window rule's "still warming" test (I12.10);
- a negative side: the water trims below the curve, slowly and at most 3 K, while every counted
  room is under 70 % open and none is short (valve-driven reset: Boegli et al. 2022; ASHRAE
  Guideline 36's trim and respond).
The correction stays off by default.
Built: the wait, the pace, the raise hold and the trim (1 K per 2 h, 3 K) in `core/comfort_rules`.

### I13.4 The building's heat loss and the verdict

The fit's range is fixed at ±20 %; daily samples with correlated residuals give ranges too narrow
(IEA Annex 58), and the fit leaves out sun and setpoints (Leiria et al. 2024; omitted-variable
bias). The range comes from the fit, with an allowance for correlated days, never under ±15 %; the
signature's comparison (control against watched) gets a range; a change-point fit once days lie on
both sides of the heating threshold. The verdict no longer names an oversized boiler as "the main
cause" of short burns (Bennett and Elwell 2020 measured it in UK houses without room zoning); it
shows the boiler's minimum and maximum output against the house's design load. Checked on the
simulator first.

### I13.5 The monitor's other figures

- The weekly gas per degree-day: shown only from a floor of degree-days, with a band from the
  house's own day-to-day scatter (Phillips and Wilson 2024).
- A hot-water self-check: gas classed as hot water should not follow the outdoor temperature; a
  clear slope says the classification is wrong.
- The hysteresis drift: a longer base, from stored daily medians, so a slow drift shows.
- The share of burns under 3 minutes beside the 10-minute share: the efficiency cost sits under
  3 minutes (Bennett et al. 2019, from Orr 2009).

### I13.6 A restart pause (an exception to principle 12, off by default) ✅

Boilers' own anti-cycling timers wait 1–3 minutes and give way to a large deficit; a panel radiator
keeps most of its output through 3–5 minutes, a fan convector far less (Boháč 2019, Bartusek
2014). First a study on the simulator: 0, 3 and 5 minutes against VT cycles of 5, 10 and 15 minutes
(starts, comfort, gas). If it helps: 3 minutes after a heating stop before the next start, cut short
by a large shortfall or hot water, never delaying a stop, off by default, with its risk described.
Not built: on the simulator the 3-minute pause cut no start in any case, and 5 minutes cut starts
only at VT's 5-minute cycle, as a 10-minute cycle does with warmer rooms
(`research/2026-11-26-i13-6-sim.md`; scope §11).

### I13.7 The modulation cap, opt-in ✅

Offered as a suggestion only, to lengthen burns at low load; never below the boiler's reported
minimum modulation (DESNZ, HEM-VAL-05, 2023). Off by default.

Built: an advanced option (30–100 %, 70 %) written to the gateway's `MM=` or a picked number
entity, never under 30 % nor the minimum + 10 points, released for hot water, at every hand-back
and when the boiler falls short (3 h); the simulator shows no gain at low load.

### I13.8 The outdoor mean for heavy houses and underfloor heating ✅

The effective outdoor temperature is the lower of now and a 3-hour mean for every house. Rooms
with underfloor heating respond over 20–70 hours (Kull et al. 2017); weather compensators filter
the outdoor temperature over 10–20 hours for heavy buildings (Siemens, in the review of
2026-11-16). A longer mean (provisional 12 h, K4) for an underfloor circuit or a heavy
building (the building's answers), the lower of now and the mean kept.

Built: 12 h where the curve's circuit has an underfloor room (from VT's rooms, as the exponent
reads them); underfloor only, as the building's mass went in I8 (B5).

### I13.9 Documents ✅

The underfloor exponent's wording (1.1 is the floor surface's; the water side is about 1.0); the
starts and burn thresholds (6 and 12 an hour, 10 minutes) named as conventions; the Bennett figure
worded as its paper has it (70 % of the boilers averaged starts under 10 minutes); VT's activation
delay described as the heat call's on-delay; the fallback setpoint's text naming the 0 °C practice
of other controllers beside the design flow; the numbers checked against the literature marked as
such. EN and PL together.
