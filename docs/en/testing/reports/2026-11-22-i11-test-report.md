# Smart Boiler for Versatile Thermostat — test report

Status: history — kept as it was written, in English only. The current documents: [the documentation map](../../README.md).

**Tests in a real Home Assistant, 22 November 2026, on the `qas` branch (commit fcae678)**

This is the plain-language report. The detailed technical report is [`unreleased.md`](unreleased.md), section 4.9, with the findings L15 and L16 in section 7. The report of the tests before it is [`2026-11-22-test-report.md`](2026-11-22-test-report.md).

## In short

- **We tested only what had changed** since the last tests (18 to 21 November), as you asked:
  - the new way of switching control (step I11);
  - the fixes to the faults found last time;
  - the fixes to our own test tools.
- **Everything we ran passed: 25 test runs and the checks by hand.** We found no new fault in the plugin.
- **The four faults found last time are fixed and shown fixed in a real Home Assistant:**
  - the "water is too cool" advice now comes when the boiler runs at its minimum;
  - saving the heating curve from the Boiler page keeps the radiators' exponent and the fallback water temperature;
  - the page stays open, and keeps working, while the plugin reloads;
  - the journal now records the boiler handed back at a restart and taken again after it.
- **The comfort correction's limit now reaches the boiler exactly** (3.0 K, no longer 2.53 K).
- **Switching control works as you decided:**
  - only an administrator can switch it, in the plugin's settings, or an automation can;
  - a person calling the action directly is refused, even an administrator;
  - after a restart, control comes back as it was left.
- **Updating from the previous version while the plugin controls the boiler works.** Control comes back on, and the old control switch is removed.
- **One test could not run (Q5).** It needs SmartPI to have finished learning, and in our simulated house SmartPI never finishes. See below.

## What we tested

| Area | Result |
|---|---|
| Updating in place from the previous version with control on | works: control back on, the old switch removed, the new "Control" sensor in its place, nothing in the log |
| Switching control in the settings ("Control mode", "Control on") | works, with the reason shown when something blocks it |
| Switching control from an automation | works; a person calling the action directly is refused |
| Control after a reload, a restart and a killed Home Assistant | comes back as it was left; the journal records each step |
| Refusals in the settings, stores after a crash, another controller, a latch cleared in the settings | works |
| The relay, the boiler's own entities, a stand-alone gateway | works |
| The "water is too cool" advice (fault fixed) | works |
| The comfort correction's limit and its warning | works; the limit is written exactly |
| The Boiler page: the control card, saving the curve, a reload with the page open | works |
| The Boiler page for a user who is not an administrator | sees the state, cannot change it or save the curve |
| Renaming the control sensor while the plugin controls the boiler | control goes on undisturbed |

We did not run the tests whose code had not changed since they last passed (18 to 21 November): faults, lost signals, hot water, frost, floor heating, US units, the wall thermostat's program, the 12-hour run, the relay's timers.

## The test that could not run, and the simulated house

**Q5** checks the warning when one room cannot reach its setpoint. It needs SmartPI, which regulates the bedroom, to have finished learning.
- SmartPI learns by heating the room to 0.5 °C above its setpoint and letting it cool to 0.3 °C below, about five times each way.
- In our simulated house it never got through even one such swing in 27 hours: the room warms and cools so slowly that it never reached 0.5 °C above the setpoint.

You pointed out that the simulated house looks almost perfectly insulated:
- The house every test uses takes about 40 hours to lose most of a temperature difference, and cools by only about a third of a degree an hour with the heating off at +3 °C outside. That is a heavy, well-insulated house.
- The simulator also has a draughty house, but no test uses it.

We will ask the development session to:
- make the house more typical;
- give the SmartPI tests a faster room, or a SmartPI that has already learned;
- check again, after the change, that the boiler still starts no more often under the plugin.

## Not tested, and why

- The tests whose code did not change (above).
- Q5 (above).
- As before:
  - the "Forget" buttons for measured building values;
  - the curve's offset at the simple settings level;
  - an English title in the sidebar;
  - removing the plugin;
  - an installation saved by a much older version of the plugin.
